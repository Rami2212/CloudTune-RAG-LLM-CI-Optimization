"""Preflight gate tests: no GitHub fork, dispatch, or target CI is used."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock, patch

import evaluation.fork_pipeline as pipeline


class PreflightGateTests(unittest.TestCase):
    def test_unchanged_arm_is_admitted_only_with_valid_baseline(self):
        verdict = {"verdict": "NO_CHANGE", "reasons": ["OPTIMIZER_ABSTAINED"]}
        with patch.object(pipeline, "validate_baseline", return_value={"verdict": "PASS"}):
            data = pipeline._admitted_workflow(b"original", None, verdict)
        self.assertEqual(data, b"original")
        self.assertEqual(verdict["verdict"], "NO_CHANGE")
        repo = {"validation": {"B": verdict, "C": verdict}}
        self.assertTrue(pipeline._hold_for_preflight(
            repo, {"A": data, "B": data, "C": data},
            preflight_only=True, require_all_arms=True))
        self.assertEqual(repo["status"], "PREFLIGHT_READY")

    def test_unchanged_arm_with_invalid_baseline_remains_blocked(self):
        verdict = {"verdict": "NO_CHANGE"}
        with patch.object(pipeline, "validate_baseline", return_value={
                "verdict": "FAIL", "reasons": ["ACTIONLINT_FAIL"]}):
            self.assertIsNone(pipeline._admitted_workflow(b"invalid", None, verdict))
        self.assertEqual(verdict["baseline_validation"]["verdict"], "FAIL")

    def test_rejected_candidate_never_falls_back_to_original(self):
        for verdict in ("FAIL", "REVIEW_REQUIRED", "INCONCLUSIVE"):
            with self.subTest(verdict=verdict):
                self.assertIsNone(pipeline._admitted_workflow(
                    b"original", b"unsafe", {"verdict": verdict}))

    def test_preflight_holds_even_when_all_three_arms_pass(self):
        repo = {"validation": {"B": {"verdict": "PASS"}, "C": {"verdict": "PASS"}}}
        hold = pipeline._hold_for_preflight(
            repo, {"A": b"a", "B": b"b", "C": b"c"},
            preflight_only=True, require_all_arms=False)
        self.assertTrue(hold)
        self.assertEqual(repo["status"], "PREFLIGHT_READY")
        self.assertEqual(repo["admitted_arms"], ["A", "B", "C"])

    def test_preflight_holds_when_b_requires_review(self):
        repo = {"validation": {"B": {"verdict": "REVIEW_REQUIRED"},
                               "C": {"verdict": "PASS"}}}
        hold = pipeline._hold_for_preflight(
            repo, {"A": b"a", "C": b"c"}, preflight_only=True,
            require_all_arms=False)
        self.assertTrue(hold)
        self.assertEqual(repo["status"], "PREFLIGHT_BLOCKED")
        self.assertIn("B=REVIEW_REQUIRED", repo["failure_reason"])

    def test_require_all_arms_blocks_hosted_execution_when_c_abstains(self):
        repo = {"validation": {"B": {"verdict": "PASS"},
                               "C": {"verdict": "NO_CHANGE"}}}
        self.assertTrue(pipeline._hold_for_preflight(
            repo, {"A": b"a", "B": b"b"},
            preflight_only=False, require_all_arms=True))
        self.assertEqual(repo["status"], "PREFLIGHT_BLOCKED")

    def test_require_all_arms_allows_hosted_path_only_when_all_admitted(self):
        repo = {"validation": {"B": {"verdict": "PASS"}, "C": {"verdict": "PASS"}}}
        self.assertFalse(pipeline._hold_for_preflight(
            repo, {"A": b"a", "B": b"b", "C": b"c"},
            preflight_only=False, require_all_arms=True))

    def test_existing_incomplete_run_policy_is_unchanged_without_flag(self):
        repo = {"validation": {"B": {"verdict": "REVIEW_REQUIRED"}}}
        self.assertFalse(pipeline._hold_for_preflight(
            repo, {"A": b"a"}, preflight_only=False, require_all_arms=False))
        self.assertNotIn("status", repo)

    def _run_cli(self, args, status):
        config = {"evaluation_id": "dev-smoke-003", "repository_start_at": 1,
                  "repository_limit": 1, "execution": {"development_smoke": True}}
        report = {"evaluation_id": config["evaluation_id"],
                  "repositories": {"owner/repo": {"status": status,
                     "cleanup_status": "NOT_STARTED"}}}
        with (patch.object(sys, "argv", ["controller", "--config", "unused", *args]),
              patch.dict(os.environ, {"OPENROUTER_MODEL": "offline/test:free",
                                      "OPENROUTER_MAX_TOKENS": "24000"}),
              patch.object(pipeline, "_config", return_value=config),
              patch.object(pipeline, "selected_repository_rows", return_value=[(1, "owner/repo")]),
              patch.object(pipeline, "load_env"),
              patch.object(pipeline, "exclusive_controller", return_value=nullcontext()),
              patch.object(pipeline, "run_fork_evaluation", return_value=report) as run):
            exit_code = pipeline.main()
        return exit_code, run

    def test_preflight_cli_passes_hold_flag_and_surfaces_blocked_status(self):
        exit_code, run = self._run_cli(["--preflight"], "PREFLIGHT_BLOCKED")
        self.assertEqual(exit_code, 2)
        self.assertTrue(run.call_args.kwargs["preflight_only"])

    def test_preflight_cli_reports_ready_without_hosted_dispatch(self):
        exit_code, run = self._run_cli(["--preflight"], "PREFLIGHT_READY")
        self.assertEqual(exit_code, 0)
        self.assertTrue(run.call_args.kwargs["preflight_only"])

    def test_hosted_require_all_cli_surfaces_blocked_status(self):
        exit_code, run = self._run_cli(["--require-all-arms"], "PREFLIGHT_BLOCKED")
        self.assertEqual(exit_code, 2)
        self.assertTrue(run.call_args.kwargs["require_all_arms"])

    def test_preflight_rejects_combined_watch(self):
        code, run = self._run_cli(["--preflight", "--watch"], "PREFLIGHT_READY")
        self.assertEqual(code, 1)
        run.assert_not_called()

    def test_controller_preflight_archives_both_passes_without_fork_writes(self):
        self._controller_preflight()

    def test_cuda_pause_preserves_trial_and_resumes_without_regenerating_b(self):
        self._controller_preflight(pause_device=True)

    def _controller_preflight(self, pause_device=False):
        """Exercise the actual coordinator path up to the fork safety boundary."""
        original = b"on: workflow_dispatch\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo ok\n"
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = {"evaluation_id": "dev-preflight-001", "dataset": "evaluation/results/repos.csv",
                      "repository_limit": 1, "repetitions": 1, "ci_cost": {"version": "1.0.0"},
                      "rag": {"embedding_revision": "AUTO_PIN_SINGLE", "dataset_sha256": "a" * 64,
                              "generator_model": "example:free", "top_k": 5, "max_tokens": 100},
                      "execution": {"required_job_names": []}}
            snapshot = root / "evaluation/results/dev-preflight-001/repositories/owner-repo"
            source = snapshot / "source/original.yml"
            source.parent.mkdir(parents=True)
            source.write_bytes(original)
            (snapshot / "manifest.json").write_text(json.dumps({
                "repo_id": "owner/repo", "workflow_path": ".github/workflows/ci.yml",
                "workflow_sha256": hashlib.sha256(original).hexdigest(),
                "source_commit_sha": "a" * 40}))

            def prepared(_, state, store, token=None):
                output = root / "evaluation/results/dev-preflight-001"
                with (output / "screening.csv").open("w", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=["repo_id", "status", "manifest_path"])
                    writer.writeheader()
                    writer.writerow({"repo_id": "owner/repo", "status": "prepared",
                                     "manifest_path": str(snapshot / "manifest.json")})
                return output

            b = {"decision": "APPLY", "status": "GENERATED_NOT_VALIDATED",
                 "after_sha256": "b" * 64, "candidate_relative_dir": "candidates/B",
                 "generated_artifact": "candidate.yml"}
            c = {"decision": "APPLY", "after_sha256": "c" * 64,
                 "generated_artifact": "candidate.yml"}
            experiment = MagicMock()
            experiment.provision.side_effect = AssertionError("preflight must not provision a fork")
            experiment.prepare.side_effect = AssertionError("preflight must not prepare a fork")
            experiment.make_arm.side_effect = AssertionError("preflight must not push an arm")
            experiment.execute.side_effect = AssertionError("preflight must not dispatch CI")
            with (patch.dict(os.environ, {"GITHUB_TOKEN": "offline-test-token",
                                       "CI_COST_DIR": str(root / "reviewed-ci-cost-v2"),
                                       "CLOUDTUNE_AUTO_DELETE_FORKS": "true"}),
                  patch.object(pipeline, "ROOT", root),
                  patch.object(pipeline, "implementation_digest", return_value="code-sha"),
                  patch.object(pipeline, "_ensure_preparation", side_effect=prepared),
                  patch.object(pipeline, "GitHub", return_value=MagicMock()),
                  patch.object(pipeline, "ForkExperiment", return_value=experiment),
                  patch.object(pipeline, "install_ci_cost") as install,
                  patch.object(pipeline, "generate_ci_cost_candidate", return_value=b) as generate,
                  patch.object(pipeline, "Retriever") as retriever,
                  patch.object(pipeline, "generate_rag_candidate", side_effect=(
                      [pipeline.RagDevicePaused("No CUDA GPUs are available"), c]
                      if pause_device else [c])) as rag,
                  patch.object(pipeline, "_candidate_yaml", return_value=b"safe-cache-workflow"),
                  patch.object(pipeline, "validate_and_archive", return_value={"verdict": "PASS"}) as validate):
                retriever.return_value.revision = "a" * 40
                retriever.return_value.pattern_catalogue = [{}] * 25
                report = pipeline.run_fork_evaluation(config, preflight_only=True)
                if pause_device:
                    paused = report["repositories"]["owner/repo"]
                    self.assertEqual(paused["status"], "RAG_PAUSED")
                    self.assertIn("No CUDA GPUs", paused["failure_reason"])
                    self.assertNotIn("C", paused["candidates"])
                    validate.assert_not_called()
                    experiment.provision.assert_not_called()
                    experiment.execute.assert_not_called()
                    report = pipeline.run_fork_evaluation(config, preflight_only=True)
                    self.assertEqual(rag.call_count, 2)
                generate.assert_called_once()
                install.assert_called_once_with((root / "reviewed-ci-cost-v2").resolve())
                self.assertEqual(generate.call_args.kwargs["tool_dir"],
                                 (root / "reviewed-ci-cost-v2").resolve())
            result = report["repositories"]["owner/repo"]
            self.assertEqual(result["status"], "PREFLIGHT_READY")
            self.assertEqual(result["admitted_arms"], ["A", "B", "C"])
            self.assertEqual(result["run_records"], [])
            experiment.provision.assert_not_called()
            experiment.prepare.assert_not_called()
            experiment.make_arm.assert_not_called()
            experiment.execute.assert_not_called()

    def test_cuda_paused_cli_exits_nonzero(self):
        code, run = self._run_cli(["--preflight"], "RAG_PAUSED")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
