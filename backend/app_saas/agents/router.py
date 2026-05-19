from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app_saas.agents.schemas import AgentActionDraftIn, AgentEventIn, AiAgentCreateIn, AiAgentPatchIn
from app_saas.agents.service import (
    add_agent_event,
    agent_runtime_summary,
    builder_catalog,
    create_agent_action_draft,
    create_agent,
    create_from_template,
    get_agent,
    list_agent_action_drafts,
    list_agent_events,
    list_agents,
    list_templates,
    plan_limits,
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
def archive_agent(agent_id: str, ctx: AuthContext = Depends(require_role("owner", "admin"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        item = set_agent_status(conn, ctx.tenant_id, ctx.user_id, agent_id, "archived")
        return {"ok": True, "agent": item, "limits": plan_limits(conn, ctx.tenant_id)}


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
