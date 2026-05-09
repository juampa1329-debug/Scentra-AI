from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app_saas.billing.limits import ensure_monthly_message_quota
from app_saas.crm.schemas import CustomerUpdateIn, LabelCreateIn, LabelPatchIn, SendMessageIn
from app_saas.db import db_session, set_tenant_context
from app_saas.shared.security import AuthContext, get_current_user, require_role
from app_saas.workers.dispatch import process_due_outbound_messages
from app_saas.workers.triggers import execute_triggers_for_message

router = APIRouter(tags=["saas-crm"])

DEFAULT_LABELS = [
    ("VIP", "#5eead4", "Clientes prioritarios o de alto valor", "ventas"),
    ("Interes compra", "#60a5fa", "Pregunto precio, disponibilidad o referencias", "ventas"),
    ("Pago pendiente", "#fbbf24", "Cliente con pago o comprobante pendiente", "ventas"),
    ("Seguimiento 24h", "#a78bfa", "Debe recibir seguimiento comercial pronto", "automatizacion"),
    ("Recompra", "#34d399", "Candidato para recompra o fidelizacion", "retencion"),
]

CUSTOMER_FIELDS = {
    "display_name",
    "phone",
    "first_name",
    "last_name",
    "city",
    "customer_type",
    "interests",
    "tags",
    "notes",
    "payment_status",
    "payment_reference",
    "crm_stage",
    "intent",
    "profile_json",
}


def _period_yyyymm() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y%m")


def _clean_text(value: object, max_len: int = 4000) -> str:
    return str(value or "").strip()[:max_len]


