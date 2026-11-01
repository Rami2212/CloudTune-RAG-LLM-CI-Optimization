# CloudTune — A/B/C Evaluation Pipeline Implementation Plan

**Document type:** Technical implementation plan (not a handoff document)  
**Project:** CloudTune — RAG and LLM-Based CI Optimization  
**Repository:** <https://github.com/Rami2212/CloudTune-RAG-LLM-CI-Optimization>  
**Target branch for all implementation commits:** `feature/evaluation-pipeline`  
**Base branch:** `develop`  
**Repository source reviewed:** `develop`, commit `305463509678c1cbf0ba3a45b94d789701710234`, October 31, 2026  
**Document updated:** November 1, 2026  
**Scope:** Evaluation arms **A (Original)**, **B (`ci-cost`)**, **C (LLM + RAG)**; **exclude D (LLM-only)**.  
**Repository documentation policy:** **Do not change any existing README**, including the existing `evaluation/README.md`, as part of the current implementation. The pipeline has its own new, permanent `evaluation/PIPELINE_GUIDE.md`. Do not create a README for each implementation phase. The implementation plan is distributed separately and **must not be included in the implementation patch**.

> This is a **forward-looking implementation plan**, not a claim that the entire evaluation pipeline or research study has already been executed. The reviewed source revision is pinned above. Line numbers in existing scripts refer to that revision and may differ as new code is introduced.

---

## 1. Goals, boundaries and research questions

Build a safe, reproducible, resumable evaluation pipeline that runs three approaches against the **same pinned GitHub Actions source workflow**. Reuse existing CloudTune experimental and RAG infrastructure rather than duplicating or rewriting the research system.

### 1.1 Three arms

| Arm | Name | Candidate | Purpose |
| --- | --- | --- | --- |
| **A** | Original baseline | Same original pinned workflow, no optimizer-generated modifications | Establish the actual baseline execution time, runner-time, status and required-check results. |
| **B** | `ci-cost` | Rule-based tool's generated workflow, or `NO_CHANGE` | Measure whether the rule-based approach improves upon A. |
| **C** | LLM + RAG | Fixed LLM using retrieved, frozen RAG evidence; generated workflow, or `NO_CHANGE` | Evaluate the combined proposed CloudTune optimization method relative to A and B. |

**Excluded:** D, LLM-only. Because D is absent, the evaluation **cannot isolate the contribution of retrieval from that of the LLM**. Findings must be phrased as performance of the **combined LLM + RAG system**, not proof that RAG itself independently improves performance.

### 1.2 Required comparisons

1. **B vs A:** Improvement by `ci-cost` over the original.
2. **C vs A:** Improvement by CloudTune over the original.
3. **C vs B:** Direct comparison of CloudTune with the rule-based optimizer (**primary between-optimizer comparison**).

A valid speedup requires **executed, comparable CI evidence and preserved intended behavior**. A generated diff, valid YAML or `ci-cost`'s estimated improvement is not sufficient on its own.

### 1.3 What the implementation work includes

- Evaluation dataset selection and screening.
- Pinned, reproducible repository/workflow/context snapshots.
- A/B/C candidate creation and shared candidate contract.
- A `ci-cost` adapter and RAG retrieval/LLM generation adapter.
- Shared validation of safety, workflow scope, syntax and intended CI behavior.
- Isolated GitHub Actions execution with repeated measurements, safe resume and run archival.
- Candidate/run-level evidence, direct paired statistics and research-ready reports.
- Automated offline tests and an incremental development pilot.

### 1.4 What is deliberately not included

- LLM-only Arm D.
- Recreating the 500-repository development pattern experiment pipeline.
- Training a new foundation model.
- Treating synthetic-scenario or inconclusive development records as demonstrated performance gains.
- Automatically applying optimizer changes to upstream repositories.
- Rewriting the existing `evaluation/README.md` or making separate phase READMEs.
- Including the implementation-plan Markdown file in the source patch.

---

## 2. End-to-end architecture

```text
             HELD-OUT EVALUATION DATASET
     evaluation/evaluation_repositories_4000.csv
                         |
                         v
           +--------------------------+
           | Repository preparation   |
           | - eligibility screening  |
           | - upstream/fork identity |
           | - workflow selection     |
           | - source/harness freeze  |
           | - manifest/check context |
           +------------+-------------+
                        |
                 PINNED SNAPSHOT
                        |
           +------------+-------------+
           |            |             |
           v            v             v
      +---------+ +-----------+ +----------------+
      | A:      | | B:        | | C:             |
      | Original| | ci-cost   | | LLM + RAG      |
      | no edit | | --fix     | | BGE-M3 search  |
      |         | | or abstain| | + fixed LLM    |
      +----+----+ +-----+-----+ +-------+--------+
           |            |               |
           |            +-------+-------+
           |                    |
           |                    v
           |           +--------------------+
           |           | Common validation  |
           |           | YAML, actionlint,   |
           |           | behavior, security, |
           |           | required checks     |
           |           +---------+----------+
           |                     |
           +----------+----------+
                      |
                      v
          +---------------------------+
          | Isolated A/B/C execution  |
          | same pinned source commit |
          | interleaved repetitions   |
          | GitHub Actions evidence   |
          | resumable run tracking    |
          +------------+--------------+
                       |
                       v
          +---------------------------+
          | Export and statistics     |
          | B-A, C-A, paired C-B      |
          | elapsed time, runner time |
          | validity, safety, errors  |
          | confidence intervals      |
          +---------------------------+
```

