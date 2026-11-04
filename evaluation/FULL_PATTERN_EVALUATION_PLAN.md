> Scope note: This document describes the separate experimental study, not the normal batch flow. The normal A/B/C controller and logs are preserved; broader pattern consideration is integrated into its existing Arm C generator.

# Full-pattern RAG evaluation: coverage audit and proposed redesign

Status: planning only, 2026-11-03. No generator, validator, executor, corpus,
checkpoint, or CI configuration is changed by this document.

Implementation update, 2026-11-04: the separate
[`full_patterns` study pipeline](full_patterns/README.md) now implements the
complete registry, catalogue-wide applicability, extended source context,
per-pattern retrieval, structured proposals, and source-bound structural review.
It also implements controlled scenarios for all 25 mechanisms, exact-file hosted
complete-work execution, shared comparator admission, member-batch integration,
device preflight, history/evidence contracts, retries and stratified analysis.
The executable development verification is separate from live infrastructure
availability and measured effectiveness. The original design below remains the
research rationale; current command and scope details are in the linked README.

## Finding and intended research question

The current protocol measures a narrow caching treatment, not the effectiveness
of the full pattern corpus. The proposed question is: can retrieval-assisted
optimization identify applicable patterns and produce valid, effective changes
across the corpus's mechanisms, compared with the original and ci-cost?

All 25 patterns must be eligible for consideration. Eligibility is not a claim
that every pattern fits every repository or that every treatment preserves an
identical execution trace. Some preserve all work, some intentionally omit work
under an explicit contract, and one is an analytical aid rather than a patch.
Their outcomes need separate, declared estimands rather than one speedup score.

## Inventory and current implementation

Audited local sources:

- `knowledge/extracted_patterns.jsonl`: 25 canonical literature patterns.
- `research-data/rag/rag_dataset.jsonl`: 74 records, comprising 25 pattern
  records and 49 experiment examples. Every pattern has examples: two each,
  except BUILD-PRIORITY, which has one. These are retrieval records, not 49
  independent demonstrations of effectiveness on held-out repositories.
- `knowledge/research_patterns.jsonl`: nine earlier question drafts; not the
  canonical support checklist.
- `evaluation/optimizers/rag_llm.py`: caching-specific retrieval query and
  generation instruction; only complete workflow YAML or NO_CHANGE output.
  Repository context has a 12,000-character total budget, at most 1,800
  characters per file, selected by filename and traversal order. Required-check
  contracts and CI history may explicitly be unverified/uncollected.
- `evaluation/repository_preparation.py`: selected manifest/workflow snapshots;
  does not provide an exhaustive source dependency graph, consumer graph,
  representative timing history, or verified test/required-check contract.
- `evaluation/candidate_validator.py`: narrow additive cache admission and one
  exact workflow/branch concurrency addition under isolated serial dispatch.
  Other changes are rejected or require review. Workflow syntax and passing CI
  alone do not establish equivalence.
- `evaluation/ci_executor.py`: checks that only the selected workflow changes;
  dispatches workflow_dispatch runs and records job timing. This does not
  exercise native path-filter triggers, scheduling policies, or realistic
  superseding revisions.
- `evaluation/fork_pipeline.py`: three-arm admission and serial repeated trial
  execution. A blocked arm can prevent an otherwise eligible arm being measured.

Current support labels below describe the complete generation/admission/measurement
path, not merely whether a YAML field can be parsed:

- **Partial**: narrow generation and admission exist, but mechanism-specific
  causal measurement is incomplete.
- **Admission only**: a narrow edit can pass, but generation discourages it and
  the execution scenario does not exercise its benefit.
- **Unsupported**: no adequate end-to-end mechanism-specific path. Some proposals
  can still be generated contrary to the current prompt; that is not support.

## Complete support matrix

All IDs below have the prefix `P-LIT-`. The proposed checks are implementation
requirements, not assertions that current fixtures already prove them. Every
row is eligible for retrieval and assessment in the proposed protocol.

