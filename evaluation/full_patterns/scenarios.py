"""Executable controlled scenarios for all 25 mechanisms.

Durations are trace inputs, never GitHub measurements. The adapter consumes an
explicit candidate policy or derives an unambiguous supported workflow edit;
it never silently substitutes a hand-written optimized candidate for the model.
"""
from __future__ import annotations

import copy
import math
import statistics

from scripts import scenario_replay as replay
from evaluation.repository_preparation import workflow_doc
from .registry import digest

VERSION = "full-pattern-scenarios-v1"
EXTRA = {"P-LIT-GHA-CACHE", "P-LIT-FAIL-FAST", "P-LIT-CANCEL-STALE", "P-LIT-SKIP-WORKFLOW",
         "P-LIT-CHANGE-FILTER", "P-LIT-CUSTOM-TIMEOUT", "P-LIT-HISTORY-TIMEOUT",
         "P-LIT-DISTRIBUTED-CACHE", "P-LIT-CONFIG-REUSE"}
SUPPORTED = replay.PATTERNS | EXTRA


def reference_policy(pid: str, enabled: bool = False) -> dict:
    if pid=="P-LIT-ENV-CACHE":
        return {"enabled":enabled,"reset_files":enabled,"reset_services":enabled,
                "invalidate_inputs":True}
    if pid in replay.PATTERNS and pid!="P-LIT-ENV-CACHE":
        return replay.policy(pid, enabled)
    if pid not in EXTRA:
        raise ValueError("Unknown scenario mechanism")
    if pid in {"P-LIT-CUSTOM-TIMEOUT", "P-LIT-HISTORY-TIMEOUT"}:
        return {"timeout_seconds": 50 if enabled else 3600, "headroom_factor": 2.0}
    if pid == "P-LIT-FAIL-FAST":
        return {"fail_fast": enabled}
    if pid == "P-LIT-CANCEL-STALE":
        return {"cancel_superseded": enabled, "scope": "workflow_branch"}
    if pid in {"P-LIT-SKIP-WORKFLOW", "P-LIT-CHANGE-FILTER"}:
        return {"skip_dispensable": enabled, "unknown_inputs": "run_all"}
    return {"enabled": enabled, "isolate_project": True, "invalidate_inputs": True}


def policy_contract(pid: str) -> dict:
    return {"adapter": "controlled_replay", "version": VERSION,
            "baseline_settings": reference_policy(pid), "example_treatment_settings": reference_policy(pid, True),
            "note": "Examples define an executable schema, not an instruction to apply a treatment or evidence of benefit."}


def validate_policy(pid: str, settings: dict) -> None:
    if pid in replay.PATTERNS and pid!="P-LIT-ENV-CACHE":
        # These existing audited engines have finite policies. A novel mechanism
        # needs its own verified adapter instead of being reported as executed.
        if settings not in (reference_policy(pid), reference_policy(pid, True)):
            raise ValueError("Policy is outside this version's audited replay contract")
        if any(type(settings[k]) is not type(v) for k,v in reference_policy(pid).items()):
            raise ValueError("Replay settings must preserve declared value types")
        return
    baseline = reference_policy(pid)
    if not isinstance(settings, dict) or set(settings) != set(baseline):
        raise ValueError("Scenario policy keys differ from declared mechanism contract")
    for key, default in baseline.items():
        if (type(default) is float and type(settings[key]) not in {int,float}) or (type(default) is not float and type(settings[key]) is not type(default)):
            raise ValueError("Scenario policy value has the wrong type")
        if type(settings[key]) in {int,float} and (not math.isfinite(settings[key]) or settings[key]<0):
            raise ValueError("Scenario policy contains an invalid numeric value")
    if "timeout_seconds" in settings and not 1 <= settings["timeout_seconds"] <= 86400:
        raise ValueError("Invalid timeout budget")
    if settings.get("scope", "workflow_branch") != "workflow_branch":
        raise ValueError("Cancellation must isolate workflow and branch")
    if settings.get("unknown_inputs", "run_all") != "run_all":
        raise ValueError("Unknown selection inputs require full execution")


