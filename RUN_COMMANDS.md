# Run commands

For local BGE-M3 embeddings, Supabase setup, ingestion, and semantic search, see [RUN_RAG_COMMANDS.md](RUN_RAG_COMMANDS.md).

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