| Pattern ID                | Examples | Current support | Required evidence and allowed treatment                                                                                              | Required validation and measurement                                                                                                                                               |
| ------------------------- | -------: | --------------- | ------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| P-LIT-GHA-CACHE           |        2 | Partial         | Frozen dependency/toolchain inputs, install behavior and existing caches; add or repair download caching across supported ecosystems | Isolate cache namespaces; cold and warm runs; dependency/OS changes; equivalent tests; transfer and total job time                                                                |
| P-LIT-FAIL-FAST           |        2 | Unsupported     | Matrix contract explicitly permits remaining work to stop after failure; change fail-fast behavior                                   | All-pass and injected-failure scenarios; report expected cancellations, diagnostic loss, time to failure and runner work; do not require intentionally cancelled cells to succeed |
| P-LIT-CANCEL-STALE        |        2 | Admission only  | Branch/PR identity, supersession contract and protected release/deployment exclusions; add scoped cancellation                       | Overlapping old/new revisions on the same branch plus independent branches; latest revision checks finish; saved runner work and latest-revision feedback latency                 |
| P-LIT-SKIP-WORKFLOW       |        2 | Unsupported     | Verified dispensable-event policy and required-status contract; explicit run omission                                                | Event replay with positive/negative cases, branch-protection semantics and full-run oracle; false omissions and work per event, not duration of a nonexistent run                 |
| P-LIT-CHANGE-FILTER       |        2 | Unsupported     | Source/config/generated-file dependency mapping and check contract; path-based triggering                                            | Native push/PR events or a separately validated event emulator; docs/source/shared-config/mixed changes; false negatives, required status, avoided work per event                 |
| P-LIT-CUSTOM-TIMEOUT      |        2 | Unsupported     | Representative successful durations and resource/workload bounds; explicit timeout with headroom                                     | Ordinary, cold, slow-valid and hung workloads; false timeout rate and runaway resource bounds; no claim that a timeout accelerates passing work                                   |
| P-LIT-FAIL-SCHEDULE       |        2 | Unsupported     | Historical failure streak and explicit monitored pause/recovery policy; schedule suppression                                         | Chronological schedule replay; threshold boundary, recovery and reactivation; work saved, missed checks and recovery delay; notifications remain simulated in fixtures            |
| P-LIT-IDLE-SCHEDULE       |        2 | Unsupported     | Repository activity plus external/time-dependent input contract; suppress genuinely redundant schedules                              | Inactivity, external dependency changes and generated commits; work per time window and missed freshness obligations                                                              |
| P-LIT-FAILED-JOB-FIRST    |        2 | Unsupported     | Prior failures, job DAG, artifact dependencies and early-stop contract; reorder/gate jobs                                            | Prior failure repeats and recovers; dependency validity; all required outcomes under the declared policy; failure feedback and total work                                         |
| P-LIT-HISTORY-TIMEOUT     |        2 | Unsupported     | Successful historical durations preceding the evaluated revision, runner/workload identity; derived timeout                          | Chronological holdout, slow-valid and changed-workload scenarios; false cutoffs and runaway work; freeze estimator before test cases                                              |
| P-LIT-PRIORITIZE          |        2 | Unsupported     | Test inventory, order independence and prior failure/duration evidence; reorder tests while retaining full set                       | Compare test IDs/results; order-dependent negative fixture; time to first failure and total suite time                                                                            |
| P-LIT-BUILD-PRIORITY      |        1 | Unsupported     | Constrained-worker queue, arrival/service history and explicit fairness policy; scheduling priority                                  | Controlled contended and uncontended queues; feedback latency, throughput, tail wait and starvation; cannot establish hosted GitHub queue control from YAML alone                 |
| P-LIT-SELECT              |        2 | Unsupported     | Change-to-test dependencies, test inventory and declared selection contract; select affected tests with fallback                     | Complete-suite oracle; added/renamed files, transitive changes and seeded regressions; missed failures, selection recall, time and runner work                                    |
| P-LIT-BUILD-SELECT        |        2 | Unsupported     | Change/history features and explicit build-selection policy; decide whether to build                                                 | Chronological event replay against full-build oracle including setup failures; false omissions, fault recall and resource use; no future outcome features                         |
| P-LIT-BAZEL-PARALLEL      |        2 | Unsupported     | Existing Bazel build, target graph, runner CPU/memory and flags; tune parallelism without removing targets                           | Resource-matched trials, output/test equivalence, memory pressure and failures; elapsed and summed job time                                                                       |
| P-LIT-BAZEL-INCREMENTAL   |        2 | Unsupported     | Bazel inputs/toolchains and trusted result cache; enable input-keyed incremental reuse                                               | Clean/restored outputs, source/toolchain changes, cache corruption/misses and isolation; warm/cold time and transfer overhead                                                     |
| P-LIT-BAZEL-DEPS          |        2 | Unsupported     | Dependency-fetch/install/transfer timings; enable, disable or adjust caching based on measured overhead                              | Cold/warm and no-cache controls; end-to-end time, restore/save bytes and overhead; accept removal of harmful caching when evidence supports it                                    |
| P-LIT-ENV-CACHE           |        2 | Unsupported     | Pinned transitive environment, image identity and reset procedures; reuse validated environments                                     | Clean/restored results, changed dependencies, files/services cleanup and contamination tests; provisioning time and full resource cost                                            |
| P-LIT-UNAFFECTED-STEPS    |        2 | Unsupported     | Input/output traces, conditional dependencies and cold fallback; skip demonstrably unaffected work                                   | Full-run oracle, dynamic paths, added/renamed/config inputs and stale-state cases; false omissions and resource use                                                               |
| P-LIT-SMELL-REPAIR        |        2 | Unsupported     | Concrete smell and evidence for the exact repair; modify relevant workflow/build configuration                                       | Repair-specific semantic/output checks and negative cases; measured timing; a smell label alone never authorizes removal                                                          |
| P-LIT-DURATION-PREDICTION |        2 | Unsupported     | Historical timing features available before prediction; analytical prediction/recommendation                                         | Chronological prediction error, calibration and leakage checks; prediction alone has no direct CI saving; measure any resulting patch separately                                  |
| P-LIT-UNUSED-OUTPUTS      |        2 | Unsupported     | Complete consumer/artifact graph including other workflows and downstream users; remove genuinely unused production                  | Downstream consumer and required artifact comparison; counterexample with a hidden consumer; output-production time and resource use                                              |
| P-LIT-DISTRIBUTED-CACHE   |        2 | Unsupported     | Trusted cache service, isolation, pinned inputs and network topology; shared dependency cache                                        | Cross-project/branch isolation, miss/corruption fallback and transfer overhead; end-to-end resource use including cache infrastructure                                            |
| P-LIT-CONFIG-REUSE        |        2 | Unsupported     | Build configuration compatibility, input/output graph and toolchain identity; reuse compatible intermediate work                     | Retain all configurations; clean/reused outputs, incompatible-setting negative fixture and invalidation; elapsed and total resource use                                           |
| P-LIT-UNUSED-DEP-SKIP     |        2 | Unsupported     | Actual dependency use, transitive/lockfile changes and selection contract; omit unaffected dependency-update builds                  | Complete-build oracle; transitive updates, misclassification and changed locks; missed failures and work per update event                                                         |

