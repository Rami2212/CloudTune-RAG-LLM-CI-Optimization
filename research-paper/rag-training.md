# RAG knowledge preparation: patterns, evaluation, and results

Snapshot: 31 October 2026. This document describes the scripts and the experiment evidence currently retained locally. Missing or deleted runs are not reconstructed from batch labels. Literature citations and their role in the research are in [citations.md](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-paper/citations.md>).

## 1. What we identified and measured

Five full-text papers supplied **25 pattern records**: S01 supplied 10, S02 four, S03 three, S04 two, and S05 six. The registry distinguishes paper findings, analyst-proposed methods, illustrative pseudocode, and locally measured cases. All five source records have human review pending, and all 25 pattern records are draft.

The inspected experiment scripts supply the selected pattern directly to the LLM with repository context. This work prepares examples for a retrieval corpus; these saved experiments do not demonstrate model fine-tuning or a completed comparison of LLM-only against LLM-plus-retrieval.

| Retained evidence | Case reports | Patterns with reports | Faster | Equal | Slower | No paired timing |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Main repository workflows | 100 | 10 | 10 | 0 | 9 | 81 |
| Synthetic scenario fixtures/replays | 62 | 13 | 21 | 26 | 13 | 2 |

The 128 main case reports contain **345 run records**: 282 baseline and 63 optimized. There are 239 usable baseline successes and 63 usable optimized successes. 21 cases have complete three-versus-three successful comparisons: 11 faster, 0 equal, and 10 slower by workflow elapsed time. Final outcomes are 76 inconclusive and 52 unsafe; none is yet `safe_success` because independent safety review remains pending.

The 81 scenario reports contain **472 repeat records**, 238 baseline and 234 optimized. 78 cases pass their behavior assertions and 3 are inconclusive. Among 78 complete paired timings, 29 are lower, 34 equal, and 15 higher by median scenario job runtime. These synthetic fixture results do not measure speedups on the source repositories.

Across both routes, **39 reports have `pattern_satisfied=true`, spanning 20 patterns**; 19 patterns have at least two qualifying reports. These automated gates do not replace independent safety or applicability review. The meaning of these labels is explained below.

## 2. What the scripts do

### 2.1 Candidate selection and batch behavior

The default input is `research-data/zenodo_20340547/pattern_repo_candidates_20.csv`: 500 ordered candidates, 20 per pattern. These are screening candidates, not confirmed pattern matches. The batch uses pattern ID plus source repository as its stable row identity. The inclusive start and stop positions refer to the original candidate CSV.

The runners seek **two qualifying examples per pattern**. After the target is reached, remaining rows can be marked `pattern_satisfied` without execution. That batch status is a quota skip; it is not another measured positive example. Reruns replace the row's summary pointer while retaining a new experiment generation. Model/configuration changes can remain in the same batch, but each case keeps its saved configuration and model.

Results are saved before fork cleanup. The runner deletes only forks it confirmed it created and retains pre-existing forks. An ordinary failed attempt stops that repository and moves to the next candidate. An unresolved run or OpenRouter HTTP error pauses the batch to preserve the attempt for resumption.

### 2.2 Main workflow experiment

Implemented in `scripts/run_pattern_batch.py`, `scripts/run_ci_experiment.py`, and `scripts/openrouter_optimizer.py`.

1. Create/reuse the selected fork, enable Actions, and choose an eligible test/build workflow from its **current default branch**. No historical CI YAML scan is performed.
2. Add `workflow_dispatch` when necessary **before pinning the baseline**. The measured baseline is therefore the prepared workflow, not necessarily byte-identical to the upstream YAML. Freeze the source commit, workflow, repository tree, selected pattern, and relevant context files.
3. Run up to **three sequential baseline measurements with zero warmups**. Required job names are inferred from observed baseline jobs; they are not an owner-approved branch-protection contract. Stop on the first unexpected failure/cancellation or unusable result.
4. Send the selected pattern, baseline records, required job names, workflow YAML, and bounded relevant manifest/path context to a specific free OpenRouter model. The prompt requests one concrete **APPLY** change even when expected benefit is uncertain. Save request, response, model/usage, proposal, before/after YAML, diff, and hashes.
5. Parse YAML and enforce the protected workload structure plus selected-pattern scope checks. Cache and timeout mechanisms have bounded validators. Seven other main mechanisms currently lack dedicated supported change validation. Run `actionlint` when installed; otherwise record that it was unavailable. All 73 retained main proposals record actionlint as not installed, so their automatic checks used YAML parsing and bounded structural validation.
6. Create a candidate revision on an isolated experiment branch, preserving non-workflow source, and run up to **three optimized measurements**. Correlate the workflow path/ID, branch, commit SHA, run attempt, and run ID. Retain failures and cancellations. Stop the case on the first unexpected result.
7. Report medians, timing change, validation findings, satisfaction, overall outcome, and admission status. Trials run in baseline and optimized blocks, rather than randomized/interleaved order. Cache state is explicitly uncontrolled.

**Workflow elapsed seconds** run from `run_started_at` to final job completion. **Summed job runtime** adds all job start-to-completion durations; parallel jobs can make this total exceed workflow elapsed time. These metrics are not billing cost. Main medians use only successful, protocol-valid measurements with complete timing and passing required observed jobs. A median from a partial baseline does not make a complete experiment.

**Reduction (%) = 100 × (baseline median − optimized median) / baseline median.** Positive values mean faster, negative values mean slower, and missing values remain missing.

### 2.3 Scenario experiment

Implemented in `scripts/run_scenario_batch.py`, `scripts/scenario_experiments.py`, and `scripts/scenario_replay.py`.

Ten patterns require scenario support because ordinary dispatch timing does not faithfully test their event, cancellation, scheduling, queue, or prediction behavior. The scenario runner creates a dedicated `ct-scenario` fork, archives original workflow context, disables inherited workflow listeners, and builds synthetic fixture branches. The measured fixture does not execute the original repository's workload.

The LLM receives the **exact allowed semantic treatment** through a scenario contract, and the checker requires that treatment. The LLM implements the supplied policy; it does not discover the scenario policy. Baseline and optimized suites each run three times. Expected failures, cancellations, and suppressed runs count as passing scenario behavior when the assertions require them.

Four patterns use controlled push events: FAIL-FAST, CANCEL-STALE, SKIP-WORKFLOW, and CHANGE-FILTER. Six use deterministic service-policy replays inside a hosted one-job fixture: FAIL-SCHEDULE, IDLE-SCHEDULE, FAILED-JOB-FIRST, BUILD-PRIORITY, BUILD-SELECT, and DURATION-PREDICTION. Replay traces are reproduced locally from frozen inputs/engine and linked to the hosted run ID.

Scenario timing compares **median summed job runtime across each repetition's events**. Replays also retain separate simulated work, missed-failure, and prediction-error metrics when applicable. A Python replay taking four seconds instead of three is distinct from the simulated workload it describes; it does not establish a 25% real repository speedup.

### 2.4 Meaning of the result labels

| Field | Main workflow | Scenario |
| --- | --- | --- |
| `pattern_satisfied` | Changed and structurally accepted YAML; exactly three usable successful measurements per arm; optimized median elapsed strictly lower. | Changed fixture/policy; three passing suites per arm; optimized median summed scenario job runtime strictly lower. |
| `inconclusive` | Insufficient comparable measurements and/or pending independent safety/change-specific behavior review. Can coexist with `pattern_satisfied=true`. | Incomplete suite or failed behavior assertions. |
| `unsafe` | Structural/workload/scope gate rejected the proposal; it can be rejected before optimized execution. | Scope/assertion errors stop the attempt; none of the retained scenario cases has this outcome. |
| `safe_success` | All review/behavior gates pass and a real change meets the minimum saving, configured as 5% in these cases. No retained case currently qualifies. | Not assigned to synthetic cases. |
| `scenario_passed` | Not a main outcome. | All six repeat records pass assertions, irrespective of timing direction. |
| RAG admission | All 128 cases are `pending_review`. | All 81 are `controlled_scenario_only_pending_applicability_review`. |

The main satisfaction expression is a narrower automatic gate than final independent safety approval. It does not itself establish owner-approved required checks or semantic equivalence. The generic pending behavior-review reason mentions caching even on timeout cases; it should not be read as evidence that cache tests were executed.

## 3. Pattern coverage and detailed results

The current all-pattern results and batch-row summaries are also available in [patterns-test-results.md](patterns-test-results.md). The detailed examples below link to retained artifacts. “Saved cases” excludes preparation failures, quota skips, blocked rows, and missing reports. Main tables use successful/recorded run counts; scenario tables use passing/recorded repeat-suite counts. B/O means baseline/optimized. Missing timings are shown as —.

