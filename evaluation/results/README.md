# Evaluation results: complete research evidence

Commit all files in this directory, including batch configuration and identity,
raw checkpoints, frozen workflows, candidate patches, prompts, request bodies,
responses, and published summaries. The local `.gitignore` overrides parent
exclusions, including those for patches and logs.

Each batch stores configuration and published summaries in `<batch-id>/`.
Raw trial checkpoints live in `<batch-id>/<batch-id>-r0001/`, etc. Preserve these paths
for resumption. Published summaries alone cannot resume a trial.

Published evidence remains the analysis interface: `published/attempts.csv`,
`published/manifest.json`, `published/trials/rNNNN.json`, and the merged
`cohort/published/attempts_4000.csv` with its manifest.

Stop the runner before taking a consistent checkpoint snapshot. Review files
for credentials before committing. Stage the complete evidence with:

```powershell
git add evaluation/assignments evaluation/results
git status --short
git diff --cached --check
git diff --cached --stat
```

Keep interrupted trial checkpoints and backups; do not delete old results to
tidy up or use `git clean -fdx`. The CI-Cost installation remains outside this
folder in `.venv/ci-cost` and is installed separately by each teammate.

This complete-evidence policy replaces the former published-only allowlist.

Directory layout:

```text
results/
  eval-member-01/
    batch_config.json
    batch_identity.json
    published/
    eval-member-01-r0001/
      state.json
      repositories/
    eval-member-01-r0002/
```

Legacy raw trial folders must be moved intact into their batch folder before
continuing. Do not rewrite frozen identities or evaluator hashes to bypass
resume checks. Moving files preserves their bytes; a changed evaluator still
requires the existing explicit recovery/version procedure.
