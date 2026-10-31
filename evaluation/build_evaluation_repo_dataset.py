"""Create a reproducible held-out repository sample from the 5,000 Zenodo rows.

The existing 500-row pattern_repo_candidates_20.csv is treated as the training /
development pool. Repository IDs present in experiment case records are also
excluded, even if they are not in that candidate file.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "research-data/zenodo_20340547/repositories_5000.csv"
DEFAULT_TRAINING = ROOT / "research-data/zenodo_20340547/pattern_repo_candidates_20.csv"
DEFAULT_OUTPUT = ROOT / "evaluation/evaluation_repositories_4000.csv"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "repo_id" not in reader.fieldnames:
            raise ValueError(f"CSV needs a repo_id column: {path}")
        return list(reader), list(reader.fieldnames)


def training_repo_ids(path: Path) -> set[str]:
    rows, _ = read_csv(path)
    ids = {row["repo_id"].strip().casefold() for row in rows if row.get("repo_id", "").strip()}
    if not ids:
        raise ValueError("Training candidate file contains no repository IDs.")
    return ids


def case_repo_ids() -> set[str]:
    ids = set()
    for root in (ROOT / "research-data/experiments", ROOT / "research-data/scenario-experiments"):
        if not root.exists():
            continue
        for case_path in root.glob("*/case.json"):
            try:
                case = json.loads(case_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            for key in ("repo_id", "source_repo_id", "repository_id", "repository_name", "source_repo"):
                value = case.get(key)
                if isinstance(value, str):
                    repo_id = value.strip().casefold()
                    if re.fullmatch(r"[\w.-]+/[\w.-]+", repo_id):
                        ids.add(repo_id)
    return ids


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--training", type=Path, default=DEFAULT_TRAINING)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--count", type=int, default=4000)
    parser.add_argument("--seed", type=int, default=20261031)
    args = parser.parse_args()
    if args.count < 1:
        parser.error("--count must be positive")

    try:
        source_rows, source_fields = read_csv(args.source)
        training_ids = training_repo_ids(args.training)
        used_case_ids = case_repo_ids()
        excluded_ids = training_ids | used_case_ids

        seen = set()
        unique_rows = []
        for row in source_rows:
            repo_id = row["repo_id"].strip().casefold()
            if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo_id):
                continue
            if repo_id in seen:
                raise ValueError(f"Duplicate repository ID in source list: {repo_id}")
            seen.add(repo_id)
            row["repo_id"] = repo_id
            unique_rows.append(row)

        eligible = [row for row in unique_rows if row["repo_id"] not in excluded_ids]
        if len(eligible) < args.count:
            raise ValueError(
                f"Only {len(eligible)} source repositories remain after training exclusions; "
                f"cannot select {args.count}."
            )

        selected = random.Random(args.seed).sample(eligible, args.count)
        # Keep the source ordering easy to compare while the seeded draw determines membership.
        source_order = {row["repo_id"]: index for index, row in enumerate(unique_rows)}
        selected.sort(key=lambda row: source_order[row["repo_id"]])

        output_fields = source_fields + (["split"] if "split" not in source_fields else [])
        for row in selected:
            row["split"] = "evaluation"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=output_fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(selected)

        manifest = {
            "dataset_name": "held-out CI evaluation repository sample",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "source_dataset": str(args.source.resolve().relative_to(ROOT)),
            "source_sha256": sha256(args.source),
            "source_rows": len(source_rows),
            "unique_source_repositories": len(unique_rows),
            "training_repo_file": str(args.training.resolve().relative_to(ROOT)),
            "training_repo_file_sha256": sha256(args.training),
            "training_candidate_ids": len(training_ids),
            "experiment_case_repo_ids_found": len(used_case_ids),
            "experiment_case_repo_ids_overlapping_source": len(used_case_ids & seen),
            "experiment_case_ids_additional_to_training_within_source": len((used_case_ids - training_ids) & seen),
            "excluded_unique_training_or_experiment_ids_in_source": len(excluded_ids & seen),
            "eligible_repositories_after_exclusion": len(eligible),
            "evaluation_repository_count": len(selected),
            "remaining_unused_repositories": len(eligible) - len(selected),
            "sampling_method": "uniform random sample without replacement",
            "random_seed": args.seed,
            "output_csv": str(args.output.resolve().relative_to(ROOT)),
            "output_sha256": sha256(args.output),
            "split_policy": "Exclude every repo_id in pattern_repo_candidates_20.csv and any repo_id found in saved experiment case records.",
            "limitations": [
                "Repository metadata comes from Zenodo's 2026-03-26 source snapshot and is not a current eligibility check.",
                "The project also contains context snapshots for some source repositories; this split treats metadata screening as distinct from training/evaluation use.",
            ],
        }
        manifest_path = args.output.with_name(args.output.stem + "_manifest.json")
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
    except (OSError, ValueError, csv.Error, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
