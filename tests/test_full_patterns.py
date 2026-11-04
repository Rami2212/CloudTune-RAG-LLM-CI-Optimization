"""Offline full-corpus proposals; no API requests, model downloads or CI dispatch."""
from __future__ import annotations

import copy
import json
import os
import sys
import types
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from evaluation.full_patterns.registry import load_registry, digest, measurement_plan
from evaluation.full_patterns.context import build_context, collect_context, safe_path
from evaluation.full_patterns.pipeline import run_proposals, request_json
from evaluation.full_patterns.proposals import validate_assessments, validate_proposal
from evaluation.full_patterns.admission import review_template, validate_treatment, validate_output
from evaluation.repository_preparation import git_blob_sha1

WORKFLOW = """name: CI
on: [push, workflow_dispatch]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: bash scripts/test.sh
"""
MODEL = "test/full-pattern-model:free"


def assessments(registry, context, applicable=()):
    return {"assessments": [{"pattern_id": pid,
        "status": "APPLICABLE" if pid in applicable else "MISSING_EVIDENCE",
        "rationale": "Fixture has evidence" if pid in applicable else "Required facts are absent",
        "evidence_paths": [context["workflow_path"]],
        "missing_evidence": [] if pid in applicable else ["Independent mechanism evidence"]}
        for pid in registry["catalogue"]]}


def proposal(pattern, context, *, decision="APPLY"):
    return {"pattern_id": pattern["pattern_id"], "decision": decision,
        "rationale": "Development fixture proposal only, pending independent validation",
        "expected_effect": "Hypothesis to be evaluated with the required scenario",
        "evidence_ids": [pattern["document_id"]], "source_evidence": [context["workflow_path"]],
        "missing_evidence": [], "preconditions": [{"requirement": req, "status": "SUPPORTED",
            "rationale": "Fixture assertion, not an automated safety proof",
            "evidence_paths": [context["workflow_path"]]} for req in pattern["required_evidence"]],
        "files": [], "policy": {"mechanism": pattern["mechanism"], "fixture": True} if decision == "APPLY" else None,
        "analysis": {"prediction_seconds": 10, "hypothesis_only": True} if decision == "ANALYZE" else None}


class FullPatternTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_registry()

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.snapshot = self.root / "snapshot"
        (self.snapshot / "source/files/scripts").mkdir(parents=True)
        files = {"mise.toml": '[tasks.test]\nrun = "bash scripts/test.sh"\n' + "# full context\n" * 200,
                 "scripts/test.sh": "#!/bin/bash\npytest -q\n", "package-lock.json": '{"lockfileVersion": 3}'}
        for path, text in files.items():
            (self.snapshot / "source/files" / path).write_bytes(text.encode())
        (self.snapshot / "source/files_manifest.json").write_text(json.dumps({
            "archived": [{"path": p, "sha256": digest(t.encode())} for p, t in files.items()], "omitted": []}))
        (self.snapshot / "source/original.yml").write_bytes(WORKFLOW.encode())
        self.manifest = {"repo_id": "development/fixture", "source_commit_sha": "a" * 40,
            "source_tree_sha": "b" * 40, "workflow_path": ".github/workflows/test.yml",
            "workflow_sha256": digest(WORKFLOW.encode()), "ci_history": {"status": "not_collected"},
            "required_checks": {"status": "not_verified"}}
        (self.snapshot / "manifest.json").write_text(json.dumps(self.manifest))
        self.context = build_context(self.snapshot)

    def evidence(self, pattern):
        return [{"document_id": pattern["document_id"], "pattern_id": pattern["pattern_id"]}]

    def test_catalogue_has_all_patterns_examples_and_scenarios(self):
        registry = self.registry
        self.assertEqual(len(registry["catalogue"]), 25)
        self.assertEqual(len(registry["documents"]), 74)
        self.assertEqual(sum(p["example_count"] for p in registry["catalogue"].values()), 49)
        for pattern in registry["catalogue"].values():
            self.assertTrue(pattern["eligible_for_proposal"])
            self.assertTrue(pattern["required_evidence"])
            self.assertTrue(pattern["metrics"])
            self.assertEqual(measurement_plan(pattern)["execution_status"], "AVAILABLE_WITH_SCENARIO_INPUTS")
        self.assertFalse(measurement_plan(registry["catalogue"]["P-LIT-DURATION-PREDICTION"])["direct_ci_speedup_claim"])

    def test_corpus_hash_and_missing_pattern_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "corpus hash"):
            load_registry(expected_sha256="0" * 64)
        records = list(self.registry["documents"].values())[1:]
        path = self.root / "bad.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in records))
        with self.assertRaisesRegex(ValueError, "25 eligible"):
            load_registry(path)

    def test_context_includes_complete_mise_and_prioritizes_referenced_script(self):
        included = {r["path"]: r for r in self.context["files"]}
        self.assertGreater(len(included["mise.toml"]["text"]), 1800)
        self.assertEqual(self.context["files"][0]["path"], "scripts/test.sh")
        tiny = build_context(self.snapshot, max_chars=len(WORKFLOW) + 50)
        self.assertNotIn("mise.toml", tiny["included_paths"])
        self.assertTrue(any(r["path"] == "mise.toml" and "full file omitted" in r["reason"] for r in tiny["omitted"]))

    def test_modified_context_or_unsafe_path_never_reaches_model(self):
        (self.snapshot / "source/files/mise.toml").write_text("changed")
        with self.assertRaisesRegex(ValueError, "context changed"):
            build_context(self.snapshot)
        for value in ("../secret", "/tmp/foo", "C:/foo", ".git/config", "foo\\bar", "x/../y", ".env", ".npmrc"):
            with self.subTest(path=value), self.assertRaises(ValueError):
                safe_path(value)

    def test_secret_file_omitted_and_workflow_credentials_rejected(self):
        raw = b"password: PRIVATE_SECRET_VALUE"
        (self.snapshot / "source/files/mise.toml").write_bytes(raw)
        listing_path = self.snapshot / "source/files_manifest.json"
        listing = json.loads(listing_path.read_text())
        listing["archived"][0]["sha256"] = digest(raw)
        listing_path.write_text(json.dumps(listing))
        context = build_context(self.snapshot)
        self.assertNotIn("PRIVATE_SECRET_VALUE", json.dumps(context))
        raw = WORKFLOW.encode() + b"env:\n  password: PRIVATE_SECRET_VALUE\n"
        (self.snapshot / "source/original.yml").write_bytes(raw)
        self.manifest["workflow_sha256"] = digest(raw)
        (self.snapshot / "manifest.json").write_text(json.dumps(self.manifest))
        with self.assertRaisesRegex(ValueError, "possible credentials"):
            build_context(self.snapshot)

    def test_assessment_requires_every_id_and_no_invented_input(self):
        good = assessments(self.registry, self.context)
        self.assertEqual(len(validate_assessments(good, self.registry["catalogue"], self.context)), 25)
        for mutate in (lambda r: r["assessments"].pop(),
                       lambda r: r["assessments"].__setitem__(0, r["assessments"][1]),
                       lambda r: r["assessments"][0].update(evidence_paths=["unseen.file"]),
                       lambda r: r["assessments"][0].update(missing_evidence=[])):
            bad = copy.deepcopy(good); mutate(bad)
            with self.assertRaises(ValueError):
                validate_assessments(bad, self.registry["catalogue"], self.context)

    def test_all_25_patterns_can_propose_their_own_treatment_type(self):
        for pattern in self.registry["catalogue"].values():
            with self.subTest(pattern=pattern["pattern_id"]):
                decision = "ANALYZE" if pattern["family"] == "analytical" else "APPLY"
                checked = validate_proposal(proposal(pattern, self.context, decision=decision),
                    pattern, self.context, self.evidence(pattern))
                self.assertEqual(checked["decision"], decision)
                result = validate_treatment(checked, self.context, self.registry, self.evidence(pattern))
                self.assertEqual(result["verdict"], "REVIEW_REQUIRED")
                self.assertEqual(result["measurement_plan"]["scenario"], pattern["scenario"])

    def test_non_cache_build_file_patch_is_supported(self):
        pattern = self.registry["catalogue"]["P-LIT-PRIORITIZE"]
        raw = proposal(pattern, self.context)
        raw["policy"] = None
        raw["files"] = [{"path": "scripts/test.sh", "before_sha256": digest(b"#!/bin/bash\npytest -q\n"),
                         "content": "#!/bin/bash\npytest tests/test_regression.py tests/test_rest.py\n"}]
        checked = validate_proposal(raw, pattern, self.context, self.evidence(pattern))
        self.assertEqual(validate_treatment(checked, self.context, self.registry,
            self.evidence(pattern))["verdict"], "REVIEW_REQUIRED")

    def test_unmet_prerequisites_wrong_citations_and_analytical_fake_patch_rejected(self):
        pattern = self.registry["catalogue"]["P-LIT-CUSTOM-TIMEOUT"]
        good = proposal(pattern, self.context)
        mutations = (lambda p: p["preconditions"][0].update(status="MISSING"),
                     lambda p: p.update(evidence_ids=["invented:doc"]),
                     lambda p: p.update(source_evidence=["not-provided.txt"]),
                     lambda p: p.update(decision="NO_CHANGE"))
        for mutate in mutations:
            bad = copy.deepcopy(good); mutate(bad)
            with self.assertRaises(ValueError):
                validate_proposal(bad, pattern, self.context, self.evidence(pattern))
        prediction = self.registry["catalogue"]["P-LIT-DURATION-PREDICTION"]
        with self.assertRaisesRegex(ValueError, "APPLY"):
            validate_proposal(proposal(prediction, self.context), prediction, self.context, self.evidence(prediction))

    def test_lint_failure_cannot_be_overridden_and_comments_are_not_optimization(self):
        pattern = self.registry["catalogue"]["P-LIT-CANCEL-STALE"]
        raw = proposal(pattern, self.context); raw["policy"] = None
        raw["files"] = [{"path": self.context["workflow_path"], "before_sha256": self.context["workflow_sha256"],
                         "content": WORKFLOW + "# estimated savings: 100 minutes\n"}]
        checked = validate_proposal(raw, pattern, self.context, self.evidence(pattern))
        with patch("evaluation.full_patterns.admission._actionlint", return_value={"status": "PASS"}):
            self.assertEqual(validate_treatment(checked, self.context, self.registry,
                self.evidence(pattern))["verdict"], "NO_SEMANTIC_CHANGE")
        with patch("evaluation.full_patterns.admission._actionlint", return_value={"status": "FAIL"}):
            self.assertEqual(validate_treatment(checked, self.context, self.registry,
                self.evidence(pattern))["verdict"], "INVALID")

    def test_review_is_source_arm_and_evidence_bound(self):
        pattern = self.registry["catalogue"]["P-LIT-CUSTOM-TIMEOUT"]
        checked = validate_proposal(proposal(pattern, self.context), pattern, self.context, self.evidence(pattern))
        review = review_template(checked, self.context, self.registry)
        review.update(verdict="APPROVE", reviewer="Fixture reviewer", reviewed_at="2026-11-04T00:00:00Z")
        artifact = self.root / "independent-evidence.json"
        artifact.write_text('{"fixture_validation": true}')
        for check in review["checks"]:
            check.update(status="VERIFIED", rationale="Fixture reviewed independently",
                         evidence=[{"path": artifact.name, "sha256": digest(artifact.read_bytes())}])
        verdict = validate_treatment(checked, self.context, self.registry, self.evidence(pattern),
                                     review=review, review_root=self.root)
        self.assertEqual(verdict["verdict"], "READY_FOR_SCENARIO")
        self.assertEqual(verdict["measurement_plan"]["execution_status"], "AVAILABLE_WITH_SCENARIO_INPUTS")
        with self.assertRaisesRegex(ValueError, "different arm"):
            validate_treatment(checked, self.context, self.registry, self.evidence(pattern),
                arm="B", review=review, review_root=self.root)
        artifact.write_text("changed")
        with self.assertRaisesRegex(ValueError, "artifact changed"):
            validate_treatment(checked, self.context, self.registry, self.evidence(pattern),
                review=review, review_root=self.root)

    def test_full_pipeline_replays_without_model_or_retrieval_and_preserves_missing(self):
        pattern = self.registry["catalogue"]["P-LIT-CANCEL-STALE"]
        raw = proposal(pattern, self.context)
        calls = []
        def transport(request):
            body = json.loads(request.data)
            calls.append(body)
            result = assessments(self.registry, self.context, [pattern["pattern_id"]]) if len(calls) == 1 else raw
            return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}]}
        class FakeRetriever:
            identity = {"dataset_sha256": self.registry["dataset_sha256"], "embedding_revision": "c" * 40}
            def retrieve(inner, pid, query, *, top_k):
                self.assertEqual(pid, pattern["pattern_id"])
                self.assertIn("superseded", query.lower())
                return []
        output = self.root / "new-study"
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "DO_NOT_ARCHIVE"}):
            report = run_proposals(self.snapshot, output, registry=self.registry, model=MODEL,
                                   retriever=FakeRetriever(), transport=transport)
        self.assertEqual(len(calls), 2)
        self.assertEqual(report["patterns_considered"], 25)
        self.assertEqual(sum(r["decision"] == "MISSING_EVIDENCE" for r in report["outcomes"]), 24)
        self.assertEqual(report["ci_dispatches"], 0)
        def forbidden(*args, **kwargs):
            raise AssertionError("Unexpected model/network during replay")
        replay = run_proposals(self.snapshot, output, registry=self.registry, model=MODEL,
                               retriever=None, transport=forbidden)
        self.assertEqual(replay, report)
        serialized = "".join(p.read_text() for p in output.rglob("*.json"))
        self.assertNotIn("DO_NOT_ARCHIVE", serialized)
        self.assertEqual((self.snapshot / "source/original.yml").read_text(), WORKFLOW)
        validated = validate_output(output, self.registry)
        self.assertEqual(len(validated["results"]), 25)
        self.assertEqual(next(r for r in validated["results"] if r["pattern_id"] == pattern["pattern_id"])["verdict"], "REVIEW_REQUIRED")
        with self.assertRaisesRegex(ValueError, "Frozen artifact changed"):
            run_proposals(self.snapshot, output, registry=self.registry, model="different/model:free", transport=forbidden)

    def test_truncated_model_response_is_archived_then_rejected(self):
        stage = self.root / "stage"
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "secret"}):
            with self.assertRaisesRegex(ValueError, "truncated"):
                request_json(stage, model=MODEL, max_tokens=100, instruction="test", payload={},
                    transport=lambda request: {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]})
        self.assertTrue((stage / "response.json").exists())

    def test_output_lock_and_source_overlap_prevent_writes(self):
        output = self.root / "locked"; output.mkdir(); (output / ".pipeline.lock").write_text("123")
        with self.assertRaisesRegex(ValueError, "already active"):
            run_proposals(self.snapshot, output, registry=self.registry, model=MODEL)
        with self.assertRaisesRegex(ValueError, "separate"):
            run_proposals(self.snapshot, self.snapshot / "child", registry=self.registry, model=MODEL)

    def test_extended_context_collects_pinned_mise_and_referenced_script_without_mutating_snapshot(self):
        files = {"mise.toml": b'[tasks.test]\nrun="bash scripts/test.sh"\n',
                 "scripts/test.sh": b"pytest -q\n", "unrelated.py": b"print('not needed')\n",
                 "composer.json": b"password: OMIT_THIS_SECRET"}
        class Reader:
            def get_json(inner, path):
                self.assertIn("b" * 40, path)
                return {"tree": [{"path": p, "type": "blob", "mode": "100644",
                         "size": len(b), "sha": git_blob_sha1(b)} for p,b in files.items()]}
            def blob(inner, repo, sha):
                return next(b for b in files.values() if git_blob_sha1(b) == sha)
        output = self.root / "extended"
        result = collect_context(self.snapshot, output, reader=Reader())
        self.assertEqual({r["path"] for r in result["archived"]}, {"mise.toml", "scripts/test.sh"})
        self.assertTrue(any(r["reason"] == "sensitive_or_binary" for r in result["omitted"]))
        class NoNetwork:
            def get_json(*args): raise AssertionError("No network on context replay")
        self.assertEqual(collect_context(self.snapshot, output, reader=NoNetwork()), result)
        self.assertFalse((self.snapshot / "context_manifest.json").exists())

    def test_pattern_retrieval_filters_rpc_and_rejects_cross_pattern_result(self):
        import evaluation
        from evaluation.full_patterns.retrieval import PatternRetriever
        pid = "P-LIT-CANCEL-STALE"
        doc_id = self.registry["catalogue"][pid]["document_id"]
        rpc_calls = []
        rows = [{"document_id": doc_id, "pattern_id": pid, "record_type": "pattern",
                 "chunk_index": 0, "content": "Cancel only superseded revisions", "similarity": 0.9}]
        class Model:
            max_seq_length = 8192
            device = "cpu"
            def tokenizer(inner, *args, **kwargs): return {"input_ids": [1, 2]}
            def encode(inner, *args, **kwargs):
                return [types.SimpleNamespace(tolist=lambda: [0.0] * 1024)]
        retriever = PatternRetriever.__new__(PatternRetriever)
        retriever.base = types.SimpleNamespace(revision="c" * 40, model=Model(),
            metadata={doc_id: {"pattern_id": pid, "record_type": "pattern", "limitations": ["fixture"]}})
        def rpc(url, key, *, body):
            rpc_calls.append(body); return rows
        backend = types.SimpleNamespace(_client_settings=lambda: ("https://fixture/rest/v1", "private"),
                                         _json_request=rpc)
        with patch.dict(sys.modules, {"evaluation.rag_retriever": backend}), \
             patch.object(evaluation, "rag_retriever", backend, create=True):
            found = retriever.retrieve(pid, "superseding revisions", top_k=3)
            self.assertEqual(found[0]["limitations"], ["fixture"])
            self.assertEqual(rpc_calls[0]["filter_pattern_id"], pid)
            self.assertEqual(rpc_calls[0]["filter_revision"], "c" * 40)
            rows[0]["pattern_id"] = "P-LIT-GHA-CACHE"
            with self.assertRaisesRegex(ValueError, "wrong-pattern"):
                retriever.retrieve(pid, "superseding revisions", top_k=3)

    def test_shared_admission_does_not_grant_a_rag_specific_exception(self):
        pattern = self.registry["catalogue"]["P-LIT-BAZEL-PARALLEL"]
        checked = validate_proposal(proposal(pattern, self.context), pattern, self.context, self.evidence(pattern))
        for arm in ("B", "C", "D"):
            with self.subTest(arm=arm):
                verdict = validate_treatment(checked, self.context, self.registry, self.evidence(pattern), arm=arm)
                self.assertEqual(verdict["verdict"], "REVIEW_REQUIRED")
                self.assertEqual(verdict["identity"]["arm"], arm)


if __name__ == "__main__":
    unittest.main()
