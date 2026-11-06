"""Regression tests for generic candidate admission.

No forks, GitHub requests or real target builds are used. Older evaluation
verdicts remain immutable; new trials use the versioned safety policy.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evaluation.candidate_validator import (
    POLICY_REVISION, validate_and_archive, validate_candidate,
)

ORIGINAL = """name: CI
on:
  push:
    branches: [master]
  pull_request:
    branches: [master]
jobs:
  build:
    runs-on: ${{ matrix.os }}
    strategy:
      matrix:
        os: [ubuntu-latest, windows-latest]
        node-version: [20.x, 22.x]
    steps:
      - uses: actions/checkout@v4
      - name: Use Node.js ${{ matrix.node-version }}
        uses: actions/setup-node@v4
        with:
          node-version: ${{ matrix.node-version }}
      - run: npm install
      - run: npm test
"""

CANDIDATE = ORIGINAL.replace(
    "          node-version: ${{ matrix.node-version }}\n",
    "          node-version: ${{ matrix.node-version }}\n          cache: 'npm'\n",
)


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class SetupNodeNpmCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory(prefix="cloudtune-setup-node-validation-")
        self.addCleanup(temp.cleanup)
        self.snapshot = Path(temp.name)
        self.original = ORIGINAL.encode("utf-8")
        self.candidate = CANDIDATE.encode("utf-8")
        self.lint = patch("evaluation.candidate_validator._actionlint",
                          return_value={"status": "PASS", "reason": ""})
        self.lint.start()
        self.addCleanup(self.lint.stop)

    def make_snapshot(self, *, lockfile: str | None = "package-lock.json",
                      tamper: bool = False) -> None:
        manifest = {"source_commit_sha": "a" * 40,
                    "workflow_path": ".github/workflows/ci.yml",
                    "workflow_sha256": _hash(self.original)}
        (self.snapshot / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        entries = []
        if lockfile is not None:
            content = b'{"lockfileVersion":3,"name":"fixture"}\n'
            dest = self.snapshot / "source/files" / lockfile
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content + (b"corrupt" if tamper else b""))
            entries.append({"path": lockfile, "sha256": _hash(content)})
        path = self.snapshot / "source/files_manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"archived": entries}), encoding="utf-8")
        path = self.snapshot / "candidates/C/candidate.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"source_sha": "a" * 40,
                                    "before_sha256": _hash(self.original),
                                    "after_sha256": _hash(self.candidate)}), encoding="utf-8")

    def verdict(self, candidate: str) -> dict:
        return validate_candidate(self.original, candidate.encode("utf-8"))

    def test_exact_additive_setup_node_npm_cache_passes_syntax_gate(self):
        self.assertNotEqual(self.original, self.candidate)
        verdict = self.verdict(CANDIDATE)
        self.assertEqual(verdict["verdict"], "PASS")
        self.assertEqual(verdict["reasons"], [])
        # Policy provenance is asserted against the archived revision below.
        # Later policies retain npm caching without retaining its old name.

    def test_frozen_root_lockfile_passes_full_admission(self):
        self.make_snapshot()
        verdict = validate_and_archive(self.snapshot, "C", self.original,
                                       self.candidate, decision="APPLY",
                                       generation={})
        self.assertEqual(verdict["verdict"], "PASS")
        saved = json.loads((self.snapshot / "validation/C/validation.json").read_text())
        self.assertEqual(saved["policy_revision"], POLICY_REVISION)
        self.assertEqual(saved["evidence"]["candidate_policy"], POLICY_REVISION)
        # Reusing the same immutable decision returns the same verdict.
        self.assertEqual(validate_and_archive(self.snapshot, "C", self.original,
                                             self.candidate, decision="APPLY",
                                             generation={}), verdict)

    def test_reviewed_sha_passes_full_admission_with_frozen_lockfile(self):
        ref = "actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1"
        self.original = ORIGINAL.replace("actions/setup-node@v4", ref).encode()
        self.candidate = CANDIDATE.replace("actions/setup-node@v4", ref).encode()
        self.make_snapshot()
        verdict = validate_and_archive(self.snapshot, "C", self.original,
                                       self.candidate, decision="APPLY", generation={})
        self.assertEqual(verdict["verdict"], "PASS")
        self.assertEqual(verdict["reasons"], [])

    def test_major_versions_and_step_edits_are_not_pattern_gated(self):
        for version in ("v5", "v6", "v7", "v4.0.0"):
            for lock in ("package-lock.json", None):
                with self.subTest(version=version, lock=lock), tempfile.TemporaryDirectory() as scratch:
                    self.snapshot = Path(scratch)
                    self.original = ORIGINAL.replace("setup-node@v4", "setup-node@" + version).encode()
                    self.candidate = CANDIDATE.replace("setup-node@v4", "setup-node@" + version).encode()
                    self.make_snapshot(lockfile=lock)
                    result = validate_and_archive(self.snapshot, "C", self.original,
                                                  self.candidate, decision="APPLY", generation={})
                    self.assertEqual(result["verdict"], "PASS")
                    changed = self.candidate.replace(b"npm test", b"echo skipped")
                    self.assertEqual(validate_candidate(self.original, changed)["verdict"], "PASS")

    def test_action_ref_changes_are_not_pattern_gated(self):
        reviewed = "actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1"
        for ref in ("actions/setup-node@" + "a" * 40, "actions/setup-node@v99.0.0"):
            with self.subTest(ref=ref):
                source = ORIGINAL.replace("actions/setup-node@v4", ref).encode()
                candidate = CANDIDATE.replace("actions/setup-node@v4", ref).encode()
                result = validate_candidate(source, candidate)
                self.assertEqual(result["verdict"], "PASS")
        result = self.verdict(CANDIDATE.replace("actions/setup-node@v4", reviewed))
        self.assertEqual(result["verdict"], "PASS")

    def test_missing_root_lockfile_does_not_block_other_optimizations(self):
        for name in (None, "packages/workspace/package-lock.json", "yarn.lock"):
            with self.subTest(file=name):
                # Each case uses a fresh snapshot so archived validation is immutable.
                with tempfile.TemporaryDirectory() as scratch:
                    self.snapshot = Path(scratch)
                    self.make_snapshot(lockfile=name)
                    verdict = validate_and_archive(self.snapshot, "C", self.original,
                                                   self.candidate, decision="APPLY",
                                                   generation={})
                    self.assertEqual(verdict["verdict"], "PASS")

    def test_workflow_step_edits_are_not_pattern_gated(self):
        cases = {
            "removed_test": CANDIDATE.replace("      - run: npm test\n", ""),
            "modified_test": CANDIDATE.replace("npm test", "npm test -- --silent"),
            "action_upgrade": CANDIDATE.replace("actions/setup-node@v4", "actions/setup-node@v6"),
            "node_version": CANDIDATE.replace("          node-version: ${{ matrix.node-version }}",
                                               "          node-version: '24'"),
            "cache_type": CANDIDATE.replace("cache: 'npm'", "cache: 'yarn'"),
            "custom_path": CANDIDATE.replace("cache: 'npm'", "cache: 'npm'\n          cache-dependency-path: 'packages/*/package-lock.json'"),
            "extra_input": CANDIDATE.replace("cache: 'npm'", "cache: 'npm'\n          always-auth: true"),
            "unapproved_concurrency": CANDIDATE.replace("jobs:\n", "concurrency:\n  group: ci\n  cancel-in-progress: true\njobs:\n"),
        }
        for label, text in cases.items():
            with self.subTest(label=label):
                verdict = self.verdict(text)
                self.assertEqual(verdict["verdict"], "PASS", label)

    def test_cache_before_checkout_is_not_a_pattern_gate(self):
        source = ORIGINAL.replace("      - uses: actions/checkout@v4\n", "")
        source = source.replace("      - run: npm install\n",
                                "      - uses: actions/checkout@v4\n      - run: npm install\n")
        self.original = source.encode("utf-8")
        self.candidate = source.replace(
            "          node-version: ${{ matrix.node-version }}\n",
            "          node-version: ${{ matrix.node-version }}\n          cache: 'npm'\n",
        ).encode("utf-8")
        self.make_snapshot()
        verdict = validate_and_archive(self.snapshot, "C", self.original,
                                       self.candidate, decision="APPLY", generation={})
        self.assertEqual(verdict["verdict"], "PASS")

    def test_cache_does_not_require_npm_install_prerequisite(self):
        cases = {
            "no_npm_install": CANDIDATE.replace("npm install", "node --version"),
            "subdirectory_install": CANDIDATE.replace(
                "      - run: npm install\n",
                "      - run: npm install\n        working-directory: packages/app\n",
            ),
        }
        for name, candidate in cases.items():
            with self.subTest(case=name), tempfile.TemporaryDirectory() as scratch:
                # Keep source and candidate identical outside the cache input.
                self.snapshot = Path(scratch)
                self.original = candidate.replace("          cache: 'npm'\n", "").encode()
                self.candidate = candidate.encode()
                self.make_snapshot()
                verdict = validate_and_archive(self.snapshot, "C", self.original,
                                               self.candidate, decision="APPLY",
                                               generation={})
                self.assertEqual(verdict["verdict"], "PASS")

    def test_tampered_dependency_manifest_does_not_gate_general_candidate(self):
        self.make_snapshot(tamper=True)
        verdict = validate_and_archive(self.snapshot, "C", self.original,
                                       self.candidate, decision="APPLY", generation={})
        self.assertEqual(verdict["verdict"], "PASS")

    def test_concurrency_is_not_rejected_by_optimization_allowlist(self):
        changed = ORIGINAL.replace("jobs:\n",
                                   "concurrency:\n  group: ${{ github.ref }}\n  cancel-in-progress: true\njobs:\n")
        verdict = self.verdict(changed)
        self.assertEqual(verdict["verdict"], "PASS")


if __name__ == "__main__":
    unittest.main()
