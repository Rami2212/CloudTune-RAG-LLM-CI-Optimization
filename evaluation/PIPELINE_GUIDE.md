# CloudTune Evaluation Pipeline — Usage Guide

> **Current implementation (November 1, 2026):** CloudTune runs a local fork coordinator;
> only evaluated candidate forks run measured GitHub Actions CI. The previous hosted
> controller instructions in Section 10 are superseded by the corrected Section 11.

This guide is the long-term **user and operator guide** for the CloudTune evaluation pipeline. It is maintained as the pipeline grows. The repository's existing [`evaluation/README.md`](README.md) remains unchanged; that document describes the research evaluation protocol. This guide describes how to operate the implementation.

## 1. Evaluation scope

The planned pipeline evaluates three arms on the **same pinned repository/workflow snapshot**:

| Arm               | Method                            | What is measured                                                            |
| ----------------- | --------------------------------- | --------------------------------------------------------------------------- |
| **A — Original**  | Unmodified original CI workflow   | Execution and runner-time baseline                                          |
| **B — `ci-cost`** | Rule-based workflow optimization  | Candidate validity, safe CI behavior and runtime/resource change vs A       |
| **C — LLM + RAG** | Frozen RAG evidence + a fixed LLM | Candidate validity, safe CI behavior and runtime/resource change vs A and B |

**LLM-only (D) is out of scope.** Do not interpret C-versus-B results as an isolation of RAG's contribution from the LLM's contribution.

## Current operating model — local coordinator and candidate-fork CI

**Only research-owned candidate forks execute measured GitHub Actions jobs.**
The CloudTune controller runs locally via `python -m evaluation.fork_pipeline`.
It screens repositories, creates the same-source A/B/C candidates, validates
optimized changes, dispatches fork workflows, and records raw GitHub evidence.
The CloudTune research repository does **not** host an evaluation Actions
controller or execute target builds/tests. See **Section 11** for the current
commands and safe fork cleanup policy.

The earlier offline preparation and `ci-cost` instructions in Sections 3–9
remain relevant. Section 10 documents a superseded hosted-controller design;
do **not** perform its GitHub `main` registration, state-branch, schedule, or
secrets setup. Use a development-only repository for the first live smoke
experiment, never the held-out evaluation cohort.

### Clock definitions for the study

- `initial_queue_seconds`: GitHub run creation to first executed job start.
- `workflow_elapsed_seconds`: **union of intervals when at least one actual
  GitHub Actions job is running**. Overlapping parallel jobs count once and
  idle gaps waiting for the next runner are excluded. This is the primary
  queue-excluded _active workflow time_ measure.
- `workflow_makespan_seconds`: first job start to last job finish, including
  possible _internal_ runner scheduling gaps. Report separately; it is not
  the queue-excluded metric.
- `inter_job_idle_seconds`: makespan minus active workflow time. This captures
  idle intervals but is not independently proof that every gap was caused by
  GitHub runner scheduling, because job dependencies may also contribute.
- `sum_job_runtime_seconds`: sum of actual executed-job durations. This is a
  runner-occupation proxy; overlapping jobs contribute separately.

The distinctions between these outcomes must be retained in exported data and
statistical analysis. No optimizer, local npm, model download, network API
request or queue wait is included in the measured target CI execution.

## 2. Current implementation status

| Capability                                               | Status                                | Entry point / file                                                                            |
| -------------------------------------------------------- | ------------------------------------- | --------------------------------------------------------------------------------------------- |
| Held-out dataset reading and development-data exclusions | Implemented                           | `evaluation/repository_preparation.py`                                                        |
| Conservative public GitHub repository/workflow screening | Implemented                           | `evaluation/repository_preparation.py`                                                        |
| Pinned snapshot and bounded manifest/lockfile archiving  | Implemented                           | `evaluation/repository_preparation.py`                                                        |
| Unchanged Arm A **candidate record**, not a CI execution | Implemented                           | `evaluation/optimizers/original.py`                                                           |
| Read-only coordinator, repeatable local output           | Implemented                           | `evaluation/run_pipeline.py` (`prepare`, `ci-cost`)                                           |
| B — `ci-cost` source-fixed candidate generation          | Implemented                           | `evaluation/optimizers/ci_cost.py`                                                            |
| C — frozen Supabase/BGE-M3 + LLM candidate generation    | Code added; live verification pending | `evaluation/rag_retriever.py`, `evaluation/optimizers/rag_llm.py`                             |
| Common `actionlint` / conservative security gate         | Code added; live verification pending | `evaluation/candidate_validator.py`                                                           |
| A/B/C fork-hosted execution and durable resumption       | Code added; live verification pending | `evaluation/ci_executor.py`                                                                   |
| Paired local summaries / repository bootstrap reporting  | Code added; live verification pending | `evaluation/results_exporter.py`; update existing analysis script only if explicitly approved |

**Available stages:** `--stage prepare` and `--stage ci-cost` (offline Arm B generation). Neither stage creates forks, dispatches CI runs, or measures CI time. The new stage invokes an external rule-based CLI on isolated snapshot copies; generated changes are not yet validated or deployed.

## 3. Prerequisites

- Run all commands from the **CloudTune repository root**.
- Python 3.11+ with the repository's `requirements.txt` installed (`PyYAML`).
- Repository files: `evaluation/evaluation_repositories_4000.csv` and `research-data/zenodo_20340547/pattern_repo_candidates_20.csv`.
- GitHub public API read access. For higher rate limits, set `GITHUB_TOKEN` in the shell or in the root `.env`; never commit credentials.
- The **preparation stage** needs read access only. The local fork coordinator in Section 11 requires appropriately scoped fork-management, Contents and Actions permissions for real execution; do not grant those merely to prepare repository snapshots.

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

