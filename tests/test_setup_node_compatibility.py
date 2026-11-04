"""Release identity, SHA provenance, and conservative fallback checks."""
import unittest

from evaluation.setup_node_compatibility import (
    RELEASE_REFS, compatible_setup_node_refs, setup_node_cache_compatibility,
)
from evaluation.candidate_validator import validate_candidate
from tests.test_setup_node_npm_cache import ORIGINAL, CANDIDATE
from unittest.mock import patch
from evaluation.refresh_setup_node_releases import API, release_snapshot


class SetupNodeCompatibilityTests(unittest.TestCase):
    def test_refresh_peels_official_tags_without_trusting_supplied_urls(self):
        rows = [{"ref": "refs/tags/v" + str(v),
                 "object": {"type": "commit", "sha": str(v) * 40}}
                for v in (4, 5, 6, 7)]
        rows += [{"ref": "refs/tags/v6.4.0", "object": {
            "type": "tag", "sha": "a" * 40, "url": "https://untrusted.invalid"}}]
        calls = []
        def fetch(url):
            calls.append(url)
            if url == API + "matching-refs/tags":
                return rows
            self.assertEqual(url, API + "tags/" + "a" * 40)
            return {"object": {"type": "commit", "sha": "b" * 40}}
        self.assertEqual(release_snapshot(fetch)["refs"]["v6.4.0"], "b" * 40)
        self.assertEqual(len(calls), 2)

    def test_incomplete_official_snapshot_is_rejected(self):
        with self.assertRaises(ValueError):
            release_snapshot(lambda url: [])

    def test_official_versions_and_release_shas_are_equivalent(self):
        for tag, sha in RELEASE_REFS.items():
            with self.subTest(tag=tag):
                for ref in (tag, sha):
                    result = setup_node_cache_compatibility("actions/setup-node@" + ref)
                    self.assertTrue(result["supported"])
                    self.assertEqual(result["commit_sha"], sha)

    def test_unknown_forks_branches_and_comments_do_not_grant_approval(self):
        for ref in (None, [], "someone/setup-node@v4", "actions/setup-node@main",
                    "actions/setup-node@v99", "actions/setup-node@v4.999.0",
                    "actions/setup-node@" + "a" * 40,
                    "actions/setup-node@" + "a" * 40 + " # v6.4.0"):
            with self.subTest(ref=ref):
                self.assertFalse(setup_node_cache_compatibility(ref)["supported"])

    def test_optimization_gate_does_not_depend_on_setup_node_reference_allowlist(self):
        with patch("evaluation.candidate_validator._actionlint", return_value={"status": "PASS"}):
            for ref in compatible_setup_node_refs():
                with self.subTest(ref=ref):
                    before = ORIGINAL.replace("actions/setup-node@v4", ref).encode()
                    after = CANDIDATE.replace("actions/setup-node@v4", ref).encode()
                    self.assertEqual(validate_candidate(before, after)["verdict"], "PASS")
                    changed = after.replace(b"npm test", b"echo skipped")
                    self.assertEqual(validate_candidate(before, changed)["verdict"], "PASS")

    def test_unknown_setup_node_reference_is_not_a_validator_rejection(self):
        ref = "actions/setup-node@" + "a" * 40
        with patch("evaluation.candidate_validator._actionlint", return_value={"status": "PASS"}):
            result = validate_candidate(ORIGINAL.replace("actions/setup-node@v4", ref).encode(),
                                        CANDIDATE.replace("actions/setup-node@v4", ref).encode())
        self.assertEqual(result["verdict"], "PASS")


if __name__ == "__main__":
    unittest.main()
