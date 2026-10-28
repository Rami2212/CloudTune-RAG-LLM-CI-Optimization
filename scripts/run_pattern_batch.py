"""Interactive fork -> 3 baseline runs -> selected-pattern free LLM -> 3 runs -> next repo."""
from __future__ import annotations

import argparse
import csv
import base64
import json
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path

import run_ci_experiment as runner
from experiment_environment import load_env, redact
from openrouter_optimizer import DEFAULT_FREE_MODEL, validate_free_model

DEFAULT_CANDIDATES = runner.ROOT / "research-data/zenodo_20340547/pattern_repo_candidates_20.csv"
EXAMPLES_PER_PATTERN = 2

TERMINAL = {"completed", "failed", "blocked", "skipped", "baseline_failed", "proposal_rejected",
            "preparation_failed", "pattern_satisfied"}


def read_rows(path, pattern=None):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not {"repo_id", "pattern_id"} <= set(reader.fieldnames or []):
            raise ValueError("Candidate CSV requires repo_id and pattern_id columns")
        rows = list(reader)
    seen, selected = set(), []
    for row in rows:
        if pattern and row["pattern_id"] != pattern:
            continue
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", row["repo_id"]):
            raise ValueError("Invalid repository identity in candidate CSV")
        key = row["pattern_id"] + "|" + row["repo_id"]
        if key not in seen:
            seen.add(key)
            selected.append(row)
    if not selected:
        raise ValueError("No matching rows in candidate CSV")
    return selected


def case_id(batch_id, row, generation=1):
    identity = batch_id + "|" + row["pattern_id"] + "|" + row["repo_id"]
    base = "batch-" + batch_id[:18] + "-" + runner.sha(identity.encode())[:16]
    return base if generation == 1 else f"{base}-r{generation}"


def parse_fork(value, username):
    value = value.strip().rstrip("/")
    if value.startswith("https://github.com/"):
        value = value.removeprefix("https://github.com/")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", value) or value.split("/", 1)[0].lower() != username.lower():
        raise ValueError("Use a GitHub fork belonging to GITHUB_USERNAME, as owner/name or https://github.com/owner/name")
    return value


def validate_fork(github, source_repo, fork_repo):
    source = github.request("GET", "/repos/" + source_repo)
    fork = github.request("GET", "/repos/" + fork_repo)
    if not fork.get("fork") or not fork.get("permissions", {}).get("push"):
        raise ValueError("Expected fork is missing or the token cannot push to it")
    source_network = source.get("source") or source.get("parent") or source
    fork_network = fork.get("source") or fork.get("parent") or {}
    if not source_network.get("full_name") or source_network["full_name"].lower() != str(fork_network.get("full_name", "")).lower():
        raise ValueError("That fork belongs to another repository family; enter the correct fork URL (renamed forks are supported)")
    return fork


def choose_workflow(github, fork_repo, repository, row, require_dispatch=True):
    prefix = "/repos/" + fork_repo
    commit = github.request("GET", prefix + "/commits/" + urllib.parse.quote(repository["default_branch"], safe=""))
    tree = github.request("GET", prefix + f"/git/trees/{commit['commit']['tree']['sha']}?recursive=1")
    if tree.get("truncated"):
        raise ValueError("Fork file tree is incomplete")
    preferred = row.get("workflow_paths", "").split(";")
    options, messages = [], []
    for entry in tree["tree"]:
        path = entry["path"]
        if entry["type"] != "blob" or not re.fullmatch(r"\.github/workflows/[^/]+\.ya?ml", path):
            continue
        doc = runner.workflow_doc(github.blob(fork_repo, entry["sha"]))
        findings = runner.hazards(doc)
        if findings:
            messages.append(path + ": " + ", ".join(findings))
            continue
        if require_dispatch and not runner.has_dispatch(doc):
            messages.append(path + ": add workflow_dispatch before recording the baseline")
            continue
        triggers = doc.get("on")
        dispatch = triggers.get("workflow_dispatch") if isinstance(triggers, dict) else None
        inputs = dispatch.get("inputs", {}) if isinstance(dispatch, dict) else {}
        if any(isinstance(spec, dict) and spec.get("required") in {True, "true"} and "default" not in spec for spec in inputs.values()):
            messages.append(path + ": required dispatch inputs need defaults before this automatic batch")
            continue
        text = json.dumps(doc)
        ci_hint = bool(re.search(r"\b(test|pytest|lint|build|check|npm ci)\b", text, re.I))
        if not ci_hint:
            continue
        options.append((path not in preferred, -len(re.findall(r"\b(test|pytest|lint|build|check)\b", text, re.I)), path))
    if not options:
        raise ValueError("No runnable test/build workflow found. " + "; ".join(messages[:8]))
    options.sort()
    return options[0][2]


