"""Offline RAG pipeline tests; no live API requests or repository mutations.

These tests exercise the Arm C candidate generator, frozen corpus validation,
metadata, replay, and request/provenance boundaries.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from evaluation.optimizers.rag_llm import generate_rag_candidate
from evaluation.rag_retriever import Retriever, verify_corpus, RagDevicePaused
from evaluation.repository_preparation import GitHubReader, PreparationError

MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
ORIGINAL = (b"name: Tests\non:\n  workflow_dispatch:\njobs:\n  test:\n    runs-on: ubuntu-latest\n"
            b"    steps:\n      - run: npm test\n")
OPTIMIZED = ORIGINAL.replace(b"      - run: npm test\n", b"      - uses: actions/cache@v4\n"
    b"        with:\n          path: ~/.npm\n          key: ${{ runner.os }}-${{ hashFiles('package-lock.json') }}\n"
    b"      - run: npm test\n")


class FakeRetriever:
    identity = {"dataset_sha256": "b" * 64, "embedding_revision": "a" * 40}
    revision = "a" * 40

    def retrieve(self, query, *, top_k):
        return [{"document_id": "pattern:cache", "pattern_id": "cache", "record_type": "pattern",
                 "chunk_index": 3, "content": "Cache dependency downloads with lockfile keys.",
                 "similarity": 0.91, "evidence_scope": "literature_report_and_analyst_example",
                 "preconditions": ["lockfile exists"], "contraindications": [],
                 "limitations": ["Synthetic fixture only"], "sources": []}]


class ApiResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return io.BytesIO(json.dumps(self.payload).encode())

    def __exit__(self, *args):
        return False


class GenerationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        (self.folder / "source/files").mkdir(parents=True)
        (self.folder / "source/original.yml").write_bytes(ORIGINAL)
        (self.folder / "manifest.json").write_text(json.dumps({
            "workflow_sha256": hashlib.sha256(ORIGINAL).hexdigest(),
            "workflow_path": ".github/workflows/test.yml", "source_commit_sha": "a" * 40,
            "required_checks": {"status": "not_verified"},
            "ci_history": {"status": "not_collected"}}))
        self.kwargs = {"retriever": FakeRetriever(), "model": MODEL,
                       "top_k": 1, "max_tokens": 24000}

    def run_model(self, proposal, *, finish="stop", **kwargs):
        reply = {"model": MODEL, "usage": {"prompt_tokens": 45, "completion_tokens": 34},
                 "choices": [{"finish_reason": finish,
                              "message": {"content": json.dumps(proposal)}}]}
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "TEST_TOKEN"}), patch(
                "evaluation.optimizers.rag_llm.urlopen", return_value=ApiResponse(reply)) as call:
            outcome = generate_rag_candidate(self.folder, **{**self.kwargs, **kwargs})
        return outcome, call

    def test_no_change_is_recorded_without_any_patch(self):
        result, mocked = self.run_model({"decision": "NO_CHANGE", "workflow_yaml": None,
                                         "rationale": "No validated safe change", "evidence_ids": []})
        self.assertEqual(result["decision"], "NO_CHANGE")
        self.assertIsNone(result["patch_sha256"])
        self.assertTrue(mocked.called)
        self.assertFalse((self.folder / "candidates/C/optimized.yml").exists())
        request = json.loads((self.folder / "candidates/C/llm_request.json").read_text())
        self.assertNotIn("response_format", request)
        self.assertEqual(request["provider"]["max_price"], {"prompt": 0, "completion": 0})
        self.assertEqual(request["max_tokens"], 24000)

    def test_apply_preserves_auditable_prompt_and_candidate_hashes(self):
        lock = b'{"name":"app","lockfileVersion":3}'
        (self.folder / "source/files/package-lock.json").write_bytes(lock)
        (self.folder / "source/files_manifest.json").write_text(json.dumps({
            "archived": [{"path": "package-lock.json", "sha256": hashlib.sha256(lock).hexdigest()}]}))
        result, _ = self.run_model({"decision": "APPLY", "workflow_yaml": OPTIMIZED.decode(),
                                    "rationale": "Reuse dependency downloads", "evidence_ids": ["pattern:cache"]},
                                   required_job_names=["test"])
        self.assertEqual(result["decision"], "APPLY")
        self.assertEqual(result["retrieved_ids"], ["pattern:cache"])
        self.assertEqual(len(result["prompt_sha256"]), 64)
        self.assertEqual(len(result["request_sha256"]), 64)
        self.assertEqual(len(result["response_sha256"]), 64)
        self.assertEqual(result["patch_sha256"], hashlib.sha256(
            (self.folder / "candidates/C/change.patch").read_bytes()).hexdigest())
        request = json.loads((self.folder / "candidates/C/llm_request.json").read_text())
        payload = json.loads(request["messages"][1]["content"])
        self.assertEqual(payload["repository_context"]["required_checks"]["names"], ["test"])
        self.assertEqual(payload["repository_context"]["ci_history"]["status"], "not_collected")
        self.assertEqual(payload["repository_context"]["repository_context"][0]["path"], "package-lock.json")
        self.assertEqual(payload["evidence"][0]["limitations"], ["Synthetic fixture only"])

    def test_concurrency_candidate_is_supported_by_general_prompt_and_gate(self):
        self.kwargs["retriever"].pattern_catalogue = [{
            "document_id": "pattern:P-LIT-CANCEL-STALE", "pattern_id": "P-LIT-CANCEL-STALE",
            "pattern": {"mechanism": "cancel_superseded_runs"}}]
        changed = ORIGINAL + (b"concurrency:\n"
            b"  group: ${{ github.workflow }}-${{ github.ref }}\n"
            b"  cancel-in-progress: true\n")
        result, _ = self.run_model({"decision": "APPLY", "workflow_yaml": changed.decode(),
            "rationale": "Cancel superseded runs within the same workflow and ref.",
            "evidence_ids": ["pattern:P-LIT-CANCEL-STALE"]})
        request = json.loads((self.folder / "candidates/C/llm_request.json").read_text())
        payload = json.loads(request["messages"][1]["content"])
        self.assertEqual(payload["pattern_catalogue"], self.kwargs["retriever"].pattern_catalogue)
        self.assertIn("no fixed optimization-type allowlist", payload["instruction"])
        self.assertEqual(result["retrieved_ids"], ["pattern:P-LIT-CANCEL-STALE"])
        self.assertEqual((self.folder / "candidates/C/optimized.yml").read_bytes(), changed)
        # Generation can return a proposal; the common gate decides admission.
        from evaluation.candidate_validator import validate_candidate
        with patch("evaluation.candidate_validator._actionlint", return_value={"status": "PASS"}):
            self.assertEqual(validate_candidate(ORIGINAL, changed)["verdict"], "PASS")

    def test_resume_after_archived_response_does_not_call_model_again(self):
        response = {"model": MODEL, "choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps({"decision": "NO_CHANGE", "workflow_yaml": None,
                                   "rationale": "Not safe", "evidence_ids": []})}}]}
        target = self.folder / "candidates/C"
        target.mkdir(parents=True)
        (target / "llm_response.json").write_text(json.dumps(response, sort_keys=True, indent=2) + "\n")
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "TEST_TOKEN"}), patch(
                "evaluation.optimizers.rag_llm.urlopen") as model:
            result = generate_rag_candidate(self.folder, **self.kwargs)
        model.assert_not_called()
        self.assertIsNone(result["optimizer_seconds"])
        self.assertEqual(result["decision"], "NO_CHANGE")

    def test_recovery_reuses_archived_rag_evidence_without_retrieving_again(self):
        result, _ = self.run_model({"decision": "NO_CHANGE", "workflow_yaml": None,
                                    "rationale": "No safe option", "evidence_ids": []})
        self.assertEqual(result["decision"], "NO_CHANGE")
        (self.folder / "candidates/C/candidate.json").unlink()
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "TEST_TOKEN"}), patch.object(
                self.kwargs["retriever"], "retrieve", side_effect=AssertionError("unexpected retrieval")), patch(
                "evaluation.optimizers.rag_llm.urlopen") as model:
            replayed = generate_rag_candidate(self.folder, **self.kwargs)
        model.assert_not_called()
        self.assertEqual(replayed["decision"], "NO_CHANGE")
        self.assertIsNone(replayed["retrieval_seconds"])

    def test_completed_candidate_is_immutable(self):
        outcome, _ = self.run_model({"decision": "APPLY", "workflow_yaml": OPTIMIZED.decode(),
                                     "rationale": "Use lockfile cache", "evidence_ids": ["pattern:cache"]})
        (self.folder / "candidates/C/optimized.yml").write_text("corrupted")
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "TEST_TOKEN"}):
            with self.assertRaisesRegex(ValueError, "missing or changed"):
                generate_rag_candidate(self.folder, **self.kwargs)
        self.assertEqual(outcome["decision"], "APPLY")

    def test_completed_catalogue_is_immutable(self):
        self.run_model({"decision": "NO_CHANGE", "workflow_yaml": None,
                        "rationale": "No supported treatment", "evidence_ids": []})
        (self.folder / "candidates/C/pattern_catalogue.json").write_text('[{"changed": true}]')
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "TEST_TOKEN"}):
            with self.assertRaisesRegex(ValueError, "catalogue is missing or changed"):
                generate_rag_candidate(self.folder, **self.kwargs)

    def test_frozen_manifest_rejects_changed_context(self):
        (self.folder / "source/files/package.json").write_text('{"name":"altered"}')
        (self.folder / "source/files_manifest.json").write_text(json.dumps({
            "archived": [{"path": "package.json", "sha256": "0" * 64}]}))
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "TEST_TOKEN"}):
            with self.assertRaisesRegex(ValueError, "context changed"):
                generate_rag_candidate(self.folder, **self.kwargs)

    def test_unsupported_paid_model_rejected(self):
        with self.assertRaisesRegex(ValueError, ":free"):
            generate_rag_candidate(self.folder, **{**self.kwargs, "model": "some/paid"})

    def test_unsupported_free_suffix_rejected(self):
        with self.assertRaisesRegex(ValueError, ":free"):
            generate_rag_candidate(self.folder, **{**self.kwargs, "model": "some/free:free-paid"})

    def test_apply_without_citations_is_rejected_and_archived(self):
        with self.assertRaisesRegex(ValueError, "cited"):
            self.run_model({"decision": "APPLY", "workflow_yaml": OPTIMIZED.decode(),
                            "rationale": "Cache", "evidence_ids": []})
        self.assertTrue((self.folder / "candidates/C/llm_response.json").exists())

    def test_no_change_with_yaml_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "NO_CHANGE"):
            self.run_model({"decision": "NO_CHANGE", "workflow_yaml": ORIGINAL.decode(),
                            "rationale": "No change", "evidence_ids": []})

    def test_truncated_response_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "truncated"):
            self.run_model({"decision": "NO_CHANGE", "workflow_yaml": None,
                            "rationale": "No change", "evidence_ids": []}, finish="length")

    def test_json_array_response_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "JSON object"):
            self.run_model([])

    def test_secret_like_context_is_not_sent(self):
        (self.folder / "source/files/package.json").write_text('password: private-value')
        result, _ = self.run_model({"decision": "NO_CHANGE", "workflow_yaml": None,
                                    "rationale": "Not safe", "evidence_ids": []})
        req = json.loads((self.folder / "candidates/C/llm_request.json").read_text())
        self.assertNotIn("private-value", json.dumps(req))
        self.assertEqual(result["decision"], "NO_CHANGE")


class CorpusTests(unittest.TestCase):
    def test_retriever_exposes_all_frozen_patterns_without_top_k_filtering(self):
        dataset = Path(__file__).resolve().parents[1] / "research-data/rag/rag_dataset.jsonl"
        docs = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
        identity = {"eligible_document_ids": [doc["document_id"] for doc in docs
                    if doc.get("retrieval_eligible")], "embedding_revision": "a" * 40}
        with patch("evaluation.rag_retriever.verify_corpus", return_value=identity):
            retriever = Retriever(revision="a" * 40, dataset_path=dataset,
                                  dataset_sha256=hashlib.sha256(dataset.read_bytes()).hexdigest())
        self.assertEqual(len(retriever.pattern_catalogue), 25)
        self.assertEqual({row["pattern_id"] for row in retriever.pattern_catalogue},
                         {doc["pattern_id"] for doc in docs if doc["record_type"] == "pattern"})
        self.assertTrue(all(row["pattern"]["preconditions"] for row in retriever.pattern_catalogue))

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "rag_dataset.jsonl"
        self.record = {"document_id": "pattern:cache", "record_type": "pattern",
                       "pattern_id": "cache", "title": "Dependency cache",
                       "text": "Cache downloads", "retrieval_eligible": True,
                       "evidence_scope": "literature_report", "pattern": {
                           "sources": [{"title": "Example paper"}],
                           "preconditions": ["cacheable dependencies"],
                           "contraindications": ["unsafe mutable cache"]}}

    def corpus(self, records):
        raw = ("\n".join(json.dumps(r) for r in records) + "\n").encode()
        self.path.write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()

    def remote(self, document=None, *, count=2):
        doc = document or self.record
        return [{"document_id": doc["document_id"],
                 "source_sha256": hashlib.sha256(json.dumps(doc, sort_keys=True,
                 ensure_ascii=False).encode()).hexdigest(),
                 "embedding_model": "BAAI/bge-m3", "embedding_revision": "a" * 40,
                 "chunk_count": count, "chunk_tokens": 1024, "chunk_overlap": 128}]

    def mocks(self, document=None, *, count=2):
        rows = self.remote(document, count=count)
        chunks = [{"document_id": rows[0]["document_id"]}] * count
        def request(url, key, **kwargs):
            return chunks if "cloudtune_rag_chunks?" in url else rows
        return patch("evaluation.rag_retriever._client_settings", return_value=("https://example/rest/v1", "secret")), patch(
            "evaluation.rag_retriever._json_request", side_effect=request)

    def test_frozen_corpus_index_and_actual_chunk_count(self):
        digest = self.corpus([self.record])
        setting, remote = self.mocks()
        with setting, remote:
            checked = verify_corpus(self.path, expected_sha256=digest, revision=None)
        self.assertEqual(checked["document_count"], 1)
        self.assertEqual(checked["chunk_count"], 2)
        self.assertEqual(checked["chunk_tokens"], 1024)
        self.assertEqual(checked["eligible_document_ids"], ["pattern:cache"])

    def test_duplicate_id_is_rejected_before_remote_access(self):
        digest = self.corpus([self.record, self.record])
        with patch("evaluation.rag_retriever._client_settings") as client:
            with self.assertRaisesRegex(ValueError, "duplicate"):
                verify_corpus(self.path, expected_sha256=digest, revision=None)
            client.assert_not_called()

    def test_dataset_hash_mismatch_is_rejected_before_remote(self):
        self.corpus([self.record])
        with patch("evaluation.rag_retriever._client_settings") as client:
            with self.assertRaisesRegex(ValueError, "frozen corpus"):
                verify_corpus(self.path, expected_sha256="0" * 64, revision=None)
            client.assert_not_called()

    def test_chunk_audit_paginates_on_stable_primary_key(self):
        digest = self.corpus([self.record])
        remote = self.remote(count=1001)
        observed_urls = []
        def response(url, key, **kwargs):
            if "cloudtune_rag_documents?" in url:
                return remote
            observed_urls.append(url)
            return ([{"document_id": "pattern:cache"}] * 1000 if "offset=0" in url
                    else [{"document_id": "pattern:cache"}])
        with patch("evaluation.rag_retriever._client_settings", return_value=("https://x", "s")), patch(
                "evaluation.rag_retriever._json_request", side_effect=response):
            checked = verify_corpus(self.path, expected_sha256=digest, revision="a" * 40)
        self.assertEqual(checked["chunk_count"], 1001)
        self.assertEqual(len(observed_urls), 2)
        self.assertTrue(all("order=document_id.asc%2Cchunk_index.asc" in u for u in observed_urls))

    def test_missing_remote_chunks_is_rejected(self):
        digest = self.corpus([self.record])
        row = self.remote()[0]
        with patch("evaluation.rag_retriever._client_settings", return_value=("https://x", "s")), patch(
                "evaluation.rag_retriever._json_request",
                side_effect=lambda url, key, **k: [] if "chunks?" in url else [row]):
            with self.assertRaisesRegex(ValueError, "chunk counts"):
                verify_corpus(self.path, expected_sha256=digest, revision="a" * 40)

    def test_retrieval_enriches_mid_chunk_with_sources_and_caveats(self):
        digest = self.corpus([self.record])
        setting, remote = self.mocks()
        with setting, remote:
            retriever = Retriever(revision="a" * 40, dataset_path=self.path, dataset_sha256=digest)
        class FakeTokenizer:
            def __call__(self, text, **kwargs):
                return {"input_ids": [1,2]}
        class FakeModel:
            tokenizer = FakeTokenizer()
            max_seq_length = 8192
            def encode(self, *args, **kwargs):
                class Array:
                    def tolist(self):
                        return [0.01] * 1024
                class Matrix:
                    def __getitem__(self, idx):
                        return Array()
                return Matrix()
        retriever.model = FakeModel()
        rpc = [{"document_id": "pattern:cache", "pattern_id": "cache", "record_type": "pattern",
                "chunk_index": 2, "content": "Middle chunk", "similarity": 0.7}]
        with patch("evaluation.rag_retriever._client_settings", return_value=("https://x", "secret")), patch(
                "evaluation.rag_retriever._json_request", return_value=rpc):
            evidence = retriever.retrieve("cache", top_k=5)
        self.assertEqual(evidence[0]["preconditions"], ["cacheable dependencies"])
        self.assertEqual(evidence[0]["contraindications"], ["unsafe mutable cache"])
        self.assertEqual(evidence[0]["sources"][0]["title"], "Example paper")
        self.assertEqual(evidence[0]["evidence_scope"], "literature_report")

    def test_unfrozen_rpc_document_is_rejected(self):
        digest = self.corpus([self.record])
        setting, remote = self.mocks()
        with setting, remote:
            retriever = Retriever(revision="a" * 40, dataset_path=self.path, dataset_sha256=digest)
        class FakeModel:
            max_seq_length = 8192
            tokenizer = lambda self, *_args, **_kwargs: {"input_ids": [1]}
            def encode(self,*args,**kwargs):
                class Item:
                    def tolist(self):return [0]*1024
                class Matrix:
                    def __getitem__(self,k):return Item()
                return Matrix()
        retriever.model=FakeModel()
        with patch("evaluation.rag_retriever._client_settings", return_value=("https://x", "secret")), patch(
                "evaluation.rag_retriever._json_request", return_value=[{
                    "document_id": "unknown", "pattern_id": "cache", "record_type": "pattern",
                    "chunk_index": 0, "content": "unsafe", "similarity": .9}]):
            with self.assertRaisesRegex(ValueError, "unapproved"):
                retriever.retrieve("cache", top_k=5)


class DevicePauseTests(unittest.TestCase):
    def test_unavailable_cuda_pauses_before_loading_weights_or_querying_index(self):
        retriever = Retriever.__new__(Retriever)
        retriever.model = None
        retriever.revision = "a" * 40
        with patch.dict(os.environ, {"CLOUDTUNE_RAG_DEVICE": "cuda"}), \
             patch("torch.cuda.is_available", return_value=False), \
             patch("evaluation.rag_retriever.SentenceTransformer") as loader, \
             patch("evaluation.rag_retriever._json_request") as index:
            with self.assertRaisesRegex(RagDevicePaused, "No CUDA GPUs are available"):
                retriever.retrieve("CI patterns", top_k=5)
        loader.assert_not_called()
        index.assert_not_called()

    def test_cuda_failure_during_encoding_pauses_without_fallback(self):
        retriever = Retriever.__new__(Retriever)
        retriever.model = MagicMock()
        retriever.model.tokenizer.return_value = {"input_ids": [1]}
        retriever.model.max_seq_length = 8192
        retriever.model.encode.side_effect = RuntimeError("CUDA out of memory")
        with patch.dict(os.environ, {"CLOUDTUNE_RAG_DEVICE": "cuda:0"}), \
             patch("evaluation.rag_retriever.SentenceTransformer") as loader, \
             patch("evaluation.rag_retriever._json_request") as index:
            with self.assertRaisesRegex(RagDevicePaused, "CUDA out of memory"):
                retriever.retrieve("CI patterns", top_k=5)
        retriever.model.encode.assert_called_once()
        loader.assert_not_called()
        index.assert_not_called()

    def test_cpu_does_not_probe_cuda_or_reclassify_unrelated_errors(self):
        retriever = Retriever.__new__(Retriever)
        retriever.model = None
        retriever.revision = "a" * 40
        with patch.dict(os.environ, {"CLOUDTUNE_RAG_DEVICE": "cpu"}), \
             patch("evaluation.rag_retriever._check_cuda_device") as probe, \
             patch("evaluation.rag_retriever.SentenceTransformer", side_effect=RuntimeError("missing model")):
            with self.assertRaises(RuntimeError) as caught:
                retriever.retrieve("CI patterns", top_k=5)
        self.assertNotIsInstance(caught.exception, RagDevicePaused)
        probe.assert_not_called()


class HistoryTests(unittest.TestCase):
    def test_preparation_history_is_read_only_context_not_measured_ci(self):
        reader = GitHubReader(token="TEST_ONLY")
        response = {"workflow_runs": [{"id": 71, "head_sha": "a" * 40,
                    "conclusion": "success", "event": "push",
                    "created_at": "2026-10-15T00:00:00Z",
                    "updated_at": "2026-10-15T00:02:00Z"}]}
        with patch.object(reader, "get_json", return_value=response) as request:
            result = reader.workflow_history("example/repository", ".github/workflows/ci.yml", "main")
        self.assertEqual(result["measurement"], "not_a_measured_baseline")
        self.assertEqual(result["status"], "historical_context_only")
        self.assertEqual(result["runs"][0]["run_id"], 71)
        self.assertIn("/actions/workflows/ci.yml/runs?", request.call_args.args[0])

    def test_missing_actions_read_permission_does_not_fail_preparation(self):
        reader = GitHubReader(token="TEST_ONLY")
        with patch.object(reader, "get_json", side_effect=PreparationError("HTTP 403", "api_error")):
            result = reader.workflow_history("example/repository", ".github/workflows/ci.yml", "main")
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["runs"], [])


if __name__ == "__main__":
    unittest.main()
