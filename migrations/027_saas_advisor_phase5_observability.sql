-- 027_saas_advisor_phase5_observability.sql
-- Observabilidad y gobernanza del Advisor: auditoria y feedback humano.

CREATE TABLE IF NOT EXISTS saas_advisor_audit_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    thread_id UUID NULL REFERENCES saas_advisor_threads(id) ON DELETE SET NULL,
    message_id UUID NULL REFERENCES saas_advisor_messages(id) ON DELETE SET NULL,
    action_id UUID NULL REFERENCES saas_advisor_actions(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    summary TEXT NOT NULL DEFAULT '',
    details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_advisor_audit_tenant_created
ON saas_advisor_audit_events (tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS saas_advisor_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    message_id UUID NOT NULL REFERENCES saas_advisor_messages(id) ON DELETE CASCADE,
    rating TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, user_id, message_id)
);

CREATE INDEX IF NOT EXISTS idx_saas_advisor_feedback_tenant_rating
ON saas_advisor_feedback (tenant_id, rating, updated_at DESC);