The **pipeline coordinator** will be one entrypoint with reusable interfaces. Candidate generation, static validation, execution and analysis remain separate modules. Every stage writes evidence that later stages can read without requerying an unpinned default branch.

---

## 3. Existing code and how to reuse it

The current repository already contains a significant amount of useful infrastructure. **Preserve the earlier experiment system and all its recorded results**. Extract shared helpers only after adding regression tests for the original behavior.

### 3.1 Core scripts and source line references

| Existing file | Relevant lines at reviewed revision | Current implementation | How the evaluation uses it |
| --- | --- | --- | --- |
| `scripts/run_ci_experiment.py` | 230–318 | GitHub API and CI timing metrics | Reuse/extract API wrappers and metric calculations. |
| `scripts/run_ci_experiment.py` | 464–548 | Pinned repository tree/workflow and manifest collection | Reuse design in evaluation-specific read-only preparation. |
| `scripts/run_ci_experiment.py` | 550–586 | Isolated branches and ref checks | Adapt for three arms while preserving commit/tree identity checks. |
| `scripts/run_ci_experiment.py` | 677–816 | Workflow dispatch, polling, safe resume and evidence archive | Reuse pending-run/uncertain POST safeguards and per-job metrics. |
| `scripts/run_pattern_batch.py` | 74–108 | Eligible CI workflow selection | Reuse conservative workflow selection for held-out repositories. |
| `scripts/run_pattern_batch.py` | 224–391 | Fork setup, dispatch preparation and cleanup | Reuse only after authorization and ownership validation. |
| `scripts/embed_rag_supabase.py` | 166–188; 232–252 | BGE-M3 and Supabase embedding/search | Provide structured, frozen retrieval results to the evaluation generator. |
| `scripts/openrouter_optimizer.py` | 90–234 | Existing selected-pattern model calls, retries and parsing | Create a new evaluation adapter that allows pattern selection and `NO_CHANGE`. |
| `evaluation/build_evaluation_repo_dataset.py` | 25–151 | Held-out dataset building | Reuse the already-generated sample; run fresh screening. |
| `evaluation/evaluate_rag_vs_ci_cost.py` | 95–278 | Baseline-relative analysis and bootstrap | Extend or wrap for A/B/C and direct paired C-B without losing existing behavior. |

### 3.2 Other scripts: reuse boundaries

| Existing scripts | Responsibility | Evaluation decision |
| --- | --- | --- |
| `prepare_data.py`, `create_zenodo_repo_dataset.py`, `create_zenodo_pattern_repo_dataset.py` | Candidate data preparation | Reuse prepared datasets; leave scripts untouched. |
| `select_pattern_repos.py`, `select_unique_pattern_repos.py` | Development pattern sampling | Do not reuse to cherry-pick held-out repositories. |
| `collect_ci_history.py`, `workflow_history.py` | Historical workflow evidence | Reuse selectively as context; do not substitute historical durations for current A/B/C measured runs. |
| `build_literature_assets.py`, `validate_knowledge.py` | Literature and knowledge validation | Preserve. |
| `build_rag_dataset.py` | RAG corpus builder | Reuse and freeze the corpus before main evaluation. |
| `colab_populate_rag.py` | Alternate RAG ingestion path | Optional ingestion helper, not a second inconsistent retrieval process. |
| `experiment_environment.py` | `.env` loading and secret redaction | Reuse unchanged. |
| `run_scenario_batch.py`, `run_new_scenario_batch.py`, `scenario_experiments.py`, `scenario_replay.py` | Synthetic and event/policy scenarios | Keep separate; label evidence correctly. |
| Existing scripts' test files and `tests/` modules | Regression tests | Run after any extraction/refactor. |

### 3.3 Existing assets and limitations

- Held-out pool: `evaluation/evaluation_repositories_4000.csv` contains **4,000 candidate repositories**, not 4,000 currently verified executable CI workloads.
- Dataset manifest: `evaluation/evaluation_repositories_4000_manifest.json` records sample source, exclusion method, seed and hashes; original Zenodo metadata is historical, not a live safety screen.
- Development exclusions: `research-data/zenodo_20340547/pattern_repo_candidates_20.csv`, plus recorded experiment-case repository IDs. Check canonical fork/source families before accepting held-out repositories.
- RAG documents: current corpus reported **25 literature patterns and 49 experiment examples**: 39 synthetic scenarios and 10 inconclusive real-repository records. These are **not proof of real CI savings**.
- Supabase readiness: existing documentation reports ingestion pending; confirm live index population, schema, frozen hashes and search before C.
- Existing `evaluation/evaluate_rag_vs_ci_cost.py` is not an end-to-end A/B/C orchestrator; it requires populated CSVs and must be extended for direct C-B pairing and the chosen missingness policy.
- Existing `scripts/openrouter_optimizer.py` **forces** `APPLY` for selected-pattern experiments. New evaluation generation must permit `NO_CHANGE`.
- Existing `scripts/run_ci_experiment.py` uses `baseline`/`optimized` and a fixed `pattern_id`; do not mutate it wholesale to add three-arm orchestration.

