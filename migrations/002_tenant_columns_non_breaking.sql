-- 002_tenant_columns_non_breaking.sql
-- Tenantizacion inicial compatible con tablas legacy si existen.
-- En una instalacion SaaS limpia, estas tablas pueden no existir; en ese caso se omiten sin fallar.

-- 1) Crear tenant legacy para mapear datos existentes
INSERT INTO saas_tenants (id, slug, name, status, plan_code, timezone, locale)
VALUES ('00000000-0000-0000-0000-000000000001', 'legacy', 'Legacy Tenant', 'active', 'legacy', 'America/Bogota', 'es-CO')
ON CONFLICT (slug) DO NOTHING;

CREATE OR REPLACE FUNCTION _saas_tenantize_legacy_table(p_table_name TEXT, p_index_sql TEXT[])
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    table_ref regclass;
    index_sql TEXT;
BEGIN
    table_ref := to_regclass(format('public.%I', p_table_name));
    IF table_ref IS NULL THEN
        RETURN;
    END IF;

    EXECUTE format('ALTER TABLE %s ADD COLUMN IF NOT EXISTS tenant_id UUID', table_ref);
    EXECUTE format(
        'UPDATE %s SET tenant_id = %L WHERE tenant_id IS NULL',
        table_ref,
        '00000000-0000-0000-0000-000000000001'
    );
    EXECUTE format('ALTER TABLE %s ALTER COLUMN tenant_id SET NOT NULL', table_ref);

    FOREACH index_sql IN ARRAY p_index_sql LOOP
        IF COALESCE(index_sql, '') <> '' THEN
            EXECUTE index_sql;
        END IF;
    END LOOP;
END;
$$;

-- 2) Tablas core CRM
SELECT _saas_tenantize_legacy_table(
    'conversations',
    ARRAY[
        'CREATE INDEX IF NOT EXISTS idx_conversations_tenant_updated ON conversations (tenant_id, updated_at DESC)'
    ]
);

SELECT _saas_tenantize_legacy_table(
    'messages',
    ARRAY[
        'CREATE INDEX IF NOT EXISTS idx_messages_tenant_created ON messages (tenant_id, created_at DESC)',
        'CREATE INDEX IF NOT EXISTS idx_messages_tenant_phone_created ON messages (tenant_id, phone, created_at DESC)'
    ]
);

-- 3) Campanas y automatizaciones
SELECT _saas_tenantize_legacy_table(
    'campaigns',
    ARRAY[
        'CREATE INDEX IF NOT EXISTS idx_campaigns_tenant_created ON campaigns (tenant_id, created_at DESC)'
    ]
);

SELECT _saas_tenantize_legacy_table(
    'campaign_recipients',
    ARRAY[
        'CREATE INDEX IF NOT EXISTS idx_campaign_recipients_tenant ON campaign_recipients (tenant_id)'
    ]
);

SELECT _saas_tenantize_legacy_table(
    'automation_triggers',
    ARRAY[
        'CREATE INDEX IF NOT EXISTS idx_automation_triggers_tenant ON automation_triggers (tenant_id)'
    ]
);

SELECT _saas_tenantize_legacy_table(
    'trigger_executions',
    ARRAY[
        'CREATE INDEX IF NOT EXISTS idx_trigger_executions_tenant_created ON trigger_executions (tenant_id, created_at DESC)'
    ]
);

SELECT _saas_tenantize_legacy_table(
    'trigger_scheduled_messages',
    ARRAY[
        'CREATE INDEX IF NOT EXISTS idx_trigger_scheduled_tenant_due ON trigger_scheduled_messages (tenant_id, send_at)'
    ]
);

-- 4) Remarketing
SELECT _saas_tenantize_legacy_table(
    'remarketing_flows',
    ARRAY[
        'CREATE INDEX IF NOT EXISTS idx_remarketing_flows_tenant ON remarketing_flows (tenant_id)'
    ]
);

SELECT _saas_tenantize_legacy_table(
    'remarketing_steps',
    ARRAY[
        'CREATE INDEX IF NOT EXISTS idx_remarketing_steps_tenant ON remarketing_steps (tenant_id)'
    ]
);

SELECT _saas_tenantize_legacy_table(
    'remarketing_enrollments',
    ARRAY[
        'CREATE INDEX IF NOT EXISTS idx_remarketing_enrollments_tenant ON remarketing_enrollments (tenant_id)'
    ]
);

-- 5) Social route tables
SELECT _saas_tenantize_legacy_table(
    'social_webhook_events',
    ARRAY[
        'CREATE INDEX IF NOT EXISTS idx_social_webhook_events_tenant_created ON social_webhook_events (tenant_id, created_at DESC)'
    ]
);

SELECT _saas_tenantize_legacy_table(
    'social_comments',
    ARRAY[
        'CREATE INDEX IF NOT EXISTS idx_social_comments_tenant_created ON social_comments (tenant_id, created_at DESC)'
    ]
);

SELECT _saas_tenantize_legacy_table(
    'meta_lead_events',
    ARRAY[
        'CREATE INDEX IF NOT EXISTS idx_meta_lead_events_tenant_created ON meta_lead_events (tenant_id, created_at DESC)'
    ]
);

DROP FUNCTION IF EXISTS _saas_tenantize_legacy_table(TEXT, TEXT[]);
