"""Hosted GitHub Actions A/B/C experiment executor.

Only GitHub-hosted jobs are measured. The controller never runs a target
repository's build/test commands locally. All source and fork writes are
versioned and the upstream repository is always read-only.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import re
import time
from pathlib import Path
from statistics import median
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from evaluation.candidate_validator import validate_baseline
from evaluation.repository_preparation import (
    dispatch_problems, has_dispatch, has_workflow_run, safety_findings,
    workflow_doc, write_json_immutable,
)


class RunPending(RuntimeError):
    """A dispatched GitHub run is still queued/running; retry collection later.

    This is never a target CI failure and must not trigger another dispatch.
    """


class GitHubError(RuntimeError):
    def __init__(self, code: int, path: str):
        super().__init__(f"GitHub HTTP {code} for {path}")
        self.code = code


class GitHub:
    """Minimal REST adapter; deliberately never logs request auth headers."""
    def __init__(self, token: str):
        if not token:
            raise ValueError("GitHub token missing")
        self.token = token

    def request(self, method: str, path: str, body: dict | None = None):
        if not path.startswith("/"):
            raise ValueError("GitHub API path must be absolute")
        req = Request("https://api.github.com" + path, method=method,
                      data=json.dumps(body).encode("utf-8") if body is not None else None,
                      headers={"Authorization": "Bearer " + self.token,
                               "Accept": "application/vnd.github+json",
                               "X-GitHub-Api-Version": "2022-11-28",
                               "Content-Type": "application/json", "User-Agent": "CloudTune-Evaluation/1"})
        try:
            with urlopen(req, timeout=60) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except HTTPError as exc:
            raise GitHubError(exc.code, path.split("?")[0]) from None
        except (URLError, TimeoutError):
            raise RuntimeError(f"GitHub request outcome uncertain: {method} {path.split('?')[0]}") from None

    def all(self, path: str, key: str) -> list[dict]:
        data = []
        for page in range(1, 11):
            sep = "&" if "?" in path else "?"
            result = self.request("GET", f"{path}{sep}per_page=100&page={page}")
            batch = result.get(key, [])
            data.extend(batch)
            if len(batch) < 100:
                return data
        raise RuntimeError("GitHub pagination limit exceeded; evidence incomplete")

    def blob(self, repository: str, sha: str) -> bytes:
        item = self.request("GET", f"/repos/{repository}/git/blobs/{sha}")
        if item.get("encoding") != "base64":
            raise ValueError("Unsupported GitHub blob encoding")
        return base64.b64decode(item["content"])


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def ensure_dispatch(raw: bytes) -> bytes:
    """Common experimental harness, applied identically to A/B/C.

    Only a plain YAML mapping `on:` may be extended. Other trigger syntax
    requires review; this function does not perform broad YAML reformatting.
    """
    before = workflow_doc(raw)
    # Existing workflow_dispatch inputs may require values that our common
    # empty-input protocol cannot safely invent. Reject instead of getting a
    # 422 response or silently changing the benchmark workload.
    problems = dispatch_problems(before)
    if has_dispatch(before):
        if problems:
            raise ValueError("Workflow cannot be safely dispatched: " + ", ".join(problems))
        return raw
    text = raw.decode("utf-8-sig")
    matches = list(re.finditer(r"^on:\s*$", text, re.MULTILINE))
    if len(matches) != 1:
        raise ValueError("Workflow has no safe plain on: mapping for dispatch harness")
    match = matches[0]
    first = text[match.end():]
    if not re.match(r"\n[ \t]+[A-Za-z_]", first):
        raise ValueError("Workflow on: block is not an ordinary mapping")
    amended = (text[:match.end()] + "\n  workflow_dispatch:" + text[match.end():]).encode("utf-8")
    after = workflow_doc(amended)
    old_on, new_on = before.get("on"), after.get("on")
    if not isinstance(old_on, dict) or not isinstance(new_on, dict) or new_on.get("workflow_dispatch") is not None:
        raise ValueError("Dispatch harness trigger parse failed")
    new_on = dict(new_on)
    new_on.pop("workflow_dispatch", None)
    if old_on != new_on or {k: v for k, v in before.items() if k != "on"} != {k: v for k, v in after.items() if k != "on"}:
        raise ValueError("Dispatch harness changed the original workflow contract")
    return amended



def _timestamp(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def job_timing_metrics(records: list[dict]) -> dict:
    """Separate GitHub-runner-active wall time from gaps between jobs.

    Intervals are merged before summing, so parallel jobs do not inflate the
    active-wall-clock metric. The raw makespan is retained as a distinct
    operational outcome; it can include GitHub's inter-job scheduling delay.
    """
    intervals = sorted((_timestamp(job["started_at"]), _timestamp(job["completed_at"]))
                       for job in records if job.get("started_at") and job.get("completed_at"))
    if not intervals:
        return {"active_seconds": None, "makespan_seconds": None, "idle_gap_seconds": None}
    start, end = intervals[0]
    if end < start:
        raise ValueError("GitHub returned a job that ended before its start")
    active = 0.0
    for left, right in intervals[1:]:
        if right < left:
            raise ValueError("GitHub returned a job that ended before its start")
        if left > end:
            active += (end-start).total_seconds()
            start, end = left, right
        else:
            end = max(end, right)
    active += (end-start).total_seconds()
    full_start = intervals[0][0]
    full_end = max(right for _, right in intervals)
    makespan = (full_end-full_start).total_seconds()
    return {"active_seconds": active, "makespan_seconds": makespan,
            "idle_gap_seconds": max(0.0, makespan-active)}


def verify_fork(fork: dict, upstream_repo: str, owner: str) -> None:
    if fork.get("owner", {}).get("login", "").lower() != owner.lower():
        raise ValueError("Experimental fork owner is not the authorized account")
    if not fork.get("fork") or not fork.get("permissions", {}).get("push"):
        raise ValueError("Fork cannot be modified by the research token")
    family = (fork.get("source") or fork.get("parent") or {}).get("full_name", "")
    if family.lower() != upstream_repo.lower():
        raise ValueError("Fork belongs to a different source family")
    if fork.get("archived") or fork.get("disabled"):
        raise ValueError("Experimental fork is archived or disabled")


def _branch_slug(evaluation_id: str, repo_id: str) -> str:
    short = hashlib.sha256(repo_id.encode()).hexdigest()[:12]
    return f"cloudtune/{evaluation_id[:45]}-{short}"


class ForkExperiment:
    """One repository, one selected workflow, three isolated arm branches."""
    def __init__(self, github: GitHub, *, repo_id: str, workflow_path: str,
                 source_sha: str, original: bytes, evaluation_id: str,
                 max_wait_seconds: int, poll_seconds: int,
                 evidence_root: Path | None = None):
        self.gh = github
        self.upstream = repo_id
        self.workflow_path = workflow_path
        self.source_sha = source_sha
        self.original = original
        self.evaluation_id = evaluation_id
        self.max_wait_seconds = max_wait_seconds
        self.poll_seconds = poll_seconds
        self.prefix = _branch_slug(evaluation_id, repo_id)
        self.evidence_root = evidence_root

    def provision(self, state: dict, save) -> None:
        """Create only research-owned forks; refuse pre-existing untracked ones."""
        if state.get("fork_repo"):
            fork = self.gh.request("GET", "/repos/" + state["fork_repo"])
            verify_fork(fork, self.upstream, state["fork_owner"])
            return
        owner = self.gh.request("GET", "/user")["login"]
        expected = owner + "/" + self.upstream.split("/", 1)[1]
        try:
            existing = self.gh.request("GET", "/repos/" + expected)
        except GitHubError as exc:
            if exc.code != 404:
                raise
        else:
            # A persisted fork-creation intent does not prove who created an
            # existing repository after an uncertain POST response. Never
            # adopt and later delete it without positive creation evidence.
            if (state.get("fork_creation_intent") != expected or
                    not state.get("fork_created_by_evaluation")):
                raise ValueError(
                    f"Existing fork {existing['full_name']} is not proven to be "
                    "created by this evaluation; preserve it for manual review")
            verify_fork(existing, self.upstream, owner)
            state.update(fork_repo=existing["full_name"], fork_owner=owner)
            save()
            return
        state["fork_creation_intent"] = expected
        save()
        # A lost response is deliberately NOT automatically retried. A rerun
        # checks existing fork identity and requires explicit recovery approval.
        created = self.gh.request("POST", "/repos/" + self.upstream + "/forks", {})
        fork_id = created["full_name"]
        state.update(fork_repo=fork_id, fork_owner=owner, fork_created_by_evaluation=True)
        save()
        for _ in range(40):
            try:
                fork = self.gh.request("GET", "/repos/" + fork_id)
                verify_fork(fork, self.upstream, owner)
                return
            except GitHubError as exc:
                if exc.code != 404:
                    raise
            time.sleep(5)
        raise RuntimeError("Fork creation pending; resume later")

    def _selected_tree(self, repo: str, ref: str):
        commit = self.gh.request("GET", f"/repos/{repo}/commits/{quote(ref, safe='')}")
        tree_sha = commit["commit"]["tree"]["sha"]
        tree = self.gh.request("GET", f"/repos/{repo}/git/trees/{tree_sha}?recursive=1")
        if tree.get("truncated"):
            raise ValueError("GitHub tree truncated; cannot prove isolation")
        return commit, tree

    def _new_tree(self, fork: str, base: str, workflow: bytes) -> str:
        blob = self.gh.request("POST", f"/repos/{fork}/git/blobs", {
            "encoding": "base64", "content": base64.b64encode(workflow).decode("ascii")})["sha"]
        tree = self.gh.request("POST", f"/repos/{fork}/git/trees", {
            "base_tree": base, "tree": [{"path": self.workflow_path,
                                         "mode": "100644", "type": "blob", "sha": blob}]})
        return tree["sha"]

    def _commit(self, fork: str, tree: str, parent: str, label: str) -> str:
        return self.gh.request("POST", f"/repos/{fork}/git/commits", {
            "message": f"[skip ci] CloudTune {self.evaluation_id} {label}",
            "tree": tree, "parents": [parent]})["sha"]

    def _ref(self, fork: str, ref: str) -> str | None:
        try:
            return self.gh.request("GET", f"/repos/{fork}/git/ref/heads/{ref}")["object"]["sha"]
        except GitHubError as exc:
            if exc.code == 404:
                return None
            raise

    def prepare(self, state: dict, save) -> None:
        if state.get("prepared_commit"):
            fork = state["fork_repo"]
            if self._ref(fork, state["default_branch"]) != state["default_branch_commit"]:
                raise ValueError("Fork default branch changed after harness registration")
            if state.get("actions_disabled_for_setup"):
                # A previous runner may have stopped after recording the
                # harness commit but before re-enabling Actions on the fork.
                self.gh.request("PUT", f"/repos/{fork}/actions/permissions", {"enabled": True})
                state["actions_disabled_for_setup"] = False
                save()
            if state.get("workflow_id"):
                return
            # Resume the registration poll even if the commit was prepared.
            # Never produce a second harness commit after a runner timeout.
            self._wait_for_workflow(state, save)
            return
        fork = state["fork_repo"]
        info = self.gh.request("GET", "/repos/" + fork)
        default = info["default_branch"]
        current, tree = self._selected_tree(fork, default)
        # Every default-branch workflow is inspected: chained listeners,
        # deployments or secrets must never run via test activity.
        for entry in tree["tree"]:
            if entry["type"] != "blob" or not re.fullmatch(r"\.github/workflows/[^/]+\.ya?ml", entry["path"]):
                continue
            doc = workflow_doc(self.gh.blob(fork, entry["sha"]))
            if has_workflow_run(doc) or safety_findings(doc):
                raise ValueError("Unsafe ancillary workflow on fork default branch: " + entry["path"])
        # Test source revision must actually exist in the fork's Git object DB.
        source = self.gh.request("GET", f"/repos/{fork}/git/commits/{self.source_sha}")
        source_tree = source["tree"]["sha"]
        common = ensure_dispatch(self.original)
        static_check = validate_baseline(common)
        if static_check["verdict"] != "PASS":
            raise ValueError("Prepared baseline workflow did not pass actionlint and static safety checks: " +
                             ", ".join(static_check["reasons"]))
        # Register the common harness exactly once. Persist the intended
        # registration commit BEFORE moving the default-branch ref, so a lost
        # PATCH response can be reconciled without another unrelated commit.
        intent = state.get("registration_intent")
        if intent:
            if intent["default_branch"] != default or intent["common_sha256"] != digest(common):
                raise ValueError("Pending default-branch registration identity changed")
            registration = intent["registration_sha"]
            if current["sha"] not in {intent["original_default_sha"], registration}:
                raise ValueError("Fork default branch moved during harness registration")
        else:
            # Disable Actions before the registration push to avoid executing
            # unrelated push-triggered workflows during harness setup.
            if not state.get("actions_disabled_for_setup"):
                self.gh.request("PUT", f"/repos/{fork}/actions/permissions", {"enabled": False})
                state["actions_disabled_for_setup"] = True
                save()
            default_tree = self._new_tree(fork, current["commit"]["tree"]["sha"], common)
            registration = self._commit(fork, default_tree, current["sha"], "register-dispatch")
            state["registration_intent"] = {
                "default_branch": default, "original_default_sha": current["sha"],
                "registration_sha": registration, "common_sha256": digest(common)}
            save()
        if current["sha"] != registration:
            self.gh.request("PATCH", f"/repos/{fork}/git/refs/heads/{default}", {
                "sha": registration, "force": False})
        # Create a common source commit from the exact pinned tree, rather than
        # the moving default branch. Every A/B/C ref derives from this commit.
        prepared_tree = self._new_tree(fork, source_tree, common)
        prepared = self._commit(fork, prepared_tree, self.source_sha, "common-dispatch-harness")
        state.update(prepared_commit=prepared, prepared_tree=prepared_tree,
                     default_branch=default, default_branch_commit=registration,
                     harness_sha256=digest(common), original_sha256=digest(self.original),
                     common_workflow=base64.b64encode(common).decode("ascii"), arms={})
        save()
        self.gh.request("PUT", f"/repos/{fork}/actions/permissions", {"enabled": True})
        state["actions_disabled_for_setup"] = False
        save()
        self._wait_for_workflow(state, save)

    def _wait_for_workflow(self, state: dict, save) -> None:
        """GitHub can index registered workflows asynchronously."""
        fork = state["fork_repo"]
        for _ in range(24):
            try:
                workflow = self.gh.request("GET", f"/repos/{fork}/actions/workflows/{Path(self.workflow_path).name}")
                if workflow.get("state") == "active":
                    state["workflow_id"] = workflow["id"]
                    save()
                    return
            except GitHubError as exc:
                if exc.code != 404:
                    raise
            time.sleep(5)
        raise RunPending("GitHub workflow registration is pending; retry on next controller run")

    def make_arm(self, state: dict, arm: str, proposed: bytes, save) -> dict:
        fork = state["fork_repo"]
        common = base64.b64decode(state["common_workflow"])
        if arm == "A" and proposed != self.original:
            raise ValueError("Arm A must be unmodified")
        rendered = ensure_dispatch(proposed)
        # Original trigger modifications must be identical common harness.
        if arm != "A":
            before = workflow_doc(self.original)
            after = workflow_doc(proposed)
            if before.get("on") != after.get("on"):
                raise ValueError("Optimizer changed original workflow triggers")
        if arm == "A" and rendered != common:
            raise ValueError("Arm A differs from common prepared baseline")
        result = state["arms"].get(arm)
        if result:
            if result["workflow_sha256"] != digest(rendered):
                raise ValueError("Experimental candidate bytes changed")
            remote = self._ref(fork, result["branch"])
            if remote is None:
                # A saved branch intent may precede an interrupted POST.
                self.gh.request("POST", f"/repos/{fork}/git/refs", {
                    "ref": "refs/heads/" + result["branch"], "sha": result["sha"]})
            elif remote != result["sha"]:
                raise ValueError("Experimental arm reference changed")
            self._verify_arm_tree(fork, state["prepared_tree"], result)
            return result
        tree = state["prepared_tree"] if arm == "A" else self._new_tree(fork, state["prepared_tree"], rendered)
        commit = state["prepared_commit"] if arm == "A" else self._commit(fork, tree, state["prepared_commit"], arm)
        branch = f"{self.prefix}-{arm.lower()}"
        # Save exact commit BEFORE remote branch creation to survive timeouts.
        result = {"sha": commit, "tree": tree, "branch": branch, "workflow_sha256": digest(rendered)}
        state["arms"][arm] = result
        save()
        remote = self._ref(fork, branch)
        if remote is None:
            self.gh.request("POST", f"/repos/{fork}/git/refs", {
                "ref": "refs/heads/" + branch, "sha": commit})
        elif remote != commit:
            raise ValueError("Experiment arm branch was modified unexpectedly")
        self._verify_arm_tree(fork, state["prepared_tree"], result)
        return result

    def _verify_arm_tree(self, fork: str, common_tree: str, arm: dict) -> None:
        """Only the target workflow may differ from the pinned common tree."""
        base = self.gh.request("GET", f"/repos/{fork}/git/trees/{common_tree}?recursive=1")
        changed = self.gh.request("GET", f"/repos/{fork}/git/trees/{arm['tree']}?recursive=1")
        if base.get("truncated") or changed.get("truncated"):
            raise ValueError("Experiment tree listing is truncated")
        def entries(tree):
            return sorted((item["path"], item["mode"], item["sha"])
                          for item in tree["tree"] if item["type"] == "blob"
                          and item["path"] != self.workflow_path)
        if entries(base) != entries(changed):
            raise ValueError("Experimental arm changed files outside the selected workflow")

    def _run_ids(self, fork: str, workflow_id: int, branch: str):
        qs = urlencode({"branch": branch, "event": "workflow_dispatch"})
        runs = self.gh.all(f"/repos/{fork}/actions/workflows/{workflow_id}/runs?{qs}", "workflow_runs")
        return runs

    def _pending_run(self, state: dict, save) -> int:
        pending = state["pending"]
        fork = state["fork_repo"]
        if pending.get("run_id"):
            return pending["run_id"]
        arm = state["arms"][pending["arm"]]
        for _ in range(max(1, self.max_wait_seconds // self.poll_seconds)):
            matches = [row for row in self._run_ids(fork, state["workflow_id"], arm["branch"])
                       if (row["id"] not in pending["old_ids"] and row.get("head_sha") == arm["sha"]
                           and row.get("event") == "workflow_dispatch")]
            if len(matches) > 1:
                raise RuntimeError("Ambiguous dispatch: multiple matching runs; manual reconciliation required")
            if matches:
                pending["run_id"] = matches[0]["id"]
                save()
                return pending["run_id"]
            time.sleep(self.poll_seconds)
        raise RunPending("Dispatch identity not resolved yet; retry observation without sending another POST")

    def execute(self, state: dict, save, *, arm: str, repeat: int,
                required: list[str], max_total: int) -> dict:
        # Pending must be collected before ANY new run; this covers ambiguous
        # POST outcomes, queue timeout and controller reruns.
        if state.get("pending"):
            p = state["pending"]
            if (p["arm"], p["repeat"]) != (arm, repeat):
                raise RuntimeError("Earlier dispatch is pending; resume it before new runs")
        else:
            if state.get("dispatch_count", 0) >= max_total:
                raise RuntimeError("Maximum GitHub Actions dispatch budget exceeded")
            fork = state["fork_repo"]
            if self._ref(fork, state["default_branch"]) != state["default_branch_commit"]:
                raise ValueError("Fork default branch moved")
            run_arm = state["arms"][arm]
            if self._ref(fork, run_arm["branch"]) != run_arm["sha"]:
                raise ValueError("Experimental branch moved")
            old = {x["id"] for x in self._run_ids(fork, state["workflow_id"], run_arm["branch"])}
            state["pending"] = {"arm": arm, "repeat": repeat, "old_ids": sorted(old),
                                "sent_at": dt.datetime.now(dt.timezone.utc).isoformat(), "run_id": None}
            state["dispatch_count"] = state.get("dispatch_count", 0) + 1
            save()
            response = self.gh.request("POST", f"/repos/{fork}/actions/workflows/{state['workflow_id']}/dispatches", {
                "ref": run_arm["branch"], "inputs": {}, "return_run_details": True})
            if response and response.get("workflow_run_id"):
                state["pending"]["run_id"] = response["workflow_run_id"]
                save()
        run_id = self._pending_run(state, save)
        fork = state["fork_repo"]
        started = time.monotonic()
        while True:
            run = self.gh.request("GET", f"/repos/{fork}/actions/runs/{run_id}")
            if run.get("status") == "completed":
                break
            if time.monotonic() - started > self.max_wait_seconds:
                raise RunPending(f"GitHub run {run_id} is queued/in progress; resume observation later")
            time.sleep(self.poll_seconds)
        attempt = run.get("run_attempt", 1)
        jobs = self.gh.all(f"/repos/{fork}/actions/runs/{run_id}/attempts/{attempt}/jobs", "jobs")
        arm_ref = state["arms"][arm]
        valid = (run.get("head_sha") == arm_ref["sha"] and
                 run.get("head_branch") == arm_ref["branch"] and
                 run.get("workflow_id") == state["workflow_id"] and
                 run.get("event") == "workflow_dispatch" and attempt == 1)
        def duration(a, b):
            if not a or not b:
                return None
            return (dt.datetime.fromisoformat(b.replace("Z", "+00:00")) -
                    dt.datetime.fromisoformat(a.replace("Z", "+00:00"))).total_seconds()
        records = []
        for job in jobs:
            seconds = duration(job.get("started_at"), job.get("completed_at"))
            if job.get("conclusion") == "skipped" and seconds is None:
                seconds = 0.0
            records.append({"id": job["id"], "name": job["name"],
                            "status": job.get("status"), "conclusion": job.get("conclusion"),
                            "started_at": job.get("started_at"), "completed_at": job.get("completed_at"),
                            "duration_seconds": seconds, "runner_name": job.get("runner_name"),
                            "runner_labels": job.get("labels", [])})
        # Workflow-level run_started_at may precede assignment of the first
        # GitHub runner. It is not an execution start and can include queueing.
        # Use executed jobs only for the execution window and resource usage.
        executed = [r for r in records if r["started_at"] and r["completed_at"]]
        first = min((r["started_at"] for r in executed), default=None)
        last = max((r["completed_at"] for r in executed), default=None)
        complete = bool(executed) and all(
            r["duration_seconds"] is not None and (r["started_at"] or r["conclusion"] == "skipped")
            for r in records)
        timing = job_timing_metrics(records) if complete else {
            "active_seconds": None, "makespan_seconds": None, "idle_gap_seconds": None}
        # Primary evaluation metric is the actual observed time with >=1 GitHub
        # job executing. Internal runner queue gaps are excluded using merged
        # job intervals. Keep makespan separately for end-to-end diagnostics.
        elapsed = timing["active_seconds"]
        total = sum(r["duration_seconds"] for r in records) if complete else None
        # Queue before the first runner is excluded. GitHub runner assignment
        # delays between dependent jobs appear only in idle_gap_seconds.
        initial_queue = duration(run.get("created_at"), first)
        if not required and arm == "A" and run.get("conclusion") == "success":
            # Freeze observed baseline jobs before B/C; note this is not
            # branch-protection-approved required-check configuration.
            required = sorted(r["name"] for r in records if r["conclusion"] != "skipped")
            state["required_names"] = required
        required_pass = bool(required) and all(any(r["name"] == name and r["conclusion"] == "success"
                                                   for r in records) for name in required)
        if self.evidence_root:
            # The state controller archives this snapshot to the durable state
            # branch together with its next ledger checkpoint.
            evidence = self.evidence_root / "runs" / str(run_id) / f"attempt-{attempt}"
            write_json_immutable(evidence / "run.json", run)
            write_json_immutable(evidence / "jobs.json", jobs)
        outcome = {"arm": arm, "repeat": repeat, "run_id": run_id, "run_attempt": attempt,
                   "source_commit_sha": self.source_sha, "config_commit_sha": arm_ref["sha"],
                   "workflow_sha256": arm_ref["workflow_sha256"], "conclusion": run.get("conclusion"),
                   "protocol_valid": valid, "required_checks_pass": required_pass,
                   "workflow_elapsed_seconds": elapsed, "sum_job_runtime_seconds": total,
                   "workflow_makespan_seconds": timing["makespan_seconds"],
                   "inter_job_idle_seconds": timing["idle_gap_seconds"],
                   "initial_queue_seconds": initial_queue,
                   "failure_class": ("PLATFORM_NO_JOB_START" if not executed else
                                    "CI_FAILURE_OR_PROTOCOL_MISMATCH" if not
                                    (valid and complete and required_pass and run.get("conclusion") == "success")
                                    else None),
                   "first_job_started_at": first, "last_job_completed_at": last,
                   "run_created_at": run.get("created_at"),
                   "github_run_started_at": run.get("run_started_at"), "jobs": records,
                   "raw_evidence_ref": (f"runs/{run_id}/attempt-{attempt}" if self.evidence_root else None),
                   "comparable": bool(valid and complete and required_pass and run.get("conclusion") == "success")}
        state.setdefault("records", []).append(outcome)
        state["pending"] = None
        save()
        return outcome


    def cleanup_fork(self, state: dict, save) -> str:
        """Delete only a fork created for THIS experiment, after all runs settle.

        Persist intent before DELETE. On interrupted DELETE, a subsequent call
        confirms 404 without reusing the fork name or resending an unsafe write.
        Never delete a pre-existing fork or one with active/unknown Actions runs.
        """
        if not state.get("measurements_finalized"):
            raise ValueError("Fork cleanup requires finalized measurement records")
        if state.get("pending"):
            raise RunPending("Fork still has a pending CI dispatch; cleanup postponed")
        if not state.get("fork_repo"):
            return "NOT_CREATED"
        if state.get("cleanup_status") == "DELETED":
            return "DELETED"
        fork_name = state["fork_repo"]
        expected = state.get("fork_creation_intent")
        owner = state.get("fork_owner", "")
        if (not state.get("fork_created_by_evaluation") or not owner or
                expected != fork_name or not fork_name.startswith(owner + "/")):
            state["cleanup_status"] = "PRESERVED_NOT_OWNED"
            save()
            return "PRESERVED_NOT_OWNED"

        try:
            fork = self.gh.request("GET", "/repos/" + fork_name)
        except GitHubError as exc:
            if exc.code == 404 and state.get("cleanup_intent") == fork_name:
                state["cleanup_status"] = "DELETED"
                save()
                return "DELETED"
            raise
        verify_fork(fork, self.upstream, owner)
        if not state.get("cleanup_intent"):
            # Fail closed if ANY workflow is still queued, waiting, requested,
            # pending, or running, including workflows unrelated to the target.
            runs = self.gh.all(f"/repos/{fork_name}/actions/runs", "workflow_runs")
            active = [r for r in runs if r.get("status") not in {"completed"}]
            if active:
                state["cleanup_status"] = "WAITING_FOR_OTHER_RUNS"
                state["cleanup_active_run_ids"] = [r.get("id") for r in active]
                save()
                return "WAITING_FOR_OTHER_RUNS"
            state["cleanup_intent"] = fork_name
            state["cleanup_status"] = "DELETE_REQUESTED"
            save()  # Critical: crash-safe DELETE intent, before the API call.
        else:
            if state["cleanup_intent"] != fork_name:
                raise ValueError("Fork cleanup intent changed")
            # An earlier DELETE may have been accepted despite a lost response.
            # Never blindly send the destructive request twice.
            state["cleanup_status"] = "DELETE_OUTCOME_UNKNOWN"
            save()
            return "DELETE_OUTCOME_UNKNOWN"
        try:
            self.gh.request("DELETE", "/repos/" + fork_name)
        except GitHubError as exc:
            state["cleanup_status"] = "BLOCKED_PERMISSION" if exc.code in {401, 403} else "DELETE_OUTCOME_UNKNOWN"
            save()
            return state["cleanup_status"]
        except RuntimeError:
            state["cleanup_status"] = "DELETE_OUTCOME_UNKNOWN"
            save()
            return "DELETE_OUTCOME_UNKNOWN"
        state["cleanup_status"] = "DELETED"
        save()
        return "DELETED"


def summarize_records(records: list[dict], *, repetitions: int | None = None) -> dict:
    """Compute only actual comparable GitHub-hosted measurements.

    Incomplete repetition sets have no effect-size estimate. No queue time
    enters the elapsed or summed-runner timing measurements.
    """
    by_arm = {arm: [r for r in records if r["arm"] == arm] for arm in "ABC"}
    results = {}
    for arm, runs in by_arm.items():
        valid = [r for r in runs if r["comparable"]]
        complete = bool(valid) and (repetitions is None or len(valid) == repetitions)
        results[arm] = {"attempted": len(runs), "comparable": len(valid),
                        "failed": len(runs) - len(valid), "complete": complete,
                        "median_elapsed_seconds": median(r["workflow_elapsed_seconds"] for r in valid) if complete else None,
                        "median_runner_seconds": median(r["sum_job_runtime_seconds"] for r in valid) if complete else None,
                        "median_initial_queue_seconds": (median(r["initial_queue_seconds"] for r in valid
                                                         if r.get("initial_queue_seconds") is not None)
                                  if complete and all(r.get("initial_queue_seconds") is not None for r in valid)
                                  else None)}
    for target, baseline_arm in (("B", "A"), ("C", "A"), ("C", "B")):
        suffix = ("vs_A" if baseline_arm == "A" else "vs_B")
        for kind in ("elapsed", "runner"):
            baseline = results[baseline_arm][f"median_{kind}_seconds"]
            optimized = results[target][f"median_{kind}_seconds"]
            results[target][f"{kind}_saving_percent_{suffix}"] = (
                100 * (baseline - optimized) / baseline
                if baseline is not None and optimized is not None and baseline > 0 else None)
    return results
