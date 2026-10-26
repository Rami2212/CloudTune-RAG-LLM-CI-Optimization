"""Offline protocol tests. All API calls and experiment data use temporary fixtures."""
import base64
import copy
import csv
import json
import tempfile
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest.mock import patch

import run_ci_experiment as runner


WORKFLOW = b"""name: CI
on:
  workflow_dispatch:
  push:
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '22'
      - run: npm ci
      - run: npm test
"""


class FakeGitHub:
    def __init__(self):
        self.prefix = "/repos/research/fork"
        self.refs, self.commits, self.runs, self.jobs = {}, {}, {}, {}
        self.blobs = {"workflow": WORKFLOW, "lock": b'{"lockfileVersion":3}', "package": b'{}'}
        self.trees = {"tree-source": {"tree": [
            {"path": ".github/workflows/ci.yml", "mode": "100644", "type": "blob", "sha": "workflow", "size": len(WORKFLOW)},
            {"path": "package-lock.json", "mode": "100644", "type": "blob", "sha": "lock", "size": 21},
            {"path": "package.json", "mode": "100644", "type": "blob", "sha": "package", "size": 2}], "truncated": False}}
        self.commit = {"sha": "source-sha", "commit": {"tree": {"sha": "tree-source"}}}
        self.dispatches = 0
        self.lose_response = False
        self.fail_next = False

    def blob(self, repo, blob_sha):
        return self.blobs[blob_sha]

    def request(self, method, path, body=None):
        route = path.removeprefix(self.prefix)
        if method == "GET":
            if route == "":
                return {"fork": True, "permissions": {"push": True}, "default_branch": "main", "parent": {"full_name": "upstream/project"}}
            if route == "/commits/main":
                return copy.deepcopy(self.commit)
            if route.startswith("/git/trees/"):
                return copy.deepcopy(self.trees[route.split("/")[-1].split("?")[0]])
            if route == "/actions/workflows/ci.yml":
                return {"id": 42, "state": "active"}
            if route.startswith("/git/ref/heads/"):
                branch = route.removeprefix("/git/ref/heads/")
                if branch not in self.refs:
                    raise RuntimeError("GitHub GET ref: HTTP 404")
                return {"object": {"sha": self.refs[branch]}}
            if route.startswith("/actions/runs/"):
                return copy.deepcopy(self.runs[int(route.split("/")[-1])])
        if method == "POST":
            if route == "/git/blobs":
                blob_sha = f"blob-{len(self.blobs)}"
                self.blobs[blob_sha] = base64.b64decode(body["content"])
                return {"sha": blob_sha}
            if route == "/git/trees":
                tree_sha = f"tree-{len(self.trees)}"
                items = {e["path"]: e for e in self.trees[body["base_tree"]]["tree"]}
                items.update({e["path"]: e for e in body["tree"]})
                self.trees[tree_sha] = {"tree": list(items.values()), "truncated": False}
                return {"sha": tree_sha}
            if route == "/git/commits":
                commit_sha = f"commit-{len(self.commits)}"
                self.commits[commit_sha] = copy.deepcopy(body)
                return {"sha": commit_sha}
            if route == "/git/refs":
                self.refs[body["ref"].removeprefix("refs/heads/")] = body["sha"]
                return {}
            if route == "/actions/workflows/42/dispatches":
                self.dispatches += 1
                run_id = self.dispatches
                optimized = body["ref"].endswith("-optimized")
                end = "2026-10-26T00:01:30Z" if optimized else "2026-10-26T00:01:50Z"
                conclusion = "failure" if self.fail_next else "success"
                self.fail_next = False
                self.runs[run_id] = {"id": run_id, "head_sha": self.refs[body["ref"]], "head_branch": body["ref"],
                                     "workflow_id": 42, "event": "workflow_dispatch", "status": "completed",
                                     "run_attempt": 1, "conclusion": conclusion,
                                     "created_at": "2026-10-26T00:00:00Z", "run_started_at": "2026-10-26T00:00:10Z"}
                self.jobs[run_id] = [{"id": run_id * 10, "name": "build", "status": "completed", "conclusion": conclusion,
                                      "started_at": "2026-10-26T00:00:10Z", "completed_at": end,
                                      "labels": ["ubuntu-latest"], "steps": [{"name": "test", "status": "completed",
                                      "conclusion": conclusion, "started_at": "2026-10-26T00:00:10Z", "completed_at": end}]}]
                if self.lose_response:
                    self.lose_response = False
                    raise RuntimeError("simulated response lost after accepted dispatch")
                return None  # Traditional GitHub 204 response, without a run ID.
        raise AssertionError((method, path, body))

    def pages(self, path, key):
        if key == "workflow_runs":
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)
            return [copy.deepcopy(r) for r in self.runs.values()
                    if r["head_branch"] == query["branch"][0] and r["head_sha"] == query["head_sha"][0]]
        if key == "jobs":
            run_id = int(path.split("/actions/runs/")[1].split("/")[0])
            return copy.deepcopy(self.jobs[run_id])
        if key == "artifacts":
            return []
        raise AssertionError((path, key))


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp_base = (runner.ROOT / "tmp").resolve()
        self.temp_base.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="ci-runner-test-", dir=self.temp_base)
        self.root = Path(self.temp.name)
        if not self.root.resolve().is_relative_to(self.temp_base):
            raise RuntimeError("Test directory escaped the workspace temporary root")
        self.root_patch = patch.object(runner, "ROOT", self.root)
        self.root_patch.start()
        self.lint_patch = patch.object(runner.shutil, "which", return_value=None)
        self.lint_patch.start()
        self.print_patch = patch("builtins.print")
        self.print_patch.start()
        knowledge = self.root / "knowledge"
        knowledge.mkdir()
        (knowledge / "extracted_patterns.jsonl").write_text(json.dumps({
            "pattern_id": "P-LIT-GHA-CACHE", "optimization_question": "Assess dependency caching"}) + "\n", encoding="utf-8")
        self.config_path = self.root / "pilot.json"
        runner.write_json(self.config_path, {"experiment_id": "fixture-only", "fork_repo": "research/fork",
            "workflow_path": ".github/workflows/ci.yml", "pattern_id": "P-LIT-GHA-CACHE",
            "required_job_names": ["build"], "optimizer": {"type": "npm-cache"}, "max_total_runs": 10})

    def tearDown(self):
        self.print_patch.stop()
        self.lint_patch.stop()
        self.root_patch.stop()
        if not self.root.resolve().is_relative_to(self.temp_base):
            raise RuntimeError("Refusing cleanup outside the verified temporary root")
        self.temp.cleanup()

    def experiment(self):
        experiment = runner.Experiment(runner.load_config(self.config_path))
        experiment.github = FakeGitHub()
        return experiment

    def test_yaml_on_boolean_and_duplicate_keys(self):
        doc = runner.workflow_doc(WORKFLOW)
        self.assertIn("workflow_dispatch", doc["on"])
        self.assertNotIn(True, doc)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            runner.workflow_doc(WORKFLOW + b"jobs: {}\n")

    def test_cache_candidate_preserves_workload_and_rejects_unsafe_layout(self):
        after, changes = runner.npm_cache_candidate(WORKFLOW, ["package-lock.json"])
        self.assertEqual(len(changes), 1)
        self.assertEqual(runner.protected_contract(runner.workflow_doc(WORKFLOW), runner.workflow_doc(after)), [])
        self.assertEqual(runner.workflow_doc(after)["jobs"]["build"]["steps"][1]["with"]["cache"], "npm")
        for unsupported in [after, WORKFLOW.replace(b"run: npm ci", b"run: cd app && npm ci"), WORKFLOW.replace(b"actions/checkout@v4", b"other/checkout@v4")]:
            with self.assertRaisesRegex(ValueError, "NO_CHANGE"):
                runner.npm_cache_candidate(unsupported, ["package-lock.json"])

    def test_parallel_runtime_is_not_workflow_elapsed(self):
        run = {"run_started_at": "2026-10-26T00:00:00Z", "created_at": "2026-10-25T23:59:50Z"}
        jobs = [{"id": i, "name": name, "status": "completed", "conclusion": "success",
                 "started_at": "2026-10-26T00:00:00Z", "completed_at": end}
                for i, name, end in [(1, "build", "2026-10-26T00:01:40Z"), (2, "test", "2026-10-26T00:01:00Z")]]
        result = runner.metrics(run, jobs, ["build", "test"])
        self.assertEqual(result["workflow_elapsed_seconds"], 100)
        self.assertEqual(result["sum_job_runtime_seconds"], 160)
        self.assertEqual(result["initial_queue_seconds"], 10)
        self.assertTrue(result["required_checks_pass"])
        jobs[0]["conclusion"] = "cancelled"
        self.assertFalse(runner.metrics(run, jobs, ["build"])["required_checks_pass"])
        jobs[0]["completed_at"] = None
        self.assertIsNone(runner.metrics(run, jobs, ["build"])["sum_job_runtime_seconds"])

    def test_contract_rejects_dropped_command_or_matrix(self):
        before = runner.workflow_doc(WORKFLOW)
        after = copy.deepcopy(before)
        after["jobs"]["build"]["steps"].pop()
        self.assertIn("RUN_COMMAND_OR_CONTEXT_CHANGED:build", runner.protected_contract(before, after))
        after = copy.deepcopy(before)
        after["jobs"]["build"]["strategy"] = {"matrix": {"node": [22]}}
        self.assertIn("JOB_FIELD_CHANGED:build:strategy", runner.protected_contract(before, after))

    def test_full_cycle_archives_two_revisions_and_requires_behavior_review(self):
        experiment = self.experiment()
        experiment.prepare()
        experiment.measure("baseline")
        experiment.optimize()
        experiment.measure("optimized")
        case = experiment.report()
        self.assertEqual(experiment.github.dispatches, 10)
        self.assertEqual(len(experiment.state["records"]), 10)
        self.assertEqual((experiment.directory / "before.yml").read_bytes(), WORKFLOW)
        self.assertNotEqual(experiment.state["arms"]["baseline"]["sha"], experiment.state["arms"]["optimized"]["sha"])
        self.assertEqual(case["outcome"], "inconclusive")
        self.assertEqual(case["elapsed_savings_percent"], 20)
        with (self.root / "research-data/runs/experiment_runs.csv").open() as handle:
            self.assertEqual(len(list(csv.DictReader(handle))), 10)
        self.assertTrue((experiment.directory / "runs/10-attempt-1/jobs.json").exists())
        self.assertTrue((experiment.directory / "artifact_manifest.json").exists())
        runner.write_json(experiment.directory / "candidate_review.json", {
            "reviewed_by": "fixture reviewer", "diff_sha256": case["patch_sha256"], "verdict": "PASS",
            "rationale": "Synthetic fixture validates the classification gate only.",
            "behavior_validation": {"status": "PASS", "evidence_refs": ["test-fixture-only"]}})
        self.assertEqual(experiment.report()["outcome"], "safe_success")
        experiment.measure("baseline")
        experiment.measure("optimized")
        self.assertEqual(experiment.github.dispatches, 10, "Resume must not duplicate completed slots")

    def test_lost_dispatch_response_resumes_without_duplicate(self):
        experiment = self.experiment()
        experiment.prepare()
        experiment.github.lose_response = True
        with self.assertRaisesRegex(RuntimeError, "response lost"):
            experiment.measure("baseline")
        self.assertIsNotNone(experiment.state["pending"])
        remote = experiment.github
        resumed = runner.Experiment(runner.load_config(self.config_path))
        resumed.github = remote
        resumed.measure("baseline")
        self.assertEqual(remote.dispatches, 5)
        self.assertEqual(len(resumed.state["records"]), 5)
        self.assertIsNone(resumed.state["pending"])

    def test_failed_baseline_is_retained_and_blocks_optimization(self):
        experiment = self.experiment()
        experiment.prepare()
        experiment.github.fail_next = True
        experiment.measure("baseline")
        self.assertEqual(experiment.state["records"][0]["conclusion"], "failure")
        self.assertFalse(experiment.state["records"][0]["required_checks_pass"])
        with self.assertRaisesRegex(ValueError, "Baseline is not reproducibly successful"):
            experiment.optimize()
        self.assertEqual(experiment.report()["outcome"], "inconclusive")

    def test_missing_dispatch_fails_before_any_remote_mutation(self):
        experiment = self.experiment()
        experiment.github.blobs["workflow"] = WORKFLOW.replace(b"  workflow_dispatch:\n", b"")
        with self.assertRaisesRegex(ValueError, "no workflow_dispatch"):
            experiment.prepare()
        self.assertEqual(experiment.github.commits, {})
        self.assertEqual(experiment.github.dispatches, 0)

    def test_config_freeze_and_budget(self):
        experiment = self.experiment()
        experiment.prepare()
        experiment.state["dispatch_count"] = 10
        with self.assertRaisesRegex(RuntimeError, "budget exhausted"):
            experiment.measure("baseline")
        config = runner.load_config(self.config_path)
        config["repetitions"] = 4
        with self.assertRaisesRegex(ValueError, "Configuration changed"):
            runner.Experiment(config)

    def test_external_proposal_requires_review_of_the_exact_diff(self):
        candidate = self.root / "candidate.yml"
        candidate.write_bytes(runner.npm_cache_candidate(WORKFLOW, ["package-lock.json"])[0])
        config = runner.read_json(self.config_path)
        config["optimizer"] = {"type": "candidate-file", "path": str(candidate)}
        runner.write_json(self.config_path, config)
        experiment = self.experiment()
        experiment.prepare()
        experiment.measure("baseline")
        experiment.optimize()
        with self.assertRaisesRegex(ValueError, "awaits review"):
            experiment.measure("optimized")
        self.assertEqual(experiment.github.dispatches, 5)
        runner.write_json(experiment.directory / "candidate_review.json", {
            "reviewed_by": "fixture reviewer", "verdict": "PASS", "rationale": "Fixture only", "diff_sha256": "wrong-hash"})
        with self.assertRaisesRegex(ValueError, "exact current diff hash"):
            experiment.measure("optimized")
        self.assertEqual(experiment.github.dispatches, 5)

    def test_warmups_stored_and_excluded_from_summaries(self):
        config = runner.read_json(self.config_path)
        config.update({"warmup_runs": 1, "max_total_runs": 12})
        runner.write_json(self.config_path, config)
        experiment = self.experiment()
        experiment.prepare()
        experiment.measure("baseline")
        experiment.optimize()
        experiment.measure("optimized")
        case = experiment.report()
        self.assertEqual(len(experiment.state["records"]), 12)
        self.assertEqual(sum(r["warmup"] for r in experiment.state["records"]), 2)
        self.assertEqual(case["arms"]["baseline"]["total_runs"], 5)
        self.assertEqual(case["arms"]["optimized"]["total_runs"], 5)

    def test_artifact_tampering_stops_before_optimized_dispatch(self):
        experiment = self.experiment()
        experiment.prepare()
        experiment.measure("baseline")
        experiment.optimize()
        with (experiment.directory / "after.yml").open("ab") as handle:
            handle.write(b"# changed after validation\n")
        with self.assertRaisesRegex(ValueError, "artifact changed"):
            experiment.measure("optimized")
        self.assertEqual(experiment.github.dispatches, 5)

    def test_post_is_not_retried_and_credentials_not_logged(self):
        ledger = self.root / "api_calls.jsonl"
        client = runner.GitHub("fixture-secret-value", ledger)
        error = urllib.error.HTTPError("https://api.github.com/path", 503, "temporarily unavailable", {}, None)
        with patch.object(runner.urllib.request, "urlopen", side_effect=error) as request:
            with self.assertRaisesRegex(RuntimeError, "HTTP 503"):
                client.request("POST", "/repos/research/fork/actions/workflows/42/dispatches", {"ref": "branch"})
            self.assertEqual(request.call_count, 1)
            self.assertEqual(request.call_args.args[0].get_header("Content-type"), "application/json")
        self.assertNotIn("fixture-secret-value", ledger.read_text())

    def test_diff_preserves_missing_final_newline_marker(self):
        result = runner.workflow_diff(b"one\ntwo", b"one\nthree\n", ".github/workflows/ci.yml")
        self.assertIn("-two\n\\ No newline at end of file\n+three\n", result)


if __name__ == "__main__":
    unittest.main()
