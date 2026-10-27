"""Controlled push-event experiments; results are synthetic scenario evidence."""
from __future__ import annotations

import copy
import csv
import json
import os
import statistics
import time
import urllib.parse
from pathlib import Path

import run_ci_experiment as runner
from experiment_environment import redact
from openrouter_optimizer import generate
from run_pattern_batch import Batch, validate_fork
import scenario_replay as replay

SUPPORTED = {"P-LIT-FAIL-FAST", "P-LIT-CANCEL-STALE", "P-LIT-SKIP-WORKFLOW", "P-LIT-CHANGE-FILTER"} | replay.PATTERNS
POLICY_PATTERNS = replay.PATTERNS | {"P-LIT-SKIP-WORKFLOW"}
WORKFLOW = ".github/workflows/cloudtune-scenario.yml"
NAME = "CloudTune controlled scenario"


def settings_from_env():
    settings = {"absence_seconds": int(os.environ.get("SCENARIO_ABSENCE_SECONDS", "120")),
                "poll_seconds": int(os.environ.get("SCENARIO_POLL_SECONDS", "5")),
                "wait_seconds": int(os.environ.get("SCENARIO_WAIT_SECONDS", "900")),
                "work_seconds": int(os.environ.get("SCENARIO_WORK_SECONDS", "90")),
                "fail_delay_seconds": 20, "max_events": 90, "repetitions": 3}
    if not 60 <= settings["absence_seconds"] <= 900:
        raise ValueError("SCENARIO_ABSENCE_SECONDS must be between 60 and 900")
    if not 2 <= settings["poll_seconds"] <= 30:
        raise ValueError("SCENARIO_POLL_SECONDS must be between 2 and 30")
    if not 300 <= settings["wait_seconds"] <= 3600:
        raise ValueError("SCENARIO_WAIT_SECONDS must be between 300 and 3600")
    if not 60 <= settings["work_seconds"] <= 180:
        raise ValueError("SCENARIO_WORK_SECONDS must be between 60 and 180")
    return settings


def fixture(pattern, settings):
    job = {"name": "probe", "runs-on": "ubuntu-latest", "timeout-minutes": 5,
           "steps": [{"name": "Controlled workload", "shell": "bash", "run": "sleep 5\nprintf 'probe completed\\n'\n"}]}
    doc = {"name": NAME, "on": {"push": {"branches": ["ct-scenario/**"]}},
           "permissions": {"contents": "read"}, "jobs": {"probe": job}}
    if pattern == "P-LIT-FAIL-FAST":
        job["name"] = "cell-${{ matrix.cell }}"
        job["strategy"] = {"fail-fast": False, "max-parallel": 3,
                           "matrix": {"cell": ["fail", "worker-a", "worker-b"]}}
        job["steps"][0]["env"] = {"CELL": "${{ matrix.cell }}", "MESSAGE": "${{ github.event.head_commit.message }}"}
        job["steps"][0]["run"] = (
            'if [[ "$CELL" == "fail" && "$MESSAGE" == *"[ct-fail]"* ]]; then\n'
            f'  sleep {settings["fail_delay_seconds"]}\n  exit 1\nfi\n'
            f'sleep {settings["work_seconds"]}\nprintf "healthy cell completed\\n"\n')
    if pattern == "P-LIT-CANCEL-STALE":
        job["steps"][0]["run"] = f'sleep {settings["work_seconds"]}\nprintf "revision completed\\n"\n'
    if pattern in replay.PATTERNS:
        job["steps"][0]["env"] = {"CT_PATTERN": pattern,
            "CT_POLICY": json.dumps(replay.policy(pattern), sort_keys=True),
            "CT_DATA": json.dumps(replay.dataset(pattern, 1), sort_keys=True)}
        engine = Path(replay.__file__).read_text(encoding="utf-8")
        job["steps"][0]["run"] = "python3 - <<'CLOUDTUNE_REPLAY_ENGINE'\n" + engine + "\nCLOUDTUNE_REPLAY_ENGINE\n"
    return doc


def candidate_document(pattern, before):
    """Exact allowed change; the LLM must produce this semantic document."""
    result = copy.deepcopy(before)
    if pattern == "P-LIT-FAIL-FAST":
        result["jobs"]["probe"]["strategy"]["fail-fast"] = True
    elif pattern == "P-LIT-CANCEL-STALE":
        result["concurrency"] = {"group": "${{ github.workflow }}-${{ github.ref }}", "cancel-in-progress": True}
    elif pattern == "P-LIT-CHANGE-FILTER":
        result["on"]["push"]["paths"] = ["src/**", "config/**", ".github/workflows/**"]
    elif pattern == "P-LIT-SKIP-WORKFLOW":
        result["dispensable_commit_suffix"] = "[skip ci]"
    elif pattern in replay.PATTERNS:
        # Service-level mechanisms are explicit policy documents, not native Actions settings.
        result = replay.policy(pattern, True)
    else:
        raise ValueError("Unsupported scenario pattern")
    return result


