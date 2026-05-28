-- 040_saas_crm_commercial_phase5.sql
-- Phase 5 commercial CRM: custom fields, configurable pipeline, timeline and merge audit.

CREATE TABLE IF NOT EXISTS saas_crm_custom_fields (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    field_key TEXT NOT NULL,
    label TEXT NOT NULL,
    field_type TEXT NOT NULL DEFAULT 'text',
    options_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_required BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    display_order INTEGER NOT NULL DEFAULT 100,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_saas_crm_custom_fields_key CHECK (field_key ~ '^[a-z0-9_]{1,80}$'),
    CONSTRAINT chk_saas_crm_custom_fields_type CHECK (
        field_type IN ('text', 'number', 'select', 'multiselect', 'date', 'boolean', 'url', 'email', 'phone')
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_saas_crm_custom_fields_tenant_key
ON saas_crm_custom_fields (tenant_id, field_key);

CREATE INDEX IF NOT EXISTS idx_saas_crm_custom_fields_tenant_active
ON saas_crm_custom_fields (tenant_id, is_active, display_order, label);

CREATE TABLE IF NOT EXISTS saas_crm_pipelines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    name TEXT NOT NULL DEFAULT 'Pipeline comercial',
    industry_code TEXT NOT NULL DEFAULT 'general',
    is_default BOOLEAN NOT NULL DEFAULT TRUE,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_saas_crm_pipelines_default
ON saas_crm_pipelines (tenant_id)
WHERE is_default = TRUE;

CREATE UNIQUE INDEX IF NOT EXISTS uniq_saas_crm_pipelines_tenant_lower_name
ON saas_crm_pipelines (tenant_id, lower(name));

CREATE TABLE IF NOT EXISTS saas_crm_pipeline_stages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    pipeline_id UUID NOT NULL REFERENCES saas_crm_pipelines(id) ON DELETE CASCADE,
    stage_key TEXT NOT NULL,
    label TEXT NOT NULL,
    probability INTEGER NOT NULL DEFAULT 0,
    display_order INTEGER NOT NULL DEFAULT 100,
    is_won BOOLEAN NOT NULL DEFAULT FALSE,
    is_lost BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_saas_crm_pipeline_stage_key CHECK (stage_key ~ '^[a-z0-9_]{1,80}$'),
    CONSTRAINT chk_saas_crm_pipeline_stage_probability CHECK (probability >= 0 AND probability <= 100)
);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_saas_crm_pipeline_stages_key
ON saas_crm_pipeline_stages (tenant_id, pipeline_id, stage_key);

CREATE INDEX IF NOT EXISTS idx_saas_crm_pipeline_stages_active
ON saas_crm_pipeline_stages (tenant_id, pipeline_id, is_active, display_order);

CREATE TABLE IF NOT EXISTS saas_crm_timeline_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL REFERENCES saas_conversations(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL DEFAULT 'crm_event',
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    actor_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMP NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_crm_timeline_conversation
ON saas_crm_timeline_events (tenant_id, conversation_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_crm_timeline_type
ON saas_crm_timeline_events (tenant_id, event_type, occurred_at DESC);

CREATE TABLE IF NOT EXISTS saas_crm_merge_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    source_conversation_id UUID NULL REFERENCES saas_conversations(id) ON DELETE SET NULL,
    target_conversation_id UUID NULL REFERENCES saas_conversations(id) ON DELETE SET NULL,
    merged_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    reason TEXT NOT NULL DEFAULT '',
    source_snapshot_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    target_snapshot_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_crm_merge_events_tenant_created
ON saas_crm_merge_events (tenant_id, created_at DESC);

WITH created_pipelines AS (
    INSERT INTO saas_crm_pipelines (tenant_id, name, industry_code, is_default)
    SELECT t.id, 'Pipeline comercial', 'general', TRUE
    FROM saas_tenants t
    WHERE NOT EXISTS (
        SELECT 1
        FROM saas_crm_pipelines p
        WHERE p.tenant_id = t.id
          AND p.is_default = TRUE
    )
    RETURNING id, tenant_id
),
default_pipelines AS (
    SELECT id, tenant_id FROM created_pipelines
    UNION
    SELECT id, tenant_id
    FROM saas_crm_pipelines
    WHERE is_default = TRUE
)
INSERT INTO saas_crm_pipeline_stages (
    tenant_id,
    pipeline_id,
    stage_key,
    label,
    probability,
    display_order,
    is_won
)
SELECT
    p.tenant_id,
    p.id,
    s.stage_key,
    s.label,
    s.probability,
    s.display_order,
    s.is_won
FROM default_pipelines p
CROSS JOIN (
    VALUES
        ('contactado', 'Contactado', 10, 10, FALSE),
        ('interes', 'Interes', 30, 20, FALSE),
        ('intencion_compra', 'Intencion de compra', 55, 30, FALSE),
        ('pago_pendiente', 'Pago pendiente', 75, 40, FALSE),
        ('pago_confirmado', 'Pago confirmado', 100, 50, TRUE)
) AS s(stage_key, label, probability, display_order, is_won)
ON CONFLICT DO NOTHING;
