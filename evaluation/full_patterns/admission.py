"""Shared structural checks and source-bound review for any pattern proposal.

Review establishes eligibility for a scenario, never evidence of measured benefit.
No branch, fork or CI run is created here.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import yaml

from evaluation.candidate_validator import _actionlint
from evaluation.repository_preparation import safety_findings, workflow_doc, write_json_immutable
from . import PROTOCOL
from .context import safe_path
from .proposals import validate_proposal
from .registry import digest, measurement_plan
from .progress import progress

POLICY = "full-pattern-shared-review-v1"


def review_identity(proposal: dict, context: dict, registry: dict, *, arm: str) -> dict:
    if arm not in {"B", "C", "D"}:
        raise ValueError("Review arm must be B, C or D")
    return {"protocol": PROTOCOL, "policy_revision": POLICY, "arm": arm,
            "proposal_sha256": proposal["proposal_sha256"],
            "source_commit_sha": context["source_commit_sha"],
            "context_sha256": digest(context), "registry_sha256": registry["registry_sha256"]}


def review_template(proposal: dict, context: dict, registry: dict, *, arm: str = "C") -> dict:
    pattern = registry["catalogue"][proposal["pattern_id"]]
    obligations = pattern["required_evidence"] + ["safety_test:" + x for x in pattern["safety_tests"]]
    return {"identity": review_identity(proposal, context, registry, arm=arm),
            "verdict": "UNDECIDED", "reviewer": "", "reviewed_at": "",
            "checks": [{"requirement": x, "status": "UNVERIFIED", "rationale": "", "evidence": []}
                       for x in obligations],
            "note": "Approval authorizes scenario evaluation only; it is not a measured-success claim."}


def verify_review(review: dict, expected: dict, *, review_root: Path) -> bool:
    if review.get("identity") != expected["identity"]:
        raise ValueError("Review is stale or belongs to a different arm/source/candidate/policy")
    if review.get("verdict") not in {"APPROVE", "REJECT"}:
        raise ValueError("Review verdict must be APPROVE or REJECT")
    if not isinstance(review.get("reviewer"), str) or not review["reviewer"].strip():
        raise ValueError("Review must identify the reviewer")
    # Require a UTC timestamp; it is audit metadata, not an authentication claim.
    if not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", str(review.get("reviewed_at", ""))):
        raise ValueError("Review timestamp must be YYYY-MM-DDTHH:MM:SSZ")
    if review["verdict"] == "REJECT":
        return False
    checks = review.get("checks")
    required = {x["requirement"] for x in expected["checks"]}
    if (not isinstance(checks, list) or len(checks) != len(required) or
            any(not isinstance(c, dict) for c in checks) or {c.get("requirement") for c in checks} != required):
        raise ValueError("Approval must address every evidence and safety requirement")
    for check in checks:
        if check.get("status") != "VERIFIED" or not isinstance(check.get("rationale"), str) or not check["rationale"].strip():
            raise ValueError("Approval contains an unverified requirement")
        evidence = check.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError("Approval requires actual hashed evidence artifacts")
        for item in evidence:
            if not isinstance(item, dict):
                raise ValueError("Review evidence must be a path/hash object")
            safe_path(item.get("path"))
            from .context import read_source
            if digest(read_source(review_root, item["path"])) != item.get("sha256"):
                raise ValueError("Review evidence artifact changed")
    return True


def validate_treatment(proposal: dict, context: dict, registry: dict, evidence: list[dict],
                       *, arm: str = "C", review: dict | None = None,
                       review_root: Path | None = None, actionlint: str | None = None) -> dict:
    pattern = registry["catalogue"][proposal["pattern_id"]]
    if any(not isinstance(row, dict) or row.get("pattern_id") != pattern["pattern_id"] or
           row.get("document_id") not in registry["documents"] or
           registry["documents"][row["document_id"]]["pattern_id"] != pattern["pattern_id"] for row in evidence):
        raise ValueError("Admission evidence differs from frozen pattern corpus")
    raw = {k: v for k, v in proposal.items() if k != "proposal_sha256"}
    checked = validate_proposal(raw, pattern, context, evidence,
                                require_citations=arm != "B", require_supported=arm != "B")
    if checked["proposal_sha256"] != proposal.get("proposal_sha256"):
        raise ValueError("Proposal checksum differs from source-bound payload")
    identity = review_identity(proposal, context, registry, arm=arm)
    result = {"identity": identity, "measurement_plan": measurement_plan(pattern),
              "ci_dispatches": 0, "checks": [], "reasons": []}
    if proposal["decision"] not in {"APPLY", "ANALYZE"}:
        return {**result, "verdict": proposal["decision"]}
    workflow_path = context["workflow_path"]
    semantic_change = bool(proposal.get("policy") or proposal.get("analysis"))
    for item in proposal["files"]:
        path = item["path"]
        if path == workflow_path or (path.startswith(".github/workflows/") and path.endswith((".yml", ".yaml"))):
            try:
                doc = workflow_doc(item["content"].encode())
                original_text = context["original_workflow"] if path == workflow_path else next(
                    x["text"] for x in context["files"] if x["path"] == path)
                old_doc = workflow_doc(original_text.encode())
            except (ValueError, TypeError, UnicodeError, yaml.YAMLError) as exc:
                return {**result, "verdict": "INVALID", "reasons": ["INVALID_WORKFLOW:" + str(exc)]}
            def events(document):
                value=document.get("on")
                return {value} if isinstance(value,str) else set(value) if isinstance(value,(list,dict)) else set()
            if (events(doc)-events(old_doc)) & {"pull_request_target","workflow_run","repository_dispatch"}:
                return {**result,"verdict":"INVALID","reasons":["NEW_PRIVILEGED_TRIGGER"]}
            if doc.get("permissions")!=old_doc.get("permissions"):
                return {**result,"verdict":"INVALID","reasons":["PERMISSION_SCOPE_CHANGED"]}
            for jid,job in doc["jobs"].items():
                previous=old_doc["jobs"].get(jid,{})
                if job.get("permissions")!=previous.get("permissions"):
                    return {**result,"verdict":"INVALID","reasons":["JOB_PERMISSION_SCOPE_CHANGED:"+jid]}
                if job.get("continue-on-error") and not previous.get("continue-on-error"):
                    return {**result,"verdict":"INVALID","reasons":["NEW_FAILURE_MASKING:"+jid]}
                old_masked=sum(bool(s.get("continue-on-error")) for s in previous.get("steps",[]))
                new_masked=sum(bool(s.get("continue-on-error")) for s in job.get("steps",[]))
                if new_masked>old_masked:
                    return {**result,"verdict":"INVALID","reasons":["NEW_STEP_FAILURE_MASKING:"+jid]}
            findings = sorted(set(safety_findings(doc)) - set(safety_findings(old_doc)))
            if findings:
                return {**result, "verdict": "INVALID", "reasons": ["NEW_UNSAFE_WORKFLOW:" + x for x in findings]}
            lint = _actionlint(item["content"].encode(), actionlint)
            result["checks"].append({"path": path, "actionlint": lint})
            if lint["status"] != "PASS":
                return {**result, "verdict": "INVALID" if lint["status"] == "FAIL" else "INCONCLUSIVE",
                        "reasons": ["ACTIONLINT_" + lint["status"]]}
            semantic_change |= doc != old_doc
        else:
            semantic_change = True
    if not semantic_change:
        return {**result, "verdict": "NO_SEMANTIC_CHANGE", "reasons": ["COMMENTS_OR_FORMATTING_ONLY"]}
    # Every pattern can reach review. Neither a model's SUPPORTED claims nor a
    # valid YAML parse can establish selection, reuse or infrastructure safety.
    template = review_template(proposal, context, registry, arm=arm)
    if review is None:
        return {**result, "verdict": "REVIEW_REQUIRED",
                "reasons": ["MECHANISM_EVIDENCE_AND_CONTRACT_REVIEW_REQUIRED"]}
    if review_root is None:
        raise ValueError("Review evidence root is required")
    approved = verify_review(review, template, review_root=review_root)
    return {**result, "verdict": "READY_FOR_SCENARIO" if approved else "REJECTED",
            "review_sha256": digest(review)}


def validate_output(output: Path, registry: dict, *, reviews: Path | None = None,
                    arm: str = "C") -> dict:
    context = json.loads((output / "context.json").read_text(encoding="utf-8"))
    identity = json.loads((output / "identity.json").read_text(encoding="utf-8"))
    if identity["context_sha256"] != digest(context) or identity["registry_sha256"] != registry["registry_sha256"]:
        raise ValueError("Validation context/corpus identity changed")
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    if report.get("identity") != identity:
        raise ValueError("Report identity differs from frozen generation")
    outcomes = report.get("outcomes")
    if (not isinstance(outcomes, list) or len(outcomes) != len(registry["catalogue"]) or
            any(not isinstance(row, dict) for row in outcomes) or
            {row.get("pattern_id") for row in outcomes} != set(registry["catalogue"])):
        raise ValueError("Report must retain every catalogue disposition")
    results = []
    for row in report["outcomes"]:
        pid = row["pattern_id"]
        if "proposal_path" not in row:
            progress("VALIDATION",f"{pid}: arm={arm}; verdict={row['decision']}; no generated treatment")
            results.append({"pattern_id": pid, "verdict": row["decision"]})
            continue
        folder = output / "patterns" / pid
        proposal = json.loads((folder / "proposal.json").read_text(encoding="utf-8"))
        if row["proposal_sha256"] != proposal.get("proposal_sha256"):
            raise ValueError("Report points to a different proposal")
        retrieval = json.loads((folder / "retrieval.json").read_text(encoding="utf-8"))
        template = review_template(proposal, context, registry, arm=arm)
        write_json_immutable(folder / f"review_template_{arm}.json", template)
        review_file = reviews / f"{pid}.json" if reviews else None
        review = json.loads(review_file.read_text(encoding="utf-8")) if review_file and review_file.exists() else None
        verdict = validate_treatment(proposal, context, registry, retrieval["results"], arm=arm,
                                     review=review, review_root=reviews)
        progress("VALIDATION",f"{pid}: arm={arm}; verdict={verdict['verdict']}; reasons={','.join(verdict.get('reasons',[])) or 'none'}")
        suffix = "unreviewed" if review is None else digest(review)[:16]
        write_json_immutable(folder / f"admission_{arm}_{suffix}.json", verdict)
        results.append({"pattern_id": pid, **verdict})
    return {"protocol": PROTOCOL, "policy_revision": POLICY, "results": results, "ci_dispatches": 0}
