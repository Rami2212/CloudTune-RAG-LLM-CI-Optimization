"""Offline regression tests for the read-only A/B/C preparation stage."""
from __future__ import annotations

import csv
import hashlib
from http.client import IncompleteRead
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from evaluation.optimizers.original import original_candidate
from evaluation.repository_preparation import (
    GitHubReader,
    PreparationError,
    git_blob_sha1,
    prepare_repository,
    read_evaluation_rows,
    workflow_doc,
)
from evaluation.run_pipeline import load_config, prepare

SHA = "a" * 40
TREE_SHA = "b" * 40
BASIC_WORKFLOW = b"""name: CI
on:
  workflow_dispatch:
  push:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Run tests
        run: pytest -q
"""
MISSING_DISPATCH = BASIC_WORKFLOW.replace(b"  workflow_dispatch:\n", b"")


class GitHubReaderRetryTests(unittest.TestCase):
    def test_incomplete_response_is_retried_from_scratch(self):
        broken = MagicMock()
        broken.__enter__.return_value = broken
        broken.read.side_effect = IncompleteRead(b'{"partial":', 20)
        complete = MagicMock()
        complete.__enter__.return_value = complete
        complete.read.return_value = b'{"content": "complete"}'
        with patch('evaluation.repository_preparation.urllib.request.urlopen',
                   side_effect=[broken, complete]) as open_request, \
                patch('evaluation.repository_preparation.time.sleep') as sleep:
            result = GitHubReader().get_json('/repos/owner/repo/git/blobs/abc')
        self.assertEqual(result, {"content": "complete"})
        self.assertEqual(open_request.call_count, 2)
        sleep.assert_called_once_with(0.5)
        broken.__exit__.assert_called_once()

    def test_repeated_incomplete_responses_stop_after_three_attempts(self):
        response = MagicMock()
        response.__enter__.return_value = response
        error = IncompleteRead(b'partial', 20)
        response.read.side_effect = error
        with patch('evaluation.repository_preparation.urllib.request.urlopen',
                   return_value=response) as open_request, \
                patch('evaluation.repository_preparation.time.sleep') as sleep:
            with self.assertRaises(PreparationError) as caught:
                GitHubReader().get_json('/repos/owner/repo/git/blobs/abc')
        self.assertIs(caught.exception.__cause__, error)
        self.assertEqual(open_request.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [0.5, 1.0])


class FakeReader:
    """Typed test double matching the public, read-only GitHubReader interface."""

    def __init__(self, *, repo="demo/ci", workflow=BASIC_WORKFLOW, extra_workflows=None,
                 source=None, truncated=False):
        self.repo = repo
        self.files = {".github/workflows/ci.yml": workflow, "pyproject.toml": b"[project]\nname='demo'\n"}
        self.files.update(extra_workflows or {})
        self.blobs = {git_blob_sha1(raw): raw for raw in self.files.values()}
        self.responses = {
            f"/repos/{repo}": {
                "full_name": repo, "default_branch": "main", "private": False,
                "archived": False, "disabled": False,
                **({"source": {"full_name": source}} if source else {}),
            },
            f"/repos/{repo}/commits/main": {
                "sha": SHA, "commit": {"tree": {"sha": TREE_SHA}},
            },
            f"/repos/{repo}/git/trees/{TREE_SHA}?recursive=1": {
                "truncated": truncated,
                "tree": [
                    {"path": path, "type": "blob", "mode": "100644",
                     "sha": git_blob_sha1(raw), "size": len(raw)}
                    for path, raw in self.files.items()
                ],
            },
        }
        self.calls = []

    def get_json(self, path):
        self.calls.append(path)
        return self.responses[path]

    def blob(self, repo, sha):
        self.calls.append("blob:" + sha)
        return self.blobs[sha]


class RepositoryPreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.row = {"repo_id": "demo/ci", "split": "evaluation", "selection_rank": "1"}
        self.exclusions = {"training/sample"}

    def _prepare(self, fake=None, exclusions=None):
        return prepare_repository(self.row, fake or FakeReader(), self.root, "dataset-hash",
                                  self.exclusions if exclusions is None else exclusions)

    def test_prepares_immutable_snapshot_and_original_arm(self):
        result = self._prepare()
        self.assertEqual(result["status"], "prepared")
        folder = Path(result["manifest_path"]).parent
        manifest = json.loads((folder / "manifest.json").read_text())
        candidate = original_candidate(folder)
        self.assertEqual((folder / "source/original.yml").read_bytes(), BASIC_WORKFLOW)
        self.assertEqual(candidate["before_sha256"], candidate["after_sha256"])
        self.assertEqual(manifest["source_commit_sha"], SHA)
        self.assertEqual(manifest["source_tree_sha"], TREE_SHA)
        self.assertEqual(manifest["required_checks"]["status"], "not_verified")
        self.assertEqual(manifest["context_files_archived"], 2)
        self.assertEqual(candidate["status"], "NOT_EXECUTED")
        self.assertEqual(candidate["dispatch_ready"], True)

    def test_rerun_reuses_frozen_source_not_moving_head(self):
        fake = FakeReader()
        first = self._prepare(fake)
        fake.responses[f"/repos/{fake.repo}/commits/main"]["sha"] = "f" * 40
        initial_calls = len(fake.calls)
        second = self._prepare(fake)
        self.assertEqual(second["status"], "prepared")
        self.assertEqual(second["source_commit_sha"], first["source_commit_sha"])
        self.assertEqual(len(fake.calls), initial_calls)

    def test_missing_dispatch_marks_harness_requirement_without_mutating_workflow(self):
        result = self._prepare(FakeReader(workflow=MISSING_DISPATCH))
        self.assertEqual(result["status"], "needs_harness")
        folder = Path(result["manifest_path"]).parent
        manifest = json.loads((folder / "manifest.json").read_text())
        self.assertIn("MISSING_WORKFLOW_DISPATCH", manifest["dispatch_problems"])
        self.assertEqual((folder / "source/original.yml").read_bytes(), MISSING_DISPATCH)
        self.assertFalse(original_candidate(folder)["dispatch_ready"])

    def test_workflow_run_listener_is_excluded_from_selected_harness(self):
        listener = b"""on: workflow_run
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - run: echo release
"""
        result = self._prepare(FakeReader(extra_workflows={".github/workflows/listener.yml": listener}))
        folder = Path(result["manifest_path"]).parent
        manifest = json.loads((folder / "manifest.json").read_text())
        self.assertEqual(manifest["workflow_path"], ".github/workflows/ci.yml")

    def test_deployment_and_secret_workflows_are_rejected(self):
        unsafe = BASIC_WORKFLOW.replace(b"run: pytest -q", b"run: npm publish")
        with self.assertRaisesRegex(PreparationError, "No safe test/build workflow"):
            self._prepare(FakeReader(workflow=unsafe))

    def test_training_exclusion_is_checked_before_api_access(self):
        fake = FakeReader(source="training/sample")
        with self.assertRaisesRegex(PreparationError, "family overlaps"):
            self._prepare(fake)
        self.assertEqual(fake.calls, ["/repos/demo/ci"])

    def test_truncated_tree_is_inconclusive_not_prepared(self):
        with self.assertRaises(PreparationError) as failure:
            self._prepare(FakeReader(truncated=True))
        self.assertEqual(failure.exception.status, "inconclusive")

    def test_duplicate_yaml_key_is_rejected(self):
        invalid = BASIC_WORKFLOW + b"jobs: {}\n"
        with self.assertRaises(PreparationError) as failure:
            self._prepare(FakeReader(workflow=invalid))
        self.assertEqual(failure.exception.status, "inconclusive")

    def test_saved_snapshot_tampering_is_detected(self):
        result = self._prepare()
        path = Path(result["manifest_path"]).parent / "source/original.yml"
        path.write_bytes(b"tampered")
        with self.assertRaises(PreparationError) as failure:
            self._prepare()
        self.assertEqual(failure.exception.status, "inconclusive")

    def test_canonical_workflow_on_key_survives_yaml_parser(self):
        document = workflow_doc(BASIC_WORKFLOW)
        self.assertIn("on", document)
        self.assertEqual(document["on"]["workflow_dispatch"], None)
        self.assertNotIn(True, document)

    def test_dataset_duplicate_and_wrong_split_fail(self):
        dataset = self.root / "candidates.csv"
        dataset.write_text("repo_id,split\ndemo/ci,evaluation\nDemo/CI,evaluation\n")
        with self.assertRaisesRegex(ValueError, "Duplicate repository"):
            read_evaluation_rows(dataset)
        dataset.write_text("repo_id,split\ndemo/ci,development\n")
        with self.assertRaisesRegex(ValueError, "Unexpected split"):
            read_evaluation_rows(dataset)

    def test_invalid_repo_id_cannot_escape_output_path(self):
        bad = {**self.row, "repo_id": "../ci"}
        with self.assertRaises(ValueError):
            prepare_repository(bad, FakeReader(), self.root, "dataset-hash", set())

    def test_config_disallows_dispatch_and_invalid_arm_selection(self):
        config = self.root / "config.json"
        good = {"evaluation_id": "dry-run-1", "dataset": "eval.csv", "repository_limit": 1,
                "arms": ["original", "ci_cost", "rag"], "execution": {"dry_run": True}}
        config.write_text(json.dumps(good))
        self.assertEqual(load_config(config)["evaluation_id"], "dry-run-1")
        good["execution"]["dry_run"] = False
        config.write_text(json.dumps(good))
        with self.assertRaisesRegex(ValueError, "dry_run"):
            load_config(config)
        good["execution"]["dry_run"] = True
        good["arms"] = ["original"]
        config.write_text(json.dumps(good))
        with self.assertRaisesRegex(ValueError, "three arms"):
            load_config(config)

    def test_coordinator_produces_screening_report_and_a_candidate(self):
        dataset = self.root / "evaluation/repositories.csv"
        dataset.parent.mkdir(parents=True)
        dataset.write_text("selection_rank,repo_id,split\n1,demo/ci,evaluation\n")
        training = self.root / "research-data/zenodo_20340547/pattern_repo_candidates_20.csv"
        training.parent.mkdir(parents=True)
        training.write_text("repo_id,pattern_id\ntraining/sample,P-LIT-GHA-CACHE\n")
        cfg = {"evaluation_id": "pilot001", "dataset": "evaluation/repositories.csv",
               "repository_limit": 1, "arms": ["original", "ci_cost", "rag"],
               "execution": {"dry_run": True}}
        summary = prepare(cfg, reader=FakeReader(), project_root=self.root)
        self.assertEqual(summary["counts"], {"prepared": 1})
        self.assertEqual(summary["github_actions_runs"], 0)
        output = self.root / "evaluation/results/pilot001"
        self.assertTrue((output / "screening.csv").exists())
        self.assertEqual(len(list(output.glob("repositories/*/candidates/A/candidate.json"))), 1)
        self.assertEqual(prepare(cfg, reader=FakeReader(), project_root=self.root)["counts"], {"prepared": 1})


if __name__ == "__main__":
    unittest.main()
