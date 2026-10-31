# Evaluation: RAG-assisted CI optimization vs `ci-cost`

## Goal

Evaluate whether a RAG-assisted optimizer can recommend safe CI workflow changes that reduce CI time and runner cost, compared with the rule-based `ci-cost` optimizer. The original workflow is the no-change reference used to calculate savings.

The current RAG corpus contains 25 literature patterns and 49 pattern-satisfied experiment examples: 39 synthetic scenarios and 10 main-batch cases whose source outcome was inconclusive (the inconclusive `outcome` field is omitted in the RAG record). These examples provide context, not proof of speedups on the evaluation repositories. This evaluation must measure each proposed change on the target repository.

## Comparison arms

| Arm | Method | Purpose |
| --- | --- | --- |
| **A — Original** | Run the original pinned workflow without optimization. | Measures baseline time and runner use. |
| **B — `ci-cost`** | Run a pinned version of `ci-cost` and evaluate its generated candidate. | Rule-based optimizer comparison. |
| **C — LLM + RAG** | Give the same repository context and original workflow to a fixed LLM, with relevant retrieved RAG patterns/examples. | Proposed method. |
| **Optional D — LLM-only** | Same as C, using the same model and prompt, but without retrieved material. | Separates the effect of RAG from the effect of using an LLM. Recommended if the claim is that RAG itself helps. |

Keep the generator model, base prompt, repository files, output format, safety limits, retry count, and token budget the same for C and D. The embedding model is `BAAI/bge-m3`; it retrieves evidence and does not generate the workflow patch.

## Evaluation set and controls

1. Start from the held-out candidate pool [`evaluation_repositories_4000.csv`](evaluation_repositories_4000.csv). Screen current workflow availability and CI history before execution; the Zenodo snapshot is not a current eligibility check. Record inclusion rules before running optimizers. Do not use held-out repositories to develop prompts or tune recommendations.
2. Pin each repository to one commit and select one target workflow. Freeze the workflow, source tree, dependency lockfiles, runner labels, and required-check contract for all arms.
3. Use the same evaluation repositories for every arm. Make isolated branches or forks from the same commit; only the intended workflow change may differ.
4. Record the RAG dataset hash, embedding model revision, retrieved document IDs, `ci-cost` version/commit, generator model/version, prompts, and patch hashes.
5. Run a pilot on a small number of repositories to check reproducibility and budget. For the main run, target five measured executions per arm and repository, increasing that number if pilot variance is high and budget allows.
6. Interleave arm order (for example, rotate A/B/C/D each round) to reduce bias from runner load and time-of-day effects. Fix cache state: compare cold and warm runs separately if the optimization affects caching.

## Generate and validate candidates

### `ci-cost` arm

Pin and record the exact tool version. Run its documented analysis/fix command on a clean snapshot. Its `--fix` output may be placed under `.github/workflows/optimized/`; do not leave duplicate runnable workflow files in the evaluation branch. Transplant only the tool-generated intended change to the original workflow path. Do not hand-author or improve the rule-based proposal. Record `NO_CHANGE`, unsupported suggestions, and invalid candidates.

### RAG arm

Provide the optimizer with the target workflow, relevant build/test configuration, repository context, required checks, and optimization goal. Retrieve the most relevant patterns and examples, retaining their limitations and evidence scope. Ask the LLM to return either a minimal patch or `NO_CHANGE`, plus cited RAG record IDs, applicability reasons, preconditions, risks, and expected CI-time effect. A retrieval match alone is not a recommendation: reject patterns whose preconditions do not fit.

### Same checks for every candidate

Run the same validation on B, C, and optional D:

- Patch applies to the pinned commit and changes only allowed workflow files.
- Workflow YAML parses and passes `actionlint`.
- Triggers, required checks, jobs, test/build commands, matrix coverage, permissions, dependencies, and required artifacts remain within the declared contract.
- Run change-specific checks for caches, path filters, concurrency, timeouts, or parallel jobs.
- Execute the intended CI workload on an isolated fork/branch. Record failures and cancellations; they are not successful speedups.

