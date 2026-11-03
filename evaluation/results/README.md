# Evaluation results: frozen checkpoints and commit-ready evidence

The held-out dataset has 4,000 repository rows, divided into four fixed
1,000-row assignments. The sequential runner gives each member a unique batch
ID automatically, with a supported `--batch-id` override.

## Files and Git rules

```text
evaluation/results/
  .gitignore
  README.md
  eval-member-01/
    .batch.lock                     # IGNORE: protects batch from parallel runners
    batch_config.json               # IGNORE: frozen controller template
    batch_identity.json             # IGNORE: model/config/assignment identity
    published/
      attempts.csv                  # TRACK: all 1,000 assigned rows
      manifest.json                 # TRACK: assigned hash and status counts
      trials/
        r0001.json                  # TRACK: allowlisted evidence, if attempted
        r0002.json
  eval-member-01-r0001/             # IGNORE: RAW per-repo checkpoint
    state.json                      #   never stage or delete
    repositories/                   #   frozen source, candidate and raw jobs
    fork_report.json
  cohort/published/
    attempts_4000.csv               # TRACK: checked merge of four assignments
    manifest.json                   # TRACK: cohort identity and status counts
```

Custom `--batch-id example-id` stores commit-ready evidence in
`evaluation/results/example-id/published/`, with raw trial checkpoints in
`evaluation/results/example-id-r0001/`, etc. The existing controller requires
its raw folder directly under `evaluation/results/<evaluation_id>/`; do not
move or rename it. A Git commit of published metadata **cannot** resume a
running trial; preserve raw checkpoints and backups privately.

Only files named `published/attempts.csv`, `published/manifest.json`,
`published/attempts_4000.csv` and `published/trials/rNNNN.json` are allowed by
`.gitignore`. Source files, prompts, provider responses, API blobs, tokens,
`batch_identity.json`, and `state.json` remain ignored. The exported trial JSON
contains only explicit source/provenance identifiers, safety verdict codes,
GitHub run IDs and numeric job timings. Review content before committing.

The compiled CI-Cost checkout is stored in `.venv/ci-cost` outside this folder;
repository-wide `.gitignore` already excludes it. Every teammate installs
this tool locally, using the same pinned source-fix revision.

## Windows PowerShell — publish and commit

```powershell
# Publish member 1 without dispatching GitHub Actions or making API calls.
.\.venv\Scripts\python.exe -m scripts.run_evaluation_batch --member 1 --publish-only

# Inspect the exact files Git would stage.
git add evaluation/assignments evaluation/results/.gitignore evaluation/results/README.md evaluation/results/eval-member-01/published
git status --short
git diff --cached --check
git diff --cached --stat
```

For custom batch IDs, replace `eval-member-01` with your chosen ID. Do not use
`git add -f` on raw results. Do not delete old trial folders or archived
checkpoints. To transfer unfinished work between machines, privately transfer
all raw result folders for that batch before restarting from the same state.

See [Batch Evaluation Guide](../BATCH_EVALUATION_GUIDE.md) for the full
PowerShell setup, run, stop/resume, and four-member merge process.

## Intentional fresh reset (all platforms)

Reset only after checking that no GitHub Actions jobs are pending or
running, and no research forks or raw checkpoints still require
investigation. The reset cannot cancel jobs or remove GitHub forks.
Never reset merely to resume an interrupted batch: use its same ID.

The workspace helper first verifies the frozen held-out CSV SHA-256,
checks existing assignments, and refuses to delete previously tracked
published evidence. It preserves this README and the results .gitignore.
Without `--confirm-reset` it only previews candidates and prepares
the four deterministic member CSVs plus their shared manifest.

Windows PowerShell (from the repository root):

```powershell
.\.venv\Scripts\python.exe -m scripts.prepare_evaluation_workspace --reset-results --reset-ci-cost
# Only after reviewing the preview and resolving external CI/forks:
.\.venv\Scripts\python.exe -m scripts.prepare_evaluation_workspace --reset-results --reset-ci-cost --confirm-reset
```

Linux Bash:

```bash
./.venv/bin/python -m scripts.prepare_evaluation_workspace --reset-results --reset-ci-cost
# Only after reviewing the preview and resolving external CI/forks:
./.venv/bin/python -m scripts.prepare_evaluation_workspace --reset-results --reset-ci-cost --confirm-reset
```

The unversioned `.venv/ci-cost` is installed again from the pinned
upstream source when Arm B next requires it. If `CI_COST_DIR` was set
to an old version-suffixed location, remove that variable from your
terminal and private `.env` before starting a fresh evaluation.

Normal setup (without resetting anything) also generates/verifies
all five assignment files:

```powershell
.\.venv\Scripts\python.exe -m scripts.prepare_evaluation_workspace
```

Commit `evaluation/assignments/member_01.csv` through `member_04.csv`
and `evaluation/assignments/manifest.json` before running a shared
4,000-repository cohort. The batch runner already publishes only the
Git-eligible summaries under `<batch-id>/published/`; raw checkpoint
directories remain ignored by Git and are needed for safe resumption.

## Publishing the new four-member, 4,000-repository study

The existing runner publishes allowlisted results for **any** valid batch ID:
`evaluation/results/<batch-id>/published/attempts.csv`, `manifest.json`,
and `trials/r0001.json` through `trials/r1000.json` where available. The
four-member merge publishes `cohort/published/attempts_4000.csv` and its
manifest. These are the study's commit-ready status, provenance, and CI
measurements; the ignored raw GitHub API/request/checkpoint state is not.

Before staging, use the preview-first reset command above to inspect and
remove **abandoned** old `.tools/ci-cost`, `dev-fork-*`,
`cloudtune-abc-preparation-pilot-*`, and temporary files **only when no
active jobs or recovery evidence need them**. The reset retains this README
and `.gitignore`; it does not delete the committed 4,000-row dataset or the
four assignment CSVs. It cannot cancel GitHub Actions or remove forks.

Stage the four generated CSVs and all eligible published study results without
force-adding ignored data (same Git commands in PowerShell and Bash):

```bash
git add evaluation/assignments evaluation/results
git diff --cached --check
git diff --cached --stat
git diff --cached --name-only
```

Inspect staged filenames and content before committing. The Git allowlist
accepts any independent `--batch-id` automatically, but does not make raw
checkpoints committable. `git status --short --ignored evaluation/results`
can show `!!` for still-ignored local raw data; that is expected until
intentionally removed. Do not use `git clean -fdx` for this task.
