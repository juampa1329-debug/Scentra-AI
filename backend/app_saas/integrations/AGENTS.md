# Integrations AGENTS

Scope: SaaS external provider integrations.

Active path: `saas-version/backend/app_saas/integrations`.

## Real Structure

- `router.py`: tenant integration records, Meta token health/refresh, WhatsApp phone registration.
- `instagram_router.py`: Instagram/Facebook OAuth/connect/diagnostics.
- `instagram_graph.py`: Meta Graph helpers and OAuth state/subscription checks.
- `whatsapp_subscription.py`: WhatsApp subscription checks.
- Credentials are encrypted through `shared/secrets.py`.

## Rules

- Never store provider secrets without `encrypt_secret`.
- Never display raw secrets; use `mask_secret` behavior.
- Preserve `ensure_integration_quota` checks before creating new integrations.
- Keep provider/channel uniqueness and `ON CONFLICT` upserts intact.
- Do not hardcode Meta app secrets or tokens.
- Preserve token health/refresh diagnostics.

## Dangerous Zones

- OAuth state and callback handling.
- Page/user access token refresh.
- WhatsApp phone registration.
- Provider config JSON keys consumed by workers, media, social, broadcasts, and diagnostics.

## Required Checks

- Search config keys across `workers`, `media`, `social`, `broadcasts`, `webhooks`, and frontend settings.
- Update env docs when provider env vars change.

