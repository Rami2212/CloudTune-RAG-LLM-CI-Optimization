# Literature extraction: five requested papers

The stored set contains 25 full-text extraction records. Human admission review is pending; this is separate from completing the extraction. No local CI experiments or RAG indexing were performed.

Paper evidence, proposed application steps, and illustrative examples are distinct fields. Reported benefits are not local safe-success labels. Different records can describe related mechanisms and are not independent success observations.

## Coverage and source versions

All locators below refer to the archived PDFs, whose hashes and page counts are in [papers.jsonl](papers.jsonl). The bibliography URL alone is not a frozen source version.

| Paper | Records | Reviewed full-text sections |
| --- | ---: | --- |
| [S01: Resource Usage and Optimization Opportunities in Workflows of GitHub Actions](https://software-lab.org/publications/icse2024_workflows.pdf) | 10 | 3: methodology; 4.2: six existing mechanisms; 4.3: four proposals; 6: limitations |
| [S02: What helped, and what did not? An Evaluation of the Strategies to Improve Continuous Integration](https://arxiv.org/pdf/2102.06666) | 4 | III: methodology; IV-V: selection and prioritization; VI: trade-offs; VII: threats |
| [S03: Does Using Bazel Help Speed Up Continuous Integration Builds?](https://arxiv.org/pdf/2405.00796) | 3 | 2.3: mechanisms; 3.2.2-3.2.3: experiment design; 4.2-4.3: results; 5-6: discussion/threats |
| [S04: Accelerating Continuous Integration by Caching Environments and Inferring Dependencies](https://rebels.cs.uwaterloo.ca/papers/tse2020_gallaba.pdf) | 2 | 4: mechanisms/listings; 5-6: evaluation; 7: overhead/correctness; 9-10: limitations/requirements |
| [S05: Build Optimization: A Systematic Literature Review](https://arxiv.org/pdf/2501.11940) | 6 | 3: review protocol; 4.3/Table 2: optimization methods; 4.4: quality boundary; 4.5: metrics; 4.6/5: datasets/conclusions |

## Extraction boundaries

S01 covers all six existing mechanisms and four proposed heuristics in Sections 4.2-4.3. S02 covers all four selection/prioritization families; named replicated techniques are preserved in the paper registry. S03 covers build parallelism, result caching and the dependency-only negative result. S04 covers both acceleration levels and their joint limitations. S05 contributes six optimization or investigation leads; its underlying 97 studies were not independently read as part of this five-paper task.

Failure repair, co-change prediction, classifier architecture variants and dataset surveys are contextual material outside the working-workflow optimization task. The requested sources do not establish a standalone safe recipe for every initial topic: shallow checkout, generic artifact reuse, matrix pruning and GitHub job parallelism still need more specific evidence. Bazel build parallelism must not be relabeled as proof about GitHub job parallelism.

## What each record stores

- `research_question` and `optimization_question`: analyst-authored questions for investigation and later proposal generation.
- `method`, preconditions, contraindications and safety tests: proposed application guidance, explicitly identified as analyst synthesis.
- `reported_result`: a concise paper finding, reported metrics and a section/table/page locator. Consult the source registry's metric context and method before comparing numbers.
- `success_status`: `reported_benefit`, `estimated_benefit`, `mixed_results`, `secondary_report_only`, or `no_direct_speedup_evidence`. These are literature classifications, not proof of safety.
- `local_outcome`: `not_evaluated`. Real development cases, execution IDs and safe-success labels require Phase A/B experiments.
- `example`: hashed illustrative before/after pseudocode and a matching diff. It is not a source repository's workflow or an executed patch.

## Original examples and diffs

The requested papers do not supply a uniform set of paired GitHub Actions YAML patches. S04 has paired Travis/Kotinos configuration listings on PDF p. 4; S03 has build configuration examples; S02 uses a conceptual timeline; S05 summarizes other studies. See each source's `reported_workflow_example`. Original before/after/diff references are explicitly null in the extracted records rather than invented. The locally archived PDF retains the published listings for inspection.

## Pattern details

### P-LIT-GHA-CACHE: Cache dependency downloads

Source: S01, 4.2.1; Table 4; PDF pp. 6, 7. Scope: `workflow_yaml`. Literature outcome: `reported_benefit`.

**Question:** Assess cache dependency downloads for this repository, preserve its required checks, and propose a minimal change or NO_CHANGE.

**Paper finding:** Caching has modest aggregate benefit.

Reported metrics (interpret using the source registry's metric context):

```json
{
  "vm_time_reduction_percent": {
    "paid": 3.4,
    "free": 6
  }
}
```

**Proposed method (analyst synthesis):**

1. Choose dependency download state rather than unchecked build outputs
2. Keep installation and all required tests

**Preconditions:** Repeated dependency fetching is measurable; Cache inputs include lockfile and environment.

**Contraindications:** Mutable or untrusted cached content; An equivalent cache already exists.

**Proposed safety checks:** Cold/warm cache comparison; Change lockfile and runner environment.

Illustration only: [before](examples/P-LIT-GHA-CACHE/before.txt), [after](examples/P-LIT-GHA-CACHE/after.txt), [diff](examples/P-LIT-GHA-CACHE/change.diff).

### P-LIT-FAIL-FAST: Cancel remaining matrix jobs after failure

Source: S01, 4.2.2; Table 4; PDF pp. 6, 7. Scope: `workflow_yaml`. Literature outcome: `estimated_benefit`.

**Question:** Assess cancel remaining matrix jobs after failure for this repository, preserve its required checks, and propose a minimal change or NO_CHANGE.

**Paper finding:** Matrix cancellation saves remaining work.

Reported metrics (interpret using the source registry's metric context):

```json
{
  "vm_time_reduction_percent": {
    "paid": 1.5,
    "free": 2
  }
}
```

**Proposed method (analyst synthesis):**

1. Evaluate the contract before changing cancellation
2. Record canceled jobs

**Preconditions:** Matrix failure makes remaining results dispensable under an explicit study policy.

**Contraindications:** Every matrix outcome is required; Full failure diagnostics are required.

**Proposed safety checks:** Inject one failing matrix cell; Verify required matrix result policy.

Illustration only: [before](examples/P-LIT-FAIL-FAST/before.txt), [after](examples/P-LIT-FAIL-FAST/after.txt), [diff](examples/P-LIT-FAIL-FAST/change.diff).

### P-LIT-CANCEL-STALE: Cancel superseded runs

Source: S01, 4.2.3; Table 4; PDF pp. 7. Scope: `workflow_yaml`. Literature outcome: `estimated_benefit`.

**Question:** Assess cancel superseded runs for this repository, preserve its required checks, and propose a minimal change or NO_CHANGE.

**Paper finding:** Superseding runs can reduce duplicate work.

Reported metrics (interpret using the source registry's metric context):

```json
{
  "vm_time_reduction_percent": {
    "paid": 4.1,
    "free": 1.9
  }
}
```

**Proposed method (analyst synthesis):**

1. Partition cancellation by workflow and branch/PR
2. Preserve run identity and audit records

**Preconditions:** Runs represent the same workflow and branch or PR; A newer revision supersedes older checks.

**Contraindications:** Release or deployment work; Distinct branches share a cancellation group.

**Proposed safety checks:** Dispatch two revisions on one branch; Dispatch different branches and confirm isolation.

Illustration only: [before](examples/P-LIT-CANCEL-STALE/before.txt), [after](examples/P-LIT-CANCEL-STALE/after.txt), [diff](examples/P-LIT-CANCEL-STALE/change.diff).

### P-LIT-SKIP-WORKFLOW: Skip explicitly dispensable workflow runs

Source: S01, 4.2.4; Table 4; PDF pp. 7. Scope: `ci_service`. Literature outcome: `estimated_benefit`.

**Question:** Assess skip explicitly dispensable workflow runs for this repository, preserve its required checks, and propose a minimal change or NO_CHANGE.

**Paper finding:** Explicit skipping has limited aggregate impact.

Reported metrics (interpret using the source registry's metric context):

```json
{
  "paid_vm_time_reduction_upper_bound_percent": 0.1,
  "comparison": "less_than"
}
```

**Proposed method (analyst synthesis):**

1. Treat as behavior-changing rather than a safe default
2. Require evidence about affected checks

**Preconditions:** Repository policy permits a specific run to be omitted.

**Contraindications:** Strict contract requires all triggers to execute.

**Proposed safety checks:** Exercise branch protection and required-status behavior.

Illustration only: [before](examples/P-LIT-SKIP-WORKFLOW/before.txt), [after](examples/P-LIT-SKIP-WORKFLOW/after.txt), [diff](examples/P-LIT-SKIP-WORKFLOW/change.diff).

### P-LIT-CHANGE-FILTER: Filter workflow triggers by changed paths

Source: S01, 4.2.5; Table 4; PDF pp. 7. Scope: `workflow_yaml`. Literature outcome: `estimated_benefit`.

**Question:** Assess filter workflow triggers by changed paths for this repository, preserve its required checks, and propose a minimal change or NO_CHANGE.

**Paper finding:** Path filters have limited aggregate impact.

Reported metrics (interpret using the source registry's metric context):

```json
{
  "paid_vm_time_reduction_upper_bound_percent": 0.1,
  "comparison": "less_than"
}
```

**Proposed method (analyst synthesis):**

1. Map checks to relevant inputs before defining filters
2. Retain coverage for configuration changes

**Preconditions:** Changed-file dependencies are understood; Required-status semantics are preserved.

**Contraindications:** Shared configuration, generators or dependencies affect supposedly unrelated paths.

**Proposed safety checks:** Documentation-only, source, config and mixed changes; Check required-status completion.

Illustration only: [before](examples/P-LIT-CHANGE-FILTER/before.txt), [after](examples/P-LIT-CHANGE-FILTER/after.txt), [diff](examples/P-LIT-CHANGE-FILTER/change.diff).

### P-LIT-CUSTOM-TIMEOUT: Bound jobs with a custom timeout

Source: S01, 4.2.6; Table 4; PDF pp. 7, 8. Scope: `workflow_yaml`. Literature outcome: `estimated_benefit`.

**Question:** Assess bound jobs with a custom timeout for this repository, preserve its required checks, and propose a minimal change or NO_CHANGE.

**Paper finding:** Custom timeouts reduce runaway consumption.

Reported metrics (interpret using the source registry's metric context):

```json
{
  "vm_time_reduction_percent": {
    "paid": 8.1,
    "free": 12.9
  }
}
```

**Proposed method (analyst synthesis):**

1. Choose an explicit budget with operational headroom
2. Measure false timeout failures separately

**Preconditions:** Representative successful-duration history exists.

**Contraindications:** Valid slow runs exceed the proposed limit.

**Proposed safety checks:** Cold dependency installation; A deliberately hung step; Slow valid run.

Illustration only: [before](examples/P-LIT-CUSTOM-TIMEOUT/before.txt), [after](examples/P-LIT-CUSTOM-TIMEOUT/after.txt), [diff](examples/P-LIT-CUSTOM-TIMEOUT/change.diff).

### P-LIT-FAIL-SCHEDULE: Pause repeatedly failing scheduled workflows

Source: S01, 4.3.1; Tables 5-6; PDF pp. 8, 9. Scope: `ci_service`. Literature outcome: `estimated_benefit`.

**Question:** Assess pause repeatedly failing scheduled workflows for this repository, preserve its required checks, and propose a minimal change or NO_CHANGE.

**Paper finding:** Failure-streak suppression offers estimated savings.

Reported metrics (interpret using the source registry's metric context):

```json
{
  "consecutive_failure_threshold": 3,
  "paid_total_vm_time_reduction_percent": 3.2
}
```

**Proposed method (analyst synthesis):**

1. Notify the owner when pausing
2. Define an explicit recovery and reactivation path

**Preconditions:** A monitored pause/resume policy is approved.

**Contraindications:** Continuous monitoring or periodic checks are mandatory.

**Proposed safety checks:** Threshold, notification and recovery scenarios.

Illustration only: [before](examples/P-LIT-FAIL-SCHEDULE/before.txt), [after](examples/P-LIT-FAIL-SCHEDULE/after.txt), [diff](examples/P-LIT-FAIL-SCHEDULE/change.diff).

### P-LIT-IDLE-SCHEDULE: Suppress schedules during repository inactivity

Source: S01, 4.3.2; Table 5; PDF pp. 8, 9. Scope: `ci_service`. Literature outcome: `estimated_benefit`.

**Question:** Assess suppress schedules during repository inactivity for this repository, preserve its required checks, and propose a minimal change or NO_CHANGE.

**Paper finding:** Inactivity suppression saves some scheduled work.

Reported metrics (interpret using the source registry's metric context):

```json
{
  "paid_scheduled_vm_time_reduction_percent": 1.1
}
```

**Proposed method (analyst synthesis):**

1. Identify meaningful activity rather than generated self-updates
2. Resume when relevant inputs change

**Preconditions:** Periodic results depend only on repository changes.

**Contraindications:** External dependencies, security or time-based requirements need fresh checks.

**Proposed safety checks:** No-change interval; External input change; Workflow-generated commit.

Illustration only: [before](examples/P-LIT-IDLE-SCHEDULE/before.txt), [after](examples/P-LIT-IDLE-SCHEDULE/after.txt), [diff](examples/P-LIT-IDLE-SCHEDULE/change.diff).

### P-LIT-FAILED-JOB-FIRST: Run previously failing jobs first

Source: S01, 4.3.3; Table 5; PDF pp. 8, 9. Scope: `ci_service`. Literature outcome: `estimated_benefit`.

**Question:** Assess run previously failing jobs first for this repository, preserve its required checks, and propose a minimal change or NO_CHANGE.

**Paper finding:** Failure-first gating saves work on failures.

Reported metrics (interpret using the source registry's metric context):

```json
{
  "paid_total_vm_time_reduction_percent": 1.1,
  "paid_failed_run_vm_time_reduction_percent": 31.6
}
```

**Proposed method (analyst synthesis):**

1. Separate early feedback from cancellation-based savings
2. Preserve the dependency graph

**Preconditions:** Required dependencies allow reordering; Policy permits stopping after an earlier failure.

**Contraindications:** Independent outcomes must all be collected; Adding a gate would hide required results.

**Proposed safety checks:** Previously failed job fails again; Previously failed job now passes; Cross-job artifact dependency.

Illustration only: [before](examples/P-LIT-FAILED-JOB-FIRST/before.txt), [after](examples/P-LIT-FAILED-JOB-FIRST/after.txt), [diff](examples/P-LIT-FAILED-JOB-FIRST/change.diff).

### P-LIT-HISTORY-TIMEOUT: Derive timeout candidates from successful history

Source: S01, 4.3.4; Table 5; PDF pp. 9. Scope: `workflow_yaml`. Literature outcome: `estimated_benefit`.

**Question:** Assess derive timeout candidates from successful history for this repository, preserve its required checks, and propose a minimal change or NO_CHANGE.

**Paper finding:** History-based timeout savings are retrospective estimates.

Reported metrics (interpret using the source registry's metric context):

```json
{
  "buffer_multiplier": 1.1,
  "historical_cap_hours": 6,
  "paid_total_vm_time_reduction_percent": 3.5
}
```

**Proposed method (analyst synthesis):**

1. Use past data only when proposing a limit
2. Evaluate the candidate on future slow and cold runs

**Preconditions:** Successful job history is representative.

**Contraindications:** New workloads or runners invalidate historical bounds.

**Proposed safety checks:** Chronological validation; Changed workload; Timeout false positives.

Illustration only: [before](examples/P-LIT-HISTORY-TIMEOUT/before.txt), [after](examples/P-LIT-HISTORY-TIMEOUT/after.txt), [diff](examples/P-LIT-HISTORY-TIMEOUT/change.diff).

### P-LIT-PRIORITIZE: Prioritize tests for early failure feedback

Source: S02, V.A.1; V.B; VI.C; PDF pp. 6, 8, 9. Scope: `build_configuration`. Literature outcome: `reported_benefit`.

**Question:** Assess prioritize tests for early failure feedback for this repository, preserve required checks, and propose a minimal change or NO_CHANGE.

**Paper finding:** Ordering advances failure feedback without inherently saving compute.

**Proposed method (analyst synthesis):**

1. Rank tests using history or diversity
2. Retain every required test

**Preconditions:** Tests tolerate reordering.

**Contraindications:** Order-dependent tests; Required tests would be stopped.

**Proposed safety checks:** Complete test-set comparison; Time to first failure.

Illustration only: [before](examples/P-LIT-PRIORITIZE/before.txt), [after](examples/P-LIT-PRIORITIZE/after.txt), [diff](examples/P-LIT-PRIORITIZE/change.diff).

### P-LIT-BUILD-PRIORITY: Prioritize queued builds

Source: S02, V.A.2; V.B; VI.C; PDF pp. 6, 8, 9. Scope: `ci_service`. Literature outcome: `mixed_results`.

**Question:** Assess prioritize queued builds for this repository, preserve required checks, and propose a minimal change or NO_CHANGE.

**Paper finding:** Build ordering had limited benefit without contention.

Reported metrics (interpret using the source registry's metric context):

```json
{
  "projects_with_meaningful_queue": 1
}
```

**Proposed method (analyst synthesis):**

1. Measure contention first
2. Retain fairness

**Preconditions:** Runs compete for constrained workers.

**Contraindications:** No queue; Priority starvation.

**Proposed safety checks:** No-contention baseline; Contended queue; Maximum wait.

Illustration only: [before](examples/P-LIT-BUILD-PRIORITY/before.txt), [after](examples/P-LIT-BUILD-PRIORITY/after.txt), [diff](examples/P-LIT-BUILD-PRIORITY/change.diff).

### P-LIT-SELECT: Select tests using change dependencies

Source: S02, IV.A.1; IV.C; VI.B; PDF pp. 4, 5, 9. Scope: `build_configuration`. Literature outcome: `mixed_results`.

**Question:** Assess select tests using change dependencies for this repository, preserve required checks, and propose a minimal change or NO_CHANGE.

**Paper finding:** Selection savings can hide failing tests.

**Proposed method (analyst synthesis):**

1. Compare full and selected results
2. Retain configuration-failure detection

**Preconditions:** Reliable dependency data; Separately approved selection treatment.

**Contraindications:** Strict contract requires the full test set.

**Proposed safety checks:** Full-run oracle; Added or renamed files.

Illustration only: [before](examples/P-LIT-SELECT/before.txt), [after](examples/P-LIT-SELECT/after.txt), [diff](examples/P-LIT-SELECT/change.diff).

### P-LIT-BUILD-SELECT: Select builds using change or outcome predictions

Source: S02, IV.A.2; IV.B.2; VI.B; PDF pp. 4, 5, 9. Scope: `ci_service`. Literature outcome: `mixed_results`.

**Question:** Assess select builds using change or outcome predictions for this repository, preserve required checks, and propose a minimal change or NO_CHANGE.

**Paper finding:** Apparently safe changes can still fail.

Reported metrics (interpret using the source registry's metric context):

```json
{
  "SB_Abd19_median_build_time_saved_percent": 21
}
```

**Proposed method (analyst synthesis):**

1. Measure missed failures and savings together
2. Hide future and skipped outcomes during replay

**Preconditions:** Selection is a separately approved experiment.

**Contraindications:** Required checks must run on each revision.

**Proposed safety checks:** Chronological replay; Omitted setup failures.

Illustration only: [before](examples/P-LIT-BUILD-SELECT/before.txt), [after](examples/P-LIT-BUILD-SELECT/after.txt), [diff](examples/P-LIT-BUILD-SELECT/change.diff).

### P-LIT-BAZEL-PARALLEL: Tune Bazel build parallelism

Source: S03, 3.2.2; 4.2; 6.3; PDF pp. 18, 19, 31, 32, 33, 43. Scope: `build_configuration`. Literature outcome: `reported_benefit`.

**Question:** Assess tune bazel build parallelism for this repository, preserve required checks, and propose a minimal change or NO_CHANGE.

**Paper finding:** Long compilations benefited most from parallelism.

Reported metrics (interpret using the source registry's metric context):

```json
{
  "long_build_median_speedup": {
    "cores_2": 2,
    "cores_4": 3.84,
    "cores_8": 7.36,
    "cores_16": 12.8
  }
}
```

**Proposed method (analyst synthesis):**

1. Compare concurrency within resource quotas
2. Keep targets and inputs identical

**Preconditions:** Existing Bazel build; Sufficient CPU and memory.

**Contraindications:** Larger flags are assumed to supply more runner resources.

**Proposed safety checks:** Repeated resource-matched runs; Outputs and runner usage.

Illustration only: [before](examples/P-LIT-BAZEL-PARALLEL/before.txt), [after](examples/P-LIT-BAZEL-PARALLEL/after.txt), [diff](examples/P-LIT-BAZEL-PARALLEL/change.diff).

### P-LIT-BAZEL-INCREMENTAL: Cache Bazel build results

Source: S03, 3.2.3; 4.3; Table 10; PDF pp. 24, 25, 36, 37, 38. Scope: `build_configuration`. Literature outcome: `reported_benefit`.

**Question:** Assess cache bazel build results for this repository, preserve required checks, and propose a minimal change or NO_CHANGE.

**Paper finding:** Result caching particularly helped long compilations.

Reported metrics (interpret using the source registry's metric context):

```json
{
  "long_build_median_speedup": {
    "general_deps_and_results": 4.22,
    "specific_deps_and_results": 4.71
  }
}
```

**Proposed method (analyst synthesis):**

1. Separate dependency and result caching
2. Record cold behavior and hit rates

**Preconditions:** Existing Bazel build; Trusted, input-keyed cache.

**Contraindications:** Mutable undeclared inputs; Untrusted cache writes.

**Proposed safety checks:** Changed source and toolchain; Clean/cached output comparison.

Illustration only: [before](examples/P-LIT-BAZEL-INCREMENTAL/before.txt), [after](examples/P-LIT-BAZEL-INCREMENTAL/after.txt), [diff](examples/P-LIT-BAZEL-INCREMENTAL/change.diff).

### P-LIT-BAZEL-DEPS: Evaluate dependency cache overhead

Source: S03, 3.2.3; 4.3; PDF pp. 24, 25, 36, 37, 38. Scope: `build_configuration`. Literature outcome: `mixed_results`.

**Question:** Assess evaluate dependency cache overhead for this repository, preserve required checks, and propose a minimal change or NO_CHANGE.

**Paper finding:** Dependency-only caching offered no clear speedup.

Reported metrics (interpret using the source registry's metric context):

```json
{
  "dependency_only_median_speedup": {
    "short": 1,
    "medium": 0.88,
    "long": 0.85
  }
}
```

**Proposed method (analyst synthesis):**

1. Compare total restore/upload cost
2. Evaluate result caching separately

**Preconditions:** Transfer and installation time can be separated.

**Contraindications:** Cache benefit is assumed without measurement.

**Proposed safety checks:** Cold/warm comparison; End-to-end transfer overhead.

Illustration only: [before](examples/P-LIT-BAZEL-DEPS/before.txt), [after](examples/P-LIT-BAZEL-DEPS/after.txt), [diff](examples/P-LIT-BAZEL-DEPS/change.diff).

### P-LIT-ENV-CACHE: Reuse validated build environments

Source: S04, 4.1; 6.3; 7.2; 10; PDF pp. 4, 8, 10, 11. Scope: `ci_service`. Literature outcome: `reported_benefit`.

**Question:** Assess reuse validated build environments for this repository, preserve required checks, and propose a minimal change or NO_CHANGE.

**Paper finding:** Reuse needs pinned dependencies and resettable state.

Reported metrics (interpret using the source registry's metric context):

```json
{
  "correctness_matching_outcomes": 466,
  "correctness_flaky_exclusions": 34
}
```

**Proposed method (analyst synthesis):**

1. Reuse a trusted successful snapshot
2. Invalidate changed environment inputs
3. Always execute necessary state resets

**Preconditions:** Dependencies pinned including transitives; Tests reset files and services.

**Contraindications:** Mutable dependency resolution; Persistent test contamination.

**Proposed safety checks:** Clean/restored result comparison; Changed dependencies; State cleanup.

Illustration only: [before](examples/P-LIT-ENV-CACHE/before.txt), [after](examples/P-LIT-ENV-CACHE/after.txt), [diff](examples/P-LIT-ENV-CACHE/change.diff).

### P-LIT-UNAFFECTED-STEPS: Skip steps using traced dependencies

Source: S04, 4.2; 6.3; 7.2; 10; PDF pp. 5, 6, 8, 10, 11. Scope: `ci_service`. Literature outcome: `mixed_results`.

**Question:** Assess skip steps using traced dependencies for this repository, preserve required checks, and propose a minimal change or NO_CHANGE.

**Paper finding:** Coarse test processes limited skipping gains.

Reported metrics (interpret using the source registry's metric context):

```json
{
  "combined_acceleration_warm_builds_at_least_2x_faster_percent": 74,
  "benefiting_replay_projects": 5,
  "replay_projects": 7
}
```

**Proposed method (analyst synthesis):**

1. Update traced dependencies after runs
2. Fall back after added/renamed files
3. Do not attribute combined gains solely to skipping

**Preconditions:** Tracing and cold fallback exist.

**Contraindications:** Incomplete dynamic paths; Full check execution is required.

**Proposed safety checks:** Full-run comparison; Conditional inputs; Added/renamed files.

Illustration only: [before](examples/P-LIT-UNAFFECTED-STEPS/before.txt), [after](examples/P-LIT-UNAFFECTED-STEPS/after.txt), [diff](examples/P-LIT-UNAFFECTED-STEPS/change.diff).

### P-LIT-SMELL-REPAIR: Repair evidenced configuration smells

Source: S05, 4.3.3; Table 2, BuildSonic; PDF pp. 14, 16. Scope: `workflow_yaml`. Literature outcome: `secondary_report_only`.

**Question:** Assess repair evidenced configuration smells for this repository, preserve required checks, and propose a minimal change or NO_CHANGE.

**Paper finding:** BuildSonic reports acceleration through configuration repair.

Reported metrics (interpret using the source registry's metric context):

```json
{
  "secondary_reported_build_speedup_percent": 12.4
}
```

**Proposed method (analyst synthesis):**

1. Identify the exact issue
2. Verify the primary method before adapting

**Preconditions:** Concrete primary-source repair is verified.

**Contraindications:** A smell name alone justifies removal.

**Proposed safety checks:** Required command comparison; Actual timing.

Illustration only: [before](examples/P-LIT-SMELL-REPAIR/before.txt), [after](examples/P-LIT-SMELL-REPAIR/after.txt), [diff](examples/P-LIT-SMELL-REPAIR/change.diff).

### P-LIT-DURATION-PREDICTION: Predict duration to guide investigation

Source: S05, 4.3.3; Table 2; PDF pp. 14, 18. Scope: `research_only`. Literature outcome: `no_direct_speedup_evidence`.

**Question:** Assess predict duration to guide investigation for this repository, preserve required checks, and propose a minimal change or NO_CHANGE.

**Paper finding:** Prediction supports analysis rather than direct acceleration.

**Proposed method (analyst synthesis):**

1. Identify candidates or estimate budgets
2. Measure actual workflow changes separately

**Preconditions:** Timing data and chronological validation.

**Contraindications:** Predictions are claimed as speedups.

**Proposed safety checks:** Held-out timing error; Future-data leakage.

Illustration only: [before](examples/P-LIT-DURATION-PREDICTION/before.txt), [after](examples/P-LIT-DURATION-PREDICTION/after.txt), [diff](examples/P-LIT-DURATION-PREDICTION/change.diff).

### P-LIT-UNUSED-OUTPUTS: Remove genuinely unused outputs

Source: S05, 4.3.3; Table 2, OptCD; PDF pp. 14, 16. Scope: `workflow_yaml`. Literature outcome: `secondary_report_only`.

**Question:** Assess remove genuinely unused outputs for this repository, preserve required checks, and propose a minimal change or NO_CHANGE.

**Paper finding:** OptCD removes work producing unused content.

Reported metrics (interpret using the source registry's metric context):

```json
{
  "secondary_reported_build_speedup_percent": 7
}
```

**Proposed method (analyst synthesis):**

1. Trace consumers
2. Retain required deliverables

**Preconditions:** All output consumers are identified.

**Contraindications:** A downstream check or artifact needs the output.

**Proposed safety checks:** Downstream and artifact comparison.

Illustration only: [before](examples/P-LIT-UNUSED-OUTPUTS/before.txt), [after](examples/P-LIT-UNUSED-OUTPUTS/after.txt), [diff](examples/P-LIT-UNUSED-OUTPUTS/change.diff).

### P-LIT-DISTRIBUTED-CACHE: Share cached build dependencies

Source: S05, 4.3.3; Table 2, CloudBuild; PDF pp. 14, 16. Scope: `ci_service`. Literature outcome: `secondary_report_only`.

**Question:** Assess share cached build dependencies for this repository, preserve required checks, and propose a minimal change or NO_CHANGE.

**Paper finding:** Distributed caching reuses earlier dependencies.

**Proposed method (analyst synthesis):**

1. Evaluate transfer overhead and trust
2. Keep inputs pinned

**Preconditions:** Trusted cache infrastructure.

**Contraindications:** Infrastructure changes exceed treatment scope.

**Proposed safety checks:** Isolation; Cache misses; Total consumption.

Illustration only: [before](examples/P-LIT-DISTRIBUTED-CACHE/before.txt), [after](examples/P-LIT-DISTRIBUTED-CACHE/after.txt), [diff](examples/P-LIT-DISTRIBUTED-CACHE/change.diff).

### P-LIT-CONFIG-REUSE: Reuse work across compatible configurations

Source: S05, 4.3.3; Table 2, Randrianaina et al.; PDF pp. 14, 16, 17. Scope: `build_configuration`. Literature outcome: `secondary_report_only`.

**Question:** Assess reuse work across compatible configurations for this repository, preserve required checks, and propose a minimal change or NO_CHANGE.

**Paper finding:** Configuration ordering enables common-work reuse.

Reported metrics (interpret using the source registry's metric context):

```json
{
  "secondary_reported_build_time_reduction_upper_bound_percent": 66
}
```

**Proposed method (analyst synthesis):**

1. Retain every configuration
2. Reuse only input-compatible work

**Preconditions:** Primary method establishes configuration compatibility.

**Contraindications:** Target settings make artifacts incompatible.

**Proposed safety checks:** Full configuration and output comparison.

Illustration only: [before](examples/P-LIT-CONFIG-REUSE/before.txt), [after](examples/P-LIT-CONFIG-REUSE/after.txt), [diff](examples/P-LIT-CONFIG-REUSE/change.diff).

### P-LIT-UNUSED-DEP-SKIP: Evaluate skipping unused-dependency updates

Source: S05, 4.3.3; Table 2, Dep-sCImitar; PDF pp. 14, 16. Scope: `ci_service`. Literature outcome: `secondary_report_only`.

**Question:** Assess evaluate skipping unused-dependency updates for this repository, preserve required checks, and propose a minimal change or NO_CHANGE.

**Paper finding:** Unused dependency updates offer selection opportunities.

Reported metrics (interpret using the source registry's metric context):

```json
{
  "secondary_reported_build_time_saved_percent": 68.34
}
```

**Proposed method (analyst synthesis):**

1. Evaluate under a separate selection policy
2. Compare with complete builds

**Preconditions:** Primary dependency-use and history conditions hold.

**Contraindications:** Transitive or lockfile changes affect required checks.

**Proposed safety checks:** Transitive update; Lockfile change; Misclassification.

Illustration only: [before](examples/P-LIT-UNUSED-DEP-SKIP/before.txt), [after](examples/P-LIT-UNUSED-DEP-SKIP/after.txt), [diff](examples/P-LIT-UNUSED-DEP-SKIP/change.diff).

## Rebuild and validate offline

```powershell
.\.venv\Scripts\python.exe scripts\build_literature_assets.py
.\.venv\Scripts\python.exe scripts\validate_knowledge.py --check-artifacts
```

Rebuilding intentionally updates source/example hashes and regenerates this report. Investigate an unexpected integrity failure before rebuilding. Human review checks the interpretation against the cited paper; structural validation cannot perform that scientific judgment.
