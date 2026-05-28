-- 052_saas_autonomous_operational_intelligence_phase11.sql
-- Phase 11: Autonomous Operational Intelligence with human-supervised remediation.

CREATE TABLE IF NOT EXISTS saas_ai_operation_policies (
    tenant_id UUID PRIMARY KEY REFERENCES saas_tenants(id) ON DELETE CASCADE,
    autonomy_level INTEGER NOT NULL DEFAULT 0,
    auto_remediation_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    low_risk_auto_execute BOOLEAN NOT NULL DEFAULT FALSE,
    sensitivity TEXT NOT NULL DEFAULT 'medium',
    max_daily_actions INTEGER NOT NULL DEFAULT 0,
    approval_required_from_level INTEGER NOT NULL DEFAULT 2,
    settings_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_saas_ai_operation_policies_level CHECK (autonomy_level >= 0 AND autonomy_level <= 4),
    CONSTRAINT chk_saas_ai_operation_policies_approval_level CHECK (approval_required_from_level >= 0 AND approval_required_from_level <= 4)
);

CREATE TABLE IF NOT EXISTS saas_ai_operation_playbooks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    playbook_key TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'operations',
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    risk_level TEXT NOT NULL DEFAULT 'medium',
    required_autonomy_level INTEGER NOT NULL DEFAULT 1,
    approval_required BOOLEAN NOT NULL DEFAULT TRUE,
    auto_executable BOOLEAN NOT NULL DEFAULT FALSE,
    action_type TEXT NOT NULL DEFAULT '',
    action_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    rollback_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, playbook_key),
    CONSTRAINT chk_saas_ai_operation_playbooks_level CHECK (required_autonomy_level >= 0 AND required_autonomy_level <= 4)
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_operation_playbooks_tenant
ON saas_ai_operation_playbooks (tenant_id, enabled, category, risk_level);

CREATE TABLE IF NOT EXISTS saas_ai_operation_anomalies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    anomaly_type TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'autonomous_operations',
    entity_type TEXT NOT NULL DEFAULT 'tenant',
    entity_id TEXT NOT NULL DEFAULT '',
    severity TEXT NOT NULL DEFAULT 'info',
    confidence NUMERIC(8,4) NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'open',
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    recommended_playbook_key TEXT NOT NULL DEFAULT '',
    first_seen_at TIMESTAMP NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMP NOT NULL DEFAULT NOW(),
    occurrence_count INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_saas_ai_operation_anomalies_open
ON saas_ai_operation_anomalies (tenant_id, anomaly_type, entity_type, entity_id)
WHERE status = 'open';

CREATE INDEX IF NOT EXISTS idx_saas_ai_operation_anomalies_tenant_status
ON saas_ai_operation_anomalies (tenant_id, status, severity, last_seen_at DESC);

CREATE TABLE IF NOT EXISTS saas_ai_operation_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    anomaly_id UUID NULL REFERENCES saas_ai_operation_anomalies(id) ON DELETE SET NULL,
    recommendation_id UUID NULL REFERENCES saas_intelligence_recommendations(id) ON DELETE SET NULL,
    playbook_key TEXT NOT NULL DEFAULT '',
    action_type TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    risk_level TEXT NOT NULL DEFAULT 'medium',
    status TEXT NOT NULL DEFAULT 'suggested',
    approval_required BOOLEAN NOT NULL DEFAULT TRUE,
    autonomy_level INTEGER NOT NULL DEFAULT 0,
    confidence NUMERIC(8,4) NOT NULL DEFAULT 0,
    input_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    rollback_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    approved_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    approved_at TIMESTAMP NULL,
    executed_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_saas_ai_operation_actions_level CHECK (autonomy_level >= 0 AND autonomy_level <= 4)
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_operation_actions_tenant_status
ON saas_ai_operation_actions (tenant_id, status, risk_level, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_ai_operation_actions_anomaly
ON saas_ai_operation_actions (tenant_id, anomaly_id, created_at DESC);

CREATE TABLE IF NOT EXISTS saas_ai_operation_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    report_type TEXT NOT NULL,
    period_key TEXT NOT NULL DEFAULT 'latest',
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    score NUMERIC(8,4) NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'open',
    findings_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    recommendations_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, report_type, period_key)
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_operation_reports_tenant
ON saas_ai_operation_reports (tenant_id, report_type, updated_at DESC);

UPDATE saas_plan_limits
SET feature_flags_json = COALESCE(feature_flags_json, '{}'::jsonb)
    || jsonb_build_object(
        'autonomous_operations', FALSE,
        'ai_self_healing', FALSE,
        'ai_control_center', FALSE
    ),
    updated_at = NOW();
