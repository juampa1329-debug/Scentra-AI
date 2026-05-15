from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app_saas.billing.limits import ensure_monthly_message_quota
from app_saas.crm.schemas import CustomerCreateIn, CustomerUpdateIn, LabelCreateIn, LabelPatchIn, SendMessageIn
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
    "takeover",
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


@router.get("/dashboard/overview")
def dashboard_overview(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        totals = conn.execute(
            text(
                """
                SELECT
                    COUNT(*)::int AS conversations,
                    COALESCE(SUM(unread_count), 0)::int AS unread,
                    COUNT(*) FILTER (WHERE takeover = TRUE)::int AS takeover,
                    COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '30 days')::int AS new_customers_30d,
                    COUNT(*) FILTER (WHERE payment_status = 'pending')::int AS pending_payments,
                    COUNT(*) FILTER (WHERE payment_status = 'paid')::int AS paid_customers
                FROM saas_conversations
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().first() or {}

        message_totals = conn.execute(
            text(
                """
                SELECT
                    COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '30 days')::int AS messages_30d,
                    COUNT(*) FILTER (WHERE direction = 'in' AND created_at >= NOW() - INTERVAL '30 days')::int AS inbound_30d,
                    COUNT(*) FILTER (WHERE direction = 'out' AND created_at >= NOW() - INTERVAL '30 days')::int AS outbound_30d
                FROM saas_messages
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().first() or {}

        funnel_rows = conn.execute(
            text(
                """
                SELECT COALESCE(NULLIF(crm_stage, ''), 'sin_etapa') AS stage, COUNT(*)::int AS count
                FROM saas_conversations
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                GROUP BY COALESCE(NULLIF(crm_stage, ''), 'sin_etapa')
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().all()

        payment_rows = conn.execute(
            text(
                """
                SELECT COALESCE(NULLIF(payment_status, ''), 'sin_estado') AS status, COUNT(*)::int AS count
                FROM saas_conversations
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                GROUP BY COALESCE(NULLIF(payment_status, ''), 'sin_estado')
                ORDER BY count DESC, status ASC
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().all()

        channel_rows = conn.execute(
            text(
                """
                SELECT channel, COUNT(*)::int AS count
                FROM saas_conversations
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                GROUP BY channel
                ORDER BY count DESC, channel ASC
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().all()

        activity_rows = conn.execute(
            text(
                """
                WITH days AS (
                    SELECT generate_series((CURRENT_DATE - INTERVAL '13 days')::date, CURRENT_DATE, INTERVAL '1 day')::date AS day
                ),
                message_counts AS (
                    SELECT
                        created_at::date AS day,
                        COUNT(*) FILTER (WHERE direction = 'in')::int AS inbound,
                        COUNT(*) FILTER (WHERE direction = 'out')::int AS outbound,
                        COUNT(*)::int AS total
                    FROM saas_messages
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND created_at >= CURRENT_DATE - INTERVAL '13 days'
                    GROUP BY created_at::date
                )
                SELECT
                    days.day::text AS date,
                    COALESCE(message_counts.inbound, 0)::int AS inbound,
                    COALESCE(message_counts.outbound, 0)::int AS outbound,
                    COALESCE(message_counts.total, 0)::int AS total
                FROM days
                LEFT JOIN message_counts ON message_counts.day = days.day
                ORDER BY days.day ASC
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().all()

        recent_rows = conn.execute(
            text(
                """
                SELECT
                    m.created_at::text,
                    m.direction,
                    m.msg_type,
                    LEFT(COALESCE(NULLIF(m.text, ''), '[' || m.msg_type || ']'), 220) AS text,
                    c.channel,
                    c.display_name,
                    c.phone,
                    c.external_contact_id
                FROM saas_messages m
                JOIN saas_conversations c ON c.id = m.conversation_id
                WHERE m.tenant_id = CAST(:tenant_id AS uuid)
                ORDER BY m.created_at DESC
                LIMIT 8
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().all()

    total_conversations = int(totals.get("conversations") or 0)
    stage_order = ["contactado", "interes", "intencion_compra", "pago_pendiente", "pago_confirmado", "sin_etapa"]
    stage_labels = {
        "contactado": "Contactados",
        "interes": "Interes",
        "intencion_compra": "Intencion de compra",
        "pago_pendiente": "Pago pendiente",
        "pago_confirmado": "Pago confirmado",
        "sin_etapa": "Sin etapa",
    }
    funnel_map = {str(row["stage"]): int(row["count"] or 0) for row in funnel_rows}
    funnel = [
        {
            "stage": stage,
            "label": stage_labels.get(stage, stage.replace("_", " ").title()),
            "count": funnel_map.get(stage, 0),
            "pct": round((funnel_map.get(stage, 0) / total_conversations) * 100, 2) if total_conversations else 0,
        }
        for stage in stage_order
        if stage in funnel_map or stage != "sin_etapa"
    ]

    return {
        "tenant_id": ctx.tenant_id,
        "totals": {**dict(totals), **dict(message_totals)},
        "funnel": funnel,
        "payments": [dict(row) for row in payment_rows],
        "channels": [dict(row) for row in channel_rows],
        "activity": [dict(row) for row in activity_rows],
        "recent": [dict(row) for row in recent_rows],
    }


@router.post("/customers")
def create_customer(
    payload: CustomerCreateIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor", "agent")),
):
    raw = payload.model_dump(exclude_unset=True)
    channel = _clean_text(raw.get("channel"), 40).lower() or "whatsapp"
    phone = _clean_text(raw.get("phone"), 80)
    display_name = _clean_text(raw.get("display_name"), 160)
    external_contact_id = _clean_text(raw.get("external_contact_id"), 180) or phone
    if not external_contact_id:
        external_contact_id = f"manual:{uuid4().hex}"
    if not display_name and not phone and external_contact_id.startswith("manual:"):
        raise HTTPException(status_code=400, detail="customer_name_or_phone_required")

    params: dict[str, Any] = {
        "tenant_id": ctx.tenant_id,
        "channel": channel,
        "external_contact_id": external_contact_id,
        "phone": phone,
        "display_name": display_name or phone or "Cliente manual",
        "first_name": _clean_text(raw.get("first_name"), 100),
        "last_name": _clean_text(raw.get("last_name"), 100),
        "city": _clean_text(raw.get("city"), 120),
        "customer_type": _clean_text(raw.get("customer_type"), 80),
        "interests": _clean_text(raw.get("interests"), 800),
        "tags": _tags_csv(_normalize_tags(raw.get("tags"))),
        "notes": _clean_text(raw.get("notes"), 4000),
        "payment_status": _clean_text(raw.get("payment_status"), 80),
        "payment_reference": _clean_text(raw.get("payment_reference"), 160),
        "crm_stage": _clean_text(raw.get("crm_stage"), 80) or "contactado",
        "intent": _clean_text(raw.get("intent"), 120),
        "profile_json": json.dumps(raw.get("profile_json") or {}),
        "last_message_text": "Cliente creado manualmente",
    }

    try:
        with db_session() as conn:
            set_tenant_context(conn, ctx.tenant_id)
            row = conn.execute(
                text(
                    """
                    INSERT INTO saas_conversations (
                        tenant_id,
                        channel,
                        external_contact_id,
                        phone,
                        display_name,
                        first_name,
                        last_name,
                        city,
                        customer_type,
                        interests,
                        tags,
                        notes,
                        payment_status,
                        payment_reference,
                        crm_stage,
                        intent,
                        profile_json,
                        last_message_text,
                        updated_at
                    )
                    VALUES (
                        CAST(:tenant_id AS uuid),
                        :channel,
                        :external_contact_id,
                        :phone,
                        :display_name,
                        :first_name,
                        :last_name,
                        :city,
                        :customer_type,
                        :interests,
                        :tags,
                        :notes,
                        :payment_status,
                        :payment_reference,
                        :crm_stage,
                        :intent,
                        CAST(:profile_json AS jsonb),
                        :last_message_text,
                        NOW()
                    )
                    RETURNING id::text
                    """
                ),
                params,
            ).mappings().first()

            created = conn.execute(
                text(
                    f"""
                    {CUSTOMER_SELECT}
                    WHERE c.tenant_id = CAST(:tenant_id AS uuid)
                      AND c.id = CAST(:conversation_id AS uuid)
                    LIMIT 1
                    """
                ),
                {"tenant_id": ctx.tenant_id, "conversation_id": row["id"]},
            ).mappings().first()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="customer_already_exists")

    return {"ok": True, "tenant_id": ctx.tenant_id, "customer": _customer_row(created)}


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
        elif key == "takeover":
            params[key] = bool(value)
            assignments.append("takeover = :takeover")
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
                    first_name,
                    last_name,
                    city,
                    customer_type,
                    interests,
                    takeover,
                    last_message_text,
                    last_message_at::text,
                    unread_count,
                    tags,
                    notes,
                    payment_status,
                    payment_reference,
                    crm_stage,
                    intent,
                    profile_json,
                    updated_at::text
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
                    payload_json,
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
    requested_media_id = payload.media_id.strip()
    requested_type = payload.msg_type.strip().lower() or ("file" if requested_media_id else "text")
    allowed_types = {"text", "image", "video", "audio", "document", "file"}
    if requested_type not in allowed_types:
        raise HTTPException(status_code=400, detail="unsupported_message_type")
    if not body_text and not requested_media_id:
        raise HTTPException(status_code=400, detail="message_content_required")

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

        media_id = ""
        mime_type = payload.mime_type.strip()
        filename = payload.filename.strip()
        message_type = requested_type
        if requested_media_id:
            asset = conn.execute(
                text(
                    """
                    SELECT id::text, kind, filename, content_type, byte_size
                    FROM saas_media_assets
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND id::text = :media_id
                    LIMIT 1
                    """
                ),
                {"tenant_id": ctx.tenant_id, "media_id": requested_media_id},
            ).mappings().first()
            if not asset:
                raise HTTPException(status_code=404, detail="media_not_found")
            media_id = asset["id"]
            mime_type = mime_type or str(asset["content_type"] or "")
            filename = filename or str(asset["filename"] or "")
            if requested_type in {"text", "file"}:
                asset_kind = str(asset["kind"] or "file").lower()
                message_type = asset_kind if asset_kind in allowed_types else "file"
            if message_type == "file":
                message_type = "document"

        local_external_id = f"local:out:{uuid4().hex}"
        message_payload = {
            "source": "saas_console",
            "actor_user_id": ctx.user_id,
            "dispatch_status": "queued",
            "message_type": message_type,
            "media_id": media_id,
            "mime_type": mime_type,
            "filename": filename,
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
                    media_id,
                    mime_type,
                    payload_json
                )
                VALUES (
                    CAST(:tenant_id AS uuid),
                    CAST(:conversation_id AS uuid),
                    :channel,
                    :external_message_id,
                    'out',
                    :msg_type,
                    :body_text,
                    :media_id,
                    :mime_type,
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
                "msg_type": message_type,
                "body_text": body_text,
                "media_id": media_id,
                "mime_type": mime_type,
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
                "payload_json": json.dumps({
                    "local_external_message_id": local_external_id,
                    "source": "saas_console",
                    "message_type": message_type,
                    "media_id": media_id,
                    "mime_type": mime_type,
                    "filename": filename,
                }),
            },
        ).mappings().first()

        last_preview = body_text or f"[{message_type}]"
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
            {"tenant_id": ctx.tenant_id, "conversation_id": conversation_id, "body_text": last_preview},
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

    try:
        dispatch_result = process_due_outbound_messages(limit=5, tenant_id=ctx.tenant_id)
    except Exception as exc:
        dispatch_result = {"picked": 0, "sent": 0, "blocked": 0, "failed": 1, "last_error": str(exc)[:300], "errors": [{"error": str(exc)[:300]}]}

    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        outbound_status = conn.execute(
            text(
                """
                SELECT id::text, status, provider, error, attempts, payload_json, updated_at::text
                FROM saas_outbound_messages
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:outbound_id AS uuid)
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id, "outbound_id": outbound["id"]},
        ).mappings().first()
    if outbound_status and outbound_status.get("error") and not dispatch_result.get("last_error"):
        dispatch_result["last_error"] = str(outbound_status["error"])

    return {
        "ok": True,
        "tenant_id": ctx.tenant_id,
        "message": dict(message),
        "outbound": dict(outbound),
        "outbound_status": dict(outbound_status) if outbound_status else None,
        "dispatch": dispatch_result,
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
