# 4 Results and Analysis

Arm A denotes the original workflow, Arm B denotes CI-Cost, and Arm C denotes RAG + LLM.

## 4.1 Overview of Results

The CSV contains 157 distinct repository records: 151 with `COMPLETE` status and six with `FAILED_TARGET_CI` status. Every completed record contains three comparable repetitions per effective arm. Performance analysis uses these 151 complete, paired records. The six incomplete records contribute only to the functional execution summary because they lack complete A/B/C measurements.

| Dataset characteristic | Count |
| --- | ---: |
| Repository records | 157 |
| Complete A/B/C comparisons | 151 |
| Selected failed records | 6 |
| Comparable repetitions per arm in each complete record | 3 |
| Effective comparable measurements per arm in the complete subset | 453 |


## 4.2 Performance Evaluation

For repository i, let A_i, B_i, and C_i be its median elapsed seconds. Percentage saving for candidate X against reference Y is:

`saving_i(X versus Y) = 100 × (Y_i − X_i) / Y_i`.

A positive value indicates a reduction, a negative value indicates a slowdown, and zero indicates an exact tie in the stored medians. The same calculation applies separately to runner seconds. The mean percentage gives equal weight to each repository. Aggregate saving is `100 × (ΣY_i − ΣX_i) / ΣY_i`, which gives longer reference workflows more weight.

### Elapsed and runner times

| Arm | Mean repository median elapsed (s) | Median repository median elapsed (s) | Mean repository median runner (s) | Median repository median runner (s) |
| --- | ---: | ---: | ---: | ---: |
| A — Original | 122.82 | 74.00 | 256.82 | 130.00 |
| B — CI-Cost | 121.53 | 74.00 | 256.75 | 129.00 |
| C — RAG + LLM | 108.44 | 65.00 | 237.52 | 106.00 |

These are summaries of per-repository medians, not summaries of all individual trial durations. Elapsed time describes workflow duration; runner time sums job execution and can be higher when jobs run concurrently.

| Comparison | Mean elapsed saving | Median elapsed saving | Aggregate elapsed saving | Aggregate runner saving |
| --- | ---: | ---: | ---: | ---: |
| B versus A | 1.06% | 0.00% | 1.05% | 0.03% |
| C versus A | 11.30% | 8.22% | 11.71% | 7.51% |
| C versus B | 10.45% | 7.14% | 10.77% | 7.49% |

Across the 151 paired medians, elapsed totals are 18,546 seconds for A, 18,351 seconds for B, and 16,374 seconds for C. C therefore saves 2,172 seconds relative to A and 1,977 seconds relative to B. Its summed repository median runner time is 2,914 seconds below A and 2,903 seconds below B.

## 4.3 Functional Testing Results

The available functional evidence is the recorded CI outcome and comparability counters. The 151 complete comparisons each report three comparable repetitions in A, B, and C, with zero failed counters. This supports successful execution of the selected workflows under the evaluation conditions. 

| Arm | Attempted counter total | Comparable counter total | Failed counter total |
| --- | ---: | ---: | ---: |
| A | 465 | 462 | 3 |
| B | 459 | 456 | 3 |
| C | 458 | 456 | 2 |

The table sums counters over all 157 rows, including the six incomplete records. Counters can include reused baseline values, so they are effective dataset counts rather than verified counts of distinct hosted runs. The selected failure examples do not provide a representative denominator for experiment-wide failure rates.

## 4.4 Comparison with Existing Solutions

CI-Cost is the existing optimization comparator represented by Arm B. Arm A provides the original workflow reference, while Arm C represents the combined RAG + LLM approach. The CSV supports the following paired comparison within the selected complete subset:

| Comparison | Candidate faster | Candidate slower | Exact median ties | Candidate faster proportion |
| --- | ---: | ---: | ---: | ---: |
| B versus A | 55 | 25 | 71 | 36.42% |
| C versus A | 124 | 18 | 9 | 82.12% |
| C versus B | 129 | 19 | 3 | 85.43% |

