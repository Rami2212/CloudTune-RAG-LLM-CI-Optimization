"""CloudTune A/B/C evaluation coordinator — read-only preparation and Arm B generation.

``prepare`` snapshots original workflows and ``ci-cost`` generates offline B
candidates. Neither stage creates forks, dispatches CI or measures savings.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

from scripts.experiment_environment import load_env

from evaluation.optimizers.ci_cost import generate_ci_cost_candidate
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


def load_config(path: Path, *, allow_hosted: bool = False) -> dict:
    config = json.loads(path.read_text(encoding="utf-8"))
    evaluation_id = config.get("evaluation_id", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", evaluation_id):
        raise ValueError("evaluation_id must contain only letters, digits, underscores and hyphens")
    if config.get("arms") != ["original", "ci_cost", "rag"]:
        raise ValueError("Evaluation config must reserve three arms: original, ci_cost, rag")
    if not isinstance(config.get("repository_limit"), int) or not 1 <= config["repository_limit"] <= 100:
        raise ValueError("repository_limit must be between 1 and 100")
    if not isinstance(config.get("repository_start_at", 1), int) or config.get("repository_start_at", 1) < 1:
        raise ValueError("repository_start_at must be a positive integer")
    if config.get("execution", {}).get("development_smoke") is True and not allow_hosted:
        raise ValueError("Development smoke requires fork controller")
    if config.get("execution", {}).get("dry_run") is not True and not allow_hosted:
        raise ValueError("Preparation and local candidate generation require execution.dry_run=true")
    development_smoke = config.get("execution", {}).get("development_smoke") is True
    if development_smoke:
        # A development-only smoke uses separate, labeled repositories.
        # It must never be accepted by the read-only preparation CLI.
        if (not allow_hosted or config.get("dataset_split") != "development" or
                not evaluation_id.startswith("dev-")):
            raise ValueError("Development smoke requires fork controller, development split and dev- evaluation ID")
    elif config.get("dataset_split", "evaluation") != "evaluation":
        raise ValueError("Evaluation requires the held-out evaluation dataset")
    return config


def prepare(config: dict, *, reader: GitHubReader | None = None, project_root: Path = ROOT) -> dict:
    """Screen a fixed set of source rows, retain outcomes, and create A snapshots."""
    dataset = project_root / config["dataset"]
    training = project_root / "research-data/zenodo_20340547/pattern_repo_candidates_20.csv"
    development_smoke = config.get("execution", {}).get("development_smoke") is True
    dataset_split = "development" if development_smoke else "evaluation"
    rows = read_evaluation_rows(dataset, expected_split=dataset_split)
    start_at = config.get("repository_start_at", 1)
    selected = rows[start_at - 1:start_at - 1 + config["repository_limit"]]
    if not selected:
        raise ValueError("No dataset rows in the requested range")
    dataset_hash = file_sha256(dataset)
    exclusions = excluded_repo_ids(
        training,
        (project_root / "research-data/experiments", project_root / "research-data/scenario-experiments"),
    )
    if development_smoke:
        # Fail closed on the entire held-out cohort, including case-insensitive IDs.
        held_out = project_root / "evaluation/evaluation_repositories_4000.csv"
        exclusions.update(row["repo_id"].casefold() for row in read_evaluation_rows(held_out))
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



def generate_b(config: dict, *, project_root: Path = ROOT,
               optimizer=generate_ci_cost_candidate) -> dict:
    """Generate B from pinned preparation output without further GitHub reads.

    ``screening.csv`` includes ineligible rows for transparent attrition counts;
    only prepared/needs_harness repositories have valid original snapshots.
    """
    output = project_root / "evaluation/results" / config["evaluation_id"]
    frozen_config = output / "config.json"
    screening = output / "screening.csv"
    if not frozen_config.exists() or not screening.exists():
        raise ValueError("Run --stage prepare first; frozen configuration/screening is missing")
    if json.loads(frozen_config.read_text(encoding="utf-8")) != config:
        raise ValueError("Evaluation configuration differs from pinned preparation")
    dataset_hash = file_sha256(project_root / config["dataset"])
    previous = json.loads((output / "preparation_summary.json").read_text(encoding="utf-8"))
    if previous.get("dataset_sha256") != dataset_hash:
        raise ValueError("Held-out dataset has changed since preparation")
    version = config.get("ci_cost", {}).get("version", "")
    if version != "1.0.0":
        raise ValueError("Arm B requires reviewed ci-cost version 1.0.0")

    with screening.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    split = "development" if config.get("execution", {}).get("development_smoke") is True else "evaluation"
    selected = read_evaluation_rows(project_root / config["dataset"], expected_split=split)
    start = config.get("repository_start_at", 1) - 1
    expected_ids = [row["repo_id"] for row in selected[start:start + config["repository_limit"]]]
    if [row["repo_id"] for row in rows] != expected_ids:
        raise ValueError("Screening rows do not match selected evaluation dataset rows")

    summaries: list[dict] = []
    for row in rows:
        if row["status"] not in ("prepared", "needs_harness"):
            summaries.append({"repo_id": row["repo_id"], "decision": "SKIPPED",
                              "reason": "Not eligible for candidate generation: " + row["status"]})
            continue
        manifest_path = Path(row["manifest_path"]).resolve()
        if not manifest_path.is_relative_to((output / "repositories").resolve()):
            raise ValueError("Screening references a manifest outside this evaluation")
        if not manifest_path.is_file():
            raise ValueError("Prepared repository manifest is missing")
        snapshot_dir = manifest_path.parent
        candidate = optimizer(snapshot_dir, version=version)
        summaries.append({"repo_id": row["repo_id"], "decision": candidate["decision"],
                          "status": candidate["status"], "reason": candidate.get("error")})
        print(f"{row['repo_id']}: Arm B {candidate['decision']} — {candidate['status']}", flush=True)
    counts = {name: sum(row["decision"] == name for row in summaries)
              for name in sorted({row["decision"] for row in summaries})}
    summary = {"evaluation_id": config["evaluation_id"],
               "stage": "ci_cost_offline_generation_only", "repositories": summaries,
               "counts": counts, "github_actions_runs": 0,
               "note": "Generated candidates are NOT safety-validated or CI-executed."}
    (output / "ci_cost_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--stage", choices=("prepare", "ci-cost"), default="prepare")
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        # Reuse the repository's existing .env loader; exported shell values win.
        load_env(ROOT / ".env")
        summary = prepare(config) if args.stage == "prepare" else generate_b(config)
        print(json.dumps(summary, indent=2))
        if args.stage == "ci-cost" and summary["counts"].get("ERROR", 0):
            return 1
    except (OSError, ValueError, KeyError, csv.Error, json.JSONDecodeError) as error:
        print(f"Evaluation stage failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
