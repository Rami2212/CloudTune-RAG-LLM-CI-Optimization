"""Offline checks for corpus admission and lossless token-window boundaries."""
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("embed_rag_supabase", SCRIPTS / "embed_rag_supabase.py")
rag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rag)


class WordTokenizer:
    def __call__(self, text, **kwargs):
        spans = [match.span() for match in re.finditer(r"\S+", text)]
        return {"input_ids": list(range(len(spans))), "offset_mapping": spans}


class RagTests(unittest.TestCase):
    def document(self, kind="pattern", **extra):
        return {"document_id": "doc", "pattern_id": "pattern", "title": "Title", "text": "Body",
                "record_type": kind, "retrieval_eligible": True, **extra}

    def read(self, docs):
        text = "\n".join(json.dumps(doc) for doc in docs)
        with patch.object(Path, "read_text", return_value=text):
            return rag.read_documents(Path("records.jsonl"))

    def test_approved_and_pattern_satisfied_only_including_inconclusive(self):
        good = self.document("experiment_example", experiment={"pattern_satisfied": True, "outcome": "scenario_passed"})
        bad = self.document("experiment_example", document_id="bad", experiment={"pattern_satisfied": False})
        inconclusive = self.document("experiment_example", document_id="inc", experiment={"pattern_satisfied": True, "outcome": "inconclusive"})
        hidden = self.document(document_id="hidden", retrieval_eligible=False)
        self.assertEqual(self.read([good, bad, inconclusive, hidden]), [good, inconclusive])

    def test_duplicate_ids_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.read([self.document(), self.document()])

    def test_missing_text_rejected(self):
        with self.assertRaisesRegex(ValueError, "Missing required"):
            self.read([self.document(text="")])

    def test_no_overlap_preserves_unicode_whitespace_and_tail(self):
        text = "  α\nβ  γ\n\nδ five six seven end\n "
        chunks = rag.chunk_text(text, WordTokenizer(), chunk_tokens=3, overlap=0)
        self.assertEqual("".join(c["content"] for c in chunks), text)
        self.assertTrue(all(0 < c["token_count"] <= 3 for c in chunks))
        self.assertEqual([c["chunk_index"] for c in chunks], list(range(len(chunks))))

    def test_overlap_keeps_boundary_tokens(self):
        chunks = rag.chunk_text("one two three four five six seven", WordTokenizer(), 3, 1)
        self.assertEqual([c["content"].split() for c in chunks],
                         [["one", "two", "three"], ["three", "four", "five"], ["five", "six", "seven"]])

    def test_invalid_overlap_rejected(self):
        with self.assertRaises(ValueError):
            rag.chunk_text("one two", WordTokenizer(), 2, 2)

    def test_secret_key_is_not_sent_as_jwt(self):
        with patch.dict(os.environ, {"SUPABASE_URL": "https://example.supabase.co", "SUPABASE_SECRET_KEY": "sb_secret_placeholder"}, clear=True):
            client = rag.Supabase()
        self.assertEqual(client.headers, {"apikey": "sb_secret_placeholder"})


if __name__ == "__main__":
    unittest.main()
