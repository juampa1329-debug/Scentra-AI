# Intelligence AGENTS

Scope: Scentra Intelligence Engine, predictive features, feature store, events, recommendations, Autonomous Operational Intelligence and AI premium gating.

Active path: `saas-version/backend/app_saas/intelligence`.

## Real Structure

- Router prefix: `/intelligence`.
- Admin control endpoints are exposed from `admin/router.py` using this service layer.
- Schema sources: `saas-version/migrations/046_saas_intelligence_engine_phase11.sql` through `054_saas_enterprise_ai_network_phase11.sql`.
- Licensing uses both existing billing feature flags and `saas_intelligence_feature_grants`.

## Rules

- Preserve tenant isolation in every query.
- Predictive features must stay behind feature flags, grants, mode, quotas and tenant status.
- Demo mode can return limited previews; full predictions require premium/full mode.
- Autonomous operations must stay behind `autonomous_operations`, `ai_self_healing`, `ai_control_center`, `ai_premium`, grants and tenant status.
- Demo mode must never persist auto-remediation or low-risk auto-execute settings.
- Do not add direct provider, queue, campaign, CRM or billing side effects to autonomous actions without an ADR, explicit user approval and staging validation.
- Keep autonomous action execution approval-first except report-only/low-risk Level 4 records explicitly allowed by policy.
- Enterprise AI Network must stay privacy-safe: use only aggregate/anonymized cross-tenant metrics, enforce minimum benchmark sample sizes, and never share raw messages, tenant names, conversations, private content or sensitive data.
- Vertical playbooks/advisors are recommendation surfaces only; do not auto-activate triggers, flows, campaigns or workflow changes from this layer without a future explicit design and approval.
- Do not train models or add ML dependencies from this package without explicit approval. When approved, keep them optional, feature-flagged, tenant-safe, and isolated from the default API/worker runtime.
- Treat baseline rule predictions as production-safe placeholders, not as trained ML.
- Do not call LLM providers from prediction endpoints unless explicitly requested; Advisor/AI Gateway remain separate.

## Dangerous Zones

- Feature grants and billing entitlements.
- Event replay idempotency.
- Prediction usage/billing counters.
- Admin feature toggles.
- Autonomous policy/action status transitions.
- Playbook rollback metadata and action audit events.
- Enterprise AI Network benchmark cohorts and sample-count thresholds.
- Vertical model/playbook metadata that could be mistaken for executable automation.
- Future worker/event-bus integration.

## Required Checks

- Inspect `billing/limits.py` before changing feature gating.
- Inspect `admin/router.py` and `admin-frontend/src/AdminApp.jsx` before changing admin surfaces.
- Update docs, architecture and memory after any change.
