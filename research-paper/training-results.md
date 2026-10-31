# Training results

Snapshot: 31 October 2026. This summary includes real-repository case reports and controlled-scenario case reports across 25 patterns. A qualifying example is a case whose `pattern_satisfied` field is `true` and has usable timing data. Non-qualifying cases are excluded from the time averages below.

There are **49 qualifying examples across all 25 patterns.**

## Results by pattern

“Mean decrease” is baseline median minus optimized median; positive means faster. Percentages are the arithmetic mean of qualifying cases' individual percentage decreases. Real-repository rows use workflow elapsed time. Synthetic rows use hosted scenario job runtime, which measures the test harness and is not a saving on the source repository's CI. In the Evidence column, each source is shown as `case reports / qualifying reports`; `Repository` means the real-repository script, and `Scenario` means the controlled-scenario script.

| Pattern | Qualifying examples / target | Evidence (reports / qualifying) | Mean decrease (seconds; percent) |
| --- | ---: |------------------------------------------------| ---: |
| P-LIT-GHA-CACHE | 2/2 | Repository 4/2                                 | +11.00 s (+13.23%) |
| P-LIT-FAIL-FAST | 2/2 | Scenario 2/2                                   | +4.50 s (+0.93%) |
| P-LIT-CANCEL-STALE | 2/2 | Scenario 3/2                                   | +2.50 s (+0.90%) |
| P-LIT-SKIP-WORKFLOW | 2/2 | Scenario 2/2                                   | +8.00 s (+34.78%) |
| P-LIT-CHANGE-FILTER | 2/2 | Scenario 2/2                                   | +8.00 s (+20.78%) |
| P-LIT-CUSTOM-TIMEOUT | 2/2 | Repository 3/2                                       | +12.50 s (+18.31%) |
| P-LIT-FAIL-SCHEDULE | 2/2 | Scenario 2/2                                   | +1.00 s (+25.00%) |
| P-LIT-IDLE-SCHEDULE | 2/2 | Scenario 2/2                                   | +1.00 s (+25.00%) |
| P-LIT-FAILED-JOB-FIRST | 2/2 | Scenario 4/2                                   | +1.00 s (+25.00%) |
| P-LIT-HISTORY-TIMEOUT | 2/2 | Repository 10/2                                      | +1.00 s (+4.85%) |
| P-LIT-PRIORITIZE | 2/2 | Repository 4/2                                       | +1.00 s (+29.17%) |
| P-LIT-BUILD-PRIORITY | 1/2 | Scenario 5/1                                   | +1.00 s (+25.00%) |
| P-LIT-SELECT | 2/2 | Repository 18/2                                      | +1.00 s (+33.33%) |
| P-LIT-BUILD-SELECT | 2/2 | Scenario 2/2                                   | +1.00 s (+29.17%) |
| P-LIT-BAZEL-PARALLEL | 2/2 | Scenario 10/2                                  | +1.00 s (+29.17%) |
| P-LIT-BAZEL-INCREMENTAL | 2/2 | Scenario 7/2                                   | +1.00 s (+29.17%) |
| P-LIT-BAZEL-DEPS | 2/2 | Scenario 8/2                                   | +1.00 s (+33.33%) |
| P-LIT-ENV-CACHE | 2/2 | Scenario 13/2                                  | +1.00 s (+25.00%) |
| P-LIT-UNAFFECTED-STEPS | 2/2 | Repository 9/2                                       | +1.00 s (+33.33%) |
| P-LIT-SMELL-REPAIR | 2/2 | Repository 2/2                                       | +1.00 s (+29.17%) |
| P-LIT-DURATION-PREDICTION | 2/2 | Scenario 9/2                                   | +1.00 s (+29.17%) |
| P-LIT-UNUSED-OUTPUTS | 2/2 | Repository 4/2                                       | +1.00 s (+25.00%) |
| P-LIT-DISTRIBUTED-CACHE | 2/2 | Repository 7/2                                       | +34.50 s (+9.87%) |
| P-LIT-CONFIG-REUSE | 2/2 | Repository 5/2                                       | +38.00 s (+27.90%) |
| P-LIT-UNUSED-DEP-SKIP | 2/2 | Repository 4/2                                       | +1.00 s (+25.00%) |