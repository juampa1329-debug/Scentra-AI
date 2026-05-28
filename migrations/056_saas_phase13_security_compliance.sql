-- 056_saas_phase13_security_compliance.sql
-- Phase 13: MFA login challenges, security compliance and privacy request tracking.

CREATE TABLE IF NOT EXISTS saas_mfa_challenges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES saas_users(id) ON DELETE CASCADE,
    tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    context TEXT NOT NULL DEFAULT 'tenant',
    role TEXT NOT NULL DEFAULT '',
    platform_role TEXT NOT NULL DEFAULT '',
    method TEXT NOT NULL DEFAULT 'email_otp',
    challenge_token_hash TEXT NOT NULL UNIQUE,
    code_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    email_sent BOOLEAN NOT NULL DEFAULT FALSE,
    requested_ip TEXT NOT NULL DEFAULT '',
    user_agent TEXT NOT NULL DEFAULT '',
    expires_at TIMESTAMP NOT NULL,
    verified_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_saas_mfa_challenges_context CHECK (context IN ('tenant', 'platform_admin')),
    CONSTRAINT chk_saas_mfa_challenges_status CHECK (status IN ('pending', 'verified', 'failed', 'expired', 'blocked'))
);

CREATE INDEX IF NOT EXISTS idx_saas_mfa_challenges_user_created
ON saas_mfa_challenges (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_mfa_challenges_pending
ON saas_mfa_challenges (context, status, expires_at)
WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS saas_privacy_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    requester_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    subject_type TEXT NOT NULL DEFAULT 'customer',
    subject_id TEXT NOT NULL DEFAULT '',
    request_type TEXT NOT NULL DEFAULT 'export',
    status TEXT NOT NULL DEFAULT 'pending',
    reason TEXT NOT NULL DEFAULT '',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    resolved_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    resolved_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_saas_privacy_requests_type CHECK (request_type IN ('export', 'delete', 'memory_delete')),
    CONSTRAINT chk_saas_privacy_requests_status CHECK (status IN ('pending', 'approved', 'rejected', 'completed', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS idx_saas_privacy_requests_tenant_status
ON saas_privacy_requests (tenant_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_privacy_requests_subject
ON saas_privacy_requests (tenant_id, subject_type, subject_id);
