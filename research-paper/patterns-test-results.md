# CI optimization patterns: simple test and result guide

Snapshot: 30 October 2026. Covers all 25 registry patterns and all 181 retained case reports: 100 main and 81 scenario.

**Reading the results:** Main tests use repository workflows; scenario tests use controlled fixtures or synthetic replays. Each complete comparison requires three successful baseline and three successful optimized measurements; attempts can stop early. Faster/unchanged/slower compares median workflow elapsed time for main tests and median summed job runtime for scenario tests. Replay timing is the hosted fixture runtime; simulated work and feedback are separate metrics. Scenario results do not establish speedups in the original repositories.

**Review status:** Main results remain unsafe or inconclusive; independent safety review is pending. A scenario pass means its behavior assertions passed. Patterns with no retained cases list planned steps only. Case counts include repeated attempts, so they are not counts of distinct repositories.

## 1. Cache dependency downloads (`P-LIT-GHA-CACHE`)

**What:** Reuse downloaded dependencies between CI runs.

**Test steps:** 1. Run the repository workflow baseline. 2. Ask the LLM to add dependency caching and validate the YAML. 3. Repeat the workflow and compare timings; dedicated cold/warm-cache controls were not run.

**Results:** Main: 4 cases (4 inconclusive); 2 faster, 0 unchanged, 2 slower, 0 without complete paired timing.

## 2. Cancel remaining matrix jobs after failure (`P-LIT-FAIL-FAST`)

**What:** Cancel remaining matrix jobs when one job fails.

**Test steps:** 1. Run a three-job matrix with cancellation disabled. 2. Enable fail-fast and repeat a deliberate failure. 3. Check cancellation and a healthy matrix control.

**Results:** Scenario: 2 cases (2 passed); 2 faster, 0 unchanged, 0 slower, 0 without complete paired timing.

## 3. Cancel superseded runs (`P-LIT-CANCEL-STALE`)

**What:** Cancel an older run when a newer commit replaces it.

**Test steps:** 1. Push overlapping commits plus a separate-branch control. 2. Enable concurrency cancellation by workflow and branch. 3. Check old-run cancellation, latest-run completion, and branch isolation.

**Results:** Scenario: 3 cases (3 passed); 2 faster, 1 unchanged, 0 slower, 0 without complete paired timing.

## 4. Skip explicitly dispensable workflow runs (`P-LIT-SKIP-WORKFLOW`)

**What:** Skip a workflow run when a change is explicitly dispensable.

**Test steps:** 1. Run documentation and source-change controls. 2. Add the allowed [skip ci] commit suffix to the documentation event. 3. Check suppression and passing source controls before and after it.

**Results:** Scenario: 2 cases (2 passed); 2 faster, 0 unchanged, 0 slower, 0 without complete paired timing.

## 5. Filter workflow triggers by changed paths (`P-LIT-CHANGE-FILTER`)

**What:** Run CI only when relevant file paths change.

**Test steps:** 1. Trigger documentation, source, configuration, and mixed changes. 2. Add path filters. 3. Check documentation suppression while relevant changes still run.

**Results:** Scenario: 2 cases (2 passed); 2 faster, 0 unchanged, 0 slower, 0 without complete paired timing.

## 6. Bound jobs with a custom timeout (`P-LIT-CUSTOM-TIMEOUT`)

**What:** Limit how long a CI job may run.

**Test steps:** 1. Measure the normal repository workflow. 2. Let the LLM change only job timeout values and validate them. 3. Repeat and compare normal-run timings; hung-job behavior was not tested.

**Results:** Main: 3 cases (3 inconclusive); 2 faster, 0 unchanged, 1 slower, 0 without complete paired timing.

## 7. Pause repeatedly failing scheduled workflows (`P-LIT-FAIL-SCHEDULE`)

**What:** Pause scheduled workflows after repeated failures.

**Test steps:** 1. Replay scheduled successes, failures, and owner resets without pausing. 2. Enable pausing after two failures and notification. 3. Check suppression, notification, reset, and recovery.

**Results:** Scenario: 2 cases (2 passed); 2 faster, 0 unchanged, 0 slower, 0 without complete paired timing.

## 8. Suppress schedules during repository inactivity (`P-LIT-IDLE-SCHEDULE`)

**What:** Skip scheduled runs when meaningful inputs have not changed.

**Test steps:** 1. Replay idle ticks, generated commits, dependency changes, and source changes. 2. Enable unchanged-input suppression. 3. Check idle suppression and resumption after meaningful changes.

**Results:** Scenario: 2 cases (2 passed); 2 faster, 0 unchanged, 0 slower, 0 without complete paired timing.

