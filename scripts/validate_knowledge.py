"""Validate Phase B records and optionally check archived source/example integrity."""
import argparse
import difflib
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "knowledge/extracted_patterns.jsonl"
EVIDENCE_TYPES = {"observational", "simulation_estimate", "controlled_execution", "guidance"}
REVIEWED_FIELDS = {
    "preconditions", "contraindications", "affected_checks", "implementation_notes",
    "evidence_type", "sources", "expected_direction", "safety_tests", "reviewed_by", "reviewed_at",
}
ALLOWED_FIELDS = {
    "pattern_id", "title", "mechanism", "status", "research_question", "preconditions",
    "contraindications", "affected_checks", "implementation_notes", "evidence_type", "sources",
    "expected_direction", "safety_tests", "reviewed_by", "reviewed_at",
}
ALLOWED_FIELDS.update({"paper_id", "extraction_status", "optimization_question", "method", "scope",
                      "success_status", "local_outcome", "reported_result", "example", "related_pattern_ids"})


def validate_extraction(record, label):
    errors = []
    required = {"paper_id", "optimization_question", "method", "scope", "success_status", "local_outcome",
                "reported_result", "example", "related_pattern_ids"}
    if required - record.keys():
        errors.append(f"{label}: full-text record missing {sorted(required - record.keys())}")
    if not isinstance(record.get("paper_id"), str) or not re.fullmatch(r"S[0-9]{2}", record["paper_id"]):
        errors.append(f"{label}: invalid paper_id")
    if not isinstance(record.get("optimization_question"), str) or not record.get("optimization_question", "").strip():
        errors.append(f"{label}: optimization_question must be non-empty")
    method = record.get("method")
    if not isinstance(method, list) or not method or not all(isinstance(x, str) and x.strip() for x in method):
        errors.append(f"{label}: method must be a non-empty list of instructions")
    if record.get("scope") not in ("workflow_yaml", "build_configuration", "ci_service", "research_only"):
        errors.append(f"{label}: invalid scope")
    if record.get("success_status") not in ("reported_benefit", "estimated_benefit", "mixed_results", "secondary_report_only", "no_direct_speedup_evidence"):
        errors.append(f"{label}: invalid literature success_status")
    if record.get("local_outcome") != "not_evaluated":
        errors.append(f"{label}: literature patterns cannot assert local experiment outcomes")
    result = record.get("reported_result")
    if not isinstance(result, dict) or set(result) != {"finding", "metrics", "pdf_pages", "locator"}:
        errors.append(f"{label}: reported_result must contain finding, metrics, pdf_pages and locator")
    else:
        for field in ("finding", "locator"):
            if not isinstance(result[field], str) or not result[field].strip():
                errors.append(f"{label}: result {field} must be non-empty")
        pages = result["pdf_pages"]
        if not isinstance(pages, list) or not pages or not all(type(x) is int and x > 0 for x in pages) or len(pages) != len(set(pages)):
            errors.append(f"{label}: pdf_pages must be unique positive integers")
        if not isinstance(result["metrics"], dict):
            errors.append(f"{label}: metrics must be an object")
    example = record.get("example")
    expected = {"origin", "format", "before_ref", "after_ref", "diff_ref", "source_before_ref", "source_after_ref", "source_diff_ref", "source_artifact_note", "before_sha256", "after_sha256", "diff_sha256"}
    if not isinstance(example, dict) or set(example) != expected:
        errors.append(f"{label}: example has missing or unknown fields")
    else:
        if example["origin"] != "analyst_illustration_not_executed" or example["format"] != "pseudocode":
            errors.append(f"{label}: example must identify unexecuted illustrative pseudocode")
        for field in ("before_ref", "after_ref", "diff_ref", "source_artifact_note"):
            if not isinstance(example[field], str) or not example[field].strip():
                errors.append(f"{label}: example {field} must be non-empty")
        for field in ("before_sha256", "after_sha256", "diff_sha256"):
            if not isinstance(example[field], str) or not re.fullmatch(r"[a-f0-9]{64}", example[field]):
                errors.append(f"{label}: invalid example {field}")
        for field in ("source_before_ref", "source_after_ref", "source_diff_ref"):
            if example[field] is not None:
                errors.append(f"{label}: illustrative examples must not claim original source artifacts")
    related = record.get("related_pattern_ids")
    if not isinstance(related, list) or not all(isinstance(x, str) and re.fullmatch(r"P-[A-Z0-9-]+", x) for x in related):
        errors.append(f"{label}: invalid related_pattern_ids")
    return errors


