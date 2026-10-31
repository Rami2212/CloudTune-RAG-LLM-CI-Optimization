# RAG data and setup

## What is in the RAG

The retrieval dataset is generated from `knowledge/extracted_patterns.jsonl` and experiment records under `research-data/experiments/` and `research-data/scenario-experiments/`.

| Record type | Count | Description |
| --- | ---: | --- |
| `pattern` | 25 | Literature-derived CI optimization patterns and their evidence, conditions, and source details. |
| `experiment_example` | 49 | Experiments marked `pattern_satisfied: true`; inconclusive cases are retained with the `outcome` field omitted. |
| **Total retrieval-eligible records** | **74** | Every emitted record is approved for retrieval. |

Of the 49 examples, 39 are synthetic scenario results: 31 use service-policy replay and 8 use a dedicated fork fixture. The other 10 are main-batch cases whose source outcome was inconclusive; their inconclusive `outcome` field is omitted, while their evidence scope, limitations, and measurements are retained. Synthetic scenarios are not verified speedups on real repositories. Every pattern has at least one example; 24 have two and one has one. The records retain evidence scope, limitations, metrics, and artifacts so retrieved results are not presented as general performance claims.

Dataset snapshot (2026-10-31): `rag_dataset.jsonl` has 74 records (25 patterns + 49 experiment examples), is 2,658,800 bytes, and contains 1,016,341 searchable-text characters (mean 13,734; median 3,036 per record). Pattern text averages 1,423 characters; experiment-example text averages 20,016. Dataset counts describe generated files, not rows currently stored in Supabase.

## Full RAG record structure

Each line in `research-data/rag/rag_dataset.jsonl` is one JSON document. The following are the full current structures; artifact keys and experiment metrics vary by record.

### Pattern document

```json
{
  "document_id": "pattern:<pattern_id>",
  "record_type": "pattern",
  "pattern_id": "<pattern_id>",
  "title": "<pattern title>",
  "model": "nvidia/nemotron-3-ultra-550b-a55b:free",
  "evidence_scope": "literature_report_and_analyst_example",
  "rag_status": "approved_for_rag",
  "retrieval_eligible": true,
  "text": "<searchable pattern text with literature example contents>",
  "pattern": {"<pattern fields below>": "..."},
  "artifacts": {"before": {"sha256": "...", "encoding": "utf-8", "content": "..."}},
  "experiment_document_ids": ["experiment:<case_id>"]
}
```

The nested `pattern` fields in this build are: `pattern_id`, `paper_id`, `title`, `mechanism`, `status`, `extraction_status`, `research_question`, `optimization_question`, `preconditions`, `contraindications`, `affected_checks`, `implementation_notes`, `evidence_type`, `sources`, `expected_direction`, `safety_tests`, `reported_result`, `method`, `scope`, `success_status`, `example`, and `related_pattern_ids`. The `reported_result` contains `finding`, `metrics`, `pdf_pages`, and `locator`; each `sources` entry contains `title`, `url`, `year`, and `locator`. The cleaned `example` contains `origin`, `format`, `source_artifact_note`, and available before/after/diff SHA-256 hashes.

### Experiment-example document

```json
{
  "document_id": "experiment:<case_id>",
  "record_type": "experiment_example",
  "pattern_id": "<pattern_id>",
  "title": "<pattern and outcome title>",
  "model": "nvidia/nemotron-3-ultra-550b-a55b:free",
  "evidence_scope": "<measured or synthetic evidence scope>",
  "rag_status": "approved_for_rag",
  "retrieval_eligible": true,
  "text": "<searchable experiment summary and file contents>",
  "pattern_satisfied": true,
  "outcome": "scenario_passed",
  "experiment": {"<experiment fields below>": "..."},
  "runs": [{"<per-run measurements and checks>": "..."}],
  "artifacts": {"before": {"sha256": "...", "encoding": "utf-8", "content": "..."}}
}
```

For the 10 source cases with `outcome: "inconclusive"`, the record is retained because `pattern_satisfied` is true, but the inconclusive `outcome` field is omitted from the outer document, nested `experiment`, searchable text, and nested objects. Other outcome values are retained (the current 39 scenario examples use `scenario_passed`).

The nested `experiment` fields in this build are: `case_id`, `record_kind`, `split`, `pattern_id`, `pattern_satisfied`, `rag_admission`, `outcome` (omitted if inconclusive), `evidence_scope`, `arms`, `elapsed_savings_percent`, `realized_optimization_savings_percent`, `min_savings_percent`, `limitations`, `safe_for_repository_use`, `runtime_improved`, `required_status_validated`, `real_repo_optimization_verified`, `direct_speedup_claimed`, `no_change`, `absence_window_seconds`, `required_job_names`, `required_checks_source`, `run_ids`, `before_sha256`, `after_sha256`, `patch_sha256`, `model`, and `review`. `arms` contains `baseline` and `optimized` measurements; exact metrics depend on the experiment. `review` may be empty.

