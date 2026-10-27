# Controlled pattern scenario

Pattern: P-LIT-BUILD-SELECT
Outcome: scenario_passed

| Arm | Recorded repeats | Passing repeats | Median summed job runtime (s) |
|---|---:|---:|---:|
| baseline | 3 | 3 | 2.0 |
| optimized | 3 | 3 | 3.0 |

## Replay metrics (synthetic logical time)

| Arm | Median simulated work (s) | Median missed failures | Median missed-failure rate | Held-out MAE (s) |
|---|---:|---:|---:|---:|
| baseline | 80 | 0 | 0.0 | None |
| optimized | 50 | 1 | 0.3333333333333333 | None |

- Synthetic workload: timings are scenario resource costs, not original repository CI savings.
- No-run results are bounded observations with positive controls.
- Source branch-protection and required-check safety need a separate applicability review.
- Synthetic service policies replay logical time; hosted job runtime measures only replay execution overhead.
- Replay traces are reproduced locally from the exact hosted inputs/engine; GitHub success attests the hosted assertions.
- No real cron pause, owner notification, GitHub queue priority, build omission, or repository prediction accuracy is established.
- The optimized selector deliberately exposes a missed setup failure; scenario_passed does not mean safe selection.
