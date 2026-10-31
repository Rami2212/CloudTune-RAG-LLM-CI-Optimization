begin;

create schema if not exists extensions;
create extension if not exists vector with schema extensions;

create table if not exists public.cloudtune_rag_documents (
    document_id text primary key,
    record_type text not null check (record_type in ('pattern', 'experiment_example')),
    pattern_id text not null,
    title text not null,
    content text not null,
    record jsonb not null,
    source_sha256 text not null,
    embedding_model text not null check (embedding_model = 'BAAI/bge-m3'),
    embedding_revision text not null,
    chunk_tokens integer not null check (chunk_tokens > 0),
    chunk_overlap integer not null check (chunk_overlap >= 0 and chunk_overlap < chunk_tokens),
    chunk_count integer not null check (chunk_count > 0),
    updated_at timestamptz not null default now()
);

create table if not exists public.cloudtune_rag_chunks (
    document_id text not null references public.cloudtune_rag_documents(document_id) on delete cascade,
    chunk_index integer not null check (chunk_index >= 0),
    content text not null,
    token_count integer not null check (token_count > 0),
    embedding extensions.vector(1024) not null,
    primary key (document_id, chunk_index)
);

create index if not exists cloudtune_rag_chunks_embedding_hnsw
    on public.cloudtune_rag_chunks using hnsw (embedding extensions.vector_cosine_ops);
create index if not exists cloudtune_rag_documents_pattern_idx
    on public.cloudtune_rag_documents (pattern_id);

alter table public.cloudtune_rag_documents enable row level security;
alter table public.cloudtune_rag_chunks enable row level security;
revoke all on public.cloudtune_rag_documents, public.cloudtune_rag_chunks from public, anon, authenticated;
grant select, insert, update, delete on public.cloudtune_rag_documents, public.cloudtune_rag_chunks to service_role;

-- Replace one document and all its chunks together; a failed upload keeps its previous version.
create or replace function public.upsert_cloudtune_rag_document(p_document jsonb, p_chunks jsonb)
returns integer
language plpgsql
security invoker
set search_path = public, extensions, pg_temp
as $$
declare
    v_document_id text := p_document->>'document_id';
    v_count integer;
begin
    if jsonb_typeof(p_chunks) <> 'array' or jsonb_array_length(p_chunks) = 0 then
        raise exception 'At least one embedded chunk is required';
    end if;
    v_count := jsonb_array_length(p_chunks);
    insert into public.cloudtune_rag_documents (
        document_id, record_type, pattern_id, title, content, record, source_sha256,
        embedding_model, embedding_revision, chunk_tokens, chunk_overlap, chunk_count
    ) values (
        v_document_id, p_document->>'record_type', p_document->>'pattern_id',
        p_document->>'title', p_document->>'content', p_document->'record',
        p_document->>'source_sha256', p_document->>'embedding_model',
        p_document->>'embedding_revision', (p_document->>'chunk_tokens')::integer,
        (p_document->>'chunk_overlap')::integer, v_count
    ) on conflict (document_id) do update set
        record_type = excluded.record_type, pattern_id = excluded.pattern_id,
        title = excluded.title, content = excluded.content, record = excluded.record,
        source_sha256 = excluded.source_sha256, embedding_model = excluded.embedding_model,
        embedding_revision = excluded.embedding_revision, chunk_tokens = excluded.chunk_tokens,
        chunk_overlap = excluded.chunk_overlap, chunk_count = excluded.chunk_count, updated_at = now();

    delete from public.cloudtune_rag_chunks where document_id = v_document_id;
    insert into public.cloudtune_rag_chunks (document_id, chunk_index, content, token_count, embedding)
    select v_document_id, (item->>'chunk_index')::integer, item->>'content',
           (item->>'token_count')::integer, (item->'embedding')::text::extensions.vector(1024)
    from jsonb_array_elements(p_chunks) as item;
    return v_count;
end;
$$;

create or replace function public.match_cloudtune_rag_chunks(
    query_embedding extensions.vector(1024), match_count integer default 5,
    filter_pattern_id text default null, filter_revision text default null
)
returns table (
    document_id text, pattern_id text, title text, record_type text,
    chunk_index integer, content text, similarity double precision
)
language sql stable security invoker
set search_path = public, extensions, pg_temp
as $$
    select d.document_id, d.pattern_id, d.title, d.record_type, c.chunk_index, c.content,
           1 - (c.embedding <=> query_embedding) as similarity
    from public.cloudtune_rag_chunks c
    join public.cloudtune_rag_documents d using (document_id)
    where (filter_pattern_id is null or d.pattern_id = filter_pattern_id)
      and (filter_revision is null or d.embedding_revision = filter_revision)
    order by c.embedding <=> query_embedding
    limit greatest(1, least(match_count, 100));
$$;

revoke all on function public.upsert_cloudtune_rag_document(jsonb, jsonb) from public, anon, authenticated;
grant execute on function public.upsert_cloudtune_rag_document(jsonb, jsonb) to service_role;
revoke all on function public.match_cloudtune_rag_chunks(extensions.vector, integer, text, text) from public, anon, authenticated;
grant execute on function public.match_cloudtune_rag_chunks(extensions.vector, integer, text, text) to service_role;

notify pgrst, 'reload schema';
commit;
