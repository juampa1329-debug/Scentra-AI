from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app_saas.advisor.schemas import AdvisorChatIn, AdvisorChatOut
from app_saas.advisor.service import (
    advisor_chat,
    dismiss_insight,
    dismiss_recommendation,
    generate_seed_insights,
    list_insights,
    list_recommendations,
    list_threads,
    thread_messages,
)
from app_saas.db import db_session, set_tenant_context
from app_saas.shared.security import AuthContext, get_current_user, require_role

router = APIRouter(prefix="/advisor", tags=["saas-advisor"])


@router.get("/threads")
def get_advisor_threads(
    limit: int = Query(default=20, ge=1, le=100),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "threads": list_threads(conn, ctx.tenant_id, ctx.user_id, limit=limit)}


@router.get("/threads/{thread_id}")
def get_advisor_thread(thread_id: str, ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "messages": thread_messages(conn, ctx.tenant_id, thread_id)}


@router.post("/chat", response_model=AdvisorChatOut)
def post_advisor_chat(payload: AdvisorChatIn, ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return advisor_chat(
            conn,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            message=payload.message,
            thread_id=payload.thread_id,
            context_type=payload.context_type,
            context_id=payload.context_id,
            module=payload.module,
        )


@router.get("/insights")
def get_advisor_insights(
    refresh: bool = Query(default=True),
    limit: int = Query(default=20, ge=1, le=100),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        insights = generate_seed_insights(conn, ctx.tenant_id) if refresh else list_insights(conn, ctx.tenant_id, limit=limit)
        return {"ok": True, "insights": insights[:limit]}


@router.get("/recommendations")
def get_advisor_recommendations(
    limit: int = Query(default=20, ge=1, le=100),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "recommendations": list_recommendations(conn, ctx.tenant_id, limit=limit)}


@router.post("/insights/{insight_id}/dismiss")
def dismiss_advisor_insight(
    insight_id: str,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor", "agent")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "item": dismiss_insight(conn, ctx.tenant_id, insight_id)}


@router.post("/recommendations/{recommendation_id}/dismiss")
def dismiss_advisor_recommendation(
    recommendation_id: str,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor", "agent")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "item": dismiss_recommendation(conn, ctx.tenant_id, recommendation_id)}