| # | Pattern | Route | Saved | Faster / equal / slower | Unpaired | Case reports with `pattern_satisfied=true` |
| ---: | --- | --- | ---: | --- | ---: | --- |
| 1 | P-LIT-GHA-CACHE | Main | 4 | 2 / 0 / 2 | 0 | 2 / 2 |
| 2 | P-LIT-FAIL-FAST | Scenario | 2 | 2 / 0 / 0 | 0 | 2 / 2 |
| 3 | P-LIT-CANCEL-STALE | Scenario | 3 | 2 / 1 / 0 | 0 | 2 / 2 |
| 4 | P-LIT-SKIP-WORKFLOW | Scenario | 2 | 2 / 0 / 0 | 0 | 2 / 2 |
| 5 | P-LIT-CHANGE-FILTER | Scenario | 2 | 2 / 0 / 0 | 0 | 2 / 2 |
| 6 | P-LIT-CUSTOM-TIMEOUT | Main | 3 | 2 / 0 / 1 | 0 | 2 / 2 |
| 7 | P-LIT-FAIL-SCHEDULE | Scenario | 2 | 2 / 0 / 0 | 0 | 2 / 2 |
| 8 | P-LIT-IDLE-SCHEDULE | Scenario | 2 | 2 / 0 / 0 | 0 | 2 / 2 |
| 9 | P-LIT-FAILED-JOB-FIRST | Scenario | 4 | 2 / 2 / 0 | 0 | 2 / 2 |
| 10 | P-LIT-HISTORY-TIMEOUT | Main | 10 | 2 / 0 / 2 | 6 | 2 / 2 |
| 11 | P-LIT-PRIORITIZE | Both | 38 | 3 / 1 / 2 | 32 | 2 / 2 |
| 12 | P-LIT-BUILD-PRIORITY | Scenario | 5 | 1 / 2 / 2 | 0 | 1 / 2 |
| 13 | P-LIT-SELECT | Both | 17 | 0 / 3 / 6 | 8 | 0 / 2 |
| 14 | P-LIT-BUILD-SELECT | ci_service | 0 | 0 / 0 / 0 | 0 | 0 / 2 |
| 15 | P-LIT-BAZEL-PARALLEL | Scenario | 6 | 0 / 5 / 1 | 0 | 0 / 2 |
| 16 | P-LIT-BAZEL-INCREMENTAL | build_configuration | 0 | 0 / 0 / 0 | 0 | 0 / 2 |
| 17 | P-LIT-BAZEL-DEPS | Scenario | 8 | 2 / 5 / 1 | 0 | 2 / 2 |
| 18 | P-LIT-ENV-CACHE | Scenario | 13 | 2 / 7 / 2 | 2 | 2 / 2 |
| 19 | P-LIT-UNAFFECTED-STEPS | Both | 17 | 2 / 5 / 1 | 9 | 2 / 2 |
| 20 | P-LIT-SMELL-REPAIR | Both | 23 | 2 / 0 / 0 | 21 | 2 / 2 |
| 21 | P-LIT-DURATION-PREDICTION | research_only | 0 | 0 / 0 / 0 | 0 | 0 / 2 |
| 22 | P-LIT-UNUSED-OUTPUTS | Both | 21 | 2 / 2 / 1 | 16 | 2 / 2 |
| 23 | P-LIT-DISTRIBUTED-CACHE | Main | 7 | 2 / 0 / 3 | 2 | 2 / 2 |
| 24 | P-LIT-CONFIG-REUSE | Main | 5 | 2 / 0 / 0 | 3 | 2 / 2 |
| 25 | P-LIT-UNUSED-DEP-SKIP | Both | 15 | 2 / 1 / 1 | 11 | 2 / 2 |

These satisfaction counts are case-level counts across all saved main and scenario reports. They are not the batch-local `pattern_progress.csv` successful-example counts. The CSV counts distinct repositories in that batch only when its row completed successfully, the case passes the pattern gate, and optimized median runtime is lower than baseline.

### 3.1 Inventory included in this snapshot

The tables and pattern summaries above use all 128 retained main reports and 81 retained scenario reports. This is a full retained-file snapshot, not a count of distinct repositories; a repository can have separate attempts. Batch row counts and statuses are summarized in Section 4.

### 1. P-LIT-GHA-CACHE — Cache dependency downloads

**Identified mechanism:** dependency_cache. **Citation:** S01; 4.2.1; Table 4; PDF pp. 6, 7.

**Literature finding:** Caching has modest aggregate benefit. Evidence label: reported_benefit.

**Catalog application method (analyst synthesis):** Choose dependency download state rather than unchecked build outputs; Keep installation and all required tests.

**Conditions:** Repeated dependency fetching is measurable; Cache inputs include lockfile and environment. **Risks/contraindications:** Mutable or untrusted cached content; An equivalent cache already exists.

**What our script evaluates:** The main LLM adds dependency-download caching or configures an existing setup action. The validator permits recognized narrow cache steps/options while preserving original commands and structure. Saved cases cover Cargo, Ruby, Gradle, and Go. Cache state is uncontrolled; no dedicated cold/warm/lockfile-invalidation experiments are recorded.


| Source repository | B/O successful runs | Median elapsed seconds B → O | Reduction | Median summed job seconds B → O | Satisfied | Saved outcome | Evidence |
| --- | --- | --- | ---: | --- | --- | --- | --- |
| 3hren/msgpack-rust | 3/3; 3/3 | 33 → 36 | -9.09% | 53 → 57 | no | inconclusive | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-interactive-three--87ed1d219ea5ab9c/case.json>) |
| 88250/lute | 3/3; 3/3 | 33 → 31 | 6.06% | 29 → 28 | yes | inconclusive | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-interactive-three--f6d2974a5cef7cc9/case.json>) |
| aaronlasseigne/active_interaction | 3/3; 3/3 | 37 → 38 | -2.70% | 175 → 202 | no | inconclusive | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-interactive-three--3955f80b6d0b0955/case.json>) |
| acmerobotics/road-runner | 3/3; 3/3 | 98 → 78 | 20.41% | 95 → 74 | yes | inconclusive | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-interactive-three--91c08fe132959200/case.json>) |

- **3hren/msgpack-rust:** Added actions/cache@v4 for ~/.cargo/registry and ~/.cargo/git, keyed by runner OS and checked-in Cargo.lock hashes. Three successful runs per arm; independent safety and change-specific review pending. Model: nvidia/nemotron-3-ultra-550b-a55b:free. [run records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-interactive-three--87ed1d219ea5ab9c/run_records.json>); [diff](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-interactive-three--87ed1d219ea5ab9c/change.diff>).
- **88250/lute:** Added actions/cache@v4 for ~/go/pkg/mod keyed by runner OS plus go.mod/go.sum hashes. Three successful runs per arm; independent safety and change-specific review pending. Model: nvidia/nemotron-3-ultra-550b-a55b:free. [run records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-interactive-three--f6d2974a5cef7cc9/run_records.json>); [diff](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-interactive-three--f6d2974a5cef7cc9/change.diff>).
- **aaronlasseigne/active_interaction:** Added actions/cache@v4 steps for vendor/bundle alongside existing bundler caching, with Ruby/lockfile-derived keys and restore-key fallbacks. Three successful runs per arm; independent safety and change-specific review pending. Model: nvidia/nemotron-3-ultra-550b-a55b:free. [run records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-interactive-three--3955f80b6d0b0955/run_records.json>); [diff](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-interactive-three--3955f80b6d0b0955/change.diff>).
- **acmerobotics/road-runner:** Added actions/cache@v4 for ~/.gradle/caches keyed by runner OS and Gradle build/wrapper file hashes. Three successful runs per arm; independent safety and change-specific review pending. Model: nvidia/nemotron-3-ultra-550b-a55b:free. [run records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-interactive-three--91c08fe132959200/run_records.json>); [diff](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-interactive-three--91c08fe132959200/change.diff>).

**Recorded batch coverage:** completed: 5; pattern_satisfied: 14; running: 1. Counts combine all five batch CSVs, including retries and quota skips.

**Interpretation:** Two of four retained comparisons are faster and two slower. Road-runner improves 20.41% and lute 6.06%. The Ruby candidate rationale acknowledges existing bundler caching, so selection does not guarantee initially unoptimized YAML. All four overall outcomes remain inconclusive pending review. The Ruby diff includes restore-key fallbacks even though the prompt requests exact keys without broad fallbacks; the bounded validator accepted that syntax. This shows why prompt requirements and semantic cache safety require a separate review.

**Missing detailed evidence:** 11ty/webc is marked completed, inconclusive, and example_satisfied=True in the batch, but its referenced case report is missing. It is excluded from the measured counts/timings above. 24pullrequests/24pullrequests is marked running without a retained case report.

### 2. P-LIT-FAIL-FAST — Cancel remaining matrix jobs after failure

**Identified mechanism:** matrix_fail_fast. **Citation:** S01; 4.2.2; Table 4; PDF pp. 6, 7.

**Literature finding:** Matrix cancellation saves remaining work. Evidence label: estimated_benefit.

**Catalog application method (analyst synthesis):** Evaluate the contract before changing cancellation; Record canceled jobs.

**Conditions:** Matrix failure makes remaining results dispensable under an explicit study policy. **Risks/contraindications:** Every matrix outcome is required; Full failure diagnostics are required.

**What our script evaluates:** A three-cell matrix starts with fail-fast disabled. A tagged failing cell exits after a controlled delay; healthy cells perform a longer workload. The LLM may only enable fail-fast. Assertions require the failing cell to fail, healthy cells to complete in baseline and be cancelled in the candidate, all cells to remain present, and an independent healthy matrix control to pass. Deliberate workflow failure is expected.


| Source-repository label | B/O passing suites | Median scenario job seconds B → O | Reduction | Satisfied | Saved outcome | Evidence |
| --- | --- | --- | ---: | --- | --- | --- |
| 1bardesign/batteries | 3/3; 3/3 | 485 → 482 | 0.62% | yes | scenario_passed | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-4bb0552aeb09c242/case.json>) |
| 3kh0/ext-remover | 3/3; 3/3 | 487 → 481 | 1.23% | yes | scenario_passed | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-b6e04fef7ef24997/case.json>) |


**Recorded batch coverage:** blocked: 20; completed: 2; pattern_satisfied: 18. Counts combine all five batch CSVs, including retries and quota skips.

**Interpretation:** Both fixtures pass failure/cancellation and healthy-control assertions and have slightly lower total scenario job runtime. The totals include failure probes plus healthy controls, not the source repositories' original tests.

### 3. P-LIT-CANCEL-STALE — Cancel superseded runs

**Identified mechanism:** stale_run_cancellation. **Citation:** S01; 4.2.3; Table 4; PDF pp. 7.

**Literature finding:** Superseding runs can reduce duplicate work. Evidence label: estimated_benefit.

**Catalog application method (analyst synthesis):** Partition cancellation by workflow and branch/PR; Preserve run identity and audit records.

**Conditions:** Runs represent the same workflow and branch or PR; A newer revision supersedes older checks. **Risks/contraindications:** Release or deployment work; Distinct branches share a cancellation group.

