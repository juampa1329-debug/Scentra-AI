-- 066_saas_revenue_memory_network_phase19_20.sql
-- Phase 19 Autonomous Revenue Engine and Phase 20 AI Enterprise Memory Network.
-- This migration adds supervised control-plane records only. It does not send
-- messages, charge customers, mutate CRM, activate campaigns/workflows or share
-- private tenant content across tenants.

CREATE TABLE IF NOT EXISTS saas_ai_revenue_policies (
    tenant_id UUID PRIMARY KEY REFERENCES saas_tenants(id) ON DELETE CASCADE,
    autonomy_level INTEGER NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'USD',
    revenue_goal_cents BIGINT NOT NULL DEFAULT 0,
    approval_required_min_value_cents BIGINT NOT NULL DEFAULT 0,
    max_monthly_revenue_actions INTEGER NOT NULL DEFAULT 0,
    auto_execute_low_risk BOOLEAN NOT NULL DEFAULT FALSE,
    allowed_action_types_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    settings_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS saas_ai_revenue_opportunities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    opportunity_key TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT '',
    source_id TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'conversion',
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    estimated_value_cents BIGINT NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'USD',
    confidence NUMERIC(8,4) NOT NULL DEFAULT 0,
    priority_score NUMERIC(8,4) NOT NULL DEFAULT 0,
    stage TEXT NOT NULL DEFAULT 'detected',
    status TEXT NOT NULL DEFAULT 'suggested',
    recommended_action_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    approval_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    execution_result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    approved_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    executed_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    approved_at TIMESTAMP NULL,
    executed_at TIMESTAMP NULL,
    expires_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, opportunity_key)
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_revenue_opportunities_tenant_status
ON saas_ai_revenue_opportunities (tenant_id, status, priority_score DESC, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_ai_revenue_opportunities_source
ON saas_ai_revenue_opportunities (tenant_id, source_type, source_id, category);

CREATE TABLE IF NOT EXISTS saas_ai_revenue_forecasts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    period_key TEXT NOT NULL DEFAULT 'latest',
    forecast_type TEXT NOT NULL DEFAULT 'pipeline',
    forecast_value_cents BIGINT NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'USD',
    confidence NUMERIC(8,4) NOT NULL DEFAULT 0,
    scenario_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, period_key, forecast_type)
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_revenue_forecasts_tenant
ON saas_ai_revenue_forecasts (tenant_id, period_key, forecast_type);

CREATE TABLE IF NOT EXISTS saas_ai_revenue_experiments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    experiment_key TEXT NOT NULL,
    title TEXT NOT NULL,
    hypothesis TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    target_metric TEXT NOT NULL DEFAULT 'conversion_rate',
    variants_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    guardrails_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, experiment_key)
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_revenue_experiments_tenant_status
ON saas_ai_revenue_experiments (tenant_id, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_ai_revenue_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    report_key TEXT NOT NULL,
    report_type TEXT NOT NULL DEFAULT 'analysis',
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    score NUMERIC(8,4) NOT NULL DEFAULT 0,
    findings_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    recommendations_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, report_key)
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_revenue_reports_tenant
ON saas_ai_revenue_reports (tenant_id, report_type, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_enterprise_memory_policies (
    tenant_id UUID PRIMARY KEY REFERENCES saas_tenants(id) ON DELETE CASCADE,
    privacy_mode TEXT NOT NULL DEFAULT 'tenant_private',
    retention_days INTEGER NOT NULL DEFAULT 365,
    auto_capture_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    require_review_for_customer_content BOOLEAN NOT NULL DEFAULT TRUE,
    allow_cross_agent_retrieval BOOLEAN NOT NULL DEFAULT TRUE,
    allowed_scopes_json JSONB NOT NULL DEFAULT '["tenant","agent","customer","knowledge","workflow"]'::jsonb,
    settings_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS saas_enterprise_memory_nodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    node_key TEXT NOT NULL,
    memory_scope TEXT NOT NULL DEFAULT 'tenant',
    node_type TEXT NOT NULL DEFAULT 'fact',
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL DEFAULT '',
    privacy_level TEXT NOT NULL DEFAULT 'tenant_private',
    sensitivity TEXT NOT NULL DEFAULT 'normal',
    confidence NUMERIC(8,4) NOT NULL DEFAULT 0,
    quality_score NUMERIC(8,4) NOT NULL DEFAULT 0,
    source_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    tags_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    review_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'candidate',
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    reviewed_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    reviewed_at TIMESTAMP NULL,
    expires_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, node_key)
);

CREATE INDEX IF NOT EXISTS idx_saas_enterprise_memory_nodes_tenant_status
ON saas_enterprise_memory_nodes (tenant_id, status, memory_scope, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_enterprise_memory_nodes_type
ON saas_enterprise_memory_nodes (tenant_id, node_type, quality_score DESC, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_enterprise_memory_edges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    source_node_id UUID NOT NULL REFERENCES saas_enterprise_memory_nodes(id) ON DELETE CASCADE,
    target_node_id UUID NOT NULL REFERENCES saas_enterprise_memory_nodes(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL DEFAULT 'related_to',
    weight NUMERIC(8,4) NOT NULL DEFAULT 1,
    evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, source_node_id, target_node_id, relation_type)
);

CREATE INDEX IF NOT EXISTS idx_saas_enterprise_memory_edges_tenant_source
ON saas_enterprise_memory_edges (tenant_id, source_node_id, relation_type);

CREATE TABLE IF NOT EXISTS saas_enterprise_memory_sync_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    sync_type TEXT NOT NULL DEFAULT 'manual',
    status TEXT NOT NULL DEFAULT 'completed',
    source_counts_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    nodes_scanned INTEGER NOT NULL DEFAULT 0,
    nodes_created INTEGER NOT NULL DEFAULT 0,
    nodes_updated INTEGER NOT NULL DEFAULT 0,
    edges_created INTEGER NOT NULL DEFAULT 0,
    findings_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    started_at TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP NULL,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_enterprise_memory_sync_runs_tenant
ON saas_enterprise_memory_sync_runs (tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS saas_enterprise_memory_access_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    node_id UUID NULL REFERENCES saas_enterprise_memory_nodes(id) ON DELETE SET NULL,
    accessor_type TEXT NOT NULL DEFAULT 'user',
    accessor_id TEXT NOT NULL DEFAULT '',
    purpose TEXT NOT NULL DEFAULT '',
    result_status TEXT NOT NULL DEFAULT 'allowed',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_enterprise_memory_access_logs_tenant
ON saas_enterprise_memory_access_logs (tenant_id, created_at DESC);

UPDATE saas_plan_limits
SET feature_flags_json =
    '{
      "autonomous_revenue_engine": false,
      "revenue_opportunity_detection": false,
      "revenue_forecasting": false,
      "revenue_playbooks": false,
      "revenue_experiments": false,
      "enterprise_memory_network": false,
      "memory_graph": false,
      "memory_governance": false,
      "cross_agent_memory_routing": false,
      "memory_quality_scoring": false
    }'::jsonb || COALESCE(feature_flags_json, '{}'::jsonb),
    updated_at = NOW();
