# Campaigns AGENTS

Scope: SaaS campaigns, templates, segments, triggers, flows, remarketing.

Active path: `saas-version/backend/app_saas/campaigns`.

## Real Structure

- Router prefix: `/campaigns`.
- Handles catalogs, templates, segments, campaign items, preflight, triggers, trigger copy, flows, flow processing.
- Uses billing feature/quota checks for campaigns, triggers, and remarketing.
- Workers process scheduled triggers and remarketing flows.

## Rules

- Preserve preflight and version recording behavior.
- Do not bypass `ensure_campaign_quota` or feature checks.
- Keep trigger/flow JSON shapes compatible with builder UI.
- Preserve trigger copy and uniqueness behavior.
- Do not change scheduled processing semantics without checking workers.

## Dangerous Zones

- Conditions/actions JSON.
- Trigger runtime and flow steps.
- Preflight records.
- Campaign version history.
- Feature flags: `triggers`, `remarketing`.

## Required Checks

- Inspect `frontend/src/CampaignsPanel.jsx`, `SaasTriggerBuilderPanel.jsx`, `workers/triggers.py`, and `workers/remarketing.py`.

