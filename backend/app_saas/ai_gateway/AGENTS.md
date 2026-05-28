# AI Gateway AGENTS

Scope: SaaS AI provider routing and run records.

Active path: `saas-version/backend/app_saas/ai_gateway`.

## Real Structure

- Router prefix: `/ai-gateway`.
- Service maintains providers, models, routes, runs, tool calls, and recommendations.
- Provider adapters live under `providers/`.
- Secrets are retrieved from API credentials and decrypted near provider calls.

## Rules

- Do not hardcode provider API keys.
- Preserve provider registry/model route semantics.
- Record run metadata/errors consistently.
- Keep provider adapters isolated; do not mix provider-specific logic into generic routing without need.
- Respect AI token/limit checks where caller domain applies them.

## Dangerous Zones

- Provider fallback behavior.
- Run logging and token estimates.
- Decrypted credential handling.
- Runtime table creation overlapping migrations.

## Required Checks

- Search callers in `ai_agent`, `advisor`, `agents`, `social`, and `knowledge`.
- Update AI docs/memory if provider routing changes.

