"""Attribute only actual ci-cost edits; do not hand-improve its proposal."""
from __future__ import annotations

import json
from pathlib import Path

from evaluation.optimizers.ci_cost import generate_ci_cost_candidate
from evaluation.repository_preparation import workflow_doc, write_json_immutable
from .registry import digest


def adapt_candidate(generated: dict, original: str, candidate: str | None, context: dict,
                    registry: dict) -> dict:
    decisions = {}
    observed = set()
    if generated.get("decision") == "APPLY" and candidate is not None:
        old, new = workflow_doc(original.encode()), workflow_doc(candidate.encode())
        if old.get("concurrency") != new.get("concurrency"):
            observed.add("P-LIT-CANCEL-STALE")
        for jid, job in new["jobs"].items():
            before = old["jobs"].get(jid, {})
            if before.get("strategy", {}).get("fail-fast", True) != job.get("strategy", {}).get("fail-fast", True):
                observed.add("P-LIT-FAIL-FAST")
            def caches(j):
                return [s for s in j.get("steps", []) if str(s.get("uses", "")).startswith("actions/cache@") or
                        isinstance(s.get("with"), dict) and "cache" in s["with"]]
            if caches(before) != caches(job):
                observed.add("P-LIT-GHA-CACHE")
            if before.get("timeout-minutes") != job.get("timeout-minutes"):
                observed.add("P-LIT-CUSTOM-TIMEOUT")
    for pid, pattern in registry["catalogue"].items():
        # The full exact comparator patch is retained even when it combines
        # mechanisms. Attribution is not permission to strip unwanted hunks.
        decision = "APPLY" if pid in observed else "NO_CHANGE"
        if generated.get("decision") == "ERROR":
            decisions[pid] = {"decision": "GENERATION_ERROR", "generation": generated}
            continue
        proposal = {"pattern_id": pid, "decision": decision,
            "rationale": "Observed ci-cost transformation" if pid in observed else "Pinned ci-cost made no attributable edit for this mechanism",
            "expected_effect": "Unmeasured comparator proposal; evaluate exact emitted bytes",
            "evidence_ids": [], "source_evidence": [context["workflow_path"]],
            "missing_evidence": pattern["required_evidence"] if decision == "APPLY" else [],
            "preconditions": [{"requirement": req, "status": "MISSING", "evidence_paths": [],
                               "rationale": "The tool does not establish this prerequisite; shared independent admission is required"}
                              for req in pattern["required_evidence"]],
            "files": [{"path": context["workflow_path"], "before_sha256": context["workflow_sha256"],
                       "content": candidate}] if decision == "APPLY" else [], "policy": None, "analysis": None}
        proposal["proposal_sha256"] = digest(proposal)
        decisions[pid] = {"decision": decision, "proposal": proposal,
                          "observed_mechanisms": sorted(observed), "combined_treatment": len(observed) > 1}
    return decisions


def generate_comparator(snapshot: Path, output: Path, context: dict, registry: dict,
                        *, generator=generate_ci_cost_candidate) -> dict:
    archive = output / "comparator.json"
    identity = {"source_commit_sha": context["source_commit_sha"], "context_sha256": digest(context),
                "registry_sha256": registry["registry_sha256"]}
    if archive.exists():
        saved = json.loads(archive.read_text(encoding="utf-8"))
        if saved["identity"] != identity:
            raise ValueError("Comparator identity changed")
        return saved
    generation = generator(snapshot, version="1.0.0")
    candidate = None
    if generation.get("decision") == "APPLY":
        if (generation.get("before_sha256")!=context["workflow_sha256"] or
                generation.get("source_commit_sha")!=context["source_commit_sha"]):
            raise ValueError("Comparator provenance differs from pinned source")
        folder = (snapshot / generation["candidate_relative_dir"]).resolve()
        if not folder.is_relative_to((snapshot / "candidates").resolve()):
            raise ValueError("Comparator artifact escaped snapshot")
        artifact = folder / generation["generated_artifact"]
        raw = artifact.read_bytes()
        if digest(raw) != generation["after_sha256"]:
            raise ValueError("Comparator artifact checksum differs from generator output")
        candidate = raw.decode("utf-8-sig")
    result = {"identity": identity, "generation": generation,
              "patterns": adapt_candidate(generation, context["original_workflow"], candidate, context, registry)}
    write_json_immutable(archive, result)
    return result
