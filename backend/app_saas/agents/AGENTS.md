# Agents AGENTS

Scope: SaaS multi-agent registry, governance, memory, and orchestrator.

Active path: `saas-version/backend/app_saas/agents`.

## Real Structure

- Router prefix: `/agents`.
- `service.py`: templates, catalog, limits, agent registry, memories, governance, collective memory, prompt versions, action drafts.
- `orchestrator.py`: orchestration jobs, locks, handoffs, conflicts, events, due orchestration processing.

## Rules

- Preserve governance, limit, and feature checks before enabling/activating agents.
- Preserve preflight-gated activation; do not create activation paths that bypass `preflight_agent`.
- Preserve runtime budget hard-stop checks before provider execution.
- Treat orchestrator jobs as concurrent queue work.
- Preserve agent memory archive/export/import safety; archiving agents should preserve memories by default unless explicitly changed.
- Preserve tenant collective memory as a shared runtime context for agents.
- Do not bypass action draft approval paths.
- Keep prompt version history when prompt behavior changes.
- Keep conversation AI ownership single-owner: assigned agent, released general AI, no silent fallback when an assigned agent is inactive.
- Agent multimodal tools must stay read-only/contextual. Reuse `multimodal_tools.py`, existing media/search endpoints and `saas_ai_agent_tool_runs`; do not add direct customer-send, CRM mutation, workflow/campaign execution, agent assignment or training side effects.
- External search output may enter agent prompts only from approved, non-blocked search result rows.
- Multimodal memory/training capture must stay tenant-scoped and feature-gated. Use `multimodal_memory.py` and `saas_multimodal_memory_events`; do not persist raw media/base64 payloads.
- Training-ready flags require `multimodal_training_events`, `ml_predictions`, or `ai_premium`; memory capture alone must not imply model-training authorization.
- RAG/collective-memory materialization from customer content requires explicit operator approval through the materialize endpoint payload.

## Dangerous Zones

- Agent activation/pause/archive lifecycle.
- Orchestrator locks and conflict handling.
- Collective memory deletion/import.
- Prompt versions and tool approvals.
- Custom-agent prompt templates and rendered prompts.
- Conversation assignment helpers that write `assigned_ai_agent_id`.
- Plan limit initialization.
- Agent multimodal tool execution and prompt context injection.
- Multimodal memory materialization into Knowledge/RAG or collective memory.

## Required Checks

- Inspect `billing/limits.py`, `ai_agent/service.py`, `advisor/service.py`, and worker runner references.
- Update ADR/memory for durable agent governance decisions.
