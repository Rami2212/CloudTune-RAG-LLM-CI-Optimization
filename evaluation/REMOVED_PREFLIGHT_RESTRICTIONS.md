# Removed preflight restrictions

This records eligibility and validation restrictions relaxed by protocol v10.
It is historical reference only; current evaluations use the v10 policy.

## Relaxed rules

- A secret reference by itself no longer excludes the selected workflow.
- A malformed workflow file no longer excludes the repository when another
  usable test/build workflow can be selected.
- Missing `workflow_dispatch` no longer blocks preflight. The evaluation fork
  adds dispatch as a common harness change for A, B and C.
- An `actionlint` finding already present in the baseline is a warning. Only
  new candidate diagnostics block admission. If lint output cannot be parsed,
  the candidate remains blocked rather than treating the result as clean.
- Transient GitHub API connection, rate-limit and server errors are retried
  up to three times with short backoff.

## Rules retained

Explicit publishing/deployment operations, self-hosted runners and reusable
workflows that cannot be inspected remain excluded from selection. These can
execute side effects or prevent comparable measurements. YAML parsing remains
required for the selected workflow, and all arms still use the same dispatch
harness and candidate gate.

## Restore guidance

To restore the earlier behavior, reinstate secret-reference screening, fail on
any malformed workflow encountered during repository screening, require
`workflow_dispatch` before selection, require a clean `actionlint` result for
baseline and candidates, and remove the API retry loop. Update protocol and
candidate-policy revision identifiers and start a new evaluation ID. Do not
rewrite frozen checkpoints or archived validation decisions.
