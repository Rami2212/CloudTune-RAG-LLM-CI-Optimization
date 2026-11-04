"""Every corpus mechanism has an explicit evidence and measurement contract."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "research-data/rag/rag_dataset.jsonl"
REGISTRY_VERSION = "full-pattern-registry-v1"

# Family is an experiment requirement, not a claim of implemented hosted support.
# Short IDs are expanded below; neither generation nor admission has a cache-only
# whitelist. Corpus prerequisite text remains attached without reinterpretation.
ROUTES = {
    "GHA-CACHE": ("complete_work", "cache_state", ["dependency_inputs", "cache_isolation"], ["elapsed_seconds", "runner_seconds", "cache_transfer_seconds"]),
    "FAIL-FAST": ("failure_overlap", "matrix_failure", ["matrix_contract", "failure_policy"], ["failure_feedback_seconds", "runner_seconds", "cancelled_cells"]),
    "CANCEL-STALE": ("failure_overlap", "superseding_revisions", ["revision_identity", "supersession_contract"], ["latest_revision_feedback_seconds", "runner_seconds"]),
    "SKIP-WORKFLOW": ("event_selection", "event_oracle", ["event_contract", "required_status_contract"], ["false_omissions", "runner_seconds_per_event"]),
    "CHANGE-FILTER": ("event_selection", "path_events", ["change_dependencies", "required_status_contract"], ["false_omissions", "runner_seconds_per_event"]),
    "CUSTOM-TIMEOUT": ("resource_control", "slow_and_hung", ["successful_history", "duration_headroom"], ["false_timeouts", "runaway_runner_seconds"]),
    "FAIL-SCHEDULE": ("event_selection", "failure_streak", ["chronological_history", "pause_recovery_policy"], ["missed_obligations", "runner_seconds_per_window", "recovery_delay_seconds"]),
    "IDLE-SCHEDULE": ("event_selection", "idle_and_external_changes", ["activity_history", "external_input_contract"], ["missed_obligations", "runner_seconds_per_window"]),
    "FAILED-JOB-FIRST": ("failure_overlap", "job_order", ["job_dependencies", "prior_failure_history", "failure_policy"], ["failure_feedback_seconds", "runner_seconds"]),
    "HISTORY-TIMEOUT": ("resource_control", "chronological_timeout", ["successful_history", "history_cutoff", "duration_headroom"], ["false_timeouts", "runaway_runner_seconds"]),
    "PRIORITIZE": ("failure_overlap", "test_order", ["test_inventory", "order_independence", "prior_failure_history"], ["failure_feedback_seconds", "elapsed_seconds", "test_set_preserved"]),
    "BUILD-PRIORITY": ("infrastructure", "contended_queue", ["controlled_workers", "queue_history", "fairness_policy"], ["feedback_seconds", "tail_wait_seconds", "starvation_count"]),
    "SELECT": ("event_selection", "test_selection_oracle", ["change_dependencies", "test_inventory", "selection_contract"], ["missed_failures", "selection_recall", "runner_seconds_per_event"]),
    "BUILD-SELECT": ("event_selection", "build_selection_oracle", ["chronological_history", "history_cutoff", "selection_contract"], ["missed_failures", "runner_seconds_per_event"]),
    "BAZEL-PARALLEL": ("complete_work", "resource_matched", ["bazel_targets", "runner_resources"], ["elapsed_seconds", "runner_seconds", "output_equivalence"]),
    "BAZEL-INCREMENTAL": ("complete_work", "incremental_invalidation", ["bazel_targets", "toolchain_inputs", "cache_isolation"], ["elapsed_seconds", "runner_seconds", "output_equivalence"]),
    "BAZEL-DEPS": ("complete_work", "cache_overhead", ["dependency_inputs", "cache_transfer_timings"], ["elapsed_seconds", "cache_transfer_seconds", "runner_seconds"]),
    "ENV-CACHE": ("infrastructure", "environment_reset", ["pinned_environment", "state_reset_contract", "cache_isolation"], ["provision_seconds", "contamination_count", "runner_seconds"]),
    "UNAFFECTED-STEPS": ("event_selection", "step_selection_oracle", ["input_output_traces", "cold_fallback", "selection_contract"], ["false_omissions", "runner_seconds_per_event"]),
    "SMELL-REPAIR": ("complete_work", "repair_equivalence", ["concrete_repair_evidence", "required_work_contract"], ["elapsed_seconds", "runner_seconds", "output_equivalence"]),
    "DURATION-PREDICTION": ("analytical", "chronological_prediction", ["chronological_history", "history_cutoff"], ["prediction_mae_seconds", "prediction_calibration"]),
    "UNUSED-OUTPUTS": ("complete_work", "output_consumers", ["output_consumer_graph", "required_artifact_contract"], ["elapsed_seconds", "runner_seconds", "output_equivalence"]),
    "DISTRIBUTED-CACHE": ("infrastructure", "shared_cache_isolation", ["trusted_cache_service", "cache_isolation", "dependency_inputs"], ["elapsed_seconds", "cache_infrastructure_seconds", "runner_seconds"]),
    "CONFIG-REUSE": ("complete_work", "configuration_compatibility", ["configuration_graph", "toolchain_inputs", "required_work_contract"], ["elapsed_seconds", "runner_seconds", "output_equivalence"]),
    "UNUSED-DEP-SKIP": ("event_selection", "dependency_update_oracle", ["dependency_use_graph", "transitive_inputs", "selection_contract"], ["missed_failures", "runner_seconds_per_event"]),
}


def digest(value) -> str:
    raw = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def load_registry(dataset: Path = DATASET, *, expected_sha256: str | None = None) -> dict:
    raw = dataset.read_bytes()
    if expected_sha256 is not None and digest(raw) != expected_sha256:
        raise ValueError("Full-pattern corpus hash differs from pinned configuration")
    records = [json.loads(line) for line in raw.decode("utf-8-sig").splitlines() if line.strip()]
    documents = {}
    patterns = {}
    for row in records:
        doc_id = row.get("document_id")
        if not isinstance(doc_id, str) or not doc_id or doc_id in documents:
            raise ValueError("Corpus has missing or duplicate document IDs")
        if row.get("retrieval_eligible") is not True:
            continue
        if row.get("record_type") == "experiment_example":
            if row.get("experiment", {}).get("pattern_satisfied") is not True:
                continue
        elif row.get("record_type") != "pattern":
            continue
        documents[doc_id] = row
        if row["record_type"] == "pattern":
            pid = row.get("pattern_id")
            if pid in patterns:
                raise ValueError("Corpus has duplicate pattern IDs")
            patterns[pid] = row
    expected_ids = {"P-LIT-" + short for short in ROUTES}
    if set(patterns) != expected_ids:
        raise ValueError("Registry must cover exactly the 25 eligible corpus patterns")
    if any(row.get("pattern_id") not in patterns for row in documents.values()):
        raise ValueError("Example references an unknown pattern")
    catalogue = {}
    for pid, doc in sorted(patterns.items()):
        family, scenario, required, metrics = ROUTES[pid.removeprefix("P-LIT-")]
        detail = doc["pattern"]
        catalogue[pid] = {
            "pattern_id": pid, "document_id": doc["document_id"],
            "title": doc["title"], "mechanism": detail["mechanism"],
            "scope": detail["scope"], "eligible_for_proposal": True,
            "family": family, "scenario": scenario, "required_evidence": required,
            "metrics": metrics, "preconditions": detail.get("preconditions", []),
            "contraindications": detail.get("contraindications", []),
            "safety_tests": detail.get("safety_tests", []),
            "evidence_scope": doc.get("evidence_scope"),
            "example_count": sum(r["record_type"] == "experiment_example" and r["pattern_id"] == pid
                                 for r in documents.values()),
        }
    result = {"registry_version": REGISTRY_VERSION, "dataset_sha256": digest(raw),
              "catalogue": catalogue, "documents": documents}
    result["registry_sha256"] = digest(result)
    return result


def measurement_plan(pattern: dict) -> dict:
    """Do not mislabel an unimplemented scenario as a no-change decision."""
    return {"pattern_id": pattern["pattern_id"], "family": pattern["family"],
            "scenario": pattern["scenario"], "required_evidence": pattern["required_evidence"],
            "safety_tests": pattern["safety_tests"], "metrics": pattern["metrics"],
            "execution_status": "AVAILABLE_WITH_SCENARIO_INPUTS",
            "adapters": ["controlled_replay"] + (["github_actions"] if pattern["family"] == "complete_work" else []),
            "direct_ci_speedup_claim": pattern["family"] != "analytical"}