def fixture(pid: str, repeat: int = 1) -> object:
    if repeat not in (1, 2, 3):
        raise ValueError("Development fixtures have repeats 1..3")
    if pid=="P-LIT-ENV-CACHE":
        return {"builds":replay.dataset(pid,repeat)["builds"],"install_seconds":20*repeat,
                "compile_test_seconds":20*repeat,"restore_seconds":2*repeat}
    if pid in replay.PATTERNS:
        return replay.dataset(pid, repeat)
    if pid in {"P-LIT-GHA-CACHE", "P-LIT-DISTRIBUTED-CACHE", "P-LIT-CONFIG-REUSE"}:
        return {"builds": [{"id": i, "project": project, "dependency": dep,
                            "toolchain": tool, "configuration": config, "required_output": f"{project}/{dep}/{tool}/{config}",
                            "compatibility_group":"different-abi" if config=="c3" else "shared-abi",
                            "worker":"worker-"+str(i%2),
                            "fetch_seconds": 20 * repeat, "build_seconds": 10 * repeat}
                           for i, (project, dep, tool, config) in enumerate([
                               ("a", "d1", "t1", "c1"), ("a", "d1", "t1", "c1"),
                               ("a", "d2", "t1", "c1"), ("a", "d2", "t2", "c1"),
                               ("a", "d2", "t2", "c2"), ("b", "d2", "t2", "c2"),
                               ("a", "d2", "t2", "c3")])],"cache_service":{"available":True,"trusted":True}}
    if pid == "P-LIT-FAIL-FAST":
        return {"cases": [{"id": "all_pass", "durations": [10, 20, 30], "failure_cell": None},
                          {"id": "one_fails", "durations": [5, 20, 30], "failure_cell": 0}],
                "required_all_diagnostics": False}
    if pid == "P-LIT-CANCEL-STALE":
        return {"runs": [{"id": "old", "branch": "main", "workflow": "CI", "arrival": 0, "duration": 60},
                         {"id": "isolated", "branch": "other", "workflow": "CI", "arrival": 5, "duration": 60},
                         {"id": "new", "branch": "main", "workflow": "CI", "arrival": 10, "duration": 60}]}
    if pid in {"P-LIT-SKIP-WORKFLOW", "P-LIT-CHANGE-FILTER"}:
        return {"events": [{"id": label, "known_inputs": known, "dispensable": disp,
                             "required": not disp, "outcome": outcome, "duration": 20 * repeat}
                            for label, known, disp, outcome in [
                                ("docs", True, True, "success"), ("source", True, False, "failure"),
                                ("config", True, False, "success"), ("mixed", True, False, "success"),
                                ("unknown", False, False, "success")]]}
    if pid in {"P-LIT-CUSTOM-TIMEOUT", "P-LIT-HISTORY-TIMEOUT"}:
        return {"historical_successes": [10, 12, 15],
                "cases": [{"id": "ordinary", "duration": 12, "valid": True},
                          {"id": "cold", "duration": 25, "valid": True},
                          {"id": "slow_valid", "duration": 40, "valid": True},
                          {"id": "hung", "duration": 3600, "valid": False}]}
    raise ValueError("No scenario fixture for mechanism")


