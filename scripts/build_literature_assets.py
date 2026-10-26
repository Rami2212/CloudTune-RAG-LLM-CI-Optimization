"""Hash archived sources and build illustrative diffs from curated literature records.

Run offline from any directory. This does not extract scientific claims automatically.
"""
import difflib
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path, records):
    path.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8")


def local_path(ref):
    path = (ROOT / ref).resolve()
    path.relative_to(ROOT)
    return path


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_report(papers, patterns):
    lines = [
        "# Literature extraction: five requested papers", "",
        "The stored set contains 25 full-text extraction records. Human admission review is pending; this is separate from completing the extraction. No local CI experiments or RAG indexing were performed.", "",
        "Paper evidence, proposed application steps, and illustrative examples are distinct fields. Reported benefits are not local safe-success labels. Different records can describe related mechanisms and are not independent success observations.", "",
        "## Coverage and source versions", "",
        "All locators below refer to the archived PDFs, whose hashes and page counts are in [papers.jsonl](papers.jsonl). The bibliography URL alone is not a frozen source version.", "",
        "| Paper | Records | Reviewed full-text sections |", "| --- | ---: | --- |",
    ]
    for paper in papers:
        count = sum(r["paper_id"] == paper["paper_id"] for r in patterns)
        lines.append(f"| [{paper['paper_id']}: {paper['title']}]({paper['url']}) | {count} | {'; '.join(paper['sections_reviewed'])} |")
    lines += ["", "## Extraction boundaries", "",
              "S01 covers all six existing mechanisms and four proposed heuristics in Sections 4.2-4.3. S02 covers all four selection/prioritization families; named replicated techniques are preserved in the paper registry. S03 covers build parallelism, result caching and the dependency-only negative result. S04 covers both acceleration levels and their joint limitations. S05 contributes six optimization or investigation leads; its underlying 97 studies were not independently read as part of this five-paper task.", "",
              "Failure repair, co-change prediction, classifier architecture variants and dataset surveys are contextual material outside the working-workflow optimization task. The requested sources do not establish a standalone safe recipe for every initial topic: shallow checkout, generic artifact reuse, matrix pruning and GitHub job parallelism still need more specific evidence. Bazel build parallelism must not be relabeled as proof about GitHub job parallelism.", "",
              "## What each record stores", "",
              "- `research_question` and `optimization_question`: analyst-authored questions for investigation and later proposal generation.",
              "- `method`, preconditions, contraindications and safety tests: proposed application guidance, explicitly identified as analyst synthesis.",
              "- `reported_result`: a concise paper finding, reported metrics and a section/table/page locator. Consult the source registry's metric context and method before comparing numbers.",
              "- `success_status`: `reported_benefit`, `estimated_benefit`, `mixed_results`, `secondary_report_only`, or `no_direct_speedup_evidence`. These are literature classifications, not proof of safety.",
              "- `local_outcome`: `not_evaluated`. Real development cases, execution IDs and safe-success labels require Phase A/B experiments.",
              "- `example`: hashed illustrative before/after pseudocode and a matching diff. It is not a source repository's workflow or an executed patch.", "",
              "## Original examples and diffs", "",
              "The requested papers do not supply a uniform set of paired GitHub Actions YAML patches. S04 has paired Travis/Kotinos configuration listings on PDF p. 4; S03 has build configuration examples; S02 uses a conceptual timeline; S05 summarizes other studies. See each source's `reported_workflow_example`. Original before/after/diff references are explicitly null in the extracted records rather than invented. The locally archived PDF retains the published listings for inspection.", "",
              "## Pattern details", ""]
    for record in patterns:
        ident = record["pattern_id"]
        example = record["example"]
        before = example["before_ref"].removeprefix("knowledge/")
        after = example["after_ref"].removeprefix("knowledge/")
        diff = example["diff_ref"].removeprefix("knowledge/")
        lines += [f"### {ident}: {record['title']}", "",
                  f"Source: {record['paper_id']}, {record['sources'][0]['locator']}. Scope: `{record['scope']}`. Literature outcome: `{record['success_status']}`.", "",
                  f"**Question:** {record['optimization_question']}", "",
                  f"**Paper finding:** {record['reported_result']['finding']}", ""]
        if record["reported_result"]["metrics"]:
            lines += ["Reported metrics (interpret using the source registry's metric context):", "", "```json", json.dumps(record["reported_result"]["metrics"], indent=2), "```", ""]
        lines += ["**Proposed method (analyst synthesis):**", ""]
        lines += [f"{i}. {step}" for i, step in enumerate(record["method"], 1)]
        lines += ["", "**Preconditions:** " + "; ".join(record["preconditions"]) + ".", "",
                  "**Contraindications:** " + "; ".join(record["contraindications"]) + ".", "",
                  "**Proposed safety checks:** " + "; ".join(record["safety_tests"]) + ".", "",
                  f"Illustration only: [before]({before}), [after]({after}), [diff]({diff}).", ""]
    lines += ["## Rebuild and validate offline", "", "```powershell",
              ".\\.venv\\Scripts\\python.exe scripts\\build_literature_assets.py",
              ".\\.venv\\Scripts\\python.exe scripts\\validate_knowledge.py --check-artifacts", "```", "",
              "Rebuilding intentionally updates source/example hashes and regenerates this report. Investigate an unexpected integrity failure before rebuilding. Human review checks the interpretation against the cited paper; structural validation cannot perform that scientific judgment.", ""]
    (ROOT / "knowledge/LITERATURE_REVIEW.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    paper_path = ROOT / "knowledge/papers.jsonl"
    pattern_path = ROOT / "knowledge/extracted_patterns.jsonl"
    papers = read_jsonl(paper_path)
    patterns = read_jsonl(pattern_path)
    for paper in papers:
        paper["pdf_sha256"] = sha256(local_path(paper["fulltext_ref"]))
        paper["text_sha256"] = sha256(local_path(paper["text_ref"]))
    for record in patterns:
        example = record["example"]
        before = local_path(example["before_ref"])
        after = local_path(example["after_ref"])
        diff = local_path(example["diff_ref"])
        diff.relative_to(ROOT / "knowledge/examples")
        content = "".join(difflib.unified_diff(
            before.read_text(encoding="utf-8").splitlines(keepends=True),
            after.read_text(encoding="utf-8").splitlines(keepends=True),
            fromfile=example["before_ref"], tofile=example["after_ref"],
        ))
        diff.write_text(content, encoding="utf-8")
        example["before_sha256"] = sha256(before)
        example["after_sha256"] = sha256(after)
        example["diff_sha256"] = sha256(diff)
    write_jsonl(paper_path, papers)
    write_jsonl(pattern_path, patterns)
    write_report(papers, patterns)
    manifest = {
        "schema_version": 2,
        "extraction_date": "2026-10-23",
        "paper_count": len(papers),
        "pattern_count": len(patterns),
        "paper_registry_sha256": sha256(paper_path),
        "pattern_registry_sha256": sha256(pattern_path),
        "pattern_schema_sha256": sha256(ROOT / "knowledge/pattern.schema.json"),
        "review_policy": "Full-text extraction is complete; human admission review remains pending.",
        "local_experiments_executed": False,
    }
    (ROOT / "knowledge/extraction_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Built {len(patterns)} illustrative diffs and hashed {len(papers)} archived papers.")


if __name__ == "__main__":
    main()
