"""Connect structured A/B/C proposals, shared admission and scenario execution."""
from __future__ import annotations

import json
from pathlib import Path
import statistics

from evaluation.repository_preparation import write_json_immutable
from .admission import validate_output, validate_treatment, review_template
from .context import read_source
from .registry import digest
from .scenarios import compare, candidate_policy, validate_policy
from .progress import progress


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def admit_comparator(comparator, context, registry, output, *, reviews=None):
    results = {}
    for pid, entry in comparator["patterns"].items():
        if entry["decision"] != "APPLY":
            progress("VALIDATION",f"{pid}: arm=B; verdict={entry['decision']}; no attributable generated treatment")
            results[pid] = {"verdict": entry["decision"]}
            continue
        proposal = entry["proposal"]
        folder = output / "comparator" / pid
        write_json_immutable(folder / "proposal.json", proposal)
        write_json_immutable(folder / "review_template_B.json", review_template(proposal, context, registry, arm="B"))
        path = reviews / f"{pid}.json" if reviews else None
        review = _load(path) if path and path.exists() else None
        result = validate_treatment(proposal, context, registry, [], arm="B", review=review, review_root=reviews)
        progress("VALIDATION",f"{pid}: arm=B; verdict={result['verdict']}; reasons={','.join(result.get('reasons',[])) or 'none'}")
        suffix = digest(review)[:16] if review else "unreviewed"
        write_json_immutable(folder / f"admission_{suffix}.json", result)
        results[pid] = result
    return results


def scenario_spec(root: Path, pid: str, context: dict) -> dict | None:
    path = root / f"{pid}.json"
    if not path.exists():
        return None
    data = _load(path)
    if (data.get("pattern_id") != pid or data.get("source_commit_sha") != context["source_commit_sha"]
            or data.get("context_sha256") != digest(context)):
        raise ValueError("Scenario specification is stale or belongs to another candidate source")
    if data.get("mode") not in {"controlled_replay", "github_actions"}:
        raise ValueError("Unsupported scenario mode")
    if not data.get("verified_by") or not data.get("artifacts"):
        raise ValueError("Scenario inputs require independent provenance and hashed artifacts")
    for artifact in data["artifacts"]:
        if digest(read_source(root, artifact["path"])) != artifact.get("sha256"):
            raise ValueError("Scenario evidence artifact changed")
    return data


def _hosted_summary(report, decisions, repetitions):
    arms = {}
    baseline = [r for r in report["records"] if r["arm"] == "A" and r.get("comparable") and r["repeat"]>0]
    for arm in report["admitted_arms"]:
        own = [r for r in report["records"] if r["arm"] == arm and r.get("comparable") and r["repeat"]>0]
        full = len(own) == repetitions and len(baseline) == repetitions
        metrics = {}
        for key in ("workflow_elapsed_seconds", "sum_job_runtime_seconds"):
            a = statistics.median(r[key] for r in baseline) if len(baseline) == repetitions else None
            b = statistics.median(r[key] for r in own) if len(own) == repetitions else None
            raw = 100 * (a - b) / a if full and a and b is not None else None
            metrics[key] = {"median": b, "observed_reduction_percent": raw,
                            "realized_reduction_percent": 0.0 if decisions.get(arm) == "NO_CHANGE" else raw}
        arms[arm] = {"complete": full, "contract_pass": full, "decision": decisions.get(arm),
                     "metrics": metrics, "evidence_scope": "github_actions"}
    return arms


