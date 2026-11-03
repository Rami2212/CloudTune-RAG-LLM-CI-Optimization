"""Explicitly refresh the official release snapshot for FUTURE trials only.

Run: python -m evaluation.refresh_setup_node_releases --output PATH
Review the diff, rebuild CI-Cost, and use a fresh evaluation ID afterwards.
Admission itself never calls this module or performs a network lookup.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import urllib.request
from pathlib import Path

from evaluation.setup_node_compatibility import SUPPORTED_MAJORS

API = "https://api.github.com/repos/actions/setup-node/git/"


def fetch_json(url: str):
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                  "User-Agent": "CloudTune-release-registry"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def release_snapshot(fetch=fetch_json) -> dict:
    rows = fetch(API + "matching-refs/tags")
    if not isinstance(rows, list):
        raise ValueError("Expected official GitHub refs list")
    refs = {}
    for row in rows:
        match = re.fullmatch(r"refs/tags/(v(\d+)(?:\.\d+(?:\.\d+)?)?)", row["ref"])
        if not match or int(match[2]) not in SUPPORTED_MAJORS:
            continue
        obj = row["object"]
        # Peel annotated tags using only this fixed official repository URL.
        for _ in range(8):
            sha = obj.get("sha", "")
            if not re.fullmatch(r"[a-f0-9]{40}", sha):
                raise ValueError("Malformed official tag object SHA")
            if obj.get("type") == "commit":
                break
            if obj.get("type") != "tag":
                raise ValueError("Release ref does not identify a commit")
            obj = fetch(API + "tags/" + sha)["object"]
        else:
            raise ValueError("Excessively nested release tag")
        refs[match[1]] = sha
    if not all("v" + str(major) in refs for major in SUPPORTED_MAJORS):
        raise ValueError("Official snapshot is missing a supported major tag")
    return {"schema": 1, "repository": "actions/setup-node",
            "supported_majors": sorted(SUPPORTED_MAJORS),
            "source_url": API + "matching-refs/tags",
            "retrieved_date": dt.datetime.now(dt.timezone.utc).date().isoformat(),
            "refs": dict(sorted(refs.items()))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True,
                        help="Write a candidate registry for review; never refresh during an active trial")
    args = parser.parse_args()
    document = release_snapshot()  # Collect and validate all evidence before writing.
    args.output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(document['refs'])} official refs to {args.output}")


if __name__ == "__main__":
    main()
