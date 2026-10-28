"""Run and archive a two-arm CI experiment in an existing research-owned fork.

Python 3.11+, PyYAML. Credentials come only from GITHUB_TOKEN or GH_TOKEN.
See experiments/README.md for the setup, execution boundary and review gates.
"""
from __future__ import annotations

import argparse
import base64
import copy
import csv
import difflib
import hashlib
import json
import math
import os
import re
import statistics
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import yaml

from experiment_environment import load_env, redact
from openrouter_optimizer import DEFAULT_FREE_MODEL, generate as generate_openrouter, scope_errors, validate_free_model

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.2.0"
API = "https://api.github.com"
SCENARIO_PATTERNS = {"P-LIT-CANCEL-STALE", "P-LIT-SKIP-WORKFLOW", "P-LIT-CHANGE-FILTER",
                     "P-LIT-FAIL-SCHEDULE", "P-LIT-IDLE-SCHEDULE", "P-LIT-FAILED-JOB-FIRST",
                     "P-LIT-BUILD-PRIORITY", "P-LIT-BUILD-SELECT", "P-LIT-DURATION-PREDICTION", "P-LIT-FAIL-FAST"}
FIELDS = ("experiment_id", "repo_id", "source_commit_sha", "config_commit_sha",
          "workflow_path", "pattern_id", "arm", "repeat_index", "warmup", "cache_regime",
          "run_id", "run_attempt", "event", "status", "conclusion", "started_at_utc",
          "completed_at_utc", "workflow_elapsed_seconds", "sum_job_runtime_seconds",
          "initial_queue_seconds", "required_checks_pass", "protocol_valid", "failure_reason",
          "raw_ref")


def stamp():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False).encode("utf-8")


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Unique temp names prevent concurrent writers from clobbering one another.
    # Windows can briefly deny replacement while another process scans/opens the file.
    temp = path.with_name(path.name + f".{os.getpid()}.{time.time_ns()}.tmp")
    temp.write_bytes(encode(value) + b"\n")
    for attempt in range(5):
        try:
            temp.replace(path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.2 * (attempt + 1))


def append_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def seconds(start, end):
    if not start or not end:
        return None
    delta = (datetime.fromisoformat(end.replace("Z", "+00:00")) -
             datetime.fromisoformat(start.replace("Z", "+00:00"))).total_seconds()
    return delta if delta >= 0 else None


class ActionsLoader(yaml.SafeLoader):
    # YAML 1.2 booleans: GitHub's `on` key must remain a string.
    yaml_implicit_resolvers = {
        key: [(tag, rx) for tag, rx in resolvers if tag != "tag:yaml.org,2002:bool"]
        for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }


ActionsLoader.add_implicit_resolver("tag:yaml.org,2002:bool", re.compile(r"^(?:true|false|True|False|TRUE|FALSE)$"), list("tTfF"))


def unique_mapping(loader, node, deep=False):
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError(f"Duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


ActionsLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def workflow_doc(data):
    result = yaml.load(data.decode("utf-8"), Loader=ActionsLoader)
    if not isinstance(result, dict) or not isinstance(result.get("jobs"), dict):
        raise ValueError("Workflow must contain a jobs mapping")
    for job_id, job in result["jobs"].items():
        if not isinstance(job, dict):
            raise ValueError("Workflow job must be a mapping: " + str(job_id))
        steps = job.get("steps", [])
        if not isinstance(steps, list) or any(not isinstance(step, dict) for step in steps):
            raise ValueError("Workflow steps must be a list of mappings: " + str(job_id))
        if any("with" in step and not isinstance(step["with"], dict) for step in steps):
            raise ValueError("Action inputs must be a mapping: " + str(job_id))
    return result


def workflow_diff(before, after, path):
    parts = difflib.unified_diff(before.decode("utf-8").splitlines(keepends=True),
                                 after.decode("utf-8").splitlines(keepends=True),
                                 fromfile="a/" + path, tofile="b/" + path)
    return "".join(part if part.endswith("\n") else part + "\n\\ No newline at end of file\n"
                   for part in parts)


def has_dispatch(doc):
    triggers = doc.get("on")
    return triggers == "workflow_dispatch" or (
        isinstance(triggers, (dict, list)) and "workflow_dispatch" in triggers)


def hazards(doc):
    text = yaml.safe_dump(doc).lower()
    findings = []
    if re.search(r"\b(deploy\w*|publish\w*|release|signing)\b|npm\s+publish|docker\s+push", text):
        findings.append("POSSIBLE_DEPLOY_PUBLISH_RELEASE")
    if "self-hosted" in text:
        findings.append("SELF_HOSTED_RUNNER")
    if re.search(r"secrets\s*(?:\.|\[)|secrets:\s*inherit", text):
        findings.append("SECRET_REFERENCE")
    if any("uses" in job for job in doc["jobs"].values()):
        findings.append("REUSABLE_WORKFLOW_NOT_INSPECTED")
    return findings


def protected_contract(before, after):
    """Check key workload invariants; this is not a semantic equivalence proof."""
    errors = []
    if set(before["jobs"]) != set(after["jobs"]):
        errors.append("JOB_SET_CHANGED")
        return errors
    for key in set(before) | set(after):
        if key != "jobs" and before.get(key) != after.get(key):
            errors.append(f"TOP_LEVEL_CHANGED:{key}")
    for job_id, original in before["jobs"].items():
        candidate = after["jobs"][job_id]
        # Preserve environment, dependencies, matrix, conditions, outputs,
        # permissions and runner selection. Steps may contain an approved edit.
        for key in set(original) | set(candidate):
            if key not in {"steps", "timeout-minutes"} and original.get(key) != candidate.get(key):
                errors.append(f"JOB_FIELD_CHANGED:{job_id}:{key}")
        commands_before = [step for step in original.get("steps", []) if "run" in step]
        commands_after = [step for step in candidate.get("steps", []) if "run" in step]
        if commands_before != commands_after:
            errors.append(f"RUN_COMMAND_OR_CONTEXT_CHANGED:{job_id}")
    return errors


def npm_cache_candidate(before, tree_paths):
    """Enable native setup-node npm caching without adding or removing steps."""
    doc = workflow_doc(before)
    changed = []
    lockfiles = {p for p in tree_paths if p.endswith(("package-lock.json", "npm-shrinkwrap.json"))}
    for job_id, job in doc["jobs"].items():
        steps = job.get("steps", [])
        defaults = {**doc.get("defaults", {}).get("run", {}), **job.get("defaults", {}).get("run", {})}
        if defaults.get("working-directory", ".") not in {".", "./"}:
            continue
        if not any(re.search(r"\bnpm\s+ci\b", str(s.get("run", ""))) for s in steps):
            continue
        if any(s.get("working-directory", ".") not in {".", "./"} or re.search(r"\bcd\s|--(?:prefix|workspace)", str(s.get("run", ""))) for s in steps):
            continue
        if any(str(s.get("uses", "")).lower().startswith("actions/cache") for s in steps):
            continue
        for index, step in enumerate(steps):
            uses = str(step.get("uses", ""))
            if not re.fullmatch(r"actions/setup-node@v[3456](?:\.\d+){0,2}", uses, re.I):
                continue
            if not any(str(s.get("uses", "")).lower().startswith("actions/checkout@")
                       and s.get("with", {}).get("path", ".") in {".", "./"}
                       and not s.get("with", {}).get("repository") for s in steps[:index]):
                continue
            if not any(re.search(r"\bnpm\s+ci\b", str(s.get("run", ""))) for s in steps[index + 1:]):
                continue
            options = step.setdefault("with", {})
            if options.get("cache"):
                continue
            # Explicit paths avoid guessing a monorepo's lockfile scope.
            if "package-lock.json" not in lockfiles and "npm-shrinkwrap.json" not in lockfiles:
                continue
            options["cache"] = "npm"
            options["cache-dependency-path"] = (
                "package-lock.json" if "package-lock.json" in lockfiles else "npm-shrinkwrap.json")
            changed.append({"job_id": job_id, "step_index": index, "uses": uses})
    if not changed:
        raise ValueError("NO_CHANGE: no supported setup-node/npm-ci job with a root lockfile and no equivalent cache. Supply a candidate workflow for another pattern.")
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True).encode("utf-8"), changed


