# Repository data preparation

## Source and initial sample

Repository metadata comes from Cardoen et al.'s [GitHub Actions workflow history dataset](https://doi.org/10.1145/3643991.3644867), using the [Zenodo 2026-05-22 release](https://doi.org/10.5281/zenodo.20340547). Its source list was collected on 26 March 2026. The project verified the source archive checksum, retained 54,758 unique repository rows, applied its recency filter (updated since 27 October 2025), and uniformly sampled 5,000 repositories without replacement using seed `20261027`.

The source repositories were pre-screened as non-forks with at least 300 commits, at least 100 stars, recent activity, and a `.github/workflows` directory. These are candidate repositories; the metadata does not confirm current activity or that a repository fits a particular optimization.

## Development and evaluation split

The 500-row `pattern_repo_candidates_20.csv` pool (25 patterns × 20 candidates) is reserved for development. Evaluation candidates found in earlier experiment records are excluded to reduce repository overlap. Of 4,500 eligible repositories, 4,000 were uniformly sampled without replacement using seed `20261031`; 500 remain unused. The evaluation manifest found 207 prior-case repository IDs, 98 of which overlap the source list; all source overlaps were already in the development pool, so no additional source repositories were excluded.


## Reproducibility files

- Initial sample and checksum/filter details: `research-data/zenodo_20340547/selection_manifest.json`
- Development candidates: `research-data/zenodo_20340547/pattern_repo_candidates_20.csv`
- Held-out sample and SHA-256: `evaluation/evaluation_repositories_4000.csv` and `evaluation/evaluation_repositories_4000_manifest.json`
- Four assignment files and hashes: `evaluation/assignments/manifest.json`
- Builders: `scripts/create_zenodo_repo_dataset.py`, `evaluation/build_evaluation_repo_dataset.py`, and `evaluation/prepare_evaluation_assignments.py`

The Zenodo snapshot reflects metadata through 26 March 2026; it is not a live repository eligibility check. Pattern assignments are screening leads, not confirmed pattern matches.
