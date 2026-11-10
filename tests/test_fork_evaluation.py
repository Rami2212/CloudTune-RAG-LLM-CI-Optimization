"""Offline protocol checks; no workflow dispatch, fork writes, or network requests."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import evaluation.fork_pipeline as pipeline

from evaluation.candidate_validator import validate_candidate
from evaluation.ci_executor import (
    ForkExperiment, GitHubError, RunPending, automatic_fork_deletion_enabled,
    ensure_dispatch, job_timing_metrics, summarize_records, verify_fork,
)
from evaluation.fork_pipeline import StateStore, _config, exclusive_controller
from evaluation.results_exporter import summarize_cohort
from evaluation.third_party.ci_cost.setup import _safe_tool_environment


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




class HostedProtocolTests(unittest.TestCase):
    def test_inline_dispatch_harness_preserves_events_and_jobs(self):
        from evaluation.repository_preparation import workflow_doc
        for trigger, events in (("[ push ]", ["push"]), ("push", ["push"]),
                                ("[push, pull_request]", ["push", "pull_request"])):
            for newline in ("\n", "\r\n"):
                source = ORIGINAL.replace(b"on:\n  workflow_dispatch:", ("on: " + trigger).encode())
                source = source.replace(b"\n", newline.encode())
                result = ensure_dispatch(source)
                doc = workflow_doc(result)
                self.assertEqual(doc["on"], {"workflow_dispatch": None, **{e: None for e in events}})
                self.assertEqual(result.split(b"jobs:", 1)[1], source.split(b"jobs:", 1)[1])
                self.assertEqual(ensure_dispatch(result), result)

    def test_concurrency_change_is_supported_by_general_candidate_gate(self):
        candidate = ORIGINAL + b"concurrency:\n  group: ${{ github.workflow }}-${{ github.ref }}\n  cancel-in-progress: true\n"
        with patch("evaluation.candidate_validator._actionlint", return_value={"status": "PASS"}):
            self.assertEqual(validate_candidate(ORIGINAL, candidate)["verdict"], "PASS")

    def test_ancillary_workflow_isolation_preserves_source_files(self):
        experiment = self.experiment()
        tree = {"tree": [
            {"type": "blob", "path": ".github/workflows/ci.yml"},
            {"type": "blob", "path": ".github/workflows/release-drafter.yml"},
            {"type": "blob", "path": ".github/workflows/publish.yaml"},
            {"type": "blob", "path": "src/main.py"},
            {"type": "blob", "path": ".github/release-drafter.yml"}]}
        removals = experiment._ancillary_paths(tree)
        self.assertEqual(removals, [".github/workflows/publish.yaml",
                                    ".github/workflows/release-drafter.yml"])
        github = MagicMock()
        github.request.side_effect = [{"sha": "blob"}, {"sha": "isolated-tree"}]
        experiment.gh = github
        self.assertEqual(experiment._new_tree("research/test", "source", ORIGINAL,
                                             remove_workflows=removals), "isolated-tree")
        payload = github.request.call_args.args[2]
        self.assertEqual(payload["base_tree"], "source")
        self.assertEqual([entry["path"] for entry in payload["tree"]],
                         [experiment.workflow_path, *removals])
        self.assertTrue(all(entry["sha"] is None for entry in payload["tree"][1:]))

    def test_workflow_isolation_rejects_incomplete_tree(self):
        with self.assertRaisesRegex(ValueError, "cannot prove"):
            self.experiment()._ancillary_paths({"truncated": True, "tree": []})

    def test_prepare_isolates_default_and_source_before_enabling_actions(self):
        experiment = self.experiment()
        github = MagicMock()
        experiment.gh = github
        listing = {"tree": [
            {"type": "blob", "path": ".github/workflows/ci.yml"},
            {"type": "blob", "path": ".github/workflows/release-drafter.yml"}]}
        events = []

        def request(method, path, body=None):
            events.append((method, path, body))
            if path == "/repos/research/test":
                return {"default_branch": "main"}
            if "/git/commits/" in path:
                return {"tree": {"sha": "source-tree"}}
            if "/git/trees/" in path:
                return listing
            return {}

        github.request.side_effect = request
        current = {"sha": "head", "commit": {"tree": {"sha": "default-tree"}}}
        state = {"fork_repo": "research/test"}
        with (patch.object(experiment, "_selected_tree", return_value=(current, listing)),
              patch.object(experiment, "_new_tree", return_value="isolated") as new_tree,
              patch.object(experiment, "_commit", side_effect=["registration", "prepared"]),
              patch.object(experiment, "_wait_for_workflow"),
              patch("evaluation.ci_executor.validate_baseline", return_value={"verdict": "PASS"})):
            experiment.prepare(state, lambda: None)
        self.assertEqual(new_tree.call_count, 2)
        for call in new_tree.call_args_list:
            self.assertEqual(call.kwargs["remove_workflows"],
                             [".github/workflows/release-drafter.yml"])
        changes = [body for method, path, body in events if path.endswith("actions/permissions")]
        self.assertEqual(changes, [{"enabled": False}, {"enabled": True}])
        self.assertEqual(state["isolated_workflows"]["source"],
                         [".github/workflows/release-drafter.yml"])

    def test_workflow_isolation_cannot_delete_selected_workflow_or_source(self):
        experiment = self.experiment()
        experiment.gh = MagicMock()
        experiment.gh.request.return_value = {"sha": "blob"}
        for path in (experiment.workflow_path, "src/main.py"):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "removal path"):
                experiment._new_tree("research/test", "base", ORIGINAL, remove_workflows=[path])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env_patch = patch.dict(os.environ, {"CLOUDTUNE_AUTO_DELETE_FORKS": "true"})
        env_patch.start()
        self.addCleanup(env_patch.stop)
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

    def test_dispatch_harness_accepts_quoted_mapping_keys_without_reformatting(self):
        for key in ("on", "'on'", '"on"'):
            for newline in ("\n", "\r\n"):
                with self.subTest(key=key, newline=repr(newline)):
                    source = (f"name: CI\n{key}: # events\n    push:\n"
                              "jobs:\n  test:\n    runs-on: ubuntu-latest\n"
                              "    steps:\n      - run: echo ok\n").replace("\n", newline).encode()
                    expected = source.replace(b"    push:", b"    workflow_dispatch:" +
                                              newline.encode() + b"    push:")
                    self.assertEqual(ensure_dispatch(source), expected)
                    self.assertEqual(ensure_dispatch(expected), expected)

    def test_dispatch_harness_preserves_comments_and_blank_lines_after_on(self):
        for newline in ("\n", "\r\n"):
            for prefix in ("  # Trigger on push\n", "\n  # Trigger on push\n  \n"):
                with self.subTest(newline=repr(newline), prefix=prefix):
                    source = ("name: CI\non:\n" + prefix +
                              "  push:\n    branches: [master]\n"
                              "  pull_request:\njobs:\n  test:\n"
                              "    runs-on: ubuntu-latest\n"
                              "    steps:\n      - run: echo ok\n").replace("\n", newline).encode()
                    expected = source.replace(b"on:" + newline.encode(),
                                              b"on:" + newline.encode() +
                                              b"  workflow_dispatch:" + newline.encode(), 1)
                    self.assertEqual(ensure_dispatch(source), expected)
                    self.assertEqual(ensure_dispatch(expected), expected)

    def test_dispatch_harness_rejects_quoted_sequence_events(self):
        source = b"'on':\n  - push\njobs:\n  test:\n    steps:\n      - run: echo ok\n"
        with self.assertRaises(ValueError):
            ensure_dispatch(source)

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

    def test_disabled_fork_workflow_is_enabled_then_verified_active(self):
        methods = []
        class Fake:
            def __init__(self):
                self.enabled = False
            def request(self, method, path, body=None):
                methods.append((method, path))
                if method == "GET":
                    return {"id": 42, "state": "active" if self.enabled else "disabled_fork"}
                if method == "PUT" and path.endswith("/actions/workflows/42/enable"):
                    self.enabled = True
                    return None  # GitHub 204 No Content.
                raise AssertionError((method, path))
        runner = ForkExperiment(Fake(), repo_id="source/test",
             workflow_path=".github/workflows/ci.yml", source_sha="a"*40,
             original=ORIGINAL, evaluation_id="sample", max_wait_seconds=10,
             poll_seconds=1)
        state = {"fork_repo": "research/test"}
        saved = []
        with patch("evaluation.ci_executor.time.sleep", return_value=None):
            runner._wait_for_workflow(state, lambda: saved.append(dict(state)))
        self.assertEqual(state["workflow_id"], 42)
        self.assertEqual(len(saved), 1)
        self.assertEqual(sum(method == "PUT" for method, _ in methods), 1)
        self.assertEqual(methods[-1][0], "GET")

    def test_already_active_workflow_never_sends_enable(self):
        class Fake:
            def request(self, method, path, body=None):
                assert method == "GET"
                return {"id": 42, "state": "active"}
        runner = ForkExperiment(Fake(), repo_id="source/test",
             workflow_path=".github/workflows/ci.yml", source_sha="a"*40,
             original=ORIGINAL, evaluation_id="sample", max_wait_seconds=10,
             poll_seconds=1)
        state = {"fork_repo": "research/test", "workflow_id": 42}
        runner._wait_for_workflow(state, lambda: None)

    def test_changed_workflow_identity_is_rejected(self):
        class Fake:
            def request(self, method, path, body=None):
                return {"id": 99, "state": "active"}
        runner = ForkExperiment(Fake(), repo_id="source/test",
             workflow_path=".github/workflows/ci.yml", source_sha="a"*40,
             original=ORIGINAL, evaluation_id="sample", max_wait_seconds=10,
             poll_seconds=1)
        with self.assertRaisesRegex(ValueError, "workflow ID changed"):
            runner._wait_for_workflow({"fork_repo": "research/test", "workflow_id": 42}, lambda: None)

    def test_queued_run_stays_pending_and_is_not_redispatched(self):
        with self.assertRaises(RunPending):
            self.experiment(status="queued", max_wait_seconds=0).execute(
                self.state, lambda: None, arm="A", repeat=1, required=["test"], max_total=3)
        self.assertEqual(self.state["pending"]["run_id"], 901)
        self.assertEqual(self.state["records"], [])

    def _cleanup_experiment(self, github):
        return ForkExperiment(github, repo_id="source/test",
                              workflow_path=".github/workflows/ci.yml",
                              source_sha="a" * 40, original=ORIGINAL,
                              evaluation_id="sample", max_wait_seconds=0,
                              poll_seconds=1)

    def _cleanup_state(self):
        return {"fork_repo": "research/test", "fork_owner": "research",
                "fork_creation_intent": "research/test", "fork_id": 4242,
                "fork_created_by_evaluation": True,
                "measurements_finalized": True, "pending": None,
                "records": [{"arm": "A", "run_id": 901}]}

    def test_uncertain_fork_create_does_not_authorize_deletion(self):
        class ExistingFork:
            def request(self, method, path, body=None):
                if method == "GET" and path == "/user":
                    return {"login": "research"}
                if method == "GET" and path == "/repos/research/test":
                    return {"full_name": "research/test"}
                raise AssertionError((method, path, body))
        state = {"fork_creation_intent": "research/test"}
        with self.assertRaisesRegex(ValueError, "not proven to be created"):
            self._cleanup_experiment(ExistingFork()).provision(state, lambda: None)
        self.assertFalse(state.get("fork_created_by_evaluation", False))

    def test_cleanup_deletes_only_created_fork_after_jobs_finish(self):
        events = []
        class Fake:
            def __init__(self):
                self.deleted = False

            def request(self, method, path, body=None):
                events.append((method, path))
                if method == "GET":
                    if self.deleted:
                        raise GitHubError(404, path)
                    return {"id": 4242, "owner": {"login": "research"}, "fork": True,
                            "permissions": {"push": True},
                            "source": {"full_name": "source/test"}}
                if method == "DELETE":
                    self.deleted = True
                    return None
                raise AssertionError((method, path))
            def all(self, path, key):
                self_check = key == "workflow_runs"
                if not self_check: raise AssertionError((path, key))
                return [{"id": 901, "status": "completed"}]
        state = self._cleanup_state()
        saved = []
        result = self._cleanup_experiment(Fake()).cleanup_fork(
            state, lambda: saved.append(dict(state)))
        self.assertEqual(result, "DELETED")
        self.assertEqual(events[-2:], [("DELETE", "/repos/research/test"),
                                       ("GET", "/repos/research/test")])
        self.assertEqual(saved[-2]["cleanup_status"], "DELETE_REQUESTED")
        self.assertEqual(saved[-1]["cleanup_status"], "DELETED")
        self.assertEqual(len([e for e in events if e[0] == "DELETE"]), 1)
        self._cleanup_experiment(Fake()).cleanup_fork(state, lambda: None)
        self.assertEqual(len([e for e in events if e[0] == "DELETE"]), 1)

    def test_auto_delete_env_defaults_true_and_rejects_invalid_values(self):
        # Opt-out is deliberate; malformed values cannot silently change safety.
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(automatic_fork_deletion_enabled())
        for value in ("false", "0", "no", "off", " FALSE "):
            with self.subTest(value=value), patch.dict(
                os.environ, {"CLOUDTUNE_AUTO_DELETE_FORKS": value}
            ):
                self.assertFalse(automatic_fork_deletion_enabled())
        with patch.dict(os.environ, {"CLOUDTUNE_AUTO_DELETE_FORKS": "true"}):
            self.assertTrue(automatic_fork_deletion_enabled())
        with patch.dict(os.environ, {"CLOUDTUNE_AUTO_DELETE_FORKS": "sometimes"}):
            with self.assertRaisesRegex(ValueError, "CLOUDTUNE_AUTO_DELETE_FORKS"):
                automatic_fork_deletion_enabled()

    def test_retained_fork_requires_no_github_calls_and_survives_resume(self):
        class Forbidden:
            def request(self, *args):
                raise AssertionError("Retained fork must not be queried or deleted")
            def all(self, *args):
                raise AssertionError("Retained fork must not list Actions runs")

        runner = self._cleanup_experiment(Forbidden())
        state = self._cleanup_state()
        checkpoints = []
        with patch.dict(os.environ, {"CLOUDTUNE_AUTO_DELETE_FORKS": "false"}):
            result = runner.cleanup_fork(state, lambda: checkpoints.append(dict(state)))
        self.assertEqual(result, "RETAINED_BY_CONFIGURATION")
        self.assertEqual(state["cleanup_status"], "RETAINED_BY_CONFIGURATION")
        self.assertEqual(state["fork_repo"], "research/test")
        self.assertNotIn("cleanup_intent", state)
        self.assertEqual(len(checkpoints), 1)

        # Later re-enabling must not delete a deliberately preserved fork.
        with patch.dict(os.environ, {"CLOUDTUNE_AUTO_DELETE_FORKS": "true"}):
            result = runner.cleanup_fork(state, lambda: checkpoints.append(dict(state)))
        self.assertEqual(result, "RETAINED_BY_CONFIGURATION")
        self.assertEqual(len(checkpoints), 1)

    def test_retention_cannot_reverse_an_already_requested_delete(self):
        class Fake:
            def request(self, method, path, body=None):
                if method != "GET":
                    raise AssertionError("Never repeat a DELETE")
                return {"id": 4242, "owner": {"login": "research"}, "fork": True,
                        "permissions": {"push": True},
                        "source": {"full_name": "source/test"}}

        state = self._cleanup_state()
        state["cleanup_intent"] = "research/test"
        with patch.dict(os.environ, {"CLOUDTUNE_AUTO_DELETE_FORKS": "false"}):
            result = self._cleanup_experiment(Fake()).cleanup_fork(state, lambda: None)
        self.assertEqual(result, "DELETE_OUTCOME_UNKNOWN")
        self.assertNotEqual(state["cleanup_status"], "RETAINED_BY_CONFIGURATION")

    def test_cleanup_does_not_claim_deletion_while_fork_still_exists(self):
        methods = []

        class Fake:
            def request(self, method, path, body=None):
                methods.append(method)
                if method == "DELETE":
                    return None
                return {"id": 4242, "owner": {"login": "research"}, "fork": True,
                        "permissions": {"push": True},
                        "source": {"full_name": "source/test"}}

            def all(self, path, key):
                return [{"id": 901, "status": "completed"}]

        state = self._cleanup_state()
        runner = self._cleanup_experiment(Fake())
        with patch("evaluation.ci_executor.time.sleep", return_value=None):
            self.assertEqual(runner.cleanup_fork(state, lambda: None),
                             "DELETE_OUTCOME_UNKNOWN")
        self.assertEqual(state["cleanup_intent"], "research/test")
        # A second check cannot send another destructive request.
        self.assertEqual(runner.cleanup_fork(state, lambda: None),
                         "DELETE_OUTCOME_UNKNOWN")
        self.assertEqual(methods.count("DELETE"), 1)

    def test_cleanup_never_deletes_preexisting_fork(self):
        class Forbidden:
            def request(self, *args): raise AssertionError("Should never call GitHub")
            def all(self, *args): raise AssertionError("Should never list jobs")
        state = self._cleanup_state()
        state["fork_created_by_evaluation"] = False
        result = self._cleanup_experiment(Forbidden()).cleanup_fork(state, lambda: None)
        self.assertEqual(result, "PRESERVED_NOT_OWNED")

    def test_cleanup_refuses_pending_target_run(self):
        class Forbidden:
            def request(self, *args): raise AssertionError("Should never call GitHub")
        state = self._cleanup_state()
        state["pending"] = {"arm": "A", "repeat": 1, "run_id": 901}
        with self.assertRaises(RunPending):
            self._cleanup_experiment(Forbidden()).cleanup_fork(state, lambda: None)

    def test_cleanup_refuses_other_queued_fork_runs(self):
        class Fake:
            def request(self, method, path, body=None):
                assert method == "GET"
                return {"id": 4242, "owner": {"login": "research"}, "fork": True,
                        "permissions": {"push": True},
                        "source": {"full_name": "source/test"}}
            def all(self, path, key):
                return [{"id": 901, "status": "completed"},
                        {"id": 902, "status": "queued"}]
        state = self._cleanup_state()
        result = self._cleanup_experiment(Fake()).cleanup_fork(state, lambda: None)
        self.assertEqual(result, "WAITING_FOR_OTHER_RUNS")
        self.assertEqual(state["cleanup_active_run_ids"], [902])
        self.assertNotIn("cleanup_intent", state)

    def test_cleanup_lost_delete_response_does_not_resend(self):
        methods = []
        class Fake:
            def request(self, method, path, body=None):
                methods.append(method)
                if method == "DELETE":
                    raise RuntimeError("GitHub DELETE response uncertain")
                return {"id": 4242, "owner": {"login": "research"}, "fork": True,
                        "permissions": {"push": True},
                        "source": {"full_name": "source/test"}}
            def all(self, path, key): return []
        state = self._cleanup_state()
        runner = self._cleanup_experiment(Fake())
        self.assertEqual(runner.cleanup_fork(state, lambda: None), "DELETE_OUTCOME_UNKNOWN")
        self.assertEqual(runner.cleanup_fork(state, lambda: None), "DELETE_OUTCOME_UNKNOWN")
        self.assertEqual(methods.count("DELETE"), 1)
        class Missing:
            def request(self, *args): raise GitHubError(404, "missing")
        self.assertEqual(self._cleanup_experiment(Missing()).cleanup_fork(state, lambda: None), "DELETED")

    def test_ci_cost_setup_does_not_inherit_research_secrets(self):
        with patch.dict(os.environ, {
            "OPENROUTER_API_KEY": "fixture-model-secret",
            "GITHUB_TOKEN": "fixture-github-secret",
            "SUPABASE_SECRET_KEY": "fixture-db-secret",
            "PATH": "fixture-path",
        }):
            env = _safe_tool_environment()
        self.assertNotIn("OPENROUTER_API_KEY", env)
        self.assertNotIn("GITHUB_TOKEN", env)
        self.assertNotIn("SUPABASE_SECRET_KEY", env)
        self.assertEqual(env["PATH"], "fixture-path")

    def test_cleanup_denied_permission_does_not_discard_evidence(self):
        class Fake:
            def request(self, method, path, body=None):
                if method == "DELETE": raise GitHubError(403, path)
                return {"id": 4242, "owner": {"login": "research"}, "fork": True,
                        "permissions": {"push": True},
                        "source": {"full_name": "source/test"}}
            def all(self, path, key): return []
        state = self._cleanup_state()
        self.assertEqual(self._cleanup_experiment(Fake()).cleanup_fork(state, lambda: None), "BLOCKED_PERMISSION")
        self.assertEqual(len(state["records"]), 1)

    def test_no_savings_claimed_without_both_arms(self):
        data = [{"arm":"A", "comparable":True, "workflow_elapsed_seconds":100,
                 "sum_job_runtime_seconds":110}]
        stats = summarize_records(data)
        self.assertIsNone(stats["B"]["elapsed_saving_percent_vs_A"])
        self.assertIsNone(stats["C"]["elapsed_saving_percent_vs_A"])

    def test_invalid_yaml_is_classified_not_raised(self):
        result = validate_candidate(ORIGINAL, b"name: test\njobs:\n  x: [bad\n")
        self.assertEqual(result["verdict"], "FAIL")

    def test_cache_path_change_is_not_rejected_by_optimization_allowlist(self):
        bad = ORIGINAL.replace(b"      - run: echo ok", b"      - name: Cache SSH\n        uses: actions/cache@v4\n        with:\n          path: ~/.ssh\n          key: test\n      - run: echo ok")
        with patch("evaluation.candidate_validator._actionlint", return_value={"status": "PASS", "reason":""}):
            verdict = validate_candidate(ORIGINAL, bad)
        self.assertEqual(verdict["verdict"], "PASS")

    def test_cache_key_is_not_checked_by_optimization_allowlist(self):
        bad = ORIGINAL.replace(b"      - run: echo ok", b"      - name: Cache dependencies\n        uses: actions/cache@v4\n        with:\n          path: ~/.npm\n          key: constant\n      - run: echo ok")
        with patch("evaluation.candidate_validator._actionlint", return_value={"status": "PASS", "reason": ""}):
            outcome = validate_candidate(ORIGINAL, bad)
        self.assertEqual(outcome["verdict"], "PASS")

    def test_allowlist_accepts_source_bound_dependency_cache(self):
        good = ORIGINAL.replace(b"      - run: echo ok", b"      - name: Cache dependencies\n        uses: actions/cache@v4\n        with:\n          path: ~/.npm\n          key: ${{ runner.os }}-${{ hashFiles('package-lock.json') }}\n      - run: echo ok")
        with patch("evaluation.candidate_validator._actionlint", return_value={"status": "PASS", "reason": ""}):
            outcome = validate_candidate(ORIGINAL, good)
        self.assertEqual(outcome["verdict"], "PASS")

    def test_general_cache_key_is_not_checked_by_optimization_allowlist(self):
        bad = ORIGINAL.replace(b"      - run: echo ok", b"      - name: Cache deps\n        uses: actions/cache@v4\n        with:\n          path: ~/.npm\n          key: ${{ runner.os }}-${{ hashFiles('README.md') }}\n      - run: echo ok")
        with patch("evaluation.candidate_validator._actionlint", return_value={"status": "PASS", "reason": ""}):
            self.assertEqual(validate_candidate(ORIGINAL, bad)["verdict"], "PASS")

    def test_ineligible_first_row_does_not_require_a_snapshot(self):

        root = self.root
        out = root / "evaluation/results/skipped"
        out.mkdir(parents=True)
        with (out / "screening.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=["repo_id", "status", "manifest_path"])
            writer.writeheader()
            writer.writerow({"repo_id": "source/repo", "status": "ineligible", "manifest_path": ""})
        config = {"evaluation_id": "skipped", "repetitions": 3, "ci_cost": {"version": "1.0.0"},
                  "rag": {"embedding_revision": "AUTO_PIN_SINGLE", "dataset_sha256": "a"*64}}
        with patch.object(pipeline, "ROOT", root), \
             patch.object(pipeline, "_ensure_preparation", return_value=out), \
             patch.object(pipeline, "GitHub", return_value=MagicMock()), \
             patch.object(pipeline, "implementation_digest", return_value="f" * 64), \
             patch.dict("os.environ", {"GITHUB_TOKEN": "fake"}):
            report = pipeline.run_fork_evaluation(config)
        self.assertEqual(report["repositories"]["source/repo"]["status"], "SKIPPED")
        self.assertTrue((out / "state.json").is_file())

    def test_local_state_survives_restart_without_replaying_a_dispatch(self):
        output = self.root / "evaluation/results/study"
        snapshot = output / "repositories" / "demo-repo"
        (snapshot / "source").mkdir(parents=True)
        (snapshot / "source/original.yml").write_bytes(ORIGINAL)
        (snapshot / "manifest.json").write_text(json.dumps({
            "repo_id": "demo/repo", "workflow_sha256": hashlib.sha256(ORIGINAL).hexdigest()}))
        dataset = self.root / "dataset.csv"
        dataset.write_text("repo_id,split\ndemo/repo,evaluation\n")
        record = {"evaluation_id": "study", "dataset": "dataset.csv",
                  "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
                  "repositories": {"demo/repo": {"status": "WAITING_FOR_GITHUB_RUN",
                                                 "pending": {"arm": "A", "repeat": 1,
                                                             "run_id": 901}}},
                  "screening": [{"repo_id": "demo/repo", "status": "prepared"}]}
        with patch.object(pipeline, "ROOT", self.root):
            first = StateStore("study", output_root=self.root)
            first.save(record, snapshots={"demo/repo": snapshot})
            recovered = StateStore("study", output_root=self.root).load()
            self.assertEqual(recovered["repositories"]["demo/repo"]["pending"]["run_id"], 901)
            restored = StateStore("study", output_root=self.root).restore(output, recovered)
        self.assertEqual(Path(restored[0]["manifest_path"]), snapshot / "manifest.json")
        self.assertEqual((snapshot / "source/original.yml").read_bytes(), ORIGINAL)

    def test_local_checkpoint_fails_closed_on_mutated_snapshot(self):
        output = self.root / "evaluation/results/study"
        snapshot = output / "repositories/repo"
        (snapshot / "source").mkdir(parents=True)
        (snapshot / "source/original.yml").write_bytes(ORIGINAL)
        (snapshot / "manifest.json").write_text(json.dumps({
            "repo_id": "demo/repo", "workflow_sha256": "f" * 64}))
        with self.assertRaisesRegex(ValueError, "Pinned repository snapshot changed"):
            StateStore("study", output_root=self.root).save(
                {"repositories": {"demo/repo": {}}}, snapshots={"demo/repo": snapshot})

    def test_local_controller_lock_blocks_parallel_evaluations(self):
        with patch.object(pipeline, "ROOT", self.root):
            with exclusive_controller("study"):
                with self.assertRaisesRegex(RuntimeError, "Controller already active"):
                    with exclusive_controller("study"):
                        pass
            with exclusive_controller("study"):
                pass

    def test_no_cloudtune_actions_workflow_or_remote_state_branch(self):
        root = Path(__file__).resolve().parents[1]
        self.assertFalse((root / ".github/workflows/cloudtune-evaluation.yml").exists())
        source = (root / "evaluation/fork_pipeline.py").read_text()
        self.assertNotIn("/git/refs/heads/cloudtune-evaluation-state", source)
        self.assertNotIn("cloudtune-evaluation-state", source)

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
                        "B": {"complete": True},
                        "C": {"complete": True, "elapsed_saving_percent_vs_B": 15.0}}},
                   "repo2": {"status": "INCOMPLETE", "run_statistics": {
                        "B": {"complete": True},
                        "C": {"complete": False, "elapsed_saving_percent_vs_B": 99.0}}},
                   "repo3": {"status": "SKIPPED", "run_statistics": {}}}
        summary = summarize_cohort(dataset, bootstrap_samples=100)
        self.assertEqual(summary["total_selected"], 3)
        self.assertEqual(summary["incomplete_repositories"], 1)
        comparison = summary["comparisons"]["C_vs_B_elapsed"]
        self.assertEqual(comparison["paired_repositories"], 1)
        self.assertEqual(comparison["median_saving_percent"], 15.0)
        self.assertIsNone(comparison["bootstrap_95pct_ci_percent"])

    def test_aggregate_retains_valid_b_vs_a_when_c_abstains(self):
        records = [
            {"arm": "A", "comparable": True, "workflow_elapsed_seconds": 100,
             "sum_job_runtime_seconds": 110},
            {"arm": "B", "comparable": True, "workflow_elapsed_seconds": 90,
             "sum_job_runtime_seconds": 99},
        ]
        stats = summarize_records(records, repetitions=1)
        summary = summarize_cohort({
            "repo1": {"status": "INCOMPLETE", "run_statistics": stats}
        }, bootstrap_samples=100)
        self.assertEqual(summary["comparisons"]["B_vs_A_elapsed"]["paired_repositories"], 1)
        self.assertAlmostEqual(summary["comparisons"]["B_vs_A_elapsed"]["median_saving_percent"], 10)
        self.assertEqual(summary["comparisons"]["C_vs_A_elapsed"]["paired_repositories"], 0)
        self.assertEqual(summary["comparisons"]["C_vs_B_elapsed"]["paired_repositories"], 0)

    def test_fork_config_validates_without_tokens_or_git_api(self):
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
