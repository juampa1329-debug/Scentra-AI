-- 029_social_comments_inbox.sql
-- Persistencia social para comentarios de Facebook/Instagram y entrenamiento IA.

CREATE TABLE IF NOT EXISTS social_posts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    provider TEXT NOT NULL DEFAULT 'meta',
    channel TEXT NOT NULL DEFAULT 'instagram',
    external_post_id TEXT NOT NULL,
    page_id TEXT NOT NULL DEFAULT '',
    instagram_business_account_id TEXT NOT NULL DEFAULT '',
    author_external_id TEXT NOT NULL DEFAULT '',
    caption TEXT NOT NULL DEFAULT '',
    post_type TEXT NOT NULL DEFAULT '',
    permalink_url TEXT NOT NULL DEFAULT '',
    media_url TEXT NOT NULL DEFAULT '',
    thumbnail_url TEXT NOT NULL DEFAULT '',
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    external_created_time TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, channel, external_post_id)
);

CREATE TABLE IF NOT EXISTS social_comments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    post_id UUID NULL REFERENCES social_posts(id) ON DELETE SET NULL,
    provider TEXT NOT NULL DEFAULT 'meta',
    channel TEXT NOT NULL DEFAULT 'instagram',
    external_comment_id TEXT NOT NULL,
    parent_comment_id TEXT NOT NULL DEFAULT '',
    author_external_id TEXT NOT NULL DEFAULT '',
    author_name TEXT NOT NULL DEFAULT '',
    author_username TEXT NOT NULL DEFAULT '',
    author_profile_pic TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    ai_status TEXT NOT NULL DEFAULT '',
    ai_suggestion TEXT NOT NULL DEFAULT '',
    last_reply_text TEXT NOT NULL DEFAULT '',
    last_reply_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    external_created_time TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, channel, external_comment_id)
);

CREATE TABLE IF NOT EXISTS comment_ai_settings (
    tenant_id UUID PRIMARY KEY REFERENCES saas_tenants(id) ON DELETE CASCADE,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    auto_generate BOOLEAN NOT NULL DEFAULT FALSE,
    auto_reply BOOLEAN NOT NULL DEFAULT FALSE,
    tone TEXT NOT NULL DEFAULT 'calido, breve y util',
    instructions TEXT NOT NULL DEFAULT '',
    blocked_words_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    escalation_keywords_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    provider_policy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_social_comments_tenant_status
ON social_comments (tenant_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_social_posts_tenant_updated
ON social_posts (tenant_id, updated_at DESC);

