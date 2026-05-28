# Broadcasts AGENTS

Scope: SaaS broadcast manager, Meta templates, recipients, reports, retry.

Active path: `saas-version/backend/app_saas/broadcasts`.

## Real Structure

- Router prefix: `/broadcasts`.
- Handles Meta templates, sync/create/patch, broadcast list/create/patch, preview, enqueue, report, CSV export, retry failed, recipients.
- Uses billing feature/quota and monthly message quota checks.
- Uses encrypted Meta tokens from integrations.

## Rules

- Preserve `broadcast` feature check and broadcast/message quota checks.
- Do not expose decrypted Meta tokens.
- Keep recipient status/report fields compatible with frontend.
- Preserve enqueue/retry idempotency and conflict handling.
- Do not change Meta template shape without checking Meta API consumers and frontend.

## Dangerous Zones

- Enqueueing recipients.
- Retry failed recipients with quota checks.
- Meta template sync/create.
- CSV export response.
- Usage counter increments.

## Required Checks

- Inspect `frontend/src/BroadcastPanel.jsx`, `workers/dispatch.py`, integrations config, and migrations.

