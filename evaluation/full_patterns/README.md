# Full-pattern evaluation implementation

The versioned study is available through `python -m evaluation.full_patterns`
as separate experimental tooling. `scripts.run_evaluation_batch` retains the
original A/B/C controller, logging, ordering and batch IDs. All 25 frozen
corpus mechanisms can be assessed, proposed, admitted and executed in declared
controlled scenarios. Complete-work file treatments also have a GitHub Actions
adapter. Legacy batch results are not migrated or reinterpreted.

Controlled replay uses supplied traces and policies; its numbers are not real
repository speedups. Hosted measurements use actual admitted source changes and
GitHub job evidence. These scopes, mechanisms, metrics and prior-exposure cohorts
remain separate in analysis.

## Implemented

- A versioned registry checks exact coverage of the 25 pattern records and 49
  eligible examples. Each mechanism declares evidence requirements, a scenario
  and outcome metrics. Duration prediction has an analytical output rather than
  a fabricated workflow patch.
- Applicability explicitly assesses every catalogue ID, before per-pattern
  retrieval. Missing source/history/contract information is MISSING_EVIDENCE,
  distinct from an already implemented or inapplicable optimization.
- BGE-M3 retrieval uses the existing verified Supabase index and its existing
  `filter_pattern_id` parameter. Every applicable pattern also receives its
  complete frozen canonical record, including prerequisites and limitations.
  No corpus rebuild or re-ingestion is needed.
- Source context includes complete bounded files, explicit omissions and hash
  checks. Additional read-only collection follows source references and includes
  mise, Bazel, Gradle, Composer, test and local-action configuration. It reads
  the pinned Git tree; it never executes repository scripts. An omission is
  disclosed, not silently presented as a complete source/dependency graph.
- Proposals can edit frozen build/configuration inputs, propose a scheduling or
  infrastructure policy, or supply an analytical result. They are not limited
  to caching. All preconditions and source/corpus citations are recorded.
- Structural validation checks provenance, file paths, workflows and actionlint.
  All patterns can reach evidence/contract review under the same validation
  function for structured B/C proposals. The ci-cost adapter retains its exact
  emitted patch and attributes observed edits, never hand-improves the comparator
  or credits recommendation comments as implemented optimizations.
- Review artifacts bind the arm, source, context, corpus, policy and proposal,
  and reference hashed evidence artifacts. A reviewer must verify every declared
  evidence requirement and safety test. Approval produces READY_FOR_SCENARIO,
  never an automatic successful-optimization verdict. Local review files are
  audit artifacts, not cryptographic reviewer authentication.
- Requests, responses, context, retrieval rankings and results are immutable.
  A normal Ctrl+C releases the output lock. Restart the identical command to
  reuse completed requests/responses; provider timeouts are not auto-retried.
  On a timeout an explicit restart may send an unanswered request again; it
  cannot recover a response the process never received. Code, context, model,
  corpus or budget changes require a new output directory.
- All 25 mechanism scenarios execute with declared policies, oracle checks and
  appropriate metrics, including failure feedback, constrained-queue wait,
  selection misses, timeout false positives and chronological prediction error.
  Unexecutable candidate policies remain UNSUPPORTED_EXECUTION; a reference
  treatment is never silently substituted for a model/tool proposal. Existing
  audited replay engines accept their versioned finite policy contracts; novel
  parameterizations require an adapter revision and development verification.
- The hosted complete-work adapter permits exact admitted build/configuration
  file edits, preserves file modes and verifies the full source tree. It reuses
  the existing durable dispatch-intent/run-ID ledger. Queued/cancelled runs,
  provider errors and review/missing-evidence outcomes remain explicit.
- Forks have study-specific names, numeric identity checks and retention. The
  adapter refuses to adopt an untracked existing fork, including a different
  fork GitHub may return when an account already belongs to that fork network.
  Resolve account/fork ownership deliberately; never delete evidence to bypass it.
- Historical runs completed after the source-commit cutoff are excluded. A
  source-bound evidence bundle supplies independent contracts, traces and graphs;
  the collector never claims that bounded source inspection proves a complete
  dependency graph. Missing facts produce an actionable evidence request file.
- CPU is the default. CUDA is used only when CLOUDTUNE_RAG_DEVICE=cuda or cuda:N
  is set in the shell or ignored `.env`. Explicit CUDA requests are checked
  before model calls, with no silent CPU fallback. Runtime and actual model
  device are recorded. CUDA installation is optional.

## Commands

Run from the repository root. Existing Python dependencies are sufficient for
offline catalogue/context work. Model generation uses `OPENROUTER_API_KEY` and
the existing RAG dependencies, Supabase credentials and model revision checks.
Environment variables override the ignored root `.env`, as in the legacy code.

Audit the complete catalogue offline:

```powershell
.\.venv\Scripts\python.exe -m evaluation.full_patterns catalogue
```

