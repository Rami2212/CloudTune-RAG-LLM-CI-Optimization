"""Offline protocol checks: no GitHub/OpenRouter calls or real CI runs."""
import copy
import sys
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import scenario_experiments as scenarios
import run_pattern_batch as batch_module


def successful(names=("probe",)):
    return {"conclusion": "success", "jobs": [{"name": name, "conclusion": "success"} for name in names]}


class ProtocolTests(unittest.TestCase):
    def test_every_pattern_has_exactly_scoped_candidate(self):
        for pattern in scenarios.SUPPORTED:
            with self.subTest(pattern=pattern):
                before = ({"dispensable_commit_suffix": "", "required_commit_suffix": ""}
                          if pattern == "P-LIT-SKIP-WORKFLOW" else scenarios.fixture(pattern, scenarios.settings_from_env()))
                if pattern in scenarios.replay.PATTERNS:
                    before = scenarios.replay.policy(pattern)
                after = scenarios.candidate_document(pattern, before)
                scenarios.check_candidate(pattern, before, scenarios.dump(after))
                altered = copy.deepcopy(after)
                altered["permissions"] = {"contents": "write"}
                with self.assertRaisesRegex(ValueError, "SCOPE_EXCEEDED"):
                    scenarios.check_candidate(pattern, before, scenarios.dump(altered))

    def test_matrix_expected_failure_is_successful_scenario(self):
        for arm in ("baseline", "optimized"):
            failure = {"conclusion": "failure", "jobs": [
                {"name": "cell-fail", "conclusion": "failure"},
                {"name": "cell-worker-a", "conclusion": "cancelled" if arm == "optimized" else "success"},
                {"name": "cell-worker-b", "conclusion": "cancelled" if arm == "optimized" else "success"}]}
            events = {"failure": failure, "healthy": successful(("cell-fail", "cell-worker-a", "cell-worker-b"))}
            self.assertTrue(all(scenarios.evaluate("P-LIT-FAIL-FAST", arm, events).values()))
            events["healthy"]["jobs"].pop()
            self.assertFalse(all(scenarios.evaluate("P-LIT-FAIL-FAST", arm, events).values()))

    def test_cancellation_requires_overlap_and_other_branch_success(self):
        events = {"old": {"conclusion": "cancelled"}, "new": successful(), "isolated": successful()}
        self.assertTrue(all(scenarios.evaluate("P-LIT-CANCEL-STALE", "optimized", events, True).values()))
        self.assertFalse(all(scenarios.evaluate("P-LIT-CANCEL-STALE", "optimized", events, False).values()))
        events["isolated"]["conclusion"] = "cancelled"
        self.assertFalse(all(scenarios.evaluate("P-LIT-CANCEL-STALE", "optimized", events, True).values()))

    def test_path_filter_requires_all_positive_controls(self):
        events = {name: successful() for name in ("source", "source_after", "config", "mixed")}
        events["docs"] = {"no_run_observed": True}
        self.assertTrue(all(scenarios.evaluate("P-LIT-CHANGE-FILTER", "optimized", events).values()))
        events["config"]["conclusion"] = "failure"
        self.assertFalse(all(scenarios.evaluate("P-LIT-CHANGE-FILTER", "optimized", events).values()))

    def test_skip_requires_both_required_controls_and_observed_absence(self):
        events = {name: successful() for name in ("source", "source_after", "docs")}
        self.assertTrue(all(scenarios.evaluate("P-LIT-SKIP-WORKFLOW", "baseline", events).values()))
        self.assertFalse(all(scenarios.evaluate("P-LIT-SKIP-WORKFLOW", "optimized", events).values()))
        events["docs"] = {"no_run_observed": True}
        self.assertTrue(all(scenarios.evaluate("P-LIT-SKIP-WORKFLOW", "optimized", events).values()))
        events["source_after"]["conclusion"] = "cancelled"
        self.assertFalse(all(scenarios.evaluate("P-LIT-SKIP-WORKFLOW", "optimized", events).values()))


class RefAPI:
    def __init__(self, apply_before_disconnect=True):
        self.current = None
        self.mutations = 0
        self.apply_before_disconnect = apply_before_disconnect

    def request(self, method, path, body=None):
        if method == "GET" and "/git/ref/" in path:
            if self.current is None:
                raise RuntimeError("GitHub GET: HTTP 404")
            return {"object": {"sha": self.current}}
        if method == "POST" and path.endswith("/git/trees"):
            return {"sha": "tree-sha"}
        if method == "POST" and path.endswith("/git/commits"):
            return {"sha": "commit-sha"}
        if method == "POST" and path.endswith("/git/refs"):
            self.mutations += 1
            if self.apply_before_disconnect:
                self.current = body["sha"]
            raise RuntimeError("Connection lost after request")
        raise AssertionError((method, path))


