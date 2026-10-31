"""Embed an approved RAG JSONL dataset with local BGE-M3 and upload to Supabase.

Colab setup:
  1. Apply supabase/migrations/202610310001_cloudtune_rag.sql in Supabase SQL Editor.
  2. Add SUPABASE_URL and SUPABASE_SECRET_KEY to Colab Secrets.
  3. Upload rag_dataset.jsonl, install sentence-transformers, and run this file.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

MODEL_NAME = "BAAI/bge-m3"
DIMENSIONS = 1024
CHUNK_TOKENS = 1024
OVERLAP_TOKENS = 128
BATCH_SIZE = 2
REST_TABLE = "cloudtune_rag_documents"


def get_secrets():
    try:
        from google.colab import userdata
    except ImportError:
        raise RuntimeError("Run this script in Google Colab and add the Supabase values under Colab Secrets.") from None
    url = (userdata.get("SUPABASE_URL") or "").rstrip("/")
    key = userdata.get("SUPABASE_SECRET_KEY") or ""
    if not url.startswith("https://") or not key:
        raise RuntimeError("Add SUPABASE_URL and SUPABASE_SECRET_KEY to Colab Secrets.")
    return url, key


def headers_for(key):
    headers = {"apikey": key, "Content-Type": "application/json"}
    # Legacy service-role keys are JWTs; new sb_secret keys are not bearer tokens.
    if key.startswith("eyJ"):
        headers["Authorization"] = "Bearer " + key
    return headers


def request_json(url, headers, body=None, method="GET", timeout=180):
    data = json.dumps(body, allow_nan=False).encode("utf-8") if body is not None else None
    for attempt in range(5):
        req = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=timeout) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < 4:
                time.sleep(min(2 ** attempt, 16))
                continue
            code = "unknown"
            try:
                code = json.loads(exc.read()).get("code", "unknown")
            except Exception:
                pass
            raise RuntimeError(f"Supabase returned HTTP {exc.code} (code {code}). Check the migration and service key.") from None
        except (URLError, TimeoutError):
            if attempt < 4:
                time.sleep(min(2 ** attempt, 16))
                continue
            raise RuntimeError("Could not reach Supabase after retries; check the Colab network and project URL.") from None


def load_dataset(path):
    docs = []
    seen = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        doc = json.loads(line)
        if not doc.get("retrieval_eligible"):
            continue
        if doc.get("record_type") == "experiment_example":
            if doc.get("experiment", {}).get("pattern_satisfied") is not True:
                continue
        elif doc.get("record_type") != "pattern":
            continue
        required = ("document_id", "pattern_id", "title", "text")
        if any(not isinstance(doc.get(k), str) or not doc[k].strip() for k in required):
            raise ValueError(f"Missing required fields on JSONL line {line_number}.")
        if doc["document_id"] in seen:
            raise ValueError(f"Duplicate document_id on JSONL line {line_number}.")
        seen.add(doc["document_id"])
        docs.append(doc)
    if not docs:
        raise ValueError("No retrieval-eligible records found in the JSONL file.")
    return docs


def chunk_text(text, tokenizer):
    encoded = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True,
                        truncation=False, verbose=False)
    offsets = encoded["offset_mapping"]
    if not offsets:
        raise ValueError("A record's searchable text has no BGE-M3 tokens.")
    chunks = []
    start = 0
    while start < len(offsets):
        end = min(start + CHUNK_TOKENS, len(offsets))
        char_start = 0 if start == 0 else offsets[start][0]
        while True:
            char_end = len(text) if end == len(offsets) else offsets[end][0]
            content = text[char_start:char_end]
            count = len(tokenizer(content, add_special_tokens=False, truncation=False,
                                  verbose=False)["input_ids"])
            if count <= CHUNK_TOKENS:
                break
            end -= 1
            if end <= start:
                raise ValueError("Unable to fit a text span within the chunk token limit.")
        chunks.append({"chunk_index": len(chunks), "content": content, "token_count": count})
        if end == len(offsets):
            break
        start = max(start + 1, end - OVERLAP_TOKENS)
    return chunks


def make_supabase_request(base_url, key, method, table_or_rpc, params=None, body=None):
    headers = headers_for(key)
    if table_or_rpc.startswith("rpc/"):
        url = f"{base_url}/rest/v1/{table_or_rpc}"
    else:
        url = f"{base_url}/rest/v1/{table_or_rpc}"
    if params:
        url += "?" + urlencode(params)
    return request_json(url, headers, body=body, method=method)


def main():
    data_path = Path("/content/rag_dataset.jsonl")
    if not data_path.exists():
        try:
            from google.colab import files
            print("Upload the generated rag_dataset.jsonl file.")
            uploaded = files.upload()
            if not uploaded:
                raise RuntimeError("No JSONL file was uploaded.")
            data_path = Path(next(iter(uploaded)))
        except ImportError:
            raise RuntimeError("Place rag_dataset.jsonl in /content before running this script.") from None

    base_url, secret_key = get_secrets()
    docs = load_dataset(data_path)
    print(f"Loaded {len(docs)} eligible records. Checking Supabase tables...")
    make_supabase_request(base_url, secret_key, "GET", REST_TABLE,
                          params={"select": "document_id", "limit": "1"})
    make_supabase_request(base_url, secret_key, "GET", "cloudtune_rag_chunks",
                          params={"select": "document_id", "limit": "1"})

    try:
        from huggingface_hub import HfApi
        from sentence_transformers import SentenceTransformer
    except ImportError:
        raise RuntimeError("Install the Colab dependency first: %pip install -q sentence-transformers") from None

    revision = HfApi().model_info(MODEL_NAME, revision="main").sha
    device = "cuda" if __import__("torch").cuda.is_available() else "cpu"
    print(f"Loading {MODEL_NAME} on {device}; the first run downloads about 2.3 GB of model weights...")
    model = SentenceTransformer(MODEL_NAME, revision=revision, device=device)
    if model.get_sentence_embedding_dimension() != DIMENSIONS:
        raise RuntimeError("BGE-M3 output dimension does not match the Supabase vector column.")
    max_tokens = min(model.max_seq_length, 8192) - model.tokenizer.num_special_tokens_to_add(pair=False)
    if CHUNK_TOKENS > max_tokens:
        raise RuntimeError(f"Reduce CHUNK_TOKENS to at most {max_tokens}.")

    uploaded_docs = skipped_docs = chunk_total = 0
    for index, doc in enumerate(docs, 1):
        source_hash = hashlib.sha256(json.dumps(doc, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        previous = make_supabase_request(
            base_url, secret_key, "GET", REST_TABLE,
            params={"document_id": "eq." + doc["document_id"],
                    "select": "source_sha256,embedding_revision,chunk_tokens,chunk_overlap,chunk_count", "limit": "1"})
        if previous:
            old = previous[0]
            if (old.get("source_sha256") == source_hash and old.get("embedding_revision") == revision
                    and old.get("chunk_tokens") == CHUNK_TOKENS and old.get("chunk_overlap") == OVERLAP_TOKENS):
                skipped_docs += 1
                print(f"[{index}/{len(docs)}] Unchanged record; skipped.")
                continue

        chunks = chunk_text(doc["text"], model.tokenizer)
        vectors = model.encode([c["content"] for c in chunks], batch_size=BATCH_SIZE,
                               normalize_embeddings=True, show_progress_bar=False,
                               convert_to_numpy=True).tolist()
        if len(vectors) != len(chunks) or any(
                len(v) != DIMENSIONS or not all(math.isfinite(x) for x in v) for v in vectors):
            raise RuntimeError("BGE-M3 returned an invalid embedding vector.")
        for chunk, vector in zip(chunks, vectors):
            chunk["embedding"] = vector

        document_row = {
            "document_id": doc["document_id"], "record_type": doc["record_type"],
            "pattern_id": doc["pattern_id"], "title": doc["title"], "content": doc["text"],
            "record": doc, "source_sha256": source_hash, "embedding_model": MODEL_NAME,
            "embedding_revision": revision, "chunk_tokens": CHUNK_TOKENS,
            "chunk_overlap": OVERLAP_TOKENS,
        }
        saved_chunks = make_supabase_request(
            base_url, secret_key, "POST", "rpc/upsert_cloudtune_rag_document",
            body={"p_document": document_row, "p_chunks": chunks})
        if saved_chunks != len(chunks):
            raise RuntimeError("Supabase returned a different number of stored chunks than uploaded.")
        uploaded_docs += 1
        chunk_total += saved_chunks
        print(f"[{index}/{len(docs)}] Uploaded {saved_chunks} chunks.")

    print(json.dumps({
        "uploaded_documents": uploaded_docs,
        "unchanged_documents": skipped_docs,
        "uploaded_chunks": chunk_total,
        "embedding_model": MODEL_NAME,
        "embedding_revision": revision,
        "dimensions": DIMENSIONS,
    }, indent=2))


if __name__ == "__main__":
    main()