Summary: one partially supported mechanism, one narrow admission-only mechanism,
and 23 without adequate end-to-end support. The existing cache gate is not
equivalent to environment caching, Bazel result caching or distributed caching.

## Proposed architecture and decisions

### 1. Corpus-wide applicability before detailed retrieval

Expose a compact catalogue of all 25 IDs, mechanisms, scopes and prerequisites
to the applicability stage. Use repository evidence to identify candidates,
then retrieve detailed records/examples with mechanism-aware queries. The
current global top-five caching query must not silently define the eligible set.
Record every catalogue disposition and reason: applicable, already implemented,
not applicable, or missing evidence. Measure catalogue coverage and retrieval
relevance separately. Preserve synthetic/inconclusive evidence labels.

Request missing evidence before deciding NO_CHANGE when collection is possible.
Use bounded evidence rounds with an explicit budget and a final missing-evidence
outcome. Do not force an APPLY when no justified opportunity exists.

### 2. Evidence collector and repository contract

Collect immutable, source-hashed workflow/build configuration, referenced scripts,
test inventories, artifacts/consumers, job dependencies and relevant tool config
(for example mise/Bazel files). Prioritize by references and mechanism, disclose
omissions/truncation, and keep secret filtering and input-size limits. Obtain
representative pre-treatment CI history where needed, including failures,
cancellations, step timings, queue state and runner labels. Distinguish configured
required checks from verified branch-protection requirements.

