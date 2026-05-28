-- 062_saas_web_image_search_intelligence_phase24.sql
-- Phase 24.4: Web and Image Search Intelligence with source tracking and human approval.
-- Search results are advisory review records; this migration does not add automatic sends,
-- CRM mutation, agent tool execution, or web crawling.

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

CREATE INDEX IF NOT EXISTS idx_saas_web_search_runs_tenant_created
ON saas_web_search_intelligence_runs (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_web_search_runs_conversation
ON saas_web_search_intelligence_runs (tenant_id, conversation_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_web_search_results_run_rank
ON saas_web_search_intelligence_results (run_id, rank ASC);

CREATE INDEX IF NOT EXISTS idx_saas_web_search_results_tenant_approval
ON saas_web_search_intelligence_results (tenant_id, approval_status, updated_at DESC);

UPDATE saas_plan_limits
SET feature_flags_json = COALESCE(feature_flags_json, '{}'::jsonb)
    || jsonb_build_object(
        'web_search_intelligence', COALESCE((feature_flags_json ->> 'web_search_intelligence')::boolean, false),
        'image_search_intelligence', COALESCE((feature_flags_json ->> 'image_search_intelligence')::boolean, false),
        'external_source_assist', COALESCE((feature_flags_json ->> 'external_source_assist')::boolean, false)
    ),
    updated_at = NOW();
