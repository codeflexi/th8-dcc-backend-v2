-- =====================================================
-- 001_enable_pgvector.sql
-- Enable pgvector extension (required for embeddings)
-- =====================================================

create extension if not exists vector;

-- Optional sanity check
-- select extname from pg_extension where extname = 'vector';
