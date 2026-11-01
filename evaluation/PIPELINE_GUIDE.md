# CloudTune Evaluation Pipeline — Usage Guide

This guide is the long-term **user and operator guide** for the CloudTune evaluation pipeline. It is maintained as the pipeline grows. The repository's existing [`evaluation/README.md`](README.md) remains unchanged; that document describes the research evaluation protocol. This guide describes how to operate the implementation.

## 1. Evaluation scope

The planned pipeline evaluates three arms on the **same pinned repository/workflow snapshot**:

| Arm               | Method                            | What is measured                                                            |
| ----------------- | --------------------------------- | --------------------------------------------------------------------------- |
| **A — Original**  | Unmodified original CI workflow   | Execution and runner-time baseline                                          |
| **B — `ci-cost`** | Rule-based workflow optimization  | Candidate validity, safe CI behavior and runtime/resource change vs A       |
| **C — LLM + RAG** | Frozen RAG evidence + a fixed LLM | Candidate validity, safe CI behavior and runtime/resource change vs A and B |

**LLM-only (D) is out of scope.** Do not interpret C-versus-B results as an isolation of RAG's contribution from the LLM's contribution.

## 2. Current implementation status

| Capability                                               | Status      | Entry point / file                                                                            |
| -------------------------------------------------------- | ----------- | --------------------------------------------------------------------------------------------- |
| Held-out dataset reading and development-data exclusions | Implemented | `evaluation/repository_preparation.py`                                                        |
| Conservative public GitHub repository/workflow screening | Implemented | `evaluation/repository_preparation.py`                                                        |
| Pinned snapshot and bounded manifest/lockfile archiving  | Implemented | `evaluation/repository_preparation.py`                                                        |
| Unchanged Arm A **candidate record**, not a CI execution | Implemented | `evaluation/optimizers/original.py`                                                           |
| Read-only coordinator, repeatable local output           | Implemented | `evaluation/run_pipeline.py`                                                                  |
| B — `ci-cost` candidate generation                       | Planned     | `evaluation/optimizers/ci_cost.py`                                                            |
| C — retrieval and LLM candidate generation               | Planned     | `evaluation/rag_retriever.py`, `evaluation/optimizers/rag_llm.py`                             |
| Common `actionlint` / semantic / security validation     | Planned     | `evaluation/candidate_validator.py`                                                           |
| A/B/C isolated CI execution and resumption               | Planned     | `evaluation/ci_executor.py`                                                                   |
| Full run export and paired comparative statistics        | Planned     | `evaluation/results_exporter.py`; update existing analysis script only if explicitly approved |

**Current entrypoint only implements `--stage prepare`.** It neither creates forks nor enables GitHub Actions, edits workflow YAML, makes optimizer calls, dispatches CI runs, or measures CI time. It must not be used to claim measured evaluation results.

## 3. Prerequisites

- Run all commands from the **CloudTune repository root**.
- Python 3.11+ with the repository's `requirements.txt` installed (`PyYAML`).
- Repository files: `evaluation/evaluation_repositories_4000.csv` and `research-data/zenodo_20340547/pattern_repo_candidates_20.csv`.
- GitHub public API read access. For higher rate limits, set `GITHUB_TOKEN` in the shell or in the root `.env`; never commit credentials.
- The current implementation needs **read access only**. Do not grant repository write or Actions permissions just to run preparation.

### Install dependencies

**Windows PowerShell**

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

