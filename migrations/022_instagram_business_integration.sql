-- 022_instagram_business_integration.sql
-- OAuth, discovery y auditoria para Instagram Business multi-tenant.

CREATE TABLE IF NOT EXISTS saas_instagram_oauth_states (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES saas_users(id) ON DELETE CASCADE,
    state_hash TEXT NOT NULL UNIQUE,
    redirect_uri TEXT NOT NULL DEFAULT '',
    result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT NOT NULL DEFAULT '',
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_instagram_oauth_states_tenant_created
ON saas_instagram_oauth_states (tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS saas_instagram_subscription_checks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    integration_id UUID NULL REFERENCES saas_integrations(id) ON DELETE SET NULL,
    page_id TEXT NOT NULL,
    instagram_business_account_id TEXT NOT NULL DEFAULT '',
    app_id TEXT NOT NULL DEFAULT '',
    access_token_hint TEXT NOT NULL DEFAULT '',
    subscribed_fields TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'unknown',
    already_subscribed BOOLEAN NOT NULL DEFAULT FALSE,
    auto_subscribe_attempted BOOLEAN NOT NULL DEFAULT FALSE,
    final_subscribed BOOLEAN NOT NULL DEFAULT FALSE,
    http_status INTEGER NULL,
    meta_code INTEGER NULL,
    meta_error_type TEXT NOT NULL DEFAULT '',
    meta_error_message TEXT NOT NULL DEFAULT '',
    request_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_instagram_subscription_checks_tenant_created
ON saas_instagram_subscription_checks (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_instagram_subscription_checks_page_created
ON saas_instagram_subscription_checks (page_id, created_at DESC);
