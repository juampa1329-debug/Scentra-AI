# AI Agent AGENTS

Scope: tenant conversation AI settings, memory, pending replies, and processing.

Active path: `saas-version/backend/app_saas/ai_agent`.

## Real Structure

- Router prefix: `/ai`.
- `service.py` manages settings, conversation memory, pending replies, provider credentials, knowledge context, CRM updates, outbound chunks, and due AI replies.
- Uses AI gateway, billing quotas, and knowledge context.
- Phase 8 runtime can select a persisted assigned agent, inject its rendered system prompt, inject collective memory, and enforce agent budget hard stop.

## Rules

- Do not bypass `ensure_ai_token_quota` or message quota checks.
- Do not bypass assigned-agent ownership or agent budget hard-stop checks.
- Preserve conversation memory tenant scoping.
- Preserve collective-memory prompt injection for assigned agents.
- If a conversation has an inactive/unavailable assigned agent, do not silently fall back to general AI.
- Keep provider credential resolution encrypted until provider-call boundary.
- Do not auto-send AI output without checking existing process/outbound pattern.
- Preserve pending reply status transitions and `FOR UPDATE SKIP LOCKED`.

## Dangerous Zones

- System prompt construction.
- Assigned-agent runtime selection and fallback behavior.
- CRM field updates from AI facts.
- Outbound message chunking and quota increments.
- Knowledge context injection.
- Pending reply scheduler.

## Required Checks

- Inspect CRM, workers, knowledge, ai_gateway, and agents runtime before changing AI behavior.
- Update business logic memory after AI workflow changes.
