"""Collect historical workflow versions and their existing GitHub Actions runs."""
from __future__ import annotations

import base64
import statistics
import urllib.parse
from pathlib import Path


MAX_HISTORY_COMMITS = 500


def cache_evidence(document):
    """Return evidence for common GitHub Actions dependency-cache mechanisms."""
    evidence = []
    jobs = document.get("jobs", {}) if isinstance(document, dict) else {}
    for job_id, job in jobs.items():
        for index, step in enumerate(job.get("steps", []) if isinstance(job, dict) else []):
            action = str(step.get("uses", "")).lower().split("@", 1)[0]
            inputs = step.get("with", {}) if isinstance(step.get("with", {}), dict) else {}
            if action in {"actions/cache", "actions/cache/restore", "actions/cache/save"}:
                evidence.append({"job_id": job_id, "step_index": index, "kind": "actions/cache", "uses": step.get("uses")})
            elif action in {"actions/setup-node", "actions/setup-python", "actions/setup-go", "actions/setup-java"}:
                if inputs.get("cache"):
                    evidence.append({"job_id": job_id, "step_index": index, "kind": "setup-action-cache", "uses": step.get("uses"), "cache": inputs.get("cache")})
            elif action == "ruby/setup-ruby" and inputs.get("bundler-cache"):
                evidence.append({"job_id": job_id, "step_index": index, "kind": "bundler-cache", "uses": step.get("uses")})
    return evidence


def pattern_evidence(pattern_id, document):
    # Add new IDs only with explicit, reviewable detectors; never guess from prose.
    if pattern_id == "P-LIT-GHA-CACHE":
        return cache_evidence(document)
    return None


def _content(github, repo, path, ref, cache, runner):
    key = (repo.lower(), path, ref)
    if key in cache:
        return cache[key]
    encoded_path = urllib.parse.quote(path, safe="/")
    encoded_ref = urllib.parse.quote(ref, safe="")
    response = github.request("GET", f"/repos/{repo}/contents/{encoded_path}?ref={encoded_ref}")
    if response.get("encoding") != "base64" or not response.get("content"):
        raise ValueError(f"GitHub did not return a base64 workflow for {path} at {ref}")
    raw = base64.b64decode(response["content"])
    runner.workflow_doc(raw)
    cache[key] = raw
    return raw


def _runs_for_commit(github, repo, workflow_id, workflow_path, commit_sha, output, runner):
    query = urllib.parse.urlencode({"head_sha": commit_sha})
    endpoint = f"/repos/{repo}/actions/workflows/{workflow_id}/runs?{query}"
    try:
        runs = github.pages(endpoint, "workflow_runs")
    except RuntimeError as exc:
        # Historical Actions records can expire or be inaccessible. Preserve that fact.
        return {"status": "unavailable", "reason": str(exc), "runs": []}

    records = []
    for run in runs:
        if run.get("head_sha") != commit_sha:
            continue
        attempt = int(run.get("run_attempt", 1))
        jobs_endpoint = f"/repos/{repo}/actions/runs/{run['id']}/attempts/{attempt}/jobs"
        try:
            jobs = github.pages(jobs_endpoint, "jobs")
        except RuntimeError as exc:
            records.append({"run": run, "attempt": attempt, "status": "jobs_unavailable", "reason": str(exc)})
            continue
        details = runner.metrics(run, jobs, [])
        # Historical runs have no owner-approved required-check contract in this dataset.
        details["required_checks_pass"] = None
        details["required_checks_assessed"] = False
        folder = output / ("runs_" + commit_sha[:12]) / f"{run['id']}-attempt-{attempt}"
        runner.write_json(folder / "run.json", run)
        runner.write_json(folder / "jobs.json", jobs)
        runner.write_json(folder / "metrics.json", details)
        records.append({"run_id": run["id"], "attempt": attempt, "status": run.get("status"),
                        "conclusion": run.get("conclusion"), "workflow_path": workflow_path,
                        "workflow_elapsed_seconds": details["workflow_elapsed_seconds"],
                        "sum_job_runtime_seconds": details["sum_job_runtime_seconds"],
                        "raw_dir": str(folder.relative_to(runner.ROOT))})
    usable = [row for row in records if row.get("workflow_elapsed_seconds") is not None]
    return {"status": "collected" if records else "no_runs_found", "run_count": len(records), "runs": records,
            "median_workflow_elapsed_seconds": statistics.median(
                row["workflow_elapsed_seconds"] for row in usable) if usable else None,
            "median_sum_job_runtime_seconds": statistics.median(
                row["sum_job_runtime_seconds"] for row in usable if row.get("sum_job_runtime_seconds") is not None)
                if any(row.get("sum_job_runtime_seconds") is not None for row in usable) else None}


