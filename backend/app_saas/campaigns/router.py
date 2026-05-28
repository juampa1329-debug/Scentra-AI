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
    PreflightIn,
    QuietHoursIn,
    SegmentIn,
    SegmentPatchIn,
    SegmentPreviewIn,
    TemplateIn,
    TemplatePatchIn,
    TriggerCopyIn,
    TriggerIn,
    TriggerPatchIn,
    TriggerSimulateIn,
    TriggerVersionRestoreIn,
)
from app_saas.db import db_session, set_tenant_context
from app_saas.shared.security import AuthContext, get_current_user, require_role
from app_saas.workers.remarketing import process_due_remarketing_flows
from app_saas.workers.triggers import simulate_trigger_draft

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


def _json_value(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if value in (None, ""):
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _preflight_score(checks: list[dict[str, Any]]) -> tuple[int, bool, str]:
    failed_high = sum(1 for item in checks if not item.get("ok") and item.get("severity") == "high")
    failed_medium = sum(1 for item in checks if not item.get("ok") and item.get("severity") == "medium")
    failed_low = sum(1 for item in checks if not item.get("ok") and item.get("severity") == "low")
    score = max(0, 100 - failed_high * 28 - failed_medium * 14 - failed_low * 6)
    ready = failed_high == 0 and score >= 70
    status = "ready" if ready else "blocked" if failed_high else "warning"
    return score, ready, status


def _template_status(conn, tenant_id: str, template_id: str) -> dict[str, Any] | None:
    clean_id = _clean_id(template_id)
    if not clean_id:
        return None
    row = conn.execute(
        text(
            """
            SELECT id::text, name, channel, status, template_scope
            FROM saas_message_templates
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:template_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "template_id": clean_id},
    ).mappings().first()
    return dict(row) if row else None


def _ab_variant_checks(conn, tenant_id: str, config: Any) -> list[dict[str, Any]]:
    root = _json_value(config, {})
    if not isinstance(root, dict) or not root.get("enabled"):
        return [{"code": "ab_test", "label": "A/B testing desactivado o sin variantes", "ok": True, "severity": "low"}]
    variants = [row for row in root.get("variants", []) if isinstance(row, dict)]
    checks = [{
        "code": "ab_variants_present",
        "label": "A/B testing tiene variantes",
        "ok": bool(variants),
        "severity": "medium",
        "details": {"variants": len(variants)},
    }]
    total_weight = 0
    for idx, variant in enumerate(variants):
        total_weight += int(variant.get("weight") or variant.get("traffic") or 0)
        template_id = _clean_id(variant.get("template_id"))
        if template_id:
            template = _template_status(conn, tenant_id, template_id)
            checks.append({
                "code": f"ab_variant_{idx + 1}_template",
                "label": f"Variante {variant.get('key') or idx + 1} tiene plantilla valida",
                "ok": bool(template) and str(template.get("status") or "").lower() in {"approved", "draft"},
                "severity": "high",
                "details": {"template_id": template_id, "template": template},
            })
    checks.append({
        "code": "ab_weight",
        "label": "Pesos A/B configurados",
        "ok": total_weight <= 0 or 80 <= total_weight <= 120,
        "severity": "low",
        "details": {"total_weight": total_weight},
    })
    return checks


def _quiet_hours_checks(config: Any) -> list[dict[str, Any]]:
    root = _json_value(config, {})
    if not isinstance(root, dict) or not root.get("enabled"):
        return [{"code": "quiet_hours", "label": "Quiet hours opcionales", "ok": True, "severity": "low"}]
    start = _clean_text(root.get("start_time"), 10)
    end = _clean_text(root.get("end_time"), 10)
    days = root.get("days") if isinstance(root.get("days"), list) else []
    valid = bool(start and end and days)
    return [{
        "code": "quiet_hours",
        "label": "Quiet hours configuradas",
        "ok": valid,
        "severity": "medium",
        "details": {"start_time": start, "end_time": end, "days": days, "timezone": root.get("timezone") or "America/Bogota"},
    }]


def _clean_days(value: Any) -> list[str]:
    rows = value if isinstance(value, list) else []
    days = []
    for item in rows:
        token = _clean_text(item, 12).lower()[:3]
        if token in {"mon", "tue", "wed", "thu", "fri", "sat", "sun"} and token not in days:
            days.append(token)
    return days or ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _quiet_config(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": bool(row.get("enabled")),
        "timezone": _clean_text(row.get("timezone"), 80) or "America/Bogota",
        "start_time": _clean_text(row.get("start_time"), 10) or "21:00",
        "end_time": _clean_text(row.get("end_time"), 10) or "08:00",
        "days": _clean_days(row.get("days_json") if "days_json" in row else row.get("days")),
    }


def _global_quiet_hours_checks(conn, tenant_id: str, channel: str, entity_type: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT channel, entity_type, enabled, timezone, start_time, end_time, days_json
            FROM saas_campaign_quiet_hours
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND enabled = TRUE
              AND channel IN ('all', :channel)
              AND entity_type IN ('all', :entity_type)
            ORDER BY updated_at DESC
            """
        ),
        {"tenant_id": tenant_id, "channel": _clean_channel(channel), "entity_type": _clean_text(entity_type, 40).lower() or "all"},
    ).mappings().all()
    if not rows:
        return [{"code": "global_quiet_hours", "label": "Quiet hours globales opcionales", "ok": True, "severity": "low"}]
    checks = []
    for row in rows:
        cfg = _quiet_config(dict(row))
        checks.append({
            "code": "global_quiet_hours",
            "label": f"Quiet hours globales {row['entity_type']}/{row['channel']}",
            "ok": bool(cfg["start_time"] and cfg["end_time"] and cfg["days"]),
            "severity": "medium",
            "details": {"channel": row["channel"], "entity_type": row["entity_type"], **cfg},
        })
    return checks


def _campaign_checks(conn, tenant_id: str, values: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    try:
        ensure_tenant_operational(conn, tenant_id)
        checks.append({"code": "tenant_operational", "label": "Empresa operativa", "ok": True, "severity": "high"})
    except HTTPException as exc:
        checks.append({"code": "tenant_operational", "label": "Empresa operativa", "ok": False, "severity": "high", "details": exc.detail})
    template = _template_status(conn, tenant_id, values.get("template_id") or "")
    checks.append({
        "code": "template",
        "label": "Plantilla CRM seleccionada",
        "ok": bool(template) and str(template.get("status") or "").lower() in {"approved", "draft"},
        "severity": "high",
        "details": {"template": template},
    })
    audience_count = int(values.get("audience_count") or 0)
    segment_id = _clean_id(values.get("segment_id"))
    if segment_id and audience_count <= 0:
        audience_count = _count_segment(conn, tenant_id, _fetch_segment_filters(conn, tenant_id, segment_id))
    checks.append({
        "code": "audience",
        "label": "Audiencia calculada",
        "ok": audience_count > 0,
        "severity": "high",
        "details": {"audience_count": audience_count, "segment_id": segment_id},
    })
    status = _clean_text(values.get("status"), 40).lower()
    scheduled_at = _clean_text(values.get("scheduled_at"), 80)
    checks.append({
        "code": "schedule",
        "label": "Programacion valida",
        "ok": status not in {"scheduled", "running"} or bool(scheduled_at) or status == "running",
        "severity": "medium",
        "details": {"status": status, "scheduled_at": scheduled_at},
    })
    checks.extend(_global_quiet_hours_checks(conn, tenant_id, values.get("channel") or "whatsapp", "campaign"))
    checks.extend(_quiet_hours_checks(values.get("quiet_hours_json")))
    checks.extend(_ab_variant_checks(conn, tenant_id, values.get("ab_test_json")))
    return checks


def _campaign_preflight(conn, tenant_id: str, values: dict[str, Any]) -> dict[str, Any]:
    checks = _campaign_checks(conn, tenant_id, values)
    score, ready, status = _preflight_score(checks)
    return {"status": status, "ready": ready, "score": score, "checks": checks}


def _trigger_checks(conn, tenant_id: str, values: dict[str, Any]) -> list[dict[str, Any]]:
    conditions = _json_value(values.get("conditions_json"), {})
    actions = _json_value(values.get("actions_json"), {})
    action_rows = actions.get("actions") if isinstance(actions, dict) else []
    condition_rows = conditions.get("conditions") if isinstance(conditions, dict) else []
    checks: list[dict[str, Any]] = [
        {"code": "conditions", "label": "Tiene condiciones", "ok": bool(condition_rows), "severity": "medium", "details": {"count": len(condition_rows or [])}},
        {"code": "actions", "label": "Tiene acciones", "ok": bool(action_rows), "severity": "high", "details": {"count": len(action_rows or [])}},
        {"code": "ai_priority", "label": "Bloquea IA cuando matchea", "ok": bool(values.get("block_ai")), "severity": "low"},
    ]
    for idx, action in enumerate(action_rows or []):
        if not isinstance(action, dict):
            continue
        if _clean_text(action.get("type"), 80).lower() in {"send_template", "schedule_message"}:
            template = _template_status(conn, tenant_id, action.get("template_id") or "")
            checks.append({
                "code": f"action_{idx + 1}_template",
                "label": f"Accion {idx + 1} tiene plantilla valida",
                "ok": bool(template) and str(template.get("status") or "").lower() in {"approved", "draft"},
                "severity": "high",
                "details": {"template": template},
            })
    checks.extend(_global_quiet_hours_checks(conn, tenant_id, values.get("channel") or "whatsapp", "trigger"))
    checks.extend(_quiet_hours_checks(values.get("quiet_hours_json")))
    checks.extend(_ab_variant_checks(conn, tenant_id, values.get("ab_test_json")))
    return checks


def _trigger_preflight(conn, tenant_id: str, values: dict[str, Any]) -> dict[str, Any]:
    checks = _trigger_checks(conn, tenant_id, values)
    score, ready, status = _preflight_score(checks)
    return {"status": status, "ready": ready, "score": score, "checks": checks}


def _flow_checks(conn, tenant_id: str, values: dict[str, Any]) -> list[dict[str, Any]]:
    steps = _json_value(values.get("steps_json"), [])
    step_rows = steps if isinstance(steps, list) else []
    checks: list[dict[str, Any]] = []
    try:
        ensure_tenant_operational(conn, tenant_id)
        checks.append({"code": "tenant_operational", "label": "Empresa operativa", "ok": True, "severity": "high"})
    except HTTPException as exc:
        checks.append({"code": "tenant_operational", "label": "Empresa operativa", "ok": False, "severity": "high", "details": exc.detail})
    checks.append({"code": "steps", "label": "Flow tiene pasos", "ok": bool(step_rows), "severity": "high", "details": {"count": len(step_rows)}})
    for idx, step in enumerate(step_rows):
        if not isinstance(step, dict):
            continue
        template = _template_status(conn, tenant_id, step.get("template_id") or "")
        checks.append({
            "code": f"step_{idx + 1}_template",
            "label": f"Paso {idx + 1} tiene plantilla valida",
            "ok": bool(template) and str(template.get("status") or "").lower() in {"approved", "draft"},
            "severity": "high",
            "details": {"template": template},
        })
    checks.extend(_global_quiet_hours_checks(conn, tenant_id, values.get("channel") or "whatsapp", "flow"))
    checks.extend(_quiet_hours_checks(values.get("quiet_hours_json")))
    checks.extend(_ab_variant_checks(conn, tenant_id, values.get("ab_test_json")))
    return checks


def _flow_preflight(conn, tenant_id: str, values: dict[str, Any]) -> dict[str, Any]:
    checks = _flow_checks(conn, tenant_id, values)
    score, ready, status = _preflight_score(checks)
    return {"status": status, "ready": ready, "score": score, "checks": checks}


def _trigger_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "channel": row.get("channel"),
        "event_type": row.get("event_type"),
        "trigger_type": row.get("trigger_type"),
        "flow_event": row.get("flow_event"),
        "conditions_json": _json_value(row.get("conditions_json"), {}),
        "actions_json": _json_value(row.get("actions_json"), {}),
        "priority": row.get("priority"),
        "cooldown_minutes": row.get("cooldown_minutes"),
        "is_active": row.get("is_active"),
        "assistant_enabled": row.get("assistant_enabled"),
        "assistant_message_type": row.get("assistant_message_type"),
        "block_ai": row.get("block_ai"),
        "stop_on_match": row.get("stop_on_match"),
        "only_when_no_takeover": row.get("only_when_no_takeover"),
        "quiet_hours_json": _json_value(row.get("quiet_hours_json"), {}),
        "ab_test_json": _json_value(row.get("ab_test_json"), {}),
        "version_number": row.get("version_number"),
    }


def _record_trigger_version(conn, tenant_id: str, user_id: str, row: dict[str, Any], reason: str = "") -> None:
    conn.execute(
        text(
            """
            INSERT INTO saas_crm_trigger_versions (
                tenant_id, trigger_id, version_number, snapshot_json, change_reason, created_by_user_id
            )
            VALUES (
                CAST(:tenant_id AS uuid), CAST(:trigger_id AS uuid), :version_number,
                CAST(:snapshot_json AS jsonb), :change_reason, CAST(NULLIF(:user_id, '') AS uuid)
            )
            ON CONFLICT (tenant_id, trigger_id, version_number) DO NOTHING
            """
        ),
        {
            "tenant_id": tenant_id,
            "trigger_id": row.get("id") or "",
            "version_number": int(row.get("version_number") or 1),
            "snapshot_json": _json_dump(_trigger_snapshot(row), {}),
            "change_reason": _clean_text(reason, 500),
            "user_id": user_id or "",
        },
    )


def _record_preflight_run(
    conn,
    *,
    tenant_id: str,
    user_id: str,
    entity_type: str,
    entity_id: str = "",
    result: dict[str, Any],
) -> None:
    conn.execute(
        text(
            """
            INSERT INTO saas_campaign_preflight_runs (
                tenant_id, campaign_id, entity_type, entity_id, status, score, checks_json, created_by_user_id
            )
            VALUES (
                CAST(:tenant_id AS uuid),
                CASE WHEN :entity_type = 'campaign' AND NULLIF(:entity_id, '') IS NOT NULL THEN CAST(:entity_id AS uuid) ELSE NULL END,
                :entity_type,
                CAST(NULLIF(:entity_id, '') AS uuid),
                :status,
                :score,
                CAST(:checks_json AS jsonb),
                CAST(NULLIF(:user_id, '') AS uuid)
            )
            """
        ),
        {
            "tenant_id": tenant_id,
            "user_id": user_id or "",
            "entity_type": _clean_text(entity_type, 40).lower() or "campaign",
            "entity_id": _clean_id(entity_id),
            "status": _clean_text(result.get("status"), 40) or "warning",
            "score": int(result.get("score") or 0),
            "checks_json": _json_dump(result.get("checks") or [], []),
        },
    )


def _load_trigger_row(conn, tenant_id: str, trigger_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            """
            SELECT id::text, name, channel, event_type, trigger_type, flow_event, conditions_json, actions_json,
                   priority, cooldown_minutes, is_active, assistant_enabled, assistant_message_type,
                   block_ai, stop_on_match, only_when_no_takeover, quiet_hours_json, ab_test_json,
                   preflight_json, last_preflight_at::text, version_number, revision_note,
                   last_run_at::text, created_at::text, updated_at::text
            FROM saas_crm_triggers
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:trigger_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "trigger_id": trigger_id},
    ).mappings().first()
    return dict(row) if row else None


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
        "trigger_conditions": [
            "last_message_sent",
            "sent_count",
            "check_words",
            "comment_keywords",
            "template_sent_status",
            "current_tag",
            "crm_stage",
            "payment_status",
            "customer_type",
            "intent",
            "schedule",
        ],
        "trigger_actions": ["send_template", "reply_comment", "change_tag", "configure_conversation", "change_contact_status", "notify_admins", "extract_conversation_info", "schedule_message"],
        "segment_filters": ["tag", "crm_stage", "payment_status", "city", "customer_type", "intent", "takeover", "channel"],
        "phase7": {
            "preflight": True,
            "trigger_simulator": True,
            "quiet_hours": True,
            "ab_testing": True,
            "versioning": True,
        },
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
                {"key": "crm_stage", "label": "Etapa CRM"},
                {"key": "payment_status", "label": "Estado de pago"},
                {"key": "customer_type", "label": "Tipo de cliente"},
                {"key": "intent", "label": "Intencion comercial"},
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


@router.get("/settings/quiet-hours")
def list_quiet_hours(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        rows = _list_rows(
            conn,
            """
            SELECT id::text, channel, entity_type, enabled, timezone, start_time, end_time,
                   days_json AS days, created_at::text, updated_at::text
            FROM saas_campaign_quiet_hours
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY entity_type ASC, channel ASC, updated_at DESC
            """,
            {"tenant_id": ctx.tenant_id},
        )
    return {"tenant_id": ctx.tenant_id, "quiet_hours": rows}


@router.patch("/settings/quiet-hours")
def upsert_quiet_hours(payload: QuietHoursIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    channel = _clean_channel(payload.channel) if payload.channel != "all" else "all"
    entity_type = _clean_text(payload.entity_type, 40).lower() or "all"
    if entity_type not in {"all", "campaign", "trigger", "flow", "broadcast"}:
        raise HTTPException(status_code=400, detail="invalid_quiet_hours_entity_type")
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        row = conn.execute(
            text(
                """
                INSERT INTO saas_campaign_quiet_hours (
                    tenant_id, channel, entity_type, enabled, timezone, start_time, end_time, days_json, created_by_user_id, updated_at
                )
                VALUES (
                    CAST(:tenant_id AS uuid), :channel, :entity_type, :enabled, :timezone, :start_time, :end_time,
                    CAST(:days_json AS jsonb), CAST(:user_id AS uuid), NOW()
                )
                ON CONFLICT (tenant_id, channel, entity_type)
                DO UPDATE SET
                    enabled = EXCLUDED.enabled,
                    timezone = EXCLUDED.timezone,
                    start_time = EXCLUDED.start_time,
                    end_time = EXCLUDED.end_time,
                    days_json = EXCLUDED.days_json,
                    updated_at = NOW()
                RETURNING id::text, channel, entity_type, enabled, timezone, start_time, end_time,
                          days_json AS days, created_at::text, updated_at::text
                """
            ),
            {
                "tenant_id": ctx.tenant_id,
                "user_id": ctx.user_id,
                "channel": channel,
                "entity_type": entity_type,
                "enabled": bool(payload.enabled),
                "timezone": _clean_text(payload.timezone, 80) or "America/Bogota",
                "start_time": _clean_text(payload.start_time, 10) or "21:00",
                "end_time": _clean_text(payload.end_time, 10) or "08:00",
                "days_json": _json_dump(_clean_days(payload.days), []),
            },
        ).mappings().first()
    return {"ok": True, "tenant_id": ctx.tenant_id, "quiet_hours": _row_dict(row)}


@router.get("/ab-report")
def get_ab_report(
    entity_type: str = Query("trigger", max_length=40),
    entity_id: str = Query("", max_length=80),
    ctx: AuthContext = Depends(get_current_user),
):
    clean_type = _clean_text(entity_type, 40).lower() or "trigger"
    if clean_type not in {"trigger", "flow", "campaign"}:
        raise HTTPException(status_code=400, detail="invalid_ab_entity_type")
    clean_entity_id = _clean_id(entity_id)
    filters = ["tenant_id = CAST(:tenant_id AS uuid)", "entity_type = :entity_type"]
    params = {"tenant_id": ctx.tenant_id, "entity_type": clean_type, "entity_id": clean_entity_id}
    if clean_entity_id:
        filters.append("entity_id = CAST(:entity_id AS uuid)")
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        rows = _list_rows(
            conn,
            f"""
            SELECT
                COALESCE(NULLIF(variant_key, ''), 'default') AS variant_key,
                COALESCE(template_id::text, '') AS template_id,
                COUNT(*)::int AS events,
                COUNT(*) FILTER (WHERE outcome = 'queued')::int AS queued,
                COUNT(*) FILTER (WHERE outcome = 'failed')::int AS failed,
                MAX(created_at)::text AS last_seen_at
            FROM saas_campaign_ab_events
            WHERE {" AND ".join(filters)}
            GROUP BY COALESCE(NULLIF(variant_key, ''), 'default'), COALESCE(template_id::text, '')
            ORDER BY events DESC, variant_key ASC
            """,
            params,
        )
    totals = {
        "events": sum(int(row.get("events") or 0) for row in rows),
        "queued": sum(int(row.get("queued") or 0) for row in rows),
        "failed": sum(int(row.get("failed") or 0) for row in rows),
    }
    return {"tenant_id": ctx.tenant_id, "entity_type": clean_type, "entity_id": clean_entity_id, "totals": totals, "variants": rows}


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
                c.quiet_hours_json,
                c.ab_test_json,
                c.preflight_json,
                c.last_preflight_at::text,
                c.activation_blocked_reason,
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
        values = {
            "name": _clean_text(payload.name, 160),
            "channel": _clean_channel(payload.channel),
            "objective": _clean_text(payload.objective, 1000),
            "template_id": _clean_id(payload.template_id),
            "segment_id": segment_id,
            "status": _clean_text(payload.status, 40).lower() or "draft",
            "scheduled_at": _clean_text(payload.scheduled_at, 60),
            "audience_count": audience_count,
            "quiet_hours_json": payload.quiet_hours_json or {},
            "ab_test_json": payload.ab_test_json or {},
        }
        preflight = _campaign_preflight(conn, ctx.tenant_id, values)
        if values["status"] in {"scheduled", "running"} and not preflight["ready"]:
            raise HTTPException(status_code=409, detail={"code": "campaign_preflight_failed", "preflight": preflight})
        row = conn.execute(
            text(
                """
                INSERT INTO saas_campaigns (
                    tenant_id, name, channel, objective, template_id, segment_id, status, scheduled_at,
                    audience_count, quiet_hours_json, ab_test_json, preflight_json, last_preflight_at, created_by_user_id
                )
                VALUES (
                    CAST(:tenant_id AS uuid), :name, :channel, :objective,
                    CAST(NULLIF(:template_id, '') AS uuid), CAST(NULLIF(:segment_id, '') AS uuid),
                    :status, CAST(NULLIF(:scheduled_at, '') AS timestamp), :audience_count,
                    CAST(:quiet_hours_json AS jsonb), CAST(:ab_test_json AS jsonb), CAST(:preflight_json AS jsonb),
                    NOW(), CAST(:user_id AS uuid)
                )
                RETURNING id::text, name, channel, objective, template_id::text, segment_id::text, status,
                          scheduled_at::text, audience_count, sent_count, failed_count, metrics_json,
                          quiet_hours_json, ab_test_json, preflight_json, last_preflight_at::text,
                          activation_blocked_reason, created_at::text, updated_at::text
                """
            ),
            {
                "tenant_id": ctx.tenant_id,
                "user_id": ctx.user_id,
                **values,
                "quiet_hours_json": _json_dump(values["quiet_hours_json"], {}),
                "ab_test_json": _json_dump(values["ab_test_json"], {}),
                "preflight_json": _json_dump(preflight, {}),
            },
        ).mappings().first()
        _record_preflight_run(
            conn,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            entity_type="campaign",
            entity_id=row["id"] if row else "",
            result=preflight,
        )
    return {"ok": True, "tenant_id": ctx.tenant_id, "campaign": _row_dict(row)}


@router.post("/items/preflight")
def preflight_campaign_draft(payload: PreflightIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    draft = payload.draft if isinstance(payload.draft, dict) else {}
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        segment_id = _clean_id(draft.get("segment_id"))
        audience_count = 0
        if segment_id:
            audience_count = _count_segment(conn, ctx.tenant_id, _fetch_segment_filters(conn, ctx.tenant_id, segment_id))
        values = {
            "name": _clean_text(draft.get("name"), 160),
            "channel": _clean_channel(draft.get("channel")),
            "objective": _clean_text(draft.get("objective"), 1000),
            "template_id": _clean_id(draft.get("template_id")),
            "segment_id": segment_id,
            "status": _clean_text(draft.get("status"), 40).lower() or "draft",
            "scheduled_at": _clean_text(draft.get("scheduled_at"), 60),
            "audience_count": audience_count,
            "quiet_hours_json": _json_value(draft.get("quiet_hours_json"), {}),
            "ab_test_json": _json_value(draft.get("ab_test_json"), {}),
        }
        preflight = _campaign_preflight(conn, ctx.tenant_id, values)
        _record_preflight_run(conn, tenant_id=ctx.tenant_id, user_id=ctx.user_id, entity_type="campaign_draft", result=preflight)
    return {"ok": True, "tenant_id": ctx.tenant_id, "preflight": preflight}


@router.post("/items/{campaign_id}/preflight")
def preflight_campaign(campaign_id: str, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        row = conn.execute(
            text(
                """
                SELECT id::text, name, channel, objective, template_id::text, segment_id::text, status,
                       scheduled_at::text, audience_count, quiet_hours_json, ab_test_json
                FROM saas_campaigns
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:campaign_id AS uuid)
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id, "campaign_id": campaign_id},
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="campaign_not_found")
        preflight = _campaign_preflight(conn, ctx.tenant_id, dict(row))
        conn.execute(
            text(
                """
                UPDATE saas_campaigns
                SET preflight_json = CAST(:preflight_json AS jsonb),
                    last_preflight_at = NOW(),
                    activation_blocked_reason = :activation_blocked_reason,
                    updated_at = NOW()
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:campaign_id AS uuid)
                """
            ),
            {
                "tenant_id": ctx.tenant_id,
                "campaign_id": campaign_id,
                "preflight_json": _json_dump(preflight, {}),
                "activation_blocked_reason": "" if preflight["ready"] else "campaign_preflight_failed",
            },
        )
        _record_preflight_run(conn, tenant_id=ctx.tenant_id, user_id=ctx.user_id, entity_type="campaign", entity_id=campaign_id, result=preflight)
    return {"ok": True, "tenant_id": ctx.tenant_id, "campaign_id": campaign_id, "preflight": preflight}


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
        for key in ("quiet_hours_json", "ab_test_json"):
            if key in data:
                params[key] = _json_dump(data[key], {})
                assignments.append(f"{key} = CAST(:{key} AS jsonb)")
        if any(key in data for key in ("name", "channel", "objective", "status", "scheduled_at", "template_id", "segment_id", "quiet_hours_json", "ab_test_json")):
            current = conn.execute(
                text(
                    """
                    SELECT name, channel, objective, template_id::text, segment_id::text, status,
                           scheduled_at::text, audience_count, quiet_hours_json, ab_test_json
                    FROM saas_campaigns
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND id = CAST(:campaign_id AS uuid)
                    LIMIT 1
                    """
                ),
                {"tenant_id": ctx.tenant_id, "campaign_id": campaign_id},
            ).mappings().first()
            if not current:
                raise HTTPException(status_code=404, detail="campaign_not_found")
            preflight_values = {**dict(current), **data}
            if "segment_id" in data:
                preflight_values["audience_count"] = params.get("audience_count", current["audience_count"])
            preflight = _campaign_preflight(conn, ctx.tenant_id, preflight_values)
            params["preflight_json"] = _json_dump(preflight, {})
            params["activation_blocked_reason"] = "" if preflight["ready"] else "campaign_preflight_failed"
            assignments.append("preflight_json = CAST(:preflight_json AS jsonb)")
            assignments.append("last_preflight_at = NOW()")
            assignments.append("activation_blocked_reason = :activation_blocked_reason")
            next_status = _clean_text(preflight_values.get("status"), 40).lower()
            if next_status in {"scheduled", "running"} and not preflight["ready"]:
                raise HTTPException(status_code=409, detail={"code": "campaign_preflight_failed", "preflight": preflight})
            _record_preflight_run(conn, tenant_id=ctx.tenant_id, user_id=ctx.user_id, entity_type="campaign", entity_id=campaign_id, result=preflight)
        assignments.append("updated_at = NOW()")
        row = conn.execute(
            text(
                f"""
                UPDATE saas_campaigns
                SET {", ".join(assignments)}
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:campaign_id AS uuid)
                RETURNING id::text, name, channel, objective, template_id::text, segment_id::text, status,
                          scheduled_at::text, audience_count, sent_count, failed_count, metrics_json,
                          quiet_hours_json, ab_test_json, preflight_json, last_preflight_at::text,
                          activation_blocked_reason, created_at::text, updated_at::text
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
                   block_ai, stop_on_match, only_when_no_takeover, quiet_hours_json, ab_test_json,
                   preflight_json, last_preflight_at::text, version_number, revision_note, last_run_at::text,
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


@router.post("/triggers/preflight")
def preflight_trigger_draft(payload: PreflightIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    draft = payload.draft if isinstance(payload.draft, dict) else {}
    values = {
        "name": _clean_text(draft.get("name"), 160),
        "channel": _clean_channel(draft.get("channel")),
        "event_type": _clean_text(draft.get("event_type"), 80).lower() or "message_in",
        "trigger_type": _clean_text(draft.get("trigger_type"), 80).lower() or "message_flow",
        "flow_event": _clean_text(draft.get("flow_event"), 40).lower() or "received",
        "conditions_json": _json_value(draft.get("conditions_json"), {"conditions": []}),
        "actions_json": _json_value(draft.get("actions_json"), {"actions": []}),
        "block_ai": bool(draft.get("block_ai", True)),
        "quiet_hours_json": _json_value(draft.get("quiet_hours_json"), {}),
        "ab_test_json": _json_value(draft.get("ab_test_json"), {}),
    }
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_triggers(conn, ctx.tenant_id)
        preflight = _trigger_preflight(conn, ctx.tenant_id, values)
        _record_preflight_run(conn, tenant_id=ctx.tenant_id, user_id=ctx.user_id, entity_type="trigger_draft", result=preflight)
    return {"ok": True, "tenant_id": ctx.tenant_id, "preflight": preflight}


@router.post("/triggers/simulate")
def simulate_trigger(payload: TriggerSimulateIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_triggers(conn, ctx.tenant_id)
        trigger = payload.trigger if isinstance(payload.trigger, dict) else None
        if payload.trigger_id:
            trigger = _load_trigger_row(conn, ctx.tenant_id, payload.trigger_id)
            if not trigger:
                raise HTTPException(status_code=404, detail="trigger_not_found")
        if not trigger:
            raise HTTPException(status_code=400, detail="trigger_or_trigger_id_required")
        result = simulate_trigger_draft(
            conn,
            tenant_id=ctx.tenant_id,
            trigger=trigger,
            conversation_id=_clean_id(payload.conversation_id or ""),
            event_kind=_clean_text(payload.event_kind, 40).lower() or "received",
            message_text=_clean_text(payload.message_text, 4000),
            context={
                "channel": _clean_channel(payload.channel),
                "customer_name": _clean_text(payload.customer_name, 160),
                "customer_phone": _clean_text(payload.customer_phone, 80),
                "tags": _clean_text(payload.tags, 500),
                "crm_stage": _clean_text(payload.crm_stage, 120),
                "payment_status": _clean_text(payload.payment_status, 120),
                "takeover": bool(payload.takeover),
            },
        )
    return {"ok": True, "tenant_id": ctx.tenant_id, "simulation": result}


@router.post("/triggers/{trigger_id}/preflight")
def preflight_trigger(trigger_id: str, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_triggers(conn, ctx.tenant_id)
        row = _load_trigger_row(conn, ctx.tenant_id, trigger_id)
        if not row:
            raise HTTPException(status_code=404, detail="trigger_not_found")
        preflight = _trigger_preflight(conn, ctx.tenant_id, row)
        conn.execute(
            text(
                """
                UPDATE saas_crm_triggers
                SET preflight_json = CAST(:preflight_json AS jsonb),
                    last_preflight_at = NOW(),
                    updated_at = NOW()
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:trigger_id AS uuid)
                """
            ),
            {"tenant_id": ctx.tenant_id, "trigger_id": trigger_id, "preflight_json": _json_dump(preflight, {})},
        )
        _record_preflight_run(conn, tenant_id=ctx.tenant_id, user_id=ctx.user_id, entity_type="trigger", entity_id=trigger_id, result=preflight)
    return {"ok": True, "tenant_id": ctx.tenant_id, "trigger_id": trigger_id, "preflight": preflight}


@router.post("/triggers")
def create_trigger(payload: TriggerIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    try:
        with db_session() as conn:
            set_tenant_context(conn, ctx.tenant_id)
            _ensure_triggers(conn, ctx.tenant_id)
            values = {
                "name": _clean_text(payload.name, 160),
                "channel": _clean_channel(payload.channel),
                "event_type": _clean_text(payload.event_type, 80).lower() or "message_in",
                "trigger_type": _clean_text(payload.trigger_type, 80).lower() or "message_flow",
                "flow_event": _clean_text(payload.flow_event, 40).lower() or "received",
                "conditions_json": payload.conditions_json or {"conditions": []},
                "actions_json": payload.actions_json or {"actions": []},
                "priority": payload.priority,
                "cooldown_minutes": payload.cooldown_minutes,
                "is_active": payload.is_active,
                "assistant_enabled": bool(payload.assistant_enabled),
                "assistant_message_type": _clean_text(payload.assistant_message_type, 40).lower() or "auto",
                "block_ai": bool(payload.block_ai),
                "stop_on_match": bool(payload.stop_on_match),
                "only_when_no_takeover": bool(payload.only_when_no_takeover),
                "quiet_hours_json": payload.quiet_hours_json or {},
                "ab_test_json": payload.ab_test_json or {},
                "revision_note": _clean_text(payload.revision_note, 500),
            }
            preflight = _trigger_preflight(conn, ctx.tenant_id, values)
            if values["is_active"] and not preflight["ready"]:
                raise HTTPException(status_code=409, detail={"code": "trigger_preflight_failed", "preflight": preflight})
            row = conn.execute(
                text(
                    """
                    INSERT INTO saas_crm_triggers (
                        tenant_id, name, channel, event_type, trigger_type, flow_event, conditions_json, actions_json,
                        priority, cooldown_minutes, is_active, assistant_enabled, assistant_message_type,
                        block_ai, stop_on_match, only_when_no_takeover, quiet_hours_json, ab_test_json,
                        preflight_json, last_preflight_at, revision_note, created_by_user_id
                    )
                    VALUES (
                        CAST(:tenant_id AS uuid), :name, :channel, :event_type, :trigger_type, :flow_event,
                        CAST(:conditions_json AS jsonb), CAST(:actions_json AS jsonb), :priority, :cooldown_minutes,
                        :is_active, :assistant_enabled, :assistant_message_type, :block_ai, :stop_on_match,
                        :only_when_no_takeover, CAST(:quiet_hours_json AS jsonb), CAST(:ab_test_json AS jsonb),
                        CAST(:preflight_json AS jsonb), NOW(), :revision_note, CAST(:user_id AS uuid)
                    )
                    RETURNING id::text, name, channel, event_type, trigger_type, flow_event, conditions_json, actions_json,
                              priority, cooldown_minutes, is_active, assistant_enabled, assistant_message_type,
                              block_ai, stop_on_match, only_when_no_takeover, quiet_hours_json, ab_test_json,
                              preflight_json, last_preflight_at::text, version_number, revision_note,
                              last_run_at::text, created_at::text, updated_at::text
                    """
                ),
                {
                    "tenant_id": ctx.tenant_id,
                    "user_id": ctx.user_id,
                    **values,
                    "conditions_json": _json_dump(values["conditions_json"], {"conditions": []}),
                    "actions_json": _json_dump(values["actions_json"], {"actions": []}),
                    "quiet_hours_json": _json_dump(values["quiet_hours_json"], {}),
                    "ab_test_json": _json_dump(values["ab_test_json"], {}),
                    "preflight_json": _json_dump(preflight, {}),
                },
            ).mappings().first()
            _record_trigger_version(conn, ctx.tenant_id, ctx.user_id, dict(row or {}), values["revision_note"] or "trigger_created")
            _record_preflight_run(conn, tenant_id=ctx.tenant_id, user_id=ctx.user_id, entity_type="trigger", entity_id=row["id"] if row else "", result=preflight)
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
    normalized: dict[str, Any] = {}
    for key, value in data.items():
        if key in ("conditions_json", "actions_json", "quiet_hours_json", "ab_test_json"):
            fallback = {"conditions": []} if key == "conditions_json" else {"actions": []} if key == "actions_json" else {}
            normalized[key] = _json_value(value, fallback)
            params[key] = _json_dump(normalized[key], fallback)
            assignments.append(f"{key} = CAST(:{key} AS jsonb)")
        elif key in ("is_active", "assistant_enabled", "block_ai", "stop_on_match", "only_when_no_takeover"):
            normalized[key] = bool(value)
            params[key] = normalized[key]
            assignments.append(f"{key} = :{key}")
        elif key in ("priority", "cooldown_minutes"):
            normalized[key] = int(value)
            params[key] = normalized[key]
            assignments.append(f"{key} = :{key}")
        elif key == "channel":
            normalized[key] = _clean_channel(value)
            params[key] = normalized[key]
            assignments.append("channel = :channel")
        elif key == "revision_note":
            normalized[key] = _clean_text(value, 500)
            params[key] = normalized[key]
        else:
            normalized[key] = _clean_text(value, 160)
            params[key] = normalized[key]
            assignments.append(f"{key} = :{key}")
    preflight = None
    row = None
    assignments.append("updated_at = NOW()")
    try:
        with db_session() as conn:
            set_tenant_context(conn, ctx.tenant_id)
            _ensure_triggers(conn, ctx.tenant_id)
            current = _load_trigger_row(conn, ctx.tenant_id, trigger_id)
            if not current:
                raise HTTPException(status_code=404, detail="trigger_not_found")
            preflight_values = {**current, **normalized}
            preflight = _trigger_preflight(conn, ctx.tenant_id, preflight_values)
            if bool(preflight_values.get("is_active")) and not preflight["ready"]:
                raise HTTPException(status_code=409, detail={"code": "trigger_preflight_failed", "preflight": preflight})
            _record_trigger_version(conn, ctx.tenant_id, ctx.user_id, current, "before_update")
            params["preflight_json"] = _json_dump(preflight, {})
            params["revision_note"] = normalized.get("revision_note") or _clean_text(current.get("revision_note"), 500) or "trigger_updated"
            assignments.append("preflight_json = CAST(:preflight_json AS jsonb)")
            assignments.append("last_preflight_at = NOW()")
            assignments.append("revision_note = :revision_note")
            assignments.append("version_number = version_number + 1")
            row = conn.execute(
                text(
                    f"""
                    UPDATE saas_crm_triggers
                    SET {", ".join(assignments)}
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND id = CAST(:trigger_id AS uuid)
                    RETURNING id::text, name, channel, event_type, trigger_type, flow_event, conditions_json, actions_json,
                              priority, cooldown_minutes, is_active, assistant_enabled, assistant_message_type,
                              block_ai, stop_on_match, only_when_no_takeover, quiet_hours_json, ab_test_json,
                              preflight_json, last_preflight_at::text, version_number, revision_note,
                              last_run_at::text, created_at::text, updated_at::text
                    """
                ),
                params,
            ).mappings().first()
            _record_trigger_version(conn, ctx.tenant_id, ctx.user_id, dict(row or {}), params["revision_note"])
            _record_preflight_run(conn, tenant_id=ctx.tenant_id, user_id=ctx.user_id, entity_type="trigger", entity_id=trigger_id, result=preflight)
    except IntegrityError:
        raise HTTPException(status_code=409, detail="trigger_already_exists")
    if not row:
        raise HTTPException(status_code=404, detail="trigger_not_found")
    return {"ok": True, "tenant_id": ctx.tenant_id, "trigger": _row_dict(row)}


@router.get("/triggers/{trigger_id}/versions")
def list_trigger_versions(trigger_id: str, ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_triggers(conn, ctx.tenant_id)
        if not _load_trigger_row(conn, ctx.tenant_id, trigger_id):
            raise HTTPException(status_code=404, detail="trigger_not_found")
        rows = _list_rows(
            conn,
            """
            SELECT id::text, trigger_id::text, version_number, snapshot_json, change_reason,
                   created_by_user_id::text, created_at::text
            FROM saas_crm_trigger_versions
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND trigger_id = CAST(:trigger_id AS uuid)
            ORDER BY version_number DESC, created_at DESC
            """,
            {"tenant_id": ctx.tenant_id, "trigger_id": trigger_id},
        )
    return {"tenant_id": ctx.tenant_id, "trigger_id": trigger_id, "versions": rows}


@router.post("/triggers/{trigger_id}/versions/{version_id}/restore")
def restore_trigger_version(
    trigger_id: str,
    version_id: str,
    payload: TriggerVersionRestoreIn | None = None,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    note = _clean_text((payload.revision_note if payload else "") or "restore_version", 500)
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_triggers(conn, ctx.tenant_id)
        current = _load_trigger_row(conn, ctx.tenant_id, trigger_id)
        if not current:
            raise HTTPException(status_code=404, detail="trigger_not_found")
        version = conn.execute(
            text(
                """
                SELECT snapshot_json
                FROM saas_crm_trigger_versions
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND trigger_id = CAST(:trigger_id AS uuid)
                  AND id = CAST(:version_id AS uuid)
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id, "trigger_id": trigger_id, "version_id": version_id},
        ).mappings().first()
        if not version:
            raise HTTPException(status_code=404, detail="trigger_version_not_found")
        snapshot = _json_value(version.get("snapshot_json"), {})
        if not isinstance(snapshot, dict):
            raise HTTPException(status_code=400, detail="invalid_trigger_version_snapshot")
        values = {
            "name": _clean_text(snapshot.get("name"), 160) or current["name"],
            "channel": _clean_channel(snapshot.get("channel")),
            "event_type": _clean_text(snapshot.get("event_type"), 80).lower() or "message_in",
            "trigger_type": _clean_text(snapshot.get("trigger_type"), 80).lower() or "message_flow",
            "flow_event": _clean_text(snapshot.get("flow_event"), 40).lower() or "received",
            "conditions_json": _json_value(snapshot.get("conditions_json"), {"conditions": []}),
            "actions_json": _json_value(snapshot.get("actions_json"), {"actions": []}),
            "priority": int(snapshot.get("priority") or 100),
            "cooldown_minutes": int(snapshot.get("cooldown_minutes") or 0),
            "is_active": bool(snapshot.get("is_active")),
            "assistant_enabled": bool(snapshot.get("assistant_enabled")),
            "assistant_message_type": _clean_text(snapshot.get("assistant_message_type"), 40).lower() or "auto",
            "block_ai": bool(snapshot.get("block_ai")),
            "stop_on_match": bool(snapshot.get("stop_on_match")),
            "only_when_no_takeover": bool(snapshot.get("only_when_no_takeover")),
            "quiet_hours_json": _json_value(snapshot.get("quiet_hours_json"), {}),
            "ab_test_json": _json_value(snapshot.get("ab_test_json"), {}),
        }
        preflight = _trigger_preflight(conn, ctx.tenant_id, values)
        if values["is_active"] and not preflight["ready"]:
            raise HTTPException(status_code=409, detail={"code": "trigger_preflight_failed", "preflight": preflight})
        _record_trigger_version(conn, ctx.tenant_id, ctx.user_id, current, "before_restore")
        row = conn.execute(
            text(
                """
                UPDATE saas_crm_triggers
                SET name = :name,
                    channel = :channel,
                    event_type = :event_type,
                    trigger_type = :trigger_type,
                    flow_event = :flow_event,
                    conditions_json = CAST(:conditions_json AS jsonb),
                    actions_json = CAST(:actions_json AS jsonb),
                    priority = :priority,
                    cooldown_minutes = :cooldown_minutes,
                    is_active = :is_active,
                    assistant_enabled = :assistant_enabled,
                    assistant_message_type = :assistant_message_type,
                    block_ai = :block_ai,
                    stop_on_match = :stop_on_match,
                    only_when_no_takeover = :only_when_no_takeover,
                    quiet_hours_json = CAST(:quiet_hours_json AS jsonb),
                    ab_test_json = CAST(:ab_test_json AS jsonb),
                    preflight_json = CAST(:preflight_json AS jsonb),
                    last_preflight_at = NOW(),
                    revision_note = :revision_note,
                    version_number = version_number + 1,
                    updated_at = NOW()
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:trigger_id AS uuid)
                RETURNING id::text, name, channel, event_type, trigger_type, flow_event, conditions_json, actions_json,
                          priority, cooldown_minutes, is_active, assistant_enabled, assistant_message_type,
                          block_ai, stop_on_match, only_when_no_takeover, quiet_hours_json, ab_test_json,
                          preflight_json, last_preflight_at::text, version_number, revision_note,
                          last_run_at::text, created_at::text, updated_at::text
                """
            ),
            {
                "tenant_id": ctx.tenant_id,
                "trigger_id": trigger_id,
                **values,
                "conditions_json": _json_dump(values["conditions_json"], {"conditions": []}),
                "actions_json": _json_dump(values["actions_json"], {"actions": []}),
                "quiet_hours_json": _json_dump(values["quiet_hours_json"], {}),
                "ab_test_json": _json_dump(values["ab_test_json"], {}),
                "preflight_json": _json_dump(preflight, {}),
                "revision_note": note,
            },
        ).mappings().first()
        _record_trigger_version(conn, ctx.tenant_id, ctx.user_id, dict(row or {}), note)
        _record_preflight_run(conn, tenant_id=ctx.tenant_id, user_id=ctx.user_id, entity_type="trigger", entity_id=trigger_id, result=preflight)
    return {"ok": True, "tenant_id": ctx.tenant_id, "trigger": _row_dict(row), "preflight": preflight}


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
                       block_ai, stop_on_match, only_when_no_takeover, quiet_hours_json, ab_test_json
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

        values = {
            "name": candidate,
            "channel": target_channel,
            "event_type": source["event_type"],
            "trigger_type": source["trigger_type"],
            "flow_event": source["flow_event"],
            "conditions_json": _json_value(source["conditions_json"], {"conditions": []}),
            "actions_json": _json_value(source["actions_json"], {"actions": []}),
            "priority": int(source["priority"] or 100),
            "cooldown_minutes": int(source["cooldown_minutes"] or 0),
            "is_active": bool(source["is_active"]),
            "assistant_enabled": bool(source["assistant_enabled"]),
            "assistant_message_type": source["assistant_message_type"] or "auto",
            "block_ai": bool(source["block_ai"]),
            "stop_on_match": bool(source["stop_on_match"]),
            "only_when_no_takeover": bool(source["only_when_no_takeover"]),
            "quiet_hours_json": _json_value(source["quiet_hours_json"], {}),
            "ab_test_json": _json_value(source["ab_test_json"], {}),
        }
        preflight = _trigger_preflight(conn, ctx.tenant_id, values)
        if values["is_active"] and not preflight["ready"]:
            raise HTTPException(status_code=409, detail={"code": "trigger_preflight_failed", "preflight": preflight})
        row = conn.execute(
            text(
                """
                INSERT INTO saas_crm_triggers (
                    tenant_id, name, channel, event_type, trigger_type, flow_event,
                    conditions_json, actions_json, priority, cooldown_minutes, is_active,
                    assistant_enabled, assistant_message_type, block_ai, stop_on_match,
                    only_when_no_takeover, quiet_hours_json, ab_test_json, preflight_json,
                    last_preflight_at, revision_note, created_by_user_id
                )
                VALUES (
                    CAST(:tenant_id AS uuid), :name, :channel, :event_type, :trigger_type, :flow_event,
                    CAST(:conditions_json AS jsonb), CAST(:actions_json AS jsonb), :priority, :cooldown_minutes,
                    :is_active, :assistant_enabled, :assistant_message_type, :block_ai, :stop_on_match,
                    :only_when_no_takeover, CAST(:quiet_hours_json AS jsonb), CAST(:ab_test_json AS jsonb),
                    CAST(:preflight_json AS jsonb), NOW(), 'trigger_copied', CAST(:user_id AS uuid)
                )
                RETURNING id::text, name, channel, event_type, trigger_type, flow_event, conditions_json, actions_json,
                          priority, cooldown_minutes, is_active, assistant_enabled, assistant_message_type,
                          block_ai, stop_on_match, only_when_no_takeover, quiet_hours_json, ab_test_json,
                          preflight_json, last_preflight_at::text, version_number, revision_note,
                          last_run_at::text, created_at::text, updated_at::text
                """
            ),
            {
                "tenant_id": ctx.tenant_id,
                "user_id": ctx.user_id,
                **values,
                "conditions_json": _json_dump(values["conditions_json"], {"conditions": []}),
                "actions_json": _json_dump(values["actions_json"], {"actions": []}),
                "quiet_hours_json": _json_dump(values["quiet_hours_json"], {}),
                "ab_test_json": _json_dump(values["ab_test_json"], {}),
                "preflight_json": _json_dump(preflight, {}),
            },
        ).mappings().first()
        _record_trigger_version(conn, ctx.tenant_id, ctx.user_id, dict(row or {}), "trigger_copied")
        _record_preflight_run(conn, tenant_id=ctx.tenant_id, user_id=ctx.user_id, entity_type="trigger", entity_id=row["id"] if row else "", result=preflight)
    return {"ok": True, "tenant_id": ctx.tenant_id, "source_trigger_id": trigger_id, "trigger": _row_dict(row)}