def execute_study(snapshot: Path, output: Path, *, registry: dict, comparator: dict,
                  scenarios: Path, reviews: Path | None = None, repetitions: int = 3,
                  github=None, hosted_runner=None) -> dict:
    """Absent prerequisites remain outcomes, not fabricated successful executions."""
    if type(repetitions) is not int or not 1 <= repetitions <= 20:
        raise ValueError("repetitions must be 1..20")
    context, generation = _load(output / "context.json"), _load(output / "report.json")
    if comparator["identity"]["context_sha256"] != digest(context):
        raise ValueError("Comparator and RAG did not see the same frozen context")
    c_reviews = reviews / "C" if reviews else None
    c_admissions = {r["pattern_id"]: r for r in validate_output(output, registry, reviews=c_reviews)["results"]}
    b_admissions = admit_comparator(comparator, context, registry, output, reviews=reviews / "B" if reviews else None)
    generated = {r["pattern_id"]: r for r in generation["outcomes"]}
    results = []
    for pid, pattern in registry["catalogue"].items():
        row = {"pattern_id": pid, "admission": {"B": b_admissions[pid], "C": c_admissions[pid]},
               "outcomes": {"B": comparator["patterns"][pid]["decision"], "C": generated[pid]["decision"]}}
        if all(v == "NO_CHANGE" for v in row["outcomes"].values()):
            status = "NOT_APPLICABLE" if generated[pid].get("assessment", {}).get("status") == "NOT_APPLICABLE" else "NO_CHANGE"
            results.append({**row, "status": status, "realized_optimization_benefit": 0,
                            "note": "No treatment; no nonexistent workflow duration was fabricated"})
            continue
        spec = scenario_spec(scenarios, pid, context)
        if spec is None:
            progress("SCENARIO",f"{pid}: MISSING_SCENARIO_EVIDENCE; no execution dispatched")
            results.append({**row, "status": "MISSING_SCENARIO_EVIDENCE"})
            continue
        proposals, admitted, decisions = {}, [], {"A": "NO_CHANGE"}
        b = comparator["patterns"][pid]
        if b.get("proposal"):
            proposals["B"] = b["proposal"]
        if generated[pid].get("proposal_path"):
            proposals["C"] = _load(output / generated[pid]["proposal_path"])
        policies = {"A": spec.get("baseline_policy")}
        for arm in ("B", "C"):
            decisions[arm] = row["outcomes"][arm]
            verdict = row["admission"][arm]["verdict"]
            if verdict == "NO_CHANGE":
                admitted.append(arm)
                policies[arm] = spec.get("baseline_policy")
                proposals.setdefault(arm, {"files": [], "decision": "NO_CHANGE"})
            elif verdict == "READY_FOR_SCENARIO":
                try:
                    if spec["mode"] == "controlled_replay":
                        policies[arm] = candidate_policy(pid, proposals[arm], context)
                    admitted.append(arm)
                except ValueError as exc:
                    row["admission"][arm] = {"verdict": "UNSUPPORTED_EXECUTION", "reason": str(exc)}
        identity = {"context_sha256": digest(context), "scenario_sha256": digest(spec),
                    "comparator_sha256": digest(b), "rag_sha256": generated[pid].get("proposal_sha256"),
                    "admission_sha256": digest(row["admission"]), "repetitions": repetitions}
        location = output / "measurements" / pid
        artifact = location / "result.json"
        if artifact.exists():
            progress("RESUME",f"{pid}: restoring immutable measurement; no duplicate execution")
            previous = _load(artifact)
            if previous["identity"] != identity:
                raise ValueError("Scenario inputs or admission changed after measurements; use a new study generation")
            results.append(previous)
            continue
        if spec["mode"] == "controlled_replay":
            progress("EXECUTION",f"{pid}: controlled replay; arms={','.join(policies)}; repetitions={repetitions}")
            validate_policy(pid, policies["A"])
            data = spec.get("inputs")
            if not isinstance(data, list) or len(data) != repetitions:
                raise ValueError("Replay inputs must provide one frozen workload per repetition")
            measured = compare(pid, policies, inputs=data, decisions=decisions)
            result = {**row, "identity": identity, "status": "MEASURED_REPLAY", **measured}
        else:
            if pattern["family"] != "complete_work":
                results.append({**row, "status": "UNSUPPORTED_EXECUTION",
                    "reason": "This mechanism requires its event/history/infrastructure scenario, not serial manual dispatch"})
                continue
            if not isinstance(spec.get("required_job_names"), list) or not spec["required_job_names"]:
                raise ValueError("Hosted scenario requires explicit required-job obligations")
            if github is None:
                results.append({**row, "status": "HOSTED_CREDENTIALS_REQUIRED"})
                continue
            cache_regime=spec.get("cache_regime","uncontrolled")
            if pid in {"P-LIT-GHA-CACHE","P-LIT-BAZEL-INCREMENTAL","P-LIT-BAZEL-DEPS","P-LIT-CONFIG-REUSE"} and cache_regime not in {"cold","warm"}:
                results.append({**row,"status":"MISSING_CACHE_REGIME","reason":"Cache treatment measurements require a controlled cold or warm scenario"})
                continue
            if hosted_runner is None:
                from .hosted import run_hosted
                hosted_runner = run_hosted
            # A policy without deployable files cannot silently measure unchanged
            # code as though a distributed/cache or build treatment were applied.
            for arm in list(admitted):
                if decisions[arm] != "NO_CHANGE" and not proposals[arm].get("files"):
                    admitted.remove(arm)
                    row["admission"][arm] = {"verdict": "UNSUPPORTED_EXECUTION", "reason": "No deployable file treatment"}
            observed = hosted_runner(snapshot, location, study_id=("fp-" + digest({"output":str(output.resolve()),"pid":pid,
                "generation":generation["identity"]})[:32]),
                context=context, treatments=proposals, repetitions=repetitions, github=github,
                required_jobs=spec["required_job_names"], admitted=admitted,cache_regime=cache_regime)
            result = {**row, "identity": identity, "status": "MEASURED_HOSTED", "evidence_scope": "github_actions",
                      "cache_regime":cache_regime,
                      "records": observed["records"], "fork_repo": observed["fork_repo"],
                      "arms": _hosted_summary(observed, decisions, repetitions)}
        write_json_immutable(artifact, result)
        progress("MEASUREMENT",f"{pid}: {result['status']}; archived={artifact}")
        results.append(result)
    report = {"protocol": "full-pattern-study-v1", "source_commit_sha": context["source_commit_sha"],
              "patterns": results, "repetitions": repetitions,
              "note": "Replay and GitHub Actions observations are distinct strata; no pooled cross-scope savings."}
    # Admission can progress from review to measurement. Individual measurement
    # artifacts stay immutable; only this derived index is replaced atomically.
    temp = output / "study_report.tmp"
    temp.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temp.replace(output / "study_report.json")
    return report