---

## 4. Repository layout and documentation policy

The following structure separates reusable research scripts from a dedicated evaluation subsystem. Existing files stay untouched unless a later change is separately approved and regression-tested.

```text
CloudTune-RAG-LLM-CI-Optimization/
|
+-- scripts/                         # EXISTING research/experiments
|   +-- run_ci_experiment.py
|   +-- run_pattern_batch.py
|   +-- openrouter_optimizer.py
|   +-- embed_rag_supabase.py
|   +-- ...
|
+-- evaluation/
|   +-- README.md                    # EXISTING: DO NOT MODIFY
|   +-- PIPELINE_GUIDE.md            # NEW permanent usage guide; update over time
|   +-- evaluation_repositories_4000.csv
|   +-- evaluation_repositories_4000_manifest.json
|   +-- build_evaluation_repo_dataset.py
|   +-- evaluate_rag_vs_ci_cost.py   # EXISTING; only modify if separately approved
|   +-- __init__.py                  # NEW
|   +-- run_pipeline.py             # NEW: coordinator
|   +-- repository_preparation.py    # NEW: selection, screening, frozen snapshots
|   +-- rag_retriever.py             # PLANNED: structured retrieval
|   +-- candidate_validator.py       # PLANNED: common safety contract
|   +-- ci_executor.py               # PLANNED: remote execution & resume
|   +-- results_exporter.py          # PLANNED: CSV/JSON evidence
|   +-- optimizers/
|   |   +-- __init__.py              # NEW
|   |   +-- original.py              # NEW: A candidate
|   |   +-- ci_cost.py               # PLANNED: B adapter
|   |   +-- rag_llm.py               # PLANNED: C adapter
|   +-- configs/
|   |   +-- pilot.json               # NEW
|   +-- results/
|       +-- .gitignore               # NEW: ignore generated experiments
|       +-- <evaluation_id>/
|           +-- config.json
|           +-- screening.csv
|           +-- preparation_summary.json
|           +-- repositories/
|           +-- candidates/
|           +-- runs/
|           +-- evaluation_runs.csv
|           +-- per_repository_results.csv
|           +-- summary.json
|
+-- tests/
    +-- test_evaluation_preparation.py   # NEW
    +-- test_evaluation_optimizers.py    # PLANNED
    +-- test_evaluation_pipeline.py      # PLANNED
    +-- test_evaluation_analysis.py      # PLANNED
```

**Documentation decisions:**

- Keep the current `evaluation/README.md` byte-for-byte unchanged for the current feature work.
- Use **one new** `evaluation/PIPELINE_GUIDE.md` for installation, commands, operator instructions, results and changing implementation status.
- **Do not** add `PHASE1_README.md`, `PHASE2_README.md`, etc.
- Store this **implementation plan outside the patch**, as a separate Markdown document for long-term reference.
- One Git feature branch, `feature/evaluation-pipeline`, for all phases, with distinct commits for each completed step and a single eventual PR to `develop`.

---

## 5. Implementation phases

### Phase 1 — Repository preparation and unchanged Arm A candidate

**New files already implemented in the revised preparation patch:**

- `evaluation/repository_preparation.py` — read-only GitHub API, dataset screening, workflow selection and immutable snapshots.
- `evaluation/run_pipeline.py` — configuration and `--stage prepare` coordinator.
- `evaluation/optimizers/original.py` — Arm A unchanged **candidate record** (not CI execution).
- `evaluation/configs/pilot.json`, package initializer files, output `.gitignore`.
- `tests/test_evaluation_preparation.py` — offline tests.
- `evaluation/PIPELINE_GUIDE.md` — permanent user guide.

**Implementation requirements:**

1. Read the held-out CSV deterministically and validate its `repo_id` and `split` fields.
2. Exclude known development/training IDs, including saved experiment-case IDs; inspect canonical GitHub fork/source family and record ambiguity when provenance is incomplete.
3. Inspect live repository metadata: archived, disabled, private/unavailable, default branch, fork information and current workflow tree.
4. Screen workflow files for test/build eligibility; conservatively reject suspected publishing/deployment, secrets, self-hosted runners, uninspected reusable workflows and dangerous listeners.
5. Freeze a commit and complete Git tree; reject truncated trees and changed/inconsistent blobs.
6. Select one pinned workflow; capture original bytes, SHA-256 hash, relevant manifests and lockfiles, with provenance and explicit omission reasons for context limits.
7. Preserve workflow dispatch prerequisites. If `workflow_dispatch` or required defaults are missing, record `needs_harness`; **do not silently edit the workflow** during Phase 1.
8. Prepare an immutable Arm A candidate record. Required checks are **not yet verified**; no CI run has occurred.
9. Record screening results including `prepared`, `needs_harness`, `ineligible`, `inconclusive`, and `api_error` with transparent reasons.
10. Reuse frozen snapshots on rerun; changing the configuration or source/protocol requires a new evaluation ID.

