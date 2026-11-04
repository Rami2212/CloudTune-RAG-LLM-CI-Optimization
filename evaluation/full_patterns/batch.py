"""Member-local full-pattern batch orchestration, isolated from legacy ledgers."""
from __future__ import annotations

import argparse
import csv
import json
import os
import math
from pathlib import Path
import re

from scripts.experiment_environment import load_env
from evaluation.prepare_evaluation_assignments import split_dataset
from evaluation.repository_preparation import (GitHubReader, PreparationError, prepare_repository,
    excluded_repo_ids, read_evaluation_rows, write_json_immutable)
from . import PROTOCOL
from .analysis import summarize
from .context import collect_context
from .evidence import collect_history
from .pipeline import run_proposals, implementation_sha256, exclusive_output
from .registry import ROOT, DATASET, load_registry, digest
from .scenarios import development_pilot, validate_policy, reference_policy
from .progress import progress

DEFAULT_CONFIG = ROOT / "evaluation/configs/full_patterns.json"
RESULTS = ROOT / "evaluation/full-pattern-results"


def latest_studies(root):
    latest={}
    for path in sorted(root.glob("trials/*/study_report.json")):
        study=json.loads(path.read_text(encoding="utf-8"))
        position=study["position"]
        generation=int(path.parent.name.rsplit("-g",1)[1])
        if position not in latest or generation>latest[position][0]:
            latest[position]=(generation,study)
    return [value[1] for _,value in sorted(latest.items())]


def bounds(start_at=1, stop_at=None, limit=None):
    if type(start_at) is not int or not 1 <= start_at <= 1000:
        raise ValueError("--start-at must be within this member's 1..1000 rows")
    if stop_at is not None and limit is not None:
        raise ValueError("Use --stop-at or --limit, not both")
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("--limit must be positive")
    end = stop_at if stop_at is not None else start_at + limit - 1 if limit is not None else 1000
    if type(end) is not int or not start_at <= end <= 1000:
        raise ValueError("Member-local range must remain within 1..1000")
    return start_at, end


def verify_development(registry, output):
    pilot = development_pilot(registry)
    checks = {}
    for pattern in pilot["patterns"]:
        pid = pattern["pattern_id"]
        expected = pid != "P-LIT-BUILD-SELECT"  # seeded unseen setup failure
        checks[pid] = pattern["arms"]["A"]["contract_pass"] and pattern["arms"]["REFERENCE"]["contract_pass"] == expected
        bad = {**reference_policy(pid), "not_an_audited_setting": True}
        try:
            validate_policy(pid, bad)
        except ValueError:
            pass
        else:
            checks[pid] = False
    result = {"protocol": PROTOCOL, "implementation_sha256": implementation_sha256(),
        "registry_sha256": registry["registry_sha256"], "checks": checks,
        "passed": len(checks) == 25 and all(checks.values()), "pilot": pilot,
        "scope": "offline_development_integration; no live provider or hosted validation"}
    write_json_immutable(output.parent/"verification"/(result["implementation_sha256"]+".json"), result)
    output.parent.mkdir(parents=True,exist_ok=True)
    temp=output.with_suffix(".tmp");temp.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8");temp.replace(output)
    return result


def require_development(path, registry):
    saved = json.loads(path.read_text(encoding="utf-8"))
    if (saved.get("passed") is not True or saved.get("implementation_sha256") != implementation_sha256()
            or saved.get("registry_sha256") != registry["registry_sha256"]):
        raise ValueError("Development verification is missing, stale or failed; run full_patterns verify for this code version")


def load_study_config(path):
    config = json.loads(path.read_text(encoding="utf-8"))
    if config.get("protocol") != PROTOCOL:
        raise ValueError("Full-pattern config protocol differs")
    model = os.environ.get("OPENROUTER_MODEL") if config.get("generator_model") == "ENV" else config.get("generator_model")
    if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9_./:-]+:free", model):
        raise ValueError("Configure one pinned free generator model before starting")
    config["generator_model"] = model
    for key, lower, upper in (("repetitions",1,20), ("top_k",1,20), ("max_tokens",1,100000), ("context_chars",1000,200000)):
        if type(config.get(key)) is not int or not lower <= config[key] <= upper:
            raise ValueError("Invalid full-pattern configuration: " + key)
    revision=config.get("embedding_revision")
    if revision!="AUTO_PIN_SINGLE" and (not isinstance(revision,str) or not re.fullmatch(r"[a-f0-9]{40}",revision)):
        raise ValueError("Embedding revision must be AUTO_PIN_SINGLE or a pinned SHA")
    budget=config.get("max_evidence_rounds",3)
    benefit=config.get("minimum_benefit_percent",5)
    if type(budget) is not int or not 1<=budget<=10:
        raise ValueError("max_evidence_rounds must be 1..10")
    if type(benefit) not in {int,float} or not math.isfinite(benefit) or not 0<=benefit<=100:
        raise ValueError("minimum_benefit_percent must be a finite percentage")
    return config


