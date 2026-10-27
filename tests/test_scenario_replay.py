"""Offline replay correctness, visibility boundaries, and hosted payload execution."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import scenario_replay as replay
import scenario_experiments as scenarios


class ReplayTests(unittest.TestCase):
    def test_all_three_workloads_and_both_policies(self):
        for pattern in replay.PATTERNS:
            for repeat in (1, 2, 3):
                for optimized in (False, True):
                    with self.subTest(pattern=pattern, repeat=repeat, optimized=optimized):
                        data = replay.dataset(pattern, repeat)
                        settings = replay.policy(pattern, optimized)
                        result = replay.run(pattern, settings, data)
                        checks = replay.validate(pattern, settings, data, result)
                        self.assertTrue(checks)
                        self.assertTrue(all(checks.values()), checks)

    def test_selection_cannot_see_skipped_or_future_outcomes(self):
        pattern = "P-LIT-BUILD-SELECT"
        data = replay.dataset(pattern, 1)
        settings = replay.policy(pattern, True)
        original = replay.run(pattern, settings, data)
        self.assertEqual(original["missed_failures"], 1)
        changed = copy.deepcopy(data)
        changed[2]["outcome"] = "success"  # suppressed oracle outcome must not affect later decisions
        altered = replay.run(pattern, settings, changed)
        self.assertEqual(original["trace"], altered["trace"])
        self.assertEqual(altered["missed_failures"], 0)
        changed[-1]["outcome"] = "success"
        changed[-1]["duration"] = 9999
        self.assertEqual(original["trace"][:-1], replay.run(pattern, settings, changed)["trace"][:-1])

    def test_prediction_uses_only_past_outcomes_and_measures_error(self):
        pattern = "P-LIT-DURATION-PREDICTION"
        data = replay.dataset(pattern, 1)
        baseline = replay.run(pattern, replay.policy(pattern), data)
        settings = replay.policy(pattern, True)
        optimized = replay.run(pattern, settings, data)
        self.assertLess(optimized["held_out_mae_seconds"], baseline["held_out_mae_seconds"])
        changed = copy.deepcopy(data)
        changed[6]["duration"] = 99999
        altered = replay.run(pattern, settings, changed)
        self.assertEqual([r["prediction"] for r in optimized["trace"][:7]],
                         [r["prediction"] for r in altered["trace"][:7]])
        self.assertFalse(optimized["direct_speedup_claimed"])
        self.assertEqual(optimized["simulated_work_seconds"], baseline["simulated_work_seconds"])

    def test_job_priority_preserves_artifacts_and_only_changes_feedback(self):
        pattern = "P-LIT-FAILED-JOB-FIRST"
        data = replay.dataset(pattern, 1)
        baseline = replay.run(pattern, replay.policy(pattern), data)
        optimized = replay.run(pattern, replay.policy(pattern, True), data)
        self.assertLess(optimized["cases"][0]["first_failure_seconds"], baseline["cases"][0]["first_failure_seconds"])
        self.assertEqual(optimized["simulated_work_seconds"], baseline["simulated_work_seconds"])
        corrupted = copy.deepcopy(optimized)
        corrupted["cases"][2]["trace"][0], corrupted["cases"][2]["trace"][1] = (
            corrupted["cases"][2]["trace"][1], corrupted["cases"][2]["trace"][0])
        self.assertFalse(all(replay.validate(pattern, replay.policy(pattern, True), data, corrupted).values()))

    def test_queue_priority_improves_urgent_wait_and_ages_old_work(self):
        pattern = "P-LIT-BUILD-PRIORITY"
        data = replay.dataset(pattern, 1)
        baseline = replay.run(pattern, replay.policy(pattern), data)
        optimized = replay.run(pattern, replay.policy(pattern, True), data)
        self.assertLess(optimized["cases"]["contended"]["urgent_wait_seconds"],
                        baseline["cases"]["contended"]["urgent_wait_seconds"])
        self.assertTrue(any(r["reason"] == "aging" for r in optimized["cases"]["contended"]["trace"]))

    def test_pause_requires_threshold_notification_and_recovery(self):
        pattern = "P-LIT-FAIL-SCHEDULE"
        data = replay.dataset(pattern, 1)
        settings = replay.policy(pattern, True)
        result = replay.run(pattern, settings, data)
        self.assertEqual([r["id"] for r in result["trace"] if r["action"] == "suppressed"], [2, 3])
        result["notifications"] = []
        self.assertFalse(replay.validate(pattern, settings, data, result)["notification"])

    def test_idle_ignores_generated_updates_and_resumes_for_external_inputs(self):
        pattern = "P-LIT-IDLE-SCHEDULE"
        data = replay.dataset(pattern, 1)
        result = replay.run(pattern, replay.policy(pattern, True), data)
        self.assertEqual([r["id"] for r in result["trace"] if r["action"] == "run"], [0, 5, 8])

    def test_embedded_hosted_script_executes_exactly_the_replay(self):
        # Execute the actual standalone engine embedded in the workflow (no API calls).
        for pattern in sorted(replay.PATTERNS):
            for optimized in (False, True):
                with self.subTest(pattern=pattern, optimized=optimized):
                    workflow = scenarios.fixture(pattern, scenarios.settings_from_env())
                    step = workflow["jobs"]["probe"]["steps"][0]
                    step["env"]["CT_POLICY"] = json.dumps(replay.policy(pattern, optimized))
                    source = step["run"].split("\n", 1)[1].rsplit("\nCLOUDTUNE_REPLAY_ENGINE", 1)[0]
                    process = subprocess.run([sys.executable, "-c", source], env={**os.environ, **step["env"]},
                                             capture_output=True, text=True, timeout=15)
                    self.assertEqual(process.returncode, 0, process.stderr)
                    actual = json.loads(process.stdout)
                    expected = replay.run(pattern, replay.policy(pattern, optimized), replay.dataset(pattern, 1))
                    self.assertEqual(actual["result"], expected)
                    self.assertTrue(all(actual["assertions"].values()))


if __name__ == "__main__":
    unittest.main()
