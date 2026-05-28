-- 070_saas_crm_intelligence_schema_drift_repair.sql
-- Production schema-drift repair for databases where CRM, verticalization,
-- campaign or Intelligence migrations were marked applied before all runtime
-- tables/columns existed.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

ALTER TABLE saas_tenants
    ADD COLUMN IF NOT EXISTS industry_code TEXT NOT NULL DEFAULT 'general',
    ADD COLUMN IF NOT EXISTS vertical_pack_version INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS vertical_pack_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS vertical_pack_applied_at TIMESTAMP NULL;

UPDATE saas_tenants
SET industry_code = 'general'
WHERE industry_code IS NULL OR BTRIM(industry_code) = '';

CREATE INDEX IF NOT EXISTS idx_saas_tenants_industry_code
ON saas_tenants (industry_code, status, updated_at DESC);

ALTER TABLE saas_integrations
    ADD COLUMN IF NOT EXISTS secret_ref TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS last_sync_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT NOW();

ALTER TABLE saas_conversations
    ADD COLUMN IF NOT EXISTS first_name TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS last_name TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS city TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS customer_type TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS interests TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS payment_status TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS payment_reference TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS crm_stage TEXT NOT NULL DEFAULT 'contactado',
    ADD COLUMN IF NOT EXISTS intent TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS profile_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS last_profiled_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS assigned_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS priority TEXT NOT NULL DEFAULT 'normal',
    ADD COLUMN IF NOT EXISTS sla_due_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS first_response_due_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS lead_score INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS lead_temperature TEXT NOT NULL DEFAULT 'cold',
    ADD COLUMN IF NOT EXISTS last_customer_message_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS last_agent_message_at TIMESTAMP NULL;

DO $$
BEGIN
    IF to_regclass('public.saas_ai_agents') IS NOT NULL THEN
        ALTER TABLE saas_conversations
            ADD COLUMN IF NOT EXISTS assigned_ai_agent_id UUID NULL REFERENCES saas_ai_agents(id) ON DELETE SET NULL,
            ADD COLUMN IF NOT EXISTS ai_owner_mode TEXT NOT NULL DEFAULT 'general',
            ADD COLUMN IF NOT EXISTS ai_owner_locked_at TIMESTAMP NULL;
    ELSE
        ALTER TABLE saas_conversations
            ADD COLUMN IF NOT EXISTS assigned_ai_agent_id UUID NULL,
            ADD COLUMN IF NOT EXISTS ai_owner_mode TEXT NOT NULL DEFAULT 'general',
            ADD COLUMN IF NOT EXISTS ai_owner_locked_at TIMESTAMP NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_saas_conversations_tenant_stage
