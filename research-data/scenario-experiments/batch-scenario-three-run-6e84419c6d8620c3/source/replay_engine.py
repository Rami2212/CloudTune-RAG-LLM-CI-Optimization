"""Deterministic service-policy replays, also executed inside the hosted CI fixture.

All times and outcomes here are synthetic. They are never repository speedups.
Only previously observed outcomes are exposed to a scheduling/selection policy.
"""
import json
import os
import statistics


PATTERNS = {
    "P-LIT-FAIL-SCHEDULE", "P-LIT-IDLE-SCHEDULE", "P-LIT-FAILED-JOB-FIRST",
    "P-LIT-BUILD-PRIORITY", "P-LIT-BUILD-SELECT", "P-LIT-DURATION-PREDICTION",
}


def policy(pattern, optimized=False):
    values = {
        "P-LIT-FAIL-SCHEDULE": {"pause_after_failures": 2 if optimized else 0,
                                "notify_on_pause": optimized, "recovery": "explicit_owner_reset"},
        "P-LIT-IDLE-SCHEDULE": {"suppress_unchanged_inputs": optimized,
                                "meaningful_inputs": ["user_source", "external_dependency"]},
        "P-LIT-FAILED-JOB-FIRST": {"order": "previous_failure_ancestors_first" if optimized else "declared",
                                    "cancel_other_jobs": False},
        "P-LIT-BUILD-PRIORITY": {"order": "priority_with_aging" if optimized else "fifo", "max_wait": 12},
        "P-LIT-BUILD-SELECT": {"skip_docs_after_observed_success": optimized,
                               "always_build": ["source", "lockfile", "setup"]},
        "P-LIT-DURATION-PREDICTION": {"predictor": "past_feature_mean" if optimized else "past_global_mean",
                                     "initial_estimate": 20, "train_count": 6},
    }
    return values[pattern]


def dataset(pattern, repeat):
    """Three reproducible workloads; repeat changes durations, never visibility rules."""
    if repeat not in (1, 2, 3):
        raise ValueError("Replay repeat must be 1, 2 or 3")
    scale = repeat
    if pattern == "P-LIT-FAIL-SCHEDULE":
        return [{"id": i, "kind": kind, "outcome": outcome, "duration": 5 * scale}
                for i, (kind, outcome) in enumerate([
                    ("scheduled", "failure"), ("scheduled", "failure"), ("scheduled", "failure"),
                    ("scheduled", "failure"), ("owner_reset", None), ("scheduled", "success"),
                    ("scheduled", "failure"), ("scheduled", "success"),
                    ("scheduled", "failure"), ("scheduled", "success")])]
    if pattern == "P-LIT-IDLE-SCHEDULE":
        return [{"id": i, "kind": kind, "duration": 5 * scale} for i, kind in enumerate([
            "tick", "tick", "generated_commit", "tick", "external_dependency", "tick",
            "tick", "user_source", "tick", "tick"])]
    if pattern == "P-LIT-FAILED-JOB-FIRST":
        jobs = [{"id": "lint", "needs": [], "duration": 30 * scale},
                {"id": "compile", "needs": [], "duration": 10 * scale},
                {"id": "test", "needs": ["compile"], "duration": 5 * scale},
                {"id": "package", "needs": ["test"], "duration": 3 * scale}]
        return {"previous_failures": ["test"], "jobs": jobs,
                "cases": [{"id": "fails_again", "failure": "test"},
                          {"id": "recovered", "failure": None},
                          {"id": "artifact_dependency", "failure": None}]}
    if pattern == "P-LIT-BUILD-PRIORITY":
        return {"no_contention": [{"id": "a", "arrival": 0, "duration": 2, "priority": 1},
                                   {"id": "b", "arrival": 10, "duration": 2, "priority": 5}],
                "contended": [{"id": "blocker", "arrival": 0, "duration": 8, "priority": 0},
                              {"id": "old", "arrival": 1, "duration": 6, "priority": 0},
                              {"id": "ordinary", "arrival": 1, "duration": 6, "priority": 0},
                              {"id": "urgent", "arrival": 2, "duration": 1, "priority": 10},
                              *[{"id": "new-" + str(i), "arrival": 9 + i, "duration": 3, "priority": 9}
                                for i in range(6)]]}
    if pattern == "P-LIT-BUILD-SELECT":
        return [{"id": i, "change": change, "outcome": outcome, "duration": 5 * scale,
                 "failure_cause": "external_setup_failure" if i == 2 else "build_failure" if outcome == "failure" else None}
                for i, (change, outcome) in enumerate([
                    ("source", "success"), ("docs", "success"), ("docs", "failure"),
                    ("lockfile", "failure"), ("docs", "success"), ("setup", "success"),
                    ("docs", "success"), ("source", "failure")])]
    if pattern == "P-LIT-DURATION-PREDICTION":
        return [{"id": i, "feature": feature, "duration": duration * scale}
                for i, (feature, duration) in enumerate([
                    ("small", 10), ("large", 90), ("small", 12), ("large", 92),
                    ("small", 11), ("large", 91), ("small", 12), ("large", 93),
                    ("small", 10), ("large", 90)])]
    raise ValueError("Unsupported replay pattern: " + pattern)


