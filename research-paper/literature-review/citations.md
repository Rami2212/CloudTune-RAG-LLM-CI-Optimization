# Research citations

This list contains sources used for the project's 16 literature-derived CI optimization patterns, repository dataset preparation, RAG retrieval, and evaluation methodology. Pattern IDs below are limited to the current 16-pattern catalog.

## CI optimization patterns

| Source | Patterns supported | Use in this research |
|---|---|---|
| **S01.** Bouzenia, I., & Pradel, M. (2024). [Resource Usage and Optimization Opportunities in Workflows of GitHub Actions](https://doi.org/10.1145/3597503.3623303). *ICSE 2024*. | `P-LIT-GHA-CACHE` (§4.2.1); `P-LIT-FAIL-FAST` (§4.2.2); `P-LIT-CANCEL-STALE` (§4.2.3); `P-LIT-CHANGE-FILTER` (§4.2.5); `P-LIT-CUSTOM-TIMEOUT` (§4.2.6); `P-LIT-HISTORY-TIMEOUT` (§4.3.4). | Primary GitHub Actions study. Historical estimates in the paper are not this project's measured outcomes. |
| **S02.** Jin, X., & Servant, F. (2021). [What Helped, and What Did Not? An Evaluation of the Strategies to Improve Continuous Integration](https://doi.org/10.48550/arXiv.2102.06666). | `P-LIT-PRIORITIZE` (§§V.A.1, V.B); `P-LIT-SELECT` (§§IV.A.1, IV.C). | CI test/build prioritization and selection; the study's historical replay setting differs from live workflow trials. |
| **S03.** Zheng, S., Adams, B., & Hassan, A. E. (2024). [Does Using Bazel Help Speed Up Continuous Integration Builds?](https://doi.org/10.48550/arXiv.2405.00796). | `P-LIT-BAZEL-DEPS` (§§3.2.3, 4.3). | Build-level dependency-cache overhead; findings concern Bazel builds, not arbitrary end-to-end workflows. |
| **S04.** Gallaba, K., Ewart, J., Junqueira, Y., & McIntosh, S. (2022). [Accelerating Continuous Integration by Caching Environments and Inferring Dependencies](https://doi.org/10.1109/TSE.2020.3048335). *IEEE TSE, 48*(6), 2040–2052. | `P-LIT-ENV-CACHE` (§§4.1, 6.3); `P-LIT-UNAFFECTED-STEPS` (§§4.2, 6.3). | Environment reuse and dependency-informed step skipping; applicability depends on correctly inferred dependencies. |
| **S05.** Aïdasso, H., Sayagh, M., & Bordeleau, F. (2025). [Build Optimization: A Systematic Literature Review](https://doi.org/10.48550/arXiv.2501.11940). | `P-LIT-SMELL-REPAIR`, `P-LIT-UNUSED-OUTPUTS`, `P-LIT-DISTRIBUTED-CACHE`, `P-LIT-CONFIG-REUSE`, `P-LIT-UNUSED-DEP-SKIP` (§4.3.3, Table 2). | Secondary review. Underlying primary studies were not all independently examined, so its findings remain secondary evidence. |

## Repository dataset

| Source | Use in this research |
|---|---|
| Cardoen, G. (2026). [A Dataset of GitHub Actions Workflow Histories](https://doi.org/10.5281/zenodo.20340547), version 2026-05-22. Zenodo. | Supplies the repository metadata sampled for development and evaluation candidates. The snapshot does not establish current eligibility or pattern applicability. |
| Cardoen, G., Mens, T., & Decan, A. (2024). [A Dataset of GitHub Actions Workflow Histories](https://doi.org/10.1145/3643991.3644867). *MSR 2024*. | Provides the dataset's collection context and publication provenance for the metadata source. |

## RAG training and retrieval

| Source | Use in this research |
|---|---|
| Lewis, P., et al. (2020). [Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks](https://arxiv.org/abs/2005.11401). | Provides the retrieval-plus-generation framing for the RAG pipeline. The project retrieves from a frozen corpus and does not fine-tune generator weights. |
| Chen, J., Xiao, S., Zhang, P., Luo, K., Lian, D., & Liu, Z. (2024). [M3-Embedding: Multi-Linguality, Multi-Functionality, Multi-Granularity Text Embeddings Through Self-Knowledge Distillation](https://doi.org/10.18653/v1/2024.findings-acl.137). | Provides the research basis for using BGE-M3 as the corpus and query embedding model. The paper's benchmarks are not treated as retrieval results for this project's corpus. |

## Evaluation methodology

| Source | Use in this research |
|---|---|
| Kitchenham, B. A., et al. (2002). [Preliminary Guidelines for Empirical Research in Software Engineering](https://doi.org/10.1109/TSE.2002.1027796). | Informs transparent planning of the study, collection of measurements, interpretation, and reporting of limitations. |
| Jedlitschka, A., & Pfahl, D. (2005). [Reporting Guidelines for Controlled Experiments in Software Engineering](https://doi.org/10.1109/ISESE.2005.1541818). | Informs how the A/B/C treatments, procedure, measures, and validity context are described. |
| Efron, B., & Tibshirani, R. (1986). [Bootstrap Methods for Standard Errors, Confidence Intervals, and Other Measures of Statistical Accuracy](https://doi.org/10.1214/ss/1177013815). | Provides the statistical basis for bootstrap uncertainty intervals when aggregating repository-level evaluation results. |

These methodological sources inform the study but do not prescribe or validate its exact three-arm design. The evaluation protocol and archived run records define the actual procedures and local results. Cite those records for outcomes; literature-reported estimates are not local measurements.

## Research gaps addressed

The following gaps motivate this study within the cited literature. They describe the scope of the present comparison and are not a claim that no other work addresses these questions.

| Gap | Related sources | How this research addresses it |
|---|---|---|
| Identifying an optimization mechanism does not establish its suitability for a particular repository. | S01–S05 | Combines the 16 patterns' conditions and limitations with relevant workflow, dependency, and build context when generating a candidate. |
| Historical estimates, replay results, and build-specific findings do not directly establish improvements for a newly generated GitHub Actions workflow. | S01–S04 | Measures original and generated workflow variants through repeated GitHub Actions executions on the same pinned repository source. |
| A pattern catalog or a general RAG method does not establish whether retrieved research evidence helps produce useful CI workflow changes. | S01–S05; Lewis et al. (2020); Chen et al. (2024) | Evaluates the combined repository-aware RAG + LLM method against original workflows and pinned, source-corrected CI-Cost. Without an LLM-only arm, retrieval's individual contribution remains unresolved. |
| Timing improvements alone do not describe applicability or execution reliability. | S02; S04; Kitchenham et al. (2002); Jedlitschka & Pfahl (2005) | Reports no-change decisions, generation and validation failures, execution outcomes, and regressions alongside timing savings. Successful runs provide limited evidence of preserved behavior. |
| Findings across different CI settings need a clear sampling and measurement basis for comparison. | Cardoen et al. (2024); Cardoen (2026); Kitchenham et al. (2002) | Documents candidate sampling and development/evaluation separation, and compares per-repository median active time and summed job runtime while recording queue delay separately. |