def _extra_run(pid, settings, data):
    trace, work, checks = [], 0, {}
    if pid=="P-LIT-ENV-CACHE":
        cache=set();dirty_files=False;dirty_services=False;contamination=0
        for build in data["builds"]:
            key=tuple(build[k] for k in ("dependency","environment","toolchain")) if settings["invalidate_inputs"] else ("all",)
            restored=settings["enabled"] and key in cache
            if not restored:
                dirty_files=dirty_services=False
            if settings["reset_files"]:dirty_files=False
            if settings["reset_services"]:dirty_services=False
            contamination+=int(dirty_files or dirty_services)
            checks[f"clean_{build['id']}"]=not dirty_files and not dirty_services
            duration=(data["restore_seconds"] if restored else data["install_seconds"])+data["compile_test_seconds"]
            work+=duration;cache.add(key)
            trace.append({"id":build["id"],"restored":restored,"tests_executed":True,
                          "output":[build[k] for k in ("source","dependency","environment","toolchain")],"duration":duration})
            dirty_files=dirty_services=True
        checks["input_invalidation"]=settings["invalidate_inputs"]
        return {"trace":trace,"simulated_work_seconds":work,"contamination_count":contamination,"assertions":checks}
    if pid in {"P-LIT-GHA-CACHE", "P-LIT-DISTRIBUTED-CACHE", "P-LIT-CONFIG-REUSE"}:
        cache = {}
        for build in data["builds"]:
            configuration_key="compatibility_group" if pid=="P-LIT-CONFIG-REUSE" else "configuration"
            key = tuple(build[k] for k in (["project"] if settings["isolate_project"] else []) +
                        (["dependency", "toolchain", configuration_key] if settings["invalidate_inputs"] else []))
            trusted=data.get("cache_service",{}).get("trusted",False) and data.get("cache_service",{}).get("available",False)
            hit = settings["enabled"] and key in cache and (trusted or pid!="P-LIT-DISTRIBUTED-CACHE")
            required_intermediate="/".join(build[k] for k in ("project","dependency","toolchain","compatibility_group"))
            intermediate=cache[key] if hit else required_intermediate
            output = build["required_output"]
            # For configuration reuse this is the shared intermediate stage;
            # the configuration-specific final stage still executes every time.
            duration = (2 if hit else build["fetch_seconds"]) + build["build_seconds"]
            cache[key] = required_intermediate
            work += duration
            checks[f"output_{build['id']}"] = output == build["required_output"]
            if pid=="P-LIT-CONFIG-REUSE":checks[f"intermediate_{build['id']}"]=intermediate==required_intermediate
            trace.append({"id": build["id"], "cache_hit": hit, "output": output, "duration": duration,
                          "worker":build.get("worker"),"intermediate_reused":hit and pid=="P-LIT-CONFIG-REUSE"})
        checks["project_isolation"] = settings["isolate_project"]
        checks["input_invalidation"] = settings["invalidate_inputs"]
        return {"trace": trace, "simulated_work_seconds": work, "assertions": checks}
    if pid == "P-LIT-FAIL-FAST":
        for case in data["cases"]:
            failure = case["failure_cell"]
            end = case["durations"][failure] if failure is not None and settings["fail_fast"] else None
            for index, duration in enumerate(case["durations"]):
                actual = min(end, duration) if end is not None else duration
                cancelled = end is not None and duration > end
                trace.append({"case": case["id"], "cell": index, "duration": actual, "cancelled": cancelled})
                work += actual
            checks[case["id"]] = not (settings["fail_fast"] and failure is not None and data["required_all_diagnostics"])
        return {"trace": trace, "simulated_work_seconds": work, "assertions": checks}
    if pid == "P-LIT-CANCEL-STALE":
        rows = data["runs"]
        for row in rows:
            newer = [other["arrival"] for other in rows if other["arrival"] > row["arrival"] and
                     (row["branch"], row["workflow"]) == (other["branch"], other["workflow"])]
            end = row["arrival"] + row["duration"]
            if settings["cancel_superseded"] and newer:
                end = min(end, min(newer))
            trace.append({"id": row["id"], "start": row["arrival"], "end": end,
                          "cancelled": end < row["arrival"] + row["duration"]})
            work += end - row["arrival"]
        checks["latest_and_independent_finish"] = all(not t["cancelled"] for t in trace if t["id"] in {"new", "isolated"})
        return {"trace": trace, "simulated_work_seconds": work, "assertions": checks}
    if pid in {"P-LIT-SKIP-WORKFLOW", "P-LIT-CHANGE-FILTER"}:
        misses = 0
        for event in data["events"]:
            # Decisions see declared input policy, never the oracle outcome.
            run = not (settings["skip_dispensable"] and event["known_inputs"] and event["dispensable"])
            misses += int(not run and (event["required"] or event["outcome"] == "failure"))
            work += event["duration"] if run else 0
            trace.append({"id": event["id"], "run": run, "observed_outcome": event["outcome"] if run else None})
        return {"trace": trace, "missed_failures": misses, "simulated_work_seconds": work,
                "assertions": {"no_required_omissions": misses == 0}}
    false_timeouts = 0
    for case in data["cases"]:
        duration = min(case["duration"], settings["timeout_seconds"])
        cutoff = duration < case["duration"]
        false_timeouts += int(case["valid"] and cutoff)
        work += duration
        trace.append({"id": case["id"], "duration": duration, "timed_out": cutoff})
    return {"trace": trace, "false_timeouts": false_timeouts, "simulated_work_seconds": work,
            "assertions": {"slow_valid_not_cut_off": false_timeouts == 0}}