Define obligations as required tests, outputs, platform configurations, event
coverage and allowed failure/skip semantics. Preserve those obligations, rather
than requiring textual equality of every command. Selection/suppression patterns
must declare a different execution policy and be checked against a full-run oracle.
Unavailable evidence is a reportable limitation, not inferred permission.

### 3. Structured proposals and shared admission

Replace workflow-only output with a versioned proposal containing pattern IDs,
cited document IDs, source evidence paths/hashes, applicability reasoning,
preconditions, contract obligations, intended changes, scenario adapter,
expected outcome and validation plan. Treatments can contain workflow patches,
allowlisted build-file patches, scheduling policy or an analytical prediction.
Predictions must not be forced into fake workflow patches.

Keep failure states separate: NO_CHANGE, MISSING_EVIDENCE, UNSUPPORTED_EXECUTION,
REVIEW_REQUIRED, INVALID and provider/generation errors. Missing adapter support
must never masquerade as model abstention. Record actual semantic changes rather
than trusting generated comments or estimated-savings text.

Use a mechanism registry linking each pattern to evidence, permitted edits,
validators, scenario adapters and outcome metrics. Apply identical admission
requirements to B and C when proposing the same treatment. Preserve security,
secret, source-integrity and provenance checks. Reviewer approval must be an
explicit source/candidate/policy-bound artifact when automated checks cannot
establish the contract; build the consumption path rather than leaving every
non-cache proposal permanently blocked. Review acceptance is not measured success.

### 4. Execution and outcomes by mechanism

Implement four experiment families and one analytical evaluation:

1. Complete-work execution: caching, parallelism, configuration/output repair
   and reuse. Compare successful equivalent outputs and full workloads.
2. Failure/overlap: fail-fast, stale cancellation and job/test prioritization.
   Include faulted and recovered cases; measure failure/latest-revision feedback
   and resource work. Expected treatment cancellations have explicit semantics.
3. Event selection and schedules: filtering, skipping and selection. Replay
   event sequences with a full-work oracle; measure omissions and work per event
   or window. Zero execution is not a zero-second successful workflow.
4. Resource controls and infrastructure: timeout, shared/environment caches and
   queue priority. Include history, constrained resources, external costs,
   fairness, contamination and false-cutoff scenarios as applicable.
5. Duration prediction: chronological prediction quality. Any downstream timing
   benefit requires an independently measured treatment.

Adapters must declare when they are controlled fixtures, historical replay or
real hosted CI. Replay/simulation estimates must not be pooled with measured
hosted savings. Native trigger/queue behavior cannot be inferred from manually
dispatched workflow runs. Multi-revision scenarios preserve source identity
within each matched scenario rather than pretending every run uses one commit.

For each eligible scenario compare A original, B pinned ci-cost and C fixed-model
RAG under the same resources, history and obligations. Tool inability becomes
explicit abstention/unsupported coverage. Optional D LLM-only is necessary for
a direct claim about retrieval's added value. Do not hand-improve B proposals.
Remove the all-arms admission bottleneck for per-arm collection: measure an
admitted arm against A even if another is rejected; retain rejected arms in
the relevant eligible denominator and keep paired C-vs-B availability explicit.

### 5. Reporting and predeclared denominators

