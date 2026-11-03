"""Merge four published team outcome tables; no APIs or raw checkpoints read.

The repository is the unit of analysis. This combines statuses and safe run
metadata; it does not fabricate a CI-time effect estimate for missing trials.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import sys
from pathlib import Path

from evaluation.prepare_evaluation_assignments import ROOT, split_dataset
from scripts.run_evaluation_batch import EXPORT_COLUMNS, default_batch_id, validated_batch_id


def merge_published(*, root: Path = ROOT,
                    batch_ids: tuple[str, str, str, str] | None = None) -> dict:
    """Combine exactly four assigned batch IDs (defaults are member-specific)."""
    batch_ids = batch_ids or tuple(default_batch_id(member) for member in range(1, 5))
    if len(batch_ids) != 4 or len(set(batch_ids)) != 4:
        raise ValueError("Supply four distinct batch IDs, one for each member")
    for member, batch_id in enumerate(batch_ids, 1):
        validated_batch_id(member, batch_id)
    manifest = split_dataset(root=root)
    published = root / "evaluation/results"
    table: list[dict[str, str]] = []
    all_ids = set()
    for entry in manifest["assignments"]:
        member = entry["member"]
        batch_id = batch_ids[member - 1]
        folder = published / batch_id / "published"
        report = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        if (report.get("assignment_sha256") != entry["sha256"] or
                report.get("member") != member or report.get("batch_id") != batch_id):
            raise ValueError(f"Member {member} report does not match assigned dataset hash")
        with (folder / "attempts.csv").open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != EXPORT_COLUMNS:
                raise ValueError(f"Member {member} report columns changed")
            rows = list(reader)
        with (root / entry["file"]).open("r", newline="", encoding="utf-8-sig") as handle:
            expected = [row["repo_id"] for row in csv.DictReader(handle)]
        if len(rows) != 1000 or any(row["repo_id"] != expected[i] or
             row["source_position"] != str((member-1)*1000+i+1) or
             row["position"] != str(i+1) or row["member"] != str(member) or
             row["evaluation_id"] != f"{batch_id}-r{i+1:04d}" or
             row["batch_id"] != batch_id
             for i, row in enumerate(rows)):
            raise ValueError(f"Member {member} report rows do not match assignment")
        for row in rows:
            key = row["repo_id"].casefold()
            if key in all_ids:
                raise ValueError(f"Repository counted twice: {row['repo_id']}")
            all_ids.add(key)
        table.extend(rows)
    if len(table) != 4000:
        raise ValueError("Merged cohort must account for exactly 4000 rows")
    destination = published / "cohort" / "published"
    destination.mkdir(parents=True, exist_ok=True)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=EXPORT_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(table)
    raw = buffer.getvalue().encode("utf-8")
    temporary = destination / "attempts_4000.csv.tmp"
    temporary.write_bytes(raw)
    os.replace(temporary, destination / "attempts_4000.csv")
    counts: dict[str, int] = {}
    for row in table:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    summary = {"schema": 1, "total_selected": 4000,
               "held_out_source_sha256": manifest["source_sha256"],
               "assignments": [{"member": x["member"], "sha256": x["sha256"],
                                "batch_id": batch_ids[x["member"] - 1]}
                               for x in manifest["assignments"]],
               "merged_csv_sha256": hashlib.sha256(raw).hexdigest(),
               "status_counts": dict(sorted(counts.items())),
               "note": "Statuses only; not paired savings estimates or independent replication evidence"}
    mtmp = destination / "manifest.json.tmp"
    mtmp.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    os.replace(mtmp, destination / "manifest.json")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-ids", nargs=4, metavar=("MEMBER_1", "MEMBER_2", "MEMBER_3", "MEMBER_4"),
                        help="Four batch IDs in member order (default: eval-member-01 ... 04)")
    args = parser.parse_args()
    try:
        print(json.dumps(merge_published(batch_ids=tuple(args.batch_ids) if args.batch_ids else None), indent=2))
        return 0
    except (ValueError, OSError, csv.Error, json.JSONDecodeError) as exc:
        print(f"Team result merge rejected: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
