"""Frozen retrieval adapter using CloudTune's existing Supabase/BGE-M3 schema.

Does not rebuild or upload training records. The corpus identity is checked
against research-data/rag/rag_dataset.jsonl before any candidate is generated.
"""
from __future__ import annotations

import hashlib
from collections import Counter
import json
import math
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
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
    if urlparse(url).scheme != "https" or not urlparse(url).hostname or not key:
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
        # Mirror the admission policy in scripts/embed_rag_supabase.py exactly.
        kind = doc.get("record_type")
        if kind == "experiment_example":
            if doc.get("experiment", {}).get("pattern_satisfied") is not True:
                continue
        elif kind != "pattern":
            continue
        document_id = doc.get("document_id")
        if not isinstance(document_id, str) or not document_id or document_id in identity:
            raise ValueError("Frozen corpus has a missing or duplicate document_id")
        value = json.dumps(doc, sort_keys=True, ensure_ascii=False).encode("utf-8")
        identity[document_id] = hashlib.sha256(value).hexdigest()
    if not identity:
        raise ValueError("Frozen RAG corpus has no approved records")
    base, key = _client_settings()
    remote = _json_request(base + "/cloudtune_rag_documents?" + urlencode({
        "select": "document_id,source_sha256,embedding_model,embedding_revision,chunk_count,chunk_tokens,chunk_overlap", "limit": 1000}), key)
    if not isinstance(remote, list) or len(remote) >= 1000:
        raise ValueError("Supabase RAG index is invalid or reached the audit pagination limit")
    indexed = {entry["document_id"]: entry for entry in remote}
    if len(indexed) != len(remote):
        raise ValueError("Supabase RAG index has duplicate document IDs")
    if set(indexed) != set(identity):
        raise ValueError("Supabase document membership differs from the pinned corpus")
    revisions = {entry["embedding_revision"] for entry in indexed.values()}
    if revision is None:
        if len(revisions) != 1:
            raise ValueError("Supabase contains multiple embedding revisions; cannot auto-pin")
        revision = next(iter(revisions))
    if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
        raise ValueError("Supabase returned an invalid embedding revision")
    chunk_config = set()
    for name, digest in identity.items():
        row = indexed[name]
        if (row["source_sha256"] != digest or row["embedding_revision"] != revision or
                row["embedding_model"] != MODEL or type(row.get("chunk_count")) is not int
                or row["chunk_count"] < 1):
            raise ValueError(f"Supabase RAG record differs from frozen corpus: {name}")
        tokens, overlap = row.get("chunk_tokens"), row.get("chunk_overlap")
        if (type(tokens) is not int or type(overlap) is not int
                or tokens < 1 or overlap < 0 or overlap >= tokens):
            raise ValueError("Supabase RAG chunk configuration is invalid")
        chunk_config.add((tokens, overlap))
    if len(chunk_config) != 1:
        raise ValueError("Supabase RAG index mixes chunking configurations")
    tokens, overlap = next(iter(chunk_config))
    # Check the actual stored chunks, not just the documents table's claimed
    # chunk_count. Paginate so the default PostgREST row cap cannot hide rows.
    observed_chunks = Counter()
    for offset in range(0, 100_000, 1000):
        page = _json_request(base + "/cloudtune_rag_chunks?" + urlencode({
            "select": "document_id", "limit": 1000, "offset": offset,
            "order": "document_id.asc,chunk_index.asc"}), key)
        if not isinstance(page, list) or len(page) > 1000:
            raise ValueError("Supabase RAG chunk pagination failed")
        for chunk in page:
            document_id = chunk.get("document_id") if isinstance(chunk, dict) else None
            if document_id not in identity:
                raise ValueError("Supabase contains chunks outside the frozen corpus")
            observed_chunks[document_id] += 1
        if len(page) < 1000:
            break
    else:
        raise ValueError("Supabase RAG chunk audit exceeded the safety limit")
    if observed_chunks != Counter({name: row["chunk_count"] for name, row in indexed.items()}):
        raise ValueError("Supabase RAG stored chunk counts differ from frozen documents")
    return {"dataset_sha256": expected_sha256, "document_count": len(identity),
            "embedding_revision": revision, "model": MODEL,
            "chunk_tokens": tokens, "chunk_overlap": overlap,
            "chunk_count": sum(observed_chunks.values()),
            "eligible_document_ids": sorted(identity)}


class Retriever:
    def __init__(self, *, revision: str | None, dataset_path: Path, dataset_sha256: str):
        self.identity = verify_corpus(dataset_path, expected_sha256=dataset_sha256, revision=revision)
        self.revision = self.identity["embedding_revision"]
        self.model = None
        # Only pinned, locally verified corpus metadata can provide provenance.
        # Supabase returns chunk text and similarity; a chunk may omit caveats.
        self.metadata = {}
        for line in dataset_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            doc = json.loads(line)
            if doc.get("document_id") not in self.identity["eligible_document_ids"]:
                continue
            detail = doc.get("pattern", {}) if doc["record_type"] == "pattern" else doc.get("experiment", {})
            self.metadata[doc["document_id"]] = {
                "evidence_scope": doc.get("evidence_scope", "unspecified"),
                "outcome": doc.get("outcome"),
                "sources": detail.get("sources", []) if isinstance(detail, dict) else [],
                "limitations": detail.get("limitations", []) if isinstance(detail, dict) else [],
                "preconditions": detail.get("preconditions", []) if isinstance(detail, dict) else [],
                "contraindications": detail.get("contraindications", []) if isinstance(detail, dict) else [],
                "record_type": doc["record_type"], "pattern_id": doc["pattern_id"],
            }

    def retrieve(self, query: str, *, top_k: int) -> list[dict]:
        if not 1 <= top_k <= 20:
            raise ValueError("top_k must be 1..20")
        if self.model is None:
            if SentenceTransformer is None:
                raise RuntimeError("Install requirements-rag.txt in the local controller environment")
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
        if not isinstance(rows, list) or len(rows) > top_k:
            raise ValueError("Supabase returned invalid retrieval cardinality")
        verified = []
        for row in rows:
            if not isinstance(row, dict) or row.get("document_id") not in self.metadata:
                raise ValueError("Supabase returned an unapproved RAG record")
            metadata = self.metadata[row["document_id"]]
            similarity = row.get("similarity")
            if (row.get("pattern_id") != metadata["pattern_id"]
                    or row.get("record_type") != metadata["record_type"]
                    or type(row.get("chunk_index")) is not int or row["chunk_index"] < 0
                    or not isinstance(row.get("content"), str) or not row["content"].strip()
                    or not isinstance(similarity, (int, float)) or isinstance(similarity, bool)
                    or not math.isfinite(similarity) or not -1.00001 <= similarity <= 1.00001):
                raise ValueError("Supabase returned invalid RAG chunk evidence")
            # Record-level provenance is attached even for a mid-document hit.
            # The model must treat this metadata as untrusted research evidence.
            verified.append({"document_id": row["document_id"],
                             "pattern_id": row["pattern_id"],
                             "record_type": row["record_type"],
                             "chunk_index": row["chunk_index"],
                             "content": row["content"], "similarity": similarity,
                             **{k: v for k, v in metadata.items() if k not in {"pattern_id", "record_type"}}})
        return verified