def dump(doc):
    return runner.yaml.safe_dump(doc, sort_keys=False, allow_unicode=True).encode("utf-8")


def check_candidate(pattern, before, after):
    parsed = runner.yaml.load(after.decode("utf-8"), Loader=runner.ActionsLoader)
    expected = candidate_document(pattern, before)
    if runner.encode(parsed) != runner.encode(expected):
        raise ValueError("SCENARIO_PATTERN_SCOPE_EXCEEDED: only the specified pattern setting may change")
    return parsed


def evaluate(pattern, arm, events, overlap=False):
    """Expected failure/cancellation is a passing scenario, not green CI."""
    optimized = arm == "optimized"
    def success(label, jobs=1):
        event = events[label]
        return (event.get("conclusion") == "success" and len(event.get("jobs", [])) == jobs and
                all(job["conclusion"] == "success" for job in event["jobs"]))
    checks = {}
    if pattern == "P-LIT-FAIL-FAST":
        observed = {job["name"]: job["conclusion"] for job in events["failure"].get("jobs", [])}
        checks["failure_cell_failed"] = observed.get("cell-fail") == "failure"
        checks["matrix_workflow_failed_as_expected"] = events["failure"].get("conclusion") == "failure"
        checks["matrix_cells_preserved"] = set(observed) == {"cell-fail", "cell-worker-a", "cell-worker-b"}
        wanted = "cancelled" if optimized else "success"
        checks["remaining_cells_" + wanted] = all(observed.get("cell-" + cell) == wanted for cell in ("worker-a", "worker-b"))
        checks["healthy_control_passed"] = success("healthy", 3)
    elif pattern == "P-LIT-CANCEL-STALE":
        checks["runs_overlapped_before_superseding_push"] = overlap
        checks["old_revision_expected_conclusion"] = events["old"].get("conclusion") == ("cancelled" if optimized else "success")
        checks["new_revision_passed"] = success("new")
        checks["other_branch_not_cancelled"] = success("isolated")
    else:
        controls = ["source", "source_after"]
        if pattern == "P-LIT-CHANGE-FILTER":
            controls += ["config", "mixed"]
        checks.update({label + "_control_passed": success(label) for label in controls})
        checks["dispensable_run_suppressed" if optimized else "dispensable_baseline_ran"] = (
            events["docs"].get("no_run_observed") is True if optimized else success("docs"))
    return checks


