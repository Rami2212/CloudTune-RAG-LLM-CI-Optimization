"""Arm A: produce a record of the pinned, unchanged CI workflow.

Arm A is not an optimization. Execution and measured baseline runs will be
integrated in the later GitHub Actions execution phase.
"""
from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path


def original_candidate(snapshot_dir: Path) -> dict:
    """Verify the prepared source snapshot and describe its unchanged A candidate."""
    manifest = json.loads((snapshot_dir / "manifest.json").read_text(encoding="utf-8"))
    original_path = snapshot_dir / "source" / "original.yml"
    original_bytes = original_path.read_bytes()
    if sha256(original_bytes).hexdigest() != manifest["workflow_sha256"]:
        raise ValueError("Arm A source bytes do not match the frozen manifest")
    return {
        "arm": "original",
        "decision": "BASELINE",
        "status": "NOT_EXECUTED",
        "source_commit_sha": manifest["source_commit_sha"],
        "workflow_path": manifest["workflow_path"],
        "before_sha256": manifest["workflow_sha256"],
        "after_sha256": manifest["workflow_sha256"],
        "dispatch_ready": manifest["status"] == "prepared",
        "required_checks_status": manifest["required_checks"]["status"],
        "note": "Original pinned workflow, no optimization or GitHub Actions execution",
    }