def execute(pid: str, settings: dict, inputs: object) -> dict:
    validate_policy(pid, settings)
    def valid_numbers(value):
        if type(value) in {int,float} and (not math.isfinite(value) or value<0):
            raise ValueError("Scenario inputs must contain finite nonnegative observations")
        if isinstance(value,dict):
            for item in value.values():valid_numbers(item)
        elif isinstance(value,list):
            for item in value:valid_numbers(item)
    valid_numbers(inputs)
    # Every replay is pure: do not mutate inputs used by the paired arm.
    data = copy.deepcopy(inputs)
    if pid in replay.PATTERNS and pid!="P-LIT-ENV-CACHE":
        result = replay.run(pid, settings, data)
        checks = replay.validate(pid, settings, data, result)
        if result.get("missed_failures", 0):
            checks["no_missed_failures"] = False
    else:
        result = _extra_run(pid, settings, data)
        checks = result.pop("assertions")
    numbers = [v for v in result.values() if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if not all(math.isfinite(v) and v >= 0 for v in numbers):
        raise ValueError("Scenario returned invalid numeric observations")
    return {"adapter_version": VERSION, "pattern_id": pid, "evidence_scope": "controlled_replay",
            "inputs_sha256": digest(inputs), "policy_sha256": digest(settings), "settings": settings,
            "assertions": checks, "contract_pass": bool(checks) and all(checks.values()),
            "result": result, "hosted_ci_speedup_claim": False}


def candidate_policy(pid: str, proposal: dict, context: dict) -> dict:
    policy = proposal.get("policy")
    if isinstance(policy, dict) and policy.get("adapter") == "controlled_replay":
        if policy.get("version") != VERSION:
            raise ValueError("Candidate replay policy version differs")
        settings = policy.get("settings")
        validate_policy(pid, settings)
        return settings
    if pid == "P-LIT-DURATION-PREDICTION":
        settings = (proposal.get("analysis") or {}).get("settings")
        validate_policy(pid, settings)
        return settings
    files = proposal.get("files", [])
    changed = next((f for f in files if f["path"] == context["workflow_path"]), None)
    if changed:
        before, after = workflow_doc(context["original_workflow"].encode()), workflow_doc(changed["content"].encode())
        if pid == "P-LIT-CANCEL-STALE" and before.get("concurrency") != after.get("concurrency"):
            if after.get("concurrency") == {"group": "${{ github.workflow }}-${{ github.ref }}", "cancel-in-progress": True}:
                return reference_policy(pid, True)
        if pid == "P-LIT-FAIL-FAST":
            edits = [new.get("strategy", {}).get("fail-fast", True) for jid,new in after["jobs"].items()
                     if jid in before["jobs"] and before["jobs"][jid].get("strategy", {}).get("fail-fast", True)
                     != new.get("strategy", {}).get("fail-fast", True)]
            if edits and len(set(edits)) == 1 and type(edits[0]) is bool:
                return {"fail_fast": edits[0]}
        if pid in {"P-LIT-CUSTOM-TIMEOUT", "P-LIT-HISTORY-TIMEOUT"}:
            values = {job["timeout-minutes"] for job in after["jobs"].values() if type(job.get("timeout-minutes")) is int}
            if len(values) == 1:
                return {"timeout_seconds": values.pop() * 60, "headroom_factor": 2.0}
        if pid == "P-LIT-GHA-CACHE":
            def caches(doc):
                return [s for job in doc["jobs"].values() for s in job.get("steps", []) if
                        str(s.get("uses", "")).startswith("actions/cache@") or
                        isinstance(s.get("with"), dict) and "cache" in s["with"]]
            old_cache,new_cache=caches(before),caches(after)
            if old_cache != new_cache and new_cache:
                # Native cache actions isolate repositories. Explicit cache keys
                # must track inputs; opaque/broad mechanisms are not assumed safe.
                inputs_valid=all("cache" in s.get("with",{}) or
                    ("hashFiles(" in s.get("with",{}).get("key", "") and "runner.os" in s["with"]["key"])
                    for s in new_cache)
                return {"enabled":True,"isolate_project":True,"invalidate_inputs":inputs_valid}
    raise ValueError("Exact candidate has no executable policy for this scenario; no reference treatment was substituted")


def compare(pid: str, arms: dict[str, dict], *, inputs: list[object], decisions: dict[str,str]) -> dict:
    if "A" not in arms:
        raise ValueError("Scenario comparison requires the original arm")
    records = []
    for repeat, data in enumerate(inputs, 1):
        order = list(arms)
        offset = (repeat - 1) % len(order)
        for arm in order[offset:] + order[:offset]:
            records.append({"arm": arm, "repeat": repeat, **execute(pid, arms[arm], data)})
    summaries = {}
    for arm in arms:
        own = [r for r in records if r["arm"] == arm]
        baseline = [r for r in records if r["arm"] == "A"]
        def primary(result):
            if pid == "P-LIT-DURATION-PREDICTION":
                return "prediction_mae_seconds", result["held_out_mae_seconds"]
            if pid == "P-LIT-BAZEL-PARALLEL":
                return "simulated_elapsed_seconds", result["simulated_elapsed_seconds"]
            if pid == "P-LIT-BUILD-PRIORITY":
                return "urgent_wait_seconds", result["cases"]["contended"]["urgent_wait_seconds"]
            if pid == "P-LIT-PRIORITIZE":
                return "failure_feedback_seconds", result["first_failure_seconds"]
            if pid == "P-LIT-FAILED-JOB-FIRST":
                failing = [c["first_failure_seconds"] for c in result["cases"] if c["first_failure_seconds"] is not None]
                return "failure_feedback_seconds", statistics.mean(failing) if failing else None
            return "simulated_work_seconds", result["simulated_work_seconds"]
        key = primary(baseline[0]["result"])[0]
        controls = [primary(r["result"])[1] for r in baseline]
        observed_values = [primary(r["result"])[1] for r in own]
        control = statistics.median(controls) if all(v is not None for v in controls) else None
        observed = statistics.median(observed_values) if all(v is not None for v in observed_values) else None
        valid = all(r["contract_pass"] for r in own + baseline)
        savings = 100 * (control - observed) / control if control is not None and control > 0 and observed is not None else None
        summaries[arm] = {"complete": control is not None and observed is not None, "contract_pass": valid, "metric": key,
                          "median": observed, "observed_reduction_percent": savings,
                          "realized_reduction_percent": (0.0 if decisions.get(arm) == "NO_CHANGE" or not valid else savings),
                          "decision": decisions.get(arm), "evidence_scope": "controlled_replay"}
    return {"pattern_id": pid, "evidence_scope": "controlled_replay", "records": records,
            "arms": summaries, "ci_dispatches": 0, "hosted_ci_speedup_claim": False}


def development_pilot(registry: dict) -> dict:
    if set(registry["catalogue"]) != SUPPORTED:
        raise ValueError("Scenario implementations do not cover the corpus exactly")
    results = []
    for pid in sorted(SUPPORTED):
        # The treatment here is intentionally a named development reference,
        # never attributed to ci-cost or a model.
        result = compare(pid, {"A": reference_policy(pid), "REFERENCE": reference_policy(pid, True)},
                         inputs=[fixture(pid, i) for i in (1,2,3)], decisions={"A": "NO_CHANGE", "REFERENCE": "APPLY"})
        results.append(result)
    return {"protocol": VERSION, "evidence_scope": "synthetic_development_pilot",
            "patterns": results, "pattern_count": len(results), "ci_dispatches": 0,
            "note": "Includes unsafe negative controls; this is engine verification, not RAG effectiveness."}