def schedule_failures(data, settings):
    failures, paused, trace, notifications = 0, False, [], []
    for row in data:
        if row["kind"] == "owner_reset":
            failures, paused = 0, False
            trace.append({"id": row["id"], "action": "owner_reset"})
            continue
        if paused:
            trace.append({"id": row["id"], "action": "suppressed"})
            continue
        trace.append({**row, "action": "run"})
        failures = failures + 1 if row["outcome"] == "failure" else 0
        if settings["pause_after_failures"] and failures >= settings["pause_after_failures"]:
            paused = True
            if settings["notify_on_pause"]:
                notifications.append({"after_event": row["id"], "recipient": "synthetic_owner"})
    return {"trace": trace, "notifications": notifications,
            "simulated_work_seconds": sum(r.get("duration", 0) for r in trace if r["action"] == "run")}


def schedule_idle(data, settings):
    version, built, trace = 0, None, []
    for row in data:
        if row["kind"] in settings["meaningful_inputs"]:
            version += 1
        if row["kind"] != "tick":
            trace.append({"id": row["id"], "action": "input", "kind": row["kind"], "version": version})
            continue
        run = not settings["suppress_unchanged_inputs"] or built != version
        trace.append({**row, "version": version, "action": "run" if run else "suppressed"})
        if run:
            built = version
    return {"trace": trace, "simulated_work_seconds": sum(r.get("duration", 0) for r in trace if r["action"] == "run")}


def order_jobs(data, settings):
    jobs = data["jobs"]
    preferred = set(data["previous_failures"])
    while True:
        expanded = preferred | {dep for job in jobs if job["id"] in preferred for dep in job["needs"]}
        if expanded == preferred:
            break
        preferred = expanded
    cases = []
    for case in data["cases"]:
        done, trace, clock, feedback = {}, [], 0, None
        while len(done) < len(jobs):
            ready = [job for job in jobs if job["id"] not in done and all(dep in done for dep in job["needs"])]
            if not ready:
                raise ValueError("Invalid replay dependency graph")
            if settings["order"] == "previous_failure_ancestors_first":
                ready.sort(key=lambda job: job["id"] not in preferred)
            job = ready[0]
            skipped = any(done[dep] != "success" for dep in job["needs"])
            status = "skipped" if skipped else "failure" if job["id"] == case["failure"] else "success"
            started = clock
            clock += 0 if skipped else job["duration"]
            if status == "failure" and feedback is None:
                feedback = clock
            done[job["id"]] = status
            trace.append({"id": job["id"], "needs": job["needs"], "start": started, "end": clock, "outcome": status})
        cases.append({"id": case["id"], "trace": trace, "first_failure_seconds": feedback,
                      "simulated_work_seconds": clock})
    return {"cases": cases, "simulated_work_seconds": sum(c["simulated_work_seconds"] for c in cases)}


