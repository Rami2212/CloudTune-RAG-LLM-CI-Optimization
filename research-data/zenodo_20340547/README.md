# Zenodo GitHub Actions repository sample

`repositories_5000.csv` is a 5,000-repository sample from the repository metadata published with [Zenodo record 20340547](https://zenodo.org/records/20340547).

## Selection

- The source contains 54,758 repositories with GitHub Actions workflow histories.
- Kept repositories whose source `updated` date is on or after 2025-10-27 (46,068 met this cutoff).
- Selected 5,000 uniformly at random without replacement, using seed `20261027`.
- Repository IDs are unique within this sample.
- The source dataset selected non-fork repositories with at least 300 commits, 100 stars, recent activity, and a `.github/workflows` directory.

The source was collected on 2026-03-26. The sample is a candidate list; repository activity and workflow contents have not been refreshed or individually matched to a specific optimization pattern since then.

## Files

- `repositories_5000.csv` — repository IDs, GitHub URLs, and source metadata.
- `selection_manifest.json` — source checksum, selection criteria, counts, and random seed.
- `source/repositories.csv.gz` — downloaded Zenodo source file (MD5 verified).

To regenerate the sample:

```powershell
.\.venv\Scripts\python.exe scripts\create_zenodo_repo_dataset.py
```