Run the development pilot before any new repository set. It executes all 25
controlled mechanisms, including a deliberately unsafe build-selection control,
and binds the verification record to this implementation and corpus:

```powershell
.\.venv\Scripts\python.exe -m evaluation.full_patterns verify
```

The pilot is offline engine/integration verification, not a live GitHub/provider
availability check or evidence of RAG effectiveness. Updating evaluator code
invalidates its verification record until it is rerun.

An optional live smoke contacts the configured free model and read-only index
with a synthetic matrix source; it never creates a GitHub repository or job:

```powershell
.\.venv\Scripts\python.exe -m evaluation.full_patterns smoke --output evaluation/full-pattern-results/live-smoke-study01
```

A provider error pauses without paid fallback or automatic retry. The archived
request can be retried by the same command while code/settings are unchanged.
After a code change, preserve that output and choose a new smoke output path.

Preview the first 20 assigned rows without model/API calls:

```powershell
.\.venv\Scripts\python.exe -m evaluation.full_patterns batch --member 1 --list --start-at 1 --limit 20
```

Preflight prepares new snapshots, collects context/history, generates A/B/C
proposals and writes review/evidence/scenario templates. It does not dispatch CI:

```powershell
.\.venv\Scripts\python.exe -m evaluation.full_patterns batch --member 1 --preflight-only --start-at 1 --limit 20
```

`evaluation/configs/full_patterns.json` freezes budgets and repetitions. Its
ENV model setting resolves OPENROUTER_MODEL once into the batch identity. Do
not change model, code, device, corpus or study configuration within a batch.
Positions are member-local: member 2 position 100 is global row 1100.
`--batch-id` is optional and defaults to `full-member-01` for member 1,
`full-member-02` for member 2, and so on. Repeating a command without a batch ID
resumes that member's default full-pattern batch. Supply a separate ID when
starting an independent study without archiving the existing default batch.
`--stop-at` is inclusive; `--limit` counts original positions, and
`--max-repositories` separately caps unfinished rows attempted in an invocation.

Source snapshots, prompts and private ledgers live under the ignored
`evaluation/full-pattern-results/<batch-id>/trials/rNNNN-gNN/` tree. For a trial,
`rag/evidence_requests.json` lists absent prerequisites; `scenario_templates/`
contains unverified templates. Supply independent source-derived evidence, not
the synthetic reference fixture pretending to be target-repository evidence.

With source-bound inputs and reviews prepared, the connected run command is:

```powershell
.\.venv\Scripts\python.exe -m evaluation.full_patterns batch --member 1 --run --start-at 1 --limit 20 --scenario-root "D:\path\to\scenario-inputs" --evidence-root "D:\path\to\evidence" --reviews "D:\path\to\reviews"
```

No repository set is launched by installing or verifying this implementation.
An explicit run can dispatch hosted jobs only for admitted hosted scenarios.
Missing facts/reviews/scenarios stay visible and prevent fabricated successes.
An admitted arm can run when another is rejected; all rejected arms remain
in the outcome accounting.

## Input and recovery contracts

Input roots use member-local subdirectories `r0001/`, `r0002/`, etc. An evidence
directory contains `evidence.json` with source_commit_sha and named `facts`.
Each fact has status VERIFIED/UNVERIFIED, a value/explanation, verified_by when
verified, and artifacts [{path, sha256}] relative to the evidence directory.
No verifier name alone establishes an assertion: source-bound artifact hashes
are required, and the shared independent review checks applicability.

Scenario directories contain one `P-LIT-*.json` per applicable pattern, with
pattern_id, source_commit_sha, context_sha256, mode, verified_by and hashed
artifacts. Controlled replay also supplies baseline_policy and one workload per
configured repetition in `inputs`. Those inputs use the adapter's scenario
schema; independent review must establish their correspondence to the source.
Hosted scenarios supply nonempty required_job_names and use the actual patches;
they do not infer event-filter, supersession, queue or service semantics from
manual workflow dispatch. Policy-only proposals cannot be measured as if they
were deployed code.