def collect(github, source_repo, workflow_path, pattern_id, directory, runner):
    """Save the nearest historical absent->present transition and source run metrics."""
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "manifest.json"
    if manifest_path.exists():
        return runner.read_json(manifest_path)

    base = {"record_kind": "historical_ci_pattern_transition", "source_repo": source_repo,
            "workflow_path": workflow_path, "pattern_id": pattern_id,
            "detection_method": "deterministic pattern-specific workflow inspection; no LLM"}
    detector_supported = pattern_id == "P-LIT-GHA-CACHE"
    if not detector_supported:
        result = {**base, "status": "detector_not_implemented", "reason": "No deterministic detector is registered for this pattern ID."}
        runner.write_json(manifest_path, result)
        return result

    try:
        commits = []
        last_page_size = 0
        for page in range(1, MAX_HISTORY_COMMITS // 100 + 1):
            query = urllib.parse.urlencode({"path": workflow_path, "per_page": 100, "page": page})
            batch = github.request("GET", f"/repos/{source_repo}/commits?{query}")
            last_page_size = len(batch)
            commits.extend(batch)
            if last_page_size < 100:
                break
    except RuntimeError as exc:
        result = {**base, "status": "history_unavailable", "reason": str(exc)}
        runner.write_json(manifest_path, result)
        return result

    content_cache = {}
    transition = None
    scanned = 0
    truncated = len(commits) == MAX_HISTORY_COMMITS and last_page_size == 100
    for item in commits[:MAX_HISTORY_COMMITS]:
        commit_sha = item.get("sha")
        if not commit_sha:
            continue
        scanned += 1
        try:
            after_bytes = _content(github, source_repo, workflow_path, commit_sha, content_cache, runner)
            after_evidence = pattern_evidence(pattern_id, runner.workflow_doc(after_bytes))
            if not after_evidence:
                continue
            parent_sha = (item.get("parents") or [{}])[0].get("sha")
            before_bytes = None
            if parent_sha:
                try:
                    before_bytes = _content(github, source_repo, workflow_path, parent_sha, content_cache, runner)
                except RuntimeError as exc:
                    if "HTTP 404" not in str(exc):
                        raise
            before_evidence = pattern_evidence(pattern_id, runner.workflow_doc(before_bytes)) if before_bytes else []
            if not before_evidence:
                transition = {"before_sha": parent_sha, "after_sha": commit_sha,
                              "before_bytes": before_bytes, "after_bytes": after_bytes,
                              "before_evidence": before_evidence, "after_evidence": after_evidence,
                              "commit": item}
                break
        except RuntimeError as exc:
            # A missing version is expected for workflow creation/deletion commits.
            if "HTTP 404" not in str(exc):
                result = {**base, "status": "history_scan_error", "reason": str(exc), "commits_scanned": scanned}
                runner.write_json(manifest_path, result)
                return result
        except (ValueError, UnicodeDecodeError):
            continue

    if not transition:
        status = "scan_limit_reached" if truncated else "transition_not_found"
        reason = (f"No transition found in the newest {MAX_HISTORY_COMMITS} workflow commits; history is incomplete."
                  if truncated else "No absent-to-present transition for this pattern was found in workflow history.")
        result = {**base, "status": status, "reason": reason, "commits_scanned": scanned,
                  "commits_available": len(commits), "history_complete_for_scan": not truncated}
        runner.write_json(manifest_path, result)
        return result

    before_path, after_path = directory / "before.yml", directory / "after.yml"
    before_path.write_bytes(transition["before_bytes"] or b"")
    after_path.write_bytes(transition["after_bytes"])
    diff = runner.workflow_diff(transition["before_bytes"] or b"", transition["after_bytes"], workflow_path)
    (directory / "change.diff").write_text(diff, encoding="utf-8", newline="")

    try:
        workflow = github.request("GET", f"/repos/{source_repo}/actions/workflows/{urllib.parse.quote(Path(workflow_path).name, safe='')}")
        workflow_id = workflow["id"]
    except (RuntimeError, KeyError, TypeError):
        workflow_id = None
    before_runs = (_runs_for_commit(github, source_repo, workflow_id, workflow_path,
                                    transition["before_sha"], directory, runner)
                   if workflow_id and transition["before_sha"] and transition["before_bytes"] is not None else
                   {"status": "workflow_absent_at_before_commit" if transition["before_bytes"] is None else "unavailable",
                    "reason": "The workflow file did not exist at the parent commit." if transition["before_bytes"] is None else "Workflow ID or parent commit unavailable.",
                    "runs": []})
    after_runs = (_runs_for_commit(github, source_repo, workflow_id, workflow_path,
                                   transition["after_sha"], directory, runner)
                  if workflow_id else {"status": "unavailable", "reason": "Workflow ID unavailable.", "runs": []})
    commit_meta = transition["commit"].get("commit", {})
    result = {**base, "status": "transition_found", "commits_scanned": scanned,
              "workflow_id": workflow_id,
              "before": {"commit_sha": transition["before_sha"], "workflow_present": transition["before_bytes"] is not None,
                         "file": "before.yml",
                         "pattern_evidence": transition["before_evidence"], "runs": before_runs},
              "after": {"commit_sha": transition["after_sha"], "file": "after.yml",
                        "commit_message": commit_meta.get("message"),
                        "commit_date": (commit_meta.get("committer") or {}).get("date"),
                        "pattern_evidence": transition["after_evidence"], "runs": after_runs},
              "diff_file": "change.diff", "history_complete_for_scan": not truncated}
    runner.write_json(manifest_path, result)
    return result