### Install RAG dependencies for Arm C

The lightweight `requirements.txt` installs PyYAML for preparation, validation,
and Arm B. **Real BGE-M3 retrieval and the Arm C smoke test additionally require
`requirements-rag.txt`** (`sentence-transformers` and `psycopg`). Install both
into the **same** `.venv`; never install the large model into the repository.

**Windows PowerShell**

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-rag.txt
.\.venv\Scripts\python.exe -m pip check
```

**Linux Bash**

```bash
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python -m pip install -r requirements-rag.txt
./.venv/bin/python -m pip check
```

`--mode local` and `--mode remote` do **not** load the embedding weights;
`--mode retrieve` and `--mode smoke` do. On first retrieval, Hugging Face
may download BGE-M3 weights (roughly 2 GB) into its model cache, normally
`~/.cache/huggingface/hub/models--BAAI--bge-m3/` on Linux or
`%USERPROFILE%\.cache\huggingface\hub\models--BAAI--bge-m3\` on Windows.
`HF_HOME` or `HF_HUB_CACHE` can change that cache location. Repeated runs
should reuse the downloaded revision. BGE-M3 **embeds** queries locally;
OpenRouter generates workflow candidates remotely. No local LLM training is
needed.

Windows may warn that the Hugging Face cache cannot use symlinks. Retrieval
still works but large files may consume extra disk space; enabling Windows
Developer Mode can improve cache efficiency. Unauthenticated downloads of
public BGE-M3 weights are supported but may face lower rate limits; optional
`HF_TOKEN` credentials can improve rate limits. The Windows
`torch.distributed.elastic` redirect warning is informational, too.
Allow several GB of disk space, especially if both `pytorch_model.bin`
and `model.safetensors` are cached. Never commit cached weights.

### Optional NVIDIA GPU: install a CUDA-enabled PyTorch build

**CPU is supported** and is the default. For an NVIDIA GPU, verify the driver
with `nvidia-smi` and check whether the existing PyTorch build can access it.
If `torch.cuda.is_available()` is already `True`, **do not reinstall PyTorch**.
Do not install a second copy of the entire `requirements-rag.txt` stack just
to change the PyTorch compute backend.

**Windows PowerShell**

```powershell
nvidia-smi
.\.venv\Scripts\python.exe -c "import torch; print('torch:', torch.__version__, 'CUDA:', torch.version.cuda, 'available:', torch.cuda.is_available()); print('GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'not detected')"
```

**Linux Bash**

```bash
nvidia-smi
./.venv/bin/python -c "import torch; print('torch:', torch.__version__, 'CUDA:', torch.version.cuda, 'available:', torch.cuda.is_available()); print('GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'not detected')"
```

If CUDA is unavailable despite a supported NVIDIA GPU and driver, **replace**
the CPU-only PyTorch wheel with a matching official CUDA wheel. The pinned
CUDA 12.8 example below matches the tested RTX 4050 environment. Other
hardware or CUDA releases should follow the official [PyTorch installation
selector](https://pytorch.org/get-started/locally/) instead.

**Windows PowerShell (only if CUDA is currently unavailable)**

```powershell
.\.venv\Scripts\python.exe -m pip install --force-reinstall "torch==2.11.0" --index-url https://download.pytorch.org/whl/cu128
.\.venv\Scripts\python.exe -m pip check
```

**Linux Bash (only if CUDA is currently unavailable)**

```bash
./.venv/bin/python -m pip install --force-reinstall 'torch==2.11.0' --index-url https://download.pytorch.org/whl/cu128
./.venv/bin/python -m pip check
```

PyTorch `2.11.0` / CUDA `12.8` is an **example pinned environment**, not
an instruction to replace a working or otherwise pinned installation.
`--force-reinstall` is intentionally only in the repair path. Use an
appropriately compatible `torchvision` version if your environment has it
installed; do not mix mismatched PyTorch/torchvision wheels.

After verifying `torch.cuda.is_available() == True`, set
`CLOUDTUNE_RAG_DEVICE=cuda` in the ignored root `.env`. To keep CPU inference,
use `CLOUDTUNE_RAG_DEVICE=cpu` (or omit the setting). The committed
`evaluation/rag_retriever.py` reads this device setting. Do not claim a GPU run
without verifying which device the retriever actually used. On a 6-GB laptop
GPU, CUDA out-of-memory is possible; switch to CPU if necessary. The current
candidate metadata does not automatically record the selected inference
device: keep it fixed and record it in experiment environment notes.

For the later fork-based execution phase, also install Node.js/npm for the
pinned `ci-cost` adapter and install `actionlint` on PATH; candidate admission
fails closed if `actionlint` is absent. Check with `node --version`,
`npm --version`, and `actionlint -version`. **No Docker is required.**

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

## 9. Install and run Arm B — corrected pinned `ci-cost` source

**Research identity:** Arm B now uses **ci-cost 1.0.0, pinned at upstream
`e3722ea83da600bebac9ad21ec52490df824eb5c`, with the reviewed
`cloudtune-ci-cost-source-fix-v1` TypeScript correctness fixes**. It is **not**
the unchanged off-the-shelf release. Cite this distinction in the methods and
limitations; do not call it an unmodified `ci-cost` baseline. All fixes are
applied to the _upstream source_ and compiled before any evaluation; the Python
adapter never rewrites generated workflow output.

The upstream README documents `npx ci-cost`, but `ci-cost@1.0.0` is not available
from the public npm registry. Use the pinned GitHub source instead. The source
fixes address incorrect checkout `fetch-depth` handling (checkout v4 defaults
to depth 1), invalid indentation in generated cache steps, and a matrix
`fail-fast` change that formerly inserted only a comment. Generation also
validates YAML before writing output. No heuristic post-generation repair is
allowed.

Prerequisites: Node.js 20+, npm, Git, Python with PyYAML, and access to GitHub
and the public npm registry. The local tool is kept under `.venv/ci-cost` and
has its own npm dependencies; the CloudTune root remains a Python project.

### Setup and verification

In **Windows PowerShell**, from the existing CloudTune repository root:

```powershell
.\.venv\Scripts\python.exe -m evaluation.third_party.ci_cost.setup
.\.venv\Scripts\python.exe -m evaluation.third_party.ci_cost.setup --verify
```

In **Linux Bash**:

```bash
./.venv/bin/python -m evaluation.third_party.ci_cost.setup
./.venv/bin/python -m evaluation.third_party.ci_cost.setup --verify
```

Setup checks out the exact upstream SHA, verifies an initially clean checkout,
patches only reviewed TypeScript source, installs dependencies using `npm ci
--ignore-scripts`, recompiles with the pinned TypeScript dependency, then
executes the **real compiled CLI** on two YAML smoke cases including the
previously failing `fabrikt` checkout shape. It refuses to record a successful
installation if any generated YAML is invalid or source changes differ from
the allowed compiled source files. The generated installation manifest hashes
the fix specification, modified source/compiled files, and upstream lockfile.

**Do not run `npm ci --omit=dev` for setup:** the TypeScript compiler is a
development dependency and is needed to rebuild the fixed source. Do not run
`npx ci-cost@1.0.0`; that package is unavailable from npm.

### Candidate generation

**Windows PowerShell**:

```powershell
.\.venv\Scripts\python.exe -m evaluation.run_pipeline --config evaluation\configs\pilot.json --stage ci-cost
Get-Content evaluation\results\cloudtune-abc-preparation-pilot-001\ci_cost_summary.json
```

**Linux Bash**:

```bash
./.venv/bin/python -m evaluation.run_pipeline --config evaluation/configs/pilot.json --stage ci-cost
cat evaluation/results/cloudtune-abc-preparation-pilot-001/ci_cost_summary.json
```

The corrected build writes immutable candidates under
`repositories/<repo>/candidates/B/cloudtune-ci-cost-source-fix-v1/`. Earlier
`candidates/B/candidate.json` artifacts (including the previous `fabrikt`
error) are **preserved**. The coordinator reports the corrected build's result
without overwriting historical evidence.

`APPLY` means a substantive YAML change was generated, `NO_CHANGE` means none
was generated, and `ERROR` means the tool, source verification or generated
output failed. `SKIPPED` means the repository was screened out. An APPLY result
is not proof of behavior-preserving optimization or time savings. Common
candidate validation, required checks and real GitHub Actions runs remain
separate subsequent implementation stages. `github_actions_runs` is 0 here.

A source-fixed comparator is methodologically different from the original
upstream tool. Preserve upstream failures as separate evidence; do not combine
or replace those measurements without declaring which ci-cost build was used.

### Tests

**Windows PowerShell**:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

**Linux Bash**:

```bash
./.venv/bin/python -m unittest discover -s tests -v
```

The offline tests verify snapshot integrity, candidate archiving, source-fix
identity, and compiled transformation functions where TypeScript is available.
They do not substitute for the real CLI smoke tests or future candidate-fork
GitHub Actions evaluation runs.

---

## 10. Historical design record — superseded GitHub-hosted controller

> **Do not use any commands or setup steps in this section.** It records an
> intermediate hosted-controller proposal, which was abandoned during the
> earlier implementation work. No `.github/workflows/cloudtune-evaluation.yml`
> controller, CloudTune state branch, or scheduled resume exists in the adopted
> architecture. Follow **Section 11** for the actual local coordinator.

**Measured target CI execution happens only on GitHub Actions runners in
research-owned forks of the target repositories.** The CloudTune controller
performs repository screening, candidate generation, static safety checks,
remote GitHub Actions dispatch and REST evidence collection. **It never runs
selected repositories' build/test workloads locally.** Python, npm, TypeScript,
BGE-M3 and OpenRouter are used for candidate preparation; those durations are
not counted as target CI execution time.

**Repository audit / existing code reuse:** The previous experiment subsystem
`scripts/run_pattern_batch.py` and `scripts/run_ci_experiment.py` already uses
forks, pinned Git trees, experiment commits, `workflow_dispatch`, pending-run
recovery and GitHub Actions job timing. The new evaluation implementation
preserves these proven mechanisms while adding three-arm comparisons and a
hosted controller. Its RAG retrieval reads the existing `cloudtune_rag_documents`
/ `cloudtune_rag_chunks` Supabase schema defined by
`supabase/migrations/202610310001_cloudtune_rag.sql`. It does **not** train,
rebuild, upload, or update the corpus during an evaluation. The committed corpus
manifest declares 74 records (25 literature patterns + 49 examples); this is
**not proof that 74 records are currently installed in Supabase**. The controller
verifies live document hashes, memberships and one BGE-M3 embedding revision
against `research-data/rag/rag_dataset.jsonl` before creating Arm C.

### 10.1 Two GitHub Actions execution locations

```text
CloudTune repository: .github/workflows/cloudtune-evaluation.yml
  |
  +-- prepare a frozen source commit and documented eligibility
  +-- create A (unchanged), B (source-fixed ci-cost), C (BGE-M3/Supabase + LLM)
  +-- actionlint and conservative common safety admission
  +-- create/prepare research-owned fork, register common dispatch harness
  +-- commit A/B/C to isolated refs derived from the SAME pinned source
  |
  v
