"""Common conservative candidate gate for both rule-based and RAG arms.

This is an admission gate, not a mathematical proof of CI equivalence. A
candidate requiring judgment is REVIEW_REQUIRED and is never auto-dispatched.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import shutil
import subprocess

import yaml
from pathlib import Path

from evaluation.repository_preparation import workflow_doc, safety_findings, write_json_immutable
from evaluation.setup_node_compatibility import setup_node_cache_compatibility, compatibility_digest


class CandidateValidationError(ValueError):
    pass


FORBIDDEN_STEP_KEYS = {"continue-on-error"}

def _setup_node_npm_cache_added(original_step: dict, candidate_step: dict) -> bool:
    """Recognize ONLY reviewed setup-node npm-download-cache additions.

    This is not permission to change an action version, test commands, step
    identity, Node version or arbitrary action inputs. The separate evidence
    gate must still verify a frozen root lockfile and checkout ordering.
    """
    if not isinstance(original_step, dict) or not isinstance(candidate_step, dict):
        return False
    if not setup_node_cache_compatibility(original_step.get("uses"))["supported"]:
        return False
    old_with = original_step.get("with")
    if (not isinstance(old_with, dict) or not old_with.get("node-version")
            or "cache" in old_with or "cache-dependency-path" in old_with):
        return False
    if set(original_step) != set(candidate_step) or not isinstance(candidate_step.get("with"), dict):
        return False
    return (all(candidate_step[key] == value for key, value in original_step.items()
                if key != "with")
            and candidate_step["with"] == {**old_with, "cache": "npm"})


def _original_steps_preserved(original_steps: list, candidate_steps: list) -> bool:
    """Check original-step subsequence independently of unapproved additions.

    An inserted step can be unapproved without deleting any original step.
    An edited/replaced original step, however, is not considered preserved.
    The narrow approved setup-node cache addition counts as preserved.
    """
    position = 0
    for step in candidate_steps:
        if position >= len(original_steps):
            break
        if (step == original_steps[position] or
                _setup_node_npm_cache_added(original_steps[position], step)):
            position += 1
    return position == len(original_steps)


# The cache key must invalidate when the dependencies represented by its path
# change. Matching hashFiles( alone is insufficient: README.md is not a lockfile.
CACHE_DEPENDENCY_GLOBS = {
    "node_modules": ("package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml"),
    "~/.npm": ("package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml"),
    "~/.cache/pip": ("requirements.txt", "requirements*.txt", "poetry.lock", "pdm.lock", "uv.lock", "Pipfile.lock"),
    "~/.cargo/registry": ("Cargo.lock",),
    "~/.cargo/git": ("Cargo.lock",),
    "~/.gradle/caches": ("gradle.lockfile", "libs.versions.toml"),
    "~/.m2/repository": ("pom.xml",),
}


def _cache_key_tracks_dependencies(path: str, key: str) -> bool:
    """Approve explicit runner+dependency hashes, never arbitrary file hashes."""
    if "${{ runner.os }}" not in key:
        return False
    # Conservative, intentionally allow only plain quoted paths. Advanced
    # expressions can be considered in a separately reviewed safety policy.
    hashes = re.findall(r"hashFiles\(\s*['\"]([^'\"]+)['\"]\s*\)", key)
    if not hashes:
        return False
    allowed = CACHE_DEPENDENCY_GLOBS[path]
    return any(glob == known or (glob.startswith("**/") and glob[3:] == known)
               for glob in hashes for known in allowed)


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


def validate_candidate(original: bytes, candidate: bytes, *, actionlint: str | None = None,
                       isolated_serial_dispatch: bool = False) -> dict:
    """Reject changes to observable CI coverage; allow only additive caching.

    General callers require review for concurrency/timeout edits. The isolated
    serial fork protocol may allow one exact branch-scoped concurrency addition.
    This gate treats both B and C alike.
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
    # The fork evaluator uses unique arm refs and waits for each run to finish
    # before dispatching another. This exact group cannot cancel a peer arm or
    # another repetition under that protocol. General callers remain strict.
    concurrency_allowed = (isolated_serial_dispatch and "concurrency" not in before
                           and after.get("concurrency") == {
                               "group": "${{ github.workflow }}-${{ github.ref }}",
                               "cancel-in-progress": True})
    ignored = {"concurrency"} if concurrency_allowed else set()
    if set(before) - ignored != set(after) - ignored:
        reasons.append("TOP_LEVEL_KEYS_CHANGED")
    # In the initial fork evaluation protocol, require exactly the same
    # trigger, permissions, jobs, matrix, runner, dependencies and commands.
    for key in set(before) | set(after):
        if key not in {"jobs"} | ignored and before.get(key) != after.get(key):
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
            elif (pos < len(old_steps) and
                  _setup_node_npm_cache_added(old_steps[pos], step)):
                # The original step is still present, with exactly one safe
                # additional input; do not mistake it for a removed step.
                pos += 1
            elif (set(step) == {"name", "uses", "with"} and
                  step.get("uses") == "actions/cache@v4" and
                  isinstance(step.get("with"), dict) and
                  isinstance(step["with"].get("path"), str) and
                  isinstance(step["with"].get("key"), str) and
                  # No broad restore keys or unpinned cache keys: dependency
                  # changes must invalidate the cache to preserve CI behavior.
                  set(step["with"]) == {"path", "key"} and
                  "**" not in step["with"]["path"] and
                  not re.search(r"(^|/)\.{2}(/|$)", step["with"]["path"]) and
                  step["with"]["path"].strip() in CACHE_DEPENDENCY_GLOBS and
                  _cache_key_tracks_dependencies(step["with"]["path"].strip(), step["with"]["key"])):
                continue
            else:
                ref = step.get("uses")
                if (isinstance(ref, str) and ref.startswith("actions/setup-node@")
                        and not setup_node_cache_compatibility(ref)["supported"]):
                    reasons.append("UNREVIEWED_SETUP_NODE_REF:" + jid + ":" + ref)
                reasons.append("UNAPPROVED_STEP_EDIT:" + jid)
                break
        # The fast first-pass match may stop at an *inserted* unapproved
        # step. Rescan the full sequence before claiming an original step was
        # deleted. Keep UNAPPROVED_STEP_EDIT regardless of that diagnosis.
        if pos != len(old_steps) and not _original_steps_preserved(old_steps, new_steps):
            reasons.append("REQUIRED_STEP_REMOVED_OR_MODIFIED:" + jid)
    lint = _actionlint(candidate, actionlint)
    if lint["status"] != "PASS":
        reasons.append("ACTIONLINT_" + lint["status"])
    # Non-allowlisted optimization mechanisms require manual review rather
    # than silently weakening protections in the name of efficiency.
    verdict = "FAIL" if any(s.startswith(("INVALID", "UNSAFE", "ACTIONLINT_FAIL")) for s in reasons) else ("REVIEW_REQUIRED" if reasons else "PASS")
    return {"verdict": verdict, "reasons": sorted(set(reasons)), "actionlint": lint,
            "isolated_serial_concurrency": concurrency_allowed,
            "equivalence_scope": "additive cache; exact branch-scoped concurrency only with isolated serial dispatch; runtime safety is verified on GitHub"}


