"""CloudTune A/B/C controller following the existing fork-based research flow.

The coordinator runs locally and invokes GitHub's API; target repositories'
build and test commands execute ONLY on GitHub Actions inside research-owned
forks. Local durable state survives long runner queues and interrupted sessions.
No GitHub Actions workflow or state branch is needed in the CloudTune repo.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from scripts.experiment_environment import load_env
from evaluation.third_party.ci_cost.setup import (
    DEFAULT_DIR as DEFAULT_CI_COST_DIR, install as install_ci_cost,
)

from evaluation.candidate_validator import validate_and_archive
from evaluation.ci_executor import (
    ForkExperiment, GitHub, RunPending, automatic_fork_deletion_enabled,
    arm_name, log_progress, summarize_records,
)
from evaluation.optimizers.ci_cost import generate_ci_cost_candidate
from evaluation.openrouter_http import OpenRouterPaused
from evaluation.openrouter_settings import resolve_openrouter_env
from evaluation.optimizers.rag_llm import generate_rag_candidate
from evaluation.rag_retriever import Retriever
from evaluation.results_exporter import summarize_cohort
from evaluation.repository_preparation import (GitHubReader, file_sha256, read_evaluation_rows,
                                               workflow_doc)
from evaluation.run_pipeline import ROOT, load_config, prepare


PROTOCOL = "cloudtune-local-fork-abc-v2"


class StateStore:
    """Crash-safe local experiment ledger; never writes to CloudTune GitHub.

    Frozen snapshots remain in evaluation/results/<evaluation_id>/repositories.
    Restart the same command after interruption: a pending GitHub dispatch is
    discovered from its recorded intent instead of sent again.
    """

    def __init__(self, evaluation_id: str, output_root: Path | None = None):
        output_root = output_root if output_root is not None else ROOT
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", evaluation_id):
            raise ValueError("Unsafe evaluation_id for local state path")
        self.root = output_root / "evaluation" / "results" / evaluation_id
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "state.json"

    def load(self) -> dict | None:
        if not self.path.exists():
            return None
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, document: dict, *, snapshots: dict[str, Path] | None = None) -> None:
        """Write ledger atomically AFTER verifying local immutable snapshots."""
        for repo_id, snapshot in (snapshots or {}).items():
            snapshot = snapshot.resolve()
            base = (self.root / "repositories").resolve()
            if not snapshot.is_relative_to(base):
                raise ValueError("Snapshot escaped evaluation results")
            manifest = snapshot / "manifest.json"
            original = snapshot / "source" / "original.yml"
            if not manifest.is_file() or not original.is_file():
                raise ValueError("Evaluation snapshot is incomplete")
            details = json.loads(manifest.read_text(encoding="utf-8"))
            if (details.get("repo_id") != repo_id or
                    file_sha256(original) != details.get("workflow_sha256")):
                raise ValueError("Pinned repository snapshot changed")
            document["repositories"][repo_id]["snapshot_name"] = snapshot.name
        raw = (json.dumps(document, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if len(raw) > 2_000_000:
            raise ValueError("Experiment ledger too large; do not discard recorded runs")
        # The write is atomic on the same volume; a killed process cannot leave
        # a half-written state.json that could trigger a duplicate dispatch.
        fd, name = tempfile.mkstemp(prefix=".state-", suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def restore(self, output: Path, document: dict) -> list[dict]:
        """Recover only locally frozen snapshots, never moving upstream HEAD."""
        if document.get("dataset_sha256") != file_sha256(ROOT / document["dataset"]):
            raise ValueError("Held-out dataset changed since frozen evaluation")
        rows = []
        base = (output / "repositories").resolve()
        for entry in document["screening"]:
            row = dict(entry)
            if row["status"] in {"prepared", "needs_harness"}:
                name = document["repositories"][row["repo_id"]].get("snapshot_name", "")
                if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
                    raise ValueError("Unsafe or missing frozen snapshot name")
                target = (base / name).resolve()
                if not target.is_relative_to(base):
                    raise ValueError("Frozen snapshot escaped evaluation directory")
                manifest = target / "manifest.json"
                original = target / "source" / "original.yml"
                if not manifest.is_file() or not original.is_file():
                    raise ValueError("Frozen snapshot missing; cannot silently re-fetch")
                meta = json.loads(manifest.read_text(encoding="utf-8"))
                if (meta.get("repo_id") != row["repo_id"] or
                        file_sha256(original) != meta.get("workflow_sha256")):
                    raise ValueError("Frozen snapshot was altered")
                row["manifest_path"] = str(manifest)
            else:
                row["manifest_path"] = ""
            rows.append(row)
        return rows




@contextmanager
def exclusive_controller(evaluation_id: str):
    """Prevent two local controllers dispatching the same trial concurrently.

    An interrupted process may leave the lock. Verify no evaluation process is
    running before deleting the stale .controller.lock file to resume.
    """
    folder = ROOT / "evaluation/results" / evaluation_id
    folder.mkdir(parents=True, exist_ok=True)
    lock = folder / ".controller.lock"
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise RuntimeError(f"Controller already active or stale lock: {lock}") from None
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()) + "\n")
        yield
    finally:
        lock.unlink(missing_ok=True)


def implementation_digest() -> str:
    """Freeze evaluator code identity across every resumed GitHub dispatch."""
    names = ("fork_pipeline.py", "ci_executor.py", "candidate_validator.py",
             "setup_node_compatibility.py", "setup_node_releases.json",
             "rag_retriever.py", "results_exporter.py", "repository_preparation.py",
             "run_pipeline.py", "openrouter_http.py", "openrouter_settings.py",
             "optimizers/ci_cost.py", "optimizers/rag_llm.py",
             "third_party/ci_cost/setup.py", "third_party/ci_cost/source_fixes.py")
    sha = hashlib.sha256()
    for name in names:
        sha.update(name.encode("utf-8") + b"\0")
        sha.update((ROOT / "evaluation" / name).read_bytes())
    return sha.hexdigest()


def _repo_snapshot(output: Path, row: dict) -> Path:
    # Never blindly trust absolute paths from persisted screening.csv.
    path = Path(row["manifest_path"]).resolve()
    base = (output / "repositories").resolve()
    if not path.is_relative_to(base) or not path.is_file():
        raise ValueError("Frozen repository manifest path is missing or escaped its root")
    return path.parent


def _config(path: Path) -> dict:
    config = load_config(path, allow_hosted=True)
    if config.get("execution", {}).get("dry_run") is not False:
        raise ValueError("Fork evaluation config must explicitly specify execution.dry_run=false")
    if config.get("arms") != ["original", "ci_cost", "rag"]:
        raise ValueError("Fork evaluation requires the three A/B/C arms")
    if not 1 <= config.get("repository_limit", 0) <= 100:
        raise ValueError("Evaluation repository_limit must be 1..100; partition larger cohorts")
    if type(config.get("repetitions")) is not int or config["repetitions"] != 3:
        raise ValueError("Fork evaluation requires exactly 3 measured repetitions per admitted arm")
    if config.get("execution", {}).get("development_smoke") is True:
        if config["repository_limit"] != 1:
            raise ValueError("Development smoke is limited to one repository; 3 repetitions per arm")
    if config.get("execution", {}).get("cache_regime") != "uncontrolled":
        raise ValueError("This protocol only supports explicitly reported uncontrolled caches")
    if config.get("warmup_runs") != 0:
        raise ValueError("Fork protocol v2 does not implement separate warmup runs")
    if config.get("rag", {}).get("embedding_model") != "BAAI/bge-m3":
        raise ValueError("The existing RAG system uses BAAI/bge-m3")
    revision = config.get("rag", {}).get("embedding_revision", "")
    if revision != "AUTO_PIN_SINGLE" and not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("Select AUTO_PIN_SINGLE or a 40-character BGE-M3 revision")
    if not re.fullmatch(r"[a-f0-9]{64}", config.get("rag", {}).get("dataset_sha256", "")):
        raise ValueError("Pin the RAG dataset SHA256")
    # Model and output ceiling are validated separately from the environment,
    # before any evaluation state is created or a model request is sent.
    return config



def configure_batch(config: dict, *, start_at: int | None = None,
                    stop_at: int | None = None, limit: int | None = None,
                    batch_id: str | None = None) -> dict:
    """Resolve CLI range overrides into the frozen experiment configuration.

    Positions are 1-based in the original dataset; --stop-at is inclusive.
    Never mutate the loaded template: the resolved values are hashed with the
    evaluator implementation and checked on every resume.
    """
    if stop_at is not None and limit is not None:
        raise ValueError("--stop-at and --limit cannot be used together")
    start = config.get("repository_start_at", 1) if start_at is None else start_at
    if type(start) is not int or start < 1:
        raise ValueError("--start-at must be a positive integer")
    if stop_at is not None:
        if type(stop_at) is not int or stop_at < start:
            raise ValueError("--stop-at must be at least --start-at")
        count = stop_at - start + 1
    elif limit is not None:
        count = limit
    else:
        count = config["repository_limit"]
    if type(count) is not int or not 1 <= count <= 100:
        raise ValueError("Select between 1 and 100 repositories per batch")
    resolved = dict(config)
    resolved["repository_start_at"] = start
    resolved["repository_limit"] = count
    if batch_id is not None:
        # A batch has its own local state, snapshots, and report directory.
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", batch_id):
            raise ValueError("--batch-id must be 1-64 letters, digits, underscores or hyphens")
        resolved["evaluation_id"] = batch_id
    if config.get("execution", {}).get("development_smoke") is True:
        if count != 1 or not resolved["evaluation_id"].startswith("dev-"):
            raise ValueError("Development smoke requires one row and a dev- batch ID")
    return resolved


def selected_repository_rows(config: dict, *, explicit_stop: int | None = None
                             ) -> list[tuple[int, str]]:
    """Validate a cohort slice before any fork/API writes or local checkpoint.

    A preview is only a dataset-position check; safety/eligibility screening
    happens later in the read-only preparation stage.
    """
    rows = read_evaluation_rows(ROOT / config["dataset"],
                                expected_split=config.get("dataset_split", "evaluation"))
    start = config["repository_start_at"]
    end = min(len(rows), start + config["repository_limit"] - 1)
    if start > len(rows):
        raise ValueError(f"--start-at {start} exceeds dataset size {len(rows)}")
    if explicit_stop is not None and explicit_stop > len(rows):
        raise ValueError(f"--stop-at {explicit_stop} exceeds dataset size {len(rows)}")
    return [(position, rows[position - 1]["repo_id"])
            for position in range(start, end + 1)]


def _batch_generation_finalized(state: dict, config: dict,
                                selection: list[tuple[int, str]]) -> bool:
    """A rerun can only follow a settled generation with immutable evidence.

    Existing pending GitHub dispatches are resumed, NEVER replayed. Retained
    supervisor evidence is preserved; the next provisioning gate rejects any
    still-existing fork until it has been manually removed.
    """
    expected_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    if state.get("protocol") != PROTOCOL or state.get("config_sha256") != expected_hash:
        raise ValueError("Existing batch has a different frozen protocol/configuration")
    if state.get("dataset_sha256") != file_sha256(ROOT / config["dataset"]):
        raise ValueError("Existing batch has a different frozen dataset")
    entries = state.get("repositories")
    if not isinstance(entries, dict) or set(entries) != {repo for _, repo in selection}:
        return False
    for row in entries.values():
        if not isinstance(row, dict) or row.get("pending") is not None:
            return False
        if row.get("status") == "SKIPPED" and not row.get("fork_repo"):
            continue
        if (row.get("status") not in {"COMPLETE", "INCOMPLETE", "FAILED_TARGET_CI",
                                      "INCONCLUSIVE_PLATFORM"}
                or row.get("measurements_finalized") is not True):
            return False
        if row.get("fork_repo") and row.get("cleanup_status") not in {
                "DELETED", "RETAINED_BY_CONFIGURATION"}:
            return False
    return True


def resolve_rerun_batch(config: dict, selection: list[tuple[int, str]]) -> dict:
    """Create independent -r2/-r3 generations without overwriting prior runs.

    Repeated --rerun resumes an unfinished numbered generation. Once the
    generation finishes, the NEXT --rerun allocates the next unused number.
    """
    base_id = config["evaluation_id"]
    for generation in range(1, 10000):
        trial_id = base_id if generation == 1 else f"{base_id}-r{generation}"
        if len(trial_id) > 80:
            raise ValueError("Batch ID is too long for numbered rerun generations")
        trial = dict(config)
        trial["evaluation_id"] = trial_id
        folder = ROOT / "evaluation/results" / trial_id
        state_file = folder / "state.json"
        if not state_file.exists():
            if generation == 1:
                raise ValueError("--rerun requires an existing batch; start normally first")
            if folder.exists():
                raise ValueError(f"Generation {trial_id} has no state; inspect before retrying")
            return trial
        state = json.loads(state_file.read_text(encoding="utf-8"))
        if not _batch_generation_finalized(state, trial, selection):
            if generation == 1:
                raise ValueError("Original batch is not finalized; resume without --rerun")
            return trial  # Continue the same pending numbered generation safely.
    raise ValueError("Too many rerun generations")


def _candidate_yaml(snapshot: Path, arm: str, outcome: dict, original: bytes) -> bytes | None:
    if outcome.get("decision") == "NO_CHANGE":
        return None
    if outcome.get("decision") != "APPLY":
        raise ValueError(f"Arm {arm} was not generated successfully")
    if arm == "B":
        directory = snapshot / outcome["candidate_relative_dir"]
    else:
        directory = snapshot / "candidates/C"
    candidate = directory / outcome["generated_artifact"]
    data = candidate.read_bytes()
    if hashlib.sha256(data).hexdigest() != outcome["after_sha256"]:
        raise ValueError(f"Arm {arm} archived workflow checksum changed")
    return data


def _ensure_preparation(config: dict, state: dict, store: StateStore, token: str | None = None) -> Path:
    """Freeze once; later runner invocations restore identical archived blobs."""
    output = ROOT / "evaluation/results" / config["evaluation_id"]
    if "screening" not in state:
        # Reuse the same research-account token for read-only screening.
        log_progress("PREP", f"Screening selected repository range for {config['evaluation_id']}")
        prepare(config, reader=GitHubReader(token=token))
        with (output / "screening.csv").open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        state["screening"] = [{k: v for k, v in row.items() if k != "manifest_path"} for row in rows]
        state["dataset"] = config["dataset"]
        state["dataset_sha256"] = file_sha256(ROOT / config["dataset"])
        state["preparation_summary"] = json.loads((output / "preparation_summary.json").read_text())
        snapshot_paths: dict[str, Path] = {}
        for row in rows:
            state["repositories"].setdefault(row["repo_id"], {
                "status": "SELECTED" if row["status"] in {"prepared", "needs_harness"} else "SKIPPED",
                "candidates": {}, "validation": {}, "records": [], "pending": None})
            if row["status"] in {"prepared", "needs_harness"}:
                snapshot_paths[row["repo_id"]] = _repo_snapshot(output, row)
        store.save(state, snapshots=snapshot_paths)
    else:
        log_progress("PREP", "Restoring pinned repository snapshots from existing checkpoint")
        restored = store.restore(output, state)
        (output / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        (output / "preparation_summary.json").write_text(
            json.dumps(state["preparation_summary"], indent=2) + "\n", encoding="utf-8")
        with (output / "screening.csv").open("w", newline="", encoding="utf-8") as stream:
            columns = ("repo_id", "status", "reason", "workflow_path", "source_commit_sha", "manifest_path")
            writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(restored)
    return output


def _hold_for_preflight(repo: dict, candidates: dict, *, preflight_only: bool,
                        require_all_arms: bool) -> bool:
    """Archive the admission outcome before allowing any research-fork writes.

    The preflight never provisions a fork, even when B/C both pass. A later
    hosted run with the same frozen ID reuses the exact candidate artifacts.
    A complete three-arm study must not silently degrade to baseline-only CI.
    """
    if not (preflight_only or require_all_arms):
        return False
    missing = [arm for arm in ("B", "C") if arm not in candidates]
    repo["admitted_arms"] = list(candidates)
    repo["status"] = "PREFLIGHT_BLOCKED" if missing else "PREFLIGHT_READY"
    repo["failure_reason"] = (
        "Optimized arms not admitted: " + ", ".join(
            f"{arm}={repo.get('validation', {}).get(arm, {}).get('verdict', 'UNKNOWN')}"
            for arm in missing)
        if missing else None)
    return preflight_only or bool(missing)


def _save_report(output: Path, state: dict) -> dict:
    summaries = {}
    for repo_id, record in state.get("repositories", {}).items():
        results = summarize_records(record.get("records", []),
                                    repetitions=state.get("repetitions"))
        if record.get("candidates", {}).get("B", {}).get("decision") == "NO_CHANGE":
            results["B"]["descriptive_zero_change"] = True
        if record.get("candidates", {}).get("C", {}).get("decision") == "NO_CHANGE":
            results["C"]["descriptive_zero_change"] = True
        summaries[repo_id] = {"status": record.get("status", "UNKNOWN"),
                              "candidates": record.get("candidates", {}),
                              "validation": record.get("validation", {}),
                              "admitted_arms": record.get("admitted_arms", []),
                              "run_statistics": results,
                              "run_records": record.get("records", []),
                              "failure_reason": record.get("failure_reason"),
                              "cleanup_status": record.get("cleanup_status", "NOT_STARTED"),
                              "fork_repo": record.get("fork_repo")}
    report = {"evaluation_id": state["evaluation_id"], "protocol": PROTOCOL,
              "timing_source": "GitHub Actions REST jobs API exclusively; active job interval union excludes runner queue gaps",
              "reported_utc": datetime.now(timezone.utc).isoformat(),
              "repositories": summaries,
              "aggregate": summarize_cohort(summaries)}
    path = output / "fork_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output / "fork_aggregate.json").write_text(
        json.dumps(report["aggregate"], indent=2) + "\n", encoding="utf-8")
    with (output / "fork_runs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["repo_id", "arm", "repeat", "run_id", "run_attempt",
                         "config_commit_sha", "conclusion", "protocol_valid", "required_checks_pass",
                         "comparable", "workflow_elapsed_seconds", "sum_job_runtime_seconds",
                         "workflow_makespan_seconds", "inter_job_idle_seconds",
                         "initial_queue_seconds", "failure_class"])
        writer.writeheader()
        for repo, record in state.get("repositories", {}).items():
            for r in record.get("records", []):
                writer.writerow({k: (repo if k == "repo_id" else r.get(k)) for k in writer.fieldnames})
    return report


def run_fork_evaluation(config: dict, *, resume_only: bool = False,
                        preflight_only: bool = False,
                        require_all_arms: bool = False) -> dict:
    # GitHub credentials authorize research-owned forks only. This process does
    # not modify CloudTune's GitHub repository or execute target build scripts.
    # Validate before any GitHub writes; reject ambiguous deletion preferences.
    automatic_fork_deletion_enabled()
    token = os.environ.get("CLOUDTUNE_FORK_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise ValueError("Set GITHUB_TOKEN or CLOUDTUNE_FORK_TOKEN in the existing .env")
    # Diagnostic logging must not require fields omitted by valid minimal test fixtures.
    log_progress(
        "BATCH",
        f"Evaluation {config['evaluation_id']} started; "
        f"{config.get('repository_limit', 'unspecified')} selected rows, "
        f"{config['repetitions']} repeats/arm",
    )
    config_sha = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    code_sha = implementation_digest()
    store = StateStore(config["evaluation_id"])
    state = store.load()
    if state is None:
        if resume_only:
            return {"evaluation_id": config["evaluation_id"], "protocol": PROTOCOL,
                    "repositories": {}, "status": "NO_ACTIVE_RUN"}
        state = {"evaluation_id": config["evaluation_id"], "config_sha256": config_sha,
                 "implementation_sha256": code_sha, "protocol": PROTOCOL,
                 "repetitions": config["repetitions"], "repositories": {}}
    elif (state.get("config_sha256"), state.get("implementation_sha256"), state.get("protocol")) != (config_sha, code_sha, PROTOCOL):
        raise ValueError("Frozen config or evaluator implementation changed; use a new evaluation_id")
    output = _ensure_preparation(config, state, store, token=token)
    version = config.get("ci_cost", {}).get("version")
    if version != "1.0.0":
        raise ValueError("Unexpected ci-cost version")
    # RAG access is intentionally lazy. An unavailable Supabase index must not
    # prevent baseline A or rule-based B GitHub measurements.
    retriever = None
    with (output / "screening.csv").open(newline="", encoding="utf-8") as stream:
        decisions = list(csv.DictReader(stream))
    fork_api = GitHub(token)
    for position, row in enumerate(decisions, 1):
        repo_id = row["repo_id"]
        log_progress("REPO", f"[{position}/{len(decisions)}] {repo_id}: screening={row['status']}")
        state["repositories"].setdefault(repo_id, {"status": "SELECTED", "candidates": {},
                                                   "validation": {}, "records": [], "pending": None})
        repo = state["repositories"][repo_id]
        if preflight_only and (repo.get("fork_repo") or repo.get("pending") or
                               repo.get("records") or repo.get("measurements_finalized")):
            raise ValueError("Cannot preflight a trial with hosted execution state; use a new dev- ID")
        failed_baseline = next((record for record in repo.get("records", [])
                                if record["arm"] == "A" and not record.get("comparable")), None)
        if failed_baseline:
            # Only a failed ORIGINAL baseline invalidates the whole repository.
            # A failed B or C is isolated and its other admitted peer continues
            # after process restarts; evidence is never silently replayed.
            platform = failed_baseline.get("failure_class") == "PLATFORM_NO_JOB_START"
            repo["status"] = "INCONCLUSIVE_PLATFORM" if platform else "FAILED_TARGET_CI"
            repo["failure_reason"] = (
                f"Original Workflow run {failed_baseline['run_id']} completed without a started job"
                if platform else
                f"Original Workflow run {failed_baseline['run_id']} failed correctness or protocol checks")
            store.save(state)
            if row["status"] in {"prepared", "needs_harness"} and repo.get("fork_repo"):
                snapshot = _repo_snapshot(output, row)
                meta = json.loads((snapshot / "manifest.json").read_text())
                experiment = ForkExperiment(fork_api, repo_id=repo_id,
                     workflow_path=meta["workflow_path"], source_sha=meta["source_commit_sha"],
                     original=(snapshot / "source/original.yml").read_bytes(),
                     evaluation_id=config["evaluation_id"], max_wait_seconds=None,
                     poll_seconds=15, evidence_root=snapshot)
                repo["measurements_finalized"] = True
                experiment.cleanup_fork(repo, lambda: store.save(state, snapshots={repo_id: snapshot}))
            continue
        if row["status"] not in {"prepared", "needs_harness"}:
            repo.update(status="PREFLIGHT_BLOCKED" if (preflight_only or require_all_arms)
                        else "SKIPPED", failure_reason=row["status"])
            log_progress("REPO", f"{repo_id}: skipped by eligibility screening: {row['status']}")
            store.save(state)
            continue
        snapshot = _repo_snapshot(output, row)

        def save():
            # Always checkpoint THIS repository's frozen files and run ledger.
            store.save(state, snapshots={repo_id: snapshot})
        manifest = json.loads((snapshot / "manifest.json").read_text())
        original = (snapshot / "source/original.yml").read_bytes()
        if file_sha256(snapshot / "source/original.yml") != manifest["workflow_sha256"]:
            raise ValueError("Frozen source workflow hash mismatch")
        workflow_doc(original)
        experiment = ForkExperiment(fork_api, repo_id=repo_id, workflow_path=manifest["workflow_path"],
             source_sha=manifest["source_commit_sha"], original=original,
             evaluation_id=config["evaluation_id"], max_wait_seconds=None,
             poll_seconds=15, evidence_root=snapshot)
        try:
            if repo.get("measurements_finalized"):
                log_progress("REPO", f"{repo_id}: measurements already finalized; reconciling cleanup only")
                # All target repetitions already ended in a prior process.
                # Retry only non-destructive fork cleanup/reconciliation.
                experiment.cleanup_fork(repo, save)
                continue
            if "B" not in repo["candidates"]:
                try:
                    # Local candidate generation only; the target's CI still
                    # runs exclusively on GitHub Actions in its research fork.
                    # Share the installer/optimizer's stable, unversioned tool path.
                    # Source-fix revisions remain versioned for scientific provenance.
                    tool_dir = Path(os.environ.get("CI_COST_DIR", str(DEFAULT_CI_COST_DIR))).resolve()
                    log_progress("OPTIMIZER", f"{repo_id}: preparing CI-Cost optimizer")
                    install_ci_cost(tool_dir)
                    b = generate_ci_cost_candidate(snapshot, version=version, tool_dir=tool_dir)
                except (OSError, ValueError, RuntimeError) as exc:
                    b = {"decision": "ERROR", "status": "GENERATION_ERROR",
                         "error": type(exc).__name__ + ": " + str(exc)[:400]}
                repo["candidates"]["B"] = {k: b.get(k) for k in ("decision", "status", "after_sha256",
                                                          "candidate_relative_dir", "generated_artifact", "error")}
                log_progress("OPTIMIZER", f"{repo_id}: CI-Cost decision={b.get('decision')}, status={b.get('status')}")
                store.save(state, snapshots={repo_id: snapshot})
            if "C" not in repo["candidates"]:
                try:
                    if retriever is None:
                        log_progress("OPTIMIZER", f"{repo_id}: initializing BGE-M3 retriever for LLM + RAG")
                        retriever = Retriever(
                            revision=state.get("rag_revision") or (
                                None if config["rag"]["embedding_revision"] == "AUTO_PIN_SINGLE"
                                else config["rag"]["embedding_revision"]),
                            dataset_path=ROOT / "research-data/rag/rag_dataset.jsonl",
                            dataset_sha256=config["rag"]["dataset_sha256"])
                        state["rag_revision"] = retriever.revision
                        save()
                    log_progress("OPTIMIZER", f"{repo_id}: requesting free LLM + RAG candidate")
                    c = generate_rag_candidate(snapshot, retriever=retriever,
                             model=config["rag"]["generator_model"], top_k=config["rag"]["top_k"],
                             max_tokens=config["rag"]["max_tokens"],
                             required_job_names=config["execution"].get("required_job_names", []))
                except OpenRouterPaused as exc:
                    # Unlike an invalid candidate, an unavailable free provider
                    # must not become a permanent C=ERROR on this checkpoint.
                    # Stop before creating any fork; resume the frozen request
                    # only after a human explicitly restarts the controller.
                    repo["status"] = "LLM_PAUSED"
                    repo["failure_reason"] = str(exc)
                    save()
                    log_progress("OPTIMIZER", f"{repo_id}: LLM + RAG paused: {exc}")
                    return _save_report(output, state)
                except (ValueError, RuntimeError, OSError, KeyError, json.JSONDecodeError) as exc:
                    # A provider/network/generation failure is a valid research
                    # outcome, not a reason to drop the repository or fabricate
                    # a C candidate. A/B may still be measured independently.
                    c = {"decision": "ERROR", "after_sha256": None,
                         "generated_artifact": None, "model": config["rag"]["generator_model"],
                         "error": type(exc).__name__ + ": " + str(exc)[:400]}
                repo["candidates"]["C"] = {k: c.get(k) for k in ("decision", "after_sha256", "generated_artifact", "error", "model")}
                log_progress("OPTIMIZER", f"{repo_id}: LLM + RAG decision={c.get('decision')}")
                store.save(state, snapshots={repo_id: snapshot})
            candidates = {"A": original}
            for arm in "BC":
                result = repo["candidates"][arm]
                decision = result.get("decision", "ERROR")
                # Both optimizers receive the identical, source-bound gate.
                # Save immutable validation.json before touching candidate forks.
                data = (_candidate_yaml(snapshot, arm, result, original)
                        if decision == "APPLY" else None)
                verdict = validate_and_archive(snapshot, arm, original, data,
                                               decision=decision if decision in {"APPLY", "NO_CHANGE"} else "ERROR",
                                               generation=result)
                repo["validation"][arm] = verdict
                save()
                log_progress("VALIDATION", f"{repo_id}: {arm_name(arm)} verdict={verdict['verdict']}")
                if verdict["verdict"] == "PASS" and data is not None:
                    candidates[arm] = data
            repo["admitted_arms"] = list(candidates)
            if _hold_for_preflight(repo, candidates, preflight_only=preflight_only,
                                   require_all_arms=require_all_arms):
                save()  # Archive every verdict without creating any fork/arm.
                log_progress("PREFLIGHT", f"{repo_id}: {repo['status']}; admitted={', '.join(arm_name(arm) for arm in candidates)}")
                continue
            log_progress("REPO", f"{repo_id}: admitted arms={', '.join(arm_name(arm) for arm in candidates)}; preparing research fork")
            experiment.provision(repo, save)
            experiment.prepare(repo, save)
            if repo.get("workflow_id") is None:
                raise RuntimeError("Fork workflow is not registered/active")
            for arm, data in candidates.items():
                experiment.make_arm(repo, arm, data, save)
            # Measure only admitted arms. A failure in Original Workflow
            # invalidates the baseline and stops the entire repository. A failed
            # optimized arm is quarantined for this repository, but its peer
            # continues; this policy also applies when resuming checkpoints.
            reps = config["repetitions"]
            failed_optimized_arms = {record["arm"] for record in repo["records"]
                                     if record["arm"] in {"B", "C"}
                                     and not record.get("comparable")}
            failed_trial = None
            for repeat in range(1, reps + 1):
                order = (["A", "B", "C"] if repeat % 3 == 1 else
                         ["B", "C", "A"] if repeat % 3 == 2 else ["C", "A", "B"])
                # The first actual experiment run must be A to establish
                # required jobs; subsequent repetitions use rotating orders.
                for arm in order:
                    if arm not in candidates or arm in failed_optimized_arms:
                        continue
                    if any(r["arm"] == arm and r["repeat"] == repeat for r in repo["records"]):
                        continue
                    required = repo.get("required_names") or config["execution"].get("required_job_names", [])
                    log_progress("CI", f"{repo_id}: measuring {arm_name(arm)}, repeat {repeat}/{reps}")
                    outcome = experiment.execute(repo, save, arm=arm, repeat=repeat,
                             required=required, max_total=reps*3)
                    if not outcome["comparable"]:
                        if arm == "A":
                            # A is the reference for every speedup comparison.
                            failed_trial = outcome
                            log_progress("CI", f"{repo_id}: Original Workflow failed; stopping this repository")
                            break
                        failed_optimized_arms.add(arm)
                        log_progress("CI", f"{repo_id}: {arm_name(arm)} failed; "
                                            "stopping only this arm's remaining trials")
                if failed_trial:
                    break
            if failed_trial:
                platform = failed_trial.get("failure_class") == "PLATFORM_NO_JOB_START"
                repo["status"] = "INCONCLUSIVE_PLATFORM" if platform else "FAILED_TARGET_CI"
                repo["failure_reason"] = (
                    f"Original Workflow run {failed_trial['run_id']} completed without a started job"
                    if platform else
                    f"Original Workflow run {failed_trial['run_id']} failed correctness or protocol checks")
            else:
                complete = (len(candidates) == 3 and
                            len(repo["records"]) == reps * 3 and
                            all(record.get("comparable") for record in repo["records"]))
                if complete:
                    repo["status"] = "COMPLETE"
                    repo["failure_reason"] = None
                elif failed_optimized_arms:
                    # Platform failures remain distinct from actual target-CI
                    # failures; both are excluded from invalid pair metrics.
                    failures = [record for record in repo["records"]
                                if record["arm"] in failed_optimized_arms
                                and not record.get("comparable")]
                    repo["status"] = ("INCONCLUSIVE_PLATFORM" if failures and all(
                        record.get("failure_class") == "PLATFORM_NO_JOB_START" for record in failures)
                        else "FAILED_TARGET_CI")
                else:
                    repo["status"] = "INCOMPLETE"
                if not complete:
                    # Record failure and abstention separately; the valid A/B or
                    # A/C comparison remains eligible in the cohort exporter.
                    issues = [f"{arm_name(arm)}: "
                              f"{repo['candidates'][arm].get('decision', 'UNKNOWN')} / "
                              f"{repo.get('validation', {}).get(arm, {}).get('verdict', 'UNKNOWN')}"
                              for arm in "BC" if arm not in candidates]
                    issues.extend(
                        f"{arm_name(record['arm'])}: GitHub run {record['run_id']} "
                        f"{record.get('failure_class') or 'not comparable'}"
                        for record in repo["records"]
                        if record["arm"] in failed_optimized_arms
                        and not record.get("comparable"))
                    repo["failure_reason"] = "No complete A/B/C comparison; " + "; ".join(issues)
            repo["measurements_finalized"] = True
            repo.pop("pending_reason", None)
            save()  # Persist ALL measurements before deleting the research fork.
            log_progress("REPO", f"{repo_id}: finalized status={repo['status']}; runs={len(repo.get('records', []))}; reason={repo.get('failure_reason', 'none')}")
            experiment.cleanup_fork(repo, save)
        except RunPending as pending:
            repo["status"] = "WAITING_FOR_GITHUB_RUN"
            repo["pending_reason"] = str(pending)
            log_progress("PENDING", f"{repo_id}: {pending}; pending run={repo.get('pending', {}).get('run_id') if repo.get('pending') else None}")
            save()
            return _save_report(output, state)
        except Exception as exc:
            # Durable checkpoint is retained. We do not dispatch again after
            # an ambiguous failure, and we never label a failed run a speedup.
            repo["status"] = "INCOMPLETE"
            repo["failure_reason"] = type(exc).__name__ + ": " + str(exc)[:400]
            log_progress("ERROR", f"{repo_id}: interrupted by {type(exc).__name__}; inspect checkpoint")
            save()
            _save_report(output, state)
            raise
        _save_report(output, state)
    return _save_report(output, state)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--start-at", type=int,
                        help="First 1-based row in the shared evaluation CSV")
    parser.add_argument("--stop-at", type=int,
                        help="Last 1-based row, inclusive (exclusive with --limit)")
    parser.add_argument("--limit", type=int,
                        help="Maximum rows from --start-at, capped at 100")
    parser.add_argument("--batch-id",
                        help="Unique team/member experiment ID and checkpoint directory")
    parser.add_argument("--list", action="store_true",
                        help="Preview selected repository rows without network calls")
    parser.add_argument("--rerun", action="store_true",
                        help="Run completed cases in a preserved generation (-r2/-r3/...)")
    parser.add_argument("--check-config", action="store_true")
    parser.add_argument("--preflight", action="store_true",
                        help="Screen, generate and validate A/B/C without creating a fork or dispatching CI")
    parser.add_argument("--require-all-arms", action="store_true",
                        help="Block hosted fork creation unless B and C both pass admission")
    parser.add_argument("--resume-only", action="store_true",
                        help="Continue only a previously started evaluation")
    parser.add_argument("--watch", action="store_true",
                        help="Continue checking queued GitHub runs until all rows settle")
    parser.add_argument("--poll-interval", type=int, default=120,
                        help="Seconds between long-queue resume cycles (default 120)")
    args = parser.parse_args()
    try:
        if args.preflight and (args.watch or args.resume_only or args.rerun):
            raise ValueError("--preflight cannot be combined with --watch, --resume-only or --rerun")
        # Load .env BEFORE resolving the config. The selected generator model
        # and output limit are env-only, then frozen into the evaluation hash.
        load_env(ROOT / ".env")
        config = configure_batch(_config(args.config), start_at=args.start_at,
                                 stop_at=args.stop_at, limit=args.limit,
                                 batch_id=args.batch_id)
        config = resolve_openrouter_env(config)
        if args.rerun:
            if not args.batch_id:
                raise ValueError("--rerun requires --batch-id")
            if args.resume_only:
                raise ValueError("Use --rerun alone to resume a pending rerun generation")
            # Resolve only from frozen local state; never issue network requests.
            selection = selected_repository_rows(config, explicit_stop=args.stop_at)
            config = resolve_rerun_batch(config, selection)
        if args.check_config:
            print(json.dumps({"valid": True, "protocol": PROTOCOL,
                              "evaluation_id": config["evaluation_id"],
                              "repository_start_at": config["repository_start_at"],
                              "repository_limit": config["repository_limit"],
                              "openrouter_model": config["rag"]["generator_model"],
                              "openrouter_max_tokens": config["rag"]["max_tokens"]}, indent=2))
            return 0
        # Validate selection before loading any credentials or starting work.
        # --list prints dataset positions only; no GitHub or model calls.
        selection = selected_repository_rows(config, explicit_stop=args.stop_at)
        if args.list:
            print(f"evaluation_id: {config['evaluation_id']}")
            for position, repo_id in selection:
                print(f"{position}\t{repo_id}\thttps://github.com/{repo_id}")
            return 0
        if args.poll_interval < 10:
            raise ValueError("--poll-interval must be at least 10 seconds")
        with exclusive_controller(config["evaluation_id"]):
            while True:
                report = run_fork_evaluation(config, resume_only=args.resume_only,
                    preflight_only=args.preflight, require_all_arms=args.require_all_arms)
                status = {k: v["status"] for k, v in report["repositories"].items()}
                cleanup = {k: v.get("cleanup_status") for k, v in report["repositories"].items()}
                print(json.dumps({"evaluation_id": report["evaluation_id"],
                                  "repositories": status, "fork_cleanup": cleanup}, indent=2), flush=True)
                if (args.preflight or args.require_all_arms) and any(
                        value == "PREFLIGHT_BLOCKED" for value in status.values()):
                    print("A/B/C admission blocked; no fork created for blocked repositories.",
                          file=sys.stderr, flush=True)
                    return 2
                if any(value == "LLM_PAUSED" for value in status.values()):
                    print("OpenRouter request paused; inspect archived llm_error.json "
                          "and resume explicitly with the same frozen evaluation ID. "
                          "No automatic LLM retry or CI dispatch occurred.",
                          file=sys.stderr, flush=True)
                    return 2
                active = {"SELECTED", "WAITING_FOR_GITHUB_RUN", "READY_FOR_NEXT_CONTROLLER_RUN"}
                needs_cleanup = any(row.get("cleanup_status") in {
                                    "WAITING_FOR_OTHER_RUNS", "DELETE_OUTCOME_UNKNOWN"}
                                    for row in report["repositories"].values())
                if not args.watch or not (any(value in active for value in status.values()) or needs_cleanup):
                    unresolved = {k: v for k, v in cleanup.items()
                                  if v in {"BLOCKED_PERMISSION", "DELETE_OUTCOME_UNKNOWN",
                                           "WAITING_FOR_OTHER_RUNS", "PRESERVED_NOT_OWNED",
                                           "PRESERVED_UNVERIFIED_ID"}}
                    if unresolved:
                        print("Fork cleanup is not complete: " + json.dumps(unresolved),
                              file=sys.stderr, flush=True)
                        return 2
                    return 0
                log_progress("BATCH", f"Pending hosted CI or cleanup; checking again in {args.poll_interval}s (no duplicate dispatch)")
                time.sleep(args.poll_interval)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"Fork evaluation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