Target research fork: selected .github/workflows/<workflow>.yml
  +-- workflow_dispatch on A => actual GitHub Actions build/tests
  +-- workflow_dispatch on B => actual GitHub Actions build/tests, if admitted
  +-- workflow_dispatch on C => actual GitHub Actions build/tests, if admitted
  |
  v
GitHub REST workflow-run + jobs endpoints
  +-- preserve raw run/job JSON, SHA and conclusion
  +-- initial GitHub runner queue delay: creation -> FIRST job start
  +-- active job time: union of started_at -> completed_at job intervals
  +-- raw makespan: FIRST job start -> LAST executed job finish
  +-- inter-job idle: raw makespan - active job time
  +-- job runtime: sum of each executed job's start -> completion
  +-- CI required-check outcome and protocol identity
  |
  v
CloudTune state branch + archived report/evidence
```

**Queue measurement policy:** `run_started_at` is not accepted as a substitute
for the first job's `started_at`. Even multi-hour initial GitHub queue delays
must not inflate execution time. The queue-excluded primary `workflow_elapsed_seconds` merges overlapping job
intervals and excludes _all_ intervals where no target job is running. The
unmodified start-to-finish makespan remains available separately to explain
practical workflow completion latency, and `inter_job_idle_seconds` shows its
gaps. Those gaps may reflect dependencies as well as runner scheduling; their
cause must not be asserted without additional GitHub evidence. The **sum of
executed job runtimes** is reported as a separate runner-resource proxy. Neither measure
is described as GitHub billed minutes without official billing evidence.

A queued/running GitHub workflow is **not** a failed target CI run. The
controller saves dispatch intent and run identity before further actions,
returns `WAITING_FOR_GITHUB_RUN`, and rechecks in later scheduled invocations.
It must never send a second POST simply because an earlier dispatch timed out
or a runner remained queued. Ambiguous dispatches are retained for investigation
and never converted to measured failures or fake speedups.

### 10.2 Archived hosted setup — do not follow

The hosted controller is `.github/workflows/cloudtune-evaluation.yml`.
It installs Node.js, Python, actionlint and the pinned source-corrected ci-cost
**inside GitHub's temporary controller runner environment**. No ci-cost clone
inside the developer's `.venv` is required for a hosted evaluation. The
source-corrected B comparator **must be reported as such**; it is not the
unmodified upstream `ci-cost` release.

**GitHub Actions default-branch constraint:** CloudTune's remote default branch
is `main`. GitHub's regular Actions UI manual `workflow_dispatch` requires this
controller workflow to be registered on the default branch. Pushing the new
workflow only to `feature/evaluation-pipeline` triggers the **non-dispatching
verification** job; it does not enable a reliable manual UI start. Review and
merge the controller workflow to `main` (or register an appropriately reviewed
workflow on `main`) before manually starting hosted experiments. All evaluation
commits remain versioned and separate from the original upstream source.

Configure the following **CloudTune Actions repository secrets** using the
GitHub repository settings (do not commit them or pass them to target builds):

- `CLOUDTUNE_FORK_TOKEN`: GitHub credential that can create and administer
  research-account forks, enable Actions, write branches and dispatch target
  workflows. A repository-scoped `GITHUB_TOKEN` cannot write into another
  account's forks. Grant only the permissions required for your research-owned
  forks, and test them with a disposable development repository first.
- `SUPABASE_URL`, `SUPABASE_SECRET_KEY`: the existing Supabase RAG index.
- `OPENROUTER_API_KEY`: the chosen pinned free generation model.

CloudTune's own temporary `GITHUB_TOKEN` needs `contents: write` **only** for
its versioned `cloudtune-evaluation-state` branch. These secrets are exposed
only to the controller execution step, **not** to the third-party npm install
or source compilation steps, and never to the target fork's CI jobs.

GitHub UI: **Actions -> CloudTune GitHub-hosted A/B/C evaluation -> Run workflow**.
Choose `main` after the controller has been registered there, and select
`evaluation/configs/hosted_pilot.json`. The committed hosted pilot attempts
three **dataset rows**, not necessarily three eligible forks, with three
repetitions per valid arm. Do not run against the full 4,000-row candidate pool
without a separately pre-registered research sampling and spending protocol.

Every 30 minutes GitHub's scheduled controller attempts to resume an
**already-started** pilot. A schedule alone does not start a new study. Each
invocation caps fresh dispatches at three; pending runs are resolved before any
new dispatch. GitHub scheduled events can be delayed or dropped under load:
manual re-dispatch with the **same** frozen controller revision and config is
also possible without reissuing a pending target run.

### 10.3 Evidence and safety boundaries

Scheduled resumes check out the **exact original controller commit**
archived in the experiment ledger, even if CloudTune's default branch has moved
since the initial launch. If the newer default-branch _workflow definition_ has
changed, the controller refuses automatic resume instead of silently changing
the experiment protocol. The GitHub-hosted controller and measured fork runs
remain separately versioned.

The hosted controller checkpoints frozen source files, LLM retrieval/results,
candidates and real GitHub API run/job responses to the dedicated
`cloudtune-evaluation-state` branch. Commits are non-force, hashes are checked,
and resumes restore archived snapshots rather than re-screening moving upstream
heads. The controller uploads an additional per-invocation GitHub Actions
artifact from `evaluation/results/`; that artifact is **not** the durable
source of truth across separate hosted runner instances.

The conservative initial shared validator automatically admits only narrow
**additive dependency-cache** proposals preserving the original job IDs,
steps, commands, matrices, triggers and permissions. Cache keys must be
bound to the runner OS and dependency input hashes. Required dispatch inputs
without defaults are rejected before experiment branch creation. Other valid optimization
mechanisms are `REVIEW_REQUIRED` and **not** automatically executed. Neither
YAML parsing, actionlint nor a successful CI conclusion alone proves general
behavioral equivalence; a broader study needs a predeclared mechanism-specific
safety protocol and independent review.

Initial baseline required-job names are inferred from the successful first
GitHub Actions run only when an explicit list is absent. This is a **heuristic
experiment contract**, not proof of an upstream branch-protection requirement.
For research-grade main evaluation, freeze a reviewed required-check contract
before generating comparisons.

**Important:** source-corrected ci-cost changes are attributed only to the
`ci-cost v1.0.0 + CloudTune source-fix v1` comparator. For C, the BGE-M3
embedding revision, retrieval results and model response are retained; model
provider aliases and free-tier availability may change and can make an
experiment inconclusive. Failed or unavailable models are not silently replaced
with a paid model.

### 10.4 Report interpretation

`evaluation/results/<evaluation_id>/hosted_report.json` and
`hosted_runs.csv` and `hosted_aggregate.json` contain observed runs,
paired repository-level statistics and queue-separated timings, including
active job time, full makespan, inter-job idle gaps, initial queue and summed
job runtime. A free-model error is recorded as an Arm C generation failure;
it does not erase successful A/B evidence. Each
repository's raw GitHub run and jobs responses are archived under its frozen
snapshot `runs/<run_id>/attempt-<attempt>/`. Summaries include C-vs-B,
B-vs-A and C-vs-A **only where required comparable GitHub executions exist**.
Incomplete repetitions, rejected candidates, failed builds, and skipped
repositories remain visible with explicit missing values; no imputed or
invented elapsed-time savings are reported. A failed actual CI run is terminal
(`FAILED_TARGET_CI`) under this protocol. A completed GitHub run where **no
job acquired a runner** is `INCONCLUSIVE_PLATFORM`, not an execution-time
measurement or a failed target build; it is not silently retried. Later
scheduled controllers must not run replacement repetitions merely to obtain
a favorable result. Preserving failures in the study
denominator is mandatory.

### 10.5 Verification limits

The local automated tests validate the controller state machine, source checks,
queue-time arithmetic, archive creation, candidate validation and mocked GitHub
run collection. They **cannot** establish that a real GitHub token has fork
administration rights, that a particular upstream workflow is runnable on a
research fork, that the live Supabase corpus is populated, or that the hosted
A/B/C study has finished. A real one-repository development smoke experiment
on GitHub Actions is required before a held-out pilot or main research run.

---

## 11. Current operator model — candidate-fork execution

**This section supersedes Section 10 wherever it describes a GitHub Actions controller in the CloudTune repository.** The research repository must not run selected repositories' CI workflows. The coordinator runs locally using `python -m evaluation.fork_pipeline`; only candidate repository forks run measured CI jobs through GitHub Actions.

The earlier `.github/workflows/cloudtune-evaluation.yml`, `evaluation/hosted_pipeline.py` and `evaluation/configs/hosted_pilot.json` are replaced by the local fork coordinator and `evaluation/configs/fork_pilot.json`. No CloudTune Actions workflow, default-branch registration or remote state branch is necessary.

The process screens and freezes each repository, prepares original A, source-corrected `ci-cost` B and frozen RAG+LLM C candidates, applies the common conservative validator, creates isolated refs on a **research-owned candidate fork**, dispatches workflows using GitHub APIs, collects real GitHub job timestamps and stores all results in `evaluation/results/<evaluation_id>/`. Local setup and model latency are never measured as target CI duration. Long queues and gaps between jobs are excluded from active execution-time metrics.

### Shared candidate validation (local, no CI dispatch)

The local controller uses `evaluation/candidate_validator.py` as one common gate
for Arm B (`ci-cost`) and Arm C (RAG). Every outcome produces immutable evidence
under `evaluation/results/<evaluation_id>/repositories/<repository>/validation/<arm>/validation.json`
_before_ an optimized arm branch can be created. This records the pinned source
and candidate hashes, selected workflow, policy revision, `actionlint` status,
reasons and verified frozen lockfile paths. Existing records can only be reused
when identities match; a policy change requires a new `evaluation_id`.

Only narrow additive dependency-download caches can automatically receive
`PASS`. Such a cache must follow checkout, use a static OS-and-lockfile cache
key, and hash a dependency input verified in the pinned source snapshot.
Missing input files, unsafe/dynamic expressions, installed-artifact caches,
complex triggers or unreviewed workflow changes cannot be auto-dispatched.
`FAIL`, `REVIEW_REQUIRED`, `INCONCLUSIVE` and `NO_CHANGE` never create optimized
arm branches. `actionlint` must be installed locally for approval. The validator
checks duplicate YAML keys through the existing Actions loader, but even `PASS`
is not a mathematical proof that execution behavior is equivalent.

Install `actionlint` from the [official releases](https://github.com/rhysd/actionlint/releases)
(or use the commands below); verify that `actionlint -version` works before
launching an evaluation. On Windows PowerShell:

```powershell
winget install --id rhysd.actionlint --exact
actionlint -version
```

On Linux Bash, with a compatible installed Go toolchain:

```bash
go install github.com/rhysd/actionlint/cmd/actionlint@v1.7.12
export PATH="$(go env GOPATH)/bin:$PATH"
actionlint -version
```

Run the offline candidate admission tests before starting a pilot:

**Windows PowerShell**

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_candidate_validator.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

**Linux Bash**

```bash
./.venv/bin/python -m unittest discover -s tests -p 'test_candidate_validator.py' -v
./.venv/bin/python -m unittest discover -s tests -v
```

These tests use temporary snapshots and mocked validation tools. They do not
create forks, run GitHub Actions, or prove Phase 5 live execution and cleanup.

### Safe automatic fork cleanup and optional retention

The default is `CLOUDTUNE_AUTO_DELETE_FORKS=true` (also used when the key is absent). Once a candidate repository's runs are finalized and raw GitHub run/job evidence is persisted locally, the controller attempts to delete its temporary fork. Deletion requires explicit proof that the fork was created by this evaluation, a matching fork identity, no pending dispatch and no non-completed GitHub Actions runs on that fork. A pre-existing fork is **never deleted**. The deletion intent is checkpointed before the GitHub DELETE. Missing delete permissions are recorded as `BLOCKED_PERMISSION`; uncertain responses are reconciled without blindly sending another DELETE. Active runs postpone cleanup and remain visible in `cleanup_status`.

To preserve the evaluation-created fork and its GitHub Actions history for supervisor review, set `CLOUDTUNE_AUTO_DELETE_FORKS=false` in the ignored root `.env` **before starting the trial**. This does not skip CI, validation, evidence archival or reporting. After completion the ledger records `cleanup_status=RETAINED_BY_CONFIGURATION`, and `fork_report.json` retains the `fork_repo` GitHub name. A retained fork is not automatically deleted on subsequent resumes, even after the flag is changed back to true; delete it manually after supervisor review. A false setting cannot reverse a previously requested DELETE, and any uncertain DELETE outcome remains explicitly unresolved. Invalid boolean values cause an early error before GitHub writes.

### Commands from repository root

**Windows PowerShell**

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m evaluation.fork_pipeline --config evaluation/configs/fork_pilot.json --check-config
```

