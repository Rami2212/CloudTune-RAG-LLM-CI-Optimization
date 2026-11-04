"""Offline tests for deterministic four-way split and pause-safe team runner."""
from __future__ import annotations

import csv
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evaluation.prepare_evaluation_assignments import split_dataset
from scripts import run_evaluation_batch as team
from scripts.merge_evaluation_results import merge_published


class TeamEvaluationTests(unittest.TestCase):
    def test_member_position_bounds(self):
        self.assertEqual(team.position_bounds(), (1, 1000))
        self.assertEqual(team.position_bounds(14, 16), (14, 16))
        self.assertEqual(team.position_bounds(14, limit=3), (14, 16))
        self.assertEqual(team.position_bounds(1000, limit=1), (1000, 1000))
        for args in ((0, None, None), (1001, None, None), (14, 13, None),
                     (1, 1001, None), (1, None, 0), (1000, None, 2), (1, 3, 2)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                team.position_bounds(*args)

    def test_range_limits_active_rerun_without_losing_unvisited_positions(self):
        rows = team._assignment(1)
        team.freeze_batch(1, "eval-member-01")
        for i in (13, 14, 15, 16):
            self._save_trial(i, status="PREFLIGHT_BLOCKED")
        calls = []
        def invoke(member, position, mode, batch_id):
            calls.append(position)
            self._save_trial(position, status="PREFLIGHT_BLOCKED")
            return 2
        with patch.object(team, "_invoke", side_effect=invoke):
            self.assertEqual(team.run_batch(1, "eval-member-01", preflight_only=True,
                max_repositories=None, rerun_failed=True, start_at=14, limit=2), 0)
        self.assertEqual(calls, [14, 15])
        plan = team._read_json(team.RESULTS / "eval-member-01/rerun_state.json")
        self.assertTrue(plan["active"])
        self.assertEqual(plan["positions"], [13, 14, 15, 16])
        with patch.object(team, "_invoke", side_effect=invoke):
            self.assertEqual(team.run_batch(1, "eval-member-01", preflight_only=True,
                max_repositories=None, rerun_failed=True, start_at=13, stop_at=13), 0)
        self.assertEqual(calls, [14, 15, 13])

    def test_finalized_cancelled_trial_with_preserved_fork_can_advance(self):
        state = {"status": "FAILED_TARGET_CI", "measurements_finalized": True,
                 "fork_repo": "research/breakpad", "cleanup_status": "PRESERVED_NOT_OWNED"}
        self.assertEqual(team._stage(state, {}), "finished")
        for cleanup in ("WAITING_FOR_OTHER_RUNS", "DELETE_OUTCOME_UNKNOWN", "BLOCKED_PERMISSION"):
            self.assertEqual(team._stage({**state, "cleanup_status": cleanup}, {}), "hosted")
        self.assertEqual(team._stage({**state, "pending": {"run_id": 123}}, {}), "hosted")
        self.assertEqual(team._stage({**state, "measurements_finalized": False}, {}), "hosted")

    def test_preserved_fork_controller_exit_allows_batch_to_continue(self):
        state = {"status": "FAILED_TARGET_CI", "measurements_finalized": True,
                 "fork_repo": "research/breakpad", "cleanup_status": "PRESERVED_NOT_OWNED"}
        with patch.object(team, "_member_config", return_value=Path("config.json")), \
             patch.object(team, "_assignment", return_value=[{"repo_id": "google/breakpad"}]), \
             patch.object(team, "_record", return_value=({}, state, {})), \
             patch.object(team.subprocess, "run", return_value=subprocess.CompletedProcess([], 2)):
            self.assertEqual(team._invoke(1, 1, "hosted", "batch"), 0)
            state["pending"] = {"run_id": 123}
            self.assertEqual(team._invoke(1, 1, "hosted", "batch"), 2)

    def test_same_batch_rerun_allocates_generations_and_preserves_success(self):
        self._save_trial(1, status="PREFLIGHT_BLOCKED")
        self._save_trial(2, status="COMPLETE", finalized=True)
        self._save_trial(3, status="FAILED_TARGET_CI", finalized=True)
        original = team.trial_directory(team.RESULTS, "eval-member-01-r0001") / "state.json"
        original_bytes = original.read_bytes()
        rows = [{"repo_id": f"owner/repo-{i:04d}"} for i in range(1, 5)]
        plan = team.prepare_failed_rerun("eval-member-01", rows)
        self.assertEqual(plan["positions"], [1, 3])
        self.assertEqual(team._trial_id("eval-member-01", 1), "eval-member-01-r0001-r2")
        self.assertEqual(team._trial_id("eval-member-01", 2), "eval-member-01-r0002")
        self.assertEqual(team.prepare_failed_rerun("eval-member-01", rows), plan)
        self.assertEqual(original.read_bytes(), original_bytes)
        self._save_trial(1, status="PREFLIGHT_BLOCKED")
        self._save_trial(3, status="COMPLETE", finalized=True)
        plan["active"] = False
        team._atomic_json(team.RESULTS / "eval-member-01/rerun_state.json", plan)
        next_plan = team.prepare_failed_rerun("eval-member-01", rows)
        self.assertEqual(next_plan["positions"], [1])
        self.assertEqual(team._trial_id("eval-member-01", 1), "eval-member-01-r0001-r3")
        self.assertEqual(team._trial_id("eval-member-01", 3), "eval-member-01-r0003-r2")

    def test_same_batch_rerun_resumes_round_and_publishes_latest_generation(self):
        rows = team._assignment(1)
        team.freeze_batch(1, "eval-member-01")
        self._save_trial(1, status="PREFLIGHT_BLOCKED")
        self._save_trial(2, status="COMPLETE", finalized=True)
        invoked = []

        def invoke(member, position, mode, batch_id):
            invoked.append((position, mode, team._trial_id(batch_id, position)))
            self._save_trial(position, status="PREFLIGHT_READY" if mode == "preflight" else "COMPLETE",
                             finalized=mode == "hosted", cleanup="RETAINED_BY_CONFIGURATION")
            return 0

        with patch.object(team, "_invoke", side_effect=invoke):
            self.assertEqual(team.run_batch(1, "eval-member-01", preflight_only=True,
                                           max_repositories=1, rerun_failed=True), 0)
            self.assertEqual(team.run_batch(1, "eval-member-01", preflight_only=False,
                                           max_repositories=1, rerun_failed=True), 0)
        self.assertEqual(invoked, [(1, "preflight", "eval-member-01-r0001-r2"),
                                   (1, "hosted", "eval-member-01-r0001-r2")])
        plan = team._read_json(team.RESULTS / "eval-member-01/rerun_state.json")
        self.assertFalse(plan["active"])
        with (team.RESULTS / "eval-member-01/published/attempts.csv").open(newline="") as handle:
            published = list(csv.DictReader(handle))
        self.assertEqual(published[0]["evaluation_id"], "eval-member-01-r0001-r2")
        self.assertEqual(published[1]["evaluation_id"], "eval-member-01-r0002")

    def test_rerun_preserves_original_identity_and_still_rejects_model_change(self):
        team._assignment(1)
        identity_path = team.freeze_batch(1, "eval-member-01")
        identity = json.loads(identity_path.read_text())
        identity["runner_sha256"] = "previous-runner"
        identity_path.write_text(json.dumps(identity))
        original = identity_path.read_bytes()
        team.freeze_batch(1, "eval-member-01", rerun_failed=True)
        self.assertEqual(identity_path.read_bytes(), original)
        with patch.dict("os.environ", {"OPENROUTER_MODEL": "other/model:free"}):
            with self.assertRaisesRegex(ValueError, "Frozen batch identity changed"):
                team.freeze_batch(1, "eval-member-01", rerun_failed=True)

    def test_retry_selection_excludes_successful_and_unattempted_repositories(self):
        self._save_trial(1, status="PREFLIGHT_BLOCKED")
        self._save_trial(2, status="COMPLETE", finalized=True)
        self._save_trial(3, status="FAILED_TARGET_CI", finalized=True)
        self._save_trial(4, status="INCOMPLETE")
        rows = [{"repo_id": f"owner/repo-{i:04d}"} for i in range(1, 6)]
        self.assertEqual(team.failed_positions("eval-member-01", rows), [1, 3, 4])

    def test_retry_selection_refuses_pending_trial(self):
        self._save_trial(1, status="LLM_PAUSED")
        path = team.trial_directory(team.RESULTS, "eval-member-01-r0001") / "state.json"
        state = json.loads(path.read_text())
        state["repositories"]["owner/repo-0001"]["pending"] = {"run_id": 123}
        path.write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError, "pending CI"):
            team.failed_positions("eval-member-01", [{"repo_id": "owner/repo-0001"}])

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        source = self.root / "evaluation/evaluation_repositories_4000.csv"
        source.parent.mkdir(parents=True)
        with source.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=("selection_rank", "repo_id", "split"))
            writer.writeheader()
            for n in range(1, 4001):
                writer.writerow({"selection_rank": n, "repo_id": f"owner/repo-{n:04d}", "split": "evaluation"})
        (self.root / "evaluation/configs").mkdir()
        (self.root / "evaluation/configs/fork_pilot.json").write_text("{}", encoding="utf-8")
        self.patches = [patch.object(team, "ROOT", self.root),
                        patch.object(team, "RESULTS", self.root / "evaluation/results"),
                        patch.object(team, "BASE_CONFIG", self.root / "evaluation/configs/fork_pilot.json"),
                        patch.object(team, "load_env"),
                        patch.dict("os.environ", {"CLOUDTUNE_AUTO_DELETE_FORKS": "false", "OPENROUTER_MODEL": "test/model-a:free", "OPENROUTER_MAX_TOKENS": "24000"})]
        for monkey in self.patches:
            monkey.start()
            self.addCleanup(monkey.stop)

    def test_trial_paths_group_batches_and_reject_misplaced_checkpoints(self):
        trial = "custom-batch-r0017"
        expected = team.RESULTS / "custom-batch" / trial
        self.assertEqual(team.trial_directory(team.RESULTS, trial), expected)
        self.assertEqual(team.trial_directory(team.RESULTS, trial + "-r2"),
                         expected.with_name(trial + "-r2"))
        self.assertEqual(team.trial_directory(team.RESULTS, "dev-smoke"),
                         team.RESULTS / "dev-smoke")
        (team.RESULTS / trial).mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, "Checkpoint outside batch directory"):
            team.trial_directory(team.RESULTS, trial)

    def test_assignments_are_disjoint_and_byte_stable(self):
        first = split_dataset(root=self.root)
        second = split_dataset(root=self.root)
        self.assertEqual(first, second)
        self.assertEqual(first["rows"], 4000)
        values = []
        for assignment in first["assignments"]:
            with (self.root / assignment["file"]).open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1000)
            values.extend(row["repo_id"] for row in rows)
        self.assertEqual(len(set(values)), 4000)
        changed = self.root / first["assignments"][0]["file"]
        changed.write_text("modified\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "do not overwrite"):
            split_dataset(root=self.root)

    def _save_trial(self, position, *, status, finalized=False, cleanup="NOT_STARTED"):
        directory = team.trial_directory(team.RESULTS, team._trial_id(team.default_batch_id(1), position))
        directory.mkdir(parents=True, exist_ok=True)
        repo = f"owner/repo-{position:04d}"
        (directory / "state.json").write_text(json.dumps({
            "config_sha256": "a" * 64, "implementation_sha256": "b" * 64,
            "repositories": {repo: {"status": status,
                "measurements_finalized": finalized, "cleanup_status": cleanup,
                "candidates": {}, "validation": {}, "records": [],
                "pending": {"run_id": 123} if status == "WAITING_FOR_GITHUB_RUN" else None,
                "fork_repo": "research/" + repo.split("/")[-1] if finalized else None}}
        }), encoding="utf-8")
        (directory / "fork_report.json").write_text(json.dumps({
            "repositories": {repo: {"status": status}}}), encoding="utf-8")

    def test_recovers_first_unfinished_without_replaying_finalized_row(self):
        split_dataset(root=self.root)
        self._save_trial(1, status="PREFLIGHT_BLOCKED")
        self._save_trial(2, status="WAITING_FOR_GITHUB_RUN")
        calls = []
        def fake_invoke(member, position, mode, batch_id):
            calls.append((member, position, mode))
            self._save_trial(position, status="COMPLETE", finalized=True,
                             cleanup="RETAINED_BY_CONFIGURATION")
            return 0
        with patch.object(team, "_invoke", side_effect=fake_invoke):
            self.assertEqual(team.run_batch(1, team.default_batch_id(1), preflight_only=False, max_repositories=1), 0)
        self.assertEqual(calls, [(1, 2, "hosted")])
        published = team.RESULTS / "eval-member-01/published/attempts.csv"
        with published.open(newline="", encoding="utf-8") as handle:
            records = list(csv.DictReader(handle))
        self.assertEqual(len(records), 1000)
        self.assertEqual(records[0]["status"], "PREFLIGHT_BLOCKED")
        self.assertEqual(records[1]["status"], "COMPLETE")
        self.assertEqual(records[2]["status"], "NOT_STARTED")

    def test_child_uses_member_partition_and_local_row_position(self):
        split_dataset(root=self.root)
        completed = type("Finished", (), {"returncode": 0})()
        with patch.object(team.subprocess, "run", return_value=completed) as run:
            self.assertEqual(team._invoke(2, 17, "preflight", team.default_batch_id(2)), 0)
        args = run.call_args.args[0]
        self.assertEqual(args[args.index("--batch-id") + 1], "eval-member-02-r0017")
        self.assertEqual(args[args.index("--start-at") + 1], "17")
        self.assertEqual(args[args.index("--limit") + 1], "1")
        config = json.loads(Path(args[args.index("--config") + 1]).read_text())
        self.assertEqual(config["dataset"], "evaluation/assignments/member_02.csv")
        self.assertIn("--preflight", args)
        self.assertNotIn("--watch", args)

    def test_openrouter_pause_stops_without_skipping_or_retrying(self):
        split_dataset(root=self.root)
        for status in ("LLM_PAUSED", "RAG_PAUSED"):
            with self.subTest(status=status):
                calls = []
                def fake_invoke(member, position, mode, batch_id):
                    calls.append((position, mode))
                    self._save_trial(position, status=status)
                    return 2
                with patch.object(team, "_invoke", side_effect=fake_invoke):
                    self.assertEqual(team.run_batch(1, team.default_batch_id(1), preflight_only=False, max_repositories=4), 2)
                self.assertEqual(calls, [(1, "preflight")])
                self.assertEqual(team._stage({"status": status}, {}), "preflight")

    def test_member_config_uses_its_own_partition_and_fails_on_changes(self):
        split_dataset(root=self.root)
        config = team._member_config(3, team.default_batch_id(3))
        self.assertEqual(json.loads(config.read_text())["dataset"],
                         "evaluation/assignments/member_03.csv")
        config.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "configuration has changed"):
            team._member_config(3, team.default_batch_id(3))

    def test_merge_4000_committed_results_with_identity_checks(self):
        split_dataset(root=self.root)
        for member in (1, 2, 3, 4):
            # No API calls needed: a not-yet-started row must remain in the denominator.
            with patch.object(team, "ROOT", self.root):
                team.publish_batch(member, team._assignment(member), team.default_batch_id(member))
        manifest = merge_published(root=self.root)
        self.assertEqual(manifest["total_selected"], 4000)
        self.assertEqual(manifest["status_counts"], {"NOT_STARTED": 4000})
        merged = self.root / "evaluation/results/cohort/published/attempts_4000.csv"
        with merged.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 4000)
        self.assertEqual(rows[1000]["repo_id"], "owner/repo-1001")
        self.assertEqual(rows[1000]["evaluation_id"], "eval-member-02-r0001")

    def test_published_trial_does_not_copy_raw_request(self):
        split_dataset(root=self.root)
        self._save_trial(1, status="COMPLETE", finalized=True,
                         cleanup="RETAINED_BY_CONFIGURATION")
        raw = team.trial_directory(team.RESULTS, team._trial_id(team.default_batch_id(1), 1)) / "secret_prompt.json"
        raw.write_text('{"token":"NOT_FOR_GIT"}')
        rows = team._assignment(1)
        folder = team.publish_batch(1, rows, team.default_batch_id(1))
        evidence = (folder / "trials/r0001.json").read_text()
        self.assertNotIn("NOT_FOR_GIT", evidence)
        self.assertNotIn('"token":', evidence)
        self.assertTrue(raw.exists())

    def test_distinct_custom_batch_ids_are_isolated_and_resume_exactly(self):
        split_dataset(root=self.root)
        a, b = "evaluation-smoke-a", "evaluation-smoke-b"
        self.assertEqual(team._trial_id(a, 19), "evaluation-smoke-a-r0019")
        self.assertEqual(team._trial_id(b, 19), "evaluation-smoke-b-r0019")
        # The two IDs have distinct private identity/config and published outputs.
        with patch.dict("os.environ", {"OPENROUTER_MODEL": "test/free:free",
                                     "OPENROUTER_MAX_TOKENS": "24000",
                                     "CLOUDTUNE_AUTO_DELETE_FORKS": "false"}):
            team.freeze_batch(1, a)
            team.freeze_batch(1, b)
        self.assertNotEqual(team._member_config(1, a), team._member_config(1, b))
        self.assertNotEqual(team.publish_batch(1, team._assignment(1), a),
                            team.publish_batch(1, team._assignment(1), b))

    def test_changed_model_does_not_silently_mix_trials_in_batch(self):
        split_dataset(root=self.root)
        batch_id = team.default_batch_id(1)
        with patch.dict("os.environ", {"OPENROUTER_MODEL": "test/model-a:free",
                                     "OPENROUTER_MAX_TOKENS": "24000",
                                     "CLOUDTUNE_AUTO_DELETE_FORKS": "false"}):
            team.freeze_batch(1, batch_id)
        with patch.dict("os.environ", {"OPENROUTER_MODEL": "test/model-b:free",
                                     "OPENROUTER_MAX_TOKENS": "24000",
                                     "CLOUDTUNE_AUTO_DELETE_FORKS": "false"}):
            with self.assertRaisesRegex(ValueError, "Frozen batch identity changed"):
                team.freeze_batch(1, batch_id)

    def test_rejects_duplicate_custom_batch_ids_or_invalid_suffix(self):
        for value in ("bad id", "x" * 59, "foo-r0001", "cohort"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                team.validated_batch_id(1, value)
        self.assertEqual(team.validated_batch_id(4, None), "eval-member-04")

    def test_merging_custom_batch_ids_preserves_member_identity(self):
        split_dataset(root=self.root)
        names = tuple(f"custom-eval-m{m:02d}" for m in range(1, 5))
        for m, name in enumerate(names, 1):
            team.publish_batch(m, team._assignment(m), name)
        manifest = merge_published(root=self.root, batch_ids=names)
        self.assertEqual(manifest["total_selected"], 4000)
        self.assertEqual(manifest["assignments"][0]["batch_id"], names[0])
        with self.assertRaisesRegex(ValueError, "distinct"):
            merge_published(root=self.root, batch_ids=(names[0], names[0], names[2], names[3]))

    def test_batch_publication_refuses_other_members_identity(self):
        split_dataset(root=self.root)
        name = "shared-name"
        with patch.dict("os.environ", {"OPENROUTER_MODEL": "test/model-a:free",
                                     "OPENROUTER_MAX_TOKENS": "24000",
                                     "CLOUDTUNE_AUTO_DELETE_FORKS": "false"}):
            team.freeze_batch(1, name)
            with self.assertRaisesRegex(ValueError, "Frozen batch identity changed"):
                team.freeze_batch(2, name)
        with self.assertRaisesRegex(ValueError, "belongs to another member"):
            team.publish_batch(2, team._assignment(2), name)

    def test_batch_lock_refuses_second_controller_and_releases(self):
        split_dataset(root=self.root)
        batch_id = team.default_batch_id(1)
        with team.exclusive_batch(batch_id):
            with self.assertRaisesRegex(RuntimeError, "already active"):
                with team.exclusive_batch(batch_id):
                    pass
        self.assertFalse((team.RESULTS / batch_id / ".batch.lock").exists())
        with team.exclusive_batch(batch_id):
            self.assertTrue((team.RESULTS / batch_id / ".batch.lock").exists())

    def test_gitignore_accepts_published_metrics_but_blocks_live_state(self):
        if not shutil.which("git"):
            self.skipTest("Git is required for ignore-rule verification")
        destination = self.root / "evaluation/results/.gitignore"
        source = Path(__file__).resolve().parents[1] / "evaluation/results/.gitignore"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
        subprocess.run(["git", "init", "-q", str(self.root)], check=True, capture_output=True)
        allowed = (
            "evaluation/results/eval-member-01/published/attempts.csv",
            "evaluation/results/eval-member-01/published/manifest.json",
            "evaluation/results/eval-member-01/published/trials/r0001.json",
            "evaluation/results/cohort/published/attempts_4000.csv",
        )
        forbidden = (
            "evaluation/results/eval-member-01/state.json",
            "evaluation/results/eval-member-01/batch_identity.json",
            "evaluation/results/eval-member-01-r0001/state.json",
            "evaluation/results/eval-member-01-r0001/repositories/manifest.json",
            "evaluation/results/.tools/ci-cost/index.js",
            "evaluation/results/eval-member-01/published/trials/secret_prompt.json",
        )
        for relpath, ignored in ((*[(p, False) for p in allowed],
                                  *[(p, True) for p in forbidden])):
            path = self.root / relpath
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("test", encoding="utf-8")
            checked = subprocess.run(["git", "check-ignore", "-q", relpath], cwd=self.root,
                                     check=False, capture_output=True)
            self.assertEqual(checked.returncode == 0, ignored, relpath)


if __name__ == "__main__":
    unittest.main()
