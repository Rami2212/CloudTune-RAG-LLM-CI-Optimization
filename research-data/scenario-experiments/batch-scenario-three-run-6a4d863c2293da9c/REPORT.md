# Controlled pattern scenario

Pattern: P-LIT-DURATION-PREDICTION
Outcome: inconclusive

| Arm | Recorded repeats | Passing repeats | Median summed job runtime (s) |
|---|---:|---:|---:|
| baseline | 0 | 0 | None |
| optimized | 0 | 0 | None |

## Replay metrics (synthetic logical time)

| Arm | Median simulated work (s) | Median missed failures | Median missed-failure rate | Held-out MAE (s) |
|---|---:|---:|---:|---:|
| baseline | None | None | None | None |
| optimized | None | None | None | None |

- Synthetic workload: timings are scenario resource costs, not original repository CI savings.
- No-run results are bounded observations with positive controls.
- Source branch-protection and required-check safety need a separate applicability review.
- Synthetic service policies replay logical time; hosted job runtime measures only replay execution overhead.
- Replay traces are reproduced locally from the exact hosted inputs/engine; GitHub success attests the hosted assertions.
- No real cron pause, owner notification, GitHub queue priority, build omission, or repository prediction accuracy is established.