# Frozen repository evidence and immutable candidate admission records.
POLICY_REVISION = "cloudtune-frozen-cache-v6-isolated-serial-concurrency"
_HASH_EXPRESSION = re.compile(r"hashFiles\(\s*(['\"])([^'\"]+)\1\s*\)")
_EXPRESSION = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _archived_inputs(snapshot: Path) -> tuple[set[str], list[str]]:
    """Verify immutable dependency evidence from the source commit, not HEAD.

    Missing or unarchived lockfiles cannot justify a cache optimization.
    The preparer already bounds archived files and rejects symlinks; verify the
    stored hash again rather than trusting only a filename in a manifest.
    """
    path = snapshot / "source" / "files_manifest.json"
    if not path.is_file():
        return set(), ["FROZEN_INPUT_MANIFEST_MISSING"]
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("archived")
    if not isinstance(entries, list):
        return set(), ["FROZEN_INPUT_MANIFEST_INVALID"]
    present: set[str] = set()
    for row in entries:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            return set(), ["FROZEN_INPUT_MANIFEST_INVALID"]
        relative = row["path"]
        # Never trust path components taken from a persisted JSON artifact.
        if (not relative or relative.startswith("/") or "\\" in relative or ":" in relative
                or any(part in ("", ".", "..") for part in relative.split("/"))):
            return set(), ["FROZEN_INPUT_PATH_UNSAFE"]
        source = snapshot / "source" / "files" / relative
        if (not source.is_file() or source.is_symlink() or
                not re.fullmatch(r"[a-f0-9]{64}", str(row.get("sha256", ""))) or
                _digest(source.read_bytes()) != row["sha256"]):
            return set(), ["FROZEN_INPUT_HASH_MISMATCH"]
        if relative in present:
            return set(), ["FROZEN_INPUT_DUPLICATE"]
        present.add(relative)
    return present, []