**Linux Bash**

```bash
./.venv/bin/python -m unittest discover -s tests -v
./.venv/bin/python -m evaluation.fork_pipeline --config evaluation/configs/fork_pilot.json --check-config
```

`--check-config` performs no GitHub writes. The `--watch` option is for actual experiments after repository selection, credentials, dependencies and study eligibility are reviewed. **Do not use held-out evaluation rows as a development smoke test.** The implementation has mock-based verification, not a confirmed live fork-execution-and-deletion test. Keep existing `scripts/`, RAG data and README files unchanged.

### Team-controlled evaluation batches (up to 500 sample rows)

The fork controller accepts the same dataset-position controls as the pattern
runner: `--start-at` (1-based), inclusive `--stop-at`, and `--limit`.
Use **either** `--stop-at` or `--limit`, never both. The upper bound is
100 repository rows per controller invocation, not 100 completed A/B/C trials.
Ineligible/abstaining rows keep their original dataset positions. Every team
member must use a unique `--batch-id`; this becomes the frozen
`evaluation_id` and `evaluation/results/<batch-id>/` directory. Reuse the
**same batch ID, range, configuration and code version** when resuming.
Changed identities are rejected rather than replaying GitHub dispatches.

`--rerun` repeats a **finished batch** under the same base `--batch-id`, but
stores every generation separately (`team-02-r2`, `team-02-r3`, ...). Previous
snapshots, runs, and reports stay unchanged. When a numbered generation has
pending CI, repeat the exact `--rerun` command to resume it, not to dispatch
again. An unfinished original batch must be resumed **without** `--rerun`.
Unresolved cleanup blocks a new generation. Retained supervisor-review forks
are never deleted by rerun; remove them manually before new provisioning, or
the controller will safely reject the existing fork. `--resume-only` and
`--rerun` cannot be combined.

