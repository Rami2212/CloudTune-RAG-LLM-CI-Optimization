# Member 1: first 160 repository results

Snapshot: 10 November 2026. Source: `evaluation/results/eval-member-01/published/trials/r0001.json` through `r0160.json`. The batch has begun position 161; it is excluded. These are 160 assigned repository/workflow cases, not 160 successful experiments. This report evaluates archived local evidence; it does not query GitHub or rerun experiments.

## Assessment

The current results do not establish an overall CI-time improvement for RAG + LLM or CI-Cost. RAG + LLM is near neutral against the original and modestly better against CI-Cost on the smaller directly paired subset; bootstrap intervals include zero. Completion and generation reliability are the larger immediate limitations.

## Coverage

| Recorded outcome | Repositories | Share of 160 |
|---|---:|---:|
| FAILED_TARGET_CI | 32 | 20.00% |
| COMPLETE | 43 | 26.88% |
| PREFLIGHT_BLOCKED | 48 | 30.00% |
| QUEUE_TIMEOUT | 11 | 6.88% |
| IN_PROGRESS_TIMEOUT | 17 | 10.62% |
| INCONCLUSIVE_PLATFORM | 6 | 3.75% |
| SKIPPED | 3 | 1.88% |

43/160 (26.88%) are COMPLETE. The 160 cases represent 16% of Member 1's 1,000 assignments and 4% of the full 4,000 assignments. The 43 complete cases represent 4.3% and 1.075%, respectively. A COMPLETE status does not mean both optimizers applied a change.

## Paired effects

A = original; B = CI-Cost; C = RAG + LLM. Positive savings mean faster execution or lower summed job runtime.

| Comparison | Measure | Paired repositories | Median saving | IQR | Bootstrap 95% interval | Faster / tied / slower |
|---|---|---:|---:|---|---|---|
| B vs A | elapsed | 23 | -4.61% | -19.54% to 1.92% | -17.65% to 1.47% | 8 / 2 / 13 |
| B vs A | runner | 23 | -3.77% | -9.49% to 2.03% | -8.33% to 1.61% | 8 / 2 / 13 |
| C vs A | elapsed | 38 | -1.14% | -11.10% to 5.69% | -6.25% to 2.69% | 17 / 1 / 20 |
| C vs A | runner | 38 | -2.76% | -10.92% to 5.80% | -7.92% to 1.63% | 15 / 1 / 22 |
| C vs B | elapsed | 22 | 2.26% | -1.40% to 8.89% | -0.88% to 5.56% | 13 / 1 / 8 |
| C vs B | runner | 22 | 2.43% | -3.80% to 5.48% | -1.49% to 5.18% | 13 / 1 / 8 |

Eligibility requires APPLY + PASS for each optimized arm, three distinct successful, comparable, protocol-valid runs with passing required checks and repetition IDs 1–3 for each arm, and pinned source consistency. Each arm is summarized by its median before repository-level percentage savings are calculated. Bootstrap uses 1,000 repository resamples, seed 20261101, with interpolated percentile intervals. No-change outcomes remain in coverage accounting and are excluded from measured optimization effects. Pair eligibility does not require the third arm to complete. Different comparison rows can cover different repositories. Runner runtime is a resource-use proxy, not billed cost.

## Candidate reliability

- CI-Cost: 60 APPLY/PASS, 75 NO_CHANGE, 25 without candidate decisions. Applied-candidate coverage is 37.50% of 160, or 44.44% of the 135 cases with decisions.
- RAG + LLM: 86 APPLY/PASS, 26 NO_CHANGE, 21 ERROR/FAIL, 2 APPLY/FAIL, 25 without decisions. Applied-candidate coverage is 53.75% of 160, or 63.70% of 135. Admission does not establish measured savings.
- Local controller reports attribute the 21 generation errors to 17 invalid/duplicate frozen-evidence references and 4 truncated responses. Two additional candidates fail with ACTIONLINT_NEW.
- The 48 preflight blocks comprise 23 C-admission failures, 23 ineligible repositories, and 2 API errors in local controller reports. A rejected C also prevented otherwise admitted arms from obtaining measurements in these blocked cases.
- There are 34 recorded platform/timeout outcomes (17 in-progress, 11 queue, 6 platform-inconclusive), plus 3 manual skips associated with fork-creation HTTP 307 redirects. These are not timing observations.

## Interpretation and limitations

- C vs A: improvement and regression counts are close; no positive median saving is established. C vs B offers a small favorable median but substantial uncertainty.
- C elapsed-time examples: retroachievements/rcheevos 284 to 195 seconds (+31.34%); yuria-shikibe/newhorizonmod 48 to 33 (+31.25%); pengutronix/genimage 69 to 146 (-111.59%). Investigate differences and run variability before treating any example as causal.
- Very short workflows magnify percentages: react-component/tree changes from 4 to 7 seconds (-75%) despite a 3-second difference.
- Failures frequently occur in original-arm execution, so the FAILED_TARGET_CI total cannot be interpreted as optimizer-induced regression. Candidate run pass rates would also be conditional on passing baseline/admission and should not be compared naively.
- Four implementation hashes occur across the 160 cases (104, 40, 14, and 2 cases); pooled effects are exploratory until version changes are documented and sensitivity by version is checked. All 160 record the same model identifier and RAG corpus digest; that alone does not guarantee identical provider behavior or generation parameters.
- Safety/required-check flags are archived controller judgments. This analysis checks those flags, not independent semantic workflow equivalence.
- The methodology document is out of sync: it describes additive-cache-only admission and pending live execution, whereas current controller evidence includes general workflow candidates and actual run measurements. Update the documented protocol to the actual approved execution rules before paper claims.
- This is a partial, success-selected subset of one member, not evidence of generalization across all 4,000 assignments. Do not tune held-out prompts or policies from these outcomes and silently pool new results; version and separate subsequent cohorts.

## Recommended next steps

1. Diagnose frozen-evidence validation, response truncation, and newly introduced Actions syntax errors using separate development fixtures; preserve held-out outcomes and version any changes.
2. Diagnose baseline failures separately from candidate failures, and reconcile platform/timeouts and redirect skips under a documented retry policy.
3. Document implementation changes and actual safety protocol. Report per-version sensitivity and paired sample counts alongside pooled results.
4. Continue the fixed assignments and report full coverage, no-change outcomes, paired medians, uncertainty, and correctness together.

Evidence audit: 420 archived run records; 420 distinct run IDs; 0 source-consistency issues among eligible arm repetition sets. Published files contain the selected final trial per repository; earlier retries are outside this analysis. Input hashes are saved in summary.json; exact paired observations are saved in paired-results.csv.
