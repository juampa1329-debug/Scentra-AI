# Trust Center Domain Rules

Scope: `saas-version/backend/app_saas/trust_center/`

## Purpose

Phase 22 AI Trust, Compliance & Governance is a tenant-scoped control-plane for AI policies, risk assessments, model cards, incidents, audit and compliance reporting.

## Rules

- Preserve tenant isolation on every query.
- Keep all advanced trust features behind Intelligence premium gates and demo/full modes.
- Demo mode may preview/read trust state, but mutations require full feature access.
- Do not execute Meta, CRM, billing, workflow, plugin, model rollout or agent actions from this domain.
- Risk assessments are governance records; they do not pause agents, change workflows, deploy models or mutate queues.
- Model cards are documentation/control records; actual model rollout remains in the Intelligence registry.
- Incidents and reports must stay auditable and reversible as records only.
- Do not export raw private tenant data or cross-tenant content.

## Dangerous Zones

- AI model rollout status and production/canary labels.
- Agent/tool/workflow risk scoring that could be mistaken for automatic enforcement.
- Cross-tenant benchmark/privacy claims.
- Admin trust overview across tenants.

## Required Checks

- Inspect `intelligence/service.py`, `billing/limits.py`, `admin/router.py` and tenant/admin frontend consumers before changing gates or response shapes.
- Update docs, architecture, ADR and memory after any change.
