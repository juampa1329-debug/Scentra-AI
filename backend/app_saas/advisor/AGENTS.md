# Advisor AGENTS

Scope: SaaS advisor chat, memory, insights, recommendations, and actions.

Active path: `saas-version/backend/app_saas/advisor`.

## Real Structure

- Router prefix: `/advisor`.
- `service.py` manages advisor threads/messages/memory/actions/audit/feedback/insights/recommendations.
- Supports normal chat and streaming chat.

## Rules

- Keep advisor memory tenant/user scoped.
- Preserve approval/dismiss/execute action workflow.
- Do not execute recommendations automatically unless existing endpoint explicitly does.
- Keep feedback and audit records intact.
- Respect tenant context in streamed operations.

## Dangerous Zones

- Streaming response DB access.
- Action execution side effects.
- Advisor memory updates.
- Recommendations that create executable actions.

## Required Checks

- Search advisor consumers in frontend and agents service.
- Update business logic docs if action semantics change.

