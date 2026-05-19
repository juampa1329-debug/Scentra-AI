-- 025_saas_advisor_phase2_realtime.sql
-- Memoria operativa del Advisor para streaming, contexto persistente y senales proactivas.

CREATE TABLE IF NOT EXISTS saas_advisor_memory (
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES saas_users(id) ON DELETE CASCADE,
    memory_key TEXT NOT NULL DEFAULT 'default',
    summary TEXT NOT NULL DEFAULT '',
    facts_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_thread_id UUID NULL REFERENCES saas_advisor_threads(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, user_id, memory_key)
);

CREATE INDEX IF NOT EXISTS idx_saas_advisor_memory_tenant_updated
ON saas_advisor_memory (tenant_id, updated_at DESC);
