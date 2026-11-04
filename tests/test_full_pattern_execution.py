"""Connected development evaluation tests. No live repository set is executed."""
from __future__ import annotations

import copy
import contextlib
import io
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from tests import test_full_patterns as source_fixtures
from tests.test_full_patterns import assessments, proposal, WORKFLOW, MODEL
from evaluation.full_patterns import scenarios
from evaluation.full_patterns.registry import digest
from evaluation.full_patterns.pipeline import run_proposals
from evaluation.full_patterns.study import execute_study, scenario_spec
from evaluation.full_patterns.comparator import adapt_candidate
from evaluation.full_patterns.admission import review_template
from evaluation.full_patterns.analysis import summarize
from evaluation.full_patterns.batch import verify_development, require_development, bounds
from evaluation.full_patterns.device import inspect_device
from evaluation.full_patterns.evidence import collect_history


class ExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from evaluation.full_patterns.registry import load_registry
        cls.registry=load_registry()

    def setUp(self):
        source_fixtures.FullPatternTests.setUp(self)
    def test_all_scenarios_execute_and_choose_mechanism_outcomes(self):
        pilot = scenarios.development_pilot(self.registry)
        self.assertEqual(pilot["pattern_count"],25)
        by_id={p["pattern_id"]:p for p in pilot["patterns"]}
        for pid,result in by_id.items():
            self.assertTrue(result["arms"]["A"]["contract_pass"])
            self.assertEqual(len(result["records"]),6)
            self.assertEqual(result["ci_dispatches"],0)
            self.assertFalse(result["hosted_ci_speedup_claim"])
        self.assertFalse(by_id["P-LIT-BUILD-SELECT"]["arms"]["REFERENCE"]["contract_pass"])
        self.assertEqual(by_id["P-LIT-BUILD-SELECT"]["arms"]["REFERENCE"]["realized_reduction_percent"],0)
        for pid,metric in (("P-LIT-PRIORITIZE","failure_feedback_seconds"),
                           ("P-LIT-BAZEL-PARALLEL","simulated_elapsed_seconds"),
                           ("P-LIT-BUILD-PRIORITY","urgent_wait_seconds"),
                           ("P-LIT-DURATION-PREDICTION","prediction_mae_seconds")):
            self.assertEqual(by_id[pid]["arms"]["REFERENCE"]["metric"],metric)
            self.assertGreater(by_id[pid]["arms"]["REFERENCE"]["observed_reduction_percent"],0)

    def test_negative_controls_expose_coverage_and_state_loss(self):
        for pid in ("P-LIT-CUSTOM-TIMEOUT","P-LIT-HISTORY-TIMEOUT"):
            policy=scenarios.reference_policy(pid,True);policy["timeout_seconds"]=5
            result=scenarios.execute(pid,policy,scenarios.fixture(pid))
            self.assertFalse(result["contract_pass"])
            self.assertEqual(result["result"]["false_timeouts"],3)
        pid="P-LIT-FAIL-FAST";data=scenarios.fixture(pid);data["required_all_diagnostics"]=True
        self.assertFalse(scenarios.execute(pid,scenarios.reference_policy(pid,True),data)["contract_pass"])
        pid="P-LIT-CONFIG-REUSE";policy=scenarios.reference_policy(pid,True);policy["invalidate_inputs"]=False
        self.assertFalse(scenarios.execute(pid,policy,scenarios.fixture(pid))["contract_pass"])
        pid="P-LIT-DISTRIBUTED-CACHE";policy=scenarios.reference_policy(pid,True);policy["isolate_project"]=False
        self.assertFalse(scenarios.execute(pid,policy,scenarios.fixture(pid))["contract_pass"])
        pid="P-LIT-ENV-CACHE";policy=scenarios.reference_policy(pid,True);policy["reset_files"]=False
        result=scenarios.execute(pid,policy,scenarios.fixture(pid))
        self.assertFalse(result["contract_pass"])
        self.assertGreater(result["result"]["contamination_count"],0)
        pid="P-LIT-CONFIG-REUSE"
        result=scenarios.execute(pid,scenarios.reference_policy(pid,True),scenarios.fixture(pid))
        trace=result["result"]["trace"]
        self.assertTrue(trace[4]["intermediate_reused"])
        self.assertFalse(trace[6]["intermediate_reused"])
        self.assertNotEqual(trace[3]["output"],trace[4]["output"])

    def test_no_implicit_reference_treatment_for_model_or_tool(self):
        for pid in self.registry["catalogue"]:
            with self.subTest(pid=pid),self.assertRaises((ValueError,TypeError)):
                scenarios.candidate_policy(pid,{"policy":None,"files":[],"analysis":None},self.context)
        pid="P-LIT-CANCEL-STALE"
        exact=WORKFLOW.replace("jobs:","concurrency:\n  group: ${{ github.workflow }}-${{ github.ref }}\n  cancel-in-progress: true\njobs:")
        chosen=scenarios.candidate_policy(pid,{"files":[{"path":self.context["workflow_path"],"content":exact}]},self.context)
        self.assertEqual(chosen,scenarios.reference_policy(pid,True))

    def test_broad_pattern_support_cannot_escalate_permissions_or_hide_failures(self):
        from evaluation.full_patterns.admission import validate_treatment
        from evaluation.full_patterns.proposals import validate_proposal
        pattern=self.registry["catalogue"]["P-LIT-SMELL-REPAIR"]
        for candidate in (WORKFLOW+"permissions:\n  contents: write\n",
                          WORKFLOW.replace("    runs-on:","    continue-on-error: true\n    runs-on:"),
                          WORKFLOW.replace("on: [push, workflow_dispatch]","on: [push, workflow_dispatch, pull_request_target]")):
            raw=proposal(pattern,self.context);raw["policy"]=None
            raw["files"]=[{"path":self.context["workflow_path"],"before_sha256":self.context["workflow_sha256"],"content":candidate}]
            checked=validate_proposal(raw,pattern,self.context,self.evidence_for(pattern))
            result=validate_treatment(checked,self.context,self.registry,self.evidence_for(pattern))
            self.assertEqual(result["verdict"],"INVALID")

    def test_verified_supplementary_artifact_is_citable_but_not_editable(self):
        from evaluation.full_patterns.evidence import attach_evidence
        from evaluation.full_patterns.proposals import validate_proposal
        artifact=self.root/"contract.txt";artifact.write_text("Independent matrix cancellation contract")
        bundle=self.root/"evidence.json"
        bundle.write_text(json.dumps({"source_commit_sha":"a"*40,"facts":{"matrix_contract":{
            "status":"VERIFIED","verified_by":"fixture","artifacts":[{"path":"contract.txt","sha256":digest(artifact.read_bytes())}]}}}))
        context=attach_evidence(self.context,bundle=bundle)
        pattern=self.registry["catalogue"]["P-LIT-FAIL-FAST"]
        raw=proposal(pattern,context)
        raw["preconditions"][0]["evidence_paths"]=["contract.txt"]
        self.assertEqual(validate_proposal(raw,pattern,context,self.evidence_for(pattern))["decision"],"APPLY")
        raw["files"]=[{"path":"contract.txt","before_sha256":digest(artifact.read_bytes()),"content":"Override the contract"}]
        with self.assertRaisesRegex(ValueError,"frozen inputs"):
            validate_proposal(raw,pattern,context,self.evidence_for(pattern))

    def evidence_for(self,pattern):
        return [{"pattern_id":pattern["pattern_id"],"document_id":pattern["document_id"]}]

    def test_comparator_keeps_full_patch_and_no_rag_citations(self):
        candidate=WORKFLOW.replace("jobs:","concurrency:\n  group: ${{ github.workflow }}-${{ github.ref }}\n  cancel-in-progress: true\njobs:")
        result=adapt_candidate({"decision":"APPLY"},WORKFLOW,candidate,self.context,self.registry)
        entry=result["P-LIT-CANCEL-STALE"]
        self.assertEqual(entry["proposal"]["files"][0]["content"],candidate)
        self.assertEqual(entry["proposal"]["evidence_ids"],[])
        self.assertTrue(all(c["status"]=="MISSING" for c in entry["proposal"]["preconditions"]))
        self.assertEqual(result["P-LIT-SELECT"]["decision"],"NO_CHANGE")

    def _connected_output(self):
        pid="P-LIT-CANCEL-STALE";pattern=self.registry["catalogue"][pid]
        raw=proposal(pattern,self.context)
        raw["policy"]={"adapter":"controlled_replay","version":scenarios.VERSION,
                       "settings":scenarios.reference_policy(pid,True)}
        assessment=assessments(self.registry,self.context,[pid])
        for row in assessment["assessments"]:
            if row["pattern_id"]!=pid:
                row.update(status="NOT_APPLICABLE",missing_evidence=[])
        calls=[]
        def transport(req):
            calls.append(req)
            value=assessment if len(calls)==1 else raw
            return {"choices":[{"finish_reason":"stop","message":{"content":json.dumps(value)}}]}
        class Retriever:
            identity={"dataset_sha256":self.registry["dataset_sha256"],"embedding_revision":"c"*40}
            def retrieve(inner,*args,**kwargs):return []
        output=self.root/"connected"
        with patch.dict("os.environ",{"OPENROUTER_API_KEY":"fixture"}):
            run_proposals(self.snapshot,output,registry=self.registry,model=MODEL,retriever=Retriever(),transport=transport)
        return pid,output

    def _approved_scenario(self,pid,output):
        context=json.loads((output/"context.json").read_text())
        proposed=json.loads((output/"patterns"/pid/"proposal.json").read_text())
        root=self.root/"reviews";folder=root/"C";folder.mkdir(parents=True)
        facts=b'{"development_proof":true}'
        (folder/"proof.json").write_bytes(facts)
        review=review_template(proposed,context,self.registry)
        review.update(verdict="APPROVE",reviewer="Independent fixture",reviewed_at="2026-11-04T00:00:00Z")
        for check in review["checks"]:
            check.update(status="VERIFIED",rationale="Development-only evidence fixture",
                         evidence=[{"path":"proof.json","sha256":digest(facts)}])
        (folder/f"{pid}.json").write_text(json.dumps(review))
        scenarios_root=self.root/"scenarios";scenarios_root.mkdir()
        (scenarios_root/"trace.json").write_bytes(facts)
        spec={"pattern_id":pid,"source_commit_sha":context["source_commit_sha"],"context_sha256":digest(context),
              "mode":"controlled_replay","verified_by":"Independent fixture",
              "artifacts":[{"path":"trace.json","sha256":digest(facts)}],
              "baseline_policy":scenarios.reference_policy(pid),"inputs":[scenarios.fixture(pid,i) for i in (1,2,3)]}
        (scenarios_root/f"{pid}.json").write_text(json.dumps(spec))
        return root,scenarios_root

    def test_connected_generation_review_execution_analysis_and_resume(self):
        pid,output=self._connected_output()
        reviews,specs=self._approved_scenario(pid,output)
        context=json.loads((output/"context.json").read_text())
        comparator={"identity":{"context_sha256":digest(context)},
            "patterns":adapt_candidate({"decision":"NO_CHANGE"},WORKFLOW,None,context,self.registry)}
        report=execute_study(self.snapshot,output,registry=self.registry,comparator=comparator,scenarios=specs,reviews=reviews)
        row=next(p for p in report["patterns"] if p["pattern_id"]==pid)
        self.assertEqual(row["status"],"MEASURED_REPLAY")
        self.assertEqual(set(row["arms"]),{"A","B","C"})
        self.assertGreater(row["arms"]["C"]["realized_reduction_percent"],0)
        self.assertEqual(row["arms"]["B"]["realized_reduction_percent"],0)
        self.assertEqual(len(row["records"]),9)
        self.assertEqual(execute_study(self.snapshot,output,registry=self.registry,comparator=comparator,scenarios=specs,reviews=reviews),report)
        report.update(repo_id="development/fixture",exposure="unexposed")
        summary=summarize([report])
        paired=next(x for x in summary["comparisons"] if x["comparison"]=="C_vs_A")
        self.assertEqual(paired["paired_valid_units"],1)
        self.assertEqual(paired["evidence_scope"],"controlled_replay")

    def test_rejected_arm_does_not_block_admitted_comparator_or_baseline(self):
        pid,output=self._connected_output()
        reviews,specs=self._approved_scenario(pid,output)
        review=json.loads((reviews/"C"/f"{pid}.json").read_text());review["verdict"]="REJECT"
        (reviews/"C"/f"{pid}.json").write_text(json.dumps(review))
        context=json.loads((output/"context.json").read_text())
        comparator={"identity":{"context_sha256":digest(context)},
            "patterns":adapt_candidate({"decision":"NO_CHANGE"},WORKFLOW,None,context,self.registry)}
        report=execute_study(self.snapshot,output,registry=self.registry,comparator=comparator,scenarios=specs,reviews=reviews)
        row=next(p for p in report["patterns"] if p["pattern_id"]==pid)
        self.assertEqual(set(row["arms"]),{"A","B"})
        self.assertEqual(row["admission"]["C"]["verdict"],"REJECTED")
        report.update(repo_id="development/fixture")
        effect=next(p for p in summarize([report])["comparisons"] if p["comparison"]=="C_vs_A")
        self.assertEqual(effect["safe_benefit_rate_among_baseline_valid"],0)

    def test_history_excludes_post_cutoff_runs(self):
        self.manifest["source_default_branch"]="main"
        (self.snapshot/"manifest.json").write_text(json.dumps(self.manifest))
        class Reader:
            def get_json(inner,path):
                if "/commits/" in path:
                    return {"sha":"a"*40,"commit":{"committer":{"date":"2026-01-10T00:00:00Z"}}}
                if "/jobs?" in path:
                    return {"jobs":[{"id":1,"name":"tests","conclusion":"success",
                        "started_at":"2026-01-01T00:00:00Z","completed_at":"2026-01-01T00:00:10Z"}]}
                return {"workflow_runs":[{"id":1,"created_at":"2026-01-01T00:00:00Z","updated_at":"2026-01-01T00:00:10Z"},
                    {"id":2,"created_at":"2026-01-01T00:00:00Z","updated_at":"2026-02-01T00:00:00Z"}]}
        result=collect_history(self.snapshot,self.root/"history",reader=Reader())
        self.assertEqual(len(result["runs"]),1)
        self.assertEqual(result["future_or_incomplete_excluded"],1)

    def test_unavailable_cuda_is_a_startup_failure(self):
        torch=SimpleNamespace(__version__="fixture",version=SimpleNamespace(cuda="12.8"),
                              cuda=SimpleNamespace(is_available=lambda:False,device_count=lambda:0))
        with self.assertRaisesRegex(RuntimeError,"no CPU fallback"):
            inspect_device(torch_module=torch,requested="cuda")
        self.assertEqual(inspect_device(torch_module=torch,requested="cpu")["actual_device"],"cpu")

    def test_verification_is_bound_to_code_and_member_positions(self):
        artifact=self.root/"verification.json"
        result=verify_development(self.registry,artifact)
        self.assertTrue(result["passed"])
        require_development(artifact,self.registry)
        with patch("evaluation.full_patterns.batch.implementation_sha256",return_value="changed"):
            with self.assertRaisesRegex(ValueError,"stale"):
                require_development(artifact,self.registry)
        self.assertEqual(bounds(100,limit=20),(100,119))
        for args in ((0,None,None),(999,None,3),(1,2,2)):
            with self.assertRaises(ValueError):bounds(*args)

    def test_normal_entry_point_preserves_member_local_range(self):
        from scripts import run_evaluation_batch
        stream = io.StringIO()
        rows = [{"repo_id": f"development/fixture-{i}"} for i in range(1, 1001)]
        with patch("sys.argv",["runner","--member","2","--list","--start-at","100","--limit","1"]),\
             patch.object(run_evaluation_batch,"_assignment",return_value=rows),\
             patch("evaluation.full_patterns.batch.main") as entry, contextlib.redirect_stdout(stream):
            self.assertEqual(run_evaluation_batch.main(),0)
        entry.assert_not_called()
        self.assertEqual(stream.getvalue().strip(), "0100 (global 1100): development/fixture-100")

    def test_normal_run_preserves_original_batch_and_controller(self):
        from scripts import run_evaluation_batch
        with patch("sys.argv",["runner","--member","1","--run","--limit","20"]),\
             patch.object(run_evaluation_batch,"_assignment",return_value=[{"repo_id":"development/fixture"}]),\
             patch.object(run_evaluation_batch,"exclusive_batch",return_value=contextlib.nullcontext()),\
             patch.object(run_evaluation_batch,"run_batch",return_value=0) as run,\
             patch("evaluation.full_patterns.batch.main") as current:
            self.assertEqual(run_evaluation_batch.main(),0)
        current.assert_not_called()
        run.assert_called_once_with(1,"eval-member-01",preflight_only=False,
            max_repositories=None,retry_failed_from=None,rerun_failed=False,
            start_at=1,stop_at=None,limit=20)

    def test_detailed_progress_is_flushed_timestamped_and_redacts_credentials(self):
        from evaluation.full_patterns.progress import progress
        stream=io.StringIO()
        with patch.dict("os.environ",{"OPENROUTER_API_KEY":"fixture-model-secret","SUPABASE_SECRET_KEY":"fixture-index-secret"}),\
             contextlib.redirect_stdout(stream):
            progress("VALIDATION","verdict=PASS fixture-model-secret fixture-index-secret\nhttps://user:password@example.com")
        logged=stream.getvalue()
        self.assertRegex(logged,r"\[\d\d:\d\d:\d\d UTC\] \[VALIDATION\]")
        self.assertIn("verdict=PASS",logged)
        self.assertNotIn("fixture-model-secret",logged)
        self.assertNotIn("fixture-index-secret",logged)
        self.assertNotIn("user:password",logged)

    def test_normal_logging_hides_noise_but_keeps_decisions_errors_and_ci(self):
        from evaluation.full_patterns.progress import progress
        stream=io.StringIO()
        with patch.dict("os.environ",{"CLOUDTUNE_LOG_LEVEL":"info"}),contextlib.redirect_stdout(stream):
            progress("CONTEXT","[1/100] archived Cargo.toml; bytes=9740")
            progress("HISTORY","Reading jobs for historical run 123, attempt 1")
            progress("HISTORY","[1/20] run=123; conclusion=success; jobs=1")
            progress("PATTERN","P-LIT-CACHE: NOT_APPLICABLE; no relevant dependency step")
            progress("VALIDATION","P-LIT-CACHE: arm=C; verdict=NO_CHANGE; no generated treatment")
            progress("CONTEXT","Collection complete: files=41; omitted=15; bytes=262073")
            progress("LLM","applicability: request paused; OpenRouterPaused")
            progress("VALIDATION","P-LIT-FAIL-FAST: arm=C; verdict=REVIEW_REQUIRED; reasons=contract")
            progress("CI","Run 123 completed with conclusion=success")
        logged=stream.getvalue()
        self.assertNotIn("Cargo.toml",logged)
        self.assertNotIn("historical run",logged)
        self.assertNotIn("NOT_APPLICABLE",logged)
        self.assertNotIn("verdict=NO_CHANGE",logged)
        self.assertIn("files=41; omitted=15",logged)
        self.assertIn("OpenRouterPaused",logged)
        self.assertIn("REVIEW_REQUIRED",logged)
        self.assertIn("Run 123 completed",logged)
        with patch.dict("os.environ",{"CLOUDTUNE_LOG_LEVEL":"debug"}),contextlib.redirect_stdout(stream):
            progress("CONTEXT","[1/100] archived Cargo.toml; bytes=9740")
        self.assertIn("Cargo.toml",stream.getvalue())

    def test_hosted_multifile_tree_preserves_modes_and_exact_approved_bytes(self):
        from evaluation.full_patterns.hosted import TreatmentFork
        from evaluation.repository_preparation import git_blob_sha1
        old=b"pytest -q\n";new=b"pytest tests/test_a.py tests/test_b.py\n"
        github=MagicMock()
        listing={"tree":[{"type":"blob","path":".github/workflows/test.yml","mode":"100644","sha":git_blob_sha1(WORKFLOW.encode())},
                         {"type":"blob","path":"scripts/test.sh","mode":"100755","sha":git_blob_sha1(old)},
                         {"type":"blob","path":"src/app.py","mode":"100644","sha":"unchanged"}]}
        runner=TreatmentFork(github,repo_id="development/fixture",workflow_path=".github/workflows/test.yml",
            source_sha="a"*40,original=WORKFLOW.encode(),evaluation_id="new",max_wait_seconds=1,poll_seconds=1)
        runner.extra={"scripts/test.sh":{"before":old,"after":new}}
        github.request.side_effect=[listing,{"sha":"workflow-blob"},{"sha":"script-blob"},{"sha":"candidate-tree"}]
        self.assertEqual(runner._new_tree("owner/fork","base",WORKFLOW.encode()),"candidate-tree")
        payload=github.request.call_args.args[2]
        self.assertEqual(next(r for r in payload["tree"] if r["path"]=="scripts/test.sh")["mode"],"100755")
        changed=copy.deepcopy(listing)
        next(r for r in changed["tree"] if r["path"]=="scripts/test.sh")["sha"]=git_blob_sha1(new)
        github.request.side_effect=[listing,changed];github.blob.return_value=WORKFLOW.encode()
        runner._verify_arm_tree("owner/fork","base",{"tree":"candidate-tree","workflow_sha256":digest(WORKFLOW.encode())})
        changed["tree"][-1]["sha"]="unexpected"
        github.request.side_effect=[listing,changed]
        with self.assertRaisesRegex(ValueError,"unapproved source"):
            runner._verify_arm_tree("owner/fork","base",{"tree":"candidate-tree","workflow_sha256":digest(WORKFLOW.encode())})

    def test_named_fork_requires_creation_proof_and_never_adopts_legacy_fork(self):
        from evaluation.full_patterns.hosted import TreatmentFork
        from evaluation.ci_executor import GitHubError
        calls=[];created={}
        def request(method,path,body=None):
            calls.append((method,path,body))
            if path=="/user":return {"login":"owner"}
            if method=="POST":
                created.update(id=123,full_name="owner/"+body["name"],owner={"login":"owner"},
                    fork=True,parent={"full_name":"development/fixture"},permissions={"push":True,"admin":True})
                return created
            if not created:raise GitHubError(404,path)
            return created
        runner=TreatmentFork(SimpleNamespace(request=request),repo_id="development/fixture",workflow_path=".github/workflows/test.yml",
            source_sha="a"*40,original=WORKFLOW.encode(),evaluation_id="new-study-13",max_wait_seconds=1,poll_seconds=1)
        state={};runner.provision(state,lambda:None)
        self.assertTrue(state["fork_repo"].startswith("owner/ct-fixture-"))
        self.assertNotEqual(state["fork_repo"],"owner/fixture")
        runner.provision(state,lambda:None)
        self.assertEqual(sum(m=="POST" for m,_,_ in calls),1)
        with self.assertRaisesRegex(ValueError,"without this state's"):
            runner.provision({},lambda:None)

    def test_hosted_pending_dispatch_resumes_once_and_cancelled_run_is_not_comparable(self):
        from evaluation.full_patterns.hosted import run_hosted
        from evaluation.ci_executor import RunPending
        queued=[True];dispatches=[]
        class Experiment:
            def __init__(inner,*args,**kwargs):pass
            def provision(inner,state,save):state["fork_repo"]="owner/fixture";save()
            def prepare(inner,state,save):pass
            def make_treatment_arm(inner,state,arm,*args):state["arms"][arm]={}
            def execute(inner,state,save,*,arm,repeat,**kwargs):
                if not state.get("pending"):
                    dispatches.append((arm,repeat));state["pending"]={"arm":arm,"repeat":repeat};save()
                if (arm,repeat)==("B",1) and queued[0]:
                    queued[0]=False;raise RunPending("runner queued")
                row={"arm":arm,"repeat":repeat,"comparable":(arm,repeat)!=("B",2),
                     "conclusion":"cancelled" if (arm,repeat)==("B",2) else "success"}
                state["records"].append(row);state["pending"]=None;save();return row
        output=self.root/"hosted"
        params=dict(study_id="newstudy",context=self.context,treatments={"B":{"files":[]},"C":{"files":[]}},
                    repetitions=3,github=object(),required_jobs=["test"],admitted=["B","C"])
        with patch("evaluation.full_patterns.hosted.TreatmentFork",Experiment):
            with self.assertRaises(RunPending):run_hosted(self.snapshot,output,**params)
            state=json.loads((output/"hosted_state.json").read_text())
            self.assertEqual(state["pending"]["arm"],"B")
            report=run_hosted(self.snapshot,output,**params)
        self.assertEqual(len(dispatches),9)
        self.assertEqual(len(set(dispatches)),9)
        self.assertEqual(len(report["records"]),9)
        self.assertEqual(report["cleanup_status"],"RETAINED_BY_CONFIGURATION")
        self.assertFalse(next(r for r in report["records"] if (r["arm"],r["repeat"])==("B",2))["comparable"])

    def test_cold_cache_control_cannot_touch_unowned_replaced_or_active_fork(self):
        from evaluation.full_patterns.hosted import clear_owned_caches
        from evaluation.ci_executor import RunPending
        github=MagicMock()
        info={"id":123,"owner":{"login":"owner"},"fork":True,"permissions":{"push":True},
              "parent":{"full_name":"development/fixture"}}
        state={"fork_repo":"owner/ct-fixture","fork_owner":"owner","fork_id":123,"fork_created_by_evaluation":True}
        experiment=SimpleNamespace(gh=github,upstream="development/fixture")
        github.request.side_effect=[info,None]
        github.all.side_effect=[[],[{"id":5}],[]]
        clear_owned_caches(experiment,state,lambda:None)
        self.assertEqual(state["cache_delete_intents"],[5])
        self.assertEqual(github.request.call_args.args[:2],("DELETE","/repos/owner/ct-fixture/actions/caches/5"))
        with self.assertRaisesRegex(ValueError,"owned fork"):
            clear_owned_caches(experiment,{**state,"fork_created_by_evaluation":False},lambda:None)
        github.reset_mock();github.request.side_effect=[{**info,"id":456}]
        with self.assertRaisesRegex(ValueError,"repository ID changed"):
            clear_owned_caches(experiment,state,lambda:None)
        self.assertFalse(any(c.args[0]=="DELETE" for c in github.request.call_args_list))
        github.reset_mock();github.request.side_effect=[info];github.all.side_effect=[[{"status":"queued"}]]
        with self.assertRaises(RunPending):clear_owned_caches(experiment,state,lambda:None)
        self.assertFalse(any(c.args[0]=="DELETE" for c in github.request.call_args_list))

    def test_warmups_are_durable_and_excluded_from_measured_repetitions(self):
        from evaluation.full_patterns.hosted import run_hosted
        from evaluation.full_patterns.study import _hosted_summary
        class Experiment:
            def __init__(inner,*args,**kwargs):pass
            def provision(inner,state,save):state["fork_repo"]="owner/fixture";save()
            def prepare(inner,state,save):pass
            def make_treatment_arm(inner,*args):pass
            def execute(inner,state,save,*,arm,repeat,max_total,**kwargs):
                self.assertEqual(max_total,12)
                result={"arm":arm,"repeat":repeat,"comparable":True,"workflow_elapsed_seconds":10,
                        "sum_job_runtime_seconds":20}
                state["records"].append(result);save();return result
        with patch("evaluation.full_patterns.hosted.TreatmentFork",Experiment),\
             patch("evaluation.full_patterns.hosted.clear_owned_caches") as reset:
            result=run_hosted(self.snapshot,self.root/"warm-hosted",study_id="warm",context=self.context,
                treatments={"B":{"files":[]},"C":{"files":[]}},repetitions=3,github=object(),
                required_jobs=["test"],admitted=["B","C"],cache_regime="warm")
        self.assertEqual(reset.call_count,1)
        self.assertEqual(len(result["records"]),12)
        self.assertTrue(all(r["complete"] for r in _hosted_summary(result,{"B":"NO_CHANGE","C":"NO_CHANGE"},3).values()))

    def test_real_member_batch_connects_new_pipeline_and_resumes_without_regeneration(self):
        from evaluation.full_patterns import batch
        config=self.root/"study-config.json"
        config.write_text(json.dumps({"protocol":"cloudtune-full-pattern-study-v1","generator_model":"ENV",
            "embedding_revision":"AUTO_PIN_SINGLE","top_k":3,"max_tokens":24000,"context_chars":48000,"repetitions":3}))
        verification=self.root/"verified.json";verify_development(self.registry,verification)
        args=SimpleNamespace(member=2,batch_id="independent",start_at=100,stop_at=None,limit=1,list=False,
            config=config,verification=verification,publish_only=False,rerun=False,max_repositories=None,
            evidence_root=None,preflight_only=False,scenario_root=self.root/"no-scenarios-needed",reviews=None)
        def collect(snapshot,extended,**kwargs):
            extended.mkdir(parents=True,exist_ok=True)
            (extended/"context_manifest.json").write_text(json.dumps({"identity":{"manifest_sha256":digest((snapshot/"manifest.json").read_bytes())},
                "archived":[],"omitted":[]}))
        calls=[]
        def transport(req):
            calls.append(req)
            context=json.loads(json.loads(req.data)["messages"][1]["content"])["source"]
            rows=assessments(self.registry,context)
            for row in rows["assessments"]:row.update(status="NOT_APPLICABLE",missing_evidence=[])
            return {"choices":[{"finish_reason":"stop","message":{"content":json.dumps(rows)}}]}
        def proposer(*params,**kwargs):
            return run_proposals(*params,**kwargs,transport=transport)
        partitions={"assignments":[{"file":"assignment.csv","sha256":"d"*64} for _ in range(4)]}
        with patch.object(batch,"ROOT",self.root),patch.object(batch,"RESULTS",self.root/"results"),\
             patch.object(batch,"split_dataset",return_value=partitions),\
             patch.object(batch,"read_evaluation_rows",return_value=[{"repo_id":f"development/repo-{i}","split":"evaluation"} for i in range(1,1001)]),\
             patch.object(batch,"load_env"),patch.object(batch,"excluded_repo_ids",return_value=set()),\
             patch.object(batch,"prepare_repository",return_value={"manifest_path":str(self.snapshot/"manifest.json")}),\
             patch.object(batch,"collect_context",side_effect=collect),\
             patch.object(batch,"collect_history",return_value={"identity":{"source_commit_sha":"a"*40},"status":"no_completed_runs","runs":[]}),\
             patch.dict("os.environ",{"OPENROUTER_MODEL":MODEL,"OPENROUTER_API_KEY":"fixture","GITHUB_TOKEN":"","CLOUDTUNE_FORK_TOKEN":""}):
            result=batch.run_member(args,registry=self.registry,reader=object(),proposer=proposer,
                comparator_generator=lambda *a,**kw:{"decision":"NO_CHANGE"},device_checker=lambda:{"actual_device":"cpu"})
            again=batch.run_member(args,registry=self.registry,reader=object(),proposer=proposer,
                comparator_generator=lambda *a,**kw: (_ for _ in ()).throw(AssertionError("Comparator regenerated")),
                device_checker=lambda:{"actual_device":"cpu"})
            prior=self.root/"results/independent/trials/r0101-g01"
            prior.mkdir(parents=True);(prior/"state.json").write_text('{"status":"BLOCKED"}')
            args.start_at=101;args.rerun=True
            batch.run_member(args,registry=self.registry,reader=object(),proposer=proposer,
                comparator_generator=lambda *a,**kw:{"decision":"NO_CHANGE"},device_checker=lambda:{"actual_device":"cpu"})
            args.start_at=102;args.rerun=False
            batch.run_member(args,registry=self.registry,reader=object(),proposer=proposer,
                comparator_generator=lambda *a,**kw:{"decision":"NO_CHANGE"},device_checker=lambda:{"actual_device":"cpu"})
        self.assertEqual(len(calls),3)
        self.assertEqual(result["status"],"COMPLETE")
        self.assertEqual(again["processed"],0)
        report=json.loads((self.root/"results/independent/trials/r0100-g01/study_report.json").read_text())
        self.assertEqual(report["global_position"],1100)
        self.assertEqual(len(report["patterns"]),25)
        self.assertTrue(all(p["status"]=="NOT_APPLICABLE" for p in report["patterns"]))
        self.assertTrue((self.root/"results/independent/trials/r0101-g02/study_report.json").exists())
        self.assertTrue((self.root/"results/independent/trials/r0102-g01/study_report.json").exists())
