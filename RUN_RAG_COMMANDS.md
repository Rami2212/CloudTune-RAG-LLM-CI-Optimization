# Local BGE-M3 embeddings and Supabase

Run from the repository root in PowerShell. The first embedding run downloads BGE-M3 weights (approximately 2.3 GB); inference runs on your computer. Supabase stores the approved records and vectors.

1. Install dependencies:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements-rag.txt
   ```

2. Set `SUPABASE_URL` and `SUPABASE_SECRET_KEY` in `.env`. Table creation also needs **either** `SUPABASE_DB_URL` (the Postgres connection string, preferably the session pooler) **or** `SUPABASE_ACCESS_TOKEN` (a Supabase management token). API secret/publishable keys cannot create tables.

3. Create the tables and search/upload functions:

   ```powershell
   .\.venv\Scripts\python.exe scripts\embed_rag_supabase.py --setup-only
   ```

   Alternatively, execute `supabase/migrations/202610310001_cloudtune_rag.sql` in the project's Supabase SQL Editor. You then only need the API credentials in `.env`.

4. Rebuild approved records, then embed and upload:

   ```powershell
   .\.venv\Scripts\python.exe scripts\build_rag_dataset.py
   .\.venv\Scripts\python.exe scripts\embed_rag_supabase.py
   ```

   It embeds only `text`, using 1,024-token chunks with 128-token overlap and normalized 1,024-dimensional vectors. It keeps the complete approved record as JSON metadata. Only approved records and pattern-satisfied, non-inconclusive experiment examples are ingested.

   If GPU memory is limited, use `--device cpu --batch-size 1`. For a small initial upload, use `--limit 2`. Repeating ingestion skips unchanged documents. Changed documents and their chunks are replaced atomically. Existing documents absent from the input are not deleted automatically.

5. Search the stored RAG chunks:

   ```powershell
   .\.venv\Scripts\python.exe scripts\embed_rag_supabase.py --query "When should I cache dependencies in GitHub Actions?" --top-k 5
   ```

   Optional: `--pattern-id P-LIT-GHA-CACHE`. Queries use the stored embedding-model revision. Results contain the relevant chunks and cosine-similarity scores; feed those chunks into your answer-generation prompt. This command retrieves evidence rather than generating an LLM answer.

The tables are `public.cloudtune_rag_documents` and `public.cloudtune_rag_chunks`. Row-level security restricts access to the backend service role. `embedding_model` is `BAAI/bge-m3`; the existing `model` metadata remains the generation model. No OpenRouter or other embedding API is called.

To check credentials and table availability without downloading the model:

```powershell
.\.venv\Scripts\python.exe scripts\embed_rag_supabase.py --check-connection
```