Run `--list` first to preview repository IDs and positions without GitHub
requests, credential loading, fork creation or CI dispatch. A preview is not
an eligibility or safety verdict. `--check-config` validates flags and the
effective range but does not require the CSV file to exist.

Example for a 500-row shared evaluation dataset, divided into five non-overlapping
100-row batches:

| Member | Batch ID | Start | Stop |
| ------ | -------- | ----: | ---: |
| 1      | team-01  |     1 |  100 |
| 2      | team-02  |   101 |  200 |
| 3      | team-03  |   201 |  300 |
| 4      | team-04  |   301 |  400 |
| 5      | team-05  |   401 |  500 |

**Windows PowerShell**

```powershell
.\.venv\Scripts\python.exe -m evaluation.fork_pipeline --config evaluation/configs/fork_pilot.json --batch-id team-02 --start-at 101 --stop-at 200 --list
# After the study and live-safety preflight, execute and resume with identical flags:
.\.venv\Scripts\python.exe -m evaluation.fork_pipeline --config evaluation/configs/fork_pilot.json --batch-id team-02 --start-at 101 --stop-at 200 --watch
# Rerun this finished batch with a new, evidence-preserving generation:
.\.venv\Scripts\python.exe -m evaluation.fork_pipeline --config evaluation/configs/fork_pilot.json --batch-id team-02 --start-at 101 --stop-at 200 --rerun --watch
```

