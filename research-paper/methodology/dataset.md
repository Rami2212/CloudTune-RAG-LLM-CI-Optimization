# Repository dataset preparation

## Source

Repository metadata comes from Cardoen's [GitHub Actions workflow-history dataset](https://doi.org/10.1145/3643991.3644867), using its [2026-05-22 Zenodo release](https://doi.org/10.5281/zenodo.20340547). The source snapshot was collected through 26 March 2026.

## Preparation and split

- Verified the downloaded archive checksum and retained 54,758 unique repository records.
- Kept repositories updated since 27 October 2025, leaving 46,068 candidates.
- Uniformly sampled 5,000 repositories without replacement using seed `20261027`. Source screening required a non-fork, at least 300 commits, at least 100 stars, recent activity, and a workflow directory.
- Reserved 500 development candidate IDs. Excluded these and repositories already represented in experiment records; all source overlaps from prior experiment records were already in the development pool.
- Uniformly sampled 4,000 evaluation repositories from the remaining 4,500 using seed `20261031`; 500 remained unused.

The current literature pattern catalog contains 16 patterns. Repository assignments are candidate leads, not confirmed pattern matches. The historical metadata snapshot does not prove current repository activity or evaluation eligibility; repositories are screened again before evaluation.
