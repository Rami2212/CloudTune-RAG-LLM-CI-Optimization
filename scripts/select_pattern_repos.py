#!/usr/bin/env python3
"""Rank collected repositories for manual screening against literature patterns.

This is a metadata-only candidate finder. It does not establish that a pattern
applies, that a repository is safe to change, or that it is ready for an
experiment. The collected context currently omits workflow YAML bodies, matrix
details, step outputs, dependency graphs, and usable run history; the report
marks patterns that need those signals as screening-only.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATTERNS = ROOT / "knowledge" / "extracted_patterns.jsonl"
DEFAULT_OUTPUT = ROOT / "research-data" / "pattern_repo_candidates.csv"

RISK_FLAGS = {
    "SECRET_REFERENCE",
    "POSSIBLE_EXTERNAL_SIDE_EFFECT",
    "SELF_HOSTED_RUNNER",
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: expected a JSON object")
            records.append(value)
    return records


def latest_snapshot(research_data: Path) -> Path:
    candidates = sorted(
        p for p in research_data.iterdir()
        if p.is_dir() and (p / "repo_context.jsonl").is_file()
    )
    if not candidates:
        raise FileNotFoundError(
            f"No snapshot containing repo_context.jsonl found under {research_data}"
        )
    return candidates[-1]


def workflow_trigger_names(workflow: dict[str, Any]) -> set[str]:
    triggers = workflow.get("triggers")
    if isinstance(triggers, dict):
        return {str(name).lower() for name in triggers}
    if isinstance(triggers, list):
        return {str(name).lower() for name in triggers}
    return set()


def has_schedule(workflow: dict[str, Any]) -> bool:
    triggers = workflow.get("triggers")
    if isinstance(triggers, dict):
        return bool(triggers.get("schedule"))
    return isinstance(triggers, list) and "schedule" in {str(t).lower() for t in triggers}


def has_unfiltered_push_or_pr(workflow: dict[str, Any]) -> bool:
    triggers = workflow.get("triggers")
    if isinstance(triggers, list):
        return bool({str(t).lower() for t in triggers} & {"push", "pull_request", "pull_request_target"})
    if not isinstance(triggers, dict):
        return False
    for name in ("push", "pull_request", "pull_request_target"):
        trigger = triggers.get(name)
        if trigger is None or trigger == "":
            continue
        if not isinstance(trigger, dict) or not trigger.get("paths"):
            return True
    return False


def bazel_manifest(paths: list[str]) -> bool:
    names = {Path(str(path)).name.lower() for path in paths}
    # Gradle's build.gradle is not a Bazel BUILD file. Accept only Bazel's
    # conventional workspace/module/BUILD names.
    return bool(names & {"workspace", "workspace.bazel", "module", "module.bazel", "build", "build.bazel"})


def feature_for(pattern_id: str, repo: dict[str, Any]) -> tuple[int, list[str], list[str], bool]:
    """Return metadata-fit score, observed reasons, and evidence still needed."""
    workflows = [w for w in repo.get("workflows", []) if isinstance(w, dict)]
    manifests = [str(p) for p in repo.get("manifest_paths", [])]
    language = str(repo.get("language", "")).lower()
    score = 0
    reasons: list[str] = []
    missing: list[str] = []
    specific_signal = False

    if not workflows:
        return 0, ["No collected workflow metadata"], ["workflow configuration"], False

    score += 1
    reasons.append(f"{len(workflows)} collected workflow(s)")

    if pattern_id in {"P-LIT-GHA-CACHE", "P-LIT-ENV-CACHE", "P-LIT-DISTRIBUTED-CACHE"}:
        if manifests:
            score += 3
            specific_signal = True
            reasons.append(f"{len(manifests)} build/dependency manifest path(s)")
        else:
            missing.append("dependency/build manifest paths")
        missing.append("workflow steps and cache keys")

    elif pattern_id in {"P-LIT-FAIL-FAST", "P-LIT-BAZEL-PARALLEL", "P-LIT-BAZEL-INCREMENTAL", "P-LIT-BAZEL-DEPS"}:
        if pattern_id.startswith("P-LIT-BAZEL"):
            if bazel_manifest(manifests):
                score += 5
                specific_signal = True
                reasons.append("Bazel manifest/build file found")
            else:
                missing.append("Bazel manifest/build file (not present in collected manifest paths)")
        else:
            missing.append("matrix strategy and fail-fast setting (not collected)")
        missing.append("workflow YAML and actual build configuration")

    elif pattern_id in {"P-LIT-CANCEL-STALE", "P-LIT-SKIP-WORKFLOW", "P-LIT-CHANGE-FILTER"}:
        if pattern_id == "P-LIT-SKIP-WORKFLOW":
            scheduled = sum(has_schedule(w) for w in workflows)
            if scheduled:
                score += 4
                specific_signal = True
                reasons.append(f"{scheduled} scheduled workflow(s)")
            else:
                missing.append("scheduled workflow trigger")
            missing.append("evidence the scheduled work is dispensable and downstream checks remain covered")
        elif pattern_id == "P-LIT-CHANGE-FILTER":
            broad = sum(has_unfiltered_push_or_pr(w) for w in workflows)
            if broad:
                score += 3
                specific_signal = True
                reasons.append(f"{broad} push/PR workflow(s) without a collected path filter")
            else:
                missing.append("broad push/PR trigger that could be screened for path filtering")
            missing.append("required-check-to-path mapping")
        else:
            event_workflows = sum(
                bool(workflow_trigger_names(w) & {"push", "pull_request", "pull_request_target"})
                for w in workflows
            )
            if event_workflows:
                score += 2
                specific_signal = True
                reasons.append(f"{event_workflows} push/PR-triggered workflow(s)")
            missing.append("current concurrency/cancellation configuration and overlapping-run evidence")

    elif pattern_id in {"P-LIT-FAIL-SCHEDULE", "P-LIT-IDLE-SCHEDULE"}:
        scheduled = sum(has_schedule(w) for w in workflows)
        if scheduled:
            score += 4
            specific_signal = True
            reasons.append(f"{scheduled} scheduled workflow(s)")
        else:
            missing.append("scheduled workflow trigger")
        missing.append("schedule run history and owner/recovery policy")

    elif pattern_id in {"P-LIT-CUSTOM-TIMEOUT", "P-LIT-HISTORY-TIMEOUT"}:
        jobs = sum(len(w.get("jobs", [])) for w in workflows)
        if jobs:
            score += 1
            reasons.append(f"{jobs} collected job name(s)")
        missing.append("timeout settings and comparable job duration history")

    elif pattern_id in {"P-LIT-FAILED-JOB-FIRST", "P-LIT-BUILD-PRIORITY", "P-LIT-BUILD-SELECT", "P-LIT-DURATION-PREDICTION"}:
        if len(workflows) > 1:
            score += 1
            reasons.append("multiple workflows available for screening")
        missing.append("run/job history with status, duration, and queue timing")

    elif pattern_id in {"P-LIT-PRIORITIZE", "P-LIT-SELECT"}:
        if language:
            score += 1
            reasons.append(f"language metadata: {repo.get('language')}")
        if manifests:
            score += 1
            reasons.append("build/test manifest paths are available")
        missing.append("test inventory, test-to-file dependencies, and full-suite comparison")

    elif pattern_id in {"P-LIT-UNAFFECTED-STEPS", "P-LIT-UNUSED-OUTPUTS"}:
        missing.append("workflow step definitions and step dependency/output usage")

    elif pattern_id == "P-LIT-SMELL-REPAIR":
        review = sorted({str(flag) for w in workflows for flag in w.get("review", [])})
        if review:
            score += 2
            specific_signal = True
            reasons.append("workflow review flags: " + ", ".join(review))
        missing.append("specific, confirmed optimization smell and a safe remediation")

    elif pattern_id == "P-LIT-CONFIG-REUSE":
        if manifests:
            score += 2
            reasons.append("build manifests available")
        missing.append("matrix/configuration axes and proof of compatible reusable work")

    elif pattern_id in {"P-LIT-UNUSED-DEP-SKIP"}:
        if manifests:
            score += 1
            reasons.append("dependency/build manifest paths available")
        missing.append("dependency-update workflow and complete-build comparison")

    else:
        if manifests:
            score += 1
            reasons.append("build/dependency manifest paths available")
        missing.append("pattern-specific workflow or run evidence")

    if any(w.get("has_build_test_lint_hint") for w in workflows):
        score += 1
        reasons.append("at least one workflow has a build/test/lint hint")

    return score, reasons, sorted(set(missing)), specific_signal


def candidate_pool(repos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # This is for research screening only: require an active repository with at
    # least one collected workflow, while retaining REVIEW_REQUIRED candidates.
    return [
        repo for repo in repos
        if repo.get("eligibility") not in {"EXCLUDED", "COLLECTION_ERROR"}
        and not repo.get("archived", False)
        and any(isinstance(w, dict) for w in repo.get("workflows", []))
    ]


def choose_rows(patterns: list[dict[str, Any]], repos: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pattern in patterns:
        pattern_id = str(pattern.get("pattern_id", "UNKNOWN"))
        # Keep one source repository per project family in each pattern's list;
        # multiple forks of one upstream are not independent experiment targets.
        families: dict[str, tuple[Any, ...]] = {}
        for repo in repos:
            score, reasons, missing, specific_signal = feature_for(pattern_id, repo)
            workflows = [w for w in repo.get("workflows", []) if isinstance(w, dict)]
            flags = sorted({str(flag) for w in workflows for flag in w.get("review", [])})
            # Risk flags lower ranking, but are retained and shown for review.
            ranked_score = score - 3 * len(RISK_FLAGS.intersection(flags))
            family = str(repo.get("family_id") or repo.get("repo_id", ""))
            fork_penalty = int(bool(repo.get("fork")))
            item = (ranked_score, score, fork_penalty, str(repo.get("repo_id", "")).casefold(),
                    repo, reasons, missing, flags, specific_signal)
            old = families.get(family)
            if old is None or item[:4] < old[:4]:
                families[family] = item
        scored = list(families.values())
        scored.sort(key=lambda item: (-item[0], -item[1], item[3]))

        for rank, (_, score, _, _, repo, reasons, missing, flags, specific_signal) in enumerate(scored[:limit], 1):
            rows.append({
                "pattern_id": pattern_id,
                "pattern_title": pattern.get("title", ""),
                "rank": rank,
                "source_snapshot": "",
                "repo_id": repo.get("repo_id", ""),
                "family_id": repo.get("family_id", ""),
                "source_is_fork": repo.get("fork", ""),
                "source_commit_sha": repo.get("source_commit_sha", ""),
                "eligibility": repo.get("eligibility", ""),
                "eligibility_reasons": ";".join(repo.get("reasons", [])),
                "language": repo.get("language", ""),
                "score": score,
                "match_level": "metadata_signal" if specific_signal else "screening_only",
                "workflow_paths": ";".join(str(w.get("path", "")) for w in repo.get("workflows", []) if w.get("path")),
                "observed_signals": "; ".join(reasons),
                "needs_manual_check": "; ".join(missing),
                "review_flags": ";".join(flags),
                "experiment_ready": "no; baseline, safety contract, and fork/budget review are pending",
            })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, help="Snapshot directory; defaults to the latest collected snapshot")
    parser.add_argument("--patterns", type=Path, default=DEFAULT_PATTERNS, help="Pattern JSONL (default: extracted literature patterns)")
    parser.add_argument("--limit", type=int, default=5, help="Maximum candidate repositories per pattern (default: 5)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="CSV output path")
    args = parser.parse_args()

    if args.limit < 1:
        parser.error("--limit must be at least 1")
    snapshot = args.snapshot or latest_snapshot(ROOT / "research-data")
    context_path = snapshot / "repo_context.jsonl"
    if not context_path.is_file():
        parser.error(f"snapshot has no repo_context.jsonl: {context_path}")
    if not args.patterns.is_file():
        parser.error(f"patterns file not found: {args.patterns}")

    try:
        snapshot = snapshot.resolve()
        repos = candidate_pool(read_jsonl(context_path))
        patterns = read_jsonl(args.patterns)
        if not repos:
            raise ValueError("No non-excluded active repositories with collected workflow metadata")
        if not patterns:
            raise ValueError("No pattern records found")
        rows = choose_rows(patterns, repos, args.limit)
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    snapshot_label = str(snapshot.relative_to(ROOT)) if snapshot.is_relative_to(ROOT) else str(snapshot)
    for row in rows:
        row["source_snapshot"] = snapshot_label
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output = output.resolve()
    research_root = (ROOT / "research-data").resolve()
    if not output.is_relative_to(research_root):
        print(f"Error: output must be inside {research_root}", file=sys.stderr)
        return 2
    output.parent.mkdir(parents=True, exist_ok=True)
    columns = list(rows[0])
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    selected = len(rows)
    print(f"Snapshot: {snapshot.relative_to(ROOT)}")
    print(f"Patterns: {len(patterns)}; repositories screened: {len(repos)}")
    print(f"Candidate rows written: {selected} ({args.limit} max per pattern)")
    print(f"Output: {output.relative_to(ROOT)}")
    print("These are screening candidates only; inspect each row's match_level and needs_manual_check before experiments.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
