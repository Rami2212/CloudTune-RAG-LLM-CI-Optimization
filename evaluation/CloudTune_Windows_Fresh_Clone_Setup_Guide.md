# CloudTune Evaluation — Windows Fresh-Clone Setup Guide

**Platform:** Windows 10/11, PowerShell.  
**Purpose:** Set up a fresh clone to run the existing three-arm (A: original, B: source-corrected CI-Cost, C: RAG + LLM) evaluation of the frozen 4,000-repository cohort.  
**Audience:** Any of the four research members. No branch-specific steps are required.

> **Before starting:** Clone a revision that already includes the evaluation workspace changes, the four `evaluation/assignments/member_01.csv`–`member_04.csv` files, and `evaluation/assignments/manifest.json`. Those files must be committed before teammates clone. Do not use unpublished changes from someone else's computer.

## 1. Install required software

Install the following on each Windows workstation, then restart PowerShell:

- **Git** and **Python 3.12** (64-bit; the guide uses the Windows `py` launcher). Use a supported Python version consistently across members.
- **Node.js 20+ with npm** to compile the pinned CI-Cost baseline **locally**. Candidate repositories' CI is never run locally.
- **actionlint** (Windows executable available from [rhysd/actionlint releases](https://github.com/rhysd/actionlint/releases)); ensure `actionlint.exe` is on `PATH`.
- Internet access to GitHub, PyPI, npm, Hugging Face, the existing Supabase RAG corpus, and OpenRouter.

Verify in **PowerShell**:

```powershell
py -3.12 --version
git --version
node --version
npm --version
actionlint --version
```

If `py -3.12` is unavailable, install Python 3.12 before continuing. Do not silently substitute a different interpreter partway through the study.

## 2. Clone and install Python dependencies

```powershell
git clone https://github.com/Rami2212/CloudTune-RAG-LLM-CI-Optimization.git
Set-Location .\CloudTune-RAG-LLM-CI-Optimization

git rev-parse HEAD
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-rag.txt
```

Record the `git rev-parse HEAD` value. **All four members must use the same approved evaluation revision** for a comparable study; coordinate any code changes before new measurements.

The default RAG device is CPU. An NVIDIA GPU is optional and must be configured consistently; this guide does not change PyTorch/CUDA settings.

## 3. Create a private `.env`

```powershell
Copy-Item .env.example .env
notepad .env
```

Set the following keys to your **own authorized credentials** and the agreed experimental settings:

```dotenv
GITHUB_USERNAME=YOUR_RESEARCH_GITHUB_ACCOUNT
GITHUB_TOKEN=YOUR_AUTHORIZED_GITHUB_TOKEN
OPENROUTER_API_KEY=YOUR_OPENROUTER_KEY
OPENROUTER_MODEL=YOUR_AGREED_AVAILABLE_FREE_MODEL
OPENROUTER_MAX_TOKENS=24000
SUPABASE_URL=YOUR_EXISTING_POPULATED_SUPABASE_URL
SUPABASE_SECRET_KEY=YOUR_AUTHORIZED_SERVER_KEY
CLOUDTUNE_AUTO_DELETE_FORKS=false
CLOUDTUNE_RAG_DEVICE=cpu
```

**Important:** `CLOUDTUNE_AUTO_DELETE_FORKS=false` is required by the team batch runner. The stock `.env.example` may say `true`; change it to `false` in your private `.env`. Forks then remain for evidence review and may consume account limits; manually clean them up _after_ research review.

Use the **same agreed free OpenRouter model and token ceiling across the four members**. The local loader does not overwrite nonempty environment variables already exported in PowerShell, so check any session-level overrides. Never commit `.env` or paste credentials into logs.

Do **not** set `CI_COST_DIR` unless you intentionally use a reviewed custom installation. The default installation path is `.venv/ci-cost`—not an older `evaluation/results/.tools/ci-cost-npm-download-v4` directory. The string `npm-download-v4` may legitimately remain in the scientific `source_fix_revision` metadata; it is not an installation folder name.

## 4. Install and verify CI-Cost (Arm B)

The installer checks out the **pinned upstream Git commit**, applies the reviewed TypeScript source fixes, compiles the CLI, and verifies it. This downloads third-party source on the workstation, **not** a candidate repository's CI workflow.

```powershell
.\.venv\Scripts\python.exe -m evaluation.third_party.ci_cost.setup
.\.venv\Scripts\python.exe -m evaluation.third_party.ci_cost.setup --verify
```

The expected tool folder is `.venv\ci-cost`. Installation needs Git, Node.js, npm and working network access. If verification fails, **stop**; do not change the pinned tool revision or accept an unverified CLI for the evaluation.

## 5. Verify frozen RAG and dependencies (Arm C)

The RAG dataset is frozen; do **not** retrain or re-ingest it during evaluation.

```powershell
.\.venv\Scripts\python.exe -m evaluation.rag_verification --mode local
.\.venv\Scripts\python.exe -m evaluation.rag_verification --mode remote
.\.venv\Scripts\python.exe -m evaluation.rag_verification --mode retrieve
```

Expected statuses are `LOCAL_CORPUS_VERIFIED`, `REMOTE_CORPUS_VERIFIED`, and `RAG_RETRIEVAL_VERIFIED`, respectively. The remote/retrieve checks require the existing populated Supabase corpus and may download the `BAAI/bge-m3` embedding model. If a verification fails, resolve it before running experiments. An optional `--mode smoke` **calls OpenRouter** on a synthetic fixture; it is not a held-out measurement or GitHub Actions run.

## 6. Verify assignments and run offline tests

The evaluation source CSV is `evaluation/evaluation_repositories_4000.csv`. The four assignments are consecutive groups of 1,000 rows **without reshuffling**. If already committed, the builder verifies them rather than replacing them.

```powershell
.\.venv\Scripts\python.exe -m evaluation.prepare_evaluation_assignments
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Confirm the four CSVs and manifest exist:

```powershell
Get-ChildItem .\evaluation\assignments\member_*.csv
Get-Item .\evaluation\assignments\manifest.json
```

The assignment builder rejects altered source files or mismatched assignments. Do not bypass a mismatch. Investigate any failed or skipped tests, particularly CI-Cost integration tests, before hosted work.

If your cloned revision contains the workspace-preparation script, you can also perform a **non-destructive** assignment/setup check:

```powershell
.\.venv\Scripts\python.exe -m scripts.prepare_evaluation_workspace
```

**Do not** run `--reset-results --confirm-reset` during an active or resumable evaluation; it deletes local checkpoint evidence.

## 7. Select your member and preview the work

Each member receives a different 1,000-repository assignment:

| Member | Name    | Assignment CSV                         | Default batch ID |
| ------ | ------- | -------------------------------------- | ---------------- |
| 1      | Ishara  | `evaluation/assignments/member_01.csv` | `eval-member-01` |
| 2      | Ramitha | `evaluation/assignments/member_02.csv` | `eval-member-02` |
| 3      | Isuru   | `evaluation/assignments/member_03.csv` | `eval-member-03` |
| 4      | Hiruni  | `evaluation/assignments/member_04.csv` | `eval-member-04` |

Choose **one member number** and preview the assigned repository order without dispatching anything (replace `1` with your member number):

```powershell
.\.venv\Scripts\python.exe -m scripts.run_evaluation_batch --member 1 --list
```

After the team has approved the environment, protocol and GitHub Actions budget, the run command is:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_evaluation_batch --member 1 --run
```

This command can create forks and dispatch real GitHub Actions runs on **research-owned candidate forks**, not on the original repositories or the CloudTune repository. GitHub Actions queue time is excluded from measured execution time. The pipeline evaluates original **A**, reviewed CI-Cost **B**, and frozen RAG+LLM **C**; the LLM-only D arm is not included.

If interrupted, **resume using exactly the same member, batch ID, and command**. Never delete a partially completed batch folder to make it restart. To specify an additional, separate experiment, supply an explicit unique `--batch-id` and keep those results separate from the primary cohort.

## 8. Publish and merge results safely

The team runner writes commit-eligible evidence to `evaluation/results/<batch-id>/published/` and private resume checkpoints to `evaluation/results/<batch-id>-rNNNN/`. The committed `evaluation/results/.gitignore` should allow only published summaries and reject raw checkpoint state, prompts and secrets.

For one member, refresh local published summaries **without rerunning hosted CI**:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_evaluation_batch --member 1 --publish-only
```

Stage only allowable outputs, then inspect:

```powershell
git add evaluation/assignments evaluation/results
git diff --cached --check
git diff --cached --name-only
```

Once all four member batches' published results are available locally, merge them:

```powershell
.\.venv\Scripts\python.exe -m scripts.merge_evaluation_results
```

The combined file is `evaluation/results/cohort/published/attempts_4000.csv`. It retains all 4,000 source rows, including skipped, blocked and incomplete cases; it does **not** fabricate measurements.

**Stop conditions:** mismatched assignment hashes, unverified CI-Cost, incorrect or missing RAG corpus, failures in required tests, unexpected model changes, unresolved queued Actions, or a changed shared evaluation commit. Resolve these before continuing the held-out experiment.
