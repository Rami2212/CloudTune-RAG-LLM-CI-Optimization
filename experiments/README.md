# Fork CI experiments

## Interactive pattern/repository batch

Both runners use `research-data/zenodo_20340547/pattern_repo_candidates_20.csv`: 25 patterns with 20 distinct repositories each. They try candidates until two distinct repositories per supported pattern have validated pattern changes and three passing baseline and optimized measurements. Remaining candidates for that pattern are skipped, including on resume. Performance gain and independent safety review remain separate report outcomes. Scenario examples validate controlled fixtures, not original repository CI savings. Failed CI or preparation attempts advance to the next candidate. Uncertain runs, unavailable LLM service, and pending fork cleanup still pause the batch. `pattern_progress.csv` records each pattern's count and target; a target is not guaranteed if candidates fail. Results retain original CSV positions, with inclusive `--start-at 20 --stop-at 100` selecting rows 20 through 100. Use `--rerun` to replace a finished row's summary while preserving its previous experiment directory.

Changing the model, token budget, candidate selection, or scenario settings keeps the same batch ID. Selection and scenario settings revisions are archived. An existing attempt keeps its frozen configuration; new and rerun attempts use current settings.

Fill the local `.env` file in the project root:

```dotenv
GITHUB_USERNAME=your-github-login
GITHUB_TOKEN=your-fork-write-token
OPENROUTER_API_KEY=your-openrouter-key
OPENROUTER_MODEL=recursive/flint-v1.0:free
OPENROUTER_MAX_TOKENS=24000
```

The actual `.env` is gitignored; `.env.example` is the reusable template. Credentials already exported in the shell take precedence. Tokens are loaded locally, never placed in experiment configs or prompts. The batch token needs **Administration: write**, **Contents: read/write**, **Actions: write**, and **Workflows: write** on experiment forks. Administration write lets the batch enable Actions and delete forks it created; Workflows write lets it add the dispatch trigger. Ensure the token can access newly created forks; a token restricted to selected repositories may need its repository selection updated. No additional dotenv/LLM SDK package is required.

Run from the project root:

```powershell
.\.venv\Scripts\python.exe scripts\run_pattern_batch.py
```

For each row in the selected dataset, the terminal shows the selected pattern, source repository link and fork URL under `GITHUB_USERNAME`. The script reuses an existing fork or creates one automatically under your account, then waits up to five minutes for its Git objects. It enables Actions and selects an eligible test/build workflow. If that workflow lacks `workflow_dispatch`, the script adds that trigger to the fork's default branch before collecting the baseline. No terminal setup prompt is needed. The batch stops and records a preparation failure if GitHub rejects a required change.

Fork creation requests are saved before submission. If a response is lost, restarting checks the saved target without resending the creation request; an unrelated repository with the same name is never reused.

After preparation, the runner verifies fork-family membership and push access, chooses the eligible CI workflow, and freezes the source snapshot. It executes **three baseline runs, one selected-pattern OpenRouter proposal, and three comparison runs**. There are **no warmups**, with a maximum of **six CI dispatches per case**. Required job display names are inferred from the first baseline run and then frozen; this observation is recorded separately from an owner-approved required-check policy. For a workflow that lacked manual dispatch, the only preparation edit is adding `workflow_dispatch` before the baseline snapshot; measured optimization changes remain constrained to the selected pattern.

The batch uses the fork's current default-branch workflow and does not scan repository history. Each attempt still pins its source commit so its baseline and optimized measurements compare the same code.

Collect this historical evidence by itself, without forking or calling an LLM:

```powershell
.\.venv\Scripts\python.exe scripts\collect_ci_history.py --pattern P-LIT-GHA-CACHE --start-at 1 --limit 5
```

The command reads the candidate CSV, scans up to 500 workflow-changing commits per file, and archives exact-commit Actions runs when available. Output is under `research-data/historical-workflows/<pattern>/<owner>__<repo>/<workflow>/`. It is safe to rerun; completed manifests are reused. `--start-at` is one-based in the filtered candidate list.

After each finished experiment, the runner deletes the fork if this batch created it. Existing forks are kept. Experiment evidence remains saved locally. Fork deletion requires Administration write permission; if deletion fails, the batch pauses and retries cleanup when resumed.

The optimizer receives just the current pattern record, original workflow, baseline measurements and relevant collected manifests. It must implement the selected pattern even if the performance benefit is uncertain. If it returns `NO_CHANGE`, an incomplete response, or unchanged workflow, the runner retries once with a stricter implementation request; it rejects the case if that still produces no valid change. For caching, it uses lockfiles when available and otherwise keys narrowly on checked-in install declarations plus the runner environment. All original install and test commands still run on cache hits. Each arm runs **up to three times** and stops immediately after its first failed CI run, failed required check, or invalid run; the batch records that repo as failed, cleans up a batch-created fork, and continues to the next candidate. The runner cannot guarantee external CI services will always pass.

