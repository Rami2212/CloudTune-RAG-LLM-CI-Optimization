"""CloudTune A/B/C evaluation coordinator — Phase 1 read-only preparation.

Until later implementation phases, this entrypoint supports only the
``prepare`` stage. It deliberately cannot dispatch workflows, create forks or
claim execution measurements. B and C optimizers remain planned work.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

from scripts.experiment_environment import load_env

from evaluation.optimizers.original import original_candidate
from evaluation.repository_preparation import (
    GitHubReader,
    PreparationError,
    excluded_repo_ids,
    file_sha256,
    prepare_repository,
    read_evaluation_rows,
    write_json_immutable,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "evaluation" / "configs" / "pilot.json"


def load_config(path: Path) -> dict:
    config = json.loads(path.read_text(encoding="utf-8"))
    evaluation_id = config.get("evaluation_id", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", evaluation_id):
        raise ValueError("evaluation_id must contain only letters, digits, underscores and hyphens")
    if config.get("arms") != ["original", "ci_cost", "rag"]:
        raise ValueError("Phase 1 config must reserve the three arms: original, ci_cost, rag")
    if not isinstance(config.get("repository_limit"), int) or not 1 <= config["repository_limit"] <= 100:
        raise ValueError("repository_limit must be between 1 and 100")
    if not isinstance(config.get("repository_start_at", 1), int) or config.get("repository_start_at", 1) < 1:
        raise ValueError("repository_start_at must be a positive integer")
    if config.get("execution", {}).get("dry_run") is not True:
        raise ValueError("Phase 1 is strictly read-only; execution.dry_run must be true")
    if config.get("dataset_split", "evaluation") != "evaluation":
        raise ValueError("Phase 1 expects the held-out evaluation dataset")
    return config


def prepare(config: dict, *, reader: GitHubReader | None = None, project_root: Path = ROOT) -> dict:
    """Screen a fixed set of source rows, retain outcomes, and create A snapshots."""
    dataset = project_root / config["dataset"]
    training = project_root / "research-data/zenodo_20340547/pattern_repo_candidates_20.csv"
    rows = read_evaluation_rows(dataset)
    start_at = config.get("repository_start_at", 1)
    selected = rows[start_at - 1:start_at - 1 + config["repository_limit"]]
    if not selected:
        raise ValueError("No dataset rows in the requested range")
    dataset_hash = file_sha256(dataset)
    exclusions = excluded_repo_ids(
        training,
        (project_root / "research-data/experiments", project_root / "research-data/scenario-experiments"),
    )
    output = project_root / "evaluation/results" / config["evaluation_id"]
    output.mkdir(parents=True, exist_ok=True)
    write_json_immutable(output / "config.json", config)
    reader = reader or GitHubReader()
    decisions: list[dict] = []
    for row in selected:
        repo_id = row["repo_id"]
        try:
            result = prepare_repository(row, reader, output, dataset_hash, exclusions)
            if result["status"] in ("prepared", "needs_harness"):
                folder = Path(result["manifest_path"]).parent
                candidate = original_candidate(folder)
                write_json_immutable(folder / "candidates" / "A" / "candidate.json", candidate)
        except PreparationError as error:
            result = {"repo_id": repo_id, "status": error.status, "reason": str(error),
                      "workflow_path": "", "source_commit_sha": "", "manifest_path": ""}
        decisions.append(result)
        print(f"{repo_id}: {result['status']} — {result['reason'] or 'snapshot saved'}", flush=True)
    # Overwrite only aggregated *screening* records: individual pinned snapshots
    # stay immutable. Screening summary is not evidence of any executed CI run.
    columns = ("repo_id", "status", "reason", "workflow_path", "source_commit_sha", "manifest_path")
    with (output / "screening.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(decisions)
    counts = {key: sum(d["status"] == key for d in decisions) for key in sorted({d["status"] for d in decisions})}
    summary = {
        "evaluation_id": config["evaluation_id"],
        "phase": "repository_preparation_and_original_candidate_only",
        "dataset_sha256": dataset_hash,
        "rows_screened": len(decisions),
        "counts": counts,
        "github_actions_runs": 0,
        "remarks": "B, C, common validation and real CI runs are not yet implemented.",
    }
    (output / "preparation_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--stage", choices=("prepare",), default="prepare")
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        # Reuse the repository's existing .env loader; exported shell values win.
        load_env(ROOT / ".env")
        print(json.dumps(prepare(config), indent=2))
    except (OSError, ValueError, KeyError, csv.Error, json.JSONDecodeError) as error:
        print(f"Preparation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
