"""Offline candidate admission tests; never creates forks or calls GitHub APIs."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evaluation.candidate_validator import POLICY_REVISION, validate_and_archive


BASE = (b"name: CI\non:\n  workflow_dispatch:\njobs:\n  test:\n"
        b"    runs-on: ubuntu-latest\n    steps:\n"
        b"      - uses: actions/checkout@v4\n"
        b"      - uses: actions/setup-node@v6\n        with:\n          node-version: 20.x\n"
        b"      - run: npm ci\n")
CANDIDATE = BASE.replace(b"          node-version: 20.x\n",
                         b"          node-version: 20.x\n          cache: npm\n")


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class CandidateAdmissionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "source/files").mkdir(parents=True)
        self.lock = b'{"lockfileVersion":3}'
        (self.root / "source/files/package-lock.json").write_bytes(self.lock)
        (self.root / "source/files_manifest.json").write_text(json.dumps({
            "archived": [{"path": "package-lock.json", "sha256": digest(self.lock)}],
            "omitted": []}))
        (self.root / "manifest.json").write_text(json.dumps({
            "source_commit_sha": "a" * 40, "workflow_path": ".github/workflows/ci.yml",
            "workflow_sha256": digest(BASE)}))
        self.generation = {"candidate_relative_dir": "candidates/B/revision"}
        self.write_provenance("B", CANDIDATE)
        self.write_provenance("C", CANDIDATE)

    def write_provenance(self, arm: str, candidate: bytes, *, before: bytes = BASE):
        p = self.root / ("candidates/B/revision" if arm == "B" else "candidates/C")
        p.mkdir(parents=True, exist_ok=True)
        (p / "candidate.json").write_text(json.dumps({
            "source_commit_sha" if arm == "B" else "source_sha": "a" * 40,
            "before_sha256": digest(before), "after_sha256": digest(candidate)}))

    def evaluate(self, arm="B", *, candidate=CANDIDATE, original=BASE,
                 decision="APPLY", actionlint_status="PASS"):
        with patch("evaluation.candidate_validator._actionlint", return_value={
                "status": actionlint_status, "reason": "test actionlint"}):
            return validate_and_archive(self.root, arm, original, candidate,
                                        decision=decision, generation=self.generation)

    def test_general_candidate_passes_for_B_and_C(self):
        for arm in ("B", "C"):
            with self.subTest(arm=arm):
                result = self.evaluate(arm)
                self.assertEqual(result["verdict"], "PASS")
                archived = json.loads((self.root / "validation" / arm / "validation.json").read_text())
                self.assertEqual(archived["policy_revision"], POLICY_REVISION)
                self.assertEqual(archived["evidence"]["candidate_policy"], POLICY_REVISION)
                self.assertEqual(archived["before_sha256"], digest(BASE))
                self.assertEqual(archived["after_sha256"], digest(CANDIDATE))
                self.assertEqual(self.evaluate(arm), result)

    def test_missing_pinned_lockfile_does_not_block_general_candidate(self):
        (self.root / "source/files_manifest.json").write_text(json.dumps({
            "archived": [], "omitted": [{"path": "package-lock.json"}]}))
        result = self.evaluate()
        self.assertEqual(result["verdict"], "PASS")

    def test_dependency_manifest_is_not_a_generic_admission_requirement(self):
        (self.root / "source/files/package-lock.json").write_text("tampered")
        result = self.evaluate()
        self.assertEqual(result["verdict"], "PASS")

    def test_cache_before_checkout_is_not_a_special_case(self):
        original = BASE.replace(b"      - uses: actions/checkout@v4\n      - uses: actions/setup-node@v6\n",
                                b"      - uses: actions/setup-node@v6\n")
        original = original.replace(b"          node-version: 20.x\n      - run: npm ci\n",
                                    b"          node-version: 20.x\n      - uses: actions/checkout@v4\n      - run: npm ci\n")
        bad = original.replace(b"          node-version: 20.x\n",
                               b"          node-version: 20.x\n          cache: npm\n")
        self.root.joinpath("manifest.json").write_text(json.dumps({
            "source_commit_sha": "a" * 40, "workflow_path": ".github/workflows/ci.yml",
            "workflow_sha256": digest(original)}))
        self.write_provenance("B", bad, before=original)
        result = self.evaluate(candidate=bad, original=original)
        self.assertEqual(result["verdict"], "PASS")

    def test_generic_cache_step_is_allowed_by_shared_policy(self):
        bad = BASE.replace(b"      - run: npm ci\n",
                           b"      - uses: actions/cache@v4\n        with:\n          path: ~/.npm\n          key: arbitrary\n      - run: npm ci\n")
        self.write_provenance("B", bad)
        result = self.evaluate(candidate=bad)
        self.assertEqual(result["verdict"], "PASS")

    def test_missing_actionlint_never_passes(self):
        result = self.evaluate(actionlint_status="INCONCLUSIVE")
        self.assertEqual(result["verdict"], "INCONCLUSIVE")
        self.assertIn("ACTIONLINT_UNAVAILABLE", result["reasons"])

    def test_generator_source_provenance_mismatch_fails(self):
        self.write_provenance("B", CANDIDATE, before=b"wrong")
        result = self.evaluate()
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(result["reasons"], ["GENERATOR_PROVENANCE_MISMATCH"])

    def test_invalid_yaml_and_duplicate_keys_fail(self):
        for bad in (b"jobs: [invalid", CANDIDATE + b"name: Duplicate\n"):
            with self.subTest(bad=bad[:20]):
                self.write_provenance("B", bad)
                result = self.evaluate(candidate=bad)
                self.assertEqual(result["verdict"], "FAIL")
                (self.root / "validation/B/validation.json").unlink()

    def test_job_condition_change_is_not_rejected_by_pattern_allowlist(self):
        bad = CANDIDATE.replace(b"    runs-on: ubuntu-latest\n",
                                b"    runs-on: ubuntu-latest\n    if: always()\n")
        self.write_provenance("B", bad)
        result = self.evaluate(candidate=bad)
        self.assertEqual(result["verdict"], "PASS")

    def test_trigger_change_is_not_rejected_by_pattern_allowlist(self):
        original = BASE.replace(b"workflow_dispatch:", b"pull_request_target:")
        self.root.joinpath("manifest.json").write_text(json.dumps({
            "source_commit_sha": "a" * 40, "workflow_path": ".github/workflows/ci.yml",
            "workflow_sha256": digest(original)}))
        candidate = original.replace(b"          node-version: 20.x\n",
                                     b"          node-version: 20.x\n          cache: npm\n")
        self.write_provenance("B", candidate, before=original)
        result = self.evaluate(candidate=candidate, original=original)
        self.assertEqual(result["verdict"], "PASS")

    def test_no_change_and_error_have_durable_verdicts(self):
        for arm, decision, verdict in (("B", "NO_CHANGE", "NO_CHANGE"),
                                       ("C", "ERROR", "FAIL")):
            with self.subTest(arm=arm):
                result = self.evaluate(arm, candidate=None, decision=decision)
                self.assertEqual(result["verdict"], verdict)
                self.assertTrue((self.root / "validation" / arm / "validation.json").is_file())

    def test_archived_validation_refuses_changed_candidate(self):
        self.assertEqual(self.evaluate()["verdict"], "PASS")
        changed = CANDIDATE.replace(b"npm ci", b"npm test")
        self.write_provenance("B", changed)
        with self.assertRaisesRegex(ValueError, "identity changed"):
            self.evaluate(candidate=changed)

    def test_manifest_checksum_mismatch_fails_before_validation(self):
        manifest = json.loads((self.root / "manifest.json").read_text())
        manifest["workflow_sha256"] = "0" * 64
        (self.root / "manifest.json").write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "pinned original"):
            self.evaluate()

    def test_other_cache_types_are_not_rejected_by_pattern_allowlist(self):
        bad = CANDIDATE.replace(b"cache: npm", b"cache: node_modules")
        self.write_provenance("B", bad)
        result = self.evaluate(candidate=bad)
        self.assertEqual(result["verdict"], "PASS")


if __name__ == "__main__":
    unittest.main()
