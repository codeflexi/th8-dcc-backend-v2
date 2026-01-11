-- =====================================================
-- 002_create_evidence_vectors.sql
-- Evidence Vector Store (Clause-level)
-- =====================================================

create table if not exists evidence_vectors (
    id uuid primary key,
    doc_id text not null,
    title text not null,
    uri text not null,

    page_start int not null,
    page_end int not null,

    clause_id text,
    section_path text,

    content text not null,

    embedding vector(1536) not null,

    policy_id text,
    domain text,

    created_at timestamptz default now()
);

-- -----------------------------------------------------
-- Index for vector similarity search
-- -----------------------------------------------------
create index if not exists evidence_vectors_embedding_idx
on evidence_vectors
using ivfflat (embedding vector_cosine_ops)
with (lists = 100);

-- -----------------------------------------------------
-- Helpful metadata indexes
-- -----------------------------------------------------
create index if not exists evidence_vectors_policy_id_idx
on evidence_vectors (policy_id);

create index if not exists evidence_vectors_domain_idx
on evidence_vectors (domain);