class GitHub:
    def __init__(self, token, ledger):
        self.token, self.ledger = token, ledger

    def request(self, method, path, body=None):
        for attempt in range(4):
            began = time.monotonic()
            headers = {"User-Agent": "CloudTune-experiment/" + VERSION,
                       "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                       "Content-Type": "application/json",
                       "Authorization": "Bearer " + self.token}
            data = encode(body) if body is not None else None
            request = urllib.request.Request(API + path, data=data, headers=headers, method=method)
            status = "NETWORK_ERROR"
            try:
                with urllib.request.urlopen(request, timeout=45) as response:
                    status = response.status
                    raw = response.read()
                    return json.loads(raw) if raw else None
            except urllib.error.HTTPError as exc:
                status = exc.code
                # Retrying a dispatch/POST could create duplicate runs. Only GET retries.
                if method == "GET" and exc.code in {429, 500, 502, 503, 504} and attempt < 3:
                    time.sleep(min(30, 2 ** (attempt + 1)))
                    continue
                details = []
                try:
                    payload = json.loads(exc.read().decode("utf-8"))
                    if isinstance(payload.get("message"), str):
                        details.append(payload["message"][:400])
                except (ValueError, UnicodeDecodeError, AttributeError):
                    pass
                accepted = exc.headers.get("X-Accepted-GitHub-Permissions") if exc.headers else None
                if accepted:
                    details.append("accepted permissions: " + accepted[:300])
                suffix = "; " + redact("; ".join(details)) if details else ""
                raise RuntimeError(f"GitHub {method} {path}: HTTP {exc.code}{suffix}") from None
            finally:
                append_json(self.ledger, {"at": stamp(), "method": method, "path": path,
                                         "status": status, "elapsed_seconds": round(time.monotonic() - began, 3)})

    def pages(self, path, key):
        rows = []
        for page in range(1, 1001):
            separator = "&" if "?" in path else "?"
            data = self.request("GET", f"{path}{separator}per_page=100&page={page}")
            items = data[key] if key else data
            rows.extend(items)
            if len(items) < 100:
                return rows
        raise RuntimeError("Pagination limit exceeded; evidence is incomplete")

    def blob(self, repo, blob_sha):
        data = self.request("GET", f"/repos/{repo}/git/blobs/{blob_sha}")
        if data.get("encoding") != "base64":
            raise RuntimeError("Unsupported GitHub blob encoding")
        return base64.b64decode(data["content"])


def metrics(run, jobs, required_names):
    durations, completed, normalized = [], [], []
    incomplete = False
    for job in jobs:
        duration = seconds(job.get("started_at"), job.get("completed_at"))
        if job.get("conclusion") == "skipped" and duration is None:
            duration = 0.0
        if duration is None:
            incomplete = True
        else:
            durations.append(duration)
        if job.get("completed_at"):
            completed.append(job["completed_at"])
        normalized.append({"job_id": job["id"], "name": job["name"],
                           "status": job.get("status"), "conclusion": job.get("conclusion"),
                           "runner_labels": job.get("labels", []), "runner_name": job.get("runner_name"),
                           "duration_seconds": duration,
                           "steps": [{**s, "duration_seconds": seconds(s.get("started_at"), s.get("completed_at"))}
                                     for s in job.get("steps", [])]})
    required_pass = bool(required_names) and all(any(j["name"] == name for j in jobs) and
                        all(j.get("conclusion") == "success" for j in jobs if j["name"] == name)
                        for name in required_names)
    last = max(completed) if completed else None
    elapsed = seconds(run.get("run_started_at"), last)
    return {"workflow_elapsed_seconds": None if incomplete else elapsed,
            "elapsed_method": "run_started_at_to_last_job_completed_at; not billing time",
            "sum_job_runtime_seconds": None if incomplete or not jobs else sum(durations),
            "initial_queue_seconds": seconds(run.get("created_at"), run.get("run_started_at")),
            "completed_at_utc": last, "required_checks_pass": required_pass,
            "jobs": normalized}


