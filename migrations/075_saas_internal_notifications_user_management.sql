-- 075_saas_internal_notifications_user_management.sql
-- Internal SaaS communications and user-profile metadata.

ALTER TABLE saas_users
    ADD COLUMN IF NOT EXISTS profile_json JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS saas_system_notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sender_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    sender_platform_role TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    severity TEXT NOT NULL DEFAULT 'info',
    category TEXT NOT NULL DEFAULT 'system',
    audience_type TEXT NOT NULL DEFAULT 'selected',
    target_tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE SET NULL,
    target_roles_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ai_assisted BOOLEAN NOT NULL DEFAULT FALSE,
    email_copy BOOLEAN NOT NULL DEFAULT FALSE,
    status TEXT NOT NULL DEFAULT 'sent',
    sent_at TIMESTAMP NULL DEFAULT NOW(),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS saas_system_notification_recipients (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    notification_id UUID NOT NULL REFERENCES saas_system_notifications(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES saas_users(id) ON DELETE CASCADE,
    membership_role TEXT NOT NULL DEFAULT '',
    delivery_channel TEXT NOT NULL DEFAULT 'in_app',
    popup_until_read BOOLEAN NOT NULL DEFAULT TRUE,
    pinned_until_read BOOLEAN NOT NULL DEFAULT TRUE,
    email_sent BOOLEAN NOT NULL DEFAULT FALSE,
    email_error TEXT NOT NULL DEFAULT '',
    read_at TIMESTAMP NULL,
    dismissed_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (notification_id, tenant_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_saas_system_notifications_created
ON saas_system_notifications (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_system_notifications_sender
ON saas_system_notifications (sender_user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_system_notification_recipients_user
ON saas_system_notification_recipients (tenant_id, user_id, read_at, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_system_notification_recipients_notification
ON saas_system_notification_recipients (notification_id, created_at DESC);
