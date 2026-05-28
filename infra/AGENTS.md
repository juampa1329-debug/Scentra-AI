# Infra AGENTS

Scope: SaaS infra/deployment notes only.

Active path: `saas-version/infra`.

## Real Structure

- Local dev and Coolify production documentation.
- Compose file lives at `saas-version/docker-compose.saas.yml`.
- Services include Postgres, API, and worker.

## Rules

- Do not change deployment docs without checking `docker-compose.saas.yml` and backend/frontend env requirements.
- Never recommend production use of default local secrets.
- Keep API and worker environment expectations aligned.
- Preserve external `coolify` network assumptions unless deployment architecture changes explicitly.

## Dangerous Zones

- `SAAS_JWT_SECRET` and `SAAS_SECRET_KEY`.
- CORS/public URL settings.
- Billing provider secrets.
- Meta/Instagram OAuth/webhook URLs.
- Embedded worker plus standalone worker concurrency.

## Required Checks

- Update `docs/ENVIRONMENT.md` after env/deployment changes.
- Update root memory if deployment topology changes.

