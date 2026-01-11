-- =====================================================
-- 003_create_match_evidence_function.sql
-- Vector similarity search function
-- =====================================================

create or replace function match_evidence(
    query_embedding vector,
    match_count int,
    filter_policy_id text default null
)
returns table (
    id uuid,
    doc_id text,
    title text,
    uri text,
    page_start int,
    page_end int,
    clause_id text,
    section_path text,
    content text,
    similarity float
)
language sql
stable
as $$
    select
        ev.id,
        ev.doc_id,
        ev.title,
        ev.uri,
        ev.page_start,
        ev.page_end,
        ev.clause_id,
        ev.section_path,
        ev.content,
        1 - (ev.embedding <=> query_embedding) as similarity
    from evidence_vectors ev
    where
        (filter_policy_id is null or ev.policy_id = filter_policy_id)
    order by ev.embedding <=> query_embedding
    limit match_count;
$$;
