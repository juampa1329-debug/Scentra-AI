-- 060_saas_voice_intelligence_phase24.sql
-- Phase 24.2: Voice Intelligence for audio transcription, summary, sentiment and intent.
-- Tenant-scoped, explicit user action only; no automatic Meta sends or autonomous CRM mutation.

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

CREATE INDEX IF NOT EXISTS idx_saas_voice_intel_tenant_created
ON saas_voice_intelligence_analyses (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_voice_intel_conversation
ON saas_voice_intelligence_analyses (tenant_id, conversation_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_voice_intel_sentiment_intent
ON saas_voice_intelligence_analyses (tenant_id, sentiment, intent, updated_at DESC);

UPDATE saas_plan_limits
SET feature_flags_json = COALESCE(feature_flags_json, '{}'::jsonb)
    || jsonb_build_object(
        'voice_intelligence', COALESCE((feature_flags_json ->> 'voice_intelligence')::boolean, false),
        'voice_transcription', COALESCE((feature_flags_json ->> 'voice_transcription')::boolean, false),
        'voice_sentiment_intent', COALESCE((feature_flags_json ->> 'voice_sentiment_intent')::boolean, false)
    ),
    updated_at = NOW();
