# Migrations AGENTS

Scope: SaaS database migrations only.

Active path: `saas-version/migrations`.

## Real Structure

- Ordered SQL files from `001_saas_core.sql` through current SaaS phases.
- Migration runner: `backend/app_saas/tools/migrate.py`.
- Database: PostgreSQL.
- Application code also contains runtime `CREATE TABLE IF NOT EXISTS` in some services.

## Rules

- Add forward migrations for schema changes.
- Do not edit historical migrations unless the user explicitly approves local reset semantics.
- Preserve tenant_id columns, indexes, RLS expectations, and foreign keys.
- Keep migration filenames ordered and descriptive.
- Search runtime SQL before changing any table or column.

## Dangerous Zones

- RLS policies.
- Tables referenced by workers and webhooks.
- Non-prefixed social tables.
- Billing/usage/limits tables.
- AI/agent/knowledge runtime-created tables.

## Required Checks

- `rg "<table_or_column>" saas-version/backend/app_saas saas-version/frontend saas-version/admin-frontend`
- Update `docs/DATABASE.md`, `architecture/DB_FLOW.md`, and memory after schema changes.