class ScenarioExperiment:
    def __init__(self, config, github):
        self.github = github
        self.directory = runner.ROOT / "research-data/scenario-experiments" / config["experiment_id"]
        self.directory.mkdir(parents=True, exist_ok=True)
        frozen = self.directory / "config.json"
        if frozen.exists():
            saved = runner.read_json(frozen)
            if {k: v for k, v in saved.items() if k not in {"model", "max_tokens"}} != {
                    k: v for k, v in config.items() if k not in {"model", "max_tokens"}}:
                raise ValueError("Scenario settings changed; use another --batch-id")
            config = saved
        else:
            runner.write_json(frozen, config)
        self.config = config
        self.state_path = self.directory / "state.json"
        self.state = runner.read_json(self.state_path) if self.state_path.exists() else {
            "records": [], "operations": {}, "pending": None, "event_count": 0}
        self.prefix = "/repos/" + config["fork_repo"]
        self.settings = config["settings"]
        self.pattern = config["pattern_id"]

    def save(self):
        runner.write_json(self.state_path, self.state)

    def event(self, kind, **values):
        runner.append_json(self.directory / "events.jsonl", {"at": runner.stamp(), "kind": kind, **values})

    def prepare(self):
        if self.state.get("prepared"):
            if self.pattern in replay.PATTERNS:
                engine = self.directory / "source/replay_engine.py"
                if engine.read_text(encoding="utf-8") != Path(replay.__file__).read_text(encoding="utf-8"):
                    raise ValueError("Replay engine changed; use a new --batch-id to keep evidence reproducible")
            return
        repository = self.github.request("GET", self.prefix)
        commit = self.github.request("GET", self.prefix + "/commits/" + urllib.parse.quote(repository["default_branch"], safe=""))
        tree = self.github.request("GET", self.prefix + f"/git/trees/{commit['commit']['tree']['sha']}?recursive=1")
        if tree.get("truncated"):
            raise ValueError("Source tree is truncated")
        for name, value in (("repository", repository), ("commit", commit), ("tree", tree)):
            runner.write_json(self.directory / "source" / (name + ".json"), value)
        registry = [json.loads(line) for line in (runner.ROOT / "knowledge/extracted_patterns.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        pattern = next(p for p in registry if p["pattern_id"] == self.pattern)
        runner.write_json(self.directory / "source/pattern.json", pattern)
        archived = []
        for entry in tree["tree"]:
            path = entry["path"]
            if entry["type"] != "blob" or not path.startswith(".github/workflows/") or len(archived) >= 30:
                continue
            if Path(path).is_absolute() or ".." in Path(path).parts or entry.get("size", 0) > 200000 or entry.get("mode") == "120000":
                continue
            destination = self.directory / "source/repository-files" / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(self.github.blob(self.config["fork_repo"], entry["sha"]))
            archived.append(path)
        # Only ScenarioBatch-confirmed, newly created dedicated forks reach here.
        # Disable inherited listeners, especially workflow_run, before any push.
        workflows = self.github.pages(self.prefix + "/actions/workflows", "workflows")
        for workflow in workflows:
            if workflow.get("state") == "active":
                self.github.request("PUT", self.prefix + f"/actions/workflows/{workflow['id']}/disable")
        runner.write_json(self.directory / "source/inherited_workflows.json", {"disabled": workflows, "archived_paths": archived})
        (self.directory / "before.yml").write_bytes(dump(fixture(self.pattern, self.settings)))
        if self.pattern == "P-LIT-SKIP-WORKFLOW":
            (self.directory / "before_policy.yml").write_bytes(dump({"dispensable_commit_suffix": "", "required_commit_suffix": ""}))
        if self.pattern in replay.PATTERNS:
            (self.directory / "before_policy.yml").write_bytes(dump(replay.policy(self.pattern)))
            (self.directory / "source/replay_engine.py").write_text(Path(replay.__file__).read_text(encoding="utf-8"), encoding="utf-8")
            runner.write_json(self.directory / "source/replay_inputs.json",
                              {str(i): replay.dataset(self.pattern, i) for i in (1, 2, 3)})
        self.state["prepared"] = True
        self.save()
        self.event("prepared", evidence_scope="synthetic_fixture_on_dedicated_fork", source_sha=commit["sha"])

    def optimize(self):
        if self.state.get("proposal"):
            return
        if len([r for r in self.state["records"] if r["arm"] == "baseline" and r["scenario_pass"]]) != 3:
            raise ValueError("Three passing baseline scenarios are required before optimization")
        policy = self.pattern in POLICY_PATTERNS
        path = self.directory / ("before_policy.yml" if policy else "before.yml")
        before = path.read_bytes()
        doc = runner.yaml.load(before.decode(), Loader=runner.ActionsLoader)
        expected = candidate_document(self.pattern, doc)
        request = {"pattern": runner.read_json(self.directory / "source/pattern.json"),
                   "baseline_records": self.state["records"], "required_job_names": ["controlled scenario assertions"],
                   "scenario_contract": {"evidence_scope": "synthetic_fixture", "allowed_result": expected,
                                         "instruction": "Produce precisely the allowed_result YAML. Keep every other value unchanged."}}
        after, metadata = generate(self.directory, request, before, self.config["model"], self.config["max_tokens"])
        check_candidate(self.pattern, doc, after)
        (self.directory / ("after_policy.yml" if policy else "after.yml")).write_bytes(after)
        if policy:
            workflow = runner.yaml.load((self.directory / "before.yml").read_text(encoding="utf-8"), Loader=runner.ActionsLoader)
            if self.pattern in replay.PATTERNS:
                workflow["jobs"]["probe"]["steps"][0]["env"]["CT_POLICY"] = json.dumps(expected, sort_keys=True)
            (self.directory / "after.yml").write_bytes(dump(workflow))
        diff = runner.workflow_diff(before, after, "scenario-policy.yml" if policy else WORKFLOW)
        (self.directory / "change.diff").write_text(diff, encoding="utf-8")
        if self.pattern in replay.PATTERNS:
            (self.directory / "workflow_change.diff").write_text(runner.workflow_diff(
                (self.directory / "before.yml").read_bytes(), (self.directory / "after.yml").read_bytes(), WORKFLOW), encoding="utf-8")
        self.state["proposal"] = {"llm": metadata, "before_sha256": runner.sha(before), "after_sha256": runner.sha(after)}
        self.save()

    def ref(self, branch):
        try:
            return self.github.request("GET", self.prefix + "/git/ref/heads/" + urllib.parse.quote(branch, safe="/"))
        except RuntimeError as exc:
            if "HTTP 404" in str(exc):
                return None
            raise

    def operation(self, key, branch, files, message, *, root=False, absent=False):
        """Persist commit SHA and publish intent before ref mutation. Never resend uncertain pushes."""
        operations = self.state["operations"]
        if key not in operations:
            if self.state["event_count"] >= self.settings["max_events"]:
                raise ValueError("Scenario event budget exhausted")
            existing = self.ref(branch)
            if root and existing:
                raise ValueError("Scenario branch already exists without an owned saved intent")
            parent = existing["object"]["sha"] if existing else None
            if not root and not parent:
                raise ValueError("Scenario branch was removed")
            base = self.github.request("GET", self.prefix + "/git/commits/" + parent) if parent else None
            body = {"tree": [{"path": path, "mode": "100644", "type": "blob", "content": content}
                             for path, content in files.items()]}
            if base:
                body["base_tree"] = base["tree"]["sha"]
            tree = self.github.request("POST", self.prefix + "/git/trees", body)
            commit = self.github.request("POST", self.prefix + "/git/commits", {
                "message": message, "tree": tree["sha"], "parents": [parent] if parent else []})
            operations[key] = {"sha": commit["sha"], "branch": branch, "parent": parent, "root": root,
                               "expect_absent": absent, "message": message, "changed_files": sorted(files),
                               "requested": False, "applied": False}
            self.save()
        op = operations[key]
        if op["applied"]:
            return op
        current = self.ref(op["branch"])
        if current and current["object"]["sha"] == op["sha"]:
            op["applied"] = True
            self.state["pending"] = None
            self.save()
            return op
        if op["requested"]:
            self.state["pending"] = {"operation": key, "sha": op["sha"], "reason": "Uncertain ref update; no automatic resend"}
            self.save()
            raise RuntimeError("Push outcome is uncertain. Inspect saved ref intent and GitHub branch, then resume; no push was resent.")
        if current and current["object"]["sha"] != op["parent"]:
            raise ValueError("Scenario branch moved unexpectedly")
        op.update(requested=True, sent_at=runner.stamp())
        self.state["event_count"] += 1
        self.state["pending"] = {"operation": key, "sha": op["sha"]}
        self.save()
        try:
            if op["root"]:
                self.github.request("POST", self.prefix + "/git/refs", {"ref": "refs/heads/" + branch, "sha": op["sha"]})
            else:
                self.github.request("PATCH", self.prefix + "/git/refs/heads/" + urllib.parse.quote(branch, safe="/"),
                                    {"sha": op["sha"], "force": False})
        except RuntimeError as exc:
            if any(f"HTTP {code}" in str(exc) for code in (400, 401, 403, 404, 409, 422)):
                op["rejected"] = True
                self.state["pending"] = None
                self.save()
            raise
        op["applied"] = True
        self.state["pending"] = None
        self.save()
        return op

    def start_branch(self, arm, repeat, label):
        branch = f"ct-scenario/{runner.sha(self.config['experiment_id'].encode())[:12]}/{arm}-{repeat}-{label}"
        raw = (self.directory / ("after.yml" if arm == "optimized" else "before.yml")).read_text(encoding="utf-8")
        if self.pattern in replay.PATTERNS:
            workflow = runner.yaml.load(raw, Loader=runner.ActionsLoader)
            inputs = runner.read_json(self.directory / "source/replay_inputs.json")[str(repeat)]
            workflow["jobs"]["probe"]["steps"][0]["env"]["CT_DATA"] = json.dumps(inputs, sort_keys=True)
            raw = dump(workflow).decode("utf-8")
            (self.directory / f"{arm}_repeat_{repeat}.yml").write_text(raw, encoding="utf-8")
        self.operation(f"{arm}/{repeat}/root-{label}", branch,
                       {WORKFLOW: raw, "src/sentinel.txt": "source\n", "docs/note.md": "docs\n",
                        "config/settings.json": "{}\n"}, "Initialize controlled fixture [skip ci]", root=True)
        return branch

    def push(self, arm, repeat, label, branch, paths, message="scenario probe", absent=False):
        key = f"{arm}/{repeat}/{label}"
        op = self.operation(key, branch, {path: key + "\n" for path in paths}, message, absent=absent)
        self.state["pending"] = {"operation": key, "sha": op["sha"]}
        self.save()
        return key

    def matches(self, op):
        query = urllib.parse.urlencode({"event": "push", "branch": op["branch"], "head_sha": op["sha"]})
        runs = self.github.pages(self.prefix + "/actions/runs?" + query, "workflow_runs")
        matches = [run for run in runs if run.get("head_sha") == op["sha"] and
                   run.get("head_branch") == op["branch"] and run.get("event") == "push" and
                   str(run.get("path", "")).split("@", 1)[0] == WORKFLOW]
        if len(matches) > 1 or any(run.get("run_attempt", 1) != 1 for run in matches):
            raise ValueError("Duplicate run or manual rerun invalidated the scenario")
        return matches

    def collect(self, key):
        op = self.state["operations"][key]
        if "result" in op:
            return op["result"]
        self.state["pending"] = {"operation": key, "sha": op["sha"]}
        self.save()
        began = time.monotonic()
        while True:
            matches = self.matches(op)
            if matches and matches[0].get("status") == "completed":
                run = matches[0]
                break
            if time.monotonic() - began > self.settings["wait_seconds"]:
                raise RuntimeError("Waiting limit reached for " + key + "; event retained, resume to collect without resending")
            print(key + ": " + (matches[0].get("status", "unknown") if matches else "awaiting push event"), flush=True)
            time.sleep(self.settings["poll_seconds"])
        jobs = self.github.pages(self.prefix + f"/actions/runs/{run['id']}/attempts/1/jobs", "jobs")
        raw = self.directory / "runs" / str(run["id"])
        runner.write_json(raw / "run.json", run)
        runner.write_json(raw / "jobs.json", jobs)
        metrics = runner.metrics(run, jobs, [])
        runner.write_json(raw / "metrics.json", metrics)
        op["result"] = {"run_id": run["id"], "run_attempt": 1, "sha": op["sha"], "branch": op["branch"],
                        "conclusion": run.get("conclusion"), "event": "push",
                        "created_at": run.get("created_at"),
                        "workload_intervals": [{"started_at": step.get("started_at"), "completed_at": step.get("completed_at")}
                                               for job in jobs for step in job.get("steps", [])
                                               if step.get("name") == "Controlled workload"],
                        "jobs": [{"name": j["name"], "conclusion": j.get("conclusion")} for j in jobs],
                        "workflow_elapsed_seconds": metrics["workflow_elapsed_seconds"],
                        "sum_job_runtime_seconds": metrics["sum_job_runtime_seconds"],
                        "raw_ref": str(raw.relative_to(runner.ROOT))}
        self.state["pending"] = None
        self.save()
        return op["result"]

    def observe_absence(self, key):
        op = self.state["operations"][key]
        if "result" in op:
            return op["result"]
        self.state["pending"] = {"operation": key, "sha": op["sha"]}
        self.save()
        # Restart a full window after interruption; partial observation cannot pass.
        began = time.monotonic()
        while time.monotonic() - began < self.settings["absence_seconds"]:
            matches = self.matches(op)
            self.event("absence_poll", operation=key, matching_run_ids=[r["id"] for r in matches])
            if matches:
                return self.collect(key)
            time.sleep(self.settings["poll_seconds"])
        # Boundary query closes the observation window; absence is still bounded evidence.
        if self.matches(op):
            return self.collect(key)
        checks = self.github.pages(self.prefix + f"/commits/{op['sha']}/check-runs", "check_runs")
        status = self.github.request("GET", self.prefix + f"/commits/{op['sha']}/status")
        raw = self.directory / "observations" / runner.sha(key.encode())[:16]
        runner.write_json(raw / "checks.json", checks)
        runner.write_json(raw / "commit_status.json", status)
        op["result"] = {"sha": op["sha"], "branch": op["branch"], "no_run_observed": True,
                        "observation_seconds": round(time.monotonic() - began, 2),
                        "conclusion": "not_triggered_within_observation_window", "jobs": [],
                        "sum_job_runtime_seconds": 0, "raw_ref": str(raw.relative_to(runner.ROOT)),
                        "required_status_validated": False}
        self.state["pending"] = None
        self.save()
        return op["result"]

    def running(self, key):
        matches = self.matches(self.state["operations"][key])
        if not matches or matches[0].get("status") != "in_progress":
            return False
        jobs = self.github.pages(self.prefix + f"/actions/runs/{matches[0]['id']}/jobs", "jobs")
        return any(step.get("name") == "Controlled workload" and step.get("status") == "in_progress"
                   for job in jobs for step in job.get("steps", []))

    def wait_started(self, key):
        began = time.monotonic()
        while not self.running(key):
            matches = self.matches(self.state["operations"][key])
            if matches and matches[0].get("status") == "completed":
                raise ValueError("Run completed before the overlap scenario could be established")
            if time.monotonic() - began > self.settings["wait_seconds"]:
                raise RuntimeError("Runner capacity did not establish overlapping jobs; resume to collect tracked events")
            time.sleep(self.settings["poll_seconds"])

    def sample(self, arm, repeat):
        if self.pattern in replay.PATTERNS:
            return self.sample_replay(arm, repeat)
        events, overlap = {}, False
        if self.pattern == "P-LIT-FAIL-FAST":
            for label in ("failure", "healthy"):
                branch = self.start_branch(arm, repeat, label)
                key = self.push(arm, repeat, label, branch, ["src/sentinel.txt"],
                                "Controlled failure [ct-fail]" if label == "failure" else "Healthy matrix control")
                events[label] = self.collect(key)
        elif self.pattern == "P-LIT-CANCEL-STALE":
            branch = self.start_branch(arm, repeat, "same")
            other = self.start_branch(arm, repeat, "isolated")
            old = self.push(arm, repeat, "old", branch, ["src/sentinel.txt"])
            isolated_key = f"{arm}/{repeat}/isolated"
            new_key = f"{arm}/{repeat}/new"
            if new_key not in self.state["operations"]:
                if isolated_key not in self.state["operations"]:
                    self.wait_started(old)
                isolated = self.push(arm, repeat, "isolated", other, ["src/sentinel.txt"])
                self.wait_started(isolated)
                overlap = self.running(old) and self.running(isolated)
                self.state.setdefault("overlap", {})[f"{arm}/{repeat}"] = overlap
                self.save()
                if not overlap:
                    self.collect(old)
                    self.collect(isolated)
                    raise ValueError("No simultaneous old/isolated jobs; scenario cannot measure cancellation")
            new = self.push(arm, repeat, "new", branch, ["src/sentinel.txt"])
            overlap = self.state.get("overlap", {}).get(f"{arm}/{repeat}", False)
            for label, key in (("old", old), ("isolated", isolated_key), ("new", new)):
                events[label] = self.collect(key)
            # Verify overlap using GitHub timestamps after collecting all runs,
            # so a delayed publish or interrupted process cannot falsely pass.
            boundary = events["new"].get("created_at")
            def covered(event):
                return any(runner.seconds(interval["started_at"], boundary) is not None and
                           runner.seconds(interval["started_at"], boundary) >= 0 and
                           runner.seconds(boundary, interval["completed_at"]) is not None and
                           runner.seconds(boundary, interval["completed_at"]) > 0
                           for interval in event.get("workload_intervals", []))
            overlap = overlap and covered(events["old"]) and covered(events["isolated"])
        else:
            branch = self.start_branch(arm, repeat, "events")
            cases = [("source", ["src/sentinel.txt"]), ("docs", ["docs/note.md"])]
            if self.pattern == "P-LIT-CHANGE-FILTER":
                cases += [("config", ["config/settings.json"]), ("mixed", ["src/sentinel.txt", "docs/note.md"])]
            cases += [("source_after", ["src/sentinel.txt"])]
            for label, paths in cases:
                absent = label == "docs" and arm == "optimized"
                message = "Explicitly dispensable documentation" if label == "docs" else "Required source/config control"
                if absent and self.pattern == "P-LIT-SKIP-WORKFLOW":
                    policy = runner.yaml.safe_load((self.directory / "after_policy.yml").read_text())
                    message += " " + policy["dispensable_commit_suffix"]
                key = self.push(arm, repeat, label, branch, paths, message, absent)
                events[label] = self.observe_absence(key) if absent else self.collect(key)
            if arm == "optimized" and events["docs"].get("no_run_observed"):
                # Recheck after the final healthy control as well as at the
                # window boundary, catching events delivered late in the repeat.
                docs_key = f"{arm}/{repeat}/docs"
                op = self.state["operations"][docs_key]
                if self.matches(op):
                    op.pop("result")
                    self.save()
                    events["docs"] = self.collect(docs_key)
        checks = evaluate(self.pattern, arm, events, overlap)
        timings = [event.get("sum_job_runtime_seconds") for event in events.values()]
        return {"arm": arm, "repeat_index": repeat, "scenario_pass": all(checks.values()),
                "assertions": checks, "events": events, "completed_at": runner.stamp(),
                "model": self.config["model"],
                "sum_job_runtime_seconds": sum(timings) if all(t is not None for t in timings) else None}

    def sample_replay(self, arm, repeat):
        inputs = runner.read_json(self.directory / "source/replay_inputs.json")[str(repeat)]
        policy_path = self.directory / ("after_policy.yml" if arm == "optimized" else "before_policy.yml")
        settings = runner.yaml.safe_load(policy_path.read_text(encoding="utf-8"))
        if settings != replay.policy(self.pattern, arm == "optimized"):
            raise ValueError("Replay policy does not match the selected arm")
        branch = self.start_branch(arm, repeat, "replay")
        key = self.push(arm, repeat, "replay", branch, ["src/sentinel.txt"], "Execute controlled service-policy replay")
        event = self.collect(key)
        result = replay.run(self.pattern, settings, inputs)
        checks = replay.validate(self.pattern, settings, inputs, result)
        checks["hosted_replay_assertions_passed"] = (event.get("conclusion") == "success" and
            len(event.get("jobs", [])) == 1 and event["jobs"][0].get("conclusion") == "success")
        evidence = {"evidence_scope": "synthetic_service_policy_replay", "pattern_id": self.pattern,
                    "arm": arm, "repeat_index": repeat, "inputs": inputs, "policy": settings,
                    "result": result, "assertions": checks,
                    "trace_origin": "local_deterministic_reproduction_of_hosted_fixture",
                    "inputs_sha256": runner.sha(runner.encode(inputs)),
                    "engine_sha256": runner.sha((self.directory / "source/replay_engine.py").read_bytes()),
                    "github_run_id": event.get("run_id")}
        path = self.directory / "replays" / f"{arm}-{repeat}.json"
        runner.write_json(path, evidence)
        return {"arm": arm, "repeat_index": repeat, "scenario_pass": all(checks.values()),
                "assertions": checks, "events": {"replay": event}, "completed_at": runner.stamp(),
                "model": self.config["model"],
                "sum_job_runtime_seconds": event.get("sum_job_runtime_seconds"),
                "replay_ref": str(path.relative_to(runner.ROOT)),
                "simulated_work_seconds": result["simulated_work_seconds"],
                "missed_failures": result.get("missed_failures"),
                "missed_failure_rate": result.get("missed_failure_rate"),
                "held_out_mae_seconds": result.get("held_out_mae_seconds")}

    def measure(self, arm):
        if arm == "optimized" and not self.state.get("proposal"):
            raise ValueError("Run baseline and optimization before optimized scenarios")
        for repeat in range(1, 4):
            previous = next((r for r in self.state["records"] if r["arm"] == arm and r["repeat_index"] == repeat), None)
            if previous:
                if not previous["scenario_pass"]:
                    raise ValueError("Previous scenario failed; use --rerun for a fresh case")
                continue
            print(f"Controlled {self.pattern} {arm} repeat {repeat}/3", flush=True)
            try:
                record = self.sample(arm, repeat)
            except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
                try:
                    if isinstance(exc, ValueError):
                        # Drain known pushes before allowing deletion of the fork.
                        for key, op in self.state["operations"].items():
                            if op["applied"] and not op["root"] and "result" not in op:
                                self.observe_absence(key) if op["expect_absent"] else self.collect(key)
                finally:
                    unresolved = [key for key, op in self.state["operations"].items()
                                  if not op.get("rejected") and
                                  ((op["requested"] and not op["applied"]) or
                                   (op["applied"] and not op["root"] and "result" not in op))]
                    self.state["pending"] = {"operations": unresolved} if unresolved else None
                    self.save()
                raise
            self.state["records"].append(record)
            self.state["pending"] = None
            self.save()
            self.export()
            if not record["scenario_pass"]:
                raise ValueError("Unexpected scenario behavior: " + ", ".join(k for k, passed in record["assertions"].items() if not passed))

    def export(self):
        runner.write_json(self.directory / "run_records.json", self.state["records"])
        with (self.directory / "experiment_runs.csv").open("w", encoding="utf-8", newline="") as handle:
            fields = ["arm", "repeat_index", "model", "scenario_pass", "sum_job_runtime_seconds", "completed_at",
                      "simulated_work_seconds", "missed_failures", "missed_failure_rate", "held_out_mae_seconds", "replay_ref"]
            writer = csv.DictWriter(handle, fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(self.state["records"])

    def report(self):
        self.export()
        arms = {}
        for arm in ("baseline", "optimized"):
            records = [r for r in self.state["records"] if r["arm"] == arm]
            times = [r["sum_job_runtime_seconds"] for r in records if r["sum_job_runtime_seconds"] is not None]
            arms[arm] = {"total_repeats": len(records), "passing_repeats": sum(r["scenario_pass"] for r in records),
                         "median_job_runtime_seconds": statistics.median(times) if times else None}
            if self.pattern in replay.PATTERNS:
                for metric in ("simulated_work_seconds", "missed_failures", "missed_failure_rate", "held_out_mae_seconds"):
                    values = [r[metric] for r in records if r.get(metric) is not None]
                    arms[arm]["median_" + metric] = statistics.median(values) if values else None
        passed = all(stats["passing_repeats"] == 3 for stats in arms.values())
        case = {"case_id": self.config["experiment_id"], "record_kind": "controlled_pattern_scenario",
                "evidence_scope": "synthetic_fixture_on_dedicated_fork", "source_repo_id": self.config["source_repo"],
                "fork_repo": self.config["fork_repo"], "pattern_id": self.pattern, "model": self.config["model"],
                "outcome": "scenario_passed" if passed else "inconclusive", "arms": arms,
                "real_repo_optimization_verified": False, "required_status_validated": False,
                "rag_admission": "controlled_scenario_only_pending_applicability_review",
                "absence_window_seconds": self.settings["absence_seconds"],
                "limitations": ["Synthetic workload: timings are scenario resource costs, not original repository CI savings.",
                                "No-run results are bounded observations with positive controls.",
                                "Source branch-protection and required-check safety need a separate applicability review."],
                "run_records_ref": str((self.directory / "run_records.json").relative_to(runner.ROOT))}
        if self.pattern in replay.PATTERNS:
            case["evidence_scope"] = "synthetic_service_policy_replay"
            case["direct_speedup_claimed"] = False
            case["limitations"] += ["Synthetic service policies replay logical time; hosted job runtime measures only replay execution overhead.",
                "Replay traces are reproduced locally from the exact hosted inputs/engine; GitHub success attests the hosted assertions.",
                "No real cron pause, owner notification, GitHub queue priority, build omission, or repository prediction accuracy is established."]
            if self.pattern == "P-LIT-BUILD-SELECT":
                case["safe_for_repository_use"] = False
                case["limitations"].append("The optimized selector deliberately exposes a missed setup failure; scenario_passed does not mean safe selection.")
        runner.write_json(self.directory / "case.json", case)
        lines = ["# Controlled pattern scenario", "", f"Pattern: {self.pattern}", f"Outcome: {case['outcome']}",
                 "", "| Arm | Recorded repeats | Passing repeats | Median summed job runtime (s) |", "|---|---:|---:|---:|"]
        lines += [f"| {arm} | {stats['total_repeats']} | {stats['passing_repeats']} | {stats['median_job_runtime_seconds']} |"
                  for arm, stats in arms.items()]
        if self.pattern in replay.PATTERNS:
            lines += ["", "## Replay metrics (synthetic logical time)", "",
                      "| Arm | Median simulated work (s) | Median missed failures | Median missed-failure rate | Held-out MAE (s) |",
                      "|---|---:|---:|---:|---:|"]
            lines += [f"| {arm} | {s['median_simulated_work_seconds']} | {s['median_missed_failures']} | {s['median_missed_failure_rate']} | {s['median_held_out_mae_seconds']} |"
                      for arm, s in arms.items()]
        lines += ["", *["- " + limitation for limitation in case["limitations"]]]
        (self.directory / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        runner.write_json(self.directory / "artifact_manifest.json", {
            "generated_at": runner.stamp(),
            "files": {str(path.relative_to(self.directory)): runner.sha(path.read_bytes())
                      for path in sorted(self.directory.rglob("*")) if path.is_file() and
                      path.name not in {".lock", "artifact_manifest.json"} and not path.name.endswith(".tmp")}})
        return case


class ScenarioBatch(Batch):
    supported_patterns = SUPPORTED
    supported_scenario_patterns = SUPPORTED
    measurement_name = "controlled scenario repeats"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.scenario_settings = settings_from_env()
        frozen = self.directory / "scenario_settings.json"
        if frozen.exists() and runner.read_json(frozen) != self.scenario_settings:
            raise ValueError("Scenario settings changed; use another --batch-id")
        runner.write_json(frozen, self.scenario_settings)

    def ready_experiment(self, row):
        try:
            # A separate fork name avoids altering the user's normal experiment forks.
            target = self.username + "/ct-scenario-" + runner.sha(row["repo_id"].encode())[:16]
            requested_target = target
            target = self.ensure_fork(row, target)
            if target.lower() != requested_target.lower():
                # GitHub may return an existing fork in the same network instead
                # of creating the requested fork. Never claim or modify that repo.
                self.state.setdefault("created_forks", {}).pop(row["repo_id"], None)
                self.state["forks"].pop(row["repo_id"], None)
                self.state["fork_requests"][row["repo_id"]]["status"] = "rejected"
                self.save()
                raise ValueError("GitHub returned an existing fork with another name; it will be preserved")
            validate_fork(self.github, row["repo_id"], target)
            if self.state.get("created_forks", {}).get(row["repo_id"]) != target:
                raise ValueError("Scenario runner requires a dedicated fork created by this batch; pre-existing forks are kept")
            self.enable_actions(target)
            config = {"experiment_id": self.case_id(row), "source_repo": row["repo_id"], "fork_repo": target,
                      "pattern_id": row["pattern_id"], "model": self.model, "max_tokens": self.max_tokens,
                      "settings": self.scenario_settings, "evidence_scope": "synthetic_fixture_on_dedicated_fork"}
            config_path = self.directory / "configs" / (self.case_id(row) + ".json")
            if config_path.exists():
                saved = runner.read_json(config_path)
                if {k: v for k, v in saved.items() if k not in {"max_tokens", "model"}} != {k: v for k, v in config.items() if k not in {"max_tokens", "model"}}:
                    raise ValueError("Scenario config changed; use another --batch-id")
                config = saved
            else:
                runner.write_json(config_path, config)
            experiment = ScenarioExperiment(config, self.github)
            with runner.exclusive(experiment.directory / ".lock"):
                experiment.prepare()
                runner.write_json(experiment.directory / "selection.json", row)
            self.state["forks"][row["repo_id"]] = target
            self.save()
            return experiment, target
        except (OSError, ValueError, RuntimeError, KeyError, TypeError, runner.yaml.YAMLError) as exc:
            print("Scenario fork preparation failed: " + redact(str(exc)), flush=True)
            return None, "failed"
