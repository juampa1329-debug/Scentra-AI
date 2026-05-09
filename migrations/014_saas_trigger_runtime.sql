-- 014_saas_trigger_runtime.sql
-- Runtime SaaS para ejecuciones de triggers y mensajes programados por trigger.

CREATE TABLE IF NOT EXISTS saas_trigger_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    trigger_id UUID NOT NULL REFERENCES saas_crm_triggers(id) ON DELETE CASCADE,
    conversation_id UUID NULL REFERENCES saas_conversations(id) ON DELETE SET NULL,
    message_id UUID NULL REFERENCES saas_messages(id) ON DELETE SET NULL,
    channel TEXT NOT NULL DEFAULT 'whatsapp',
    event_kind TEXT NOT NULL DEFAULT 'received',
    recipient_external_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'ok',
    error TEXT NOT NULL DEFAULT '',
    details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    executed_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_trigger_exec_trigger_recipient
ON saas_trigger_executions (tenant_id, trigger_id, recipient_external_id, executed_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_trigger_exec_conversation
ON saas_trigger_executions (tenant_id, conversation_id, executed_at DESC);

CREATE TABLE IF NOT EXISTS saas_trigger_scheduled_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    trigger_id UUID NULL REFERENCES saas_crm_triggers(id) ON DELETE SET NULL,
    conversation_id UUID NOT NULL REFERENCES saas_conversations(id) ON DELETE CASCADE,
    template_id UUID NULL REFERENCES saas_message_templates(id) ON DELETE SET NULL,
    channel TEXT NOT NULL DEFAULT 'whatsapp',
    recipient_external_id TEXT NOT NULL DEFAULT '',
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'pending',
    run_at TIMESTAMP NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    sent_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_trigger_sched_due
ON saas_trigger_scheduled_messages (tenant_id, status, run_at);

CREATE INDEX IF NOT EXISTS idx_saas_trigger_sched_conversation
ON saas_trigger_scheduled_messages (tenant_id, conversation_id, created_at DESC);
