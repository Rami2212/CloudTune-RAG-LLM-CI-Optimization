# Phase B knowledge

The canonical extracted literature registry is [extracted_patterns.jsonl](extracted_patterns.jsonl). The complete readable extraction is [LITERATURE_REVIEW.md](LITERATURE_REVIEW.md).

## Stored artifacts

- `papers.jsonl`: five source records, methods, samples, limitations, archived PDF paths, page counts and SHA-256 hashes.
- `extracted_patterns.jsonl`: 25 full-text pattern records, including questions, proposed methods, paper-reported outcomes and evidence locators.
- `examples/`: illustrative before/after pseudocode and unified diffs with hashes. These are not executed workflows or paper-provided patches.
- `pattern.schema.json`: the record format, including literature outcomes and example provenance.
- `extraction_manifest.json`: source/pattern counts and registry/schema hashes.
- `research_patterns.jsonl`: the original nine research-question drafts; this is a planning list, not the canonical evidence set.

## Run flow

From the repository root:

To rank collected repositories for manual screening against the 25 extracted literature patterns:

```powershell
.\.venv\Scripts\python.exe scripts\select_pattern_repos.py
```

This writes up to five candidates per pattern to `research-data/pattern_repo_candidates.csv`, choosing at most one repository from each upstream family for each pattern. `source_is_fork` identifies collected repos that are themselves forks. Rows marked `screening_only` lack a pattern-specific signal and are general repositories for manual screening; review `needs_manual_check` on all rows. The scores are rule-based hints, not proof of applicability or experiment readiness. To screen against the original nine research questions instead, pass `--patterns knowledge/research_patterns.jsonl`.

```powershell
.\.venv\Scripts\python.exe scripts\validate_knowledge.py --check-artifacts
```

This validates the canonical records, references, source page bounds, archived source hashes and before/after diff consistency. It runs offline and requires only Python's standard library.

After deliberately editing the curated source or example records, regenerate hashes, diffs and the readable report:

```powershell
.\.venv\Scripts\python.exe scripts\build_literature_assets.py
.\.venv\Scripts\python.exe scripts\validate_knowledge.py --check-artifacts
```

The full-text extraction is complete for the documented five-paper scope. Entries remain `draft` because admission to the RAG store requires human review under the research protocol. Review each cited finding and the proposed applicability/safety conditions; then record `reviewed_by`, `reviewed_at` and `status: reviewed`.

```powershell
.\.venv\Scripts\python.exe scripts\validate_knowledge.py --require-reviewed --check-artifacts
```

That command checks the review requirement; it does not create an index or filter records into RAG. A future indexer must admit only reviewed entries. Repository-specific outcomes, measured workflow diffs and run IDs are added separately after development experiments. Literature results must not be relabeled as local safe successes.
