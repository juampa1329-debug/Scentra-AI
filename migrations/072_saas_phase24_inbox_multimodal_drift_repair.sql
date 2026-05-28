-- 072_saas_phase24_inbox_multimodal_drift_repair.sql
-- Production drift repair for Phase 24 Inbox multimodal read paths.
-- Keeps behavior unchanged; creates/adds only missing tables/columns used by:
-- - /saas/v1/media/search/runs
-- - /saas/v1/agents/multimodal-memory/events
-- - Inbox audio/image/document media analysis cards

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS saas_intelligence_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL DEFAULT '',
    entity_type TEXT NOT NULL DEFAULT '',
    entity_id TEXT NOT NULL DEFAULT '',
    conversation_id UUID NULL REFERENCES saas_conversations(id) ON DELETE SET NULL,
    customer_key TEXT NOT NULL DEFAULT '',
    occurred_at TIMESTAMP NOT NULL DEFAULT NOW(),
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    correlation_id TEXT NOT NULL DEFAULT '',
    replay_key TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

ALTER TABLE saas_intelligence_events
    ADD COLUMN IF NOT EXISTS event_type TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS entity_type TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS entity_id TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS conversation_id UUID NULL REFERENCES saas_conversations(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS customer_key TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS occurred_at TIMESTAMP NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS correlation_id TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS replay_key TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_saas_intelligence_events_tenant_type_time
ON saas_intelligence_events (tenant_id, event_type, occurred_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS ux_saas_intelligence_events_replay_key
ON saas_intelligence_events (tenant_id, replay_key)
WHERE replay_key <> '';

CREATE TABLE IF NOT EXISTS saas_knowledge_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL DEFAULT 'note',
    name TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    filename TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    content_hash TEXT NOT NULL DEFAULT '',
    chunk_count INTEGER NOT NULL DEFAULT 0,
    last_indexed_at TIMESTAMP NULL,
    expires_at TIMESTAMP NULL,
    error TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

ALTER TABLE saas_knowledge_sources
    ADD COLUMN IF NOT EXISTS source_type TEXT NOT NULL DEFAULT 'note',
    ADD COLUMN IF NOT EXISTS name TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS title TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS url TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS filename TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS content TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active',
    ADD COLUMN IF NOT EXISTS metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS content_hash TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS chunk_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_indexed_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS error TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_saas_knowledge_tenant_status
ON saas_knowledge_sources (tenant_id, status, updated_at DESC);

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

ALTER TABLE saas_ai_agent_collective_memory
    ADD COLUMN IF NOT EXISTS source_agent_id UUID NULL REFERENCES saas_ai_agents(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS source_agent_type TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS memory_scope TEXT NOT NULL DEFAULT 'tenant',
    ADD COLUMN IF NOT EXISTS memory_type TEXT NOT NULL DEFAULT 'fact',
    ADD COLUMN IF NOT EXISTS title TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS content TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS confidence_score INTEGER NOT NULL DEFAULT 80,
    ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'agents',
    ADD COLUMN IF NOT EXISTS tags_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_saas_ai_agent_collective_memory_tenant_updated
ON saas_ai_agent_collective_memory (tenant_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_ai_agent_collective_memory_type
ON saas_ai_agent_collective_memory (tenant_id, memory_type, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_voice_intelligence_analyses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL REFERENCES saas_conversations(id) ON DELETE CASCADE,
    message_id UUID NOT NULL REFERENCES saas_messages(id) ON DELETE CASCADE,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    media_id TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'inbox_audio',
    provider_code TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    ai_gateway_run_id UUID NULL REFERENCES saas_ai_runs(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'completed',
    transcript TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    sentiment TEXT NOT NULL DEFAULT 'neutral',
    sentiment_score NUMERIC(6,4) NOT NULL DEFAULT 0,
    intent TEXT NOT NULL DEFAULT 'other',
    intent_label TEXT NOT NULL DEFAULT '',
    urgency TEXT NOT NULL DEFAULT 'low',
    language TEXT NOT NULL DEFAULT '',
    confidence NUMERIC(6,4) NOT NULL DEFAULT 0,
    analysis_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, message_id)
);

ALTER TABLE saas_voice_intelligence_analyses
    ADD COLUMN IF NOT EXISTS tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS conversation_id UUID NULL REFERENCES saas_conversations(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS message_id UUID NULL REFERENCES saas_messages(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS media_id TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'inbox_audio',
    ADD COLUMN IF NOT EXISTS provider_code TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS model TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS ai_gateway_run_id UUID NULL REFERENCES saas_ai_runs(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'completed',
    ADD COLUMN IF NOT EXISTS transcript TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS summary TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS sentiment TEXT NOT NULL DEFAULT 'neutral',
    ADD COLUMN IF NOT EXISTS sentiment_score NUMERIC(6,4) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS intent TEXT NOT NULL DEFAULT 'other',
    ADD COLUMN IF NOT EXISTS intent_label TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS urgency TEXT NOT NULL DEFAULT 'low',
    ADD COLUMN IF NOT EXISTS language TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS confidence NUMERIC(6,4) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS analysis_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT NOW();

CREATE UNIQUE INDEX IF NOT EXISTS ux_saas_voice_intelligence_tenant_message
ON saas_voice_intelligence_analyses (tenant_id, message_id)
WHERE tenant_id IS NOT NULL AND message_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_saas_voice_intel_tenant_created
ON saas_voice_intelligence_analyses (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_voice_intel_conversation
ON saas_voice_intelligence_analyses (tenant_id, conversation_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_vision_intelligence_analyses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL REFERENCES saas_conversations(id) ON DELETE CASCADE,
    message_id UUID NOT NULL REFERENCES saas_messages(id) ON DELETE CASCADE,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    media_id TEXT NOT NULL DEFAULT '',
    media_kind TEXT NOT NULL DEFAULT 'image',
    source TEXT NOT NULL DEFAULT 'inbox_media',
    provider_code TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    ai_gateway_run_id UUID NULL REFERENCES saas_ai_runs(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'completed',
    visual_description TEXT NOT NULL DEFAULT '',
    extracted_text TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    document_type TEXT NOT NULL DEFAULT 'unknown',
    sentiment TEXT NOT NULL DEFAULT 'neutral',
    sentiment_score NUMERIC(6,4) NOT NULL DEFAULT 0,
    intent TEXT NOT NULL DEFAULT 'other',
    intent_label TEXT NOT NULL DEFAULT '',
    urgency TEXT NOT NULL DEFAULT 'low',
    language TEXT NOT NULL DEFAULT '',
    confidence NUMERIC(6,4) NOT NULL DEFAULT 0,
    entities_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    topics_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    product_hints_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    moderation_flags_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    analysis_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, message_id)
);

ALTER TABLE saas_vision_intelligence_analyses
    ADD COLUMN IF NOT EXISTS tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS conversation_id UUID NULL REFERENCES saas_conversations(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS message_id UUID NULL REFERENCES saas_messages(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS media_id TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS media_kind TEXT NOT NULL DEFAULT 'image',
    ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'inbox_media',
    ADD COLUMN IF NOT EXISTS provider_code TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS model TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS ai_gateway_run_id UUID NULL REFERENCES saas_ai_runs(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'completed',
    ADD COLUMN IF NOT EXISTS visual_description TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS extracted_text TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS summary TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS document_type TEXT NOT NULL DEFAULT 'unknown',
    ADD COLUMN IF NOT EXISTS sentiment TEXT NOT NULL DEFAULT 'neutral',
    ADD COLUMN IF NOT EXISTS sentiment_score NUMERIC(6,4) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS intent TEXT NOT NULL DEFAULT 'other',
    ADD COLUMN IF NOT EXISTS intent_label TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS urgency TEXT NOT NULL DEFAULT 'low',
    ADD COLUMN IF NOT EXISTS language TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS confidence NUMERIC(6,4) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS entities_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS topics_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS product_hints_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS moderation_flags_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS analysis_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT NOW();

CREATE UNIQUE INDEX IF NOT EXISTS ux_saas_vision_intelligence_tenant_message
ON saas_vision_intelligence_analyses (tenant_id, message_id)
WHERE tenant_id IS NOT NULL AND message_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_saas_vision_intel_tenant_created
ON saas_vision_intelligence_analyses (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_vision_intel_conversation
ON saas_vision_intelligence_analyses (tenant_id, conversation_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_vision_intel_doc_type
ON saas_vision_intelligence_analyses (tenant_id, document_type, urgency, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_web_search_intelligence_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    conversation_id UUID NULL REFERENCES saas_conversations(id) ON DELETE SET NULL,
    message_id UUID NULL REFERENCES saas_messages(id) ON DELETE SET NULL,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    query TEXT NOT NULL DEFAULT '',
    search_type TEXT NOT NULL DEFAULT 'mixed',
    provider_code TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'completed',
    access_mode TEXT NOT NULL DEFAULT 'demo',
    result_count INTEGER NOT NULL DEFAULT 0,
    approved_count INTEGER NOT NULL DEFAULT 0,
    blocked_count INTEGER NOT NULL DEFAULT 0,
    summary TEXT NOT NULL DEFAULT '',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

ALTER TABLE saas_web_search_intelligence_runs
    ADD COLUMN IF NOT EXISTS tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS conversation_id UUID NULL REFERENCES saas_conversations(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS message_id UUID NULL REFERENCES saas_messages(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS query TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS search_type TEXT NOT NULL DEFAULT 'mixed',
    ADD COLUMN IF NOT EXISTS provider_code TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'completed',
    ADD COLUMN IF NOT EXISTS access_mode TEXT NOT NULL DEFAULT 'demo',
    ADD COLUMN IF NOT EXISTS result_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS approved_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS blocked_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS summary TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT NOW();

CREATE TABLE IF NOT EXISTS saas_web_search_intelligence_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    run_id UUID NOT NULL REFERENCES saas_web_search_intelligence_runs(id) ON DELETE CASCADE,
    result_type TEXT NOT NULL DEFAULT 'web',
    title TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    display_url TEXT NOT NULL DEFAULT '',
    snippet TEXT NOT NULL DEFAULT '',
    source_name TEXT NOT NULL DEFAULT '',
    image_url TEXT NOT NULL DEFAULT '',
    thumbnail_url TEXT NOT NULL DEFAULT '',
    license_label TEXT NOT NULL DEFAULT '',
    license_details_url TEXT NOT NULL DEFAULT '',
    width INTEGER NOT NULL DEFAULT 0,
    height INTEGER NOT NULL DEFAULT 0,
    rank INTEGER NOT NULL DEFAULT 0,
    safety_status TEXT NOT NULL DEFAULT 'pending_review',
    approval_status TEXT NOT NULL DEFAULT 'pending',
    approved_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    approved_at TIMESTAMP NULL,
    rejected_reason TEXT NOT NULL DEFAULT '',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

ALTER TABLE saas_web_search_intelligence_results
    ADD COLUMN IF NOT EXISTS tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS run_id UUID NULL REFERENCES saas_web_search_intelligence_runs(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS result_type TEXT NOT NULL DEFAULT 'web',
    ADD COLUMN IF NOT EXISTS title TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS url TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS display_url TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS snippet TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS source_name TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS image_url TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS thumbnail_url TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS license_label TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS license_details_url TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS width INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS height INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS rank INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS safety_status TEXT NOT NULL DEFAULT 'pending_review',
    ADD COLUMN IF NOT EXISTS approval_status TEXT NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS approved_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS rejected_reason TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_saas_web_search_runs_tenant_created
ON saas_web_search_intelligence_runs (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_web_search_runs_conversation
ON saas_web_search_intelligence_runs (tenant_id, conversation_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_web_search_results_run_rank
ON saas_web_search_intelligence_results (run_id, rank ASC);

CREATE INDEX IF NOT EXISTS idx_saas_web_search_results_tenant_approval
ON saas_web_search_intelligence_results (tenant_id, approval_status, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_multimodal_memory_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    conversation_id UUID NULL REFERENCES saas_conversations(id) ON DELETE SET NULL,
    message_id UUID NULL REFERENCES saas_messages(id) ON DELETE SET NULL,
    agent_id UUID NULL REFERENCES saas_ai_agents(id) ON DELETE SET NULL,
    source_kind TEXT NOT NULL DEFAULT '',
    source_id TEXT NOT NULL DEFAULT '',
    event_type TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'ready',
    privacy_level TEXT NOT NULL DEFAULT 'tenant_private',
    approval_status TEXT NOT NULL DEFAULT 'not_required',
    eligible_for_training BOOLEAN NOT NULL DEFAULT TRUE,
    eligible_for_rag BOOLEAN NOT NULL DEFAULT FALSE,
    eligible_for_agent_memory BOOLEAN NOT NULL DEFAULT TRUE,
    memory_text TEXT NOT NULL DEFAULT '',
    rag_text TEXT NOT NULL DEFAULT '',
    training_features_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    training_labels_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    safety_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    intelligence_event_id UUID NULL REFERENCES saas_intelligence_events(id) ON DELETE SET NULL,
    knowledge_source_id UUID NULL REFERENCES saas_knowledge_sources(id) ON DELETE SET NULL,
    collective_memory_id UUID NULL REFERENCES saas_ai_agent_collective_memory(id) ON DELETE SET NULL,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    materialized_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    materialized_at TIMESTAMP NULL,
    replay_key TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

ALTER TABLE saas_multimodal_memory_events
    ADD COLUMN IF NOT EXISTS tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS conversation_id UUID NULL REFERENCES saas_conversations(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS message_id UUID NULL REFERENCES saas_messages(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS agent_id UUID NULL REFERENCES saas_ai_agents(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS source_kind TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS source_id TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS event_type TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'ready',
    ADD COLUMN IF NOT EXISTS privacy_level TEXT NOT NULL DEFAULT 'tenant_private',
    ADD COLUMN IF NOT EXISTS approval_status TEXT NOT NULL DEFAULT 'not_required',
    ADD COLUMN IF NOT EXISTS eligible_for_training BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS eligible_for_rag BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS eligible_for_agent_memory BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS memory_text TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS rag_text TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS training_features_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS training_labels_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS source_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS safety_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS intelligence_event_id UUID NULL REFERENCES saas_intelligence_events(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS knowledge_source_id UUID NULL REFERENCES saas_knowledge_sources(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS collective_memory_id UUID NULL REFERENCES saas_ai_agent_collective_memory(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS materialized_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS materialized_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS replay_key TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT NOW();

CREATE UNIQUE INDEX IF NOT EXISTS ux_saas_multimodal_memory_events_replay
ON saas_multimodal_memory_events (tenant_id, replay_key)
WHERE replay_key <> '';

CREATE INDEX IF NOT EXISTS idx_saas_multimodal_memory_events_tenant_created
ON saas_multimodal_memory_events (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_multimodal_memory_events_conversation
ON saas_multimodal_memory_events (tenant_id, conversation_id, updated_at DESC)
WHERE conversation_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_saas_multimodal_memory_events_agent
ON saas_multimodal_memory_events (tenant_id, agent_id, updated_at DESC)
WHERE agent_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_saas_multimodal_memory_events_training
ON saas_multimodal_memory_events (tenant_id, eligible_for_training, event_type, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_multimodal_memory_events_rag
ON saas_multimodal_memory_events (tenant_id, eligible_for_rag, approval_status, updated_at DESC);
