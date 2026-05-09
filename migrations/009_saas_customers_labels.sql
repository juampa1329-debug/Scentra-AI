-- 009_saas_customers_labels.sql
-- Extiende el CRM SaaS con ficha comercial y catalogo de etiquetas por empresa.

ALTER TABLE saas_conversations
    ADD COLUMN IF NOT EXISTS first_name TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS last_name TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS city TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS customer_type TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS interests TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS payment_status TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS payment_reference TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS crm_stage TEXT NOT NULL DEFAULT 'contactado',
    ADD COLUMN IF NOT EXISTS intent TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS profile_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS last_profiled_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS assigned_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_saas_conversations_tenant_stage
ON saas_conversations (tenant_id, crm_stage, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_conversations_tenant_payment
ON saas_conversations (tenant_id, payment_status, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_labels (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    color TEXT NOT NULL DEFAULT '#5eead4',
    description TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'general',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_saas_labels_tenant_lower_name
ON saas_labels (tenant_id, lower(name));

CREATE INDEX IF NOT EXISTS idx_saas_labels_tenant_active
ON saas_labels (tenant_id, is_active, name);

CREATE TABLE IF NOT EXISTS saas_conversation_labels (
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL REFERENCES saas_conversations(id) ON DELETE CASCADE,
    label_id UUID NOT NULL REFERENCES saas_labels(id) ON DELETE CASCADE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, conversation_id, label_id)
);

CREATE INDEX IF NOT EXISTS idx_saas_conversation_labels_label
ON saas_conversation_labels (tenant_id, label_id);
