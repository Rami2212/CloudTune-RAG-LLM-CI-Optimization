# CI Optimization Patterns

Patterns distilled from the studies below. The wording explains the idea; it does not claim each is a proven change for every repository.

| Pattern | Source | Meaning |
|---|---|---|
| P-LIT-GHA-CACHE — Cache dependency downloads | S01 §4.2.1 | Reuse downloaded packages between runs. |
| P-LIT-FAIL-FAST — Cancel remaining matrix jobs after failure | S01 §4.2.2 | Stop other matrix jobs after a failure when their results are no longer needed. |
| P-LIT-CANCEL-STALE — Cancel superseded runs | S01 §4.2.3 | Stop older runs when a newer commit makes them obsolete. |
| P-LIT-SKIP-WORKFLOW — Skip dispensable workflow runs | S01 §4.2.4 | Avoid starting a workflow when its checks are unnecessary. |
| P-LIT-CHANGE-FILTER — Filter triggers by changed paths | S01 §4.2.5 | Run only workflows relevant to changed files. |
| P-LIT-CUSTOM-TIMEOUT — Set a custom job timeout | S01 §4.2.6 | Stop jobs that exceed a suitable time limit. |
| P-LIT-FAIL-SCHEDULE — Pause failing scheduled workflows | S01 §4.3.1 | Temporarily stop schedules that keep failing. |
| P-LIT-IDLE-SCHEDULE — Suppress schedules during inactivity | S01 §4.3.2 | Avoid scheduled runs when the repository is inactive. |
| P-LIT-FAILED-JOB-FIRST — Run failing jobs first | S01 §4.3.3 | Start jobs with a history of failure earlier for faster feedback. |
| P-LIT-HISTORY-TIMEOUT — Set timeouts from successful-run history | S01 §4.3.4 | Use past successful durations to choose timeout values. |
| P-LIT-PRIORITIZE — Prioritize tests for early feedback | S02 §V.A.1, §V.B | Run tests likely to fail earlier. |
| P-LIT-BUILD-PRIORITY — Prioritize queued builds | S02 §V.A.2, §V.B | Order waiting builds to surface failures sooner. |
| P-LIT-SELECT — Select tests using change dependencies | S02 §IV.A.1, §IV.C | Run tests related to the changed code. |
| P-LIT-BUILD-SELECT — Select builds using change or outcome predictions | S02 §IV.A.2, §IV.B.2 | Choose builds to run based on changes or predicted outcomes. |
| P-LIT-BAZEL-PARALLEL — Tune Bazel parallelism | S03 §§3.2.2, 4.2 | Adjust concurrent build work to suit available resources. |
| P-LIT-BAZEL-INCREMENTAL — Cache Bazel build results | S03 §§3.2.3, 4.3 | Reuse valid outputs from earlier builds. |
| P-LIT-BAZEL-DEPS — Evaluate dependency-cache overhead | S03 §§3.2.3, 4.3 | Check whether dependency caching saves more time than it costs. |
| P-LIT-ENV-CACHE — Reuse validated build environments | S04 §§4.1, 6.3 | Cache prepared environments to avoid setting them up again. |
| P-LIT-UNAFFECTED-STEPS — Skip steps using traced dependencies | S04 §§4.2, 6.3 | Skip a step only when tracked inputs show it is unaffected. |
| P-LIT-SMELL-REPAIR — Repair evidenced configuration smells | S05 §4.3.3, Table 2 | Fix a documented inefficient build configuration. |
| P-LIT-DURATION-PREDICTION — Predict duration for investigation | S05 §4.3.3, Table 2 | Estimate build duration to help analysis; prediction alone does not speed up builds. |
| P-LIT-UNUSED-OUTPUTS — Remove genuinely unused outputs | S05 §4.3.3, Table 2 | Avoid producing outputs no later step consumes. |
| P-LIT-DISTRIBUTED-CACHE — Share cached build dependencies | S05 §4.3.3, Table 2 | Reuse dependencies through a shared cache. |
| P-LIT-CONFIG-REUSE — Reuse work across compatible configurations | S05 §4.3.3, Table 2 | Share completed work between configurations with compatible inputs. |
| P-LIT-UNUSED-DEP-SKIP — Evaluate skipping unused-dependency updates | S05 §4.3.3, Table 2 | Consider skipping updates that do not affect used dependencies, with correctness checks. |

## Sources

- **S01** — Bouzenia & Pradel (2024), [Resource Usage and Optimization Opportunities in Workflows of GitHub Actions](https://software-lab.org/publications/icse2024_workflows.pdf).
- **S02** — Jin & Servant (2021), [What helped, and what did not? An Evaluation of the Strategies to Improve Continuous Integration](https://arxiv.org/pdf/2102.06666).
- **S03** — Zheng, Adams & Hassan (2024), [Does Using Bazel Help Speed Up Continuous Integration Builds?](https://arxiv.org/pdf/2405.00796).
- **S04** — Gallaba et al. (2022), [Accelerating Continuous Integration by Caching Environments and Inferring Dependencies](https://rebels.cs.uwaterloo.ca/papers/tse2020_gallaba.pdf).
- **S05** — Aïdasso, Sayagh & Bordeleau (2025), [Build Optimization: A Systematic Literature Review](https://arxiv.org/pdf/2501.11940).
