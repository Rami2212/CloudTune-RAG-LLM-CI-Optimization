"""Run one held-out evaluation repository at a time with restart-safe checkpoints.

Use --member 1..4 with --preflight-only or --run. The local fork controller owns
ALL real trial state; this wrapper never edits its immutable checkpoint, changes
A/B/C safety verdicts, or dispatches GitHub Actions directly.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path

from scripts.experiment_environment import load_env
from evaluation.result_paths import trial_directory
from evaluation.prepare_evaluation_assignments import ROOT, DESTINATION, ROWS_PER_MEMBER, split_dataset

RESULTS = ROOT / "evaluation" / "results"
BASE_CONFIG = ROOT / "evaluation" / "configs" / "fork_pilot.json"
COMPLETED = {"COMPLETE", "SKIPPED", "FAILED_TARGET_CI", "INCONCLUSIVE_PLATFORM", "INCOMPLETE"}
RETAINED_OR_DONE = {"RETAINED_BY_CONFIGURATION", "NOT_CREATED", "NOT_STARTED",
                    "PRESERVED_NOT_OWNED"}
EXPORT_COLUMNS = ("batch_id", "member", "position", "source_position", "repo_id", "evaluation_id", "status",
                  "ci_cost_verdict", "rag_verdict", "admitted_arms", "original_runs", "ci_cost_runs",
                  "rag_runs", "original_comparable", "ci_cost_comparable", "rag_comparable",
                  "fork_cleanup", "github_fork")
RUN_COLUMNS = ("arm", "repeat", "run_id", "run_attempt", "source_commit_sha",
               "config_commit_sha", "workflow_sha256", "conclusion", "protocol_valid",
               "required_checks_pass", "comparable", "workflow_elapsed_seconds",
               "sum_job_runtime_seconds", "workflow_makespan_seconds", "inter_job_idle_seconds",
               "initial_queue_seconds", "failure_class", "run_created_at",
               "github_run_started_at", "first_job_started_at", "last_job_completed_at")
JOB_COLUMNS = ("id", "name", "status", "conclusion", "started_at", "completed_at",
               "duration_seconds")


@contextmanager
def exclusive_batch(batch_id: str):
    """Prevent two local processes from publishing or dispatching one batch.

    Follow the existing fork controller's O_EXCL lock convention. An ordinary
    Ctrl+C releases the lock. After a hard process kill, confirm there is no
    active worker before removing the stale lock; never delete checkpoint data.
    """
    folder = RESULTS / batch_id
    folder.mkdir(parents=True, exist_ok=True)
    lock = folder / ".batch.lock"
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise RuntimeError(f"Batch already active or has a stale lock: {lock}") from None
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()) + "\n")
        yield
    finally:
        lock.unlink(missing_ok=True)


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_json(path: Path, document: dict) -> None:
    """Publish derived summaries atomically; never write a controller checkpoint."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _atomic_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=EXPORT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def default_batch_id(member: int) -> str:
    """Unique, readable default ID per contributor; explicit IDs are supported."""
    return f"eval-member-{member:02d}"


def validated_batch_id(member: int, selected: str | None) -> str:
    """A batch ID owns one member's published results and 1,000 trials.

    Reserve six characters for the per-repository suffix (`-r0001`) so the
    existing fork controller's maximum 64-character evaluation ID is obeyed.
    """
    value = default_batch_id(member) if selected is None else selected
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,57}", value):
        raise ValueError("--batch-id must be 1-58 letters, digits, underscores or hyphens")
    if re.fullmatch(r".+-r[0-9]{4}", value):
        raise ValueError("--batch-id cannot end in a repository trial suffix (-rNNNN)")
    if value == "cohort":
        raise ValueError("'cohort' is reserved for merged results")
    return value


def _trial_id(batch_id: str, position: int) -> str:
    base = f"{batch_id}-r{position:04d}"
    generation = _read_json(RESULTS / batch_id / "rerun_state.json").get("generations", {}).get(str(position), 1)
    return base if generation == 1 else f"{base}-r{generation}"


