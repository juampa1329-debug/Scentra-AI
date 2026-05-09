-- 010_saas_campaigns_core.sql
-- Base SaaS para plantillas, segmentos, campanas CRM, triggers y flows de remarketing.

CREATE TABLE IF NOT EXISTS saas_message_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'whatsapp',
    category TEXT NOT NULL DEFAULT 'general',
    status TEXT NOT NULL DEFAULT 'draft',
    body TEXT NOT NULL DEFAULT '',
    variables_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    blocks_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    params_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_saas_templates_tenant_channel_lower_name
ON saas_message_templates (tenant_id, channel, lower(name));

CREATE INDEX IF NOT EXISTS idx_saas_templates_tenant_status
ON saas_message_templates (tenant_id, channel, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_segments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    filters_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    audience_count INTEGER NOT NULL DEFAULT 0,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_saas_segments_tenant_lower_name
ON saas_segments (tenant_id, lower(name));

CREATE TABLE IF NOT EXISTS saas_campaigns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'whatsapp',
    objective TEXT NOT NULL DEFAULT '',
    template_id UUID NULL REFERENCES saas_message_templates(id) ON DELETE SET NULL,
    segment_id UUID NULL REFERENCES saas_segments(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    scheduled_at TIMESTAMP NULL,
    audience_count INTEGER NOT NULL DEFAULT 0,
    sent_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_campaigns_tenant_status
ON saas_campaigns (tenant_id, status, scheduled_at, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_crm_triggers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'whatsapp',
    event_type TEXT NOT NULL DEFAULT 'message_in',
    trigger_type TEXT NOT NULL DEFAULT 'message_flow',
    conditions_json JSONB NOT NULL DEFAULT '{"conditions":[]}'::jsonb,
    actions_json JSONB NOT NULL DEFAULT '{"actions":[]}'::jsonb,
    priority INTEGER NOT NULL DEFAULT 100,
    cooldown_minutes INTEGER NOT NULL DEFAULT 60,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_saas_triggers_tenant_channel_lower_name
ON saas_crm_triggers (tenant_id, channel, lower(name));

CREATE INDEX IF NOT EXISTS idx_saas_triggers_tenant_active
ON saas_crm_triggers (tenant_id, channel, is_active, priority);

CREATE TABLE IF NOT EXISTS saas_remarketing_flows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL DEFAULT 'whatsapp',
    status TEXT NOT NULL DEFAULT 'draft',
    entry_rules_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    exit_rules_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    steps_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_saas_flows_tenant_channel_lower_name
ON saas_remarketing_flows (tenant_id, channel, lower(name));

CREATE INDEX IF NOT EXISTS idx_saas_flows_tenant_status
ON saas_remarketing_flows (tenant_id, channel, status, updated_at DESC);
