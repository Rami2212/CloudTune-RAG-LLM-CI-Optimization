"""Embed approved RAG text locally with BGE-M3 and store it in Supabase pgvector."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode, urlparse
from urllib.request import Request, urlopen

from experiment_environment import load_env

ROOT = Path(__file__).resolve().parents[1]
MODEL = "BAAI/bge-m3"
DIMENSIONS = 1024
MIGRATION = ROOT / "supabase/migrations/202610310001_cloudtune_rag.sql"
DOCUMENT_TABLE = "cloudtune_rag_documents"


def request_json(url, *, headers, body=None, method="GET", timeout=60):
    raw = json.dumps(body, allow_nan=False).encode() if body is not None else None
    for attempt in range(4):
        try:
            request = Request(url, data=raw, headers={"Content-Type": "application/json", **headers}, method=method)
            with urlopen(request, timeout=timeout) as response:
                data = response.read()
                return json.loads(data) if data else None
        except HTTPError as exc:
            if exc.code in {429, 500, 502, 503, 504} and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            # Print only the status/code, never credentials, URL, or raw server payloads.
            try:
                code = json.loads(exc.read()).get("code", "unknown")
            except (ValueError, AttributeError):
                code = "unknown"
            hint = " Apply the Supabase migration first (--setup)." if code in {"PGRST202", "PGRST205", "42P01"} else ""
            raise RuntimeError(f"Supabase request failed: HTTP {exc.code}, code {code}.{hint}") from None
        except (URLError, TimeoutError):
            if attempt < 3:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError("Supabase connection failed or timed out; check network and environment settings.") from None


def supabase_url():
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    if urlparse(url).scheme != "https" or not urlparse(url).hostname:
        raise ValueError("Set SUPABASE_URL to the project's HTTPS URL in .env.")
    return url


class Supabase:
    def __init__(self):
        self.url = supabase_url() + "/rest/v1/"
        key = os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if not key:
            raise ValueError("Set SUPABASE_SECRET_KEY or SUPABASE_SERVICE_ROLE_KEY in .env.")
        self.headers = {"apikey": key}
        # New sb_secret_ keys belong only in apikey, not a JWT Authorization header.
        if key.startswith("eyJ"):
            self.headers["Authorization"] = "Bearer " + key

    def get(self, table, params):
        return request_json(self.url + table + "?" + urlencode(params), headers=self.headers)

    def rpc(self, name, body):
        return request_json(self.url + "rpc/" + name, headers=self.headers, body=body, method="POST", timeout=120)

    def check(self):
        self.get(DOCUMENT_TABLE, {"select": "document_id", "limit": "1"})
        self.get("cloudtune_rag_chunks", {"select": "document_id", "limit": "1"})


def setup_database():
    sql = MIGRATION.read_text(encoding="utf-8")
    connection = os.environ.get("SUPABASE_DB_URL") or os.environ.get("DATABASE_URL")
    if connection:
        try:
            import psycopg
        except ImportError:
            raise RuntimeError("Install requirements-rag.txt to use the Postgres connection.") from None
        try:
            with psycopg.connect(connection, sslmode="require", connect_timeout=20, autocommit=True) as db:
                db.execute(sql, prepare=False)
        except psycopg.Error as exc:
            detail = str(exc).splitlines()[0]
            for secret in (connection, urlparse(connection).password):
                if secret:
                    detail = detail.replace(secret, "[REDACTED]").replace(unquote(secret), "[REDACTED]")
            raise RuntimeError(f"Database migration failed ({type(exc).__name__}): {detail}. If direct-host IPv6 is unavailable, use the session-pooler connection string.") from None
    else:
        token = os.environ.get("SUPABASE_ACCESS_TOKEN")
        if not token:
            raise ValueError("Table creation requires SUPABASE_DB_URL or SUPABASE_ACCESS_TOKEN in .env. API keys cannot execute DDL. Alternatively run the migration in the Supabase SQL Editor.")
        hostname = urlparse(supabase_url()).hostname
        ref = os.environ.get("SUPABASE_PROJECT_REF") or hostname.split(".")[0]
        if not re.fullmatch(r"[a-z0-9]+", ref):
            raise ValueError("Set SUPABASE_PROJECT_REF to the Supabase project reference.")
        request_json(f"https://api.supabase.com/v1/projects/{ref}/database/query",
                     headers={"Authorization": "Bearer " + token}, body={"query": sql}, method="POST", timeout=120)
    print("Supabase migration applied.", flush=True)


def read_documents(path):
    documents = []
    seen = set()
    for line_no, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        doc = json.loads(line)
        if not doc.get("retrieval_eligible"):
            continue
        if doc.get("record_type") == "experiment_example":
            case = doc.get("experiment", {})
            if case.get("pattern_satisfied") is not True:
                continue
        elif doc.get("record_type") != "pattern":
            continue
        if not all(isinstance(doc.get(k), str) and doc[k].strip() for k in ("document_id", "pattern_id", "title", "text")):
            raise ValueError(f"Missing required RAG document fields at line {line_no}.")
        if doc["document_id"] in seen:
            raise ValueError(f"Duplicate document ID at line {line_no}.")
        seen.add(doc["document_id"])
        documents.append(doc)
    if not documents:
        raise ValueError("No approved, eligible documents found. Build the corpus first.")
    return documents


def chunk_text(text, tokenizer, chunk_tokens=1024, overlap=128):
    """Use character offsets from real model tokens to preserve the entire input."""
    if chunk_tokens <= 0 or not 0 <= overlap < chunk_tokens:
        raise ValueError("Require 0 <= overlap < chunk-tokens.")
    encoded = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True, truncation=False, verbose=False)
    offsets = encoded["offset_mapping"]
    if not offsets:
        raise ValueError("Document text has no encodable tokens.")
    chunks = []
    start = 0
    while start < len(offsets):
        end = min(start + chunk_tokens, len(offsets))
        char_start = 0 if start == 0 else offsets[start][0]
        while True:
            char_end = len(text) if end == len(offsets) else offsets[end][0]
            content = text[char_start:char_end]
            count = len(tokenizer(content, add_special_tokens=False, truncation=False, verbose=False)["input_ids"])
            if count <= chunk_tokens:
                break
            end -= 1
            if end <= start:
                raise ValueError("Cannot fit a text span into the token budget.")
        chunks.append({"chunk_index": len(chunks), "content": content, "token_count": count})
        if end == len(offsets):
            break
        start = max(start + 1, end - overlap)
    return chunks


def load_model(revision=None, device=None):
    try:
        from huggingface_hub import HfApi
        from sentence_transformers import SentenceTransformer
    except ImportError:
        raise RuntimeError("Install dependencies: .\\.venv\\Scripts\\python.exe -m pip install -r requirements-rag.txt") from None
    revision = revision or "main"
    # Resolve once and save an immutable revision so queries use identical weights.
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        revision = HfApi().model_info(MODEL, revision=revision).sha
    print("Loading BGE-M3 locally (first run downloads the model weights)...", flush=True)
    model = SentenceTransformer(MODEL, revision=revision, device=device)
    if model.get_sentence_embedding_dimension() != DIMENSIONS:
        raise ValueError("Embedding dimension does not match the database schema.")
    return model, revision


def embeddings(model, texts, batch_size):
    vectors = model.encode(texts, batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False,
                           convert_to_numpy=True).tolist()
    if len(vectors) != len(texts) or any(len(v) != DIMENSIONS or not all(math.isfinite(x) for x in v) for v in vectors):
        raise ValueError("Embedding model returned an invalid vector.")
    return vectors


def ingest(client, args):
    docs = read_documents(args.input)
    if args.limit:
        docs = docs[:args.limit]
    model, revision = load_model(args.revision, args.device)
    max_tokens = min(model.max_seq_length, 8192) - model.tokenizer.num_special_tokens_to_add(pair=False)
    if args.chunk_tokens > max_tokens:
        raise ValueError(f"chunk-tokens must be <= {max_tokens} for BGE-M3.")
    uploaded = skipped = total_chunks = 0
    for index, doc in enumerate(docs, 1):
        raw = json.dumps(doc, sort_keys=True, ensure_ascii=False).encode("utf-8")
        source_hash = hashlib.sha256(raw).hexdigest()
        previous = client.get(DOCUMENT_TABLE, {"document_id": "eq." + doc["document_id"],
                              "select": "source_sha256,embedding_revision,chunk_tokens,chunk_overlap,chunk_count"})
        if previous and not args.force:
            old = previous[0]
            if (old["source_sha256"] == source_hash and old["embedding_revision"] == revision
                    and old["chunk_tokens"] == args.chunk_tokens and old["chunk_overlap"] == args.overlap):
                skipped += 1
                print(f"[{index}/{len(docs)}] Unchanged document; skipped.", flush=True)
                continue
        chunks = chunk_text(doc["text"], model.tokenizer, args.chunk_tokens, args.overlap)
        # Only text is embedded. The complete approved JSON record is retained as metadata.
        vectors = embeddings(model, [c["content"] for c in chunks], args.batch_size)
        for chunk, vector in zip(chunks, vectors):
            chunk["embedding"] = vector
        row = {"document_id": doc["document_id"], "record_type": doc["record_type"],
               "pattern_id": doc["pattern_id"], "title": doc["title"], "content": doc["text"],
               "record": doc, "source_sha256": source_hash, "embedding_model": MODEL,
               "embedding_revision": revision, "chunk_tokens": args.chunk_tokens, "chunk_overlap": args.overlap}
        saved = client.rpc("upsert_cloudtune_rag_document", {"p_document": row, "p_chunks": chunks})
        if saved != len(chunks):
            raise RuntimeError("Database chunk count differs from the uploaded count.")
        uploaded += 1
        total_chunks += saved
        print(f"[{index}/{len(docs)}] Stored {saved} chunks.", flush=True)
    print(json.dumps({"uploaded_documents": uploaded, "unchanged_documents": skipped,
                      "uploaded_chunks": total_chunks, "embedding_model": MODEL,
                      "embedding_revision": revision, "dimensions": DIMENSIONS}, indent=2))


def search(client, args):
    params = {"select": "embedding_revision", "limit": "1000"}
    if args.pattern_id:
        params["pattern_id"] = "eq." + args.pattern_id
    revisions = {row["embedding_revision"] for row in client.get(DOCUMENT_TABLE, params)}
    if not revisions:
        raise ValueError("No embedded documents found. Ingest the corpus first.")
    if args.revision:
        revision = args.revision
    elif len(revisions) == 1:
        revision = next(iter(revisions))
    else:
        raise ValueError("Database contains multiple model revisions; pass --revision with the desired commit SHA.")
    model, revision = load_model(revision, args.device)
    if len(model.tokenizer(args.query, add_special_tokens=True)["input_ids"]) > model.max_seq_length:
        raise ValueError("Search query exceeds the embedding model's token limit.")
    vector = embeddings(model, [args.query], 1)[0]
    results = client.rpc("match_cloudtune_rag_chunks", {"query_embedding": vector,
                         "match_count": args.top_k, "filter_pattern_id": args.pattern_id,
                         "filter_revision": revision})
    print(json.dumps(results, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "research-data/rag/rag_dataset.jsonl")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--setup", action="store_true", help="Apply the database migration before ingestion")
    parser.add_argument("--setup-only", action="store_true", help="Apply the migration and exit")
    parser.add_argument("--check-connection", action="store_true", help="Check both database tables without loading the model")
    parser.add_argument("--chunk-tokens", type=int, default=1024)
    parser.add_argument("--overlap", type=int, default=128)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--device", choices=("cpu", "cuda", "mps"), default=None, help="Default: auto-detect")
    parser.add_argument("--revision", help="Hugging Face model revision; the resolved commit is saved")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--force", action="store_true", help="Re-embed unchanged documents")
    parser.add_argument("--query", help="Embed a question and search the stored chunks")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--pattern-id", help="Optional pattern filter for search")
    args = parser.parse_args()
    try:
        if args.batch_size < 1 or args.limit is not None and args.limit < 1:
            raise ValueError("batch-size and limit must be positive.")
        if args.chunk_tokens < 1 or not 0 <= args.overlap < args.chunk_tokens:
            raise ValueError("Require 0 <= overlap < chunk-tokens.")
        if not 1 <= args.top_k <= 100:
            raise ValueError("top-k must be between 1 and 100.")
        load_env(args.env_file)
        if args.setup or args.setup_only:
            setup_database()
        if args.setup_only:
            return 0
        client = Supabase()
        # A newly applied migration can take a few seconds to reach PostgREST's schema cache.
        for attempt in range(6):
            try:
                client.check()
                break
            except RuntimeError as exc:
                if args.setup and "PGRST205" in str(exc) and attempt < 5:
                    time.sleep(2)
                    continue
                raise
        if args.check_connection:
            print("Supabase tables are reachable.")
        elif args.query:
            search(client, args)
        else:
            ingest(client, args)
        return 0
    except (ValueError, OSError, RuntimeError) as exc:
        # Some library exceptions can contain URLs/secrets. Redact all configured credentials.
        message = str(exc)
        for name in ("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_ACCESS_TOKEN",
                     "SUPABASE_DB_URL", "DATABASE_URL"):
            if os.environ.get(name):
                message = message.replace(os.environ[name], "[REDACTED]")
        for name in ("SUPABASE_DB_URL", "DATABASE_URL"):
            password = urlparse(os.environ.get(name, "")).password
            if password:
                message = message.replace(password, "[REDACTED]").replace(unquote(password), "[REDACTED]")
        print("Error: " + message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
