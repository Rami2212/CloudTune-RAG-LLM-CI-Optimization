"""Per-mechanism, per-scope paired summaries; repeats are not independent repos."""
from __future__ import annotations

from collections import Counter, defaultdict
import random
import statistics


def summarize(studies: list[dict], *, minimum_benefit: float = 5.0) -> dict:
    strata = defaultdict(list)
    dispositions = Counter()
    for study in studies:
        repo = study["repo_id"]
        exposure = study.get("exposure", "unexposed")
        for row in study.get("patterns", []):
            dispositions[row["status"]] += 1
            scope = row.get("evidence_scope", "not_measured")
            for arm in ("B", "C"):
                dispositions[f"{arm}:{row.get('outcomes', {}).get(arm, 'UNKNOWN')}"] += 1
            a = row.get("arms", {}).get("A", {})
            metrics = list(a.get("metrics", {})) if scope == "github_actions" else [a.get("metric")]
            for metric in metrics:
                if metric is None:
                    continue
                data = {"repo_id": repo, "arms": {}, "baseline_valid": a.get("complete") and a.get("contract_pass")}
                for arm, obs in row.get("arms", {}).items():
                    value = obs.get("metrics", {}).get(metric, {}) if scope == "github_actions" else obs
                    data["arms"][arm] = {"median": value.get("median"),
                        "valid": bool(obs.get("complete") and obs.get("contract_pass")),
                        "realized": value.get("realized_reduction_percent"),
                        "decision": obs.get("decision")}
                strata[(row["pattern_id"], scope, metric, exposure,row.get("cache_regime","not_applicable"))].append(data)
    comparisons = []
    for (pid, scope, metric, exposure,cache_regime), units in sorted(strata.items()):
        # Multiple input repetitions are already collapsed by the study runner.
        if len({u["repo_id"] for u in units}) != len(units):
            raise ValueError("Duplicate repository/scenario analysis unit")
        for treatment, control in (("B", "A"), ("C", "A"), ("C", "B")):
            effects, successful = [], 0
            baseline_count = sum(bool(u["baseline_valid"]) for u in units)
            for unit in units:
                t, c = unit["arms"].get(treatment), unit["arms"].get(control)
                if not t or not c or not t["valid"] or not c["valid"] or not c["median"] or t["median"] is None:
                    continue
                observed = 100 * (c["median"] - t["median"]) / c["median"]
                # NO_CHANGE variability is retained in raw records, never credited
                # as a realized optimizer improvement against the original arm.
                realized = 0.0 if t["decision"] == "NO_CHANGE" and control == "A" else observed
                effects.append(realized)
                successful += int(realized >= minimum_benefit and t["decision"] not in {"NO_CHANGE", None})
            bootstrap = []
            if len(effects) >= 2:
                rng = random.Random(20261104)
                bootstrap = sorted(statistics.median(rng.choices(effects, k=len(effects))) for _ in range(1000))
            comparisons.append({"pattern_id": pid, "evidence_scope": scope, "metric": metric, "exposure": exposure,"cache_regime":cache_regime,
                "comparison": f"{treatment}_vs_{control}", "repository_units": len(units),
                "baseline_valid_units": baseline_count, "paired_valid_units": len(effects),
                "median_realized_reduction_percent": statistics.median(effects) if effects else None,
                "bootstrap_95pct_interval": [bootstrap[24], bootstrap[974]] if bootstrap else None,
                "safe_beneficial_units": successful, "minimum_benefit_percent": minimum_benefit,
                "safe_benefit_rate_among_baseline_valid": successful / baseline_count if baseline_count else None})
    return {"schema": "full-pattern-analysis-v1", "repositories": len(studies),
            "dispositions": dict(dispositions), "comparisons": comparisons,
            "note": "No pooling of replay, hosted CI, prediction metrics or prior-exposure strata."}
