-- 023_ai_gateway_core.sql
-- Catalogo AI Gateway, observabilidad de ejecuciones y base para agentes multi-modelo.

CREATE TABLE IF NOT EXISTS saas_ai_providers (
    provider_code TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    credential_key TEXT NOT NULL DEFAULT '',
    default_model TEXT NOT NULL DEFAULT '',
    capabilities_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS saas_ai_models (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider_code TEXT NOT NULL REFERENCES saas_ai_providers(provider_code) ON DELETE CASCADE,
    model_id TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    capabilities_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    context_window INTEGER NOT NULL DEFAULT 0,
    cost_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (provider_code, model_id)
);

CREATE TABLE IF NOT EXISTS saas_ai_routes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    route_code TEXT NOT NULL,
    task_type TEXT NOT NULL,
    primary_provider TEXT NOT NULL DEFAULT '',
    primary_model TEXT NOT NULL DEFAULT '',
    fallback_provider TEXT NOT NULL DEFAULT '',
    fallback_model TEXT NOT NULL DEFAULT '',
    policy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, route_code)
);

CREATE TABLE IF NOT EXISTS saas_ai_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    conversation_id UUID NULL,
    agent_type TEXT NOT NULL DEFAULT '',
    task_type TEXT NOT NULL DEFAULT '',
    route_code TEXT NOT NULL DEFAULT '',
    provider_code TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    credential_key TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'started',
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    fallback_used BOOLEAN NOT NULL DEFAULT FALSE,
    error_code TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_runs_tenant_created
