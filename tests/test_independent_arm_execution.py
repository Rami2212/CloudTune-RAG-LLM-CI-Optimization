"""Offline controller regression checks: failures must not cross-arm contaminate."""
from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import evaluation.fork_pipeline as pipeline
from evaluation.ci_executor import arm_name, summarize_records


class FakeExperiment:
    def __init__(self, fail: dict[str, int], calls: list, *, interrupt_after=None):
        self.fail = fail
        self.calls = calls
        self.interrupt_after = interrupt_after

    def provision(self, state, save):
        state["fork_repo"] = "research/repo"
        save()

    def prepare(self, state, save):
        state["workflow_id"] = 42
        save()

    def make_arm(self, state, arm, data, save):
        pass

    def execute(self, state, save, *, arm, repeat, required, max_total):
        self.calls.append((arm, repeat))
        comparable = self.fail.get(arm) != repeat
        record = {"arm": arm, "repeat": repeat, "run_id": len(self.calls),
                  "comparable": comparable,
                  "failure_class": None if comparable else "CI_FAILURE_OR_PROTOCOL_MISMATCH",
                  "workflow_elapsed_seconds": 50.0 if arm == "A" else 40.0,
                  "sum_job_runtime_seconds": 50.0 if arm == "A" else 40.0,
                  "initial_queue_seconds": 5.0}
        state.setdefault("records", []).append(record)
        state["pending"] = None
        if arm == "A" and repeat == 1:
            state["required_names"] = ["test"]
        save()
        if self.interrupt_after == (arm, repeat):
            raise RuntimeError("test forced interruption after checkpoint")
        return record

    def cleanup_fork(self, state, save):
        state["cleanup_status"] = "RETAINED_BY_CONFIGURATION"
        save()
        return "RETAINED_BY_CONFIGURATION"


class IndependentArmExecutionTests(unittest.TestCase):
    def test_display_names_are_descriptive_but_ids_remain_unchanged(self):
        self.assertEqual([arm_name(arm) for arm in "ABC"],
                         ["Original Workflow", "CI-Cost", "LLM + RAG"])

    def _case(self, failures, *, interrupted=None, restart=False):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "evaluation/results/dev-abc-unit"
            snapshot = output / "repositories" / "repo"
            (snapshot / "source").mkdir(parents=True)
            original = b"on: workflow_dispatch\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo ok\n"
            (snapshot / "source/original.yml").write_bytes(original)
            (snapshot / "manifest.json").write_text(json.dumps({
                "repo_id": "source/repo", "workflow_sha256": hashlib.sha256(original).hexdigest(),
                "workflow_path": ".github/workflows/ci.yml", "source_commit_sha": "a" * 40}))
            with (output / "screening.csv").open("w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["repo_id", "status", "manifest_path"])
                writer.writeheader()
                writer.writerow({"repo_id": "source/repo", "status": "prepared",
                                 "manifest_path": str(snapshot / "manifest.json")})
            config = {"evaluation_id": "dev-abc-unit", "repository_limit": 1,
                      "repetitions": 3, "ci_cost": {"version": "1.0.0"},
                      "rag": {"embedding_revision": "AUTO_PIN_SINGLE", "dataset_sha256": "a" * 64,
                              "generator_model": "mock/free:free", "top_k": 2, "max_tokens": 100},
                      "execution": {"required_job_names": []}}
            all_calls=[]
            def run(controller):
                with (patch.object(pipeline, "ROOT", root),
                      patch.object(pipeline, "implementation_digest", return_value="f" * 64),
                      patch.object(pipeline, "_ensure_preparation", return_value=output),
                      patch.object(pipeline, "GitHub", return_value=MagicMock()),
                      patch.object(pipeline, "ForkExperiment", return_value=controller),
                      patch.object(pipeline, "install_ci_cost"),
                      patch.object(pipeline, "generate_ci_cost_candidate", return_value={
                          "decision": "APPLY", "status": "GENERATED_NOT_VALIDATED",
                          "after_sha256": "b" * 64, "candidate_relative_dir": "candidates/B",
                          "generated_artifact": "optimized.yml"}),
                      patch.object(pipeline, "Retriever") as retriever,
                      patch.object(pipeline, "generate_rag_candidate", return_value={
                          "decision": "APPLY", "after_sha256": "c" * 64,
                          "generated_artifact": "optimized.yml"}),
                      patch.object(pipeline, "_candidate_yaml", return_value=b"modified"),
                      patch.object(pipeline, "validate_and_archive", return_value={"verdict": "PASS"}),
                      patch.dict("os.environ", {"GITHUB_TOKEN": "fake-offline-token",
                                                    "CLOUDTUNE_AUTO_DELETE_FORKS": "false"})):
                    retriever.return_value.revision = "a" * 40
                    return pipeline.run_fork_evaluation(config)
            fake=FakeExperiment(failures,all_calls,interrupt_after=interrupted)
            if interrupted:
                with self.assertRaisesRegex(RuntimeError, "forced interruption"):
                    run(fake)
                fake.interrupt_after=None
                report=run(fake)
            else:
                report=run(fake)
            row=report["repositories"]["source/repo"]
            self.assertTrue((output / "state.json").exists())
            return row,all_calls

    def test_b_failure_does_not_stop_a_or_c(self):
        row,calls=self._case({"B":1})
        self.assertEqual(calls,[("A",1),("B",1),("C",1),("C",2),("A",2),("C",3),("A",3)])
        self.assertEqual(row["status"],"FAILED_TARGET_CI")
        self.assertTrue(row["run_statistics"]["A"]["complete"])
        self.assertTrue(row["run_statistics"]["C"]["complete"])
        self.assertFalse(row["run_statistics"]["B"]["complete"])
        self.assertEqual(row["run_statistics"]["C"]["elapsed_saving_percent_vs_A"],20.0)
        self.assertIn("CI-Cost",row["failure_reason"])

    def test_c_failure_does_not_stop_a_or_b(self):
        row,calls=self._case({"C":1})
        self.assertEqual([x for x in calls if x[0]=="C"],[('C',1)])
        self.assertEqual(len([x for x in calls if x[0]=="A"]),3)
        self.assertEqual(len([x for x in calls if x[0]=="B"]),3)
        self.assertTrue(row["run_statistics"]["B"]["complete"])

    def test_original_failure_stops_every_arm(self):
        row,calls=self._case({"A":1})
        self.assertEqual(calls,[("A",1)])
        self.assertEqual(row["status"],"FAILED_TARGET_CI")
        self.assertIn("Original Workflow",row["failure_reason"])

    def test_original_later_failure_stops_all_remaining_trials(self):
        row,calls=self._case({"A":2})
        self.assertEqual(calls,[("A",1),("B",1),("C",1),("B",2),("C",2),("A",2)])
        self.assertEqual(row["status"],"FAILED_TARGET_CI")

    def test_restart_after_b_failure_skips_b_and_continues_a_c(self):
        row,calls=self._case({"B":1},interrupted=("B",1))
        self.assertEqual([x for x in calls if x[0]=="B"],[('B',1)])
        self.assertEqual(len([x for x in calls if x[0]=="A"]),3)
        self.assertEqual(len([x for x in calls if x[0]=="C"]),3)
        self.assertTrue(row["run_statistics"]["C"]["complete"])

if __name__=="__main__":
    unittest.main()