def _assignment(member: int) -> list[dict[str, str]]:
    # Detect replaced/misassigned source data before generating a live evaluation.
    manifest = split_dataset(root=ROOT)
    entry = manifest["assignments"][member - 1]
    path = ROOT / entry["file"]
    if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
        raise ValueError("Assignment integrity mismatch")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 1000 or any(row["split"] != "evaluation" for row in rows):
        raise ValueError("Member assignment must contain exactly 1000 held-out repositories")
    return rows


def _record(batch_id: str, position: int, repo_id: str) -> tuple[dict, dict, dict]:
    trial = trial_directory(RESULTS, _trial_id(batch_id, position))
    state = _read_json(trial / "state.json")
    report = _read_json(trial / "fork_report.json")
    repo_state = state.get("repositories", {}).get(repo_id, {})
    repo_report = report.get("repositories", {}).get(repo_id, {})
    return state, repo_state, repo_report


def _terminal(repo_state: dict, repo_report: dict) -> bool:
    if repo_state.get("pending"):
        return False
    status = repo_report.get("status") or repo_state.get("status", "NOT_STARTED")
    if status == "PREFLIGHT_BLOCKED":
        return not repo_state.get("fork_repo")
    if status == "SKIPPED":
        return True
    if not repo_state.get("measurements_finalized") or status not in COMPLETED:
        return False
    cleanup = repo_state.get("cleanup_status", "NOT_STARTED")
    return not repo_state.get("fork_repo") or cleanup in RETAINED_OR_DONE | {"DELETED"}


def _stage(repo_state: dict, repo_report: dict) -> str:
    """Derive recovery from the controller's durable state, not a batch cursor."""
    if _terminal(repo_state, repo_report):
        return "finished"
    if repo_state.get("fork_repo") or repo_state.get("pending") or repo_state.get("records"):
        return "hosted"
    if repo_state.get("status") == "PREFLIGHT_READY":
        return "ready"
    return "preflight"


