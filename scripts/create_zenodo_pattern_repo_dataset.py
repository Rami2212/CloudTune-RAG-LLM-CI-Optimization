#!/usr/bin/env python3
"""Collect workflow context and rank a fixed number of Zenodo repos per pattern."""

from __future__ import annotations

import argparse
import base64
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPOS = ROOT / "research-data" / "zenodo_20340547" / "repositories_5000.csv"
DEFAULT_PATTERNS = ROOT / "knowledge" / "extracted_patterns.jsonl"
DEFAULT_OUTPUT = ROOT / "research-data" / "zenodo_20340547" / "pattern_repo_candidates_40.csv"
DEFAULT_SNAPSHOT = ROOT / "research-data" / "zenodo_20340547" / "context_snapshot"
MANIFEST_NAMES = {
    "package.json", "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml",
    "requirements.txt", "pyproject.toml", "poetry.lock", "pipfile", "pipfile.lock",
    "go.mod", "go.sum", "cargo.toml", "cargo.lock", "pom.xml", "build.gradle",
    "build.gradle.kts", "gradle.lockfile", "composer.json", "composer.lock", "gemfile",
    "gemfile.lock", "mix.exs", "mix.lock", "pubspec.yaml", "pubspec.lock", "*.sln",
}
API_BASE = "https://api.github.com"
RAW_BASE = "https://raw.githubusercontent.com"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not {"repo_id", "branch"}.issubset(reader.fieldnames or []):
            raise ValueError(f"Repository CSV needs repo_id and branch columns: {path}")
        rows = list(reader)
    unique = {}
    for row in rows:
        repo_id = (row.get("repo_id") or "").strip().lower()
        if re.fullmatch(r"[\w.-]+/[\w.-]+", repo_id):
            row["repo_id"] = repo_id
            unique.setdefault(repo_id, row)
    return list(unique.values())


def get_json(url: str, token: str) -> dict | list:
    request = Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "CloudTune-pattern-research",
    })
    for attempt in range(4):
        try:
            with urlopen(request, timeout=45) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code in {403, 429} and attempt < 3:
                reset = exc.headers.get("X-RateLimit-Reset")
                retry_after = exc.headers.get("Retry-After")
                delay = int(retry_after or max(5, int(reset or time.time() + 5) - int(time.time()) + 1))
                time.sleep(min(delay, 3600))
                continue
            raise
        except (URLError, TimeoutError, HTTPException, ConnectionError) as exc:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError(f"GitHub request failed after retries: {url}")


def get_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": "CloudTune-pattern-research"})
    for attempt in range(4):
        try:
            with urlopen(request, timeout=45) as response:
                return response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            if exc.code in {403, 429, 502, 503, 504} and attempt < 3:
                time.sleep(2 ** (attempt + 1))
                continue
            raise
        except (URLError, TimeoutError, HTTPException, ConnectionError):
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    return ""


def actions_triggers(workflow: dict) -> dict | list:
    # PyYAML's YAML 1.1 resolver may decode the unquoted key `on` as True.
    value = workflow.get("on", workflow.get(True, {}))
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        return [value]
    return {}


def parse_workflow(path: str, text: str) -> dict:
    try:
        workflow = yaml.safe_load(text) or {}
        if not isinstance(workflow, dict):
            workflow = {}
    except yaml.YAMLError:
        workflow = {}
    jobs = workflow.get("jobs", {})
    job_names = list(jobs) if isinstance(jobs, dict) else []
    low = text.lower()
    review = []
    if re.search(r"\bsecrets\.[a-z0-9_]+", text, re.IGNORECASE):
        review.append("SECRET_REFERENCE")
    if re.search(r"pull_request_target|permissions:\s*write-all", text, re.IGNORECASE):
        review.append("POSSIBLE_EXTERNAL_SIDE_EFFECT")
    if re.search(r"runs-on:\s*['\"]?\[?self-hosted", text, re.IGNORECASE):
        review.append("SELF_HOSTED_RUNNER")
    return {
        "path": path,
        "triggers": actions_triggers(workflow),
        "jobs": job_names,
        "has_build_test_lint_hint": bool(re.search(r"\b(build|test|lint|check|verify)\b", low)),
        "review": review,
    }


