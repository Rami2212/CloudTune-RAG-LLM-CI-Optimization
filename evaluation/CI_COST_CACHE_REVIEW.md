# CI-Cost npm cache admission review

Historical decision recorded before general candidate admission. Protocol v9
no longer blocks candidates based on optimization type or requires npm lockfile
evidence. The review below documents why the older npm-cache-only policy was
introduced; existing archived trial verdicts remain unchanged.

Reviewed 2026-11-02 against source-fix v2 and admission policy v4.

## Decision

Keep the existing CI-Cost npm cache proposal at REVIEW_REQUIRED. Do not
retroactively approve archived candidates or weaken the common B/C gate.
This is a static review, not independent runtime equivalence evidence.

## Evidence

The compiled optimizer inserts actions/cache@v4 with path node_modules,
key `${{ runner.os }}-node-${{ hashFiles('**/package-lock.json') }}`, and
restore prefix `${{ runner.os }}-node-`. The key does not distinguish Node
versions or architectures. Restore prefixes can select a different dependency
graph. The recursive lockfile pattern cannot be established from the preparer's
selected-file snapshot as an exhaustive set of matching dependency files.

The npm documentation states that npm ci removes an existing node_modules
before installation. Restoring that directory immediately before npm ci
therefore does not establish an install-speed benefit and adds restore/save
work. For npm install, restored installed artifacts need separate behavioral
review; unchanged commands alone do not prove equivalence.

Source: https://docs.npmjs.com/cli/v11/commands/npm-ci/

UUID trial dev-fork-abc-uuid-gemma-003 and Chalk trial
dev-fork-abc-chalk-gemma-002 demonstrate actual cache insertion after the v2
source fix. Both B candidates pass actionlint but require cache-policy review.
Chalk C additionally lacks a frozen root npm lockfile.

## Implemented adapted baseline

`cloudtune-ci-cost-npm-download-v3` replaces the npm installed-artifact proposal
with `with.cache: npm` on the existing reviewed setup-node action, in the
recommendation's affected job. This uses the action's platform-aware npm
download cache and lockfile key. It leaves existing action refs, inputs, install
commands and test commands unchanged. Unsupported action refs or missing
setup-node steps receive no edit; the adapter records semantic NO_CHANGE when
no other transformation applies. The common admission gate still verifies
checkout order, a frozen root npm lockfile and root install context.

This is a changed cache mechanism in an explicitly adapted baseline, applied
to upstream TypeScript before compilation, not a validator exception or a
post-generation YAML repair. Unrelated concurrency and fail-fast edits still
require review. Earlier v1/v2 candidates retain their original verdicts.
Record genuine NO_CHANGE outcomes rather than interpreting them as optimizer
failures or silently selecting only repositories where both optimizers edit CI.

## Next development candidate

isaacs/node-lru-cache is absent from evaluation/evaluation_repositories_4000.csv.
Connected GitHub reads on the review date confirmed a root package-lock.json
(lockfileVersion 3), and .github/workflows/ci.yml uses npm install followed by
npm test. It has Linux, macOS and Windows matrix entries and workflow_dispatch.
These are discovery observations; the actual preflight must freeze and validate
the selected source commit before any execution.

Sources:

- https://github.com/isaacs/node-lru-cache/blob/main/package-lock.json
- https://github.com/isaacs/node-lru-cache/blob/main/.github/workflows/ci.yml

At the time of initial review setup-node@v6 was outside the allowlist. Policy
v5 now recognizes official v6 release tags and their SHAs through a shared
frozen release registry. This resolves the version compatibility issue; it does
not establish full A/B/C admission or runtime success for this repository.
The current CI-Cost adaptation is cloudtune-ci-cost-npm-download-v4-compatibility;
the historical installed-artifact cache proposals retain their review verdicts.

Prepared entry: evaluation/results/development_smoke_lru_cache_gemma.json,
trial dev-fork-abc-lru-cache-gemma-001. No preflight or hosted CI was started
as part of this review.
