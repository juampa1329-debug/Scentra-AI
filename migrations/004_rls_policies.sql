-- 004_rls_policies.sql
-- Activa RLS para aislamiento por tenant.
-- Requiere que la app establezca: SET app.current_tenant = '<uuid>';

CREATE OR REPLACE FUNCTION saas_current_tenant() RETURNS uuid
LANGUAGE sql
STABLE
AS $$
    SELECT NULLIF(current_setting('app.current_tenant', true), '')::uuid
$$;

DO $$
BEGIN
    IF to_regclass('public.conversations') IS NOT NULL THEN
        EXECUTE 'ALTER TABLE public.conversations ENABLE ROW LEVEL SECURITY';
        EXECUTE 'ALTER TABLE public.conversations FORCE ROW LEVEL SECURITY';
        IF NOT EXISTS (
            SELECT 1 FROM pg_policies
            WHERE schemaname = 'public'
              AND tablename = 'conversations'
              AND policyname = 'conversations_tenant_policy'
        ) THEN
            EXECUTE 'CREATE POLICY conversations_tenant_policy ON public.conversations
                     USING (tenant_id = saas_current_tenant())
                     WITH CHECK (tenant_id = saas_current_tenant())';
        END IF;
    END IF;

    IF to_regclass('public.messages') IS NOT NULL THEN
        EXECUTE 'ALTER TABLE public.messages ENABLE ROW LEVEL SECURITY';
        EXECUTE 'ALTER TABLE public.messages FORCE ROW LEVEL SECURITY';
        IF NOT EXISTS (
            SELECT 1 FROM pg_policies
            WHERE schemaname = 'public'
              AND tablename = 'messages'
              AND policyname = 'messages_tenant_policy'
        ) THEN
            EXECUTE 'CREATE POLICY messages_tenant_policy ON public.messages
                     USING (tenant_id = saas_current_tenant())
                     WITH CHECK (tenant_id = saas_current_tenant())';
        END IF;
    END IF;

    IF to_regclass('public.campaigns') IS NOT NULL THEN
        EXECUTE 'ALTER TABLE public.campaigns ENABLE ROW LEVEL SECURITY';
        EXECUTE 'ALTER TABLE public.campaigns FORCE ROW LEVEL SECURITY';
        IF NOT EXISTS (
            SELECT 1 FROM pg_policies
            WHERE schemaname = 'public'
              AND tablename = 'campaigns'
              AND policyname = 'campaigns_tenant_policy'
        ) THEN
            EXECUTE 'CREATE POLICY campaigns_tenant_policy ON public.campaigns
                     USING (tenant_id = saas_current_tenant())
                     WITH CHECK (tenant_id = saas_current_tenant())';
        END IF;
    END IF;

    IF to_regclass('public.remarketing_enrollments') IS NOT NULL THEN
        EXECUTE 'ALTER TABLE public.remarketing_enrollments ENABLE ROW LEVEL SECURITY';
        EXECUTE 'ALTER TABLE public.remarketing_enrollments FORCE ROW LEVEL SECURITY';
        IF NOT EXISTS (
            SELECT 1 FROM pg_policies
            WHERE schemaname = 'public'
              AND tablename = 'remarketing_enrollments'
              AND policyname = 'remarketing_enrollments_tenant_policy'
        ) THEN
            EXECUTE 'CREATE POLICY remarketing_enrollments_tenant_policy ON public.remarketing_enrollments
                     USING (tenant_id = saas_current_tenant())
                     WITH CHECK (tenant_id = saas_current_tenant())';
        END IF;
    END IF;
END $$;
