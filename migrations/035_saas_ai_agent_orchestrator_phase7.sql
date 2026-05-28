-- Phase 7: real multi-agent orchestration runtime.
-- Creates queue, locks, handoffs and conflict audit tables.

CREATE TABLE IF NOT EXISTS saas_ai_agent_orchestration_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    source TEXT NOT NULL DEFAULT 'system',
    event_type TEXT NOT NULL DEFAULT 'agent.event',
    entity_type TEXT NOT NULL DEFAULT '',
    entity_id TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL DEFAULT '',
    lock_key TEXT NOT NULL DEFAULT '',
    source_agent_id UUID NULL REFERENCES saas_ai_agents(id) ON DELETE SET NULL,
    selected_agent_id UUID NULL REFERENCES saas_ai_agents(id) ON DELETE SET NULL,
    priority INTEGER NOT NULL DEFAULT 50,
    status TEXT NOT NULL DEFAULT 'queued',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    scheduled_at TIMESTAMP NOT NULL DEFAULT NOW(),
    locked_by TEXT NOT NULL DEFAULT '',
    locked_at TIMESTAMP NULL,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT NOT NULL DEFAULT '',
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP NULL
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_agent_orchestration_jobs_due
ON saas_ai_agent_orchestration_jobs (tenant_id, status, scheduled_at, priority DESC, created_at);

CREATE INDEX IF NOT EXISTS idx_saas_ai_agent_orchestration_jobs_lock
ON saas_ai_agent_orchestration_jobs (tenant_id, lock_key, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_ai_agent_locks (
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    lock_key TEXT NOT NULL,
    owner_agent_id UUID NULL REFERENCES saas_ai_agents(id) ON DELETE SET NULL,
    owner_job_id UUID NULL REFERENCES saas_ai_agent_orchestration_jobs(id) ON DELETE SET NULL,
    entity_type TEXT NOT NULL DEFAULT '',
    entity_id TEXT NOT NULL DEFAULT '',
    lock_scope TEXT NOT NULL DEFAULT 'orchestrator',
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    expires_at TIMESTAMP NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, lock_key)
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_agent_locks_expires
ON saas_ai_agent_locks (tenant_id, expires_at);

CREATE TABLE IF NOT EXISTS saas_ai_agent_handoffs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    source_agent_id UUID NULL REFERENCES saas_ai_agents(id) ON DELETE SET NULL,
    target_agent_id UUID NULL REFERENCES saas_ai_agents(id) ON DELETE SET NULL,
    job_id UUID NULL REFERENCES saas_ai_agent_orchestration_jobs(id) ON DELETE SET NULL,
    entity_type TEXT NOT NULL DEFAULT '',
    entity_id TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'proposed',
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    accepted_at TIMESTAMP NULL
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_agent_handoffs_tenant_status
ON saas_ai_agent_handoffs (tenant_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS saas_ai_agent_conflicts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    lock_key TEXT NOT NULL DEFAULT '',
    entity_type TEXT NOT NULL DEFAULT '',
    entity_id TEXT NOT NULL DEFAULT '',
    source_job_id UUID NULL REFERENCES saas_ai_agent_orchestration_jobs(id) ON DELETE SET NULL,
    existing_owner_agent_id UUID NULL REFERENCES saas_ai_agents(id) ON DELETE SET NULL,
    requested_agent_id UUID NULL REFERENCES saas_ai_agents(id) ON DELETE SET NULL,
    conflict_type TEXT NOT NULL DEFAULT 'lock_conflict',
    resolution_status TEXT NOT NULL DEFAULT 'open',
    details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMP NULL
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_agent_conflicts_tenant_status
ON saas_ai_agent_conflicts (tenant_id, resolution_status, created_at DESC);
