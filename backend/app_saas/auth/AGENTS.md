# Auth AGENTS

Scope: tenant user auth only.

Active path: `saas-version/backend/app_saas/auth`.

## Real Structure

- Router prefix: `/auth`.
- Mounted under `/saas/v1`.
- Endpoints include register, login, refresh, switch-tenant, me.
- Uses Argon2 hashing, JWT access/refresh tokens, tenant memberships, trial tenant/subscription creation.

## Rules

- Do not merge tenant auth with platform admin auth.
- Preserve token payload requirements: access tokens need tenant context and role.
- Preserve membership checks during login and tenant switching.
- Keep captcha/rate-limit/security-event behavior intact unless explicitly changing security policy.
- Registration side effects can create tenant, owner membership, and trial subscription; inspect billing trials before edits.

## Dangerous Zones

- Refresh token handling.
- `switch-tenant` membership validation.
- Trial creation and default plan code.
- Email normalization and slug normalization.

## Required Checks

- Inspect `shared/security.py`, `billing/trials.py`, and migrations for users/memberships/tenants.
- Search frontend auth consumers in `saas-version/frontend/src/App.jsx`.

