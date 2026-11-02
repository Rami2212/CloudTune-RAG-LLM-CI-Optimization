"""Offline regression tests for exactly-three-run hosted CI protocol.

These tests never contact GitHub or invoke a generator. They exercise the real
checkpoint-aware run collection and summary code with deterministic responses.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evaluation.ci_executor import ForkExperiment, summarize_records
from evaluation.fork_pipeline import _config


class ThreeTrialProtocolTests(unittest.TestCase):
    def test_hosted_development_config_requires_exactly_three_runs(self):
        config = {
            "evaluation_id": "dev-three-runs", "dataset_split": "development",
            "dataset": "evaluation/results/development_repositories.csv",
            "arms": ["original", "ci_cost", "rag"],
            "repository_limit": 1, "repetitions": 3, "warmup_runs": 0,
            "rag": {"embedding_model": "BAAI/bge-m3",
                    "embedding_revision": "AUTO_PIN_SINGLE",
                    "dataset_sha256": "a" * 64,
                    "generator_model": "test/free:free"},
            "execution": {"dry_run": False, "cache_regime": "uncontrolled",
                          "development_smoke": True},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            self.assertEqual(_config(path)["repetitions"], 3)
            for count in (1, 2, 4, 5):
                with self.subTest(repetitions=count):
                    config["repetitions"] = count
                    path.write_text(json.dumps(config), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "exactly 3"):
                        _config(path)

    def test_hour_long_queued_run_has_no_local_poll_timeout_or_redispatch(self):
        class LongQueueGitHub:
            def __init__(self):
                self.observations = 0
                self.methods = []

            def request(self, method, path, body=None):
                self.methods.append(method)
                if method != "GET":
                    raise AssertionError("A resumed pending run must never dispatch again")
                self.observations += 1
                status = ("queued" if self.observations <= 245 else
                          "in_progress" if self.observations <= 250 else "completed")
                return {"status": status, "conclusion": "success" if status == "completed" else None,
                        "run_attempt": 1, "workflow_id": 42,
                        "head_sha": "b" * 40, "head_branch": "cloudtune/dev-a",
                        "event": "workflow_dispatch",
                        "created_at": "2026-11-02T10:00:00Z",
                        "run_started_at": "2026-11-02T11:00:00Z"}

            def all(self, path, key):
                if key != "jobs":
                    raise AssertionError("Expected only GitHub job evidence")
                return [{"id": 7, "name": "test", "status": "completed",
                         "conclusion": "success", "started_at": "2026-11-02T11:03:00Z",
                         "completed_at": "2026-11-02T11:04:00Z", "labels": ["ubuntu-latest"]}]

        github = LongQueueGitHub()
        runner = ForkExperiment(
            github, repo_id="source/repo", workflow_path=".github/workflows/ci.yml",
            source_sha="a" * 40,
            original=b"on: workflow_dispatch\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo ok\n",
            evaluation_id="dev-three-runs", max_wait_seconds=None,
            poll_seconds=15,
        )
        state = {"fork_repo": "research/repo", "workflow_id": 42,
                 "pending": {"arm": "A", "repeat": 1, "run_id": 901},
                 "records": [], "arms": {"A": {"sha": "b" * 40,
                 "branch": "cloudtune/dev-a", "workflow_sha256": "frozen"}}}
        saved = []
        with patch("evaluation.ci_executor.time.sleep", return_value=None), \
             patch("evaluation.ci_executor.log_progress"):
            outcome = runner.execute(state, lambda: saved.append(True),
                                     arm="A", repeat=1, required=["test"], max_total=9)
        self.assertGreater(github.observations * 15, 3600)
        self.assertTrue(outcome["comparable"])
        self.assertEqual(outcome["workflow_elapsed_seconds"], 60)
        self.assertIsNone(state["pending"])
        self.assertEqual(len(state["records"]), 1)
        self.assertTrue(all(method == "GET" for method in github.methods))

    def test_unknown_dispatch_is_discovered_after_many_polls_without_post(self):
        runner = ForkExperiment(
            None, repo_id="source/repo", workflow_path=".github/workflows/ci.yml",
            source_sha="a" * 40, original=b"", evaluation_id="dev-three-runs",
            max_wait_seconds=None, poll_seconds=15,
        )
        attempts = []
        def observe(*args):
            attempts.append(1)
            return [] if len(attempts) <= 20 else [{"id": 908,
                       "head_sha": "b" * 40, "event": "workflow_dispatch"}]
        runner._run_ids = observe
        state = {"fork_repo": "research/repo", "workflow_id": 42,
                 "arms": {"A": {"sha": "b" * 40, "branch": "cloudtune/dev-a"}},
                 "pending": {"arm": "A", "repeat": 1, "run_id": None, "old_ids": []}}
        with patch("evaluation.ci_executor.time.sleep", return_value=None), \
             patch("evaluation.ci_executor.log_progress"):
            run_id = runner._pending_run(state, lambda: None)
        self.assertEqual(run_id, 908)
        self.assertEqual(state["pending"]["run_id"], 908)
        self.assertEqual(len(attempts), 21)

    def test_three_complete_runs_report_mean_and_median_but_never_partial_savings(self):
        def record(arm, number, elapsed):
            return {"arm": arm, "repeat": number, "comparable": True,
                    "workflow_elapsed_seconds": elapsed,
                    "sum_job_runtime_seconds": elapsed * 2,
                    "initial_queue_seconds": 3600}
        records = ([record("A", i, t) for i, t in enumerate((10, 10, 100), 1)]
                   + [record("B", i, t) for i, t in enumerate((8, 9, 11), 1)])
        stats = summarize_records(records, repetitions=3)
        self.assertTrue(stats["A"]["complete"])
        self.assertEqual(stats["A"]["median_elapsed_seconds"], 10)
        self.assertEqual(stats["A"]["mean_elapsed_seconds"], 40)
        self.assertAlmostEqual(stats["B"]["mean_elapsed_seconds"], 28/3)
        self.assertAlmostEqual(stats["B"]["elapsed_saving_percent_vs_A"], 10)
        self.assertAlmostEqual(stats["B"]["mean_elapsed_saving_percent_vs_A"], 100*(40-28/3)/40)
        self.assertEqual(stats["A"]["mean_initial_queue_seconds"], 3600)
        self.assertIsNone(stats["C"]["mean_elapsed_seconds"])
        partial = summarize_records(records[:-1], repetitions=3)
        self.assertFalse(partial["B"]["complete"])
        self.assertIsNone(partial["B"]["mean_elapsed_seconds"])
        self.assertIsNone(partial["B"]["mean_elapsed_saving_percent_vs_A"])

    def test_undiscoverable_dispatch_stops_without_resending(self):
        runner = ForkExperiment(
            None,
            repo_id="source/repo",
            workflow_path=".github/workflows/ci.yml",
            source_sha="a" * 40,
            original=b"",
            evaluation_id="dev-test",
            max_wait_seconds=None,
            poll_seconds=15,
        )

        observations = []

        def no_runs(*args):
            observations.append(1)
            return []

        runner._run_ids = no_runs

        state = {
            "fork_repo": "research/repo",
            "workflow_id": 42,
            "arms": {
                "A": {
                    "sha": "b" * 40,
                    "branch": "cloudtune/dev-a",
                }
            },
            "pending": {
                "arm": "A",
                "repeat": 1,
                "run_id": None,
                "old_ids": [],
            },
        }

        with patch("evaluation.ci_executor.time.sleep", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "not discoverable"):
                runner._pending_run(state, lambda: None)

        self.assertEqual(len(observations), 40)
        self.assertIsNone(state["pending"]["run_id"])

    def test_unknown_github_status_stops_without_redispatch(self):
        class UnknownStatusGitHub:
            def request(self, method, path, body=None):
                if method != "GET":
                    raise AssertionError("Duplicate dispatch attempted")
                return {"status": "unexpected_state"}

        runner = ForkExperiment(
            UnknownStatusGitHub(),
            repo_id="source/repo",
            workflow_path=".github/workflows/ci.yml",
            source_sha="a" * 40,
            original=b"",
            evaluation_id="dev-test",
            max_wait_seconds=None,
            poll_seconds=15,
        )

        state = {
            "fork_repo": "research/repo",
            "pending": {
                "arm": "A",
                "repeat": 1,
                "run_id": 901,
            },
            "records": [],
        }

        with self.assertRaisesRegex(ValueError, "Unexpected GitHub Actions run status"):
            runner.execute(
                state,
                lambda: None,
                arm="A",
                repeat=1,
                required=["test"],
                max_total=9,
            )

        self.assertEqual(state["pending"]["run_id"], 901)
        self.assertEqual(state["records"], [])

if __name__ == "__main__":
    unittest.main()
