# Frontend AGENTS

Scope: tenant SaaS client app only.

Active path: `saas-version/frontend`.

## Real Structure

- Main shell: `src/App.jsx`.
- Domain panels: `CrmPanel.jsx`, `LabelsPanel.jsx`, `CampaignsPanel.jsx`, `SaasTriggerBuilderPanel.jsx`, `BroadcastPanel.jsx`, `AdsPanel.jsx`, `AiAgentsPanel.jsx`.
- Styles: `src/styles.css` and component CSS.
- API base: `VITE_API_BASE`.
- Tokens: `scentra_ai_access_token`, `scentra_ai_refresh_token`.

## Rules

- Do not copy patterns from root `frontend/`.
- Do not hardcode hostnames; use `VITE_API_BASE` and existing API helpers.
- Keep all SaaS API calls under `/saas/v1`.
- Preserve refresh-token behavior and localStorage key names unless explicitly migrating sessions.
- Reuse existing panel props such as `apiCall`, `showStatus`, `apiBase`, and `accessToken`.
- Before changing a response consumer, inspect the backend router/schema for that endpoint.
- Do not duplicate global state already owned by `App.jsx`.
- Keep tenant UI separate from platform admin UI.
- Preserve Inbox AI-agent assignment/filter behavior: users can manually assign/release an agent and the list can filter by assigned agent.
- Preserve `AiAgentsPanel.jsx` custom-agent prompt/preflight/budget controls when changing agents UI.
- Billing invoice PDF downloads must use authenticated fetch/blob flow; do not open protected PDF endpoints directly without Bearer auth.
- Preserve Phase 10 verticalization behavior: public packs for registration, authenticated `/verticals/*` calls for tenant settings, and no automatic trigger/flow activation from the UI.

## Dangerous Zones

- Auth/session logic in `App.jsx`.
- Webhook callback URL generation.
- Media URLs with access token query params.
- Billing/feature flag UI that gates SaaS modules.
- Plan/checkout/invoice history in Settings > Plan.
- Industry/vertical pack state in Settings > Industria.
- Provider credential forms; never display raw stored secrets.
- Agent activation/preflight error handling and budget hard-stop messages.

## Required Checks

- Search frontend references with `rg "<field-or-endpoint>" saas-version/frontend/src`.
- Search backend endpoint references under `saas-version/backend/app_saas`.
- If API shape changes, update `docs/API_REFERENCE.md` and memory.
