CREATE TABLE IF NOT EXISTS saas_billing_provider_settings (
    provider TEXT PRIMARY KEY,
    display_name TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    is_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    test_mode BOOLEAN NOT NULL DEFAULT TRUE,
    debug_logging BOOLEAN NOT NULL DEFAULT FALSE,
    test_public_key TEXT NOT NULL DEFAULT '',
    test_private_key_enc TEXT NOT NULL DEFAULT '',
    test_event_key_enc TEXT NOT NULL DEFAULT '',
    test_integrity_key_enc TEXT NOT NULL DEFAULT '',
    live_public_key TEXT NOT NULL DEFAULT '',
    live_private_key_enc TEXT NOT NULL DEFAULT '',
    live_event_key_enc TEXT NOT NULL DEFAULT '',
    live_integrity_key_enc TEXT NOT NULL DEFAULT '',
    test_access_token_enc TEXT NOT NULL DEFAULT '',
    test_webhook_secret_enc TEXT NOT NULL DEFAULT '',
    live_access_token_enc TEXT NOT NULL DEFAULT '',
    live_webhook_secret_enc TEXT NOT NULL DEFAULT '',
    config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_by_user_id UUID NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CHECK (provider IN ('wompi', 'mercadopago'))
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_saas_billing_provider_settings_default
    ON saas_billing_provider_settings (is_default)
    WHERE is_default = TRUE;
