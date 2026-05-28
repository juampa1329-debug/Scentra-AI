-- Phase 4: robust inbox/CRM operations.
-- Adds assignment, SLA, lead scoring, follow-up tasks and message status history.

ALTER TABLE saas_conversations
    ADD COLUMN IF NOT EXISTS assigned_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS priority TEXT NOT NULL DEFAULT 'normal',
    ADD COLUMN IF NOT EXISTS sla_due_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS first_response_due_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS lead_score INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS lead_temperature TEXT NOT NULL DEFAULT 'cold',
    ADD COLUMN IF NOT EXISTS last_customer_message_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS last_agent_message_at TIMESTAMP NULL;

CREATE INDEX IF NOT EXISTS idx_saas_conversations_assignee
    ON saas_conversations (tenant_id, assigned_user_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_conversations_sla
    ON saas_conversations (tenant_id, sla_due_at)
    WHERE sla_due_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_saas_conversations_score
    ON saas_conversations (tenant_id, lead_score DESC, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_crm_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL REFERENCES saas_conversations(id) ON DELETE CASCADE,
    assigned_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    priority TEXT NOT NULL DEFAULT 'normal',
    due_at TIMESTAMP NULL,
    completed_at TIMESTAMP NULL,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_crm_tasks_tenant_status
    ON saas_crm_tasks (tenant_id, status, due_at NULLS LAST, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_crm_tasks_conversation
    ON saas_crm_tasks (tenant_id, conversation_id, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_message_status_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    conversation_id UUID NULL REFERENCES saas_conversations(id) ON DELETE CASCADE,
    message_id UUID NULL REFERENCES saas_messages(id) ON DELETE SET NULL,
    provider_message_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    error TEXT NOT NULL DEFAULT '',
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMP NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_message_status_events_conversation
    ON saas_message_status_events (tenant_id, conversation_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_message_status_events_provider
    ON saas_message_status_events (tenant_id, provider_message_id, occurred_at DESC);
