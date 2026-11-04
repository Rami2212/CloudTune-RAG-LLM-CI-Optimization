"""Use the existing verified BGE-M3 index with an explicit pattern filter."""
from __future__ import annotations

import math
import os
from .progress import progress


class PatternRetriever:
    """Lazy ML imports keep catalogue/context/offline validation lightweight."""

    def __init__(self, *, dataset, dataset_sha256, revision=None):
        from evaluation.rag_retriever import Retriever
        progress("RAG_INIT","Auditing the existing Supabase index against the frozen corpus; read-only, no ingestion")
        self.base = Retriever(revision=revision, dataset_path=dataset, dataset_sha256=dataset_sha256)
        self.identity = self.base.identity
        progress("RAG_INIT",f"Index verified: documents={self.identity.get('document_count')}; chunks={self.identity.get('chunk_count')}; revision={self.base.revision}")

    def retrieve(self, pattern_id: str, query: str, *, top_k: int) -> list[dict]:
        from evaluation import rag_retriever as backend
        if type(top_k) is not int or not 1 <= top_k <= 20:
            raise ValueError("top_k must be 1..20")
        if pattern_id not in {r["pattern_id"] for r in self.base.metadata.values()}:
            raise ValueError("Unknown retrieval pattern")
        if self.base.model is None:
            if backend.SentenceTransformer is None:
                raise RuntimeError("Install requirements-rag.txt for BGE-M3 retrieval")
            progress("EMBEDDING",f"Loading BGE-M3; revision={self.base.revision}; device={os.environ.get('CLOUDTUNE_RAG_DEVICE','cpu')}")
            self.base.model = backend.SentenceTransformer(
                backend.MODEL, revision=self.base.revision,
                device=os.environ.get("CLOUDTUNE_RAG_DEVICE", "cpu"))
        model = self.base.model
        actual=str(model.device)
        progress("EMBEDDING",f"{pattern_id}: model ready on {actual}; encoding query")
        requested=os.environ.get("CLOUDTUNE_RAG_DEVICE","cpu")
        if requested.startswith("cuda") and not actual.startswith("cuda"):
            raise RuntimeError("Embedding model did not load on requested CUDA device; no fallback is permitted")
        if hasattr(self,"identity"):
            self.identity.update(requested_device=requested,actual_device=actual)
        if len(model.tokenizer(query, add_special_tokens=True)["input_ids"]) > model.max_seq_length:
            raise ValueError("Pattern retrieval query exceeds embedding token budget")
        vector = model.encode([query], normalize_embeddings=True, show_progress_bar=False,
                              convert_to_numpy=True)[0].tolist()
        if len(vector) != 1024 or not all(math.isfinite(x) for x in vector):
            raise ValueError("Invalid pattern retrieval embedding")
        url, key = backend._client_settings()
        rows = backend._json_request(url + "/rpc/match_cloudtune_rag_chunks", key, body={
            "query_embedding": vector, "match_count": top_k,
            "filter_pattern_id": pattern_id, "filter_revision": self.base.revision})
        if not isinstance(rows, list) or len(rows) > top_k:
            raise ValueError("Invalid pattern retrieval cardinality")
        evidence = []
        for row in rows:
            metadata = self.base.metadata.get(row.get("document_id")) if isinstance(row, dict) else None
            if (not metadata or row.get("pattern_id") != pattern_id or metadata["pattern_id"] != pattern_id
                    or row.get("record_type") != metadata["record_type"]
                    or type(row.get("chunk_index")) is not int or row["chunk_index"] < 0
                    or not isinstance(row.get("content"), str) or not row["content"].strip()
                    or type(row.get("similarity")) not in {int, float}
                    or not math.isfinite(row["similarity"]) or not -1.00001 <= row["similarity"] <= 1.00001):
                raise ValueError("Unverified or wrong-pattern retrieval evidence")
            evidence.append({**row, **metadata})
        return evidence
