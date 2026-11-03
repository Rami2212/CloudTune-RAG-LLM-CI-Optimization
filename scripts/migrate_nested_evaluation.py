"""Migrate frozen hashes for the reviewed batch-directory-only code change.

Accepts only the exact pre/post versions; preserves original ledgers verbatim.
Does not dispatch CI, call APIs, or change experiment records/configuration.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from evaluation.fork_pipeline import implementation_digest
from scripts import run_evaluation_batch as team

OLD_RUNNER = "77ecb8b2538d4874f8ce238036a3251449ca352f43819f86a2180edb7cb8fdfd"
NEW_RUNNER = "13e0ee84eb16b1db244bc81b7d04b598f879b7aaaa5048dbd3ee6bcb9498fe0e"
OLD_EVALUATOR = "d054c17a8c8d29448e1a9299760905891c76bb86948b28231525babe23be0986"
NEW_EVALUATOR = "da02796d93801b95254d1eec1ce0e3d969528f1e8d2bd96f45add9316414b08f"


def migrate(batch_id: str) -> None:
    team.validated_batch_id(1, batch_id)
    if hashlib.sha256(Path(team.__file__).read_bytes()).hexdigest() != NEW_RUNNER:
        raise ValueError("Runner differs from the reviewed layout-only version")
    if implementation_digest() != NEW_EVALUATOR:
        raise ValueError("Evaluator differs from the reviewed layout-only version")
    with team.exclusive_batch(batch_id):
        folder = team.RESULTS / batch_id
        if list(folder.rglob(".controller.lock")):
            raise ValueError("Controller lock exists; stop the controller first")
        identity_path = folder / "batch_identity.json"
        identity = json.loads(identity_path.read_text())
        if identity["runner_sha256"] != OLD_RUNNER:
            raise ValueError("Batch does not have the expected original runner hash")
        updates = [(identity_path, identity, "runner_sha256", NEW_RUNNER)]
        for path in sorted(folder.glob(batch_id + "-r*/state.json")):
            state = json.loads(path.read_text())
            if state["implementation_sha256"] != OLD_EVALUATOR:
                raise ValueError(f"Unexpected evaluator hash: {path}")
            updates.append((path, state, "implementation_sha256", NEW_EVALUATOR))
        backup = folder / "layout_migration_backup"
        if backup.exists():
            raise ValueError("Migration backup exists; inspect before retrying")
        # Back up every original before changing any identity or ledger.
        checksums = {}
        for path, _, _, _ in updates:
            relative = path.relative_to(folder)
            destination = backup / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            raw = path.read_bytes()
            with destination.open("xb") as stream:
                stream.write(raw)
            checksums[str(relative)] = hashlib.sha256(raw).hexdigest()
        for path, document, key, value in updates:
            document[key] = value
            team._atomic_json(path, document)
        team._atomic_json(backup / "migration.json", {
            "reason": "Reviewed storage-layout-only change; experiment settings and records preserved",
            "at_utc": datetime.now(timezone.utc).isoformat(),
            "original_sha256": checksums,
            "old_runner": OLD_RUNNER, "new_runner": NEW_RUNNER,
            "old_evaluator": OLD_EVALUATOR, "new_evaluator": NEW_EVALUATOR,
        })
        print(f"Migrated {len(updates)-1} trial ledgers; originals preserved in {backup}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-id", required=True)
    migrate(parser.parse_args().batch_id)