The model defaults to the pinned code-focused free model `recursive/flint-v1.0:free`; you can set another specific model ID ending in `:free`. The request sets prompt/completion maximum prices to zero, with no paid-model fallback. Free capacity and quota errors pause the batch, preserving completed baseline runs. The actual response model, usage, latency, exact prompt, raw response and rationale are archived.

Cache and timeout proposals have additional validators restricting the type of edit to the selected mechanism. A changed workflow for another mechanism needs its own validator; a rejected proposal is recorded and the batch advances. A candidate that passes CI can still produce no speedup; the experiment records that result. Safety/behavior review is required before labeling measured changes as safe; no manual review prompt interrupts the batch.

Event/history patterns that cannot be evaluated by sequential manual dispatch (path filters, cancellation, schedule suppression, fail-fast, queue/build selection and prediction) are recorded as **blocked** and skipped before requesting a fork. A failing baseline or rejected proposal retains all available results and advances to the next row. An uncertain/active pending dispatch pauses the batch to avoid duplicate or overlapping experiments. Failures are not silently replaced with new green runs.

Preview without tokens, prompts or API calls:

```powershell
.\.venv\Scripts\python.exe scripts\run_pattern_batch.py --list --start-at 20 --limit 5
```

Start with one repository for a selected pattern:

```powershell
.\.venv\Scripts\python.exe scripts\run_pattern_batch.py --pattern P-LIT-GHA-CACHE --limit 1 --batch-id cache-pilot-001
```

Rerun the same command to resume unfinished cases; completed rows are skipped. `--start-at 20` begins with the 20th row in the selected CSV order (one-based); `--list --start-at 20 --limit 5` previews rows 20–24. Batch results keep this row position and are always written in source order, even when later positions run first. Use `--rerun --start-at 5 --limit 1` to rerun row 5: its batch summary is replaced by the latest result, while the old experiment evidence stays in its own folder. `--limit` caps rows visited from that starting position. You may increase `OPENROUTER_MAX_TOKENS` and append new cases to the same batch; already-created case configs keep their original token budget. To measure again from scratch or use a changed selection/model, use a new `--batch-id`. Pattern/repository pairs have separate case IDs, so reusing a fork for another pattern always starts from the pinned default-branch workflow, not the previous optimized branch. Preparation changes to the default branch must be finished before each source snapshot is collected.

Batch progress and per-row reasons are in `research-data/batches/<batch_id>/batch_results.csv`; frozen CSV selection, generated case configurations and resumable state are alongside it. Each experiment's detailed evidence remains in `research-data/experiments/<experiment_id>/`, and global indexes below are updated after each collected run/report. `llm_request.json`, `llm_response.json` and `llm_proposal.json` hold generation evidence. The reported three-run medians are pilot observations, with uncontrolled cache state and no statistical significance claim.

