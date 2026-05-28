-- Phase 6: Knowledge Base and RAG operational hardening.
-- Adds local sparse-vector metadata and tenant-scoped RAG quality evaluations.

ALTER TABLE saas_knowledge_chunks
  ADD COLUMN IF NOT EXISTS vector_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS keywords_json JSONB NOT NULL DEFAULT '[]'::jsonb;

CREATE INDEX IF NOT EXISTS idx_saas_knowledge_chunks_tenant_updated
ON saas_knowledge_chunks (tenant_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_knowledge_evaluations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    query TEXT NOT NULL DEFAULT '',
    expected_answer TEXT NOT NULL DEFAULT '',
    expected_sources_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    result_count INTEGER NOT NULL DEFAULT 0,
    top_score NUMERIC NOT NULL DEFAULT 0,
    confidence INTEGER NOT NULL DEFAULT 0,
    answerability TEXT NOT NULL DEFAULT 'unknown',
    quality_score INTEGER NOT NULL DEFAULT 0,
    passed BOOLEAN NOT NULL DEFAULT FALSE,
    citations_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_knowledge_evaluations_tenant_created
ON saas_knowledge_evaluations (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_knowledge_evaluations_tenant_passed
ON saas_knowledge_evaluations (tenant_id, passed, created_at DESC);