C has lower elapsed medians than B in 129 of the 151 retained complete comparisons and achieves a 10.45% mean repository-level reduction. The outcome-based exclusions favour C, so this proportion is a property of the selected dataset rather than an estimate of the full approach's win rate.

The largest retained C-versus-B percentage reductions are:

| Repository | B median elapsed (s) | C median elapsed (s) | Reduction |
| --- | ---: | ---: | ---: |
| wpovernight/woocommerce-pdf-invoices-packing-slips | 40 | 14 | 65.00% |
| thoughtindustries/helium | 159 | 91 | 42.77% |
| yolk/valvat | 24 | 15 | 37.50% |
| waikato/moa | 493 | 333 | 32.45% |
| yuria-shikibe/newhorizonmod | 48 | 33 | 31.25% |

## 4.5 Statistical Analysis

The unit of analysis is a repository, using its median of three comparable repetitions per effective arm. All paired summaries use the same 151 complete records. Incomplete records are excluded from timing comparisons rather than assigned zero execution time.

| Repository-level elapsed saving | B versus A | C versus A | C versus B |
| --- | ---: | ---: | ---: |
| Mean | 1.06% | 11.30% | 10.45% |
| Median | 0.00% | 8.22% | 7.14% |
| Sample standard deviation | 6.39 percentage points | 12.26 percentage points | 10.64 percentage points |
| First quartile | 0.00% | 3.11% | 3.42% |
| Third quartile | 3.81% | 16.67% | 16.67% |
| Minimum | −40.00% | −9.80% | −3.57% |
| Maximum | 20.00% | 67.44% | 65.00% |

Quartiles use linear interpolation at the 25th and 75th percentiles. The mean C-versus-B saving exceeds the median, indicating that larger improvements raise the average. The aggregate reduction of 10.77% differs from the 10.45% mean because it weights repositories by reference elapsed time.

## 4.6 Discussion

### 4.6.1 Key Findings

- In the retained complete subset, C reduces mean repository-level elapsed time by 11.30% against A and 10.45% against B.
- The corresponding aggregate runner-time reductions are 7.51% and 7.49%, indicating that workflow-duration improvements and summed job-runtime improvements differ.
- CI-Cost yields a smaller mean elapsed saving of 1.06% against A in this subset.
- C is slower than B in 19 retained comparisons.

### 4.6.2 Addressing Research Questions

| Research question | Evidence available from this CSV | Supported interpretation |
| --- | --- | --- |
| RQ1: How does RAG + LLM compare with original workflows and CI-Cost in elapsed time and summed job runtime? | Paired medians for 151 complete records | C has lower elapsed time and runner use on average in this selected subset; full-experiment superiority is not established. |
| RQ2: How often do optimizers produce applicable changes, no change, or generation/validation failures? | No decision, retrieval, or validation fields | Not answerable from this CSV. Timing equality cannot substitute for applicability evidence. |
| RQ3: How reliably do generated candidates execute, and do they introduce failures or regressions? | Completed comparisons, failed counters, and elapsed regressions | Selected execution successes and regressions can be described; representative failure rates and causal attribution cannot be established. |

### 4.6.3 Limitations of Results

1. **Limited execution evidence:** Medians conceal trial variability. Logs, test inventories, cache conditions, queue times, and environment details are absent.
2. **Missing additional metrics:** CodeBLEU, actual monetary cost, candidate-generation overhead, and retrieval quality are not recorded.

## 4.7 Chapter Summary

This contains 151 complete comparisons and six selected failed records. Using its numeric medians, C is faster than B in 129 complete comparisons, slower in 19, and tied in three. Mean repository-level elapsed savings are 11.30% against A and 10.45% against B; aggregate runner-time savings are 7.51% and 7.49%, respectively.