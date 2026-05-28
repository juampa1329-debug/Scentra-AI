-- Phase 8: operational Knowledge Base RAG.
-- Adds chunk indexing, retrieval logs and source indexing metadata.

CREATE TABLE IF NOT EXISTS saas_knowledge_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    name TEXT NOT NULL DEFAULT '',
    source_type TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    filename TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    content TEXT NOT NULL DEFAULT '',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

ALTER TABLE saas_knowledge_sources
  ADD COLUMN IF NOT EXISTS name TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS source_type TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS title TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS url TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS filename TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'pending',
  ADD COLUMN IF NOT EXISTS content TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS content_hash TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS chunk_count INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_indexed_at TIMESTAMP NULL,
  ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP NULL,
  ADD COLUMN IF NOT EXISTS error TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_saas_knowledge_tenant_status
ON saas_knowledge_sources (tenant_id, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_knowledge_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    source_id UUID NOT NULL REFERENCES saas_knowledge_sources(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL DEFAULT 0,
    content TEXT NOT NULL DEFAULT '',
    token_estimate INTEGER NOT NULL DEFAULT 0,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    content_hash TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (source_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_saas_knowledge_chunks_tenant_source
ON saas_knowledge_chunks (tenant_id, source_id, chunk_index);

CREATE TABLE IF NOT EXISTS saas_knowledge_retrieval_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    query TEXT NOT NULL DEFAULT '',
    result_count INTEGER NOT NULL DEFAULT 0,
    top_score NUMERIC NOT NULL DEFAULT 0,
    used_by TEXT NOT NULL DEFAULT '',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_knowledge_retrieval_logs_tenant_created
ON saas_knowledge_retrieval_logs (tenant_id, created_at DESC);
