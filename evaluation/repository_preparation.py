"""Read-only eligibility screening and immutable snapshots for CloudTune evaluation.

This module never creates forks, edits workflow files, enables Actions, or dispatches
runs. The execution fork adds a common ``workflow_dispatch`` harness when it is
missing, so missing dispatch alone does not block repository preparation.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import yaml

REPO_ID = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
WORKFLOW_PATH = re.compile(r"\.github/workflows/[^/]+\.ya?ml\Z")
CI_HINT = re.compile(r"\b(test|pytest|lint|build|check|npm ci)\b", re.I)
MANIFEST_NAMES = frozenset({
    "package.json", "package-lock.json", "npm-shrinkwrap.json", "pyproject.toml",
    "requirements.txt", "pom.xml", "build.gradle", "go.mod", "go.sum",
    "Cargo.toml", "Cargo.lock", "Makefile", "WORKSPACE", "MODULE.bazel",
    "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "uv.lock", "Pipfile.lock",
    "gradle.lockfile",
})
MAX_FILE_BYTES = 2_000_000
MAX_CONTEXT_FILES = 100
MAX_WORKFLOWS_TO_INSPECT = 40


class PreparationError(ValueError):
    """An ineligible or unresolved repository with a reportable reason."""

    def __init__(self, reason: str, status: str = "ineligible") -> None:
        super().__init__(reason)
        self.status = status


class ActionsLoader(yaml.SafeLoader):
    """Parse GitHub Actions 'on' as a string while retaining duplicate-key checks."""

    yaml_implicit_resolvers = {
        key: [(tag, pattern) for tag, pattern in rules if tag != "tag:yaml.org,2002:bool"]
        for key, rules in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }


ActionsLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|false|True|False|TRUE|FALSE)$"),
    list("tTfF"),
)


def _unique_mapping(loader: yaml.Loader, node: yaml.MappingNode) -> dict:
    loader.flatten_mapping(node)
    result: dict = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in result:
            raise ValueError(f"Duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=True)
    return result


ActionsLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def workflow_doc(raw: bytes) -> dict:
    """Conservative syntax validation; not a proof of workflow equivalence."""
    doc = yaml.load(raw.decode("utf-8-sig"), Loader=ActionsLoader)
    if not isinstance(doc, dict) or not isinstance(doc.get("jobs"), dict) or not doc["jobs"]:
        raise ValueError("Workflow must contain a nonempty jobs mapping")
    for job_id, job in doc["jobs"].items():
        if not isinstance(job, dict):
            raise ValueError(f"Job {job_id} must be a mapping")
        steps = job.get("steps", [])
        if not isinstance(steps, list) or any(not isinstance(step, dict) for step in steps):
            raise ValueError(f"Job {job_id} steps must be mappings")
    return doc


def has_dispatch(doc: dict) -> bool:
    triggers = doc.get("on")
    return triggers == "workflow_dispatch" or (
        isinstance(triggers, (dict, list)) and "workflow_dispatch" in triggers
    )


def has_workflow_run(doc: dict) -> bool:
    triggers = doc.get("on")
    return triggers == "workflow_run" or (
        isinstance(triggers, (dict, list)) and "workflow_run" in triggers
    )


def safety_findings(doc: dict) -> list[str]:
    """Screen only explicit high-risk workflow features for evaluation eligibility.

    This is a narrow execution-safety gate, not a comprehensive security audit.
    In particular, do not reject workflows merely because descriptive text
    mentions deployment, publishing, release, or signing. Secret references
    alone are not an eligibility blocker.
    """
    serialized = yaml.safe_dump(doc).lower()
    findings = []
    side_effect = re.compile(
        r"\b(?:npm\s+publish|docker\s+push|git\s+push|gh\s+release\s+create|"
        r"kubectl\s+(?:apply|set\s+image)|helm\s+upgrade)\b", re.IGNORECASE)
    explicit_publish_action = re.compile(
        r"(?:docker/build-push-action|softprops/action-gh-release|ncipollo/release-action)",
        re.IGNORECASE)
    has_explicit_side_effect = any(
        (isinstance(step.get("run"), str) and side_effect.search(step["run"])) or
        (isinstance(step.get("uses"), str) and explicit_publish_action.search(step["uses"]))
        for job in doc["jobs"].values()
        for step in job.get("steps", [])
    )
    if has_explicit_side_effect:
        findings.append("POSSIBLE_DEPLOY_PUBLISH_RELEASE")
    if "self-hosted" in serialized:
        findings.append("SELF_HOSTED_RUNNER")
    if any("uses" in job for job in doc["jobs"].values()):
        findings.append("REUSABLE_WORKFLOW_NOT_INSPECTED")
    return findings


def dispatch_problems(doc: dict) -> list[str]:
    problems: list[str] = []
    if not has_dispatch(doc):
        problems.append("MISSING_WORKFLOW_DISPATCH")
        return problems
    triggers = doc.get("on")
    dispatch = triggers.get("workflow_dispatch") if isinstance(triggers, dict) else None
    inputs = dispatch.get("inputs", {}) if isinstance(dispatch, dict) else {}
    if not isinstance(inputs, dict):
        problems.append("INVALID_WORKFLOW_DISPATCH_INPUTS")
        return problems
    for name, spec in inputs.items():
        if isinstance(spec, dict) and spec.get("required") in (True, "true") and "default" not in spec:
            problems.append(f"DISPATCH_INPUT_MISSING_DEFAULT:{name}")
    return problems


def validate_repo_id(repo_id: str) -> str:
    if (not REPO_ID.fullmatch(repo_id) or any(part in {".", ".."} for part in repo_id.split("/"))):
        raise ValueError(f"Invalid repository ID: {repo_id!r}")
    return repo_id


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_blob_sha1(raw: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()


def write_immutable(path: Path, raw: bytes) -> None:
    """A resumed evaluation must never overwrite a different frozen snapshot."""
    if path.exists():
        if path.read_bytes() != raw:
            raise PreparationError(f"Frozen artifact changed: {path}", "inconclusive")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation avoids silently overwriting files from a previous attempt.
    with path.open("xb") as stream:
        stream.write(raw)


def write_json_immutable(path: Path, value: Any) -> None:
    write_immutable(path, (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


class GitHubReader:
    """Small read-only GitHub REST client. Never exposes the token in artifacts."""

    def __init__(self, token: str | None = None, api_base: str = "https://api.github.com") -> None:
        self.token = token or os.getenv("GITHUB_TOKEN", "")
        self.api_base = api_base.rstrip("/")

    def get_json(self, api_path: str) -> dict:
        if not api_path.startswith("/") or ".." in api_path.split("/"):
            raise ValueError("Invalid GitHub API path")
        request = urllib.request.Request(
            self.api_base + api_path,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "CloudTune-ABC-evaluation-preparation/1.0",
                "X-GitHub-Api-Version": "2022-11-28",
                **({"Authorization": "Bearer " + self.token} if self.token else {}),
            },
        )
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=35) as response:
                    return json.loads(response.read())
            except urllib.error.HTTPError as error:
                # Retry transient service/rate-limit responses, but do not retry
                # permanent authorization or missing-repository errors.
                if error.code not in {429, 500, 502, 503, 504} or attempt == 2:
                    raise PreparationError(f"GitHub API HTTP {error.code}: {api_path}", "api_error") from error
                last_error = error
                error.close()
            except (urllib.error.URLError, TimeoutError) as error:
                if attempt == 2:
                    raise PreparationError(f"GitHub API connection failed for {api_path}", "api_error") from error
                last_error = error
            time.sleep(0.5 * (2 ** attempt))
        raise PreparationError(f"GitHub API request failed for {api_path}: {type(last_error).__name__}",
                               "api_error")

    def workflow_history(self, repo_id: str, workflow_path: str, branch: str) -> dict:
        """Read bounded, pre-evaluation CI history; never claim it is a measured baseline.

        No write permissions or fork access are required. If GitHub denies run
        history, preserve an explicit unavailable status rather than guessing.
        """
        query = urllib.parse.urlencode({"per_page": 5, "branch": branch, "status": "completed"})
        workflow_name = urllib.parse.quote(Path(workflow_path).name, safe="")
        try:
            history = self.get_json(
                f"/repos/{validate_repo_id(repo_id)}/actions/workflows/{workflow_name}/runs?{query}")
        except PreparationError as error:
            return {"status": "unavailable", "reason": error.status, "runs": []}
        rows = history.get("workflow_runs")
        if not isinstance(rows, list):
            return {"status": "unavailable", "reason": "invalid_history_response", "runs": []}
        return {"status": "historical_context_only" if rows else "no_completed_runs",
                "measurement": "not_a_measured_baseline",
                "runs": [{"run_id": item.get("id"), "head_sha": item.get("head_sha"),
                          "conclusion": item.get("conclusion"), "event": item.get("event"),
                          "created_at_utc": item.get("created_at"),
                          "updated_at_utc": item.get("updated_at")}
                         for item in rows[:5] if isinstance(item, dict)]}

    def blob(self, repo_id: str, blob_sha: str) -> bytes:
        if not re.fullmatch(r"[0-9a-fA-F]{40}", blob_sha):
            raise PreparationError("Invalid Git blob SHA", "inconclusive")
        payload = self.get_json(f"/repos/{validate_repo_id(repo_id)}/git/blobs/{blob_sha}")
        if payload.get("encoding") != "base64":
            raise PreparationError("GitHub blob response is not base64", "inconclusive")
        try:
            raw = base64.b64decode(payload["content"], validate=False)
        except (KeyError, ValueError) as error:
            raise PreparationError("Malformed GitHub blob content", "inconclusive") from error
        if git_blob_sha1(raw) != blob_sha.lower():
            raise PreparationError("Downloaded blob SHA mismatch", "inconclusive")
        return raw


def read_evaluation_rows(csv_path: Path, expected_split: str = "evaluation") -> list[dict[str, str]]:
    """Preserve the dataset's recorded ordering; do not optimize selection based on results."""
    with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not {"repo_id", "split"} <= set(reader.fieldnames):
            raise ValueError("Dataset requires repo_id and split columns")
        rows = list(reader)
    seen: set[str] = set()
    selected: list[dict[str, str]] = []
    for row in rows:
        repo_id = validate_repo_id((row.get("repo_id") or "").strip())
        key = repo_id.casefold()
        if key in seen:
            raise ValueError(f"Duplicate repository ID: {repo_id}")
        seen.add(key)
        if row.get("split") != expected_split:
            raise ValueError(f"Unexpected split for {repo_id}: {row.get('split')}")
        selected.append({**row, "repo_id": repo_id})
    if not selected:
        raise ValueError("No repository candidates in CSV")
    return selected


