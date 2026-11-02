"""Offline fork identity and development-split smoke safeguards.

Tests use fake GitHub API clients and do not create or delete repositories.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evaluation.ci_executor import ForkExperiment, GitHubError, verify_fork
from evaluation.fork_pipeline import _config
from evaluation.run_pipeline import load_config, prepare


class ForkSafetyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.runner = ForkExperiment(None, repo_id="source/repo",
            workflow_path=".github/workflows/ci.yml", source_sha="a" * 40,
            original=b"on: workflow_dispatch\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo ok\n",
            evaluation_id="dev-smoke", max_wait_seconds=1, poll_seconds=1)

    def fork(self, fork_id=777):
        return {"id": fork_id, "owner": {"login": "research"},
                "fork": True, "permissions": {"push": True},
                "source": {"full_name": "source/repo"}}

    def state(self):
        return {"fork_repo": "research/repo", "fork_owner": "research",
                "fork_id": 777, "fork_creation_intent": "research/repo",
                "fork_created_by_evaluation": True,
                "measurements_finalized": True, "pending": None}

    def test_fork_id_matches_even_with_same_name_and_source(self):
        verify_fork(self.fork(), "source/repo", "research", expected_id=777)
        with self.assertRaisesRegex(ValueError, "ID changed"):
            verify_fork(self.fork(888), "source/repo", "research", expected_id=777)

    def test_cleanup_blocks_recreated_fork_without_delete(self):
        calls = []
        class Fake:
            def request(_, method, path, body=None):
                calls.append(method)
                if method == "GET":
                    return self.fork(888)
                raise AssertionError("DELETE must never be called")
            def all(_, path, key):
                raise AssertionError("No run listing before identity verified")
        self.runner.gh = Fake()
        with self.assertRaisesRegex(ValueError, "ID changed"):
            self.runner.cleanup_fork(self.state(), lambda: None)
        self.assertEqual(calls, ["GET"])

    def test_cleanup_preserves_old_unpinned_state_without_requests(self):
        class Forbidden:
            def request(*args):
                raise AssertionError("GitHub request must not run")
        self.runner.gh = Forbidden()
        state = self.state()
        state.pop("fork_id")
        self.assertEqual(self.runner.cleanup_fork(state, lambda: None), "PRESERVED_UNVERIFIED_ID")
        self.assertNotIn("cleanup_intent", state)

    def test_provision_checks_numeric_id_on_resume(self):
        class Fake:
            def request(_, method, path, body=None):
                return self.fork(888)
        self.runner.gh = Fake()
        with self.assertRaisesRegex(ValueError, "ID changed"):
            self.runner.provision(self.state(), lambda: None)

    def test_create_rejects_existing_fork_with_another_name(self):
        calls = []
        class Fake:
            def request(_, method, path, body=None):
                calls.append((method, path))
                if path == "/user":
                    return {"login": "research"}
                if method == "GET" and path == "/repos/research/repo":
                    raise GitHubError(404, path)
                if method == "POST":
                    return {"id": 555, "full_name": "research/different-name"}
                raise AssertionError((method, path))
        self.runner.gh = Fake()
        state = {}
        with self.assertRaisesRegex(ValueError, "unexpected name"):
            self.runner.provision(state, lambda: None)
        self.assertNotIn("fork_created_by_evaluation", state)
        self.assertEqual([method for method, _ in calls].count("POST"), 1)

    def test_create_requires_numeric_id_before_marking_owned(self):
        class Fake:
            def request(_, method, path, body=None):
                if path == "/user":
                    return {"login": "research"}
                if method == "GET":
                    raise GitHubError(404, path)
                return {"full_name": "research/repo"}
        self.runner.gh = Fake()
        state = {}
        with self.assertRaisesRegex(ValueError, "numeric repository ID"):
            self.runner.provision(state, lambda: None)
        self.assertNotIn("fork_created_by_evaluation", state)

    def config(self, *, dev=True):
        return {"evaluation_id": "dev-smoke-001" if dev else "regular",
                "dataset": "evaluation/results/development_repositories.csv",
                "dataset_split": "development" if dev else "evaluation",
                "repository_start_at": 1, "repository_limit": 1,
                "arms": ["original", "ci_cost", "rag"], "repetitions": 1,
                "warmup_runs": 0,
                "rag": {"embedding_model": "BAAI/bge-m3", "embedding_revision": "AUTO_PIN_SINGLE",
                        "dataset_sha256": "a" * 64, "generator_model": "free/model:free"},
                "execution": {"dry_run": False, "cache_regime": "uncontrolled",
                              "development_smoke": dev}}

    def test_dev_smoke_is_accepted_only_by_fork_controller(self):
        config = self.config()
        path = self.root / "config.json"
        path.write_text(json.dumps(config))
        self.assertEqual(_config(path)["dataset_split"], "development")
        with self.assertRaisesRegex(ValueError, "Development smoke requires fork controller"):
            load_config(path)

    def test_dev_smoke_requires_separate_split_and_id(self):
        path = self.root / "config.json"
        for key, value in (("dataset_split", "evaluation"), ("evaluation_id", "smoke")):
            config = self.config()
            config[key] = value
            path.write_text(json.dumps(config))
            with self.subTest(key=key), self.assertRaises(ValueError):
                _config(path)

    def test_development_smoke_excludes_heldout_before_network(self):
        root = self.root / "project"
        (root / "evaluation/results").mkdir(parents=True)
        dataset = root / "evaluation/results/development_repositories.csv"
        dataset.write_text("repo_id,split\nselected/repo,development\n")
        heldout = root / "evaluation/evaluation_repositories_4000.csv"
        heldout.write_text("repo_id,split\nselected/repo,evaluation\n")
        config = self.config()
        class ForbiddenReader:
            def get_json(self, path):
                raise AssertionError("Held-out repository must not reach GitHub")
        with patch("evaluation.run_pipeline.excluded_repo_ids", return_value=set()):
            outcome = prepare(config, reader=ForbiddenReader(), project_root=root)
        self.assertEqual(outcome["counts"], {"ineligible": 1})
        self.assertEqual(outcome["github_actions_runs"], 0)

    def test_dev_smoke_is_limited_to_one_repo_and_repeat(self):
        path = self.root / "config.json"
        for key in ("repository_limit", "repetitions"):
            config = self.config()
            config[key] = 2
            path.write_text(json.dumps(config))
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "Development smoke is limited"):
                _config(path)


if __name__ == "__main__":
    unittest.main()
