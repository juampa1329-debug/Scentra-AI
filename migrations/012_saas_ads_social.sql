-- 012_saas_ads_social.sql
-- Ads Manager SaaS: cuentas publicitarias, campanas, leads y comentarios sociales.

CREATE TABLE IF NOT EXISTS saas_ad_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    provider TEXT NOT NULL DEFAULT 'meta',
    external_account_id TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'connected',
    currency TEXT NOT NULL DEFAULT '',
    timezone TEXT NOT NULL DEFAULT '',
    config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_sync_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, provider, external_account_id)
);

CREATE INDEX IF NOT EXISTS idx_saas_ad_accounts_tenant_provider
ON saas_ad_accounts (tenant_id, provider, status);

CREATE TABLE IF NOT EXISTS saas_ad_campaigns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    account_id UUID NULL REFERENCES saas_ad_accounts(id) ON DELETE SET NULL,
    provider TEXT NOT NULL DEFAULT 'meta',
    channel TEXT NOT NULL DEFAULT 'facebook',
    external_campaign_id TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    objective TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'unknown',
    daily_budget_cents INTEGER NOT NULL DEFAULT 0,
    lifetime_budget_cents INTEGER NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT '',
    metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_sync_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, provider, external_campaign_id)
);

CREATE INDEX IF NOT EXISTS idx_saas_ad_campaigns_tenant_status
ON saas_ad_campaigns (tenant_id, provider, channel, status);

CREATE TABLE IF NOT EXISTS saas_ad_leads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    provider TEXT NOT NULL DEFAULT 'meta',
    channel TEXT NOT NULL DEFAULT 'facebook',
    external_lead_id TEXT NOT NULL,
    external_form_id TEXT NOT NULL DEFAULT '',
    external_ad_id TEXT NOT NULL DEFAULT '',
    external_campaign_id TEXT NOT NULL DEFAULT '',
    contact_name TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'new',
    conversation_id UUID NULL REFERENCES saas_conversations(id) ON DELETE SET NULL,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    received_at TIMESTAMP NOT NULL DEFAULT NOW(),
    converted_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, provider, external_lead_id)
);

CREATE INDEX IF NOT EXISTS idx_saas_ad_leads_tenant_status
ON saas_ad_leads (tenant_id, provider, channel, status, received_at DESC);

CREATE TABLE IF NOT EXISTS saas_social_comments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    provider TEXT NOT NULL DEFAULT 'meta',
    channel TEXT NOT NULL DEFAULT 'facebook',
    external_comment_id TEXT NOT NULL,
    external_parent_id TEXT NOT NULL DEFAULT '',
    external_post_id TEXT NOT NULL DEFAULT '',
    external_ad_id TEXT NOT NULL DEFAULT '',
    external_campaign_id TEXT NOT NULL DEFAULT '',
    author_id TEXT NOT NULL DEFAULT '',
    author_name TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    permalink_url TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'new',
    conversation_id UUID NULL REFERENCES saas_conversations(id) ON DELETE SET NULL,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    received_at TIMESTAMP NOT NULL DEFAULT NOW(),
    replied_at TIMESTAMP NULL,
    resolved_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, provider, external_comment_id)
);

CREATE INDEX IF NOT EXISTS idx_saas_social_comments_tenant_status
ON saas_social_comments (tenant_id, provider, channel, status, received_at DESC);
