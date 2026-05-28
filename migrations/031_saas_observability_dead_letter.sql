-- 031_saas_observability_dead_letter.sql
-- Indice operativo de errores para observabilidad admin.

CREATE TABLE IF NOT EXISTS saas_dead_letter_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    reason TEXT NOT NULL DEFAULT '',
    severity TEXT NOT NULL DEFAULT 'medium',
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    first_seen_at TIMESTAMP NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMP NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMP NULL,
    UNIQUE (source_type, source_id)
);

CREATE INDEX IF NOT EXISTS idx_saas_dead_letter_status_seen
ON saas_dead_letter_events (status, last_seen_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_dead_letter_tenant_seen
ON saas_dead_letter_events (tenant_id, last_seen_at DESC);