Report separately: screened repositories, study eligibility, per-pattern
applicability, evidence sufficiency, proposal/admission rates, review outcomes,
execution correctness, abstention reasons, and measured benefits/regressions.
Keep incompatible research contracts in separate strata. Predeclare minimum
benefit and equivalence/selection-quality criteria, history windows, cache
regimes, repetitions and maximum budgets before the held-out run.

Use repository/scenario as the analysis unit, not independent repeated runs.
Report paired medians and uncertainty where sample size permits; include failed
and rejected eligible candidates in realized-success denominators. Ineligible
repositories remain visible in screening totals. Do not turn missing/invalid
baselines into numeric savings. Report NO_CHANGE and semantic no-effect changes
as zero realized optimization benefit while retaining raw timing variability.
Never aggregate prediction accuracy, selection recall and CI time into one
percentage. Publish raw job/event records and protocol identities.

## Implementation sequence and acceptance criteria

1. Add a versioned 25-pattern mechanism registry and schema; validate exact ID
   coverage against the frozen corpus. Each row has an evidence contract,
   validator, scenario adapter and metric. Unsupported execution is explicit.
2. Expand source/context collection and history contracts; test integrity,
   referenced-file selection, omitted inputs and secret filtering.
3. Add corpus-wide applicability, general retrieval, evidence requests and
   structured proposals. Test known applicable cases for all 25 patterns,
   already-optimized cases, missing evidence and justified abstention.
4. Implement shared mechanism validators plus source-bound review artifacts.
   Test unsafe scope changes, missing obligations, irrelevant citations,
   stale approvals and patch/provenance mismatch. Fail closed on invalid data.
5. Implement scenario adapters in stages: complete-work; failure/overlap;
   selection/schedules; infrastructure/controls; prediction. Every pattern needs
   an applicability-positive fixture, negative/contraindicated fixture and the
   mechanism-specific correctness/measurement tests listed in the matrix.
6. Update arm orchestration, result schemas and analysis; prove that rejected
   B/C arms, expected cancellations, zero-run events and missing baselines are
   represented without inflated savings or suppressed eligible observations.
7. Run a development-only pilot on repositories/fixtures outside the held-out
   pool. Freeze prompts, model, registry, policy, history windows and analysis
   after the pilot. All 25 patterns must have a demonstrated evaluation route
   before calling the system a full-pattern evaluation. Fixture success does
   not imply universal applicability to held-out repositories.
8. Launch a separately named study only after those acceptance checks pass.

## Migration and active-run protection

Do not modify or reset an active controller's frozen inputs. Retain existing
results as the narrow-protocol pilot, not evidence of full-pattern effectiveness.
After an orderly stop, preserve pending dispatch reconciliation and archive
all evidence before replacing any evaluator implementation. A code change to
files included in implementation_digest can intentionally invalidate resume.

Use new prompt, policy, protocol, result-schema and adapter versions and a new
batch identity/configuration for the expanded study. Never patch existing
identity hashes to bypass checks or reinterpret earlier verdicts retroactively.
Corpus expansion/re-ingestion is not required merely to remove the current
evaluation restrictions. If the corpus changes independently, version its hash.

The first 24 held-out rows already inspected must be tracked as exposed under
the old protocol. Do not use their outcomes to tune new prompts or thresholds;
declare their handling before the new study (for example, separate exploratory
reporting rather than presenting them as untouched confirmation data).

## Decisions to resolve during design, before implementation

- Whether all mechanism families run in one study with separate strata, or
  in linked substudies; either way every pattern remains represented.
- Which source/test/artifact obligations establish acceptable equivalence and
  which selection policies are explicitly permitted in each stratum.
- Which scheduling/cache infrastructure can be measured directly, versus only
  simulated or replayed; controlled worker queues may be needed for priority.
- Budget and pilot-based repetition requirements per scenario, and whether D
  is included to isolate retrieval's contribution.

These decisions do not justify retaining a hidden cache-only restriction. They
define the honest scope and evidence needed to evaluate every corpus mechanism.
