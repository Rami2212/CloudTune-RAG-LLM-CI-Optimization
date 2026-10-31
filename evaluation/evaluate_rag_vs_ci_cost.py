"""Summarize matched CI evaluation runs for original, ci-cost, and RAG arms.

Input CSV columns:
  evaluation_repo_id, arm, run_status, workflow_elapsed_seconds,
  sum_job_runtime_seconds, required_checks_pass, safety_verdict,
  optimizer_seconds, tokens_in, tokens_out, ci_cost_usd

Required columns are evaluation_repo_id, arm, and run_status. Candidate-level
results can be represented by a row with an empty run_status and a safety_verdict
such as NO_CHANGE, FAIL, REVIEW_REQUIRED, or INCONCLUSIVE.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import random
import statistics
import sys

ARMS = ("original", "ci_cost", "rag", "llm_only")
OPTIMIZERS = ("ci_cost", "rag", "llm_only")
SUCCESS_STATUSES = {"success", "succeeded", "successful", "passed", "pass"}
PASS_VERDICTS = {"pass", "passed", "safe"}
NO_CHANGE_VERDICTS = {"no_change", "no change", "abstain", "abstained"}


def normalized_arm(value: str) -> str:
    raw = value.strip().lower().replace("—", "_").replace("–", "_")
    raw = raw.replace("+", "_").replace("-", "_").replace(" ", "_")
    while "__" in raw:
        raw = raw.replace("__", "_")
    aliases = {
        "a": "original", "m0": "original", "baseline": "original",
        "a_original": "original", "original_workflow": "original",
        "b": "ci_cost", "m1": "ci_cost", "ci_cost": "ci_cost",
        "b_ci_cost": "ci_cost", "rule_based": "ci_cost",
        "c": "rag", "m3": "rag", "llm_rag": "rag", "llm_rag_optimizer": "rag",
        "c_llm_rag": "rag", "rag_assisted": "rag",
        "d": "llm_only", "m2": "llm_only", "llm_only": "llm_only",
        "d_llm_only": "llm_only",
    }
    return aliases.get(raw, raw)


def parse_bool(value):
    if value is None or not str(value).strip():
        return None
    raw = str(value).strip().lower()
    if raw in {"true", "1", "yes", "y", "pass", "passed"}:
        return True
    if raw in {"false", "0", "no", "n", "fail", "failed"}:
        return False
    return None


def parse_number(value):
    if value is None or not str(value).strip():
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def median(values):
    return statistics.median(values) if values else None


def pct_reduction(baseline, treatment):
    if baseline is None or baseline <= 0 or treatment is None:
        return None
    return 100.0 * (baseline - treatment) / baseline


def valid_execution(row, arm):
    status = (row.get("run_status") or "").strip().lower()
    if status not in SUCCESS_STATUSES:
        return False
    required_pass = parse_bool(row.get("required_checks_pass"))
    if required_pass is False:
        return False
    if required_pass is None and arm != "original":
        return False
    if arm != "original":
        verdict = (row.get("safety_verdict") or "").strip().lower()
        if verdict not in PASS_VERDICTS:
            return False
    return True


def read_runs(path):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        missing = {"evaluation_repo_id", "arm", "run_status"} - fields
        if missing:
            raise ValueError("CSV is missing required columns: " + ", ".join(sorted(missing)))
        groups = {}
        repos = set()
        for line_number, raw in enumerate(reader, 2):
            repo = (raw.get("evaluation_repo_id") or "").strip()
            if not repo:
                raise ValueError(f"Missing evaluation_repo_id on CSV row {line_number}.")
            arm = normalized_arm(raw.get("arm") or "")
            if arm not in ARMS:
                raise ValueError(f"Unknown arm {raw.get('arm')!r} on CSV row {line_number}.")
            row = dict(raw)
            row["arm"] = arm
            row["elapsed"] = parse_number(raw.get("workflow_elapsed_seconds"))
            row["runner"] = parse_number(raw.get("sum_job_runtime_seconds"))
            row["cost"] = parse_number(raw.get("ci_cost_usd"))
            row["optimizer"] = parse_number(raw.get("optimizer_seconds"))
            row["checks"] = parse_bool(raw.get("required_checks_pass"))
            row["rag_relevant"] = parse_bool(raw.get("rag_relevant"))
            groups.setdefault((repo, arm), []).append(row)
            repos.add(repo)
    if not repos:
        raise ValueError("Input CSV has no evaluation rows.")
    if not any(arm == "original" for _, arm in groups):
        raise ValueError("Input CSV must include original-arm baseline rows.")
    return groups, sorted(repos)


def summarize_group(rows, arm):
    valid = [row for row in rows if valid_execution(row, arm)]
    all_status = [(row.get("run_status") or "").strip().lower() for row in rows]
    verdicts = [(row.get("safety_verdict") or "").strip().lower() for row in rows]
    return {
        "rows": rows,
        "run_count": sum(bool(status) for status in all_status),
        "successful_equivalent_runs": len(valid),
        "failed_or_incomplete_runs": sum(status not in SUCCESS_STATUSES for status in all_status if status),
        "elapsed_values": [row["elapsed"] for row in valid if row["elapsed"] is not None],
        "runner_values": [row["runner"] for row in valid if row["runner"] is not None],
        "cost_values": [row["cost"] for row in valid if row["cost"] is not None],
        "optimizer_values": [row["optimizer"] for row in rows if row["optimizer"] is not None],
        "pass_verdict": any(verdict in PASS_VERDICTS for verdict in verdicts),
        "no_change": any(verdict in NO_CHANGE_VERDICTS for verdict in verdicts),
        "rejected": any(verdict in {
            "fail", "failed", "reject", "rejected", "unsafe", "review_required", "inconclusive"
        } for verdict in verdicts),
        "rag_relevance": [row["rag_relevant"] for row in rows if row["rag_relevant"] is not None],
    }


def bootstrap_median_ci(values, iterations, seed):
    if not values:
        return None, None
    rng = random.Random(seed)
    n = len(values)
    samples = [statistics.median(rng.choices(values, k=n)) for _ in range(iterations)]
    samples.sort()
    lo = samples[int(0.025 * (iterations - 1))]
    hi = samples[int(0.975 * (iterations - 1))]
    return lo, hi


def analyze(groups, repos, min_savings, bootstrap_iterations, seed):
    per_repo = []
    by_repo_arm = {
        key: summarize_group(rows, key[1]) for key, rows in groups.items()
    }
    base_by_repo = {
        repo: by_repo_arm.get((repo, "original"), summarize_group([], "original"))
        for repo in repos
    }

    for repo in repos:
        base = base_by_repo[repo]
        base_elapsed = median(base["elapsed_values"])
        base_runner = median(base["runner_values"])
        base_cost = median(base["cost_values"])
        per_repo.append({
            "evaluation_repo_id": repo, "arm": "original",
            "run_count": base["run_count"],
            "successful_equivalent_runs": base["successful_equivalent_runs"],
            "safety_verdict": "BASELINE",
            "median_elapsed_seconds": base_elapsed,
            "median_runner_seconds": base_runner,
            "median_ci_cost_usd": base_cost,
            "elapsed_savings_pct": 0.0 if base_elapsed is not None else None,
            "runner_savings_pct": 0.0 if base_runner is not None else None,
            "ci_cost_savings_pct": 0.0 if base_cost is not None else None,
            "safe_candidate": True,
            "safe_beneficial": False,
            "no_change": False,
            "rejected": False,
            "optimizer_seconds_median": None,
            "rag_relevance_rate": None,
        })
        for arm in OPTIMIZERS:
            summary = by_repo_arm.get((repo, arm), summarize_group([], arm))
            elapsed = median(summary["elapsed_values"])
            runner = median(summary["runner_values"])
            cost = median(summary["cost_values"])
            safety_pass = summary["pass_verdict"]
            safe_candidate = safety_pass and summary["successful_equivalent_runs"] > 0
            elapsed_saving = pct_reduction(base_elapsed, elapsed) if safe_candidate else (
                0.0 if base_elapsed is not None else None
            )
            runner_saving = pct_reduction(base_runner, runner) if safe_candidate else (
                0.0 if base_runner is not None else None
            )
            cost_saving = pct_reduction(base_cost, cost) if safe_candidate else (
                0.0 if base_cost is not None else None
            )
            beneficial = bool(
                safe_candidate and elapsed_saving is not None and elapsed_saving > 0
                and elapsed_saving >= min_savings
            )
            relevance_rate = (
                sum(summary["rag_relevance"]) / len(summary["rag_relevance"])
                if summary["rag_relevance"] else None
            )
            verdicts = [
                (row.get("safety_verdict") or "").strip().upper()
                for row in summary["rows"] if (row.get("safety_verdict") or "").strip()
            ]
            per_repo.append({
                "evaluation_repo_id": repo, "arm": arm,
                "run_count": summary["run_count"],
                "successful_equivalent_runs": summary["successful_equivalent_runs"],
                "safety_verdict": ";".join(sorted(set(verdicts))) or "MISSING",
                "median_elapsed_seconds": elapsed,
                "median_runner_seconds": runner,
                "median_ci_cost_usd": cost,
                "elapsed_savings_pct": elapsed_saving,
                "runner_savings_pct": runner_saving,
                "ci_cost_savings_pct": cost_saving,
                "safe_candidate": safe_candidate,
                "safe_beneficial": beneficial,
                "no_change": summary["no_change"],
                "rejected": summary["rejected"],
                "optimizer_seconds_median": median(summary["optimizer_values"]),
                "rag_relevance_rate": relevance_rate if arm == "rag" else None,
            })

    summaries = []
    for arm in OPTIMIZERS:
        rows = [row for row in per_repo if row["arm"] == arm]
        elapsed = [row["elapsed_savings_pct"] for row in rows if row["elapsed_savings_pct"] is not None]
        runner = [row["runner_savings_pct"] for row in rows if row["runner_savings_pct"] is not None]
        costs = [row["ci_cost_savings_pct"] for row in rows if row["ci_cost_savings_pct"] is not None]
        ci_low, ci_high = bootstrap_median_ci(elapsed, bootstrap_iterations, seed)
        summaries.append({
            "arm": arm,
            "repositories": len(rows),
            "safe_candidate_repositories": sum(row["safe_candidate"] for row in rows),
            "safe_beneficial_repositories": sum(row["safe_beneficial"] for row in rows),
            "safe_optimization_success_rate": (
                sum(row["safe_beneficial"] for row in rows) / len(rows) if rows else None
            ),
            "no_change_repositories": sum(row["no_change"] for row in rows),
            "rejected_or_review_repositories": sum(row["rejected"] for row in rows),
            "median_elapsed_savings_pct": median(elapsed),
            "elapsed_savings_iqr_pct": (
                statistics.quantiles(elapsed, n=4)[2] - statistics.quantiles(elapsed, n=4)[0]
                if len(elapsed) >= 2 else None
            ),
            "elapsed_savings_median_bootstrap_95ci_pct": [ci_low, ci_high],
            "median_runner_savings_pct": median(runner),
            "median_ci_cost_savings_pct": median(costs),
            "median_optimizer_seconds": median([
                row["optimizer_seconds_median"] for row in rows
                if row["optimizer_seconds_median"] is not None
            ]),
            "mean_rag_relevance_rate": (
                statistics.mean([row["rag_relevance_rate"] for row in rows
                                 if row["rag_relevance_rate"] is not None])
                if arm == "rag" and any(row["rag_relevance_rate"] is not None for row in rows)
                else None
            ),
        })
    return per_repo, summaries


def write_csv(path, rows):
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_csv", type=Path, help="Run-level evaluation CSV")
    parser.add_argument("--output-dir", type=Path, default=Path("evaluation/results"))
    parser.add_argument("--min-savings-pct", type=float, default=0.0,
                        help="Minimum positive elapsed savings for a safe-benefit success")
    parser.add_argument("--bootstrap-iterations", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()
    if args.min_savings_pct < 0 or args.bootstrap_iterations < 100:
        parser.error("min-savings-pct must be non-negative and bootstrap-iterations at least 100")

    try:
        groups, repos = read_runs(args.input_csv)
        per_repo, summaries = analyze(
            groups, repos, args.min_savings_pct, args.bootstrap_iterations, args.seed
        )
        args.output_dir.mkdir(parents=True, exist_ok=True)
        write_csv(args.output_dir / "per_repository_results.csv", per_repo)
        result = {
            "input_csv": str(args.input_csv),
            "repository_count": len(repos),
            "minimum_savings_threshold_pct": args.min_savings_pct,
            "arms": summaries,
            "notes": [
                "Elapsed and runner-time savings use per-repository medians against the original arm.",
                "Candidates without PASS safety verdict and successful required checks receive zero realized savings.",
                "NO_CHANGE, rejected, and missing candidate results remain in the repository denominator.",
                "Bootstrap confidence intervals resample repositories, not individual runs.",
                "Runner seconds are a cost proxy; dollar cost is not inferred unless separately reported.",
            ],
        }
        (args.output_dir / "summary.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except (OSError, ValueError, csv.Error) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
