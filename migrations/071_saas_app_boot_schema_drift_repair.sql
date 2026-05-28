-- 071_saas_app_boot_schema_drift_repair.sql
-- Production schema-drift repair for app boot paths that can still fail when
-- older CRM/Inbox/Advisor/Campaign migrations were marked applied but core
-- tables/columns are missing.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS saas_conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    external_contact_id TEXT NOT NULL,
    phone TEXT NOT NULL DEFAULT '',
    display_name TEXT NOT NULL DEFAULT '',
    takeover BOOLEAN NOT NULL DEFAULT FALSE,
    last_message_text TEXT NOT NULL DEFAULT '',
    last_message_at TIMESTAMP NULL,
    unread_count INTEGER NOT NULL DEFAULT 0,
    tags TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

ALTER TABLE saas_conversations
    ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'whatsapp',
    ADD COLUMN IF NOT EXISTS external_contact_id TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS phone TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS display_name TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS takeover BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS last_message_text TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS last_message_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS unread_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS tags TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS notes TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT NOW();

UPDATE saas_conversations
SET channel = COALESCE(NULLIF(channel, ''), 'whatsapp'),
    external_contact_id = COALESCE(external_contact_id, ''),
    phone = COALESCE(phone, ''),
    display_name = COALESCE(display_name, ''),
    takeover = COALESCE(takeover, FALSE),
    last_message_text = COALESCE(last_message_text, ''),
    unread_count = COALESCE(unread_count, 0),
    tags = COALESCE(tags, ''),
    notes = COALESCE(notes, ''),
    updated_at = COALESCE(updated_at, NOW());

CREATE INDEX IF NOT EXISTS idx_saas_conversations_tenant_channel_external
ON saas_conversations (tenant_id, channel, external_contact_id);

