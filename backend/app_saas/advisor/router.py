from __future__ import annotations

import json
import time

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app_saas.advisor.schemas import AdvisorChatIn, AdvisorChatOut
from app_saas.advisor.service import (
    advisor_chat,
    advisor_memory,
    chunk_advisor_text,
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


def _ndjson_event(event_type: str, data) -> str:
    return json.dumps({"type": event_type, "data": data}, ensure_ascii=False) + "\n"


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


@router.get("/memory")
def get_advisor_memory(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "memory": advisor_memory(conn, ctx.tenant_id, ctx.user_id)}


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


@router.post("/chat/stream")
def post_advisor_chat_stream(payload: AdvisorChatIn, ctx: AuthContext = Depends(get_current_user)):
    def generate_events():
        yield _ndjson_event("status", {"message": "Preparando contexto operativo..."})
        try:
            with db_session() as conn:
                set_tenant_context(conn, ctx.tenant_id)
                result = advisor_chat(
                    conn,
                    tenant_id=ctx.tenant_id,
                    user_id=ctx.user_id,
                    message=payload.message,
                    thread_id=payload.thread_id,
                    context_type=payload.context_type,
                    context_id=payload.context_id,
                    module=payload.module,
                )
            assistant = dict(result.get("assistant_message") or {})
            content = str(assistant.get("content") or "")
            assistant_shell = {**assistant, "content": ""}
            yield _ndjson_event("thread", result.get("thread") or {})
            yield _ndjson_event("user_message", result.get("user_message") or {})
            yield _ndjson_event("assistant_start", assistant_shell)
            for chunk in chunk_advisor_text(content):
                yield _ndjson_event("delta", {"text": chunk + " "})
                time.sleep(0.015)
            yield _ndjson_event("assistant_done", assistant)
            yield _ndjson_event(
                "signals",
                {
                    "insights": result.get("insights") or [],
                    "recommendations": result.get("recommendations") or [],
                    "memory": result.get("memory") or {},
                },
            )
            yield _ndjson_event("done", {"ok": bool(result.get("ok", True))})
        except Exception as exc:
            yield _ndjson_event("error", {"message": str(exc)[:700]})

    return StreamingResponse(
        generate_events(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
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
