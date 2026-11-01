"""Frozen retrieval adapter using CloudTune's existing Supabase/BGE-M3 schema.

Does not rebuild or upload training records. The corpus identity is checked
against research-data/rag/rag_dataset.jsonl before any candidate is generated.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
    from sentence_transformers import SentenceTransformer
except ImportError:  # Lightweight config/validator tests do not need ML weights.
    SentenceTransformer = None


ROOT = Path(__file__).resolve().parents[1]
MODEL = "BAAI/bge-m3"


def _json_request(url: str, key: str, *, body: dict | None = None):
    headers = {"apikey": key, "Content-Type": "application/json"}
    if key.startswith("eyJ"):
        headers["Authorization"] = "Bearer " + key
    request = Request(url, data=json.dumps(body).encode("utf-8") if body is not None else None,
                      headers=headers, method="POST" if body is not None else "GET")
    try:
        with urlopen(request, timeout=120) as response:
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"Supabase HTTP {exc.code}") from None
    except (URLError, TimeoutError):
        raise RuntimeError("Supabase retrieval connection error") from None


def _client_settings() -> tuple[str, str]:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url.startswith("https://") or not key:
        raise ValueError("SUPABASE_URL and SUPABASE_SECRET_KEY are required for Arm C")
    return url + "/rest/v1", key


def verify_corpus(dataset_path: Path, *, expected_sha256: str, revision: str | None) -> dict:
    """Exact document-ID/hash membership check prevents test-data contamination."""
    raw = dataset_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("RAG dataset does not match the frozen corpus SHA256")
    documents = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    identity = {}
    for doc in documents:
        if not doc.get("retrieval_eligible"):
            continue
        value = json.dumps(doc, sort_keys=True, ensure_ascii=False).encode("utf-8")
        identity[doc["document_id"]] = hashlib.sha256(value).hexdigest()
    base, key = _client_settings()
    remote = _json_request(base + "/cloudtune_rag_documents?" + urlencode({
        "select": "document_id,source_sha256,embedding_model,embedding_revision,chunk_count", "limit": 1000}), key)
    indexed = {entry["document_id"]: entry for entry in remote}
    if set(indexed) != set(identity):
        raise ValueError("Supabase document membership differs from the pinned corpus")
    revisions = {entry["embedding_revision"] for entry in indexed.values()}
    if revision is None:
        if len(revisions) != 1:
            raise ValueError("Supabase contains multiple embedding revisions; cannot auto-pin")
        revision = next(iter(revisions))
    if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
        raise ValueError("Supabase returned an invalid embedding revision")
    for name, digest in identity.items():
        row = indexed[name]
        if (row["source_sha256"] != digest or row["embedding_revision"] != revision or
                row["embedding_model"] != MODEL or row["chunk_count"] < 1):
            raise ValueError(f"Supabase RAG record differs from frozen corpus: {name}")
    return {"dataset_sha256": expected_sha256, "document_count": len(identity),
            "embedding_revision": revision, "model": MODEL}


class Retriever:
    def __init__(self, *, revision: str | None, dataset_path: Path, dataset_sha256: str):
        self.identity = verify_corpus(dataset_path, expected_sha256=dataset_sha256, revision=revision)
        self.revision = self.identity["embedding_revision"]
        self.model = None

    def retrieve(self, query: str, *, top_k: int) -> list[dict]:
        if not 1 <= top_k <= 20:
            raise ValueError("top_k must be 1..20")
        if self.model is None:
            if SentenceTransformer is None:
                raise RuntimeError("Install requirements-rag.txt on the GitHub controller runner")
            self.model = SentenceTransformer(MODEL, revision=self.revision, device="cpu")
        if len(self.model.tokenizer(query, add_special_tokens=True)["input_ids"]) > self.model.max_seq_length:
            raise ValueError("RAG retrieval query exceeds model token limit")
        vector = self.model.encode([query], normalize_embeddings=True, show_progress_bar=False,
                                   convert_to_numpy=True)[0].tolist()
        if len(vector) != 1024:
            raise ValueError("Embedding vector dimensions are incorrect")
        url, key = _client_settings()
        rows = _json_request(url + "/rpc/match_cloudtune_rag_chunks", key, body={
            "query_embedding": vector, "match_count": top_k,
            "filter_pattern_id": None, "filter_revision": self.revision})
        return [{"document_id": row["document_id"], "pattern_id": row["pattern_id"],
                 "record_type": row["record_type"], "chunk_index": row["chunk_index"],
                 "content": row["content"], "similarity": row["similarity"]} for row in rows]
