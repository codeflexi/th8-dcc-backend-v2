-- Mock Supabase Vector Schema (pgvector)
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE contract_chunks (
    id uuid PRIMARY KEY,
    document_id text,
    clause_id text,
    content text,
    embedding vector(1536),
    metadata jsonb
);

-- Example similarity search
-- SELECT content, clause_id
-- FROM contract_chunks
-- ORDER BY embedding <-> :query_embedding
-- LIMIT 3;