ON saas_ai_runs (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_ai_runs_tenant_provider
ON saas_ai_runs (tenant_id, provider_code, status, created_at DESC);

CREATE TABLE IF NOT EXISTS saas_ai_tool_calls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    ai_run_id UUID NULL REFERENCES saas_ai_runs(id) ON DELETE SET NULL,
    tool_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    input_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    requires_approval BOOLEAN NOT NULL DEFAULT FALSE,
    approved_by UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    error TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_tool_calls_tenant_created
ON saas_ai_tool_calls (tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS saas_ai_recommendations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    ai_run_id UUID NULL REFERENCES saas_ai_runs(id) ON DELETE SET NULL,
    recommendation_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    action_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence NUMERIC(5,2) NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_ai_recommendations_tenant_status
ON saas_ai_recommendations (tenant_id, status, created_at DESC);

INSERT INTO saas_ai_providers (provider_code, display_name, credential_key, default_model, capabilities_json, metadata_json)
VALUES
    ('google', 'Google / Gemini', 'GOOGLE_AI_API_KEY', 'gemini-2.5-flash', '["generate","stream","structured_outputs","long_context","multimodal"]'::jsonb, '{"official": true}'::jsonb),
    ('groq', 'Groq', 'GROQ_API_KEY', 'llama-3.1-8b-instant', '["generate","structured_outputs","low_latency"]'::jsonb, '{}'::jsonb),
    ('mistral', 'Mistral', 'MISTRAL_API_KEY', 'mistral-small-latest', '["generate","structured_outputs","classification"]'::jsonb, '{"official": true}'::jsonb),
    ('openrouter', 'OpenRouter', 'OPENROUTER_API_KEY', 'google/gemini-2.5-flash', '["generate","structured_outputs","fallback_gateway","multi_model"]'::jsonb, '{"official": true}'::jsonb),
    ('kimi', 'Kimi / Moonshot AI', 'KIMI_API_KEY', 'kimi-k2.6', '["generate","stream","structured_outputs","reasoning","long_context","tool_calling"]'::jsonb, '{"official": true, "aliases": ["MOONSHOT_API_KEY"]}'::jsonb)
ON CONFLICT (provider_code)
DO UPDATE SET
    display_name = EXCLUDED.display_name,
    credential_key = EXCLUDED.credential_key,
    default_model = EXCLUDED.default_model,
    capabilities_json = EXCLUDED.capabilities_json,
    metadata_json = saas_ai_providers.metadata_json || EXCLUDED.metadata_json,
    updated_at = NOW();

INSERT INTO saas_ai_models (provider_code, model_id, display_name, capabilities_json, metadata_json)
VALUES
    ('google', 'gemini-2.5-flash', 'gemini-2.5-flash', '["generate","structured_outputs"]'::jsonb, '{"static": true}'::jsonb),
    ('google', 'gemini-2.5-pro', 'gemini-2.5-pro', '["generate","structured_outputs","reasoning"]'::jsonb, '{"static": true}'::jsonb),
    ('mistral', 'mistral-small-latest', 'mistral-small-latest', '["generate","classification"]'::jsonb, '{"static": true}'::jsonb),
    ('mistral', 'mistral-medium-latest', 'mistral-medium-latest', '["generate","classification"]'::jsonb, '{"static": true}'::jsonb),
    ('mistral', 'mistral-large-latest', 'mistral-large-latest', '["generate","reasoning"]'::jsonb, '{"static": true}'::jsonb),
    ('openrouter', 'google/gemini-2.5-flash', 'google/gemini-2.5-flash', '["generate","fallback_gateway"]'::jsonb, '{"static": true}'::jsonb),
    ('openrouter', 'openai/gpt-4o-mini', 'openai/gpt-4o-mini', '["generate","fallback_gateway"]'::jsonb, '{"static": true}'::jsonb),
    ('groq', 'llama-3.1-8b-instant', 'llama-3.1-8b-instant', '["generate","low_latency"]'::jsonb, '{"static": true}'::jsonb),
    ('groq', 'llama-3.1-70b-versatile', 'llama-3.1-70b-versatile', '["generate"]'::jsonb, '{"static": true}'::jsonb),
    ('kimi', 'kimi-k2.6', 'kimi-k2.6', '["generate","reasoning","long_context"]'::jsonb, '{"static": true}'::jsonb),
    ('kimi', 'kimi-k2', 'kimi-k2', '["generate","reasoning","long_context"]'::jsonb, '{"static": true}'::jsonb),
    ('kimi', 'moonshot-v1-8k', 'moonshot-v1-8k', '["generate"]'::jsonb, '{"static": true}'::jsonb),
    ('kimi', 'moonshot-v1-32k', 'moonshot-v1-32k', '["generate","long_context"]'::jsonb, '{"static": true}'::jsonb),
    ('kimi', 'moonshot-v1-128k', 'moonshot-v1-128k', '["generate","long_context"]'::jsonb, '{"static": true}'::jsonb)
ON CONFLICT (provider_code, model_id)
DO UPDATE SET
    display_name = EXCLUDED.display_name,
    capabilities_json = EXCLUDED.capabilities_json,
    metadata_json = saas_ai_models.metadata_json || EXCLUDED.metadata_json,
    updated_at = NOW();

INSERT INTO saas_ai_routes (route_code, task_type, primary_provider, primary_model, fallback_provider, fallback_model, policy_json)
VALUES
    ('conversation.sales', 'conversation_reply', 'google', 'gemini-2.5-flash', 'openrouter', 'google/gemini-2.5-flash', '{"requires_approval": false, "default_agent": "sales_agent"}'::jsonb),
    ('advisor.insights', 'advisor_insights', 'kimi', 'kimi-k2.6', 'google', 'gemini-2.5-pro', '{"requires_approval": false, "default_agent": "advisor_agent"}'::jsonb),
    ('crm.classification', 'crm_classification', 'mistral', 'mistral-small-latest', 'openrouter', 'openai/gpt-4o-mini', '{"requires_approval": false, "default_agent": "crm_enrichment_agent"}'::jsonb),
    ('summaries.executive', 'executive_summary', 'google', 'gemini-2.5-pro', 'kimi', 'kimi-k2.6', '{"requires_approval": false, "default_agent": "executive_summary_agent"}'::jsonb)
ON CONFLICT DO NOTHING;

