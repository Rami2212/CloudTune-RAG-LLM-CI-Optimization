"""Complete bounded text inputs with hashes and explicit collection omissions."""
from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath

from evaluation.repository_preparation import (
    MANIFEST_NAMES, git_blob_sha1, validate_repo_id, write_immutable, write_json_immutable,
)
from .registry import digest
from .progress import progress

CONTEXT_VERSION = "full-pattern-context-v1"
EXTRA_NAMES = {"mise.toml", ".mise.toml", "mise.lock", ".bazelrc", ".bazelversion",
               "BUILD", "BUILD.bazel", "WORKSPACE.bazel", "MODULE.bazel.lock", "settings.gradle",
               "settings.gradle.kts", "build.gradle.kts", "gradle.properties", "tox.ini",
               "pytest.ini", "setup.cfg", "setup.py", "justfile", "Taskfile.yml",
               "composer.json", "composer.lock", "Gemfile", "Gemfile.lock", ".tool-versions"}
SECRET = re.compile(r"(?i)(?:private[_ -]?key|api[_-]?key|access[_-]?key|password|token|credential|secret|authorization)\s*[:=]\s*['\"]?[^\s'\"]+|https?://[^\s/]+:[^\s/@]+@|-----BEGIN .*PRIVATE KEY-----|\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-or-v1-[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16})\b")


def safe_path(value: str) -> str:
    if (not isinstance(value, str) or not value or "\\" in value or ":" in value
            or value.startswith("/") or any(p in {"", ".", ".."} for p in value.split("/"))):
        raise ValueError("Unsafe repository-relative path")
    if any(p.casefold() in {".git", ".aws", ".ssh", ".codex", ".agents"} for p in value.split("/")):
        raise ValueError("Private metadata path is not repository evidence")
    name = PurePosixPath(value).name.casefold()
    if name == ".env" or name.startswith(".env.") or name in {".npmrc", ".pypirc", ".netrc", "_netrc"}:
        raise ValueError("Credential configuration is not repository evidence")
    return value


def read_source(root: Path, relative: str) -> bytes:
    relative = safe_path(relative)
    path = root / relative
    # Reject symlink ancestors too: a safe-looking relative name can escape.
    if any(p.is_symlink() for p in [root, *[root / Path(*PurePosixPath(relative).parts[:i])
                                         for i in range(1, len(PurePosixPath(relative).parts) + 1)]]):
        raise ValueError("Symlink evidence is not allowed")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Evidence escaped source root")
    return path.read_bytes()


def is_context_file(path: str) -> bool:
    try:
        safe_path(path)
    except ValueError:
        return False
    name = PurePosixPath(path).name
    return (name in MANIFEST_NAMES | EXTRA_NAMES or
            (path.startswith(".github/workflows/") and name.endswith((".yml", ".yaml"))) or
            (path.startswith(".github/actions/") and name in {"action.yml", "action.yaml"}))


def collect_context(snapshot: Path, output: Path, *, reader, max_files: int = 100,
                    max_file_bytes: int = 65536, max_total_bytes: int = 262144) -> dict:
    """Read extra files at the pinned tree; never rewrite the legacy snapshot.

    No repository code is executed. Text references may select additional blobs
    only when those paths exist in the frozen source tree. Large files are
    disclosed as omitted instead of forwarding misleading partial file contents.
    """
    if min(max_files, max_file_bytes, max_total_bytes) < 1:
        raise ValueError("Context limits must be positive")
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    repo = validate_repo_id(manifest["repo_id"])
    tree_sha = manifest["source_tree_sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", tree_sha):
        raise ValueError("Pinned source tree SHA is invalid")
    identity = {"version": CONTEXT_VERSION, "manifest_sha256": digest((snapshot / "manifest.json").read_bytes()),
                "max_files": max_files, "max_file_bytes": max_file_bytes, "max_total_bytes": max_total_bytes}
    archive = output / "context_manifest.json"
    if archive.exists():
        old = json.loads(archive.read_text(encoding="utf-8"))
        if old.get("identity") != identity:
            raise ValueError("Archived context identity changed; use a new output directory")
        for entry in old["archived"]:
            if digest(read_source(output / "files", entry["path"])) != entry["sha256"]:
                raise ValueError("Archived extended context changed")
        progress("CONTEXT",f"Restored {len(old['archived'])} frozen context files; omissions={len(old['omitted'])}")
        return old
    progress("CONTEXT",f"{repo}: reading pinned tree {tree_sha[:12]}")
    tree = reader.get_json(f"/repos/{repo}/git/trees/{tree_sha}?recursive=1")
    if tree.get("truncated") or not isinstance(tree.get("tree"), list):
        raise ValueError("Cannot collect complete pinned tree listing")
    blobs = {e["path"]: e for e in tree["tree"] if e.get("type") == "blob" and isinstance(e.get("path"), str)}
    original = (snapshot / "source/original.yml").read_bytes()
    if digest(original) != manifest["workflow_sha256"]:
        raise ValueError("Pinned original workflow changed")
    archived, omitted, seen = [], [], set()
    pending = sorted(p for p in blobs if is_context_file(p))
    # Include existing local action and script references before unrelated manifests.
    def references(text):
        return sorted({p for p in blobs if len(p) > 2 and p in text and
                       not p.endswith((".png", ".jpg", ".zip", ".pdf"))})
    pending = references(original.decode("utf-8-sig")) + pending
    total = 0
    while pending:
        path = pending.pop(0)
        if path in seen:
            continue
        seen.add(path)
        try:
            safe_path(path)
        except ValueError:
            omitted.append({"path": path, "reason": "unsafe_path"})
            continue
        item = blobs[path]
        if item.get("mode") == "120000":
            omitted.append({"path": path, "reason": "symlink"})
            continue
        if len(archived) >= max_files or item.get("size", max_file_bytes + 1) > max_file_bytes:
            omitted.append({"path": path, "reason": "collection_budget"})
            continue
        raw = reader.blob(repo, item["sha"])
        if git_blob_sha1(raw) != item["sha"]:
            raise ValueError("Git blob content differs from pinned source tree")
        if len(raw) > max_file_bytes or total + len(raw) > max_total_bytes:
            omitted.append({"path": path, "reason": "collection_budget"})
            continue
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeError:
            omitted.append({"path": path, "reason": "non_text"})
            continue
        if SECRET.search(text) or "\0" in text:
            omitted.append({"path": path, "reason": "sensitive_or_binary"})
            continue
        write_immutable(output / "files" / path, raw)
        archived.append({"path": path, "sha256": digest(raw), "git_blob_sha": item["sha"]})
        progress("CONTEXT",f"[{len(archived)}/{max_files}] archived {path}; bytes={len(raw)}")
        total += len(raw)
        pending = references(text) + pending
    result = {"identity": identity, "archived": archived, "omitted": omitted,
              "tree_blob_count": len(blobs), "bytes": total,
              "coverage": "bounded_configuration_and_referenced_files; not a complete dependency graph"}
    write_json_immutable(archive, result)
    progress("CONTEXT",f"Collection complete: files={len(archived)}; omitted={len(omitted)}; bytes={total}")
    return result


