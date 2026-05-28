-- Phase 1 security hardening: account lockout, password recovery and 2FA preparation.

ALTER TABLE saas_users
  ADD COLUMN IF NOT EXISTS failed_login_count INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS locked_until TIMESTAMPTZ NULL,
  ADD COLUMN IF NOT EXISTS password_changed_at TIMESTAMPTZ NULL,
  ADD COLUMN IF NOT EXISTS two_factor_enabled BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS two_factor_method TEXT NOT NULL DEFAULT 'none',
  ADD COLUMN IF NOT EXISTS two_factor_secret_ref TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS two_factor_recovery_hashes_json JSONB NOT NULL DEFAULT '[]'::jsonb;

CREATE INDEX IF NOT EXISTS idx_saas_users_locked_until
ON saas_users (locked_until)
WHERE locked_until IS NOT NULL;

CREATE TABLE IF NOT EXISTS saas_password_reset_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES saas_users(id) ON DELETE CASCADE,
    email TEXT NOT NULL DEFAULT '',
    token_hash TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending',
    requested_ip TEXT NOT NULL DEFAULT '',
    user_agent TEXT NOT NULL DEFAULT '',
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_password_reset_user_status
ON saas_password_reset_tokens (user_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_password_reset_expires
ON saas_password_reset_tokens (status, expires_at);

CREATE TABLE IF NOT EXISTS saas_security_events (
    id UUID PRIMARY KEY,
    tenant_id UUID NULL,
    user_id UUID NULL,
    event_type TEXT NOT NULL,
    rate_limit_key TEXT NOT NULL DEFAULT '',
    principal TEXT NOT NULL DEFAULT '',
    ip_address TEXT NOT NULL DEFAULT '',
    user_agent TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'attempt',
    reason TEXT NOT NULL DEFAULT '',
    details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_security_events_rate
ON saas_security_events (event_type, rate_limit_key, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_security_events_created
ON saas_security_events (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_security_events_principal_created
ON saas_security_events (event_type, principal, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_security_events_ip_created
ON saas_security_events (event_type, ip_address, created_at DESC);