**Current Phase 1 limitations:** read-only; no fork creation; no workflow dispatch; no actual baseline durations; B/C optimizers are placeholders in config only. The runnable coordinator explicitly rejects `dry_run: false`.

**Outputs:** `evaluation/results/<id>/screening.csv`, `preparation_summary.json`, `config.json`, and each repository's snapshot/manifest and `candidates/A/candidate.json`.

**Phase 1 acceptance:** all offline tests pass; prepared snapshots have immutable hashes; an eligible repository is selected without mutating remote GitHub state; no false claims of executed CI runs.

### Phase 2 — B: `ci-cost` adapter

**New file:** `evaluation/optimizers/ci_cost.py`.

1. Pin the exact `ci-cost` version **and resolved source/package revision**; the reviewed upstream implementation describes version 1.0.0, but verify the pinned executable on installation.
2. Run it only in a temporary isolated workspace with the frozen selected original workflow; record input and environment hashes.
3. Run its documented analysis and `--fix` generation mode. Archive exact logs, tool diagnostics, optimizer processing time and generated files.
4. The tool may produce workflows in `.github/workflows/optimized/`; treat them as **candidate artifacts**, not additional workflows committed to the fork. Normalize intended output back to the selected original workflow path for execution.
5. Handle nonzero exit statuses carefully: current `ci-cost` can return status 1 for high-severity findings even when output exists. Inspect artifacts and diagnostics before classifying as `ERROR`.
6. Check semantic YAML structure as well as bytes; comment-only report headers must not count as a real change.
7. Never hand-improve the generated candidate; classify `APPLY`, `NO_CHANGE` or `ERROR` and record before/after workflow hashes and diff.
8. Send changed candidates to the **same validation engine** that will check C.

**Outputs:** B candidate YAML, diff, analysis findings, tool revision, candidate JSON, logs, status and optimizer latency.

**Acceptance:** reproducible tool-generated B candidate from the same frozen A workflow, without hidden modifications or manual optimization.

### Phase 3 — C: LLM + RAG adapter

**New files:** `evaluation/rag_retriever.py`, `evaluation/optimizers/rag_llm.py`.

1. Verify/create the RAG schema and ingest the frozen `build_rag_dataset.py` corpus through the existing BGE-M3/Supabase implementation.
2. Pin corpus hash, embedding-model revision, chunking, index details and retrieval configuration. Never blend evaluation results into the corpus during benchmark runs.
3. Build a repository-specific retrieval query from selected CI YAML, build/test steps, dependencies/lockfiles, job structure, runner configuration and relevant CI history.
4. Retrieve `top_k` chunks with document IDs, scores, pattern IDs, sources and limitations. Similarity alone is not proof of applicability.
5. Compose a fixed versioned generator prompt containing the original workflow, repository context, required checks, retrieved evidence, preconditions, contraindications and safety policies.
6. Call the pinned OpenRouter generator; BGE-M3 is the embedding/retrieval model, **not** the workflow-generating LLM.
7. Allow either `APPLY` with an unambiguous candidate and mechanism reasoning, **or `NO_CHANGE`**. Do not reuse old forced `APPLY` evaluation behavior.
8. Preserve exact model ID/revision, prompt, retrieved evidence IDs/scores, response, token counts, generator latency/retries, candidate/diff hashes and status.
9. Do not describe synthetic scenario records or inconclusive real-repository records as proven real-repository optimization gains.

**Outputs:** C candidate YAML/diff, retrieval JSON, prompt/response archive, optimizer metadata, decision and evidence references.

**Acceptance:** C demonstrably uses the frozen RAG knowledge base, supports safe abstention and produces transparent, traceable outputs.

### Phase 4 — Shared candidate validation

**New file:** `evaluation/candidate_validator.py`.

Apply exactly the same **acceptance standard** to B and C, with mechanism-specific checks when applicable:

1. Verify candidate starts from the pinned A workflow and changes only explicitly allowed target workflow file(s).
2. Parse YAML safely, detect duplicate keys and run mandatory `actionlint`.
3. Preserve required checks, test/build commands, intended branches/triggers, matrices, permissions, environment, artifacts and job dependencies according to predeclared policy.
4. Ban unauthorized publishing/deployment, unapproved secrets, inappropriate broad workflow permissions, external side effects, changes to unrelated workflows and unsafe branch interactions.
5. Check caching validity and cache-key invalidation; concurrency cancellation semantics; timeouts; path filtering and conditional execution; parallelization and dependencies; any proposed job elimination.
6. Preserve workload equivalence, not merely YAML syntax. Where static checks are inconclusive, require independent safety review and behavior checks before approving execution.
7. The existing conservative `protected_contract()` is **not** a general semantic-equivalence proof and may reject certain legitimate changes. Refactor only in a tested, predeclared way, without favoritism toward B or C.
8. Verdicts: `PASS`, `FAIL`, `REVIEW_REQUIRED`, `INCONCLUSIVE`, each with reasons and evidence pointers. Do not execute unsafe or still-under-review optimized candidates.