## 9. Run previously failing jobs first (`P-LIT-FAILED-JOB-FIRST`)

**What:** Run previously failing jobs and their prerequisites earlier.

**Test steps:** 1. Replay jobs in declared order. 2. Prioritize the previously failing job and its prerequisites. 3. Check dependencies, outcomes, total work, and time to first failure.

**Results:** Scenario: 4 cases (4 passed); 2 faster, 2 unchanged, 0 slower, 0 without complete paired timing.

## 10. Derive timeout candidates from successful history (`P-LIT-HISTORY-TIMEOUT`)

**What:** Use observed successful durations to propose timeout limits.

**Test steps:** 1. Collect fresh repository baseline durations. 2. Ask the LLM for timeout-only changes and validate them. 3. Repeat and compare; historical CI YAML and a deterministic history estimator were not used.

**Results:** Main: 10 cases (1 unsafe, 9 inconclusive); 2 faster, 0 unchanged, 2 slower, 6 without complete paired timing.

## 11. Prioritize tests for early failure feedback (`P-LIT-PRIORITIZE`)

**What:** Order tests so likely failures are reported earlier.

**Test steps:** Main: 1. Run repository baselines. 2. Request a test-ordering change. 3. Apply scope checks; no optimized arm was retained. Scenario: 1. Replay the original test order. 2. Move a previously failing test first. 3. Check the same tests/outcomes, total work, and failure-feedback time.

**Results:** Main: 14 cases (7 unsafe, 7 inconclusive); 0 faster, 0 unchanged, 0 slower, 14 without complete paired timing. Scenario: 4 cases (4 passed); 2 faster, 1 unchanged, 1 slower, 0 without complete paired timing.

## 12. Prioritize queued builds (`P-LIT-BUILD-PRIORITY`)

**What:** Give urgent queued builds earlier access to a worker.

**Test steps:** 1. Replay FIFO queues with and without contention. 2. Enable priority with aging. 3. Check urgent-build waiting time, no dropped builds, and valid starts.

**Results:** Scenario: 5 cases (5 passed); 1 faster, 2 unchanged, 2 slower, 0 without complete paired timing.

## 13. Select tests using change dependencies (`P-LIT-SELECT`)

**What:** Run tests affected by the changed files and dependencies.

**Test steps:** 1. Replay all tests for documentation, source, mixed, dependency, and unknown changes. 2. Select tests using the supplied dependency map. 3. Check required tests and failure detection; lockfile, setup, and unknown changes run all tests.

**Results:** Scenario: 9 cases (9 passed); 0 faster, 3 unchanged, 6 slower, 0 without complete paired timing.

## 14. Select builds using change or outcome predictions (`P-LIT-BUILD-SELECT`)

**What:** Skip selected builds using change information and observed outcomes.

**Planned test steps (not executed in retained evidence):** 1. Replay all builds. 2. Skip documentation builds after an observed success while retaining source, lockfile, and setup builds. 3. Count skipped failures with an evaluator-only oracle.

**Results:** No retained case report or measured comparison.

## 15. Tune Bazel build parallelism (`P-LIT-BAZEL-PARALLEL`)

**What:** Run independent build tasks in parallel.

**Test steps:** 1. Replay a build dependency graph with one worker. 2. Increase the worker limit to four. 3. Check dependencies and identical work, then compare simulated completion time.

**Results:** Scenario: 6 cases (6 passed); 0 faster, 5 unchanged, 1 slower, 0 without complete paired timing.

## 16. Cache Bazel build results (`P-LIT-BAZEL-INCREMENTAL`)

**What:** Reuse valid build results when inputs are unchanged.

**Planned test steps (not executed in retained evidence):** 1. Replay builds without result caching. 2. Enable caching keyed by source, dependencies, environment, and toolchain. 3. Check cold/repeated builds, invalidation, outputs, and tests.

**Results:** No retained case report or measured comparison.

## 17. Evaluate dependency cache overhead (`P-LIT-BAZEL-DEPS`)

**What:** Reuse dependency downloads while accounting for cache overhead.

**Test steps:** 1. Replay dependency fetching without caching. 2. Enable dependency caching. 3. Check cold/hit behavior, dependency/environment/toolchain changes, retained compilation/tests, and a cheap-download overhead control.

**Results:** Scenario: 8 cases (8 passed); 2 faster, 5 unchanged, 1 slower, 0 without complete paired timing.

## 18. Reuse validated build environments (`P-LIT-ENV-CACHE`)

**What:** Reuse a compatible prepared build environment.

**Test steps:** 1. Replay builds with fresh setup. 2. Enable reuse for matching dependency, environment, and toolchain keys. 3. Check reuse and invalidation while preserving compilation, outputs, and tests.

