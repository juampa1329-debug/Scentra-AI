-- 003_conversations_cutover.sql
-- Corte de conversations a modelo multi-tenant real si la tabla legacy existe.
-- En una instalacion SaaS limpia, la tabla legacy no existe y esta migracion se omite sin fallar.

DO $$
BEGIN
    IF to_regclass('public.conversations') IS NOT NULL THEN
        EXECUTE 'ALTER TABLE conversations DROP CONSTRAINT IF EXISTS conversations_pkey';
        EXECUTE 'ALTER TABLE conversations ADD CONSTRAINT conversations_pkey PRIMARY KEY (tenant_id, phone)';
    END IF;

    IF to_regclass('public.messages') IS NOT NULL THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_messages_tenant_phone ON messages (tenant_id, phone)';
    END IF;
END $$;