class DurabilityTests(unittest.TestCase):
    def setUp(self):
        self.test_root = Path(__file__).resolve().parent
        self.temp = tempfile.TemporaryDirectory(dir=self.test_root, prefix=".scenario-check-")
        self.root_patch = patch.object(scenarios.runner, "ROOT", Path(self.temp.name))
        self.root_patch.start()
        self.config = {"experiment_id": "scenario-check", "fork_repo": "owner/dedicated", "source_repo": "source/repo",
                       "pattern_id": "P-LIT-CHANGE-FILTER", "model": "test/model:free", "max_tokens": 24000,
                       "settings": scenarios.settings_from_env()}

    def tearDown(self):
        self.root_patch.stop()
        assert Path(self.temp.name).resolve().is_relative_to(self.test_root)
        self.temp.cleanup()

    def test_lost_push_response_recovers_without_second_push(self):
        api = RefAPI()
        exp = scenarios.ScenarioExperiment(self.config, api)
        with self.assertRaises(RuntimeError):
            exp.operation("root", "ct-scenario/test", {scenarios.WORKFLOW: "fixture"}, "init [skip ci]", root=True)
        resumed = scenarios.ScenarioExperiment(self.config, api)
        self.assertTrue(resumed.operation("root", "ct-scenario/test", {}, "ignored", root=True)["applied"])
        self.assertEqual(api.mutations, 1)
        self.assertEqual(resumed.state["event_count"], 1)

    def test_uncertain_unapplied_push_is_not_resent(self):
        api = RefAPI(apply_before_disconnect=False)
        exp = scenarios.ScenarioExperiment(self.config, api)
        with self.assertRaises(RuntimeError):
            exp.operation("root", "ct-scenario/test", {}, "init [skip ci]", root=True)
        with self.assertRaisesRegex(RuntimeError, "uncertain"):
            exp.operation("root", "ct-scenario/test", {}, "ignored", root=True)
        self.assertEqual(api.mutations, 1)
        self.assertIsNotNone(exp.state["pending"])

    def test_boundary_run_does_not_pass_as_absence(self):
        exp = scenarios.ScenarioExperiment(self.config, None)
        exp.state["operations"]["docs"] = {"sha": "sha", "branch": "branch"}
        with patch.object(scenarios.time, "monotonic", side_effect=[0, 121]), \
             patch.object(exp, "matches", return_value=[{"id": 99}]), \
             patch.object(exp, "collect", return_value={"conclusion": "success"}) as collect:
            result = exp.observe_absence("docs")
        collect.assert_called_once_with("docs")
        self.assertNotIn("no_run_observed", result)

    def test_absence_api_failure_retains_pending_instead_of_passing(self):
        exp = scenarios.ScenarioExperiment(self.config, None)
        exp.state["operations"]["docs"] = {"sha": "sha", "branch": "branch"}
        with patch.object(exp, "matches", side_effect=RuntimeError("API unavailable")):
            with self.assertRaises(RuntimeError):
                exp.observe_absence("docs")
        self.assertIsNotNone(exp.state["pending"])
        self.assertNotIn("result", exp.state["operations"]["docs"])

    def test_failed_scenario_stops_after_one_repeat(self):
        exp = scenarios.ScenarioExperiment(self.config, None)
        record = {"arm": "baseline", "repeat_index": 1, "scenario_pass": False,
                  "assertions": {"required_control": False}}
        with patch.object(exp, "sample", return_value=record) as sample:
            with self.assertRaisesRegex(ValueError, "Unexpected scenario behavior"):
                exp.measure("baseline")
        self.assertEqual(sample.call_count, 1)
        self.assertEqual(len(exp.state["records"]), 1)

    def test_unfinished_other_events_prevent_fork_cleanup(self):
        exp = scenarios.ScenarioExperiment(self.config, None)
        exp.state["operations"]["old"] = {"root": False, "requested": True, "applied": True}
        with patch.object(exp, "sample", side_effect=RuntimeError("second push rejected")):
            with self.assertRaises(RuntimeError):
                exp.measure("baseline")
        self.assertEqual(exp.state["pending"]["operations"], ["old"])

    def test_reports_cannot_claim_real_repo_optimization(self):
        exp = scenarios.ScenarioExperiment(self.config, None)
        exp.state["records"] = [{"arm": arm, "repeat_index": repeat, "scenario_pass": True,
                                  "sum_job_runtime_seconds": 12} for arm in ("baseline", "optimized") for repeat in (1, 2, 3)]
        case = exp.report()
        self.assertEqual(case["outcome"], "scenario_passed")
        self.assertFalse(case["real_repo_optimization_verified"])
        self.assertFalse(case["required_status_validated"])
        self.assertTrue((exp.directory / "artifact_manifest.json").exists())

    def test_normal_batch_manifest_is_shared_across_models_and_migrates_old_manifest(self):
        rows = [{"repo_id": "source/repo", "pattern_id": "P-LIT-GHA-CACHE"}]
        first = batch_module.Batch("same-batch", rows, "owner", "token", "provider/model-a:free")
        second = batch_module.Batch("same-batch", rows, "owner", "token", "provider/model-b:free")
        manifest = first.directory / "selection.json"
        self.assertEqual(first.directory, second.directory)
        self.assertEqual(scenarios.runner.read_json(manifest)["model"], "provider/model-b:free")
        legacy = {**scenarios.runner.read_json(manifest), "model": "provider/old-model:free"}
        scenarios.runner.write_json(manifest, legacy)
        migrated = batch_module.Batch("same-batch", rows, "owner", "token", "provider/model-c:free")
        self.assertEqual(migrated.directory, first.directory)
        self.assertEqual(scenarios.runner.read_json(manifest)["model"], "provider/model-c:free")

    def test_scenario_config_model_is_not_scenario_identity(self):
        config = {**self.config, "pattern_id": "P-LIT-CHANGE-FILTER"}
        exp = scenarios.ScenarioExperiment(config, None)
        scenarios.ScenarioExperiment({**config, "model": "provider/model-b:free"}, None)
        self.assertEqual(scenarios.runner.read_json(exp.directory / "config.json")["model"], config["model"])

    def test_returned_existing_fork_is_never_modified_or_deleted(self):
        batch = scenarios.ScenarioBatch.__new__(scenarios.ScenarioBatch)
        batch.username = "owner"
        batch.state = {"created_forks": {"source/repo": "owner/existing"},
                       "forks": {"source/repo": "owner/existing"},
                       "fork_requests": {"source/repo": {"status": "accepted"}}}
        batch.save = lambda: None
        batch.ensure_fork = lambda row, target: "owner/existing"
        with patch.object(batch, "enable_actions") as enable:
            experiment, status = batch.ready_experiment({"repo_id": "source/repo", "pattern_id": "P-LIT-FAIL-FAST"})
        self.assertIsNone(experiment)
        self.assertEqual(status, "failed")
        self.assertNotIn("source/repo", batch.state["created_forks"])
        enable.assert_not_called()

    def test_recreated_fork_gets_a_new_cleanup_attempt(self):
        batch = scenarios.ScenarioBatch.__new__(scenarios.ScenarioBatch)
        batch.username = "owner"
        batch.state = {"forks": {}, "fork_requests": {"source/repo": {"status": "deleted"}},
                       "fork_deletions": {"source/repo": {"status": "deleted", "target": "owner/fork"}}}
        batch.save = lambda: None
        from unittest.mock import Mock
        batch.github = Mock()
        batch.github.request.side_effect = [{"login": "owner"}, {"full_name": "owner/fork"}, {}]
        with patch.object(batch_module, "validate_fork", side_effect=[
                RuntimeError("GET /repos/owner/fork: HTTP 404"), {"default_branch": "main"}]):
            batch.ensure_fork({"repo_id": "source/repo"}, "owner/fork")
        self.assertNotIn("source/repo", batch.state["fork_deletions"])

    def test_batch_stops_pattern_and_retains_original_row_positions(self):
        from unittest.mock import Mock
        batch = scenarios.ScenarioBatch.__new__(scenarios.ScenarioBatch)
        batch.batch_id = "memory-check"
        batch.directory = Path(self.temp.name)
        batch.state = {"items": {}, "forks": {}}
        batch.rows = [{"repo_id": f"source/repo{i}", "pattern_id": pattern} for i, pattern in enumerate(
            ["P-LIT-GHA-CACHE", "P-LIT-FAIL-FAST", "P-LIT-FAIL-FAST", "P-LIT-FAIL-FAST", "P-LIT-CANCEL-STALE"], 1)]
        batch.save = lambda: None
        exp = Mock()
        exp.directory = Path(self.temp.name)
        exp.state = {"proposal": {"llm": {"decision": "APPLY"}}}
        exp.report.return_value = {"outcome": "scenario_passed", "pattern_satisfied": True}
        attempted = []
        def prepare(row):
            attempted.append(row["repo_id"])
            return exp, "owner/fork"
        batch.ready_experiment = prepare
        batch.cleanup_fork = lambda row, target: True
        with patch.object(scenarios.runner, "exclusive", side_effect=lambda path: nullcontext()):
            batch.run()
            batch.run()
        self.assertEqual(attempted, ["source/repo2", "source/repo3", "source/repo5"])
        skipped = batch.state["items"]["P-LIT-FAIL-FAST|source/repo4"]
        self.assertEqual(skipped["status"], "pattern_satisfied")
        self.assertEqual(skipped["row_position"], 4)

    def test_all_scenario_drivers_build_passing_control_sets(self):
        for pattern in scenarios.SUPPORTED:
            for arm in ("baseline", "optimized"):
                with self.subTest(pattern=pattern, arm=arm):
                    config = {**self.config, "pattern_id": pattern, "experiment_id": pattern + "-" + arm}
                    exp = scenarios.ScenarioExperiment(config, None)
                    if pattern in scenarios.replay.PATTERNS:
                        scenarios.runner.write_json(exp.directory / "source/replay_inputs.json",
                            {str(i): scenarios.replay.dataset(pattern, i) for i in (1, 2, 3)})
                        (exp.directory / "source/replay_engine.py").write_text("mock frozen engine", encoding="utf-8")
                        for optimized in (False, True):
                            (exp.directory / ("after_policy.yml" if optimized else "before_policy.yml")).write_bytes(
                                scenarios.dump(scenarios.replay.policy(pattern, optimized)))
                    if pattern == "P-LIT-SKIP-WORKFLOW":
                        (exp.directory / "after_policy.yml").write_bytes(scenarios.dump({"dispensable_commit_suffix": "[skip ci]"}))
                    def push(a, repeat, label, branch, paths, message="probe", absent=False):
                        key = f"{a}/{repeat}/{label}"
                        exp.state["operations"][key] = {}
                        return key
                    def collect(key):
                        label = key.rsplit("/", 1)[1]
                        if label == "failure":
                            return {"conclusion": "failure", "jobs": [
                                {"name": "cell-fail", "conclusion": "failure"},
                                *[{"name": "cell-" + cell, "conclusion": "cancelled" if arm == "optimized" else "success"}
                                  for cell in ("worker-a", "worker-b")]]}
                        event = successful(("cell-fail", "cell-worker-a", "cell-worker-b")) if label == "healthy" else successful()
                        if label == "old" and arm == "optimized":
                            event["conclusion"] = "cancelled"
                        event.update(created_at="2026-01-01T00:00:30Z", workload_intervals=[{
                            "started_at": "2026-01-01T00:00:00Z", "completed_at": "2026-01-01T00:01:30Z"}])
                        event["sum_job_runtime_seconds"] = 90
                        return event
                    with patch.object(exp, "start_branch", return_value="ct-scenario/branch"), \
                         patch.object(exp, "push", side_effect=push), patch.object(exp, "collect", side_effect=collect), \
                         patch.object(exp, "observe_absence", return_value={"no_run_observed": True, "sum_job_runtime_seconds": 0}), \
                         patch.object(exp, "wait_started"), patch.object(exp, "running", return_value=True), \
                         patch.object(exp, "matches", return_value=[]):
                        result = exp.sample(arm, 1)
                    self.assertTrue(result["scenario_pass"], result["assertions"])

    def test_replay_baseline_llm_policy_optimized_report_and_resume(self):
        for pattern in sorted(scenarios.replay.PATTERNS):
            with self.subTest(pattern=pattern):
                config = {**self.config, "pattern_id": pattern, "experiment_id": "integration-" + pattern}
                exp = scenarios.ScenarioExperiment(config, None)
                baseline = scenarios.fixture(pattern, exp.settings)
                (exp.directory / "before.yml").write_bytes(scenarios.dump(baseline))
                (exp.directory / "before_policy.yml").write_bytes(scenarios.dump(scenarios.replay.policy(pattern)))
                scenarios.runner.write_json(exp.directory / "source/pattern.json", {"pattern_id": pattern})
                scenarios.runner.write_json(exp.directory / "source/replay_inputs.json",
                    {str(i): scenarios.replay.dataset(pattern, i) for i in (1, 2, 3)})
                (exp.directory / "source/replay_engine.py").write_text(
                    Path(scenarios.replay.__file__).read_text(encoding="utf-8"), encoding="utf-8")
                published = {}
                def operation(key, branch, files, message, *, root=False, absent=False):
                    if root:
                        published[branch] = scenarios.runner.yaml.load(files[scenarios.WORKFLOW], Loader=scenarios.runner.ActionsLoader)
                    op = {"sha": key, "branch": branch, "requested": True, "applied": True,
                          "root": root, "expect_absent": absent}
                    exp.state["operations"][key] = op
                    return op
                def collect(key):
                    arm, repeat, _ = key.split("/")
                    workflow = published[exp.state["operations"][key]["branch"]]
                    actual_env = workflow["jobs"]["probe"]["steps"][0]["env"]
                    self.assertEqual(scenarios.json.loads(actual_env["CT_POLICY"]), scenarios.replay.policy(pattern, arm == "optimized"))
                    self.assertEqual(scenarios.json.loads(actual_env["CT_DATA"]), scenarios.replay.dataset(pattern, int(repeat)))
                    return {**successful(), "run_id": int(repeat), "sum_job_runtime_seconds": 4}
                def generate(directory, request, before, model, max_tokens):
                    self.assertEqual(request["pattern"]["pattern_id"], pattern)
                    self.assertEqual(len(request["baseline_records"]), 3)
                    return scenarios.dump(request["scenario_contract"]["allowed_result"]), {"decision": "APPLY"}
                with patch.object(exp, "operation", side_effect=operation), \
                     patch.object(exp, "collect", side_effect=collect) as collected, \
                     patch.object(scenarios, "generate", side_effect=generate) as generated:
                    exp.measure("baseline")
                    exp.optimize()
                    exp.measure("optimized")
                    exp.measure("optimized")  # resume must reuse all three saved repeats
                self.assertEqual(collected.call_count, 6)
                generated.assert_called_once()
                case = exp.report()
                self.assertEqual(case["outcome"], "scenario_passed")
                self.assertEqual(case["evidence_scope"], "synthetic_service_policy_replay")
                self.assertFalse(case["direct_speedup_claimed"])
                self.assertEqual(len(list((exp.directory / "replays").glob("*.json"))), 6)
                self.assertTrue((exp.directory / "workflow_change.diff").exists())
                self.assertIn("median_simulated_work_seconds", case["arms"]["optimized"])
                if pattern == "P-LIT-BUILD-SELECT":
                    self.assertFalse(case["safe_for_repository_use"])
                    self.assertEqual(case["arms"]["optimized"]["median_missed_failures"], 1)
                if pattern == "P-LIT-DURATION-PREDICTION":
                    self.assertIsNotNone(case["arms"]["optimized"]["median_held_out_mae_seconds"])

    def test_failed_hosted_replay_stops_and_cannot_be_recorded_as_passing(self):
        pattern = "P-LIT-FAIL-SCHEDULE"
        config = {**self.config, "pattern_id": pattern, "experiment_id": "failed-hosted"}
        exp = scenarios.ScenarioExperiment(config, None)
        scenarios.runner.write_json(exp.directory / "source/replay_inputs.json", {"1": scenarios.replay.dataset(pattern, 1)})
        (exp.directory / "source/replay_engine.py").write_text("engine", encoding="utf-8")
        (exp.directory / "before_policy.yml").write_bytes(scenarios.dump(scenarios.replay.policy(pattern)))
        with patch.object(exp, "start_branch", return_value="branch"), patch.object(exp, "push", return_value="key"), \
             patch.object(exp, "collect", return_value={"conclusion": "failure", "jobs": [{"conclusion": "failure"}]}) as collected:
            with self.assertRaisesRegex(ValueError, "hosted_replay_assertions_passed"):
                exp.measure("baseline")
        collected.assert_called_once()
        self.assertFalse(exp.state["records"][0]["scenario_pass"])


if __name__ == "__main__":
    unittest.main()
