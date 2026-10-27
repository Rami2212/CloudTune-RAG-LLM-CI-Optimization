# Automated scenario experiments

Run `scripts/run_scenario_batch.py` for all ten blocked patterns. Use the same `.env`, GitHub permissions and pinned OpenRouter free model as the main batch. Commands are in [RUN_SCENARIO_COMMANDS.md](../RUN_SCENARIO_COMMANDS.md).

The runner reads `research-data/pattern_repo_candidates.csv` in its original order. It visits only the ten supported patterns, keeping original row positions. `--start-at`, `--limit`, `--pattern`, `--batch-id`, `--list` and `--rerun` work like the main batch. `--limit` counts visited candidates, not an ending row number. Filtering with `--pattern` uses positions within that filtered selection, as in the main script. A changed CSV selection requires a new batch ID. The model is not part of batch identity: change `OPENROUTER_MODEL` and resume the same batch. Existing experiment cases keep their saved model; new or rerun cases use the model from `.env`. Each result records the model used.

For each candidate it creates a dedicated `ct-scenario-...` fork, saves the source commit/tree/workflows and pattern, and disables inherited workflows in that dedicated fork. Isolated branches contain a controlled fixture with no source-code execution or third-party actions. Existing forks returned instead of the requested dedicated fork are preserved and that candidate is rejected.

Each experiment runs **three baseline scenario repeats**, asks the free LLM to apply **only the selected mechanism**, validates its allowed changes, then runs **three optimized repeats**. A repeat can include several workflow runs or a deliberate no-run observation. Expected failures and cancellations pass only when the scenario assertions match. An unexpected result stops that candidate. One completed scenario experiment per pattern stops further candidates for that pattern, including after resuming. Forks created by the batch are deleted after completion or a definitive failure. Pending events, uncertain pushes, unavailable LLM service and failed cleanup pause the batch and retain its evidence.

| Pattern | Baseline | Optimized assertions |
|---|---|---|
| Fail fast | One matrix cell intentionally fails; both workers finish. A separate healthy matrix passes. | Only `strategy.fail-fast` changes. Both workers are canceled after the intentional failure. The healthy matrix still passes. |
| Cancel stale | Old/new revisions and an isolated branch all finish. | Workflow/branch-scoped concurrency cancels the old revision. New revision and isolated branch finish. Actual job timestamps must prove overlap at the new event. |
| Skip workflow | Source controls and explicitly dispensable documentation pushes run. | The LLM changes a commit policy to append `[skip ci]` only to dispensable commits. Source controls still run. Documentation push has no matching run within the observation window. |
| Path filter | Source, documentation, config and mixed changes all run. | The LLM adds watched paths for source, config and workflows. Documentation-only change has no matching run within the window. Source, config and mixed controls still pass. |
| Pause failing schedules | Replay every scheduled attempt. | Pause after two consecutive failures, record a synthetic owner notification, suppress subsequent ticks, and resume after an explicit owner reset. A success resets the failure counter. |
| Idle schedules | Replay every timer tick. | Build the initial inputs, suppress unchanged inputs and generated commits, resume for source changes and external dependency changes. |
| Previously failed job first | Replay jobs in declared order on a single worker. | Prioritize the previously failing job and its prerequisite closure. Check repeated failure, recovery, and producer/consumer artifact dependencies. Every unrelated job still runs; measure early feedback separately from work. |
| Build priority | Replay a FIFO build queue. | Prefer urgent ready builds and age waiting builds. Check a queue without contention, urgent wait under contention, no dropped builds, and maximum wait. |
| Build selection | Execute all chronological build records. | Select using the visible change and last executed outcome. Skipped outcomes remain hidden. Report savings and missed failures together, including a documentation change with an external setup failure. |
| Duration prediction | Predict using the mean of past build durations. | Use past feature-specific means. Walk forward chronologically, predicting before observing each outcome. Measure MAE on records after the training prefix; execution work remains unchanged. |

