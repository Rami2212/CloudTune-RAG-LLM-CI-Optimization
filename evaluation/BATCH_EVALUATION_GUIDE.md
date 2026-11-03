# CloudTune held-out A/B/C evaluation — four-member batch guide

**Windows PowerShell only.** This describes the held-out 4,000-row evaluation,
not the separate RAG training-pattern batch. Run development-only smoke tests
before freezing the held-out study. Do not use held-out outcomes to tune the
optimizer, choose repositories, or relax the validator.

## Fresh-clone reproducibility for every team member

Protocol v3 admits an optimizer's `NO_CHANGE` outcome as an unchanged arm only
when the original workflow passes baseline syntax and safety validation. The
arm runs the original bytes and remains labeled `NO_CHANGE`, with
`descriptive_zero_change` in its statistics. This is not evidence that an
optimization was applied. Generated candidates still require `PASS`; failed or
review-required candidates never fall back to the original automatically.

Use a new batch ID after upgrading from v2; its immutable checkpoints cannot
be resumed under v3. Keep v2 and v3 results separate. Validation console output
now includes admission and rejection reasons. Preflight itself creates no forks
and dispatches no hosted workflows.

Protocol v4 additionally removes every unrelated `.github/workflows/*.yml`
or `.yaml` file from both the research fork's default branch and the common
pinned trial tree. Actions is disabled during default-branch registration.
All A/B/C arms inherit the same removals; source files and the selected test
workflow are preserved. The upstream repository is never modified.

For a v3 checkpoint that stopped before harness preparation (no registration
intent, arm branches, pending dispatch, or measurements), recover explicitly:

```powershell
.\.venv\Scripts\python.exe -m scripts.upgrade_unstarted_evaluation --evaluation-id eval-member-01-r0005
```

Recovery saves the original ledger and records the implementation upgrade. It
refuses prepared or dispatched trials, which must retain their frozen evaluator.
Then resume the same batch command. Do not combine measured v3 and v4 trials.

Each member can reproduce the installation and evaluator from a **separate
Windows workstation**, using the same pinned CloudTune Git commit and the
same 4,000-row source/assignment hashes. New machines need no pre-existing
CI-Cost installation or trial results. Git, Python 3.11+, Node.js 20+ with npm,
and `actionlint.exe` on PATH are required; install the Windows release of
actionlint from https://github.com/rhysd/actionlint/releases if it is missing.

```powershell
git clone --branch feature/evaluation-pipeline https://github.com/Rami2212/CloudTune-RAG-LLM-CI-Optimization.git
Set-Location .\CloudTune-RAG-LLM-CI-Optimization
git rev-parse HEAD
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-rag.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m scripts.prepare_evaluation_workspace
```

Each person fills in **their own** GitHub/OpenRouter credentials privately in
`.env`; use authorized access to the **same frozen, populated Supabase corpus**
without retraining or modifying it. Never commit or send `.env`, tokens, or raw
provider responses to teammates. Agree on the same free model and token ceiling
before collecting comparable measurements. Select one `--member` from 1–4 and
verify `evaluation/assignments/manifest.json` is identical across clones.
The remainder of this guide contains the setup verification and run commands.

