-- 021_whatsapp_subscription_checks.sql
-- Auditoria operativa para validar/suscribir WABAs a los webhooks de la app Meta.

CREATE TABLE IF NOT EXISTS saas_whatsapp_subscription_checks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    integration_id UUID NULL REFERENCES saas_integrations(id) ON DELETE SET NULL,
    waba_id TEXT NOT NULL,
    app_id TEXT NOT NULL DEFAULT '',
    access_token_hint TEXT NOT NULL DEFAULT '',
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

CREATE INDEX IF NOT EXISTS idx_saas_whatsapp_subscription_checks_tenant_created
ON saas_whatsapp_subscription_checks (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_whatsapp_subscription_checks_waba_created
ON saas_whatsapp_subscription_checks (waba_id, created_at DESC);
