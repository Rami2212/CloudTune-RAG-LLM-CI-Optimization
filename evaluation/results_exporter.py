"""Research-safe cross-repository summaries from actual GitHub Actions evidence.

Repository is the independent analysis unit; repeated runs within one
repository are summarized before bootstrapping across repositories.
Incomplete, unsafe and no-change outcomes stay in the denominator accounting.
"""
from __future__ import annotations

import random
from statistics import median


def _quantile(sorted_values: list[float], percentile: float) -> float:
    if not sorted_values:
        raise ValueError("Quantile requires data")
    at = (len(sorted_values) - 1) * percentile
    lower = int(at)
    upper = min(lower + 1, len(sorted_values) - 1)
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * (at - lower)


def summarize_cohort(repositories: dict, *, bootstrap_samples: int = 1000,
                     seed: int = 20261101) -> dict:
    """Use only fully comparable GitHub job measurements for effect sizes."""
    if bootstrap_samples < 100:
        raise ValueError("At least 100 bootstrap samples are required")
    result = {"total_selected": len(repositories),
              "completed_repositories": sum(r.get("status") == "COMPLETE" for r in repositories.values()),
              "skipped_repositories": sum(r.get("status") == "SKIPPED" for r in repositories.values()),
              "failed_ci_repositories": sum(r.get("status") == "FAILED_TARGET_CI" for r in repositories.values()),
              "platform_inconclusive_repositories": sum(
                  r.get("status") == "INCONCLUSIVE_PLATFORM" for r in repositories.values()),
              "incomplete_repositories": sum(r.get("status") not in {"COMPLETE", "SKIPPED", "FAILED_TARGET_CI", "INCONCLUSIVE_PLATFORM"}
                                             for r in repositories.values()),
              "comparisons": {}}
    comparisons = (("B", "vs_A"), ("C", "vs_A"), ("C", "vs_B"))
    for arm, suffix in comparisons:
        for measure in ("elapsed", "runner"):
            key = f"{measure}_saving_percent_{suffix}"
            values = []
            for repo_id, row in sorted(repositories.items()):
                num = row.get("run_statistics", {}).get(arm, {}).get(key)
                # Values from rejected or incomplete candidates cannot be
                # reported as measured optimization effects.
                if row.get("status") != "COMPLETE" or not isinstance(num, (int, float)):
                    continue
                values.append(float(num))
            values.sort()
            label = f"{arm}_{suffix}_{measure}"
            if not values:
                result["comparisons"][label] = {"paired_repositories": 0,
                    "median_saving_percent": None, "iqr_percent": None,
                    "bootstrap_95pct_ci_percent": None}
                continue
            rng = random.Random(seed)
            medians = sorted(median(rng.choices(values, k=len(values)))
                             for _ in range(bootstrap_samples)) if len(values) >= 2 else []
            result["comparisons"][label] = {
                "paired_repositories": len(values),
                "median_saving_percent": median(values),
                "iqr_percent": [_quantile(values, 0.25), _quantile(values, 0.75)],
                "bootstrap_95pct_ci_percent": (
                    [_quantile(medians, 0.025), _quantile(medians, 0.975)]
                    if medians else None),
            }
    return result
