-- Phase 24.6 Multimodal Memory & Training Events.
-- Stores sanitized voice/vision/search/tool outputs as tenant-scoped memory,
-- RAG candidates and ML training signals. This migration does not add
-- automatic customer sends, autonomous CRM mutation or model training.

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

UPDATE saas_plan_limits
SET feature_flags_json =
    '{
      "multimodal_memory_events": false,
      "multimodal_training_events": false,
      "multimodal_rag_materialization": false,
      "multimodal_agent_memory": false
    }'::jsonb || COALESCE(feature_flags_json, '{}'::jsonb),
    updated_at = NOW();
