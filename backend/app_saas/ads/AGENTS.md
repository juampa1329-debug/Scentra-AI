# Ads AGENTS

Scope: SaaS ad accounts/campaigns/leads/comments and inbox conversion.

Active path: `saas-version/backend/app_saas/ads`.

## Real Structure

- Router prefix: `/ads`.
- Handles summary, accounts, campaigns, leads import/update/to-inbox, comments import/update/to-inbox, webhook event processing.
- Uses `ensure_feature_enabled(conn, tenant_id, "ads")`.

## Rules

- Preserve ads feature gating.
- Keep external lead/comment ids idempotent with `ON CONFLICT`.
- Keep conversion-to-inbox compatible with CRM conversation/message schema.
- Preserve tenant scoping and status filters.
- Do not duplicate social comment automation logic without checking `social/`.

## Dangerous Zones

- Import dedupe keys.
- Conversion to inbox.
- Webhook event processing.
- Usage counters.
- Lead/comment status transitions.

## Required Checks

- Inspect `frontend/src/AdsPanel.jsx`, `crm/router.py`, `social/service.py`, and webhook ingestion.

