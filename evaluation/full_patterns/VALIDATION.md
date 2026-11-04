# Validation record — 2026-11-04

## Automated verification

- Full offline suite: **318 tests passed; zero failures, errors or skips**.
- All 25 mechanisms execute through the controlled development pilot.
- Positive/negative checks include missing failures, discarded required matrix
  diagnostics, invalidation errors, state contamination, incompatible
  configurations, untrusted policies and unsupported candidate execution.
- Connected tests cover generation, supplementary evidence, shared B/C admission,
  review, scenario execution, metrics, cohort analysis and member-local batching.
- Member 2 local position 100 was verified to map to global row 1100.
- Resume checks cover queued dispatches, cancelled runs, retained evidence,
  preserved retry generations, and unstarted rows after a retry round.
- Hosted API tests use mocks, including exact multi-file/mode/tree verification,
  numeric fork identity, cache reset ownership, warm-ups and dispatch accounting.
- New modules compile; whitespace checks pass. A stale legacy test's policy-name
  assertion was removed; archived policy identity and functional behavior remain
  tested. The frozen legacy production policy was not changed to satisfy a name.

The current code/corpus fingerprint and detailed synthetic observations are
stored locally by `python -m evaluation.full_patterns verify`, under the ignored
`evaluation/full-pattern-results/` tree. The full suite log is under ignored
`.test-tmp/full-pattern-validation-final.log`.

## Live synthetic provider/retriever check

The configured free OpenRouter model assessed all 25 catalogue patterns for a
synthetic matrix source: one applicable (FAIL-FAST), fifteen missing evidence,
nine not applicable. BGE-M3 retrieval used the existing verified index and
`cuda:0`, with revision `5617a9f61b028005a4858fdac845db406aefb181`.

The model returned an actual non-cache APPLY proposal. This exposed a citation
boundary bug: the supplied verified `contract.txt` artifact was citable evidence
but the original validator accepted only source paths. That bug was fixed with
a regression test. The archived live response passes the corrected schema and
real actionlint, and reaches REVIEW_REQUIRED as intended. The supplementary
artifact remains read-only and cannot be proposed as an editable source file.

Fresh live attempts also returned OpenRouter HTTP 502. Consequently **a clean
complete live smoke under the final implementation is not recorded as passed**.
Provider failures retain the request without paid fallback or automatic retry.
Preserve earlier output after code changes; retry with a fresh output directory
using the documented `smoke` command when the provider is available.

## Repository-set status

No held-out repository set, real fork creation, cache deletion, or GitHub Actions
job was launched during this implementation. Existing experiment evidence and
checkpoints were preserved. The native adapter has offline integration coverage;
it has not been represented as a completed live hosted pilot.

Before a held-out run, complete the clean synthetic live smoke and the relevant
source-bound preflight, reviews and scenario inputs. Controlled replay results
are not native repository speedups; approval is not a measured benefit. CUDA is
optional and CPU remains the default unless explicitly selected through ENV.