def _normalize_tags(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = str(value).replace("\n", ",").split(",")

    seen: set[str] = set()
    tags: list[str] = []
    for item in raw_items:
        tag = _clean_text(item, 60)
        key = tag.lower()
        if tag and key not in seen:
            seen.add(key)
            tags.append(tag)
    return tags[:40]


def _tags_csv(tags: list[str]) -> str:
    return ", ".join(tags)


def _customer_row(row) -> dict:
    data = dict(row)
    labels = data.get("labels") or []
    if isinstance(labels, str):
        try:
            labels = json.loads(labels)
        except Exception:
            labels = []
    data["labels"] = labels
    data["tag_list"] = _normalize_tags(data.get("tags") or "")
    return data


def _ensure_default_labels(conn, tenant_id: str) -> None:
    count = conn.execute(
        text("SELECT COUNT(*) FROM saas_labels WHERE tenant_id = CAST(:tenant_id AS uuid)"),
        {"tenant_id": tenant_id},
    ).scalar_one()
    if int(count or 0) > 0:
        return

    for name, color, description, category in DEFAULT_LABELS:
        conn.execute(
            text(
                """
                INSERT INTO saas_labels (tenant_id, name, color, description, category)
                VALUES (CAST(:tenant_id AS uuid), :name, :color, :description, :category)
                ON CONFLICT DO NOTHING
                """
            ),
            {
                "tenant_id": tenant_id,
                "name": name,
                "color": color,
                "description": description,
                "category": category,
            },
        )


CUSTOMER_SELECT = """
    SELECT
        c.id::text,
        c.channel,
        c.external_contact_id,
        c.phone,
        c.display_name,
        c.first_name,
        c.last_name,
        c.city,
        c.customer_type,
        c.interests,
        c.takeover,
        c.last_message_text,
        c.last_message_at::text,
        c.unread_count,
        c.tags,
        c.notes,
        c.payment_status,
        c.payment_reference,
        c.crm_stage,
        c.intent,
        c.profile_json,
        c.last_profiled_at::text,
        c.updated_at::text,
        (
            SELECT COALESCE(
                jsonb_agg(
                    jsonb_build_object(
                        'id', l.id::text,
                        'name', l.name,
                        'color', l.color,
                        'category', l.category
                    )
                    ORDER BY l.name
                ),
                '[]'::jsonb
            )
            FROM saas_conversation_labels cl
            JOIN saas_labels l ON l.id = cl.label_id
            WHERE cl.tenant_id = c.tenant_id
              AND cl.conversation_id = c.id
        ) AS labels
    FROM saas_conversations c
"""


@router.get("/customers")
def list_customers(
    search: str = Query("", max_length=120),
    stage: str = Query("", max_length=80),
    payment_status: str = Query("", max_length=80),
    limit: int = Query(100, ge=1, le=500),
    ctx: AuthContext = Depends(get_current_user),
):
    term = str(search or "").strip().lower()
    where = ["c.tenant_id = CAST(:tenant_id AS uuid)"]
    params: dict[str, Any] = {"tenant_id": ctx.tenant_id, "limit": limit}
    if term:
        where.append(
            """
            (
                LOWER(c.phone) LIKE :term
                OR LOWER(c.display_name) LIKE :term
                OR LOWER(c.first_name) LIKE :term
                OR LOWER(c.last_name) LIKE :term
                OR LOWER(c.city) LIKE :term
                OR LOWER(c.customer_type) LIKE :term
                OR LOWER(c.interests) LIKE :term
                OR LOWER(COALESCE(c.tags, '')) LIKE :term
                OR LOWER(c.external_contact_id) LIKE :term
            )
            """
        )
        params["term"] = f"%{term}%"
    if stage:
        where.append("LOWER(c.crm_stage) = :stage")
        params["stage"] = stage.strip().lower()
    if payment_status:
        where.append("LOWER(c.payment_status) = :payment_status")
        params["payment_status"] = payment_status.strip().lower()

    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        rows = conn.execute(
            text(
                f"""
                {CUSTOMER_SELECT}
                WHERE {" AND ".join(where)}
                ORDER BY c.updated_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
    return {"tenant_id": ctx.tenant_id, "customers": [_customer_row(row) for row in rows]}


@router.get("/customers/{conversation_id}")
def get_customer(conversation_id: str, ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        row = conn.execute(
            text(
                f"""
                {CUSTOMER_SELECT}
                WHERE c.tenant_id = CAST(:tenant_id AS uuid)
                  AND c.id = CAST(:conversation_id AS uuid)
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id, "conversation_id": conversation_id},
        ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="customer_not_found")
    return {"tenant_id": ctx.tenant_id, "customer": _customer_row(row)}


@router.patch("/customers/{conversation_id}")
def update_customer(
    conversation_id: str,
    payload: CustomerUpdateIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor", "agent")),
):
    raw = payload.model_dump(exclude_unset=True)
    data = {key: value for key, value in raw.items() if key in CUSTOMER_FIELDS and value is not None}
    if not data:
        raise HTTPException(status_code=400, detail="customer_patch_required")

    assignments: list[str] = []
    params: dict[str, Any] = {"tenant_id": ctx.tenant_id, "conversation_id": conversation_id}
    for key, value in data.items():
        if key == "tags":
            params[key] = _tags_csv(_normalize_tags(value))
            assignments.append("tags = :tags")
        elif key == "profile_json":
            params[key] = json.dumps(value or {})
            assignments.append("profile_json = CAST(:profile_json AS jsonb)")
            assignments.append("last_profiled_at = NOW()")
        else:
            params[key] = _clean_text(value)
            assignments.append(f"{key} = :{key}")

    assignments.append("updated_at = NOW()")

    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        row = conn.execute(
            text(
                f"""
                UPDATE saas_conversations
                SET {", ".join(assignments)}
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:conversation_id AS uuid)
                RETURNING id::text
                """
            ),
            params,
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="customer_not_found")

        updated = conn.execute(
            text(
                f"""
                {CUSTOMER_SELECT}
                WHERE c.tenant_id = CAST(:tenant_id AS uuid)
                  AND c.id = CAST(:conversation_id AS uuid)
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id, "conversation_id": conversation_id},
        ).mappings().first()

    return {"ok": True, "tenant_id": ctx.tenant_id, "customer": _customer_row(updated)}


@router.get("/labels")
def list_labels(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_default_labels(conn, ctx.tenant_id)
        rows = conn.execute(
            text(
                """
                SELECT
                    l.id::text,
                    l.name,
                    l.color,
                    l.description,
                    l.category,
                    l.is_active,
                    l.created_at::text,
                    l.updated_at::text,
                    COUNT(cl.label_id)::int AS usage_count
                FROM saas_labels l
                LEFT JOIN saas_conversation_labels cl
                    ON cl.tenant_id = l.tenant_id
                   AND cl.label_id = l.id
                WHERE l.tenant_id = CAST(:tenant_id AS uuid)
                GROUP BY l.id
                ORDER BY l.is_active DESC, LOWER(l.name) ASC
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().all()
    return {"tenant_id": ctx.tenant_id, "labels": [dict(row) for row in rows]}


@router.post("/labels")
def create_label(
    payload: LabelCreateIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    name = _clean_text(payload.name, 80)
    if not name:
        raise HTTPException(status_code=400, detail="label_name_required")
    try:
        with db_session() as conn:
            set_tenant_context(conn, ctx.tenant_id)
            row = conn.execute(
                text(
                    """
                    INSERT INTO saas_labels (tenant_id, name, color, description, category)
                    VALUES (CAST(:tenant_id AS uuid), :name, :color, :description, :category)
                    RETURNING
                        id::text,
                        name,
                        color,
                        description,
                        category,
                        is_active,
                        created_at::text,
                        updated_at::text,
                        0::int AS usage_count
                    """
                ),
                {
                    "tenant_id": ctx.tenant_id,
                    "name": name,
                    "color": _clean_text(payload.color, 32) or "#5eead4",
                    "description": _clean_text(payload.description, 500),
                    "category": _clean_text(payload.category, 80) or "general",
                },
            ).mappings().first()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="label_already_exists")
    return {"ok": True, "tenant_id": ctx.tenant_id, "label": dict(row)}


@router.patch("/labels/{label_id}")
def update_label(
    label_id: str,
    payload: LabelPatchIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    raw = payload.model_dump(exclude_unset=True)
    data = {key: value for key, value in raw.items() if value is not None}
    if not data:
        raise HTTPException(status_code=400, detail="label_patch_required")

    assignments: list[str] = []
    params: dict[str, Any] = {"tenant_id": ctx.tenant_id, "label_id": label_id}
    for key, value in data.items():
        if key == "is_active":
            params[key] = bool(value)
        else:
            params[key] = _clean_text(value, 500 if key == "description" else 80)
            if key == "name" and not params[key]:
                raise HTTPException(status_code=400, detail="label_name_required")
        assignments.append(f"{key} = :{key}")
    assignments.append("updated_at = NOW()")

    try:
        with db_session() as conn:
            set_tenant_context(conn, ctx.tenant_id)
            row = conn.execute(
                text(
                    f"""
                    UPDATE saas_labels
                    SET {", ".join(assignments)}
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND id = CAST(:label_id AS uuid)
                    RETURNING
                        id::text,
                        name,
                        color,
                        description,
                        category,
                        is_active,
                        created_at::text,
                        updated_at::text
                    """
                ),
                params,
            ).mappings().first()
            if not row:
                raise HTTPException(status_code=404, detail="label_not_found")
    except IntegrityError:
        raise HTTPException(status_code=409, detail="label_already_exists")
    return {"ok": True, "tenant_id": ctx.tenant_id, "label": dict(row)}


@router.post("/customers/{conversation_id}/labels/{label_id}")
def assign_customer_label(
    conversation_id: str,
    label_id: str,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor", "agent")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        row = conn.execute(
            text(
                """
                SELECT c.tags, l.name
                FROM saas_conversations c
                JOIN saas_labels l
                  ON l.tenant_id = c.tenant_id
                 AND l.id = CAST(:label_id AS uuid)
                 AND l.is_active = TRUE
                WHERE c.tenant_id = CAST(:tenant_id AS uuid)
                  AND c.id = CAST(:conversation_id AS uuid)
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id, "conversation_id": conversation_id, "label_id": label_id},
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="customer_or_label_not_found")

        conn.execute(
            text(
                """
                INSERT INTO saas_conversation_labels (tenant_id, conversation_id, label_id)
                VALUES (
                    CAST(:tenant_id AS uuid),
                    CAST(:conversation_id AS uuid),
                    CAST(:label_id AS uuid)
                )
                ON CONFLICT DO NOTHING
                """
            ),
            {"tenant_id": ctx.tenant_id, "conversation_id": conversation_id, "label_id": label_id},
        )
        tags = _normalize_tags(row["tags"])
        label_name = str(row["name"])
        if label_name.lower() not in {tag.lower() for tag in tags}:
            tags.append(label_name)
        conn.execute(
            text(
                """
                UPDATE saas_conversations
                SET tags = :tags, updated_at = NOW()
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:conversation_id AS uuid)
                """
            ),
            {"tenant_id": ctx.tenant_id, "conversation_id": conversation_id, "tags": _tags_csv(tags)},
        )
    return {"ok": True, "tenant_id": ctx.tenant_id}


@router.delete("/customers/{conversation_id}/labels/{label_id}")
def remove_customer_label(
    conversation_id: str,
    label_id: str,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor", "agent")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        row = conn.execute(
            text(
                """
                SELECT c.tags, l.name
                FROM saas_conversations c
                JOIN saas_labels l
                  ON l.tenant_id = c.tenant_id
                 AND l.id = CAST(:label_id AS uuid)
                WHERE c.tenant_id = CAST(:tenant_id AS uuid)
                  AND c.id = CAST(:conversation_id AS uuid)
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id, "conversation_id": conversation_id, "label_id": label_id},
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="customer_or_label_not_found")

        conn.execute(
            text(
                """
                DELETE FROM saas_conversation_labels
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND conversation_id = CAST(:conversation_id AS uuid)
                  AND label_id = CAST(:label_id AS uuid)
                """
            ),
            {"tenant_id": ctx.tenant_id, "conversation_id": conversation_id, "label_id": label_id},
        )
        label_key = str(row["name"]).lower()
        tags = [tag for tag in _normalize_tags(row["tags"]) if tag.lower() != label_key]
        conn.execute(
            text(
                """
                UPDATE saas_conversations
                SET tags = :tags, updated_at = NOW()
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:conversation_id AS uuid)
                """
            ),
            {"tenant_id": ctx.tenant_id, "conversation_id": conversation_id, "tags": _tags_csv(tags)},
        )
    return {"ok": True, "tenant_id": ctx.tenant_id}


@router.get("/conversations")
def list_conversations(
    search: str = Query("", max_length=120),
    limit: int = Query(100, ge=1, le=500),
    ctx: AuthContext = Depends(get_current_user),
):
    term = str(search or "").strip().lower()
    where = ["tenant_id = CAST(:tenant_id AS uuid)"]
    params: dict[str, Any] = {"tenant_id": ctx.tenant_id, "limit": limit}
    if term:
        where.append(
            """
            (
                LOWER(phone) LIKE :term
                OR LOWER(display_name) LIKE :term
                OR LOWER(COALESCE(tags, '')) LIKE :term
                OR LOWER(external_contact_id) LIKE :term
            )
            """
        )
        params["term"] = f"%{term}%"

    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        rows = conn.execute(
            text(
                f"""
                SELECT
                    id::text,
                    channel,
                    external_contact_id,
                    phone,
                    display_name,
                    takeover,
                    last_message_text,
                    last_message_at,
                    unread_count,
                    tags,
                    notes,
                    updated_at
                FROM saas_conversations
                WHERE {" AND ".join(where)}
                ORDER BY updated_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
    return {"tenant_id": ctx.tenant_id, "conversations": [dict(row) for row in rows]}


@router.get("/conversations/{conversation_id}/messages")
def list_messages(
    conversation_id: str,
    limit: int = Query(200, ge=1, le=500),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        conversation = conn.execute(
            text(
                """
                SELECT id::text, external_contact_id, phone
                FROM saas_conversations
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:conversation_id AS uuid)
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id, "conversation_id": conversation_id},
        ).mappings().first()
        if not conversation:
            raise HTTPException(status_code=404, detail="conversation_not_found")

        rows = conn.execute(
            text(
                """
                SELECT
                    id::text,
                    channel,
                    external_message_id,
                    direction,
                    msg_type,
                    text,
                    media_id,
                    mime_type,
                    created_at::text
                FROM saas_messages
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND conversation_id = CAST(:conversation_id AS uuid)
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            {"tenant_id": ctx.tenant_id, "conversation_id": conversation_id, "limit": limit},
        ).mappings().all()

    messages = [dict(row) for row in rows]
    messages.reverse()
    return {"tenant_id": ctx.tenant_id, "conversation": dict(conversation), "messages": messages}


@router.post("/conversations/{conversation_id}/messages")
def send_message(
    conversation_id: str,
    payload: SendMessageIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor", "agent")),
):
    body_text = payload.text.strip()
    if not body_text:
        raise HTTPException(status_code=400, detail="message_text_required")

    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        conversation = conn.execute(
            text(
                """
                SELECT id::text, channel, external_contact_id, phone
                FROM saas_conversations
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:conversation_id AS uuid)
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id, "conversation_id": conversation_id},
        ).mappings().first()
        if not conversation:
            raise HTTPException(status_code=404, detail="conversation_not_found")

        channel = payload.channel.strip().lower() or str(conversation["channel"])
        if channel != str(conversation["channel"]):
            raise HTTPException(status_code=400, detail="conversation_channel_mismatch")

        ensure_monthly_message_quota(conn, ctx.tenant_id, requested=1)

        local_external_id = f"local:out:{uuid4().hex}"
        message_payload = {
            "source": "saas_console",
            "actor_user_id": ctx.user_id,
            "dispatch_status": "queued",
        }
        message = conn.execute(
            text(
                """
                INSERT INTO saas_messages (
                    tenant_id,
                    conversation_id,
                    channel,
                    external_message_id,
                    direction,
                    msg_type,
                    text,
                    payload_json
                )
                VALUES (
                    CAST(:tenant_id AS uuid),
                    CAST(:conversation_id AS uuid),
                    :channel,
                    :external_message_id,
                    'out',
                    'text',
                    :body_text,
                    CAST(:payload_json AS jsonb)
                )
                RETURNING
                    id::text,
                    channel,
                    external_message_id,
                    direction,
                    msg_type,
                    text,
                    media_id,
                    mime_type,
                    created_at::text
                """
            ),
            {
                "tenant_id": ctx.tenant_id,
                "conversation_id": conversation_id,
                "channel": channel,
                "external_message_id": local_external_id,
                "body_text": body_text,
                "payload_json": json.dumps(message_payload),
            },
        ).mappings().first()

        outbound = conn.execute(
            text(
                """
                INSERT INTO saas_outbound_messages (
                    tenant_id,
                    conversation_id,
                    message_id,
                    channel,
                    recipient_external_id,
                    body_text,
                    payload_json
                )
                VALUES (
                    CAST(:tenant_id AS uuid),
                    CAST(:conversation_id AS uuid),
                    CAST(:message_id AS uuid),
                    :channel,
                    :recipient_external_id,
                    :body_text,
                    CAST(:payload_json AS jsonb)
                )
                RETURNING id::text, status, attempts, next_attempt_at::text
                """
            ),
            {
                "tenant_id": ctx.tenant_id,
                "conversation_id": conversation_id,
                "message_id": message["id"],
                "channel": channel,
                "recipient_external_id": str(conversation["external_contact_id"] or conversation["phone"] or ""),
                "body_text": body_text,
                "payload_json": json.dumps({"local_external_message_id": local_external_id}),
            },
        ).mappings().first()

        conn.execute(
            text(
                """
                UPDATE saas_conversations
                SET
                    last_message_text = :body_text,
                    last_message_at = NOW(),
                    updated_at = NOW()
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:conversation_id AS uuid)
                """
            ),
            {"tenant_id": ctx.tenant_id, "conversation_id": conversation_id, "body_text": body_text},
        )
        conn.execute(
            text(
                """
                INSERT INTO saas_usage_counters (tenant_id, metric_code, period_yyyymm, metric_value)
                VALUES (CAST(:tenant_id AS uuid), 'outbound_messages_queued', :period, 1)
                ON CONFLICT (tenant_id, metric_code, period_yyyymm)
                DO UPDATE SET
                    metric_value = saas_usage_counters.metric_value + 1,
                    updated_at = NOW()
                """
            ),
            {"tenant_id": ctx.tenant_id, "period": _period_yyyymm()},
        )
        trigger_result = execute_triggers_for_message(
            conn,
            tenant_id=ctx.tenant_id,
            conversation_id=conversation_id,
            message_id=message["id"],
            event_kind="sent",
        )

    return {
        "ok": True,
        "tenant_id": ctx.tenant_id,
        "message": dict(message),
        "outbound": dict(outbound),
        "triggers": trigger_result,
    }


@router.post("/outbound/process")
def process_outbound_now(
    limit: int = Query(25, ge=1, le=200),
    ctx: AuthContext = Depends(require_role("owner", "admin")),
):
    result = process_due_outbound_messages(limit=limit, tenant_id=ctx.tenant_id)
    return {"ok": True, "tenant_id": ctx.tenant_id, "result": result}


@router.post("/conversations/{conversation_id}/read")
def mark_conversation_read(
    conversation_id: str,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor", "agent")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        result = conn.execute(
            text(
                """
                UPDATE saas_conversations
                SET unread_count = 0, updated_at = NOW()
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:conversation_id AS uuid)
                """
            ),
            {"tenant_id": ctx.tenant_id, "conversation_id": conversation_id},
        )
        if int(result.rowcount or 0) <= 0:
            raise HTTPException(status_code=404, detail="conversation_not_found")
    return {"ok": True}


@router.post("/conversations/{conversation_id}/takeover")
def set_takeover(
    conversation_id: str,
    takeover: bool = Query(...),
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor", "agent")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        result = conn.execute(
            text(
                """
                UPDATE saas_conversations
                SET takeover = :takeover, updated_at = NOW()
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:conversation_id AS uuid)
                """
            ),
            {"tenant_id": ctx.tenant_id, "conversation_id": conversation_id, "takeover": bool(takeover)},
        )
        if int(result.rowcount or 0) <= 0:
            raise HTTPException(status_code=404, detail="conversation_not_found")
    return {"ok": True, "takeover": bool(takeover)}
