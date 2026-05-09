-- 006_saas_crm_core.sql
-- Tablas CRM nativas para la version SaaS limpia.

CREATE TABLE IF NOT EXISTS saas_conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    external_contact_id TEXT NOT NULL,
    phone TEXT NOT NULL DEFAULT '',
    display_name TEXT NOT NULL DEFAULT '',
    takeover BOOLEAN NOT NULL DEFAULT FALSE,
    last_message_text TEXT NOT NULL DEFAULT '',
    last_message_at TIMESTAMP NULL,
    unread_count INTEGER NOT NULL DEFAULT 0,
    tags TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, channel, external_contact_id)
);
CREATE INDEX IF NOT EXISTS idx_saas_conversations_tenant_updated
ON saas_conversations (tenant_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL REFERENCES saas_conversations(id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    external_message_id TEXT NOT NULL,
    direction TEXT NOT NULL,
    msg_type TEXT NOT NULL DEFAULT 'text',
    text TEXT NOT NULL DEFAULT '',
    media_id TEXT NOT NULL DEFAULT '',
    mime_type TEXT NOT NULL DEFAULT '',
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, channel, external_message_id)
);
CREATE INDEX IF NOT EXISTS idx_saas_messages_conversation_created
ON saas_messages (conversation_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_saas_messages_tenant_created
ON saas_messages (tenant_id, created_at DESC);