@router.get("/flows")
def list_flows(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_remarketing(conn, ctx.tenant_id)
        rows = _list_rows(
            conn,
            """
            SELECT id::text, name, description, channel, status, entry_rules_json, exit_rules_json, steps_json,
                   quiet_hours_json, ab_test_json, preflight_json, last_preflight_at::text, version_number,
                   created_at::text, updated_at::text
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


@router.post("/flows/preflight")
def preflight_flow_draft(payload: PreflightIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    draft = payload.draft if isinstance(payload.draft, dict) else {}
    values = {
        "name": _clean_text(draft.get("name"), 160),
        "description": _clean_text(draft.get("description"), 1000),
        "channel": _clean_channel(draft.get("channel")),
        "status": _clean_text(draft.get("status"), 40).lower() or "draft",
        "entry_rules_json": _json_value(draft.get("entry_rules_json"), {}),
        "exit_rules_json": _json_value(draft.get("exit_rules_json"), {}),
        "steps_json": _json_value(draft.get("steps_json"), []),
        "quiet_hours_json": _json_value(draft.get("quiet_hours_json"), {}),
        "ab_test_json": _json_value(draft.get("ab_test_json"), {}),
    }
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_remarketing(conn, ctx.tenant_id)
        preflight = _flow_preflight(conn, ctx.tenant_id, values)
        _record_preflight_run(conn, tenant_id=ctx.tenant_id, user_id=ctx.user_id, entity_type="flow_draft", result=preflight)
    return {"ok": True, "tenant_id": ctx.tenant_id, "preflight": preflight}


@router.post("/flows/{flow_id}/preflight")
def preflight_flow(flow_id: str, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_remarketing(conn, ctx.tenant_id)
        row = conn.execute(
            text(
                """
                SELECT id::text, name, description, channel, status, entry_rules_json, exit_rules_json, steps_json,
                       quiet_hours_json, ab_test_json
                FROM saas_remarketing_flows
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:flow_id AS uuid)
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id, "flow_id": flow_id},
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="flow_not_found")
        preflight = _flow_preflight(conn, ctx.tenant_id, dict(row))
        conn.execute(
            text(
                """
                UPDATE saas_remarketing_flows
                SET preflight_json = CAST(:preflight_json AS jsonb),
                    last_preflight_at = NOW(),
                    updated_at = NOW()
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:flow_id AS uuid)
                """
            ),
            {"tenant_id": ctx.tenant_id, "flow_id": flow_id, "preflight_json": _json_dump(preflight, {})},
        )
        _record_preflight_run(conn, tenant_id=ctx.tenant_id, user_id=ctx.user_id, entity_type="flow", entity_id=flow_id, result=preflight)
    return {"ok": True, "tenant_id": ctx.tenant_id, "flow_id": flow_id, "preflight": preflight}