**Linux Bash**

```bash
./.venv/bin/python -m evaluation.fork_pipeline --config evaluation/configs/fork_pilot.json --batch-id team-02 --start-at 101 --stop-at 200 --list
# After the study and live-safety preflight, execute and resume with identical flags:
./.venv/bin/python -m evaluation.fork_pipeline --config evaluation/configs/fork_pilot.json --batch-id team-02 --start-at 101 --stop-at 200 --watch
# Rerun this finished batch with a new, evidence-preserving generation:
./.venv/bin/python -m evaluation.fork_pipeline --config evaluation/configs/fork_pilot.json --batch-id team-02 --start-at 101 --stop-at 200 --rerun --watch
```

These examples describe the future team evaluation, **not permission to launch
the 500-repository sample before the development smoke and evidence export
have been completed**. Do not start overlapping controllers for the same
batch or target repositories.

### Live evaluation progress and fork workflow activation

The local controller now prints timestamped stages for preparation, optimizer
B/C decisions, validation admission, fork creation, harness setup, workflow
registration, arm branches, CI dispatch and run status, measurements, and fork
retention/deletion. Workflow runs still execute on GitHub Actions in the
research-owned candidate fork, never on the CloudTune repository.

GitHub can disable individual workflows on new public forks even when
repository-level Actions is enabled. After registering the common dispatch
harness, the controller checks the workflow ID and state, uses GitHub's
idempotent `PUT /repos/{owner}/{repo}/actions/workflows/{workflow_id}/enable`
only when needed, and re-checks for `active` before making arm branches or
dispatches. The research token needs **Actions: write** permission.

