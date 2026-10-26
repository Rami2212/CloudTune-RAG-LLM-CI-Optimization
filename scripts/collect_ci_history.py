"""Collect historical CI workflow transitions and available runs from candidate repos."""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from pathlib import Path

import run_ci_experiment as runner
from experiment_environment import load_env
from workflow_history import collect


def read_rows(path, pattern=None):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not {"repo_id", "pattern_id", "workflow_paths"} <= set(reader.fieldnames or []):
            raise ValueError("Candidate CSV requires repo_id, pattern_id and workflow_paths columns")
        rows = list(reader)
    selected, seen = [], set()
    for row in rows:
        if pattern and row["pattern_id"] != pattern:
            continue
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", row["repo_id"]):
            continue
        key = (row["pattern_id"], row["repo_id"])
        if key in seen:
            continue
        seen.add(key)
        paths = [path.strip().replace("\\", "/") for path in row.get("workflow_paths", "").split(";") if path.strip()]
        selected.append((row, paths))
    if not selected:
        raise ValueError("No matching repository rows")
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=runner.ROOT / "research-data/pattern_repo_candidates.csv")
    parser.add_argument("--env-file", type=Path, default=runner.ROOT / ".env")
    parser.add_argument("--pattern", help="Only collect one pattern ID")
    parser.add_argument("--start-at", type=int, default=1, help="One-based candidate row position")
    parser.add_argument("--limit", type=int, help="Maximum repositories to process")
    args = parser.parse_args()
    if args.start_at < 1 or args.limit is not None and args.limit < 1:
        parser.error("--start-at and --limit must be positive")

    rows = read_rows(args.csv, args.pattern)
    load_env(args.env_file)
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise ValueError("Set GITHUB_TOKEN or GH_TOKEN in .env")

    api_ledger = runner.ROOT / "research-data/historical-workflows/api_calls.jsonl"
    github = runner.GitHub(token, api_ledger)
    stop = len(rows) if args.limit is None else min(len(rows), args.start_at - 1 + args.limit)
    for index in range(args.start_at - 1, stop):
        row, paths = rows[index]
        print(f"\n[{index + 1}/{len(rows)}] {row['pattern_id']} — {row['repo_id']}", flush=True)
        if not paths:
            print("No workflow paths in candidate data; skipped.", flush=True)
            continue
        for workflow_path in paths:
            safe_repo = row["repo_id"].replace("/", "__")
            folder = runner.ROOT / "research-data/historical-workflows" / row["pattern_id"] / safe_repo / Path(workflow_path).name
            result = collect(github, row["repo_id"], workflow_path, row["pattern_id"], folder, runner)
            print(f"  {workflow_path}: {result['status']} -> {folder}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        print("Error: " + runner.redact(str(exc)), file=sys.stderr)
        raise SystemExit(1)
