-- 028_saas_ai_agents_registry.sql
-- Registro base para Scentra AI Agents y limites independientes por plan.

CREATE TABLE IF NOT EXISTS saas_ai_agent_plan_limits (
    plan_code TEXT PRIMARY KEY,
    max_ai_agents INTEGER NOT NULL DEFAULT 1,
    max_active_ai_agents INTEGER NOT NULL DEFAULT 1,
    max_memory_archives INTEGER NOT NULL DEFAULT 1,
    allowed_agent_types_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    builder_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    notes TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS saas_ai_agents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    agent_type TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    provider_policy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    personality_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    goals_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    rules_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    channels_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    tools_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    memory_policy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    approval_policy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_saas_ai_agents_tenant_type_lower_name
ON saas_ai_agents (tenant_id, agent_type, lower(name))
WHERE status <> 'archived';

CREATE INDEX IF NOT EXISTS idx_saas_ai_agents_tenant_status
ON saas_ai_agents (tenant_id, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_ai_agent_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    agent_id UUID NULL REFERENCES saas_ai_agents(id) ON DELETE CASCADE,
    actor_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_agent_events_tenant_created
ON saas_ai_agent_events (tenant_id, created_at DESC);

INSERT INTO saas_ai_agent_plan_limits (
    plan_code, max_ai_agents, max_active_ai_agents, max_memory_archives, allowed_agent_types_json, builder_enabled, notes, updated_at
)
VALUES
  ('demo', 2, 1, 2, '["advisor","sales","support","crm_intelligence","campaign_strategist","retention","operations","executive_summary","knowledge","workflow_architect"]'::jsonb, TRUE, 'Demo de 30 dias: explora AI Agents con ejecucion controlada.', NOW()),
  ('starter', 1, 1, 1, '["advisor","sales","support","crm_intelligence","campaign_strategist","retention","operations","executive_summary","knowledge","workflow_architect"]'::jsonb, TRUE, 'Plan starter: un agente AI activo.', NOW()),
  ('basic', 1, 1, 1, '["advisor","sales","support","crm_intelligence","campaign_strategist","retention","operations","executive_summary","knowledge","workflow_architect"]'::jsonb, TRUE, 'Plan basico: un agente AI activo.', NOW()),
  ('growth', 3, 3, 5, '["advisor","sales","support","crm_intelligence","campaign_strategist","retention","operations","executive_summary","knowledge","workflow_architect"]'::jsonb, TRUE, 'Growth: equipo pequeno con varios agentes AI.', NOW()),
  ('pro', 6, 6, 15, '["advisor","sales","support","crm_intelligence","campaign_strategist","retention","operations","executive_summary","knowledge","workflow_architect"]'::jsonb, TRUE, 'Pro: suite de agentes AI para operacion comercial.', NOW()),
  ('enterprise', 50, 50, 200, '["advisor","sales","support","crm_intelligence","campaign_strategist","retention","operations","executive_summary","knowledge","workflow_architect"]'::jsonb, TRUE, 'Enterprise: limites negociables y gobierno avanzado.', NOW())
ON CONFLICT (plan_code) DO NOTHING;
