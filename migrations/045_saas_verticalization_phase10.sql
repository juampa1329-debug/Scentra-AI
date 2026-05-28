-- 045_saas_verticalization_phase10.sql
-- Fase 10: verticalizacion tenant-scoped con packs de industria idempotentes.

ALTER TABLE saas_tenants
    ADD COLUMN IF NOT EXISTS industry_code TEXT NOT NULL DEFAULT 'general',
    ADD COLUMN IF NOT EXISTS vertical_pack_version INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS vertical_pack_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS vertical_pack_applied_at TIMESTAMP NULL;

CREATE INDEX IF NOT EXISTS idx_saas_tenants_industry_code
ON saas_tenants (industry_code, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_vertical_pack_applications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    industry_code TEXT NOT NULL DEFAULT 'general',
    pack_version INTEGER NOT NULL DEFAULT 1,
    applied_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_agents BOOLEAN NOT NULL DEFAULT FALSE,
    result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_vertical_pack_applications_tenant_created
ON saas_vertical_pack_applications (tenant_id, created_at DESC);