@router.post("/flows")
def create_flow(payload: FlowIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    try:
        with db_session() as conn:
            set_tenant_context(conn, ctx.tenant_id)
            _ensure_remarketing(conn, ctx.tenant_id)
            values = {
                "name": _clean_text(payload.name, 160),
                "description": _clean_text(payload.description, 1000),
                "channel": _clean_channel(payload.channel),
                "status": _clean_text(payload.status, 40).lower() or "draft",
                "entry_rules_json": payload.entry_rules_json or {},
                "exit_rules_json": payload.exit_rules_json or {},
                "steps_json": payload.steps_json or [],
                "quiet_hours_json": payload.quiet_hours_json or {},
                "ab_test_json": payload.ab_test_json or {},
            }
            preflight = _flow_preflight(conn, ctx.tenant_id, values)
            if values["status"] == "active" and not preflight["ready"]:
                raise HTTPException(status_code=409, detail={"code": "flow_preflight_failed", "preflight": preflight})
            row = conn.execute(
                text(
                    """
                    INSERT INTO saas_remarketing_flows (
                        tenant_id, name, description, channel, status, entry_rules_json, exit_rules_json, steps_json,
                        quiet_hours_json, ab_test_json, preflight_json, last_preflight_at, created_by_user_id
                    )
                    VALUES (
                        CAST(:tenant_id AS uuid), :name, :description, :channel, :status,
                        CAST(:entry_rules_json AS jsonb), CAST(:exit_rules_json AS jsonb), CAST(:steps_json AS jsonb),
                        CAST(:quiet_hours_json AS jsonb), CAST(:ab_test_json AS jsonb), CAST(:preflight_json AS jsonb),
                        NOW(), CAST(:user_id AS uuid)
                    )
                    RETURNING id::text, name, description, channel, status, entry_rules_json, exit_rules_json, steps_json,
                              quiet_hours_json, ab_test_json, preflight_json, last_preflight_at::text, version_number,
                              created_at::text, updated_at::text
                    """
                ),
                {
                    "tenant_id": ctx.tenant_id,
                    "user_id": ctx.user_id,
                    **values,
                    "entry_rules_json": _json_dump(values["entry_rules_json"], {}),
                    "exit_rules_json": _json_dump(values["exit_rules_json"], {}),
                    "steps_json": _json_dump(values["steps_json"], []),
                    "quiet_hours_json": _json_dump(values["quiet_hours_json"], {}),
                    "ab_test_json": _json_dump(values["ab_test_json"], {}),
                    "preflight_json": _json_dump(preflight, {}),
                },
            ).mappings().first()
            _record_preflight_run(conn, tenant_id=ctx.tenant_id, user_id=ctx.user_id, entity_type="flow", entity_id=row["id"] if row else "", result=preflight)
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
    normalized: dict[str, Any] = {}
    for key, value in data.items():
        if key in ("entry_rules_json", "exit_rules_json", "quiet_hours_json", "ab_test_json"):
            normalized[key] = _json_value(value, {})
            params[key] = _json_dump(normalized[key], {})
            assignments.append(f"{key} = CAST(:{key} AS jsonb)")
        elif key == "steps_json":
            normalized[key] = _json_value(value, [])
            params[key] = _json_dump(normalized[key], [])
            assignments.append("steps_json = CAST(:steps_json AS jsonb)")
        elif key == "channel":
            normalized[key] = _clean_channel(value)
            params[key] = normalized[key]
            assignments.append("channel = :channel")
        else:
            normalized[key] = _clean_text(value, 1000 if key == "description" else 160)
            params[key] = normalized[key]
            assignments.append(f"{key} = :{key}")
    row = None
    assignments.append("updated_at = NOW()")
    try:
        with db_session() as conn:
            set_tenant_context(conn, ctx.tenant_id)
            _ensure_remarketing(conn, ctx.tenant_id)
            current = conn.execute(
                text(
                    """
                    SELECT id::text, name, description, channel, status, entry_rules_json, exit_rules_json, steps_json,
                           quiet_hours_json, ab_test_json
                    FROM saas_remarketing_flows
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND id = CAST(:flow_id AS uuid)
                    LIMIT 1
                    """
                ),
                {"tenant_id": ctx.tenant_id, "flow_id": flow_id},
            ).mappings().first()
            if not current:
                raise HTTPException(status_code=404, detail="flow_not_found")
            preflight_values = {**dict(current), **normalized}
            preflight = _flow_preflight(conn, ctx.tenant_id, preflight_values)
            if _clean_text(preflight_values.get("status"), 40).lower() == "active" and not preflight["ready"]:
                raise HTTPException(status_code=409, detail={"code": "flow_preflight_failed", "preflight": preflight})
            params["preflight_json"] = _json_dump(preflight, {})
            assignments.append("preflight_json = CAST(:preflight_json AS jsonb)")
            assignments.append("last_preflight_at = NOW()")
            assignments.append("version_number = version_number + 1")
            row = conn.execute(
                text(
                    f"""
                    UPDATE saas_remarketing_flows
                    SET {", ".join(assignments)}
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND id = CAST(:flow_id AS uuid)
                    RETURNING id::text, name, description, channel, status, entry_rules_json, exit_rules_json, steps_json,
                              quiet_hours_json, ab_test_json, preflight_json, last_preflight_at::text, version_number,
                              created_at::text, updated_at::text
                    """
                ),
                params,
            ).mappings().first()
            _record_preflight_run(conn, tenant_id=ctx.tenant_id, user_id=ctx.user_id, entity_type="flow", entity_id=flow_id, result=preflight)
    except IntegrityError:
        raise HTTPException(status_code=409, detail="flow_already_exists")
    if not row:
        raise HTTPException(status_code=404, detail="flow_not_found")
    return {"ok": True, "tenant_id": ctx.tenant_id, "flow": _row_dict(row)}
