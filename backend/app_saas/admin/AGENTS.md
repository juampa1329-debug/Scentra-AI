# Admin AGENTS

Scope: SaaS platform admin backend.

Active path: `saas-version/backend/app_saas/admin`.

## Real Structure

- Router prefix: `/admin`.
- Mounted under `/saas/v1`.
- Covers platform auth, overview, tenants, feature flags, plans, subscriptions, billing ops, audit, operations, observability, dead-letter.
- Uses platform auth dependencies from `shared/security.py`.

## Rules

- Do not expose admin endpoints to tenant auth.
- Preserve platform role checks for superadmin, platform_admin, billing_admin, support, and viewer.
- Treat impersonation and tenant mutation as audit-sensitive.
- Billing plan/subscription changes must stay consistent with tenant status and plan limits.
- Operations endpoints can process queues; keep them role-gated.

## Dangerous Zones

- Bootstrap admin creation.
- Tenant impersonation.
- Feature flags and plan limits.
- Manual billing credits/invoices/subscription lifecycle.
- Dead-letter resolution and queue processors.

## Required Checks

- Inspect `admin-frontend/src/AdminApp.jsx` for consumers.
- Search `saas_platform_admins`, `saas_tenant_feature_flags`, and billing tables before schema/API changes.