**Outputs:** `validation.json` per candidate, optional reviewer/evidence records.

**Acceptance:** B and C face fair, identical safety requirements; invalid candidates cannot be counted as successful speedups.

### Phase 5 — Isolated A/B/C execution and resumption

**New file:** `evaluation/ci_executor.py`.

1. Prepare a **common dispatch harness** before freezing the execution source commit if the original workflow lacks `workflow_dispatch`. Preserve upstream and harness commit SHAs separately.
2. Use research-owned forks with verified ownership and permissions. Never mutate upstream repositories.
3. Create isolated refs A, B, C from the **same prepared source commit**. Arm A remains unchanged; B and C only contain their approved target workflow candidate.
4. Verify remote source/branch/tree SHAs before dispatch. Ensure the selected workflow is registered/active and no dangerous ancillary workflow is triggered.
5. Execute configurable repetitions: initial pilot 3 per arm, main evaluation commonly 5 per arm, subject to pilot variation.
6. Interleave run order (for example A-B-C, B-C-A, C-A-B), rather than running all of one arm first.
7. Before dispatch, save pending state. If POST returns an ambiguous network error, **do not blindly retry**; resolve the existing run identity first.
8. Record run ID/attempt, branch/commit, workflow ID, raw GitHub Actions API responses, job/step status, required-check results, artifacts, timestamps, queue timing and failure reasons.
9. Time consistently: elapsed workflow time, summed executed-job runtime, initial queue separately. Parallel work can shorten elapsed time without decreasing summed job time.
10. Track cache regime and runner environment. `uncontrolled` caching is an explicitly reported limitation, not a claim of comparable cold/warm cache behavior.
11. Preserve failed/canceled/incomplete attempts. Do not replace unfavorable outcomes without recording the predeclared retry policy and all earlier attempts.
12. Resume safely after queue timeouts, rate limits and interruptions without dispatch duplication; cleanup only newly created research forks and keep audit evidence.

**Outputs:** A/B/C run records and raw API evidence, state machine snapshots and execution report.

**Acceptance:** one eligible repository completes valid, repeatable A/B/C real GitHub Actions runs with no unintended repository mutations and safe resume.

### Phase 6 — Results, statistics and exports

**New file:** `evaluation/results_exporter.py`.  
**Existing:** `evaluation/evaluate_rag_vs_ci_cost.py` is available for later extension, but **do not modify it under the current no-existing-file-changes requirement**. A new A/B/C comparison module can wrap it or replace its role if needed; only update existing files when separately approved.

1. Export **every run attempt** and all candidate-level outcomes, including nonexecuted candidates.
2. Provide normalized source and candidate identities, arm, repetition, run_id/attempt, execution order, status/conclusion, required-check verdict, timestamps and failure reason.
3. Only calculate timing statistics from comparable, protocol-valid, behavior-preserving successful runs. Never impute missing speeds or discard a failure from complete success-rate reporting.
4. Compute **B vs A**, **C vs A**, and paired **C vs B** differences per repository.
5. Summarize per-repository repetitions first (medians), then aggregate across repository units; report median savings, IQR, paired comparisons and repository-bootstrap 95% CIs.
6. Record eligible, attempted, valid, safe, actually executed and timing-comparable denominators separately.
7. Calculate runner-time resource reductions, regression rates, validity/pass/rejection/`NO_CHANGE` rates and optimizer-generation latency. Report model usage and retrieval relevance as supplementary outcomes.
8. Report real monetary CI cost only if justified billing rates are known; otherwise use summed job runtime as the resource proxy. `ci-cost`'s heuristic dollar estimates must not be represented as measured savings.
9. Produce a per-repository table, full summary JSON, and a readable report with limitations and provenance.

**Outputs:** `evaluation_runs.csv`, `per_repository_results.csv`, `summary.json`, optional narrative report and raw references.

**Acceptance:** the researcher can reproduce numerical claims from archived raw events, input snapshots and configuration.

---

## 6. Common data contracts

### 6.1 Candidate record (proposed schema)

```json
{
  "evaluation_id": "cloudtune-abc-pilot-001",
  "evaluation_repo_id": "owner/repository",
  "source_commit_sha": "pinned-source-sha",
  "workflow_path": ".github/workflows/ci.yml",
  "arm": "rag",
  "decision": "APPLY",
  "before_sha256": "original-workflow-hash",
  "after_sha256": "candidate-workflow-hash",
  "patch_sha256": "candidate-diff-hash",
  "retrieved_document_ids": ["example-document-id"],
  "validation": {
    "yaml": "PASS",
    "actionlint": "PASS",
    "required_checks": "REVIEW_REQUIRED",
    "overall": "REVIEW_REQUIRED"
  },
  "execution": {
    "run_ids": [],
    "status": "NOT_STARTED"
  }
}
```

This is **illustrative**, not an existing interface. Include tool/model/corpus revision, prompt hashes, optimizer latency, API run identity, input path, output path and evidence references in the implemented schema. Arm A has `decision="BASELINE"` and is unchanged.

