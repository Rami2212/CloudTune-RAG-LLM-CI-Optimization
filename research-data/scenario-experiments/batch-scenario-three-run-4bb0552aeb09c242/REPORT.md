# Controlled pattern scenario

Pattern: P-LIT-FAIL-FAST
Outcome: scenario_passed

| Arm | Recorded repeats | Passing repeats | Median summed job runtime (s) |
|---|---:|---:|---:|
| baseline | 3 | 3 | 485.0 |
| optimized | 3 | 3 | 482.0 |

- Synthetic workload: timings are scenario resource costs, not original repository CI savings.
- No-run results are bounded observations with positive controls.
- Source branch-protection and required-check safety need a separate applicability review.
