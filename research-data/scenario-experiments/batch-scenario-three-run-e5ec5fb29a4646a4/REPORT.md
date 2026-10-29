# Controlled pattern scenario

Pattern: P-LIT-SKIP-WORKFLOW
Outcome: scenario_passed

| Arm | Recorded repeats | Passing repeats | Median summed job runtime (s) |
|---|---:|---:|---:|
| baseline | 3 | 3 | 23.0 |
| optimized | 3 | 3 | 15.0 |

- Synthetic workload: timings are scenario resource costs, not original repository CI savings.
- No-run results are bounded observations with positive controls.
- Source branch-protection and required-check safety need a separate applicability review.
