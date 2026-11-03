"""Prepare the frozen four-member evaluation study, with an optional safe reset.

Default use generates and verifies all four deterministic 1,000-row assignment
CSVs plus their manifest without touching recorded trial state.

A fresh reset is an explicit, irreversible choice. It is never performed by
ordinary setup or by batch resume; live GitHub Actions and retained research
forks must be checked separately before confirming a reset.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

from evaluation.prepare_evaluation_assignments import ROOT, split_dataset

RESULTS_RETAINED = frozenset({".gitignore", "README.md"})
SOURCE = Path("evaluation/evaluation_repositories_4000.csv")
SOURCE_MANIFEST = Path("evaluation/evaluation_repositories_4000_manifest.json")


def verify_frozen_source(root: Path) -> str:
    """Reject a modified held-out source before generation or destructive work."""
    manifest = json.loads((root / SOURCE_MANIFEST).read_text(encoding="utf-8"))
    expected = manifest.get("output_sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError("Frozen 4,000-repository manifest lacks output_sha256")
    digest = hashlib.sha256((root / SOURCE).read_bytes()).hexdigest()
    if digest != expected:
        raise ValueError("Frozen 4,000-repository CSV does not match its committed manifest")
    return digest


def _tracked_results(root: Path) -> list[str]:
    """Never silently remove any previously committed published evidence."""
    completed = subprocess.run(
        ["git", "ls-files", "-z", "--", "evaluation/results"],
        cwd=root, capture_output=True, check=True,
    )
    paths = completed.stdout.decode("utf-8").split("\0")
    return [path for path in paths if path and path not in {
        "evaluation/results/.gitignore", "evaluation/results/README.md"
    }]


def _retry_readonly_delete(function, filename: str, error_info: tuple) -> None:
    """Retry a failed deletion after clearing Windows Git pack read-only flags.

    Git checks out object pack files as read-only on some Windows systems.
    shutil.rmtree invokes this handler only when its normal removal fails.
    Other errors still propagate so incomplete resets cannot look successful.
    """
    error = error_info[1]
    if not isinstance(error, PermissionError):
        raise error
    # Preserve all other mode bits; only enable owner writing for the retry.
    os.chmod(filename, os.stat(filename).st_mode | stat.S_IWRITE)
    function(filename)


def _remove_local_entry(path: Path) -> None:
    """Remove one result entry without following directory symlinks."""
    if path.is_symlink() or path.is_file():
        try:
            path.unlink()
        except PermissionError:
            path.chmod(path.stat().st_mode | stat.S_IWRITE)
            path.unlink()
    elif path.is_dir():
        shutil.rmtree(path, onerror=_retry_readonly_delete)
    else:
        raise ValueError(f"Unrecognized results entry: {path}")


def prepare_workspace(*, root: Path = ROOT, reset_results: bool = False,
                      reset_ci_cost: bool = False, confirm_reset: bool = False) -> dict:
    """Verify source, optionally reset abandoned state, then generate CSVs."""
    root = root.resolve()
    if not (root / ".git").exists():
        raise ValueError("Run from a CloudTune Git checkout")
    if confirm_reset and not (reset_results or reset_ci_cost):
        raise ValueError("--confirm-reset requires --reset-results or --reset-ci-cost")

    # The study must be pinned before deleting or preparing any local state.
    source_sha256 = verify_frozen_source(root)
    # Validate existing CSVs and manifest before any irreversible deletion.
    manifest = split_dataset(root=root)
    if manifest.get("source_sha256") != source_sha256:
        raise ValueError("Partitioned dataset hash differs from frozen source")
    results = root / "evaluation" / "results"
    retained = [results / name for name in sorted(RESULTS_RETAINED)]
    if reset_results:
        if results.is_symlink() or not all(path.is_file() for path in retained):
            raise ValueError("Results root must be a real directory with tracked .gitignore and README.md")
        tracked = _tracked_results(root)
        if tracked:
            raise ValueError("Refusing to reset committed result evidence: " + ", ".join(tracked[:5]))
        to_remove = sorted((path for path in results.iterdir()
                            if path.name not in RESULTS_RETAINED), key=lambda p: p.name)
    else:
        to_remove = []

    tool = root / ".venv" / "ci-cost"
    if reset_ci_cost:
        override = os.environ.get("CI_COST_DIR", "").strip()
        if override and Path(override).resolve() != tool.resolve():
            raise ValueError("CI_COST_DIR points elsewhere; unset it before resetting ci-cost")
        if tool.is_symlink():
            raise ValueError("Refusing to reset a symlinked ci-cost directory")

    if reset_results or reset_ci_cost:
        print("CAUTION: reset cannot cancel hosted CI or delete retained forks.")
        print("Confirm there are no pending GitHub Actions or unfinished checkpoints before proceeding.")
        for path in to_remove:
            print(f"Results reset candidate: {path.relative_to(root)}")
        if reset_ci_cost and tool.exists():
            print(f"CI-Cost reset candidate: {tool.relative_to(root)}")
        if not confirm_reset:
            print("PREVIEW ONLY: rerun with --confirm-reset after reviewing these paths.")

    if confirm_reset:
        failures: list[tuple[Path, Exception]] = []
        for path in to_remove:
            try:
                _remove_local_entry(path)
            except (OSError, ValueError) as error:
                # One locked Git pack must not stop cleanup of unrelated smoke
                # trials; report every remaining problem at the end.
                print(f"Reset could not remove {path.relative_to(root)}: {error}", file=sys.stderr)
                failures.append((path, error))
        if reset_ci_cost and tool.exists():
            try:
                if not tool.is_dir():
                    raise ValueError("CI-Cost checkout exists but is not a directory")
                _remove_local_entry(tool)
            except (OSError, ValueError) as error:
                print(f"Reset could not remove {tool.relative_to(root)}: {error}", file=sys.stderr)
                failures.append((tool, error))
        if failures:
            raise OSError(f"Reset INCOMPLETE: {len(failures)} entries could not be removed; "
                          "close processes using those files, then rerun the same command")
        print("Local reset completed; external GitHub forks and runs are unchanged.")

    # Reuse the existing deterministic splitter; never implement a second split.
    for assignment in manifest["assignments"]:
        print(f"Member {assignment['member']}: {assignment['file']} "
              f"({assignment['rows']} rows, SHA-256 {assignment['sha256']})")
    print("Assignment manifest: evaluation/assignments/manifest.json")
    print("Commit the four assignment CSVs and manifest before live evaluation.")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset-results", action="store_true",
                        help="Preview removal of abandoned results while retaining tracked policy/docs")
    parser.add_argument("--reset-ci-cost", action="store_true",
                        help="Preview removal of local .venv/ci-cost so Arm B reinstalls it")
    parser.add_argument("--confirm-reset", action="store_true",
                        help="Execute the explicitly requested reset after checking no external jobs are active")
    args = parser.parse_args()
    try:
        prepare_workspace(reset_results=args.reset_results,
                          reset_ci_cost=args.reset_ci_cost,
                          confirm_reset=args.confirm_reset)
        return 0
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        print(f"Evaluation workspace preparation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
