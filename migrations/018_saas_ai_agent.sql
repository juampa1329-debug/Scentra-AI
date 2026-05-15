-- 018_saas_ai_agent.sql
-- Persistencia de ajustes IA y memoria comercial por conversacion.

CREATE TABLE IF NOT EXISTS saas_ai_settings (
    tenant_id UUID PRIMARY KEY REFERENCES saas_tenants(id) ON DELETE CASCADE,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    provider_code TEXT NOT NULL DEFAULT 'google',
    fallback_provider_code TEXT NOT NULL DEFAULT '',
    system_prompt TEXT NOT NULL DEFAULT '',
    max_tokens INTEGER NOT NULL DEFAULT 1800,
    temperature NUMERIC(4,2) NOT NULL DEFAULT 0.5,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS saas_conversation_memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL REFERENCES saas_conversations(id) ON DELETE CASCADE,
    summary TEXT NOT NULL DEFAULT '',
    facts_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_message_id UUID NULL REFERENCES saas_messages(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, conversation_id)
);

CREATE INDEX IF NOT EXISTS idx_saas_conversation_memory_tenant_updated
ON saas_conversation_memory (tenant_id, updated_at DESC);
