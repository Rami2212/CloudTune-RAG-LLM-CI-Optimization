"""Automated CloudTune hosted A/B/C evaluation coordinator.

The controller may run on a GitHub-hosted runner, but ALL MEASURED target
build/test jobs run on GitHub Actions inside isolated research-owned forks.
Remote state is checkpointed in CloudTune's dedicated state branch so it can
resume across runner restarts without replaying ambiguous workflow dispatches.
"""
from __future__ import annotations

import argparse
import base64
import io
import zipfile
import csv
import hashlib
import json
import os
import re
from datetime import datetime, timezone
import sys
from pathlib import Path

from evaluation.candidate_validator import validate_candidate
from evaluation.ci_executor import ForkExperiment, GitHub, GitHubError, RunPending, summarize_records
from evaluation.optimizers.ci_cost import generate_ci_cost_candidate
from evaluation.optimizers.rag_llm import generate_rag_candidate
from evaluation.rag_retriever import Retriever
from evaluation.results_exporter import summarize_cohort
from evaluation.repository_preparation import file_sha256, read_evaluation_rows, workflow_doc
from evaluation.run_pipeline import ROOT, load_config, prepare


STATE_BRANCH = "cloudtune-evaluation-state"
PROTOCOL = "cloudtune-hosted-abc-v1"


