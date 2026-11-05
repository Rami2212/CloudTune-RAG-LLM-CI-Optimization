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
import os
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


# Human-readable names are for diagnostics only. Persisted A/B/C identifiers,
# GitHub experiment branches, and exported arm keys are intentionally unchanged.
ARM_NAMES = {
    "A": "Original Workflow",
    "B": "CI-Cost",
    "C": "LLM + RAG",
}

QUEUE_TIMEOUT_SECONDS = 120
IN_PROGRESS_TIMEOUT_SECONDS = 600


def arm_name(arm: str) -> str:
    """Return the stable display name of a controlled evaluation arm."""
    return ARM_NAMES[arm]


def log_progress(stage: str, message: str) -> None:
    """Print safe, time-stamped operational progress; never log API credentials.

    Keep this intentionally independent from GitHub state and checkpoint data.
    Terminal output is diagnostic and must not become experimental evidence.
    """
    now = dt.datetime.now(dt.timezone.utc).strftime("%H:%M:%S UTC")
    print(f"[{now}] [{stage}] {message}", flush=True)


class RunPending(RuntimeError):
    """A dispatched GitHub run is still queued/running; retry collection later.

    This is never a target CI failure and must not trigger another dispatch.
    """


class RunQueueTimeout(RuntimeError):
    """A confirmed queued run exceeded the queue budget and was stopped."""

    failure_class = "QUEUE_TIMEOUT"


class RunExecutionTimeout(RuntimeError):
    """A running workflow exceeded the execution-time budget and was stopped."""

    failure_class = "IN_PROGRESS_TIMEOUT"


class GitHubError(RuntimeError):
    def __init__(self, code: int, path: str):
        super().__init__(f"GitHub HTTP {code} for {path}")
        self.code = code


def automatic_fork_deletion_enabled() -> bool:
    """Read the fork-cleanup setting; reject ambiguous values.

    Automatic deletion is enabled unless explicitly disabled by the operator.
    """
    value = os.environ.get("CLOUDTUNE_AUTO_DELETE_FORKS", "true").strip().lower()
    if value in {"true", "1", "yes", "on"}:
        return True
    if value in {"false", "0", "no", "off"}:
        return False
    raise ValueError("CLOUDTUNE_AUTO_DELETE_FORKS must be true or false")


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

    Extend block mappings, scalar/event lists, or block-sequence event lists.
    Only the trigger section is changed; jobs and commands are never reformatted.
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
    old_events = before.get("on")
    if isinstance(old_events, str) or (
            isinstance(old_events, list) and old_events
            and all(isinstance(event, str) for event in old_events)):
        # Rewrite only the trigger header; preserve every job and command byte.
        events = [old_events] if isinstance(old_events, str) else old_events
        headers = list(re.finditer(r'''^(?:on|'on'|"on"):[^\r\n]*''', text, re.MULTILINE))
        if len(headers) != 1 or len(set(events)) != len(events):
            raise ValueError("Workflow trigger header requires independent review")
        header = headers[0]
        header_value = text[header.start():header.end()].split(":", 1)[1].strip()
        if not header_value or header_value.startswith("#"):
            # Preserve list-style triggers by appending one event item. Validate
            # the complete sequence shape first; never rewrite jobs or infer
            # events from comments/aliases.
            lines = text.splitlines(keepends=True)
            header_line = text.count("\n", 0, header.start())
            sequence_lines = []
            sequence_indent = None
            for index in range(header_line + 1, len(lines)):
                line = lines[index].rstrip("\r\n")
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                if not line[0].isspace():
                    break
                item = re.match(r"^( *)-\s+(.+?)\s*(?:#.*)?$", line)
                if not item or (sequence_indent is not None and item.group(1) != sequence_indent):
                    raise ValueError("Block sequence triggers require independent review")
                sequence_indent = item.group(1)
                sequence_lines.append(index)
            if not sequence_lines or len(sequence_lines) != len(events):
                raise ValueError("Block sequence triggers require independent review")
            newline = "\r\n" if "\r\n" in text else "\n"
            insert_at = sequence_lines[-1] + 1
            if not lines[sequence_lines[-1]].endswith(("\n", "\r")):
                lines[sequence_lines[-1]] += newline
            lines.insert(insert_at, sequence_indent + "- workflow_dispatch" + newline)
            amended = "".join(lines).encode("utf-8")
            after = workflow_doc(amended)
            expected = dict(before)
            expected["on"] = [*events, "workflow_dispatch"]
            if after != expected:
                raise ValueError("Dispatch harness changed the original workflow contract")
            return amended
        newline = "\r\n" if "\r\n" in text else "\n"
        replacement = "on:" + newline + "  workflow_dispatch:" + newline
        replacement += newline.join("  " + json.dumps(event) + ":" for event in events)
        amended = (text[:header.start()] + replacement + text[header.end():]).encode("utf-8")
        after = workflow_doc(amended)
        expected = dict(before)
        expected["on"] = {"workflow_dispatch": None, **{event: None for event in events}}
        if after != expected:
            raise ValueError("Dispatch harness changed the original workflow contract")
        return amended
    matches = list(re.finditer(r'''^(?:on|'on'|"on"):[ \t]*(?:#[^\r\n]*)?(?=\r?$)''',
                               text, re.MULTILINE))
    if len(matches) != 1:
        raise ValueError("Workflow has no safe plain on: mapping for dispatch harness")
    match = matches[0]
    first = text[match.end():]
    child = re.match(r"(\r?\n)( +)[A-Za-z_]", first)
    if not child:
        raise ValueError("Workflow on: block is not an ordinary mapping")
    amended = (text[:match.end()] + child[1] + child[2] + "workflow_dispatch:" +
               text[match.end():]).encode("utf-8")
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


