-- 053_saas_ai_platform_ecosystem_phase11.sql
-- Phase 11: AI Platform Ecosystem control-plane for marketplace, plugins, SDK, tools and tenant AI apps.

CREATE TABLE IF NOT EXISTS saas_ai_marketplace_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    item_key TEXT NOT NULL UNIQUE,
    item_type TEXT NOT NULL DEFAULT 'agent_template',
    category TEXT NOT NULL DEFAULT 'general',
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    publisher TEXT NOT NULL DEFAULT 'Scentra',
    version TEXT NOT NULL DEFAULT '1.0.0',
    status TEXT NOT NULL DEFAULT 'published',
    premium_required BOOLEAN NOT NULL DEFAULT TRUE,
    required_feature_key TEXT NOT NULL DEFAULT 'ai_marketplace',
    manifest_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    permissions_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    install_schema_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    tags_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_by_tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_marketplace_items_type_status
ON saas_ai_marketplace_items (item_type, status, category);

CREATE INDEX IF NOT EXISTS idx_saas_ai_marketplace_items_feature
ON saas_ai_marketplace_items (required_feature_key, premium_required, status);

CREATE TABLE IF NOT EXISTS saas_ai_marketplace_installations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES saas_ai_marketplace_items(id) ON DELETE CASCADE,
    installed_version TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'installed',
    config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    installation_result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    installed_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    enabled_at TIMESTAMP NULL,
    installed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, item_id)
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_marketplace_installations_tenant
ON saas_ai_marketplace_installations (tenant_id, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_ai_plugins (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    plugin_key TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'ai',
    status TEXT NOT NULL DEFAULT 'draft',
    version TEXT NOT NULL DEFAULT '1.0.0',
    runtime_type TEXT NOT NULL DEFAULT 'manifest',
    sandbox_mode TEXT NOT NULL DEFAULT 'metadata_only',
    permissions_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    manifest_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    approval_status TEXT NOT NULL DEFAULT 'pending',
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, plugin_key)
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_plugins_tenant_status
ON saas_ai_plugins (tenant_id, status, category, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_ai_tool_registry (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    tool_key TEXT NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'ai',
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'enabled',
    risk_level TEXT NOT NULL DEFAULT 'medium',
    runtime_type TEXT NOT NULL DEFAULT 'internal',
    handler_ref TEXT NOT NULL DEFAULT '',
    input_schema_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_schema_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    permission_scopes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_saas_ai_tool_registry_system_key
ON saas_ai_tool_registry (tool_key)
WHERE tenant_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_saas_ai_tool_registry_tenant_key
ON saas_ai_tool_registry (tenant_id, tool_key)
WHERE tenant_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_saas_ai_tool_registry_tenant_status
ON saas_ai_tool_registry (tenant_id, status, category, risk_level);

CREATE TABLE IF NOT EXISTS saas_ai_ecosystem_event_subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    subscriber_type TEXT NOT NULL DEFAULT 'plugin',
    subscriber_id TEXT NOT NULL DEFAULT '',
    event_type TEXT NOT NULL,
    target_type TEXT NOT NULL DEFAULT 'internal',
    target_ref TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'enabled',
    priority INTEGER NOT NULL DEFAULT 50,
    filters_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    retry_policy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, subscriber_type, subscriber_id, event_type, target_ref)
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_ecosystem_subscriptions_enabled
ON saas_ai_ecosystem_event_subscriptions (tenant_id, status, event_type, priority DESC);

CREATE TABLE IF NOT EXISTS saas_ai_developer_apps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    app_key TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    scopes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    webhook_url TEXT NOT NULL DEFAULT '',
    api_key_hash TEXT NOT NULL DEFAULT '',
    api_key_hint TEXT NOT NULL DEFAULT '',
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    last_used_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, app_key)
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_developer_apps_tenant_status
ON saas_ai_developer_apps (tenant_id, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_ai_external_integrations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    integration_key TEXT NOT NULL,
    provider_type TEXT NOT NULL DEFAULT 'crm',
    provider_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    auth_mode TEXT NOT NULL DEFAULT 'none',
    scopes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    health_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, integration_key)
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_external_integrations_tenant_status
ON saas_ai_external_integrations (tenant_id, status, provider_type);

CREATE TABLE IF NOT EXISTS saas_ai_apps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    app_key TEXT NOT NULL,
    name TEXT NOT NULL,
    app_type TEXT NOT NULL DEFAULT 'dashboard',
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    manifest_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    permissions_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    layout_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, app_key)
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_apps_tenant_status
ON saas_ai_apps (tenant_id, status, app_type);

CREATE TABLE IF NOT EXISTS saas_ai_ecosystem_traces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL DEFAULT '',
    event_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ok',
    duration_ms INTEGER NOT NULL DEFAULT 0,
    input_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_text TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_ecosystem_traces_tenant_time
ON saas_ai_ecosystem_traces (tenant_id, entity_type, event_type, created_at DESC);

CREATE TABLE IF NOT EXISTS saas_ai_ecosystem_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    metric_key TEXT NOT NULL,
    metric_value NUMERIC(18,4) NOT NULL DEFAULT 0,
    dimensions_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    period_key TEXT NOT NULL DEFAULT 'latest',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_ecosystem_metrics_tenant
ON saas_ai_ecosystem_metrics (tenant_id, metric_key, period_key, created_at DESC);

UPDATE saas_plan_limits
SET feature_flags_json = COALESCE(feature_flags_json, '{}'::jsonb)
    || jsonb_build_object(
        'ai_marketplace', FALSE,
        'ai_plugin_center', FALSE,
        'ai_developer_console', FALSE,
        'ai_tool_registry', FALSE,
        'ai_app_framework', FALSE
    ),
    updated_at = NOW();
