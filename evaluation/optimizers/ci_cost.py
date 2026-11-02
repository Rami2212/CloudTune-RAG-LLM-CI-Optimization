"""Arm B: archive candidates from reviewed, source-corrected ci-cost.

Upstream source defects are corrected before TypeScript compilation, never by
changing generated workflow YAML. This is an explicitly labelled, patched
ci-cost baseline. No fork or GitHub Actions run occurs at this stage.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import tempfile
import time
from hashlib import sha256
from pathlib import Path
from typing import Callable

import yaml

from evaluation.repository_preparation import WORKFLOW_PATH, workflow_doc, write_immutable, write_json_immutable
from evaluation.third_party.ci_cost.setup import isolate_npm_config, verify_installation
from evaluation.third_party.ci_cost.source_fixes import FIX_REVISION, fix_identity

PINNED_VERSION = "1.0.0"
# The source is pinned to the upstream commit and corrected using a separately
# versioned source-fix specification. The original upstream B result, if any,
# is preserved and never silently overwritten.
PINNED_SOURCE_COMMIT = "e3722ea83da600bebac9ad21ec52490df824eb5c"
DEFAULT_TOOL_DIR = Path(os.environ.get("CI_COST_DIR", str(Path(__file__).resolve().parents[2] / ".venv" / "ci-cost")))
TOOL_TIMEOUT_SECONDS = 180
MAX_OUTPUT_BYTES = 2_000_000


def _hash(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _environment() -> dict[str, str]:
    """Allow npm/Node to execute without inheriting research API credentials.

    This is credential minimization, not a security sandbox for third-party code.
    """
    result = {
        key: val for key, val in os.environ.items()
        if not re.search(r"(TOKEN|SECRET|PASSWORD|API_KEY|PRIVATE_KEY|CREDENTIAL|AUTH)", key, re.I)
        and key.upper() not in {"CI_COST_DIR", "NODE_OPTIONS", "NPM_CONFIG_USERCONFIG", "NPM_CONFIG_GLOBALCONFIG"}
    }
    # Individual subprocesses supply distinct, empty npmrc files in their
    # temporary workspace. Never reuse the caller's npm authentication files.
    result["CI"] = "true"
    return result


def _diff(original: bytes, optimized: bytes, workflow_path: str) -> bytes:
    before = original.decode("utf-8-sig").splitlines(keepends=True)
    after = optimized.decode("utf-8-sig").splitlines(keepends=True)
    return "".join(difflib.unified_diff(before, after,
        fromfile="a/" + workflow_path, tofile="b/" + workflow_path)).encode("utf-8")


def _recommendation_audit(original: bytes, generated: bytes) -> dict:
    """Compare *claims* in ci-cost's header against observed YAML edits.

    Upstream prints recommendations as if they were applied, even when its
    transformer leaves the corresponding field unchanged. This metadata is
    diagnostic only: it does not modify YAML, grant admission, or establish
    any measured savings. Unknown recommendation types remain UNVERIFIED.
    """
    before, after = workflow_doc(original), workflow_doc(generated)
    text = generated.decode("utf-8-sig")
    claims = re.findall(r"(?m)^# - \[[^]\n]+\] ([^\r\n]+)$", text)
    estimate = re.search(r"(?m)^# Estimated savings: ([^\r\n]+)$", text)

    before_jobs, after_jobs = before.get("jobs", {}), after.get("jobs", {})

    def steps(job: dict) -> list[dict]:
        return [step for step in job.get("steps", []) if isinstance(step, dict)]

    def cached_steps(job: dict) -> list[dict]:
        return [step for step in steps(job) if
                str(step.get("uses", "")).startswith("actions/cache@") or
                (isinstance(step.get("with"), dict) and "cache" in step["with"])]

    def commands(job: dict) -> list[str]:
        return [step["run"] for step in steps(job) if isinstance(step.get("run"), str)]

    added_cache = False
    npm_install_replaced = False
    fail_fast_changed = False
    shallow_clone_changed = False
    for job_id in before_jobs.keys() & after_jobs.keys():
        old, new = before_jobs[job_id], after_jobs[job_id]
        # A modification of an existing cache is not a newly added cache.
        added_cache |= len(cached_steps(new)) > len(cached_steps(old))
        # Align run steps independently of added action steps, preserving order.
        old_commands, new_commands = commands(old), commands(new)
        npm_install_replaced |= (len(old_commands) == len(new_commands) and any(
            re.search(r"\bnpm install\b", previous) and
            re.search(r"\bnpm ci\b", current) and previous != current
            for previous, current in zip(old_commands, new_commands)))
        old_strategy, new_strategy = old.get("strategy", {}), new.get("strategy", {})
        if isinstance(old_strategy, dict) and isinstance(new_strategy, dict):
            fail_fast_changed |= (old_strategy.get("fail-fast") != new_strategy.get("fail-fast")
                                  and new_strategy.get("fail-fast") is True)
        old_checkouts = [step.get("with", {}).get("fetch-depth") for step in steps(old)
                         if str(step.get("uses", "")).startswith("actions/checkout@")
                         and isinstance(step.get("with", {}), dict)]
        new_checkouts = [step.get("with", {}).get("fetch-depth") for step in steps(new)
                         if str(step.get("uses", "")).startswith("actions/checkout@")
                         and isinstance(step.get("with", {}), dict)]
        shallow_clone_changed |= old_checkouts != new_checkouts

    observed = {
        "concurrency_changed": ("concurrency" not in before and "concurrency" in after),
        "dependency_cache_added": added_cache,
        "npm_install_replaced_with_npm_ci": npm_install_replaced,
        "fail_fast_changed": fail_fast_changed,
        "checkout_fetch_depth_changed": shallow_clone_changed,
    }
    checks = []
    for claim in claims:
        lower = claim.lower()
        if "concurrency" in lower:
            key = "concurrency_changed"
        elif "npm ci" in lower and "npm install" in lower:
            key = "npm_install_replaced_with_npm_ci"
        elif "fail-fast" in lower:
            key = "fail_fast_changed"
        elif "shallow" in lower or "fetch-depth" in lower:
            key = "checkout_fetch_depth_changed"
        elif "cache" in lower:
            key = "dependency_cache_added"
        else:
            key = None
        checks.append({"recommendation": claim, "matched_observation": key,
                       "status": ("OBSERVED" if observed[key] else "NOT_OBSERVED")
                       if key else "UNVERIFIED"})
    return {
        "reported_recommendations": claims,
        "reported_estimated_savings": estimate.group(1).strip() if estimate else None,
        "reported_estimate_is_measured": False,
        "observed_transformations": observed,
        "recommendation_checks": checks,
        "unobserved_reported_recommendations": [item["recommendation"] for item in checks
                                                  if item["status"] == "NOT_OBSERVED"],
        "audit_scope": "Known ci-cost recommendation categories; not admission or runtime evidence",
    }


def generate_ci_cost_candidate(
    snapshot_dir: Path,
    *,
    version: str = PINNED_VERSION,
    command_runner: Callable = subprocess.run,
    timeout_seconds: int = TOOL_TIMEOUT_SECONDS,
    tool_dir: Path | None = None,
) -> dict:
    """Run the source-corrected pinned ci-cost on one frozen workflow.

    Exit code 1 is not automatically a failure: ci-cost returns 1 whenever it
    detects high-severity opportunities, including when --fix succeeds.
    """
    if version != PINNED_VERSION:
        raise ValueError(f"Only the reviewed ci-cost version {PINNED_VERSION} is supported")
    manifest_path = snapshot_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    workflow_path = manifest["workflow_path"]
    if not WORKFLOW_PATH.fullmatch(workflow_path):
        raise ValueError("Manifest contains an invalid selected workflow path")
    if manifest.get("status") not in {"prepared", "needs_harness"}:
        raise ValueError("Arm B requires an eligible frozen repository snapshot")
    original = (snapshot_dir / "source" / "original.yml").read_bytes()
    if _hash(original) != manifest["workflow_sha256"]:
        raise ValueError("Frozen Arm A workflow hash does not match manifest")
    workflow_doc(original)
    target = snapshot_dir / "candidates" / "B" / FIX_REVISION
    existing = target / "candidate.json"
    if existing.exists():
        saved = json.loads(existing.read_text(encoding="utf-8"))
        if (saved.get("source_commit_sha") != manifest["source_commit_sha"] or
                saved.get("before_sha256") != _hash(original) or
                saved.get("tool_version") != version or
                saved.get("tool_source_commit") != PINNED_SOURCE_COMMIT or
                saved.get("tool_source_fix_revision") != FIX_REVISION or
                saved.get("tool_source_fix_sha256") != fix_identity()):
            raise ValueError("Existing Arm B candidate uses different source/tool provenance; use a new evaluation_id")
        artifact = saved.get("generated_artifact")
        if artifact and (not (target / artifact).exists() or
                         _hash((target / artifact).read_bytes()) != saved.get("generated_sha256")):
            raise ValueError("Previously archived ci-cost artifact is missing or was modified")
        return saved

    # Resolve the real checked-out executable directly; do not invoke npx.
    # This avoids fetching an unpublished package and preserves the reviewed Git SHA.
    tool_dir = (tool_dir or DEFAULT_TOOL_DIR).resolve()
    command = ["node", str(tool_dir / "dist" / "index.js")]
    outcome = {
        "arm": "ci_cost", "decision": "ERROR", "status": "GENERATION_ERROR",
        "tool": "ci-cost", "tool_version": version,
        "package_spec": "https://github.com/mariotavarez/ci-cost",
        "tool_source_commit": PINNED_SOURCE_COMMIT,
        "tool_source_fix_revision": FIX_REVISION,
        "candidate_relative_dir": f"candidates/B/{FIX_REVISION}",
        "tool_source_fix_sha256": fix_identity(),
        "tool_lock_sha256": None,
        "tool_file_hashes": None,
        "package_integrity": "PINNED_GIT_COMMIT_AND_REVIEWED_COMPILED_SOURCE_FIX",
        "source_commit_sha": manifest["source_commit_sha"],
        "workflow_path": workflow_path, "before_sha256": _hash(original),
        "after_sha256": _hash(original), "generated_artifact": None,
        "generated_sha256": None, "semantic_changed": False,
        "required_checks_status": "not_verified", "safety_verdict": "NOT_CHECKED",
        "execution_status": "NOT_EXECUTED", "optimizer_seconds": 0.0,
        "exit_code": None, "error": None, "recommendation_audit": None,
    }
    stdout = ""
    stderr = ""
    generated: bytes | None = None
    started = time.monotonic()
    try:
        # The setup verifier checks the exact pinned Git SHA, approved tracked
        # source changes and rebuilt output hashes before running the CLI.
        provenance = verify_installation(tool_dir)
        outcome["tool_lock_sha256"] = provenance["upstream_lock_sha256"]
        outcome["tool_file_hashes"] = provenance["file_hashes"]
        with tempfile.TemporaryDirectory(prefix="cloudtune-ci-cost-") as directory:
            root = Path(directory)
            workflow_dir = root / ".github" / "workflows"
            workflow_dir.mkdir(parents=True)
            target_file = workflow_dir / Path(workflow_path).name
            target_file.write_bytes(original)
            opts = {"cwd": str(root), "env": isolate_npm_config(_environment(), root),
                    "capture_output": True,
                    "text": True, "timeout": timeout_seconds, "check": False}
            version_run = command_runner([*command, "--version"], **opts)
            version_output = (version_run.stdout or "").strip()
            if (version_run.returncode != 0 or
                    not re.fullmatch(r"ci-cost\s+v?" + re.escape(version), version_output)):
                raise RuntimeError(f"Expected ci-cost {version}, got {version_output[:150]!r} "+
                                   f"(exit {version_run.returncode})")
            args = [*command, "--fix", "--dir=" + str(workflow_dir)]
            proc = command_runner(args, **opts)
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            outcome["exit_code"] = proc.returncode
            generated_path = workflow_dir / "optimized" / target_file.name
            if generated_path.is_symlink():
                raise RuntimeError("ci-cost output is an unexpected symlink")
            if generated_path.is_file():
                generated = generated_path.read_bytes()
                if len(generated) > MAX_OUTPUT_BYTES:
                    raise RuntimeError("ci-cost generated an oversized workflow")
                outcome["generated_artifact"] = "optimized.yml"
                outcome["generated_sha256"] = _hash(generated)
                outcome["after_sha256"] = _hash(generated)
            if proc.returncode not in (0, 1):
                raise RuntimeError(f"ci-cost failed with exit code {proc.returncode}")
            # Upstream may catch its own --fix errors and still exit 0.
            if "Error generating optimized files:" in stderr or "Error:" in stderr:
                raise RuntimeError("ci-cost reported a generation error")
            # ci-cost also exits 1 for a HIGH recommendation it could not fix.
            # That is a valid NO_CHANGE, provided analysis completed normally.
            if (proc.returncode == 1 and generated is None and
                    ("Found 1 workflow" not in stdout or "Error:" in stderr)):
                raise RuntimeError("ci-cost exited 1 without successful analysis or a generated workflow")
            if target_file.read_bytes() != original:
                raise RuntimeError("ci-cost unexpectedly modified the input workflow")
            if generated is not None:
                # Header comments alone are not an applied optimization.
                changed = workflow_doc(original) != workflow_doc(generated)
                outcome["semantic_changed"] = changed
                # Keep upstream's exact output, but archive an independent
                # observation of which advertised changes really occurred.
                outcome["recommendation_audit"] = _recommendation_audit(original, generated)
                outcome["decision"] = "APPLY" if changed else "NO_CHANGE"
            else:
                outcome["decision"] = "NO_CHANGE"
            outcome["status"] = "GENERATED_NOT_VALIDATED"
    except (OSError, subprocess.TimeoutExpired, RuntimeError, UnicodeError, ValueError, yaml.YAMLError) as error:
        outcome["error"] = f"{type(error).__name__}: {error}"[:600]
    finally:
        outcome["optimizer_seconds"] = round(time.monotonic() - started, 6)

    # Preserve original generated bytes, even when YAML is invalid, for audit.
    if generated is not None:
        write_immutable(target / "optimized.yml", generated)
        # Diff remains optional for invalid non-UTF-8 output, which is still
        # retained verbatim as evidence of a failed generator candidate.
        try:
            write_immutable(target / "change.patch", _diff(original, generated, workflow_path))
        except UnicodeError:
            pass
    write_immutable(target / "ci_cost.stdout.txt", stdout.encode("utf-8")[:MAX_OUTPUT_BYTES])
    write_immutable(target / "ci_cost.stderr.txt", stderr.encode("utf-8")[:MAX_OUTPUT_BYTES])
    write_json_immutable(target / "candidate.json", outcome)
    return outcome
