-- 069_saas_auth_billing_schema_drift_repair.sql
-- Production schema-drift repair for databases where older phase migrations were
-- marked as applied before all auth/billing columns existed.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

ALTER TABLE saas_tenants
  ADD COLUMN IF NOT EXISTS industry_code TEXT NOT NULL DEFAULT 'general',
  ADD COLUMN IF NOT EXISTS vertical_pack_applied_at TIMESTAMP NULL;

UPDATE saas_tenants
SET industry_code = 'general'
WHERE industry_code IS NULL OR BTRIM(industry_code) = '';

ALTER TABLE saas_tenants
  ALTER COLUMN industry_code SET DEFAULT 'general';

ALTER TABLE saas_users
  ADD COLUMN IF NOT EXISTS failed_login_count INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS locked_until TIMESTAMPTZ NULL,
  ADD COLUMN IF NOT EXISTS password_changed_at TIMESTAMPTZ NULL,
  ADD COLUMN IF NOT EXISTS two_factor_enabled BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS two_factor_method TEXT NOT NULL DEFAULT 'none',
  ADD COLUMN IF NOT EXISTS two_factor_secret_ref TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS two_factor_recovery_hashes_json JSONB NOT NULL DEFAULT '[]'::jsonb;

UPDATE saas_users
SET two_factor_method = 'none'
WHERE two_factor_method IS NULL OR BTRIM(two_factor_method) = '';

UPDATE saas_users
SET failed_login_count = 0
WHERE failed_login_count IS NULL;

ALTER TABLE saas_users
  ALTER COLUMN failed_login_count SET DEFAULT 0,
  ALTER COLUMN two_factor_enabled SET DEFAULT FALSE,
  ALTER COLUMN two_factor_method SET DEFAULT 'none',
  ALTER COLUMN two_factor_secret_ref SET DEFAULT '',
  ALTER COLUMN two_factor_recovery_hashes_json SET DEFAULT '[]'::jsonb;

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
    event_type TEXT NOT NULL DEFAULT 'security.event',
    rate_limit_key TEXT NOT NULL DEFAULT '',
    principal TEXT NOT NULL DEFAULT '',
    ip_address TEXT NOT NULL DEFAULT '',
    user_agent TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'attempt',
    reason TEXT NOT NULL DEFAULT '',
    details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE saas_security_events
  ADD COLUMN IF NOT EXISTS tenant_id UUID NULL,
  ADD COLUMN IF NOT EXISTS user_id UUID NULL,
  ADD COLUMN IF NOT EXISTS event_type TEXT NOT NULL DEFAULT 'security.event',
  ADD COLUMN IF NOT EXISTS rate_limit_key TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS principal TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS ip_address TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS user_agent TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'attempt',
  ADD COLUMN IF NOT EXISTS reason TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_saas_security_events_rate
