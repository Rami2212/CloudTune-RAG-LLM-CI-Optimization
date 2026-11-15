# Progress report: RAG training patterns

Snapshot: 31 October 2026. This report covers the 16 patterns in the project's pattern catalog. Each has two qualifying examples in the training summary. Results are preliminary and do not establish that a pattern will improve every workflow.

## Results

Mean decrease is baseline median minus optimized median; positive values indicate faster runs. Percentage is the arithmetic mean of qualifying cases' individual percentage decreases. Evidence counts are reports / qualifying cases.

| Pattern | Qualifying / target | Reports / qualifying | Mean decrease (seconds) | Mean decrease (%) |
|---|---:|---:|---:|---:|
| `P-LIT-GHA-CACHE` | 2/2 | 4/2 | +11.00 | +13.23% |
| `P-LIT-FAIL-FAST` | 2/2 | 2/2 | +4.50 | +0.93% |
| `P-LIT-CANCEL-STALE` | 2/2 | 3/2 | +2.50 | +0.90% |
| `P-LIT-CHANGE-FILTER` | 2/2 | 2/2 | +8.00 | +20.78% |
| `P-LIT-CUSTOM-TIMEOUT` | 2/2 | 3/2 | +12.50 | +18.31% |
| `P-LIT-HISTORY-TIMEOUT` | 2/2 | 6/2 | +1.00 | +4.85% |
| `P-LIT-PRIORITIZE` | 2/2 | 4/2 | +1.00 | +29.17% |
| `P-LIT-SELECT` | 2/2 | 8/2 | +1.00 | +33.33% |
| `P-LIT-BAZEL-DEPS` | 2/2 | 8/2 | +1.00 | +33.33% |
| `P-LIT-ENV-CACHE` | 2/2 | 5/2 | +1.00 | +25.00% |
| `P-LIT-UNAFFECTED-STEPS` | 2/2 | 9/2 | +1.00 | +33.33% |
| `P-LIT-SMELL-REPAIR` | 2/2 | 2/2 | +1.00 | +29.17% |
| `P-LIT-UNUSED-OUTPUTS` | 2/2 | 4/2 | +1.00 | +25.00% |
| `P-LIT-DISTRIBUTED-CACHE` | 2/2 | 7/2 | +34.50 | +9.87% |
| `P-LIT-CONFIG-REUSE` | 2/2 | 5/2 | +38.00 | +27.90% |
| `P-LIT-UNUSED-DEP-SKIP` | 2/2 | 4/2 | +1.00 | +25.00% |

## Pattern details and checks

| Pattern | Optimization and literature source | How it was checked |
|---|---|---|
| `P-LIT-GHA-CACHE` | Reuse downloaded packages; S01 §4.2.1. | Compared runs before and after dependency caching; validated workflow YAML. |
| `P-LIT-FAIL-FAST` | Cancel remaining matrix jobs after a failure; S01 §4.2.2. | Checked cancellation after failure and confirmed the healthy control completed. |
| `P-LIT-CANCEL-STALE` | Cancel a run superseded by a newer commit; S01 §4.2.3. | Checked superseded-run cancellation, latest-run completion, and branch isolation. |
| `P-LIT-CHANGE-FILTER` | Run workflows only for relevant file changes; S01 §4.2.5. | Checked relevant and irrelevant change classes and confirmed required workflows still ran. |
| `P-LIT-CUSTOM-TIMEOUT` | Set a suitable upper time limit; S01 §4.2.6. | Compared runs after timeout-only edits and validated configuration. |
| `P-LIT-HISTORY-TIMEOUT` | Use successful-run durations to propose a timeout; S01 §4.3.4. | Compared repeat runs after timeout-only edits; a history estimator was not used. |
| `P-LIT-PRIORITIZE` | Run tests likely to fail earlier; S02 §§V.A.1, V.B. | Checked test coverage, outcomes, work performed, and time to failure. |
| `P-LIT-SELECT` | Run tests related to changed code; S02 §§IV.A.1, IV.C. | Checked selection against changed-file classes, including unknown changes, and verified failure detection. |
| `P-LIT-BAZEL-DEPS` | Check whether dependency caching saves more time than it costs; S03 §§3.2.3, 4.3. | Compared cached and uncached dependency fetching, invalidation, build/test retention, and overhead. |
| `P-LIT-ENV-CACHE` | Reuse prepared environments when inputs remain compatible; S04 §§4.1, 6.3. | Checked reuse and invalidation after dependency, environment, and toolchain changes. |
| `P-LIT-UNAFFECTED-STEPS` | Skip steps only when tracked inputs are unaffected; S04 §§4.2, 6.3. | Checked direct, transitive, setup, lockfile, and unknown changes; verified affected steps ran. |
| `P-LIT-SMELL-REPAIR` | Fix documented inefficient build configuration; S05 §4.3.3, Table 2. | Checked required outputs, side effects, and work performed after a bounded build change. |
| `P-LIT-UNUSED-OUTPUTS` | Avoid producing outputs with no required consumers; S05 §4.3.3, Table 2. | Checked required outputs and work performed with consumed and unconsumed outputs. |
| `P-LIT-DISTRIBUTED-CACHE` | Share cached dependencies across workers; S05 §4.3.3, Table 2. | Compared workflow runs after a bounded cache change. |
| `P-LIT-CONFIG-REUSE` | Reuse work across compatible configurations; S05 §4.3.3, Table 2. | Compared workflow runs after a cache-based reuse proposal. |
| `P-LIT-UNUSED-DEP-SKIP` | Evaluate skipping updates to unused dependencies; S05 §4.3.3, Table 2. | Checked used, unused, setup, lockfile, and unknown dependency changes; verified required builds and failure detection. |

