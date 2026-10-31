"""Build a JSONL retrieval dataset from literature patterns and saved experiments."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = ROOT / "knowledge" / "extracted_patterns.jsonl"
MAIN_EXPERIMENTS = ROOT / "research-data" / "experiments"
SCENARIO_EXPERIMENTS = ROOT / "research-data" / "scenario-experiments"
DEFAULT_OUTPUT = ROOT / "research-data" / "rag" / "rag_dataset.jsonl"
RAG_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
OMIT_FIELDS = {
    "local_outcome", "llm", "pattern_satisfaction_scope", "protocol", "reasons",
    "source_repo_id", "source_repo", "repo_id", "repo_ids", "repository_id",
    "repository_name", "repository", "fork_repo", "family_id", "source_commit_sha",
    "config_commit_sha",
}


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_jsonl(path: Path) -> list[dict]:
    records = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in {path} line {number}: {exc}") from exc
    return records


def safe_artifact(ref: str | None) -> tuple[str, bytes] | None:
    if not ref:
        return None
    # Stored refs use repository-relative paths; accept older Windows separators too.
    path = ROOT.joinpath(*ref.replace("\\", "/").split("/"))
    resolved = path.resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        raise ValueError(f"Artifact path escapes repository: {ref}")
    if not resolved.is_file():
        return None
    return ref.replace("\\", "/"), resolved.read_bytes()


def artifact_entry(name: str, ref: str | None) -> dict | None:
    loaded = safe_artifact(ref)
    if loaded is None:
        return None
    _, raw = loaded
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        return {"sha256": digest(raw), "encoding": "binary", "content": None}
    return {"sha256": digest(raw), "encoding": "utf-8", "content": content}


def without_paths(value):
    """Remove local paths, excluded metadata, and only inconclusive outcome fields."""
    if isinstance(value, dict):
        return {
            key: without_paths(item)
            for key, item in value.items()
            if key.lower() not in OMIT_FIELDS
            and not (key == "outcome" and item == "inconclusive")
            and not key.endswith(("_ref", "_path"))
            and key not in {"path", "workflow_path"}
        }
    if isinstance(value, list):
        return [without_paths(item) for item in value]
    return value


def pattern_document(pattern: dict) -> dict:
    example = pattern.get("example") or {}
    artifacts = {}
    for name in ("before", "after", "diff"):
        item = artifact_entry(name, example.get(name + "_ref"))
        if item:
            artifacts[name] = item
    source_text = "; ".join(
        f"{source.get('title')} ({source.get('year')}), {source.get('locator')}: {source.get('url')}"
        for source in pattern.get("sources", []))
    sections = [pattern.get("title", ""), f"Pattern: {pattern['pattern_id']} ({pattern.get('mechanism', '')})",
                pattern.get("research_question", ""), pattern.get("optimization_question", ""),
                "Preconditions: " + "; ".join(pattern.get("preconditions", [])),
                "Contraindications: " + "; ".join(pattern.get("contraindications", [])),
                "Method: " + "; ".join(pattern.get("method", [])),
                "Reported finding: " + pattern.get("reported_result", {}).get("finding", ""),
                "Reported metrics: " + json.dumps(pattern.get("reported_result", {}).get("metrics", {}), sort_keys=True),
                "Source: " + source_text]
    for name in ("before", "after", "diff"):
        if name in artifacts:
            sections += [f"Literature example {name}:", artifacts[name]["content"] or ""]
    approved_pattern = without_paths(pattern)
    # User has confirmed manual review of the pattern collection.
    approved_pattern["status"] = "reviewed"
    return {"document_id": "pattern:" + pattern["pattern_id"], "record_type": "pattern",
            "pattern_id": pattern["pattern_id"], "title": pattern.get("title"),
            "model": RAG_MODEL,
            "evidence_scope": "literature_report_and_analyst_example",
            "rag_status": "approved_for_rag",
            "retrieval_eligible": True,
            "text": "\n\n".join(section for section in sections if section),
            "pattern": approved_pattern, "artifacts": artifacts, "experiment_document_ids": []}


def read_case_runs(case: dict) -> list:
    item = safe_artifact(case.get("run_records_ref"))
    if not item:
        return []
    try:
        return json.loads(item[1].decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return []


def case_artifacts(case: dict, folder: Path) -> dict:
    refs = {"before": case.get("before_ref"), "after": case.get("after_ref"),
            "diff": case.get("patch_ref")}
    if case.get("record_kind") == "controlled_pattern_scenario":
        refs.update(before="research-data/scenario-experiments/" + folder.name + "/before.yml",
                    after="research-data/scenario-experiments/" + folder.name + "/after.yml",
                    diff="research-data/scenario-experiments/" + folder.name + "/change.diff")
        for name in ("workflow_change.diff", "before_policy.yml", "after_policy.yml"):
            refs[name] = "research-data/scenario-experiments/" + folder.name + "/" + name
    artifacts = {}
    for name, ref in refs.items():
        entry = artifact_entry(name, ref)
        if entry:
            artifacts[name] = entry
    return artifacts


def experiment_document(case: dict, folder: Path) -> dict:
    runs = read_case_runs(case)
    artifacts = case_artifacts(case, folder)
    evidence_scope = case.get("evidence_scope", "measured_ci_workflow_on_fork")
    outcome = case.get("outcome")
    sections = [f"Experiment example for {case.get('pattern_id')}"]
    if outcome != "inconclusive":
        sections.append(f"Outcome: {outcome}; RAG admission: approved_for_rag; evidence scope: {evidence_scope}.")
    else:
        sections.append(f"RAG admission: approved_for_rag; evidence scope: {evidence_scope}.")
    sections += [
                f"Case: {case.get('case_id')}.",
                "Arm metrics: " + json.dumps(case.get("arms", {}), sort_keys=True),
                "Elapsed savings percent: " + str(case.get("elapsed_savings_percent", "not measured")),
                "This record is experimental evidence, not a recommendation. Check its outcome, evidence scope, and safety caveats."]
    if case.get("limitations"):
        sections.insert(-1, "Limitations: " + "; ".join(case["limitations"]))
    for name in ("before", "after", "diff", "workflow_change.diff", "before_policy.yml", "after_policy.yml"):
        if name in artifacts:
            sections.extend([f"Artifact {name}:", artifacts[name]["content"] or ""])
    approved_case = without_paths(case)
    approved_case["rag_admission"] = "approved_for_rag"
    clean_runs = without_paths(runs)
    return {"document_id": "experiment:" + str(case.get("case_id", folder.name)),
            "record_type": "experiment_example", "pattern_id": case.get("pattern_id"),
            "title": (f"{case.get('pattern_id')} experiment: {outcome}"
                      if outcome != "inconclusive" else f"{case.get('pattern_id')} experiment example"),
            "model": RAG_MODEL,
            "evidence_scope": evidence_scope,
            **({"outcome": outcome} if outcome != "inconclusive" else {}),
            "pattern_satisfied": True,
            "rag_status": "approved_for_rag", "retrieval_eligible": True,
            "text": "\n\n".join(section for section in sections if section),
            "experiment": approved_case, "runs": clean_runs, "artifacts": artifacts}


def build(output: Path) -> dict:
    patterns = load_jsonl(PATTERNS)
    by_id = {record["pattern_id"]: record for record in patterns}
    if len(by_id) != len(patterns):
        raise ValueError("Pattern registry has duplicate pattern IDs")
    documents = [pattern_document(record) for record in patterns]
    patterns_by_id = {doc["pattern_id"]: doc for doc in documents}
    experiment_dirs = []
    for parent in (MAIN_EXPERIMENTS, SCENARIO_EXPERIMENTS):
        if parent.exists():
            experiment_dirs.extend(sorted(p for p in parent.iterdir() if p.is_dir()))
    included = 0
    for folder in experiment_dirs:
        case_path = folder / "case.json"
        if not case_path.is_file():
            continue
        case = json.loads(case_path.read_text(encoding="utf-8"))
        pattern_id = case.get("pattern_id")
        if pattern_id not in by_id or case.get("pattern_satisfied") is not True:
            continue
        document = experiment_document(case, folder)
        documents.append(document)
        patterns_by_id[pattern_id]["experiment_document_ids"].append(document["document_id"])
        included += 1

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        for document in documents:
            handle.write(json.dumps(document, ensure_ascii=False, sort_keys=True) + "\n")
    # Read the emitted JSONL back before recording the manifest.
    written = load_jsonl(output)
    if len(written) != len(documents) or len({doc["document_id"] for doc in written}) != len(written):
        raise ValueError("Generated RAG dataset has missing or duplicate document IDs")
    output_hash = digest(output.read_bytes())
    counts = Counter(doc["record_type"] for doc in written)
    eligible = sum(bool(doc["retrieval_eligible"]) for doc in written)
    examples_by_pattern: dict[str, list[dict]] = {pattern_id: [] for pattern_id in by_id}
    ungrouped_examples = []
    for document in written:
        if document["record_type"] != "experiment_example":
            continue
        example = {key: value for key, value in document.items() if key not in {"pattern_id"}}
        pattern_id = document.get("pattern_id")
        if pattern_id in examples_by_pattern:
            examples_by_pattern[pattern_id].append(example)
        else:
            ungrouped_examples.append(example)
    grouped_patterns = []
    for record in patterns:
        pattern_doc = patterns_by_id[record["pattern_id"]]
        grouped_patterns.append({
            "pattern_id": record["pattern_id"],
            "title": record.get("title"),
            "model": pattern_doc["model"],
            "rag_status": pattern_doc["rag_status"],
            "retrieval_eligible": pattern_doc["retrieval_eligible"],
            "pattern": pattern_doc["pattern"],
            "literature_example": pattern_doc["artifacts"],
            "search_text": pattern_doc["text"],
            "experiment_examples": examples_by_pattern[record["pattern_id"]],
        })
    structured = {
        "dataset_version": 1,
        "dataset_type": "cloudtune_pattern_and_experiment_rag_corpus",
        "description": "Literature-derived CI optimization patterns linked to their illustrative examples and saved experiments.",
        "admission_policy": {
            "approval_basis": "User confirmed manual review of the pattern collection and qualifying experiment examples.",
            "retrieval_eligible_means": "The record is approved for RAG retrieval; experiment examples must also have pattern_satisfied=true.",
            "exclude_when_false": True,
            "experiment_examples_require": "pattern_satisfied=true; if outcome is inconclusive, retain the example but omit its inconclusive outcome field. Synthetic scenarios remain clearly identified and are not real repository speedup evidence.",
        },
        "summary": {
            "pattern_count": len(grouped_patterns),
            "experiment_example_count": counts["experiment_example"],
            "retrieval_eligible_count": eligible,
            "pending_review_count": len(written) - eligible,
        },
        "patterns": grouped_patterns,
        "ungrouped_experiment_examples": ungrouped_examples,
    }
    structured_path = output.with_suffix(".json")
    structured_bytes = (json.dumps(structured, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    structured_path.write_bytes(structured_bytes)
    manifest = {"dataset_version": 1, "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "dataset_path": str(output.resolve().relative_to(ROOT)), "dataset_sha256": output_hash,
                "structured_json_path": str(structured_path.resolve().relative_to(ROOT)),
                "structured_json_sha256": digest(structured_bytes),
                "source_patterns": "knowledge/extracted_patterns.jsonl",
                "source_experiment_roots": [str(p.relative_to(ROOT)) for p in (MAIN_EXPERIMENTS, SCENARIO_EXPERIMENTS)],
                "document_count": len(written), "pattern_document_count": counts["pattern"],
                "experiment_example_count": counts["experiment_example"],
                "retrieval_eligible_count": eligible,
                "pending_review_count": len(written) - eligible,
                "note": "This is a retrieval dataset build. It contains approved pattern records and all pattern-satisfied experiments; inconclusive outcome fields and repository identifiers/local paths are omitted. It does not create embeddings or ingest a vector index."}
    manifest_path = output.with_name(output.stem + "_manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help=f"Output JSONL path (default: {DEFAULT_OUTPUT})")
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    try:
        build(output.resolve())
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print("Error: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
