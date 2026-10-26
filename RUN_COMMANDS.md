# Run commands

```powershell
# One-time setup
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env

# Run or resume the batch
.\.venv\Scripts\python.exe scripts\run_pattern_batch.py

# Start at row 20 and run one repository

Ramitha
.\.venv\Scripts\python.exe scripts\run_pattern_batch.py --start-at 1 --limit 125 --rerun

Ishara
.\.venv\Scripts\python.exe scripts\run_pattern_batch.py --start-at 126 --limit 250 --rerun

Isuru
.\.venv\Scripts\python.exe scripts\run_pattern_batch.py --start-at 251 --limit 375 --rerun

Hiruni
.\.venv\Scripts\python.exe scripts\run_pattern_batch.py --start-at 376 --limit 500 --rerun

```