def excluded_repo_ids(training_csv: Path, experiment_roots: tuple[Path, ...]) -> set[str]:
    """Apply development/training exclusions before inspecting evaluation outcomes."""
    with training_csv.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or "repo_id" not in reader.fieldnames:
            raise ValueError("Training candidate dataset requires repo_id")
        excluded = {r["repo_id"].strip().casefold() for r in reader if r.get("repo_id", "").strip()}
    if not excluded:
        raise ValueError("Training candidate exclusion list is empty")
    for root in experiment_roots:
        if not root.exists():
            continue
        for case_path in root.glob("*/case.json"):
            try:
                case = json.loads(case_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                # Fail closed: an unreadable case record prevents leakage verification.
                raise PreparationError(f"Cannot verify experiment case: {case_path}", "inconclusive")
            for field in ("repo_id", "source_repo_id", "repository_id", "repository_name", "source_repo"):
                value = case.get(field)
                if isinstance(value, str) and REPO_ID.fullmatch(value.strip()):
                    excluded.add(value.strip().casefold())
    return excluded


def _get_repo_path(repo_id: str, suffix: str) -> str:
    return f"/repos/{validate_repo_id(repo_id)}{suffix}"


def _family_id(repository: dict) -> str:
    return str((repository.get("source") or repository.get("parent") or repository).get("full_name", "")).casefold()


def _context_path(path: str) -> bool:
    parts = Path(path).parts
    return (bool(parts) and not Path(path).is_absolute() and ".." not in parts and
            "\\" not in path and ":" not in path and
            (Path(path).name in MANIFEST_NAMES or bool(WORKFLOW_PATH.fullmatch(path))))


def _repository_output_dir(root: Path, repo_id: str) -> Path:
    # Hash suffix prevents collisions for names containing separators/underscores.
    slug = re.sub(r"[^A-Za-z0-9_.-]", "_", repo_id)
    return root / "repositories" / (slug + "-" + sha256(repo_id.casefold().encode())[:10])


def prepare_repository(
    row: dict[str, str], reader: GitHubReader, root: Path,
    dataset_sha256: str, excluded: set[str],
) -> dict[str, Any]:
    """Screen one repo and freeze its A candidate. Network access is read-only.

    A prior snapshot is reused as-is; a moved upstream branch does not mutate it.
    """
    repo_id = validate_repo_id(row["repo_id"])
    if repo_id.casefold() in excluded:
        raise PreparationError("Repository appears in training/development exclusions")
    folder = _repository_output_dir(root, repo_id)
    manifest_path = folder / "manifest.json"
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (old.get("repo_id", "").casefold() != repo_id.casefold() or
                old.get("dataset_sha256") != dataset_sha256):
            raise PreparationError("Saved manifest conflicts with this dataset", "inconclusive")
        if old.get("family_id", "").casefold() in excluded:
            raise PreparationError("Pinned repository now conflicts with development exclusions", "inconclusive")
        original = folder / "source" / "original.yml"
        if not original.exists() or file_sha256(original) != old.get("workflow_sha256"):
            raise PreparationError("Saved snapshot is incomplete or changed", "inconclusive")
        return {"repo_id": repo_id, "status": old["status"], "reason": "existing pinned snapshot reused",
                "workflow_path": old["workflow_path"], "source_commit_sha": old["source_commit_sha"],
                "manifest_path": str(manifest_path)}

    repository = reader.get_json(_get_repo_path(repo_id, ""))
    if repository.get("private") or repository.get("archived") or repository.get("disabled"):
        raise PreparationError("Repository is private, archived, or disabled")
    canonical_repo = str(repository.get("full_name", repo_id))
    validate_repo_id(canonical_repo)
    if _family_id(repository) in excluded or canonical_repo.casefold() in excluded:
        raise PreparationError("Repository family overlaps training/development pool")
    default_branch = repository.get("default_branch")
    if not isinstance(default_branch, str) or not default_branch:
        raise PreparationError("Repository has no default branch")
    commit = reader.get_json(_get_repo_path(repo_id, "/commits/" + urllib.parse.quote(default_branch, safe="")))
    source_commit_sha = commit.get("sha", "")
    tree_sha = (commit.get("commit") or {}).get("tree", {}).get("sha", "")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", source_commit_sha) or not re.fullmatch(r"[0-9a-fA-F]{40}", tree_sha):
        raise PreparationError("Cannot pin source commit and tree", "inconclusive")
    tree = reader.get_json(_get_repo_path(repo_id, "/git/trees/" + tree_sha + "?recursive=1"))
    if tree.get("truncated") or not isinstance(tree.get("tree"), list):
        raise PreparationError("Repository tree is truncated or unavailable", "inconclusive")
    blobs = {e["path"]: e for e in tree["tree"] if e.get("type") == "blob" and isinstance(e.get("path"), str)}
    workflow_paths = sorted(p for p in blobs if WORKFLOW_PATH.fullmatch(p))
    if not workflow_paths:
        raise PreparationError("No GitHub Actions workflow on pinned commit")
    if len(workflow_paths) > MAX_WORKFLOWS_TO_INSPECT:
        raise PreparationError("Too many workflows for complete safety screening", "inconclusive")

    options: list[tuple[tuple, str, bytes, dict]] = []
    dismissed: list[str] = []
    workflow_bytes: dict[str, bytes] = {}
    preferred = set((row.get("workflow_paths") or "").split(";"))
    for path in workflow_paths:
        entry = blobs[path]
        if entry.get("mode") == "120000" or entry.get("size", 0) > MAX_FILE_BYTES:
            raise PreparationError(f"Workflow cannot be fully inspected: {path}", "inconclusive")
        raw = reader.blob(repo_id, entry["sha"])
        workflow_bytes[path] = raw
        try:
            doc = workflow_doc(raw)
        except (ValueError, UnicodeError, yaml.YAMLError) as error:
            # One unrelated malformed workflow should not discard an otherwise
            # usable test workflow. If every candidate is malformed, the final
            # eligibility reason includes these exclusions.
            dismissed.append(f"{path}: unparseable workflow ({error})")
            continue
        if has_workflow_run(doc):
            # The isolated fork harness removes every unselected workflow.
            # Never select a listener, but do not discard unrelated safe CI.
            dismissed.append(f"{path}: workflow_run listener excluded from isolated harness")
            continue
        findings = safety_findings(doc)
        if findings:
            dismissed.append(f"{path}: {', '.join(findings)}")
            continue
        # Dispatch inputs without defaults cannot be populated safely by the
        # common A/B/C runner. Skip such workflows and prefer another test/CI
        # workflow; if none remains, preparation will mark this repository
        # ineligible and the batch can continue to the next row.
        input_problems = [problem for problem in dispatch_problems(doc)
                          if problem != "MISSING_WORKFLOW_DISPATCH"]
        if input_problems:
            dismissed.append(f"{path}: not safely dispatchable ({', '.join(input_problems)})")
            continue
        serialized = json.dumps(doc, default=str)
        hint_count = len(CI_HINT.findall(serialized))
        if hint_count == 0:
            dismissed.append(f"{path}: no clear build/test/check steps")
            continue
        # Prefer immediately dispatchable CI workflows and deterministic paths.
        rank = (not has_dispatch(doc), path not in preferred, -hint_count, path)
        options.append((rank, path, raw, doc))
    if not options:
        raise PreparationError("No safe test/build workflow found. " + "; ".join(dismissed[:8]))
    options.sort(key=lambda candidate: candidate[0])
    _, workflow_path, raw, workflow = options[0]
    problems = dispatch_problems(workflow)
    # The execution fork adds workflow_dispatch to the common A/B/C harness.
    # Missing dispatch alone therefore does not make this row ineligible.
    status = "needs_harness" if any(not item.startswith("MISSING_WORKFLOW_DISPATCH")
                                    for item in problems) else "prepared"
    screening_reason = ("workflow_dispatch will be added to the evaluation fork"
                        if "MISSING_WORKFLOW_DISPATCH" in problems and status == "prepared"
                        else "; ".join(problems))

    archived: list[dict[str, Any]] = []
    omitted: list[dict[str, str]] = []
    for path in sorted(blobs):
        if not _context_path(path):
            continue
        entry = blobs[path]
        if (entry.get("mode") == "120000" or entry.get("size", 0) > MAX_FILE_BYTES or
                len(archived) >= MAX_CONTEXT_FILES):
            omitted.append({"path": path, "reason": "symlink, oversized, or context file limit"})
            continue
        contents = workflow_bytes[path] if path in workflow_bytes else reader.blob(repo_id, entry["sha"])
        write_immutable(folder / "source" / "files" / path, contents)
        archived.append({"path": path, "git_blob_sha": entry["sha"], "sha256": sha256(contents)})
    write_immutable(folder / "source" / "original.yml", raw)
    selection = {"repo_id": repo_id, "selection_rank": row.get("selection_rank"),
                 "language": row.get("language"), "split": row.get("split")}
    write_json_immutable(folder / "selection.json", selection)
    write_json_immutable(folder / "source" / "files_manifest.json", {"archived": archived, "omitted": omitted})
    history_reader = getattr(reader, "workflow_history", None)
    ci_history = (history_reader(repo_id, workflow_path, default_branch)
                  if callable(history_reader) else {"status": "not_collected", "runs": []})
    manifest = {
        "schema_version": 1,
        "repo_id": repo_id,
        "canonical_repo_id": canonical_repo,
        "family_id": _family_id(repository),
        "dataset_sha256": dataset_sha256,
        "source_default_branch": default_branch,
        "source_commit_sha": source_commit_sha,
        "source_tree_sha": tree_sha,
        "workflow_path": workflow_path,
        "workflow_blob_sha": blobs[workflow_path]["sha"],
        "workflow_sha256": sha256(raw),
        "status": status,
        "dispatch_problems": problems,
        "context_files_archived": len(archived),
        "context_files_omitted": len(omitted),
        "ci_history": ci_history,
        "required_checks": {"status": "not_verified", "reason": "Requires branch-protection and/or baseline evidence"},
        "notes": ["Read-only snapshot. No fork, workflow mutation, CI dispatch, or baseline execution performed.",
                  "Safety screening is conservative, not a semantic equivalence proof."],
    }
    write_json_immutable(folder / "manifest.json", manifest)
    return {"repo_id": repo_id, "status": status, "reason": screening_reason,
            "workflow_path": workflow_path, "source_commit_sha": source_commit_sha,
            "manifest_path": str(manifest_path)}
