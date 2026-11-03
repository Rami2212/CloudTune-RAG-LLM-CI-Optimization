# Held-out repository assignments

The source of truth is `evaluation/evaluation_repositories_4000.csv`.
The deterministic builder `evaluation/prepare_evaluation_assignments.py` keeps
all source metadata, source-row order, and held-out `split=evaluation` status.
No repository is selected based on an optimization outcome.

| Member | Name    | CSV             | Original source rows | Member-local rows |
| ------ | ------- | --------------- | -------------------: | ----------------: |
| 1      | Ishara  | `member_01.csv` |               1–1000 |            1–1000 |
| 2      | Ramitha | `member_02.csv` |            1001–2000 |            1–1000 |
| 3      | Isuru   | `member_03.csv` |            2001–3000 |            1–1000 |
| 4      | Hiruni  | `member_04.csv` |            3001–4000 |            1–1000 |

From the project root, Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m evaluation.prepare_evaluation_assignments
```

It generates four CSV files plus `manifest.json`, with each file's SHA-256.
Run the command again to verify; it refuses to overwrite a modified assignment
or a modified manifest. Commit the generated assignments and manifest before
starting the held-out experiment. A CSV row is **not** evidence of a completed
experiment. See [Batch Evaluation Guide](../BATCH_EVALUATION_GUIDE.md).