ON saas_conversations (tenant_id, crm_stage, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_conversations_tenant_payment
ON saas_conversations (tenant_id, payment_status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_conversations_assignee
ON saas_conversations (tenant_id, assigned_user_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_conversations_sla
ON saas_conversations (tenant_id, sla_due_at)
WHERE sla_due_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_saas_conversations_score
ON saas_conversations (tenant_id, lead_score DESC, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_conversations_ai_agent
ON saas_conversations (tenant_id, assigned_ai_agent_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_labels (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    color TEXT NOT NULL DEFAULT '#5eead4',
    description TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'general',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_saas_labels_tenant_lower_name
ON saas_labels (tenant_id, lower(name));

CREATE INDEX IF NOT EXISTS idx_saas_labels_tenant_active
ON saas_labels (tenant_id, is_active, name);

CREATE TABLE IF NOT EXISTS saas_conversation_labels (
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL REFERENCES saas_conversations(id) ON DELETE CASCADE,
    label_id UUID NOT NULL REFERENCES saas_labels(id) ON DELETE CASCADE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, conversation_id, label_id)
);

CREATE INDEX IF NOT EXISTS idx_saas_conversation_labels_label
ON saas_conversation_labels (tenant_id, label_id);

CREATE TABLE IF NOT EXISTS saas_crm_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL REFERENCES saas_conversations(id) ON DELETE CASCADE,
    assigned_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    priority TEXT NOT NULL DEFAULT 'normal',
    due_at TIMESTAMP NULL,
    completed_at TIMESTAMP NULL,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_crm_tasks_tenant_status
ON saas_crm_tasks (tenant_id, status, due_at NULLS LAST, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_crm_tasks_conversation
ON saas_crm_tasks (tenant_id, conversation_id, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_message_status_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    conversation_id UUID NULL REFERENCES saas_conversations(id) ON DELETE CASCADE,
    message_id UUID NULL REFERENCES saas_messages(id) ON DELETE SET NULL,
    provider_message_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    error TEXT NOT NULL DEFAULT '',
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMP NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_message_status_events_conversation
ON saas_message_status_events (tenant_id, conversation_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_message_status_events_provider
ON saas_message_status_events (tenant_id, provider_message_id, occurred_at DESC);

CREATE TABLE IF NOT EXISTS saas_crm_custom_fields (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    field_key TEXT NOT NULL,
    label TEXT NOT NULL,
    field_type TEXT NOT NULL DEFAULT 'text',
    options_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_required BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    display_order INTEGER NOT NULL DEFAULT 100,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_saas_crm_custom_fields_tenant_key
ON saas_crm_custom_fields (tenant_id, field_key);

CREATE INDEX IF NOT EXISTS idx_saas_crm_custom_fields_tenant_active
ON saas_crm_custom_fields (tenant_id, is_active, display_order, label);

CREATE TABLE IF NOT EXISTS saas_crm_pipelines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    name TEXT NOT NULL DEFAULT 'Pipeline comercial',
    industry_code TEXT NOT NULL DEFAULT 'general',
    is_default BOOLEAN NOT NULL DEFAULT TRUE,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_saas_crm_pipelines_default
ON saas_crm_pipelines (tenant_id)
WHERE is_default = TRUE;

CREATE UNIQUE INDEX IF NOT EXISTS uniq_saas_crm_pipelines_tenant_lower_name
ON saas_crm_pipelines (tenant_id, lower(name));

CREATE TABLE IF NOT EXISTS saas_crm_pipeline_stages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    pipeline_id UUID NOT NULL REFERENCES saas_crm_pipelines(id) ON DELETE CASCADE,
    stage_key TEXT NOT NULL,
    label TEXT NOT NULL,
    probability INTEGER NOT NULL DEFAULT 0,
    display_order INTEGER NOT NULL DEFAULT 100,
    is_won BOOLEAN NOT NULL DEFAULT FALSE,
    is_lost BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_saas_crm_pipeline_stages_key
ON saas_crm_pipeline_stages (tenant_id, pipeline_id, stage_key);

CREATE INDEX IF NOT EXISTS idx_saas_crm_pipeline_stages_active
ON saas_crm_pipeline_stages (tenant_id, pipeline_id, is_active, display_order);

CREATE TABLE IF NOT EXISTS saas_crm_timeline_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL REFERENCES saas_conversations(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL DEFAULT 'crm_event',
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    actor_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMP NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_crm_timeline_conversation
ON saas_crm_timeline_events (tenant_id, conversation_id, occurred_at DESC);

CREATE TABLE IF NOT EXISTS saas_crm_merge_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    source_conversation_id UUID NULL REFERENCES saas_conversations(id) ON DELETE SET NULL,
    target_conversation_id UUID NULL REFERENCES saas_conversations(id) ON DELETE SET NULL,
    merged_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    reason TEXT NOT NULL DEFAULT '',
    source_snapshot_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    target_snapshot_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

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

ALTER TABLE saas_message_templates
    ADD COLUMN IF NOT EXISTS render_mode TEXT NOT NULL DEFAULT 'chat',
    ADD COLUMN IF NOT EXISTS template_scope TEXT NOT NULL DEFAULT 'crm',
    ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'internal';

CREATE UNIQUE INDEX IF NOT EXISTS uniq_saas_templates_tenant_channel_lower_name
ON saas_message_templates (tenant_id, channel, lower(name));

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

ALTER TABLE saas_crm_triggers
    ADD COLUMN IF NOT EXISTS flow_event TEXT NOT NULL DEFAULT 'received',
    ADD COLUMN IF NOT EXISTS assistant_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS assistant_message_type TEXT NOT NULL DEFAULT 'auto',
    ADD COLUMN IF NOT EXISTS block_ai BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS stop_on_match BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS only_when_no_takeover BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS last_run_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS version_number INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS revision_note TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS quiet_hours_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS ab_test_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS preflight_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS last_preflight_at TIMESTAMP NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uniq_saas_triggers_tenant_channel_lower_name
ON saas_crm_triggers (tenant_id, channel, lower(name));

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

ALTER TABLE saas_remarketing_flows
    ADD COLUMN IF NOT EXISTS version_number INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS quiet_hours_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS ab_test_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS preflight_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS last_preflight_at TIMESTAMP NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uniq_saas_flows_tenant_channel_lower_name
ON saas_remarketing_flows (tenant_id, channel, lower(name));

CREATE TABLE IF NOT EXISTS saas_campaign_quiet_hours (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    channel TEXT NOT NULL DEFAULT 'all',
    entity_type TEXT NOT NULL DEFAULT 'all',
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    timezone TEXT NOT NULL DEFAULT 'America/Bogota',
    start_time TEXT NOT NULL DEFAULT '21:00',
    end_time TEXT NOT NULL DEFAULT '08:00',
    days_json JSONB NOT NULL DEFAULT '["mon","tue","wed","thu","fri","sat","sun"]'::jsonb,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, channel, entity_type)
);

CREATE TABLE IF NOT EXISTS saas_vertical_pack_applications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    industry_code TEXT NOT NULL DEFAULT 'general',
    pack_version INTEGER NOT NULL DEFAULT 1,
    applied_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_agents BOOLEAN NOT NULL DEFAULT FALSE,
    result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_vertical_pack_applications_tenant_created
ON saas_vertical_pack_applications (tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS saas_intelligence_predictions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    subject_type TEXT NOT NULL DEFAULT 'tenant',
    subject_id TEXT NOT NULL DEFAULT '',
    prediction_type TEXT NOT NULL,
    model_key TEXT NOT NULL DEFAULT 'baseline_rules',
    model_version TEXT NOT NULL DEFAULT 'v1',
    mode TEXT NOT NULL DEFAULT 'demo',
    score NUMERIC(8,4) NOT NULL DEFAULT 0,
    label TEXT NOT NULL DEFAULT '',
    confidence NUMERIC(8,4) NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'ready',
    explanation_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    features_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP NULL
);

CREATE INDEX IF NOT EXISTS idx_saas_intelligence_predictions_tenant_type
ON saas_intelligence_predictions (tenant_id, prediction_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_intelligence_predictions_subject
ON saas_intelligence_predictions (tenant_id, subject_type, subject_id, created_at DESC);

CREATE TABLE IF NOT EXISTS saas_intelligence_recommendations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    recommendation_type TEXT NOT NULL,
    source_prediction_id UUID NULL REFERENCES saas_intelligence_predictions(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    severity TEXT NOT NULL DEFAULT 'info',
    confidence NUMERIC(8,4) NOT NULL DEFAULT 0,
    action_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_intelligence_recommendations_tenant_status
ON saas_intelligence_recommendations (tenant_id, status, updated_at DESC);