### 6.2 Run-level schema (minimum fields)

| Area | Fields |
| --- | --- |
| Identity | `evaluation_id`, `repo_id`, `workflow_path`, `source_commit_sha`, `arm`, `candidate_sha256` |
| Run protocol | `repeat_index`, `warmup`, `execution_order`, `cache_regime` |
| GitHub | `run_id`, `run_attempt`, `run_status`, `conclusion`, `run_branch_sha`, `protocol_valid` |
| Timings | `started_at_utc`, `completed_at_utc`, `workflow_elapsed_seconds`, `sum_job_runtime_seconds`, `initial_queue_seconds` |
| Correctness | `required_checks_pass`, `safety_verdict`, `failure_reason`, `review_evidence_ref` |
| Generation | `optimizer_seconds`, optional `retrieval_seconds`, `tokens_in`, `tokens_out`, pinned tool/model refs |
| Monetary estimates | Optional CI rate/date/source and `ci_cost_usd` only if justified |
| Evidence | `raw_ref`, original/patch hashes, C retrieval IDs/scores |

### 6.3 Persisted run state

```text
PENDING
   ↓
PREPARED
   ↓
GENERATED
   ↓
VALIDATED
   ↓
EXECUTED
   ↓
REPORTED
```

Maintain explicit terminal or suspended states such as `INELIGIBLE`, `NO_CHANGE`, `REJECTED`, `FAILED`, `INCONCLUSIVE`, `PENDING_RUN`. Save state atomically before sensitive remote actions; never assume an unsuccessful local POST means no GitHub Actions run was created. Separate per-repo/per-arm state from global aggregated reporting.

---

## 7. Evaluation methods and calculations

### 7.1 Primary outcomes

1. **Workflow elapsed time** of successful, equivalent runs: B vs A, C vs A, C vs B.
2. **Summed job runtime** as an approximate resource-usage measure: B vs A, C vs A, C vs B.
3. **Safe beneficial optimization success**: B vs C after documented safety acceptance and minimum savings threshold.
4. **Candidate validity and required-check preservation**: do not substitute a speed benefit for safety/correctness.

Use a repository's median valid elapsed time for each arm: `T_A`, `T_B`, `T_C`.

```text
B savings over A (%)  = 100 × (T_A − T_B) / T_A
C savings over A (%)  = 100 × (T_A − T_C) / T_A
C advantage over B (%)= 100 × (T_B − T_C) / T_B
```

Positive value: left-mentioned optimizer is faster under its comparison. Negative: regression. Repeat with per-arm **summed job runtime** medians for the resource comparison. **Do not calculate a valid speedup without comparable valid executions.**

### 7.2 Secondary metrics

- Candidate YAML and `actionlint` validity.
- Required-check pass and independent safety validation rates.
- `NO_CHANGE`, refusal/abstention, rejected/unsafe/inconclusive rates.
- Failed, canceled, incomplete run rates and performance regressions.
- B tool runtime and C retrieval/LLM generation overhead.
- LLM tokens and API costs, retrieval evidence provenance and relevance.
- Queue time, runner environment and observed cache state.
- Optionally defensible billed CI dollars with explicit rates and evidence.

### 7.3 Statistical protocol

- Run repetitions **within repository/arm** to estimate a stable median.
- Do not treat repeated executions of one repository as independent repositories.
- For C vs B, use **the same repositories** with valid measurements in both arms (paired analysis).
- Report median and IQR of per-repository savings; repository-bootstrap 95% confidence intervals; full denominator accounting and noncomparable outcome counts.
- Predeclare the safe-benefit threshold (e.g., **at least 5% elapsed reduction** plus approved safety). This is a design parameter, not a study result.
- Report selection/screening attrition and study limitations, including uncontrolled cache effects, external services, platform scheduling, incomplete GitHub runner information, and restricted applicability.

### 7.4 Special outcomes

- **`NO_CHANGE`:** report descriptive zero realized optimization savings vs original; do not pretend an unchanged workflow has a separate independently measured run unless it actually ran. Keep `NO_CHANGE` in the full attempted-candidate denominator.
- **Unsafe/`FAIL` or unreviewed candidate:** do not run as approved optimization; preserve its invalidity and absence of timing in the report.
- **A baseline failure:** do not claim valid percent improvement; preserve attempt and failure details.
- **Unexpected run failures:** retain all attempts, do not silently replace failures with successful retries.
- **Inconclusive snapshots or missing histories:** report as such, do not convert to eligible successes.

### 7.5 Hypothetical illustration only

| Arm | Example median time | Example savings vs A |
| --- | ---: | ---: |
| A — Original | 200 s | 0% |
| B — `ci-cost` | 175 s | 12.5% |
| C — LLM + RAG | 140 s | 30% |

On these **illustrative data**, C's direct advantage over B is `100 × (175 − 140) / 175 = 20%`. These are **not actual CloudTune results**; safety and run-protocol acceptance are prerequisites for a measured claim.

---

## 8. Configuration