def validate_record(record, line_number):
    errors = []
    label = f"line {line_number}"
    if not isinstance(record, dict):
        return [f"{label}: record must be a JSON object"]
    extra = set(record) - ALLOWED_FIELDS
    if extra:
        errors.append(f"{label}: unknown fields: {', '.join(sorted(extra))}")
    for field in ("pattern_id", "title", "mechanism", "status"):
        if not isinstance(record.get(field), str) or not record[field].strip():
            errors.append(f"{label}: '{field}' must be a non-empty string")
    if isinstance(record.get("pattern_id"), str) and not re.fullmatch(r"P-[A-Z0-9-]+", record["pattern_id"]):
        errors.append(f"{label}: pattern_id must match P-[A-Z0-9-]+")
    status = record.get("status")
    if status not in ("draft", "reviewed"):
        errors.append(f"{label}: status must be 'draft' or 'reviewed'")
    complete = record.get("extraction_status") == "full_text_extracted"
    if "extraction_status" in record and not complete:
        errors.append(f"{label}: invalid extraction_status")
    if complete:
        errors.extend(validate_extraction(record, label))
    if status == "reviewed" or complete:
        required = REVIEWED_FIELDS if status == "reviewed" else REVIEWED_FIELDS - {"reviewed_by", "reviewed_at"}
        missing = required - record.keys()
        if missing:
            errors.append(f"{label}: reviewed record missing: {', '.join(sorted(missing))}")
        for field in ("preconditions", "contraindications", "affected_checks", "implementation_notes", "safety_tests"):
            if field in record and (not isinstance(record[field], list) or not all(isinstance(x, str) and x.strip() for x in record[field])):
                errors.append(f"{label}: '{field}' must be an array of non-empty strings")
        if not isinstance(record.get("evidence_type"), str) or record["evidence_type"] not in EVIDENCE_TYPES:
            errors.append(f"{label}: evidence_type must be one of {', '.join(sorted(EVIDENCE_TYPES))}")
        if not isinstance(record.get("expected_direction"), str) or not record.get("expected_direction", "").strip():
            errors.append(f"{label}: expected_direction must be a non-empty string")
        if status == "reviewed" and (not isinstance(record.get("reviewed_by"), str) or not record.get("reviewed_by", "").strip()):
            errors.append(f"{label}: reviewed_by must be a non-empty string")
        try:
            if status == "reviewed":
                date.fromisoformat(record.get("reviewed_at", ""))
        except (TypeError, ValueError):
            errors.append(f"{label}: reviewed_at must be an ISO date (YYYY-MM-DD)")
        sources = record.get("sources")
        if not isinstance(sources, list) or not sources:
            errors.append(f"{label}: reviewed record must contain at least one source")
        else:
            for index, source in enumerate(sources, 1):
                source_label = f"{label}: source {index}"
                if not isinstance(source, dict):
                    errors.append(f"{source_label} must be an object")
                    continue
                for field in ("title", "url", "year", "locator"):
                    if field not in source:
                        errors.append(f"{source_label} missing '{field}'")
                for field in ("title", "locator"):
                    if not isinstance(source.get(field), str) or not source.get(field, "").strip():
                        errors.append(f"{source_label}: {field} must be non-empty")
                url = source.get("url", "")
                try:
                    parsed = urlparse(url) if isinstance(url, str) else None
                except ValueError:
                    parsed = None
                if not parsed or parsed.scheme not in ("http", "https") or not parsed.netloc:
                    errors.append(f"{source_label}: url must be an http(s) URL")
                if not isinstance(source.get("year"), int) or isinstance(source.get("year"), bool) or source.get("year", 0) < 1900:
                    errors.append(f"{source_label}: year must be an integer >= 1900")
    return errors


