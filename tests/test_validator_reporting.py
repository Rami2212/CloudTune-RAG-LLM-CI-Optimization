"""Regression tests for honest ci-cost reporting and precise admission diagnostics."""
from __future__ import annotations

import json
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from evaluation.candidate_validator import validate_candidate
from evaluation.optimizers.ci_cost import _recommendation_audit, generate_ci_cost_candidate
from evaluation.third_party.ci_cost.source_fixes import FIX_REVISION

BASE = b"""name: CI
on: workflow_dispatch
jobs:
  build:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        node: [20, 22]
    steps:
      - uses: actions/checkout@v4
      - name: Setup Node
        uses: actions/setup-node@v4
        with:
          node-version: 22
      - name: Install
        run: npm install
      - name: Test
        run: npm test
"""
UNAPPROVED_CACHE = b"""      - name: Cache npm dependencies
        uses: actions/cache@v4
        with:
          path: ~/.npm
          key: ${{ runner.os }}-npm-${{ hashFiles('package-lock.json') }}
          restore-keys: |
            ${{ runner.os }}-npm-
"""
HEADER = b"""# Optimized by ci-cost (https://github.com/mariotavarez/ci-cost)
# Applied 4 optimizations:
# - [HIGH] Add npm dependency cache to "build" job
# - [MEDIUM] Add concurrency group to "ci.yml"
# - [MEDIUM] Use "npm ci" instead of "npm install" in "build"
# - [LOW] Explicitly set fail-fast for large matrix job "build" (12 combinations)
# Estimated savings: ~9 min/run
#
"""


def with_cache(original: bytes = BASE) -> bytes:
    return original.replace(b"      - name: Install\n", UNAPPROVED_CACHE + b"      - name: Install\n")


class ValidatorReportingTests(unittest.TestCase):
    def _validate(self, candidate: bytes) -> dict:
        with patch("evaluation.candidate_validator._actionlint", return_value={"status": "PASS", "reason": ""}):
            return validate_candidate(BASE, candidate)

    def test_added_cache_step_passes_general_candidate_gate(self):
        result = self._validate(with_cache())
        self.assertEqual(result["verdict"], "PASS")

    def test_removing_step_is_not_rejected_by_pattern_allowlist(self):
        result = self._validate(BASE.replace(b"      - name: Test\n        run: npm test\n", b""))
        self.assertEqual(result["verdict"], "PASS")

    def test_modifying_step_is_not_rejected_by_pattern_allowlist(self):
        result = self._validate(BASE.replace(b"run: npm test", b"run: echo skipped"))
        self.assertEqual(result["verdict"], "PASS")

    def test_header_claims_are_not_mistaken_for_applied_changes(self):
        changed = HEADER + with_cache(BASE)
        changed = changed.replace(b"on: workflow_dispatch\n", b"on: workflow_dispatch\nconcurrency:\n  group: demo\n  cancel-in-progress: true\n")
        report = _recommendation_audit(BASE, changed)
        self.assertEqual([c["status"] for c in report["recommendation_checks"]],
                         ["OBSERVED", "OBSERVED", "NOT_OBSERVED", "NOT_OBSERVED"])
        self.assertEqual(len(report["unobserved_reported_recommendations"]), 2)
        self.assertEqual(report["reported_estimated_savings"], "~9 min/run")
        self.assertFalse(report["reported_estimate_is_measured"])

    def test_actual_install_and_fail_fast_changes_are_detected(self):
        changed = BASE.replace(b"run: npm install", b"run: npm ci")
        changed = changed.replace(b"    strategy:\n", b"    strategy:\n      fail-fast: true\n")
        claims = (b"# - [HIGH] Use 'npm ci' instead of 'npm install'\n"
                  b"# - [LOW] Explicitly set fail-fast for matrix\n")
        report = _recommendation_audit(BASE, claims + changed)
        self.assertEqual([x["status"] for x in report["recommendation_checks"]],
                         ["OBSERVED", "OBSERVED"])

    def test_changing_existing_cache_is_not_counted_as_addition(self):
        cached = with_cache(BASE)
        changed = cached.replace(b"runner.os }}-npm", b"runner.os }}-other")
        claim = b"# - [HIGH] Add npm dependency cache\n"
        report = _recommendation_audit(cached, claim + changed)
        self.assertEqual(report["recommendation_checks"][0]["status"], "NOT_OBSERVED")

    def test_disabling_fail_fast_is_not_claimed_as_enabling_it(self):
        old = BASE.replace(b"    strategy:\n", b"    strategy:\n      fail-fast: true\n")
        new = old.replace(b"fail-fast: true", b"fail-fast: false")
        report = _recommendation_audit(old, b"# - [LOW] Explicitly set fail-fast\n" + new)
        self.assertEqual(report["recommendation_checks"][0]["status"], "NOT_OBSERVED")

    def test_unknown_recommendation_is_unverified_not_assumed_false(self):
        report = _recommendation_audit(BASE, b"# - [LOW] Tune custom compiler flags\n" + BASE)
        self.assertEqual(report["recommendation_checks"][0]["status"], "UNVERIFIED")

    def test_generator_archives_audit_without_changing_optimizer_output(self):
        candidate = HEADER + with_cache(BASE)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "snapshot"
            source = snapshot / "source/original.yml"
            source.parent.mkdir(parents=True)
            source.write_bytes(BASE)
            (snapshot / "manifest.json").write_text(json.dumps({
                "source_commit_sha": "a" * 40,
                "workflow_path": ".github/workflows/ci.yml",
                "workflow_sha256": sha256(BASE).hexdigest(),
                "status": "prepared",
            }), encoding="utf-8")
            tool = root / "tool"
            (tool / "dist").mkdir(parents=True)

            def runner(command, **options):
                if command[-1] == "--version":
                    return CompletedProcess(command, 0, "ci-cost v1.0.0", "")
                workflow_dir = Path(command[-1].removeprefix("--dir="))
                dest = workflow_dir / "optimized/ci.yml"
                dest.parent.mkdir()
                dest.write_bytes(candidate)
                return CompletedProcess(command, 0, "Found 1 workflow", "")

            record = {"upstream_lock_sha256": "a" * 64, "file_hashes": {}}
            with patch("evaluation.optimizers.ci_cost.verify_installation", return_value=record):
                result = generate_ci_cost_candidate(snapshot, tool_dir=tool, command_runner=runner)
            self.assertEqual(result["decision"], "APPLY")
            target = snapshot / "candidates/B" / FIX_REVISION
            self.assertEqual((target / "optimized.yml").read_bytes(), candidate)
            self.assertEqual(json.loads((target / "candidate.json").read_text())["recommendation_audit"],
                             result["recommendation_audit"])
            self.assertEqual(len(result["recommendation_audit"]["unobserved_reported_recommendations"]), 3)


if __name__ == "__main__":
    unittest.main()