## Data and method notes

The repository candidate metadata is sourced from Cardoen's GitHub Actions workflow-history dataset and its Zenodo release; this is repository-selection data, not evidence that a pattern applies to a particular repository. The RAG method uses a fixed, cited knowledge corpus with retrieval and generation, and BGE-M3 for embeddings; it does not fine-tune generator weights. Pattern results compare baseline and optimized workflow timings. Evaluation guidance supports repeated, controlled comparisons and transparent reporting; cited methods papers do not independently validate these local outcomes.

## Citations

### Pattern literature

- **S01:** Bouzenia, I., & Pradel, M. (2024). [Resource Usage and Optimization Opportunities in Workflows of GitHub Actions](https://doi.org/10.1145/3597503.3623303). *ICSE 2024*.
- **S02:** Jin, X., & Servant, F. (2021). [What Helped, and What Did Not? An Evaluation of the Strategies to Improve Continuous Integration](https://doi.org/10.48550/arXiv.2102.06666).
- **S03:** Zheng, S., Adams, B., & Hassan, A. E. (2024). [Does Using Bazel Help Speed Up Continuous Integration Builds?](https://doi.org/10.48550/arXiv.2405.00796).
- **S04:** Gallaba, K., Ewart, J., Junqueira, Y., & McIntosh, S. (2022). [Accelerating Continuous Integration by Caching Environments and Inferring Dependencies](https://doi.org/10.1109/TSE.2020.3048335). *IEEE TSE, 48*(6), 2040–2052.
- **S05:** Aïdasso, H., Sayagh, M., & Bordeleau, F. (2025). [Build Optimization: A Systematic Literature Review](https://doi.org/10.48550/arXiv.2501.11940).

### Dataset

- Cardoen, G. (2026). [A Dataset of GitHub Actions Workflow Histories](https://doi.org/10.5281/zenodo.20340547), version 2026-05-22. Zenodo.
- Cardoen, G., Mens, T., & Decan, A. (2024). [A Dataset of GitHub Actions Workflow Histories](https://doi.org/10.1145/3643991.3644867). *MSR 2024*.

### RAG training and retrieval

- Lewis, P., et al. (2020). [Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks](https://arxiv.org/abs/2005.11401). Provides the retrieval-plus-generation framing; this project prepares a frozen retrieval corpus and does not fine-tune generator weights.
- Chen, J., et al. (2024). [M3-Embedding: Multi-Linguality, Multi-Functionality, Multi-Granularity Text Embeddings Through Self-Knowledge Distillation](https://doi.org/10.18653/v1/2024.findings-acl.137). Source for the BGE-M3 embedding model.

### Evaluation method

- Kitchenham, B. A., et al. (2002). [Preliminary Guidelines for Empirical Research in Software Engineering](https://doi.org/10.1109/TSE.2002.1027796).
- Jedlitschka, A., & Pfahl, D. (2005). [Reporting Guidelines for Controlled Experiments in Software Engineering](https://doi.org/10.1109/ISESE.2005.1541818).
- Efron, B., & Tibshirani, R. (1986). [Bootstrap Methods for Standard Errors, Confidence Intervals, and Other Measures of Statistical Accuracy](https://doi.org/10.1214/ss/1177013815).