The **existing Phase 1 implementation** provides `evaluation/configs/pilot.json` as a placeholder for eventual A/B/C configuration. The following is its current schema:

```json
{
  "evaluation_id": "cloudtune-abc-preparation-pilot-001",
  "dataset": "evaluation/evaluation_repositories_4000.csv",
  "dataset_split": "evaluation",
  "repository_start_at": 1,
  "repository_limit": 5,
  "arms": ["original", "ci_cost", "rag"],
  "repetitions": 3,
  "warmup_runs": 0,
  "minimum_savings_percent": 5.0,
  "ci_cost": { "version": "1.0.0" },
  "rag": {
    "embedding_model": "BAAI/bge-m3",
    "top_k": 5,
    "generator_model": "SET_PINNED_OPENROUTER_MODEL",
    "max_tokens": 24000
  },
  "execution": {
    "dry_run": true,
    "interleave_arms": true,
    "require_actionlint": true,
    "cache_regime": "uncontrolled"
  }
}
```

**Important:** `run_pipeline.py` currently supports only `--stage prepare` and rejects any `execution.dry_run` other than `true`. The B, C, `actionlint`, cache and repetition settings are **reserved for later stages**. Setting them does not activate an optimizer or remote CI execution.

The completed pipeline configuration should additionally pin the `ci-cost` commit/executable checksum, exact generator model, RAG corpus/index and embedding revision, prompt hash, fork policy, dispatch timeouts, GitHub Actions permissions, required-check contract, run budget and acceptance thresholds. Configuration changes after execution require a distinct immutable evaluation ID.

---

## 9. Running and testing the currently implemented preparation stage

### 9.1 Install dependencies

**Windows PowerShell**

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

**Linux Bash**

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
```

A working existing `.venv` can be reused. Place your GitHub token in the existing `.env` or shell environment; **read permissions suffice** for this initial stage.

### 9.2 Run preparation

**Windows PowerShell**

```powershell
.\.venv\Scripts\python.exe -m evaluation.run_pipeline --config evaluation\configs\pilot.json --stage prepare
```

**Linux Bash**

```bash
./.venv/bin/python -m evaluation.run_pipeline --config evaluation/configs/pilot.json --stage prepare
```

This produces `evaluation/results/cloudtune-abc-preparation-pilot-001/` with `screening.csv`, `preparation_summary.json` and per-repository snapshots/candidates. The summary explicitly states `github_actions_runs: 0`.

### 9.3 Run Phase 1 offline tests

**Windows PowerShell**

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_evaluation_preparation.py -v
```

**Linux Bash**

```bash
./.venv/bin/python -m unittest discover -s tests -p 'test_evaluation_preparation.py' -v
```

### 9.4 Commands for future execution stages

The planned unified invocation remains `python -m evaluation.run_pipeline --config ...`. It should add explicit stages for candidate generation, validation, execution and reporting, retaining the current `prepare` stage. **Do not represent unimplemented flags/commands as runnable today.** After execution modules are implemented, document their actual CLI flags in the permanent `evaluation/PIPELINE_GUIDE.md`.

---

## 10. Test and verification requirements

### 10.1 Offline preparation tests

- CSV parsing, correct split and identity validation.
- Development and experiment-case exclusion and fork/source-family identity checks.
- Safe runnable workflow detection, unsafe workflow rejection and incomplete-tree behavior.
- Correct parsing of GitHub Actions YAML `on` key and duplicate-key rejection.
- Required dispatch missing -> `needs_harness` (no silent modification).
- Immutable original SHA/hash and reproducible snapshots despite moving upstream heads.
- Arm A unchanged candidate status `NOT_EXECUTED`.
- Config validation, run-level dry-run protection and read-only operation.

### 10.2 Later optimizer/validator tests

- `ci-cost` nonzero exit code **with** candidate output; genuinely failed generation; report-header-only change; meaningful candidate.
- B-generated path normalization and no duplicate runnable optimized workflow file.
- RAG index not ingested, empty retrieval, invalid evidence, mismatched corpus hash, `NO_CHANGE` and malformed LLM result.
- `actionlint` unavailable/failing, invalid YAML, forbidden changes, unapproved permissions, dropped required jobs/commands and artifact/runner changes.
- Review-required candidate cannot execute as safe.

### 10.3 Later execution/statistical tests

- Pinned branch/source SHA checks; fork ownership and safe cleanup.
- Lost/ambiguous POST response must not duplicate dispatch; pending run resume works.
- Failed/canceled/incomplete runs retained, and repetition/interleaving recorded.
- Paired C-B comparison only over common valid repository pairs.
- Medians and repository-level bootstrap CI correctness, negative savings and missing values.
- Distinct denominators for attempted, safe, successful, comparable and incomplete outcomes.
- Existing `scripts/` tests remain green after any shared utility extraction.

Use unit and mocked-integration tests before spending GitHub Actions minutes.

---

## 11. Implementation order and experimental rollout

### 11.1 Incremental implementation/commit order