def queue_builds(data, settings):
    cases = {}
    for name, rows in data.items():
        pending, trace, clock = list(rows), [], 0
        while pending:
            clock = max(clock, min(row["arrival"] for row in pending))
            ready = [row for row in pending if row["arrival"] <= clock]
            aged = [row for row in ready if clock - row["arrival"] >= settings["max_wait"]]
            reason = "fifo"
            if settings["order"] == "priority_with_aging":
                ready = aged if aged else ready
                reason = "aging" if aged else "priority"
                ready.sort(key=lambda row: (row["arrival"], rows.index(row)) if aged else
                           (-row["priority"], row["arrival"], rows.index(row)))
            else:
                ready.sort(key=lambda row: (row["arrival"], rows.index(row)))
            row = ready[0]
            trace.append({**row, "start": clock, "wait": clock - row["arrival"], "reason": reason})
            clock += row["duration"]
            pending.remove(row)
        cases[name] = {"trace": trace, "max_wait_seconds": max(row["wait"] for row in trace),
                       "urgent_wait_seconds": next((row["wait"] for row in trace if row["id"] == "urgent"), None)}
    return {"cases": cases, "simulated_work_seconds": sum(r["duration"] for rows in data.values() for r in rows)}


def select_builds(data, settings):
    observed, trace, missed = None, [], []
    for row in data:
        # Decision sees only the change and last executed build outcome.
        run = not (settings["skip_docs_after_observed_success"] and row["change"] == "docs" and observed == "success")
        trace.append({"id": row["id"], "change": row["change"], "action": "run" if run else "suppressed",
                      "last_observed_outcome": observed,
                      "observed_outcome": row["outcome"] if run else None})
        if run:
            observed = row["outcome"]
        elif row["outcome"] == "failure":
            missed.append({"id": row["id"], "cause": row.get("failure_cause")})  # Evaluator-only oracle.
    work = sum(row["duration"] for row, decision in zip(data, trace) if decision["action"] == "run")
    return {"trace": trace, "missed_failures": len(missed), "missed_failure_details": missed,
            "missed_failure_rate": len(missed) / max(1, sum(r["outcome"] == "failure" for r in data)),
            "simulated_work_seconds": work, "simulated_saved_seconds": sum(r["duration"] for r in data) - work}


def predict_duration(data, settings):
    history, trace = [], []
    for index, row in enumerate(data):
        pool = history
        if settings["predictor"] == "past_feature_mean":
            pool = [past for past in history if past["feature"] == row["feature"]] or history
        predicted = statistics.mean(p["duration"] for p in pool) if pool else settings["initial_estimate"]
        trace.append({"id": row["id"], "prediction": predicted, "actual": row["duration"],
                      "training_ids": [p["id"] for p in pool], "held_out": index >= settings["train_count"]})
        history.append(row)
    held = [r for r in trace if r["held_out"]]
    return {"trace": trace, "held_out_mae_seconds": statistics.mean(abs(r["prediction"] - r["actual"]) for r in held),
            "simulated_work_seconds": sum(r["duration"] for r in data), "direct_speedup_claimed": False}


def run(pattern, settings, data):
    engines = {"P-LIT-FAIL-SCHEDULE": schedule_failures, "P-LIT-IDLE-SCHEDULE": schedule_idle,
               "P-LIT-FAILED-JOB-FIRST": order_jobs, "P-LIT-BUILD-PRIORITY": queue_builds,
               "P-LIT-BUILD-SELECT": select_builds, "P-LIT-DURATION-PREDICTION": predict_duration}
    return engines[pattern](data, settings)