def verify_fork(fork: dict, upstream_repo: str, owner: str,
                *, expected_id: int | None = None) -> None:
    """Verify source and owner, plus the immutable repository ID when pinned."""
    if fork.get("owner", {}).get("login", "").lower() != owner.lower():
        raise ValueError("Experimental fork owner is not the authorized account")
    if not fork.get("fork") or not fork.get("permissions", {}).get("push"):
        raise ValueError("Fork cannot be modified by the research token")
    family = (fork.get("source") or fork.get("parent") or {}).get("full_name", "")
    if family.lower() != upstream_repo.lower():
        raise ValueError("Fork belongs to a different source family")
    if fork.get("archived") or fork.get("disabled"):
        raise ValueError("Experimental fork is archived or disabled")
    # A fork can be deleted and recreated with the same owner/name/source.
    # The numeric GitHub repository ID prevents adopting or deleting its replacement.
    if expected_id is not None and (type(fork.get("id")) is not int or
                                    fork["id"] != expected_id):
        raise ValueError("Fork repository ID changed; refuse unsafe reuse or deletion")


def _branch_slug(evaluation_id: str, repo_id: str) -> str:
    short = hashlib.sha256(repo_id.encode()).hexdigest()[:12]
    return f"cloudtune/{evaluation_id[:45]}-{short}"


