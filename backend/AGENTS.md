# Backend AGENTS

Scope: SaaS backend only.

Active path: `saas-version/backend`.

## Real Structure

- FastAPI package: `app_saas`.
- Dependencies: `requirements.txt`.
- Container: `Dockerfile`.
- App entry: `app_saas/main.py`.
- Public API prefix: `/saas/v1`.

## Rules

- Do not infer behavior from root `backend/`.
- Do not update `requirements.txt` unless explicitly requested.
- Do not change `/saas/v1` compatibility without approval.
- Follow existing pattern: FastAPI routers, Pydantic schemas, `db_session()`, raw SQL, explicit tenant filters.
- Do not invent a global service layer. Some domains use `service.py`; others keep SQL in routers. Follow the local domain pattern.
- Before changing startup behavior, inspect embedded worker loop in `app_saas/main.py` and Docker worker behavior.

## Dangerous Zones

- `app_saas/config.py` env defaults.
- `app_saas/main.py` router mounting and startup worker.
- `app_saas/db.py` session and tenant context.
- `requirements.txt` and Docker image assumptions.

## Required Checks

- `rg "<symbol|endpoint|table>" saas-version/backend/app_saas`
- Inspect matching frontend/admin consumers before response-shape changes.
- Update memory after backend code/config changes.

