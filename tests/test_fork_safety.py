"""Offline fork identity and development-split smoke safeguards.

Tests use fake GitHub API clients and do not create or delete repositories.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import hashlib
from unittest.mock import patch

from evaluation.ci_executor import ForkExperiment, GitHubError, verify_fork
from evaluation.fork_pipeline import (
    PROTOCOL, _config, configure_batch, resolve_rerun_batch,
    selected_repository_rows,
)
from evaluation.run_pipeline import load_config, prepare


class ForkSafetyTests(unittest.TestCase):
    def setUp(self):
        # Force deletion-mode tests to exercise fork identity verification,
        # regardless of the developer's fork-retention environment setting.
        # These tests use fake GitHub clients and never delete real forks.
        deletion_mode = patch.dict(
            "os.environ",
            {"CLOUDTUNE_AUTO_DELETE_FORKS": "true"},
        )
        deletion_mode.start()
        self.addCleanup(deletion_mode.stop)

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
                "arms": ["original", "ci_cost", "rag"], "repetitions": 3,
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

    def test_batch_flags_resolve_inclusive_ranges_without_mutating_config(self):
        baseline = self.config(dev=False)
        baseline["repository_limit"] = 3
        first = configure_batch(baseline, start_at=1, stop_at=100, batch_id="team-01")
        second = configure_batch(baseline, start_at=101, limit=100, batch_id="team-02")
        self.assertEqual((first["repository_start_at"], first["repository_limit"],
                          first["evaluation_id"]), (1, 100, "team-01"))
        self.assertEqual((second["repository_start_at"], second["repository_limit"],
                          second["evaluation_id"]), (101, 100, "team-02"))
        self.assertEqual(baseline["repository_limit"], 3)
        self.assertEqual(baseline["repository_start_at"], 1)
        self.assertEqual(configure_batch(baseline)["evaluation_id"], "regular")
        self.assertEqual(configure_batch(baseline, start_at=16)["repository_limit"], 3)

    def test_batch_flags_reject_invalid_or_unsafe_ranges(self):
        baseline = self.config(dev=False)
        cases = (
            {"start_at": 0}, {"stop_at": 0}, {"start_at": 10, "stop_at": 9},
            {"start_at": 1, "stop_at": 101}, {"limit": 0}, {"limit": 101},
            {"limit": 10, "stop_at": 10}, {"batch_id": "../bad"},
            {"batch_id": ""}, {"batch_id": "name with spaces"},
        )
        for kwargs in cases:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                configure_batch(baseline, **kwargs)
        with self.assertRaisesRegex(ValueError, "Development smoke"):
            configure_batch(self.config(dev=True), limit=2)
        with self.assertRaisesRegex(ValueError, "Development smoke"):
            configure_batch(self.config(dev=True), batch_id="team-01")

    def test_team_ranges_partition_500_rows_with_no_overlap(self):
        # The preview uses the exact CSV order, never a filtered/reindexed list.
        dataset = self.root / "team.csv"
        dataset.write_text("repo_id,split\n" + "".join(
            f"example/repo-{index},evaluation\n" for index in range(1, 501)))
        baseline = self.config(dev=False)
        baseline["dataset"] = "team.csv"
        positions = []
        with patch("evaluation.fork_pipeline.ROOT", self.root):
            for member in range(5):
                first = member * 100 + 1
                last = first + 99
                batch = configure_batch(baseline, start_at=first, stop_at=last,
                                        batch_id=f"team-{member + 1:02d}")
                selection = selected_repository_rows(batch, explicit_stop=last)
                self.assertEqual(len(selection), 100)
                self.assertEqual(selection[0], (first, f"example/repo-{first}"))
                self.assertEqual(selection[-1], (last, f"example/repo-{last}"))
                positions.extend(position for position, _ in selection)
            self.assertEqual(positions, list(range(1, 501)))
            with self.assertRaisesRegex(ValueError, "exceeds dataset size"):
                selected_repository_rows(
                    configure_batch(baseline, start_at=501, limit=1))
            with self.assertRaisesRegex(ValueError, "exceeds dataset size"):
                selected_repository_rows(
                    configure_batch(baseline, start_at=451, stop_at=520),
                    explicit_stop=520)

    def test_rerun_generation_requires_settled_original_and_preserves_evidence(self):
        dataset = self.root / "team.csv"
        dataset.write_text("repo_id,split\nexample/one,evaluation\nexample/two,evaluation\n")
        original = self.config(dev=False)
        original["dataset"] = "team.csv"
        batch = configure_batch(original, start_at=1, limit=2, batch_id="team-02")

        def save(trial, *, finished, cleanup="DELETED"):
            path = self.root / "evaluation/results" / trial["evaluation_id"] / "state.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            record = {"status": "COMPLETE" if finished else "WAITING_FOR_GITHUB_RUN",
                      "measurements_finalized": finished,
                      "pending": None if finished else {"arm": "A", "repeat": 1},
                      "fork_repo": "research/one", "cleanup_status": cleanup}
            payload = {"protocol": PROTOCOL,
                       "config_sha256": hashlib.sha256(json.dumps(trial, sort_keys=True).encode()).hexdigest(),
                       "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
                       "repositories": {"example/one": dict(record), "example/two": dict(record)}}
            path.write_text(json.dumps(payload), encoding="utf-8")
            return path

        with patch("evaluation.fork_pipeline.ROOT", self.root):
            selection = selected_repository_rows(batch)
            with self.assertRaisesRegex(ValueError, "existing batch"):
                resolve_rerun_batch(batch, selection)
            save(batch, finished=False)
            with self.assertRaisesRegex(ValueError, "not finalized"):
                resolve_rerun_batch(batch, selection)
            source = save(batch, finished=True)
            saved_bytes = source.read_bytes()
            second = resolve_rerun_batch(batch, selection)
            self.assertEqual(second["evaluation_id"], "team-02-r2")
            save(second, finished=False)
            self.assertEqual(resolve_rerun_batch(batch, selection)["evaluation_id"], "team-02-r2")
            save(second, finished=True)
            self.assertEqual(resolve_rerun_batch(batch, selection)["evaluation_id"], "team-02-r3")
            self.assertEqual(source.read_bytes(), saved_bytes)

    def test_rerun_rejects_unsettled_cleanup_or_changed_config(self):
        dataset = self.root / "team.csv"
        dataset.write_text("repo_id,split\nexample/one,evaluation\n")
        original = self.config(dev=False)
        original["dataset"] = "team.csv"
        batch = configure_batch(original, limit=1, batch_id="team-01")
        path = self.root / "evaluation/results/team-01/state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        state = {"protocol": PROTOCOL,
                 "config_sha256": hashlib.sha256(json.dumps(batch, sort_keys=True).encode()).hexdigest(),
                 "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
                 "repositories": {"example/one": {
                     "status": "COMPLETE", "measurements_finalized": True,
                     "pending": None, "fork_repo": "research/one",
                     "cleanup_status": "DELETE_OUTCOME_UNKNOWN"}}}
        path.write_text(json.dumps(state), encoding="utf-8")
        with patch("evaluation.fork_pipeline.ROOT", self.root):
            selection = selected_repository_rows(batch)
            with self.assertRaisesRegex(ValueError, "not finalized"):
                resolve_rerun_batch(batch, selection)
            state["repositories"]["example/one"]["cleanup_status"] = "RETAINED_BY_CONFIGURATION"
            path.write_text(json.dumps(state), encoding="utf-8")
            # Rerun preserves a retained fork; provisioning checks its identity.
            self.assertEqual(resolve_rerun_batch(batch, selection)["evaluation_id"], "team-01-r2")
            altered = dict(batch)
            altered["repetitions"] = 2
            with self.assertRaisesRegex(ValueError, "frozen protocol/configuration"):
                resolve_rerun_batch(altered, selection)

    def test_dev_smoke_is_limited_to_one_repo_and_requires_three_runs(self):
        path = self.root / "config.json"
        config = self.config()
        config["repository_limit"] = 2
        path.write_text(json.dumps(config))
        with self.assertRaisesRegex(ValueError, "Development smoke is limited"):
            _config(path)
        config["repository_limit"] = 1
        for repetitions in (1, 2, 4, 5):
            config["repetitions"] = repetitions
            path.write_text(json.dumps(config))
            with self.subTest(repetitions=repetitions), self.assertRaisesRegex(ValueError, "exactly 3"):
                _config(path)


if __name__ == "__main__":
    unittest.main()
