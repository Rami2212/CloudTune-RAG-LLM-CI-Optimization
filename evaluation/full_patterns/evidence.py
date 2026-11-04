"""Bounded historical facts and explicit source-bound supplementary evidence."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import quote, urlencode

from evaluation.repository_preparation import write_json_immutable
from .context import SECRET, read_source
from .registry import digest
from .progress import progress


def instant(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("History times must include a timezone")
    return parsed.astimezone(timezone.utc)


def collect_history(snapshot: Path, output: Path, *, reader, limit: int = 20) -> dict:
    """Exclude runs completed after the source commit, including rerun attempts."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("History limit must be 1..100")
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    identity = {"source_commit_sha": manifest["source_commit_sha"],
                "manifest_sha256": digest((snapshot / "manifest.json").read_bytes()), "limit": limit}
    archive = output / "history.json"
    if archive.exists():
        saved = json.loads(archive.read_text(encoding="utf-8"))
        if saved["identity"] != identity:
            raise ValueError("History identity changed")
        progress("HISTORY",f"Restored {len(saved['runs'])} frozen historical runs; cutoff={saved['cutoff_utc']}")
        return saved
    repo = manifest["repo_id"]
    commit = reader.get_json(f"/repos/{repo}/commits/{manifest['source_commit_sha']}")
    if commit.get("sha") != manifest["source_commit_sha"]:
        raise ValueError("History cutoff commit differs from snapshot")
    cutoff = commit["commit"]["committer"]["date"]
    progress("HISTORY",f"{repo}: source cutoff={cutoff}; collecting up to {limit} pre-commit completed runs")
    workflow = quote(Path(manifest["workflow_path"]).name, safe="")
    query = urlencode({"per_page": 100, "status": "completed", "created": "<=" + cutoff,
                       "branch": manifest["source_default_branch"]})
    runs, excluded = [], 0
    for page in range(1, 6):
        rows = reader.get_json(f"/repos/{repo}/actions/workflows/{workflow}/runs?{query}&page={page}").get("workflow_runs")
        if not isinstance(rows, list):
            raise ValueError("Invalid history response")
        for row in rows:
            if (not row.get("created_at") or not row.get("updated_at") or
                    instant(row["created_at"]) > instant(cutoff) or instant(row["updated_at"]) > instant(cutoff)):
                excluded += 1
                continue
            jobs = []
            progress("HISTORY",f"Reading jobs for historical run {row['id']}, attempt {row.get('run_attempt',1)}")
            for job_page in range(1, 11):
                batch = reader.get_json(f"/repos/{repo}/actions/runs/{row['id']}/attempts/{row.get('run_attempt', 1)}/jobs?per_page=100&page={job_page}").get("jobs")
                if not isinstance(batch, list):
                    raise ValueError("Invalid historical jobs response")
                for job in batch:
                    start, end = job.get("started_at"), job.get("completed_at")
                    if not start or not end or instant(end) > instant(cutoff):
                        continue
                    jobs.append({"id": job["id"], "name": job.get("name"), "conclusion": job.get("conclusion"),
                                 "runner_labels": job.get("labels", []), "started_at": start, "completed_at": end,
                                 "duration_seconds": max(0, (instant(end) - instant(start)).total_seconds())})
                if len(batch) < 100:
                    break
            else:
                raise ValueError("Historical job list exceeded evidence budget")
            runs.append({"run_id": row["id"], "run_attempt": row.get("run_attempt", 1),
                         "conclusion": row.get("conclusion"), "created_at": row["created_at"],
                         "completed_at": row["updated_at"], "jobs": jobs})
            progress("HISTORY",f"[{len(runs)}/{limit}] run={row['id']}; conclusion={row.get('conclusion')}; jobs={len(jobs)}")
            if len(runs) >= limit:
                break
        if len(runs) >= limit or len(rows) < 100:
            break
    result = {"identity": identity, "status": "historical_context_only", "cutoff_utc": cutoff,
              "runs": runs, "future_or_incomplete_excluded": excluded,
              "coverage": "bounded pre-commit observed history; not a measured baseline"}
    if SECRET.search(json.dumps(result)):
        raise ValueError("History contains possible sensitive text; refusing model context")
    write_json_immutable(archive, result)
    return result


def attach_evidence(context: dict, *, history: dict | None = None, bundle: Path | None = None) -> dict:
    context = {**context}
    if history is not None:
        if history["identity"]["source_commit_sha"] != context["source_commit_sha"]:
            raise ValueError("Historical evidence belongs to another source commit")
        context["ci_history"] = history
    if bundle is not None:
        data = json.loads(bundle.read_text(encoding="utf-8"))
        if data.get("source_commit_sha") != context["source_commit_sha"]:
            raise ValueError("Supplementary evidence source differs from snapshot")
        facts = data.get("facts")
        if not isinstance(facts, dict):
            raise ValueError("Supplementary evidence requires named facts")
        for name, fact in facts.items():
            if not isinstance(name, str) or not isinstance(fact, dict):
                raise ValueError("Invalid evidence fact")
            if fact.get("status") not in {"VERIFIED", "UNVERIFIED"}:
                raise ValueError("Evidence status must be explicit")
            references = fact.get("artifacts", [])
            if fact["status"] == "VERIFIED" and (not references or not fact.get("verified_by")):
                raise ValueError("Verified facts require an identified verifier and hashed artifacts")
            for artifact in references:
                raw = read_source(bundle.parent, artifact["path"])
                if digest(raw) != artifact.get("sha256"):
                    raise ValueError("Supplementary evidence artifact changed")
                if SECRET.search(raw.decode("utf-8-sig", errors="replace")):
                    raise ValueError("Supplementary evidence contains possible credentials")
        if SECRET.search(json.dumps(data)):
            raise ValueError("Supplementary evidence contains possible credentials")
        context["mechanism_evidence"] = data
        context["mechanism_evidence_sha256"] = digest(data)
    return context


def evidence_requests(assessments: list[dict], context: dict, registry: dict) -> dict:
    """An actionable queue of missing facts, not a silent permanent abstention."""
    requests=[]
    for row in assessments:
        if row["status"]=="MISSING_EVIDENCE":
            pattern=registry["catalogue"][row["pattern_id"]]
            requests.append({"pattern_id":row["pattern_id"],"missing":row["missing_evidence"],
                "required_fact_keys":pattern["required_evidence"],"source_commit_sha":context["source_commit_sha"],
                "status":"AWAITING_SOURCE_BOUND_EVIDENCE"})
    return {"source_commit_sha":context["source_commit_sha"],"context_sha256":digest(context),
            "requests":requests,"retry_contract":"Supply verified facts in evidence.json and start a preserved retry generation; never rewrite an archived request."}
