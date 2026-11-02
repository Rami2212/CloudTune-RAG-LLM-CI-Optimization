"""Unit coverage for env-only OpenRouter settings and frozen provenance."""
from __future__ import annotations

import hashlib
import json
import os
import unittest
from unittest.mock import patch

from evaluation.openrouter_settings import resolve_openrouter_env


class OpenRouterSettingsTests(unittest.TestCase):
    def test_env_overrides_stale_json_without_mutation(self):
        original = {"evaluation_id": "dev-1", "rag": {
            "generator_model": "nvidia/old-model:free", "max_tokens": 100,
            "top_k": 5, "embedding_model": "BAAI/bge-m3"}}
        with patch.dict(os.environ, {
            "OPENROUTER_MODEL": "google/gemma-4-26b-a4b-it:free",
            "OPENROUTER_MAX_TOKENS": "24000"}):
            resolved = resolve_openrouter_env(original)
        self.assertEqual(resolved["rag"]["generator_model"], "google/gemma-4-26b-a4b-it:free")
        self.assertEqual(resolved["rag"]["max_tokens"], 24000)
        self.assertEqual(resolved["rag"]["top_k"], 5)
        self.assertEqual(original["rag"]["generator_model"], "nvidia/old-model:free")
        self.assertEqual(original["rag"]["max_tokens"], 100)

    def test_requires_env_even_when_json_contains_old_model(self):
        original = {"rag": {"generator_model": "old/free:free", "max_tokens": 24000}}
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "OPENROUTER_MODEL"):
                resolve_openrouter_env(original)

    def test_rejects_paid_or_malformed_models(self):
        for model in ("", "google/gemma", "google/model:paid", "some model:free"):
            with self.subTest(model=model), patch.dict(os.environ, {
                "OPENROUTER_MODEL": model, "OPENROUTER_MAX_TOKENS": "24000"}):
                with self.assertRaisesRegex(ValueError, "OPENROUTER_MODEL"):
                    resolve_openrouter_env({"rag": {}})

    def test_rejects_invalid_token_ceilings(self):
        for token in ("", "abc", "255", "48001", "24000.0", "-1"):
            with self.subTest(token=token), patch.dict(os.environ, {
                "OPENROUTER_MODEL": "google/gemma-4-26b-a4b-it:free",
                "OPENROUTER_MAX_TOKENS": token}):
                with self.assertRaisesRegex(ValueError, "OPENROUTER_MAX_TOKENS"):
                    resolve_openrouter_env({"rag": {}})

    def test_changed_env_changes_frozen_config_hash(self):
        config = {"evaluation_id": "dev-1", "rag": {"top_k": 5}}
        with patch.dict(os.environ, {"OPENROUTER_MODEL": "test/model-a:free",
                                     "OPENROUTER_MAX_TOKENS": "24000"}):
            a = resolve_openrouter_env(config)
        with patch.dict(os.environ, {"OPENROUTER_MODEL": "test/model-b:free",
                                     "OPENROUTER_MAX_TOKENS": "24000"}):
            b = resolve_openrouter_env(config)
        frozen_hash = lambda x: hashlib.sha256(json.dumps(x, sort_keys=True).encode()).hexdigest()
        self.assertNotEqual(frozen_hash(a), frozen_hash(b))


if __name__ == "__main__":
    unittest.main()
