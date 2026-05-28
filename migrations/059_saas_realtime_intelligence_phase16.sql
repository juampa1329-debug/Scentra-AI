-- 059_saas_realtime_intelligence_phase16.sql
-- Phase 16: AI Real-Time Intelligence Layer.
-- PostgreSQL-first live intelligence control-plane; no external streaming dependency.

CREATE TABLE IF NOT EXISTS saas_realtime_intelligence_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES saas_users(id) ON DELETE CASCADE,
    session_key TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'tenant',
    status TEXT NOT NULL DEFAULT 'active',
    last_event_id TEXT NOT NULL DEFAULT '',
    filters_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    client_meta_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    connected_at TIMESTAMP NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMP NOT NULL DEFAULT NOW(),
    closed_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, user_id, session_key)
);

CREATE INDEX IF NOT EXISTS idx_saas_realtime_sessions_tenant_status
ON saas_realtime_intelligence_sessions (tenant_id, status, last_seen_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_realtime_sessions_user
ON saas_realtime_intelligence_sessions (tenant_id, user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_realtime_intelligence_cursors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES saas_users(id) ON DELETE CASCADE,
    cursor_key TEXT NOT NULL DEFAULT 'default',
    last_event_id TEXT NOT NULL DEFAULT '',
    last_event_at TIMESTAMP NULL,
    filters_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_seen_at TIMESTAMP NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, user_id, cursor_key)
);

CREATE INDEX IF NOT EXISTS idx_saas_realtime_cursors_tenant_user
ON saas_realtime_intelligence_cursors (tenant_id, user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_realtime_intelligence_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    metric_key TEXT NOT NULL,
    metric_value NUMERIC(18,6) NOT NULL DEFAULT 0,
    window_seconds INTEGER NOT NULL DEFAULT 900,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    measured_at TIMESTAMP NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_realtime_metrics_tenant_key_time
ON saas_realtime_intelligence_metrics (tenant_id, metric_key, measured_at DESC);

UPDATE saas_plan_limits
SET feature_flags_json = COALESCE(feature_flags_json, '{}'::jsonb)
    || jsonb_build_object(
        'realtime_intelligence_layer', COALESCE((feature_flags_json ->> 'realtime_intelligence_layer')::boolean, false),
        'realtime_event_stream', COALESCE((feature_flags_json ->> 'realtime_event_stream')::boolean, false),
        'realtime_ai_alerts', COALESCE((feature_flags_json ->> 'realtime_ai_alerts')::boolean, false),
        'realtime_intelligence_dashboard', COALESCE((feature_flags_json ->> 'realtime_intelligence_dashboard')::boolean, false)
    ),
    updated_at = NOW();
