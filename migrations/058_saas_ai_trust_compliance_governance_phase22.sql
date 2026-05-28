-- 058_saas_ai_trust_compliance_governance_phase22.sql
-- Phase 22: AI Trust, Compliance & Governance control-plane.
-- This migration is tenant-scoped, idempotent and does not execute AI, CRM,
-- Meta, workflow, billing or plugin side effects.

CREATE TABLE IF NOT EXISTS saas_ai_governance_policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    policy_key TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'enabled',
    risk_tier TEXT NOT NULL DEFAULT 'standard',
    enforcement_mode TEXT NOT NULL DEFAULT 'monitor',
    applies_to_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    rules_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    updated_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, policy_key)
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_governance_policies_tenant_status
ON saas_ai_governance_policies (tenant_id, status, risk_tier, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_ai_governance_policy_attestations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    policy_id UUID NOT NULL REFERENCES saas_ai_governance_policies(id) ON DELETE CASCADE,
    attestation_type TEXT NOT NULL DEFAULT 'human_review',
    status TEXT NOT NULL DEFAULT 'attested',
    signed_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    signed_at TIMESTAMP NULL,
    evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    notes TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_policy_attestations_tenant_policy
ON saas_ai_governance_policy_attestations (tenant_id, policy_id, created_at DESC);

CREATE TABLE IF NOT EXISTS saas_ai_risk_assessments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    risk_level TEXT NOT NULL DEFAULT 'medium',
    status TEXT NOT NULL DEFAULT 'open',
    score NUMERIC(8,4) NOT NULL DEFAULT 0,
    findings_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    mitigations_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    reviewed_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    reviewed_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_risk_assessments_tenant_status
ON saas_ai_risk_assessments (tenant_id, status, risk_level, updated_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS ux_saas_ai_risk_assessments_open_entity
ON saas_ai_risk_assessments (tenant_id, entity_type, entity_id)
WHERE status = 'open';

CREATE TABLE IF NOT EXISTS saas_ai_model_cards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    model_key TEXT NOT NULL,
    provider_key TEXT NOT NULL DEFAULT '',
    task_type TEXT NOT NULL DEFAULT '',
    version TEXT NOT NULL DEFAULT 'v1',
    status TEXT NOT NULL DEFAULT 'draft',
    intended_use TEXT NOT NULL DEFAULT '',
    limitations TEXT NOT NULL DEFAULT '',
    training_data_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    evaluation_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    rollout_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    compliance_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    owner_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, model_key)
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_model_cards_tenant_status
ON saas_ai_model_cards (tenant_id, status, task_type, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_ai_governance_incidents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    incident_type TEXT NOT NULL DEFAULT 'ai_governance',
    severity TEXT NOT NULL DEFAULT 'medium',
    status TEXT NOT NULL DEFAULT 'open',
    entity_type TEXT NOT NULL DEFAULT '',
    entity_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    remediation_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    opened_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    closed_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    closed_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_governance_incidents_tenant_status
ON saas_ai_governance_incidents (tenant_id, status, severity, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_ai_governance_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    report_type TEXT NOT NULL DEFAULT 'trust_summary',
    period_key TEXT NOT NULL DEFAULT 'latest',
    status TEXT NOT NULL DEFAULT 'completed',
    summary TEXT NOT NULL DEFAULT '',
    findings_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, report_type, period_key)
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_governance_reports_tenant_type
ON saas_ai_governance_reports (tenant_id, report_type, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_ai_governance_audits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT '',
    entity_id TEXT NOT NULL DEFAULT '',
    severity TEXT NOT NULL DEFAULT 'info',
    actor_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    summary TEXT NOT NULL DEFAULT '',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_governance_audits_tenant_time
ON saas_ai_governance_audits (tenant_id, created_at DESC);

UPDATE saas_plan_limits
SET feature_flags_json = COALESCE(feature_flags_json, '{}'::jsonb)
    || jsonb_build_object(
        'ai_trust_center', COALESCE((feature_flags_json ->> 'ai_trust_center')::boolean, false),
        'ai_governance_policies', COALESCE((feature_flags_json ->> 'ai_governance_policies')::boolean, false),
        'ai_risk_assessments', COALESCE((feature_flags_json ->> 'ai_risk_assessments')::boolean, false),
        'ai_model_cards', COALESCE((feature_flags_json ->> 'ai_model_cards')::boolean, false),
        'ai_compliance_reports', COALESCE((feature_flags_json ->> 'ai_compliance_reports')::boolean, false),
        'ai_audit_exports', COALESCE((feature_flags_json ->> 'ai_audit_exports')::boolean, false)
    );
