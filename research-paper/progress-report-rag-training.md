# Progress report: RAG training patterns

Snapshot: 31 October 2026. This report covers the 16 patterns in `training-results-v2.md`. Each is listed there with 2/2 qualifying examples. These are preliminary results; the reported tests and timing comparisons do not establish that every change is safe or will speed up every repository.

## Results

Mean decrease is baseline median minus optimized median; positive values indicate faster runs. The percentage is the arithmetic mean of qualifying cases' individual percentage decreases. Evidence counts are reports / qualifying cases. Per-pattern baseline and optimized medians are not included in the v2 summary.

| Pattern | Qualifying / target | Reports / qualifying | Mean decrease (seconds) | Mean decrease (%) |
|---|---:|---:|---:|---:|
| `P-LIT-GHA-CACHE` | 2/2 | 4/2 | +11.00 | +13.23% |
| `P-LIT-FAIL-FAST` | 2/2 | 2/2 | +4.50 | +0.93% |
| `P-LIT-CANCEL-STALE` | 2/2 | 3/2 | +2.50 | +0.90% |
| `P-LIT-CHANGE-FILTER` | 2/2 | 2/2 | +8.00 | +20.78% |
| `P-LIT-CUSTOM-TIMEOUT` | 2/2 | 3/2 | +12.50 | +18.31% |
| `P-LIT-HISTORY-TIMEOUT` | 2/2 | 6/2 | +1.00 | +4.85% |
| `P-LIT-PRIORITIZE` | 2/2 | 4/2 | +1.00 | +29.17% |
| `P-LIT-SELECT` | 2/2 | 8/2 | +1.00 | +33.33% |
| `P-LIT-BAZEL-DEPS` | 2/2 | 8/2 | +1.00 | +33.33% |
| `P-LIT-ENV-CACHE` | 2/2 | 5/2 | +1.00 | +25.00% |
| `P-LIT-UNAFFECTED-STEPS` | 2/2 | 9/2 | +1.00 | +33.33% |
| `P-LIT-SMELL-REPAIR` | 2/2 | 2/2 | +1.00 | +29.17% |
| `P-LIT-UNUSED-OUTPUTS` | 2/2 | 4/2 | +1.00 | +25.00% |
| `P-LIT-DISTRIBUTED-CACHE` | 2/2 | 7/2 | +34.50 | +9.87% |
| `P-LIT-CONFIG-REUSE` | 2/2 | 5/2 | +38.00 | +27.90% |
| `P-LIT-UNUSED-DEP-SKIP` | 2/2 | 4/2 | +1.00 | +25.00% |

| Pattern | What it does; literature source | How it was tested |
|---|---|---|
| `P-LIT-GHA-CACHE` | Reuses downloaded packages. S01 §4.2.1. | Compared workflow runs before and after adding dependency caching; YAML was validated. Cache cold/warm state was not controlled. |
| `P-LIT-FAIL-FAST` | Cancels remaining matrix jobs after a failure. S01 §4.2.2. | Ran a three-job matrix with fail-fast off and on; checked cancellation and a healthy control run. |
| `P-LIT-CANCEL-STALE` | Cancels an older run superseded by a newer commit. S01 §4.2.3. | Created overlapping commits and a separate-branch control; checked cancellation, latest-run completion, and branch isolation. |
| `P-LIT-CHANGE-FILTER` | Starts workflows only for relevant file changes. S01 §4.2.5. | Checked documentation, source, configuration, and mixed changes; confirmed relevant workflows still ran. |
| `P-LIT-CUSTOM-TIMEOUT` | Sets a suitable upper time limit for jobs. S01 §4.2.6. | Compared normal workflow runs after timeout-only edits and validated the configuration; hung-job behavior was not exercised. |
| `P-LIT-HISTORY-TIMEOUT` | Uses successful-run durations to propose timeout limits. S01 §4.3.4. | Collected baseline durations, made timeout-only edits, and compared repeat runs; a history estimator was not used. |
| `P-LIT-PRIORITIZE` | Runs tests likely to fail earlier. S02 §V.A.1, §V.B. | Reordered tests to put a previously failing test first; checked test coverage, outcomes, total work, and time to failure. |
| `P-LIT-SELECT` | Runs tests related to changed code. S02 §IV.A.1, §IV.C. | Applied a dependency map to documentation, source, mixed, dependency, and unknown changes; checked required tests and failure detection. |
| `P-LIT-BAZEL-DEPS` | Checks whether dependency caching saves more time than it costs. S03 §§3.2.3, 4.3. | Compared cached and uncached dependency fetching; checked cache hits, invalidation, retained build/tests, and overhead for cheap downloads. |
| `P-LIT-ENV-CACHE` | Reuses prepared environments when inputs remain compatible. S04 §§4.1, 6.3. | Checked environment reuse and invalidation for dependency, environment, and toolchain changes; verified builds, outputs, and tests remained. |
| `P-LIT-UNAFFECTED-STEPS` | Skips steps whose tracked inputs did not change. S04 §§4.2, 6.3. | Applied a dependency map across direct, transitive, lockfile, setup, and unknown changes; checked affected steps still ran. |
| `P-LIT-SMELL-REPAIR` | Fixes documented inefficient build configuration. S05 §4.3.3, Table 2. | Removed a redundant compile in a controlled build; checked required outputs, side effects, and work performed. |
| `P-LIT-UNUSED-OUTPUTS` | Avoids producing outputs with no required consumers. S05 §4.3.3, Table 2. | Compared builds with consumed and unconsumed outputs; checked required outputs and work performed. |
| `P-LIT-DISTRIBUTED-CACHE` | Shares cached dependencies across workers. S05 §4.3.3, Table 2. | Compared workflow runs after a bounded cache change; cross-worker cache correctness was not independently verified. |
| `P-LIT-CONFIG-REUSE` | Reuses work across compatible configurations. S05 §4.3.3, Table 2. | Compared workflow runs after a cache-based reuse proposal; compatibility across configurations still needs review. |
| `P-LIT-UNUSED-DEP-SKIP` | Evaluates skipping updates to dependencies not used by the build. S05 §4.3.3, Table 2. | Checked used, unused, lockfile, setup, and unknown dependency changes; verified required builds and failure detection. |

## Sources

- **S01:** Bouzenia & Pradel (2024), [Resource Usage and Optimization Opportunities in Workflows of GitHub Actions](https://software-lab.org/publications/icse2024_workflows.pdf).
- **S02:** Jin & Servant (2021), [What helped, and what did not? An Evaluation of the Strategies to Improve Continuous Integration](https://arxiv.org/pdf/2102.06666).
- **S03:** Zheng, Adams & Hassan (2024), [Does Using Bazel Help Speed Up Continuous Integration Builds?](https://arxiv.org/pdf/2405.00796).
- **S04:** Gallaba et al. (2022), [Accelerating Continuous Integration by Caching Environments and Inferring Dependencies](https://rebels.cs.uwaterloo.ca/papers/tse2020_gallaba.pdf).
- **S05:** Aïdasso, Sayagh & Bordeleau (2025), [Build Optimization: A Systematic Literature Review](https://arxiv.org/pdf/2501.11940).

Local sources: `research-paper/training-results-v2.md`, `research-paper/patterns.md`, and `research-paper/patterns-test-results.md`.
