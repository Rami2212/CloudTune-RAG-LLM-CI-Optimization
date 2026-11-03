"""Offline safety tests for fresh evaluation preparation and deliberate resets."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import prepare_evaluation_workspace as workspace
from scripts.prepare_evaluation_workspace import prepare_workspace


class EvaluationWorkspaceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        data = self.root / "evaluation"
        data.mkdir()
        source = data / "evaluation_repositories_4000.csv"
        with source.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["repo_id", "split", "selection_rank"])
            writer.writeheader()
            for index in range(1, 4001):
                writer.writerow({"repo_id": f"owner/repo-{index:04d}",
                                 "split": "evaluation", "selection_rank": str(index)})
        (data / "evaluation_repositories_4000_manifest.json").write_text(
            json.dumps({"output_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}),
            encoding="utf-8",
        )
        results = data / "results"
        results.mkdir()
        (results / ".gitignore").write_text("*\n!.gitignore\n!README.md\n", encoding="utf-8")
        (results / "README.md").write_text("Retained policy.\n", encoding="utf-8")

    def test_prepare_is_idempotent_and_preserves_existing_results(self):
        checkpoint = self.root / "evaluation/results/member-custom-r0001/state.json"
        checkpoint.parent.mkdir()
        checkpoint.write_text('{"pending": true}', encoding="utf-8")
        first = prepare_workspace(root=self.root)
        second = prepare_workspace(root=self.root)
        self.assertEqual(first, second)
        self.assertEqual([entry["rows"] for entry in first["assignments"]], [1000] * 4)
        self.assertTrue(checkpoint.exists())
        self.assertEqual(first["rows"], 4000)

    def test_reset_preview_does_not_delete_checkpoint_or_ci_cost(self):
        checkpoint = self.root / "evaluation/results/member-custom-r0001/state.json"
        checkpoint.parent.mkdir()
        checkpoint.write_text("pending", encoding="utf-8")
        local_tool = self.root / ".venv/ci-cost"
        local_tool.mkdir(parents=True)
        (local_tool / "marker").write_text("pinned", encoding="utf-8")
        prepare_workspace(root=self.root, reset_results=True, reset_ci_cost=True)
        self.assertTrue(checkpoint.exists())
        self.assertTrue((local_tool / "marker").exists())

    def test_confirm_reset_removes_abandoned_results_only(self):
        checkpoint = self.root / "evaluation/results/member-custom-r0001/state.json"
        checkpoint.parent.mkdir()
        checkpoint.write_text("abandoned", encoding="utf-8")
        tool = self.root / ".venv/ci-cost"
        tool.mkdir(parents=True)
        prepare_workspace(root=self.root, reset_results=True, reset_ci_cost=True,
                          confirm_reset=True)
        self.assertFalse(checkpoint.exists())
        self.assertFalse(tool.exists())
        self.assertTrue((self.root / "evaluation/results/.gitignore").exists())
        self.assertTrue((self.root / "evaluation/results/README.md").exists())
        self.assertTrue((self.root / "evaluation/assignments/manifest.json").exists())

    def test_modified_frozen_source_is_rejected_before_reset(self):
        source = self.root / "evaluation/evaluation_repositories_4000.csv"
        source.write_text("modified", encoding="utf-8")
        checkpoint = self.root / "evaluation/results/member-custom-r0001/state.json"
        checkpoint.parent.mkdir()
        checkpoint.write_text("pending", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "committed manifest"):
            prepare_workspace(root=self.root, reset_results=True, confirm_reset=True)
        self.assertTrue(checkpoint.exists())

    def test_tracked_published_evidence_blocks_destructive_reset(self):
        published = self.root / "evaluation/results/example/published/attempts.csv"
        published.parent.mkdir(parents=True)
        published.write_text("tracked evidence", encoding="utf-8")
        subprocess.run(["git", "add", "-f", str(published.relative_to(self.root))],
                       cwd=self.root, check=True)
        with self.assertRaisesRegex(ValueError, "Refusing to reset committed result evidence"):
            prepare_workspace(root=self.root, reset_results=True, confirm_reset=True)
        self.assertTrue(published.exists())


    def test_reset_cleans_legacy_test_results_from_uploaded_layout(self):
        """Legacy smoke/pilot data and nested ci-cost under results are disposable.

        These are the exact types of leftovers seen in the supplied archive.
        A preview must retain every file; a confirmed reset retains policy files.
        """
        results = self.root / "evaluation/results"
        leftovers = (
            ".tools/ci-cost/.git/config",
            ".tools/ci-cost/dist/index.js",
            "cloudtune-abc-preparation-pilot-001/state.json",
            "dev-fork-abc-smoke-001/state.json",
            "dev-fork-abc-smoke-002/fork_report.json",
            "dev-fork-abc-smoke-002-repositories.csv",
            "dev-fork-abc-smoke-002.json",
            "development_repositories.csv",
            "development_smoke.json",
        )
        for relative in leftovers:
            path = results / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("obsolete-development-only", encoding="utf-8")

        prepare_workspace(root=self.root, reset_results=True)
        self.assertTrue(all((results / relative).is_file() for relative in leftovers))

        prepare_workspace(root=self.root, reset_results=True, confirm_reset=True)
        self.assertTrue(all(not (results / relative).exists() for relative in leftovers))
        self.assertEqual((results / "README.md").read_text(encoding="utf-8"), "Retained policy.\n")
        self.assertTrue((results / ".gitignore").is_file())
        self.assertEqual(len(list((self.root / "evaluation/assignments").glob("member_*.csv"))), 4)

    def test_git_add_stages_custom_batch_published_study_results_only(self):
        """New member and cohort summaries are commit-ready, raw state is not."""
        results = self.root / "evaluation/results"
        # Use the exact policy file from the checkout being tested.
        source = Path(__file__).resolve().parents[1] / "evaluation/results/.gitignore"
        (results / ".gitignore").write_bytes(source.read_bytes())

        allowed = (
            "new-member-02-v1/published/attempts.csv",
            "new-member-02-v1/published/manifest.json",
            "new-member-02-v1/published/trials/r0001.json",
            "new-member-02-v1/published/trials/r1000.json",
            "cohort/published/attempts_4000.csv",
            "cohort/published/manifest.json",
        )
        ignored = (
            ".tools/ci-cost/.git/config",
            "cloudtune-abc-preparation-pilot-001/state.json",
            "dev-fork-abc-smoke-001/state.json",
            "development_smoke.json",
            "new-member-02-v1/batch_identity.json",
            "new-member-02-v1-r0001/state.json",
            "new-member-02-v1-r0001/repositories/original.yml",
            "new-member-02-v1/published/trials/rABCD.json",
            "new-member-02-v1/published/trials/prompt.json",
            "new-member-02-v1/published/secret_request.json",
        )
        for relative in allowed + ignored:
            path = results / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture", encoding="utf-8")

        subprocess.run(["git", "add", "evaluation/results"], cwd=self.root, check=True)
        staged = set(subprocess.run(
            ["git", "ls-files", "--cached", "--", "evaluation/results"],
            cwd=self.root, check=True, capture_output=True, text=True,
        ).stdout.splitlines())
        for relative in allowed:
            self.assertIn(f"evaluation/results/{relative}", staged)
        for relative in ignored:
            self.assertNotIn(f"evaluation/results/{relative}", staged)



    def test_readonly_windows_git_pack_is_retried_and_legacy_folders_removed(self):
        """Simulate rmtree's Windows access-denied callback on a pack index."""
        results = self.root / "evaluation/results"
        git_pack = results / ".tools/ci-cost/.git/objects/pack/example.idx"
        git_pack.parent.mkdir(parents=True, exist_ok=True)
        git_pack.write_text("old pack", encoding="utf-8")
        git_pack.chmod(stat.S_IREAD)
        smoke = results / "dev-fork-abc-chalk-gemma-001/state.json"
        smoke.parent.mkdir()
        smoke.write_text("old smoke", encoding="utf-8")
        real_rmtree = workspace.shutil.rmtree
        retried = []

        def emulate_access_denied(directory, *, onerror=None):
            if Path(directory).name == ".tools":
                def delete_pack(filename):
                    # Windows rejects unlinking an index with the read-only bit.
                    if not (os.stat(filename).st_mode & stat.S_IWRITE):
                        raise PermissionError("simulated Windows read-only index")
                    retried.append(filename)
                    os.unlink(filename)

                try:
                    delete_pack(str(git_pack))
                except PermissionError as error:
                    onerror(delete_pack, str(git_pack), (type(error), error, None))
            return real_rmtree(directory, onerror=onerror)

        with patch.object(workspace.shutil, "rmtree", side_effect=emulate_access_denied):
            prepare_workspace(root=self.root, reset_results=True, confirm_reset=True)
        self.assertEqual(retried, [str(git_pack)])
        self.assertFalse((results / ".tools").exists())
        self.assertFalse(smoke.exists())
        self.assertTrue((results / ".gitignore").is_file())

    def test_reset_continues_after_one_locked_folder_but_reports_failure(self):
        """The script must never report complete when Windows blocks deletion."""
        results = self.root / "evaluation/results"
        locked = results / ".tools/ci-cost/.git/objects/pack/example.idx"
        locked.parent.mkdir(parents=True, exist_ok=True)
        locked.write_text("locked", encoding="utf-8")
        smoke = results / "dev-fork-abc-json5-gemma-001/state.json"
        smoke.parent.mkdir()
        smoke.write_text("old smoke", encoding="utf-8")
        real_remove = workspace._remove_local_entry

        def selective_failure(path):
            if path.name == ".tools":
                raise PermissionError("simulated exclusive file lock")
            return real_remove(path)

        with patch.object(workspace, "_remove_local_entry", side_effect=selective_failure):
            with self.assertRaisesRegex(OSError, "Reset INCOMPLETE: 1 entries"):
                prepare_workspace(root=self.root, reset_results=True, confirm_reset=True)
        self.assertTrue(locked.exists())
        self.assertFalse(smoke.exists())
        self.assertTrue((results / "README.md").is_file())



if __name__ == "__main__":
    unittest.main()
