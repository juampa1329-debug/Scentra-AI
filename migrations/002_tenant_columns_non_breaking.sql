-- 002_tenant_columns_non_breaking.sql
-- Tenantizacion inicial compatible con el sistema actual.
-- Esta fase NO rompe PK actual de conversations.

-- 1) Crear tenant legacy para mapear datos existentes
INSERT INTO saas_tenants (id, slug, name, status, plan_code, timezone, locale)
VALUES ('00000000-0000-0000-0000-000000000001', 'legacy', 'Legacy Tenant', 'active', 'legacy', 'America/Bogota', 'es-CO')
ON CONFLICT (slug) DO NOTHING;

-- 2) Tablas core CRM
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS tenant_id UUID;
UPDATE conversations
SET tenant_id = '00000000-0000-0000-0000-000000000001'
WHERE tenant_id IS NULL;
ALTER TABLE conversations ALTER COLUMN tenant_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_conversations_tenant_updated ON conversations (tenant_id, updated_at DESC);

ALTER TABLE messages ADD COLUMN IF NOT EXISTS tenant_id UUID;
UPDATE messages
SET tenant_id = '00000000-0000-0000-0000-000000000001'
WHERE tenant_id IS NULL;
ALTER TABLE messages ALTER COLUMN tenant_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_messages_tenant_created ON messages (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_tenant_phone_created ON messages (tenant_id, phone, created_at DESC);

-- 3) Campanas y automatizaciones
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS tenant_id UUID;
UPDATE campaigns
SET tenant_id = '00000000-0000-0000-0000-000000000001'
WHERE tenant_id IS NULL;
ALTER TABLE campaigns ALTER COLUMN tenant_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_campaigns_tenant_created ON campaigns (tenant_id, created_at DESC);

ALTER TABLE campaign_recipients ADD COLUMN IF NOT EXISTS tenant_id UUID;
UPDATE campaign_recipients
SET tenant_id = '00000000-0000-0000-0000-000000000001'
WHERE tenant_id IS NULL;
ALTER TABLE campaign_recipients ALTER COLUMN tenant_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_campaign_recipients_tenant ON campaign_recipients (tenant_id);

ALTER TABLE automation_triggers ADD COLUMN IF NOT EXISTS tenant_id UUID;
UPDATE automation_triggers
SET tenant_id = '00000000-0000-0000-0000-000000000001'
WHERE tenant_id IS NULL;
ALTER TABLE automation_triggers ALTER COLUMN tenant_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_automation_triggers_tenant ON automation_triggers (tenant_id);

ALTER TABLE trigger_executions ADD COLUMN IF NOT EXISTS tenant_id UUID;
UPDATE trigger_executions
SET tenant_id = '00000000-0000-0000-0000-000000000001'
WHERE tenant_id IS NULL;
ALTER TABLE trigger_executions ALTER COLUMN tenant_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_trigger_executions_tenant_created ON trigger_executions (tenant_id, created_at DESC);

ALTER TABLE trigger_scheduled_messages ADD COLUMN IF NOT EXISTS tenant_id UUID;
UPDATE trigger_scheduled_messages
SET tenant_id = '00000000-0000-0000-0000-000000000001'
WHERE tenant_id IS NULL;
ALTER TABLE trigger_scheduled_messages ALTER COLUMN tenant_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_trigger_scheduled_tenant_due ON trigger_scheduled_messages (tenant_id, send_at);

-- 4) Remarketing
ALTER TABLE remarketing_flows ADD COLUMN IF NOT EXISTS tenant_id UUID;
UPDATE remarketing_flows
SET tenant_id = '00000000-0000-0000-0000-000000000001'
WHERE tenant_id IS NULL;
ALTER TABLE remarketing_flows ALTER COLUMN tenant_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_remarketing_flows_tenant ON remarketing_flows (tenant_id);

ALTER TABLE remarketing_steps ADD COLUMN IF NOT EXISTS tenant_id UUID;
UPDATE remarketing_steps
SET tenant_id = '00000000-0000-0000-0000-000000000001'
WHERE tenant_id IS NULL;
ALTER TABLE remarketing_steps ALTER COLUMN tenant_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_remarketing_steps_tenant ON remarketing_steps (tenant_id);

ALTER TABLE remarketing_enrollments ADD COLUMN IF NOT EXISTS tenant_id UUID;
UPDATE remarketing_enrollments
SET tenant_id = '00000000-0000-0000-0000-000000000001'
WHERE tenant_id IS NULL;
ALTER TABLE remarketing_enrollments ALTER COLUMN tenant_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_remarketing_enrollments_tenant ON remarketing_enrollments (tenant_id);

-- 5) Social routes tables
ALTER TABLE social_webhook_events ADD COLUMN IF NOT EXISTS tenant_id UUID;
UPDATE social_webhook_events
SET tenant_id = '00000000-0000-0000-0000-000000000001'
WHERE tenant_id IS NULL;
ALTER TABLE social_webhook_events ALTER COLUMN tenant_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_social_webhook_events_tenant_created ON social_webhook_events (tenant_id, created_at DESC);

ALTER TABLE social_comments ADD COLUMN IF NOT EXISTS tenant_id UUID;
UPDATE social_comments
SET tenant_id = '00000000-0000-0000-0000-000000000001'
WHERE tenant_id IS NULL;
ALTER TABLE social_comments ALTER COLUMN tenant_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_social_comments_tenant_created ON social_comments (tenant_id, created_at DESC);

ALTER TABLE meta_lead_events ADD COLUMN IF NOT EXISTS tenant_id UUID;
UPDATE meta_lead_events
SET tenant_id = '00000000-0000-0000-0000-000000000001'
WHERE tenant_id IS NULL;
ALTER TABLE meta_lead_events ALTER COLUMN tenant_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_meta_lead_events_tenant_created ON meta_lead_events (tenant_id, created_at DESC);
