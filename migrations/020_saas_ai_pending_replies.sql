-- 020_saas_ai_pending_replies.sql
-- Debounce operativo para que la IA espere antes de responder y use el ultimo contexto.

CREATE TABLE IF NOT EXISTS saas_ai_pending_replies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL REFERENCES saas_conversations(id) ON DELETE CASCADE,
    last_message_id UUID NULL REFERENCES saas_messages(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    scheduled_at TIMESTAMP NOT NULL DEFAULT NOW(),
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, conversation_id)
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_pending_due
ON saas_ai_pending_replies (tenant_id, status, scheduled_at);
