from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app_saas.billing.limits import ensure_campaign_quota, ensure_feature_enabled, ensure_tenant_operational
from app_saas.campaigns.schemas import (
    CampaignIn,
    CampaignPatchIn,
    FlowIn,
    FlowPatchIn,
    SegmentIn,
    SegmentPatchIn,
    SegmentPreviewIn,
    TemplateIn,
    TemplatePatchIn,
    TriggerCopyIn,
    TriggerIn,
    TriggerPatchIn,
)
from app_saas.db import db_session, set_tenant_context
from app_saas.shared.security import AuthContext, get_current_user, require_role
from app_saas.workers.remarketing import process_due_remarketing_flows

router = APIRouter(prefix="/campaigns", tags=["saas-campaigns"])


def _clean_text(value: object, max_len: int = 4000) -> str:
    return str(value or "").strip()[:max_len]


def _clean_channel(value: object) -> str:
    return _clean_text(value, 40).lower() or "whatsapp"


def _clean_id(value: object) -> str:
    return _clean_text(value, 80)


def _json_dump(value: Any, fallback: Any) -> str:
    if value is None:
        value = fallback
    return json.dumps(value, ensure_ascii=False)


def _row_dict(row) -> dict:
    return dict(row) if row else {}


def _segment_where(filters: dict[str, Any], params: dict[str, Any]) -> list[str]:
    filters = filters if isinstance(filters, dict) else {}
    where = ["tenant_id = CAST(:tenant_id AS uuid)"]

    for key in ("crm_stage", "payment_status", "city", "customer_type", "intent", "channel"):
        value = _clean_text(filters.get(key), 120).lower()
        if not value:
            continue
        param_key = f"filter_{key}"
        if key == "city":
            params[param_key] = f"%{value}%"
            where.append(f"LOWER(COALESCE({key}, '')) LIKE :{param_key}")
        else:
            params[param_key] = value
            where.append(f"LOWER(COALESCE({key}, '')) = :{param_key}")

    tag = _clean_text(filters.get("tag"), 120).lower()
    if tag:
        params["filter_tag"] = f"%{tag}%"
        where.append("LOWER(COALESCE(tags, '')) LIKE :filter_tag")

    search = _clean_text(filters.get("search"), 120).lower()
    if search:
        params["filter_search"] = f"%{search}%"
        where.append(
            """
            (
                LOWER(COALESCE(display_name, '')) LIKE :filter_search
                OR LOWER(COALESCE(phone, '')) LIKE :filter_search
                OR LOWER(COALESCE(interests, '')) LIKE :filter_search
                OR LOWER(COALESCE(notes, '')) LIKE :filter_search
            )
            """
        )

    takeover = _clean_text(filters.get("takeover"), 20).lower()
    if takeover in ("on", "true", "human"):
        where.append("takeover = TRUE")
    elif takeover in ("off", "false", "ai"):
        where.append("takeover = FALSE")

    return where


def _count_segment(conn, tenant_id: str, filters: dict[str, Any]) -> int:
    params: dict[str, Any] = {"tenant_id": tenant_id}
    where = _segment_where(filters, params)
    return int(
        conn.execute(
            text(f"SELECT COUNT(*) FROM saas_conversations WHERE {' AND '.join(where)}"),
            params,
        ).scalar_one()
        or 0
    )


