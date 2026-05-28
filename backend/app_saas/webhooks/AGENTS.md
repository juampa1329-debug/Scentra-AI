# Webhooks AGENTS

Scope: SaaS webhook endpoint management and inbound provider event ingestion.

Active path: `saas-version/backend/app_saas/webhooks`.

## Real Structure

- Router prefix: `/webhooks`.
- Tenant endpoints manage endpoint keys, tokens, signatures, verification, and events.
- Public provider routes include `/webhooks/{provider}/{endpoint_key}` and Instagram webhook routes.
- Events are stored for worker ingestion.

## Rules

- Preserve endpoint key lookup and tenant resolution.
- Do not weaken token or HMAC verification.
- Keep raw payload handling stable for signature checks.
- Use `ON CONFLICT`/event id patterns to avoid duplicate provider events.
- Do not process inbound events synchronously unless current pattern does.
- Keep webhook events tenant-scoped after endpoint resolution.

## Dangerous Zones

- Verification challenge responses.
- Signature secret rotation.
- Token rotation.
- Provider event deduplication.
- Usage counter increments.

## Required Checks

- Inspect `workers/ingest.py` before changing stored event shape.
- Inspect integration config and frontend callback URL generation.
- Update API docs and worker flow after contract changes.

