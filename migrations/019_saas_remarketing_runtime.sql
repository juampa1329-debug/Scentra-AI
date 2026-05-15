-- 019_saas_remarketing_runtime.sql
-- Runtime SaaS para inscripcion y ejecucion de flows de remarketing.

CREATE TABLE IF NOT EXISTS saas_remarketing_enrollments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    flow_id UUID NOT NULL REFERENCES saas_remarketing_flows(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL REFERENCES saas_conversations(id) ON DELETE CASCADE,
    channel TEXT NOT NULL DEFAULT 'whatsapp',
    recipient_external_id TEXT NOT NULL DEFAULT '',
    current_step_order INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL DEFAULT 'active',
    next_run_at TIMESTAMP NULL,
    last_sent_at TIMESTAMP NULL,
    last_sent_step_order INTEGER NULL,
    last_error TEXT NOT NULL DEFAULT '',
    meta_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    enrolled_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, flow_id, conversation_id)
);

CREATE INDEX IF NOT EXISTS idx_saas_rmk_enroll_due
ON saas_remarketing_enrollments (tenant_id, state, next_run_at);

CREATE INDEX IF NOT EXISTS idx_saas_rmk_enroll_conversation
ON saas_remarketing_enrollments (tenant_id, conversation_id, updated_at DESC);
