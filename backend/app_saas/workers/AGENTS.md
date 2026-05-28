# Workers And Queues AGENTS

Scope: SaaS background processors and DB-backed queues.

Active path: `saas-version/backend/app_saas/workers`.

## Real Structure

- `runner.py`: standalone worker loop.
- `ingest.py`: webhook event processing.
- `dispatch.py`: outbound delivery.
- `triggers.py`: scheduled trigger messages.
- `remarketing.py`: remarketing flows.
- `billing.py`: recurring billing lifecycle.
- `meta_tokens.py`: Meta token refresh.
- AI replies and agent orchestration are called from `ai_agent.service` and `agents.orchestrator`.

## Rules

- Assume embedded API worker and standalone worker can run at the same time.
- Preserve `FOR UPDATE SKIP LOCKED` and status-transition patterns.
- Keep processors idempotent and retry-safe.
- Do not add provider calls before state is safely recorded.
- Preserve tenant filters and per-tenant limits/usage counters.
- Preserve billing lifecycle advisory lock and interval throttling when changing billing workers.
- Do not swallow errors without recording status/error fields.

## Dangerous Zones

- Selecting due rows.
- Changing status names or retry counters.
- Outbound message delivery to Meta/Instagram channels.
- Usage counter increments.
- Billing subscription/trial expiry and suspension.
- Token refresh scheduling.

## Required Checks

- Search processor from `main.py`, `runner.py`, admin operations, and diagnostics.
- Inspect related queue tables in migrations and runtime SQL.
- Update `architecture/WORKER_FLOW.md` after behavior changes.
