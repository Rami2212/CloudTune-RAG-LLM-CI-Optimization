# New scenario commands

```powershell
# Uses the existing .env and scenario-three-runs-v1 batch
.\.venv\Scripts\python.exe scripts\run_new_scenario_batch.py --list
.\.venv\Scripts\python.exe scripts\run_new_scenario_batch.py --start-at 1 --stop-at 500

# Run one new pattern in that same batch
.\.venv\Scripts\python.exe scripts\run_new_scenario_batch.py --pattern P-LIT-PRIORITIZE
.\.venv\Scripts\python.exe scripts\run_new_scenario_batch.py --pattern P-LIT-SELECT
.\.venv\Scripts\python.exe scripts\run_new_scenario_batch.py --pattern P-LIT-BAZEL-PARALLEL
.\.venv\Scripts\python.exe scripts\run_new_scenario_batch.py --pattern P-LIT-UNAFFECTED-STEPS
.\.venv\Scripts\python.exe scripts\run_new_scenario_batch.py --pattern P-LIT-SMELL-REPAIR
.\.venv\Scripts\python.exe scripts\run_new_scenario_batch.py --pattern P-LIT-UNUSED-OUTPUTS
.\.venv\Scripts\python.exe scripts\run_new_scenario_batch.py --pattern P-LIT-UNUSED-DEP-SKIP
.\.venv\Scripts\python.exe scripts\run_new_scenario_batch.py --pattern P-LIT-BAZEL-INCREMENTAL
.\.venv\Scripts\python.exe scripts\run_new_scenario_batch.py --pattern P-LIT-BAZEL-DEPS
.\.venv\Scripts\python.exe scripts\run_new_scenario_batch.py --pattern P-LIT-ENV-CACHE

# Resume an original existing scenario pattern after fixing fork preparation
.\.venv\Scripts\python.exe scripts\run_scenario_batch.py --pattern P-LIT-BUILD-SELECT --rerun
.\.venv\Scripts\python.exe scripts\run_scenario_batch.py --pattern P-LIT-DURATION-PREDICTION --rerun

# If a prepared attempt reports that its replay engine changed, rerun its exact row
.\.venv\Scripts\python.exe scripts\run_new_scenario_batch.py --start-at 201 --stop-at 201 --rerun
```
