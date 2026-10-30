# Research citations and use in this project

This file records the sources that have informed the project so far, how they were applied, and the limits of those uses. It is a provenance note for the current research materials, not a claim that every source has been independently peer reviewed or approved for final publication.

## 1. Research papers used to build the optimization-pattern catalog

The five papers below were downloaded and archived locally. Their PDFs and extracted text are in `research-data/literature/fulltext/`; source metadata, PDF hashes, reviewed sections, methods, samples, and limitations are in `knowledge/papers.jsonl`. The pattern records are in `knowledge/extracted_patterns.jsonl`, with expanded locators and discussion in `knowledge/LITERATURE_REVIEW.md`.

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

## 2. Dataset source used to assemble repository candidates

Cardoen, G. (2026). *A dataset of GitHub Actions workflow histories* (version 2026-05-22). Zenodo. [Record and files](https://zenodo.org/records/20340547) · [DOI: 10.5281/zenodo.20340547](https://doi.org/10.5281/zenodo.20340547).

**What it contributes here:** The source metadata for selecting repository candidates to screen and use in experiments. The project’s `research-data/zenodo_20340547/selection_manifest.json` records the local process: source archive MD5 verified; 54,758 source rows; 46,068 eligible after the recorded recency filter; 5,000 sampled without replacement using seed `20261027`; and a 500-candidate pattern/repository mapping assembled downstream (25 patterns × 20 candidates; see `pattern_repo_candidates_20.csv` and related manifest/context snapshots).

Zenodo describes its source as repository metadata associated with GitHub Actions workflow histories and gives its own collection/selection procedure. The local 5,000-row sample is a **repository candidate list**, not a verified set of currently active repositories or proof that each repository matches its assigned optimization pattern. Pattern assignments are screening leads; experiment reports determine actual eligibility and outcomes. The source’s activity observation period ends 2026-03-26, as recorded in the local manifest.

## 3. Platform, API, and implementation documentation

These sources inform how the prototype operates and records measurements. They are technical documentation, not empirical evidence that an optimization is effective.

| Source | What it is used for in this project |
| --- | --- |
| [GitHub REST API: repository contents](https://docs.github.com/en/rest/repos/contents) | Reading workflow YAML and repository files needed for workflow selection and context. |
| [GitHub REST API: Git trees](https://docs.github.com/en/rest/git/trees) | Inspecting repository trees and locating workflow/configuration files. |
| [GitHub REST API: workflow runs](https://docs.github.com/en/rest/actions/workflow-runs) | Dispatch/run metadata, status, conclusion, timestamps, IDs, and run attempts. |
| [GitHub REST API: workflow jobs](https://docs.github.com/en/rest/actions/workflow-jobs) | Job/step results and runtime measurements associated with a run/attempt. |
| [GitHub REST API: workflows](https://docs.github.com/en/rest/actions/workflows) | Workflow metadata and dispatch endpoint behavior. |
| [GitHub Actions events and triggers](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows) | `workflow_dispatch` behavior and trigger semantics used to run controlled trials. |
| [GitHub Actions: skip workflow runs](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/skip-workflow-runs) | Documentation relevant to skip-run scenarios and the implications for check completion. |
| [GitHub App permissions](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/choosing-permissions-for-a-github-app) | Permission planning for reading repositories, editing fork workflows, enabling Actions, and dispatching runs. |
| [OpenRouter chat completions API](https://openrouter.ai/docs/api/api-reference/chat/send-chat-completion-request) | API contract for sending the selected-pattern optimization request and recording response/model metadata. |
| [OpenRouter model page: recursive/flint-v1.0:free](https://openrouter.ai/recursive/flint-v1.0:free) | Model reference corresponding to the documented default in the project README. Runs may use a different model when `OPENROUTER_MODEL` is set; each experiment should be interpreted using its recorded model. |
| [OpenRouter API key settings](https://openrouter.ai/settings/keys) | Setup instructions for the API credential stored locally in `.env`; credentials are not part of this citation record. |
| [`actionlint`](https://github.com/rhysd/actionlint) | Workflow syntax/static validation tool referenced by the research implementation blueprint. It is not itself a proof of runtime correctness. |
| [Octokit.js](https://github.com/octokit/octokit.js) | GitHub API client reference in the architecture blueprint. |
| [`ci-cost` README](https://github.com/mariotavarez/ci-cost/blob/main/README.md) | Documents a proposed comparison arm in the research plan. That plan includes `ci-cost`; it should be described as planned unless the corresponding arm was actually run and recorded. |

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
3. **Experiment design and execution:** The papers motivate candidate transformations, measurement choices, repeated trials, and safety checks. The prototype records baseline and optimized runs separately, with run IDs/statuses and elapsed/job runtime where available. Any observed effect must be cited to the project’s own run data/report, not to a literature paper’s percentages.
4. **Scenario experiments:** GitHub trigger documentation informs how controlled events are dispatched. Scenario-fixture outcomes are synthetic test evidence for scenario behavior; they are not real-project effectiveness measurements.
5. **Proposed future comparison arms:** The architecture and research-plan documents describe four arms (original, `ci-cost`, LLM-only, and LLM+RAG). The citations to `ci-cost` and related tooling document that design. Do not state that all four arms have been completed unless the experiment records show they were run.

## 6. Draft references that are not established sources

- `workflow/01_Research_Workflow_Data_Training_Evaluation.md` contains `https://example.org/source-to-replace-with-verified-reference`. This is explicitly a placeholder, not a citation; it must not appear in a final paper bibliography.
- The same working plan cites Yin et al., “Developer-Applied Accelerations in Continuous Integration” (ASE 2024), DOI `10.1145/3691620.3695533`. That entry has not been matched to a verified bibliographic record in the project’s five-paper registry or locally archived full text. Treat it as **unverified and unused for the current extracted patterns** until its metadata and actual source are checked. Do not rely on it for a research claim yet.
- `ci-cost` and other tool links in the architecture plan document possible methods/tooling, not peer-reviewed outcome evidence. The `ci-cost` comparison is a planned arm in the blueprint; report it as completed only if there are corresponding data.

## 7. Evidence and citation rules for the paper draft

- Cite S01–S04 as primary studies only for the mechanisms, datasets, methods, metrics, and limits they actually report; cite S05 as a secondary review.
- When reporting a literature number, keep its original unit and context (for example, VM/job time versus elapsed time, historical replay versus a live workflow run, or an upper-bound estimate).
- Cite the Zenodo record for the source dataset and cite the project’s own manifest for the derived sample and random seed. Do not describe the 500 candidates as 500 confirmed pattern matches.
- Cite project experiment reports/run records for local results. Published reported/estimated benefits are not local `safe_success` labels.
- Use the archived PDF version and page locators in `knowledge/papers.jsonl` and `knowledge/LITERATURE_REVIEW.md` when drafting. This preserves the basis for page-specific claims if the web-hosted version changes.
