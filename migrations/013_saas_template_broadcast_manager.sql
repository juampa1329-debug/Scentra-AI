-- 013_saas_template_broadcast_manager.sql
-- Separa plantillas internas CRM de plantillas oficiales Meta/WhatsApp para broadcast.

ALTER TABLE saas_message_templates
    ADD COLUMN IF NOT EXISTS render_mode TEXT NOT NULL DEFAULT 'chat',
    ADD COLUMN IF NOT EXISTS template_scope TEXT NOT NULL DEFAULT 'crm',
    ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'internal';

ALTER TABLE saas_crm_triggers
    ADD COLUMN IF NOT EXISTS flow_event TEXT NOT NULL DEFAULT 'received',
    ADD COLUMN IF NOT EXISTS assistant_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS assistant_message_type TEXT NOT NULL DEFAULT 'auto',
    ADD COLUMN IF NOT EXISTS block_ai BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS stop_on_match BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS only_when_no_takeover BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS last_run_at TIMESTAMP NULL;

CREATE TABLE IF NOT EXISTS saas_media_assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    kind TEXT NOT NULL DEFAULT 'file',
    filename TEXT NOT NULL DEFAULT '',
    content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    byte_size INTEGER NOT NULL DEFAULT 0,
    data BYTEA NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_media_assets_tenant_kind
ON saas_media_assets (tenant_id, kind, created_at DESC);

CREATE TABLE IF NOT EXISTS saas_meta_message_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    provider TEXT NOT NULL DEFAULT 'meta',
    meta_template_id TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'es',
    category TEXT NOT NULL DEFAULT 'MARKETING',
    status TEXT NOT NULL DEFAULT 'pending',
    quality_score TEXT NOT NULL DEFAULT '',
    header_type TEXT NOT NULL DEFAULT '',
    header_text TEXT NOT NULL DEFAULT '',
    header_media_handle TEXT NOT NULL DEFAULT '',
    body_text TEXT NOT NULL DEFAULT '',
    footer_text TEXT NOT NULL DEFAULT '',
    buttons_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    components_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    allow_category_change BOOLEAN NOT NULL DEFAULT TRUE,
    provider_response_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    rejection_reason TEXT NOT NULL DEFAULT '',
    submitted_at TIMESTAMP NULL,
    approved_at TIMESTAMP NULL,
    rejected_at TIMESTAMP NULL,
    last_sync_at TIMESTAMP NULL,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, provider, name, language)
);

CREATE INDEX IF NOT EXISTS idx_saas_meta_templates_tenant_status
ON saas_meta_message_templates (tenant_id, provider, status, updated_at DESC);

ALTER TABLE saas_broadcasts
    ADD COLUMN IF NOT EXISTS meta_template_id UUID NULL REFERENCES saas_meta_message_templates(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS meta_template_name TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS meta_template_language TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS meta_template_category TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS meta_template_body TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_saas_broadcasts_meta_template
ON saas_broadcasts (tenant_id, meta_template_id);