Label each candidate `PASS`, `FAIL`, `REVIEW_REQUIRED`, or `INCONCLUSIVE`. Have a reviewer assess safety independently of the optimizer. Do not count unsafe or behavior-changing candidates as successful optimizations.

## Measurements

Record one row per run with repository/workflow ID, pinned commit, arm, patch hash, tool/model versions, retrieved IDs, run number/order, cache regime, timestamps, status/conclusion, required-check completion, elapsed seconds, summed job-runtime seconds, and failure/safety reason. Record optimizer latency, LLM tokens/API cost, and retrieval latency where applicable.

**Primary outcome:** workflow elapsed time for a successful, equivalent run. Define the clock consistently (for example, earliest job start to latest required job finish) and report queue time separately where available.

**CI resource outcome:** sum of the durations of all executed jobs. This captures runner use; parallel jobs can lower elapsed time while increasing total job time.

If billing data or a defensible runner rate is available, report monetary CI cost and its rate/date/source. Otherwise, report summed job-runtime as the cost proxy and do not invent dollar savings.

Also report:

- Required-check and safety pass rate.
- Candidate validity, `NO_CHANGE`, abstention, and rejection rates.
- Safe optimization success rate: candidate passes safety and meets a predeclared minimum benefit threshold.
- RAG retrieval relevance, assessed by blinded reviewers against the repository and task.
- Failures, regressions, and cases where the workflow became slower.

## Analysis

For repository `r` and optimizer `m`, calculate elapsed-time savings against the original arm:

```text
elapsed_saving_pct(r, m) =
  100 * (median_elapsed(r, A) - median_elapsed(r, m)) / median_elapsed(r, A)
```

Use the same formula with summed job-runtime for the runner-use reduction. Calculate medians across repeated runs within each repository first. Compare paired per-repository results for **C vs B**; also compare C vs A and B vs A. If D is included, compare C vs D to assess RAG’s added value.

Report median savings across repositories, interquartile range, paired differences and confidence intervals, number of safe beneficial changes, and all failures/abstentions. Use the repository/workflow as the analysis unit; repeated runs of one repository are not independent repositories. Keep `NO_CHANGE`, invalid, and failed candidates in the denominator and report them separately. Never report time savings without safety and required-check results.

The analysis script reads the run-level CSV format in [`evaluation_runs_template.csv`](evaluation_runs_template.csv) and writes per-repository and aggregate summaries:

```powershell
.\.venv\Scripts\python.exe evaluation\evaluate_rag_vs_ci_cost.py evaluation\evaluation_runs.csv --output-dir evaluation\results
```

It computes paired elapsed-time, runner-time, and optional billed-cost reductions; repository-bootstrap 95% confidence intervals; and candidate safety, no-change, and rejection counts. Candidate runs without a `PASS` safety verdict and successful required checks receive zero realized savings and remain in the repository denominator.

## Result table template

| Arm | Repositories | Safe candidates | Required checks passed | Median elapsed saving vs A | Median runner-time saving vs A | `NO_CHANGE` / rejected | Median optimizer latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A — Original |  | N/A |  | 0% | 0% | N/A | N/A |
| B — `ci-cost` |  |  |  |  |  |  |  |
| C — LLM + RAG |  |  |  |  |  |  |  |
| D — LLM-only (optional) |  |  |  |  |  |  |  |

## Current status and interpretation

This document defines a planned evaluation; it does not report completed `ci-cost` vs RAG results. The RAG dataset has been built, but Supabase ingestion is pending. Before running the comparison, apply the Supabase migration and upload the frozen dataset, or use an equivalent frozen local index. Do not claim RAG improves CI time until generated candidates have passed the same safety checks and repeated CI runs on the held-out repositories.

The broader research protocol is in [`01_Research_Workflow_Data_Training_Evaluation.md`](../workflow/01_Research_Workflow_Data_Training_Evaluation.md); architecture notes are in [`02_System_Architecture_AI_Implementation_Blueprint.md`](../workflow/02_System_Architecture_AI_Implementation_Blueprint.md).
