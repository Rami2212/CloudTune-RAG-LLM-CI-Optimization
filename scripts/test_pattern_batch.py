"""Interactive batch and OpenRouter checks; all forks, runs and LLM replies are simulated."""
import copy
import json
import os
import unittest
from unittest.mock import MagicMock, patch

import experiment_environment as environment
import openrouter_optimizer as optimizer
import run_ci_experiment as runner
import run_pattern_batch as batch_module
import test_ci_experiment as fixtures

MODEL = "recursive/flint-v1.0:free"


class BatchGitHub(fixtures.FakeGitHub):
    def request(self, method, path, body=None):
        if method == "GET" and path in {"/repos/upstream/fork", "/repos/upstream/next-repo"}:
            return {"full_name": "upstream/fork", "source": {"full_name": "upstream/project"}}
        if method == "GET" and path.startswith("/repos/research/next-repo"):
            return super().request(method, path.replace("/repos/research/next-repo", "/repos/research/fork", 1), body)
        return super().request(method, path, body)


class PatternBatchTests(unittest.TestCase):
    setUp = fixtures.RunnerTests.setUp
    tearDown = fixtures.RunnerTests.tearDown

    def row(self):
        return {"repo_id": "upstream/fork", "pattern_id": "P-LIT-GHA-CACHE", "pattern_title": "Cache",
                "workflow_paths": ".github/workflows/ci.yml", "match_level": "metadata_signal"}

    def registry(self):
        path = self.root / "knowledge/extracted_patterns.jsonl"
        path.write_text(json.dumps({"pattern_id": "P-LIT-GHA-CACHE", "mechanism": "dependency_cache",
                                    "optimization_question": "Apply only dependency caching"}) + "\n", encoding="utf-8")

    def test_automatic_fork_waits_and_reuses_without_second_post(self):
        with patch.object(runner, "GitHub"):
            batch = batch_module.Batch("auto-fork", [self.row()], "research", "fixture-token", MODEL)
        remote = batch.github
        remote.request.side_effect = lambda method, path, body=None: (
            {"login": "research"} if path == "/user" else
            {"full_name": "research/fork"} if method == "POST" else {})
        missing = RuntimeError("GitHub GET /repos/research/fork: HTTP 404")
        ready = {"default_branch": "main"}
        with patch.object(batch_module, "validate_fork", side_effect=[missing, missing, ready, ready, ready]), \
             patch.object(batch_module.time, "sleep") as sleep:
            self.assertEqual(batch.ensure_fork(self.row(), "research/fork"), "research/fork")
            self.assertEqual(batch.ensure_fork(self.row(), "research/fork"), "research/fork")
        self.assertEqual(sum(call.args[0] == "POST" for call in remote.request.call_args_list), 1)
        sleep.assert_called_once_with(10)
        self.assertEqual(batch.state["fork_requests"]["upstream/fork"]["status"], "ready")

    def test_uncertain_fork_post_is_not_repeated_after_resume(self):
        with patch.object(runner, "GitHub"):
            batch = batch_module.Batch("lost-fork", [self.row()], "research", "fixture-token", MODEL)
        batch.github.request.side_effect = [{"login": "research"}, OSError("Response lost")]
        missing = RuntimeError("GitHub GET /repos/research/fork: HTTP 404")
        with patch.object(batch_module, "validate_fork", side_effect=missing):
            with self.assertRaisesRegex(RuntimeError, "not be automatically resent"):
                batch.ensure_fork(self.row(), "research/fork")
        with patch.object(runner, "GitHub"):
            resumed = batch_module.Batch("lost-fork", [self.row()], "research", "fixture-token", MODEL)
        with patch.object(batch_module, "validate_fork", side_effect=[missing, {"default_branch": "main"}]):
            resumed.ensure_fork(self.row(), "research/fork")
        self.assertFalse(any(call.args[0] == "POST" for call in resumed.github.request.call_args_list))

    def response(self, pattern="P-LIT-GHA-CACHE", decision="APPLY"):
        after = runner.npm_cache_candidate(fixtures.WORKFLOW, ["package-lock.json"])[0]
        return {"id": "fixture-response", "model": "fixture/model:free", "usage": {"prompt_tokens": 10, "completion_tokens": 10},
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"pattern_id": pattern,
                             "decision": decision, "rationale": "Only the selected caching mechanism.",
                             "workflow_yaml": after.decode() if decision == "APPLY" else None})}}]}

    def test_enter_gate_then_three_plus_three_runs_and_resume(self):
        self.registry()
        remote = BatchGitHub()
        reply = MagicMock()
        reply.__enter__.return_value.read.return_value = json.dumps(self.response()).encode()
        with patch.object(runner, "GitHub", return_value=remote), patch.dict(os.environ, {"OPENROUTER_API_KEY": "fixture-router-key"}), \
             patch.object(optimizer.urllib.request, "urlopen", return_value=reply) as llm:
            batch = batch_module.Batch("test-batch", [self.row()], "research", "fixture-token", MODEL)
            def enter(_prompt):
                self.assertEqual(remote.dispatches, 0, "No CI dispatch is allowed before Enter")
                return ""
            with patch("builtins.input", side_effect=enter) as prompt:
                batch.run()
                self.assertEqual(prompt.call_count, 1)
            self.assertEqual(remote.dispatches, 6)
            self.assertEqual(llm.call_count, 1)
            item = next(iter(batch.state["items"].values()))
            self.assertEqual(item["status"], "completed")
            directory = self.root / "research-data/experiments" / item["experiment_id"]
            records = runner.read_json(directory / "run_records.json")
            self.assertEqual(sum(r["arm"] == "baseline" for r in records), 3)
            self.assertEqual(sum(r["arm"] == "optimized" for r in records), 3)
            self.assertEqual(runner.read_json(directory / "case.json")["required_job_names"], ["build"])
            request_text = (directory / "llm_request.json").read_text()
            self.assertNotIn("fixture-router-key", request_text)
            self.assertNotIn("P-LIT-CUSTOM-TIMEOUT", request_text)
            self.assertEqual(json.loads(request_text)["provider"]["max_price"], {"prompt": 0, "completion": 0})
            with patch("builtins.input", side_effect=AssertionError("Completed rows must not prompt again")):
                batch.run()
            self.assertEqual(remote.dispatches, 6)

    def test_no_change_still_collects_three_comparison_runs(self):
        self.registry()
        remote = BatchGitHub()
        reply = MagicMock()
        reply.__enter__.return_value.read.return_value = json.dumps(self.response(decision="NO_CHANGE")).encode()
        with patch.object(runner, "GitHub", return_value=remote), patch.dict(os.environ, {"OPENROUTER_API_KEY": "fixture-router-key"}), \
             patch.object(optimizer.urllib.request, "urlopen", return_value=reply), patch("builtins.input", return_value=""):
            batch = batch_module.Batch("no-change", [self.row()], "research", "fixture-token", MODEL)
            batch.run()
        self.assertEqual(remote.dispatches, 6)
        item = next(iter(batch.state["items"].values()))
        directory = self.root / "research-data/experiments" / item["experiment_id"]
        case = runner.read_json(directory / "case.json")
        self.assertTrue(case["no_change"])
        self.assertEqual(case["realized_optimization_savings_percent"], 0)
        self.assertEqual((directory / "after.yml").read_bytes(), fixtures.WORKFLOW)

    def test_scenario_pattern_is_recorded_without_fork_or_dispatch(self):
        row = {**self.row(), "pattern_id": "P-LIT-CANCEL-STALE"}
        with patch("builtins.input", side_effect=AssertionError("Unsupported scenario must not request a fork")):
            batch = batch_module.Batch("blocked", [row], "research", "fixture-token", MODEL)
            batch.run()
        self.assertEqual(next(iter(batch.state["items"].values()))["status"], "blocked")

    def test_next_repository_is_shown_after_six_runs(self):
        self.registry()
        remote = BatchGitHub()
        reply = MagicMock()
        reply.__enter__.return_value.read.return_value = json.dumps(self.response()).encode()
        rows = [self.row(), {**self.row(), "repo_id": "upstream/next-repo"}]
        with patch.object(runner, "GitHub", return_value=remote), patch.dict(os.environ, {"OPENROUTER_API_KEY": "fixture-router-key"}), \
             patch.object(optimizer.urllib.request, "urlopen", return_value=reply), patch("builtins.input", side_effect=["", "skip"]) as prompt:
            batch = batch_module.Batch("next-repo", rows, "research", "fixture-token", MODEL)
            batch.run()
        self.assertEqual(remote.dispatches, 6)
        self.assertEqual(prompt.call_count, 2)
        self.assertEqual([item["status"] for item in batch.state["items"].values()], ["completed", "skipped"])

    def test_scope_guard_rejects_unrelated_edit_and_paid_model(self):
        before = runner.workflow_doc(fixtures.WORKFLOW)
        after = copy.deepcopy(before)
        after["jobs"]["build"]["timeout-minutes"] = 5
        self.assertIn("CACHE_PATTERN_NON_STEP_CONFIGURATION_CHANGED", optimizer.scope_errors(before, after, "dependency_cache"))
        after = copy.deepcopy(before)
        after["jobs"]["build"]["steps"].pop()
        self.assertTrue(optimizer.scope_errors(before, after, "dependency_cache"))
        with self.assertRaisesRegex(ValueError, "free"):
            optimizer.validate_free_model("vendor/paid-model")

    def test_wrong_pattern_reply_is_rejected(self):
        self.registry()
        directory = self.root / "llm-only"
        directory.mkdir()
        reply = MagicMock()
        reply.__enter__.return_value.read.return_value = json.dumps(self.response(pattern="P-LIT-CUSTOM-TIMEOUT")).encode()
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "fixture-router-key"}), patch.object(optimizer.urllib.request, "urlopen", return_value=reply):
            with self.assertRaisesRegex(ValueError, "different pattern_id"):
                optimizer.generate(directory, {"pattern": {"pattern_id": "P-LIT-GHA-CACHE"},
                                               "baseline_records": [], "required_job_names": ["build"]}, fixtures.WORKFLOW, MODEL)

    def test_env_loading_and_redaction_and_distinct_batch_ids(self):
        path = self.root / ".env"
        path.write_text("GITHUB_USERNAME=research\nOPENROUTER_API_KEY='fixture-new-key'\nGITHUB_TOKEN=from-file\n", encoding="utf-8")
        with patch.dict(os.environ, {"GITHUB_TOKEN": "already-exported-token"}, clear=True):
            environment.load_env(path)
            self.assertEqual(os.environ["GITHUB_USERNAME"], "research")
            self.assertEqual(os.environ["GITHUB_TOKEN"], "already-exported-token")
            self.assertNotIn("fixture-new-key", environment.redact("error fixture-new-key"))
        self.assertNotEqual(batch_module.case_id("same-prefix-1234567890-A", self.row()), batch_module.case_id("same-prefix-1234567890-B", self.row()))


if __name__ == "__main__":
    unittest.main()
