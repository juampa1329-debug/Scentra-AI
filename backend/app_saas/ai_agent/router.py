from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app_saas.ai_agent.schemas import AiMemoryOut, AiSettingsIn, AiSettingsOut, AiTestIn
from app_saas.ai_agent.service import get_memory, get_settings, process_conversation_ai, test_agent, upsert_settings
from app_saas.db import db_session, set_tenant_context
from app_saas.shared.security import AuthContext, get_current_user, require_role
from app_saas.workers.dispatch import process_due_outbound_messages

router = APIRouter(prefix="/ai", tags=["saas-ai-agent"])


@router.get("/settings", response_model=AiSettingsOut)
def read_ai_settings(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return get_settings(conn, ctx.tenant_id)


@router.put("/settings", response_model=AiSettingsOut)
def save_ai_settings(payload: AiSettingsIn, ctx: AuthContext = Depends(require_role("owner", "admin"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return upsert_settings(conn, ctx.tenant_id, payload.model_dump())


@router.get("/conversations/{conversation_id}/memory", response_model=AiMemoryOut)
def read_conversation_memory(conversation_id: str, ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return get_memory(conn, ctx.tenant_id, conversation_id)


@router.post("/conversations/{conversation_id}/process")
def process_conversation_now(conversation_id: str, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor", "agent"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        result = process_conversation_ai(conn, ctx.tenant_id, conversation_id)
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result)
    try:
        dispatch = process_due_outbound_messages(limit=5, tenant_id=ctx.tenant_id)
    except Exception as exc:
        dispatch = {"picked": 0, "sent": 0, "blocked": 0, "failed": 1, "last_error": str(exc)[:300]}
    return {"ok": True, "tenant_id": ctx.tenant_id, "result": result, "dispatch": dispatch}


@router.post("/test")
def test_ai_agent(payload: AiTestIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor", "agent"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        result = test_agent(conn, ctx.tenant_id, payload.phone, payload.message)
    return {"ok": True, "tenant_id": ctx.tenant_id, **result}
