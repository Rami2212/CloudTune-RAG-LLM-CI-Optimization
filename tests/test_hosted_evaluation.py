"""Offline protocol checks; no workflow dispatch, fork writes, or network requests."""
from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evaluation.candidate_validator import validate_candidate
from evaluation.ci_executor import (
    ForkExperiment, RunPending, ensure_dispatch, job_timing_metrics,
    summarize_records, verify_fork,
)
from evaluation.hosted_pipeline import StateStore, _config
from evaluation.results_exporter import summarize_cohort


ORIGINAL = b"""name: CI
on:
  workflow_dispatch:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: echo ok
"""


class FakeRunnerGitHub:
    """Deterministic Actions evidence fixture with a long GitHub runner queue."""
    def __init__(self, status="completed"):
        self.status = status

    def request(self, method, path, body=None):
        assert method == "GET", (method, path)
        if path.endswith("/actions/runs/901"):
            return {"status": self.status, "conclusion": "success", "run_attempt": 1,
                    "workflow_id": 42, "head_sha": "b" * 40,
                    "head_branch": "cloudtune/demo-a", "event": "workflow_dispatch",
                    "created_at": "2026-11-01T09:00:00Z",
                    "run_started_at": "2026-11-01T09:20:00Z"}
        raise AssertionError(path)

    def all(self, path, key):
        assert key == "jobs", path
        return [{"id": 10, "name": "test", "status": "completed",
                 "conclusion": "success", "started_at": "2026-11-01T11:00:00Z",
                 "completed_at": "2026-11-01T11:01:00Z", "runner_name": "runner-1",
                 "labels": ["ubuntu-24.04"]}]




class FakeGitState:
    """Tiny Git data API emulator for atomic state/archive checkpoints."""
    def __init__(self):
        self.head = "a" * 40
        self.blobs = {}
        self.files = {}
        self.commits = {}
        self.serial = 1

    def request(self, method, path, body=None):
        if method == "GET" and "/git/ref/heads/" in path:
            return {"object": {"sha": self.head}}
        if method == "GET" and "/git/commits/" in path:
            return {"tree": {"sha": "b" * 40}}
        if method == "GET" and "/contents/" in path:
            target = path.split("/contents/", 1)[1].split("?", 1)[0]
            sha = self.files[target]
            return {"sha": sha, "content": base64.b64encode(self.blobs[sha]).decode()}
        if method == "POST" and path.endswith("/git/blobs"):
            value = base64.b64decode(body["content"])
            sha = hashlib.sha1(b"blob " + str(len(value)).encode() + b"\0" + value).hexdigest()
            self.blobs[sha] = value
            return {"sha": sha}
        if method == "POST" and path.endswith("/git/trees"):
            self.files.update({item["path"]: item["sha"] for item in body["tree"]})
            return {"sha": "c" * 40}
        if method == "POST" and path.endswith("/git/commits"):
            self.serial += 1
            return {"sha": f"{self.serial:040x}"}
        if method == "PATCH" and "/git/refs/heads/" in path:
            self.head = body["sha"]
            return {"object": {"sha": self.head}}
        raise AssertionError((method, path, body))

    def blob(self, repository, sha):
        return self.blobs[sha]


class HostedProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = {"fork_repo": "research/test", "workflow_id": 42,
                      "pending": {"arm": "A", "repeat": 1, "run_id": 901},
                      "records": [], "arms": {"A": {"sha": "b" * 40,
                                  "branch": "cloudtune/demo-a", "workflow_sha256": "hash"}}}

    def experiment(self, status="completed", max_wait_seconds=10):
        return ForkExperiment(FakeRunnerGitHub(status), repo_id="source/test",
                  workflow_path=".github/workflows/ci.yml", source_sha="a" * 40,
                  original=ORIGINAL, evaluation_id="sample", max_wait_seconds=max_wait_seconds,
                  poll_seconds=1)

    def test_two_hour_queue_excluded_from_execution_seconds(self):
        callbacks = []
        record = self.experiment().execute(self.state, lambda: callbacks.append(1),
                                           arm="A", repeat=1, required=["test"], max_total=3)
        self.assertEqual(record["initial_queue_seconds"], 7200)
        self.assertEqual(record["workflow_elapsed_seconds"], 60)
        self.assertEqual(record["sum_job_runtime_seconds"], 60)
        self.assertEqual(record["first_job_started_at"], "2026-11-01T11:00:00Z")
        self.assertTrue(record["comparable"])
        self.assertIsNone(self.state["pending"])
        self.assertEqual(len(callbacks), 1)

    def test_internal_runner_queue_is_excluded_from_active_elapsed(self):
        # Job 1: 10:00-10:02, job 2 queued for 30 minutes, then 10:32-10:35.
        # The raw wall makespan is 35 minutes, but jobs only executed 5 minutes.
        jobs = [
            {"started_at": "2026-11-01T10:00:00Z", "completed_at": "2026-11-01T10:02:00Z"},
            {"started_at": "2026-11-01T10:32:00Z", "completed_at": "2026-11-01T10:35:00Z"},
        ]
        metrics = job_timing_metrics(jobs)
        self.assertEqual(metrics["active_seconds"], 300)
        self.assertEqual(metrics["makespan_seconds"], 2100)
        self.assertEqual(metrics["idle_gap_seconds"], 1800)

    def test_parallel_jobs_do_not_double_count_active_time(self):
        jobs = [
            {"started_at": "2026-11-01T10:00:00Z", "completed_at": "2026-11-01T10:03:00Z"},
            {"started_at": "2026-11-01T10:01:00Z", "completed_at": "2026-11-01T10:04:00Z"},
            {"started_at": "2026-11-01T10:04:00Z", "completed_at": "2026-11-01T10:05:00Z"},
        ]
        metrics = job_timing_metrics(jobs)
        self.assertEqual(metrics["active_seconds"], 300)
        self.assertEqual(metrics["makespan_seconds"], 300)
        self.assertEqual(metrics["idle_gap_seconds"], 0)

    def test_dispatch_required_inputs_without_default_fail_before_fork_write(self):
        workflow = ORIGINAL.replace(b"  workflow_dispatch:",
           b"  workflow_dispatch:\n    inputs:\n      environment:\n        required: true")
        with self.assertRaisesRegex(ValueError, "DISPATCH_INPUT_MISSING_DEFAULT"):
            ensure_dispatch(workflow)

    def test_github_no_job_start_is_platform_inconclusive(self):
        github = FakeRunnerGitHub()
        github.all = lambda path, key: []
        runner = ForkExperiment(github, repo_id="source/test",
                 workflow_path=".github/workflows/ci.yml", source_sha="a" * 40,
                 original=ORIGINAL, evaluation_id="sample", max_wait_seconds=10,
                 poll_seconds=1)
        record = runner.execute(self.state, lambda: None, arm="A", repeat=1,
                                required=["test"], max_total=3)
        self.assertEqual(record["failure_class"], "PLATFORM_NO_JOB_START")
        self.assertIsNone(record["workflow_elapsed_seconds"])
        self.assertFalse(record["comparable"])
        self.assertEqual(len(self.state["records"]), 1)

    def test_queued_run_stays_pending_and_is_not_redispatched(self):
        with self.assertRaises(RunPending):
            self.experiment(status="queued", max_wait_seconds=0).execute(
                self.state, lambda: None, arm="A", repeat=1, required=["test"], max_total=3)
        self.assertEqual(self.state["pending"]["run_id"], 901)
        self.assertEqual(self.state["records"], [])

    def test_no_savings_claimed_without_both_arms(self):
        data = [{"arm":"A", "comparable":True, "workflow_elapsed_seconds":100,
                 "sum_job_runtime_seconds":110}]
        stats = summarize_records(data)
        self.assertIsNone(stats["B"]["elapsed_saving_percent_vs_A"])
        self.assertIsNone(stats["C"]["elapsed_saving_percent_vs_A"])

    def test_invalid_yaml_is_classified_not_raised(self):
        result = validate_candidate(ORIGINAL, b"name: test\njobs:\n  x: [bad\n")
        self.assertEqual(result["verdict"], "FAIL")

    def test_unapproved_cache_path_is_rejected_even_if_syntax_valid(self):
        bad = ORIGINAL.replace(b"      - run: echo ok", b"      - name: Cache SSH\n        uses: actions/cache@v4\n        with:\n          path: ~/.ssh\n          key: test\n      - run: echo ok")
        with patch("evaluation.candidate_validator._actionlint", return_value={"status": "PASS", "reason":""}):
            verdict = validate_candidate(ORIGINAL, bad)
        self.assertNotEqual(verdict["verdict"], "PASS")

    def test_cache_key_must_depend_on_runner_and_dependency_lockfile(self):
        bad = ORIGINAL.replace(b"      - run: echo ok", b"      - name: Cache dependencies\n        uses: actions/cache@v4\n        with:\n          path: ~/.npm\n          key: constant\n      - run: echo ok")
        with patch("evaluation.candidate_validator._actionlint", return_value={"status": "PASS", "reason": ""}):
            outcome = validate_candidate(ORIGINAL, bad)
        self.assertNotEqual(outcome["verdict"], "PASS")

    def test_allowlist_accepts_source_bound_dependency_cache(self):
        good = ORIGINAL.replace(b"      - run: echo ok", b"      - name: Cache dependencies\n        uses: actions/cache@v4\n        with:\n          path: ~/.npm\n          key: ${{ runner.os }}-${{ hashFiles('package-lock.json') }}\n      - run: echo ok")
        with patch("evaluation.candidate_validator._actionlint", return_value={"status": "PASS", "reason": ""}):
            outcome = validate_candidate(ORIGINAL, good)
        self.assertEqual(outcome["verdict"], "PASS")

    def test_controller_schedule_recovers_frozen_code_revision(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/cloudtune-evaluation.yml").read_text()
        self.assertIn('controller_sha: ${{ steps.check.outputs.controller_sha }}', workflow)
        self.assertIn('ref: ${{ needs.preflight.outputs.controller_sha }}', workflow)
        self.assertIn('CLOUDTUNE_CONTROLLER_SHA: ${{ needs.preflight.outputs.controller_sha }}', workflow)
        self.assertIn('INCONCLUSIVE_PLATFORM', workflow)
        self.assertIn('cmp -s "$RUNNER_TEMP/current-controller.yml"', workflow)

    def test_pack_is_deterministic_and_does_not_depend_on_local_paths(self):
        root = self.root / "snapshot"
        (root / "source").mkdir(parents=True)
        (root / "source" / "original.yml").write_bytes(ORIGINAL)
        (root / "manifest.json").write_text("{}")
        first = StateStore._pack(root)
        self.assertEqual(first, StateStore._pack(root))
        self.assertTrue(first.startswith(b"PK"))

    def test_state_archive_survives_a_new_controller_process(self):
        import evaluation.hosted_pipeline as host
        source = self.root / "source-snapshot"
        (source / "source").mkdir(parents=True)
        (source / "source" / "original.yml").write_bytes(ORIGINAL)
        (source / "manifest.json").write_text(json.dumps({"repo_id": "demo/repo"}))
        dataset = self.root / "dataset.csv"
        dataset.write_text("repo_id,split\ndemo/repo,evaluation\n")
        record = {"evaluation_id": "study", "dataset": "dataset.csv",
                  "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
                  "repositories": {"demo/repo": {"status": "SELECTED"}},
                  "screening": [{"repo_id": "demo/repo", "status": "prepared"}]}
        fake = FakeGitState()
        with patch.object(host, "ROOT", self.root):
            controller = StateStore(fake, "control/repo", "study")
            controller.save(record, snapshots={"demo/repo": source})
            second_controller = StateStore(fake, "control/repo", "study")
            recovered = second_controller.load()
            out = self.root / "restored"
            entries = second_controller.restore(out, recovered)
        manifest = Path(entries[0]["manifest_path"])
        self.assertEqual(json.loads(manifest.read_text())["repo_id"], "demo/repo")
        self.assertEqual((manifest.parent / "source/original.yml").read_bytes(), ORIGINAL)
        archive_path = recovered["repositories"]["demo/repo"]["archive"]["path"]
        self.assertIn(archive_path, fake.files)

    def test_remote_checkpoint_refuses_external_branch_mutation(self):
        fake = FakeGitState()
        controller = StateStore(fake, "control/repo", "study")
        fake.head = "f" * 40
        with self.assertRaisesRegex(RuntimeError, "another writer"):
            controller.save({"repositories": {}, "evaluation_id": "study"})

    def test_fork_must_be_owned_by_research_account(self):
        fork = {"owner": {"login": "wrong"}, "fork": True, "permissions": {"push": True},
                "source": {"full_name": "source/test"}}
        with self.assertRaisesRegex(ValueError, "authorized"):
            verify_fork(fork, "source/test", "research")

    def test_head_to_head_c_vs_b_requires_actual_paired_runs(self):
        record = []
        for arm, elapsed in (("A", 100), ("B", 90), ("C", 80)):
            for rep in range(3):
                record.append({"arm":arm, "comparable":True,
                               "workflow_elapsed_seconds":elapsed,
                               "sum_job_runtime_seconds":elapsed,
                               "initial_queue_seconds":7200})
        complete = summarize_records(record, repetitions=3)
        self.assertAlmostEqual(complete["C"]["elapsed_saving_percent_vs_B"], 100 * 10 / 90)
        partial = summarize_records(record[:-1], repetitions=3)
        self.assertIsNone(partial["C"]["elapsed_saving_percent_vs_B"])

    def test_aggregate_requires_complete_repos_and_preserves_denominators(self):
        dataset = {"repo1": {"status": "COMPLETE", "run_statistics": {
                        "C": {"elapsed_saving_percent_vs_B": 15.0}}},
                   "repo2": {"status": "INCOMPLETE", "run_statistics": {
                        "C": {"elapsed_saving_percent_vs_B": 99.0}}},
                   "repo3": {"status": "SKIPPED", "run_statistics": {}}}
        summary = summarize_cohort(dataset, bootstrap_samples=100)
        self.assertEqual(summary["total_selected"], 3)
        self.assertEqual(summary["incomplete_repositories"], 1)
        comparison = summary["comparisons"]["C_vs_B_elapsed"]
        self.assertEqual(comparison["paired_repositories"], 1)
        self.assertEqual(comparison["median_saving_percent"], 15.0)
        self.assertIsNone(comparison["bootstrap_95pct_ci_percent"])

    def test_hosted_config_validates_without_tokens_or_git_api(self):
        config = {
            "evaluation_id": "test", "dataset":"dataset.csv", "dataset_split":"evaluation",
            "repository_start_at":1, "repository_limit":1,
            "arms":["original","ci_cost","rag"],"repetitions":3,"warmup_runs":0,
            "rag":{"embedding_model":"BAAI/bge-m3", "embedding_revision":"AUTO_PIN_SINGLE",
                   "dataset_sha256":"a"*64,"generator_model":"specific/model:free"},
            "execution":{"dry_run":False,"cache_regime":"uncontrolled"}}
        path = self.root / "hosted.json"
        path.write_text(json.dumps(config))
        self.assertEqual(_config(path)["evaluation_id"], "test")


if __name__ == "__main__":
    unittest.main()
