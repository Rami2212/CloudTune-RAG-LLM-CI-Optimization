"""Shared static candidate checks for the CI-Cost and RAG+LLM arms."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from collections import Counter

import yaml
from pathlib import Path

from evaluation.repository_preparation import workflow_doc, safety_findings, write_json_immutable


class CandidateValidationError(ValueError):
    pass


def _actionlint(data: bytes, executable: str | None = None) -> dict:
    executable = executable or shutil.which("actionlint")
    if not executable:
        return {"status": "INCONCLUSIVE", "reason": "actionlint not installed"}
    try:
        p = subprocess.run([executable, "-"], input=data, capture_output=True,
                           check=False, timeout=90)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "INCONCLUSIVE", "reason": type(exc).__name__}
    output = (p.stdout + p.stderr).decode("utf-8", "replace")[-3000:]
    diagnostics = []
    for line in output.splitlines():
        match = re.match(r"^<stdin>:\d+:\d+:\s*(.*?)\s+\[([^]]+)\]\s*$", line)
        if match:
            diagnostics.append(f"{match.group(1)} [{match.group(2)}]")
    return {"status": "PASS" if p.returncode == 0 else "FAIL",
            "reason": output, "diagnostics": sorted(set(diagnostics))}


def validate_baseline(workflow: bytes, *, actionlint: str | None = None) -> dict:
    """Approve baseline syntax/safe scope before mutating a research fork.

    This static gate is not independent evidence of behavioral equivalence.
    """
    try:
        document = workflow_doc(workflow)
    except (ValueError, TypeError, UnicodeError, yaml.YAMLError) as exc:
        return {"verdict": "FAIL", "reasons": ["INVALID_YAML:" + str(exc)]}
    findings = safety_findings(document)
    lint = _actionlint(workflow, actionlint)
    reasons = ["UNSAFE_WORKFLOW:" + v for v in findings]
    warnings = []
    if lint["status"] != "PASS":
        warnings.append("ACTIONLINT_" + lint["status"])
    return {"verdict": "PASS" if not reasons else "FAIL",
            "reasons": reasons, "warnings": warnings, "actionlint": lint}


def validate_candidate(original: bytes, candidate: bytes, *, actionlint: str | None = None) -> dict:
    """Admit general workflow optimizations after shared static checks.

    No optimization mechanism is allowlisted. The same YAML, actionlint and
    existing unsafe-workflow checks apply to CI-Cost and RAG+LLM candidates.
    Runtime correctness and performance are measured by the hosted CI runs.
    """
    try:
        workflow_doc(original)
        after = workflow_doc(candidate)
    except (ValueError, TypeError, UnicodeError, yaml.YAMLError) as exc:
        return {"verdict": "FAIL", "reasons": ["INVALID_YAML: " + str(exc)],
                "actionlint": {"status": "NOT_RUN"}}
    if original == candidate:
        return {"verdict": "NO_CHANGE", "reasons": [], "actionlint": {"status": "NOT_RUN"}}
    original_findings = set(safety_findings(workflow_doc(original)))
    findings = set(safety_findings(after)) - original_findings
    baseline_lint = _actionlint(original, actionlint)
    lint = _actionlint(candidate, actionlint)
    baseline_diagnostics = Counter(baseline_lint.get("diagnostics", []))
    candidate_diagnostics = Counter(lint.get("diagnostics", []))
    new_diagnostics = sorted(
        diagnostic
        for diagnostic, count in (candidate_diagnostics - baseline_diagnostics).items()
        for _ in range(count)
    )
    if lint["status"] == "FAIL" and not candidate_diagnostics:
        # Do not silently waive a lint failure if actionlint's output format
        # was unexpected and could not be compared with the baseline.
        new_diagnostics = ["unparsed actionlint failure; inspect actionlint.reason"]
    reasons = ["UNSAFE_WORKFLOW:" + finding for finding in findings]
    reasons.extend("ACTIONLINT_NEW:" + diagnostic for diagnostic in new_diagnostics)
    warnings = []
    if lint["status"] == "INCONCLUSIVE":
        warnings.append("ACTIONLINT_" + lint["status"])
    elif lint["status"] != "PASS" and not new_diagnostics:
        warnings.append("ACTIONLINT_PREEXISTING_FINDINGS")
    verdict = "FAIL" if reasons else "PASS"
    return {"verdict": verdict, "reasons": sorted(set(reasons)), "warnings": warnings,
            "actionlint": lint, "baseline_actionlint": baseline_lint,
            "new_actionlint_diagnostics": new_diagnostics,
            "equivalence_scope": "general workflow candidate; static checks plus the same GitHub CI correctness workflow"}


# Frozen repository evidence and immutable candidate admission records.
POLICY_REVISION = "cloudtune-candidate-gate-v10-differential-actionlint"


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def validate_and_archive(snapshot: Path, arm: str, original: bytes, candidate: bytes | None,
                         *, decision: str, generation: dict, actionlint: str | None = None) -> dict:
    """Return the shared admission verdict and persist an immutable record.

    Called before any candidate arm branch is created. Saved evidence is reused
    only with identical source, candidate and policy identity. A new policy must
    use a new evaluation_id, rather than silently rewriting earlier verdicts.
    """
    if arm not in {"B", "C"} or decision not in {"APPLY", "NO_CHANGE", "ERROR"}:
        raise ValueError("Unsupported evaluation arm/decision")
    if decision == "APPLY" and not isinstance(candidate, bytes):
        raise ValueError("APPLY candidate bytes are required")
    if decision != "APPLY" and candidate is not None:
        raise ValueError("Non-APPLY outcome must not have candidate bytes")
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    before_sha = _digest(original)
    if manifest.get("workflow_sha256") != before_sha:
        raise ValueError("Validation source differs from pinned original workflow")
    after_sha = _digest(candidate) if candidate is not None else None
    identity = {"arm": arm, "decision": decision, "policy_revision": POLICY_REVISION,
                "source_commit_sha": manifest["source_commit_sha"],
                "workflow_path": manifest["workflow_path"],
                "before_sha256": before_sha, "after_sha256": after_sha}
    artifact = snapshot / "validation" / arm / "validation.json"
    if artifact.exists():
        stored = json.loads(artifact.read_text(encoding="utf-8"))
        if any(stored.get(k) != value for k, value in identity.items()):
            raise ValueError("Archived validation identity changed; use a new evaluation_id")
        verdict = stored.get("validation")
        if not isinstance(verdict, dict) or verdict.get("verdict") not in {
                "PASS", "FAIL", "REVIEW_REQUIRED", "INCONCLUSIVE", "NO_CHANGE"}:
            raise ValueError("Archived validation verdict missing or invalid")
        return verdict

    evidence = {"source_manifest": "manifest.json", "candidate_policy": POLICY_REVISION}
    if decision == "NO_CHANGE":
        verdict = {"verdict": "NO_CHANGE", "reasons": ["OPTIMIZER_ABSTAINED"]}
    elif decision == "ERROR":
        verdict = {"verdict": "FAIL", "reasons": ["GENERATION_ERROR"]}
    else:
        # The archived generator output must be derived from exactly this
        # selected workflow at the pinned upstream commit.
        location = (snapshot / generation.get("candidate_relative_dir", "") if arm == "B"
                    else snapshot / "candidates" / "C")
        if not location.resolve().is_relative_to((snapshot / "candidates").resolve()):
            raise ValueError("Generator artifact path escaped candidate snapshot")
        archived = location / "candidate.json"
        if not archived.is_file():
            verdict = {"verdict": "FAIL", "reasons": ["GENERATOR_PROVENANCE_MISSING"]}
        else:
            provenance = json.loads(archived.read_text(encoding="utf-8"))
            if (provenance.get("before_sha256") != before_sha or
                    provenance.get("after_sha256") != after_sha or
                    provenance.get("source_commit_sha", provenance.get("source_sha")) !=
                    manifest["source_commit_sha"]):
                verdict = {"verdict": "FAIL", "reasons": ["GENERATOR_PROVENANCE_MISMATCH"]}
            else:
                verdict = validate_candidate(original, candidate, actionlint=actionlint)
                lint = verdict.get("actionlint", {}).get("status")
                if lint == "INCONCLUSIVE" and verdict["verdict"] != "FAIL":
                    verdict = {**verdict, "verdict": "INCONCLUSIVE",
                               "reasons": sorted(set(verdict.get("reasons", []) + ["ACTIONLINT_UNAVAILABLE"]))}
    write_json_immutable(artifact, {**identity, "validation": verdict, "evidence": evidence})
    return verdict