| Commit stage | Main work | Exit criterion |
| --- | --- | --- |
| **1 — Preparation + A candidate** | New read-only repository screener, original candidate, coordinator, configs, tests, permanent guide | Reproducible immutable snapshots, offline tests, zero CI dispatches. |
| **2 — B (`ci-cost`)** | Tool adapter, normalized candidate, error/`NO_CHANGE` handling | Actual pinned `ci-cost` output can be safely archived from A snapshot. |
| **3 — C (LLM + RAG)** | Structured retrieval, generator adapter, model prompt and provenance | Candidate/`NO_CHANGE` with frozen retrieval evidence. |
| **4 — Shared validation** | YAML, `actionlint`, required checks, security and behavior constraints | B/C candidates receive the same documented safety verdict. |
| **5 — GitHub Actions execution** | Isolated refs, measured A/B/C runs, pending-state resume | One repository completes proper A/B/C repeated run protocol. |
| **6 — Reporting** | Export, paired A/B/C statistics, failure accounting | Reproducible per-repository and aggregate summary. |
| **7 — Final tests/guide** | Extended test suite, protocol documentation, stable CLI | Full end-to-end smoke tests, stable single guide, PR ready. |

**All commits go to `feature/evaluation-pipeline`**; push each tested commit to the same remote branch. Do **not** create a new branch or README per phase. Open one PR from `feature/evaluation-pipeline` to `develop` after the pipeline is complete.

### 11.2 Practical research run stages

| Stage | Repositories | Measured repetitions per arm | Purpose |
| --- | ---: | ---: | --- |
| Development smoke test | 1–3 **development** repositories | 1–3 | Test the code and policies without contaminating the held-out evaluation. |
| Frozen evaluation pilot | 10–20 held-out eligible repositories | 3 | Measure practicality, variability, rate limits, safety and budget. |
| Main evaluation | Initially 50–100 eligible repositories | 5 | Full comparison, with sample size justified by pilot variation and statistical/power needs. |

A `repository_limit: 5` preparation check is **not** five eligible repositories and is **not** statistical evidence of effectiveness. For example, 50 repositories × 3 arms × 5 repetitions means 750 measured CI executions before failures/retries/warmups; the actual number depends on eligibility and policy.

---

## 12. Definition of done and limitations

The **evaluation pipeline implementation** is complete only when it can:

- [ ] Read/screen held-out repositories and report exclusions without bias.
- [ ] Freeze the original source and one comparable target workflow for A/B/C.
- [ ] Produce A unchanged candidate, B `ci-cost` output, and C LLM + frozen RAG output.
- [ ] Record `APPLY`, `NO_CHANGE`, errors and evidence/provenance for each optimizer.
- [ ] Enforce equal safety/behavioral admission rules with `actionlint` and reviewer gates where required.
- [ ] Execute valid arms on isolated forks/branches with interleaved repetitions.
- [ ] Preserve every run outcome and resume dispatches without duplication.
- [ ] Produce validated run-level CSV, paired C-B comparison, B-A/C-A results and confidence intervals.
- [ ] Export safety, failure, abstention, timing and runner-resource statistics with complete denominators.
- [ ] Pass new offline tests and existing research regression tests.
- [ ] Keep documentation in one permanent `evaluation/PIPELINE_GUIDE.md`, leaving existing README files unchanged unless explicitly requested.

**A completed software pipeline does not mean the full research evaluation has been conducted.** The final research findings still require a justified sample, real repeated runs, accepted behavioral equivalence, uncertainty assessment and transparent limitations.

**Interpretation constraints:** no unique RAG ablation without D, no synthetic examples mistaken for external validation, no implied CI-dollar savings from duration alone, no queue-time conflation, no cherry-picking successful CI runs, no silent rewriting of old experiment results, and no destructive operations on upstream repositories.

---

## 13. References

- Repository: <https://github.com/Rami2212/CloudTune-RAG-LLM-CI-Optimization>
- Existing evaluation research protocol (leave unchanged): <https://github.com/Rami2212/CloudTune-RAG-LLM-CI-Optimization/blob/main/evaluation/README.md>
- Held-out dataset builder: <https://github.com/Rami2212/CloudTune-RAG-LLM-CI-Optimization/blob/main/evaluation/build_evaluation_repo_dataset.py>
- Existing evaluation analysis: <https://github.com/Rami2212/CloudTune-RAG-LLM-CI-Optimization/blob/main/evaluation/evaluate_rag_vs_ci_cost.py>
- Existing CI runner: <https://github.com/Rami2212/CloudTune-RAG-LLM-CI-Optimization/blob/main/scripts/run_ci_experiment.py>
- Existing batch runner: <https://github.com/Rami2212/CloudTune-RAG-LLM-CI-Optimization/blob/main/scripts/run_pattern_batch.py>
- Existing optimizer: <https://github.com/Rami2212/CloudTune-RAG-LLM-CI-Optimization/blob/main/scripts/openrouter_optimizer.py>
- Existing RAG embeddings/retrieval: <https://github.com/Rami2212/CloudTune-RAG-LLM-CI-Optimization/blob/main/scripts/embed_rag_supabase.py>
- Rule-based comparison tool: <https://github.com/mariotavarez/ci-cost>

**End of implementation plan.**
