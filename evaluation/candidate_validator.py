"""Common conservative candidate gate for both rule-based and RAG arms.

This is an admission gate, not a mathematical proof of CI equivalence. A
candidate requiring judgment is REVIEW_REQUIRED and is never auto-dispatched.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess

import yaml
from pathlib import Path

from evaluation.repository_preparation import workflow_doc, safety_findings


class CandidateValidationError(ValueError):
    pass


FORBIDDEN_STEP_KEYS = {"continue-on-error"}


def _actionlint(data: bytes, executable: str | None = None) -> dict:
    executable = executable or shutil.which("actionlint")
    if not executable:
        return {"status": "INCONCLUSIVE", "reason": "actionlint not installed"}
    try:
        p = subprocess.run([executable, "-"], input=data, capture_output=True,
                           check=False, timeout=90)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "INCONCLUSIVE", "reason": type(exc).__name__}
    return {"status": "PASS" if p.returncode == 0 else "FAIL",
            "reason": (p.stdout + p.stderr).decode("utf-8", "replace")[-3000:]}


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
    if lint["status"] != "PASS":
        reasons.append("ACTIONLINT_" + lint["status"])
    return {"verdict": "PASS" if not reasons else "FAIL",
            "reasons": reasons, "actionlint": lint}


def validate_candidate(original: bytes, candidate: bytes, *, actionlint: str | None = None) -> dict:
    """Reject changes to observable CI coverage; allow only additive caching.

    Conservative by design: even a valid concurrency/timeout optimization needs
    separate change-specific approval. This gate treats both B and C alike.
    """
    reasons: list[str] = []
    try:
        before, after = workflow_doc(original), workflow_doc(candidate)
    except (ValueError, TypeError, UnicodeError, yaml.YAMLError) as exc:
        return {"verdict": "FAIL", "reasons": ["INVALID_YAML: " + str(exc)],
                "actionlint": {"status": "NOT_RUN"}}
    if before == after:
        return {"verdict": "NO_CHANGE", "reasons": [], "actionlint": {"status": "NOT_RUN"}}
    if safety_findings(after):
        reasons.append("UNSAFE_WORKFLOW:" + ",".join(safety_findings(after)))
    if set(before) != set(after):
        reasons.append("TOP_LEVEL_KEYS_CHANGED")
    # In the initial hosted evaluation protocol, require exactly the same
    # trigger, permissions, jobs, matrix, runner, dependencies and commands.
    for key in set(before) | set(after):
        if key not in {"jobs"} and before.get(key) != after.get(key):
            reasons.append("CHANGED_TOP_LEVEL:" + str(key))
    pre_jobs, post_jobs = before.get("jobs", {}), after.get("jobs", {})
    if set(pre_jobs) != set(post_jobs):
        reasons.append("JOB_IDS_CHANGED")
    for jid in sorted(set(pre_jobs) & set(post_jobs)):
        old, new = pre_jobs[jid], post_jobs[jid]
        if set(old) != set(new):
            reasons.append("JOB_FIELDS_CHANGED:" + jid)
        for key in set(old) | set(new):
            if key != "steps" and old.get(key) != new.get(key):
                reasons.append("CHANGED_JOB_FIELD:" + jid + ":" + str(key))
        old_steps = old.get("steps", [])
        new_steps = new.get("steps", [])
        # A valid additive caching proposal retains original steps in their
        # original order; no command, checkout, permissions, or test may change.
        pos = 0
        for step in new_steps:
            if pos < len(old_steps) and step == old_steps[pos]:
                pos += 1
            elif (set(step) == {"name", "uses", "with"} and
                  step.get("uses") == "actions/cache@v4" and
                  isinstance(step.get("with"), dict) and
                  isinstance(step["with"].get("path"), str) and
                  isinstance(step["with"].get("key"), str) and
                  # No broad restore keys or unpinned cache keys: dependency
                  # changes must invalidate the cache to preserve CI behavior.
                  set(step["with"]) == {"path", "key"} and
                  "${{ runner.os }}" in step["with"]["key"] and
                  "hashFiles(" in step["with"]["key"] and
                  "**" not in step["with"]["path"] and
                  not re.search(r"(^|/)\.{2}(/|$)", step["with"]["path"]) and
                  step["with"]["path"].strip() in {
                      "node_modules", "~/.npm", "~/.cache/pip", "~/.cargo/registry",
                      "~/.cargo/git", "~/.gradle/caches", "~/.m2/repository"
                  }):
                continue
            else:
                reasons.append("UNAPPROVED_STEP_EDIT:" + jid)
                break
        if pos != len(old_steps):
            reasons.append("REQUIRED_STEP_REMOVED:" + jid)
    lint = _actionlint(candidate, actionlint)
    if lint["status"] != "PASS":
        reasons.append("ACTIONLINT_" + lint["status"])
    # Non-allowlisted optimization mechanisms require manual review rather
    # than silently weakening protections in the name of efficiency.
    verdict = "FAIL" if any(s.startswith(("INVALID", "UNSAFE", "ACTIONLINT_FAIL")) for s in reasons) else ("REVIEW_REQUIRED" if reasons else "PASS")
    return {"verdict": verdict, "reasons": sorted(set(reasons)), "actionlint": lint,
            "equivalence_scope": "conservative additive cache only; runtime safety is verified on GitHub"}
