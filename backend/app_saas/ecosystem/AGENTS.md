# Ecosystem AGENTS

Scope: SaaS AI Platform Ecosystem control-plane.

Active path: `saas-version/backend/app_saas/ecosystem`.

## Real Structure

- Router prefix: `/ecosystem`.
- Schema source starts at `saas-version/migrations/053_saas_ai_platform_ecosystem_phase11.sql`.
- Feature access is resolved through Intelligence premium flags and billing entitlements.

## Rules

- Keep marketplace, plugins, SDK, tools and AI apps tenant-scoped.
- Keep advanced ecosystem features premium-gated and demo-aware.
- Do not execute untrusted plugin code inside the API or worker.
- Store plugin/app/tool manifests as metadata until a sandbox runtime is explicitly designed.
- Do not store raw external secrets in ecosystem records.
- Preserve AI governance: scopes, permissions, audit traces and lifecycle statuses.
- Do not bypass existing agent preflight, budgets, memory safety or action-approval paths.

## Dangerous Zones

- Plugin lifecycle and external integrations.
- Developer app API keys.
- Agent template installation that creates real agent records.
- Event subscription fanout into workers or orchestrators.
- Tool registry entries that imply side effects.

## Required Checks

- Inspect `billing/limits.py` and `intelligence/catalog.py` before changing feature gates.
- Inspect `agents/service.py` before creating agents from marketplace templates.
- Update docs, architecture, ADR and memory after ecosystem changes.