def load_config(path):
    config = read_json(path)
    allowed = {"experiment_id", "fork_repo", "source_ref", "workflow_path", "pattern_id", "required_job_names",
               "repetitions", "warmup_runs", "cache_regime", "optimizer", "dispatch_inputs", "min_savings_percent",
               "poll_seconds", "run_timeout_seconds", "discovery_timeout_seconds", "max_total_runs", "split", "notes", "discover_required_jobs"}
    if set(config) - allowed:
        raise ValueError("Unknown configuration keys: " + ", ".join(sorted(set(config) - allowed)))
    for key in ("experiment_id", "fork_repo", "workflow_path", "pattern_id", "required_job_names", "optimizer"):
        if key not in config:
            raise ValueError("Missing configuration key: " + key)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", config["experiment_id"]):
        raise ValueError("experiment_id must be 1-64 letters, digits, underscores or hyphens")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", config["fork_repo"]):
        raise ValueError("fork_repo must be owner/repository")
    if not re.fullmatch(r"\.github/workflows/[^/]+\.ya?ml", config["workflow_path"]):
        raise ValueError("workflow_path must be a top-level .github/workflows YAML file")
    if type(config.get("discover_required_jobs", False)) is not bool:
        raise ValueError("discover_required_jobs must be boolean")
    if not isinstance(config["required_job_names"], list) or (not config["required_job_names"] and not config.get("discover_required_jobs")) or not all(
            isinstance(s, str) and s.strip() for s in config["required_job_names"]):
        raise ValueError("required_job_names must list actual GitHub job names, including every required matrix variant")
    defaults = {"source_ref": "HEAD", "repetitions": 5, "warmup_runs": 0, "cache_regime": "uncontrolled",
                "dispatch_inputs": {}, "min_savings_percent": 5.0, "poll_seconds": 10,
                "run_timeout_seconds": 7200, "discovery_timeout_seconds": 180,
                "max_total_runs": 12, "split": "development", "notes": ""}
    config = {**defaults, **config}
    for key in ("repetitions", "max_total_runs", "poll_seconds", "run_timeout_seconds", "discovery_timeout_seconds"):
        if type(config[key]) is not int or config[key] < 1:
            raise ValueError(key + " must be a positive integer")
    if type(config["warmup_runs"]) is not int or config["warmup_runs"] < 0:
        raise ValueError("warmup_runs must be a nonnegative integer")
    if config["poll_seconds"] > 60:
        raise ValueError("poll_seconds must be at most 60")
    if 2 * (config["repetitions"] + config["warmup_runs"]) > config["max_total_runs"]:
        raise ValueError("max_total_runs is smaller than planned baseline + optimized executions")
    if config["split"] not in {"development", "pilot"}:
        raise ValueError("This knowledge-building runner accepts only development or pilot repositories")
    if config["cache_regime"] not in {"uncontrolled", "warm", "cold"}:
        raise ValueError("cache_regime must be uncontrolled, warm or cold")
    # Cache hits are not exposed by the jobs API. Never infer a controlled regime.
    if config["cache_regime"] != "uncontrolled":
        raise ValueError("This version does not reset or verify caches; use uncontrolled and run separate cache-behavior scenarios")
    if not isinstance(config["dispatch_inputs"], dict):
        raise ValueError("dispatch_inputs must be an object")
    threshold = config["min_savings_percent"]
    if type(threshold) not in {int, float} or not math.isfinite(threshold) or not 0 <= threshold < 100:
        raise ValueError("min_savings_percent must be a finite number from 0 to less than 100")
    optimizer = config["optimizer"]
    if not isinstance(optimizer, dict) or optimizer.get("type") not in {"npm-cache", "candidate-file", "openrouter-free"}:
        raise ValueError("optimizer.type must be npm-cache, candidate-file or openrouter-free")
    if set(optimizer) - {"type", "path", "model", "max_tokens"}:
        raise ValueError("optimizer accepts only type, path, model and max_tokens; put credentials in environment variables")
    if optimizer["type"] == "openrouter-free":
        validate_free_model(optimizer.get("model", DEFAULT_FREE_MODEL))
        if type(optimizer.get("max_tokens", 24000)) is not int or not 256 <= optimizer.get("max_tokens", 24000) <= 48000:
            raise ValueError("optimizer.max_tokens must be an integer from 256 to 48000")
    if optimizer["type"] == "candidate-file":
        if not optimizer.get("path"):
            raise ValueError("candidate-file requires optimizer.path")
        candidate_path = Path(optimizer["path"])
        optimizer["path"] = str(candidate_path if candidate_path.is_absolute() else (path.parent / candidate_path).resolve())
    return config


@contextmanager
def exclusive(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps({"pid": os.getpid(), "started_at": stamp()}))
    except FileExistsError:
        raise RuntimeError(f"Experiment is locked: {path}. If a previous process crashed, confirm it has stopped before removing this lock.") from None
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def update_catalog():
    """Regenerate research-plan indexes from this runner's durable case folders."""
    data = ROOT / "research-data"
    with exclusive(data / "experiments" / ".catalog.lock"):
        records, cases = [], []
        for directory in sorted((data / "experiments").iterdir()):
            if not directory.is_dir():
                continue
            runs = directory / "run_records.json"
            case = directory / "case.json"
            if runs.exists():
                records.extend(read_json(runs))
            if case.exists():
                cases.append(read_json(case))
        runs_path = data / "runs" / "experiment_runs.csv"
        runs_path.parent.mkdir(parents=True, exist_ok=True)
        temp = runs_path.with_suffix(".csv.tmp")
        with temp.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(records)
        temp.replace(runs_path)
        cases_path = data / "knowledge" / "verified_cases.jsonl"
        cases_path.parent.mkdir(parents=True, exist_ok=True)
        temp = cases_path.with_suffix(".jsonl.tmp")
        temp.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cases), encoding="utf-8")
        temp.replace(cases_path)
        analysis = data / "analysis" / "per_repo_results.csv"
        analysis.parent.mkdir(parents=True, exist_ok=True)
        temp = analysis.with_suffix(".csv.tmp")
        with temp.open("w", newline="", encoding="utf-8") as handle:
            columns = ["experiment_id", "repo_id", "pattern_id", "arm", "outcome", "total_runs", "usable_successes", "median_elapsed_seconds", "median_job_runtime_seconds"]
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            for case in cases:
                for arm, stats in case["arms"].items():
                    writer.writerow({"experiment_id": case["case_id"], "repo_id": case["source_repo_id"],
                                     "pattern_id": case["pattern_id"], "arm": arm, "outcome": case["outcome"], **stats})
        temp.replace(analysis)


