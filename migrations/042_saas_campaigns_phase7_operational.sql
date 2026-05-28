-- 042_saas_campaigns_phase7_operational.sql
-- Cierre operativo Fase 7: quiet hours globales y trazabilidad A/B.

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

CREATE INDEX IF NOT EXISTS idx_saas_campaign_quiet_hours_tenant
ON saas_campaign_quiet_hours (tenant_id, channel, entity_type);

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

CREATE INDEX IF NOT EXISTS idx_saas_campaign_ab_events_entity
ON saas_campaign_ab_events (tenant_id, entity_type, entity_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_campaign_ab_events_variant
ON saas_campaign_ab_events (tenant_id, entity_type, variant_key, created_at DESC);
