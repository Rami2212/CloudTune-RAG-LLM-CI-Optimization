"""Deterministically partition the existing held-out 4,000-repository dataset.

The original dataset is never rewritten, re-sampled, or filtered. Every source
row appears once in precisely one of the four committed member assignments.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path("evaluation/evaluation_repositories_4000.csv")
DESTINATION = Path("evaluation/assignments")
MEMBERS = 4
ROWS_PER_MEMBER = 1000


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_unchanged(path: Path, content: bytes) -> None:
    """Refuse to overwrite edited assignments or an existing manifest."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError(f"Existing assignment differs; do not overwrite: {path}")
        return
    path.write_bytes(content)


def _csv_bytes(fields: list[str], rows: list[dict[str, str]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def split_dataset(*, root: Path = ROOT) -> dict:
    source = root / SOURCE
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        if not {"repo_id", "split"} <= set(fields):
            raise ValueError("Held-out CSV requires repo_id and split columns")
        rows = list(reader)
    if len(rows) != MEMBERS * ROWS_PER_MEMBER:
        raise ValueError(f"Expected exactly 4000 source rows, found {len(rows)}")
    identities = [row["repo_id"].strip().casefold() for row in rows]
    if any(not name or "/" not in name for name in identities) or len(set(identities)) != 4000:
        raise ValueError("Source contains invalid or duplicate repository IDs")
    if any(row["split"] != "evaluation" for row in rows):
        raise ValueError("The assignment source must contain only held-out evaluation rows")

    output = root / DESTINATION
    assignments = []
    for member in range(1, MEMBERS + 1):
        begin = (member - 1) * ROWS_PER_MEMBER
        selected = rows[begin:begin + ROWS_PER_MEMBER]
        path = output / f"member_{member:02d}.csv"
        content = _csv_bytes(fields, selected)
        _write_unchanged(path, content)
        assignments.append({"member": member, "file": str(path.relative_to(root)).replace("\\", "/"),
                            "first_source_position": begin + 1,
                            "last_source_position": begin + ROWS_PER_MEMBER,
                            "rows": len(selected), "sha256": hashlib.sha256(content).hexdigest(),
                            "first_repo": selected[0]["repo_id"], "last_repo": selected[-1]["repo_id"]})
    manifest = {"source": SOURCE.as_posix(), "source_sha256": _sha(source),
                "partition_rule": "consecutive source row positions; no reshuffle or filtering",
                "rows": len(rows), "member_count": MEMBERS, "rows_per_member": ROWS_PER_MEMBER,
                "assignments": assignments}
    content = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    _write_unchanged(output / "manifest.json", content)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        print(json.dumps(split_dataset(), indent=2))
        return 0
    except (OSError, ValueError, csv.Error) as exc:
        parser.exit(1, f"Assignment verification failed: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
