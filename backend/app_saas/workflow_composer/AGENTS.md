# Workflow Composer Domain Rules

Scope: `saas-version/backend/app_saas/workflow_composer/`

## Purpose

Phase 18 AI Workflow Composer is a tenant-scoped control-plane for designing, simulating, approving, versioning and activating AI workflows safely.

It must not directly execute WhatsApp, Instagram, Meta, CRM, campaign or trigger side effects unless a specific, reviewed materialization path exists.

## Critical Rules

- Preserve tenant isolation on every query.
- Gate premium operations with `ai_workflow_composer`.
- Allow preview/demo surfaces only through explicit demo access.
- Never bypass existing campaign, trigger, flow, AI agent, budget, approval or billing controls.
- Activation means Composer control-plane activation unless code explicitly creates a safe draft in another domain.
- Simulations must be side-effect free.
- Preflight must run before approval and activation.
- Approved workflows become draft again when graph/config changes.
- Version snapshots must be written before destructive workflow graph changes.
- Do not execute plugin code or custom tools from Composer.

## Safe Extension Pattern

1. Add forward-only migrations for new tables/columns.
2. Validate graph/node types in `service.py`.
3. Keep API contracts under `/saas/v1/workflow-composer`.
4. Use existing auth dependencies in `router.py`.
5. Add UI only after backend response shapes are stable.
6. Update memory/docs after every change.
