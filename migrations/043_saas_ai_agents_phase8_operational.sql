-- Phase 8 operational hardening for AI Agents.
-- Adds custom agents, rendered system prompts, preflight state, evals and
-- persistent AI ownership per conversation.

ALTER TABLE saas_ai_agents
    ADD COLUMN IF NOT EXISTS is_custom BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS base_template_type TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS system_prompt_template TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS system_prompt_variables_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS system_prompt_rendered TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS last_preflight_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS last_preflight_at TIMESTAMP NULL;

CREATE INDEX IF NOT EXISTS idx_saas_ai_agents_custom_status
    ON saas_ai_agents (tenant_id, is_custom, status, updated_at DESC);

ALTER TABLE saas_conversations
    ADD COLUMN IF NOT EXISTS assigned_ai_agent_id UUID NULL REFERENCES saas_ai_agents(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS ai_owner_mode TEXT NOT NULL DEFAULT 'general',
    ADD COLUMN IF NOT EXISTS ai_owner_locked_at TIMESTAMP NULL;

CREATE INDEX IF NOT EXISTS idx_saas_conversations_ai_agent
    ON saas_conversations (tenant_id, assigned_ai_agent_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_conversations_ai_owner_mode
    ON saas_conversations (tenant_id, ai_owner_mode, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_ai_agent_evals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    agent_id UUID NOT NULL REFERENCES saas_ai_agents(id) ON DELETE CASCADE,
    eval_type TEXT NOT NULL DEFAULT 'preflight',
    source TEXT NOT NULL DEFAULT 'system',
    score INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    checks_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_agent_evals_agent_created
    ON saas_ai_agent_evals (tenant_id, agent_id, created_at DESC);

UPDATE saas_ai_agent_plan_limits
SET allowed_agent_types_json =
    CASE
        WHEN allowed_agent_types_json ? 'custom' THEN allowed_agent_types_json
        ELSE allowed_agent_types_json || '["custom"]'::jsonb
    END,
    updated_at = NOW();
