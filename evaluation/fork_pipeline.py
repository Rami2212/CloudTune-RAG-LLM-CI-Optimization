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
from evaluation.third_party.ci_cost.setup import install as install_ci_cost

from evaluation.candidate_validator import validate_and_archive
from evaluation.ci_executor import (
    ForkExperiment, GitHub, RunPending, automatic_fork_deletion_enabled,
    summarize_records,
)
from evaluation.optimizers.ci_cost import generate_ci_cost_candidate
from evaluation.optimizers.rag_llm import generate_rag_candidate
from evaluation.rag_retriever import Retriever
from evaluation.results_exporter import summarize_cohort
from evaluation.repository_preparation import GitHubReader, file_sha256, workflow_doc
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
             "rag_retriever.py", "results_exporter.py", "repository_preparation.py",
             "run_pipeline.py", "optimizers/ci_cost.py", "optimizers/rag_llm.py",
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
    if not 1 <= config.get("repetitions", 0) <= 5:
        raise ValueError("Fork repetitions must be 1..5")
    if config.get("execution", {}).get("development_smoke") is True:
        if config["repository_limit"] != 1 or config["repetitions"] != 1:
            raise ValueError("Development smoke is limited to one repository and one repetition per arm")
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
    if not config.get("rag", {}).get("generator_model", "").endswith(":free"):
        raise ValueError("Pin a free OpenRouter generator model")
    return config


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