The six added scenarios are **synthetic service-policy replays**, executed by a Python engine inside a successful hosted workflow. They exercise logical schedules and queues rather than modifying GitHub's scheduler. The LLM edits only `before_policy.yml` into `after_policy.yml`; the runner validates the exact allowed policy, embeds it in `after.yml`, and retains both the policy diff and `workflow_change.diff`. All three repeat inputs and the standalone engine are frozen under `source/`. Repeats use distinct duration scales. No source repository history is used to train these synthetic scenarios.

For replays, `replays/<arm>-<repeat>.json` stores inputs, policy, chronological decisions, assertions, simulated metrics, engine/input hashes, and the hosted run ID. The trace is a local deterministic reproduction of the exact hosted fixture; GitHub run/job success attests that the same hosted engine passed its assertions. Actual hosted job runtime measures replay overhead. Simulated work, failure-feedback latency, queue waits, missed failures, and prediction error are separate logical metrics. `experiment_runs.csv`, `run_records.json`, `case.json`, and `REPORT.md` retain results in the existing scenario experiment directory.

A passing build-selection scenario intentionally records a missed failure. This demonstrates the policy's risk; its case is marked `safe_for_repository_use: false`. Duration prediction reports held-out error and makes no direct speedup claim. Notifications, recovery, cron suppression, queue fairness and prediction accuracy still need evaluation with real service integration and repository history before applying these policies to a repository.

Explicit skipping is a commit-message policy, so that pattern keeps the fixture workflow unchanged and saves separate `before_policy.yml` and `after_policy.yml` files. Its diff describes the policy change.

Results are **controlled scenario evidence**. These tests establish cancellation/filter/skip behavior on a synthetic workload; their timings measure that workload. They do not establish an optimization benefit or required-check safety for the source repository. Actual branch protection and merge requirements remain an applicability review. GitHub can leave required checks pending when workflows are skipped: [GitHub documentation](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/skip-workflow-runs).

No-run evidence requires a complete observation window, successful API queries, a final boundary query, and successful controls before and after. API failures cannot count as suppression. A delayed event after the window remains possible. Interruption restarts the full observation window. Cancellation tests need capacity for at least two simultaneous hosted jobs; insufficient overlap cannot pass. Job timeouts bound fixture workloads to five minutes.

Push intents and commit identities are saved before publishing. Resuming checks the actual branch and collects the same event instead of resending an uncertain push. If a ref update remains uncertain and the branch does not point at the saved commit, the runner pauses for inspection. Successful repeats are reused on resume. `--rerun` creates a new experiment generation and replaces that row's batch summary while retaining prior evidence.

Storage:

- `research-data/batches/scenario-three-runs-v1/`: frozen selection/settings/configs, resumable batch state, API ledger, `batch_results.csv`.
- `research-data/scenario-experiments/<experiment_id>/`: original source evidence, fixture `before.yml`/`after.yml`, policy files when applicable, `change.diff`, LLM requests/responses, operation intents, raw runs/jobs/metrics, bounded no-run observations, assertions, `run_records.json`, `experiment_runs.csv`, `case.json`, `REPORT.md` and hashed artifact manifest.
- Scenario cases are labelled `controlled_pattern_scenario` with `real_repo_optimization_verified: false`; they are excluded from the ordinary experiment/RAG success catalogs.

Optional `.env` settings (frozen per batch):

```dotenv
SCENARIO_ABSENCE_SECONDS=120
SCENARIO_POLL_SECONDS=5
SCENARIO_WAIT_SECONDS=900
SCENARIO_WORK_SECONDS=90
```

The absence window must be at least 60 seconds. The waiting limit preserves unresolved events instead of canceling or redispatching them. No paid LLM fallback is used. Automated local protocol checks are in `tests/test_scenario_experiments.py`; real GitHub scenario runs consume Actions time when you launch the runner.
