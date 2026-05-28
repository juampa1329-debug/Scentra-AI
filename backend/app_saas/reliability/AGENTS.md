# Reliability AGENTS

Scope: SaaS Phase 12 Performance, Reliability & Scale control-plane.

Active path: `saas-version/backend/app_saas/reliability`.

## Rules

- Keep this domain admin-only unless explicitly adding tenant-facing reliability surfaces.
- Do not run destructive cleanup automatically. Default retention behavior must be dry-run/control-plane first.
- Do not execute real database restore, provider throttling, campaign pausing, or queue mutation from this domain without explicit approval and rollback design.
- Preserve existing worker idempotency. Reliability worker code should record snapshots and recommendations, not alter Meta/WhatsApp/Instagram runtime behavior.
- Keep table and SQL names allowlisted for retention cleanup. Never concatenate user-provided table names or conditions.

## Dangerous Zones

- Retention cleanup can delete operational history if misconfigured.
- Backpressure recommendations can be mistaken for automatic throttling.
- Backup/restore checks are readiness drills, not a replacement for external infrastructure snapshots.
- Index changes must stay forward-only and compatible with PostgreSQL clean bootstrap.

## Required Checks

- Inspect `admin/router.py`, `admin-frontend/src/AdminApp.jsx`, `workers/runner.py`, `main.py`, and migration `055` before changes.
- Run SQL BOM/UTF-8 checks and Docker Compose config after schema changes.
- Update docs, memory, ADRs and the Spanish tracking PDF after Phase 12 changes.