OpenRouter references: [Flint model](https://openrouter.ai/recursive/flint-v1.0:free), [chat completions](https://openrouter.ai/docs/api/api-reference/chat/send-chat-completion-request).

## Individual experiment commands

`scripts/run_ci_experiment.py` collects a pinned fork snapshot, measures the original CI workflow, proposes an optimization, measures the changed workflow at a new commit, and archives the evidence. The baseline workflow bytes are unchanged. The experiment uses two new `codex/ct-<experiment_id>-...` branches; both commits have the same parent source SHA and all non-target files must match.

## Set up one pilot

1. Use an **existing research-owned fork** with Actions enabled and token push permission. This runner does not create forks. Prepare the fork so the target is test/build CI, with no release, deploy, publish, secret-dependent or self-hosted jobs. The runner conservatively refuses these cases and refuses `workflow_run` listeners on the fork's default branch.
2. The selected workflow must already support `workflow_dispatch` at the pinned revision and on the fork's default branch. It must be registered and active. If a manual-run harness is needed, establish it in the fork **before** pinning the experimental baseline, and document that preparation. The runner never adds dispatch to a workflow and calls that the unchanged upstream baseline.
3. Copy `experiment.example.json` to a local config file. Set the fork, workflow, exact required **job display names**, source ref, and experiment ID. Include every required matrix expansion's display name. Default `HEAD` resolves to the fork default branch once, then the SHA is frozen. Use a fresh ID for another source revision or configuration.
4. Provide a token through `GITHUB_TOKEN` or `GH_TOKEN`, using your shell/session credential mechanism. The target fork needs Contents write, Actions write and permission to update workflow files (Workflows write where required by token type); reading public upstream repositories alone is insufficient. Keep token values out of config files and command history. PyYAML is the only Python dependency. Optional `actionlint` on PATH adds Actions syntax checking; its absence is recorded explicitly.

From the project root, run everything:

```powershell
.\.venv\Scripts\python.exe scripts\run_ci_experiment.py run --config experiments\my-pilot.json
```

Or use individual stages:

```powershell
.\.venv\Scripts\python.exe scripts\run_ci_experiment.py prepare --config experiments\my-pilot.json
.\.venv\Scripts\python.exe scripts\run_ci_experiment.py baseline --config experiments\my-pilot.json
.\.venv\Scripts\python.exe scripts\run_ci_experiment.py optimize --config experiments\my-pilot.json
.\.venv\Scripts\python.exe scripts\run_ci_experiment.py optimized --config experiments\my-pilot.json
.\.venv\Scripts\python.exe scripts\run_ci_experiment.py report --config experiments\my-pilot.json
```

`prepare` only reads GitHub and saves the source data. `baseline` and `optimized` write isolated branches and dispatch workflows, consuming GitHub runner time. The example plans up to three measured runs per arm, with a hard cap of six dispatch attempts; the batch stops that repo after the first unsuccessful attempt and advances. If configured, warmups are recorded separately and are not evidence of cache hits. Failures and cancellations are retained and never replaced with extra green runs. A failing baseline blocks optimization. Polling deadlines preserve the pending run and stop local waiting; they do not cancel a remote run. Set job timeouts in the prepared workflow if an execution-time cap is needed.

Commits include `[skip ci]` to suppress incidental push CI; the measured runs are explicit manual dispatches. The default branch is never changed, and branches remain for audit. A changed default branch or experiment branch stops further dispatches. Source commands and actions run remotely on GitHub, never in the local workspace. No actions are enabled automatically and no PRs are opened.

## Choose the optimization

The first automatic optimizer is `npm-cache`, for `P-LIT-GHA-CACHE`. It adds `cache: npm` and an explicit root lockfile path to existing `actions/setup-node@v3` through `@v6` steps, only when checkout precedes setup, npm ci follows it, and the job has no existing cache or non-root working directory. It retains all commands, actions, jobs, matrix definitions, triggers and permissions. Unsupported layouts are rejected instead of being run as unchanged optimizations.

For another applicable pattern, supply a complete candidate workflow:

```json
"optimizer": {"type": "candidate-file", "path": "candidate.yml"}
```

The path is relative to the config file. Set `pattern_id` to the matching ID in `knowledge/extracted_patterns.jsonl`. First complete `baseline` and `optimize`; inspect the saved diff and validation report. External proposals cannot alter the top-level trigger/permission configuration, job set, matrix, dependencies, runners, environment or shell-command steps. Timeout and action-step edits can be proposed, but require independent review of their behavior. A proposal that requires broader changes needs a dedicated scenario implementation.

Before executing an external proposal, save this review in the case directory, using the actual hash from `proposal.json`:

```json
{
  "diff_sha256": "EXACT_HASH_FROM_PROPOSAL",
  "reviewed_by": "reviewer-name",
  "verdict": "PASS",
  "rationale": "Explain why this exact change preserves the required checks.",
  "behavior_validation": {"status": "PENDING", "evidence_refs": []}
}
```

This file is `research-data/experiments/<experiment_id>/candidate_review.json`. For the automatic npm proposal, the bounded structural check permits the measurement stage; independent safety/behavior review is still required for a safe outcome label.

Manual dispatch timing cannot evaluate path filters, superseded-run cancellation, schedule suppression, queue prioritization, build selection, fail-fast scenarios or duration prediction. Those pattern IDs are rejected explicitly. The tool does not claim to implement all 25 paper mechanisms. A supplied proposal for a build-system pattern must express its change in the workflow while preserving protected commands; changes to application/build files require a separate runner extension.

## Stored evidence

```text
research-data/experiments/<experiment_id>/
  config.json                 # immutable normalized settings; never a token
  source/repository.json      # fork identity, permissions and parent family
  source/commit.json          # exact source SHA and tree
  source/tree.json            # complete Git tree, including file/blob identities
  source/pattern.json         # frozen pattern record
  source/default_*.json       # default-branch snapshot used by preflight
  source/files/...            # workflows and relevant manifests at the source SHA
  source/files_manifest.json  # hashes and explicit size/count omissions
  history/
    manifest.json             # detected transition, commit SHAs, evidence and historical run summaries
    before.yml                # workflow at the parent commit (empty if the workflow did not yet exist)
    after.yml                 # workflow at the commit that introduced the cache pattern
    change.diff               # workflow change across the introduction commit
    runs_<commit>/...         # archived original Actions runs, jobs and timing metrics when available
  before.yml                 # complete original workflow bytes
  after.yml                  # complete proposed workflow
  change.diff                # unified workflow diff
  optimization_request.json  # question, evidence, baseline runs and constraints
  proposal.json              # optimizer/version, hashes, structural verdict
  candidate_review.json      # independently supplied exact-diff assessment
  actionlint.txt             # generated only when actionlint is available
  baseline_tree.json         # remote arm tree; source equivalence checked
  optimized_tree.json
  runs/<run_id>-attempt-1/
    run.json                 # raw GitHub run metadata
    jobs.json                # raw jobs, runner labels and step statuses/times
    metrics.json             # normalized job/step metrics and required-check pass
    artifacts.json           # artifact metadata, not artifact binaries
  state.json                 # resumable canonical ledger, including pending dispatch
  events.jsonl               # phases and errors
  api_calls.jsonl            # API method/path/status/latency, no credentials
  run_records.json           # all measured and warmup outcomes
  experiment_runs.csv
  case.json                  # outcome, metrics, source, patch and run references
  REPORT.md
  artifact_manifest.json     # SHA-256 hashes of archived evidence at report time

research-data/runs/experiment_runs.csv        # index across runner case folders
research-data/knowledge/verified_cases.jsonl  # all case outcomes; admission tracked separately
research-data/analysis/per_repo_results.csv  # per-case, per-arm summaries
```

Every run includes the source and configuration SHA, pattern, arm, repetition, warmup flag, status/conclusion, required-check result, run ID/attempt, elapsed and summed job time. Raw jobs preserve each step's pass/fail/skipped status and timing. Metrics are in **seconds**. Elapsed time is run-start to final job completion; job runtime is the sum of parallel and sequential job durations. Initial queue delay is stored separately. Missing timestamps remain null; skipped/canceled jobs are not counted as fast successful builds. Runner runtime is not billing cost.

Context collection saves at most 100 relevant files of at most 2 MB each; omitted context files are listed, while the full Git tree is retained. It does not clone all application files or download stdout logs/artifact binaries. The interactive OpenRouter mode sends the selected pattern/workflow and limited manifest context to the configured free model. No existing `knowledge/examples/` literature illustration is overwritten.

The global indexes are regenerated from this runner's case folders. Treat those CSV/JSONL files as generated views, with per-case state/raw records as the source of truth. Local experiment data remains under the existing ignored `research-data/` directory.

## Resume and interpret results

Rerun the same command and config after interruption. Completed slots are not dispatched again. Before sending a dispatch, the runner durably records its intent and existing run IDs; ambiguous network failures are never retried as another POST. If a run is slow to appear, resume later. If concurrent manual dispatches caused ambiguity, attach the intended ID:

```powershell
.\.venv\Scripts\python.exe scripts\run_ci_experiment.py attach-run --config experiments\my-pilot.json --run-id 123456789
```

The run must match the workflow ID, branch, commit and event. An externally rerun attempt is archived and marked protocol-invalid; the runner itself creates new runs, never reruns an old revision to test a changed file. A `.lock` prevents simultaneous processes for the same case. After a hard process crash, confirm the old process has stopped before removing that one lock file. An explicitly rejected dispatch can leave an intent without a run; retain it and investigate rather than silently resending.

Reports remain `inconclusive` until there are the configured number of complete comparable successful measurements per arm (three in the batch), matching job/matrix outcomes, an exact-diff independent review and relevant behavioral evidence. To complete behavioral review, update `candidate_review.json` with `behavior_validation.status: PASS` and real `evidence_refs` for the change-specific scenarios, then rerun `report`. For caching, validate cold/warm behavior, changed lockfiles and invalidation separately. Merely setting the status is not validation; the references must identify evidence you actually collected.

`safe_success` additionally requires positive elapsed savings meeting the configured threshold. `safe_no_gain` preserves behavior but misses that threshold. Structural contract violations are `unsafe`; failures, missing data and unverified behavior remain `inconclusive` pending attribution. All outcomes remain in storage. Only development/pilot cases are supported here, and RAG admission remains a review step.

This initial protocol runs a baseline block followed by an optimized block. The report records possible environmental drift. Cache state is labeled `uncontrolled` because the GitHub jobs API does not establish cache-hit status; warmup runs are excluded from medians. Estimates are descriptive pilot medians, without confidence intervals or statistical-significance claims.

Implementation references: [workflow dispatch](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event), [run attempts and jobs](https://docs.github.com/en/rest/actions/workflow-jobs#list-jobs-for-a-workflow-run-attempt), [skipping push workflows](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/skip-workflow-runs).


