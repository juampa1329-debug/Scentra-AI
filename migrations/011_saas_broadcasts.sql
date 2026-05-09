-- 011_saas_broadcasts.sql
-- Difusiones masivas SaaS con auditoria de destinatarios y cola outbound.

CREATE TABLE IF NOT EXISTS saas_broadcasts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'whatsapp',
    template_id UUID NULL REFERENCES saas_message_templates(id) ON DELETE SET NULL,
    segment_id UUID NULL REFERENCES saas_segments(id) ON DELETE SET NULL,
    body TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    scheduled_at TIMESTAMP NULL,
    audience_count INTEGER NOT NULL DEFAULT 0,
    queued_count INTEGER NOT NULL DEFAULT 0,
    sent_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_broadcasts_tenant_status
ON saas_broadcasts (tenant_id, status, scheduled_at, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_broadcast_recipients (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    broadcast_id UUID NOT NULL REFERENCES saas_broadcasts(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL REFERENCES saas_conversations(id) ON DELETE CASCADE,
    message_id UUID NULL REFERENCES saas_messages(id) ON DELETE SET NULL,
    outbound_id UUID NULL REFERENCES saas_outbound_messages(id) ON DELETE SET NULL,
    channel TEXT NOT NULL DEFAULT 'whatsapp',
    recipient_external_id TEXT NOT NULL DEFAULT '',
    body_text TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'queued',
    error TEXT NOT NULL DEFAULT '',
    queued_at TIMESTAMP NULL,
    sent_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, broadcast_id, conversation_id)
);

CREATE INDEX IF NOT EXISTS idx_saas_broadcast_recipients_broadcast
ON saas_broadcast_recipients (tenant_id, broadcast_id, status);

CREATE INDEX IF NOT EXISTS idx_saas_broadcast_recipients_outbound
ON saas_broadcast_recipients (tenant_id, outbound_id);
