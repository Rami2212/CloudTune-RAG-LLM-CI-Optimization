# Evaluation methodology

## Aim and comparison arms

The evaluation tests whether optimized CI workflows preserve required behavior while reducing active CI time and runner use. Each repository is evaluated from the same pinned source and workflow snapshot:

- **A — Original:** unchanged workflow; establishes the baseline.
- **B — CI-Cost:** workflow candidate from the pinned, source-corrected CI-Cost implementation.
- **C — RAG + LLM:** candidate from retrieval against the frozen BGE-M3 knowledge base and a fixed OpenRouter model (nvidia/nemotron-3-ultra).

The analysis addresses three research questions:

1. **RQ1 — Execution time:** How does RAG + LLM compare with original workflows and CI-Cost in median workflow execution time?
2. **RQ2 — Runner usage:** How does RAG + LLM affect summed job runtime compared with original workflows and CI-Cost?
3. **RQ3 — Performance variation:** How do the frequency and magnitude of improvements, slowdowns, and ties vary across repositories?

## Evaluation set and controls

The held-out set was created from a 5,000-repository GitHub Actions metadata sample published by [Zenodo](https://zenodo.org/records/20340547). The selection process excluded 500 repositories associated with pattern development or prior experiment records, then sampled 4,000 of the remaining 4,500 uniformly without replacement using seed `20261031`. The 4,000 assignments are fixed and divided into four groups of 1,000. The source metadata is a historical snapshot; it is not treated as proof that a repository is currently eligible.

Before execution, screen each assigned repository for a safe, active build or test workflow and current GitHub accessibility. Pin its source commit, workflow, relevant dependency context, and declared check contract. Keep the same snapshot across A/B/C, use isolated branches on research-owned forks, and leave upstream repositories unchanged. Do not tune prompts, policies, or selection rules from held-out outcomes.

## Candidate preparation and safety admission

1. Prepare A from the original pinned workflow.
2. Generate B with the pinned CI-Cost release and its reviewed source correction.
3. Generate C using the frozen RAG corpus, the same pinned BGE-M3 embedding revision, retrieved evidence, repository context, and the fixed LLM configuration. Preserve retrieved record identifiers and candidate provenance.
4. Apply the same conservative safety gate to B and C. Check YAML structure and Actions syntax, workflow triggers and permissions, job and matrix preservation, build/test commands, dependency inputs, and allowed change scope. The current automatic admission policy is limited to narrow, additive dependency-download caching.

Record each result as admitted, rejected, review-required, inconclusive, no-change, or failed. An optimizer’s no-change decision is retained in the denominator; it is not presented as an applied optimization or a measured saving. Execute optimized candidates only after they pass admission. Preserve original workflow behavior and required checks as correctness constraints.

## GitHub Actions runs and timing

Run admitted A/B/C arms on GitHub Actions in the candidate fork. Perform three measured repetitions per admitted arm and interleave arm order to reduce time-of-day and runner-load bias. Preserve each run’s identity, pinned commit, arm, repetition order, workflow and candidate hashes, conclusion, job timestamps, required-check result, and failure reason. A run that never starts a job is platform-inconclusive, not a zero-duration or failed-workload timing.

The primary timing metric, **active workflow time**, is the union of intervals when at least one target job is running. Overlapping jobs count once; initial queue delay and periods with no active job are excluded. Also report:

- **Initial queue delay:** workflow creation to first actual job start.
- **Workflow makespan:** first job start to last job finish, including idle gaps.
- **Inter-job idle time:** makespan less active workflow time.
- **Summed job runtime:** total duration across executed jobs; overlapping jobs count separately as a runner-use proxy.

## Analysis and reporting

For each repository, first take the median of valid repetitions in each arm. Calculate elapsed-time savings for B and C against A, and for C against B:

`Savings (%) = 100 × (baseline median − candidate median) / baseline median`

Repeat the calculation with summed job runtime for runner-use savings. Report the mean, median, sample standard deviation, first and third quartiles, minimum, and maximum of paired repository-level elapsed savings. Quartiles use linear interpolation at the 25th and 75th percentiles. Calculate aggregate elapsed and runner savings as `100 × (sum of reference medians − sum of candidate medians) / sum of reference medians`; these weight repositories by reference duration. Summed medians are not total runtime across all repetitions or billed usage. Report faster, slower, and tied comparisons from the numeric medians. The repository/workflow is the analysis unit; repeated runs of one repository are not independent observations. Bootstrap confidence intervals were not reported in the current results chapter.

Report candidate admission and required-check pass rates, no-change and rejection rates, failures, regressions, incomplete and platform-inconclusive runs, and the paired repository count. Keep the full 4,000-assignment denominator visible. Calculate savings only from comparable successful executions with passing safety and required-check outcomes; never fill missing measurements with estimates. Report retrieval relevance and generation latency as supplementary measures, separate from CI time.

## Evaluation flow

```mermaid
flowchart TD
    A[Fixed 4,000-repository held-out set] --> B[Screen current eligibility and safe workflow]
    B --> C[Pin source, workflow, context, and checks]
    C --> D[Prepare A: original workflow]
    C --> E[Prepare B: CI-Cost candidate]
    C --> F[Prepare C: frozen RAG plus LLM candidate]
    D --> G[Common candidate and workflow safety checks]
    E --> G
    F --> G
    G -->|Admitted| H[Interleaved GitHub Actions runs: three repetitions per arm]
    G -->|Rejected, review, or no change| I[Record outcome; do not invent savings]
    H --> J[Archive run and job evidence]
    J --> K[Compute per-repository medians and paired savings]
    K --> L[Summarize means, medians, quartiles, aggregate savings, and variation]
    I --> L
```