def _dependency_key_evidence(cache_path: str, cache_key: str, frozen: set[str]) -> tuple[list[str], list[str]]:
    """Only a runner-specific cache with an actual frozen lockfile can pass."""
    expressions = _EXPRESSION.findall(cache_key)
    if len(expressions) != 2 or expressions[0] != "runner.os":
        return [], ["CACHE_KEY_UNREVIEWED_EXPRESSIONS"]
    match = _HASH_EXPRESSION.fullmatch(expressions[1])
    if not match:
        return [], ["CACHE_KEY_UNREVIEWED_EXPRESSIONS"]
    # No other expressions, separators, dynamic secrets, or GitHub-context input.
    literal = _EXPRESSION.sub("", cache_key)
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{0,120}", literal):
        return [], ["CACHE_KEY_UNREVIEWED_LITERAL"]
    pattern = match.group(2)
    approved = CACHE_DEPENDENCY_GLOBS.get(cache_path, ())
    if not any(pattern == token or pattern == "**/" + token for token in approved):
        return [], ["CACHE_KEY_UNAPPROVED_DEPENDENCY_PATTERN"]
    if pattern.startswith("**/"):
        # The preparer snapshots selected source files, not an exhaustive
        # manifest of every nested lockfile. A repository-wide glob could
        # hash files outside frozen evidence; require manual review.
        return [], ["CACHE_GLOB_SCOPE_REQUIRES_REVIEW"]
    matched = sorted(path for path in frozen if fnmatch.fnmatchcase(path, pattern))
    if not matched:
        return [], ["CACHE_DEPENDENCY_NOT_IN_PINNED_SOURCE"]
    return matched, []