ON saas_security_events (event_type, rate_limit_key, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_security_events_created
ON saas_security_events (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_security_events_principal_created
ON saas_security_events (event_type, principal, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_security_events_ip_created
ON saas_security_events (event_type, ip_address, created_at DESC);

CREATE TABLE IF NOT EXISTS saas_mfa_challenges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES saas_users(id) ON DELETE CASCADE,
    tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    context TEXT NOT NULL DEFAULT 'tenant',
    role TEXT NOT NULL DEFAULT '',
    platform_role TEXT NOT NULL DEFAULT '',
    method TEXT NOT NULL DEFAULT 'email_otp',
    challenge_token_hash TEXT NOT NULL UNIQUE,
    code_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    email_sent BOOLEAN NOT NULL DEFAULT FALSE,
    requested_ip TEXT NOT NULL DEFAULT '',
    user_agent TEXT NOT NULL DEFAULT '',
    expires_at TIMESTAMP NOT NULL,
    verified_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

ALTER TABLE saas_mfa_challenges
  ADD COLUMN IF NOT EXISTS tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
  ADD COLUMN IF NOT EXISTS context TEXT NOT NULL DEFAULT 'tenant',
  ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS platform_role TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS method TEXT NOT NULL DEFAULT 'email_otp',
  ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS max_attempts INTEGER NOT NULL DEFAULT 5,
  ADD COLUMN IF NOT EXISTS email_sent BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS requested_ip TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS user_agent TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS verified_at TIMESTAMP NULL,
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_saas_mfa_challenges_user_created
ON saas_mfa_challenges (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_mfa_challenges_pending
ON saas_mfa_challenges (context, status, expires_at)
WHERE status = 'pending';

ALTER TABLE saas_billing_subscriptions
  ADD COLUMN IF NOT EXISTS provider_customer_id TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS last_payment_at TIMESTAMP NULL,
  ADD COLUMN IF NOT EXISTS past_due_at TIMESTAMP NULL,
  ADD COLUMN IF NOT EXISTS lifecycle_last_checked_at TIMESTAMP NULL,
  ADD COLUMN IF NOT EXISTS payment_failed_notice_sent_at TIMESTAMP NULL,
  ADD COLUMN IF NOT EXISTS trial_expired_notice_sent_at TIMESTAMP NULL,
  ADD COLUMN IF NOT EXISTS suspension_notice_sent_at TIMESTAMP NULL;

ALTER TABLE saas_billing_customers
  ADD COLUMN IF NOT EXISTS email TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS name TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS saas_billing_checkout_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    provider TEXT NOT NULL DEFAULT 'manual',
    provider_checkout_id TEXT NOT NULL DEFAULT '',
    provider_customer_id TEXT NOT NULL DEFAULT '',
    plan_code TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    currency TEXT NOT NULL DEFAULT 'USD',
    amount_cents INTEGER NOT NULL DEFAULT 0,
    checkout_url TEXT NOT NULL DEFAULT '',
    success_url TEXT NOT NULL DEFAULT '',
    cancel_url TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    expires_at TIMESTAMP NULL,
    completed_at TIMESTAMP NULL,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_billing_checkout_tenant
ON saas_billing_checkout_sessions (tenant_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_saas_billing_checkout_provider
ON saas_billing_checkout_sessions (provider, provider_checkout_id)
WHERE provider_checkout_id <> '';

CREATE TABLE IF NOT EXISTS saas_billing_invoices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    subscription_id UUID NULL REFERENCES saas_billing_subscriptions(id) ON DELETE SET NULL,
    provider TEXT NOT NULL DEFAULT 'manual',
    provider_invoice_id TEXT NOT NULL DEFAULT '',
    invoice_number TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    plan_code TEXT NOT NULL DEFAULT '',
    currency TEXT NOT NULL DEFAULT 'USD',
    subtotal_cents INTEGER NOT NULL DEFAULT 0,
    discount_cents INTEGER NOT NULL DEFAULT 0,
    tax_cents INTEGER NOT NULL DEFAULT 0,
    total_cents INTEGER NOT NULL DEFAULT 0,
    amount_paid_cents INTEGER NOT NULL DEFAULT 0,
    amount_due_cents INTEGER NOT NULL DEFAULT 0,
    hosted_invoice_url TEXT NOT NULL DEFAULT '',
    pdf_url TEXT NOT NULL DEFAULT '',
    period_start TIMESTAMP NULL,
    period_end TIMESTAMP NULL,
    due_at TIMESTAMP NULL,
    paid_at TIMESTAMP NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_billing_invoices_tenant
ON saas_billing_invoices (tenant_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_saas_billing_invoices_provider
ON saas_billing_invoices (provider, provider_invoice_id)
WHERE provider_invoice_id <> '';

CREATE TABLE IF NOT EXISTS saas_billing_payments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    invoice_id UUID NULL REFERENCES saas_billing_invoices(id) ON DELETE SET NULL,
    provider TEXT NOT NULL DEFAULT 'manual',
    provider_payment_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    currency TEXT NOT NULL DEFAULT 'USD',
    amount_cents INTEGER NOT NULL DEFAULT 0,
    paid_at TIMESTAMP NULL,
    failure_reason TEXT NOT NULL DEFAULT '',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_billing_payments_tenant
ON saas_billing_payments (tenant_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_saas_billing_payments_provider
ON saas_billing_payments (provider, provider_payment_id)
WHERE provider_payment_id <> '';

CREATE TABLE IF NOT EXISTS saas_billing_credits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    metric_code TEXT NOT NULL DEFAULT 'monthly_messages',
    amount INTEGER NOT NULL,
    remaining_amount INTEGER NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    expires_at TIMESTAMP NULL,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_billing_credits_tenant
ON saas_billing_credits (tenant_id, metric_code, expires_at NULLS LAST, created_at DESC);

CREATE TABLE IF NOT EXISTS saas_billing_provider_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider TEXT NOT NULL,
    provider_event_id TEXT NOT NULL DEFAULT '',
    event_type TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'received',
    tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE SET NULL,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT NOT NULL DEFAULT '',
    received_at TIMESTAMP NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMP NULL
);

CREATE INDEX IF NOT EXISTS idx_saas_billing_provider_events_received
ON saas_billing_provider_events (provider, received_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_saas_billing_provider_events_unique
ON saas_billing_provider_events (provider, provider_event_id)
WHERE provider_event_id <> '';

ALTER TABLE saas_billing_invoices
  ADD COLUMN IF NOT EXISTS payment_failed_notice_sent_at TIMESTAMP NULL,
  ADD COLUMN IF NOT EXISTS pdf_generated_at TIMESTAMP NULL;

ALTER TABLE saas_billing_checkout_sessions
  ADD COLUMN IF NOT EXISTS last_provider_event_at TIMESTAMP NULL;

CREATE INDEX IF NOT EXISTS idx_saas_billing_subscriptions_status_period
ON saas_billing_subscriptions (status, current_period_end, past_due_at);

CREATE INDEX IF NOT EXISTS idx_saas_billing_invoices_status_due
ON saas_billing_invoices (status, due_at, tenant_id);

CREATE INDEX IF NOT EXISTS idx_saas_billing_provider_events_status
ON saas_billing_provider_events (status, provider, received_at DESC);
