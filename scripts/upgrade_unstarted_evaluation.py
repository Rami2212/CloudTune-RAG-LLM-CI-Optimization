"""Explicitly upgrade a v3 checkpoint that never prepared or dispatched a trial.

Preserves the old ledger and candidate artifacts. Measured or partially prepared
trials must keep their original implementation; they cannot use this recovery.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from evaluation.fork_pipeline import (
    PROTOCOL, StateStore, exclusive_controller, implementation_digest,
)


def upgrade(evaluation_id: str) -> None:
    store = StateStore(evaluation_id)
    with exclusive_controller(evaluation_id):
        state = store.load()
        if not state or state.get("protocol") != "cloudtune-local-fork-abc-v3-unchanged-arms":
            raise ValueError("Only an existing v3 checkpoint can use this recovery")
        for repo in state.get("repositories", {}).values():
            if any(repo.get(key) for key in (
                    "records", "pending", "arms", "prepared_commit", "prepared_tree",
                    "registration_intent", "actions_disabled_for_setup")):
                raise ValueError("Trial has prepared or dispatched work; preserve its original implementation")
        backup = store.root / "state.before-workflow-isolation.json"
        with backup.open("xb") as stream:
            stream.write(store.path.read_bytes())
        state.setdefault("implementation_upgrades", []).append({
            "previous_protocol": state["protocol"],
            "previous_implementation_sha256": state["implementation_sha256"],
            "backup": backup.name,
            "reason": "Isolate ancillary workflows before first harness preparation; no trial runs exist",
            "at_utc": datetime.now(timezone.utc).isoformat(),
        })
        state["protocol"] = PROTOCOL
        state["implementation_sha256"] = implementation_digest()
        store.save(state)
        print(f"Upgraded {evaluation_id}; original ledger preserved at {backup}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation-id", required=True)
    args = parser.parse_args()
    upgrade(args.evaluation_id)


if __name__ == "__main__":
    main()
