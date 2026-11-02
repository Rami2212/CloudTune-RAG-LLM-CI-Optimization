"""Offline regression tests for the pinned third-party source corrections.

These tests exercise the actual transformed TypeScript functions where a
TypeScript compiler and Node are present. No GitHub Actions are dispatched.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evaluation.repository_preparation import workflow_doc
from evaluation.candidate_validator import validate_candidate, _cache_evidence
from evaluation.optimizers.ci_cost import generate_ci_cost_candidate
from hashlib import sha256
from evaluation.third_party.ci_cost import setup
from evaluation.third_party.ci_cost.source_fixes import (
    FIX_REVISION, REPLACEMENTS, corrected_sources, fix_identity,
)


def _typescript_compiler_command() -> list[str] | None:
    """Use the compiler installed by ci-cost setup, without a global tsc.

    On Windows, `tsc` commonly resolves to a .cmd shim which subprocess
    cannot reliably launch by bare name. Node can execute its JS entrypoint
    directly on Windows and Linux. Preserve the POSIX global fallback for
    isolated developer/CI environments without the third-party checkout.
    """
    node = shutil.which("node")
    if not node:
        return None
    local_tsc = setup.DEFAULT_DIR / "node_modules" / "typescript" / "bin" / "tsc"
    if local_tsc.is_file():
        return [node, str(local_tsc)]
    if os.name != "nt":
        global_tsc = shutil.which("tsc")
        if global_tsc:
            return [global_tsc]
    return None


class SourceFixTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name, edits in REPLACEMENTS.items():
            source = self.root / name
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("\n\n".join(old for old, _ in edits) + "\n", encoding="utf-8")

    def test_exact_source_transformations_and_identity(self):
        fixed = corrected_sources(self.root)
        self.assertEqual(set(fixed), set(REPLACEMENTS))
        for name, edits in REPLACEMENTS.items():
            for old, new in edits:
                self.assertIn(new.encode("utf-8"), fixed[name])
                # The output-validation insertion intentionally retains the
                # original header as a suffix; only the added guard is new.
                if old not in new:
                    self.assertNotIn(old.encode("utf-8"), fixed[name])
        self.assertEqual(len(fix_identity()), 64)
        self.assertEqual(FIX_REVISION, "cloudtune-ci-cost-npm-download-v4-compatibility")

    def test_unknown_upstream_source_fails_closed(self):
        (self.root / "src/optimizer.ts").write_text("different version", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Unrecognized pinned upstream"):
            corrected_sources(self.root)

    def test_source_unchanged_if_other_file_cannot_be_patched(self):
        before = (self.root / "src/optimizer.ts").read_bytes()
        (self.root / "src/checks/misc.ts").write_text("changed", encoding="utf-8")
        with self.assertRaises(ValueError):
            corrected_sources(self.root)
        self.assertEqual((self.root / "src/optimizer.ts").read_bytes(), before)

    def test_verifier_rejects_uninstalled_tool(self):
        with self.assertRaisesRegex(ValueError, "manifest is missing"):
            setup.verify_installation(self.root)

    def test_real_cli_download_cache_preserves_other_jobs_and_commands(self):
        if not (setup.DEFAULT_DIR / setup.MANIFEST_FILE).is_file():
            self.skipTest("Requires current ci-cost installation")
        original = b"""name: CI
on: [push, pull_request]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v6.4.0
        with:
          node-version: 22
      - run: npm ci
      - run: npm run lint
  test:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v5
        with:
          node-version: 24
          cache: npm
      - run: npm ci
      - run: npm test
