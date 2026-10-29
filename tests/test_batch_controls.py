"""Offline checks for dataset positions, qualification quotas, and batch resumption."""
from contextlib import nullcontext
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_pattern_batch as batch_module
import scenario_experiments as scenarios


class BatchControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rows = [{"repo_id": f"source/repo{i}", "pattern_id": "P-LIT-GHA-CACHE"}
                     for i in range(1, 7)]

    def fake_batch(self, flags):
        batch = batch_module.Batch.__new__(batch_module.Batch)
        batch.batch_id, batch.rows = "test", self.rows
        batch.state = {"items": {}, "forks": {}}
        batch.directory, batch.model = self.root, "fixture:free"
        batch.save = lambda: None
        batch.cleanup_fork = lambda row, target: True
        attempted = []
        values = iter(flags)
        def prepare(row):
            attempted.append(row["repo_id"])
            experiment = Mock()
            experiment.directory = self.root
            experiment.config = {}
            experiment.state = {"proposal": {"llm": {"decision": "APPLY"}}}
            experiment.report.return_value = {"outcome": "inconclusive", "pattern_satisfied": next(values)}
            return experiment, "owner/fork"
        batch.ready_experiment = prepare
        return batch, attempted

    def test_two_qualified_repositories_skip_rest_and_resume(self):
        batch, attempted = self.fake_batch([False, True, True])
        with patch.object(batch_module.runner, "exclusive", side_effect=lambda path: nullcontext()):
            batch.run()
            batch.run()
        self.assertEqual(attempted, ["source/repo1", "source/repo2", "source/repo3"])
        self.assertEqual(len(batch.successful_examples("P-LIT-GHA-CACHE")), 2)
        self.assertEqual(batch.state["items"]["P-LIT-GHA-CACHE|source/repo4"]["status"], "pattern_satisfied")

    def test_inclusive_absolute_stop_and_original_positions(self):
        batch, attempted = self.fake_batch([False, False])
        with patch.object(batch_module.runner, "exclusive", side_effect=lambda path: nullcontext()):
            batch.run(start_at=3, stop_at=4)
        self.assertEqual(attempted, ["source/repo3", "source/repo4"])
        self.assertEqual([item["row_position"] for item in batch.state["items"].values()], [3, 4])

    def test_old_one_example_skip_reopens_without_rerun(self):
        batch, attempted = self.fake_batch([True])
        batch.state["items"] = {
            "P-LIT-GHA-CACHE|source/repo1": {"source_repo": "source/repo1", "pattern_id": "P-LIT-GHA-CACHE",
                                            "status": "completed", "example_satisfied": True},
            "P-LIT-GHA-CACHE|source/repo2": {"source_repo": "source/repo2", "pattern_id": "P-LIT-GHA-CACHE",
                                            "status": "pattern_satisfied"}}
        with patch.object(batch_module.runner, "exclusive", side_effect=lambda path: nullcontext()):
            batch.run()
        self.assertEqual(attempted, ["source/repo2"])

    def test_same_batch_accepts_model_token_dataset_and_scenario_settings_changes(self):
        with patch.object(batch_module.runner, "ROOT", self.root), patch.object(batch_module.runner, "GitHub"):
            first = batch_module.Batch("same", self.rows[:2], "owner", "token", "first:free", 24000)
            first.mark(self.rows[0], "completed", row_position=1, example_satisfied=True)
            updated = batch_module.Batch("same", self.rows, "owner", "token", "second:free", 4000)
            self.assertEqual(len(updated.state["items"]), 1)
            self.assertTrue((updated.directory / "selection_history.jsonl").exists())
            with patch.object(scenarios, "settings_from_env", return_value={"duration": 2}):
                original = scenarios.ScenarioBatch("scenario", self.rows, "owner", "token", "first:free")
            with patch.object(scenarios, "settings_from_env", return_value={"duration": 3}):
                revised = scenarios.ScenarioBatch("scenario", self.rows, "owner", "token", "second:free")
            self.assertEqual(original.directory, revised.directory)
            self.assertEqual(revised.scenario_settings, {"duration": 3})

    def test_pattern_filter_does_not_renumber_preview_positions(self):
        rows = [self.rows[0], {**self.rows[1], "pattern_id": "P-LIT-FAIL-FAST"}, self.rows[2]]
        args = ["batch", "--list", "--pattern", "P-LIT-GHA-CACHE", "--start-at", "2", "--stop-at", "3"]
        with patch.object(sys, "argv", args), patch.object(batch_module, "load_env"), \
             patch.object(batch_module, "read_rows", return_value=rows), patch("builtins.print") as output:
            self.assertEqual(batch_module.main(), 0)
        self.assertEqual(output.call_count, 1)
        self.assertEqual(output.call_args.args[0], 3)

    def test_limit_counts_rows_from_start_and_caps_at_csv_end(self):
        args = ["batch", "--list", "--start-at", "4", "--limit", "500"]
        with patch.object(sys, "argv", args), patch.object(batch_module, "load_env"), \
             patch.object(batch_module, "read_rows", return_value=self.rows), patch("builtins.print") as output:
            self.assertEqual(batch_module.main(), 0)
        self.assertEqual([call.args[0] for call in output.call_args_list], [4, 5, 6])


if __name__ == "__main__":
    unittest.main()
