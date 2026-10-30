# Controlled pattern scenario

Pattern: P-LIT-UNAFFECTED-STEPS
Outcome: scenario_passed

| Arm | Recorded repeats | Passing repeats | Median summed job runtime (s) |
|---|---:|---:|---:|
| baseline | 3 | 3 | 3.0 |
| optimized | 3 | 3 | 4.0 |

## Replay metrics (synthetic logical time)

| Arm | Median simulated work (s) | Median missed failures | Median missed-failure rate | Held-out MAE (s) |
|---|---:|---:|---:|---:|
| baseline | 480 | None | None | None |
| optimized | 280 | None | None | None |

| Arm | Simulated elapsed (s) | First failure (s) | Cache hits |
|---|---:|---:|---:|
| baseline | None | None | None |
| optimized | None | None | None |

- Synthetic workload: timings are scenario resource costs, not original repository CI savings.
- No-run results are bounded observations with positive controls.
- Source branch-protection and required-check safety need a separate applicability review.
- Synthetic service policies replay logical time; hosted job runtime measures only replay execution overhead.
- Replay traces are reproduced locally from the exact hosted inputs/engine; GitHub success attests the hosted assertions.
- No real cron pause, owner notification, GitHub queue priority, build omission, or repository prediction accuracy is established.
- Mechanisms use deterministic synthetic graphs, inputs, outputs and cost models; no actual Bazel process, environment image, file-access tracing or source-repository test suite is evaluated.
