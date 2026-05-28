from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Query

from app_saas.agents.schemas import (
    AgentActionDraftIn,
    AgentArchiveIn,
    AgentCollectiveMemoryIn,
    AgentEventIn,
    AgentMemoryImportIn,
    AgentMemoryRestoreIn,
    AgentMultimodalMemoryMaterializeIn,
    AgentMultimodalMemorySyncIn,
    AgentMultimodalToolRunIn,
    AgentOsEventSyncIn,
    AgentOsMessageIn,
    AgentOrchestrationEventIn,
    AgentPromptVersionIn,
    AgentToolRunIn,
    AiAgentCreateIn,
    AiAgentPatchIn,
)
from app_saas.agents.operating_system import (
    create_agent_os_message,
    create_agent_tool_run,
    list_agent_os_messages,
    list_agent_tool_runs,
    multi_agent_os_overview,
    sync_event_driven_agent_jobs,
)
from app_saas.agents.multimodal_tools import (
    agent_multimodal_tool_catalog,
    execute_agent_multimodal_tool,
    list_agent_multimodal_tool_runs,
)
from app_saas.agents.multimodal_memory import (
    list_multimodal_memory_events,
    materialize_multimodal_memory_event,
    sync_multimodal_memory_events,
)
from app_saas.agents.orchestrator import (
    create_manual_orchestration_event,
    orchestration_overview,
    process_due_agent_orchestration,
)
from app_saas.agents.service import (
    add_agent_event,
    agent_runtime_summary,
    agent_phase6_overview,
    archive_agent_with_memory,
    builder_catalog,
    create_collective_memory,
    create_agent_action_draft,
    create_agent,
    create_agent_from_memory_archive,
    create_from_template,
    create_prompt_version,
    delete_collective_memory,
    delete_agent_memory_archive,
    export_agent_memory_archive,
    get_agent,
    import_agent_memory_archive,
    list_collective_memory,
    list_agent_action_drafts,
    list_agent_events,
    list_agent_memory_archives,
    list_agents,
    list_templates,
    plan_limits,
    preflight_agent,
    set_agent_status,
    update_agent,
)
from app_saas.db import db_session, set_tenant_context
from app_saas.shared.security import AuthContext, get_current_user, require_role

router = APIRouter(prefix="/agents", tags=["saas-ai-agents"])


@router.get("/templates")
def get_agent_templates(ctx: AuthContext = Depends(get_current_user)):
    return {"ok": True, "templates": list_templates(), "tenant_id": ctx.tenant_id}


@router.get("/limits")
def get_agent_limits(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "limits": plan_limits(conn, ctx.tenant_id)}


@router.get("/catalog")
def get_agent_builder_catalog(ctx: AuthContext = Depends(get_current_user)):
    return {"ok": True, "tenant_id": ctx.tenant_id, "catalog": builder_catalog()}


@router.get("/multimodal-tools/catalog")
def get_agent_multimodal_tool_catalog(ctx: AuthContext = Depends(get_current_user)):
    return {"ok": True, "tenant_id": ctx.tenant_id, "tools": agent_multimodal_tool_catalog()}