def run_fork_evaluation(config: dict, *, resume_only: bool = False) -> dict:
    # GitHub credentials authorize research-owned forks only. This process does
    # not modify CloudTune's GitHub repository or execute target build scripts.
    # Validate before any GitHub writes; reject ambiguous deletion preferences.
    automatic_fork_deletion_enabled()
    token = os.environ.get("CLOUDTUNE_FORK_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise ValueError("Set GITHUB_TOKEN or CLOUDTUNE_FORK_TOKEN in the existing .env")
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
    for row in decisions:
        repo_id = row["repo_id"]
        state["repositories"].setdefault(repo_id, {"status": "SELECTED", "candidates": {},
                                                   "validation": {}, "records": [], "pending": None})
        repo = state["repositories"][repo_id]
        noncomparable = [record for record in repo.get("records", [])
                         if record.get("comparable") is False]
        if noncomparable:
            # A workflow that never acquired a runner is a platform-inconclusive
            # attempt, not evidence of slow or failed CI. Do not blindly retry.
            repo["status"] = ("INCONCLUSIVE_PLATFORM" if any(
                r.get("failure_class") == "PLATFORM_NO_JOB_START" for r in noncomparable)
                else "FAILED_TARGET_CI")
            store.save(state)
            if row["status"] in {"prepared", "needs_harness"} and repo.get("fork_repo"):
                snapshot = _repo_snapshot(output, row)
                meta = json.loads((snapshot / "manifest.json").read_text())
                experiment = ForkExperiment(fork_api, repo_id=repo_id,
                     workflow_path=meta["workflow_path"], source_sha=meta["source_commit_sha"],
                     original=(snapshot / "source/original.yml").read_bytes(),
                     evaluation_id=config["evaluation_id"], max_wait_seconds=180,
                     poll_seconds=15, evidence_root=snapshot)
                repo["measurements_finalized"] = True
                experiment.cleanup_fork(repo, lambda: store.save(state, snapshots={repo_id: snapshot}))
            continue
        if row["status"] not in {"prepared", "needs_harness"}:
            repo.update(status="SKIPPED", failure_reason=row["status"])
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
             evaluation_id=config["evaluation_id"], max_wait_seconds=180,
             poll_seconds=15, evidence_root=snapshot)
        try:
            if repo.get("measurements_finalized"):
                # All target repetitions already ended in a prior process.
                # Retry only non-destructive fork cleanup/reconciliation.
                experiment.cleanup_fork(repo, save)
                continue
            if "B" not in repo["candidates"]:
                try:
                    # Local candidate generation only; the target's CI still
                    # runs exclusively on GitHub Actions in its research fork.
                    tool_dir = ROOT / "evaluation/results/.tools/ci-cost"
                    install_ci_cost(tool_dir)
                    b = generate_ci_cost_candidate(snapshot, version=version, tool_dir=tool_dir)
                except (OSError, ValueError, RuntimeError) as exc:
                    b = {"decision": "ERROR", "status": "GENERATION_ERROR",
                         "error": type(exc).__name__ + ": " + str(exc)[:400]}
                repo["candidates"]["B"] = {k: b.get(k) for k in ("decision", "status", "after_sha256",
                                                          "candidate_relative_dir", "generated_artifact", "error")}
                store.save(state, snapshots={repo_id: snapshot})
            if "C" not in repo["candidates"]:
                try:
                    if retriever is None:
                        retriever = Retriever(
                            revision=state.get("rag_revision") or (
                                None if config["rag"]["embedding_revision"] == "AUTO_PIN_SINGLE"
                                else config["rag"]["embedding_revision"]),
                            dataset_path=ROOT / "research-data/rag/rag_dataset.jsonl",
                            dataset_sha256=config["rag"]["dataset_sha256"])
                        state["rag_revision"] = retriever.revision
                        save()
                    c = generate_rag_candidate(snapshot, retriever=retriever,
                             model=config["rag"]["generator_model"], top_k=config["rag"]["top_k"],
                             max_tokens=config["rag"]["max_tokens"],
                             required_job_names=config["execution"].get("required_job_names", []))
                except (ValueError, RuntimeError, OSError, KeyError, json.JSONDecodeError) as exc:
                    # A provider/network/generation failure is a valid research
                    # outcome, not a reason to drop the repository or fabricate
                    # a C candidate. A/B may still be measured independently.
                    c = {"decision": "ERROR", "after_sha256": None,
                         "generated_artifact": None, "model": config["rag"]["generator_model"],
                         "error": type(exc).__name__ + ": " + str(exc)[:400]}
                repo["candidates"]["C"] = {k: c.get(k) for k in ("decision", "after_sha256", "generated_artifact", "error", "model")}
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
                if verdict["verdict"] == "PASS" and data is not None:
                    candidates[arm] = data
            experiment.provision(repo, save)
            experiment.prepare(repo, save)
            if repo.get("workflow_id") is None:
                raise RuntimeError("Fork workflow is not registered/active")
            for arm, data in candidates.items():
                experiment.make_arm(repo, arm, data, save)
            # Always execute baseline first, then rotate C/B order. Every
            # target job is a real GitHub Actions run, not local simulation.
            reps = config["repetitions"]
            failed_trial = None
            for repeat in range(1, reps + 1):
                order = (["A", "B", "C"] if repeat % 3 == 1 else
                         ["B", "C", "A"] if repeat % 3 == 2 else ["C", "A", "B"])
                # The first actual experiment run must be A to establish
                # required jobs; subsequent repetitions use rotating orders.
                for arm in order:
                    if arm not in candidates:
                        continue
                    if any(r["arm"] == arm and r["repeat"] == repeat for r in repo["records"]):
                        continue
                    required = repo.get("required_names") or config["execution"].get("required_job_names", [])
                    outcome = experiment.execute(repo, save, arm=arm, repeat=repeat,
                             required=required, max_total=reps*3)
                    if not outcome["comparable"]:
                        failed_trial = outcome
                        break
                if failed_trial:
                    break
            if failed_trial:
                platform = failed_trial.get("failure_class") == "PLATFORM_NO_JOB_START"
                repo["status"] = "INCONCLUSIVE_PLATFORM" if platform else "FAILED_TARGET_CI"
                repo["failure_reason"] = (
                    f"GitHub run {failed_trial['run_id']} completed without a started job"
                    if platform else
                    f"GitHub run {failed_trial['run_id']} failed correctness or protocol checks")
            else:
                repo["status"] = ("COMPLETE"
                                  if len(candidates) == 3
                                  and len(repo["records"]) == reps * 3
                                  and all(record.get("comparable") for record in repo["records"])
                                  else "INCOMPLETE")
            repo["measurements_finalized"] = True
            save()  # Persist ALL measurements before deleting the research fork.
            experiment.cleanup_fork(repo, save)
        except RunPending as pending:
            repo["status"] = "WAITING_FOR_GITHUB_RUN"
            repo["pending_reason"] = str(pending)
            save()
            return _save_report(output, state)
        except Exception as exc:
            # Durable checkpoint is retained. We do not dispatch again after
            # an ambiguous failure, and we never label a failed run a speedup.
            repo["status"] = "INCOMPLETE"
            repo["failure_reason"] = type(exc).__name__ + ": " + str(exc)[:400]
            save()
            _save_report(output, state)
            raise
        _save_report(output, state)
    return _save_report(output, state)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--check-config", action="store_true")
    parser.add_argument("--resume-only", action="store_true",
                        help="Continue only a previously started evaluation")
    parser.add_argument("--watch", action="store_true",
                        help="Continue checking queued GitHub runs until all rows settle")
    parser.add_argument("--poll-interval", type=int, default=120,
                        help="Seconds between long-queue resume cycles (default 120)")
    args = parser.parse_args()
    try:
        config = _config(args.config)
        if args.check_config:
            print(json.dumps({"valid": True, "protocol": PROTOCOL,
                              "evaluation_id": config["evaluation_id"]}, indent=2))
            return 0
        if args.poll_interval < 10:
            raise ValueError("--poll-interval must be at least 10 seconds")
        load_env(ROOT / ".env")
        with exclusive_controller(config["evaluation_id"]):
            while True:
                report = run_fork_evaluation(config, resume_only=args.resume_only)
                status = {k: v["status"] for k, v in report["repositories"].items()}
                cleanup = {k: v.get("cleanup_status") for k, v in report["repositories"].items()}
                print(json.dumps({"evaluation_id": report["evaluation_id"],
                                  "repositories": status, "fork_cleanup": cleanup}, indent=2), flush=True)
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
                print("GitHub CI or fork cleanup pending; retrying safely without duplicate dispatch.", flush=True)
                time.sleep(args.poll_interval)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"Fork evaluation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
