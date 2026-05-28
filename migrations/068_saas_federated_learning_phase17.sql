-- 068_saas_federated_learning_phase17.sql
-- Phase 17: Federated Learning & Global Intelligence.
-- Privacy-safe control plane only: tenants submit aggregate/statistical model
-- update packages. No raw messages, conversations, media, prompts, secrets or
-- private customer content are shared across tenants.

CREATE TABLE IF NOT EXISTS saas_federated_learning_policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    opt_in_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    auto_participation_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    privacy_mode TEXT NOT NULL DEFAULT 'aggregate_only',
    min_local_samples INTEGER NOT NULL DEFAULT 25,
    min_cohort_tenants INTEGER NOT NULL DEFAULT 3,
    allowed_task_types_json JSONB NOT NULL DEFAULT '["lead_scoring","churn_prediction","smart_remarketing","operational_anomaly"]'::jsonb,
    differential_privacy_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    noise_multiplier NUMERIC(12,6) NOT NULL DEFAULT 0,
    clipping_norm NUMERIC(12,6) NOT NULL DEFAULT 1,
    share_model_metrics BOOLEAN NOT NULL DEFAULT TRUE,
    share_feature_importance BOOLEAN NOT NULL DEFAULT TRUE,
    settings_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id)
);

CREATE INDEX IF NOT EXISTS idx_saas_federated_policies_tenant
ON saas_federated_learning_policies (tenant_id, opt_in_enabled, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_federated_learning_rounds (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    round_key TEXT NOT NULL,
    task_type TEXT NOT NULL,
    model_key TEXT NOT NULL DEFAULT 'scentra_global_v1',
    model_version TEXT NOT NULL DEFAULT 'v1',
    industry_code TEXT NOT NULL DEFAULT 'general',
    cohort_key TEXT NOT NULL DEFAULT 'industry',
    window_key TEXT NOT NULL DEFAULT '90d',
    status TEXT NOT NULL DEFAULT 'open',
    min_participants INTEGER NOT NULL DEFAULT 3,
    min_total_samples INTEGER NOT NULL DEFAULT 100,
    aggregation_strategy TEXT NOT NULL DEFAULT 'weighted_average',
    privacy_budget_epsilon NUMERIC(12,6) NOT NULL DEFAULT 0,
    created_by_tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE SET NULL,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    opened_at TIMESTAMP NOT NULL DEFAULT NOW(),
    closed_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (round_key)
);

CREATE INDEX IF NOT EXISTS idx_saas_federated_rounds_lookup
ON saas_federated_learning_rounds (industry_code, task_type, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_federated_learning_updates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    round_id UUID NOT NULL REFERENCES saas_federated_learning_rounds(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    update_key TEXT NOT NULL,
    task_type TEXT NOT NULL,
    model_key TEXT NOT NULL DEFAULT 'scentra_global_v1',
    model_version TEXT NOT NULL DEFAULT 'v1',
    industry_code TEXT NOT NULL DEFAULT 'general',
    window_key TEXT NOT NULL DEFAULT '90d',
    sample_count INTEGER NOT NULL DEFAULT 0,
    metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    feature_stats_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    feature_importance_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    privacy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    update_hash TEXT NOT NULL DEFAULT '',
    quality_score NUMERIC(8,4) NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'submitted',
    submitted_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    submitted_at TIMESTAMP NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (round_id, tenant_id),
    UNIQUE (update_key)
);

CREATE INDEX IF NOT EXISTS idx_saas_federated_updates_round
ON saas_federated_learning_updates (round_id, status, submitted_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_federated_updates_tenant
ON saas_federated_learning_updates (tenant_id, task_type, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_federated_learning_aggregates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    round_id UUID NOT NULL REFERENCES saas_federated_learning_rounds(id) ON DELETE CASCADE,
    task_type TEXT NOT NULL,
    model_key TEXT NOT NULL DEFAULT 'scentra_global_v1',
    model_version TEXT NOT NULL DEFAULT 'v1',
    industry_code TEXT NOT NULL DEFAULT 'general',
    window_key TEXT NOT NULL DEFAULT '90d',
    participant_count INTEGER NOT NULL DEFAULT 0,
    total_samples INTEGER NOT NULL DEFAULT 0,
    aggregate_metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    aggregate_feature_importance_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    benchmark_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    global_signal_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    privacy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'candidate',
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    computed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (round_id)
);

CREATE INDEX IF NOT EXISTS idx_saas_federated_aggregates_lookup
ON saas_federated_learning_aggregates (industry_code, task_type, status, computed_at DESC);

CREATE TABLE IF NOT EXISTS saas_global_intelligence_signals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_key TEXT NOT NULL,
    signal_type TEXT NOT NULL DEFAULT 'federated_aggregate',
    industry_code TEXT NOT NULL DEFAULT 'general',
    task_type TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    confidence NUMERIC(8,4) NOT NULL DEFAULT 0,
    aggregate_id UUID NULL REFERENCES saas_federated_learning_aggregates(id) ON DELETE SET NULL,
    source_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    privacy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (signal_key)
);

CREATE INDEX IF NOT EXISTS idx_saas_global_intelligence_signals_lookup
ON saas_global_intelligence_signals (industry_code, task_type, status, updated_at DESC);

UPDATE saas_plan_limits
SET feature_flags_json =
    '{
      "federated_learning": false,
      "federated_model_updates": false,
      "privacy_safe_model_aggregation": false,
      "global_intelligence": false,
      "federated_benchmarking": false
    }'::jsonb || COALESCE(feature_flags_json, '{}'::jsonb),
    updated_at = NOW();
