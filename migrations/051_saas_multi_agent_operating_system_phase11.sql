-- Phase 11 Multi-Agent Operating System.
-- Adds tenant-isolated control-plane tables for agent communication,
-- tool execution traces, event-driven subscriptions and runtime tracing.

CREATE TABLE IF NOT EXISTS saas_ai_agent_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    source_agent_id UUID NULL REFERENCES saas_ai_agents(id) ON DELETE SET NULL,
    target_agent_id UUID NULL REFERENCES saas_ai_agents(id) ON DELETE SET NULL,
    job_id UUID NULL REFERENCES saas_ai_agent_orchestration_jobs(id) ON DELETE SET NULL,
    message_type TEXT NOT NULL DEFAULT 'context',
    subject TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    priority INTEGER NOT NULL DEFAULT 50,
    status TEXT NOT NULL DEFAULT 'open',
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_agent_messages_tenant_status
    ON saas_ai_agent_messages (tenant_id, status, priority DESC, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_ai_agent_messages_agents
    ON saas_ai_agent_messages (tenant_id, source_agent_id, target_agent_id, created_at DESC);

CREATE TABLE IF NOT EXISTS saas_ai_agent_runtime_traces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    agent_id UUID NULL REFERENCES saas_ai_agents(id) ON DELETE SET NULL,
    job_id UUID NULL REFERENCES saas_ai_agent_orchestration_jobs(id) ON DELETE SET NULL,
    trace_type TEXT NOT NULL DEFAULT 'reasoning',
    trace_status TEXT NOT NULL DEFAULT 'completed',
    step_key TEXT NOT NULL DEFAULT '',
    provider_code TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    latency_ms INTEGER NOT NULL DEFAULT 0,
    tokens_total INTEGER NOT NULL DEFAULT 0,
    input_summary TEXT NOT NULL DEFAULT '',
    output_summary TEXT NOT NULL DEFAULT '',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_agent_runtime_traces_agent
    ON saas_ai_agent_runtime_traces (tenant_id, agent_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_ai_agent_runtime_traces_type
    ON saas_ai_agent_runtime_traces (tenant_id, trace_type, trace_status, created_at DESC);

CREATE TABLE IF NOT EXISTS saas_ai_agent_tool_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    agent_id UUID NOT NULL REFERENCES saas_ai_agents(id) ON DELETE CASCADE,
    action_draft_id UUID NULL REFERENCES saas_advisor_actions(id) ON DELETE SET NULL,
    tool_code TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending_approval',
    approval_status TEXT NOT NULL DEFAULT 'required',
    risk_level TEXT NOT NULL DEFAULT 'medium',
    input_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_text TEXT NOT NULL DEFAULT '',
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP NULL
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_agent_tool_runs_agent
    ON saas_ai_agent_tool_runs (tenant_id, agent_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_ai_agent_tool_runs_tool
    ON saas_ai_agent_tool_runs (tenant_id, tool_code, created_at DESC);

CREATE TABLE IF NOT EXISTS saas_ai_agent_event_subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    agent_type TEXT NOT NULL DEFAULT '',
    target_agent_id UUID NULL REFERENCES saas_ai_agents(id) ON DELETE SET NULL,
    channel TEXT NOT NULL DEFAULT 'global',
    mode TEXT NOT NULL DEFAULT 'queue',
    priority INTEGER NOT NULL DEFAULT 50,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    filters_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, event_type, agent_type, channel)
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_agent_event_subscriptions_enabled
    ON saas_ai_agent_event_subscriptions (tenant_id, enabled, event_type, priority DESC);

UPDATE saas_plan_limits
SET feature_flags_json =
    '{
      "multi_agent_os": false,
      "event_driven_agents": false,
      "agent_tool_tracing": false
    }'::jsonb || COALESCE(feature_flags_json, '{}'::jsonb),
    updated_at = NOW();
