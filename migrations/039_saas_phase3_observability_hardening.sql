-- 039_saas_phase3_observability_hardening.sql
-- Phase 3 observability: worker heartbeat, correlation IDs and retry diagnostics.

CREATE TABLE IF NOT EXISTS saas_worker_heartbeats (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    worker_name TEXT NOT NULL UNIQUE,
    worker_type TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'ok',
    last_started_at TIMESTAMP NULL,
    last_seen_at TIMESTAMP NOT NULL DEFAULT NOW(),
    last_result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_error TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_worker_heartbeats_seen
ON saas_worker_heartbeats (last_seen_at DESC);

ALTER TABLE saas_webhook_events
    ADD COLUMN IF NOT EXISTS correlation_id TEXT NOT NULL DEFAULT '';

ALTER TABLE saas_outbound_messages
    ADD COLUMN IF NOT EXISTS correlation_id TEXT NOT NULL DEFAULT '';

ALTER TABLE saas_trigger_scheduled_messages
    ADD COLUMN IF NOT EXISTS correlation_id TEXT NOT NULL DEFAULT '';

ALTER TABLE saas_ai_pending_replies
    ADD COLUMN IF NOT EXISTS correlation_id TEXT NOT NULL DEFAULT '';

ALTER TABLE saas_dead_letter_events
    ADD COLUMN IF NOT EXISTS correlation_id TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_saas_webhook_events_correlation
ON saas_webhook_events (correlation_id)
WHERE correlation_id <> '';

CREATE INDEX IF NOT EXISTS idx_saas_outbound_correlation
ON saas_outbound_messages (correlation_id)
WHERE correlation_id <> '';

CREATE INDEX IF NOT EXISTS idx_saas_dead_letter_correlation
ON saas_dead_letter_events (correlation_id)
WHERE correlation_id <> '';
