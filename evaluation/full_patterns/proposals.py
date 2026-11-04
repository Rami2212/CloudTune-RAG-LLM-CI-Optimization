"""Strict full-pattern output contracts; model assertions are not safety proofs."""
from __future__ import annotations

from .context import safe_path, SECRET
from .registry import digest

ASSESSMENTS = {"APPLICABLE", "ALREADY_IMPLEMENTED", "NOT_APPLICABLE", "MISSING_EVIDENCE"}
DECISIONS = {"APPLY", "NO_CHANGE", "MISSING_EVIDENCE", "UNSUPPORTED_EXECUTION", "ANALYZE"}


def evidence_paths(context: dict) -> set[str]:
    """Verified supplementary artifacts are citable, never editable source files."""
    paths=set(context["included_paths"])|{context["workflow_path"]}
    for fact in context.get("mechanism_evidence",{}).get("facts",{}).values():
        for artifact in fact.get("artifacts",[]):
            paths.add(artifact["path"])
    return paths


def text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(field + " must contain substantive text")
    return value


def strings(value, field, *, allowed=None, nonempty=False):
    if (not isinstance(value, list) or any(not isinstance(v, str) or not v.strip() for v in value)
            or len(value) != len(set(value)) or (nonempty and not value)):
        raise ValueError(field + " must be an array of unique nonempty strings")
    if allowed is not None and not set(value) <= set(allowed):
        raise ValueError(field + " references unavailable evidence")
    return value


def validate_assessments(reply: dict, catalogue: dict, context: dict) -> list[dict]:
    rows = reply.get("assessments") if isinstance(reply, dict) else None
    if not isinstance(rows, list) or len(rows) != len(catalogue):
        raise ValueError("Applicability must assess all 25 patterns exactly once")
    seen = set()
    allowed_paths = evidence_paths(context)
    for row in rows:
        if not isinstance(row, dict) or row.get("pattern_id") not in catalogue or row["pattern_id"] in seen:
            raise ValueError("Duplicate or unknown pattern assessment")
        seen.add(row["pattern_id"])
        if row.get("status") not in ASSESSMENTS:
            raise ValueError("Unknown applicability status")
        text(row.get("rationale"), "rationale")
        strings(row.get("evidence_paths"), "evidence_paths", allowed=allowed_paths,
                nonempty=row["status"] == "APPLICABLE")
        strings(row.get("missing_evidence"), "missing_evidence",
                nonempty=row["status"] == "MISSING_EVIDENCE")
        if row["status"] == "APPLICABLE" and row["missing_evidence"]:
            raise ValueError("Applicable assessment cannot have unresolved missing evidence")
    return sorted(rows, key=lambda r: r["pattern_id"])


def validate_proposal(reply: dict, pattern: dict, context: dict, evidence: list[dict],
                      *, require_citations: bool = True, require_supported: bool = True) -> dict:
    if not isinstance(reply, dict) or reply.get("pattern_id") != pattern["pattern_id"]:
        raise ValueError("Proposal pattern differs from requested mechanism")
    decision = reply.get("decision")
    if decision not in DECISIONS:
        raise ValueError("Unknown proposal decision")
    text(reply.get("rationale"), "rationale")
    text(reply.get("expected_effect"), "expected_effect")
    allowed_docs = {x["document_id"] for x in evidence}
    strings(reply.get("evidence_ids"), "evidence_ids", allowed=allowed_docs,
            nonempty=require_citations and decision in {"APPLY", "ANALYZE"})
    paths = evidence_paths(context)
    strings(reply.get("source_evidence"), "source_evidence", allowed=paths,
            nonempty=decision in {"APPLY", "ANALYZE"})
    strings(reply.get("missing_evidence"), "missing_evidence",
            nonempty=decision == "MISSING_EVIDENCE")
    claims = reply.get("preconditions")
    if not isinstance(claims, list) or any(not isinstance(c, dict) for c in claims):
        raise ValueError("Proposal preconditions must be structured claims")
    if (len(claims) != len(pattern["required_evidence"]) or
            {c.get("requirement") for c in claims} != set(pattern["required_evidence"])):
        raise ValueError("Proposal must address every mechanism evidence requirement")
    for claim in claims:
        if claim.get("status") not in {"SUPPORTED", "MISSING", "CONTRADICTED"}:
            raise ValueError("Invalid prerequisite status")
        text(claim.get("rationale"), "prerequisite rationale")
        strings(claim.get("evidence_paths"), "prerequisite evidence_paths", allowed=paths)
    if require_supported and decision in {"APPLY", "ANALYZE"} and (reply["missing_evidence"] or
            any(c["status"] != "SUPPORTED" for c in claims)):
        raise ValueError("Treatment cannot claim applicability with unmet prerequisites")
    files = reply.get("files")
    if not isinstance(files, list):
        raise ValueError("Proposal files must be an array")
    original_files = {x["path"]: x for x in context["files"]}
    original_files[context["workflow_path"]] = {"text": context["original_workflow"],
                                               "sha256": context["workflow_sha256"]}
    seen = set()
    for item in files:
        if not isinstance(item, dict):
            raise ValueError("Proposal file must be an object")
        path = safe_path(item.get("path"))
        if path in seen or path not in original_files:
            raise ValueError("Changed files must be unique frozen inputs; collect new inputs before proposing edits")
        seen.add(path)
        text(item.get("content"), "file content")
        if len(item["content"].encode()) > 262144 or SECRET.search(item["content"]):
            raise ValueError("Proposed content exceeds budget or contains possible credentials")
        if item.get("before_sha256") != original_files[path]["sha256"]:
            raise ValueError("Proposed file before hash differs from frozen source")
        if item["content"] == original_files[path]["text"]:
            raise ValueError("Proposed file contains no change")
    policy, analysis = reply.get("policy"), reply.get("analysis")
    if policy is not None and (not isinstance(policy, dict) or not policy):
        raise ValueError("Policy treatment must be a nonempty object or null")
    if analysis is not None and (not isinstance(analysis, dict) or not analysis):
        raise ValueError("Analytical output must be a nonempty object or null")
    if decision == "ANALYZE":
        if pattern["family"] != "analytical" or files or policy is not None or analysis is None:
            raise ValueError("Analytical pattern requires analysis without a fabricated patch")
    elif decision == "APPLY":
        if pattern["family"] == "analytical" or (not files and policy is None) or analysis is not None:
            raise ValueError("APPLY requires a concrete non-analytical treatment")
    elif files or policy is not None or analysis is not None:
        raise ValueError("Abstention/missing/unsupported outcomes cannot contain a treatment")
    return {**reply, "proposal_sha256": digest(reply)}
