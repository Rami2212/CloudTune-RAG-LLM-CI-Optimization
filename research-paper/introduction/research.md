# Repository-Aware CI Workflow Optimization Using LLMs and Research-Grounded RAG

## Research focus

This research investigates whether a repository-aware LLM supported by retrieved research evidence can reduce GitHub Actions execution time and runner use compared with original workflows and the rule-based CI-Cost optimizer. The knowledge base covers 16 literature-derived patterns, their application conditions, limitations, and code examples. Relevant workflow, dependency, and build context guides candidate generation.

## Research questions

1. **RQ1 — Execution time:** How does RAG + LLM compare with original workflows and CI-Cost in median workflow execution time?
2. **RQ2 — Runner usage:** How does RAG + LLM affect summed job runtime compared with original workflows and CI-Cost?
3. **RQ3 — Performance variation:** How do the frequency and magnitude of improvements, slowdowns, and ties vary across repositories?

## Objectives

1. Organize 16 research-derived CI optimization patterns with source citations, applicability conditions, limitations, and code examples.
2. Prepare a reproducible repository sample with separate development and evaluation candidates.
3. Build a RAG pipeline that embeds the knowledge corpus with BGE-M3, retrieves relevant evidence, and combines it with repository context to generate a workflow candidate or a no-change decision.
4. Compare three approaches on the same pinned source: A — Original, B — pinned and source-corrected CI-Cost, and C — RAG + LLM.
5. Measure repeated GitHub Actions executions and compare per-repository median workflow time and summed job runtime, paired percentage savings, and the frequency and magnitude of improvements, slowdowns, and ties. Report execution status and incomplete cases as supporting context.

## Contributions

- **Research-grounded optimization knowledge:** A structured collection of 16 CI patterns with traceable sources, conditions, limitations, and code examples.
- **Repository-aware candidate generation:** A pipeline combining relevant repository context with retrieved evidence to propose workflow optimizations.
- **Reproducible comparative evaluation:** A shared A/B/C execution and reporting pipeline with pinned snapshots, archived candidates, and GitHub run evidence.
- **Measured performance and variation:** Repository-level comparisons of workflow execution time and runner use, including the frequency and magnitude of improvements, slowdowns, and ties within the analysed dataset.

## Evaluation scope

The evaluation sample contains 4,000 candidate repositories divided into four assignments of 1,000. Each eligible repository targets three measured repetitions per distinct workflow variant, with interleaved execution. A no-change arm reuses the corresponding baseline measurements and is identified as such. An optimization candidate is generated once and reused across repetitions.

Active workflow time excludes initial queue delay and periods with no active job; summed job runtime counts concurrent jobs separately. Savings use per-repository medians. Queue delay and candidate-generation latency are separate measures. Cache conditions are uncontrolled. Static validation and successful CI runs provide bounded evidence of behavior preservation; they do not establish unchanged test coverage or full functional equivalence.

There is no LLM-only comparison, so the results assess the combined RAG + LLM approach without isolating the contribution of retrieval. The assigned sample size does not imply that every repository completed evaluation. Full results must retain unsuccessful and slower outcomes; any filtered analysis must identify its exclusions.
