-- Phase 18: AI Workflow Composer
-- Tenant-scoped workflow design, simulation, approval and versioning.

CREATE TABLE IF NOT EXISTS saas_ai_workflow_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    template_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'general',
    industry_code TEXT NOT NULL DEFAULT 'general',
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'published',
    source TEXT NOT NULL DEFAULT 'scentra',
    required_feature_key TEXT NOT NULL DEFAULT 'workflow_composer_templates',
    graph_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    safety_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    tags_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_workflow_templates_status
    ON saas_ai_workflow_templates(status);
CREATE INDEX IF NOT EXISTS idx_saas_ai_workflow_templates_category
    ON saas_ai_workflow_templates(category);
CREATE INDEX IF NOT EXISTS idx_saas_ai_workflow_templates_industry
    ON saas_ai_workflow_templates(industry_code);

CREATE TABLE IF NOT EXISTS saas_ai_workflows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    category TEXT NOT NULL DEFAULT 'general',
    channel TEXT NOT NULL DEFAULT 'omnichannel',
    source_template_key TEXT,
    graph_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    preflight_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    simulation_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    version_number INTEGER NOT NULL DEFAULT 1,
    activation_mode TEXT NOT NULL DEFAULT 'composer_only',
    linked_trigger_id UUID REFERENCES saas_crm_triggers(id) ON DELETE SET NULL,
    linked_flow_id UUID REFERENCES saas_remarketing_flows(id) ON DELETE SET NULL,
    approval_status TEXT NOT NULL DEFAULT 'draft',
    approved_by_user_id UUID REFERENCES saas_users(id) ON DELETE SET NULL,
    approved_at TIMESTAMP,
    activated_at TIMESTAMP,
    created_by_user_id UUID REFERENCES saas_users(id) ON DELETE SET NULL,
    updated_by_user_id UUID REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_saas_ai_workflows_tenant_lower_name
    ON saas_ai_workflows(tenant_id, LOWER(name));
CREATE INDEX IF NOT EXISTS idx_saas_ai_workflows_tenant_status
    ON saas_ai_workflows(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_saas_ai_workflows_tenant_category
    ON saas_ai_workflows(tenant_id, category);

CREATE TABLE IF NOT EXISTS saas_ai_workflow_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    workflow_id UUID NOT NULL REFERENCES saas_ai_workflows(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    snapshot_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    change_reason TEXT NOT NULL DEFAULT '',
    created_by_user_id UUID REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, workflow_id, version_number)
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_workflow_versions_workflow
    ON saas_ai_workflow_versions(workflow_id, version_number DESC);

CREATE TABLE IF NOT EXISTS saas_ai_workflow_simulations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    workflow_id UUID REFERENCES saas_ai_workflows(id) ON DELETE CASCADE,
    scenario_key TEXT NOT NULL DEFAULT 'manual',
    status TEXT NOT NULL DEFAULT 'completed',
    input_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by_user_id UUID REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_workflow_simulations_workflow
    ON saas_ai_workflow_simulations(workflow_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_saas_ai_workflow_simulations_tenant
    ON saas_ai_workflow_simulations(tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS saas_ai_workflow_approvals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    workflow_id UUID NOT NULL REFERENCES saas_ai_workflows(id) ON DELETE CASCADE,
    requested_by_user_id UUID REFERENCES saas_users(id) ON DELETE SET NULL,
    reviewed_by_user_id UUID REFERENCES saas_users(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    risk_level TEXT NOT NULL DEFAULT 'medium',
    request_note TEXT NOT NULL DEFAULT '',
    review_note TEXT NOT NULL DEFAULT '',
    approval_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    reviewed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_workflow_approvals_workflow
    ON saas_ai_workflow_approvals(workflow_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_saas_ai_workflow_approvals_tenant_status
    ON saas_ai_workflow_approvals(tenant_id, status);

CREATE TABLE IF NOT EXISTS saas_ai_workflow_materializations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    workflow_id UUID NOT NULL REFERENCES saas_ai_workflows(id) ON DELETE CASCADE,
    target_type TEXT NOT NULL DEFAULT 'composer_only',
    target_id TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by_user_id UUID REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_workflow_materializations_workflow
    ON saas_ai_workflow_materializations(workflow_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_saas_ai_workflow_materializations_tenant
    ON saas_ai_workflow_materializations(tenant_id, target_type);

UPDATE saas_plan_limits
SET feature_flags_json = COALESCE(feature_flags_json, '{}'::jsonb)
    || jsonb_build_object(
        'ai_workflow_composer', COALESCE((feature_flags_json ->> 'ai_workflow_composer')::boolean, false),
        'workflow_composer_templates', COALESCE((feature_flags_json ->> 'workflow_composer_templates')::boolean, false)
    ),
    updated_at = NOW();
