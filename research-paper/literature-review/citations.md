# Research citations and use in this project

This file records the sources that have informed the project so far, how they were applied, and the limits of those uses. It is a provenance note for the current research materials, not a claim that every source has been independently peer reviewed or approved for final publication.

## 1. Research papers used to build the optimization-pattern catalog

The five papers S01–S05 below were downloaded and archived locally for the optimization-pattern catalog. Their PDFs and extracted text are in `research-data/literature/fulltext/`; source metadata, PDF hashes, reviewed sections, methods, samples, and limitations are in `knowledge/papers.jsonl`. The pattern records are in `knowledge/extracted_patterns.jsonl`, with expanded locators and discussion in `knowledge/LITERATURE_REVIEW.md`. S06 is supplementary CI-pattern literature; evaluation-method, dataset, RAG, and model references are listed in Sections 2–3.

### S01 — GitHub Actions resource use and opportunities

Bouzenia, I., & Pradel, M. (2024). “Resource Usage and Optimization Opportunities in Workflows of GitHub Actions.” *Proceedings of the IEEE/ACM 46th International Conference on Software Engineering (ICSE ’24)*, 12 pages. [Paper PDF](https://software-lab.org/publications/icse2024_workflows.pdf) · [DOI: 10.1145/3597503.3623303](https://doi.org/10.1145/3597503.3623303). Local copy: `research-data/literature/fulltext/gha.pdf` (12 pages; SHA-256 recorded in `knowledge/papers.jsonl`).

**What it contributes here:** The main source for ten GitHub Actions-specific optimization patterns: `P-LIT-GHA-CACHE`, `P-LIT-FAIL-FAST`, `P-LIT-CANCEL-STALE`, `P-LIT-SKIP-WORKFLOW`, `P-LIT-CHANGE-FILTER`, `P-LIT-CUSTOM-TIMEOUT`, `P-LIT-FAIL-SCHEDULE`, `P-LIT-IDLE-SCHEDULE`, `P-LIT-FAILED-JOB-FIRST`, and `P-LIT-HISTORY-TIMEOUT`. The first six are discussed in §4.2 (Tables 3–4); the latter four are proposals in §4.3 (Tables 5–6). The exact pattern-level PDF pages and table locators are recorded on each pattern entry.

The paper’s empirical analysis (952 repositories and about 1.3 million workflow runs, per the local registry) motivates the pattern catalog and measurement distinction between summed job/VM time and workflow wall-clock elapsed time. Its reported counterfactual savings are estimates based on historical runs; they are **not** the outcomes of this project’s experiments and are not used as local success labels. The paper does not provide paired before/after GitHub Actions YAML patches for every pattern.

### S02 — CI test/build selection and prioritization

Jin, X., & Servant, F. (2021). “What helped, and what did not? An Evaluation of the Strategies to Improve Continuous Integration.” [arXiv:2102.06666](https://arxiv.org/abs/2102.06666) · [DOI: 10.48550/arXiv.2102.06666](https://doi.org/10.48550/arXiv.2102.06666). Local copy: `research-data/literature/fulltext/strategies.pdf` (13 pages; hash in registry).

**What it contributes here:** Four pattern families: `P-LIT-PRIORITIZE`, `P-LIT-BUILD-PRIORITY`, `P-LIT-SELECT`, and `P-LIT-BUILD-SELECT`. Sections III–V describe methods for prioritizing tests/builds and selecting work using change dependencies or outcome predictions; §VI and §VII provide trade-offs and threats. The study’s chronological replay design, hidden outcomes of skipped work, and accumulated changes informed the project’s questions about correctness, feedback time, and what a skipped successful/failing task means.

The paper evaluates 14 variants on 100 projects and 82,427 builds, according to the local source registry. It is historical replay evidence, not a direct GitHub Actions patch experiment. Its sample and queue-contention findings have specific language/platform limits, and the project does not treat this paper as proof that arbitrary workflow filters are safe.

### S03 — Bazel parallel and incremental builds

Zheng, S., Adams, B., & Hassan, A. E. (2024). “Does Using Bazel Help Speed Up Continuous Integration Builds?” [arXiv:2405.00796](https://arxiv.org/abs/2405.00796) · [arXiv DOI](https://doi.org/10.48550/arXiv.2405.00796) · related journal DOI [10.1007/s10664-024-10497-x](https://doi.org/10.1007/s10664-024-10497-x). Local copy: `research-data/literature/fulltext/bazel.pdf` (47 pages; hash in registry).

**What it contributes here:** `P-LIT-BAZEL-PARALLEL`, `P-LIT-BAZEL-INCREMENTAL`, and `P-LIT-BAZEL-DEPS`. Sections 2.3, 3.2.2–3.2.3, 4.2–4.3, and 5–6 inform the catalog’s parallelism and build-result caching entries, the experiment repetition/measurement rationale, and the need to record cases where cache overhead outweighs benefit.

The paper reports controlled Bazel build experiments (including repeated trials); it studies compilation/build execution, not the end-to-end elapsed time of arbitrary GitHub Actions workflows. Its speedup figures are not compared directly with this project’s workflow elapsed-time results.

### S04 — Kotinos environment caching and dependency inference

Gallaba, K., Ewart, J., Junqueira, Y., & McIntosh, S. (2022). “Accelerating Continuous Integration by Caching Environments and Inferring Dependencies.” *IEEE Transactions on Software Engineering, 48*(6), 2040–2052. [Author preprint](https://rebels.cs.uwaterloo.ca/papers/tse2020_gallaba.pdf) · [DOI: 10.1109/TSE.2020.3048335](https://doi.org/10.1109/TSE.2020.3048335). Local copy: `research-data/literature/fulltext/kotinos.pdf` (13 pages; hash in registry).

**What it contributes here:** `P-LIT-ENV-CACHE` and `P-LIT-UNAFFECTED-STEPS`. Sections 4–7 and 9–10 provide evidence and constraints for reusing validated build environments and skipping steps only when dependency tracing shows they are unaffected. Its evaluation and correctness limitations informed the catalog’s preconditions and safety checks.

The paper reports historical build records plus replay experiments. Its paired configuration listings are a Travis-to-Kotinos migration, not a GitHub Actions workflow patch. Its findings therefore motivate mechanisms and safeguards; they do not establish a ready-to-apply GitHub Actions change.

### S05 — Systematic review of build optimization

Aïdasso, H., Sayagh, M., & Bordeleau, F. (2025). “Build Optimization: A Systematic Literature Review.” [arXiv:2501.11940](https://arxiv.org/abs/2501.11940) · [arXiv DOI](https://doi.org/10.48550/arXiv.2501.11940) · related journal DOI [10.1145/3757912](https://doi.org/10.1145/3757912). Local copy: `research-data/literature/fulltext/review.pdf` (36 pages; hash in registry).

**What it contributes here:** Six secondary-literature patterns/leads: `P-LIT-SMELL-REPAIR`, `P-LIT-DURATION-PREDICTION`, `P-LIT-UNUSED-OUTPUTS`, `P-LIT-DISTRIBUTED-CACHE`, `P-LIT-CONFIG-REUSE`, and `P-LIT-UNUSED-DEP-SKIP`. §3 describes the review protocol; §4.3/Table 2 and §4.4–4.6 summarize methods, quality, metrics, and datasets. These entries expand the catalog and flag techniques that may need separate experiments or primary-source review.

This is secondary evidence: the 97 studies summarized by the review were not independently read for this project. Its reported results retain a `secondary_report_only` status where applicable. Duration prediction is cataloged as an analysis aid, not as a directly measured workflow speedup.

### S06 — Developer-applied CI acceleration patterns (supplementary)

Yin, M., Kashiwa, Y., Gallaba, K., Alfadel, M., Kamei, Y., & McIntosh, S. (2024). “Developer-Applied Accelerations in Continuous Integration: A Detection Approach and Catalog of Patterns.” *Proceedings of the 39th IEEE/ACM International Conference on Automated Software Engineering (ASE ’24)*, 1655–1666. [DOI: 10.1145/3691620.3695533](https://doi.org/10.1145/3691620.3695533) · [Author-hosted paper](https://keheliya.github.io/papers/ase2024_yin.pdf).

**Use here:** Supplementary background on detecting and cataloging developer-applied CI acceleration techniques. This paper is not one of the five sources in the current `knowledge/papers.jsonl` registry, and its patterns are not currently admitted as separate records in the local catalog. It is not outcome evidence for the A/B/C pipeline.

## 2. Dataset source used to assemble repository candidates

Cardoen, G. (2026). *A dataset of GitHub Actions workflow histories* (version 2026-05-22). Zenodo. [Record and files](https://zenodo.org/records/20340547) · [DOI: 10.5281/zenodo.20340547](https://doi.org/10.5281/zenodo.20340547).

Cardoen, G., Mens, T., & Decan, A. (2024). “A dataset of GitHub Actions workflow histories.” *Proceedings of the 21st International Conference on Mining Software Repositories (MSR ’24)*, 5 pages. [DOI: 10.1145/3643991.3644867](https://doi.org/10.1145/3643991.3644867) · [Paper PDF](https://decan.lexpage.net/files/msr-2024d.pdf). This is the publication describing the dataset and `gigawork`; the 2026 Zenodo version is the repository metadata snapshot used by this project. The paper’s original collection filters and historical scope do not replace the project’s later local sample, exclusions, or split manifest.

**What it contributes here:** The source metadata for selecting repository candidates to screen and use in experiments. The project’s `research-data/zenodo_20340547/selection_manifest.json` records the local process: source archive MD5 verified; 54,758 source rows; 46,068 eligible after the recorded recency filter; 5,000 sampled without replacement using seed `20261027`; and a 500-candidate pattern/repository mapping assembled downstream (25 patterns × 20 candidates; see `pattern_repo_candidates_20.csv` and related manifest/context snapshots).

Zenodo describes its source as repository metadata associated with GitHub Actions workflow histories and gives its own collection/selection procedure. The local 5,000-row sample is a **repository candidate list**, not a verified set of currently active repositories or proof that each repository matches its assigned optimization pattern. Pattern assignments are screening leads; experiment reports determine actual eligibility and outcomes. The source’s activity observation period ends 2026-03-26, as recorded in the local manifest.

The current evaluation cohort is assembled by `evaluation/build_evaluation_repo_dataset.py`: it draws 4,000 held-out candidates from the 5,000-row sample after excluding the 500 development candidates and repositories already present in experiment records. The resulting assignments and hashes are recorded under `evaluation/`; cite Zenodo for the upstream metadata and the local manifest/script for this derived split and its exclusions.

## 3. Platform, API, and implementation documentation

These sources inform how the prototype operates and records measurements. They are technical documentation, not empirical evidence that an optimization is effective.

### 3.1 Evaluation method, RAG, and model papers

| Source | What it informs; scope and limits |
| --- | --- |
| Kitchenham, B. A., Pfleeger, S. L., Pickard, L. M., Jones, P. W., Hoaglin, D. C., El Emam, K., & Rosenberg, J. (2002). “Preliminary Guidelines for Empirical Research in Software Engineering.” *IEEE Transactions on Software Engineering, 28*(8), 721–734. [DOI: 10.1109/TSE.2002.1027796](https://doi.org/10.1109/TSE.2002.1027796). | General guidance for empirical study design, data collection, analysis, and reporting. It informs transparency and limitation reporting; it does not prescribe this project's three-arm design. |
| Jedlitschka, A., & Pfahl, D. (2005). “Reporting Guidelines for Controlled Experiments in Software Engineering.” *Proceedings of ISESE 2005*, 95–104. [DOI: 10.1109/ISESE.2005.1541818](https://doi.org/10.1109/ISESE.2005.1541818). | Reporting treatments, procedures, measures, and validity context for controlled experiments. It is a reporting reference, not evidence that this implementation meets every guideline. |
| Efron, B., & Tibshirani, R. (1986). “Bootstrap Methods for Standard Errors, Confidence Intervals, and Other Measures of Statistical Accuracy.” *Statistical Science, 1*(1), 54–75. [DOI: 10.1214/ss/1177013815](https://doi.org/10.1214/ss/1177013815). | General statistical basis for bootstrap uncertainty estimates. The local exporter resamples eligible repositories (the analysis unit) with replacement and reports percentile-based 95% intervals; this specific choice and its adequacy remain the project's method, not a result established by this paper. |
| Lewis, P., et al. (2020). “Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks.” *Advances in Neural Information Processing Systems 33*. [Paper](https://papers.nips.cc/paper/2020/hash/6b493230205f780e1bc26945df7481e5-Abstract.html) · [arXiv:2005.11401](https://arxiv.org/abs/2005.11401). | Foundational RAG terminology and the combination of external retrieval with generation. Its end-to-end trained model and NLP tasks differ from this project's frozen evidence retrieval plus external OpenRouter generation; it is not efficacy evidence for CloudTune. |
| Chen, J., Xiao, S., Zhang, P., Luo, K., Lian, D., & Liu, Z. (2024). “M3-Embedding: Multi-Linguality, Multi-Functionality, Multi-Granularity Text Embeddings Through Self-Knowledge Distillation.” *Findings of ACL 2024*, 2318–2335. [DOI: 10.18653/v1/2024.findings-acl.137](https://doi.org/10.18653/v1/2024.findings-acl.137). | BGE-M3 embedding model provenance and retrieval capabilities. Its benchmark results do not measure retrieval quality on CloudTune's corpus. |
| NVIDIA. (2026). “Nemotron 3 Ultra: Open, Efficient Mixture-of-Experts Hybrid Mamba-Transformer Model for Agentic Reasoning.” [arXiv:2606.15007](https://arxiv.org/abs/2606.15007) · [Technical report](https://research.nvidia.com/labs/nemotron/files/NVIDIA-Nemotron-3-Ultra-Technical-Report.pdf). | Provenance for the configured Arm C generator family. The actual OpenRouter route and resolved model are recorded per candidate; the model report is not a benchmark of CI workflow optimization. |

The current evaluation protocol itself is specified by `evaluation/configs/fork_pilot.json` and implemented in the local sources listed below. These references support methodological choices and provenance; the scripts and archived run artifacts define what was actually done.

| Source | What it is used for in this project |
| --- | --- |
| [GitHub REST API: repository contents](https://docs.github.com/en/rest/repos/contents) | Reading workflow YAML and repository files needed for workflow selection and context. |
| [GitHub REST API: Git trees](https://docs.github.com/en/rest/git/trees) | Inspecting repository trees and locating workflow/configuration files. |
| [GitHub REST API: workflow runs](https://docs.github.com/en/rest/actions/workflow-runs) | Dispatch/run metadata, status, conclusion, timestamps, IDs, and run attempts. |
| [GitHub REST API: workflow jobs](https://docs.github.com/en/rest/actions/workflow-jobs) | Job/step results and runtime measurements associated with a run/attempt. |
| [GitHub REST API: workflows](https://docs.github.com/en/rest/actions/workflows) | Workflow metadata and dispatch endpoint behavior. |
| [GitHub Actions events and triggers](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows) | `workflow_dispatch` behavior and trigger semantics used to run controlled trials. |
| [GitHub Actions dependency caching](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching) | Platform cache behavior and recommended package-manager setup actions relevant to the narrow dependency-cache treatment. |
| [GitHub Actions: skip workflow runs](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/skip-workflow-runs) | Documentation relevant to skip-run scenarios and the implications for check completion. |
| [GitHub App permissions](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/choosing-permissions-for-a-github-app) | Permission planning for reading repositories, editing fork workflows, enabling Actions, and dispatching runs. |
| [OpenRouter chat completions API](https://openrouter.ai/docs/api/api-reference/chat/send-chat-completion-request) | API contract for sending the selected-pattern optimization request and recording response/model metadata. |
| [OpenRouter model page: nvidia/nemotron-3-ultra-550b-a55b:free](https://openrouter.ai/nvidia/nemotron-3-ultra-550b-a55b%3Afree) | Current Arm C generator configured in `evaluation/configs/fork_pilot.json`; the pipeline records the requested and resolved model for each candidate. Interpret results using the archived model metadata. |
| [OpenRouter API key settings](https://openrouter.ai/settings/keys) | Setup instructions for the API credential stored locally in `.env`; credentials are not part of this citation record. |
| [M3-Embedding paper](https://arxiv.org/abs/2402.03216) and [BAAI/bge-m3 model card](https://huggingface.co/BAAI/bge-m3) | Provenance for the BGE-M3 embeddings configured in Arm C. The embedding model retrieves evidence; it does not generate workflow patches. |
| [Supabase Vector columns](https://supabase.com/docs/guides/ai/vector-columns) | Platform reference for the existing Supabase vector store queried by the frozen Arm C retriever. |
| [`actions/setup-node` caching documentation](https://github.com/actions/setup-node/blob/main/README.md#caching-global-packages-data) | Official behavior and keying details for the npm download cache used by the adapter and common candidate policy. |
| [npm `ci` command documentation](https://docs.npmjs.com/cli/v11/commands/npm-ci) | Supports the CI-Cost cache review's note that `npm ci` removes preexisting `node_modules`; it motivates avoiding an installed-artifact cache in that case. |
| [`actionlint`](https://github.com/rhysd/actionlint) | Required workflow syntax/static validation tool for baseline and candidate screening. It does not prove runtime correctness. |
| [Octokit.js](https://github.com/octokit/octokit.js) | Reference in an earlier architecture blueprint only. The current Python evaluation scripts call GitHub's REST API directly and do not use Octokit.js. |
| [`ci-cost` pinned upstream commit](https://github.com/mariotavarez/ci-cost/tree/e3722ea83da600bebac9ad21ec52490df824eb5c) | Arm B upstream source pinned in `evaluation/third_party/ci_cost/source_fixes.py`. The pipeline applies a reviewed, versioned source correction (`cloudtune-ci-cost-npm-download-v4-compatibility`) before compiling; this is not an unmodified upstream result. |

The following local implementation files substantiate protocol and implementation claims; they are not external literature evidence:

| Local evaluation source | What it supports |
| --- | --- |
| `evaluation/build_evaluation_repo_dataset.py`; `evaluation/prepare_evaluation_assignments.py` | Development/evaluation exclusions, held-out assignment creation, split reproducibility, and dataset hashes. |
| `evaluation/configs/fork_pilot.json`; `evaluation/fork_pipeline.py` | A/B/C arm configuration, three repetitions, frozen corpus identity, retrieval depth, generator model, and the fork execution protocol. |
| `evaluation/optimizers/original.py`; `evaluation/optimizers/ci_cost.py`; `evaluation/optimizers/rag_llm.py`; `evaluation/rag_retriever.py` | Candidate generation for A, B, and C; the source-fixed CI-Cost identity; frozen RAG retrieval and OpenRouter request/response provenance. |
| `evaluation/candidate_validator.py`; `evaluation/repository_preparation.py` | Shared static candidate gate, actionlint status, workflow safety/scope checks, and the narrow additive-cache policy. |
| `evaluation/ci_executor.py` | Repeated GitHub run dispatch, comparability decisions, measured workflow/job timing fields, and paired B–A, C–A, C–B comparisons. |
| `evaluation/results_exporter.py` | Repository-level aggregation and bootstrap summaries. Cite generated evaluation records for actual outcomes. |

## 4. Which patterns each source supports

| Source | Pattern IDs in the local catalog | Role in this research so far |
| --- | --- | --- |
| S01 | `P-LIT-GHA-CACHE`; `P-LIT-FAIL-FAST`; `P-LIT-CANCEL-STALE`; `P-LIT-SKIP-WORKFLOW`; `P-LIT-CHANGE-FILTER`; `P-LIT-CUSTOM-TIMEOUT`; `P-LIT-FAIL-SCHEDULE`; `P-LIT-IDLE-SCHEDULE`; `P-LIT-FAILED-JOB-FIRST`; `P-LIT-HISTORY-TIMEOUT` | Primary GitHub Actions-specific mechanisms/opportunities and reported-versus-estimated evidence distinctions. |
| S02 | `P-LIT-PRIORITIZE`; `P-LIT-BUILD-PRIORITY`; `P-LIT-SELECT`; `P-LIT-BUILD-SELECT` | CI test/build selection and prioritization, including trade-offs in feedback time and saved work. |
| S03 | `P-LIT-BAZEL-PARALLEL`; `P-LIT-BAZEL-INCREMENTAL`; `P-LIT-BAZEL-DEPS` | Build-level parallelism, incremental results, and cache overhead/negative results. |
| S04 | `P-LIT-ENV-CACHE`; `P-LIT-UNAFFECTED-STEPS` | Environment reuse and dependency-traced step skipping, with correctness conditions. |
| S05 | `P-LIT-SMELL-REPAIR`; `P-LIT-DURATION-PREDICTION`; `P-LIT-UNUSED-OUTPUTS`; `P-LIT-DISTRIBUTED-CACHE`; `P-LIT-CONFIG-REUSE`; `P-LIT-UNUSED-DEP-SKIP` | Secondary taxonomy and candidate directions; underlying studies remain to be checked before treating them as primary support. |

The local pattern records cite their source sections/pages and distinguish paper findings from analyst-authored questions, proposed methods, preconditions, safety checks, and illustrative examples. Those examples are pseudocode and synthesized diffs, not original repository patches from the papers.

## 5. Where these citations have been used in the research

1. **Literature extraction and RAG knowledge preparation:** The five papers were extracted into 25 pattern records and the literature review. Their evidence labels and limitations are stored alongside the patterns. The current records show `human_review_status: pending` and pattern status `draft`; completion of extraction does not mean they have been approved as final RAG evidence.
2. **Repository candidate selection:** The Zenodo record supplies the upstream repository metadata used to build the local 5,000-repository sample and 500 pattern candidate mappings. It is used for sampling, not as a source of optimization results.
3. **Experiment design and execution:** The papers motivate the pattern catalog, but the current evaluation scripts implement a narrower three-arm comparison on a shared frozen repository/workflow snapshot: A (unchanged original), B (pinned and source-corrected `ci-cost`), and C (frozen BGE-M3/Supabase retrieval plus OpenRouter LLM). Arm D (LLM-only) is excluded, so C-versus-B does not isolate retrieval's contribution. The configured pilot targets three measured repetitions per admitted arm and rotates run order; a failed or non-comparable arm may stop early. It pins a RAG dataset hash, retrieves up to five documents, and records the generator model. The common gate applies to B and C and currently permits only narrowly scoped additive dependency caching; it checks workflow syntax and protects existing triggers, permissions, jobs, matrices, steps, and commands. Cache regime is configured as uncontrolled. GitHub run/job records provide timings: active workflow time is the union of actual job execution intervals, and summed job runtime is reported separately. The exporter forms paired B–A, C–A, and C–B repository-level comparisons and bootstraps medians of per-repository savings. Cite scripts/configuration for protocol facts and archived run records/reports for measured outcomes; literature percentages are not local results.
4. **Earlier pattern experiments:** GitHub trigger documentation and earlier controlled fixtures informed the pattern-development work. Those records are separate from the current held-out A/B/C evaluation, whose outcomes must come from its own fork, candidate, safety, and run artifacts.
5. **Evaluation implementation status:** The current implementation is A/B/C only; LLM-only Arm D is explicitly out of scope. The local fork controller, shared candidate validator, run executor, and results exporter are in `evaluation/fork_pipeline.py`, `evaluation/candidate_validator.py`, `evaluation/ci_executor.py`, and `evaluation/results_exporter.py`. Code availability does not establish that a held-out benchmark was completed. Report completion and outcomes only from archived per-repository candidate, validation, and GitHub run evidence.

## 6. Citation status and unresolved references

- `workflow/01_Research_Workflow_Data_Training_Evaluation.md` contains `https://example.org/source-to-replace-with-verified-reference`. This is explicitly a placeholder, not a citation; it must not appear in a final paper bibliography.
- The working plan's Yin et al. reference is now verified as “Developer-Applied Accelerations in Continuous Integration: A Detection Approach and Catalog of Patterns,” ASE 2024, DOI `10.1145/3691620.3695533`; it is listed as supplementary S06. It remains outside the five-paper extraction registry and is not presented as support for a local evaluation outcome.
- The pinned `ci-cost` source and local compatibility correction identify the Arm B implementation, not peer-reviewed outcome evidence. Cite archived candidate, validation, and run records for local results; report an arm as completed only when corresponding records exist.

## 7. Evidence and citation rules for the paper draft

- Cite S01–S04 as primary studies only for the mechanisms, datasets, methods, metrics, and limits they actually report; cite S05 as a secondary review.
- Cite S06 only for its CI acceleration detection/catalog contribution; it is outside the current extracted-pattern registry.
- Cite Kitchenham et al. and Jedlitschka & Pfahl for general empirical-study design/reporting context, not as endorsement or proof that the present protocol meets every guideline.
- Cite Efron & Tibshirani for the general bootstrap method; cite the local exporter for the repository resampling unit, interval procedure, draw count, and seed actually used. Cite the frozen config for the run design and pinned inputs.
- Cite Lewis et al. for the RAG concept and the M3-Embedding paper/model card for the embedding model. Do not transfer their benchmark results to the CloudTune corpus or CI outcome.
- When reporting a literature number, keep its original unit and context (for example, VM/job time versus elapsed time, historical replay versus a live workflow run, or an upper-bound estimate).
- Cite Cardoen et al. (MSR 2024) and the Zenodo version record for the source dataset; cite the project’s own builder, assignments, and manifest for the derived sample, exclusions, split, and random seed. Do not describe the 500 development candidates as 500 confirmed pattern matches.
- Cite project experiment reports/run records for local results. Published reported/estimated benefits are not local `safe_success` labels.
- Use the archived PDF version and page locators in `knowledge/papers.jsonl` and `knowledge/LITERATURE_REVIEW.md` when drafting. This preserves the basis for page-specific claims if the web-hosted version changes.
