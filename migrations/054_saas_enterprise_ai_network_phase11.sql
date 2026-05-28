-- 054_saas_enterprise_ai_network_phase11.sql
-- Phase 11 closeout: privacy-safe Enterprise AI Network and Vertical Intelligence.

CREATE TABLE IF NOT EXISTS saas_ai_vertical_industry_models (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    industry_code TEXT NOT NULL DEFAULT 'general',
    prediction_type TEXT NOT NULL DEFAULT 'lead_scoring',
    model_key TEXT NOT NULL,
    model_version TEXT NOT NULL DEFAULT 'v1',
    routing_mode TEXT NOT NULL DEFAULT 'metadata_only',
    status TEXT NOT NULL DEFAULT 'active',
    feature_set_key TEXT NOT NULL DEFAULT '',
    required_feature_key TEXT NOT NULL DEFAULT 'industry_ai_models',
    model_metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (industry_code, prediction_type, model_key, model_version)
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_vertical_models_industry
ON saas_ai_vertical_industry_models (industry_code, prediction_type, status);

CREATE TABLE IF NOT EXISTS saas_ai_vertical_benchmarks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    industry_code TEXT NOT NULL DEFAULT 'general',
    cohort_key TEXT NOT NULL DEFAULT 'all',
    metric_key TEXT NOT NULL,
    period_key TEXT NOT NULL DEFAULT 'latest',
    sample_count INTEGER NOT NULL DEFAULT 0,
    average_value NUMERIC(18,6) NULL,
    p50_value NUMERIC(18,6) NULL,
    p75_value NUMERIC(18,6) NULL,
    p90_value NUMERIC(18,6) NULL,
    direction TEXT NOT NULL DEFAULT 'higher_better',
    privacy_level TEXT NOT NULL DEFAULT 'aggregated',
    source_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    computed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (industry_code, cohort_key, metric_key, period_key)
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_vertical_benchmarks_lookup
ON saas_ai_vertical_benchmarks (industry_code, period_key, metric_key);

CREATE TABLE IF NOT EXISTS saas_ai_vertical_tenant_benchmarks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    industry_code TEXT NOT NULL DEFAULT 'general',
    metric_key TEXT NOT NULL,
    period_key TEXT NOT NULL DEFAULT 'latest',
    tenant_value NUMERIC(18,6) NULL,
    benchmark_value NUMERIC(18,6) NULL,
    delta_percent NUMERIC(18,6) NULL,
    percentile NUMERIC(8,4) NULL,
    sample_count INTEGER NOT NULL DEFAULT 0,
    comparison_label TEXT NOT NULL DEFAULT 'insufficient_sample',
    recommendation_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    computed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, industry_code, metric_key, period_key)
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_vertical_tenant_benchmarks_tenant
ON saas_ai_vertical_tenant_benchmarks (tenant_id, industry_code, period_key, metric_key);

CREATE TABLE IF NOT EXISTS saas_ai_vertical_insights (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    industry_code TEXT NOT NULL DEFAULT 'general',
    insight_key TEXT NOT NULL,
    insight_type TEXT NOT NULL DEFAULT 'benchmark',
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    severity TEXT NOT NULL DEFAULT 'info',
    confidence NUMERIC(8,4) NOT NULL DEFAULT 0,
    kpi_key TEXT NOT NULL DEFAULT '',
    recommendation_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, insight_key)
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_vertical_insights_tenant
ON saas_ai_vertical_insights (tenant_id, status, severity, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_ai_vertical_playbooks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    industry_code TEXT NOT NULL DEFAULT 'general',
    playbook_key TEXT NOT NULL,
    playbook_type TEXT NOT NULL DEFAULT 'workflow',
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    kpi_key TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'published',
    premium_required BOOLEAN NOT NULL DEFAULT TRUE,
    required_feature_key TEXT NOT NULL DEFAULT 'ai_playbook_library',
    trigger_template_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    workflow_template_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    recommendation_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    safety_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (industry_code, playbook_key)
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_vertical_playbooks_industry
ON saas_ai_vertical_playbooks (industry_code, status, playbook_type);

CREATE TABLE IF NOT EXISTS saas_ai_knowledge_network (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    industry_code TEXT NOT NULL DEFAULT 'general',
    node_key TEXT NOT NULL,
    node_type TEXT NOT NULL DEFAULT 'best_practice',
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    tags_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    privacy_class TEXT NOT NULL DEFAULT 'aggregate_only',
    status TEXT NOT NULL DEFAULT 'published',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (industry_code, node_key)
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_knowledge_network_industry
ON saas_ai_knowledge_network (industry_code, node_type, status);

CREATE TABLE IF NOT EXISTS saas_ai_network_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    industry_code TEXT NOT NULL DEFAULT 'general',
    metric_key TEXT NOT NULL,
    metric_value NUMERIC(18,6) NOT NULL DEFAULT 0,
    dimensions_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    period_key TEXT NOT NULL DEFAULT 'latest',
    privacy_level TEXT NOT NULL DEFAULT 'aggregate_only',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_network_metrics_lookup
ON saas_ai_network_metrics (tenant_id, industry_code, metric_key, period_key, created_at DESC);

UPDATE saas_plan_limits
SET feature_flags_json = jsonb_build_object(
        'enterprise_ai_network', FALSE,
        'vertical_ai_intelligence', FALSE,
        'industry_ai_models', FALSE,
        'benchmark_intelligence', FALSE,
        'cross_tenant_intelligence', FALSE,
        'vertical_ai_advisors', FALSE,
        'ai_playbook_library', FALSE
    ) || COALESCE(feature_flags_json, '{}'::jsonb),
    updated_at = NOW();