**Linux Bash**

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
```

If you already have a working `.venv`, use it rather than creating another one.

## 4. Run the implemented preparation stage

The committed pilot configuration is [`configs/pilot.json`](configs/pilot.json). It reserves the three arms but deliberately uses `execution.dry_run: true`.

**Windows PowerShell**

```powershell
.\.venv\Scripts\python.exe -m evaluation.run_pipeline --config evaluation\configs\pilot.json --stage prepare
```

**Linux Bash**

```bash
./.venv/bin/python -m evaluation.run_pipeline --config evaluation/configs/pilot.json --stage prepare
```

Preparation screens the configured dataset rows; **`repository_limit: 5` means five attempted candidates, not five eligible repositories**. In particular, some candidates may be ineligible or need an approved dispatch harness.

Do **not** set `dry_run` to false expecting CI execution. The current entrypoint rejects it.

## 5. Run the offline regression tests

These tests use mocked GitHub responses and should not need a token or start GitHub Actions.

**Windows PowerShell**

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_evaluation_preparation.py -v
```

**Linux Bash**

```bash
./.venv/bin/python -m unittest discover -s tests -p 'test_evaluation_preparation.py' -v
```

Optionally run the repository's complete `tests/` suite after changes to shared experiment utilities. See `tests/test_evaluation_preparation.py` for mock fixtures and assertions.

## 6. Results and interpretation

Generated files are written under `evaluation/results/<evaluation_id>/` and are ignored by Git. They include:

```text
evaluation/results/<evaluation_id>/
├── config.json                    # immutable configuration for this ID
├── screening.csv                  # one row per selected dataset candidate
├── preparation_summary.json       # status counts; github_actions_runs = 0
└── repositories/<repo-slug-hash>/
    ├── manifest.json              # pinned commit, tree, selected workflow and checks status
    ├── source/
    │   ├── original.yml           # exact pinned workflow content
    │   └── files/                 # bounded workflow/build context snapshots
    └── candidates/A/candidate.json # unchanged original candidate, NOT_EXECUTED
```

| Status          | Meaning                                                                                                    | How to handle it                                                                                                                              |
| --------------- | ---------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `prepared`      | Repository/workflow passed conservative screening and dispatch prerequisites.                              | Ready for later validation and CI execution stages; **not** an actual safety certification.                                                   |
| `needs_harness` | A workflow is selected and snapshotted but lacks a suitable dispatch trigger or input defaults.            | Add a reviewed **common dispatch harness** on a research-owned fork in a later stage; then freeze a **new** shared source revision for A/B/C. |
| `ineligible`    | Missing safe test/build workflow or excluded repository family, among other reasons.                       | Preserve the screening reason and report attrition.                                                                                           |
| `inconclusive`  | A trustworthy snapshot could not be established, e.g. incomplete tree, ambiguous YAML, mismatched content. | Investigate; never treat as eligible by default.                                                                                              |
| `api_error`     | GitHub API/network/rate-limit failure.                                                                     | Verify access and retry without deleting existing snapshots.                                                                                  |

A repeated run with the same evaluation ID reuses already frozen repository snapshots; it does not silently follow a repository's moving default branch. **Materially changed configuration or protocol needs a new `evaluation_id`.**

## 7. Safety and reproducibility rules

- Never automatically change an upstream repository. This preparation stage is completely read-only.
- Archive inputs with pinned source commit/tree and SHA-256 hashes; record omitted manifests and files.
- Exclude known training/development repository IDs, and check fork provenance where available.
- Conservatively flag deployment/release/publishing, secret references, self-hosted runners, reusable workflows without inspection and dangerous listeners.
- These are **heuristic screens**, not a proof of behavioral equivalence. Required checks remain **not verified** at this stage.
- Keep RAG indexing, candidate generation, safety validation, and actual CI execution as separate stages.
- Preserve `NO_CHANGE`, failures, rejected candidates and incomplete runs in eventual A/B/C reporting; never invent savings.

## 8. Guide maintenance as implementation progresses

Update **this guide** when new stages and CLI commands are implemented. Do not create `PHASE2_README.md`, `PHASE3_README.md`, etc. Keep status tables, examples and commands in sync with actual code. The existing `evaluation/README.md` research protocol is deliberately untouched unless a separate, explicit change is requested.

The complete design and implementation work plan is maintained as a **separate, downloadable Markdown document**, not included in the implementation patch.