def run_member(args, *, registry, reader=None, proposer=run_proposals, comparator_generator=None,
               device_checker=None, executor=None):
    partition = split_dataset(root=ROOT)["assignments"][args.member - 1]
    rows = read_evaluation_rows(ROOT / partition["file"])
    begin, end = bounds(args.start_at, args.stop_at, args.limit)
    if args.list:
        return {"rows": [{"position": i, "global_position": (args.member-1)*1000+i,
                          "repo_id": rows[i-1]["repo_id"]} for i in range(begin,end+1)]}
    load_env(ROOT / ".env")
    progress("BATCH",f"Member {args.member}; batch={args.batch_id}; local rows {begin}..{end}; mode={'preflight' if args.preflight_only else 'publish' if args.publish_only else 'run'}")
    config = load_study_config(args.config)
    require_development(args.verification, registry)
    progress("VERIFY","Development verification matches the current implementation and corpus")
    root = RESULTS / args.batch_id
    if args.publish_only:
        studies = latest_studies(root)
        return summarize(studies, minimum_benefit=config.get("minimum_benefit_percent",5))
    if device_checker is None:
        from .device import inspect_device
        device_checker = inspect_device
    progress("DEVICE","Checking configured embedding device (CPU default; CUDA only when explicitly configured)")
    runtime = device_checker()
    progress("DEVICE",f"requested={runtime.get('requested_device','cpu')}; actual={runtime.get('actual_device')}; GPU={runtime.get('gpu_name','not selected')}")
    identity = {"protocol": PROTOCOL, "member": args.member, "batch_id": args.batch_id,
                "partition_sha256": partition["sha256"], "config": config,
                "registry_sha256": registry["registry_sha256"], "implementation_sha256": implementation_sha256(),
                "runtime": runtime}
    # The range is an invocation filter, not a new partition or protocol identity.
    reader = reader or GitHubReader()
    with exclusive_output(root):
        write_json_immutable(root / "identity.json", identity)
        plan_path = root / "generations.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8")) if plan_path.exists() else {"round":0,"generations":{},"positions":None,"active":False}
        if args.rerun and plan.get("active") is not True:
            failed = []
            for i in range(begin,end+1):
                generation=plan["generations"].get(str(i),1)
                previous = root / "trials" / f"r{i:04d}-g{generation:02d}" / "state.json"
                if previous.exists():
                    state = json.loads(previous.read_text(encoding="utf-8"))
                    if state.get("pending_hosted"):
                        raise ValueError("Cannot allocate a retry with pending hosted CI")
                    if state.get("status") in {"BLOCKED", "FAILED", "INELIGIBLE"}:
                        if generation>=config.get("max_evidence_rounds",3):
                            raise ValueError("Frozen evidence-round budget exhausted; preserve this study and predeclare a new budget/study")
                        failed.append(i)
            if not failed:
                raise ValueError("No finished failed/blocked trials in this range; resume paused or unstarted work without --rerun")
            generations=dict(plan["generations"])
            for i in failed:generations[str(i)]=generations.get(str(i),1)+1
            plan = {"round":plan["round"]+1,"generations":generations,"positions":failed,"active":True}
            plan_path.write_text(json.dumps(plan,indent=2)+"\n",encoding="utf-8")
        if plan.get("active") and not args.rerun:
            raise ValueError("An active retry round requires the same --rerun command")
        studies, processed, blocked = [], 0, False
        for index in range(begin,end+1):
            if args.rerun and plan.get("positions") is not None and index not in plan["positions"]:
                continue
            generation=plan["generations"].get(str(index),1)
            trial = root / "trials" / f"r{index:04d}-g{generation:02d}"
            state_path = trial / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
            if state.get("status") == "COMPLETE":
                progress("RESUME",f"[{index}/1000] completed generation {generation}; skipping without regeneration or dispatch")
                if (trial / "study_report.json").exists():
                    studies.append(json.loads((trial/"study_report.json").read_text(encoding="utf-8")))
                continue
            if args.max_repositories and processed >= args.max_repositories:
                break
            processed += 1
            trial.mkdir(parents=True,exist_ok=True)
            def save():
                tmp=trial/"state.tmp";tmp.write_text(json.dumps(state,indent=2)+"\n",encoding="utf-8");tmp.replace(state_path)
            row=rows[index-1]
            progress("REPO",f"[{index}/1000] {row['repo_id']}: generation={generation}; saved_state={state.get('status','NOT_STARTED')}")
            exclusions=excluded_repo_ids(ROOT/"research-data/zenodo_20340547/pattern_repo_candidates_20.csv",
                (ROOT/"research-data/experiments",ROOT/"research-data/scenario-experiments"))
            try:
                progress("PREP",f"{row['repo_id']}: screening eligibility and restoring/freezing source snapshot")
                selected=prepare_repository(row,reader,trial/"snapshot",partition["sha256"],exclusions)
                snapshot=Path(selected["manifest_path"]).parent
                progress("PREP",f"{row['repo_id']}: {selected.get('status','prepared')}; commit={selected.get('source_commit_sha','pinned')}; workflow={selected.get('workflow_path','frozen')}; snapshot={snapshot}")
            except PreparationError as exc:
                progress("SCREENING",f"{row['repo_id']}: {exc.status}; {exc}")
                state.update(status="INELIGIBLE" if exc.status=="ineligible" else "BLOCKED",reason=str(exc));save();continue
            extended=trial/"extended"
            progress("CONTEXT",f"{row['repo_id']}: collecting or restoring bounded pinned source context")
            collect_context(snapshot,extended,reader=reader)
            progress("HISTORY",f"{row['repo_id']}: collecting or restoring pre-commit CI history")
            history=collect_history(snapshot,trial/"historical",reader=reader)
            progress("HISTORY",f"{row['repo_id']}: {history.get('status')}; {len(history.get('runs',[]))} historical runs; excluded={history.get('future_or_incomplete_excluded',0)}")
            evidence=args.evidence_root/f"r{index:04d}"/"evidence.json" if args.evidence_root else None
            if evidence and not evidence.exists():
                evidence=None
            rag_output=trial/"rag"
            from .retrieval import PatternRetriever
            class Lazy:
                identity={"dataset_sha256":registry["dataset_sha256"]}
                instance=None
                def retrieve(inner,pid,query,*,top_k):
                    if inner.instance is None:
                        inner.instance=PatternRetriever(dataset=DATASET,dataset_sha256=registry["dataset_sha256"],
                            revision=None if config["embedding_revision"]=="AUTO_PIN_SINGLE" else config["embedding_revision"])
                        inner.identity=inner.instance.identity
                    return inner.instance.retrieve(pid,query,top_k=top_k)
            try:
                progress("OPTIMIZER",f"{row['repo_id']}: LLM + RAG; model={config['generator_model']}; top_k={config['top_k']} per pattern")
                proposer(snapshot,rag_output,registry=registry,model=config["generator_model"],
                    top_k=config["top_k"],max_tokens=config["max_tokens"],context_chars=config["context_chars"],
                    extended=extended,history=history,evidence_bundle=evidence,retriever=Lazy(),
                    embedding_revision=config["embedding_revision"],runtime=runtime)
            except Exception as exc:
                from evaluation.openrouter_http import OpenRouterPaused
                state.update(status="PROVIDER_PAUSED" if isinstance(exc,OpenRouterPaused) else "FAILED",reason=type(exc).__name__)
                save();raise
            context=json.loads((rag_output/"context.json").read_text(encoding="utf-8"))
            from .comparator import generate_comparator
            if comparator_generator is None:
                progress("OPTIMIZER",f"{row['repo_id']}: verifying pinned CI-Cost installation and generating/restoring comparator")
                from evaluation.third_party.ci_cost.setup import install
                install()
                comparator=generate_comparator(snapshot,trial,context,registry)
            else:
                comparator=generate_comparator(snapshot,trial,context,registry,generator=comparator_generator)
            progress("OPTIMIZER",f"{row['repo_id']}: CI-Cost decision={comparator.get('generation',{}).get('decision','recorded')}")
            if args.preflight_only:
                from .admission import validate_output
                from .study import admit_comparator
                validate_output(rag_output,registry)
                admit_comparator(comparator,context,registry,rag_output)
                templates=trial/"scenario_templates"
                for pid,pattern in registry["catalogue"].items():
                    write_json_immutable(templates/f"{pid}.json",{"pattern_id":pid,
                        "source_commit_sha":context["source_commit_sha"],"context_sha256":digest(context),
                        "mode":"controlled_replay","baseline_policy":None,"inputs":None,
                        "verified_by":"","artifacts":[],"required_safety_tests":pattern["safety_tests"],
                        "note":"Populate with independent source-derived traces and the actual original policy; synthetic reference fixtures are not repository measurements."})
                state.update(status="PREFLIGHT_READY",snapshot=str(snapshot));save()
                progress("PREFLIGHT",f"{row['repo_id']}: preparation and proposal admission recorded; review/evidence/scenario templates={trial}; no CI dispatched")
                continue
            if executor is None:
                from .study import execute_study
                executor=execute_study
            from evaluation.ci_executor import GitHub
            token=os.environ.get("CLOUDTUNE_FORK_TOKEN") or os.environ.get("GITHUB_TOKEN")
            try:
                progress("EXECUTION",f"{row['repo_id']}: resolving source-bound scenarios and independently admitted arms")
                report=executor(snapshot,rag_output,registry=registry,comparator=comparator,
                    scenarios=args.scenario_root/f"r{index:04d}",
                    reviews=args.reviews/f"r{index:04d}" if args.reviews else None,
                    repetitions=config["repetitions"],github=GitHub(token) if token else None)
            except Exception:
                pending=any(json.loads(p.read_text()).get("pending") for p in rag_output.glob("measurements/*/hosted_state.json"))
                state.update(pending_hosted=pending,status="HOSTED_PENDING" if pending else "BLOCKED")
                save();raise
            report.update(repo_id=row["repo_id"],position=index,global_position=(args.member-1)*1000+index,
                          exposure="previously_exposed" if args.member==1 and index<=24 else "unexposed")
            temp=trial/"study_report.tmp";temp.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8");temp.replace(trial/"study_report.json")
            studies.append(report)
            has_blockers=any(p["status"] not in {"MEASURED_REPLAY","MEASURED_HOSTED","NO_CHANGE","NOT_APPLICABLE"} for p in report["patterns"])
            failed_outcomes=any(not arm.get("contract_pass",True) for p in report["patterns"] for arm in p.get("arms",{}).values())
            state.update(status="BLOCKED" if has_blockers else "FAILED" if failed_outcomes else "COMPLETE",pending_hosted=False);save()
            progress("REPO",f"{row['repo_id']}: {state['status']}; {len(report['patterns'])} pattern outcomes archived")
            blocked |= has_blockers
        if plan.get("active"):
            finished=all((root/"trials"/f"r{i:04d}-g{plan['generations'].get(str(i),1):02d}"/"state.json").exists() and
                json.loads((root/"trials"/f"r{i:04d}-g{plan['generations'].get(str(i),1):02d}"/"state.json").read_text()).get("status") in {"COMPLETE","BLOCKED","INELIGIBLE","FAILED"}
                for i in plan["positions"])
            if finished:
                plan["active"]=False;plan_path.write_text(json.dumps(plan,indent=2)+"\n",encoding="utf-8")
        analysis=summarize(latest_studies(root),minimum_benefit=config.get("minimum_benefit_percent",5))
        (root/"analysis.json").write_text(json.dumps(analysis,indent=2)+"\n",encoding="utf-8")
        progress("SUMMARY",f"Batch {args.batch_id}: attempted={processed}; analysis={root/'analysis.json'}")
        return {"batch_id":args.batch_id,"processed":processed,"status":"NEEDS_EVIDENCE_OR_REVIEW" if blocked else "PREFLIGHT_READY" if args.preflight_only else "COMPLETE",
                "analysis":analysis}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--member",type=int,required=True,choices=(1,2,3,4))
    parser.add_argument("--batch-id",help="Defaults to full-member-NN for the selected member")
    parser.add_argument("--config",type=Path,default=DEFAULT_CONFIG)
    parser.add_argument("--verification",type=Path,default=RESULTS/"development-verification.json")
    parser.add_argument("--start-at",type=int,default=1)
    group=parser.add_mutually_exclusive_group();group.add_argument("--stop-at",type=int);group.add_argument("--limit",type=int)
    parser.add_argument("--max-repositories",type=int)
    parser.add_argument("--scenario-root",type=Path,default=RESULTS/"scenario-inputs")
    parser.add_argument("--evidence-root",type=Path)
    parser.add_argument("--reviews",type=Path)
    parser.add_argument("--rerun",action="store_true")
    modes=parser.add_mutually_exclusive_group(required=True)
    for mode in ("list","preflight-only","run","publish-only"):
        modes.add_argument("--"+mode,action="store_true")
    args=parser.parse_args(argv)
    if args.batch_id is None:
        args.batch_id=f"full-member-{args.member:02d}"
    try:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}",args.batch_id):
            raise ValueError("Use a distinct full-pattern batch ID of 1..48 letters/digits/_/-")
        if (ROOT/"evaluation/results"/args.batch_id).exists():
            raise ValueError("Batch ID belongs to legacy results; choose a new full-pattern ID")
        if args.max_repositories is not None and args.max_repositories<1:
            raise ValueError("--max-repositories must be positive")
        result=run_member(args,registry=load_registry())
        print(json.dumps(result,indent=2))
        return 2 if result.get("status")=="NEEDS_EVIDENCE_OR_REVIEW" else 0
    except KeyboardInterrupt:
        print("Stopped. Resume the identical full-pattern command; pending GitHub dispatches remain checkpointed.")
        return 130
    except (OSError,ValueError,RuntimeError,KeyError,TypeError) as exc:
        print(f"Full-pattern batch stopped: {type(exc).__name__}: {exc}")
        return 1
