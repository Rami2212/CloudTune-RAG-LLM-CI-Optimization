"""Offline OpenRouter deadline and safe manual-retry behavior tests."""
from __future__ import annotations

import io
import json
import threading
import unittest
from urllib.error import HTTPError, URLError

from evaluation.openrouter_http import OpenRouterPaused, request_openrouter_json


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return io.BytesIO(json.dumps(self.payload).encode("utf-8"))

    def __exit__(self, *_):
        return False


class OpenRouterHttpTests(unittest.TestCase):
    def test_success_reads_json_once(self):
        calls = []

        def opener(request, timeout):
            calls.append(timeout)
            return Response({"choices": [{"message": {"content": "ok"}}]})

        result = request_openrouter_json(object(), opener=opener, deadline_seconds=0.1)
        self.assertEqual(result["choices"][0]["message"]["content"], "ok")
        self.assertEqual(calls, [0.1])

    def test_deadline_returns_without_waiting_for_blocked_body(self):
        release = threading.Event()
        started = threading.Event()
        calls = []

        class BlockedResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self, *_):
                started.set()
                release.wait(1)
                return b'{}'

        def opener(request, timeout):
            calls.append(timeout)
            return BlockedResponse()

        try:
            with self.assertRaisesRegex(OpenRouterPaused, "exceeded"):
                request_openrouter_json(object(), opener=opener, deadline_seconds=0.02)
            self.assertTrue(started.is_set())
            self.assertEqual(len(calls), 1)
        finally:
            release.set()

    def test_http_error_is_paused_with_status(self):
        def opener(request, timeout):
            raise HTTPError("https://example.invalid", 429, "quota", {}, None)
        with self.assertRaises(OpenRouterPaused) as context:
            request_openrouter_json(object(), opener=opener, deadline_seconds=0.2)
        self.assertIn("HTTP 429", str(context.exception))
        self.assertEqual(context.exception.http_status, 429)

    def test_connection_failure_is_paused(self):
        def opener(request, timeout):
            raise URLError("network unavailable")
        with self.assertRaisesRegex(OpenRouterPaused, "connection failed"):
            request_openrouter_json(object(), opener=opener, deadline_seconds=0.2)

    def test_http_200_provider_error_is_paused(self):
        with self.assertRaisesRegex(OpenRouterPaused, "provider error"):
            request_openrouter_json(object(), opener=lambda *_args, **_kw: Response(
                {"error": {"code": 502, "message": "unavailable"}}), deadline_seconds=0.2)

    def test_invalid_response_is_paused(self):
        class Bad:
            def __enter__(self):
                return io.BytesIO(b'{bad')
            def __exit__(self, *_):
                return False
        with self.assertRaisesRegex(OpenRouterPaused, "invalid JSON"):
            request_openrouter_json(object(), opener=lambda *_args, **_kw: Bad(), deadline_seconds=0.2)

    def test_deadlines_above_120_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "120 seconds"):
            request_openrouter_json(object(), deadline_seconds=121)


if __name__ == "__main__":
    unittest.main()

class EvaluationPauseTests(unittest.TestCase):
    """Failed free-model calls archive a safe failure, not a fake C candidate."""

    def setUp(self):
        import hashlib
        import tempfile
        from pathlib import Path

        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name)
        original = (b'name: CI\non:\n  workflow_dispatch:\njobs:\n  test:\n'
                    b'    runs-on: ubuntu-latest\n    steps:\n      - run: npm test\n')
        (self.path / 'source').mkdir()
        (self.path / 'source/original.yml').write_bytes(original)
        (self.path / 'manifest.json').write_text(json.dumps({
            'workflow_sha256': hashlib.sha256(original).hexdigest(),
            'workflow_path': '.github/workflows/ci.yml',
            'source_commit_sha': 'a' * 40,
            'required_checks': {'status': 'not_verified'},
            'ci_history': {'status': 'not_collected'},
        }))

    def test_http_429_keeps_frozen_request_and_allows_explicit_retry(self):
        from pathlib import Path
        from unittest.mock import patch
        import os
        from evaluation.optimizers.rag_llm import generate_rag_candidate

        class Retriever:
            identity = {'dataset_sha256': 'b' * 64, 'embedding_revision': 'a' * 40}
            revision = 'a' * 40
            retrieved = 0

            def retrieve(self, query, *, top_k):
                self.retrieved += 1
                return []

        retriever = Retriever()
        opts = {'retriever': retriever, 'model': 'example/free:free', 'top_k': 1,
                'max_tokens': 24000}
        with patch.dict(os.environ, {'OPENROUTER_API_KEY': 'fake-token'}):
            with patch('evaluation.optimizers.rag_llm.urlopen', side_effect=HTTPError(
                    'https://example.invalid', 429, 'quota', {}, None)):
                with self.assertRaisesRegex(OpenRouterPaused, 'HTTP 429'):
                    generate_rag_candidate(self.path, **opts)
            folder = self.path / 'candidates/C'
            self.assertTrue((folder / 'llm_error.json').exists())
            self.assertTrue((folder / 'llm_request.json').exists())
            self.assertTrue((folder / 'retrieval.json').exists())
            self.assertFalse((folder / 'candidate.json').exists())
            self.assertFalse((folder / 'llm_response.json').exists())
            self.assertNotIn('fake-token', (folder / 'llm_error.json').read_text())
            self.assertEqual(json.loads((folder / 'llm_error.json').read_text())['http_status'], 429)
            request_before = (folder / 'llm_request.json').read_bytes()
            reply = {'model': 'example/free:free', 'choices': [{
                'finish_reason': 'stop', 'message': {'content': json.dumps({
                    'decision': 'NO_CHANGE', 'workflow_yaml': None,
                    'rationale': 'No safe optimization applicable', 'evidence_ids': []})}}]}
            with patch('evaluation.optimizers.rag_llm.urlopen', return_value=Response(reply)):
                result = generate_rag_candidate(self.path, **opts)
        self.assertEqual(result['decision'], 'NO_CHANGE')
        self.assertEqual(retriever.retrieved, 1)
        self.assertEqual(request_before, (folder / 'llm_request.json').read_bytes())
        self.assertTrue((folder / 'candidate.json').exists())
