"""Install and verify the transparently source-fixed ci-cost baseline.

Usage: python -m evaluation.third_party.ci_cost.setup

The upstream code is checked out at a fixed commit. Reviewed fixes are applied
in TypeScript and compiled normally; generated workflow YAML is never patched.
This is a PATCHED ci-cost baseline, not the unmodified upstream release.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from hashlib import sha256
from pathlib import Path

from evaluation.repository_preparation import workflow_doc
from evaluation.third_party.ci_cost.source_fixes import (
    FIX_REVISION, REPLACEMENTS, UPSTREAM_COMMIT, corrected_sources, fix_identity,
)

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DIR = Path(os.environ.get("CI_COST_DIR", str(ROOT / ".venv" / "ci-cost")))
REPOSITORY = "https://github.com/mariotavarez/ci-cost.git"
COMPILED_FILES = ("dist/optimizer.js", "dist/checks/misc.js")
MANIFEST_FILE = ".cloudtune-source-fix.json"


def _safe_tool_environment() -> dict[str, str]:
    """Do not pass research-account secrets to third-party Git/npm/build scripts.

    The ci-cost checkout is public. Installation and compilation must not have
    access to GitHub, Supabase, OpenRouter or local npm registry credentials.
    """
    env = {key: value for key, value in os.environ.items()
           if not re.search(r"TOKEN|SECRET|PASSWORD|API_KEY|PRIVATE_KEY|CREDENTIAL|AUTH", key, re.I)
           and key.upper() not in {"NPM_CONFIG_USERCONFIG", "NPM_CONFIG_GLOBALCONFIG"}}
    env["CI"] = "true"
    return env


def isolate_npm_config(environment: dict[str, str], scratch: Path) -> dict[str, str]:
    """Provide two distinct *empty* absolute npmrc files for an isolated process.

    On Windows, os.devnull == 'nul'. Passing it for BOTH npm config roles
    makes current npm reject the subprocess as double-loading one path.
    The caller owns the temporary directory for the whole subprocess lifetime.
    """
    user = scratch / "cloudtune-user.npmrc"
    global_file = scratch / "cloudtune-global.npmrc"
    for path in (user, global_file):
        # Exclusive creation prevents a previous config file being adopted.
        with path.open("x", encoding="utf-8"):
            pass
    result = dict(environment)
    result["NPM_CONFIG_USERCONFIG"] = str(user.resolve())
    result["NPM_CONFIG_GLOBALCONFIG"] = str(global_file.resolve())
    return result


def _run(command: list[str], *, cwd: Path | None = None) -> str:
    with tempfile.TemporaryDirectory(prefix="cloudtune-ci-cost-npm-") as scratch:
        environment = isolate_npm_config(_safe_tool_environment(), Path(scratch))
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                                check=False, env=environment)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(command)}\n{result.stderr[-1000:]}")
    return result.stdout.strip()


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def verify_installation(tool_dir: Path = DEFAULT_DIR) -> dict:
    """Fail closed on wrong revisions, altered sources, or compiled outputs."""
    root = tool_dir.resolve()
    path = root / MANIFEST_FILE
    if not path.is_file():
        raise ValueError("ci-cost source-fix installation manifest is missing; run setup first")
    record = json.loads(path.read_text(encoding="utf-8"))
    if (record.get("upstream_commit") != UPSTREAM_COMMIT or
            record.get("fix_revision") != FIX_REVISION or
            record.get("fix_sha256") != fix_identity()):
        raise ValueError("ci-cost source-fix identity does not match this evaluation")
    if _run(["git", "rev-parse", "HEAD"], cwd=root) != UPSTREAM_COMMIT:
        raise ValueError("ci-cost checkout is not at the pinned upstream commit")
    changed = set(_run(["git", "diff", "--name-only"], cwd=root).splitlines())
    expected = set(REPLACEMENTS) | set(COMPILED_FILES)
    if changed != expected:
        raise ValueError(f"ci-cost tracked modifications are not the reviewed source fix: {sorted(changed)}")
    files = record.get("file_hashes", {})
    if set(files) != expected:
        raise ValueError("ci-cost source-fix manifest has unexpected files")
    for name, digest in files.items():
        if not (root / name).is_file() or _sha(root / name) != digest:
            raise ValueError(f"ci-cost corrected source or compiled output was changed: {name}")
    if not (root / "node_modules" / "js-yaml" / "package.json").is_file():
        raise ValueError("ci-cost npm dependencies missing; run setup again")
    return record


def _smoke_test(root: Path) -> None:
    """Exercise the compiled CLI on real YAML, including upstream failure case.

    The Gradle fixture mirrors the checkout layout of fabrikt-io/fabrikt.
    The npm fixture verifies real source-level cache insertion and parsing.
    An invalid optimizer output must fail installation before research starts.
    """
    samples = {
        "fabrikt": """name: CI