CREATE INDEX IF NOT EXISTS idx_saas_conversations_tenant_updated
ON saas_conversations (tenant_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL REFERENCES saas_conversations(id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    external_message_id TEXT NOT NULL,
    direction TEXT NOT NULL,
    msg_type TEXT NOT NULL DEFAULT 'text',
    text TEXT NOT NULL DEFAULT '',
    media_id TEXT NOT NULL DEFAULT '',
    mime_type TEXT NOT NULL DEFAULT '',
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

ALTER TABLE saas_messages
    ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'whatsapp',
    ADD COLUMN IF NOT EXISTS external_message_id TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS direction TEXT NOT NULL DEFAULT 'in',
    ADD COLUMN IF NOT EXISTS msg_type TEXT NOT NULL DEFAULT 'text',
    ADD COLUMN IF NOT EXISTS text TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS media_id TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS mime_type TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT NOW();

UPDATE saas_messages
SET channel = COALESCE(NULLIF(channel, ''), 'whatsapp'),
    external_message_id = COALESCE(external_message_id, ''),
    direction = COALESCE(NULLIF(direction, ''), 'in'),
    msg_type = COALESCE(NULLIF(msg_type, ''), 'text'),
    text = COALESCE(text, ''),
    media_id = COALESCE(media_id, ''),
    mime_type = COALESCE(mime_type, ''),
    payload_json = COALESCE(payload_json, '{}'::jsonb);

CREATE INDEX IF NOT EXISTS idx_saas_messages_tenant_channel_external
ON saas_messages (tenant_id, channel, external_message_id);

CREATE INDEX IF NOT EXISTS idx_saas_messages_conversation_created
ON saas_messages (conversation_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_messages_tenant_created
ON saas_messages (tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS saas_outbound_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL REFERENCES saas_conversations(id) ON DELETE CASCADE,
    message_id UUID NULL REFERENCES saas_messages(id) ON DELETE SET NULL,
    channel TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT '',
    recipient_external_id TEXT NOT NULL DEFAULT '',
    body_text TEXT NOT NULL DEFAULT '',
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'queued',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    next_attempt_at TIMESTAMP NOT NULL DEFAULT NOW(),
    locked_at TIMESTAMP NULL,
    sent_at TIMESTAMP NULL,
    error TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

ALTER TABLE saas_outbound_messages
    ADD COLUMN IF NOT EXISTS provider TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS recipient_external_id TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS body_text TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'queued',
    ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS max_attempts INTEGER NOT NULL DEFAULT 5,
    ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMP NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS locked_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS sent_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS error TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_saas_outbound_tenant_status_next
ON saas_outbound_messages (tenant_id, status, next_attempt_at);

CREATE INDEX IF NOT EXISTS idx_saas_outbound_conversation_created
ON saas_outbound_messages (conversation_id, created_at DESC);

CREATE TABLE IF NOT EXISTS saas_audit_events (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE SET NULL,
    actor_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    action TEXT NOT NULL DEFAULT '',
    resource_type TEXT NOT NULL DEFAULT '',
    resource_id TEXT NOT NULL DEFAULT '',
    details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

ALTER TABLE saas_audit_events
    ADD COLUMN IF NOT EXISTS tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS actor_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS action TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS resource_type TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS resource_id TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_saas_audit_tenant_created
ON saas_audit_events (tenant_id, created_at DESC);

ALTER TABLE saas_crm_pipelines
    ADD COLUMN IF NOT EXISTS name TEXT NOT NULL DEFAULT 'Pipeline comercial',
    ADD COLUMN IF NOT EXISTS industry_code TEXT NOT NULL DEFAULT 'general',
    ADD COLUMN IF NOT EXISTS is_default BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT NOW();

ALTER TABLE saas_crm_pipeline_stages
    ADD COLUMN IF NOT EXISTS stage_key TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS label TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS probability INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS display_order INTEGER NOT NULL DEFAULT 100,
    ADD COLUMN IF NOT EXISTS is_won BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS is_lost BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT NOW();

ALTER TABLE saas_crm_custom_fields
    ADD COLUMN IF NOT EXISTS field_key TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS label TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS field_type TEXT NOT NULL DEFAULT 'text',
    ADD COLUMN IF NOT EXISTS options_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS is_required BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS display_order INTEGER NOT NULL DEFAULT 100,
    ADD COLUMN IF NOT EXISTS created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT NOW();

ALTER TABLE saas_labels
    ADD COLUMN IF NOT EXISTS name TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS color TEXT NOT NULL DEFAULT '#5eead4',
    ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'general',
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT NOW();

ALTER TABLE saas_message_templates
    ADD COLUMN IF NOT EXISTS name TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'whatsapp',
    ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'general',
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'draft',
    ADD COLUMN IF NOT EXISTS body TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS variables_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS blocks_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS params_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS render_mode TEXT NOT NULL DEFAULT 'chat',
    ADD COLUMN IF NOT EXISTS template_scope TEXT NOT NULL DEFAULT 'crm',
    ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'internal',
    ADD COLUMN IF NOT EXISTS created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT NOW();

ALTER TABLE saas_segments
    ADD COLUMN IF NOT EXISTS name TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS filters_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS audience_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT NOW();

ALTER TABLE saas_campaigns
    ADD COLUMN IF NOT EXISTS quiet_hours_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS ab_test_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS preflight_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS last_preflight_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS activation_blocked_reason TEXT NOT NULL DEFAULT '';

ALTER TABLE saas_crm_triggers
    ADD COLUMN IF NOT EXISTS name TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'whatsapp',
    ADD COLUMN IF NOT EXISTS event_type TEXT NOT NULL DEFAULT 'message_in',
    ADD COLUMN IF NOT EXISTS trigger_type TEXT NOT NULL DEFAULT 'message_flow',
    ADD COLUMN IF NOT EXISTS flow_event TEXT NOT NULL DEFAULT 'received',
    ADD COLUMN IF NOT EXISTS conditions_json JSONB NOT NULL DEFAULT '{"conditions":[]}'::jsonb,
    ADD COLUMN IF NOT EXISTS actions_json JSONB NOT NULL DEFAULT '{"actions":[]}'::jsonb,
    ADD COLUMN IF NOT EXISTS priority INTEGER NOT NULL DEFAULT 100,
    ADD COLUMN IF NOT EXISTS cooldown_minutes INTEGER NOT NULL DEFAULT 60,
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE,
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
    ADD COLUMN IF NOT EXISTS last_preflight_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT NOW();

ALTER TABLE saas_remarketing_flows
    ADD COLUMN IF NOT EXISTS name TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'whatsapp',
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'draft',
    ADD COLUMN IF NOT EXISTS entry_rules_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS exit_rules_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS steps_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS version_number INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS quiet_hours_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS ab_test_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS preflight_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS last_preflight_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT NOW();

CREATE UNIQUE INDEX IF NOT EXISTS uniq_saas_crm_custom_fields_tenant_key
ON saas_crm_custom_fields (tenant_id, field_key);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_saas_crm_pipeline_stages_key
ON saas_crm_pipeline_stages (tenant_id, pipeline_id, stage_key);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_saas_labels_tenant_lower_name
ON saas_labels (tenant_id, lower(name));

CREATE UNIQUE INDEX IF NOT EXISTS uniq_saas_templates_tenant_channel_lower_name
ON saas_message_templates (tenant_id, channel, lower(name));

CREATE UNIQUE INDEX IF NOT EXISTS uniq_saas_segments_tenant_lower_name
ON saas_segments (tenant_id, lower(name));

CREATE UNIQUE INDEX IF NOT EXISTS uniq_saas_triggers_tenant_channel_lower_name
ON saas_crm_triggers (tenant_id, channel, lower(name));

CREATE UNIQUE INDEX IF NOT EXISTS uniq_saas_flows_tenant_channel_lower_name
ON saas_remarketing_flows (tenant_id, channel, lower(name));

CREATE TABLE IF NOT EXISTS saas_crm_trigger_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    trigger_id UUID NOT NULL REFERENCES saas_crm_triggers(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    snapshot_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    change_reason TEXT NOT NULL DEFAULT '',
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, trigger_id, version_number)
);

CREATE TABLE IF NOT EXISTS saas_campaign_preflight_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    campaign_id UUID NULL REFERENCES saas_campaigns(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL DEFAULT 'campaign',
    entity_id UUID NULL,
    status TEXT NOT NULL DEFAULT 'warning',
    score INTEGER NOT NULL DEFAULT 0,
    checks_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS saas_campaign_ab_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL,
    entity_id UUID NULL,
    conversation_id UUID NULL REFERENCES saas_conversations(id) ON DELETE SET NULL,
    message_id UUID NULL REFERENCES saas_messages(id) ON DELETE SET NULL,
    outbound_id UUID NULL REFERENCES saas_outbound_messages(id) ON DELETE SET NULL,
    channel TEXT NOT NULL DEFAULT 'whatsapp',
    recipient_external_id TEXT NOT NULL DEFAULT '',
    variant_key TEXT NOT NULL DEFAULT '',
    template_id UUID NULL REFERENCES saas_message_templates(id) ON DELETE SET NULL,
    source TEXT NOT NULL DEFAULT '',
    outcome TEXT NOT NULL DEFAULT 'queued',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

ALTER TABLE saas_campaign_quiet_hours
    ADD COLUMN IF NOT EXISTS entity_type TEXT NOT NULL DEFAULT 'all',
    ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS timezone TEXT NOT NULL DEFAULT 'America/Bogota',
    ADD COLUMN IF NOT EXISTS start_time TEXT NOT NULL DEFAULT '21:00',
    ADD COLUMN IF NOT EXISTS end_time TEXT NOT NULL DEFAULT '08:00',
    ADD COLUMN IF NOT EXISTS days_json JSONB NOT NULL DEFAULT '["mon","tue","wed","thu","fri","sat","sun"]'::jsonb,
    ADD COLUMN IF NOT EXISTS created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT NOW();

CREATE UNIQUE INDEX IF NOT EXISTS uniq_saas_campaign_quiet_hours_tenant_channel_entity
ON saas_campaign_quiet_hours (tenant_id, channel, entity_type);

CREATE TABLE IF NOT EXISTS saas_ai_recommendations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    ai_run_id UUID NULL,
    recommendation_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    action_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence NUMERIC(5,2) NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

ALTER TABLE saas_ai_recommendations
    ADD COLUMN IF NOT EXISTS ai_run_id UUID NULL,
    ADD COLUMN IF NOT EXISTS recommendation_type TEXT NOT NULL DEFAULT 'general',
    ADD COLUMN IF NOT EXISTS severity TEXT NOT NULL DEFAULT 'info',
    ADD COLUMN IF NOT EXISTS title TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS action_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS confidence NUMERIC(5,2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'open',
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT NOW();

CREATE TABLE IF NOT EXISTS saas_ai_insights (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    insight_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    recommended_action_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'open',
    expires_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

ALTER TABLE saas_ai_insights
    ADD COLUMN IF NOT EXISTS insight_type TEXT NOT NULL DEFAULT 'general',
    ADD COLUMN IF NOT EXISTS severity TEXT NOT NULL DEFAULT 'info',
    ADD COLUMN IF NOT EXISTS title TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS recommended_action_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'open',
    ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_saas_ai_insights_tenant_status
ON saas_ai_insights (tenant_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_ai_recommendations_tenant_status
ON saas_ai_recommendations (tenant_id, status, created_at DESC);
