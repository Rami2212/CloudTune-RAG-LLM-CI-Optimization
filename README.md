# CloudTune-RAG-LLM-CI-Optimization

Data preparation, repository screening, literature patterns, and controlled CI experiments in existing forks.
The only candidate source is Bouzenia & Pradel, ICSE 2024,
*Resource Usage and Optimization Opportunities in Workflows of GitHub Actions*
(DOI: 10.1145/3597503.3623303).

## Run (PowerShell, Python 3.11+)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# Optional but recommended: supply a GitHub token through your environment.
# GITHUB_TOKEN needs only public repository/Actions read access.
.\.venv\Scripts\python.exe scripts/prepare_data.py --limit 5
```

The first run downloads the official `data_set.zip` release. It may be large.
Interrupted downloads retain `research-data/data_set.partial`; rerunning the
same command resumes from the saved byte offset when the server supports ranges.
Alternatively, download it from
[the official release](https://github.com/sola-st/github-workflow-resource-optimization/releases/tag/v1.0.0)
and run:

```powershell
.\.venv\Scripts\python.exe scripts/prepare_data.py --artifact C:\path\to\data_set.zip --limit 5
```

Only `all_repositories.csv` inside this archive supplies candidates. The tool
does not use the broader sampling lists cited by the paper or GitHub search.
If column detection fails, the error lists available columns; pass
`--repo-column COLUMN_NAME`. A supplied archive is assumed to be the official
download: its checksum is recorded for audit, not authenticated against a
publisher-provided checksum.

Each run creates a new timestamped directory under `research-data/`:

- `source_manifest.json`: paper, release URL, artifact/member hashes, selection policy.
- `repositories.csv`: eligibility summary and reason codes.
- `repo_context.jsonl`: source SHA, license, repository family, manifest paths,
  workflow hashes, triggers/jobs, risk flags and recent workflow run references.

## Eligibility interpretation

Archived/disabled repositories and repositories without Actions workflows are
excluded. Workflow inspection flags secrets, self-hosted runners, possible
deployment/publishing steps and build/test/lint hints. These are conservative
text heuristics, not proofs of workflow behavior. License uncertainty and
truncated trees require review. API failures remain `COLLECTION_ERROR`, never
silently excluded; any such failure produces a nonzero exit code.

All other candidates remain `REVIEW_REQUIRED`. Successful upstream history does
not establish fork reproducibility. Required checks, external services, baseline
execution, runtime budget and permissions still need verification. No workflow
is executed, fork created, or upstream repository modified.

The default first five sorted repositories are a convenience pilot, not a
representative randomized evaluation sample. Historical evidence is explicitly
limited to the first 100 repository runs. This initial collector does not yet
download manifests, job/step timing, logs, or create experimental outcome labels
and RAG knowledge. It deliberately does not export raw workflow contents or logs
to models. Keep the generated data local pending review for redistribution.

Network access is required. Rate limits and permission failures are recorded;
rerun into a fresh output directory after resolving them. Increase `--limit`
only after inspecting the pilot output and API usage.

## Run the experiments

1. Install Python packages if needed:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` (if you do not already have one) and fill in:

   ```text
   GITHUB_USERNAME=your-github-name
   GITHUB_TOKEN=your-fine-grained-token
   OPENROUTER_API_KEY=your-openrouter-key
   OPENROUTER_MODEL=recursive/flint-v1.0:free
   OPENROUTER_MAX_TOKENS=24000
   ```

   The GitHub token needs **Administration: write**, **Contents: read/write**, **Actions: write**, and **Workflows: write** for your forks. The batch enables Actions and adds `workflow_dispatch` to the selected workflow automatically. The OpenRouter key is created at [openrouter.ai/settings/keys](https://openrouter.ai/settings/keys). Keep real keys only in the ignored `.env` file.

3. Preview the repository order, then start the pipeline:

   ```powershell
   .\.venv\Scripts\python.exe scripts\run_pattern_batch.py --list --limit 5
   .\.venv\Scripts\python.exe scripts\run_pattern_batch.py
   ```

   To start from row 20 in the CSV, add `--start-at 20`. Combine it with `--limit 1` to run one row.

   To continue this batch with another model, change `OPENROUTER_MODEL` in `.env` and rerun the same command with the same `--batch-id`. Model choice does not change batch identity. Existing experiment cases keep their recorded model; new or `--rerun` cases use the selected model. The batch results include the model used for each repo.

4. The script creates or reuses your fork, enables Actions, and adds `workflow_dispatch` to an eligible test/build workflow when needed. It then runs the prepared workflow three times, asks the free LLM to apply only the selected pattern, runs it three more times, saves results, deletes forks it created, and moves to the next row. Existing forks are kept.

Rerun the same command to resume. Results are under `research-data/experiments/`; batch progress is in `research-data/batches/`. See [experiment details](experiments/README.md) for workflow restrictions and saved files.

For all ten blocked patterns, run `scripts/run_scenario_batch.py`. It runs four event scenarios and six synthetic service-policy replays using controlled fixture workflows in a separate scenario batch. See [scenario details](experiments/SCENARIOS.md) and [scenario run commands](RUN_SCENARIO_COMMANDS.md).

`OPENROUTER_MODEL` does not determine batch identity in either batch runner. Change it and resume with the same `--batch-id`; existing cases keep their saved model, while new and rerun cases use the selected model and record it in their results.

Build the pattern and experiment-example retrieval dataset with:

```powershell
.\.venv\Scripts\python.exe scripts\build_rag_dataset.py
```

This writes `research-data/rag/rag_dataset.json` (patterns grouped with their examples), a flat `rag_dataset.jsonl` for embedding pipelines, and a manifest. It includes literature pattern records, their before/after/diff examples, and saved experiment examples with run metrics and evidence labels. Filter on `retrieval_eligible: true` before indexing. The current build contains 25 patterns and 36 experiment examples; none are approved yet because patterns are drafts and experiment evidence is pending review or synthetic. This workspace has no configured vector-store ingestion step.

The separate experiment runner collects a source snapshot from an existing fork, runs the unchanged CI workflow, applies a pattern-specific proposal in a second branch, runs it again, and archives per-run/job/step metrics and the full before/after workflow and diff.

See [experiment setup and storage](experiments/README.md) and [example config](experiments/experiment.example.json). Copy the example, fill in your fork/workflow/required job names, and provide a GitHub token through your environment before running:

```powershell
.\.venv\Scripts\python.exe scripts\run_ci_experiment.py run --config experiments\my-pilot.json
```

The example uses three measurements per arm, capped at six dispatches. The individual-config optimizer enables npm caching on supported existing setup-node jobs; the interactive mode uses selected-pattern OpenRouter proposals with scope validation. The target workflow must already support manual dispatch. The runner retains failed and canceled executions, resumes pending runs without automatically resending dispatches, and records missing safety/behavior evidence as `inconclusive`.

All output is local under `research-data/experiments/<experiment_id>/`, with generated indexes in `research-data/runs/`, `research-data/knowledge/`, and `research-data/analysis/`. Repository-specific cases are separate from the illustrative literature files in `knowledge/examples/`.

Offline protocol checks (no real CI runs or network calls):

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s scripts -p test_ci_experiment.py
```