on:
  push:
  pull_request:
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
""",
        "npm": """name: CI
on:
  push:
  pull_request:
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install
        run: npm ci
      - name: Test
        run: npm test
""",
    }
    for name, original in samples.items():
        with tempfile.TemporaryDirectory(prefix="cloudtune-ci-cost-smoke-") as tmp:
            folder = Path(tmp) / ".github" / "workflows"
            folder.mkdir(parents=True)
            source = folder / "ci.yml"
            source.write_text(original, encoding="utf-8")
            result = subprocess.run(
                ["node", str(root / "dist/index.js"), "--fix", "--dir=" + str(folder)],
                capture_output=True, text=True, timeout=60, check=False,
                cwd=tmp,
                env=isolate_npm_config(_safe_tool_environment(), Path(tmp)),
            )
            if result.returncode not in (0, 1) or "Error generating optimized files:" in result.stderr:
                raise RuntimeError(f"ci-cost smoke case {name} failed: {result.stderr[-500:]}")
            generated = folder / "optimized" / "ci.yml"
            if not generated.is_file():
                if name == "npm":
                    raise RuntimeError("ci-cost did not generate the npm cache smoke candidate")
                continue
            parsed = workflow_doc(generated.read_bytes())
            if not isinstance(parsed.get("jobs"), dict):
                raise RuntimeError(f"ci-cost smoke case {name} lost the jobs mapping")
            if name == "npm" and "Cache node_modules" not in generated.read_text(encoding="utf-8"):
                raise RuntimeError("ci-cost smoke candidate failed to insert its intended cache step")
            # The upstream broken shallow-clone transformation inserted a new
            # `with: fetch-depth: 1` under checkout despite checkout v4 default.
            if "fetch-depth: 1" in generated.read_text(encoding="utf-8"):
                raise RuntimeError("ci-cost is still applying the upstream shallow-clone defect")


def install(tool_dir: Path = DEFAULT_DIR) -> dict:
    """Perform a reproducible source-based fix, compiling with pinned lockfile."""
    root = tool_dir.resolve()
    if (root / MANIFEST_FILE).exists():
        return verify_installation(root)
    if not root.exists():
        root.parent.mkdir(parents=True, exist_ok=True)
        _run(["git", "clone", REPOSITORY, str(root)])
    if not (root / ".git").exists():
        raise ValueError("ci-cost tool directory exists but is not a Git checkout")
    _run(["git", "checkout", "--detach", UPSTREAM_COMMIT], cwd=root)
    if _run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=root):
        raise ValueError("ci-cost contains tracked modifications; use a clean pinned checkout")
    replacements = corrected_sources(root)  # Compute all replacements before writing.
    for name, contents in replacements.items():
        (root / name).write_bytes(contents)
    # Build from the fixed TypeScript source, not a patched CLI output.
    npm = shutil.which("npm")
    if npm is None:
        raise RuntimeError("npm executable not found; Node.js 20+ and npm are required")
    _run([npm, "ci", "--ignore-scripts"], cwd=root)
    _run([npm, "run", "build"], cwd=root)
    version = _run(["node", "dist/index.js", "--version"], cwd=root)
    if version != "ci-cost v1.0.0":
        raise RuntimeError(f"Unexpected ci-cost CLI version: {version}")
    _smoke_test(root)
    file_names = set(REPLACEMENTS) | set(COMPILED_FILES)
    changed = set(_run(["git", "diff", "--name-only"], cwd=root).splitlines())
    if changed != file_names:
        raise RuntimeError(f"Compiled source modifications differ from expected: {sorted(changed)}")
    manifest = {
        "tool": "ci-cost", "upstream_version": "1.0.0",
        "upstream_commit": UPSTREAM_COMMIT,
        "source": REPOSITORY,
        "fix_revision": FIX_REVISION,
        "fix_sha256": fix_identity(),
        "upstream_lock_sha256": _sha(root / "package-lock.json"),
        "file_hashes": {name: _sha(root / name) for name in sorted(file_names)},
        "description": "Corrected TypeScript source and rebuilt CLI; not unmodified upstream",
    }
    (root / MANIFEST_FILE).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return verify_installation(root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="Only verify an existing installation")
    parser.add_argument("--tool-dir", type=Path, default=DEFAULT_DIR, help="Ephemeral or user-provided install location")
    args = parser.parse_args()
    try:
        record = verify_installation(args.tool_dir) if args.verify else install(args.tool_dir)
        print(json.dumps(record, indent=2))
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(f"ci-cost setup error: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
