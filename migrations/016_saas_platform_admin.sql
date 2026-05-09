-- 016_saas_platform_admin.sql
-- Base del panel interno Scentra Admin: administradores plataforma, planes extendidos y feature flags por empresa.

CREATE TABLE IF NOT EXISTS saas_platform_admins (
    user_id UUID PRIMARY KEY REFERENCES saas_users(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'platform_admin',
    status TEXT NOT NULL DEFAULT 'active',
    notes TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_saas_platform_admins_status_role
ON saas_platform_admins (status, role);

ALTER TABLE saas_plan_limits
    ADD COLUMN IF NOT EXISTS display_name TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS max_campaigns INTEGER NOT NULL DEFAULT 10,
    ADD COLUMN IF NOT EXISTS max_broadcasts INTEGER NOT NULL DEFAULT 10,
    ADD COLUMN IF NOT EXISTS max_ai_tokens BIGINT NOT NULL DEFAULT 1000000,
    ADD COLUMN IF NOT EXISTS feature_flags_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS price_monthly_cents INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS currency TEXT NOT NULL DEFAULT 'USD',
    ADD COLUMN IF NOT EXISTS is_public BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS sort_order INTEGER NOT NULL DEFAULT 100;

UPDATE saas_plan_limits
SET
    display_name = CASE plan_code
        WHEN 'starter' THEN 'Starter'
        WHEN 'growth' THEN 'Growth'
        WHEN 'pro' THEN 'Pro'
        ELSE COALESCE(NULLIF(display_name, ''), initcap(plan_code))
    END,
    max_campaigns = CASE plan_code
        WHEN 'starter' THEN 5
        WHEN 'growth' THEN 30
        WHEN 'pro' THEN 150
        ELSE max_campaigns
    END,
    max_broadcasts = CASE plan_code
        WHEN 'starter' THEN 5
        WHEN 'growth' THEN 40
        WHEN 'pro' THEN 200
        ELSE max_broadcasts
    END,
    max_ai_tokens = CASE plan_code
        WHEN 'starter' THEN 1000000
        WHEN 'growth' THEN 12000000
        WHEN 'pro' THEN 60000000
        ELSE max_ai_tokens
    END,
    feature_flags_json = CASE plan_code
        WHEN 'starter' THEN '{"inbox":true,"ai":true,"broadcast":true,"triggers":false,"remarketing":false,"ads":false,"whatsapp_cloud":true,"elevenlabs_voice":false}'::jsonb
        WHEN 'growth' THEN '{"inbox":true,"ai":true,"broadcast":true,"triggers":true,"remarketing":true,"ads":false,"whatsapp_cloud":true,"elevenlabs_voice":true}'::jsonb
        WHEN 'pro' THEN '{"inbox":true,"ai":true,"broadcast":true,"triggers":true,"remarketing":true,"ads":true,"whatsapp_cloud":true,"elevenlabs_voice":true}'::jsonb
        ELSE feature_flags_json
    END,
    sort_order = CASE plan_code
        WHEN 'starter' THEN 10
        WHEN 'growth' THEN 20
        WHEN 'pro' THEN 30
        ELSE sort_order
    END
WHERE display_name = '' OR feature_flags_json = '{}'::jsonb;

CREATE TABLE IF NOT EXISTS saas_tenant_feature_flags (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    feature_key TEXT NOT NULL,
    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    source TEXT NOT NULL DEFAULT 'admin',
    notes TEXT NOT NULL DEFAULT '',
    updated_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, feature_key)
);
CREATE INDEX IF NOT EXISTS idx_saas_tenant_feature_flags_tenant
ON saas_tenant_feature_flags (tenant_id, feature_key);

CREATE INDEX IF NOT EXISTS idx_saas_tenants_status_plan
ON saas_tenants (status, plan_code);
