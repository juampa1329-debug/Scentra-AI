-- 017_saas_api_credentials.sql
-- Credenciales cifradas por empresa para IA, TTS, canales y comercio.

CREATE TABLE IF NOT EXISTS saas_api_credentials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    category TEXT NOT NULL DEFAULT 'ai',
    provider_code TEXT NOT NULL,
    credential_key TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    secret_value TEXT NOT NULL DEFAULT '',
    secret_hint TEXT NOT NULL DEFAULT '',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_validated_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, credential_key)
);

CREATE INDEX IF NOT EXISTS idx_saas_api_credentials_tenant_provider
ON saas_api_credentials (tenant_id, provider_code, category);
