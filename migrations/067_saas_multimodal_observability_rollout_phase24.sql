-- 067_saas_multimodal_observability_rollout_phase24.sql
-- Phase 24.9 Observability and Phase 24.10 Safe Rollout for Voice &
-- Multimodal Intelligence. This is a control-plane/observability migration:
-- it does not send messages, mutate CRM, call providers, train models, or
-- enable runtime enforcement unless explicit tenant policy is enabled.

CREATE TABLE IF NOT EXISTS saas_multimodal_observability_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    window_key TEXT NOT NULL DEFAULT '30d',
    modality TEXT NOT NULL DEFAULT 'all',
    provider_code TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'ok',
    request_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    cached_count INTEGER NOT NULL DEFAULT 0,
    avg_latency_ms NUMERIC(18,4) NOT NULL DEFAULT 0,
    p95_latency_ms NUMERIC(18,4) NOT NULL DEFAULT 0,
    estimated_cost_cents NUMERIC(18,6) NOT NULL DEFAULT 0,
    avg_quality_score NUMERIC(8,4) NOT NULL DEFAULT 0,
    source_count INTEGER NOT NULL DEFAULT 0,
    approved_source_count INTEGER NOT NULL DEFAULT 0,
    blocked_source_count INTEGER NOT NULL DEFAULT 0,
    metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    cost_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    quality_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    sources_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    computed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, window_key, modality, provider_code)
);

CREATE INDEX IF NOT EXISTS idx_saas_multimodal_obs_snapshots_tenant
ON saas_multimodal_observability_snapshots (tenant_id, window_key, modality, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_multimodal_rollout_policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    feature_key TEXT NOT NULL DEFAULT 'multimodal_safe_rollout',
    modality TEXT NOT NULL DEFAULT 'all',
    provider_code TEXT NOT NULL DEFAULT '',
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    mode TEXT NOT NULL DEFAULT 'off',
    demo_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    canary_percent INTEGER NOT NULL DEFAULT 0,
    max_error_rate NUMERIC(8,4) NOT NULL DEFAULT 0,
    max_latency_p95_ms INTEGER NOT NULL DEFAULT 0,
    min_quality_score NUMERIC(8,4) NOT NULL DEFAULT 0,
    monthly_cost_limit_cents INTEGER NOT NULL DEFAULT 0,
    allowed_roles_json JSONB NOT NULL DEFAULT '["owner","admin","supervisor"]'::jsonb,
    settings_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, feature_key, modality, provider_code)
);

CREATE INDEX IF NOT EXISTS idx_saas_multimodal_rollout_policies_tenant
ON saas_multimodal_rollout_policies (tenant_id, feature_key, modality, provider_code);

CREATE TABLE IF NOT EXISTS saas_multimodal_rollout_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    policy_id UUID NULL REFERENCES saas_multimodal_rollout_policies(id) ON DELETE SET NULL,
    feature_key TEXT NOT NULL DEFAULT '',
    modality TEXT NOT NULL DEFAULT '',
    provider_code TEXT NOT NULL DEFAULT '',
    subject_type TEXT NOT NULL DEFAULT '',
    subject_id TEXT NOT NULL DEFAULT '',
    decision TEXT NOT NULL DEFAULT 'allow',
    mode TEXT NOT NULL DEFAULT 'off',
    canary_bucket INTEGER NOT NULL DEFAULT 0,
    canary_percent INTEGER NOT NULL DEFAULT 0,
    reason TEXT NOT NULL DEFAULT '',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_multimodal_rollout_events_tenant
ON saas_multimodal_rollout_events (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_multimodal_rollout_events_policy
ON saas_multimodal_rollout_events (policy_id, created_at DESC)
WHERE policy_id IS NOT NULL;

UPDATE saas_plan_limits
SET feature_flags_json =
    '{
      "multimodal_observability": false,
      "multimodal_cost_observability": false,
      "multimodal_quality_monitoring": false,
      "multimodal_safe_rollout": false,
      "multimodal_canary": false
    }'::jsonb || COALESCE(feature_flags_json, '{}'::jsonb),
    updated_at = NOW();