def _batch_identity_record(member: int, batch_id: str, batch_name: str | None = None) -> dict:
    assignment = DESTINATION / f"member_{member:02d}.csv"
    record = {
        "schema": 2,
        "batch_id": batch_id,
        "batch_name": batch_name or batch_id,
        "member": member,
        "assignment_sha256": hashlib.sha256((ROOT / assignment).read_bytes()).hexdigest(),
        "config_template_sha256": hashlib.sha256(BASE_CONFIG.read_bytes()).hexdigest(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "openrouter_model": os.environ.get("OPENROUTER_MODEL", "").strip(),
        "openrouter_max_tokens": os.environ.get("OPENROUTER_MAX_TOKENS", "").strip(),
        "auto_delete_forks": os.environ.get("CLOUDTUNE_AUTO_DELETE_FORKS", "").strip().lower(),
    }
    if not record["openrouter_model"].endswith(":free") or not record["openrouter_max_tokens"]:
        raise ValueError("Set a :free OPENROUTER_MODEL and OPENROUTER_MAX_TOKENS before running")
    return record


def _identity_fields(record: dict) -> dict:
    return {key: value for key, value in record.items()
            if key not in {"schema", "batch_name", "revision", "change_history", "last_change_fields"}}


def freeze_batch(member: int, batch_id: str, *, rerun_failed: bool = False,
                 allow_config_changes: bool = False, batch_name: str | None = None) -> Path:
    """Freeze batch settings, or explicitly append a recorded config revision."""
    if batch_name is not None:
        batch_name = batch_name.strip()
        if not batch_name or len(batch_name) > 120:
            raise ValueError("--batch-name must contain 1-120 non-space characters")
    record = _batch_identity_record(member, batch_id, batch_name)
    location = RESULTS / batch_id / "batch_identity.json"
    location.parent.mkdir(parents=True, exist_ok=True)
    if location.is_file():
        previous = _read_json(location)
        if batch_name is None:
            record["batch_name"] = previous.get("batch_name", batch_id)
        comparable = _identity_fields(record)
        old_comparable = _identity_fields(previous)
        if rerun_failed:
            comparable.pop("runner_sha256", None)
            old_comparable.pop("runner_sha256", None)
        immutable = {"batch_id", "member", "assignment_sha256"}
        changed_immutable = sorted(
            key for key in immutable if old_comparable.get(key) != comparable.get(key))
        if changed_immutable:
            raise ValueError(
                "Batch identity cannot change member, batch ID, or assignment: "
                + ", ".join(changed_immutable))
        if old_comparable != comparable and not allow_config_changes:
            raise ValueError(f"Frozen batch identity changed: {location}; use the original settings")
        if old_comparable != comparable:
            history = list(previous.get("change_history", []))
            history.append({"changed_at_utc": datetime.now(timezone.utc).isoformat(),
                            "from": old_comparable, "to": comparable})
            record["revision"] = int(previous.get("revision", 1)) + 1
            record["change_history"] = history
            record["last_change_fields"] = sorted(
                key for key in set(old_comparable) | set(comparable)
                if old_comparable.get(key) != comparable.get(key))
            _atomic_json(location, record)
        else:
            # Keep a stable revision marker in schema-1 batches upgraded in place.
            record["revision"] = int(previous.get("revision", 1))
            record["change_history"] = previous.get("change_history", [])
            record["last_change_fields"] = previous.get("last_change_fields", [])
            if (previous.get("schema") != 2 or
                    previous.get("batch_name", batch_id) != record["batch_name"]):
                _atomic_json(location, record)
    else:
        record["revision"] = 1
        record["change_history"] = []
        record["last_change_fields"] = []
        _atomic_json(location, record)
    return location


def _member_config(member: int, batch_id: str, position: int | None = None) -> Path:
    """Write a per-trial config, preserving the config already frozen for it."""
    source = json.loads(BASE_CONFIG.read_text(encoding="utf-8"))
    source["dataset"] = (DESTINATION / f"member_{member:02d}.csv").as_posix()
    source["dataset_split"] = "evaluation"
    source["repository_start_at"] = 1
    source["repository_limit"] = 1
    source["evaluation_id"] = (f"{batch_id}-r0001" if position is None else
                                _trial_id(batch_id, position))
    if source.get("execution", {}).get("development_smoke") is True:
        raise ValueError("Cannot run a held-out partition under development smoke")
    target = (RESULTS / batch_id / "batch_config.json" if position is None else
              RESULTS / batch_id / "configs" / f"{source['evaluation_id']}.json")
    serialized = (json.dumps(source, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_bytes() != serialized:
        if position is None:
            raise ValueError(f"Frozen member configuration has changed: {target}")
        raise ValueError(f"Frozen trial configuration has changed: {target}; use --override-existing")
    if not target.exists():
        target.write_bytes(serialized)
    return target


def _invoke(member: int, position: int, mode: str, batch_id: str) -> int:
    """Give every repository its own immutable ID; retries use that same ID."""
    args = [sys.executable, "-m", "evaluation.fork_pipeline", "--config", str(_member_config(member, batch_id, position)),
            "--batch-id", _trial_id(batch_id, position),
            "--start-at", str(position), "--limit", "1"]
    # The fork controller remains responsible for pending-run reconciliation.
    if mode == "preflight":
        args.append("--preflight")
    elif mode == "hosted":
        args.extend(("--watch", "--require-all-arms"))
    else:
        raise ValueError("Unrecognized trial stage")
    result = subprocess.run(args, cwd=ROOT, check=False).returncode
    if result == 2:
        # The controller refuses deletion without ownership proof, including
        # reused evidence forks. Finalized measurements may still advance the
        # team batch; preserve the cleanup verdict and never grant DELETE rights.
        _, current, report = _record(batch_id, position, _assignment(member)[position - 1]["repo_id"])
        if current.get("cleanup_status") == "PRESERVED_NOT_OWNED" and _terminal(current, report):
            return 0
    return result


def _index_row(member: int, position: int, repo_id: str, batch_id: str) -> tuple[dict, dict | None]:
    state, repo_state, report = _record(batch_id, position, repo_id)
    status = report.get("status") or repo_state.get("status", "NOT_STARTED")
    records = repo_state.get("records", [])
    counted = {arm: [row for row in records if row.get("arm") == arm] for arm in ("A", "B", "C")}
    validation = repo_state.get("validation", {})
    data = {"batch_id": batch_id, "member": member, "position": position,
            "source_position": (member - 1) * 1000 + position, "repo_id": repo_id,
            "evaluation_id": _trial_id(batch_id, position), "status": status,
            "ci_cost_verdict": validation.get("B", {}).get("verdict", ""),
            "rag_verdict": validation.get("C", {}).get("verdict", ""),
            "admitted_arms": ",".join(repo_state.get("admitted_arms", [])),
            "original_runs": len(counted["A"]), "ci_cost_runs": len(counted["B"]),
            "rag_runs": len(counted["C"]),
            "original_comparable": sum(bool(r.get("comparable")) for r in counted["A"]),
            "ci_cost_comparable": sum(bool(r.get("comparable")) for r in counted["B"]),
            "rag_comparable": sum(bool(r.get("comparable")) for r in counted["C"]),
            "fork_cleanup": repo_state.get("cleanup_status", "NOT_STARTED"),
            "github_fork": repo_state.get("fork_repo") or ""}
    if not state:
        return data, None
    manifest = (trial_directory(RESULTS, _trial_id(batch_id, position)) / "repositories")
    candidates = list(manifest.glob("*/manifest.json")) if manifest.exists() else []
    pinned = _read_json(candidates[0]) if len(candidates) == 1 else {}
    frozen_config = _read_json(trial_directory(RESULTS, data["evaluation_id"]) / "config.json")
    # Only explicitly allowlisted research metadata/measurements leave ignored
    # local checkpoints. Never export prompts, source files, API responses or keys.
    summary = {"repo_id": repo_id, "evaluation_id": data["evaluation_id"],
               "status": status, "selected_source_commit": pinned.get("source_commit_sha"),
               "selected_workflow": pinned.get("workflow_path"),
               "source_workflow_sha256": pinned.get("workflow_sha256"),
               "config_sha256": state.get("config_sha256"),
               "implementation_sha256": state.get("implementation_sha256"),
               "openrouter_model": frozen_config.get("rag", {}).get("generator_model"),
               "openrouter_max_tokens": frozen_config.get("rag", {}).get("max_tokens"),
               "rag_dataset_sha256": frozen_config.get("rag", {}).get("dataset_sha256"),
               "ci_cost_revision": frozen_config.get("ci_cost", {}).get("source_fix_revision"),
               "ci_cost": {"decision": repo_state.get("candidates", {}).get("B", {}).get("decision"),
                           "validation": validation.get("B", {}).get("verdict"),
                           "reason_codes": sorted(set(str(v).split(":", 1)[0] for v in
                               validation.get("B", {}).get("reasons", [])))},
               "rag": {"decision": repo_state.get("candidates", {}).get("C", {}).get("decision"),
                       "validation": validation.get("C", {}).get("verdict"),
                       "reason_codes": sorted(set(str(v).split(":", 1)[0] for v in
                               validation.get("C", {}).get("reasons", [])))},
               "github_fork": data["github_fork"],
               "fork_cleanup": data["fork_cleanup"],
               "measurements_finalized": bool(repo_state.get("measurements_finalized")),
               # Public GitHub-hosted job timing is necessary to independently
               # reproduce elapsed/runner metrics without exporting API blobs.
               "run_records": [{**{k: row.get(k) for k in RUN_COLUMNS},
                                "jobs": [{k: job.get(k) for k in JOB_COLUMNS}
                                         for job in row.get("jobs", [])]}
                               for row in records],
               "controller_report_sha256": (hashlib.sha256((trial_directory(RESULTS, data["evaluation_id"]) /
                   "fork_report.json").read_bytes()).hexdigest() if
                   (trial_directory(RESULTS, data["evaluation_id"]) / "fork_report.json").exists() else None)}
    return data, summary


def publish_batch(member: int, rows: list[dict[str, str]], batch_id: str) -> Path:
    """Publish commit-ready allowlisted evidence; ignore active controller state."""
    identity_path = RESULTS / batch_id / "batch_identity.json"
    identity = _read_json(identity_path)
    if identity and (identity.get("member") != member or identity.get("batch_id") != batch_id):
        raise ValueError("Batch folder belongs to another member/identity")
    out = RESULTS / batch_id / "published"
    table = []
    statuses: dict[str, int] = {}
    for index, row in enumerate(rows, 1):
        item, summary = _index_row(member, index, row["repo_id"], batch_id)
        table.append(item)
        statuses[item["status"]] = statuses.get(item["status"], 0) + 1
        if summary is not None:
            _atomic_json(out / "trials" / f"r{index:04d}.json", summary)
    _atomic_csv(out / "attempts.csv", table)
    _atomic_json(out / "manifest.json", {
        "schema": 1, "member": member, "batch_id": batch_id, "rows_assigned": len(rows),
        "assignment_csv": (DESTINATION / f"member_{member:02d}.csv").as_posix(),
        "assignment_sha256": hashlib.sha256((ROOT / DESTINATION /
            f"member_{member:02d}.csv").read_bytes()).hexdigest(),
        "counts": dict(sorted(statuses.items())),
        "source_commit_policy": "each repository records its own immutable upstream commit",
        "evidence_policy": "Allowlisted run metrics only; raw checkpoint and API evidence remain local",
    })
    return out


def failed_positions(source: str, rows: list[dict]) -> list[int]:
    failed = {"PREFLIGHT_BLOCKED", "FAILED_TARGET_CI", "INCOMPLETE", "INCONCLUSIVE_PLATFORM", "LLM_PAUSED", "RAG_PAUSED"}
    positions = []
    for index, row in enumerate(rows, 1):
        _, current, report = _record(source, index, row["repo_id"])
        if (report.get("status") or current.get("status")) in failed:
            if current.get("pending"):
                raise ValueError("Source trial has pending CI; resume it before retrying")
            positions.append(index)
    return positions


def prepare_failed_rerun(batch_id: str, rows: list[dict]) -> dict:
    """Allocate each failed row once per round; restarts resume that round."""
    path = RESULTS / batch_id / "rerun_state.json"
    plan = _read_json(path)
    if plan.get("active"):
        return plan
    positions = failed_positions(batch_id, rows)
    generations = dict(plan.get("generations", {}))
    previous = {}
    for position in positions:
        trial_id = _trial_id(batch_id, position)
        folder = trial_directory(RESULTS, trial_id)
        state, repo, _ = _record(batch_id, position, rows[position - 1]["repo_id"])
        if (folder / ".controller.lock").exists() or repo.get("pending"):
            raise ValueError("Source trial is still active; resume it before rerunning")
        previous[str(position)] = trial_id
        generations[str(position)] = generations.get(str(position), 1) + 1
        if len(f"{batch_id}-r{position:04d}-r{generations[str(position)]}") > 80:
            raise ValueError("Trial generation ID exceeds 80 characters")
    plan = {"round": plan.get("round", 0) + 1, "active": bool(positions),
            "positions": positions, "previous_trials": previous, "generations": generations}
    identity = _read_json(RESULTS / batch_id / "batch_identity.json")
    identity["runner_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    archive = RESULTS / batch_id / "rerun_rounds" / f"round-{plan['round']:04d}.json"
    _atomic_json(archive, {**plan, "identity": identity})
    _atomic_json(path, plan)
    return plan


def prepare_override(batch_id: str, rows: list[dict], positions: list[int]) -> dict:
    """Start fresh generations for selected rows without deleting old evidence."""
    path = RESULTS / batch_id / "rerun_state.json"
    plan = _read_json(path)
    if plan.get("active"):
        if (not plan.get("override_existing") or
                plan.get("positions") != positions):
            raise ValueError("Another rerun/override round is active; resume its original range first")
        return plan
    generations = dict(plan.get("generations", {}))
    previous = {}
    for position in positions:
        trial_id = _trial_id(batch_id, position)
        folder = trial_directory(RESULTS, trial_id)
        state, repo, _ = _record(batch_id, position, rows[position - 1]["repo_id"])
        if (folder / ".controller.lock").exists() or repo.get("pending"):
            raise ValueError(f"Position {position} has active or pending work; resume it before overriding")
        has_existing_run = bool(state or (folder / "fork_report.json").is_file())
        if has_existing_run:
            previous[str(position)] = trial_id
            generations[str(position)] = int(generations.get(str(position), 1)) + 1
            if len(f"{batch_id}-r{position:04d}-r{generations[str(position)]}") > 80:
                raise ValueError("Trial generation ID exceeds 80 characters")
    plan = {"round": int(plan.get("round", 0)) + 1, "active": bool(positions),
            "override_existing": True, "positions": positions,
            "previous_trials": previous, "generations": generations}
    identity = _read_json(RESULTS / batch_id / "batch_identity.json")
    identity["runner_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    archive = RESULTS / batch_id / "rerun_rounds" / f"round-{plan['round']:04d}.json"
    _atomic_json(archive, {**plan, "identity": identity})
    _atomic_json(path, plan)
    return plan


def position_bounds(start_at: int = 1, stop_at: int | None = None,
                    limit: int | None = None) -> tuple[int, int]:
    """Select original member-local row positions, including finished/skipped rows."""
    if not 1 <= start_at <= ROWS_PER_MEMBER:
        raise ValueError("--start-at must be between 1 and 1000")
    if stop_at is not None and limit is not None:
        raise ValueError("--stop-at and --limit cannot be used together")
    if limit is not None and limit < 1:
        raise ValueError("--limit must be positive")
    end = stop_at if stop_at is not None else (start_at + limit - 1 if limit is not None else ROWS_PER_MEMBER)
    if not start_at <= end <= ROWS_PER_MEMBER:
        raise ValueError("Selected end position must be between --start-at and 1000")
    return start_at, end


def run_batch(member: int, batch_id: str, *, preflight_only: bool, max_repositories: int | None,
              retry_failed_from: str | None = None, rerun_failed: bool = False,
              start_at: int = 1, stop_at: int | None = None, limit: int | None = None,
              allow_config_changes: bool = False, override_existing: bool = False,
              batch_name: str | None = None) -> int:
    begin, end = position_bounds(start_at, stop_at, limit)
    rows = _assignment(member)
    load_env(ROOT / ".env")
    if os.environ.get("CLOUDTUNE_AUTO_DELETE_FORKS", "").strip().lower() not in {"false", "0", "no", "off"}:
        raise ValueError("Set CLOUDTUNE_AUTO_DELETE_FORKS=false in .env to retain evidence forks")
    if not BASE_CONFIG.is_file():
        raise ValueError("Missing evaluation/configs/fork_pilot.json")
    if override_existing and (rerun_failed or retry_failed_from):
        raise ValueError("--override-existing cannot be combined with rerun or retry options")
    identity_path = RESULTS / batch_id / "batch_identity.json"
    previous_identity = _read_json(identity_path)
    requested_identity = _batch_identity_record(member, batch_id, batch_name)
    identity_changed = bool(previous_identity and
                            _identity_fields(previous_identity) != _identity_fields(requested_identity))
    if override_existing:
        for index in range(begin, end + 1):
            _, current, _ = _record(batch_id, index, rows[index - 1]["repo_id"])
            folder = trial_directory(RESULTS, _trial_id(batch_id, index))
            if (folder / ".controller.lock").exists() or current.get("pending"):
                raise ValueError(
                    f"Position {index} has active or pending work; resume it before overriding")
    if identity_changed and allow_config_changes and not override_existing and not rerun_failed:
        for index in range(begin, end + 1):
            _, current, report = _record(batch_id, index, rows[index - 1]["repo_id"])
            if _stage(current, report) != "finished" and (current or report):
                raise ValueError(
                    f"Position {index} has an unfinished run under the previous settings; "
                    "use --override-existing to start a preserved new generation")
    if rerun_failed:
        if retry_failed_from or not (RESULTS / batch_id / "batch_identity.json").is_file():
            raise ValueError("--rerun-failed requires an existing batch and cannot use --retry-failed-from")
        freeze_batch(member, batch_id, rerun_failed=True,
                     allow_config_changes=allow_config_changes, batch_name=batch_name)
    else:
        freeze_batch(member, batch_id, allow_config_changes=allow_config_changes,
                     batch_name=batch_name)
    selected = None
    rerun_plan = None
    if rerun_failed:
        rerun_plan = prepare_failed_rerun(batch_id, rows)
        selected = set(rerun_plan["positions"])
    elif override_existing:
        positions = list(range(begin, end + 1))
        rerun_plan = prepare_override(batch_id, rows, positions)
        selected = set(rerun_plan["positions"])
    if retry_failed_from:
        if retry_failed_from == batch_id:
            raise ValueError("Retry requires a new --batch-id; original evidence is preserved")
        selection_path = RESULTS / batch_id / "retry_selection.json"
        selection = _read_json(selection_path)
        if not selection:
            source_identity = _read_json(RESULTS / retry_failed_from / "batch_identity.json")
            if source_identity.get("member") != member:
                raise ValueError("Retry source is missing or belongs to a different member")
            current_identity = _read_json(RESULTS / batch_id / "batch_identity.json")
            if source_identity.get("assignment_sha256") != current_identity.get("assignment_sha256"):
                raise ValueError("Retry source uses a different repository assignment")
            selection = {"source": retry_failed_from, "positions": failed_positions(retry_failed_from, rows)}
            _atomic_json(selection_path, selection)
        if selection["source"] != retry_failed_from:
            raise ValueError("Frozen retry source changed")
        selected = set(selection["positions"])
    attempted = 0
    for index, row in enumerate(rows, 1):
        if not begin <= index <= end:
            continue
        if selected is not None and index not in selected:
            continue
        repo_id = row["repo_id"]
        _, current, report = _record(batch_id, index, repo_id)
        stage = _stage(current, report)
        if stage == "finished":
            continue
        if preflight_only and stage in {"ready", "hosted"}:
            if stage == "hosted":
                print(f"[{index}/1000] {repo_id}: hosted work exists; use --run", flush=True)
                publish_batch(member, rows, batch_id)
                return 2
            continue
        if max_repositories is not None and attempted >= max_repositories:
            break
        attempted += 1
        print(f"[{index}/1000] {repo_id}: continuing from {stage}, ID={_trial_id(batch_id, index)}", flush=True)
        if stage == "preflight":
            result = _invoke(member, index, "preflight", batch_id)
            _, current, report = _record(batch_id, index, repo_id)
            stage = _stage(current, report)
            accepted = (stage == "ready" and result == 0) or (
                stage == "finished" and current.get("status") == "PREFLIGHT_BLOCKED" and result == 2)
            if not accepted:
                publish_batch(member, rows, batch_id)
                if report.get("status") == "LLM_PAUSED" or current.get("status") == "LLM_PAUSED":
                    print("OpenRouter paused; inspect llm_error.json, then restart this SAME command.", flush=True)
                elif report.get("status") == "RAG_PAUSED" or current.get("status") == "RAG_PAUSED":
                    print("RAG paused; restore the requested GPU, then restart this SAME command.", flush=True)
                elif result != 0:
                    print(f"Preflight returned {result}. Check the saved state before restarting.", flush=True)
                return 2
        previous_trial = (rerun_plan.get("previous_trials", {}).get(str(index)) if rerun_plan else None)
        if not preflight_only and stage == "ready" and (retry_failed_from or previous_trial) and not current.get("fork_repo"):
            if previous_trial:
                previous = _read_json(trial_directory(RESULTS, previous_trial) / "state.json").get("repositories", {}).get(repo_id, {})
            else:
                _, previous, _ = _record(retry_failed_from, index, repo_id)
                previous_trial = _trial_id(retry_failed_from, index)
            if previous.get("fork_repo") and previous.get("cleanup_status") != "DELETED":
                old_path = trial_directory(RESULTS, previous_trial)
                if (old_path / ".controller.lock").exists() or previous.get("pending"):
                    raise ValueError("Source fork still has active work; cannot retry")
                if not previous.get("fork_created_by_evaluation") or not previous.get("fork_id"):
                    raise ValueError("Source fork lacks creation evidence; preserve it")
                target_path = trial_directory(RESULTS, _trial_id(batch_id, index)) / "state.json"
                target = _read_json(target_path)
                record = target["repositories"][repo_id]
                for key in ("fork_repo", "fork_owner", "fork_id", "fork_created_by_evaluation"):
                    record[key] = previous[key]
                record["fork_reused_from_evaluation"] = previous_trial
                _atomic_json(target_path, target)
        if not preflight_only and stage == "ready":
            result = _invoke(member, index, "hosted", batch_id)
            _, current, report = _record(batch_id, index, repo_id)
            stage = _stage(current, report)
            if stage != "finished" or result != 0:
                publish_batch(member, rows, batch_id)
                print(f"Hosted trial is not safely finalized (exit={result}, state={stage}). Restart SAME command after review.", flush=True)
                return 2
        elif not preflight_only and stage == "hosted":
            result = _invoke(member, index, "hosted", batch_id)
            _, current, report = _record(batch_id, index, repo_id)
            if _stage(current, report) != "finished" or result != 0:
                publish_batch(member, rows, batch_id)
                print("Hosted checkpoint unresolved; restart SAME command after review.", flush=True)
                return 2
        publish_batch(member, rows, batch_id)
    out = publish_batch(member, rows, batch_id)
    if rerun_plan and rerun_plan["active"] and all(
            _stage(*_record(batch_id, position, rows[position - 1]["repo_id"])[1:]) == "finished"
            for position in rerun_plan["positions"]):
        rerun_plan["active"] = False
        _atomic_json(RESULTS / batch_id / "rerun_state.json", rerun_plan)
    print(f"Member {member} summary: {out / 'attempts.csv'}", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--member", type=int, required=True, choices=(1, 2, 3, 4))
    parser.add_argument("--batch-id", help="Optional unique ID; defaults to eval-member-01, etc.")
    parser.add_argument("--batch-name", help="Optional human-readable label; defaults to the batch ID")
    parser.add_argument("--retry-failed-from", help="Retry only failed/blocked trials from this batch under a new ID")
    parser.add_argument("--rerun", "--rerun-failed", dest="rerun_failed", action="store_true",
                        help="Rerun only failed rows in this same batch using preserved -r2/-r3 generations")
    parser.add_argument("--allow-config-changes", action="store_true",
                        help="Record changed runner/model/config settings as a new batch revision")
    parser.add_argument("--override-existing", action="store_true",
                        help="Rerun selected existing positions in a new preserved generation")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list", action="store_true", help="Preview assigned repositories without API calls")
    mode.add_argument("--preflight-only", action="store_true", help="Screen/validate sequentially; no hosted CI")
    mode.add_argument("--run", action="store_true", help="Preflight then hosted A/B/C for PASS candidates")
    mode.add_argument("--publish-only", action="store_true", help="Refresh commit-ready results without running CI")
    parser.add_argument("--max-repositories", type=int,
                        help="Limit new nonterminal rows processed in this invocation")
    parser.add_argument("--start-at", "--start-position", dest="start_at", type=int, default=1,
                        help="First member-local row position (1-1000)")
    bounds = parser.add_mutually_exclusive_group()
    bounds.add_argument("--stop-at", "--stop-position", dest="stop_at", type=int,
                        help="Last member-local row position, inclusive")
    bounds.add_argument("--limit", type=int, help="Number of member-local row positions from --start-at")
    args = parser.parse_args()
    if args.max_repositories is not None and args.max_repositories < 1:
        parser.error("--max-repositories must be positive")
    try:
        begin, end = position_bounds(args.start_at, args.stop_at, args.limit)
        if args.publish_only and (args.start_at != 1 or args.stop_at is not None or args.limit is not None):
            raise ValueError("Position flags do not apply to --publish-only; publication always covers the full batch")
        rows = _assignment(args.member)
        batch_id = validated_batch_id(args.member, args.batch_id)
        source = validated_batch_id(args.member, args.retry_failed_from) if args.retry_failed_from else None
        if source == batch_id:
            raise ValueError("--retry-failed-from requires a different --batch-id")
        if args.list:
            for index, row in enumerate(rows, 1):
                if not begin <= index <= end:
                    continue
                print(f"{index:04d} (global {(args.member-1)*1000+index:04d}): {row['repo_id']}")
            return 0
        # Only one local controller/publisher owns each batch at a time.
        # The child fork controller separately locks every repository trial.
        with exclusive_batch(batch_id), (exclusive_batch(source) if source else nullcontext()):
            if args.publish_only:
                print(publish_batch(args.member, rows, batch_id))
                return 0
            return run_batch(args.member, batch_id, preflight_only=args.preflight_only,
                             max_repositories=args.max_repositories, retry_failed_from=source,
                             rerun_failed=args.rerun_failed, start_at=args.start_at,
                             stop_at=args.stop_at, limit=args.limit,
                             allow_config_changes=args.allow_config_changes,
                             override_existing=args.override_existing,
                             batch_name=args.batch_name)
    except KeyboardInterrupt:
        print("Stopped. Existing controller checkpoints remain intact; rerun the same command.", file=sys.stderr)
        return 130
    except (OSError, ValueError, KeyError, json.JSONDecodeError, csv.Error) as exc:
        print(f"Team evaluation paused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
