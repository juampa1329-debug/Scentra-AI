-- 034_saas_ai_agents_phase6_governance.sql
-- Fase 6: gobierno AI, memoria colectiva y orquestacion multiagente.

CREATE TABLE IF NOT EXISTS saas_ai_agent_collective_memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    source_agent_id UUID NULL REFERENCES saas_ai_agents(id) ON DELETE SET NULL,
    source_agent_type TEXT NOT NULL DEFAULT '',
    memory_scope TEXT NOT NULL DEFAULT 'tenant',
    memory_type TEXT NOT NULL DEFAULT 'fact',
    title TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    confidence_score INTEGER NOT NULL DEFAULT 80,
    visibility TEXT NOT NULL DEFAULT 'agents',
    tags_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    expires_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_agent_collective_memory_tenant_updated
ON saas_ai_agent_collective_memory (tenant_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_ai_agent_collective_memory_type
ON saas_ai_agent_collective_memory (tenant_id, memory_type, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_ai_agent_prompt_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    agent_id UUID NULL REFERENCES saas_ai_agents(id) ON DELETE CASCADE,
    agent_type TEXT NOT NULL DEFAULT '',
    version_label TEXT NOT NULL DEFAULT '',
    prompt_text TEXT NOT NULL DEFAULT '',
    variables_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'draft',
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    activated_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_agent_prompt_versions_tenant_agent
ON saas_ai_agent_prompt_versions (tenant_id, agent_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_ai_agent_tool_approvals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    agent_id UUID NULL REFERENCES saas_ai_agents(id) ON DELETE SET NULL,
    tool_code TEXT NOT NULL DEFAULT '',
    action_type TEXT NOT NULL DEFAULT '',
    target_module TEXT NOT NULL DEFAULT '',
    requested_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    risk_level TEXT NOT NULL DEFAULT 'medium',
    status TEXT NOT NULL DEFAULT 'pending',
    requested_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    decided_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    decision_note TEXT NOT NULL DEFAULT '',
    decided_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_agent_tool_approvals_tenant_status
ON saas_ai_agent_tool_approvals (tenant_id, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_ai_agent_budget_policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    agent_id UUID NOT NULL REFERENCES saas_ai_agents(id) ON DELETE CASCADE,
    monthly_token_budget INTEGER NOT NULL DEFAULT 250000,
    monthly_cost_cents INTEGER NOT NULL DEFAULT 2000,
    hard_stop BOOLEAN NOT NULL DEFAULT FALSE,
    warning_threshold_pct INTEGER NOT NULL DEFAULT 80,
    updated_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, agent_id)
);

CREATE TABLE IF NOT EXISTS saas_ai_agent_coordination_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    source_agent_id UUID NULL REFERENCES saas_ai_agents(id) ON DELETE SET NULL,
    target_agent_id UUID NULL REFERENCES saas_ai_agents(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL DEFAULT 'coordination.note',
    summary TEXT NOT NULL DEFAULT '',
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'open',
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_agent_coordination_events_tenant_created
ON saas_ai_agent_coordination_events (tenant_id, created_at DESC);

UPDATE saas_ai_agent_plan_limits
SET allowed_agent_types_json = allowed_agent_types_json || '["teacher"]'::jsonb,
    updated_at = NOW()
WHERE NOT (allowed_agent_types_json ? 'teacher');
