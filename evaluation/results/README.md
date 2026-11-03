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
  .tools/                           # IGNORE: compiled ci-cost checkout
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