The controller logs are intentionally operational diagnostics, not immutable
research results. State files, original workflow snapshots and raw job timing
remain authoritative. An existing experiment ID freezes the evaluator code;
**after applying this patch, start a NEW `dev-` evaluation ID** for further
live work, rather than changing the frozen implementation of a completed or
pending trial. Preserve any retained forks for review until manually cleared.

### Reviewed `setup-node` npm download-cache admission (policy v2)

The common B/C admission gate can now approve one exact additive edit:
adding `with.cache: npm` to an existing `actions/setup-node@v4` step.
All other step fields and inputs, triggers, jobs, test commands, matrix,
permissions, and checkout behavior must remain unchanged. Approval also
requires a checkout before setup-node, an untampered frozen root
`package-lock.json` or `npm-shrinkwrap.json`, and a subsequent root npm install.
This caches npm package downloads, **not** `node_modules` artifacts.

Adding concurrency cancellation, changing checkout depth or job commands,
adding a cache-dependency-path override, and injecting broader cache steps
remain under the pre-existing safety policy; they are **not** auto-approved.
A missing root lockfile or a non-root npm installation requires review.
Candidate validity is not proof of a runtime speedup; measure it on GitHub.
Prior validation evidence is immutable: use a **new** `dev-` evaluation ID after
this policy change, and never reuse a prior trial's saved rejection as PASS.

### Offline A/B/C admission preflight (no research fork)

For a complete development-only A/B/C comparison, first run the existing local
fork controller with `--preflight`. It performs **read-only GitHub screening**,
freezes A, generates B using pinned source-corrected ci-cost, generates C using
the frozen Supabase/BGE-M3 index and free OpenRouter model, then archives both
validation outcomes. Supabase and OpenRouter calls can incur quota use; no
forks, GitHub writes, candidate branches or Actions dispatches occur.

The trial must use a fresh `dev-` evaluation ID and a separately screened,
non-held-out development repository. On completion, inspect `fork_report.json`,
the exact B/C `change.patch` files and immutable `validation.json` artifacts.
`PREFLIGHT_READY` means both B and C received **PASS** under the common gate,
not that either has completed CI or saved time. `PREFLIGHT_BLOCKED` indicates
one or both optimized arms were rejected, required review, or abstained;
exit status 2 is expected, and **no fork is created**. Do not manually modify
generated YAML, relax policy to force PASS, or retroactively validate an old ID.

After **independent review** of the eligible source, B/C diffs, GitHub token,
remaining Actions minutes and fork cleanup policy, use the **same frozen ID**
with `--watch --require-all-arms`. The latter flag also prevents a new fork
when either optimized arm is not admitted. Without this flag, the existing
controller still permits scientifically labeled incomplete/baseline-only runs.

**PowerShell (run from the repository root):**

```powershell
.\.venv\Scripts\python.exe -m evaluation.fork_pipeline --config evaluation/results/development_smoke.json --preflight
# ONLY after both B and C PASS and fork/budget safety is reviewed:
.\.venv\Scripts\python.exe -m evaluation.fork_pipeline --config evaluation/results/development_smoke.json --watch --require-all-arms
```

**Linux Bash (run from the repository root):**

```bash
./.venv/bin/python -m evaluation.fork_pipeline --config evaluation/results/development_smoke.json --preflight
# ONLY after both B and C PASS and fork/budget safety is reviewed:
./.venv/bin/python -m evaluation.fork_pipeline --config evaluation/results/development_smoke.json --watch --require-all-arms
```

### Development-only fork execution smoke (no held-out repository)

