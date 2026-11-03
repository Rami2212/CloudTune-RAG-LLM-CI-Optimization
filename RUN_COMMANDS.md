# Run commands

For local BGE-M3 embeddings, Supabase setup, ingestion, and semantic search, see [RUN_RAG_COMMANDS.md](RUN_RAG_COMMANDS.md).

Held-out evaluation members: **1 — Ishara, 2 — Ramitha, 3 — Isuru, 4 — Hiruni**.
Use your member number with `scripts.run_evaluation_batch`; see the
[evaluation assignment table](evaluation/BATCH_EVALUATION_GUIDE.md#1-fixed-and-reproducible-assignments).
The pattern-training CSV ranges below are a separate assignment.

## Evaluation quick access

Run these commands from the project root. The run command also resumes an
interrupted batch. Use the rerun command to retry only failed or blocked
repositories in the same batch, preserving earlier generations.

### Ishara — member 1

```powershell
# Run or resume
.\.venv\Scripts\python.exe -m scripts.run_evaluation_batch --member 1 --run
# Rerun failed repositories only
.\.venv\Scripts\python.exe -m scripts.run_evaluation_batch --member 1 --run --rerun
```

### Ramitha — member 2

```powershell
# Run or resume
.\.venv\Scripts\python.exe -m scripts.run_evaluation_batch --member 2 --run
# Rerun failed repositories only
.\.venv\Scripts\python.exe -m scripts.run_evaluation_batch --member 2 --run --rerun
```

### Isuru — member 3

```powershell
# Run or resume
.\.venv\Scripts\python.exe -m scripts.run_evaluation_batch --member 3 --run
# Rerun failed repositories only
.\.venv\Scripts\python.exe -m scripts.run_evaluation_batch --member 3 --run --rerun
```

### Hiruni — member 4

```powershell
# Run or resume
.\.venv\Scripts\python.exe -m scripts.run_evaluation_batch --member 4 --run
# Rerun failed repositories only
.\.venv\Scripts\python.exe -m scripts.run_evaluation_batch --member 4 --run --rerun
```

## Pattern-training commands

```powershell
# One-time setup
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env

# Run or resume the batch
.\.venv\Scripts\python.exe scripts\run_pattern_batch.py

# Inclusive CSV ranges (new 500-repository dataset)

# Ramitha
.\.venv\Scripts\python.exe scripts\run_pattern_batch.py --start-at 1 --stop-at 125

# Ishara
.\.venv\Scripts\python.exe scripts\run_pattern_batch.py --start-at 126 --stop-at 250

# Isuru
.\.venv\Scripts\python.exe scripts\run_pattern_batch.py --start-at 251 --stop-at 375

# Hiruni
.\.venv\Scripts\python.exe scripts\run_pattern_batch.py --start-at 376 --stop-at 500

# Repeat a finished row in the same batch
.\.venv\Scripts\python.exe scripts\run_pattern_batch.py --start-at 20 --stop-at 20 --rerun

```
