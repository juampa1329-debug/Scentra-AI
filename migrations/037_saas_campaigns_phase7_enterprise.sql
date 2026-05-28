-- 037_saas_campaigns_phase7_enterprise.sql
-- Cierre Fase 7: simulacion, versionado, quiet hours, A/B testing y preflight comercial.

ALTER TABLE saas_crm_triggers
    ADD COLUMN IF NOT EXISTS version_number INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS revision_note TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS quiet_hours_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS ab_test_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS preflight_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS last_preflight_at TIMESTAMP NULL;

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

CREATE INDEX IF NOT EXISTS idx_saas_crm_trigger_versions_trigger_created
ON saas_crm_trigger_versions (tenant_id, trigger_id, created_at DESC);

ALTER TABLE saas_campaigns
    ADD COLUMN IF NOT EXISTS quiet_hours_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS ab_test_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS preflight_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS last_preflight_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS activation_blocked_reason TEXT NOT NULL DEFAULT '';

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

CREATE INDEX IF NOT EXISTS idx_saas_campaign_preflight_runs_tenant_created
ON saas_campaign_preflight_runs (tenant_id, entity_type, created_at DESC);

ALTER TABLE saas_remarketing_flows
    ADD COLUMN IF NOT EXISTS version_number INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS quiet_hours_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS ab_test_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS preflight_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS last_preflight_at TIMESTAMP NULL;
