"""Offline tests for pinned ci-cost generation, archive integrity and coordinator."""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch
from subprocess import CompletedProcess

from evaluation.optimizers.ci_cost import (
    PINNED_SOURCE_COMMIT, generate_ci_cost_candidate,
)
from evaluation.run_pipeline import generate_b
from evaluation.third_party.ci_cost.source_fixes import FIX_REVISION, fix_identity

ORIGINAL = b"""name: CI
on:
  workflow_dispatch:
  push:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Install
        run: npm install
      - run: npm test
"""
CHANGED = ORIGINAL.replace(b"npm install", b"npm ci")
HEADER = (b"# Optimized by ci-cost (https://github.com/mariotavarez/ci-cost)\n"
          b"# Applied 1 optimization:\n# - [HIGH] Test recommendation\n"
          b"# Estimated savings: ~1 min/run\n#\n")


class FakeCommandRunner:
    def __init__(self, optimized=None, *, exit_code=0, version="ci-cost v1.0.0",
                 stderr="", commit=PINNED_SOURCE_COMMIT, dirty=False,
                 analysis_completed=True):
        self.optimized = optimized
        self.exit_code = exit_code
        self.version = version
        self.stderr = stderr
        self.commit = commit
        self.dirty = dirty
        self.analysis_completed = analysis_completed
        self.commands = []

    def __call__(self, command, **options):
        self.commands.append((command, options))
        assert options["env"].get("GITHUB_TOKEN") is None
        assert options["check"] is False
        assert options["cwd"]
        if "rev-parse" in command:
            return CompletedProcess(command, 0, self.commit + "\n", "")
        if "--porcelain" in command:
            return CompletedProcess(command, 0, " M dist/index.js" if self.dirty else "", "")
        if command[-1] == "--version":
            return CompletedProcess(command, 0, self.version, "")
        if self.optimized is not None:
            workflow_dir = Path(command[-1].removeprefix("--dir="))
            generated = workflow_dir / "optimized" / "ci.yml"
            generated.parent.mkdir(parents=True)
            generated.write_bytes(self.optimized)
        output = "Found 1 workflow\nAnalysis completed" if self.analysis_completed else ""
        return CompletedProcess(command, self.exit_code, output, self.stderr)


class CiCostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.snapshot = self.root / "repositories" / "demo-ci"
        source = self.snapshot / "source" / "original.yml"
        source.parent.mkdir(parents=True)
        source.write_bytes(ORIGINAL)
        self.manifest = {
            "repo_id": "demo/ci", "source_commit_sha": "a" * 40,
            "workflow_sha256": sha256(ORIGINAL).hexdigest(),
            "workflow_path": ".github/workflows/ci.yml", "status": "prepared",
        }
        (self.snapshot / "manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        self.tool_dir = self.root / ".venv" / "ci-cost"
        entry = self.tool_dir / "dist" / "index.js"
        entry.parent.mkdir(parents=True)
        entry.write_text("// fixture CLI entrypoint\n", encoding="utf-8")
        (self.tool_dir / "package-lock.json").write_text("{}\n", encoding="utf-8")

    def candidate(self, runner, **kwargs):
        record = {
            "fix_revision": FIX_REVISION, "fix_sha256": fix_identity(),
            "upstream_lock_sha256": sha256(b"{}\n").hexdigest(),
            "file_hashes": {"src/optimizer.ts": "verified-source-hash"},
        }
        with patch("evaluation.optimizers.ci_cost.verify_installation", return_value=record):
            return generate_ci_cost_candidate(
                self.snapshot, command_runner=runner, tool_dir=self.tool_dir, **kwargs)

    def test_exit_one_with_actual_change_is_apply_and_archived(self):
        runner = FakeCommandRunner(HEADER + CHANGED, exit_code=1)
        result = self.candidate(runner)
        self.assertEqual(result["decision"], "APPLY")
        self.assertEqual(result["status"], "GENERATED_NOT_VALIDATED")
        self.assertEqual(result["exit_code"], 1)
        folder = self.snapshot / "candidates" / "B" / FIX_REVISION
        self.assertEqual((folder / "optimized.yml").read_bytes(), HEADER + CHANGED)
        self.assertIn(b"+        run: npm ci", (folder / "change.patch").read_bytes())
        self.assertEqual((self.snapshot / "source" / "original.yml").read_bytes(), ORIGINAL)
        self.assertEqual(runner.commands[0][0][0], "node")
        self.assertEqual(runner.commands[0][0][-1], "--version")
        self.assertEqual(result["tool_source_commit"], PINNED_SOURCE_COMMIT)
        self.assertIsNotNone(result["tool_lock_sha256"])

    def test_old_upstream_failure_is_preserved_when_source_fix_runs(self):
        previous = self.snapshot / "candidates" / "B" / "candidate.json"
        previous.parent.mkdir(parents=True)
        previous.write_text('{"decision":"ERROR","reason":"invalid YAML"}', encoding="utf-8")
        result = self.candidate(FakeCommandRunner(CHANGED))
        self.assertEqual(result["decision"], "APPLY")
        self.assertEqual(json.loads(previous.read_text(encoding="utf-8"))["decision"], "ERROR")
        self.assertTrue((self.snapshot / "candidates" / "B" / FIX_REVISION / "candidate.json").is_file())

    def test_cli_reported_fix_failure_is_not_no_change(self):
        result = self.candidate(FakeCommandRunner(exit_code=0, stderr="Error generating optimized files: invalid YAML"))
        self.assertEqual(result["decision"], "ERROR")
        self.assertIn("generation error", result["error"])

    def test_comment_header_only_is_not_semantic_optimization(self):
        result = self.candidate(FakeCommandRunner(HEADER + ORIGINAL))
        self.assertEqual(result["decision"], "NO_CHANGE")
        self.assertFalse(result["semantic_changed"])
        self.assertIsNotNone(result["generated_sha256"])

    def test_exit_zero_without_generated_file_is_no_change(self):
        result = self.candidate(FakeCommandRunner())
        self.assertEqual(result["decision"], "NO_CHANGE")
        self.assertEqual(result["after_sha256"], result["before_sha256"])
        self.assertIsNone(result["generated_artifact"])

    def test_exit_one_with_advisory_only_is_no_change(self):
        result = self.candidate(FakeCommandRunner(exit_code=1))
        self.assertEqual(result["decision"], "NO_CHANGE")
        self.assertEqual(result["status"], "GENERATED_NOT_VALIDATED")

    def test_exit_one_without_successful_analysis_is_error(self):
        result = self.candidate(FakeCommandRunner(exit_code=1, analysis_completed=False))
        self.assertEqual(result["decision"], "ERROR")
        self.assertIn("without successful analysis", result["error"])

    def test_version_mismatch_is_error_not_a_fallback(self):
        runner = FakeCommandRunner(CHANGED, version="ci-cost v2.0.0")
        result = self.candidate(runner)
        self.assertEqual(result["decision"], "ERROR")
        self.assertEqual(len(runner.commands), 1)

    def test_wrong_tool_commit_is_error(self):
        with patch("evaluation.optimizers.ci_cost.verify_installation",
                   side_effect=ValueError("not the pinned upstream commit")):
            result = generate_ci_cost_candidate(self.snapshot, tool_dir=self.tool_dir,
                                               command_runner=FakeCommandRunner(CHANGED))
        self.assertEqual(result["decision"], "ERROR")
        self.assertIn("pinned upstream commit", result["error"])

    def test_modified_tool_checkout_is_error(self):
        with patch("evaluation.optimizers.ci_cost.verify_installation",
                   side_effect=ValueError("corrected source was changed")):
            result = generate_ci_cost_candidate(self.snapshot, tool_dir=self.tool_dir,
                                               command_runner=FakeCommandRunner(CHANGED))
        self.assertEqual(result["decision"], "ERROR")
        self.assertIn("corrected source", result["error"])

    def test_missing_installed_tool_is_error_not_a_no_change(self):
        with patch("evaluation.optimizers.ci_cost.verify_installation",
                   side_effect=ValueError("installation manifest is missing")):
            result = generate_ci_cost_candidate(self.snapshot, tool_dir=self.tool_dir,
                                               command_runner=FakeCommandRunner(CHANGED))
        self.assertEqual(result["decision"], "ERROR")
        self.assertIn("installation manifest", result["error"])

    def test_invalid_generated_yaml_is_error_but_archived(self):
        result = self.candidate(FakeCommandRunner(b"name: CI\njobs: [invalid]\n"))
        self.assertEqual(result["decision"], "ERROR")
        self.assertTrue((self.snapshot / "candidates" / "B" / FIX_REVISION / "optimized.yml").exists())

    def test_idempotent_resume_and_tamper_detection(self):
        original = self.candidate(FakeCommandRunner(CHANGED))
        reused = self.candidate(FakeCommandRunner(exit_code=2))
        self.assertEqual(original, reused)
        (self.snapshot / "candidates" / "B" / FIX_REVISION / "optimized.yml").write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "modified"):
            self.candidate(FakeCommandRunner())

    def test_frozen_source_tampering_rejected(self):
        (self.snapshot / "source/original.yml").write_bytes(b"other")
        with self.assertRaisesRegex(ValueError, "hash"):
            self.candidate(FakeCommandRunner())

    def test_unreviewed_version_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "reviewed"):
            generate_ci_cost_candidate(self.snapshot, version="latest", command_runner=FakeCommandRunner())

    def test_coordinator_skips_ineligible_and_calls_only_prepared(self):
        project = self.root / "project"
        output = project / "evaluation/results/test-id"
        output.mkdir(parents=True)
        # The coordinator accepts manifests only within its own frozen evaluation.
        prepared_dir = output / "repositories/demo"
        prepared_dir.mkdir(parents=True)
        (prepared_dir / "manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        dataset = project / "evaluation/evaluation_repositories_4000.csv"
        dataset.parent.mkdir(parents=True, exist_ok=True)
        with dataset.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["repo_id", "split"])
            w.writeheader()
            w.writerows([{"repo_id": "demo/ci", "split": "evaluation"},
                         {"repo_id": "demo/bad", "split": "evaluation"}])
        cfg = {"evaluation_id": "test-id", "dataset": "evaluation/evaluation_repositories_4000.csv",
               "repository_limit": 2, "repository_start_at": 1, "ci_cost": {"version": "1.0.0"}}
        (output / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        (output / "preparation_summary.json").write_text(json.dumps({
            "dataset_sha256": sha256(dataset.read_bytes()).hexdigest()}), encoding="utf-8")
        with (output / "screening.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["repo_id", "status", "manifest_path"])
            w.writeheader()
            w.writerows([{"repo_id": "demo/ci", "status": "prepared",
                         "manifest_path": str(prepared_dir / "manifest.json")},
                        {"repo_id": "demo/bad", "status": "ineligible", "manifest_path": ""}])
        called = []
        def fake_optimizer(dir, *, version):
            called.append((dir, version))
            return {"decision": "APPLY", "status": "GENERATED_NOT_VALIDATED"}
        result = generate_b(cfg, project_root=project, optimizer=fake_optimizer)
        self.assertEqual(result["counts"], {"APPLY": 1, "SKIPPED": 1})
        self.assertEqual(called, [(prepared_dir, "1.0.0")])
        self.assertEqual(result["github_actions_runs"], 0)


if __name__ == "__main__":
    unittest.main()