The A/B/C fork controller now supports a separately labeled, bounded development
smoke. This is **not** an evaluation outcome and must not use a held-out
repository, a pre-existing fork, or a repository with deployment/publishing
workflows. Its cleanup pins the fork's immutable numeric GitHub repository ID,
not merely its name, before any DELETE. A missing or mismatched ID prevents
automatic deletion and requires manual review. GitHub Actions run evidence is
still archived before cleanup, and uncertain DELETE responses are never retried
blindly.

1. Pick **one** development repository that is absent from the held-out 4,000
   repositories and the excluded training/batch case list. Review the workflow's
   runner, permissions, job commands and expected spending first. It must be safe
   for a research-owned fork. The preparation screen rejects excluded repositories.
2. In `evaluation/results/development_repositories.csv` (ignored by Git), write
   exactly `repo_id,split` on the first line and `OWNER/REPO,development` on the
   second line, substituting an authorized public development repository.
3. Copy `evaluation/configs/development_smoke.example.json` to
   `evaluation/results/development_smoke.json` (ignored by Git). Use a **new** `dev-` prefixed
   `evaluation_id` for each independent trial. Keep `repository_limit: 1` and
   `repetitions: 3`; never change an existing evaluation's frozen config.
   Exactly three measured repetitions are required for each admitted arm.
   If B/C are not admitted, their non-execution remains explicit; do not
   invent timing measurements or force unsafe workflows to run.
4. Run offline tests and `--check-config` first. For a real dispatch, use a
   dedicated authorized GitHub token and reviewed Supabase/OpenRouter credentials
   in the ignored `.env`. **Only the explicit non-check command below writes to
   GitHub.** It creates and deletes a research-owned candidate fork.

**Resuming long GitHub queues:** The hosted controller keeps polling a pending
run without a local time limit. Restart with the **same evaluation ID without
`--rerun`** after interruption; the saved dispatch is observed rather than
sent again. `--rerun` intentionally starts a NEW numbered generation after the
previous generation has finalized. Hosted GitHub Actions still applies its
own platform limits. Queue time stays excluded from measured execution time.

**Windows PowerShell**

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m evaluation.fork_pipeline --config evaluation/results/development_smoke.json --check-config
# Only after verifying repository selection, credentials, and deletion permissions:
.\.venv\Scripts\python.exe -m evaluation.fork_pipeline --config evaluation/results/development_smoke.json --watch
```

**Linux Bash**

```bash
./.venv/bin/python -m unittest discover -s tests -v
./.venv/bin/python -m evaluation.fork_pipeline --config evaluation/results/development_smoke.json --check-config
# Only after verifying repository selection, credentials, and deletion permissions:
./.venv/bin/python -m evaluation.fork_pipeline --config evaluation/results/development_smoke.json --watch
```

Do not run the last command until the research token's fork-creation,
Actions-dispatch, and deletion rights have been reviewed. This development
smoke can legitimately produce only A if B/C abstain or fail validation; record
that result without claiming a complete A/B/C speedup. A completed mocked test
suite alone does not establish live GitHub run or deletion correctness.

### RAG integration verification (local, remote, retrieval, synthetic smoke)

Run these modes **in order**. `local` verifies the frozen on-disk hash with no
network access. `remote` reads and audits the existing Supabase index without
loading BGE-M3. `retrieve` additionally loads BGE-M3 on the selected local
CPU/GPU and searches the index. `smoke` additionally calls the **pinned free
OpenRouter generator** with a synthetic, non-held-out workflow. `smoke` can
use free-model quota and is **not** a measured CI experiment. None of these
modes uploads embeddings, modifies Supabase, creates forks or dispatches CI.

For `remote`, `retrieve`, and `smoke`, provide `SUPABASE_URL` and either
`SUPABASE_SECRET_KEY` or `SUPABASE_SERVICE_ROLE_KEY` through the root `.env`
or exported environment. `smoke` additionally requires `OPENROUTER_API_KEY`.
The generator model and token limit come from `evaluation/configs/fork_pilot.json`,
**not** `OPENROUTER_MODEL` / `OPENROUTER_MAX_TOKENS` in `.env`. Keep credentials
out of Git and logs. Install `requirements-rag.txt` before retrieval/smoke;
follow the CPU/CUDA setup instructions in Section 3.

**Windows PowerShell**

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_rag_pipeline.py -v
.\.venv\Scripts\python.exe -m evaluation.rag_verification --mode local
.\.venv\Scripts\python.exe -m evaluation.rag_verification --mode remote
.\.venv\Scripts\python.exe -m evaluation.rag_verification --mode retrieve
.\.venv\Scripts\python.exe -m evaluation.rag_verification --mode smoke
```

**Linux Bash**

```bash
./.venv/bin/python -m unittest discover -s tests -p 'test_rag_pipeline.py' -v
./.venv/bin/python -m evaluation.rag_verification --mode local
./.venv/bin/python -m evaluation.rag_verification --mode remote
./.venv/bin/python -m evaluation.rag_verification --mode retrieve
./.venv/bin/python -m evaluation.rag_verification --mode smoke
```

A successful local preflight is **not** proof that the live Supabase index,
OpenRouter generation, or fork-based GitHub Actions execution works. Preserve
existing implementation and experimental evidence. On Windows, Git CRLF
checkout conversion can change the frozen JSONL corpus SHA256; preserve its
committed LF bytes rather than changing the pinned dataset hash or re-ingesting
it. Confirm `remote`, `retrieve`, and optional `smoke` independently before
claiming the RAG integration is live-verified.