Each object in `runs` may contain: `experiment_id`, `pattern_id`, `arm`, `repeat_index`, `warmup`, `cache_regime`, `run_id`, `run_attempt`, `event`, `status`, `conclusion`, `started_at_utc`, `completed_at_utc`, `completed_at`, `workflow_elapsed_seconds`, `sum_job_runtime_seconds`, `initial_queue_seconds`, `job_names`, `job_outcomes`, `required_checks_pass`, `protocol_valid`, `failure_reason`, `assertions`, `events`, `cache_hits`, `first_failure_seconds`, `missed_failures`, `missed_failure_rate`, `held_out_mae_seconds`, `simulated_elapsed_seconds`, `simulated_work_seconds`, `scenario_pass`, and `model` when present.

### Artifacts and omitted metadata

Each optional artifact entry has `sha256`, `encoding`, and `content`. Common artifact keys are `before`, `after`, and `diff`; scenario records may also contain `workflow_change.diff`, `before_policy.yml`, and `after_policy.yml`. Binary content is `null` with `encoding: "binary"`. Local artifact references/paths and repository identifiers are omitted. The builder also removes the requested fields `local_outcome`, `llm`, `reasons`, `protocol`, `pattern_satisfaction_scope`, repo/commit identifiers, and path metadata recursively.

## Embedding model and process

- **Embedding model:** `BAAI/bge-m3`, run locally with Sentence Transformers. No hosted embedding API is used.
- **Vector size:** 1,024 dimensions; vectors are normalized.
- **Input:** only each approved record's `text` field is embedded. The full cleaned record is retained as JSON metadata.
- **Chunking:** default 1,024 tokenizer tokens per chunk with 128-token overlap; the model supports up to 8,192 tokens. Each chunk is embedded separately.
- **Revision:** the embed script resolves the model's `main` revision to a fixed Hugging Face commit and stores it, so searches can use the matching revision.
- **Generation metadata:** `model: nvidia/nemotron-3-ultra-550b-a55b:free` is carried over from the research records. It is not the embedding model and is not called by the embedding/search script.

## Supabase database

The migration `supabase/migrations/202610310001_cloudtune_rag.sql` defines two tables in the `public` schema:

| Table | Contents |
| --- | --- |
| `cloudtune_rag_documents` | One row per RAG record: document ID/type, pattern ID, title, searchable content, full JSON record, source hash, embedding model/revision, and chunk settings/count. |
| `cloudtune_rag_chunks` | One row per text chunk: document ID/index, chunk text, token count, and `vector(1024)` embedding. |

The chunks table has an HNSW cosine-distance index. The SQL also defines `upsert_cloudtune_rag_document` to replace one document and its chunks atomically, and `match_cloudtune_rag_chunks` to retrieve the closest chunks with optional pattern and model-revision filters. Row-level security is enabled; the migration grants table and RPC access to `service_role` only. Keep the service key on the trusted backend and out of client applications.

**Database status:** the SQL migration is prepared, but it has not been applied and no embeddings have been uploaded yet. Run the migration in the Supabase SQL Editor (or with `scripts/embed_rag_supabase.py --setup-only`) before ingestion. The direct database host tested from this machine did not have a usable IPv6 route; the SQL Editor is the available setup path unless an IPv4-compatible session-pooler URL is configured.

## Build, embed, upload, and search

From the repository root in PowerShell:

```powershell
# Build/update the approved JSONL retrieval dataset
.\.venv\Scripts\python.exe scripts\build_rag_dataset.py

# After applying the SQL migration and setting SUPABASE_URL and SUPABASE_SECRET_KEY in .env
.\.venv\Scripts\python.exe -m pip install -r requirements-rag.txt
.\.venv\Scripts\python.exe scripts\embed_rag_supabase.py

# Retrieve relevant chunks for a query
.\.venv\Scripts\python.exe scripts\embed_rag_supabase.py --query "When should I cache dependencies in GitHub Actions?" --top-k 5
```

The first embedding run downloads the local BGE-M3 model weights. Ingestion skips unchanged records; changed records and their chunks are replaced atomically. Records missing from a later dataset are not automatically deleted. Search returns evidence chunks and cosine-similarity scores; an answer-generation model must consume those results separately.

See `RUN_RAG_COMMANDS.md` for setup options, CPU/GPU flags, and connection checks.

## Populate Supabase from Google Colab

Before running Colab, apply the SQL migration in Supabase SQL Editor and add `SUPABASE_URL` and `SUPABASE_SECRET_KEY` under Google Colab → Secrets. Upload these two files to the Colab session:

- `scripts/colab_populate_rag.py`
- `research-data/rag/rag_dataset.jsonl`

Then run `%pip install -q sentence-transformers` and `%run /content/colab_populate_rag.py`. The script embeds locally with BGE-M3, skips unchanged records, and uploads chunks through the Supabase RPC. It does not create tables or delete records missing from the dataset.
