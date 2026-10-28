#!/usr/bin/env python3
"""Create a reproducible 5,000-repository sample from Zenodo record 20340547."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "research-data" / "zenodo_20340547" / "source" / "repositories.csv.gz"
DEFAULT_OUTPUT = ROOT / "research-data" / "zenodo_20340547" / "repositories_5000.csv"
DEFAULT_MANIFEST = ROOT / "research-data" / "zenodo_20340547" / "selection_manifest.json"
SOURCE_MD5 = "a345384e924083ae4da327e4fdf3af74"
SOURCE_URL = "https://zenodo.org/records/20340547/files/repositories.csv.gz?download=1"


def read_source(path: Path) -> tuple[list[dict[str, str]], str, int]:
    raw = path.read_bytes()
    md5 = hashlib.md5(raw).hexdigest()
    data = raw
    decompression_layers = 0
    while data.startswith(b"\x1f\x8b"):
        if decompression_layers >= 3:
            raise ValueError("Source has unexpectedly many gzip layers")
        data = gzip.decompress(data)
        decompression_layers += 1

    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
    required = {"name", "updated", "commits", "stars"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError(f"Unexpected source CSV columns: {reader.fieldnames}")
    return list(reader), md5, decompression_layers


def build_dataset(
    source: Path,
    output: Path,
    manifest_path: Path,
    limit: int,
    seed: int,
    updated_since: str,
) -> dict:
    rows, source_md5, gzip_layers = read_source(source)
    if source_md5 != SOURCE_MD5:
        raise ValueError(
            f"Source checksum mismatch: expected {SOURCE_MD5}, got {source_md5}"
        )

    unique: dict[str, dict[str, str]] = {}
    duplicate_count = 0
    for row in rows:
        repo_id = (row.get("name") or "").strip().lower()
        if not repo_id:
            continue
        if repo_id in unique:
            duplicate_count += 1
            continue
        unique[repo_id] = row

    eligible = [
        (repo_id, row)
        for repo_id, row in unique.items()
        if (row.get("updated") or "")[:10] >= updated_since
    ]
    eligible.sort(key=lambda item: item[0])
    if limit <= 0:
        raise ValueError("--limit must be a positive integer")
    if len(eligible) < limit:
        raise ValueError(
            f"Only {len(eligible)} repositories meet updated_since={updated_since}; "
            f"cannot select {limit}"
        )

    selected = random.Random(seed).sample(eligible, limit)
    source_fields = [field for field in rows[0] if field != "name"]
    fields = ["selection_rank", "repo_id", "repo_url", *source_fields]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for rank, (repo_id, row) in enumerate(selected, 1):
            record = {key: value for key, value in row.items() if key != "name"}
            writer.writerow({
                "selection_rank": rank,
                "repo_id": repo_id,
                "repo_url": f"https://github.com/{repo_id}",
                **record,
            })

    manifest = {
        "dataset_name": "Zenodo GitHub Actions repository sample",
        "dataset_version": 1,
        "source_title": "A dataset of GitHub Actions workflow histories",
        "source_record": "https://zenodo.org/records/20340547",
        "source_doi": "10.5281/zenodo.20340547",
        "source_version_date": "2026-05-22",
        "source_collection_date": "2026-03-26",
        "source_file": str(source.relative_to(ROOT)).replace("\\", "/"),
        "source_download_url": SOURCE_URL,
        "source_expected_md5": SOURCE_MD5,
        "source_actual_md5": source_md5,
        "source_gzip_layers": gzip_layers,
        "source_repository_rows": len(rows),
        "unique_repository_rows": len(unique),
        "duplicate_rows_removed": duplicate_count,
        "updated_since_filter": updated_since,
        "eligible_after_recency_filter": len(eligible),
        "selected_repository_count": limit,
        "sampling_method": "uniform random sample without replacement",
        "random_seed": seed,
        "selection_scope": "sampled from Zenodo's repository metadata; distinct within this source list",
        "source_selection_criteria": [
            "non-fork repository",
            "at least 300 commits",
            "at least 100 stars",
            "at least one commit in the year before the source collection date",
            "contains a .github/workflows directory",
        ],
        "important_limit": (
            "Repository activity in the source was collected through 2026-03-26; "
            "the list does not confirm activity after that date. Repositories are candidates, "
            "not yet individually screened for a specific optimization pattern."
        ),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_csv": str(output.relative_to(ROOT)).replace("\\", "/"),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=20261027)
    parser.add_argument("--updated-since", default="2025-10-27")
    args = parser.parse_args()
    try:
        manifest = build_dataset(
            args.source, args.output, args.manifest,
            args.limit, args.seed, args.updated_since,
        )
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
