-- 024_saas_advisor_phase1.sql
-- Advisor Agent persistente: hilos, mensajes e insights proactivos por tenant.

CREATE TABLE IF NOT EXISTS saas_advisor_threads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES saas_users(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT '',
    context_type TEXT NOT NULL DEFAULT 'global',
    context_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_advisor_threads_tenant_user
ON saas_advisor_threads (tenant_id, user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_advisor_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    thread_id UUID NOT NULL REFERENCES saas_advisor_threads(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ai_run_id UUID NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_advisor_messages_thread_created
ON saas_advisor_messages (thread_id, created_at ASC);

CREATE TABLE IF NOT EXISTS saas_ai_insights (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    insight_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    recommended_action_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'open',
    expires_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_insights_tenant_status
ON saas_ai_insights (tenant_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_ai_recommendations_tenant_status
ON saas_ai_recommendations (tenant_id, status, created_at DESC);
