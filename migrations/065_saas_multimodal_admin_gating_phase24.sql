-- 065_saas_multimodal_admin_gating_phase24.sql
-- Phase 24.8 Admin & Premium Gating control-plane for plan quotas,
-- tenant grants, provider availability and cost policy metadata.

CREATE TABLE IF NOT EXISTS saas_intelligence_plan_feature_limits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_code TEXT NOT NULL REFERENCES saas_plan_limits(plan_code) ON DELETE CASCADE,
    feature_key TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    mode TEXT NOT NULL DEFAULT 'disabled',
    quota_monthly INTEGER NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '',
    updated_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (plan_code, feature_key)
);

CREATE INDEX IF NOT EXISTS idx_saas_intelligence_plan_feature_limits_plan
ON saas_intelligence_plan_feature_limits (plan_code, feature_key);

CREATE TABLE IF NOT EXISTS saas_ai_provider_policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scope_type TEXT NOT NULL DEFAULT 'global',
    scope_id TEXT NOT NULL DEFAULT '',
    provider_category TEXT NOT NULL DEFAULT 'ai',
    provider_code TEXT NOT NULL,
    model_id TEXT NOT NULL DEFAULT '',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    input_cost_cents_per_1k NUMERIC(18,6) NOT NULL DEFAULT 0,
    output_cost_cents_per_1k NUMERIC(18,6) NOT NULL DEFAULT 0,
    request_cost_cents NUMERIC(18,6) NOT NULL DEFAULT 0,
    monthly_request_quota INTEGER NOT NULL DEFAULT 0,
    monthly_cost_limit_cents INTEGER NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'USD',
    notes TEXT NOT NULL DEFAULT '',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (scope_type, scope_id, provider_category, provider_code, model_id)
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_provider_policies_lookup
ON saas_ai_provider_policies (provider_category, provider_code, model_id, scope_type, scope_id);

INSERT INTO saas_ai_provider_policies (
    scope_type, scope_id, provider_category, provider_code, model_id,
    enabled, metadata_json, notes, updated_at
)
VALUES
    ('global', '', 'ai', 'google', '', TRUE, '{"phase":"24.8","pricing":"admin_config_required"}'::jsonb, 'Global default allow; configure cost policy before commercial cost reporting.', NOW()),
    ('global', '', 'ai', 'groq', '', TRUE, '{"phase":"24.8","pricing":"admin_config_required"}'::jsonb, 'Global default allow; configure cost policy before commercial cost reporting.', NOW()),
    ('global', '', 'ai', 'mistral', '', TRUE, '{"phase":"24.8","pricing":"admin_config_required"}'::jsonb, 'Global default allow; configure cost policy before commercial cost reporting.', NOW()),
    ('global', '', 'ai', 'openrouter', '', TRUE, '{"phase":"24.8","pricing":"admin_config_required"}'::jsonb, 'Global default allow; configure cost policy before commercial cost reporting.', NOW()),
    ('global', '', 'ai', 'kimi', '', TRUE, '{"phase":"24.8","pricing":"admin_config_required"}'::jsonb, 'Global default allow; configure cost policy before commercial cost reporting.', NOW()),
    ('global', '', 'search', 'tavily', '', TRUE, '{"phase":"24.8","pricing":"admin_config_required"}'::jsonb, 'Global default allow; configure per-request cost policy when pricing is approved.', NOW()),
    ('global', '', 'search', 'brave_search', '', TRUE, '{"phase":"24.8","pricing":"admin_config_required"}'::jsonb, 'Global default allow; configure per-request cost policy when pricing is approved.', NOW()),
    ('global', '', 'search', 'serpapi', '', TRUE, '{"phase":"24.8","pricing":"admin_config_required"}'::jsonb, 'Global default allow; configure per-request cost policy when pricing is approved.', NOW())
ON CONFLICT (scope_type, scope_id, provider_category, provider_code, model_id)
DO UPDATE SET
    enabled = saas_ai_provider_policies.enabled,
    metadata_json = saas_ai_provider_policies.metadata_json || EXCLUDED.metadata_json,
    updated_at = NOW();