class Experiment:
    def __init__(self, config, token=None):
        self.config = config
        self.directory = ROOT / "research-data" / "experiments" / config["experiment_id"]
        self.directory.mkdir(parents=True, exist_ok=True)
        frozen = self.directory / "config.json"
        if frozen.exists() and read_json(frozen) != config:
            raise ValueError("Configuration changed for an existing experiment. Use a new experiment_id.")
        write_json(frozen, config)
        self.state_path = self.directory / "state.json"
        self.state = read_json(self.state_path) if self.state_path.exists() else {"records": [], "pending": None, "arms": {}, "dispatch_count": 0}
        self.github = GitHub(token, self.directory / "api_calls.jsonl") if token else None
        self.repo = config["fork_repo"]
        self.prefix = "/repos/" + self.repo

    def save(self):
        write_json(self.state_path, self.state)

    def event(self, kind, **values):
        append_json(self.directory / "events.jsonl", {"at": stamp(), "kind": kind, **values})

    def required_job_names(self):
        return self.config["required_job_names"] or self.state.get("resolved_required_job_names", [])

    def prepare(self):
        if self.state.get("prepared"):
            return
        repository = self.github.request("GET", self.prefix)
        if not repository.get("fork") or not repository.get("permissions", {}).get("push"):
            raise ValueError("Use an existing fork where the token has push permission")
        if repository.get("archived") or repository.get("disabled"):
            raise ValueError("Fork is archived or disabled")
        source_ref = repository["default_branch"] if self.config["source_ref"] == "HEAD" else self.config["source_ref"]
        commit = self.github.request("GET", self.prefix + "/commits/" + urllib.parse.quote(source_ref, safe=""))
        tree_sha = commit["commit"]["tree"]["sha"]
        tree = self.github.request("GET", self.prefix + f"/git/trees/{tree_sha}?recursive=1")
        if tree.get("truncated"):
            raise ValueError("Repository tree is truncated; cannot establish a complete snapshot")
        blobs = {p["path"]: p for p in tree["tree"] if p["type"] == "blob"}
        target = self.config["workflow_path"]
        if target not in blobs:
            raise ValueError("Chosen workflow is absent at the pinned source commit")
        before = self.github.blob(self.repo, blobs[target]["sha"])
        original = workflow_doc(before)
        if not has_dispatch(original):
            raise ValueError("Unchanged workflow has no workflow_dispatch event. Prepare the dispatch harness in the fork before pinning a new baseline; this runner does not silently alter the original workflow.")
        found = hazards(original)
        if found:
            raise ValueError("Target workflow needs fork preparation before recording a baseline: " + ", ".join(found))
        registry = [json.loads(line) for line in (ROOT / "knowledge/extracted_patterns.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        pattern = next((p for p in registry if p["pattern_id"] == self.config["pattern_id"]), None)
        if not pattern:
            raise ValueError("Unknown pattern_id in canonical extracted_patterns.jsonl")
        # Dispatch cannot measure event filtering, cancellation, scheduling, or queue policies faithfully.
        if pattern["pattern_id"] in SCENARIO_PATTERNS:
            raise ValueError("This pattern requires a separate event/history/scenario benchmark, not paired workflow_dispatch timing")
        if self.config["optimizer"]["type"] == "npm-cache" and pattern["pattern_id"] != "P-LIT-GHA-CACHE":
            raise ValueError("npm-cache must be measured against P-LIT-GHA-CACHE")
        # Workflow registration/default-branch support must already exist.
        workflow = self.github.request("GET", self.prefix + "/actions/workflows/" + urllib.parse.quote(Path(target).name, safe=""))
        if workflow.get("state") != "active":
            raise ValueError("Chosen workflow is not active; enable it in the fork first")
        default_commit = self.github.request("GET", self.prefix + "/commits/" + urllib.parse.quote(repository["default_branch"], safe=""))
        default_tree = self.github.request("GET", self.prefix + f"/git/trees/{default_commit['commit']['tree']['sha']}?recursive=1")
        if default_tree.get("truncated"):
            raise ValueError("Default-branch tree is truncated")
        # Chained workflow_run listeners can publish/deploy even when target CI is harmless.
        for entry in default_tree["tree"]:
            if entry["type"] == "blob" and re.fullmatch(r"\.github/workflows/[^/]+\.ya?ml", entry["path"]):
                content = self.github.blob(self.repo, entry["sha"])
                doc = workflow_doc(content)
                triggers = doc.get("on")
                if triggers == "workflow_run" or isinstance(triggers, (list, dict)) and "workflow_run" in triggers:
                    raise ValueError("Fork has a workflow_run listener; disable/remove that listener before pinning the experiment")
                if entry["path"] == target and not has_dispatch(doc):
                    raise ValueError("Default-branch workflow must support workflow_dispatch")
        source = self.directory / "source"
        source.mkdir(exist_ok=True)
        write_json(source / "repository.json", repository)
        write_json(source / "commit.json", commit)
        write_json(source / "tree.json", tree)
        write_json(source / "pattern.json", pattern)
        write_json(source / "default_commit.json", default_commit)
        write_json(source / "default_tree.json", default_tree)
        (self.directory / "before.yml").write_bytes(before)
        manifest_names = {"package.json", "package-lock.json", "npm-shrinkwrap.json", "pyproject.toml", "requirements.txt",
                          "pom.xml", "build.gradle", "go.mod", "Cargo.toml", "Makefile", "WORKSPACE", "MODULE.bazel"}
        archived, omitted = [], []
        for path, entry in blobs.items():
            if Path(path).name not in manifest_names and not re.fullmatch(r"\.github/workflows/[^/]+\.ya?ml", path):
                continue
            if entry.get("mode") == "120000" or entry.get("size", 0) > 2_000_000 or len(archived) >= 100:
                omitted.append({"path": path, "reason": "symlink, >2MB or 100-file context limit"})
                continue
            relative = Path(path)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Unsafe repository tree path")
            destination = source / "files" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            content = self.github.blob(self.repo, entry["sha"])
            destination.write_bytes(content)
            archived.append({"path": path, "git_blob_sha": entry["sha"], "sha256": sha(content)})
        write_json(source / "files_manifest.json", {"archived": archived, "omitted": omitted})
        self.state.update({"prepared": True, "source_sha": commit["sha"], "tree_sha": tree_sha,
                           "workflow_id": workflow["id"], "before_sha256": sha(before),
                           "family_id": repository.get("parent", {}).get("full_name", self.repo)})
        self.save()
        self.event("prepared", source_sha=commit["sha"], pattern_id=pattern["pattern_id"])
        print("Collected pinned workflow, repository tree, manifests and pattern evidence.", flush=True)

    def branch(self, arm):
        if not self.state.get("prepared"):
            raise ValueError("Run prepare first")
        existing = self.state["arms"].get(arm)
        if not existing:
            tree_sha = self.state["tree_sha"]
            if arm == "optimized":
                self.check_proposal()
                after = (self.directory / "after.yml").read_bytes()
                blob = self.github.request("POST", self.prefix + "/git/blobs", {"content": base64.b64encode(after).decode(), "encoding": "base64"})
                new_tree = self.github.request("POST", self.prefix + "/git/trees", {"base_tree": tree_sha, "tree": [{"path": self.config["workflow_path"], "mode": "100644", "type": "blob", "sha": blob["sha"]}]})
                tree_sha = new_tree["sha"]
            commit = self.github.request("POST", self.prefix + "/git/commits", {
                "message": f"[skip ci] CloudTune {self.config['experiment_id']} {arm}",
                "tree": tree_sha, "parents": [self.state["source_sha"]]})
            existing = {"sha": commit["sha"], "branch": f"codex/ct-{self.config['experiment_id']}-{arm}", "tree_sha": tree_sha}
            self.state["arms"][arm] = existing
            self.save()  # Persist expected ref before its creation can trigger anything.
        branch_path = self.prefix + "/git/ref/heads/" + existing["branch"]
        try:
            ref = self.github.request("GET", branch_path)
        except RuntimeError as exc:
            if "HTTP 404" not in str(exc):
                raise
            self.github.request("POST", self.prefix + "/git/refs", {"ref": "refs/heads/" + existing["branch"], "sha": existing["sha"]})
        else:
            if ref["object"]["sha"] != existing["sha"]:
                raise ValueError("Experiment branch moved unexpectedly; refusing to run another revision")
        remote_tree = self.github.request("GET", self.prefix + f"/git/trees/{existing['tree_sha']}?recursive=1")
        original = read_json(self.directory / "source/tree.json")
        def unaffected(tree):
            return sorted((p["path"], p["mode"], p["type"], p["sha"]) for p in tree["tree"]
                          if p["type"] != "tree" and p["path"] != self.config["workflow_path"])
        if remote_tree.get("truncated") or unaffected(original) != unaffected(remote_tree):
            raise ValueError("Non-target files differ between source and arm")
        write_json(self.directory / f"{arm}_tree.json", remote_tree)
        return existing

    def optimize(self):
        measured = [r for r in self.state["records"] if r["arm"] == "baseline" and not r["warmup"]]
        if len(measured) < self.config["repetitions"]:
            raise ValueError("Complete the configured baseline measurements before optimizing")
        if not all(r["conclusion"] == "success" and r["required_checks_pass"] and r["protocol_valid"] for r in measured):
            raise ValueError("Baseline is not reproducibly successful with all required checks; retained results need investigation")
        if self.state.get("proposal"):
            self.check_proposal(require_review=False)
            return
        before = (self.directory / "before.yml").read_bytes()
        if sha(before) != self.state["before_sha256"]:
            raise ValueError("Pinned before.yml was modified")
        pattern = read_json(self.directory / "source/pattern.json")
        request = {"pattern": pattern,
                   "question": "Apply the selected pattern to this workflow even if its performance benefit is uncertain. Preserve all existing checks and commands.",
                   "before_ref": "before.yml", "source_sha": self.state["source_sha"],
                   "baseline_records": measured, "required_job_names": self.required_job_names(),
                   "instruction": "Implement one concrete change using only the selected method, even if it may not improve performance. Keep all existing install and test commands so the measured workflow can pass; do not return NO_CHANGE."}
        write_json(self.directory / "optimization_request.json", request)
        optimizer = self.config["optimizer"]
        if optimizer["type"] == "npm-cache":
            tree = read_json(self.directory / "source/tree.json")
            after, changes = npm_cache_candidate(before, [p["path"] for p in tree["tree"]])
        elif optimizer["type"] == "openrouter-free":
            after, llm = generate_openrouter(self.directory, request, before,
                                             optimizer.get("model", DEFAULT_FREE_MODEL), optimizer.get("max_tokens", 24000))
            changes = []
        else:
            after, changes = Path(optimizer["path"]).read_bytes(), []
        (self.directory / "after.yml").write_bytes(after)
        diff = workflow_diff(before, after, self.config["workflow_path"])
        (self.directory / "change.diff").write_text(diff, encoding="utf-8", newline="")
        errors = protected_contract(workflow_doc(before), workflow_doc(after))
        errors += hazards(workflow_doc(after))
        if optimizer["type"] == "openrouter-free":
            errors += scope_errors(workflow_doc(before), workflow_doc(after), pattern["mechanism"])
        no_change = before == after
        if no_change:
            errors.append("NO_CHANGE")
        proposal = {"generator": optimizer["type"], "runner_version": VERSION, "pattern_id": self.config["pattern_id"],
                    "before_sha256": sha(before), "after_sha256": sha(after), "diff_sha256": sha(diff.encode()),
                    "automatic_changes": changes, "structural_errors": errors,
                    "verdict": "FAIL" if errors else "PASS_BOUNDED_STRUCTURAL_CHECKS",
                    "no_change": no_change,
                    "semantic_preservation": "human and change-specific behavior review required"}
        if optimizer["type"] == "openrouter-free":
            proposal["llm"] = llm
        actionlint = shutil.which("actionlint")
        if actionlint:
            lint = subprocess.run([actionlint, "-shellcheck=", "-pyflakes=", "-"], input=after,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60, check=False)
            (self.directory / "actionlint.txt").write_bytes(lint.stdout)
            proposal["actionlint"] = "PASS" if lint.returncode == 0 else "FAIL"
            if lint.returncode:
                errors.append("ACTIONLINT_FAILED")
                proposal["verdict"] = "FAIL"
        else:
            proposal["actionlint"] = "not installed; only YAML parsing and bounded structural checks performed"
        write_json(self.directory / "proposal.json", proposal)
        self.state["proposal"] = proposal
        self.save()
        self.event("proposal_generated", **proposal)
        if errors:
            raise ValueError("Proposal rejected: " + ", ".join(errors))
        print("Saved after.yml, change.diff, optimization request and structural validation.", flush=True)

    def check_proposal(self, require_review=True):
        proposal = self.state.get("proposal")
        if not proposal:
            raise ValueError("Run optimize first")
        for filename, key in (("before.yml", "before_sha256"), ("after.yml", "after_sha256"), ("change.diff", "diff_sha256")):
            if sha((self.directory / filename).read_bytes()) != proposal[key]:
                raise ValueError("Stored proposal artifact changed: " + filename)
        if proposal["structural_errors"]:
            raise ValueError("Proposal has structural errors; use a new experiment after fixing the candidate")
        if require_review and proposal["generator"] == "candidate-file":
            review = self.review()
            if review.get("verdict") != "PASS":
                raise ValueError("Candidate workflow awaits review. Save candidate_review.json with this proposal's diff_sha256, reviewed_by, verdict PASS and rationale; see experiments/README.md")

    def review(self):
        path = self.directory / "candidate_review.json"
        if not path.exists():
            return {}
        review = read_json(path)
        if not review.get("reviewed_by") or not review.get("rationale") or review.get("diff_sha256") != self.state.get("proposal", {}).get("diff_sha256"):
            raise ValueError("Review must name a reviewer, rationale and the exact current diff hash")
        return review

    def find_pending(self):
        pending = self.state["pending"]
        arm_info = self.state["arms"][pending["arm"]]
        path = self.prefix + f"/actions/workflows/{self.state['workflow_id']}/runs?" + urllib.parse.urlencode({"branch": arm_info["branch"], "event": "workflow_dispatch", "head_sha": arm_info["sha"]})
        runs = self.github.pages(path, "workflow_runs")
        matches = [r for r in runs if r["id"] not in pending["before_run_ids"]
                   and r.get("head_sha") == arm_info["sha"] and r.get("head_branch") == arm_info["branch"]]
        if len(matches) > 1:
            raise RuntimeError("Multiple matching dispatches found; attach the intended run explicitly with attach-run --run-id")
        return matches[0]["id"] if matches else None

    def collect_pending(self):
        pending = self.state["pending"]
        began = time.monotonic()
        while not pending.get("run_id"):
            pending["run_id"] = self.find_pending()
            self.save()
            if pending["run_id"]:
                break
            if time.monotonic() - began > self.config["discovery_timeout_seconds"]:
                raise RuntimeError("Dispatch outcome is uncertain; no automatic resend. Resume later or attach a known run ID; pending dispatch is retained.")
            time.sleep(self.config["poll_seconds"])
        run_id = pending["run_id"]
        while True:
            run = self.github.request("GET", self.prefix + f"/actions/runs/{run_id}")
            if run.get("status") == "completed":
                break
            if seconds(pending["sent_at"], stamp()) > self.config["run_timeout_seconds"]:
                raise RuntimeError(f"Run {run_id} exceeded local waiting limit; it is still tracked and has not been canceled. Resume to collect it.")
            print(f"{pending['arm']} run {run_id}: {run.get('status')}", flush=True)
            time.sleep(self.config["poll_seconds"])
        attempt = run.get("run_attempt", 1)
        jobs = self.github.pages(self.prefix + f"/actions/runs/{run_id}/attempts/{attempt}/jobs", "jobs")
        raw = self.directory / "runs" / f"{run_id}-attempt-{attempt}"
        write_json(raw / "run.json", run)
        write_json(raw / "jobs.json", jobs)
        if self.config.get("discover_required_jobs") and not self.required_job_names() and pending["arm"] == "baseline":
            self.state["resolved_required_job_names"] = sorted({j["name"] for j in jobs if j.get("conclusion") != "skipped"})
            self.state["required_checks_source"] = "observed baseline jobs; not owner-approved branch protection"
            self.save()
        details = metrics(run, jobs, self.required_job_names())
        write_json(raw / "metrics.json", details)
        artifacts = self.github.pages(self.prefix + f"/actions/runs/{run_id}/artifacts", "artifacts")
        write_json(raw / "artifacts.json", artifacts)
        info = self.state["arms"][pending["arm"]]
        valid = run.get("head_sha") == info["sha"] and run.get("event") == "workflow_dispatch" and run.get("head_branch") == info["branch"] and run.get("workflow_id") == self.state["workflow_id"] and attempt == 1
        reasons = []
        if not valid:
            reasons.append("RUN_IDENTITY_OR_ATTEMPT_MISMATCH")
        if not details["required_checks_pass"]:
            reasons.append("REQUIRED_CHECK_MISSING_OR_NOT_SUCCESSFUL")
        if run.get("conclusion") != "success":
            reasons.append("CI_" + str(run.get("conclusion")))
        if details["workflow_elapsed_seconds"] is None or details["sum_job_runtime_seconds"] is None:
            reasons.append("INCOMPLETE_TIMING")
        record = {"experiment_id": self.config["experiment_id"], "repo_id": self.repo,
                  "source_commit_sha": self.state["source_sha"], "config_commit_sha": info["sha"],
                  "workflow_path": self.config["workflow_path"], "pattern_id": self.config["pattern_id"],
                  "arm": pending["arm"], "repeat_index": pending["repeat_index"], "warmup": pending["warmup"],
                  "cache_regime": self.config["cache_regime"], "run_id": run_id, "run_attempt": attempt,
                  "event": run.get("event"), "status": run.get("status"), "conclusion": run.get("conclusion"),
                  "started_at_utc": run.get("run_started_at"), "completed_at_utc": details["completed_at_utc"],
                  "workflow_elapsed_seconds": details["workflow_elapsed_seconds"],
                  "sum_job_runtime_seconds": details["sum_job_runtime_seconds"],
                  "initial_queue_seconds": details["initial_queue_seconds"], "required_checks_pass": details["required_checks_pass"],
                  "protocol_valid": valid, "failure_reason": ";".join(reasons), "raw_ref": str(raw.relative_to(ROOT)),
                  "job_names": sorted(j["name"] for j in jobs),
                  "job_outcomes": sorted((j["name"], j.get("conclusion")) for j in jobs)}
        # Atomic state is canonical. CSV/JSONL are regenerated and never append duplicates on resume.
        self.state["records"].append(record)
        self.state["pending"] = None
        self.save()
        self.export_runs()
        self.event("run_collected", run_id=run_id, arm=record["arm"], conclusion=record["conclusion"])
        print(f"Stored {record['arm']} run {run_id}: {record['conclusion']}; elapsed={record['workflow_elapsed_seconds']}s; job-runtime={record['sum_job_runtime_seconds']}s", flush=True)
        return record

    def export_runs(self):
        records = self.state["records"]
        write_json(self.directory / "run_records.json", records)
        with (self.directory / "experiment_runs.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(records)
        update_catalog()

    def require_successful_attempts(self, arm):
        failed = next((record for record in self.state["records"]
                       if record["arm"] == arm and
                       (record["conclusion"] != "success" or not record["required_checks_pass"] or
                        not record["protocol_valid"])), None)
        if failed:
            attempt_kind = "warmup" if failed.get("warmup") else "measured"
            raise RuntimeError(
                f"{arm.capitalize()} {attempt_kind} attempt {failed['repeat_index']} failed "
                f"(run {failed.get('run_id')}, conclusion={failed.get('conclusion')}, "
                f"reason={failed.get('failure_reason') or 'required checks/protocol did not pass'}); "
                "stopping this repository after the first failed attempt")

    def measure(self, arm):
        if arm == "optimized":
            self.check_proposal()
        self.require_successful_attempts(arm)
        info = self.branch(arm)
        if self.state.get("pending"):
            pending_arm = self.state["pending"]["arm"]
            self.collect_pending()
            if pending_arm != arm:
                print("Recovered pending run for " + pending_arm, flush=True)
        self.require_successful_attempts(arm)
        total = self.config["repetitions"] + self.config["warmup_runs"]
        for slot in range(total):
            warmup = slot < self.config["warmup_runs"]
            repeat = slot + 1 if warmup else slot - self.config["warmup_runs"] + 1
            if any(r["arm"] == arm and r["warmup"] == warmup and r["repeat_index"] == repeat for r in self.state["records"]):
                continue
            if self.state["dispatch_count"] >= self.config["max_total_runs"]:
                raise RuntimeError("Dispatch budget exhausted; no more workflow runs will be created")
            repository = read_json(self.directory / "source/repository.json")
            current_default = self.github.request("GET", self.prefix + "/commits/" + urllib.parse.quote(repository["default_branch"], safe=""))
            if current_default["sha"] != read_json(self.directory / "source/default_commit.json")["sha"]:
                raise ValueError("Fork default branch changed since preflight; create a new experiment after reviewing its listeners")
            # Confirm no one has moved the branch since the previous repetition.
            ref = self.github.request("GET", self.prefix + "/git/ref/heads/" + info["branch"])
            if ref["object"]["sha"] != info["sha"]:
                raise ValueError("Experiment branch moved; refusing dispatch")
            query = urllib.parse.urlencode({"branch": info["branch"], "event": "workflow_dispatch", "head_sha": info["sha"]})
            old = self.github.pages(self.prefix + f"/actions/workflows/{self.state['workflow_id']}/runs?{query}", "workflow_runs")
            self.state["pending"] = {"arm": arm, "repeat_index": repeat, "warmup": warmup,
                                     "sent_at": stamp(), "before_run_ids": [r["id"] for r in old], "run_id": None}
            self.state["dispatch_count"] += 1
            self.save()  # Never resend automatically after an uncertain network response.
            self.event("dispatch_intent", **self.state["pending"])
            response = self.github.request("POST", self.prefix + f"/actions/workflows/{self.state['workflow_id']}/dispatches", {
                "ref": info["branch"], "inputs": self.config["dispatch_inputs"]})
            if response and response.get("workflow_run_id"):
                self.state["pending"]["run_id"] = response["workflow_run_id"]
                self.save()
            self.collect_pending()
            self.require_successful_attempts(arm)

    def report(self):
        records = self.state["records"]
        arms = {}
        for name in ("baseline", "optimized"):
            rows = [r for r in records if r["arm"] == name and not r["warmup"]]
            usable = [r for r in rows if r["protocol_valid"] and r["conclusion"] == "success" and r["required_checks_pass"] and r["workflow_elapsed_seconds"] is not None and r["sum_job_runtime_seconds"] is not None]
            arms[name] = {"total_runs": len(rows), "usable_successes": len(usable),
                          "conclusions": {c: sum(r["conclusion"] == c for r in rows) for c in sorted({str(r["conclusion"]) for r in rows})},
                          "median_elapsed_seconds": statistics.median(r["workflow_elapsed_seconds"] for r in usable) if usable else None,
                          "median_job_runtime_seconds": statistics.median(r["sum_job_runtime_seconds"] for r in usable) if usable else None}
        baseline, optimized = arms["baseline"], arms["optimized"]
        savings = None
        if baseline["median_elapsed_seconds"] and optimized["median_elapsed_seconds"] is not None:
            savings = 100 * (baseline["median_elapsed_seconds"] - optimized["median_elapsed_seconds"]) / baseline["median_elapsed_seconds"]
        reasons = []
        outcome = "inconclusive"
        proposal = self.state.get("proposal", {})
        review = self.review() if proposal else {}
        if proposal.get("structural_errors") and proposal["structural_errors"] != ["NO_CHANGE"]:
            outcome, reasons = "unsafe", ["Structural safety contract failed"]
        else:
            if proposal.get("structural_errors") == ["NO_CHANGE"]:
                reasons.append("NO_CHANGE proposal retained; optimized measurements not executed")
            for name, stats in arms.items():
                if stats["total_runs"] < self.config["repetitions"] or stats["usable_successes"] != stats["total_runs"]:
                    reasons.append(name + ": insufficient complete comparable successful measurements; failures retained")
            baseline_names = {tuple(r["job_names"]) for r in records if r["arm"] == "baseline" and not r["warmup"]}
            optimized_names = {tuple(r["job_names"]) for r in records if r["arm"] == "optimized" and not r["warmup"]}
            if baseline_names != optimized_names:
                reasons.append("Executed job/matrix name sets differ")
            baseline_outcomes = {tuple(tuple(j) for j in r["job_outcomes"]) for r in records if r["arm"] == "baseline" and not r["warmup"]}
            optimized_outcomes = {tuple(tuple(j) for j in r["job_outcomes"]) for r in records if r["arm"] == "optimized" and not r["warmup"]}
            if baseline_outcomes != optimized_outcomes:
                reasons.append("Per-job success/failure/skipped outcomes differ")
            if review.get("verdict") != "PASS":
                reasons.append("Independent safety review pending")
            behavior = review.get("behavior_validation", {})
            if behavior.get("status") != "PASS" or not behavior.get("evidence_refs"):
                reasons.append("Change-specific behavioral evidence pending (for caching: cold, warm, changed lockfile, invalidation)")
            if not reasons and savings is not None:
                outcome = "safe_success" if not proposal.get("no_change") and savings > 0 and savings >= self.config["min_savings_percent"] else "safe_no_gain"
        runtime_improved = bool(
            baseline["median_elapsed_seconds"] is not None
            and optimized["median_elapsed_seconds"] is not None
            and optimized["median_elapsed_seconds"] < baseline["median_elapsed_seconds"])
        # A pattern example must show a real elapsed-time improvement, in
        # addition to a valid change and complete successful measurements.
        pattern_satisfied = bool(
            proposal and not proposal.get("no_change", True) and not proposal.get("structural_errors")
            and all(stats["total_runs"] == self.config["repetitions"] and
                    stats["usable_successes"] == self.config["repetitions"] for stats in arms.values())
            and runtime_improved
            and workflow_doc((self.directory / "before.yml").read_bytes()) !=
                workflow_doc((self.directory / "after.yml").read_bytes()))
        case = {"case_id": self.config["experiment_id"], "record_kind": "verified_experiment_case",
                "pattern_satisfied": pattern_satisfied,
                "pattern_satisfaction_scope": "changed YAML passed selected-pattern scope checks, all paired CI runs, and optimized median workflow elapsed time is lower than baseline; independent review remains separate",
                "runtime_improved": runtime_improved,
                "split": self.config["split"], "source_repo_id": self.repo, "family_id": self.state.get("family_id"),
                "source_commit_sha": self.state.get("source_sha"), "workflow_path": self.config["workflow_path"],
                "pattern_id": self.config["pattern_id"], "outcome": outcome, "reasons": reasons,
                "required_job_names": self.required_job_names(),
                "required_checks_source": self.state.get("required_checks_source", "configured job names"),
                "no_change": proposal.get("no_change", False), "llm": proposal.get("llm"),
                "realized_optimization_savings_percent": 0 if proposal.get("no_change") else savings,
                "arms": arms, "elapsed_savings_percent": savings,
                "min_savings_percent": self.config["min_savings_percent"], "run_ids": [r["run_id"] for r in records],
                "patch_ref": str((self.directory / "change.diff").relative_to(ROOT)) if proposal else None,
                "patch_sha256": proposal.get("diff_sha256"), "before_sha256": self.state.get("before_sha256"),
                "after_sha256": proposal.get("after_sha256"), "review": review,
                "before_ref": str((self.directory / "before.yml").relative_to(ROOT)),
                "after_ref": str((self.directory / "after.yml").relative_to(ROOT)) if proposal else None,
                "run_records_ref": str((self.directory / "run_records.json").relative_to(ROOT)),
                "rag_admission": "eligible_for_review" if outcome in {"safe_success", "safe_no_gain", "unsafe"} and review.get("verdict") == "PASS" else "pending_review",
                "protocol": {"ordering": "baseline block, then optimized block; possible environmental drift",
                             "cache_regime": self.config["cache_regime"], "runner_version": VERSION,
                             "config_sha256": sha(encode(self.config)), "cost": "job runtime, not billed cost",
                             "uncertainty": "pilot medians only; no statistical significance claim"}}
        write_json(self.directory / "case.json", case)
        self.export_runs()
        md = [f"# Experiment {self.config['experiment_id']}", "", f"Outcome: **{outcome}**", "",
              "| Arm | Recorded measured runs | Usable successes | Median elapsed seconds | Median job runtime seconds |",
              "|---|---:|---:|---:|---:|"]
        for name, stats in arms.items():
            md.append(f"| {name} | {stats['total_runs']} | {stats['usable_successes']} | {stats['median_elapsed_seconds']} | {stats['median_job_runtime_seconds']} |")
        md += ["", f"Elapsed savings: {savings}%", "", *["- " + r for r in reasons], "",
               "All failed, canceled, skipped and warm-up attempts remain in the run records. Logs/artifact binaries are not downloaded; raw API evidence includes run, job, step, and artifact metadata.",
               "Timing uses run start to final job completion. Runner runtime is summed across jobs; it is not billed usage.",
               "Runs are sequential baseline then optimized; environmental drift and unverified cache state remain limitations."]
        (self.directory / "REPORT.md").write_text("\n".join(md) + "\n", encoding="utf-8")
        manifest = {str(path.relative_to(self.directory)): sha(path.read_bytes())
                    for path in sorted(self.directory.rglob("*")) if path.is_file()
                    and path.name not in {".lock", "artifact_manifest.json"} and not path.name.endswith(".tmp")}
        write_json(self.directory / "artifact_manifest.json", {"generated_at": stamp(), "files": manifest})
        print(f"Outcome: {outcome}; elapsed savings: {savings}%; report: {self.directory / 'REPORT.md'}", flush=True)
        return case

    def attach(self, run_id):
        pending = self.state.get("pending")
        if not pending:
            raise ValueError("No pending dispatch to attach")
        run = self.github.request("GET", self.prefix + f"/actions/runs/{run_id}")
        arm = self.state["arms"][pending["arm"]]
        if (run.get("head_sha"), run.get("head_branch"), run.get("event"), run.get("workflow_id")) != (arm["sha"], arm["branch"], "workflow_dispatch", self.state["workflow_id"]) or run_id in pending["before_run_ids"]:
            raise ValueError("Run does not match the pending dispatch identity")
        pending["run_id"] = run_id
        self.save()
        self.collect_pending()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "baseline", "optimize", "optimized", "report", "run", "attach-run"))
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--run-id", type=int, help="Only for attach-run when resolving a pending dispatch")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    args = parser.parse_args()
    experiment = None
    acquired = False
    try:
        load_env(args.env_file)
        config = load_config(args.config.resolve())
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if args.command not in {"report", "optimize"} and not token:
            raise ValueError("Set GITHUB_TOKEN or GH_TOKEN in your environment; never store credentials in the configuration")
        experiment = Experiment(config, token)
        with exclusive(experiment.directory / ".lock"):
            acquired = True
            if args.command in {"prepare", "run"}:
                experiment.prepare()
            if args.command in {"baseline", "run"}:
                experiment.measure("baseline")
            if args.command in {"optimize", "run"}:
                experiment.optimize()
            if args.command in {"optimized", "run"}:
                experiment.measure("optimized")
            if args.command == "attach-run":
                if not args.run_id:
                    raise ValueError("attach-run requires --run-id")
                experiment.attach(args.run_id)
            if args.command in {"report", "run"}:
                experiment.report()
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError, yaml.YAMLError) as exc:
        # Response bodies and credential values are never written to error records.
        message = redact(str(exc))
        if experiment:
            experiment.event("error", command=args.command, error_type=type(exc).__name__, message=message)
            if acquired and experiment.state.get("prepared"):
                try:
                    with exclusive(experiment.directory / ".lock"):
                        experiment.report()
                except (OSError, ValueError, RuntimeError, KeyError, TypeError):
                    pass  # Preserve the original error; durable run evidence remains.
        print("Error: " + message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
