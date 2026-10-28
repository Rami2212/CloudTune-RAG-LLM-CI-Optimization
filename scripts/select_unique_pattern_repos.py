#!/usr/bin/env python3
"""Select distinct screening repositories across all literature patterns."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from select_pattern_repos import candidate_pool, choose_rows, read_jsonl

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATTERNS = ROOT / "knowledge" / "extracted_patterns.jsonl"
DEFAULT_OUTPUT = ROOT / "research-data" / "pattern_repo_candidates_unique.csv"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--patterns", type=Path, default=DEFAULT_PATTERNS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--per-pattern", type=int, default=20)
    args = parser.parse_args()
    if args.per_pattern < 1:
        parser.error("--per-pattern must be at least 1")

    snapshot = args.snapshot if args.snapshot.is_absolute() else ROOT / args.snapshot
    context_path = snapshot / "repo_context.jsonl"
    if not context_path.is_file():
        parser.error(f"snapshot has no repo_context.jsonl: {context_path}")
    if not args.patterns.is_file():
        parser.error(f"patterns file not found: {args.patterns}")

    try:
        repos = candidate_pool(read_jsonl(context_path))
        patterns = read_jsonl(args.patterns)
        if not repos or not patterns:
            raise ValueError("Need collected repositories and pattern records")

        # The standard selector ranks each pattern independently. Request all
        # candidates, then assign them in pattern order while reserving each
        # repository for only one pattern.
        ranked = choose_rows(patterns, repos, len(repos))
        selected = []
        used_repositories: set[str] = set()
        counts: dict[str, int] = {}
        for pattern in patterns:
            pattern_id = str(pattern.get("pattern_id", "UNKNOWN"))
            count = 0
            for row in ranked:
                if row["pattern_id"] != pattern_id:
                    continue
                repo_id = row["repo_id"]
                if repo_id in used_repositories:
                    continue
                used_repositories.add(repo_id)
                count += 1
                row = dict(row)
                row["rank"] = count
                row["source_snapshot"] = str(snapshot.resolve().relative_to(ROOT))
                selected.append(row)
                if count == args.per_pattern:
                    break
            counts[pattern_id] = count

        insufficient = {pattern_id: count for pattern_id, count in counts.items() if count < args.per_pattern}
        output = args.output if args.output.is_absolute() else ROOT / args.output
        output = output.resolve()
        research_root = (ROOT / "research-data").resolve()
        if not output.is_relative_to(research_root):
            raise ValueError(f"output must be inside {research_root}")
        output.parent.mkdir(parents=True, exist_ok=True)
        if selected:
            with output.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(selected[0]), lineterminator="\n")
                writer.writeheader()
                writer.writerows(selected)

        print(f"Patterns: {len(patterns)}; repositories screened: {len(repos)}")
        print(f"Unique candidate rows written: {len(selected)}; target: {len(patterns) * args.per_pattern}")
        print(f"Output: {output.relative_to(ROOT)}")
        if insufficient:
            print("Patterns below target: " + ", ".join(f"{key}={value}" for key, value in insufficient.items()))
            return 2
        print("Each selected repository appears once across the full dataset.")
        return 0
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