"""
        snapshot = self.root / "snapshot"
        (snapshot / "source").mkdir(parents=True)
        (snapshot / "source/original.yml").write_bytes(original)
        (snapshot / "manifest.json").write_text(json.dumps({
            "workflow_path": ".github/workflows/ci.yml", "status": "prepared",
            "source_commit_sha": "a" * 40,
            "workflow_sha256": sha256(original).hexdigest(),
        }))
        result = generate_ci_cost_candidate(snapshot, tool_dir=setup.DEFAULT_DIR)
        self.assertEqual(result["decision"], "APPLY", result.get("error"))
        candidate = (snapshot / result["candidate_relative_dir"] / "optimized.yml").read_bytes()
        expected = workflow_doc(original)
        expected["jobs"]["lint"]["steps"][1]["with"]["cache"] = "npm"
        self.assertEqual(workflow_doc(candidate), expected)
        with patch("evaluation.candidate_validator._actionlint", return_value={"status": "PASS"}):
            self.assertEqual(validate_candidate(original, candidate)["verdict"], "PASS")
        self.assertEqual(_cache_evidence(original, candidate, {"package-lock.json"}),
                         (["package-lock.json"], []))
        self.assertIn("SETUP_NODE_NPM_ROOT_LOCKFILE_NOT_FROZEN:lint",
                      _cache_evidence(original, candidate, set())[1])

    def test_compiled_source_functions_generate_valid_yaml(self):
        """Compile the same TS functions the real ci-cost build receives."""
        compiler = _typescript_compiler_command()
        if compiler is None:
            self.skipTest("Requires Node.js and TypeScript installed by ci-cost setup")
        fixed = corrected_sources(self.root)
        source = fixed["src/optimizer.ts"].decode("utf-8")
        # The file assembled from function-level fixtures also contains the
        # optimizer output guard. Test executable transformation functions.
        source = source.split("    // Fail before writing", 1)[0]
        source += "\nexport {injectCacheStep, addShallowClone, enableFailFast};\n"
        ts = self.root / "functions.ts"
        ts.write_text(source, encoding="utf-8")
        compile_result = subprocess.run(
            [*compiler, "--target", "ES2022", "--module", "commonjs",
             "--skipLibCheck", "--outDir", str(self.root), str(ts)],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
        script = r'''
const {injectCacheStep, addShallowClone, enableFailFast} = require(process.argv[1]);
const original = `name: CI
on:
  push:
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4
    - name: Install
      run: npm ci
`;
const cache = `      - name: Cache node_modules
        uses: actions/cache@v4
        with:
          path: node_modules
          key: test-key`;
const gradle = `name: CI
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-java@v4
      with:
        java-version: '17'
        distribution: 'temurin'
    - name: Build Project
      run: ./gradlew clean build
`;
const shallow = `jobs:
  build:
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
`;
console.log(JSON.stringify({
  gradle: addShallowClone(gradle),
  cache: injectCacheStep(original, 'npm', cache),
  unnamed: injectCacheStep(original.replace('- name: Install\n      run: npm ci', '- run: npm ci'), 'npm', cache),
  crlf: injectCacheStep(original.replace('- name: Install\n      run: npm ci', '- run: npm ci').replace(/\n/g, '\r\n'), 'npm', cache),
  shallow: addShallowClone(shallow),
  failfast: enableFailFast('fail-fast: false')
}));
'''
        result = subprocess.run(["node", "-e", script, str(self.root / "functions.js")],
                                text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["gradle"],
                         "name: CI\non: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n    - uses: actions/checkout@v4\n    - uses: actions/setup-java@v4\n      with:\n        java-version: '17'\n        distribution: 'temurin'\n    - name: Build Project\n      run: ./gradlew clean build\n")
        self.assertIn("Cache node_modules", data["cache"])
        for key in ("unnamed", "crlf"):
            steps = workflow_doc(data[key].encode())["jobs"]["build"]["steps"]
            self.assertEqual(steps[-1], {"run": "npm ci"})
            self.assertEqual(steps[-2]["uses"], "actions/cache@v4")
        self.assertNotIn("\n", data["crlf"].replace("\r\n", ""))
        self.assertEqual(len(workflow_doc(data["cache"].encode())["jobs"]), 1)
        self.assertIn("fetch-depth: 1", data["shallow"])
        self.assertNotIn("fetch-depth: 0", data["shallow"])
        self.assertEqual(data["failfast"], "fail-fast: true")


if __name__ == "__main__":
    unittest.main()
