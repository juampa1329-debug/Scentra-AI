-- 001_saas_core.sql
-- Crea las tablas base del dominio SaaS.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS saas_tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    plan_code TEXT NOT NULL DEFAULT 'starter',
    timezone TEXT NOT NULL DEFAULT 'America/Bogota',
    locale TEXT NOT NULL DEFAULT 'es-CO',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS saas_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    password_algo TEXT NOT NULL DEFAULT 'argon2id',
    status TEXT NOT NULL DEFAULT 'active',
    last_login_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS saas_memberships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES saas_users(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_saas_memberships_tenant_role ON saas_memberships (tenant_id, role);

CREATE TABLE IF NOT EXISTS saas_integrations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    channel TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'disconnected',
    secret_ref TEXT NOT NULL DEFAULT '',
    config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_sync_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, provider, channel)
);
CREATE INDEX IF NOT EXISTS idx_saas_integrations_tenant ON saas_integrations (tenant_id);

CREATE TABLE IF NOT EXISTS saas_webhook_endpoints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    endpoint_key TEXT NOT NULL UNIQUE,
    verify_secret_ref TEXT NOT NULL DEFAULT '',
    verify_token_hash TEXT NOT NULL DEFAULT '',
    signature_secret_hash TEXT NOT NULL DEFAULT '',
    signature_secret_salt TEXT NOT NULL DEFAULT '',
    signature_required BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_seen_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, provider)
);
CREATE INDEX IF NOT EXISTS idx_saas_webhooks_tenant_provider ON saas_webhook_endpoints (tenant_id, provider);

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
CREATE INDEX IF NOT EXISTS idx_saas_webhook_events_tenant_received ON saas_webhook_events (tenant_id, received_at DESC);

CREATE TABLE IF NOT EXISTS saas_billing_customers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL UNIQUE REFERENCES saas_tenants(id) ON DELETE CASCADE,
    provider TEXT NOT NULL DEFAULT 'stripe',
    provider_customer_id TEXT NOT NULL UNIQUE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS saas_billing_subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    provider TEXT NOT NULL DEFAULT 'stripe',
    provider_subscription_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    plan_code TEXT NOT NULL,
    current_period_start TIMESTAMP NULL,
    current_period_end TIMESTAMP NULL,
    cancel_at_period_end BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_saas_subscriptions_tenant_status ON saas_billing_subscriptions (tenant_id, status);

CREATE TABLE IF NOT EXISTS saas_plan_limits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_code TEXT NOT NULL UNIQUE,
    max_agents INTEGER NOT NULL DEFAULT 3,
    max_monthly_messages INTEGER NOT NULL DEFAULT 5000,
    max_integrations INTEGER NOT NULL DEFAULT 3,
    max_storage_gb INTEGER NOT NULL DEFAULT 5,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS saas_usage_counters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    metric_code TEXT NOT NULL,
    period_yyyymm TEXT NOT NULL,
    metric_value BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, metric_code, period_yyyymm)
);

CREATE TABLE IF NOT EXISTS saas_audit_events (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE SET NULL,
    actor_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL DEFAULT '',
    details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_saas_audit_tenant_created ON saas_audit_events (tenant_id, created_at DESC);

INSERT INTO saas_plan_limits (plan_code, max_agents, max_monthly_messages, max_integrations, max_storage_gb)
VALUES
  ('starter', 3, 5000, 3, 5),
  ('growth', 10, 50000, 8, 20),
  ('pro', 40, 250000, 20, 100)
ON CONFLICT (plan_code) DO NOTHING;