def check_artifacts(records):
    errors = []
    papers = {}

    def checked_path(ref, expected_hash):
        if not isinstance(ref, str) or not isinstance(expected_hash, str):
            raise ValueError("missing artifact path or hash")
        target = (ROOT / ref).resolve()
        target.relative_to(ROOT)
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected_hash:
            raise ValueError(f"hash mismatch: {ref}")
        return target

    try:
        for line in (ROOT / "knowledge/papers.jsonl").read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            paper = json.loads(line)
            if paper["paper_id"] in papers:
                raise ValueError("duplicate paper_id")
            papers[paper["paper_id"]] = paper
            checked_path(paper["fulltext_ref"], paper["pdf_sha256"])
            checked_path(paper["text_ref"], paper["text_sha256"])
        ids = {r["pattern_id"] for r in records}
        for record in records:
            paper = papers[record["paper_id"]]
            if any(page > paper["page_count"] for page in record["reported_result"]["pdf_pages"]):
                raise ValueError(f"{record['pattern_id']}: source page exceeds PDF length")
            if not record["sources"] or any(s["url"] != paper["url"] or s["title"] != paper["title"] or s["year"] != paper["year"] for s in record["sources"]):
                raise ValueError(f"{record['pattern_id']}: source does not match paper registry")
            if not set(record["related_pattern_ids"]) <= ids:
                raise ValueError(f"{record['pattern_id']}: unknown related pattern")
            if paper["evidence_tier"] == "secondary" and record["success_status"] not in {"secondary_report_only", "no_direct_speedup_evidence"}:
                raise ValueError("secondary findings cannot claim primary success")
            example = record["example"]
            paths = {k: checked_path(example[k + "_ref"], example[k + "_sha256"]) for k in ("before", "after", "diff")}
            expected = "".join(difflib.unified_diff(paths["before"].read_text(encoding="utf-8").splitlines(keepends=True), paths["after"].read_text(encoding="utf-8").splitlines(keepends=True), fromfile=example["before_ref"], tofile=example["after_ref"]))
            if paths["diff"].read_text(encoding="utf-8") != expected:
                raise ValueError(f"{record['pattern_id']}: diff does not match before/after")
        manifest = json.loads((ROOT / "knowledge/extraction_manifest.json").read_text(encoding="utf-8"))
        if manifest["paper_count"] != len(papers) or manifest["pattern_count"] != len(records):
            raise ValueError("manifest counts mismatch")
        checked_path("knowledge/papers.jsonl", manifest["paper_registry_sha256"])
        checked_path("knowledge/extracted_patterns.jsonl", manifest["pattern_registry_sha256"])
        checked_path("knowledge/pattern.schema.json", manifest["pattern_schema_sha256"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(f"Artifact integrity: {exc}")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help=f"JSONL file (default: {DEFAULT_INPUT})")
    parser.add_argument("--require-reviewed", action="store_true", help="fail unless at least one reviewed record exists")
    parser.add_argument("--check-artifacts", action="store_true", help="verify canonical paper registry, source hashes, page bounds and example diffs")
    args = parser.parse_args()
    if not args.input.is_file():
        print(f"Input not found: {args.input}", file=sys.stderr)
        return 2
    seen = set()
    counts = {"draft": 0, "reviewed": 0}
    errors = []
    records = []
    with args.input.open(encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, 1):
            if not raw.strip():
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError as exc:
                errors.append(f"line {line_number}: invalid JSON: {exc.msg}")
                continue
            errors.extend(validate_record(record, line_number))
            records.append(record)
            if isinstance(record, dict):
                pattern_id = record.get("pattern_id")
                if isinstance(pattern_id, str):
                    if pattern_id in seen:
                        errors.append(f"line {line_number}: duplicate pattern_id '{pattern_id}'")
                    seen.add(pattern_id)
                if isinstance(record.get("status"), str) and record["status"] in counts:
                    counts[record["status"]] += 1
    if not records:
        errors.append("Knowledge file contains no records")
    if args.require_reviewed and counts["reviewed"] == 0:
        errors.append("RAG gate: no reviewed patterns are available")
    if args.check_artifacts and not errors:
        if args.input.resolve() != DEFAULT_INPUT.resolve():
            errors.append("--check-artifacts applies to the canonical extracted_patterns.jsonl only")
        else:
            errors.extend(check_artifacts(records))
    if errors:
        print("Knowledge validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Valid knowledge file: {counts['draft']} draft, {counts['reviewed']} reviewed")
    if not counts["reviewed"]:
        print("Extraction records are stored; human admission review is pending. No RAG index has been built.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
