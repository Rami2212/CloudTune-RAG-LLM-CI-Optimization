# Scenario run commands

```powershell
# Setup: use the same .env keys as the main experiment script
if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env

# Preview supported rows; no GitHub or LLM requests
.\.venv\Scripts\python.exe scripts\run_scenario_batch.py --list

# Run all ten supported patterns, or resume the same batch
.\.venv\Scripts\python.exe scripts\run_scenario_batch.py
# Change OPENROUTER_MODEL in .env, then rerun the same command to continue this batch with that model

# Run supported scenarios in inclusive original CSV positions
.\.venv\Scripts\python.exe scripts\run_scenario_batch.py --start-at 1 --stop-at 500

# Repeat a finished case in the same batch
.\.venv\Scripts\python.exe scripts\run_scenario_batch.py --start-at 21 --stop-at 21 --rerun

# Optional: independent batch for one pattern
.\.venv\Scripts\python.exe scripts\run_scenario_batch.py --pattern P-LIT-FAIL-FAST --batch-id scenario-fail-fast-v1
.\.venv\Scripts\python.exe scripts\run_scenario_batch.py --pattern P-LIT-CANCEL-STALE --batch-id scenario-cancel-stale-v1
.\.venv\Scripts\python.exe scripts\run_scenario_batch.py --pattern P-LIT-SKIP-WORKFLOW --batch-id scenario-skip-workflow-v1
.\.venv\Scripts\python.exe scripts\run_scenario_batch.py --pattern P-LIT-CHANGE-FILTER --batch-id scenario-change-filter-v1
.\.venv\Scripts\python.exe scripts\run_scenario_batch.py --pattern P-LIT-FAIL-SCHEDULE --batch-id scenario-fail-schedule-v1
.\.venv\Scripts\python.exe scripts\run_scenario_batch.py --pattern P-LIT-IDLE-SCHEDULE --batch-id scenario-idle-schedule-v1
.\.venv\Scripts\python.exe scripts\run_scenario_batch.py --pattern P-LIT-FAILED-JOB-FIRST --batch-id scenario-failed-job-first-v1
.\.venv\Scripts\python.exe scripts\run_scenario_batch.py --pattern P-LIT-BUILD-PRIORITY --batch-id scenario-build-priority-v1
.\.venv\Scripts\python.exe scripts\run_scenario_batch.py --pattern P-LIT-BUILD-SELECT --batch-id scenario-build-select-v1
.\.venv\Scripts\python.exe scripts\run_scenario_batch.py --pattern P-LIT-DURATION-PREDICTION --batch-id scenario-duration-prediction-v1

# Offline implementation checks: no remote requests
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_scenario*.py"
```