class StateStore:
    """Durable Git state for ephemeral, hosted evaluation controllers.

    A single non-force Git commit atomically checkpoints state JSON and any
    frozen snapshot ZIPs. All writes occur on a dedicated state branch, not
    on the development or original upstream branches. GitHub Actions controller
    concurrency must prevent simultaneous writers for this state branch.
    """
    MAX_SNAPSHOT_BYTES = 25_000_000
    MAX_COMPRESSED_BYTES = 15_000_000

    def __init__(self, github: GitHub, repository: str, evaluation_id: str):
        self.gh, self.repo, self.id = github, repository, evaluation_id
        self.path = "runs/" + evaluation_id + ".json"
        self.head: str | None = None
        self._ensure_branch()

    def _head(self) -> str:
        return self.gh.request("GET", f"/repos/{self.repo}/git/ref/heads/{STATE_BRANCH}")["object"]["sha"]

    def _ensure_branch(self):
        try:
            self.head = self._head()
            return
        except GitHubError as exc:
            if exc.code != 404:
                raise
        metadata = self.gh.request("GET", f"/repos/{self.repo}")
        head = self.gh.request("GET", f"/repos/{self.repo}/commits/{metadata['default_branch']}")
        try:
            self.gh.request("POST", f"/repos/{self.repo}/git/refs", {
                "ref": "refs/heads/" + STATE_BRANCH, "sha": head["sha"]})
        except GitHubError as exc:
            if exc.code != 422:
                raise
        self.head = self._head()

    def load(self) -> dict | None:
        try:
            record = self.gh.request("GET", f"/repos/{self.repo}/contents/{self.path}?ref={STATE_BRANCH}")
        except GitHubError as exc:
            if exc.code == 404:
                return None
            raise
        return json.loads(base64.b64decode(record["content"]).decode("utf-8"))

    @classmethod
    def _pack(cls, snapshot: Path) -> bytes:
        """Create a deterministic bounded archive with no unsafe symlinks."""
        buf = io.BytesIO()
        total = 0
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path in sorted(p for p in snapshot.rglob("*") if p.is_file()):
                if path.is_symlink():
                    raise ValueError("Symlink in frozen evaluation snapshot")
                relative = path.relative_to(snapshot)
                total += path.stat().st_size
                if total > cls.MAX_SNAPSHOT_BYTES:
                    raise ValueError("Frozen snapshot exceeds hosted archive cap; mark repository unsupported")
                info = zipfile.ZipInfo(relative.as_posix(), date_time=(2020, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, path.read_bytes())
        data = buf.getvalue()
        if len(data) > cls.MAX_COMPRESSED_BYTES:
            raise ValueError("Frozen snapshot exceeds hosted compressed archive cap")
        return data

    def save(self, document: dict, *, snapshots: dict[str, Path] | None = None) -> None:
        """Atomically checkpoint metadata and requested snapshot file contents.

        No target-fork dispatch or mutation is permitted before this succeeds.
        """
        updates = []
        for repo_id, snapshot in (snapshots or {}).items():
            contents = self._pack(snapshot)
            sha = hashlib.sha256(contents).hexdigest()
            path = f"archives/{self.id}/{hashlib.sha256(repo_id.encode()).hexdigest()[:20]}.zip"
            blob = self.gh.request("POST", f"/repos/{self.repo}/git/blobs", {
                "content": base64.b64encode(contents).decode("ascii"), "encoding": "base64"})
            updates.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
            document["repositories"][repo_id]["archive"] = {
                "blob_sha": blob["sha"], "sha256": sha, "path": path,
                "snapshot_name": snapshot.name}
        raw = json.dumps(document, sort_keys=True, ensure_ascii=False, indent=2).encode("utf-8")
        if len(raw) > 900_000:
            raise RuntimeError("Durable run ledger exceeds configured limit")
        blob = self.gh.request("POST", f"/repos/{self.repo}/git/blobs", {
            "content": base64.b64encode(raw).decode("ascii"), "encoding": "base64"})
        updates.append({"path": self.path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        current = self._head()
        if current != self.head:
            raise RuntimeError("State branch was modified by another writer; do not overwrite it")
        head = self.gh.request("GET", f"/repos/{self.repo}/git/commits/{current}")
        tree = self.gh.request("POST", f"/repos/{self.repo}/git/trees", {
            "base_tree": head["tree"]["sha"], "tree": updates})
        commit = self.gh.request("POST", f"/repos/{self.repo}/git/commits", {
            "message": "[skip ci] CloudTune evaluation checkpoint " + self.id,
            "tree": tree["sha"], "parents": [current]})
        self.gh.request("PATCH", f"/repos/{self.repo}/git/refs/heads/{STATE_BRANCH}", {
            "sha": commit["sha"], "force": False})
        self.head = commit["sha"]

    def restore(self, output: Path, document: dict) -> list[dict]:
        """Restore the exact archived context, never the upstream moving HEAD."""
        if document.get("dataset_sha256") != file_sha256(ROOT / document["dataset"]):
            raise ValueError("Held-out dataset changed since frozen evaluation")
        output.mkdir(parents=True, exist_ok=True)
        rows = []
        for entry in document["screening"]:
            row = dict(entry)
            if row["status"] in {"prepared", "needs_harness"}:
                archive_info = document["repositories"][row["repo_id"]].get("archive")
                if not archive_info:
                    raise ValueError("Frozen evaluation snapshot is missing from durable ledger")
                packed = self.gh.blob(self.repo, archive_info["blob_sha"])
                if hashlib.sha256(packed).hexdigest() != archive_info["sha256"]:
                    raise ValueError("Frozen evaluation archive checksum mismatch")
                name = archive_info["snapshot_name"]
                if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
                    raise ValueError("Unsafe frozen evaluation snapshot name")
                target = output / "repositories" / name
                target.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(io.BytesIO(packed)) as zipped:
                    total = 0
                    for member in zipped.infolist():
                        rel = Path(member.filename)
                        if rel.is_absolute() or ".." in rel.parts or not member.filename or member.is_dir():
                            raise ValueError("Unsafe archived snapshot member")
                        total += member.file_size
                        if total > self.MAX_SNAPSHOT_BYTES:
                            raise ValueError("Archived snapshot exceeds size cap")
                        dest = target / rel
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(zipped.read(member))
                manifest = target / "manifest.json"
                if not manifest.is_file():
                    raise ValueError("Archived snapshot has no manifest")
                row["manifest_path"] = str(manifest)
            else:
                row["manifest_path"] = ""
            rows.append(row)
        return rows


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
        raise ValueError("Hosted config must explicitly specify execution.dry_run=false")
    if config.get("arms") != ["original", "ci_cost", "rag"]:
        raise ValueError("Hosted evaluation requires the three A/B/C arms")
    if not 1 <= config.get("repository_limit", 0) <= 3:
        raise ValueError("Hosted job allows at most 3 candidate rows per run; use batches")
    if not 1 <= config.get("repetitions", 0) <= 5:
        raise ValueError("Hosted repetitions must be 1..5")
    if config.get("execution", {}).get("cache_regime") != "uncontrolled":
        raise ValueError("This protocol only supports explicitly reported uncontrolled caches")
    if config.get("warmup_runs") != 0:
        raise ValueError("Hosted v1 does not implement separate warmup runs")
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


def _ensure_preparation(config: dict, state: dict, store: StateStore) -> Path:
    """Freeze once; later runner invocations restore identical archived blobs."""
    output = ROOT / "evaluation/results" / config["evaluation_id"]
    if "screening" not in state:
        prepare(config)
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
                              "failure_reason": record.get("failure_reason")}
    report = {"evaluation_id": state["evaluation_id"], "protocol": PROTOCOL,
              "timing_source": "GitHub Actions REST jobs API exclusively; active job interval union excludes runner queue gaps",
              "reported_utc": datetime.now(timezone.utc).isoformat(),
              "repositories": summaries,
              "aggregate": summarize_cohort(summaries)}
    path = output / "hosted_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output / "hosted_aggregate.json").write_text(
        json.dumps(report["aggregate"], indent=2) + "\n", encoding="utf-8")
    with (output / "hosted_runs.csv").open("w", encoding="utf-8", newline="") as handle:
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


def run_hosted(config: dict, *, resume_only: bool = False) -> dict:
    # Target fork writes require a separate credential; repository-scoped
    # GITHUB_TOKEN cannot write to independently owned research forks.
    controller_token = os.environ.get("GITHUB_TOKEN", "")
    fork_token = os.environ.get("CLOUDTUNE_FORK_TOKEN", "")
    controller_repo = os.environ.get("GITHUB_REPOSITORY", "")
    # Scheduled invocations use the original controller source commit selected
    # by preflight. Never silently run a different implementation after main
    # moves while a multi-day experiment is in progress.
    controller_sha = os.environ.get("CLOUDTUNE_CONTROLLER_SHA") or os.environ.get("GITHUB_SHA", "")
    if not controller_token or not fork_token or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", controller_repo):
        raise ValueError("Run in GitHub Actions with GITHUB_TOKEN and CLOUDTUNE_FORK_TOKEN")
    if not re.fullmatch(r"[a-f0-9]{40}", controller_sha):
        raise ValueError("GITHUB_SHA must be a pinned controller commit")
    config_sha = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    store = StateStore(GitHub(controller_token), controller_repo, config["evaluation_id"])
    state = store.load()
    if state is None:
        if resume_only:
            return {"evaluation_id": config["evaluation_id"], "protocol": PROTOCOL,
                    "repositories": {}, "status": "NO_ACTIVE_RUN"}
        state = {"evaluation_id": config["evaluation_id"], "config_sha256": config_sha,
                 "controller_sha": controller_sha, "protocol": PROTOCOL,
                 "repetitions": config["repetitions"], "repositories": {}}
    elif (state.get("config_sha256"), state.get("controller_sha"), state.get("protocol")) != (config_sha, controller_sha, PROTOCOL):
        raise ValueError("Frozen hosted config, controller commit or protocol changed; use a new evaluation_id")
    output = _ensure_preparation(config, state, store)
    version = config.get("ci_cost", {}).get("version")
    if version != "1.0.0":
        raise ValueError("Unexpected ci-cost version")
    # Reuse the existing pinned dataset + stored BGE-M3 embeddings, never
    # rebuild or upload a training corpus during held-out evaluation.
    retriever = Retriever(
        revision=state.get("rag_revision") or (None if config["rag"]["embedding_revision"] == "AUTO_PIN_SINGLE" else config["rag"]["embedding_revision"]),
        dataset_path=ROOT / "research-data/rag/rag_dataset.jsonl",
        dataset_sha256=config["rag"]["dataset_sha256"])
    if state.get("rag_revision") and state["rag_revision"] != retriever.revision:
        raise ValueError("Frozen Supabase embedding revision changed")
    state["rag_revision"] = retriever.revision
    store.save(state)
    with (output / "screening.csv").open(newline="", encoding="utf-8") as stream:
        decisions = list(csv.DictReader(stream))
    fork_api = GitHub(fork_token)
    new_dispatches = 0
    max_new_dispatches = 3  # bounded work per hosted runner; scheduled runs resume
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
            continue
        def save():
            store.save(state, snapshots={repo_id: snapshot})
        if row["status"] not in {"prepared", "needs_harness"}:
            repo.update(status="SKIPPED", failure_reason=row["status"])
            save()
            continue
        snapshot = _repo_snapshot(output, row)
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
            if "B" not in repo["candidates"]:
                b = generate_ci_cost_candidate(snapshot, version=version)
                repo["candidates"]["B"] = {k: b.get(k) for k in ("decision", "status", "after_sha256",
                                                          "candidate_relative_dir", "generated_artifact", "error")}
                store.save(state, snapshots={repo_id: snapshot})
            if "C" not in repo["candidates"]:
                try:
                    c = generate_rag_candidate(snapshot, retriever=retriever,
                             model=config["rag"]["generator_model"], top_k=config["rag"]["top_k"],
                             max_tokens=config["rag"]["max_tokens"])
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
                if result["decision"] == "APPLY":
                    data = _candidate_yaml(snapshot, arm, result, original)
                    verdict = validate_candidate(original, data)
                    repo["validation"][arm] = verdict
                    save()
                    if verdict["verdict"] == "PASS":
                        candidates[arm] = data
                elif result["decision"] == "NO_CHANGE":
                    repo["validation"][arm] = {"verdict": "NO_CHANGE"}
                    save()
                else:
                    repo["validation"][arm] = {"verdict": "FAIL", "reasons": ["GENERATION_ERROR"]}
                    save()
            experiment.provision(repo, save)
            experiment.prepare(repo, save)
            if repo.get("workflow_id") is None:
                raise RuntimeError("Fork workflow is not registered/active")
            for arm, data in candidates.items():
                experiment.make_arm(repo, arm, data, save)
            # Always execute baseline first, then rotate C/B order. Every
            # target job is a real GitHub Actions run, not local simulation.
            reps = config["repetitions"]
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
                    if not repo.get("pending"):
                        if new_dispatches >= max_new_dispatches:
                            repo["status"] = "READY_FOR_NEXT_CONTROLLER_RUN"
                            save()
                            return _save_report(output, state)
                        new_dispatches += 1
                    required = repo.get("required_names") or config["execution"].get("required_job_names", [])
                    outcome = experiment.execute(repo, save, arm=arm, repeat=repeat,
                             required=required, max_total=reps*3)
                    if not outcome["comparable"]:
                        if outcome.get("failure_class") == "PLATFORM_NO_JOB_START":
                            repo["status"] = "INCONCLUSIVE_PLATFORM"
                            repo["failure_reason"] = (f"GitHub run {outcome['run_id']} completed "
                                                      "without any runner executing a job")
                            save()
                            return _save_report(output, state)
                        raise RuntimeError(f"Actual GitHub Actions {arm} run {outcome['run_id']} failed correctness or protocol checks")
            repo["status"] = ("COMPLETE"
                              if len(repo["records"]) == reps * len(candidates)
                              and all(row.get("comparable") for row in repo["records"])
                              else "INCOMPLETE")
            save()
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
                        help="Only continue a previously started evaluation; schedule-safe")
    args = parser.parse_args()
    try:
        config = _config(args.config)
        if args.check_config:
            print(json.dumps({"valid": True, "protocol": PROTOCOL,
                              "evaluation_id": config["evaluation_id"]}, indent=2))
            return 0
        report = run_hosted(config, resume_only=args.resume_only)
        print(json.dumps({"evaluation_id": report["evaluation_id"],
                          "repositories": {k: v["status"] for k, v in report["repositories"].items()}}, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"Hosted evaluation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
