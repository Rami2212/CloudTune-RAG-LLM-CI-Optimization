"""Focused checks for pattern candidate signals and family deduplication."""
import unittest

import select_pattern_repos as selector


class PatternSelectorTests(unittest.TestCase):
    def test_gradle_build_file_is_not_mislabeled_bazel(self):
        self.assertFalse(selector.bazel_manifest(["build.gradle", "app/build.gradle.kts"]))
        self.assertTrue(selector.bazel_manifest(["bazel/BUILD.bazel"]))
        self.assertTrue(selector.bazel_manifest(["WORKSPACE.bazel"]))

    def test_event_list_and_mapping_triggers_are_recognized(self):
        self.assertTrue(selector.has_unfiltered_push_or_pr({"triggers": ["push", "pull_request"]}))
        self.assertTrue(selector.has_schedule({"triggers": ["schedule", "push"]}))
        self.assertTrue(selector.has_unfiltered_push_or_pr({"triggers": {"push": {"branches": ["main"]}}}))

    def test_selector_keeps_one_repository_per_upstream_family(self):
        pattern = {"pattern_id": "P-LIT-GHA-CACHE", "title": "Cache"}
        def repo(name, is_fork):
            return {"repo_id": name, "family_id": "origin/project", "fork": is_fork,
                    "eligibility": "REVIEW_REQUIRED", "manifest_paths": ["package.json"],
                    "workflows": [{"path": ".github/workflows/ci.yml", "has_build_test_lint_hint": True}]}
        rows = selector.choose_rows([pattern], [repo("fork-account/project", True), repo("origin/project", False)], 5)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["repo_id"], "origin/project")
        self.assertIs(rows[0]["source_is_fork"], False)


if __name__ == "__main__":
    unittest.main()
