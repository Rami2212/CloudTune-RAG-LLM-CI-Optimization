# Experiment batch-interactive-three--f2931297f9a8412a

Outcome: **inconclusive**

| Arm | Recorded measured runs | Usable successes | Median elapsed seconds | Median job runtime seconds |
|---|---:|---:|---:|---:|
| baseline | 3 | 3 | 246.0 | 239.0 |
| optimized | 2 | 1 | 264.0 | 260.0 |

Elapsed savings: -7.317073170731708%

- optimized: insufficient complete comparable successful measurements; failures retained
- Per-job success/failure/skipped outcomes differ
- Independent safety review pending
- Change-specific behavioral evidence pending (for caching: cold, warm, changed lockfile, invalidation)

All failed, canceled, skipped and warm-up attempts remain in the run records. Logs/artifact binaries are not downloaded; raw API evidence includes run, job, step, and artifact metadata.
Timing uses run start to final job completion. Runner runtime is summed across jobs; it is not billed usage.
Runs are sequential baseline then optimized; environmental drift and unverified cache state remain limitations.