def _fetch_segment_filters(conn, tenant_id: str, segment_id: str) -> dict[str, Any]:
    if not segment_id:
        return {}
    row = conn.execute(
        text(
            """
            SELECT filters_json
            FROM saas_segments
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:segment_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "segment_id": segment_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="segment_not_found")
    return row["filters_json"] if isinstance(row["filters_json"], dict) else {}


def _list_rows(conn, sql: str, params: dict[str, Any]) -> list[dict]:
    return [dict(row) for row in conn.execute(text(sql), params).mappings().all()]


def _ensure_triggers(conn, tenant_id: str) -> None:
    ensure_feature_enabled(conn, tenant_id, "triggers")


def _ensure_remarketing(conn, tenant_id: str) -> None:
    ensure_feature_enabled(conn, tenant_id, "remarketing")


@router.get("/catalog")
def get_campaign_catalog(ctx: AuthContext = Depends(get_current_user)):
    return {
        "tenant_id": ctx.tenant_id,
        "channels": ["whatsapp", "instagram", "facebook", "tiktok"],
        "template_status": ["draft", "approved", "archived"],
        "meta_template_status": ["pending", "approved", "rejected", "paused", "disabled"],
        "campaign_status": ["draft", "scheduled", "running", "paused", "completed"],
        "trigger_events": ["message_in", "message_out", "comment_in", "tag_changed", "time"],
        "trigger_types": ["message_flow", "comment_flow", "tag_changed", "logic", "time"],
        "flow_events": ["received", "sent", "both"],
        "trigger_conditions": ["last_message_sent", "sent_count", "check_words", "comment_keywords", "template_sent_status", "current_tag", "schedule"],
        "trigger_actions": ["send_template", "reply_comment", "change_tag", "configure_conversation", "change_contact_status", "notify_admins", "extract_conversation_info", "schedule_message"],
        "segment_filters": ["tag", "crm_stage", "payment_status", "city", "customer_type", "intent", "takeover", "channel"],
    }


@router.get("/templates/params/catalog")
def template_params_catalog(ctx: AuthContext = Depends(get_current_user)):
    return {
        "tenant_id": ctx.tenant_id,
        "params": [
            {"key": "customer_name", "label": "Nombre del cliente", "group": "system_variable", "example": "Juan Perez"},
            {"key": "customer_first_name", "label": "Primer nombre", "group": "system_variable", "example": "Juan"},
            {"key": "customer_phone", "label": "Telefono", "group": "system_variable", "example": "+573001112233"},
            {"key": "customer_email", "label": "Email", "group": "system_variable", "example": "cliente@email.com"},
            {"key": "customer_city", "label": "Ciudad", "group": "system_variable", "example": "Bogota"},
            {"key": "crm_stage", "label": "Etapa CRM", "group": "system_variable", "example": "interes"},
            {"key": "payment_status", "label": "Estado de pago", "group": "system_variable", "example": "pending"},
            {"key": "interests", "label": "Intereses", "group": "custom_field", "example": "perfume amaderado"},
            {"key": "tags", "label": "Etiquetas", "group": "custom_field", "example": "VIP"},
            {"key": "assistant_name", "label": "Asesor IA", "group": "system_variable", "example": "Laura"},
            {"key": "business_name", "label": "Empresa", "group": "system_variable", "example": "Scentra +AI"},
        ],
    }


@router.get("/triggers/catalog")
def triggers_catalog(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_triggers(conn, ctx.tenant_id)
        return {
            "tenant_id": ctx.tenant_id,
            "event_types": [
                {"key": "message_in", "label": "Mensaje entrante"},
                {"key": "message_out", "label": "Mensaje saliente"},
                {"key": "comment_in", "label": "Comentario entrante"},
                {"key": "tag_changed", "label": "Etiqueta cambiada"},
                {"key": "time", "label": "Tiempo"},
            ],
            "trigger_types": [
                {"key": "none", "label": "Ninguna"},
                {"key": "message_flow", "label": "Flujo de mensajes"},
                {"key": "comment_flow", "label": "Flujo de comentarios"},
                {"key": "tag_changed", "label": "Etiqueta cambiada"},
                {"key": "logic", "label": "Logica"},
                {"key": "time", "label": "Tiempo"},
            ],
            "flow_events": [
                {"key": "received", "label": "Recibido"},
                {"key": "sent", "label": "Enviado"},
                {"key": "both", "label": "Envian y reciben"},
            ],
            "condition_types": [
                {"key": "last_message_sent", "label": "Ultimo mensaje enviado"},
                {"key": "sent_count", "label": "Cantidad de mensajes enviado"},
                {"key": "check_words", "label": "Comprobar palabras"},
                {"key": "comment_keywords", "label": "Palabras clave en comentario"},
                {"key": "template_sent_status", "label": "Comprobar plantilla si/no enviada"},
                {"key": "current_tag", "label": "Etiqueta actual"},
                {"key": "schedule", "label": "Comprobar horario"},
            ],
            "action_types": [
                {"key": "send_template", "label": "Enviar plantilla de mensaje"},
                {"key": "reply_comment", "label": "Responder comentario"},
                {"key": "change_tag", "label": "Cambiar etiqueta"},
                {"key": "configure_conversation", "label": "Configurar conversacion"},
                {"key": "change_contact_status", "label": "Cambiar estado contacto"},
                {"key": "notify_admins", "label": "Enviar notificacion administradores"},
                {"key": "extract_conversation_info", "label": "Extraer informacion conversacion"},
                {"key": "schedule_message", "label": "Programar mensaje"},
            ],
            "assistant_message_types": [
                {"key": "auto", "label": "Auto"},
                {"key": "text", "label": "Texto"},
                {"key": "audio", "label": "Audio"},
            ],
        }


@router.get("/summary")
def get_campaign_summary(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        row = conn.execute(
            text(
                """
                SELECT
                    (SELECT COUNT(*) FROM saas_message_templates WHERE tenant_id = CAST(:tenant_id AS uuid))::int AS templates,
                    (SELECT COUNT(*) FROM saas_segments WHERE tenant_id = CAST(:tenant_id AS uuid))::int AS segments,
                    (SELECT COUNT(*) FROM saas_campaigns WHERE tenant_id = CAST(:tenant_id AS uuid))::int AS campaigns,
                    (SELECT COUNT(*) FROM saas_crm_triggers WHERE tenant_id = CAST(:tenant_id AS uuid) AND is_active = TRUE)::int AS active_triggers,
                    (SELECT COUNT(*) FROM saas_remarketing_flows WHERE tenant_id = CAST(:tenant_id AS uuid) AND status = 'active')::int AS active_flows
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().first()
    return {"tenant_id": ctx.tenant_id, "summary": dict(row or {})}


@router.get("/templates")
def list_templates(
    channel: str = Query("", max_length=40),
    ctx: AuthContext = Depends(get_current_user),
):
    params = {"tenant_id": ctx.tenant_id, "channel": _clean_channel(channel)}
    where = ["tenant_id = CAST(:tenant_id AS uuid)"]
    if channel:
        where.append("channel = :channel")
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        rows = _list_rows(
            conn,
            f"""
            SELECT id::text, name, channel, category, status, body, variables_json, blocks_json, params_json,
                   render_mode, template_scope, source, created_at::text, updated_at::text
            FROM saas_message_templates
            WHERE {" AND ".join(where)}
            ORDER BY updated_at DESC
            """,
            params,
        )
    return {"tenant_id": ctx.tenant_id, "templates": rows}


@router.post("/templates")
def create_template(payload: TemplateIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    body = _clean_text(payload.body, 8000)
    if not body:
        raise HTTPException(status_code=400, detail="template_body_required")
    try:
        with db_session() as conn:
            set_tenant_context(conn, ctx.tenant_id)
            row = conn.execute(
                text(
                    """
                    INSERT INTO saas_message_templates (
                        tenant_id, name, channel, category, status, body, variables_json, blocks_json, params_json,
                        render_mode, template_scope, source, created_by_user_id
                    )
                    VALUES (
                        CAST(:tenant_id AS uuid), :name, :channel, :category, :status, :body,
                        CAST(:variables_json AS jsonb), CAST(:blocks_json AS jsonb), CAST(:params_json AS jsonb),
                        :render_mode, :template_scope, 'internal', CAST(:user_id AS uuid)
                    )
                    RETURNING id::text, name, channel, category, status, body, variables_json, blocks_json, params_json,
                              render_mode, template_scope, source, created_at::text, updated_at::text
                    """
                ),
                {
                    "tenant_id": ctx.tenant_id,
                    "user_id": ctx.user_id,
                    "name": _clean_text(payload.name, 140),
                    "channel": _clean_channel(payload.channel),
                    "category": _clean_text(payload.category, 80).lower() or "general",
                    "status": _clean_text(payload.status, 40).lower() or "draft",
                    "body": body,
                    "variables_json": _json_dump(payload.variables_json, []),
                    "blocks_json": _json_dump(payload.blocks_json, []),
                    "params_json": _json_dump(payload.params_json, {}),
                    "render_mode": _clean_text(payload.render_mode, 40).lower() or "chat",
                    "template_scope": _clean_text(payload.template_scope, 40).lower() or "crm",
                },
            ).mappings().first()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="template_already_exists")
    return {"ok": True, "tenant_id": ctx.tenant_id, "template": _row_dict(row)}


@router.patch("/templates/{template_id}")
def update_template(template_id: str, payload: TemplatePatchIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="template_patch_required")
    assignments: list[str] = []
    params: dict[str, Any] = {"tenant_id": ctx.tenant_id, "template_id": template_id}
    for key, value in data.items():
        if key in ("variables_json", "blocks_json"):
            params[key] = _json_dump(value, [])
            assignments.append(f"{key} = CAST(:{key} AS jsonb)")
        elif key == "params_json":
            params[key] = _json_dump(value, {})
            assignments.append("params_json = CAST(:params_json AS jsonb)")
        elif key == "channel":
            params[key] = _clean_channel(value)
            assignments.append("channel = :channel")
        else:
            params[key] = _clean_text(value, 8000 if key == "body" else 160)
            assignments.append(f"{key} = :{key}")
    assignments.append("updated_at = NOW()")
    try:
        with db_session() as conn:
            set_tenant_context(conn, ctx.tenant_id)
            row = conn.execute(
                text(
                    f"""
                    UPDATE saas_message_templates
                    SET {", ".join(assignments)}
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND id = CAST(:template_id AS uuid)
                    RETURNING id::text, name, channel, category, status, body, variables_json, blocks_json, params_json,
                              render_mode, template_scope, source, created_at::text, updated_at::text
                    """
                ),
                params,
            ).mappings().first()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="template_already_exists")
    if not row:
        raise HTTPException(status_code=404, detail="template_not_found")
    return {"ok": True, "tenant_id": ctx.tenant_id, "template": _row_dict(row)}


@router.post("/segments/preview")
def preview_segment(payload: SegmentPreviewIn, ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        count = _count_segment(conn, ctx.tenant_id, payload.filters_json)
    return {"tenant_id": ctx.tenant_id, "audience_count": count}


@router.get("/segments")
def list_segments(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        rows = _list_rows(
            conn,
            """
            SELECT id::text, name, description, filters_json, audience_count, created_at::text, updated_at::text
            FROM saas_segments
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY updated_at DESC
            """,
            {"tenant_id": ctx.tenant_id},
        )
    return {"tenant_id": ctx.tenant_id, "segments": rows}


@router.post("/segments")
def create_segment(payload: SegmentIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    try:
        with db_session() as conn:
            set_tenant_context(conn, ctx.tenant_id)
            audience_count = _count_segment(conn, ctx.tenant_id, payload.filters_json)
            row = conn.execute(
                text(
                    """
                    INSERT INTO saas_segments (tenant_id, name, description, filters_json, audience_count, created_by_user_id)
                    VALUES (CAST(:tenant_id AS uuid), :name, :description, CAST(:filters_json AS jsonb), :audience_count, CAST(:user_id AS uuid))
                    RETURNING id::text, name, description, filters_json, audience_count, created_at::text, updated_at::text
                    """
                ),
                {
                    "tenant_id": ctx.tenant_id,
                    "user_id": ctx.user_id,
                    "name": _clean_text(payload.name, 140),
                    "description": _clean_text(payload.description, 800),
                    "filters_json": _json_dump(payload.filters_json, {}),
                    "audience_count": audience_count,
                },
            ).mappings().first()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="segment_already_exists")
    return {"ok": True, "tenant_id": ctx.tenant_id, "segment": _row_dict(row)}


@router.patch("/segments/{segment_id}")
def update_segment(segment_id: str, payload: SegmentPatchIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="segment_patch_required")
    assignments: list[str] = []
    params: dict[str, Any] = {"tenant_id": ctx.tenant_id, "segment_id": segment_id}
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        if "filters_json" in data:
            params["filters_json"] = _json_dump(data["filters_json"], {})
            params["audience_count"] = _count_segment(conn, ctx.tenant_id, data["filters_json"] or {})
            assignments.append("filters_json = CAST(:filters_json AS jsonb)")
            assignments.append("audience_count = :audience_count")
        for key in ("name", "description"):
            if key in data:
                params[key] = _clean_text(data[key], 800 if key == "description" else 140)
                assignments.append(f"{key} = :{key}")
        assignments.append("updated_at = NOW()")
        try:
            row = conn.execute(
                text(
                    f"""
                    UPDATE saas_segments
                    SET {", ".join(assignments)}
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND id = CAST(:segment_id AS uuid)
                    RETURNING id::text, name, description, filters_json, audience_count, created_at::text, updated_at::text
                    """
                ),
                params,
            ).mappings().first()
        except IntegrityError:
            raise HTTPException(status_code=409, detail="segment_already_exists")
    if not row:
        raise HTTPException(status_code=404, detail="segment_not_found")
    return {"ok": True, "tenant_id": ctx.tenant_id, "segment": _row_dict(row)}


@router.get("/items")
def list_campaigns(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        rows = _list_rows(
            conn,
            """
            SELECT
                c.id::text,
                c.name,
                c.channel,
                c.objective,
                c.template_id::text,
                c.segment_id::text,
                c.status,
                c.scheduled_at::text,
                c.audience_count,
                c.sent_count,
                c.failed_count,
                c.metrics_json,
                c.created_at::text,
                c.updated_at::text,
                t.name AS template_name,
                s.name AS segment_name
            FROM saas_campaigns c
            LEFT JOIN saas_message_templates t ON t.id = c.template_id
            LEFT JOIN saas_segments s ON s.id = c.segment_id
            WHERE c.tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY c.updated_at DESC
            """,
            {"tenant_id": ctx.tenant_id},
        )
    return {"tenant_id": ctx.tenant_id, "campaigns": rows}


@router.post("/items")
def create_campaign(payload: CampaignIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        ensure_campaign_quota(conn, ctx.tenant_id)
        segment_id = _clean_id(payload.segment_id)
        filters = _fetch_segment_filters(conn, ctx.tenant_id, segment_id) if segment_id else {}
        audience_count = _count_segment(conn, ctx.tenant_id, filters) if segment_id else 0
        row = conn.execute(
            text(
                """
                INSERT INTO saas_campaigns (
                    tenant_id, name, channel, objective, template_id, segment_id, status, scheduled_at, audience_count, created_by_user_id
                )
                VALUES (
                    CAST(:tenant_id AS uuid), :name, :channel, :objective,
                    CAST(NULLIF(:template_id, '') AS uuid), CAST(NULLIF(:segment_id, '') AS uuid),
                    :status, CAST(NULLIF(:scheduled_at, '') AS timestamp), :audience_count, CAST(:user_id AS uuid)
                )
                RETURNING id::text, name, channel, objective, template_id::text, segment_id::text, status, scheduled_at::text, audience_count, sent_count, failed_count, metrics_json, created_at::text, updated_at::text
                """
            ),
            {
                "tenant_id": ctx.tenant_id,
                "user_id": ctx.user_id,
                "name": _clean_text(payload.name, 160),
                "channel": _clean_channel(payload.channel),
                "objective": _clean_text(payload.objective, 1000),
                "template_id": _clean_id(payload.template_id),
                "segment_id": segment_id,
                "status": _clean_text(payload.status, 40).lower() or "draft",
                "scheduled_at": _clean_text(payload.scheduled_at, 60),
                "audience_count": audience_count,
            },
        ).mappings().first()
    return {"ok": True, "tenant_id": ctx.tenant_id, "campaign": _row_dict(row)}


@router.patch("/items/{campaign_id}")
def update_campaign(campaign_id: str, payload: CampaignPatchIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="campaign_patch_required")
    assignments: list[str] = []
    params: dict[str, Any] = {"tenant_id": ctx.tenant_id, "campaign_id": campaign_id}
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        ensure_tenant_operational(conn, ctx.tenant_id)
        if "segment_id" in data:
            segment_id = _clean_id(data["segment_id"])
            filters = _fetch_segment_filters(conn, ctx.tenant_id, segment_id) if segment_id else {}
            params["segment_id"] = segment_id
            params["audience_count"] = _count_segment(conn, ctx.tenant_id, filters) if segment_id else 0
            assignments.append("segment_id = CAST(NULLIF(:segment_id, '') AS uuid)")
            assignments.append("audience_count = :audience_count")
        for key in ("name", "channel", "objective", "status", "scheduled_at", "template_id"):
            if key not in data:
                continue
            if key == "channel":
                params[key] = _clean_channel(data[key])
                assignments.append("channel = :channel")
            elif key in ("template_id",):
                params[key] = _clean_id(data[key])
                assignments.append("template_id = CAST(NULLIF(:template_id, '') AS uuid)")
            elif key == "scheduled_at":
                params[key] = _clean_text(data[key], 60)
                assignments.append("scheduled_at = CAST(NULLIF(:scheduled_at, '') AS timestamp)")
            else:
                params[key] = _clean_text(data[key], 1000 if key == "objective" else 160)
                assignments.append(f"{key} = :{key}")
        assignments.append("updated_at = NOW()")
        row = conn.execute(
            text(
                f"""
                UPDATE saas_campaigns
                SET {", ".join(assignments)}
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:campaign_id AS uuid)
                RETURNING id::text, name, channel, objective, template_id::text, segment_id::text, status, scheduled_at::text, audience_count, sent_count, failed_count, metrics_json, created_at::text, updated_at::text
                """
            ),
            params,
        ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="campaign_not_found")
    return {"ok": True, "tenant_id": ctx.tenant_id, "campaign": _row_dict(row)}


@router.get("/triggers")
def list_triggers(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_triggers(conn, ctx.tenant_id)
        rows = _list_rows(
            conn,
            """
            SELECT id::text, name, channel, event_type, trigger_type, flow_event, conditions_json, actions_json,
                   priority, cooldown_minutes, is_active, assistant_enabled, assistant_message_type,
                   block_ai, stop_on_match, only_when_no_takeover, last_run_at::text,
                   (
                       SELECT COUNT(*)::int
                       FROM saas_trigger_executions e
                       WHERE e.tenant_id = saas_crm_triggers.tenant_id
                         AND e.trigger_id = saas_crm_triggers.id
                   ) AS executions_count,
                   (
                       SELECT MAX(e.executed_at)::text
                       FROM saas_trigger_executions e
                       WHERE e.tenant_id = saas_crm_triggers.tenant_id
                         AND e.trigger_id = saas_crm_triggers.id
                   ) AS last_execution_at,
                   (
                       SELECT COUNT(*)::int
                       FROM saas_trigger_scheduled_messages sm
                       WHERE sm.tenant_id = saas_crm_triggers.tenant_id
                         AND sm.trigger_id = saas_crm_triggers.id
                         AND sm.status IN ('pending', 'processing')
                   ) AS scheduled_pending_count,
                   created_at::text, updated_at::text
            FROM saas_crm_triggers
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY is_active DESC, priority ASC, updated_at DESC
            """,
            {"tenant_id": ctx.tenant_id},
        )
    return {"tenant_id": ctx.tenant_id, "triggers": rows}


@router.post("/triggers")
def create_trigger(payload: TriggerIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    try:
        with db_session() as conn:
            set_tenant_context(conn, ctx.tenant_id)
            _ensure_triggers(conn, ctx.tenant_id)
            row = conn.execute(
                text(
                    """
                    INSERT INTO saas_crm_triggers (
                        tenant_id, name, channel, event_type, trigger_type, flow_event, conditions_json, actions_json,
                        priority, cooldown_minutes, is_active, assistant_enabled, assistant_message_type,
                        block_ai, stop_on_match, only_when_no_takeover, created_by_user_id
                    )
                    VALUES (
                        CAST(:tenant_id AS uuid), :name, :channel, :event_type, :trigger_type, :flow_event,
                        CAST(:conditions_json AS jsonb), CAST(:actions_json AS jsonb), :priority, :cooldown_minutes,
                        :is_active, :assistant_enabled, :assistant_message_type, :block_ai, :stop_on_match,
                        :only_when_no_takeover, CAST(:user_id AS uuid)
                    )
                    RETURNING id::text, name, channel, event_type, trigger_type, flow_event, conditions_json, actions_json,
                              priority, cooldown_minutes, is_active, assistant_enabled, assistant_message_type,
                              block_ai, stop_on_match, only_when_no_takeover, last_run_at::text, created_at::text, updated_at::text
                    """
                ),
                {
                    "tenant_id": ctx.tenant_id,
                    "user_id": ctx.user_id,
                    "name": _clean_text(payload.name, 160),
                    "channel": _clean_channel(payload.channel),
                    "event_type": _clean_text(payload.event_type, 80).lower() or "message_in",
                    "trigger_type": _clean_text(payload.trigger_type, 80).lower() or "message_flow",
                    "flow_event": _clean_text(payload.flow_event, 40).lower() or "received",
                    "conditions_json": _json_dump(payload.conditions_json, {"conditions": []}),
                    "actions_json": _json_dump(payload.actions_json, {"actions": []}),
                    "priority": payload.priority,
                    "cooldown_minutes": payload.cooldown_minutes,
                    "is_active": payload.is_active,
                    "assistant_enabled": bool(payload.assistant_enabled),
                    "assistant_message_type": _clean_text(payload.assistant_message_type, 40).lower() or "auto",
                    "block_ai": bool(payload.block_ai),
                    "stop_on_match": bool(payload.stop_on_match),
                    "only_when_no_takeover": bool(payload.only_when_no_takeover),
                },
            ).mappings().first()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="trigger_already_exists")
    return {"ok": True, "tenant_id": ctx.tenant_id, "trigger": _row_dict(row)}


@router.patch("/triggers/{trigger_id}")
def update_trigger(trigger_id: str, payload: TriggerPatchIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="trigger_patch_required")
    assignments: list[str] = []
    params: dict[str, Any] = {"tenant_id": ctx.tenant_id, "trigger_id": trigger_id}
    for key, value in data.items():
        if key in ("conditions_json", "actions_json"):
            params[key] = _json_dump(value, {"conditions": []} if key == "conditions_json" else {"actions": []})
            assignments.append(f"{key} = CAST(:{key} AS jsonb)")
        elif key in ("is_active", "assistant_enabled", "block_ai", "stop_on_match", "only_when_no_takeover"):
            params[key] = bool(value)
            assignments.append(f"{key} = :{key}")
        elif key in ("priority", "cooldown_minutes"):
            params[key] = int(value)
            assignments.append(f"{key} = :{key}")
        elif key == "channel":
            params[key] = _clean_channel(value)
            assignments.append("channel = :channel")
        else:
            params[key] = _clean_text(value, 160)
            assignments.append(f"{key} = :{key}")
    assignments.append("updated_at = NOW()")
    try:
        with db_session() as conn:
            set_tenant_context(conn, ctx.tenant_id)
            _ensure_triggers(conn, ctx.tenant_id)
            row = conn.execute(
                text(
                    f"""
                    UPDATE saas_crm_triggers
                    SET {", ".join(assignments)}
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND id = CAST(:trigger_id AS uuid)
                    RETURNING id::text, name, channel, event_type, trigger_type, flow_event, conditions_json, actions_json,
                              priority, cooldown_minutes, is_active, assistant_enabled, assistant_message_type,
                              block_ai, stop_on_match, only_when_no_takeover, last_run_at::text, created_at::text, updated_at::text
                    """
                ),
                params,
            ).mappings().first()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="trigger_already_exists")
    if not row:
        raise HTTPException(status_code=404, detail="trigger_not_found")
    return {"ok": True, "tenant_id": ctx.tenant_id, "trigger": _row_dict(row)}


@router.delete("/triggers/{trigger_id}")
def delete_trigger(trigger_id: str, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_triggers(conn, ctx.tenant_id)
        row = conn.execute(
            text(
                """
                DELETE FROM saas_crm_triggers
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:trigger_id AS uuid)
                RETURNING id::text, name
                """
            ),
            {"tenant_id": ctx.tenant_id, "trigger_id": trigger_id},
        ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="trigger_not_found")
    return {"ok": True, "tenant_id": ctx.tenant_id, "deleted": _row_dict(row)}


@router.post("/triggers/{trigger_id}/copy")
def copy_trigger(
    trigger_id: str,
    payload: TriggerCopyIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    target_channel = _clean_channel(payload.channel)
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_triggers(conn, ctx.tenant_id)
        source = conn.execute(
            text(
                """
                SELECT name, event_type, trigger_type, flow_event, conditions_json, actions_json,
                       priority, cooldown_minutes, is_active, assistant_enabled, assistant_message_type,
                       block_ai, stop_on_match, only_when_no_takeover
                FROM saas_crm_triggers
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:trigger_id AS uuid)
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id, "trigger_id": trigger_id},
        ).mappings().first()
        if not source:
            raise HTTPException(status_code=404, detail="trigger_not_found")

        base_name = _clean_text(payload.name, 160) or f"{source['name']} copia"
        candidate = base_name[:160]
        suffix = 2
        while conn.execute(
            text(
                """
                SELECT 1
                FROM saas_crm_triggers
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND channel = :channel
                  AND lower(name) = lower(:name)
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id, "channel": target_channel, "name": candidate},
        ).first():
            tail = f" {suffix}"
            candidate = f"{base_name[:160 - len(tail)]}{tail}"
            suffix += 1

        row = conn.execute(
            text(
                """
                INSERT INTO saas_crm_triggers (
                    tenant_id, name, channel, event_type, trigger_type, flow_event,
                    conditions_json, actions_json, priority, cooldown_minutes, is_active,
                    assistant_enabled, assistant_message_type, block_ai, stop_on_match,
                    only_when_no_takeover, created_by_user_id
                )
                VALUES (
                    CAST(:tenant_id AS uuid), :name, :channel, :event_type, :trigger_type, :flow_event,
                    CAST(:conditions_json AS jsonb), CAST(:actions_json AS jsonb), :priority, :cooldown_minutes,
                    :is_active, :assistant_enabled, :assistant_message_type, :block_ai, :stop_on_match,
                    :only_when_no_takeover, CAST(:user_id AS uuid)
                )
                RETURNING id::text, name, channel, event_type, trigger_type, flow_event, conditions_json, actions_json,
                          priority, cooldown_minutes, is_active, assistant_enabled, assistant_message_type,
                          block_ai, stop_on_match, only_when_no_takeover, last_run_at::text, created_at::text, updated_at::text
                """
            ),
            {
                "tenant_id": ctx.tenant_id,
                "user_id": ctx.user_id,
                "name": candidate,
                "channel": target_channel,
                "event_type": source["event_type"],
                "trigger_type": source["trigger_type"],
                "flow_event": source["flow_event"],
                "conditions_json": _json_dump(source["conditions_json"], {"conditions": []}),
                "actions_json": _json_dump(source["actions_json"], {"actions": []}),
                "priority": int(source["priority"] or 100),
                "cooldown_minutes": int(source["cooldown_minutes"] or 0),
                "is_active": bool(source["is_active"]),
                "assistant_enabled": bool(source["assistant_enabled"]),
                "assistant_message_type": source["assistant_message_type"] or "auto",
                "block_ai": bool(source["block_ai"]),
                "stop_on_match": bool(source["stop_on_match"]),
                "only_when_no_takeover": bool(source["only_when_no_takeover"]),
            },
        ).mappings().first()
    return {"ok": True, "tenant_id": ctx.tenant_id, "source_trigger_id": trigger_id, "trigger": _row_dict(row)}


@router.get("/flows")
def list_flows(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_remarketing(conn, ctx.tenant_id)
        rows = _list_rows(
            conn,
            """
            SELECT id::text, name, description, channel, status, entry_rules_json, exit_rules_json, steps_json, created_at::text, updated_at::text
            FROM saas_remarketing_flows
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY updated_at DESC
            """,
            {"tenant_id": ctx.tenant_id},
        )
    return {"tenant_id": ctx.tenant_id, "flows": rows}


@router.post("/flows/process")
def process_flows_now(
    limit: int = Query(100, ge=1, le=500),
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_remarketing(conn, ctx.tenant_id)
    result = process_due_remarketing_flows(limit=limit, tenant_id=ctx.tenant_id)
    return {"ok": True, "tenant_id": ctx.tenant_id, "result": result}


@router.post("/flows")
def create_flow(payload: FlowIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    try:
        with db_session() as conn:
            set_tenant_context(conn, ctx.tenant_id)
            _ensure_remarketing(conn, ctx.tenant_id)
            row = conn.execute(
                text(
                    """
                    INSERT INTO saas_remarketing_flows (
                        tenant_id, name, description, channel, status, entry_rules_json, exit_rules_json, steps_json, created_by_user_id
                    )
                    VALUES (
                        CAST(:tenant_id AS uuid), :name, :description, :channel, :status,
                        CAST(:entry_rules_json AS jsonb), CAST(:exit_rules_json AS jsonb), CAST(:steps_json AS jsonb), CAST(:user_id AS uuid)
                    )
                    RETURNING id::text, name, description, channel, status, entry_rules_json, exit_rules_json, steps_json, created_at::text, updated_at::text
                    """
                ),
                {
                    "tenant_id": ctx.tenant_id,
                    "user_id": ctx.user_id,
                    "name": _clean_text(payload.name, 160),
                    "description": _clean_text(payload.description, 1000),
                    "channel": _clean_channel(payload.channel),
                    "status": _clean_text(payload.status, 40).lower() or "draft",
                    "entry_rules_json": _json_dump(payload.entry_rules_json, {}),
                    "exit_rules_json": _json_dump(payload.exit_rules_json, {}),
                    "steps_json": _json_dump(payload.steps_json, []),
                },
            ).mappings().first()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="flow_already_exists")
    return {"ok": True, "tenant_id": ctx.tenant_id, "flow": _row_dict(row)}


@router.patch("/flows/{flow_id}")
def update_flow(flow_id: str, payload: FlowPatchIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="flow_patch_required")
    assignments: list[str] = []
    params: dict[str, Any] = {"tenant_id": ctx.tenant_id, "flow_id": flow_id}
    for key, value in data.items():
        if key in ("entry_rules_json", "exit_rules_json"):
            params[key] = _json_dump(value, {})
            assignments.append(f"{key} = CAST(:{key} AS jsonb)")
        elif key == "steps_json":
            params[key] = _json_dump(value, [])
            assignments.append("steps_json = CAST(:steps_json AS jsonb)")
        elif key == "channel":
            params[key] = _clean_channel(value)
            assignments.append("channel = :channel")
        else:
            params[key] = _clean_text(value, 1000 if key == "description" else 160)
            assignments.append(f"{key} = :{key}")
    assignments.append("updated_at = NOW()")
    try:
        with db_session() as conn:
            set_tenant_context(conn, ctx.tenant_id)
            _ensure_remarketing(conn, ctx.tenant_id)
            row = conn.execute(
                text(
                    f"""
                    UPDATE saas_remarketing_flows
                    SET {", ".join(assignments)}
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND id = CAST(:flow_id AS uuid)
                    RETURNING id::text, name, description, channel, status, entry_rules_json, exit_rules_json, steps_json, created_at::text, updated_at::text
                    """
                ),
                params,
            ).mappings().first()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="flow_already_exists")
    if not row:
        raise HTTPException(status_code=404, detail="flow_not_found")
    return {"ok": True, "tenant_id": ctx.tenant_id, "flow": _row_dict(row)}