def validate(pattern, settings, data, result):
    """Check known scenario controls separately from the policy implementation."""
    optimized = settings == policy(pattern, True)
    checks = {"known_policy": optimized or settings == policy(pattern)}
    trace = result.get("trace", [])
    if pattern == "P-LIT-FAIL-SCHEDULE":
        actions = {r["id"]: r["action"] for r in trace}
        checks.update(threshold_not_early=actions[0] == actions[1] == "run",
                      threshold_pause=all(actions[i] == ("suppressed" if optimized else "run") for i in (2, 3)),
                      notification=len(result["notifications"]) == (1 if optimized else 0),
                      explicit_recovery=actions[4] == "owner_reset" and actions[5] == "run",
                      success_resets_counter=all(actions[i] == "run" for i in (6, 7, 8, 9)))
    elif pattern == "P-LIT-IDLE-SCHEDULE":
        actions = {r["id"]: r["action"] for r in trace}
        checks.update(initial_runs=actions[0] == "run", external_change_resumes=actions[5] == "run",
                      source_change_resumes=actions[8] == "run",
                      idle_and_generated_suppressed=all(actions[i] == ("suppressed" if optimized else "run")
                                                       for i in (1, 3, 6, 9)))
    elif pattern == "P-LIT-FAILED-JOB-FIRST":
        checks["case_set_preserved"] = {c["id"] for c in result["cases"]} == {c["id"] for c in data["cases"]}
        for case in result["cases"]:
            order = {r["id"]: i for i, r in enumerate(case["trace"])}
            statuses = {r["id"]: r["outcome"] for r in case["trace"]}
            checks[case["id"] + "_dependencies"] = all(order[d] < order[r["id"]] for r in case["trace"] for d in r["needs"])
            checks[case["id"] + "_jobs_preserved"] = set(order) == {j["id"] for j in data["jobs"]}
            checks[case["id"] + "_outcomes"] = statuses == ({"lint": "success", "compile": "success", "test": "failure", "package": "skipped"}
                if case["id"] == "fails_again" else {j["id"]: "success" for j in data["jobs"]})
            checks[case["id"] + "_order"] = list(order) == (["compile", "test", "lint", "package"] if optimized else
                                                           ["lint", "compile", "test", "package"])
    elif pattern == "P-LIT-BUILD-PRIORITY":
        for name, rows in data.items():
            observed = result["cases"][name]["trace"]
            checks[name + "_no_drops"] = sorted(r["id"] for r in observed) == sorted(r["id"] for r in rows)
            checks[name + "_valid_serial_queue"] = all(r["start"] >= r["arrival"] and
                (i == 0 or r["start"] >= observed[i-1]["start"] + observed[i-1]["duration"])
                for i, r in enumerate(observed))
        checks["no_contention_control"] = [r["wait"] for r in result["cases"]["no_contention"]["trace"]] == [0, 0]
        contended = result["cases"]["contended"]["trace"]
        checks["urgent_priority"] = contended[1]["id"] == ("urgent" if optimized else "old")
        checks["aging_prevents_starvation"] = (any(r["reason"] == "aging" for r in contended) and
            result["cases"]["contended"]["max_wait_seconds"] <= settings["max_wait"] + 2 * max(r["duration"] for r in data["contended"])) if optimized else True
    elif pattern == "P-LIT-BUILD-SELECT":
        checks.update(chronological_order=[r["id"] for r in trace] == [r["id"] for r in data],
                      required_changes_run=all(r["action"] == "run" for r in trace if r["change"] in settings["always_build"]),
                      skipped_outcomes_hidden=all(r["observed_outcome"] is None for r in trace if r["action"] == "suppressed"),
                      setup_failure_accounted=result["missed_failures"] == (1 if optimized else 0),
                      selection_occurs=any(r["action"] == "suppressed" for r in trace) == optimized,
                      recovery_after_observed_failure=trace[4]["action"] == "run")
    elif pattern == "P-LIT-DURATION-PREDICTION":
        checks.update(no_future_training=all(all(t < r["id"] for t in r["training_ids"]) for r in trace),
                      held_out_count=sum(r["held_out"] for r in trace) == len(data) - settings["train_count"],
                      error_measured=result["held_out_mae_seconds"] >= 0,
                      no_speedup_claim=result["direct_speedup_claimed"] is False,
                      all_builds_preserved=len(trace) == len(data))
    return checks


if __name__ == "__main__":
    selected = os.environ["CT_PATTERN"]
    settings = json.loads(os.environ["CT_POLICY"])
    inputs = json.loads(os.environ["CT_DATA"])
    result = run(selected, settings, inputs)
    checks = validate(selected, settings, inputs, result)
    print(json.dumps({"evidence_scope": "synthetic_service_policy_replay", "assertions": checks, "result": result}, sort_keys=True))
    if not checks or not all(checks.values()):
        raise SystemExit("Replay assertions failed: " + str(checks))