**What our script evaluates:** Two overlapping revisions of the same branch and an independent-branch control are pushed. The only allowed change adds concurrency grouped by workflow and ref with cancel-in-progress enabled. Assertions require actual overlap, cancellation of the old revision, completion of the latest revision, and branch isolation.


| Source-repository label | B/O passing suites | Median scenario job seconds B → O | Reduction | Satisfied | Saved outcome | Evidence |
| --- | --- | --- | ---: | --- | --- | --- |
| apache/datasketches-memory | 3/3; 3/3 | 279 → 277 | 0.72% | yes | scenario_passed | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-9a54817daee8f7d5/case.json>) |
| apache/echarts-doc | 3/3; 3/3 | 279 → 279 | 0.00% | no | scenario_passed | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-353807a2fd973dee/case.json>) |
| apache/felix-dev | 3/3; 3/3 | 278 → 275 | 1.08% | yes | scenario_passed | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-560f8aa17cf2dbe5/case.json>) |


**Recorded batch coverage:** blocked: 20; completed: 3; pattern_satisfied: 17. Counts combine all five batch CSVs, including retries and quota skips.

**Interpretation:** Three fixtures pass behavior assertions; two are faster in total scenario job runtime and one unchanged. The commits and workload are controlled fixtures.

### 4. P-LIT-SKIP-WORKFLOW — Skip explicitly dispensable workflow runs

**Identified mechanism:** workflow_skip. **Citation:** S01; 4.2.4; Table 4; PDF pp. 7.

**Literature finding:** Explicit skipping has limited aggregate impact. Evidence label: estimated_benefit.

**Catalog application method (analyst synthesis):** Treat as behavior-changing rather than a safe default; Require evidence about affected checks.

**Conditions:** Repository policy permits a specific run to be omitted. **Risks/contraindications:** Strict contract requires all triggers to execute.

**What our script evaluates:** The allowed commit policy sets the dispensable suffix to [skip ci]. Baseline runs a documentation-only event; the candidate must suppress it while source controls before and after still pass. Absence is observed over the saved bounded window, normally 120 seconds. This treatment is a commit-message policy, not a native workflow setting.


| Source-repository label | B/O passing suites | Median scenario job seconds B → O | Reduction | Satisfied | Saved outcome | Evidence |
| --- | --- | --- | ---: | --- | --- | --- |
| aws-actions/amazon-ecr-login | 3/3; 3/3 | 23 → 15 | 34.78% | yes | scenario_passed | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-e5ec5fb29a4646a4/case.json>) |
| azure/azure-storage-azcopy | 3/3; 3/3 | 23 → 15 | 34.78% | yes | scenario_passed | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-5d87797ead07c98e/case.json>) |


**Recorded batch coverage:** blocked: 20; completed: 2; pattern_satisfied: 18. Counts combine all five batch CSVs, including retries and quota skips.

**Interpretation:** Both fixtures pass positive controls and show lower scenario job runtime through suppression of a known dispensable event. Original repository required-check/branch-protection behavior remains unverified.

### 5. P-LIT-CHANGE-FILTER — Filter workflow triggers by changed paths

**Identified mechanism:** change_aware_filtering. **Citation:** S01; 4.2.5; Table 4; PDF pp. 7.

**Literature finding:** Path filters have limited aggregate impact. Evidence label: estimated_benefit.

**Catalog application method (analyst synthesis):** Map checks to relevant inputs before defining filters; Retain coverage for configuration changes.

**Conditions:** Changed-file dependencies are understood; Required-status semantics are preserved. **Risks/contraindications:** Shared configuration, generators or dependencies affect supposedly unrelated paths.

