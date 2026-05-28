# Admin Frontend AGENTS

Scope: SaaS platform admin UI only.

Active path: `saas-version/admin-frontend`.

## Real Structure

- Main shell: `src/AdminApp.jsx`.
- Styles: `src/styles.css`.
- API base: `VITE_API_BASE`.
- Client app base: `VITE_CLIENT_APP_BASE`.
- Token: `scentra_admin_access_token`.
- Views: overview, tenants, plans, subscriptions, billing, operations, observability, audit.

## Rules

- Use `/saas/v1/admin/*` for platform admin APIs.
- Keep platform admin auth separate from tenant auth.
- Do not reuse tenant token keys.
- Preserve role-sensitive UI flows for billing/admin/support operations.
- Billing invoice PDF downloads must use authenticated fetch/blob flow; do not open protected admin PDF endpoints directly without Bearer auth.
- Tenant industry changes must go through `/saas/v1/admin/tenants/{tenant_id}` and rely on backend vertical pack application.
- Do not hardcode production URLs; use env-driven bases.
- Before changing admin UI fields, inspect `backend/app_saas/admin/router.py`.

## Dangerous Zones

- Bootstrap/login flow.
- Tenant impersonation.
- Plan/subscription/billing mutations.
- Tenant industry/vertical pack changes.
- Billing lifecycle sync and invoice PDF downloads.
- Operations endpoints that process queues.
- Observability/dead-letter actions.

## Required Checks

- Search `AdminApp.jsx` before adding duplicate state or fetch helpers.
- Verify platform role requirements in backend admin router.
- Update memory when admin API or operational behavior changes.