def build_context(snapshot: Path, *, extended: Path | None = None,
                  max_chars: int = 48000) -> dict:
    if max_chars < 1:
        raise ValueError("Prompt context budget must be positive")
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    original = (snapshot / "source/original.yml").read_bytes()
    if digest(original) != manifest["workflow_sha256"]:
        raise ValueError("Pinned original workflow changed")
    if SECRET.search(original.decode("utf-8-sig")):
        raise ValueError("Original workflow contains possible credentials; do not forward to model")
    entries = json.loads((snapshot / "source/files_manifest.json").read_text(encoding="utf-8"))
    files, omitted, available = {}, list(entries.get("omitted", [])), {}
    sources = [(snapshot / "source/files", entries)]
    if extended is not None:
        ext = json.loads((extended / "context_manifest.json").read_text(encoding="utf-8"))
        if ext["identity"]["manifest_sha256"] != digest((snapshot / "manifest.json").read_bytes()):
            raise ValueError("Extended context belongs to a different source snapshot")
        sources.append((extended / "files", ext))
        omitted.extend(ext["omitted"])
    for root, listing in sources:
        for item in listing["archived"]:
            path = safe_path(item["path"])
            raw = read_source(root, path)
            if digest(raw) != item["sha256"]:
                raise ValueError("Frozen repository context changed")
            if path in available and available[path] != item["sha256"]:
                raise ValueError("Conflicting source context hashes")
            available[path] = item["sha256"]
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeError:
                omitted.append({"path": path, "reason": "non_text"})
                continue
            if SECRET.search(text) or "\0" in text:
                omitted.append({"path": path, "reason": "sensitive_or_binary"})
                continue
            files[path] = text
    # Referenced scripts and root tool configuration precede nested manifests.
    original_text = original.decode("utf-8-sig")
    if len(original_text) > max_chars:
        raise ValueError("Complete original workflow exceeds prompt context budget")
    ordered = sorted(files, key=lambda p: (p not in original_text, p.count("/"), p))
    included, used = [], len(original_text)
    for path in ordered:
        text = files[path]
        if used + len(text) > max_chars:
            omitted.append({"path": path, "reason": "prompt_budget; full file omitted"})
            continue
        included.append({"path": path, "text": text, "sha256": available[path]})
        used += len(text)
    # Metadata is also untrusted and may contain workflow/job names or URLs.
    metadata = {k: manifest.get(k, {"status": "not_collected"}) for k in ("ci_history", "required_checks")}
    for key, value in list(metadata.items()):
        serialized = json.dumps(value, ensure_ascii=False)
        if SECRET.search(serialized) or len(serialized) > 16000:
            metadata[key] = {"status": "omitted", "reason": "sensitive_or_metadata_budget"}
    return {"version": CONTEXT_VERSION, "source_commit_sha": manifest["source_commit_sha"],
            "workflow_path": manifest["workflow_path"], "workflow_sha256": manifest["workflow_sha256"],
            "original_workflow": original_text, "files": included, "omitted": omitted,
            "available_paths": sorted(available), "included_paths": [x["path"] for x in included],
            "context_complete": False, "coverage": "bounded source snapshot; absence is not non-applicability",
            **metadata}
