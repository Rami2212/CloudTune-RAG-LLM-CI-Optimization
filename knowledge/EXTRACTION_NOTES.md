# Extraction scope and provenance

The initial abstract-only set has been replaced by a full-text extraction from the five requested papers. See [LITERATURE_REVIEW.md](LITERATURE_REVIEW.md) for coverage, record details, source locators and run instructions.

## Completed

- Archived all five full PDFs and extracted page-marked text under `research-data/literature/fulltext/`.
- Inspected relevant methods, results, tables, examples and limitations. Source PDF page counts are 12, 13, 47, 13 and 36, respectively; cite the archived version, since HTML layouts differ.
- Stored 25 pattern records: S01 10, S02 4, S03 3, S04 2, S05 6.
- Recorded primary, simulated/counterfactual and secondary evidence distinctly; retained negative or limited-benefit findings.
- Added analyst-authored questions, proposed methods, conditions, risks and safety checks with explicit provenance.
- Added 25 illustrative before/after pairs and matching diffs, with hashes. They are pseudocode; no CI executions are asserted.
- Added source/registry hashes, page-bound checks and file/diff integrity validation.

## Interpretation boundaries

The survey's 97 underlying papers were not independently reviewed. Its entries are secondary leads, with primary study names retained in the locators. Prediction and CI service changes can exceed the primary workflow-YAML-only study. Some initial topic questions require further sources, as documented in the report.

Original paired GitHub Actions workflows and per-case run IDs are not uniformly supplied by these papers. Their references remain null. The Kotinos paper's paired configuration listings are retained in its archived PDF, with a page locator; they are a Travis-to-Kotinos migration, not a measured GitHub Actions patch.

A `reported_benefit` or `estimated_benefit` is a literature outcome classification, never a local `safe_success`. Human admission review remains pending as required by the protocol; the extraction and structural checks are independently complete.
