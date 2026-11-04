# Windows Evaluation Setup

Use this guide on Windows 10/11 with PowerShell. All members should use the same approved repository revision, evaluation settings, and free OpenRouter model/token ceiling.

## 1. Install and clone

Install Git, Python 3.12, Node.js 20+, and actionlint. For example, in PowerShell:

```powershell
winget install --id Git.Git --exact
winget install --id Python.Python.3.12 --exact
winget install --id OpenJS.NodeJS.LTS --exact
winget install --id rhysd.actionlint --exact
```

Restart PowerShell, then clone the approved revision and install dependencies:

```powershell
git clone https://github.com/Rami2212/CloudTune-RAG-LLM-CI-Optimization.git
Set-Location .\CloudTune-RAG-LLM-CI-Optimization
git rev-parse HEAD
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-rag.txt
```

Record the commit hash and coordinate so all four members use the same revision. Check that `py -3.12`, `git`, `node`, `npm`, and `actionlint` run from PowerShell.

## 2. Configure credentials

Create a private `.env` from `.env.example` and enter authorized credentials and the agreed settings:

```powershell
Copy-Item .env.example .env
notepad .env
```

Set `GITHUB_USERNAME`, `GITHUB_TOKEN`, `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `OPENROUTER_MAX_TOKENS`, `SUPABASE_URL`, and `SUPABASE_SECRET_KEY`. Set `CLOUDTUNE_AUTO_DELETE_FORKS=false` to retain evidence forks. Keep `.env` private and never commit it. The default RAG device is CPU.

## 3. Verify evaluation tools and data

Install and verify the pinned CI-Cost tool used for Arm B:

```powershell
.\.venv\Scripts\python.exe -m evaluation.third_party.ci_cost.setup
.\.venv\Scripts\python.exe -m evaluation.third_party.ci_cost.setup --verify
```

Verify the frozen RAG corpus used for Arm C:

```powershell
.\.venv\Scripts\python.exe -m evaluation.rag_verification --mode local
.\.venv\Scripts\python.exe -m evaluation.rag_verification --mode remote
.\.venv\Scripts\python.exe -m evaluation.rag_verification --mode retrieve
```

Each check should report its corresponding `*_VERIFIED` status. Confirm the four committed member assignments and manifest exist. The assignment builder verifies them and will stop if data does not match:

```powershell
.\.venv\Scripts\python.exe -m evaluation.prepare_evaluation_assignments
```

## 4. Preview and run your assignment

Member positions are local to each 1,000-repository assignment: member 1 is Ishara, 2 Ramitha, 3 Isuru, and 4 Hiruni. Preview without running hosted CI:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_evaluation_batch --member 2 --list
```

Run the full assignment:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_evaluation_batch --member 2 --run
```

The three arms are Original (A), CI-Cost (B), and RAG + LLM (C). The runner creates research-owned forks and dispatches GitHub Actions there; it does not run candidate workflows locally.

To name a batch, set `--batch-name`; it defaults to the batch ID. To provide a custom batch ID, use `--batch-id` as well. Example, running positions 20-25:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_evaluation_batch --member 2 --batch-id eval-member-02 --batch-name "November run" --run --start-at 20 --stop-at 25
```

Positions include both endpoints. `--start-position` and `--stop-position` are aliases; use `--limit` instead of a stop option if preferred. Resume interrupted work with the same member, batch ID, settings, and range.

By default, batch settings are frozen. To change configuration in the same batch, add `--allow-config-changes`. If you also want to rerun selected positions that already have results, add `--override-existing`; earlier results are kept in prior trial generations. Do not override while CI work is active or pending. Keep the range narrow: a changed batch can contain results from multiple settings revisions. Member, batch ID, and assignment cannot be changed within a batch.

## 5. Publish results

Refresh published summaries without rerunning CI, then merge the four members' published results when available:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_evaluation_batch --member 2 --publish-only
.\.venv\Scripts\python.exe -m scripts.merge_evaluation_results
```

The merged cohort retains all 4,000 assigned rows, including blocked, skipped, or incomplete cases. Resolve assignment mismatches, failed tool/corpus verification, or a changed shared revision before continuing the evaluation.