**What our script evaluates:** The allowed change adds push path filters for src/**, config/**, and .github/workflows/**. Documentation-only, source, configuration, and mixed commits are exercised. Assertions require documentation suppression and successful relevant-change controls, including source events before and after suppression.


| Source-repository label | B/O passing suites | Median scenario job seconds B → O | Reduction | Satisfied | Saved outcome | Evidence |
| --- | --- | --- | ---: | --- | --- | --- |
| axosoft/nsfw | 3/3; 3/3 | 39 → 31 | 20.51% | yes | scenario_passed | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-879ee0ca9318e6ef/case.json>) |
| azu/irodr | 3/3; 3/3 | 38 → 30 | 21.05% | yes | scenario_passed | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-569c9da25d76e527/case.json>) |


**Recorded batch coverage:** blocked: 20; completed: 2; pattern_satisfied: 18. Counts combine all five batch CSVs, including retries and quota skips.

**Interpretation:** Both fixtures pass controls and show lower scenario job runtime. The path mapping is supplied by the fixture rather than inferred and validated for the original repository.

### 6. P-LIT-CUSTOM-TIMEOUT — Bound jobs with a custom timeout

**Identified mechanism:** job_timeout. **Citation:** S01; 4.2.6; Table 4; PDF pp. 7, 8.

**Literature finding:** Custom timeouts reduce runaway consumption. Evidence label: estimated_benefit.

**Catalog application method (analyst synthesis):** Choose an explicit budget with operational headroom; Measure false timeout failures separately.

**Conditions:** Representative successful-duration history exists. **Risks/contraindications:** Valid slow runs exceed the proposed limit.

**What our script evaluates:** The main LLM receives three fresh baseline records and may only alter job timeout-minutes, constrained to integers 1–360. Saved candidates set five-minute limits. The ordinary successful workflow is repeated three times after the change. No deliberately hung-job or slow-valid-run test is recorded.


| Source repository | B/O successful runs | Median elapsed seconds B → O | Reduction | Median summed job seconds B → O | Satisfied | Saved outcome | Evidence |
| --- | --- | --- | ---: | --- | --- | --- | --- |
| banbox/banbot | 3/3; 3/3 | 39 → 40 | -2.56% | 35 → 37 | no | inconclusive | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-interactive-three--95cee2bdf26dc012/case.json>) |
| blizzhackers/kolbot | 3/3; 3/3 | 41 → 30 | 26.83% | 34 → 27 | yes | inconclusive | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-interactive-three--fb8b16eb65a11508/case.json>) |
| bmc-toolbox/bmclib | 3/3; 3/3 | 143 → 129 | 9.79% | 249 → 239 | yes | inconclusive | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-interactive-three--112e2b2e7fbe04b8/case.json>) |

- **banbox/banbot:** Added timeout-minutes: 5 to the build matrix job. Three successful runs per arm; independent safety and change-specific review pending. Model: nvidia/nemotron-3-ultra-550b-a55b:free. [run records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-interactive-three--95cee2bdf26dc012/run_records.json>); [diff](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-interactive-three--95cee2bdf26dc012/change.diff>).
- **blizzhackers/kolbot:** Added timeout-minutes: 5 to checks. Three successful runs per arm; independent safety and change-specific review pending. Model: nvidia/nemotron-3-ultra-550b-a55b:free. [run records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-interactive-three--fb8b16eb65a11508/run_records.json>); [diff](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-interactive-three--fb8b16eb65a11508/change.diff>).
- **bmc-toolbox/bmclib:** Added timeout-minutes: 5 to lint and test jobs. Three successful runs per arm; independent safety and change-specific review pending. Model: nvidia/nemotron-3-ultra-550b-a55b:free. [run records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-interactive-three--112e2b2e7fbe04b8/run_records.json>); [diff](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-interactive-three--112e2b2e7fbe04b8/change.diff>).

**Recorded batch coverage:** cleanup_pending: 1; completed: 2; pattern_satisfied: 15; preparation_failed: 1; running: 1. Counts combine all five batch CSVs, including retries and quota skips.

**Interpretation:** Two comparisons are faster and one slower. A timeout above normal runtime does not make healthy work execute faster by itself. These are observed pilot timing differences, not demonstrated causal timeout savings or validated protection against hangs.

### 7. P-LIT-FAIL-SCHEDULE — Pause repeatedly failing scheduled workflows

**Identified mechanism:** failing_schedule_suppression. **Citation:** S01; 4.3.1; Tables 5-6; PDF pp. 8, 9.

**Literature finding:** Failure-streak suppression offers estimated savings. Evidence label: estimated_benefit.

**Catalog application method (analyst synthesis):** Notify the owner when pausing; Define an explicit recovery and reactivation path.

**Conditions:** A monitored pause/resume policy is approved. **Risks/contraindications:** Continuous monitoring or periodic checks are mandatory.

**What our script evaluates:** A deterministic replay changes pause_after_failures from 0 to 2, enables notification, and retains explicit owner reset. Its event stream verifies the failure threshold, suppression, notification, owner reset, recovery, and success resetting the failure counter. Threshold 2 is this fixture's adaptation, not an exact replication of S01's proposed threshold. The policy runs in a hosted single-job fixture and is reproduced locally for saved traces.


| Source-repository label | B/O passing suites | Median scenario job seconds B → O | Reduction | Satisfied | Saved outcome | Evidence |
| --- | --- | --- | ---: | --- | --- | --- |
| cylab-tw/bluelight | 3/3; 3/3 | 4 → 3 | 25.00% | yes | scenario_passed | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-50c8bbe3faa57e20/case.json>) |
| davidstone/bounded-integer | 3/3; 3/3 | 4 → 3 | 25.00% | yes | scenario_passed | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-635cbb2ebf51a46a/case.json>) |

- **cylab-tw/bluelight:** median simulated work 90 → 70 seconds. [baseline repeat-2 trace](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-50c8bbe3faa57e20/replays/baseline-2.json>); [optimized repeat-2 trace](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-50c8bbe3faa57e20/replays/optimized-2.json>); [all repeat records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-50c8bbe3faa57e20/run_records.json>).
- **davidstone/bounded-integer:** median simulated work 90 → 70 seconds. [baseline repeat-2 trace](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-635cbb2ebf51a46a/replays/baseline-2.json>); [optimized repeat-2 trace](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-635cbb2ebf51a46a/replays/optimized-2.json>); [all repeat records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-635cbb2ebf51a46a/run_records.json>).

**Recorded batch coverage:** blocked: 20; completed: 2; pattern_satisfied: 18. Counts combine all five batch CSVs, including retries and quota skips.

**Interpretation:** Both fixtures show hosted replay runtime 4 to 3 seconds. Separately, median simulated work is 90 to 70 seconds (22.22% lower) with threshold, notification, and recovery checks passing. Simulated savings and a one-second hosted runtime difference are distinct measurements.

### 8. P-LIT-IDLE-SCHEDULE — Suppress schedules during repository inactivity

**Identified mechanism:** scheduled_run_reduction. **Citation:** S01; 4.3.2; Table 5; PDF pp. 8, 9.

**Literature finding:** Inactivity suppression saves some scheduled work. Evidence label: estimated_benefit.

**Catalog application method (analyst synthesis):** Identify meaningful activity rather than generated self-updates; Resume when relevant inputs change.

**Conditions:** Periodic results depend only on repository changes. **Risks/contraindications:** External dependencies, security or time-based requirements need fresh checks.

**What our script evaluates:** A deterministic replay enables suppress_unchanged_inputs. Events include idle ticks, generated commits, external-dependency changes, and user source changes. Assertions check idle/generated suppression and resumption after meaningful input changes. The runner does not wait for original repository cron events.


| Source-repository label | B/O passing suites | Median scenario job seconds B → O | Reduction | Satisfied | Saved outcome | Evidence |
| --- | --- | --- | ---: | --- | --- | --- |
| fastify/fastify-http-proxy | 3/3; 3/3 | 4 → 3 | 25.00% | yes | scenario_passed | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-af3418dae00ed8c4/case.json>) |
| file/file | 3/3; 3/3 | 4 → 3 | 25.00% | yes | scenario_passed | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-c7f93f541d728521/case.json>) |

- **fastify/fastify-http-proxy:** median simulated work 70 → 30 seconds. [baseline repeat-2 trace](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-af3418dae00ed8c4/replays/baseline-2.json>); [optimized repeat-2 trace](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-af3418dae00ed8c4/replays/optimized-2.json>); [all repeat records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-af3418dae00ed8c4/run_records.json>).
- **file/file:** median simulated work 70 → 30 seconds. [baseline repeat-2 trace](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-c7f93f541d728521/replays/baseline-2.json>); [optimized repeat-2 trace](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-c7f93f541d728521/replays/optimized-2.json>); [all repeat records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-c7f93f541d728521/run_records.json>).

**Recorded batch coverage:** blocked: 20; completed: 2; pattern_satisfied: 18. Counts combine all five batch CSVs, including retries and quota skips.

**Interpretation:** Both fixtures show hosted runtime 4 to 3 seconds. Median simulated work is 70 to 30 seconds (57.14% lower), retaining meaningful-input controls. These are synthetic event-stream results.

### 9. P-LIT-FAILED-JOB-FIRST — Run previously failing jobs first

**Identified mechanism:** history_based_job_gating. **Citation:** S01; 4.3.3; Table 5; PDF pp. 8, 9.

**Literature finding:** Failure-first gating saves work on failures. Evidence label: estimated_benefit.

**Catalog application method (analyst synthesis):** Separate early feedback from cancellation-based savings; Preserve the dependency graph.

**Conditions:** Required dependencies allow reordering; Policy permits stopping after an earlier failure. **Risks/contraindications:** Independent outcomes must all be collected; Adding a gate would hide required results.

**What our script evaluates:** A deterministic serial job-DAG replay changes declared order to previous_failure_ancestors_first. Lint, compile, test, and package jobs exercise recurrent failure, recovery, and artifact dependencies. Assertions preserve the job set, prerequisites, and outcomes; other jobs are not cancelled.


| Source-repository label | B/O passing suites | Median scenario job seconds B → O | Reduction | Satisfied | Saved outcome | Evidence |
| --- | --- | --- | ---: | --- | --- | --- |
| clojure/java.jdbc | 3/3; 3/3 | 4 → 3 | 25.00% | yes | scenario_passed | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-c4031f01d86b1653/case.json>) |
| cloudwego/biz-demo | 3/3; 3/3 | 3 → 3 | 0.00% | no | scenario_passed | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-64cb21318a2cfa2f/case.json>) |
| coldfix/udiskie | 3/3; 3/3 | 4 → 4 | 0.00% | no | scenario_passed | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-787e550913a7bb8f/case.json>) |
| comtihon/mongodb-erlang | 3/3; 3/3 | 4 → 3 | 25.00% | yes | scenario_passed | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-6e84419c6d8620c3/case.json>) |

- **clojure/java.jdbc:** median simulated work 282 → 282 seconds. [baseline repeat-2 trace](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-c4031f01d86b1653/replays/baseline-2.json>); [optimized repeat-2 trace](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-c4031f01d86b1653/replays/optimized-2.json>); [all repeat records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-c4031f01d86b1653/run_records.json>).
- **cloudwego/biz-demo:** median simulated work 282 → 282 seconds. [baseline repeat-2 trace](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-64cb21318a2cfa2f/replays/baseline-2.json>); [optimized repeat-2 trace](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-64cb21318a2cfa2f/replays/optimized-2.json>); [all repeat records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-64cb21318a2cfa2f/run_records.json>).
- **coldfix/udiskie:** median simulated work 282 → 282 seconds. [baseline repeat-2 trace](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-787e550913a7bb8f/replays/baseline-2.json>); [optimized repeat-2 trace](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-787e550913a7bb8f/replays/optimized-2.json>); [all repeat records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-787e550913a7bb8f/run_records.json>).
- **comtihon/mongodb-erlang:** median simulated work 282 → 282 seconds. [baseline repeat-2 trace](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-6e84419c6d8620c3/replays/baseline-2.json>); [optimized repeat-2 trace](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-6e84419c6d8620c3/replays/optimized-2.json>); [all repeat records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-6e84419c6d8620c3/run_records.json>).

**Recorded batch coverage:** blocked: 20; completed: 4; pattern_satisfied: 16. Counts combine all five batch CSVs, including retries and quota skips.

**Interpretation:** Four fixtures pass ordering/dependency assertions. Two hosted runtimes improve 4 to 3 seconds; two are unchanged. Simulated total work is unchanged at median 282 seconds. Repeat 2 gives first failure feedback at 90 versus 30 simulated seconds: improved feedback without reduced simulated total work.

### 10. P-LIT-HISTORY-TIMEOUT — Derive timeout candidates from successful history

**Identified mechanism:** history_based_timeout. **Citation:** S01; 4.3.4; Table 5; PDF pp. 9.

**Literature finding:** History-based timeout savings are retrospective estimates. Evidence label: estimated_benefit.

**Catalog application method (analyst synthesis):** Use past data only when proposing a limit; Evaluate the candidate on future slow and cold runs.

**Conditions:** Successful job history is representative. **Risks/contraindications:** New workloads or runners invalidate historical bounds.

**What our script evaluates:** The current workflow is used, with fresh baseline observations supplied to the LLM. The script does not retrieve historical CI YAML. A timeout-only validator bounds edits, but timeout values are LLM proposals rather than a deterministic implemented quantile/history-estimation algorithm. Failed baselines stop the case before optimization.


| Source repository | B/O successful runs | Median elapsed seconds B → O | Reduction | Median summed job seconds B → O | Satisfied | Saved outcome | Evidence |
| --- | --- | --- | ---: | --- | --- | --- | --- |
| chimera-linux/chimerautils | 1/2; 0/0 | 66 → — | — | 108 → — | no | inconclusive | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-5001e9c916045f12/case.json>) |
| cloudfoundry/credhub | 3/3; 3/3 | 404 → 414 | -2.48% | 400 → 410 | no | inconclusive | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-08b9348230b95d1e/case.json>) |
| cmake-js/cmake-js | 0/1; 0/0 | — → — | — | — → — | no | inconclusive | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-63903acdf1d9c3e7/case.json>) |
| cocalele/pureflash | 0/1; 0/0 | — → — | — | — → — | no | inconclusive | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-2c3a7645b8e59880/case.json>) |
| commenthol/date-holidays | 3/3; 0/0 | 89 → — | — | 127 → — | no | unsafe | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-2ff4491fb6161a82/case.json>) |
| confluentinc/parallel-consumer | 0/1; 0/0 | — → — | — | — → — | no | inconclusive | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-9effc3428fb24639/case.json>) |
| cookpad/garage | 0/1; 0/0 | — → — | — | — → — | no | inconclusive | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-19f8afb89b2c7a8e/case.json>) |
| csinva/imodels | 3/3; 3/3 | 295 → 296 | -0.34% | 765 → 690 | no | inconclusive | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-7c1ff7ef9466c9aa/case.json>) |
| cyberark/conjur | 3/3; 3/3 | 16 → 15 | 6.25% | 23 → 20 | yes | inconclusive | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-a14b642d809bf336/case.json>) |
| cyberchitta/openai_ex | 3/3; 3/3 | 29 → 28 | 3.45% | 41 → 45 | yes | inconclusive | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-ca499b3aaef0d029/case.json>) |

- **chimera-linux/chimerautils:** Baseline measured attempt 2 failed (run 40701492112, conclusion=failure, reason=REQUIRED_CHECK_MISSING_OR_NOT_SUCCESSFUL;CI_failure); stopping this repository after the first failed attempt Model: No saved successful LLM response. [run records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-5001e9c916045f12/run_records.json>).
- **cloudfoundry/credhub:** Added timeout-minutes: 10 to build. Three successful runs per arm; independent safety and change-specific review pending. Model: google/gemma-4-26b-a4b-it:free. [run records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-08b9348230b95d1e/run_records.json>); [diff](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-08b9348230b95d1e/change.diff>).
- **cmake-js/cmake-js:** Baseline measured attempt 1 failed (run 40708428791, conclusion=failure, reason=REQUIRED_CHECK_MISSING_OR_NOT_SUCCESSFUL;CI_failure); stopping this repository after the first failed attempt Model: No saved successful LLM response. [run records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-63903acdf1d9c3e7/run_records.json>).
- **cocalele/pureflash:** Baseline measured attempt 1 failed (run 40718477576, conclusion=failure, reason=REQUIRED_CHECK_MISSING_OR_NOT_SUCCESSFUL;CI_failure); stopping this repository after the first failed attempt Model: No saved successful LLM response. [run records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-2c3a7645b8e59880/run_records.json>).
- **commenthol/date-holidays:** SELECTED_TIMEOUT_PATTERN_SCOPE_EXCEEDED Model: google/gemma-4-26b-a4b-it:free. [run records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-2ff4491fb6161a82/run_records.json>); [diff](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-2ff4491fb6161a82/change.diff>).
- **confluentinc/parallel-consumer:** Baseline measured attempt 1 failed (run 40723451040, conclusion=cancelled, reason=REQUIRED_CHECK_MISSING_OR_NOT_SUCCESSFUL;CI_cancelled); stopping this repository after the first failed attempt Model: No saved successful LLM response. [run records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-9effc3428fb24639/run_records.json>).
- **cookpad/garage:** Baseline measured attempt 1 failed (run 40727535080, conclusion=failure, reason=REQUIRED_CHECK_MISSING_OR_NOT_SUCCESSFUL;CI_failure); stopping this repository after the first failed attempt Model: No saved successful LLM response. [run records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-19f8afb89b2c7a8e/run_records.json>).
- **csinva/imodels:** Added timeout-minutes: 15 to the build matrix job. Three successful runs per arm; independent safety and change-specific review pending. Model: google/gemma-4-26b-a4b-it:free. [run records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-7c1ff7ef9466c9aa/run_records.json>); [diff](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-7c1ff7ef9466c9aa/change.diff>).
- **cyberark/conjur:** Added timeout-minutes: 5 to rebase_job and commit_style. Three successful runs per arm; independent safety and change-specific review pending. Model: google/gemma-4-26b-a4b-it:free. [run records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-a14b642d809bf336/run_records.json>); [diff](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-a14b642d809bf336/change.diff>).
- **cyberchitta/openai_ex:** Added timeout-minutes: 5 to the test matrix job. Three successful runs per arm; independent safety and change-specific review pending. Model: google/gemma-4-26b-a4b-it:free. [run records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-ca499b3aaef0d029/run_records.json>); [diff](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-ca499b3aaef0d029/change.diff>).

**Recorded batch coverage:** completed: 4; failed: 6; pattern_satisfied: 3; preparation_failed: 7. Counts combine all five batch CSVs, including retries and quota skips.

**Interpretation:** Four cases have complete paired measurements: two faster and two slower. Six lack comparable optimized measurements. Positive examples conjur (16 to 15 seconds, 6.25%) and openai_ex (29 to 28 seconds, 3.45%) are small differences; the latter is below the 5% final safe_success threshold. Both still require review.

### 11. P-LIT-PRIORITIZE — Prioritize tests for early failure feedback

**Identified mechanism:** test_prioritization. **Citation:** S02; V.A.1; V.B; VI.C; PDF pp. 6, 8, 9.

**Literature finding:** Ordering advances failure feedback without inherently saving compute. Evidence label: reported_benefit.

**Catalog application method (analyst synthesis):** Rank tests using history or diversity; Retain every required test.

**Conditions:** Tests tolerate reordering. **Risks/contraindications:** Order-dependent tests; Required tests would be stopped.

**What our script evaluates:** The main runner executes baselines and requests a proposal, but the current scope validator lacks support for test ordering. Changed candidates are rejected with SELECTED_PATTERN_NEEDS_A_DEDICATED_CHANGE_VALIDATOR; several also alter protected commands, jobs, or triggers. None reaches an optimized measured arm.


| Source repository | B/O successful runs | Median elapsed seconds B → O | Reduction | Median summed job seconds B → O | Satisfied | Saved outcome | Evidence |
| --- | --- | --- | ---: | --- | --- | --- | --- |
| data-liberation-front/csvlint.rb | 0/1; 0/0 | — → — | — | — → — | no | inconclusive | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-298e7494437e2e30/case.json>) |
| davishmcclurg/json_schemer | 0/1; 0/0 | — → — | — | — → — | no | inconclusive | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-aee12a41bc653b75/case.json>) |
| ddeboer/imap | 3/3; 0/0 | 143 → — | — | 282 → — | no | unsafe | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-a275ed0ed446f1a8/case.json>) |
| debian/dh-make-golang | 3/3; 0/0 | 162 → — | — | 431 → — | no | unsafe | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-3097542a31c664c9/case.json>) |
| deligoez/laravel-model-hashid | 0/1; 0/0 | — → — | — | — → — | no | inconclusive | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-a93afa9b80197f47/case.json>) |
| dermesser/leveldb-rs | 0/1; 0/0 | — → — | — | — → — | no | inconclusive | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-bc98ade2ba87f03d/case.json>) |
| dftbplus/dftbplus | 1/2; 0/0 | 976 → — | — | 2109 → — | no | inconclusive | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-1bc0b4c27a77d928/case.json>) |
| dgibson/dtc | 0/1; 0/0 | — → — | — | — → — | no | inconclusive | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-490964f7a4e6ba58/case.json>) |
| digitalslidearchive/histomicstk | 3/3; 0/0 | 17 → — | — | 13 → — | no | unsafe | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-b18f3b5c26c6565c/case.json>) |
| dioxuslabs/taffy | 3/3; 0/0 | 131 → — | — | 1159 → — | no | unsafe | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-4e14036a740fff17/case.json>) |
| djberg96/sys-filesystem | 1/2; 0/0 | 169 → — | — | 1054 → — | no | inconclusive | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-f9a90c787161c71b/case.json>) |
| dmitriiweb/extract-emails | 3/3; 0/0 | 59 → — | — | 222 → — | no | unsafe | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-ad1bd4be58e8402b/case.json>) |
| domenic/worm-scraper | 3/3; 0/0 | 150 → — | — | 276 → — | no | unsafe | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-3c80ff648b17c73e/case.json>) |
| doronz88/pymobiledevice3 | 3/3; 0/0 | 10 → — | — | 5 → — | no | unsafe | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-63c87a4afac2f8e3/case.json>) |

- **data-liberation-front/csvlint.rb:** Baseline measured attempt 1 failed (run 40737899274, conclusion=failure, reason=REQUIRED_CHECK_MISSING_OR_NOT_SUCCESSFUL;CI_failure); stopping this repository after the first failed attempt Model: No saved successful LLM response. [run records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-298e7494437e2e30/run_records.json>).
- **davishmcclurg/json_schemer:** Baseline measured attempt 1 failed (run 40738805634, conclusion=cancelled, reason=REQUIRED_CHECK_MISSING_OR_NOT_SUCCESSFUL;CI_cancelled); stopping this repository after the first failed attempt Model: No saved successful LLM response. [run records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-aee12a41bc653b75/run_records.json>).
- **ddeboer/imap:** TOP_LEVEL_CHANGED:on; RUN_COMMAND_OR_CONTEXT_CHANGED:tests; SELECTED_PATTERN_NEEDS_A_DEDICATED_CHANGE_VALIDATOR Model: google/gemma-4-26b-a4b-it:free. [run records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-a275ed0ed446f1a8/run_records.json>); [diff](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-a275ed0ed446f1a8/change.diff>).
- **debian/dh-make-golang:** RUN_COMMAND_OR_CONTEXT_CHANGED:ci-test; SELECTED_PATTERN_NEEDS_A_DEDICATED_CHANGE_VALIDATOR Model: google/gemma-4-26b-a4b-it:free. [run records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-3097542a31c664c9/run_records.json>); [diff](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-3097542a31c664c9/change.diff>).
- **deligoez/laravel-model-hashid:** Baseline measured attempt 1 failed (run 40744129188, conclusion=failure, reason=REQUIRED_CHECK_MISSING_OR_NOT_SUCCESSFUL;CI_failure); stopping this repository after the first failed attempt Model: No saved successful LLM response. [run records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-a93afa9b80197f47/run_records.json>).
- **dermesser/leveldb-rs:** Baseline measured attempt 1 failed (run 40744372229, conclusion=cancelled, reason=REQUIRED_CHECK_MISSING_OR_NOT_SUCCESSFUL;CI_cancelled); stopping this repository after the first failed attempt Model: No saved successful LLM response. [run records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-bc98ade2ba87f03d/run_records.json>).
- **dftbplus/dftbplus:** Baseline measured attempt 2 failed (run 40748080934, conclusion=cancelled, reason=REQUIRED_CHECK_MISSING_OR_NOT_SUCCESSFUL;CI_cancelled); stopping this repository after the first failed attempt Model: No saved successful LLM response. [run records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-1bc0b4c27a77d928/run_records.json>).
- **dgibson/dtc:** Baseline measured attempt 1 failed (run 40748434130, conclusion=cancelled, reason=REQUIRED_CHECK_MISSING_OR_NOT_SUCCESSFUL;CI_cancelled); stopping this repository after the first failed attempt Model: No saved successful LLM response. [run records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-490964f7a4e6ba58/run_records.json>).
- **digitalslidearchive/histomicstk:** SELECTED_PATTERN_NEEDS_A_DEDICATED_CHANGE_VALIDATOR Model: google/gemma-4-26b-a4b-it:free. [run records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-b18f3b5c26c6565c/run_records.json>); [diff](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-b18f3b5c26c6565c/change.diff>).
- **dioxuslabs/taffy:** JOB_SET_CHANGED; SELECTED_PATTERN_NEEDS_A_DEDICATED_CHANGE_VALIDATOR Model: google/gemma-4-26b-a4b-it:free. [run records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-4e14036a740fff17/run_records.json>); [diff](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-4e14036a740fff17/change.diff>).
- **djberg96/sys-filesystem:** Baseline measured attempt 2 failed (run 40753632368, conclusion=cancelled, reason=REQUIRED_CHECK_MISSING_OR_NOT_SUCCESSFUL;CI_cancelled); stopping this repository after the first failed attempt Model: No saved successful LLM response. [run records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-f9a90c787161c71b/run_records.json>).
- **dmitriiweb/extract-emails:** RUN_COMMAND_OR_CONTEXT_CHANGED:fast; SELECTED_PATTERN_NEEDS_A_DEDICATED_CHANGE_VALIDATOR Model: google/gemma-4-26b-a4b-it:free. [run records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-ad1bd4be58e8402b/run_records.json>); [diff](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-ad1bd4be58e8402b/change.diff>).
- **domenic/worm-scraper:** RUN_COMMAND_OR_CONTEXT_CHANGED:test; SELECTED_PATTERN_NEEDS_A_DEDICATED_CHANGE_VALIDATOR Model: google/gemma-4-26b-a4b-it:free. [run records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-3c80ff648b17c73e/run_records.json>); [diff](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-3c80ff648b17c73e/change.diff>).
- **doronz88/pymobiledevice3:** SELECTED_PATTERN_NEEDS_A_DEDICATED_CHANGE_VALIDATOR Model: google/gemma-4-26b-a4b-it:free. [run records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-63c87a4afac2f8e3/run_records.json>); [diff](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/experiments/batch-ishara-pattern-bat-63c87a4afac2f8e3/change.diff>).

**Recorded batch coverage:** completed: 6; failed: 13; pattern_satisfied: 16; pending_run: 1; preparation_failed: 4. Counts combine all five batch CSVs, including retries and quota skips.

**Interpretation:** Fourteen saved reports lack optimized timing: seven unsafe proposal rejections and seven inconclusive baseline failure/cancellation cases. Six additional candidate rows failed preparation. No test-ordering speedup or earlier failure-feedback benefit was measured.

### 12. P-LIT-BUILD-PRIORITY — Prioritize queued builds

**Identified mechanism:** build_prioritization. **Citation:** S02; V.A.2; V.B; VI.C; PDF pp. 6, 8, 9.

**Literature finding:** Build ordering had limited benefit without contention. Evidence label: mixed_results.

**Catalog application method (analyst synthesis):** Measure contention first; Retain fairness.

**Conditions:** Runs compete for constrained workers. **Risks/contraindications:** No queue; Priority starvation.

**What our script evaluates:** A deterministic queue replay changes FIFO to priority_with_aging with max_wait 12. Contended and uncontended queues verify no dropped builds, valid serial starts, urgent-build priority, and aging. It simulates a queue; it does not control GitHub hosted-runner scheduling.


| Source-repository label | B/O passing suites | Median scenario job seconds B → O | Reduction | Satisfied | Saved outcome | Evidence |
| --- | --- | --- | ---: | --- | --- | --- |
| dotnet/csharpstandard | 3/3; 3/3 | 3 → 3 | 0.00% | no | scenario_passed | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-540e03c9c96d24df/case.json>) |
| drmarkusvoss/pumla | 3/3; 3/3 | 3 → 4 | -33.33% | no | scenario_passed | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-78b169154be9efc0/case.json>) |
| dry-python/returns | 3/3; 3/3 | 3 → 3 | 0.00% | no | scenario_passed | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-58f1c726cd423cb4/case.json>) |
| dswah/pygam | 3/3; 3/3 | 3 → 4 | -33.33% | no | scenario_passed | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-73814b1d70c4160f/case.json>) |
| easybuilders/easybuild-easyblocks | 3/3; 3/3 | 4 → 3 | 25.00% | yes | scenario_passed | [case](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-47e298b0849ea347/case.json>) |

- **dotnet/csharpstandard:** median simulated work 43 → 43 seconds. [baseline repeat-2 trace](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-540e03c9c96d24df/replays/baseline-2.json>); [optimized repeat-2 trace](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-540e03c9c96d24df/replays/optimized-2.json>); [all repeat records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-540e03c9c96d24df/run_records.json>).
- **drmarkusvoss/pumla:** median simulated work 43 → 43 seconds. [baseline repeat-2 trace](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-78b169154be9efc0/replays/baseline-2.json>); [optimized repeat-2 trace](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-78b169154be9efc0/replays/optimized-2.json>); [all repeat records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-78b169154be9efc0/run_records.json>).
- **dry-python/returns:** median simulated work 43 → 43 seconds. [baseline repeat-2 trace](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-58f1c726cd423cb4/replays/baseline-2.json>); [optimized repeat-2 trace](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-58f1c726cd423cb4/replays/optimized-2.json>); [all repeat records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-58f1c726cd423cb4/run_records.json>).
- **dswah/pygam:** median simulated work 43 → 43 seconds. [baseline repeat-2 trace](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-73814b1d70c4160f/replays/baseline-2.json>); [optimized repeat-2 trace](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-73814b1d70c4160f/replays/optimized-2.json>); [all repeat records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-73814b1d70c4160f/run_records.json>).
- **easybuilders/easybuild-easyblocks:** median simulated work 43 → 43 seconds. [baseline repeat-2 trace](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-47e298b0849ea347/replays/baseline-2.json>); [optimized repeat-2 trace](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-47e298b0849ea347/replays/optimized-2.json>); [all repeat records](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/scenario-experiments/batch-scenario-three-run-47e298b0849ea347/run_records.json>).

**Recorded batch coverage:** blocked: 20; completed: 5; preparation_failed: 15. Counts combine all five batch CSVs, including retries and quota skips.

**Interpretation:** Five fixtures pass queue assertions: one hosted runtime is faster, two equal, two slower. Simulated work stays 43 seconds. The urgent build waits 18 versus 6 simulated seconds under contention; maximum wait remains 22 seconds. This demonstrates urgent-feedback improvement, not less total compute.

### 13. P-LIT-SELECT — Select tests using change dependencies

**Identified mechanism:** test_selection. **Citation:** S02; IV.A.1; IV.C; VI.B; PDF pp. 4, 5, 9.

**Literature finding:** Selection savings can hide failing tests. Evidence label: mixed_results.

**Catalog application method (analyst synthesis):** Compare full and selected results; Retain configuration-failure detection.

**Conditions:** Reliable dependency data; Separately approved selection treatment. **Risks/contraindications:** Strict contract requires the full test set.

**What our script evaluates:** The main runner can select this pattern, but its mechanism lacks a dedicated supported change validator. Changed proposals are rejected with SELECTED_PATTERN_NEEDS_A_DEDICATED_CHANGE_VALIDATOR, potentially alongside protected-structure errors. No optimized comparison exists. This is an implementation/evidence gap rather than an effectiveness result.


**Recorded batch coverage:** cleanup_pending: 2; completed: 9; failed: 7; preparation_failed: 14. Counts combine all five batch CSVs, including retries and quota skips.

**Saved results:** No retained case report or paired optimized measurement.

**Interpretation:** No local effectiveness result is available. This pattern remains a literature-derived candidate direction requiring execution and mechanism-specific validation.

### 14. P-LIT-BUILD-SELECT — Select builds using change or outcome predictions

**Identified mechanism:** build_selection. **Citation:** S02; IV.A.2; IV.B.2; VI.B; PDF pp. 4, 5, 9.

**Literature finding:** Apparently safe changes can still fail. Evidence label: mixed_results.

**Catalog application method (analyst synthesis):** Measure missed failures and savings together; Hide future and skipped outcomes during replay.

**Conditions:** Selection is a separately approved experiment. **Risks/contraindications:** Required checks must run on each revision.

**What our script evaluates:** The implemented replay would skip documentation builds after an observed success while always building source, lockfile, and setup changes. Decisions see only past observed outcomes; an evaluator-only oracle counts hidden skipped failures. A deliberately missed setup failure is expected and accounted for. No retained case report exists, so this is an implemented test design rather than an executed result.


**Recorded batch coverage:** blocked: 20; preparation_failed: 20. Counts combine all five batch CSVs, including retries and quota skips.

**Saved results:** No retained case report or paired optimized measurement.

**Interpretation:** All 20 attempted scenario rows failed preparation. No measured results or retained replay traces exist; the code's expected missed-failure scenario must not be reported as an executed experiment.

### 15. P-LIT-BAZEL-PARALLEL — Tune Bazel build parallelism

**Identified mechanism:** build_parallelism. **Citation:** S03; 3.2.2; 4.2; 6.3; PDF pp. 18, 19, 31, 32, 33, 43.

**Literature finding:** Long compilations benefited most from parallelism. Evidence label: reported_benefit.

**Catalog application method (analyst synthesis):** Compare concurrency within resource quotas; Keep targets and inputs identical.

**Conditions:** Existing Bazel build; Sufficient CPU and memory. **Risks/contraindications:** Larger flags are assumed to supply more runner resources.

**What our script evaluates:** The main runner can select this pattern, but its mechanism lacks a dedicated supported change validator. Changed proposals are rejected with SELECTED_PATTERN_NEEDS_A_DEDICATED_CHANGE_VALIDATOR, potentially alongside protected-structure errors. No optimized comparison exists. This is an implementation/evidence gap rather than an effectiveness result.


**Recorded batch coverage:** cleanup_pending: 4; completed: 6; failed: 4; llm_paused: 1; pending_run: 1; preparation_failed: 21; running: 3. Counts combine all five batch CSVs, including retries and quota skips.

**Saved results:** No retained case report or paired optimized measurement.

**Interpretation:** No local effectiveness result is available. This pattern remains a literature-derived candidate direction requiring execution and mechanism-specific validation.


### 16. P-LIT-BAZEL-INCREMENTAL — Cache Bazel build results

**Identified mechanism:** incremental_build_cache. **Citation:** S03; 3.2.3; 4.3; Table 10; PDF pp. 24, 25, 36, 37, 38.

**Literature finding:** Result caching particularly helped long compilations. Evidence label: reported_benefit.

**Catalog application method (analyst synthesis):** Separate dependency and result caching; Record cold behavior and hit rates.

**Conditions:** Existing Bazel build; Trusted, input-keyed cache. **Risks/contraindications:** Mutable undeclared inputs; Untrusted cache writes.

**What our script evaluates:** This selectable mechanism routes through the shared cache validator, which permits bounded cache syntax while preserving the workload. No saved case exists. A cache-shaped patch alone would not establish full Bazel result caching, environment validity, distributed caching, or cross-configuration compatibility; these mechanism-specific claims still need evidence.



**Recorded batch coverage:** completed: 2; preparation_failed: 35; running: 3. Counts combine all five batch CSVs, including retries and quota skips.

**Saved results:** No retained case report or paired optimized measurement.

**Interpretation:** No local effectiveness result is available. This pattern remains a literature-derived candidate direction requiring execution and mechanism-specific validation.

### 17. P-LIT-BAZEL-DEPS — Evaluate dependency cache overhead

**Identified mechanism:** dependency_cache_overhead. **Citation:** S03; 3.2.3; 4.3; PDF pp. 24, 25, 36, 37, 38.

**Literature finding:** Dependency-only caching offered no clear speedup. Evidence label: mixed_results.

**Catalog application method (analyst synthesis):** Compare total restore/upload cost; Evaluate result caching separately.

**Conditions:** Transfer and installation time can be separated. **Risks/contraindications:** Cache benefit is assumed without measurement.

**What our script evaluates:** This selectable mechanism routes through the shared cache validator, which permits bounded cache syntax while preserving the workload. No saved case exists. A cache-shaped patch alone would not establish full Bazel result caching, environment validity, distributed caching, or cross-configuration compatibility; these mechanism-specific claims still need evidence.


**Recorded batch coverage:** completed: 8; preparation_failed: 31. Counts combine all five batch CSVs, including retries and quota skips.

**Saved results:** No retained case report or paired optimized measurement.

**Interpretation:** No local effectiveness result is available. This pattern remains a literature-derived candidate direction requiring execution and mechanism-specific validation.

### 18. P-LIT-ENV-CACHE — Reuse validated build environments

**Identified mechanism:** environment_cache. **Citation:** S04; 4.1; 6.3; 7.2; 10; PDF pp. 4, 8, 10, 11.

**Literature finding:** Reuse needs pinned dependencies and resettable state. Evidence label: reported_benefit.

**Catalog application method (analyst synthesis):** Reuse a trusted successful snapshot; Invalidate changed environment inputs; Always execute necessary state resets.

**Conditions:** Dependencies pinned including transitives; Tests reset files and services. **Risks/contraindications:** Mutable dependency resolution; Persistent test contamination.

**What our script evaluates:** This selectable mechanism routes through the shared cache validator, which permits bounded cache syntax while preserving the workload. No saved case exists. A cache-shaped patch alone would not establish full Bazel result caching, environment validity, distributed caching, or cross-configuration compatibility; these mechanism-specific claims still need evidence.


**Recorded batch coverage:** completed: 11; failed: 1; preparation_failed: 27; running: 1. Counts combine all five batch CSVs, including retries and quota skips.

**Saved results:** No retained case report or paired optimized measurement.

**Interpretation:** No local effectiveness result is available. This pattern remains a literature-derived candidate direction requiring execution and mechanism-specific validation.

### 19. P-LIT-UNAFFECTED-STEPS — Skip steps using traced dependencies

**Identified mechanism:** dependency_aware_step_selection. **Citation:** S04; 4.2; 6.3; 7.2; 10; PDF pp. 5, 6, 8, 10, 11.

**Literature finding:** Coarse test processes limited skipping gains. Evidence label: mixed_results.

**Catalog application method (analyst synthesis):** Update traced dependencies after runs; Fall back after added/renamed files; Do not attribute combined gains solely to skipping.

**Conditions:** Tracing and cold fallback exist. **Risks/contraindications:** Incomplete dynamic paths; Full check execution is required.

**What our script evaluates:** The main runner can select this pattern, but its mechanism lacks a dedicated supported change validator. Changed proposals are rejected with SELECTED_PATTERN_NEEDS_A_DEDICATED_CHANGE_VALIDATOR, potentially alongside protected-structure errors. No optimized comparison exists. This is an implementation/evidence gap rather than an effectiveness result.


**Recorded batch coverage:** completed: 8; failed: 9; preparation_failed: 25; running: 3. Counts combine all five batch CSVs, including retries and quota skips.

**Saved results:** No retained case report or paired optimized measurement.

**Interpretation:** No local effectiveness result is available. This pattern remains a literature-derived candidate direction requiring execution and mechanism-specific validation.

### 20. P-LIT-SMELL-REPAIR — Repair evidenced configuration smells

**Identified mechanism:** performance_smell_repair. **Citation:** S05; 4.3.3; Table 2, BuildSonic; PDF pp. 14, 16.

**Literature finding:** BuildSonic reports acceleration through configuration repair. Evidence label: secondary_report_only.

**Catalog application method (analyst synthesis):** Identify the exact issue; Verify the primary method before adapting.

**Conditions:** Concrete primary-source repair is verified. **Risks/contraindications:** A smell name alone justifies removal.

**What our script evaluates:** The main runner can select this pattern, but its mechanism lacks a dedicated supported change validator. Changed proposals are rejected with SELECTED_PATTERN_NEEDS_A_DEDICATED_CHANGE_VALIDATOR, potentially alongside protected-structure errors. No optimized comparison exists. This is an implementation/evidence gap rather than an effectiveness result.


**Recorded batch coverage:** completed: 2; failed: 21; preparation_failed: 37. Counts combine all five batch CSVs, including retries and quota skips.

**Saved results:** No retained case report or paired optimized measurement.

**Interpretation:** No local effectiveness result is available. This pattern remains a literature-derived candidate direction requiring execution and mechanism-specific validation.

### 21. P-LIT-DURATION-PREDICTION — Predict duration to guide investigation

**Identified mechanism:** build_duration_prediction. **Citation:** S05; 4.3.3; Table 2; PDF pp. 14, 18.

**Literature finding:** Prediction supports analysis rather than direct acceleration. Evidence label: no_direct_speedup_evidence.

**Catalog application method (analyst synthesis):** Identify candidates or estimate budgets; Measure actual workflow changes separately.

**Conditions:** Timing data and chronological validation. **Risks/contraindications:** Predictions are claimed as speedups.

**What our script evaluates:** The implemented replay would compare a past-global-mean predictor with a past-feature-mean predictor using chronological observations, six initial training observations, and held-out mean absolute error. Assertions forbid future-data leakage, retain all builds, and prohibit claiming prediction as a direct speedup. No retained case report exists.


**Recorded batch coverage:** blocked: 40; preparation_failed: 20. Counts combine all five batch CSVs, including retries and quota skips.

**Saved results:** No retained case report or paired optimized measurement.

**Interpretation:** All 20 attempted scenario rows failed preparation. No measured prediction error or timing comparison exists; the chronological predictor evaluation is implemented but lacks retained execution evidence.

### 22. P-LIT-UNUSED-OUTPUTS — Remove genuinely unused outputs

**Identified mechanism:** unused_output_elimination. **Citation:** S05; 4.3.3; Table 2, OptCD; PDF pp. 14, 16.

**Literature finding:** OptCD removes work producing unused content. Evidence label: secondary_report_only.

**Catalog application method (analyst synthesis):** Trace consumers; Retain required deliverables.

**Conditions:** All output consumers are identified. **Risks/contraindications:** A downstream check or artifact needs the output.

**What our script evaluates:** The main runner can select this pattern, but its mechanism lacks a dedicated supported change validator. Changed proposals are rejected with SELECTED_PATTERN_NEEDS_A_DEDICATED_CHANGE_VALIDATOR, potentially alongside protected-structure errors. No optimized comparison exists. This is an implementation/evidence gap rather than an effectiveness result.


**Recorded batch coverage:** completed: 5; failed: 15; preparation_failed: 40. Counts combine all five batch CSVs, including retries and quota skips.

**Saved results:** No retained case report or paired optimized measurement.

**Interpretation:** No local effectiveness result is available. This pattern remains a literature-derived candidate direction requiring execution and mechanism-specific validation.

### 23. P-LIT-DISTRIBUTED-CACHE — Share cached build dependencies

**Identified mechanism:** distributed_dependency_cache. **Citation:** S05; 4.3.3; Table 2, CloudBuild; PDF pp. 14, 16.

**Literature finding:** Distributed caching reuses earlier dependencies. Evidence label: secondary_report_only.

**Catalog application method (analyst synthesis):** Evaluate transfer overhead and trust; Keep inputs pinned.

**Conditions:** Trusted cache infrastructure. **Risks/contraindications:** Infrastructure changes exceed treatment scope.

**What our script evaluates:** This selectable mechanism routes through the shared cache validator, which permits bounded cache syntax while preserving the workload. No saved case exists. A cache-shaped patch alone would not establish full Bazel result caching, environment validity, distributed caching, or cross-configuration compatibility; these mechanism-specific claims still need evidence.


**Recorded batch coverage:** completed: 5; failed: 2; preparation_failed: 33. Counts combine all five batch CSVs, including retries and quota skips.

**Saved results:** No retained case report or paired optimized measurement.

**Interpretation:** No local effectiveness result is available. This pattern remains a literature-derived candidate direction requiring execution and mechanism-specific validation.

### 24. P-LIT-CONFIG-REUSE — Reuse work across compatible configurations

**Identified mechanism:** configuration_incremental_build. **Citation:** S05; 4.3.3; Table 2, Randrianaina et al.; PDF pp. 14, 16, 17.

**Literature finding:** Configuration ordering enables common-work reuse. Evidence label: secondary_report_only.

**Catalog application method (analyst synthesis):** Retain every configuration; Reuse only input-compatible work.

**Conditions:** Primary method establishes configuration compatibility. **Risks/contraindications:** Target settings make artifacts incompatible.

**What our script evaluates:** This selectable mechanism routes through the shared cache validator, which permits bounded cache syntax while preserving the workload. No saved case exists. A cache-shaped patch alone would not establish full Bazel result caching, environment validity, distributed caching, or cross-configuration compatibility; these mechanism-specific claims still need evidence.


**Recorded batch coverage:** completed: 2; failed: 3; preparation_failed: 35. Counts combine all five batch CSVs, including retries and quota skips.

**Saved results:** No retained case report or paired optimized measurement.

**Interpretation:** No local effectiveness result is available. This pattern remains a literature-derived candidate direction requiring execution and mechanism-specific validation.

### 25. P-LIT-UNUSED-DEP-SKIP — Evaluate skipping unused-dependency updates

**Identified mechanism:** unused_dependency_build_selection. **Citation:** S05; 4.3.3; Table 2, Dep-sCImitar; PDF pp. 14, 16.

**Literature finding:** Unused dependency updates offer selection opportunities. Evidence label: secondary_report_only.

**Catalog application method (analyst synthesis):** Evaluate under a separate selection policy; Compare with complete builds.

**Conditions:** Primary dependency-use and history conditions hold. **Risks/contraindications:** Transitive or lockfile changes affect required checks.

**What our script evaluates:** The main runner can select this pattern, but its mechanism lacks a dedicated supported change validator. Changed proposals are rejected with SELECTED_PATTERN_NEEDS_A_DEDICATED_CHANGE_VALIDATOR, potentially alongside protected-structure errors. No optimized comparison exists. This is an implementation/evidence gap rather than an effectiveness result.


**Recorded batch coverage:** completed: 4; failed: 6; llm_paused: 3; pending_run: 2; preparation_failed: 45. Counts combine all five batch CSVs, including retries and quota skips.

**Saved results:** No retained case report or paired optimized measurement.

**Interpretation:** No local effectiveness result is available. This pattern remains a literature-derived candidate direction requiring execution and mechanism-specific validation.

## 4. Batch coverage, incomplete evidence, and models

| Batch | Rows | Recorded statuses |
| --- | ---: | --- |
| [hiruni-pattern-batch-v1](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/batches/hiruni-pattern-batch-v1/batch_results.csv>) | 125 | blocked: 20; failed: 13; preparation_failed: 92 |
| [hiruni-pattern-batch-v2](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/batches/hiruni-pattern-batch-v2/batch_results.csv>) | 125 | blocked: 20; completed: 8; failed: 40; llm_paused: 3; pending_run: 2; preparation_failed: 52 |
| [interactive-three-runs-v1](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/batches/interactive-three-runs-v1/batch_results.csv>) | 241 | blocked: 105; cleanup_pending: 7; completed: 9; failed: 6; llm_paused: 1; pattern_satisfied: 29; pending_run: 1; preparation_failed: 72; running: 11 |
| [ishara-pattern-batch-v2](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/batches/ishara-pattern-batch-v2/batch_results.csv>) | 125 | blocked: 75; completed: 6; failed: 26; pattern_satisfied: 3; pending_run: 1; preparation_failed: 14 |
| [scenario-three-runs-v1](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/research-data/batches/scenario-three-runs-v1/batch_results.csv>) | 400 | completed: 78; failed: 2; pattern_satisfied: 139; preparation_failed: 180; running: 1 |

Across the five batch CSVs, **1016 rows are recorded**: blocked: 220; cleanup_pending: 7; completed: 101; failed: 87; llm_paused: 4; pattern_satisfied: 171; pending_run: 4; preparation_failed: 410; running: 12. These are batch statuses, not experiment counts. The current case inventory contains 128 main reports and 81 scenario reports; retries, skips, failed rows, and case reports do not map one-to-one.

Preparation-failure rows often retain only a generic failure summary, so a specific cause cannot be inferred unless the saved terminal/API log records it. Preparation failure is not evidence that an optimization was ineffective.

The main case model fields record 66 `google/gemma-4-26b-a4b-it:free`, 7 `nvidia/nemotron-3-ultra-550b-a55b:free`, 55 with no model recorded. All 81 scenario case fields record `nvidia/nemotron-3-ultra-550b-a55b:free`. All 73 retained main `proposal.json` files state that actionlint was not installed. Use each case's model, prompt, and usage fields when comparing outcomes; sharing a batch ID does not make it a single-model experiment.

## 5. What is stored for RAG and what remains to be admitted

The builder is [build_rag_dataset.py](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/scripts/build_rag_dataset.py>). It creates a literature-pattern document for each registry pattern and an experiment-example document for each retained recognized case, linking examples back to their pattern. Its output includes available before/after content, diffs, run records, replay policies/traces, model/outcome/metrics, and artifact hashes. Default outputs are research-data/rag/rag_dataset.jsonl, rag_dataset.json, and rag_dataset_manifest.json.

No generated research-data/rag corpus files are present in this snapshot. The current builder would include 25 pattern documents plus 209 experiment-example documents (128 main and 81 scenario). With the saved draft/admission flags, zero records are automatically retrieval-eligible. Patterns require review, main cases are pending_review, and scenarios require applicability review. Building a JSON corpus does not approve its documents, embed them in an index, or train an LLM.

| Information to retain | Existing evidence/artifact | Why it matters |
| --- | --- | --- |
| Pattern and source provenance | knowledge/extracted_patterns.jsonl; knowledge/papers.jsonl; source/pattern.json | Trace a method to a paper/locator and distinguish analyst guidance from published findings. |
| Repository snapshot and preparation | source metadata, commit/tree, selection.json, config.json, workflow_path | Identify the exact current version and any dispatch-harness preparation used before the baseline. |
| Before, after, and patch | before.yml, after.yml, change.diff, proposal and SHA-256 fields | Reproduce the proposed treatment and audit which checks/commands/configurations changed. |
| Each run and outcome | run_records.json, experiment_runs.csv, raw run/job/artifact metadata | Retain individual pass/failure/cancellation results and complete/protocol-valid measurement flags. |
| Arm comparisons | case.json and REPORT.md | Keep medians, metric definitions, reductions, repetition counts, satisfaction, and overall outcome together. |
| LLM provenance | llm_request.json, llm_response.json, model/usage/latency metadata | Separate different model configurations and inspect what evidence generated the candidate. |
| Review and admission | review, rag_admission, required-check source, scope findings | Filter retrieval by explicit evidence/safety approval instead of a positive timing alone. |
| Scenario controls and scope | scenario inputs/policy, assertions, replay traces, hosted run ID, real_repo_optimization_verified=false | Preserve synthetic behavior evidence without presenting it as original-repository effectiveness. |

The builder can retain inconclusive/negative examples with their labels and evidence scope. They should not become positive optimization recommendations. A useful approved example keeps its development split, source/patch identity, complete per-run results, reviewer, admission status, and method-specific validity evidence.

The present scripts use the selected registry pattern directly. These reports do not establish an LLM-plus-retrieval improvement over the same LLM without retrieval. The broader original/ci-cost/LLM-only/LLM+RAG comparison in the research plan requires its own matching experiment records.

## 6. Limits to reflect in the research paper

- Three observations per arm give pilot medians without significance estimates. Baseline/optimized blocks, runner/network variation, and uncontrolled caches limit causal claims.
- Stopping after two faster candidates produces success-selection bias. Report attempts, rejections, and failures alongside retained positive examples rather than presenting their average as an unbiased effect.
- Ordinary successful timeout trials do not measure hang termination or false timeouts. A lower healthy-run duration does not prove that the timeout setting caused it.
- Seven main mechanisms lack dedicated supported change validation. Validator rejection is an implementation limit, not a measured failure of the research technique.
- Source-repository labels on scenarios identify fixture hosts. Repeating the same fixture under multiple repository labels does not demonstrate effectiveness across their original workloads.
- Queue/job-ordering replay can improve feedback while leaving total simulated work unchanged. Use trace feedback metrics for that claim, not the hosted Python process runtime.
- Automatic scope/structure checks and observed baseline job names do not prove semantic equivalence, branch-protection safety, or applicability of secondary-literature methods. Independent review is still pending.
- This snapshot includes retained evidence only. Deleted/missing cases and prior dataset/model versions are not reconstructed from result labels.

## 7. Evidence sources and reproducibility

The counts and tables were derived from the two registries, all 5 available batch CSV files, and all 209 retained `case.json` files. Detailed interpretations also use saved run records, proposal errors/diffs, and replay traces. The derived `analysis/per_repo_results.csv` was not used as authority because summaries can become stale.

Script behavior was read from [run_pattern_batch.py](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/scripts/run_pattern_batch.py>), [run_ci_experiment.py](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/scripts/run_ci_experiment.py>), [openrouter_optimizer.py](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/scripts/openrouter_optimizer.py>), [run_scenario_batch.py](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/scripts/run_scenario_batch.py>), [scenario_experiments.py](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/scripts/scenario_experiments.py>), [scenario_replay.py](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/scripts/scenario_replay.py>), [build_rag_dataset.py](<C:/Users/LOQ/Downloads/Uni/Research/Repositories/CloudTune-RAG-LLM-CI-Optimization/scripts/build_rag_dataset.py>). This document records the implementation and results; no new GitHub runs, LLM requests, or corpus build were executed to create it.

Snapshot SHA-256 over sorted relative paths and bytes (NUL-delimited; two registries, 5 batch CSV files, 209 case JSON files): 4b1435f0a3ecdbb653868970d8e01f3cce6e85b994519370912630f19ef750f6.
