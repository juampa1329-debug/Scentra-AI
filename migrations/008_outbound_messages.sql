-- 008_outbound_messages.sql
-- Cola SaaS para mensajes salientes y dispatch asincronico.

CREATE TABLE IF NOT EXISTS saas_outbound_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL REFERENCES saas_conversations(id) ON DELETE CASCADE,
    message_id UUID NULL REFERENCES saas_messages(id) ON DELETE SET NULL,
    channel TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT '',
    recipient_external_id TEXT NOT NULL DEFAULT '',
    body_text TEXT NOT NULL DEFAULT '',
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'queued',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    next_attempt_at TIMESTAMP NOT NULL DEFAULT NOW(),
    locked_at TIMESTAMP NULL,
    sent_at TIMESTAMP NULL,
    error TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_outbound_tenant_status_next
ON saas_outbound_messages (tenant_id, status, next_attempt_at);

CREATE INDEX IF NOT EXISTS idx_saas_outbound_conversation_created
ON saas_outbound_messages (conversation_id, created_at DESC);
