# Training results

Snapshot: 31 October 2026. This summary includes case reports across 16 patterns. A qualifying example is a case whose `pattern_satisfied` field is `true` and has usable timing data.

## Results by pattern

“Mean decrease” is baseline median minus optimized median; positive means faster. Percentages are the arithmetic mean of qualifying cases' individual percentage decreases. Repository rows use workflow elapsed time.

| Pattern | Qualifying examples / target | Evidence (reports / qualifying) | Mean decrease (seconds; percent) |
| --- | ---: |---------------------------------| ---: |
| P-LIT-GHA-CACHE | 2/2 | 4/2                             | +11.00 s (+13.23%) |
| P-LIT-FAIL-FAST | 2/2 | 2/2                             | +4.50 s (+0.93%) |
| P-LIT-CANCEL-STALE | 2/2 | 3/2                             | +2.50 s (+0.90%) |
| P-LIT-CHANGE-FILTER | 2/2 | 2/2                             | +8.00 s (+20.78%) |
| P-LIT-CUSTOM-TIMEOUT | 2/2 | 3/2                             | +12.50 s (+18.31%) |
| P-LIT-HISTORY-TIMEOUT | 2/2 | 6/2                             | +1.00 s (+4.85%) |
| P-LIT-PRIORITIZE | 2/2 | 4/2                             | +1.00 s (+29.17%) |
| P-LIT-SELECT | 2/2 | 8/2                             | +1.00 s (+33.33%) |
| P-LIT-BAZEL-DEPS | 2/2 | 8/2                             | +1.00 s (+33.33%) |
| P-LIT-ENV-CACHE | 2/2 | 5/2                             | +1.00 s (+25.00%) |
| P-LIT-UNAFFECTED-STEPS | 2/2 | 9/2                             | +1.00 s (+33.33%) |
| P-LIT-SMELL-REPAIR | 2/2 | 2/2                             | +1.00 s (+29.17%) |
| P-LIT-UNUSED-OUTPUTS | 2/2 | 4/2                             | +1.00 s (+25.00%) |
| P-LIT-DISTRIBUTED-CACHE | 2/2 | 7/2                             | +34.50 s (+9.87%) |
| P-LIT-CONFIG-REUSE | 2/2 | 5/2                             | +38.00 s (+27.90%) |
| P-LIT-UNUSED-DEP-SKIP | 2/2 | 4/2                             | +1.00 s (+25.00%) |