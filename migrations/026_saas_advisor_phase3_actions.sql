-- 026_saas_advisor_phase3_actions.sql
-- Human Approval Layer: acciones sugeridas por Advisor antes de ejecutar cambios sensibles.

CREATE TABLE IF NOT EXISTS saas_advisor_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    created_by UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    recommendation_id UUID NULL REFERENCES saas_ai_recommendations(id) ON DELETE SET NULL,
    insight_id UUID NULL REFERENCES saas_ai_insights(id) ON DELETE SET NULL,
    action_type TEXT NOT NULL DEFAULT 'advisor_action',
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    impact TEXT NOT NULL DEFAULT 'medium',
    risk_level TEXT NOT NULL DEFAULT 'medium',
    approval_required BOOLEAN NOT NULL DEFAULT TRUE,
    status TEXT NOT NULL DEFAULT 'draft',
    approved_by UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    approved_at TIMESTAMP NULL,
    executed_at TIMESTAMP NULL,
    execution_result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_advisor_actions_tenant_status
ON saas_advisor_actions (tenant_id, status, updated_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS ux_saas_advisor_actions_open_recommendation
ON saas_advisor_actions (tenant_id, recommendation_id)
WHERE recommendation_id IS NOT NULL AND status IN ('draft', 'pending_approval', 'approved');

CREATE UNIQUE INDEX IF NOT EXISTS ux_saas_advisor_actions_open_insight
ON saas_advisor_actions (tenant_id, insight_id)
WHERE insight_id IS NOT NULL AND status IN ('draft', 'pending_approval', 'approved');