def _cache_evidence(original: bytes, candidate: bytes, frozen: set[str]) -> tuple[list[str], list[str]]:
    """Verify source-bound dependencies for BOTH safe cache mechanisms.

    The strict setup-node case uses the action's built-in npm download cache,
    not node_modules caching. Its default lookup requires a frozen *root*
    package-lock.json or npm-shrinkwrap.json, with unchanged setup-node inputs.
    All other candidate edits retain their existing conservative verdicts.
    """
    before, after = workflow_doc(original), workflow_doc(candidate)
    reasons: list[str] = []
    evidence: list[str] = []
    events = before.get("on")
    event_names = ({events} if isinstance(events, str) else
                   set(events) if isinstance(events, (list, dict)) else set())
    if event_names & {"pull_request_target", "workflow_run", "repository_dispatch"}:
        reasons.append("CACHE_TRIGGER_REQUIRES_INDEPENDENT_REVIEW")
    for job_id, job in after["jobs"].items():
        original_steps = before["jobs"][job_id].get("steps", [])
        cursor = 0
        checkout_seen = False
        for step in job.get("steps", []):
            if cursor < len(original_steps) and step == original_steps[cursor]:
                cursor += 1
                if str(step.get("uses", "")).startswith("actions/checkout@"):
                    checkout_seen = True
                continue
            if (cursor < len(original_steps) and
                    _setup_node_npm_cache_added(original_steps[cursor], step)):
                # setup-node reads the lockfile only after checkout. Reject a
                # seemingly valid edit that cannot initialize its npm cache.
                cursor += 1
                if not checkout_seen:
                    reasons.append("SETUP_NODE_CACHE_BEFORE_CHECKOUT:" + str(job_id))
                # A custom working directory can move the install away from
                # setup-node's default root lockfile. This narrow policy does
                # not approve monorepo/nested install layouts automatically.
                defaults = job.get("defaults", {})
                if (isinstance(defaults, dict) and
                        isinstance(defaults.get("run"), dict) and
                        defaults["run"].get("working-directory")):
                    reasons.append("SETUP_NODE_CACHE_NONROOT_WORKDIR:" + str(job_id))
                locks = sorted(frozen & {"package-lock.json", "npm-shrinkwrap.json"})
                if not locks:
                    reasons.append("SETUP_NODE_NPM_ROOT_LOCKFILE_NOT_FROZEN:" + str(job_id))
                else:
                    evidence.extend(locks)
                # Root npm installation is necessary for this exact cache to
                # be relevant. A nested install with an implicit different
                # dependency graph needs separate, reviewed lockfile mapping.
                following = original_steps[cursor:]
                installs = [item for item in following if isinstance(item, dict)
                            and isinstance(item.get("run"), str)
                            and re.search(r"\bnpm\s+(?:ci|install)\b", item["run"])]
                if not installs:
                    reasons.append("SETUP_NODE_CACHE_NO_NPM_INSTALL:" + str(job_id))
                elif any(item.get("working-directory") for item in installs):
                    reasons.append("SETUP_NODE_CACHE_NONROOT_INSTALL:" + str(job_id))
                continue
            if step.get("uses") != "actions/cache@v4":
                # The common validator has already rejected unknown edits.
                continue
            if not checkout_seen:
                reasons.append("CACHE_BEFORE_CHECKOUT:" + str(job_id))
            path = step["with"]["path"].strip()
            if path == "node_modules":
                # Installed packages/build artifacts may hide changes to
                # dependency install scripts and toolchain behavior.
                reasons.append("CACHE_INSTALLED_ARTIFACTS_NEED_REVIEW:" + str(job_id))
            matches, errors = _dependency_key_evidence(path, step["with"]["key"], frozen)
            reasons.extend(err + ":" + str(job_id) for err in errors)
            evidence.extend(matches)
    return sorted(set(evidence)), sorted(set(reasons))


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
                "setup_node_registry_sha256": compatibility_digest(),
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

    evidence = {"source_manifest": "manifest.json", "frozen_files": "source/files_manifest.json",
                "source_dependency_paths": []}
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
                verdict = validate_candidate(original, candidate, actionlint=actionlint,
                                             isolated_serial_dispatch=True)
                lint = verdict.get("actionlint", {}).get("status")
                if lint == "INCONCLUSIVE" and verdict["verdict"] != "FAIL":
                    verdict = {**verdict, "verdict": "INCONCLUSIVE",
                               "reasons": sorted(set(verdict.get("reasons", []) + ["ACTIONLINT_UNAVAILABLE"]))}
                elif verdict["verdict"] == "PASS":
                    before_doc, after_doc = workflow_doc(original), workflow_doc(candidate)
                    concurrency_only = (verdict.get("isolated_serial_concurrency") and
                                        {k: v for k, v in after_doc.items() if k != "concurrency"} == before_doc)
                    if concurrency_only:
                        evidence["concurrency_scope"] = "unique fork arm refs; one dispatched trial at a time"
                        write_json_immutable(artifact, {**identity, "validation": verdict, "evidence": evidence})
                        return verdict
                    frozen, issues = _archived_inputs(snapshot)
                    if issues:
                        verdict = {**verdict, "verdict": "INCONCLUSIVE", "reasons": issues}
                    else:
                        lockfiles, concerns = _cache_evidence(original, candidate, frozen)
                        evidence["source_dependency_paths"] = lockfiles
                        if concerns or not lockfiles:
                            verdict = {**verdict, "verdict": "REVIEW_REQUIRED",
                                       "reasons": concerns or ["NO_VERIFIED_CACHE_DEPENDENCY"]}
    write_json_immutable(artifact, {**identity, "validation": verdict, "evidence": evidence})
    return verdict
