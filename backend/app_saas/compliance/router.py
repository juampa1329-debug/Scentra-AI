from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text

from app_saas.db import db_session, set_tenant_context
from app_saas.shared.security import AuthContext, get_current_user, require_role

router = APIRouter(prefix="/compliance", tags=["saas-compliance"])


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def _table_exists(conn, table_name: str) -> bool:
    return bool(conn.execute(text("SELECT to_regclass(:table_name) IS NOT NULL"), {"table_name": table_name}).scalar())


def _ensure_privacy_requests(conn) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_privacy_requests (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                requester_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                subject_type TEXT NOT NULL DEFAULT 'customer',
                subject_id TEXT NOT NULL DEFAULT '',
                request_type TEXT NOT NULL DEFAULT 'export',
                status TEXT NOT NULL DEFAULT 'pending',
                reason TEXT NOT NULL DEFAULT '',
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                resolved_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                resolved_at TIMESTAMP NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )


def _rows(conn, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(text(sql), params).mappings().all()]


@router.get("/me/export")
def export_current_account(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        user = conn.execute(
            text(
                """
                SELECT id::text, email, full_name, status, two_factor_enabled, two_factor_method,
                       password_changed_at::text, last_login_at::text, created_at::text, updated_at::text
                FROM saas_users
                WHERE id = CAST(:user_id AS uuid)
                LIMIT 1
                """
            ),
            {"user_id": ctx.user_id},
        ).mappings().first()
        memberships = _rows(
            conn,
            """
            SELECT m.tenant_id::text, t.name AS tenant_name, t.slug AS tenant_slug, m.role, m.created_at::text
            FROM saas_memberships m
            JOIN saas_tenants t ON t.id = m.tenant_id
            WHERE m.user_id = CAST(:user_id AS uuid)
            ORDER BY m.created_at DESC
            """,
            {"user_id": ctx.user_id},
        )
        security_events = _rows(
            conn,
            """
            SELECT event_type, status, reason, created_at::text
            FROM saas_security_events
            WHERE user_id = CAST(:user_id AS uuid)
            ORDER BY created_at DESC
            LIMIT 100
            """,
            {"user_id": ctx.user_id},
        )
    return {"ok": True, "subject": "account", "user": dict(user or {}), "memberships": memberships, "security_events": security_events}


@router.get("/customers/{conversation_id}/export")
def export_customer_data(
    conversation_id: str,
    include_messages: bool = Query(True),
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        conversation = conn.execute(
            text(
                """
                SELECT *
                FROM saas_conversations
                WHERE id = CAST(:conversation_id AS uuid)
                  AND tenant_id = CAST(:tenant_id AS uuid)
                LIMIT 1
                """
            ),
            {"conversation_id": conversation_id, "tenant_id": ctx.tenant_id},
        ).mappings().first()
        if not conversation:
            raise HTTPException(status_code=404, detail="conversation_not_found")
        messages = []
        if include_messages:
            messages = _rows(
                conn,
                """
                SELECT id::text, channel, external_message_id, direction, msg_type, text, media_id, mime_type, payload_json, created_at::text
                FROM saas_messages
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND conversation_id = CAST(:conversation_id AS uuid)
                ORDER BY created_at ASC
                LIMIT 5000
                """,
                {"tenant_id": ctx.tenant_id, "conversation_id": conversation_id},
            )
        tasks = _rows(conn, "SELECT * FROM saas_crm_tasks WHERE tenant_id = CAST(:tenant_id AS uuid) AND conversation_id = CAST(:conversation_id AS uuid) ORDER BY created_at DESC", {"tenant_id": ctx.tenant_id, "conversation_id": conversation_id}) if _table_exists(conn, "saas_crm_tasks") else []
        timeline = _rows(conn, "SELECT * FROM saas_crm_timeline_events WHERE tenant_id = CAST(:tenant_id AS uuid) AND conversation_id = CAST(:conversation_id AS uuid) ORDER BY occurred_at DESC", {"tenant_id": ctx.tenant_id, "conversation_id": conversation_id}) if _table_exists(conn, "saas_crm_timeline_events") else []
        memory = _rows(conn, "SELECT id::text, summary, facts_json, last_message_id::text, created_at::text, updated_at::text FROM saas_conversation_memory WHERE tenant_id = CAST(:tenant_id AS uuid) AND conversation_id = CAST(:conversation_id AS uuid)", {"tenant_id": ctx.tenant_id, "conversation_id": conversation_id}) if _table_exists(conn, "saas_conversation_memory") else []
        agent_memory_archives = _rows(conn, "SELECT id::text, source_agent_id::text, source_agent_type, source_agent_name, title, notes, created_at::text FROM saas_ai_agent_memory_archives WHERE tenant_id = CAST(:tenant_id AS uuid) ORDER BY created_at DESC LIMIT 50", {"tenant_id": ctx.tenant_id}) if _table_exists(conn, "saas_ai_agent_memory_archives") else []
    return {
        "ok": True,
        "subject": "customer",
        "conversation": dict(conversation),
        "messages": messages,
        "tasks": tasks,
        "timeline": timeline,
        "conversation_memory": memory,
        "agent_memory_archives_sample": agent_memory_archives,
    }


@router.post("/customers/{conversation_id}/delete-request")
def request_customer_delete(
    conversation_id: str,
    reason: str = Query("", max_length=500),
    ctx: AuthContext = Depends(require_role("owner", "admin")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        conversation = conn.execute(
            text("SELECT id::text FROM saas_conversations WHERE id = CAST(:conversation_id AS uuid) AND tenant_id = CAST(:tenant_id AS uuid) LIMIT 1"),
            {"conversation_id": conversation_id, "tenant_id": ctx.tenant_id},
        ).mappings().first()
        if not conversation:
            raise HTTPException(status_code=404, detail="conversation_not_found")
        _ensure_privacy_requests(conn)
        row = conn.execute(
            text(
                """
                INSERT INTO saas_privacy_requests (
                    tenant_id, requester_user_id, subject_type, subject_id, request_type, status, reason, metadata_json
                )
                VALUES (
                    CAST(:tenant_id AS uuid), CAST(:user_id AS uuid), 'customer', :subject_id, 'delete', 'pending', :reason, CAST(:metadata_json AS jsonb)
                )
                RETURNING id::text, tenant_id::text, requester_user_id::text, subject_type, subject_id, request_type, status, reason, created_at::text
                """
            ),
            {
                "tenant_id": ctx.tenant_id,
                "user_id": ctx.user_id,
                "subject_id": conversation_id,
                "reason": reason,
                "metadata_json": _json({"source": "tenant_compliance_request"}),
            },
        ).mappings().first()
    return {"ok": True, "request": dict(row)}


@router.get("/privacy-requests")
def list_privacy_requests(ctx: AuthContext = Depends(require_role("owner", "admin"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_privacy_requests(conn)
        rows = _rows(
            conn,
            """
            SELECT id::text, tenant_id::text, requester_user_id::text, subject_type, subject_id, request_type, status, reason, metadata_json, created_at::text, updated_at::text
            FROM saas_privacy_requests
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY created_at DESC
            LIMIT 200
            """,
            {"tenant_id": ctx.tenant_id},
        )
    return {"ok": True, "requests": rows}