class ForkExperiment:
    """One repository, one selected workflow, three isolated arm branches."""
    def __init__(self, github: GitHub, *, repo_id: str, workflow_path: str,
                 source_sha: str, original: bytes, evaluation_id: str,
                 max_wait_seconds: int | None, poll_seconds: int,
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
        """Reuse a verified existing fork, or create and pin a new one."""
        if state.get("fork_repo"):
            log_progress("FORK", f"Verifying saved fork identity: {state['fork_repo']}")
            if type(state.get("fork_id")) is not int or state["fork_id"] <= 0:
                raise ValueError("Pinned fork repository ID missing; do not reuse fork")
            fork = self.gh.request("GET", "/repos/" + state["fork_repo"])
            verify_fork(fork, self.upstream, state["fork_owner"],
                        expected_id=state["fork_id"])
            log_progress("FORK", f"Saved fork identity verified (id={state['fork_id']})")
            return
        owner = self.gh.request("GET", "/user")["login"]
        expected = owner + "/" + self.upstream.split("/", 1)[1]
        try:
            existing = self.gh.request("GET", "/repos/" + expected)
        except GitHubError as exc:
            if exc.code != 404:
                raise
        else:
            numeric_id = existing.get("id")
            if type(numeric_id) is not int or numeric_id <= 0:
                raise ValueError("Existing fork has no numeric repository ID; preserve it")
            if state.get("fork_created_by_evaluation"):
                expected_id = state.get("fork_id")
                if type(expected_id) is not int or expected_id <= 0:
                    raise ValueError("Pinned fork repository ID missing; preserve existing fork")
                verify_fork(existing, self.upstream, owner, expected_id=expected_id)
                state.update(fork_repo=existing["full_name"], fork_owner=owner,
                             fork_reused_existing=False)
            else:
                # A matching, writable fork is safe to use for this evaluation,
                # but it remains user-owned and must never be deleted by cleanup.
                verify_fork(existing, self.upstream, owner)
                state.update(fork_repo=existing["full_name"], fork_owner=owner,
                             fork_id=numeric_id, fork_created_by_evaluation=False,
                             fork_reused_existing=True)
            save()
            log_progress("FORK", f"Reusing verified existing fork {existing['full_name']} (id={numeric_id})")
            return
        state["fork_creation_intent"] = expected
        save()
        log_progress("FORK", f"Creating new research-owned fork {expected} from {self.upstream}")
        # A lost response is deliberately NOT automatically retried. A rerun
        # checks existing fork identity and requires explicit recovery approval.
        created = self.gh.request("POST", "/repos/" + self.upstream + "/forks", {})
        fork_name = created["full_name"]
        if fork_name.casefold() != expected.casefold():
            # GitHub may return a previously existing differently named fork.
            # A 202 response alone does not grant deletion ownership.
            raise ValueError("Fork creation returned unexpected name; preserve existing repository")
        numeric_id = created.get("id")
        if type(numeric_id) is not int or numeric_id <= 0:
            raise ValueError("GitHub fork response lacks a numeric repository ID; manual recovery required")
        state.update(fork_repo=fork_name, fork_owner=owner, fork_id=numeric_id,
                     fork_created_by_evaluation=True, fork_reused_existing=False)
        save()
        log_progress("FORK", f"Fork created, numeric identity={numeric_id}; waiting for GitHub readiness")
        for _ in range(40):
            try:
                fork = self.gh.request("GET", "/repos/" + fork_name)
                verify_fork(fork, self.upstream, owner, expected_id=numeric_id)
                log_progress("FORK", f"Fork ready: https://github.com/{fork_name}")
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

    def _ancillary_paths(self, tree: dict) -> list[str]:
        """Remove unrelated executable workflows from the common fork harness."""
        if tree.get("truncated") or not isinstance(tree.get("tree"), list):
            raise ValueError("GitHub tree truncated; cannot prove workflow isolation")
        return sorted(entry["path"] for entry in tree["tree"]
                      if entry.get("type") == "blob"
                      and re.fullmatch(r"\.github/workflows/[^/]+\.ya?ml", entry["path"])
                      and entry["path"] != self.workflow_path)

    def _new_tree(self, fork: str, base: str, workflow: bytes,
                  *, remove_workflows: list[str] | tuple[str, ...] = ()) -> str:
        blob = self.gh.request("POST", f"/repos/{fork}/git/blobs", {
            "encoding": "base64", "content": base64.b64encode(workflow).decode("ascii")})["sha"]
        entries = [{"path": self.workflow_path, "mode": "100644", "type": "blob", "sha": blob}]
        for path in remove_workflows:
            if path == self.workflow_path or not re.fullmatch(r"\.github/workflows/[^/]+\.ya?ml", path):
                raise ValueError("Invalid ancillary workflow removal path")
            entries.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
        tree = self.gh.request("POST", f"/repos/{fork}/git/trees", {
            "base_tree": base, "tree": entries})
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
        log_progress("WORKFLOW", f"Preparing common Original Workflow / CI-Cost / LLM + RAG dispatch harness for {state['fork_repo']}")
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
                # A saved workflow ID is not proof that the workflow is active.
                # Newly forked repositories can disable a workflow separately
                # from the repository-wide Actions setting.
                self._wait_for_workflow(state, save)
                return
            # Resume the registration poll even if the commit was prepared.
            # Never produce a second harness commit after a runner timeout.
            self._wait_for_workflow(state, save)
            return
        fork = state["fork_repo"]
        info = self.gh.request("GET", "/repos/" + fork)
        default = info["default_branch"]
        current, tree = self._selected_tree(fork, default)
        # Isolate the selected workflow instead of executing unrelated inherited
        # release/push workflows. Apply the same removals to every trial arm.
        default_removals = self._ancillary_paths(tree)
        # Test source revision must actually exist in the fork's Git object DB.
        source = self.gh.request("GET", f"/repos/{fork}/git/commits/{self.source_sha}")
        source_tree = source["tree"]["sha"]
        source_listing = self.gh.request("GET", f"/repos/{fork}/git/trees/{source_tree}?recursive=1")
        source_removals = self._ancillary_paths(source_listing)
        common = ensure_dispatch(self.original)
        log_progress("WORKFLOW", f"Common dispatch harness validated for {self.workflow_path}")
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
                log_progress("WORKFLOW", "Temporarily disabling fork Actions before harness-registration push")
                self.gh.request("PUT", f"/repos/{fork}/actions/permissions", {"enabled": False})
                state["actions_disabled_for_setup"] = True
                save()
            default_tree = self._new_tree(fork, current["commit"]["tree"]["sha"], common,
                                          remove_workflows=default_removals)
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
        prepared_tree = self._new_tree(fork, source_tree, common,
                                       remove_workflows=source_removals)
        prepared = self._commit(fork, prepared_tree, self.source_sha, "common-dispatch-harness")
        state.update(prepared_commit=prepared, prepared_tree=prepared_tree,
                     default_branch=default, default_branch_commit=registration,
                     harness_sha256=digest(common), original_sha256=digest(self.original),
                     common_workflow=base64.b64encode(common).decode("ascii"), arms={},
                     isolated_workflows={"default": default_removals, "source": source_removals})
        save()
        log_progress("WORKFLOW", "Enabling GitHub Actions for the research fork")
        self.gh.request("PUT", f"/repos/{fork}/actions/permissions", {"enabled": True})
        state["actions_disabled_for_setup"] = False
        save()
        self._wait_for_workflow(state, save)

    def _wait_for_workflow(self, state: dict, save) -> None:
        """Wait for workflow indexing; enable disabled fork workflows safely.

        Repository-wide Actions permissions and the individual workflow's
        active/disabled state are independent GitHub settings. Enabling a
        workflow with PUT is idempotent and does NOT dispatch a CI run.
        """
        fork = state["fork_repo"]
        name = Path(self.workflow_path).name
        enabled_this_cycle = False
        last_state = None
        log_progress("WORKFLOW", f"Checking registration and state of {fork}/{name}")
        for attempt in range(1, 25):
            try:
                workflow = self.gh.request("GET", f"/repos/{fork}/actions/workflows/{name}")
                workflow_id = workflow.get("id")
                current = workflow.get("state")
                if type(workflow_id) is not int or workflow_id <= 0:
                    raise ValueError("GitHub workflow registration has no numeric workflow ID")
                if state.get("workflow_id") is not None and state["workflow_id"] != workflow_id:
                    raise ValueError("Registered workflow ID changed; refusing unsafe reuse")
                if current != last_state or attempt % 5 == 0:
                    log_progress("WORKFLOW", f"{name}: state={current}, id={workflow_id}, poll={attempt}/24")
                last_state = current
                if current == "active":
                    if state.get("workflow_id") != workflow_id:
                        state["workflow_id"] = workflow_id
                        save()
                    log_progress("WORKFLOW", f"Workflow active: {name} (id={workflow_id})")
                    return
                if current in {"disabled_manually", "disabled_inactivity", "disabled_fork"}:
                    if not enabled_this_cycle:
                        log_progress("WORKFLOW", f"Enabling disabled fork workflow {name} (state={current})")
                        self.gh.request("PUT", f"/repos/{fork}/actions/workflows/{workflow_id}/enable")
                        enabled_this_cycle = True
                        log_progress("WORKFLOW", "Enable request accepted; waiting for active state")
                elif current not in {"queued", "requested"}:
                    # Do not automatically enable a deleted or unknown workflow.
                    raise ValueError(f"Unexpected GitHub workflow state: {current!r}")
            except GitHubError as exc:
                if exc.code != 404:
                    raise
                if attempt == 1 or attempt % 5 == 0:
                    log_progress("WORKFLOW", f"Registration not visible yet (HTTP 404, poll={attempt}/24)")
            time.sleep(5)
        raise RunPending(f"GitHub workflow {name} not active after registration polls; retry observation")

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
            log_progress("ARM", f"Verifying existing {arm_name(arm)} branch {result['branch']}")
            if result["workflow_sha256"] != digest(rendered):
                raise ValueError("Experimental candidate bytes changed")
            remote = self._ref(fork, result["branch"])
            if remote is None:
                # A saved branch intent may precede an interrupted POST.
                self.gh.request("POST", f"/repos/{fork}/git/refs", {
                    "ref": "refs/heads/" + result["branch"], "sha": result["sha"]})
            elif remote != result["sha"]:
                pending = state.get("pending") or {}
                arm_has_runs = any(record.get("arm") == arm
                                   for record in state.get("records", []))
                if arm_has_runs or pending.get("arm") == arm:
                    raise ValueError("Experimental arm reference changed after a CI trial")
                # A reused fork may contain a stale branch from an earlier
                # interrupted attempt. Preserve it and move this untouched arm
                # to a fresh branch tied to the expected commit.
                result["branch"] = self._available_arm_branch(fork, arm, result["sha"])
                save()
                log_progress("ARM", f"Existing {arm_name(arm)} branch differed; preserving it and using {result['branch']}")
                replacement_ref = self._ref(fork, result["branch"])
                if replacement_ref is None:
                    self.gh.request("POST", f"/repos/{fork}/git/refs", {
                        "ref": "refs/heads/" + result["branch"], "sha": result["sha"]})
                elif replacement_ref != result["sha"]:
                    raise ValueError("Fresh experiment arm reference was modified unexpectedly")
            self._verify_arm_tree(fork, state["prepared_tree"], result)
            return result
        log_progress("ARM", f"Creating {arm_name(arm)} on isolated pinned-source branch")
        tree = state["prepared_tree"] if arm == "A" else self._new_tree(fork, state["prepared_tree"], rendered)
        commit = state["prepared_commit"] if arm == "A" else self._commit(fork, tree, state["prepared_commit"], arm)
        branch = self._available_arm_branch(fork, arm, commit)
        # Save exact commit BEFORE remote branch creation to survive timeouts.
        result = {"sha": commit, "tree": tree, "branch": branch, "workflow_sha256": digest(rendered)}
        state["arms"][arm] = result
        save()
        remote = self._ref(fork, branch)
        if remote is None:
            self.gh.request("POST", f"/repos/{fork}/git/refs", {
                "ref": "refs/heads/" + branch, "sha": commit})
        elif remote != commit:
            raise ValueError("Unable to reserve an uncontested experiment arm branch")
        self._verify_arm_tree(fork, state["prepared_tree"], result)
        log_progress("ARM", f"{arm_name(arm)} prepared and verified: {branch}")
        return result

    def _available_arm_branch(self, fork: str, arm: str, commit: str) -> str:
        """Choose a free deterministic branch without overwriting fork refs."""
        base = f"{self.prefix}-{arm.lower()}"
        suffix = commit[:10]
        candidate = base
        attempt = 1
        while True:
            remote = self._ref(fork, candidate)
            if remote is None or remote == commit:
                return candidate
            candidate = f"{base}-{suffix}" if attempt == 1 else f"{base}-{suffix}-{attempt}"
            attempt += 1

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
            log_progress("CI", f"Resuming existing run {pending['run_id']} without redispatch")
            return pending["run_id"]
        arm = state["arms"][pending["arm"]]
        attempt = 0
        while True:
            attempt += 1
            if attempt == 1 or attempt % 4 == 0:
                log_progress("CI", f"Reconciling dispatch for {arm_name(pending['arm'])}, repeat {pending['repeat']} (poll={attempt})")
            matches = [row for row in self._run_ids(fork, state["workflow_id"], arm["branch"])
                       if (row["id"] not in pending["old_ids"] and row.get("head_sha") == arm["sha"]
                           and row.get("event") == "workflow_dispatch")]
            if len(matches) > 1:
                raise RuntimeError("Ambiguous dispatch: multiple matching runs; manual reconciliation required")
            if matches:
                pending["run_id"] = matches[0]["id"]
                save()
                log_progress("CI", f"Found run {pending['run_id']}: https://github.com/{fork}/actions/runs/{pending['run_id']}")
                return pending["run_id"]

            # Preserve bounded polling for test callers that explicitly
            # configure a maximum wait.
            if (self.max_wait_seconds is not None and
                    attempt >= max(1, self.max_wait_seconds // self.poll_seconds)):
                raise RunPending(
                    "Dispatch identity not resolved yet; "
                    "retry observation without sending another POST"
                )

            # An undiscoverable dispatch is different from a confirmed
            # queued GitHub run. Stop after roughly 10 minutes if GitHub
            # never reveals its run ID. Preserve the pending checkpoint.
            if (self.max_wait_seconds is None and
                    attempt * self.poll_seconds >= 600):
                raise RuntimeError(
                    "GitHub dispatch not discoverable after 10 minutes; "
                    "pending dispatch retained for investigation"
                )

            time.sleep(self.poll_seconds)

    def execute(self, state: dict, save, *, arm: str, repeat: int,
                required: list[str], max_total: int) -> dict:
        # Pending must be collected before ANY new run; this covers ambiguous
        # POST outcomes, queue timeout and controller reruns.
        if state.get("pending"):
            p = state["pending"]
            log_progress("CI", f"Pending dispatch: {arm_name(p['arm'])}, repeat {p['repeat']}, run_id={p.get('run_id')}")
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
            log_progress("CI", f"Dispatching {arm_name(arm)}, repeat {repeat}, branch={run_arm['branch']}")
            response = self.gh.request("POST", f"/repos/{fork}/actions/workflows/{state['workflow_id']}/dispatches", {
                "ref": run_arm["branch"], "inputs": {}, "return_run_details": True})
            if response and response.get("workflow_run_id"):
                state["pending"]["run_id"] = response["workflow_run_id"]
                save()
                log_progress("CI", f"Dispatch accepted: https://github.com/{fork}/actions/runs/{response['workflow_run_id']}")
        run_id = self._pending_run(state, save)
        fork = state["fork_repo"]
        started = time.monotonic()
        last_run_status = None
        while True:
            run = self.gh.request("GET", f"/repos/{fork}/actions/runs/{run_id}")
            status = run.get("status", "unknown")

            # Only recognized GitHub Actions states may be polled.
            # Unknown states must not cause indefinite waiting.
            valid_statuses = {
                "queued",
                "in_progress",
                "waiting",
                "pending",
                "requested",
                "completed",
            }

            if status not in valid_statuses:
                raise ValueError(
                    f"Unexpected GitHub Actions run status {status!r} "
                    f"for run {run_id}; pending dispatch preserved"
                )

            if status != last_run_status or last_run_status is None:
                log_progress("CI", f"Run {run_id} state={status} ({arm_name(arm)}, repeat {repeat})")
                last_run_status = status
            else:
                log_progress("CI", f"Run {run_id} ({arm_name(arm)}) still {status}; checking again in {self.poll_seconds}s")
            if status == "completed":
                log_progress("CI", f"Run {run_id} ({arm_name(arm)}) completed with conclusion={run.get('conclusion')}")
                break
            if status == "queued":
                queued_since = run.get("created_at") or state["pending"].get("sent_at")
                queued_at = dt.datetime.fromisoformat(queued_since.replace("Z", "+00:00"))
                if queued_at.tzinfo is None:
                    queued_at = queued_at.replace(tzinfo=dt.timezone.utc)
                queued_seconds = max(0.0, (dt.datetime.now(dt.timezone.utc) - queued_at).total_seconds())
                if queued_seconds >= QUEUE_TIMEOUT_SECONDS:
                    cancel_status = "CANCEL_REQUESTED"
                    try:
                        self.gh.request("POST", f"/repos/{fork}/actions/runs/{run_id}/cancel")
                    except (GitHubError, RuntimeError) as exc:
                        cancel_status = "CANCEL_UNCONFIRMED:" + type(exc).__name__
                    arm_ref = state["arms"][arm]
                    evidence_ref = None
                    if self.evidence_root:
                        evidence_ref = f"runs/{run_id}/queue-timeout"
                        write_json_immutable(self.evidence_root / evidence_ref / "run.json", run)
                    outcome = {
                        "arm": arm, "repeat": repeat, "run_id": run_id,
                        "run_attempt": run.get("run_attempt", 1),
                        "source_commit_sha": self.source_sha,
                        "config_commit_sha": arm_ref["sha"],
                        "workflow_sha256": arm_ref["workflow_sha256"],
                        "conclusion": "queue_timeout", "protocol_valid": False,
                        "required_checks_pass": False,
                        "workflow_elapsed_seconds": None,
                        "sum_job_runtime_seconds": None,
                        "workflow_makespan_seconds": None,
                        "inter_job_idle_seconds": None,
                        "initial_queue_seconds": queued_seconds,
                        "failure_class": "QUEUE_TIMEOUT",
                        "queue_timeout_seconds": QUEUE_TIMEOUT_SECONDS,
                        "cancel_status": cancel_status,
                        "first_job_started_at": None, "last_job_completed_at": None,
                        "run_created_at": run.get("created_at"),
                        "github_run_started_at": run.get("run_started_at"),
                        "jobs": [], "raw_evidence_ref": evidence_ref, "comparable": False,
                    }
                    state.setdefault("records", []).append(outcome)
                    state["pending"] = None
                    state["queue_timeout"] = {"run_id": run_id, "arm": arm,
                                               "repeat": repeat,
                                               "cancel_status": cancel_status}
                    save()
                    log_progress("CI", f"Run {run_id} remained queued for {int(queued_seconds)}s; "
                                          f"cancel={cancel_status}; skipping this repository")
                    raise RunQueueTimeout(
                        f"GitHub run {run_id} stayed queued for at least "
                        f"{QUEUE_TIMEOUT_SECONDS}s; repository skipped")
            if status == "in_progress":
                in_progress_since = run.get("run_started_at") or state["pending"].get("in_progress_since")
                if not in_progress_since:
                    in_progress_since = dt.datetime.now(dt.timezone.utc).isoformat()
                    state["pending"]["in_progress_since"] = in_progress_since
                    save()
                in_progress_at = dt.datetime.fromisoformat(in_progress_since.replace("Z", "+00:00"))
                if in_progress_at.tzinfo is None:
                    in_progress_at = in_progress_at.replace(tzinfo=dt.timezone.utc)
                in_progress_seconds = max(
                    0.0, (dt.datetime.now(dt.timezone.utc) - in_progress_at).total_seconds())
                if in_progress_seconds >= IN_PROGRESS_TIMEOUT_SECONDS:
                    cancel_status = "CANCEL_REQUESTED"
                    try:
                        self.gh.request("POST", f"/repos/{fork}/actions/runs/{run_id}/cancel")
                    except (GitHubError, RuntimeError) as exc:
                        cancel_status = "CANCEL_UNCONFIRMED:" + type(exc).__name__
                    arm_ref = state["arms"][arm]
                    evidence_ref = None
                    if self.evidence_root:
                        evidence_ref = f"runs/{run_id}/in-progress-timeout"
                        write_json_immutable(self.evidence_root / evidence_ref / "run.json", run)
                    outcome = {
                        "arm": arm, "repeat": repeat, "run_id": run_id,
                        "run_attempt": run.get("run_attempt", 1),
                        "source_commit_sha": self.source_sha,
                        "config_commit_sha": arm_ref["sha"],
                        "workflow_sha256": arm_ref["workflow_sha256"],
                        "conclusion": "in_progress_timeout", "protocol_valid": False,
                        "required_checks_pass": False,
                        "workflow_elapsed_seconds": None,
                        "sum_job_runtime_seconds": None,
                        "workflow_makespan_seconds": None,
                        "inter_job_idle_seconds": None,
                        "initial_queue_seconds": None,
                        "in_progress_seconds": in_progress_seconds,
                        "in_progress_timeout_seconds": IN_PROGRESS_TIMEOUT_SECONDS,
                        "failure_class": "IN_PROGRESS_TIMEOUT",
                        "cancel_status": cancel_status,
                        "first_job_started_at": None, "last_job_completed_at": None,
                        "run_created_at": run.get("created_at"),
                        "github_run_started_at": run.get("run_started_at"),
                        "jobs": [], "raw_evidence_ref": evidence_ref, "comparable": False,
                    }
                    state.setdefault("records", []).append(outcome)
                    state["pending"] = None
                    state["in_progress_timeout"] = {
                        "run_id": run_id, "arm": arm, "repeat": repeat,
                        "cancel_status": cancel_status}
                    save()
                    log_progress("CI", f"Run {run_id} stayed in progress for "
                                          f"{int(in_progress_seconds)}s; cancel={cancel_status}; "
                                          "skipping this repository")
                    raise RunExecutionTimeout(
                        f"GitHub run {run_id} stayed in progress for at least "
                        f"{IN_PROGRESS_TIMEOUT_SECONDS}s; repository skipped")
            if (self.max_wait_seconds is not None and
                    time.monotonic() - started > self.max_wait_seconds):
                raise RunPending(f"GitHub run {run_id} is queued/in progress; resume observation later")
            time.sleep(self.poll_seconds)
        attempt = run.get("run_attempt", 1)
        log_progress("EVIDENCE", f"Fetching {arm_name(arm)} run {run_id}, attempt {attempt}, jobs and measurements")
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
        log_progress("EVIDENCE", f"{arm_name(arm)}, repeat {repeat}: comparable={outcome['comparable']}, active={elapsed}s, runner={total}s, initial_queue={initial_queue}s; archived")
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
            log_progress("CLEANUP", "No fork created; cleanup not required")
            return "NOT_CREATED"
        if state.get("fork_reused_existing"):
            state["cleanup_status"] = "REUSED_EXISTING_PRESERVED"
            save()
            log_progress("CLEANUP", f"Preserving reused fork: https://github.com/{state['fork_repo']}")
            return "REUSED_EXISTING_PRESERVED"
        if state.get("cleanup_status") == "DELETED":
            return "DELETED"
        if state.get("cleanup_status") == "RETAINED_BY_CONFIGURATION":
            # Resuming with a different environment must never silently
            # destroy the fork evidence retained for supervisor review.
            return "RETAINED_BY_CONFIGURATION"
        fork_name = state["fork_repo"]
        expected = state.get("fork_creation_intent")
        owner = state.get("fork_owner", "")
        if (not state.get("fork_created_by_evaluation") or not owner or
                expected != fork_name or not fork_name.startswith(owner + "/")):
            state["cleanup_status"] = "PRESERVED_NOT_OWNED"
            save()
            return "PRESERVED_NOT_OWNED"
        if type(state.get("fork_id")) is not int or state["fork_id"] <= 0:
            # Older/partial state has no immutable fork identity. Refuse DELETE.
            state["cleanup_status"] = "PRESERVED_UNVERIFIED_ID"
            save()
            return "PRESERVED_UNVERIFIED_ID"

        if not automatic_fork_deletion_enabled() and not state.get("cleanup_intent"):
            # Owned and identity-pinned fork: persist the retention decision
            # before any cleanup API request or destructive DELETE intent.
            state["cleanup_status"] = "RETAINED_BY_CONFIGURATION"
            save()
            log_progress("CLEANUP", f"Fork retained by configuration: https://github.com/{fork_name}")
            return "RETAINED_BY_CONFIGURATION"

        try:
            fork = self.gh.request("GET", "/repos/" + fork_name)
        except GitHubError as exc:
            if exc.code == 404 and state.get("cleanup_intent") == fork_name:
                state["cleanup_status"] = "DELETED"
                save()
                return "DELETED"
            raise
        verify_fork(fork, self.upstream, owner, expected_id=state["fork_id"])
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
            log_progress("CLEANUP", f"Deleting verified evaluation-owned fork: {fork_name}")
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
        # GitHub accepting DELETE does not prove the fork is already gone.
        # Confirm 404; never mistake a delayed or uncertain response for deletion.
        for attempt in range(3):
            try:
                self.gh.request("GET", "/repos/" + fork_name)
            except GitHubError as exc:
                if exc.code == 404:
                    state["cleanup_status"] = "DELETED"
                    save()
                    return "DELETED"
                state["cleanup_status"] = (
                    "BLOCKED_PERMISSION" if exc.code in {401, 403} else "DELETE_OUTCOME_UNKNOWN")
                save()
                return state["cleanup_status"]
            except RuntimeError:
                state["cleanup_status"] = "DELETE_OUTCOME_UNKNOWN"
                save()
                return "DELETE_OUTCOME_UNKNOWN"
            if attempt < 2:
                time.sleep(2)
        # Keep the immutable cleanup intent; a later resume may confirm 404
        # but cannot issue a second DELETE against a different repository.
        state["cleanup_status"] = "DELETE_OUTCOME_UNKNOWN"
        save()
        return "DELETE_OUTCOME_UNKNOWN"


def summarize_records(records: list[dict], *, repetitions: int | None = None) -> dict:
    """Compute only actual comparable GitHub-hosted measurements.

    Incomplete repetition sets have no effect-size estimate. No queue time
    enters the elapsed or summed-runner timing measurements.
    """
    by_arm = {arm: [r for r in records if r["arm"] == arm] for arm in "ABC"}
    results = {}
    for arm, runs in by_arm.items():
        valid = [r for r in runs if r["comparable"]]
        complete = bool(valid) and (repetitions is None or
                                    (len(runs) == repetitions and len(valid) == repetitions))
        results[arm] = {"attempted": len(runs), "comparable": len(valid),
                        "failed": len(runs) - len(valid), "complete": complete,
                        "median_elapsed_seconds": median(r["workflow_elapsed_seconds"] for r in valid) if complete else None,
                        "median_runner_seconds": median(r["sum_job_runtime_seconds"] for r in valid) if complete else None,
                        }
    for target, baseline_arm in (("B", "A"), ("C", "A"), ("C", "B")):
        suffix = ("vs_A" if baseline_arm == "A" else "vs_B")
        for kind in ("elapsed", "runner"):
            baseline = results[baseline_arm][f"median_{kind}_seconds"]
            optimized = results[target][f"median_{kind}_seconds"]
            results[target][f"{kind}_saving_percent_{suffix}"] = (
                100 * (baseline - optimized) / baseline
                if baseline is not None and optimized is not None and baseline > 0 else None)
    return results
