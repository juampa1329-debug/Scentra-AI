-- Phase 5: monetization runtime.
-- Provider-agnostic billing records for checkout, invoices, payments,
-- manual credits and provider webhook audit.

ALTER TABLE saas_billing_customers
    ADD COLUMN IF NOT EXISTS email TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS name TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE saas_billing_subscriptions
    ADD COLUMN IF NOT EXISTS provider_customer_id TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS last_payment_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS past_due_at TIMESTAMP NULL;

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