class Batch:
    supported_patterns = None
    supported_scenario_patterns = set()
    measurement_name = "CI"

    def __init__(self, batch_id, rows, username, token, model, max_tokens=24000):
        self.batch_id, self.rows, self.username, self.token = batch_id, rows, username, token
        self.model, self.max_tokens = model, max_tokens
        self.directory = runner.ROOT / "research-data/batches" / batch_id
        self.directory.mkdir(parents=True, exist_ok=True)
        self.github = runner.GitHub(token, self.directory / "api_calls.jsonl")
        manifest = self.directory / "selection.json"
        selection = {"username": username, "rows": rows, "model": model, "max_tokens": max_tokens,
                     "repetitions_per_arm": 3, "warmups": 0, "examples_per_pattern": EXAMPLES_PER_PATTERN,
                     "source_version": "current"}
        if manifest.exists():
            saved_selection = runner.read_json(manifest)
            if saved_selection != selection:
                runner.append_json(self.directory / "selection_history.jsonl",
                                   {"at": runner.stamp(), "selection": saved_selection})
        runner.write_json(manifest, selection)
        state_path = self.directory / "state.json"
        self.state = runner.read_json(state_path) if state_path.exists() else {"items": {}, "forks": {}}

    def save(self):
        self.state["items"] = dict(sorted(
            self.state["items"].items(),
            key=lambda pair: (pair[1].get("row_position", 10**9), pair[0])))
        runner.write_json(self.directory / "state.json", self.state)
        fields = ["row_position", "row_key", "source_repo", "pattern_id", "fork_repo", "experiment_id", "model", "status", "reason", "outcome", "example_satisfied", "updated_at"]
        active_keys = {row["pattern_id"] + "|" + row["repo_id"] for row in self.rows}
        with (self.directory / "batch_results.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(sorted((item for key, item in self.state["items"].items() if key in active_keys),
                                    key=lambda item: item.get("row_position", 10**9)))
        with (self.directory / "pattern_progress.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["pattern_id", "successful_examples", "target", "satisfied"])
            writer.writeheader()
            for pattern in dict.fromkeys(row["pattern_id"] for row in self.rows):
                count = len(self.successful_examples(pattern))
                writer.writerow({"pattern_id": pattern, "successful_examples": count,
                                 "target": EXAMPLES_PER_PATTERN, "satisfied": count >= EXAMPLES_PER_PATTERN})

    def generation(self, row):
        key = row["pattern_id"] + "|" + row["repo_id"]
        return self.state.setdefault("generations", {}).get(key, 1)

    def case_id(self, row):
        return case_id(self.batch_id, row, self.generation(row))

    def mark(self, row, status, row_position=None, **values):
        key = row["pattern_id"] + "|" + row["repo_id"]
        previous = self.state["items"].get(key, {})
        position = row_position if row_position is not None else previous.get("row_position")
        self.state["items"][key] = {"row_position": position, "row_key": key, "source_repo": row["repo_id"], "pattern_id": row["pattern_id"],
                                    "experiment_id": self.case_id(row), "status": status,
                                    "updated_at": runner.stamp(), **values}
        self.save()

    def backfill_row_positions(self):
        changed = False
        for position, row in enumerate(self.rows, 1):
            key = row["pattern_id"] + "|" + row["repo_id"]
            item = self.state["items"].get(key)
            if item is not None and item.get("row_position") != position:
                item["row_position"] = position
                changed = True
        if changed:
            self.save()

    def ready_experiment(self, row):
        target = self.state["forks"].get(row["repo_id"], self.username + "/" + row["repo_id"].split("/", 1)[1])
        try:
            target = self.ensure_fork(row, target)
            repository = validate_fork(self.github, row["repo_id"], target)
            self.enable_actions(target)
            workflow = choose_workflow(self.github, target, repository, row, require_dispatch=False)
            print("Using the fork's current default-branch workflow (no history scan).", flush=True)
            self.add_workflow_dispatch(target, repository["default_branch"], workflow)
            repository = self.github.request("GET", "/repos/" + target)
            workflow = choose_workflow(self.github, target, repository, row)
            config_path = self.directory / "configs" / (self.case_id(row) + ".json")
            if config_path.exists():
                config = runner.load_config(config_path)
                if config["fork_repo"].lower() != target.lower():
                    raise ValueError("Existing attempt uses a different fork; use --rerun in this batch")
                if config["workflow_path"] != workflow:
                    raise ValueError("Existing attempt uses a different workflow; use --rerun in this batch")
            else:
                raw_config = {"experiment_id": self.case_id(row), "fork_repo": target,
                              "source_ref": "HEAD", "workflow_path": workflow, "pattern_id": row["pattern_id"],
                              "required_job_names": [], "discover_required_jobs": True,
                              "repetitions": 3, "warmup_runs": 0, "max_total_runs": 6,
                              "cache_regime": "uncontrolled", "split": "development",
                              "optimizer": {"type": "openrouter-free", "model": self.model, "max_tokens": self.max_tokens},
                              "notes": "Interactive batch; three measurements per arm. Required jobs inferred from baseline, not approved branch protection."}
                runner.write_json(config_path, raw_config)
                config = runner.load_config(config_path)
            experiment = runner.Experiment(config, self.token)
            with runner.exclusive(experiment.directory / ".lock"):
                experiment.prepare()
                selection_path = experiment.directory / "selection.json"
                if not selection_path.exists():
                    runner.write_json(selection_path, row)
            self.state["forks"][row["repo_id"]] = target
            self.save()
            print("Selected workflow: " + config["workflow_path"], flush=True)
            return experiment, target
        except (OSError, ValueError, RuntimeError, KeyError, TypeError, runner.yaml.YAMLError) as exc:
            print("Automatic fork preparation failed: " + redact(str(exc)), flush=True)
            return None, "failed"

    def enable_actions(self, fork_repo):
        """Enable Actions while leaving the fork's allowed-actions policy intact."""
        self.github.request("PUT", "/repos/" + fork_repo + "/actions/permissions", {"enabled": True})
        print("GitHub Actions enabled for " + fork_repo, flush=True)

    def add_workflow_dispatch(self, fork_repo, branch, workflow_path):
        """Add only the dispatch trigger to the chosen workflow before the baseline is pinned."""
        encoded_path = urllib.parse.quote(workflow_path, safe="/")
        path = "/repos/" + fork_repo + "/contents/" + encoded_path + "?ref=" + urllib.parse.quote(branch, safe="")
        current = self.github.request("GET", path)
        raw = base64.b64decode(current["content"])
        doc = runner.workflow_doc(raw)
        if runner.has_dispatch(doc):
            print("Workflow already supports workflow_dispatch: " + workflow_path, flush=True)
            return

        text = raw.decode("utf-8-sig")
        lines = text.splitlines(keepends=True)
        trigger_line = next((i for i, line in enumerate(lines)
                             if re.match(r"^(?:on|'on'|\"on\")\s*:", line)), None)
        if trigger_line is None:
            raise ValueError("Cannot locate the top-level on: trigger in " + workflow_path)
        line = lines[trigger_line]
        match = re.match(r"^(?:on|'on'|\"on\")\s*:(.*?)(\r?\n)?$", line)
        inline = match.group(1).strip()
        if not inline or inline.startswith("#"):
            ending = match.group(2) or "\n"
            if not match.group(2):
                lines[trigger_line] = line + ending
            lines.insert(trigger_line + 1, "  workflow_dispatch:" + ending)
            updated = "".join(lines).encode("utf-8")
        else:
            triggers = doc.get("on")
            if isinstance(triggers, dict):
                expanded = dict(triggers)
            elif isinstance(triggers, list):
                expanded = {str(event): None for event in triggers}
            elif isinstance(triggers, str):
                expanded = {triggers: None}
            else:
                raise ValueError("Cannot safely add workflow_dispatch to this workflow trigger format")
            expanded["workflow_dispatch"] = None
            trigger_yaml = runner.yaml.safe_dump({"on": expanded}, sort_keys=False, allow_unicode=True)
            bom = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
            updated = bom + trigger_yaml.encode("utf-8") + "".join(lines[trigger_line + 1:]).encode("utf-8")

        body = {"message": "[skip ci] Add workflow_dispatch for CI experiment runner",
                "content": base64.b64encode(updated).decode("ascii"),
                "sha": current["sha"], "branch": branch}
        self.github.request("PUT", "/repos/" + fork_repo + "/contents/" + encoded_path, body)
        print("Added workflow_dispatch to " + workflow_path, flush=True)

    def ensure_fork(self, row, target):
        """Create once, then poll; a lost POST response must never cause a second POST."""
        source = row["repo_id"]
        try:
            validate_fork(self.github, source, target)
            print("Reusing fork: https://github.com/" + target, flush=True)
        except RuntimeError as exc:
            if f"GET /repos/{target}: HTTP 404" not in str(exc):
                raise
            requests = self.state.setdefault("fork_requests", {})
            previous = requests.get(source)
            # A prior version recorded explicit 403 responses as pending. This is
            # a definitive rejection, so it is safe to retry after fixing access.
            if previous and previous.get("status") == "pending" and "HTTP 403" in previous.get("error", ""):
                previous["status"] = "rejected"
            if source not in requests or requests[source].get("status") in {"rejected", "deleted"}:
                identity = self.github.request("GET", "/user")
                if str(identity.get("login", "")).lower() != self.username.lower():
                    raise ValueError("GITHUB_TOKEN belongs to another account than GITHUB_USERNAME")
                requests[source] = {"target": target, "requested_at": runner.stamp(), "status": "pending"}
                self.save()
                print("Creating fork: https://github.com/" + target, flush=True)
                try:
                    result = self.github.request("POST", "/repos/" + source + "/forks",
                                                 {"name": target.split("/", 1)[1], "default_branch_only": True})
                    target = parse_fork(result["full_name"], self.username)
                    requests[source].update(target=target, status="accepted")
                    self.state["forks"][source] = target
                    self.state.setdefault("created_forks", {})[source] = target
                    # A recreated fork needs a fresh deletion attempt, even if
                    # an earlier generation deleted the same repository name.
                    self.state.setdefault("fork_deletions", {}).pop(source, None)
                    self.save()
                except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
                    message = redact(str(error))
                    requests[source]["error"] = message
                    if isinstance(error, RuntimeError) and re.search(r"HTTP 4\d\d", message):
                        requests[source]["status"] = "rejected"
                    self.save()
                    if requests[source].get("status") == "rejected":
                        raise RuntimeError("GitHub rejected fork creation. Check token permissions, then rerun to retry. " + message) from None
                    raise RuntimeError("Fork request was recorded; it will not be automatically resent. " + message) from None
            else:
                target = requests[source]["target"]
            print("Waiting for GitHub to finish creating the fork...", flush=True)
        for attempt in range(31):
            try:
                repository = validate_fork(self.github, source, target)
                self.github.request("GET", "/repos/" + target + "/commits/" +
                                    urllib.parse.quote(repository["default_branch"], safe=""))
                self.state["forks"][source] = target
                if source in self.state.get("fork_requests", {}):
                    self.state["fork_requests"][source]["status"] = "ready"
                self.save()
                return target
            except RuntimeError as exc:
                if not any(code in str(exc) for code in ("HTTP 404", "HTTP 409")):
                    raise
                if attempt == 30:
                    raise RuntimeError("Fork is still initializing after five minutes; resume later or check its URL") from None
                time.sleep(10)

    def cleanup_fork(self, row, target):
        """Delete only a fork whose creation this batch confirmed."""
        source = row["repo_id"]
        created = self.state.setdefault("created_forks", {})
        if created.get(source, "").lower() != target.lower():
            print("Keeping pre-existing fork: https://github.com/" + target, flush=True)
            return True
        deletions = self.state.setdefault("fork_deletions", {})
        record = deletions.get(source)
        if not record or record.get("target", "").lower() != target.lower():
            record = {"target": target, "status": "pending", "requested_at": runner.stamp()}
            deletions[source] = record
            self.save()
        if record.get("status") == "pending":
            try:
                self.github.request("GET", "/repos/" + target)
            except RuntimeError as exc:
                if f"GET /repos/{target}: HTTP 404" in str(exc):
                    record["status"] = "deleted"
                    record["completed_at"] = runner.stamp()
                    created.pop(source, None)
                    if source in self.state.get("fork_requests", {}):
                        self.state["fork_requests"][source]["status"] = "deleted"
                    if self.state.get("forks", {}).get(source, "").lower() == target.lower():
                        self.state["forks"].pop(source, None)
                    self.save()
                    print("Fork was already deleted: https://github.com/" + target, flush=True)
                    return True
                record["error"] = redact(str(exc))
                self.save()
                return False
            print("Deleting batch-created fork: https://github.com/" + target, flush=True)
            try:
                self.github.request("DELETE", "/repos/" + target)
            except RuntimeError as exc:
                if f"DELETE /repos/{target}: HTTP 404" not in str(exc):
                    record["error"] = redact(str(exc))
                    self.save()
                    return False
            except OSError as exc:
                record["error"] = redact(str(exc))
                self.save()
                return False
            record["status"] = "deleted"
            record["completed_at"] = runner.stamp()
            record.pop("error", None)
            created.pop(source, None)
            if source in self.state.get("fork_requests", {}):
                self.state["fork_requests"][source]["status"] = "deleted"
            if self.state.get("forks", {}).get(source, "").lower() == target.lower():
                self.state["forks"].pop(source, None)
            self.save()
            print("Deleted fork: https://github.com/" + target, flush=True)
        return record.get("status") == "deleted"

    def successful_examples(self, pattern_id):
        active_keys = {row["pattern_id"] + "|" + row["repo_id"] for row in self.rows}
        return {item["source_repo"] for key, item in self.state["items"].items()
                if key in active_keys and item.get("pattern_id") == pattern_id
                and (item.get("status") == "completed" or
                     item.get("status") == "cleanup_pending" and item.get("finished_status") == "completed")
                and item.get("example_satisfied", item.get("outcome") in {"safe_success", "scenario_passed"}) is True
                and self.case_has_runtime_improvement(item)}

    def case_has_runtime_improvement(self, item):
        experiment_id = item.get("experiment_id")
        if not experiment_id:
            return False
        for parent in ("experiments", "scenario-experiments"):
            path = runner.ROOT / "research-data" / parent / experiment_id / "case.json"
            try:
                case = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if case.get("pattern_satisfied") is not True:
                return False
            arms = case.get("arms", {})
            metric = "median_elapsed_seconds" if parent == "experiments" else "median_job_runtime_seconds"
            baseline = arms.get("baseline", {}).get(metric)
            optimized = arms.get("optimized", {}).get(metric)
            return (isinstance(baseline, (int, float)) and not isinstance(baseline, bool)
                    and isinstance(optimized, (int, float)) and not isinstance(optimized, bool)
                    and optimized < baseline)
        return False

    def run(self, stop_at=None, start_at=1, rerun=False):
        self.backfill_row_positions()
        announced_patterns = set()
        for index, row in enumerate(self.rows, 1):
            if index < start_at:
                continue
            if stop_at is not None and index > stop_at:
                break
            if getattr(self, "pattern_filter", None) and row["pattern_id"] != self.pattern_filter:
                continue
            if self.supported_patterns is not None and row["pattern_id"] not in self.supported_patterns:
                continue
            key = row["pattern_id"] + "|" + row["repo_id"]
            item = self.state["items"].get(key, {})
            if item.get("status") == "cleanup_pending":
                print(f"\n[{index}/{len(self.rows)}] Retrying fork cleanup for {row['repo_id']}...", flush=True)
                if not self.cleanup_fork(row, item["fork_repo"]):
                    print("Cleanup is still pending. Fix the GitHub permission or connection, then rerun.", flush=True)
                    return
                self.mark(row, item.get("finished_status", "completed"), fork_repo=item["fork_repo"],
                          outcome=item.get("outcome"), reason=item.get("reason"),
                          model=item.get("model"), example_satisfied=item.get(
                              "example_satisfied", item.get("outcome") in {"safe_success", "scenario_passed"}))
                continue
            successes = self.successful_examples(row["pattern_id"])
            if len(successes) >= EXAMPLES_PER_PATTERN and not (rerun and row["repo_id"] in successes):
                if item.get("status") in {"running", "pending_run", "llm_paused"}:
                    print("Pattern already completed, but another case has unfinished work: " +
                          item["experiment_id"] + ". Resolve that case before continuing.", flush=True)
                    return
                reason = f"Pattern has {len(successes)}/{EXAMPLES_PER_PATTERN} successful examples: " + ", ".join(sorted(successes))
                if row["pattern_id"] not in announced_patterns:
                    print(reason + "; skipping remaining candidates for " + row["pattern_id"], flush=True)
                    announced_patterns.add(row["pattern_id"])
                if not item:
                    self.mark(row, "pattern_satisfied", row_position=index, reason=reason)
                continue
            # Old quota skips become runnable when fewer than two examples qualify.
            if item.get("status") == "pattern_satisfied":
                item = {}
            if item.get("status") in TERMINAL:
                if not rerun:
                    continue
                # Keep the prior experiment evidence and write this rerun to a
                # fresh experiment directory; the batch row below points to the
                # newest generation and replaces its prior summary.
                generations = self.state.setdefault("generations", {})
                generations[key] = generations.get(key, 1) + 1
                self.save()
            print(f"\n[{index}/{len(self.rows)}] Pattern: {row['pattern_id']} — {row.get('pattern_title', '')}", flush=True)
            print("Repository to fork: https://github.com/" + row["repo_id"], flush=True)
            print("Selection evidence: " + row.get("match_level", "unspecified"), flush=True)
            if row["pattern_id"] in runner.SCENARIO_PATTERNS and row["pattern_id"] not in self.supported_scenario_patterns:
                reason = "Requires an event/history/scenario experiment; ordinary dispatch timing cannot measure this pattern"
                self.mark(row, "blocked", row_position=index, reason=reason)
                print("Recorded as blocked: " + reason, flush=True)
                continue
            experiment, target = self.ready_experiment(row)
            if target == "failed":
                reason = "Automatic fork preparation failed; see the terminal output above"
                fork_repo = self.state.get("created_forks", {}).get(row["repo_id"])
                if fork_repo and not self.cleanup_fork(row, fork_repo):
                    self.mark(row, "cleanup_pending", row_position=index, fork_repo=fork_repo, finished_status="preparation_failed",
                              reason=reason + "; fork deletion failed")
                    print("Fork cleanup is pending. Fix the GitHub permission or connection, then rerun.", flush=True)
                    return
                self.mark(row, "preparation_failed", row_position=index, fork_repo=fork_repo, reason=reason)
                print("Preparation failed; continuing to the next candidate.", flush=True)
                continue
            if target == "quit":
                print("Progress saved. Run the same command to resume.", flush=True)
                return
            if target == "skip":
                self.mark(row, "skipped", row_position=index, reason="User skipped before execution")
                continue
            self.mark(row, "running", row_position=index, fork_repo=target)
            try:
                with runner.exclusive(experiment.directory / ".lock"):
                    print("Running baseline " + self.measurement_name + " up to 3 times; stopping on the first unexpected result...", flush=True)
                    experiment.measure("baseline")
                    print("Requesting a free LLM optimization for ONLY " + row["pattern_id"] + "...", flush=True)
                    experiment.optimize()
                    decision = experiment.state["proposal"].get("llm", {}).get("decision")
                    print("LLM decision: " + str(decision) + " (selected pattern: " + row["pattern_id"] + ")", flush=True)
                    print("Running optimized " + self.measurement_name + " up to 3 times; stopping on the first unexpected result...", flush=True)
                    experiment.measure("optimized")
                    case = experiment.report()
                model_used = experiment.config.get("optimizer", {}).get("model", experiment.config.get("model", getattr(self, "model", "")))
                satisfied = case.get("pattern_satisfied", False) is True
                self.mark(row, "completed", row_position=index, fork_repo=target, model=model_used,
                          outcome=case["outcome"], example_satisfied=satisfied)
                print("Saved results: " + str(experiment.directory), flush=True)
                count = len(self.successful_examples(row["pattern_id"]))
                print(f"Pattern examples: {count}/{EXAMPLES_PER_PATTERN}; this attempt satisfied the pattern: {satisfied}.", flush=True)
                if not self.cleanup_fork(row, target):
                    self.mark(row, "cleanup_pending", row_position=index, fork_repo=target, finished_status="completed",
                              outcome=case["outcome"], model=model_used, example_satisfied=satisfied,
                              reason="Fork deletion failed; rerun to retry cleanup")
                    print("Results are saved; cleanup is pending. Fix the GitHub permission or connection, then rerun.", flush=True)
                    return
            except (OSError, ValueError, RuntimeError, KeyError, TypeError, runner.yaml.YAMLError) as exc:
                message = redact(str(exc))
                experiment.event("batch_error", message=message)
                try:
                    with runner.exclusive(experiment.directory / ".lock"):
                        experiment.report()
                except (OSError, ValueError, RuntimeError, KeyError, TypeError):
                    pass
                pending = bool(experiment.state.get("pending"))
                llm_unavailable = "OpenRouter HTTP" in message
                status = "pending_run" if pending else "llm_paused" if llm_unavailable else "failed"
                model_used = experiment.config.get("optimizer", {}).get("model", experiment.config.get("model", getattr(self, "model", "")))
                self.mark(row, status, row_position=index, fork_repo=target, model=model_used, reason=message)
                print("Recorded: " + message, flush=True)
                if pending or llm_unavailable:
                    print("Batch paused to preserve this attempt. Resolve the issue and rerun the same command.", flush=True)
                    return
                if not self.cleanup_fork(row, target):
                    self.mark(row, "cleanup_pending", row_position=index, fork_repo=target, finished_status=status,
                              reason=message + "; fork deletion failed")
                    print("Experiment ended; fork cleanup is pending. Fix the GitHub permission or connection, then rerun.", flush=True)
                    return
                print("This repository is finished; continuing to the next candidate.", flush=True)
        self.save()
        print("\nBatch progress: " + str(self.directory / "batch_results.csv"), flush=True)
        print("Per-pattern example counts: " + str(self.directory / "pattern_progress.csv"), flush=True)


def main(batch_class=Batch, default_batch_id="interactive-three-runs-v1", description=__doc__):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--env-file", type=Path, default=runner.ROOT / ".env")
    parser.add_argument("--batch-id", default=default_batch_id)
    parser.add_argument("--pattern", help="Optional selected pattern ID")
    parser.add_argument("--stop-at", type=int, help="Inclusive ending position in the original CSV (default: last row)")
    parser.add_argument("--start-at", type=int, default=1, help="One-based CSV position to start from (default: 1)")
    parser.add_argument("--rerun", action="store_true", help="Rerun terminal rows in the selected range; replace their batch summary and keep prior experiment evidence")
    parser.add_argument("--list", action="store_true", help="Preview repository links and patterns without API calls or prompts")
    args = parser.parse_args()
    try:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", args.batch_id):
            raise ValueError("batch-id must be 1-64 letters, digits, underscores or hyphens")
        if args.stop_at is not None and args.stop_at < args.start_at:
            raise ValueError("stop-at must be at least start-at")
        if args.start_at < 1:
            raise ValueError("start-at must be at least 1")
        load_env(args.env_file)
        rows = read_rows(args.csv)
        if args.pattern and not any(row["pattern_id"] == args.pattern for row in rows):
            raise ValueError("No matching rows in candidate CSV")
        if args.pattern and batch_class.supported_patterns is not None and args.pattern not in batch_class.supported_patterns:
            raise ValueError("This runner supports: " + ", ".join(sorted(batch_class.supported_patterns)))
        if args.start_at > len(rows):
            raise ValueError(f"start-at is {args.start_at}, but the selection has only {len(rows)} rows")
        if args.stop_at is not None and args.stop_at > len(rows):
            raise ValueError(f"stop-at is {args.stop_at}, but the selection has only {len(rows)} rows")
        if args.list:
            end = args.stop_at if args.stop_at is not None else len(rows)
            for index, row in enumerate(rows[args.start_at - 1:end], args.start_at):
                if args.pattern and row["pattern_id"] != args.pattern:
                    continue
                if batch_class.supported_patterns is not None and row["pattern_id"] not in batch_class.supported_patterns:
                    continue
                print(index, row["pattern_id"], row.get("pattern_title", ""), "https://github.com/" + row["repo_id"], row.get("match_level", ""))
            return 0
        username = os.environ.get("GITHUB_USERNAME", "").strip()
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", username):
            raise ValueError("Fill GITHUB_USERNAME in .env")
        if not token:
            raise ValueError("Fill GITHUB_TOKEN in .env")
        if not os.environ.get("OPENROUTER_API_KEY"):
            raise ValueError("Fill OPENROUTER_API_KEY in .env")
        model = os.environ.get("OPENROUTER_MODEL") or DEFAULT_FREE_MODEL
        validate_free_model(model)
        max_tokens = int(os.environ.get("OPENROUTER_MAX_TOKENS") or "24000")
        if not 256 <= max_tokens <= 48000:
            raise ValueError("OPENROUTER_MAX_TOKENS must be between 256 and 48000")
        batch = batch_class(args.batch_id, rows, username, token, model, max_tokens)
        batch.pattern_filter = args.pattern
        with runner.exclusive(batch.directory / ".lock"):
            batch.run(stop_at=args.stop_at, start_at=args.start_at, rerun=args.rerun)
        return 0
    except (KeyboardInterrupt, EOFError):
        print("\nStopped. Saved progress can be resumed with the same command.")
        return 130
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, runner.yaml.YAMLError) as exc:
        print("Error: " + redact(str(exc)), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