**Results:** Scenario: 13 cases (11 passed, 2 inconclusive); 2 faster, 7 unchanged, 2 slower, 2 without complete paired timing.

## 19. Skip steps using traced dependencies (`P-LIT-UNAFFECTED-STEPS`)

**What:** Skip build or test steps unaffected by a change.

**Test steps:** Main: 1. Measure baselines. 2. Request a selective-step change. 3. Validate it; no optimized arm was retained. Scenario: 1. Replay every step. 2. Select steps using the supplied dependency map. 3. Check source, transitive, lockfile, setup, and unknown-change controls.

**Results:** Main: 8 cases (2 unsafe, 6 inconclusive); 0 faster, 0 unchanged, 0 slower, 8 without complete paired timing. Scenario: 9 cases (8 passed, 1 inconclusive); 2 faster, 5 unchanged, 1 slower, 1 without complete paired timing.

## 20. Repair evidenced configuration smells (`P-LIT-SMELL-REPAIR`)

**What:** Remove evidenced configuration inefficiencies, such as redundant work.

**Test steps:** 1. Replay compile and test steps, including a redundant compile and side-effect control. 2. Remove the redundant compile where safe. 3. Check required outputs, side effects, and simulated work.

**Results:** Main: 21 cases (10 unsafe, 11 inconclusive); 0 faster, 0 unchanged, 0 slower, 21 without complete paired timing. Scenario: 2 cases (2 passed); 2 faster, 0 unchanged, 0 slower, 0 without complete paired timing.

## 21. Predict duration to guide investigation (`P-LIT-DURATION-PREDICTION`)

**What:** Predict build duration to help identify slow builds.

**Planned test steps (not executed in retained evidence):** 1. Process observations in chronological order with six initial training observations. 2. Compare past-global-mean and past-feature-mean predictors. 3. Check held-out prediction error and prevent future-data leakage.

**Results:** No retained case report or measured comparison.

## 22. Remove genuinely unused outputs (`P-LIT-UNUSED-OUTPUTS`)

**What:** Avoid producing outputs that no required consumer uses.

**Test steps:** 1. Replay builds that produce outputs with and without consumers. 2. Skip output generation only when no consumer needs it. 3. Check required outputs and simulated work.

**Results:** Main: 17 cases (13 unsafe, 4 inconclusive); 0 faster, 0 unchanged, 1 slower, 16 without complete paired timing. Scenario: 4 cases (4 passed); 2 faster, 2 unchanged, 0 slower, 0 without complete paired timing.

## 23. Share cached build dependencies (`P-LIT-DISTRIBUTED-CACHE`)

**What:** Share reusable dependency or build state across CI workers.

**Test steps:** 1. Measure the repository workflow. 2. Request a cache change and apply bounded cache validation. 3. Run accepted candidates and compare; cross-worker cache correctness was not independently established.

**Results:** Main: 7 cases (7 inconclusive); 2 faster, 0 unchanged, 3 slower, 2 without complete paired timing.

## 24. Reuse work across compatible configurations (`P-LIT-CONFIG-REUSE`)

**What:** Reuse work across compatible build configurations.

**Test steps:** 1. Measure the repository workflow. 2. Request reuse through a cache change and validate the proposal. 3. Repeat accepted candidates and compare; cross-configuration correctness still requires review.

**Results:** Main: 5 cases (1 unsafe, 4 inconclusive); 2 faster, 0 unchanged, 0 slower, 3 without complete paired timing.

## 25. Evaluate skipping unused-dependency updates (`P-LIT-UNUSED-DEP-SKIP`)

**What:** Skip work caused only by updates to unused dependencies.

**Test steps:** 1. Replay changes to used, unused, lockfile, setup, and unknown dependencies. 2. Skip work only for the unused dependency. 3. Check required builds, failure detection, and simulated work.

**Results:** Main: 11 cases (2 unsafe, 9 inconclusive); 0 faster, 0 unchanged, 0 slower, 11 without complete paired timing. Scenario: 4 cases (4 passed); 2 faster, 1 unchanged, 1 slower, 0 without complete paired timing.

## Evidence

- Pattern descriptions: [extracted_patterns.jsonl](../knowledge/extracted_patterns.jsonl).
- All retained main reports: `research-data/experiments/*/case.json`; scenario reports: `research-data/scenario-experiments/*/case.json`.
- Test methods: `scripts/run_ci_experiment.py`, `scripts/scenario_experiments.py`, and `scripts/scenario_replay.py`.
- Longer methodology: [rag-training.md](rag-training.md).

This is a fixed snapshot of saved reports. Active batches can add results after it is written.
