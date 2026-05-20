from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app_saas.db import db_session, set_tenant_context
from app_saas.shared.security import AuthContext, get_current_user, require_role
from app_saas.social.service import (
    ensure_social_tables,
    generate_social_comment_reply,
    get_comment_ai_settings,
    list_social_comments,
    react_to_social_comment,
    reply_to_social_comment,
    upsert_comment_ai_settings,
)

router = APIRouter(prefix="/social", tags=["saas-social"])


class CommentReplyIn(BaseModel):
    message: str = Field(min_length=1, max_length=1000)


class CommentReactionIn(BaseModel):
    emoji: str = Field(default="👍", min_length=1, max_length=20)


class CommentAiSettingsIn(BaseModel):
    enabled: bool = True
    auto_generate: bool = False
    auto_reply: bool = False
    tone: str = Field(default="calido, breve y util", max_length=240)
    instructions: str = Field(default="", max_length=4000)
    blocked_words_json: list[str] = Field(default_factory=list)
    escalation_keywords_json: list[str] = Field(default_factory=list)
    provider_policy_json: dict[str, Any] = Field(default_factory=dict)


@router.get("/comments")
def get_comments(
    channel: str = Query("", max_length=40),
    status: str = Query("", max_length=40),
    limit: int = Query(50, ge=1, le=200),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        comments = list_social_comments(conn, ctx.tenant_id, channel=channel, status=status, limit=limit)
    return {"ok": True, "comments": comments}


@router.get("/comments/settings")
def get_comments_settings(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        settings = get_comment_ai_settings(conn, ctx.tenant_id)
    return {"ok": True, "settings": settings}


@router.patch("/comments/settings")
def patch_comments_settings(payload: CommentAiSettingsIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        settings = upsert_comment_ai_settings(conn, ctx.tenant_id, payload.model_dump())
    return {"ok": True, "settings": settings}


@router.post("/comments/{comment_id}/reply")
def post_comment_reply(comment_id: str, payload: CommentReplyIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor", "agent"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        result = reply_to_social_comment(conn, ctx.tenant_id, comment_id, payload.message)
    return result


@router.post("/comments/{comment_id}/react")
def post_comment_reaction(comment_id: str, payload: CommentReactionIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor", "agent"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        result = react_to_social_comment(conn, ctx.tenant_id, comment_id, payload.emoji)
    return result


@router.post("/comments/{comment_id}/generate-ai")
def post_comment_ai(comment_id: str, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor", "agent"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        result = generate_social_comment_reply(conn, ctx.tenant_id, comment_id)
    return result


@router.post("/comments/ensure-tables")
def ensure_comments_tables(ctx: AuthContext = Depends(require_role("owner", "admin"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        ensure_social_tables(conn)
    return {"ok": True}
