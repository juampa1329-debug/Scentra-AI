-- 061_saas_vision_intelligence_phase24.sql
-- Phase 24.3: Vision Intelligence for image/document understanding and OCR-style extraction.
-- Tenant-scoped, explicit user action only; no automatic Meta sends, CRM mutation or web image search.

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

CREATE INDEX IF NOT EXISTS idx_saas_vision_intel_tenant_created
ON saas_vision_intelligence_analyses (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_vision_intel_conversation
ON saas_vision_intelligence_analyses (tenant_id, conversation_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_vision_intel_doc_type
ON saas_vision_intelligence_analyses (tenant_id, document_type, urgency, updated_at DESC);

UPDATE saas_plan_limits
SET feature_flags_json = COALESCE(feature_flags_json, '{}'::jsonb)
    || jsonb_build_object(
        'vision_intelligence', COALESCE((feature_flags_json ->> 'vision_intelligence')::boolean, false),
        'image_understanding', COALESCE((feature_flags_json ->> 'image_understanding')::boolean, false),
        'document_ocr', COALESCE((feature_flags_json ->> 'document_ocr')::boolean, false)
    ),
    updated_at = NOW();
