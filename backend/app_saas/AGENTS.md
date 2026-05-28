# app_saas AGENTS

Scope: FastAPI SaaS application package.

## Real Structure

- `main.py`: app, middleware, router mounting, embedded worker startup.
- `config.py`: Pydantic settings/env.
- `db.py`: SQLAlchemy engine/session and tenant context.
- Domain packages contain routers, schemas, services, and worker helpers.
- Phase 10 verticalization lives in `verticals/` and writes existing CRM/campaign/agent tables through idempotent pack application.

## Rules

- Every public SaaS router must remain mounted under `/saas/v1`.
- Use `db_session()` for DB access and call `set_tenant_context(conn, tenant_id)` in tenant-scoped operations where local pattern does.
- Keep tenant user auth and platform admin auth separate.
- Preserve explicit `tenant_id` filters even when RLS exists.
- Use Pydantic schemas where the domain already uses them.
- Do not add cross-domain imports that create circular dependencies.

## Dangerous Zones

- Router inclusion order in `main.py`.
- CORS/error middleware.
- Embedded worker loop concurrency with standalone worker.
- Runtime `CREATE TABLE IF NOT EXISTS` mixed with migrations.
- Cross-domain pack application that touches tenants, CRM, campaigns, and agents.

## Required Checks

- Inspect `docs/BACKEND.md`, `docs/API_REFERENCE.md`, and nearest domain `AGENTS.md`.
- Search all references before editing shared symbols.
- Add/update migrations for schema changes.
