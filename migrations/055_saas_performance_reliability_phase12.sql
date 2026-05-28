-- 055_saas_performance_reliability_phase12.sql
-- Phase 12: Performance, Reliability & Scale control-plane.

CREATE TABLE IF NOT EXISTS saas_reliability_slo_policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    metric_key TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL DEFAULT '',
    comparison TEXT NOT NULL DEFAULT 'lte',
    target_value NUMERIC(18,6) NOT NULL DEFAULT 0,
    warn_threshold NUMERIC(18,6) NOT NULL DEFAULT 0,
    critical_threshold NUMERIC(18,6) NOT NULL DEFAULT 0,
    window_minutes INTEGER NOT NULL DEFAULT 15,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    source TEXT NOT NULL DEFAULT 'system',
    notes TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_reliability_slo_active
ON saas_reliability_slo_policies (is_active, metric_key);

CREATE TABLE IF NOT EXISTS saas_reliability_backpressure_policies (
    queue_key TEXT PRIMARY KEY,
    warn_backlog INTEGER NOT NULL DEFAULT 100,
    critical_backlog INTEGER NOT NULL DEFAULT 500,
    max_batch_size INTEGER NOT NULL DEFAULT 50,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    notes TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS saas_reliability_retention_policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_key TEXT NOT NULL UNIQUE,
    table_name TEXT NOT NULL,
    timestamp_column TEXT NOT NULL,
    retention_days INTEGER NOT NULL DEFAULT 180,
    batch_limit INTEGER NOT NULL DEFAULT 1000,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    dry_run_default BOOLEAN NOT NULL DEFAULT TRUE,
    last_run_at TIMESTAMP NULL,
    last_deleted_count INTEGER NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_reliability_retention_enabled
ON saas_reliability_retention_policies (enabled, policy_key);

CREATE TABLE IF NOT EXISTS saas_reliability_cleanup_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_key TEXT NOT NULL,
    table_name TEXT NOT NULL,
    dry_run BOOLEAN NOT NULL DEFAULT TRUE,
    status TEXT NOT NULL DEFAULT 'ok',
    matched_count INTEGER NOT NULL DEFAULT 0,
    deleted_count INTEGER NOT NULL DEFAULT 0,
    details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMP NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMP NULL
);

CREATE INDEX IF NOT EXISTS idx_saas_reliability_cleanup_runs_time
ON saas_reliability_cleanup_runs (started_at DESC, policy_key);

CREATE TABLE IF NOT EXISTS saas_reliability_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_key TEXT NOT NULL DEFAULT 'manual',
    status TEXT NOT NULL DEFAULT 'ok',
    slo_status TEXT NOT NULL DEFAULT 'ok',
    summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    queues_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    signals_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_reliability_snapshots_time
ON saas_reliability_snapshots (created_at DESC, snapshot_key);

CREATE TABLE IF NOT EXISTS saas_reliability_drills (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    drill_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ok',
    result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    initiated_by TEXT NOT NULL DEFAULT '',
    started_at TIMESTAMP NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMP NULL
);

CREATE INDEX IF NOT EXISTS idx_saas_reliability_drills_time
ON saas_reliability_drills (started_at DESC, drill_type);

INSERT INTO saas_reliability_slo_policies (
    metric_key, label, comparison, target_value, warn_threshold, critical_threshold, window_minutes, notes
)
VALUES
    ('db_probe_ms', 'DB probe latency', 'lte', 200, 500, 1500, 5, 'Readiness query latency in milliseconds.'),
    ('queue_backlog', 'Queue backlog', 'lte', 100, 500, 1500, 15, 'Total queued/pending runtime jobs.'),
    ('queue_error_total', 'Queue errors', 'lte', 0, 10, 50, 15, 'Failed/error/blocked runtime jobs.'),
    ('worker_fresh_ratio', 'Worker fresh ratio', 'gte', 1.0, 0.5, 0.1, 5, 'Fresh workers divided by total seen workers.'),
    ('ai_failure_rate_24h', 'AI failure rate 24h', 'lte', 0.02, 0.08, 0.20, 1440, 'AI Gateway failed runs divided by total runs.'),
    ('meta_error_total', 'Meta error total', 'lte', 0, 10, 50, 1440, 'Meta webhook/outbound/subscription/token error signals.')
ON CONFLICT (metric_key) DO NOTHING;

INSERT INTO saas_reliability_backpressure_policies (
    queue_key, warn_backlog, critical_backlog, max_batch_size, notes
)
VALUES
    ('outbound', 100, 500, 50, 'Outbound provider delivery queue.'),
    ('webhooks', 100, 500, 50, 'Inbound webhook ingestion queue.'),
    ('scheduled_triggers', 100, 500, 50, 'Scheduled trigger queue.'),
    ('ai_pending', 50, 250, 25, 'Pending AI replies queue.'),
    ('remarketing', 100, 500, 50, 'Remarketing enrollments due queue.'),
    ('agent_orchestrator', 50, 250, 25, 'Agent orchestration queue.')
ON CONFLICT (queue_key) DO NOTHING;

INSERT INTO saas_reliability_retention_policies (
    policy_key, table_name, timestamp_column, retention_days, batch_limit, enabled, dry_run_default, notes
)
VALUES
    ('dead_letter_resolved', 'saas_dead_letter_events', 'resolved_at', 90, 1000, FALSE, TRUE, 'Resolved dead-letter records only.'),
    ('webhook_processed', 'saas_webhook_events', 'processed_at', 180, 1000, FALSE, TRUE, 'Processed/ignored webhook events only.'),
    ('ai_gateway_runs', 'saas_ai_runs', 'created_at', 180, 1000, FALSE, TRUE, 'AI Gateway run history.'),
    ('intelligence_events', 'saas_intelligence_events', 'occurred_at', 365, 1000, FALSE, TRUE, 'Derived Intelligence event history.'),
    ('ecosystem_traces', 'saas_ai_ecosystem_traces', 'created_at', 180, 1000, FALSE, TRUE, 'AI Ecosystem trace records.'),
    ('operation_reports', 'saas_ai_operation_reports', 'created_at', 180, 1000, FALSE, TRUE, 'Autonomous Operations report history.')
ON CONFLICT (policy_key) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_saas_webhook_events_status_received
ON saas_webhook_events (status, received_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_webhook_events_provider_status_received
ON saas_webhook_events (provider, status, received_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_outbound_status_next
ON saas_outbound_messages (status, next_attempt_at, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_outbound_channel_status_updated
ON saas_outbound_messages (channel, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_trigger_sched_status_due
ON saas_trigger_scheduled_messages (status, run_at);

CREATE INDEX IF NOT EXISTS idx_saas_ai_pending_status_due
ON saas_ai_pending_replies (status, scheduled_at);

CREATE INDEX IF NOT EXISTS idx_saas_rmk_enroll_state_due
ON saas_remarketing_enrollments (state, next_run_at);

CREATE INDEX IF NOT EXISTS idx_saas_agent_orch_status_due
ON saas_ai_agent_orchestration_jobs (status, scheduled_at);

CREATE INDEX IF NOT EXISTS idx_saas_conversations_tenant_priority_updated
ON saas_conversations (tenant_id, priority, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_messages_tenant_direction_created
ON saas_messages (tenant_id, direction, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_intelligence_events_time
ON saas_intelligence_events (occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_audit_created
ON saas_audit_events (created_at DESC);