The main 4,000-row cohort has **one assignment per member**. Independent
repetitions of an already evaluated repository are separate experiments: give
them fresh, explicit `--batch-id` values and report them separately, **not** as
additional rows in the primary four-member merge. To restart an _interrupted_
experiment, however, always reuse its existing batch ID and raw checkpoints.
Resetting results is appropriate only when previous trials are abandoned or
completely settled; see [results reset](results/README.md#intentional-fresh-reset-all-platforms).

## 1. Fixed and reproducible assignments

| Member | Dataset                                | Source rows | Default batch ID |
| ------ | -------------------------------------- | ----------- | ---------------- |
| 1      | `evaluation/assignments/member_01.csv` | 1–1000      | `eval-member-01` |
| 2      | `evaluation/assignments/member_02.csv` | 1001–2000   | `eval-member-02` |
| 3      | `evaluation/assignments/member_03.csv` | 2001–3000   | `eval-member-03` |
| 4      | `evaluation/assignments/member_04.csv` | 3001–4000   | `eval-member-04` |

All 4,000 rows remain in the denominator, including screened-out, rejected,
failed, and no-change cases. The builder never reshuffles or overwrites the
source CSV. It also records the source/partition SHA-256 hashes.

```powershell
.\.venv\Scripts\python.exe -m evaluation.prepare_evaluation_assignments
```

Commit the four generated CSVs and `evaluation/assignments/manifest.json`
before any held-out trial so every member uses the identical assignments.

## 2. Install requirements once on each Windows workstation

```powershell
git switch feature/evaluation-pipeline
git pull --ff-only
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-rag.txt

node --version
npm --version
git --version
actionlint --version

.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Use a supported Python version from the existing project guide. Keep the same
reviewed code revision throughout the research batch. The pinned CI-Cost tool
is compiled **once locally from its reviewed source**, not in the candidate
repositories. Only GitHub Actions on research-owned candidate forks executes
target CI. Ensure compiled CI-Cost tests actually execute, rather than skip:

```powershell
# Remove any old per-session override pointing at a version-suffixed directory.
Remove-Item Env:CI_COST_DIR -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m evaluation.third_party.ci_cost.setup
.\.venv\Scripts\python.exe -m evaluation.third_party.ci_cost.setup --verify
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_ci_cost_source_fixes.py -v
```

CI-Cost is installed to `.venv/ci-cost` on **each machine**, not into results.
This optional explicit setup verifies the compiled-tool tests without skips;
normal preflight also installs the tool automatically when first needed.
Keep the `source_fix_revision` recorded in evaluation JSON unchanged: it is the
versioned research method, not a local directory name. If `.env` contains an
old `CI_COST_DIR` setting, remove it or point it at the same location.

Keep your existing `.env`; if it does not exist, create a private one:

```powershell
Copy-Item .env.example .env
```

Configure your own authorized research account and valid credentials:

```dotenv
GITHUB_USERNAME=YOUR_OWN_RESEARCH_ACCOUNT
GITHUB_TOKEN=YOUR_AUTHORIZED_GITHUB_TOKEN
OPENROUTER_API_KEY=YOUR_PRIVATE_OPENROUTER_KEY
OPENROUTER_MODEL=google/gemma-4-26b-a4b-it:free
OPENROUTER_MAX_TOKENS=24000
SUPABASE_URL=YOUR_EXISTING_PROJECT_URL
SUPABASE_SECRET_KEY=YOUR_SERVER_SECRET
CLOUDTUNE_AUTO_DELETE_FORKS=false
```

The member runner requires explicit fork retention for research inspection.
This can leave many retained forks; check your account quotas and plan manual
cleanup _after_ review. Never expose secrets or give target CI jobs research
credentials. The model and token limit come from `.env`, not the stale model
fields in an older JSON template; an exported process environment variable
may override `.env`. A model change within a batch is rejected by the batch
identity guard to avoid mixing trial protocols.

## 3. One member, one command, one repository at a time

Preview member 1's repository order without any GitHub requests or dispatch:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_evaluation_batch --member 1 --list
```

Run the no-fork, no-dispatch **preflight only** mode:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_evaluation_batch --member 1 --preflight-only
```

After successful development smoke tests and protocol review, start hosted
three-arm trials for fully admitted repositories:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_evaluation_batch --member 1 --run
```

For members 2–4, change only `--member` to 2, 3, or 4. The runner processes
**one selected row per child controller invocation**; the existing controller
still caps an individual invocation at 100 rows but is always called with
`--limit 1`. A full assignment of 1,000 is therefore processed sequentially
without altering the controller. Expect at most three measured GitHub Actions
runs per admitted arm, with queue time excluded from execution metrics.

To process at most five _new_ rows in the current invocation:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_evaluation_batch --member 1 --run --max-repositories 5
```

### Custom batch ID (optional)

Members are assigned unique default IDs automatically (`eval-member-01` etc.).
Use `--batch-id` to give a **different** ID to a separate attempt/generation:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_evaluation_batch --member 1 --batch-id isharas-heldout-v1 --run
```

That ID determines the published folder:
`evaluation/results/isharas-heldout-v1/published/`. Each row is independently
checkpointed under `evaluation/results/isharas-heldout-v1-r0001/`, `...-r0002/`,
and so on. Keep the same batch ID on every restart, including `--publish-only`.
Do **not** switch to a new batch ID just to bypass an unresolved run; that
would create a distinct experiment and risk double-running an upstream repo.

## 4. Resume the **last stopped state** exactly

The batch-pattern design (`scripts/run_pattern_batch.py`) stores item status,
revisits the first unfinished row, and skips finalized work. The new runner
reuses that recovery behavior but delegates real run/dispatch checkpoints to
`evaluation/fork_pipeline.py`, rather than duplicating GitHub dispatch logic.

Stop with Ctrl+C. Restart with the **same command and batch ID**:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_evaluation_batch --member 1 --run
```

Example: rows 1–385 are finalized, row 386 has a queued A/B/C run. The runner
skips rows 1–385 and resumes `eval-member-01-r0386`, restoring its previously
recorded GitHub run ID, arm measurements, frozen source, and validation. It
never intentionally dispatches an already-pending run again. Once that repo
finalizes it proceeds to row 387. No `--start-at` or `--rerun` is necessary.

OpenRouter HTTP 429/503/timeout pauses the **same** unfinished repository; it
is not treated as a completed failure. Manually inspect `llm_error.json` and
restart only when ready. Uncertain GitHub dispatch/fork cleanup must be
reconciled, not bypassed. If a hard-killed controller left `.controller.lock`,
first confirm no worker is alive before removing only the stale lock. The
sequential runner also uses a local `evaluation/results/<batch-id>/.batch.lock`
to prevent two controllers from processing one member simultaneously. After a
hard kill, verify that _neither_ the parent batch runner nor the child fork
controller is running before removing a stale lock file; never delete
`state.json` or any `repositories/` folder.

The batch identity freezes the CSV hash, model, token limit, controller
configuration, fork-retention flag, and wrapper source. An incompatible change
fails before processing another repository. Existing per-repository state also
freezes the evaluator implementation/config digest.

## 5. Commit-ready evidence saved by batch ID

All raw trials and published summaries are grouped under their batch ID:

```text
evaluation/results/
  eval-member-01/
    batch_identity.json         # immutable operational identity
    batch_config.json           # controller template
    published/
      attempts.csv              # Git-eligible: 1,000 source rows/statuses
      manifest.json             # Git-eligible: assignment SHA and counts
      trials/
        r0386.json              # Git-eligible: allowlisted provenance and metrics
    eval-member-01-r0386/
      state.json                # live checkpoint, preserve for resumption
      repositories/             # frozen source, prompts, API responses
  cohort/published/
    attempts_4000.csv           # Git-eligible: checked union of four members
    manifest.json
```

Published trial JSON contains explicit pinned workflow hashes, validation
verdict/reason codes, CI run IDs, job timings, conclusions, and measured run
statistics. It excludes API tokens, raw prompts, request bodies, original
workflow source, and arbitrary raw GitHub response files. Published summaries
**are not sufficient to resume** a pending trial; raw checkpoint directories
must be preserved and backed up alongside the summaries.

Refresh the published evidence without running CI or calling APIs:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_evaluation_batch --member 1 --publish-only
```

For a custom batch ID:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_evaluation_batch --member 1 --batch-id isharas-heldout-v1 --publish-only
```

Stage all results, including raw checkpoints:

```powershell
git add evaluation/assignments evaluation/results
git status --short
git diff --cached --check
git diff --cached --stat
```

The results `.gitignore` permits all artifacts, including patches and logs.
Review file contents before committing. Do not delete old checkpoint evidence.

## 6. Combine four member result batches

Once each member commits their published outputs, run:

```powershell
.\.venv\Scripts\python.exe -m scripts.merge_evaluation_results
```

For four custom IDs (in member order):

```powershell
.\.venv\Scripts\python.exe -m scripts.merge_evaluation_results --batch-ids member1-v1 member2-v1 member3-v1 member4-v1
```

The merge refuses duplicate/omitted repos, wrong member assignments,
incorrect source positions, incorrect batch IDs, or mismatched assignment
hashes. Its `cohort/published/attempts_4000.csv` contains one row for **each
of the original 4,000 repositories**, whether completed or not. The manifest
reports status counts; it does not invent savings for missing measurements.

## 7. Safety and limits

- `--preflight-only` never creates a fork; `--run` requires both optimized arms
  to pass independent admission before hosted A/B/C execution.
- No local `npm test` or target-repository builds are used to measure CI time.
- The original repository is read-only; hosted execution happens on the
  member's research-owned candidate fork, never CloudTune's GitHub Actions.
- The runner stops rather than forging success or skipping an unresolved repo.
- The three-repeat protocol, evaluator policy and dataset identity are unchanged.
- Large matrix workflows can consume substantial runner minutes; review the
  budget before launching the full cohort, particularly Windows/macOS jobs.
- No existing trial folder is renamed/deleted, and older evidence remains
  separate from new batch IDs.
