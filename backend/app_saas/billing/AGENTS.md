# Billing AGENTS

Scope: SaaS billing, plans, limits, usage, checkout, credits, invoices, provider events.

Active path: `saas-version/backend/app_saas/billing`.

## Real Structure

- Router prefix: `/billing`.
- `limits.py`: entitlements, feature flags, tenant operational status, quota checks.
- `service.py`: checkout sessions, invoices/PDFs, credits, provider event processing, lifecycle sync.
- `workers/billing.py`: recurring lifecycle runner with advisory lock/interval throttle.
- `trials.py`: trial subscription creation.
- Admin billing operations also live in `admin/router.py`.

## Rules

- Do not bypass `ensure_tenant_operational`, `ensure_feature_enabled`, or quota helpers.
- Preserve active/trial/past_due/paused/suspended/cancelled semantics.
- Provider webhooks must be verified before mutating billing state.
- Stripe, MercadoPago, and Wompi webhook secrets must be present in production; do not weaken signature checks.
- Usage counters and credits affect limits; inspect both before changing calculations.
- Keep tenant status and subscription status synchronized.
- Keep non-operational tenant write blocking compatible with billing recovery routes.
- Do not change plan limit semantics without updating admin/client consumers and docs.

## Dangerous Zones

- Checkout session activation.
- Wompi/Stripe/MercadoPago event handling.
- Lifecycle sync, failed-payment notices, and suspension state.
- Invoice PDF generation/download endpoints.
- Manual credits/invoices.
- Feature flag defaults.
- Plan code and trial config.

## Required Checks

- Search billing helper usages in CRM, campaigns, broadcasts, integrations, AI, agents, workers.
- Run backend compile plus client/admin builds after changing billing response shapes or invoice UI.
- Update `docs/ENVIRONMENT.md`, `docs/DATABASE.md`, and ADRs for billing architecture changes.