def collect_one(row: dict[str, str], token: str) -> dict:
    repo_id = row["repo_id"]
    owner, repo = repo_id.split("/", 1)
    branch = (row.get("branch") or "main").strip() or "main"
    tree_url = f"{API_BASE}/repos/{owner}/{repo}/git/trees/{quote(branch, safe='')}?recursive=1"
    tree_response = get_json(tree_url, token)
    entries = tree_response.get("tree", []) if isinstance(tree_response, dict) else []
    workflow_paths = [
        entry["path"] for entry in entries
        if entry.get("type") == "blob"
        and entry.get("path", "").startswith(".github/workflows/")
        and entry.get("path", "").lower().endswith((".yml", ".yaml"))
    ]
    manifest_paths = [
        entry["path"] for entry in entries
        if entry.get("type") == "blob"
        and Path(entry.get("path", "")).name.lower() in MANIFEST_NAMES
    ]
    workflows = []
    for path in workflow_paths:
        raw_path = "/".join(quote(part, safe="") for part in path.split("/"))
        raw_url = f"{RAW_BASE}/{owner}/{repo}/{quote(branch, safe='/')}/{raw_path}"
        try:
            workflows.append(parse_workflow(path, get_text(raw_url)))
        except (HTTPError, URLError, TimeoutError):
            workflows.append({"path": path, "triggers": {}, "jobs": [], "review": [], "content_unavailable": True})

    return {
        "repo_id": repo_id,
        "family_id": repo_id,
        "fork": False,
        "archived": False,
        "eligibility": "ACTIVE" if workflows else "REVIEW_REQUIRED",
        "reasons": ["Zenodo GitHub Actions repository sample", "current workflow tree fetched from GitHub"],
        "language": row.get("language", ""),
        "source_commit_sha": tree_response.get("sha", "") if isinstance(tree_response, dict) else "",
        "manifest_paths": manifest_paths,
        "workflows": workflows,
        "tree_truncated": bool(tree_response.get("truncated", False)) if isinstance(tree_response, dict) else False,
    }


def atomic_jsonl(path: Path, rows: list[dict]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repos", type=Path, default=DEFAULT_REPOS)
    parser.add_argument("--patterns", type=Path, default=DEFAULT_PATTERNS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--per-pattern", type=int, default=40)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--max-repos", type=int, help="Optional cap for a small trial run")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    args = parser.parse_args()
    if args.per_pattern < 1 or args.workers < 1:
        parser.error("--per-pattern and --workers must be positive")

    from experiment_environment import load_env
    from select_pattern_repos import candidate_pool, choose_rows, read_jsonl

    load_env(args.env_file)
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        print("Error: set GITHUB_TOKEN or GH_TOKEN in .env", file=sys.stderr)
        return 1
    source_rows = read_csv(args.repos)
    if args.max_repos:
        source_rows = source_rows[:args.max_repos]
    args.snapshot.mkdir(parents=True, exist_ok=True)
    context_path = args.snapshot / "repo_context.jsonl"
    existing = {}
    if context_path.is_file():
        for item in read_jsonl(context_path):
            existing[item.get("repo_id", "")] = item
    pending = [row for row in source_rows if row["repo_id"] not in existing]
    errors = 0
    completed = 0
    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        future_to_row = {pool.submit(collect_one, row, token): row for row in pending}
        for future in as_completed(future_to_row):
            row = future_to_row[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {
                    "repo_id": row["repo_id"], "family_id": row["repo_id"], "fork": False,
                    "archived": False, "eligibility": "COLLECTION_ERROR",
                    "reasons": [f"GitHub context collection failed: {type(exc).__name__}"],
                    "language": row.get("language", ""), "source_commit_sha": "",
                    "manifest_paths": [], "workflows": [],
                }
                errors += 1
            existing[result["repo_id"]] = result
            completed += 1
            if completed % 25 == 0 or completed == len(pending):
                with lock:
                    ordered = [existing[k] for k in sorted(existing)]
                    atomic_jsonl(context_path, ordered)
                print(f"Collected {completed}/{len(pending)} new repos; errors={errors}", flush=True)
    contexts = [existing.get(row["repo_id"]) for row in source_rows]
    contexts = [context for context in contexts if context]
    atomic_jsonl(context_path, contexts)

    pattern_records = read_jsonl(args.patterns)
    pool = candidate_pool(contexts)
    selected = choose_rows(pattern_records, pool, args.per_pattern)
    if selected:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        fields = list(selected[0])
        with args.output.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(selected)
    counts = {}
    for record in pattern_records:
        pattern_id = record.get("pattern_id", "UNKNOWN")
        counts[pattern_id] = sum(row.get("pattern_id") == pattern_id for row in selected)
    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_repositories_csv": str(args.repos),
        "source_repository_count": len(source_rows),
        "collected_context_count": len(contexts),
        "collection_errors": errors,
        "candidate_pool_count": len(pool),
        "pattern_count": len(pattern_records),
        "requested_repositories_per_pattern": args.per_pattern,
        "selected_rows": len(selected),
        "selected_per_pattern": counts,
        "snapshot_context_file": str(context_path),
        "selection_csv": str(args.output),
        "selection_note": "Metadata-based screening candidates; manual checks listed per row are still required before experiment use.",
    }
    manifest_path = args.output.with_name("pattern_repo_manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0 if selected else 1


if __name__ == "__main__":
    raise SystemExit(main())
