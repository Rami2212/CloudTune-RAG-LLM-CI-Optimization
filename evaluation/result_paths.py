"""Shared paths for batch-owned trial checkpoints."""
from pathlib import Path
import re


def trial_directory(results: Path, evaluation_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", evaluation_id):
        raise ValueError("Unsafe evaluation_id for local state path")
    match = re.fullmatch(r"(.+)-r[0-9]{4}(?:-r[0-9]+)?", evaluation_id)
    if match:
        target = results / match[1] / evaluation_id
        legacy = results / evaluation_id
        if legacy.exists():
            raise ValueError(f"Move legacy checkpoint {legacy} to {target} before continuing")
        return target
    return results / evaluation_id
