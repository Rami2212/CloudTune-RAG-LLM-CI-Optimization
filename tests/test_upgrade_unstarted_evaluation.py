import json
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts import upgrade_unstarted_evaluation as recovery


class UpgradeTests(unittest.TestCase):
    def exercise(self, repo):
        state = {"protocol": "cloudtune-local-fork-abc-v3-unchanged-arms",
                 "implementation_sha256": "old", "repositories": {"owner/repo": repo}}
        with tempfile.TemporaryDirectory() as folder:
            store = MagicMock()
            store.root = Path(folder)
            store.path = store.root / "state.json"
            original = json.dumps(state).encode()
            store.path.write_bytes(original)
            store.load.return_value = state
            with (patch.object(recovery, "StateStore", return_value=store),
                  patch.object(recovery, "exclusive_controller", return_value=nullcontext()),
                  patch.object(recovery, "implementation_digest", return_value="new")):
                if repo.get("records") or repo.get("registration_intent") or repo.get("pending"):
                    with self.assertRaisesRegex(ValueError, "prepared or dispatched"):
                        recovery.upgrade("trial")
                    store.save.assert_not_called()
                    self.assertFalse((store.root / "state.before-workflow-isolation.json").exists())
                else:
                    recovery.upgrade("trial")
                    self.assertEqual((store.root / "state.before-workflow-isolation.json").read_bytes(), original)
                    self.assertEqual(state["implementation_sha256"], "new")
                    self.assertEqual(state["implementation_upgrades"][0]["previous_implementation_sha256"], "old")
                    self.assertEqual(state["repositories"]["owner/repo"], repo)

    def test_unstarted_fork_identity_preserved(self):
        self.exercise({"fork_repo": "owner/repo", "fork_id": 123, "records": [], "pending": None})

    def test_measurements_cannot_be_upgraded(self):
        self.exercise({"records": [{"arm": "A"}]})

    def test_preparation_intent_cannot_be_upgraded(self):
        self.exercise({"registration_intent": {"sha": "commit"}})

    def test_pending_dispatch_cannot_be_upgraded(self):
        self.exercise({"pending": {"arm": "A"}})
