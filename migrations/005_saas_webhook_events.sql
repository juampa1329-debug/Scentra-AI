-- 005_saas_webhook_events.sql
-- Agrega soporte verificable e idempotente para webhooks SaaS.

ALTER TABLE saas_webhook_endpoints ADD COLUMN IF NOT EXISTS verify_token_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE saas_webhook_endpoints ADD COLUMN IF NOT EXISTS signature_secret_hash TEXT NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS saas_webhook_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    endpoint_id UUID NOT NULL REFERENCES saas_webhook_endpoints(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    event_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'received',
    headers_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    raw_sha256 TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    received_at TIMESTAMP NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMP NULL,
    UNIQUE (tenant_id, provider, event_id)
);

CREATE INDEX IF NOT EXISTS idx_saas_webhook_events_tenant_received
ON saas_webhook_events (tenant_id, received_at DESC);
