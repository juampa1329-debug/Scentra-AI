# CRM AGENTS

Scope: SaaS inbox, customers, conversations, messages, labels, tasks, scores, outbound.

Active path: `saas-version/backend/app_saas/crm`.

## Real Structure

- Router has no local prefix; mounted under `/saas/v1`.
- Routes include customers, dashboard overview, labels, conversations, messages, tasks, status events, outbound process, read, takeover.
- Phase 8 also exposes manual conversation AI-agent assignment/release and `agent_id` Inbox filtering.
- Uses `ensure_monthly_message_quota` for outbound messages.

## Rules

- Preserve tenant filters on every customer/conversation/message/task query.
- Do not change message direction/status semantics without checking workers and webhooks.
- Preserve quota checks before outbound sends.
- Keep label and task joins compatible with frontend panels.
- Preserve assigned AI agent fields and one-AI-owner semantics when changing conversations/customers.
- Only assign active tenant agents; releasing uses empty assignment and returns control to general AI.
- Do not break ads/social conversion into inbox.

## Dangerous Zones

- Outbound message creation and usage counters.
- Conversation takeover/read state.
- `assigned_ai_agent_id`, `ai_owner_mode`, and agent filter queries.
- Customer labels and status fields.
- Dashboard aggregate queries.
- Message media fields consumed by frontend.

## Required Checks

- Inspect `frontend/src/CrmPanel.jsx`, `AdsPanel.jsx`, workers dispatch/ingest, and migrations.