@router.get("/multimodal-memory/events")
def get_agent_multimodal_memory_events(
    conversation_id: str = Query("", max_length=80),
    agent_id: str = Query("", max_length=80),
    source_kind: str = Query("", max_length=80),
    limit: int = Query(default=80, ge=1, le=200),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {
            "ok": True,
            "tenant_id": ctx.tenant_id,
            "events": list_multimodal_memory_events(
                conn,
                ctx.tenant_id,
                conversation_id=conversation_id,
                agent_id=agent_id,
                source_kind=source_kind,
                limit=limit,
            ),
        }


@router.post("/multimodal-memory/sync")
def post_agent_multimodal_memory_sync(
    payload: AgentMultimodalMemorySyncIn = Body(default=AgentMultimodalMemorySyncIn()),
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor", "agent")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        result = sync_multimodal_memory_events(conn, ctx.tenant_id, ctx.user_id, payload.model_dump())
        return {"ok": True, "tenant_id": ctx.tenant_id, **result}


@router.post("/multimodal-memory/events/{event_id}/materialize")
def post_agent_multimodal_memory_materialize(
    event_id: str,
    payload: AgentMultimodalMemoryMaterializeIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        result = materialize_multimodal_memory_event(conn, ctx.tenant_id, ctx.user_id, event_id, payload.model_dump())
        return {"ok": True, "tenant_id": ctx.tenant_id, **result}


@router.get("/memories")
def get_agent_memories(
    limit: int = Query(default=100, ge=1, le=200),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "memories": list_agent_memory_archives(conn, ctx.tenant_id, limit=limit)}


@router.post("/memories/{memory_id}/restore")
def post_agent_from_memory(
    memory_id: str,
    payload: AgentMemoryRestoreIn = Body(default=AgentMemoryRestoreIn()),
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        item = create_agent_from_memory_archive(conn, ctx.tenant_id, ctx.user_id, memory_id, payload.model_dump())
        return {"ok": True, "agent": item, "limits": plan_limits(conn, ctx.tenant_id)}


@router.delete("/memories/{memory_id}")
def delete_agent_memory(
    memory_id: str,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        memory = delete_agent_memory_archive(conn, ctx.tenant_id, ctx.user_id, memory_id)
        return {"ok": True, "memory": memory, "limits": plan_limits(conn, ctx.tenant_id)}


@router.get("/memories/{memory_id}/export")
def export_agent_memory(
    memory_id: str,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "export": export_agent_memory_archive(conn, ctx.tenant_id, memory_id)}


@router.post("/memories/import")
def import_agent_memory(
    payload: AgentMemoryImportIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        memory = import_agent_memory_archive(conn, ctx.tenant_id, ctx.user_id, payload.model_dump())
        return {"ok": True, "memory": memory, "limits": plan_limits(conn, ctx.tenant_id)}


@router.get("")
def get_agents(
    include_archived: bool = Query(default=False),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        agents = list_agents(conn, ctx.tenant_id, include_archived=include_archived)
        limits = plan_limits(conn, ctx.tenant_id)
        return {"ok": True, "agents": agents, "limits": limits}


@router.post("")
def post_agent(payload: AiAgentCreateIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        item = create_agent(conn, ctx.tenant_id, ctx.user_id, payload.model_dump())
        return {"ok": True, "agent": item, "limits": plan_limits(conn, ctx.tenant_id)}


@router.post("/from-template/{agent_type}")
def post_agent_from_template(agent_type: str, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        item = create_from_template(conn, ctx.tenant_id, ctx.user_id, agent_type)
        return {"ok": True, "agent": item, "limits": plan_limits(conn, ctx.tenant_id)}


@router.get("/governance")
def get_agent_governance(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "tenant_id": ctx.tenant_id, **agent_phase6_overview(conn, ctx.tenant_id)}


@router.get("/collective-memory")
def get_agent_collective_memory(
    limit: int = Query(default=80, ge=1, le=200),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "memories": list_collective_memory(conn, ctx.tenant_id, limit=limit)}


@router.post("/collective-memory")
def post_agent_collective_memory(
    payload: AgentCollectiveMemoryIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        memory = create_collective_memory(conn, ctx.tenant_id, ctx.user_id, payload.model_dump())
        return {"ok": True, "memory": memory, **agent_phase6_overview(conn, ctx.tenant_id)}


@router.delete("/collective-memory/{memory_id}")
def delete_agent_collective_memory(
    memory_id: str,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        memory = delete_collective_memory(conn, ctx.tenant_id, ctx.user_id, memory_id)
        return {"ok": True, "memory": memory, **agent_phase6_overview(conn, ctx.tenant_id)}


@router.post("/{agent_id}/prompt-versions")
def post_agent_prompt_version(
    agent_id: str,
    payload: AgentPromptVersionIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        version = create_prompt_version(conn, ctx.tenant_id, ctx.user_id, agent_id, payload.model_dump())
        return {"ok": True, "prompt_version": version}


@router.get("/orchestrator")
def get_agent_orchestrator(
    limit: int = Query(default=20, ge=1, le=100),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "tenant_id": ctx.tenant_id, **orchestration_overview(conn, ctx.tenant_id, limit=limit)}


@router.post("/orchestrator/events")
def post_agent_orchestration_event(
    payload: AgentOrchestrationEventIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        event = create_manual_orchestration_event(conn, ctx.tenant_id, ctx.user_id, payload.model_dump())
        return {"ok": True, **event, "orchestrator": orchestration_overview(conn, ctx.tenant_id, limit=20)}


@router.post("/orchestrator/tick")
def post_agent_orchestrator_tick(
    limit: int = Query(default=10, ge=1, le=50),
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    result = process_due_agent_orchestration(limit=limit, tenant_id=ctx.tenant_id)
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "result": result, "orchestrator": orchestration_overview(conn, ctx.tenant_id, limit=20)}


@router.get("/os")
def get_agent_operating_system(
    limit: int = Query(default=30, ge=1, le=100),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, **multi_agent_os_overview(conn, ctx.tenant_id, limit=limit)}


@router.get("/os/messages")
def get_agent_os_messages(
    limit: int = Query(default=50, ge=1, le=100),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "messages": list_agent_os_messages(conn, ctx.tenant_id, limit=limit)}


@router.post("/os/messages")
def post_agent_os_message(
    payload: AgentOsMessageIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor", "agent")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        message = create_agent_os_message(conn, ctx.tenant_id, ctx.user_id, payload.model_dump())
        return {"ok": True, "message": message, **multi_agent_os_overview(conn, ctx.tenant_id, limit=20)}


@router.post("/os/event-sync")
def post_agent_os_event_sync(
    payload: AgentOsEventSyncIn = Body(default=AgentOsEventSyncIn()),
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        result = sync_event_driven_agent_jobs(
            conn,
            ctx.tenant_id,
            limit=payload.limit,
            lookback_days=payload.lookback_days,
            dry_run=payload.dry_run,
            source="api",
        )
        return {"ok": True, "result": result, **multi_agent_os_overview(conn, ctx.tenant_id, limit=20)}


@router.get("/{agent_id}")
def get_agent_detail(agent_id: str, ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "agent": get_agent(conn, ctx.tenant_id, agent_id)}


@router.get("/{agent_id}/runtime")
def get_agent_runtime(agent_id: str, ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        summary = agent_runtime_summary(conn, ctx.tenant_id, agent_id)
        return {"ok": True, "tenant_id": ctx.tenant_id, **summary}


@router.get("/{agent_id}/preflight")
def get_agent_preflight(agent_id: str, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "tenant_id": ctx.tenant_id, "preflight": preflight_agent(conn, ctx.tenant_id, agent_id)}


@router.get("/{agent_id}/action-drafts")
def get_agent_action_drafts(
    agent_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "actions": list_agent_action_drafts(conn, ctx.tenant_id, agent_id, limit=limit)}


@router.post("/{agent_id}/action-drafts")
def post_agent_action_draft(
    agent_id: str,
    payload: AgentActionDraftIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor", "agent")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        item = create_agent_action_draft(conn, ctx.tenant_id, ctx.user_id, agent_id, payload.model_dump())
        summary = agent_runtime_summary(conn, ctx.tenant_id, agent_id)
        return {"ok": True, "action": item, **summary}


@router.get("/{agent_id}/tool-runs")
def get_agent_tool_runs(
    agent_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "tool_runs": list_agent_tool_runs(conn, ctx.tenant_id, agent_id, limit=limit)}


@router.post("/{agent_id}/tool-runs")
def post_agent_tool_run(
    agent_id: str,
    payload: AgentToolRunIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor", "agent")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        result = create_agent_tool_run(conn, ctx.tenant_id, ctx.user_id, agent_id, payload.model_dump())
        summary = agent_runtime_summary(conn, ctx.tenant_id, agent_id)
        return {"ok": True, **result, **summary}


@router.get("/{agent_id}/multimodal-tools/runs")
def get_agent_multimodal_tool_runs(
    agent_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {
            "ok": True,
            "tools": agent_multimodal_tool_catalog(),
            "tool_runs": list_agent_multimodal_tool_runs(conn, ctx.tenant_id, agent_id, limit=limit),
        }


@router.post("/{agent_id}/multimodal-tools/execute")
def post_agent_multimodal_tool_run(
    agent_id: str,
    payload: AgentMultimodalToolRunIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor", "agent")),
):
    result = execute_agent_multimodal_tool(ctx, agent_id, payload.model_dump())
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        summary = agent_runtime_summary(conn, ctx.tenant_id, agent_id)
    return {"ok": True, **result, **summary}


@router.patch("/{agent_id}")
def patch_agent(
    agent_id: str,
    payload: AiAgentPatchIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        data = payload.model_dump(exclude_unset=True)
        item = update_agent(conn, ctx.tenant_id, ctx.user_id, agent_id, data)
        return {"ok": True, "agent": item, "limits": plan_limits(conn, ctx.tenant_id)}


@router.post("/{agent_id}/activate")
def activate_agent(agent_id: str, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        item = set_agent_status(conn, ctx.tenant_id, ctx.user_id, agent_id, "active")
        return {"ok": True, "agent": item, "limits": plan_limits(conn, ctx.tenant_id)}


@router.post("/{agent_id}/pause")
def pause_agent(agent_id: str, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        item = set_agent_status(conn, ctx.tenant_id, ctx.user_id, agent_id, "paused")
        return {"ok": True, "agent": item, "limits": plan_limits(conn, ctx.tenant_id)}


@router.post("/{agent_id}/archive")
def archive_agent(
    agent_id: str,
    payload: AgentArchiveIn = Body(default=AgentArchiveIn()),
    ctx: AuthContext = Depends(require_role("owner", "admin")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        result = archive_agent_with_memory(
            conn,
            ctx.tenant_id,
            ctx.user_id,
            agent_id,
            preserve_memory=payload.preserve_memory,
            memory_title=payload.memory_title,
            notes=payload.notes,
        )
        return {"ok": True, **result, "limits": plan_limits(conn, ctx.tenant_id)}


@router.get("/{agent_id}/events")
def get_agent_events(
    agent_id: str,
    limit: int = Query(default=60, ge=1, le=200),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        get_agent(conn, ctx.tenant_id, agent_id)
        return {"ok": True, "events": list_agent_events(conn, ctx.tenant_id, agent_id, limit=limit)}


@router.post("/{agent_id}/events")
def post_agent_event(
    agent_id: str,
    payload: AgentEventIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    # This endpoint is intentionally narrow for phase 1: human notes only.
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        add_agent_event(
            conn,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            agent_id=agent_id,
            event_type=payload.event_type,
            summary=payload.summary,
            details=payload.details_json,
        )
        return {"ok": True, "events": list_agent_events(conn, ctx.tenant_id, agent_id, limit=20)}