Native cache treatments additionally require cache_regime cold or warm. Cold
mode clears caches only inside the positively identified study-owned fork and
refuses reset while any fork job is active. Warm mode starts from that isolated
cache state and performs one successful, checkpointed warm-up per admitted arm;
warm-ups are archived separately and excluded from measured repetitions. A
warm-up is not automatically labelled a cache hit. Cold and warm observations
are separate analysis strata. Cache management uses the documented
[GitHub cache API](https://docs.github.com/en/rest/actions/cache) and requires
Actions write permission on that study fork. External cache infrastructure
still requires its own verified scenario; clearing GitHub caches does not
establish the state of an external cache service.

Reviews are stored under `rNNNN/B/P-LIT-*.json` and `rNNNN/C/P-LIT-*.json`, with
their evidence artifacts alongside. A/B/C use the same mechanism obligations.
ci-cost does not need RAG citations; its missing preconditions are explicit and
must pass independent admission just like a RAG proposal's claims.

Repeat the identical command after a normal interruption or provider pause.
GitHub pending dispatches are reconciled before new jobs. Use --rerun for a new
preserved generation of finished failed/blocked rows after collecting additional
evidence; the active retry round resumes on repeated --rerun. The configured
max_evidence_rounds bounds this process. Successful and unstarted positions are
not reset by a failed-row retry. Review changes before any measurement can
progress within a generation; changing already-measured admissions or inputs
requires a new generation. Never edit identity hashes or erase checkpoints.

`--publish-only` rebuilds the cross-repository analysis from each row's latest
generation. Results include failures, abstentions, missing evidence and review
outcomes. Confidence intervals use repository units, not repetitions; replay,
hosted, prediction and exposed/unexposed results are never pooled.

Use a pinned **development** snapshot generated by the existing preparation
workflow. Set these paths to an actual development snapshot and a new output
directory outside it. Source snapshots contain `manifest.json`,
`source/original.yml` and `source/files_manifest.json`.

```powershell
$snapshot = "D:\path\to\development\repository-snapshot"
$studyOutput = "D:\path\to\full-pattern-study\proposal-001"
$extendedContext = "D:\path\to\full-pattern-study\context-001"

# Optional: read additional files from the pinned GitHub tree.
.\.venv\Scripts\python.exe -m evaluation.full_patterns collect --snapshot $snapshot --output $extendedContext

# Inspect what will be available to the model without an LLM/API call.
.\.venv\Scripts\python.exe -m evaluation.full_patterns context --snapshot $snapshot --extended $extendedContext --output "$studyOutput-context"

# Replace this value with the fixed model chosen for the new experiment.
$generatorModel = "provider/selected-model:free"
.\.venv\Scripts\python.exe -m evaluation.full_patterns propose --snapshot $snapshot --extended $extendedContext --output $studyOutput --model $generatorModel --top-k 3

# Structural admission and review templates; no CI runs.
.\.venv\Scripts\python.exe -m evaluation.full_patterns validate --output $studyOutput
```

`--top-k` limits retrieved chunks per applicable pattern, not which patterns
are eligible. There is one applicability request plus at most one proposal
request for each of the 25 applicable patterns. Calls are sequential and frozen;
missing-evidence dispositions do not trigger speculative proposal calls.

After `validate`, each proposed pattern has a `review_template_C.json`. Copy a
template to a separate reviews directory as `P-LIT-EXAMPLE.json`, identify the
reviewer and UTC timestamp, record APPROVE or REJECT, and reference actual
evidence files beneath that reviews directory using relative paths and SHA-256.
An APPROVE requires every checklist item VERIFIED with a rationale and evidence.
Then run:

```powershell
.\.venv\Scripts\python.exe -m evaluation.full_patterns validate --output $studyOutput --reviews "D:\path\to\reviews"
```

Outputs include `identity.json`, `context.json`, complete applicability records,
per-pattern requests/responses/retrieval/proposals/patches, `report.json`, and
versioned admission records. Review submissions are not applied to source code.
Proposal output can contain repository content and provider responses: keep it
private until an explicit export step. Use separate directories from legacy
trial checkpoints and avoid committing raw output.

## Study boundaries

All mechanisms have executable controlled scenarios; this does not make every
mechanism directly deployable on arbitrary GitHub-hosted infrastructure. Real
queue control and distributed/environment cache infrastructure must actually
exist before using native measurements. Controlled replays remain a separate
evidence scope, even when their traces are repository-derived. Approval is not
measured benefit. Full-pattern candidate generation does not force an APPLY.

The optional LLM-only D ablation is not enabled by this three-arm batch; avoid
claiming a causal benefit from retrieval alone without that separate ablation.
Previously inspected member-1 rows 1–24 are marked previously_exposed and kept
apart from untouched confirmation data. Use the normal `scripts.run_evaluation_batch`
command for the original evaluation flow. Existing study data is never silently migrated.

Normal progress logging shows concise, flushed UTC stage summaries, screening
reasons, restored checkpoints, device selection, model request/response timing,
generated proposals, admission reasons and CI progress. Per-file collection,
per-history-run output, individual non-applicable patterns and repeated no-change
admission lines are hidden. Set `CLOUDTUNE_LOG_LEVEL=debug` in the shell or ignored
`.env` to display the full diagnostics when troubleshooting.
Credentials and full request/response bodies are not printed. CI run/job progress
continues to use the existing hosted executor's detailed logs.

## Verification

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_full_patterns tests.test_full_pattern_execution -v
```

Tests use mocked provider/retriever/GitHub responses and development inputs;
they exercise all catalogue mechanisms, context integrity, broad proposal
types, replay, missing evidence and review/provenance boundaries. They do not
establish live provider availability, performance gains or available external
infrastructure. The full test suite also exercises the original evaluation
controller and checks that normal batch commands never enter this experimental runner.
