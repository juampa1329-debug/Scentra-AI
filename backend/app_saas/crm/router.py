from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app_saas.agents.service import assign_conversation_ai_agent
from app_saas.billing.limits import ensure_monthly_message_quota
from app_saas.crm.schemas import (
    CrmCustomFieldCreateIn,
    CrmCustomFieldPatchIn,
    CrmPipelineStageCreateIn,
    CrmPipelineStagePatchIn,
    CrmTaskCreateIn,
    CrmTaskPatchIn,
    CustomerCreateIn,
    CustomerMergeIn,
    CustomerUpdateIn,
    LabelCreateIn,
    LabelPatchIn,
    SendMessageIn,
)
from app_saas.db import db_session, set_tenant_context
from app_saas.intelligence.capture import record_inline_event
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

PRODUCT_CARD_KEYS = {
    "id",
    "name",
    "sku",
    "price",
    "regular_price",
    "sale_price",
    "currency",
    "permalink",
    "image_url",
    "stock_status",
    "short_description",
}

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
    "assigned_user_id",
    "assigned_ai_agent_id",
    "ai_owner_mode",
    "priority",
    "sla_due_at",
    "first_response_due_at",
    "lead_score",
    "lead_temperature",
    "profile_json",
    "custom_fields",
}

PRIORITY_VALUES = {"low", "normal", "high", "urgent"}
TEMPERATURE_VALUES = {"cold", "warm", "hot"}
TASK_STATUS_VALUES = {"open", "in_progress", "done", "cancelled"}
CUSTOM_FIELD_TYPES = {"text", "number", "select", "multiselect", "date", "boolean", "url", "email", "phone"}
PIPELINE_PRESETS = {
    "general": [
        ("contactado", "Contactado", 10, False, False),
        ("interes", "Interes", 30, False, False),
        ("intencion_compra", "Intencion de compra", 55, False, False),
        ("pago_pendiente", "Pago pendiente", 75, False, False),
        ("pago_confirmado", "Pago confirmado", 100, True, False),
    ],
    "restaurant": [
        ("nuevo_lead", "Nuevo lead", 10, False, False),
        ("consulta_menu", "Consulta menu", 25, False, False),
        ("reserva_solicitada", "Reserva solicitada", 55, False, False),
        ("confirmacion_pendiente", "Confirmacion pendiente", 75, False, False),
        ("reserva_confirmada", "Reserva confirmada", 100, True, False),
    ],
    "hotel": [
        ("consulta_estadia", "Consulta estadia", 10, False, False),
        ("fechas_calificadas", "Fechas calificadas", 35, False, False),
        ("cotizacion_enviada", "Cotizacion enviada", 60, False, False),
        ("pago_pendiente", "Pago pendiente", 80, False, False),
        ("reserva_confirmada", "Reserva confirmada", 100, True, False),
    ],
    "real_estate": [
        ("lead_nuevo", "Lead nuevo", 10, False, False),
        ("requisitos_calificados", "Requisitos calificados", 35, False, False),
        ("propiedades_enviadas", "Propiedades enviadas", 55, False, False),
        ("visita_agendada", "Visita agendada", 75, False, False),
        ("negocio_cerrado", "Negocio cerrado", 100, True, False),
    ],
    "health": [
        ("consulta_inicial", "Consulta inicial", 10, False, False),
        ("datos_recolectados", "Datos recolectados", 35, False, False),
        ("cita_sugerida", "Cita sugerida", 60, False, False),
        ("confirmacion_pendiente", "Confirmacion pendiente", 80, False, False),
        ("cita_confirmada", "Cita confirmada", 100, True, False),
    ],
    "education": [
        ("aspirante", "Aspirante", 10, False, False),
        ("programa_identificado", "Programa identificado", 35, False, False),
        ("requisitos_enviados", "Requisitos enviados", 60, False, False),
        ("asesoria_agendada", "Asesoria agendada", 80, False, False),
        ("matricula_confirmada", "Matricula confirmada", 100, True, False),
    ],
    "beauty": [
        ("consulta_servicio", "Consulta servicio", 10, False, False),
        ("preferencias_capturadas", "Preferencias capturadas", 35, False, False),
        ("cita_propuesta", "Cita propuesta", 60, False, False),
        ("recordatorio_pendiente", "Recordatorio pendiente", 80, False, False),
        ("cita_confirmada", "Cita confirmada", 100, True, False),
    ],
    "legal": [
        ("intake_inicial", "Intake inicial", 10, False, False),
        ("hechos_recolectados", "Hechos recolectados", 35, False, False),
        ("documentos_pendientes", "Documentos pendientes", 55, False, False),
        ("revision_humana", "Revision humana", 80, False, False),
        ("caso_aceptado", "Caso aceptado", 100, True, False),
    ],
    "insurance": [
        ("siniestro_nuevo", "Siniestro nuevo", 10, False, False),
        ("poliza_identificada", "Poliza identificada", 35, False, False),
        ("documentos_pendientes", "Documentos pendientes", 55, False, False),
        ("revision_humana", "Revision humana", 80, False, False),
        ("caso_radicado", "Caso radicado", 100, True, False),
    ],
    "services": [
        ("solicitud_nueva", "Solicitud nueva", 10, False, False),
        ("necesidad_calificada", "Necesidad calificada", 35, False, False),
        ("cotizacion_enviada", "Cotizacion enviada", 60, False, False),
        ("agenda_pendiente", "Agenda pendiente", 80, False, False),
        ("servicio_confirmado", "Servicio confirmado", 100, True, False),
    ],
}


def _clean_text(value: Any, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _safe_product_card(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    has_product_signal = any(_clean_text(raw.get(key), 900 if key in {"permalink", "image_url"} else 500) for key in PRODUCT_CARD_KEYS)
    has_product_signal = has_product_signal or bool(raw.get("categories")) or bool(raw.get("attributes"))
    if not has_product_signal:
        return {}
    product: dict[str, Any] = {key: _clean_text(raw.get(key), 900 if key in {"permalink", "image_url"} else 500) for key in PRODUCT_CARD_KEYS}
    categories = raw.get("categories")
    if isinstance(categories, list):
        product["categories"] = [_clean_text(item, 80) for item in categories if _clean_text(item, 80)][:8]
    else:
        product["categories"] = []
    attributes = raw.get("attributes")
    clean_attributes: list[dict[str, str]] = []
    if isinstance(attributes, list):
        for item in attributes:
            if not isinstance(item, dict):
                continue
            name = _clean_text(item.get("name"), 80)
            value = _clean_text(item.get("value"), 220)
            if name and value:
                clean_attributes.append({"name": name, "value": value})
    product["attributes"] = clean_attributes[:8]
    if not product.get("name"):
        product["name"] = "Producto"
    return product


def _product_caption(product: dict[str, Any], note: str = "") -> str:
    lines: list[str] = []
    clean_note = _clean_text(note, 900)
    if clean_note:
        lines.append(clean_note)
        lines.append("")
    if product.get("name"):
        lines.append(str(product["name"]))
    price = product.get("sale_price") or product.get("price") or product.get("regular_price")
    if price:
        lines.append(f"Precio: {price}")
    sku = product.get("sku")
    if sku:
        lines.append(f"SKU: {sku}")
    for attribute in product.get("attributes") or []:
        lines.append(f"{attribute['name']}: {attribute['value']}")
    if product.get("short_description"):
        lines.append(str(product["short_description"]))
    if product.get("permalink"):
        lines.append(f"Ver producto: {product['permalink']}")
    return "\n".join(line for line in lines if line is not None).strip()[:4096]


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


def _clean_optional_uuid(value: Any) -> str:
    return _clean_text(value, 80)


def _clean_optional_timestamp(value: Any) -> str:
    return _clean_text(value, 80)


def _normalize_priority(value: Any) -> str:
    priority = _clean_text(value, 40).lower().replace(" ", "_")
    return priority if priority in PRIORITY_VALUES else "normal"


def _temperature_from_score(score: int, fallback: Any = "") -> str:
    raw = _clean_text(fallback, 40).lower()
    if raw in TEMPERATURE_VALUES:
        return raw
    if score >= 75:
        return "hot"
    if score >= 40:
        return "warm"
    return "cold"


def _clean_key(value: Any, limit: int = 80) -> str:
    key = re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower())
    key = re.sub(r"_+", "_", key).strip("_")
    return key[:limit]


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _json_list_or_object(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, (list, dict)) else []
        except Exception:
            return []
    return []


def _safe_custom_value(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return max(-999999999, min(999999999, value))
    if isinstance(value, float):
        return max(-999999999.0, min(999999999.0, value))
    if isinstance(value, list):
        return [_clean_text(item, 240) for item in value[:25] if _clean_text(item, 240)]
    return _clean_text(value, 1200)


def _sanitize_custom_fields(value: Any, allowed_keys: set[str] | None = None, *, strict: bool = True) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    clean: dict[str, Any] = {}
    unknown: list[str] = []
    for raw_key, raw_value in value.items():
        key = _clean_key(raw_key)
        if not key:
            continue
        if allowed_keys is not None and key not in allowed_keys:
            unknown.append(key)
            continue
        clean[key] = _safe_custom_value(raw_value)
        if len(clean) >= 60:
            break
    if strict and unknown:
        raise HTTPException(status_code=400, detail={"code": "unknown_custom_fields", "fields": sorted(set(unknown))[:20]})
    return clean


def _profile_with_custom_fields(profile: Any, custom_fields: dict[str, Any]) -> dict[str, Any]:
    base = _json_object(profile)
    existing = base.get("custom_fields") if isinstance(base.get("custom_fields"), dict) else {}
    base["custom_fields"] = {**existing, **custom_fields}
    return base


def _active_custom_field_keys(conn, tenant_id: str) -> set[str]:
    rows = conn.execute(
        text(
            """
            SELECT field_key
            FROM saas_crm_custom_fields
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND is_active = TRUE
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().all()
    return {str(row["field_key"]) for row in rows}


def _record_timeline_event(
    conn,
    tenant_id: str,
    conversation_id: str,
    event_type: str,
    title: str,
    description: str = "",
    actor_user_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        text(
            """
            INSERT INTO saas_crm_timeline_events (
                tenant_id,
                conversation_id,
                event_type,
                title,
                description,
                actor_user_id,
                metadata_json
            )
            VALUES (
                CAST(:tenant_id AS uuid),
                CAST(:conversation_id AS uuid),
                :event_type,
                :title,
                :description,
                CAST(NULLIF(:actor_user_id, '') AS uuid),
                CAST(:metadata_json AS jsonb)
            )
            """
        ),
        {
            "tenant_id": tenant_id,
            "conversation_id": conversation_id,
            "event_type": _clean_text(event_type, 80) or "crm_event",
            "title": _clean_text(title, 180),
            "description": _clean_text(description, 1200),
            "actor_user_id": _clean_optional_uuid(actor_user_id),
            "metadata_json": json.dumps(metadata or {}),
        },
    )


def _pipeline_preset(industry_code: str) -> list[tuple[str, str, int, bool, bool]]:
    return PIPELINE_PRESETS.get(_clean_key(industry_code), PIPELINE_PRESETS["general"])


def _ensure_default_pipeline(conn, tenant_id: str, industry_code: str = "general", user_id: str = "") -> dict[str, Any]:
    pipeline = conn.execute(
        text(
            """
            SELECT id::text, name, industry_code, is_default, created_at::text, updated_at::text
            FROM saas_crm_pipelines
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND is_default = TRUE
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    if not pipeline:
        pipeline = conn.execute(
            text(
                """
                INSERT INTO saas_crm_pipelines (tenant_id, name, industry_code, is_default, created_by_user_id)
                VALUES (
                    CAST(:tenant_id AS uuid),
                    'Pipeline comercial',
                    :industry_code,
                    TRUE,
                    CAST(NULLIF(:user_id, '') AS uuid)
                )
                RETURNING id::text, name, industry_code, is_default, created_at::text, updated_at::text
                """
            ),
            {"tenant_id": tenant_id, "industry_code": _clean_key(industry_code) or "general", "user_id": _clean_optional_uuid(user_id)},
        ).mappings().first()

    stage_count = conn.execute(
        text(
            """
            SELECT COUNT(*)::int
            FROM saas_crm_pipeline_stages
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND pipeline_id = CAST(:pipeline_id AS uuid)
            """
        ),
        {"tenant_id": tenant_id, "pipeline_id": pipeline["id"]},
    ).scalar_one()
    if int(stage_count or 0) == 0:
        for index, (stage_key, label, probability, is_won, is_lost) in enumerate(_pipeline_preset(pipeline["industry_code"] or industry_code), start=1):
            conn.execute(
                text(
                    """
                    INSERT INTO saas_crm_pipeline_stages (
                        tenant_id,
                        pipeline_id,
                        stage_key,
                        label,
                        probability,
                        display_order,
                        is_won,
                        is_lost
                    )
                    VALUES (
                        CAST(:tenant_id AS uuid),
                        CAST(:pipeline_id AS uuid),
                        :stage_key,
                        :label,
                        :probability,
                        :display_order,
                        :is_won,
                        :is_lost
                    )
                    ON CONFLICT DO NOTHING
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "pipeline_id": pipeline["id"],
                    "stage_key": stage_key,
                    "label": label,
                    "probability": probability,
                    "display_order": index * 10,
                    "is_won": is_won,
                    "is_lost": is_lost,
                },
            )
    return dict(pipeline)


def _pipeline_stages(conn, tenant_id: str, pipeline_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT
                id::text,
                pipeline_id::text,
                stage_key,
                label,
                probability,
                display_order,
                is_won,
                is_lost,
                is_active,
                created_at::text,
                updated_at::text
            FROM saas_crm_pipeline_stages
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND pipeline_id = CAST(:pipeline_id AS uuid)
            ORDER BY display_order ASC, label ASC
            """
        ),
        {"tenant_id": tenant_id, "pipeline_id": pipeline_id},
    ).mappings().all()
    return [dict(row) for row in rows]


def _table_exists(conn, table_name: str) -> bool:
    return bool(conn.execute(text("SELECT to_regclass(:table_name)"), {"table_name": table_name}).scalar_one_or_none())


def _ensure_ai_assignment_columns(conn) -> None:
    conn.execute(
        text(
            """
            ALTER TABLE saas_conversations
              ADD COLUMN IF NOT EXISTS assigned_ai_agent_id UUID NULL REFERENCES saas_ai_agents(id) ON DELETE SET NULL,
              ADD COLUMN IF NOT EXISTS ai_owner_mode TEXT NOT NULL DEFAULT 'general',
              ADD COLUMN IF NOT EXISTS ai_owner_locked_at TIMESTAMP NULL
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_conversations_ai_agent
            ON saas_conversations (tenant_id, assigned_ai_agent_id, updated_at DESC)
            """
        )
    )


def _update_conversation_reference(conn, table_name: str, tenant_id: str, source_id: str, target_id: str) -> int:
    if not _table_exists(conn, table_name):
        return 0
    result = conn.execute(
        text(
            f"""
            UPDATE {table_name}
            SET conversation_id = CAST(:target_id AS uuid)
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND conversation_id = CAST(:source_id AS uuid)
            """
        ),
        {"tenant_id": tenant_id, "source_id": source_id, "target_id": target_id},
    )
    return int(result.rowcount or 0)


def _infer_lead_score(row: dict[str, Any]) -> tuple[int, str]:
    score = 10
    stage = str(row.get("crm_stage") or "").lower()
    payment_status = str(row.get("payment_status") or "").lower()
    tags = str(row.get("tags") or "").lower()
    interests = str(row.get("interests") or "").lower()
    preview = str(row.get("last_message_text") or "").lower()
    unread = int(row.get("unread_count") or 0)
    if stage in {"interes", "intencion_compra", "pago_pendiente"}:
        score += {"interes": 18, "intencion_compra": 34, "pago_pendiente": 28}.get(stage, 0)
    if payment_status == "pending":
        score += 18
    if payment_status == "paid":
        score += 10
    if interests:
        score += 10
    if tags:
        score += 8
    if unread:
        score += min(20, 5 + unread * 3)
    if any(token in preview for token in ("precio", "compr", "pago", "cotiz", "reserv", "disponible", "envio", "catálogo", "catalogo")):
        score += 16
    score = max(0, min(100, score))
    return score, _temperature_from_score(score, row.get("lead_temperature"))


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _days_since(value: Any) -> int:
    parsed = _parse_timestamp(value)
    if not parsed:
        return 0
    return max(0, int((datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() // 86400))


def _prediction_json(row: dict[str, Any], prefix: str) -> dict[str, Any]:
    score_key = f"{prefix}_score"
    if row.get(score_key) is None and not row.get(f"{prefix}_label"):
        return {}
    output = _json_object(row.get(f"{prefix}_output_json"))
    return {
        "score": round(float(row.get(score_key) or 0), 2),
        "label": row.get(f"{prefix}_label") or "",
        "confidence": round(float(row.get(f"{prefix}_confidence") or 0), 3),
        "status": row.get(f"{prefix}_status") or "",
        "created_at": row.get(f"{prefix}_created_at") or "",
        "output_json": output,
        "source": "intelligence_prediction",
    }


def _predictive_intelligence(row: dict[str, Any]) -> dict[str, Any]:
    lead_score = int(row.get("lead_score") or 0)
    inferred_score, inferred_temperature = _infer_lead_score(row)
    score = max(lead_score, inferred_score)
    temperature = str(row.get("lead_temperature") or inferred_temperature or _temperature_from_score(score)).lower()
    inactivity_days = _days_since(row.get("last_customer_message_at") or row.get("last_message_at") or row.get("updated_at"))
    unread = int(row.get("unread_count") or 0)
    lead_prediction = _prediction_json(row, "predictive_lead")
    churn_prediction = _prediction_json(row, "predictive_churn")
    remarketing_prediction = _prediction_json(row, "predictive_remarketing")
    predictive_score = int(lead_prediction.get("score") or score)
    churn_risk = int(churn_prediction.get("score") or min(100, inactivity_days * 6 + (15 if unread == 0 and inactivity_days >= 7 else 0)))
    conversion_probability = max(0, min(100, predictive_score))
    engagement_score = max(0, min(100, predictive_score + min(unread * 4, 12) - min(inactivity_days * 2, 24)))
    if predictive_score >= 75 or temperature == "hot":
        lead_label = "Hot Lead"
        recommended_action = "Priorizar seguimiento humano"
    elif predictive_score >= 45 or temperature == "warm":
        lead_label = "Warm Lead"
        recommended_action = "Programar follow-up comercial"
    else:
        lead_label = "Cold Lead"
        recommended_action = "Nutrir con contenido o remarketing suave"
    if churn_risk >= 70:
        retention_priority = "Alta"
        churn_label = "High churn risk"
    elif churn_risk >= 40:
        retention_priority = "Media"
        churn_label = "Medium churn risk"
    else:
        retention_priority = "Baja"
        churn_label = "Low churn risk"
    remarketing_output = remarketing_prediction.get("output_json") or {}
    return {
        "lead_score": predictive_score,
        "conversion_probability": conversion_probability,
        "engagement_score": engagement_score,
        "temperature": temperature,
        "lead_label": lead_label,
        "churn_risk": churn_risk,
        "churn_label": churn_label,
        "retention_priority": retention_priority,
        "inactivity_days": inactivity_days,
        "recommended_action": recommended_action,
        "best_channel": remarketing_output.get("best_channel") or row.get("channel") or "whatsapp",
        "best_window": remarketing_output.get("best_window") or "09:00-11:00 local",
        "frequency": remarketing_output.get("frequency") or "1 touch cada 48-72 horas",
        "lead_prediction": lead_prediction,
        "churn_prediction": churn_prediction,
        "remarketing_prediction": remarketing_prediction,
        "source": "intelligence_prediction" if lead_prediction or churn_prediction or remarketing_prediction else "crm_baseline",
    }


def _task_row(row) -> dict:
    data = dict(row)
    data["is_overdue"] = bool(data.get("is_overdue"))
    return data


def _customer_row(row) -> dict:
    data = dict(row)
    labels = data.get("labels") or []
    if isinstance(labels, str):
        try:
            labels = json.loads(labels)
        except Exception:
            labels = []
    data["labels"] = labels
    profile = _json_object(data.get("profile_json"))
    data["profile_json"] = profile
    data["custom_fields"] = profile.get("custom_fields") if isinstance(profile.get("custom_fields"), dict) else {}
    data["tag_list"] = _normalize_tags(data.get("tags") or "")
    data["predictive_intelligence"] = _predictive_intelligence(data)
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
        c.assigned_user_id::text,
        au.full_name AS assigned_user_name,
        au.email AS assigned_user_email,
        c.assigned_ai_agent_id::text,
        aa.name AS assigned_ai_agent_name,
        aa.agent_type AS assigned_ai_agent_type,
        c.ai_owner_mode,
        c.ai_owner_locked_at::text,
        c.priority,
        c.sla_due_at::text,
        c.first_response_due_at::text,
        c.lead_score,
        c.lead_temperature,
        c.last_customer_message_at::text,
        c.last_agent_message_at::text,
        pred_lead.score AS predictive_lead_score,
        pred_lead.label AS predictive_lead_label,
        pred_lead.confidence AS predictive_lead_confidence,
        pred_lead.status AS predictive_lead_status,
        pred_lead.output_json AS predictive_lead_output_json,
        pred_lead.created_at::text AS predictive_lead_created_at,
        pred_churn.score AS predictive_churn_score,
        pred_churn.label AS predictive_churn_label,
        pred_churn.confidence AS predictive_churn_confidence,
        pred_churn.status AS predictive_churn_status,
        pred_churn.output_json AS predictive_churn_output_json,
        pred_churn.created_at::text AS predictive_churn_created_at,
        pred_remarketing.score AS predictive_remarketing_score,
        pred_remarketing.label AS predictive_remarketing_label,
        pred_remarketing.confidence AS predictive_remarketing_confidence,
        pred_remarketing.status AS predictive_remarketing_status,
        pred_remarketing.output_json AS predictive_remarketing_output_json,
        pred_remarketing.created_at::text AS predictive_remarketing_created_at,
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
    LEFT JOIN saas_users au ON au.id = c.assigned_user_id
    LEFT JOIN saas_ai_agents aa ON aa.id = c.assigned_ai_agent_id AND aa.tenant_id = c.tenant_id
    LEFT JOIN LATERAL (
        SELECT score, label, confidence, status, output_json, created_at
        FROM saas_intelligence_predictions p
        WHERE p.tenant_id = c.tenant_id
          AND p.subject_type = 'conversation'
          AND p.subject_id = c.id::text
          AND p.prediction_type = 'lead_scoring'
        ORDER BY p.created_at DESC
        LIMIT 1
    ) pred_lead ON TRUE
    LEFT JOIN LATERAL (
        SELECT score, label, confidence, status, output_json, created_at
        FROM saas_intelligence_predictions p
        WHERE p.tenant_id = c.tenant_id
          AND p.subject_type = 'conversation'
          AND p.subject_id = c.id::text
          AND p.prediction_type = 'churn_prediction'
        ORDER BY p.created_at DESC
        LIMIT 1
    ) pred_churn ON TRUE
    LEFT JOIN LATERAL (
        SELECT score, label, confidence, status, output_json, created_at
        FROM saas_intelligence_predictions p
        WHERE p.tenant_id = c.tenant_id
          AND p.subject_type = 'conversation'
          AND p.subject_id = c.id::text
          AND p.prediction_type = 'smart_remarketing'
        ORDER BY p.created_at DESC
        LIMIT 1
    ) pred_remarketing ON TRUE
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


@router.get("/crm/config")
def crm_config(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        pipeline = _ensure_default_pipeline(conn, ctx.tenant_id, user_id=ctx.user_id)
        field_rows = conn.execute(
            text(
                """
                SELECT
                    id::text,
                    field_key,
                    label,
                    field_type,
                    options_json,
                    is_required,
                    is_active,
                    display_order,
                    created_at::text,
                    updated_at::text
                FROM saas_crm_custom_fields
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                ORDER BY is_active DESC, display_order ASC, label ASC
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().all()
        stages = _pipeline_stages(conn, ctx.tenant_id, pipeline["id"])
    return {
        "tenant_id": ctx.tenant_id,
        "custom_fields": [dict(row) for row in field_rows],
        "pipeline": {**pipeline, "stages": stages},
        "industry_presets": [
            {"code": code, "label": code.replace("_", " ").title(), "stage_count": len(stages)}
            for code, stages in PIPELINE_PRESETS.items()
        ],
    }


@router.post("/crm/custom-fields")
def create_custom_field(
    payload: CrmCustomFieldCreateIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    field_key = _clean_key(payload.field_key)
    if not field_key:
        raise HTTPException(status_code=400, detail="invalid_custom_field_key")
    field_type = _clean_text(payload.field_type, 40).lower() or "text"
    if field_type not in CUSTOM_FIELD_TYPES:
        raise HTTPException(status_code=400, detail="invalid_custom_field_type")
    try:
        with db_session() as conn:
            set_tenant_context(conn, ctx.tenant_id)
            row = conn.execute(
                text(
                    """
                    INSERT INTO saas_crm_custom_fields (
                        tenant_id,
                        field_key,
                        label,
                        field_type,
                        options_json,
                        is_required,
                        display_order,
                        created_by_user_id
                    )
                    VALUES (
                        CAST(:tenant_id AS uuid),
                        :field_key,
                        :label,
                        :field_type,
                        CAST(:options_json AS jsonb),
                        :is_required,
                        :display_order,
                        CAST(NULLIF(:user_id, '') AS uuid)
                    )
                    RETURNING
                        id::text,
                        field_key,
                        label,
                        field_type,
                        options_json,
                        is_required,
                        is_active,
                        display_order,
                        created_at::text,
                        updated_at::text
                    """
                ),
                {
                    "tenant_id": ctx.tenant_id,
                    "field_key": field_key,
                    "label": _clean_text(payload.label, 120),
                    "field_type": field_type,
                    "options_json": json.dumps(_json_list_or_object(payload.options_json)),
                    "is_required": bool(payload.is_required),
                    "display_order": int(payload.display_order),
                    "user_id": ctx.user_id,
                },
            ).mappings().first()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="custom_field_already_exists")
    return {"ok": True, "tenant_id": ctx.tenant_id, "custom_field": dict(row)}


@router.patch("/crm/custom-fields/{field_id}")
def patch_custom_field(
    field_id: str,
    payload: CrmCustomFieldPatchIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    raw = payload.model_dump(exclude_unset=True)
    assignments: list[str] = []
    params: dict[str, Any] = {"tenant_id": ctx.tenant_id, "field_id": field_id}
    if "label" in raw and raw["label"] is not None:
        params["label"] = _clean_text(raw["label"], 120)
        assignments.append("label = :label")
    if "field_type" in raw and raw["field_type"] is not None:
        field_type = _clean_text(raw["field_type"], 40).lower() or "text"
        if field_type not in CUSTOM_FIELD_TYPES:
            raise HTTPException(status_code=400, detail="invalid_custom_field_type")
        params["field_type"] = field_type
        assignments.append("field_type = :field_type")
    if "options_json" in raw:
        params["options_json"] = json.dumps(_json_list_or_object(raw.get("options_json")))
        assignments.append("options_json = CAST(:options_json AS jsonb)")
    if "is_required" in raw and raw["is_required"] is not None:
        params["is_required"] = bool(raw["is_required"])
        assignments.append("is_required = :is_required")
    if "is_active" in raw and raw["is_active"] is not None:
        params["is_active"] = bool(raw["is_active"])
        assignments.append("is_active = :is_active")
    if "display_order" in raw and raw["display_order"] is not None:
        params["display_order"] = int(raw["display_order"])
        assignments.append("display_order = :display_order")
    if not assignments:
        raise HTTPException(status_code=400, detail="custom_field_patch_required")
    assignments.append("updated_at = NOW()")
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        row = conn.execute(
            text(
                f"""
                UPDATE saas_crm_custom_fields
                SET {", ".join(assignments)}
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:field_id AS uuid)
                RETURNING
                    id::text,
                    field_key,
                    label,
                    field_type,
                    options_json,
                    is_required,
                    is_active,
                    display_order,
                    created_at::text,
                    updated_at::text
                """
            ),
            params,
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="custom_field_not_found")
    return {"ok": True, "tenant_id": ctx.tenant_id, "custom_field": dict(row)}


@router.delete("/crm/custom-fields/{field_id}")
def deactivate_custom_field(
    field_id: str,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    return patch_custom_field(field_id, CrmCustomFieldPatchIn(is_active=False), ctx)


@router.get("/crm/pipeline")
def get_crm_pipeline(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        pipeline = _ensure_default_pipeline(conn, ctx.tenant_id, user_id=ctx.user_id)
        stages = _pipeline_stages(conn, ctx.tenant_id, pipeline["id"])
    return {"tenant_id": ctx.tenant_id, "pipeline": {**pipeline, "stages": stages}}


@router.post("/crm/pipeline/presets/{industry_code}")
def apply_pipeline_preset(
    industry_code: str,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    clean_industry = _clean_key(industry_code) or "general"
    if clean_industry not in PIPELINE_PRESETS:
        raise HTTPException(status_code=404, detail="pipeline_preset_not_found")
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        pipeline = _ensure_default_pipeline(conn, ctx.tenant_id, clean_industry, ctx.user_id)
        conn.execute(
            text(
                """
                UPDATE saas_crm_pipelines
                SET industry_code = :industry_code,
                    updated_at = NOW()
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:pipeline_id AS uuid)
                """
            ),
            {"tenant_id": ctx.tenant_id, "pipeline_id": pipeline["id"], "industry_code": clean_industry},
        )
        conn.execute(
            text(
                """
                UPDATE saas_crm_pipeline_stages
                SET is_active = FALSE,
                    updated_at = NOW()
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND pipeline_id = CAST(:pipeline_id AS uuid)
                """
            ),
            {"tenant_id": ctx.tenant_id, "pipeline_id": pipeline["id"]},
        )
        for index, (stage_key, label, probability, is_won, is_lost) in enumerate(_pipeline_preset(clean_industry), start=1):
            conn.execute(
                text(
                    """
                    INSERT INTO saas_crm_pipeline_stages (
                        tenant_id,
                        pipeline_id,
                        stage_key,
                        label,
                        probability,
                        display_order,
                        is_won,
                        is_lost,
                        is_active
                    )
                    VALUES (
                        CAST(:tenant_id AS uuid),
                        CAST(:pipeline_id AS uuid),
                        :stage_key,
                        :label,
                        :probability,
                        :display_order,
                        :is_won,
                        :is_lost,
                        TRUE
                    )
                    ON CONFLICT (tenant_id, pipeline_id, stage_key)
                    DO UPDATE SET
                        label = EXCLUDED.label,
                        probability = EXCLUDED.probability,
                        display_order = EXCLUDED.display_order,
                        is_won = EXCLUDED.is_won,
                        is_lost = EXCLUDED.is_lost,
                        is_active = TRUE,
                        updated_at = NOW()
                    """
                ),
                {
                    "tenant_id": ctx.tenant_id,
                    "pipeline_id": pipeline["id"],
                    "stage_key": stage_key,
                    "label": label,
                    "probability": probability,
                    "display_order": index * 10,
                    "is_won": is_won,
                    "is_lost": is_lost,
                },
            )
        updated = _ensure_default_pipeline(conn, ctx.tenant_id, clean_industry, ctx.user_id)
        stages = _pipeline_stages(conn, ctx.tenant_id, updated["id"])
    return {"ok": True, "tenant_id": ctx.tenant_id, "pipeline": {**updated, "stages": stages}}


@router.post("/crm/pipeline/stages")
def create_pipeline_stage(
    payload: CrmPipelineStageCreateIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    stage_key = _clean_key(payload.stage_key)
    if not stage_key:
        raise HTTPException(status_code=400, detail="invalid_stage_key")
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        pipeline = _ensure_default_pipeline(conn, ctx.tenant_id, user_id=ctx.user_id)
        try:
            row = conn.execute(
                text(
                    """
                    INSERT INTO saas_crm_pipeline_stages (
                        tenant_id,
                        pipeline_id,
                        stage_key,
                        label,
                        probability,
                        display_order,
                        is_won,
                        is_lost
                    )
                    VALUES (
                        CAST(:tenant_id AS uuid),
                        CAST(:pipeline_id AS uuid),
                        :stage_key,
                        :label,
                        :probability,
                        :display_order,
                        :is_won,
                        :is_lost
                    )
                    RETURNING
                        id::text,
                        pipeline_id::text,
                        stage_key,
                        label,
                        probability,
                        display_order,
                        is_won,
                        is_lost,
                        is_active,
                        created_at::text,
                        updated_at::text
                    """
                ),
                {
                    "tenant_id": ctx.tenant_id,
                    "pipeline_id": pipeline["id"],
                    "stage_key": stage_key,
                    "label": _clean_text(payload.label, 120),
                    "probability": int(payload.probability),
                    "display_order": int(payload.display_order),
                    "is_won": bool(payload.is_won),
                    "is_lost": bool(payload.is_lost),
                },
            ).mappings().first()
        except IntegrityError:
            raise HTTPException(status_code=409, detail="pipeline_stage_already_exists")
    return {"ok": True, "tenant_id": ctx.tenant_id, "stage": dict(row)}


@router.patch("/crm/pipeline/stages/{stage_id}")
def patch_pipeline_stage(
    stage_id: str,
    payload: CrmPipelineStagePatchIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    raw = payload.model_dump(exclude_unset=True)
    assignments: list[str] = []
    params: dict[str, Any] = {"tenant_id": ctx.tenant_id, "stage_id": stage_id}
    for key in ("label",):
        if key in raw and raw[key] is not None:
            params[key] = _clean_text(raw[key], 120)
            assignments.append(f"{key} = :{key}")
    for key in ("probability", "display_order"):
        if key in raw and raw[key] is not None:
            params[key] = int(raw[key])
            assignments.append(f"{key} = :{key}")
    for key in ("is_won", "is_lost", "is_active"):
        if key in raw and raw[key] is not None:
            params[key] = bool(raw[key])
            assignments.append(f"{key} = :{key}")
    if not assignments:
        raise HTTPException(status_code=400, detail="pipeline_stage_patch_required")
    assignments.append("updated_at = NOW()")
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        row = conn.execute(
            text(
                f"""
                UPDATE saas_crm_pipeline_stages
                SET {", ".join(assignments)}
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:stage_id AS uuid)
                RETURNING
                    id::text,
                    pipeline_id::text,
                    stage_key,
                    label,
                    probability,
                    display_order,
                    is_won,
                    is_lost,
                    is_active,
                    created_at::text,
                    updated_at::text
                """
            ),
            params,
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="pipeline_stage_not_found")
    return {"ok": True, "tenant_id": ctx.tenant_id, "stage": dict(row)}


@router.delete("/crm/pipeline/stages/{stage_id}")
def deactivate_pipeline_stage(
    stage_id: str,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    return patch_pipeline_stage(stage_id, CrmPipelineStagePatchIn(is_active=False), ctx)


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
                    COUNT(*) FILTER (WHERE payment_status = 'paid')::int AS paid_customers,
                    COUNT(*) FILTER (WHERE sla_due_at IS NOT NULL AND sla_due_at < NOW())::int AS sla_overdue,
                    COUNT(*) FILTER (WHERE lead_score >= 75 OR lead_temperature = 'hot')::int AS hot_leads,
                    COUNT(*) FILTER (WHERE assigned_user_id IS NULL)::int AS unassigned_conversations
                FROM saas_conversations
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().first() or {}

        task_totals = conn.execute(
            text(
                """
                SELECT
                    COUNT(*) FILTER (WHERE status IN ('open', 'in_progress'))::int AS open_tasks,
                    COUNT(*) FILTER (
                        WHERE status IN ('open', 'in_progress')
                          AND due_at IS NOT NULL
                          AND due_at::date <= CURRENT_DATE
                    )::int AS tasks_due_today
                FROM saas_crm_tasks
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

        predictive_rows = conn.execute(
            text(
                """
                SELECT DISTINCT ON (prediction_type)
                    prediction_type,
                    score,
                    label,
                    confidence,
                    status,
                    output_json,
                    created_at::text
                FROM saas_intelligence_predictions
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                ORDER BY prediction_type, created_at DESC
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().all()
        predictive_recommendations = conn.execute(
            text(
                """
                SELECT COUNT(*)::int
                FROM saas_intelligence_recommendations
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND status = 'open'
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).scalar()

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
        "totals": {**dict(totals), **dict(message_totals), **dict(task_totals)},
        "funnel": funnel,
        "payments": [dict(row) for row in payment_rows],
        "channels": [dict(row) for row in channel_rows],
        "activity": [dict(row) for row in activity_rows],
        "recent": [dict(row) for row in recent_rows],
        "predictive": {
            "latest": [dict(row) for row in predictive_rows],
            "open_recommendations": int(predictive_recommendations or 0),
        },
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

    profile_payload = _json_object(raw.get("profile_json"))
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
        "profile_json": json.dumps(profile_payload),
        "last_message_text": "Cliente creado manualmente",
    }

    try:
        with db_session() as conn:
            set_tenant_context(conn, ctx.tenant_id)
            if "custom_fields" in raw and raw.get("custom_fields") is not None:
                custom_values = _sanitize_custom_fields(raw.get("custom_fields"), _active_custom_field_keys(conn, ctx.tenant_id))
                params["profile_json"] = json.dumps(_profile_with_custom_fields(profile_payload, custom_values))
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
            _record_timeline_event(
                conn,
                ctx.tenant_id,
                row["id"],
                "crm_customer_created",
                "Cliente creado manualmente",
                params["display_name"],
                ctx.user_id,
                {"source": "crm_manual"},
            )
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

    custom_fields_payload = data.pop("custom_fields", None)
    profile_json_pending = "profile_json" in data
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
        elif key == "assigned_user_id":
            params[key] = _clean_optional_uuid(value)
            assignments.append("assigned_user_id = CAST(NULLIF(:assigned_user_id, '') AS uuid)")
        elif key == "assigned_ai_agent_id":
            params[key] = _clean_optional_uuid(value)
            assignments.append("assigned_ai_agent_id = CAST(NULLIF(:assigned_ai_agent_id, '') AS uuid)")
            assignments.append("ai_owner_mode = CASE WHEN NULLIF(:assigned_ai_agent_id, '') IS NULL THEN 'general' ELSE 'agent' END")
            assignments.append("ai_owner_locked_at = CASE WHEN NULLIF(:assigned_ai_agent_id, '') IS NULL THEN NULL ELSE NOW() END")
        elif key == "ai_owner_mode":
            mode = _clean_text(value, 40).lower()
            params[key] = mode if mode in {"general", "agent"} else "general"
            assignments.append("ai_owner_mode = :ai_owner_mode")
        elif key in {"sla_due_at", "first_response_due_at"}:
            params[key] = _clean_optional_timestamp(value)
            assignments.append(f"{key} = CAST(NULLIF(:{key}, '') AS timestamp)")
        elif key == "priority":
            params[key] = _normalize_priority(value)
            assignments.append("priority = :priority")
        elif key == "lead_score":
            params[key] = max(0, min(100, int(value or 0)))
            assignments.append("lead_score = :lead_score")
        elif key == "lead_temperature":
            raw_temperature = _clean_text(value, 40).lower()
            params[key] = raw_temperature if raw_temperature in TEMPERATURE_VALUES else _temperature_from_score(int(data.get("lead_score") or 0))
            assignments.append("lead_temperature = :lead_temperature")
        else:
            params[key] = _clean_text(value)
            assignments.append(f"{key} = :{key}")

    if custom_fields_payload is not None and not profile_json_pending:
        assignments.append(
            "profile_json = jsonb_set(COALESCE(profile_json, '{}'::jsonb), '{custom_fields}', "
            "COALESCE(profile_json->'custom_fields', '{}'::jsonb) || CAST(:custom_fields AS jsonb), TRUE)"
        )
        assignments.append("last_profiled_at = NOW()")
    assignments.append("updated_at = NOW()")

    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_ai_assignment_columns(conn)
        if params.get("assigned_ai_agent_id"):
            active_agent = conn.execute(
                text(
                    """
                    SELECT id
                    FROM saas_ai_agents
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND id = CAST(:agent_id AS uuid)
                      AND status = 'active'
                    LIMIT 1
                    """
                ),
                {"tenant_id": ctx.tenant_id, "agent_id": params["assigned_ai_agent_id"]},
            ).mappings().first()
            if not active_agent:
                raise HTTPException(status_code=409, detail={"code": "ai_agent_not_active", "agent_id": params["assigned_ai_agent_id"]})
        if custom_fields_payload is not None:
            custom_values = _sanitize_custom_fields(custom_fields_payload, _active_custom_field_keys(conn, ctx.tenant_id))
            if profile_json_pending:
                params["profile_json"] = json.dumps(_profile_with_custom_fields(json.loads(params["profile_json"]), custom_values))
            else:
                params["custom_fields"] = json.dumps(custom_values)
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

        changed_fields = sorted(set(data.keys()) | ({"custom_fields"} if custom_fields_payload is not None else set()))
        _record_timeline_event(
            conn,
            ctx.tenant_id,
            conversation_id,
            "crm_updated",
            "Ficha CRM actualizada",
            ", ".join(changed_fields),
            ctx.user_id,
            {"fields": changed_fields},
        )

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


@router.get("/customers/{conversation_id}/dedupe-candidates")
def customer_dedupe_candidates(
    conversation_id: str,
    limit: int = Query(8, ge=1, le=25),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        target = conn.execute(
            text(
                """
                SELECT id::text, phone, external_contact_id, display_name, profile_json
                FROM saas_conversations
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:conversation_id AS uuid)
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id, "conversation_id": conversation_id},
        ).mappings().first()
        if not target:
            raise HTTPException(status_code=404, detail="customer_not_found")
        rows = conn.execute(
            text(
                """
                WITH target AS (
                    SELECT phone, external_contact_id, display_name, profile_json
                    FROM saas_conversations
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND id = CAST(:conversation_id AS uuid)
                )
                SELECT
                    c.id::text,
                    c.channel,
                    c.external_contact_id,
                    c.phone,
                    c.display_name,
                    c.crm_stage,
                    c.payment_status,
                    c.last_message_at::text,
                    c.updated_at::text,
                    (
                        CASE WHEN NULLIF(target.phone, '') IS NOT NULL AND c.phone = target.phone THEN 80 ELSE 0 END
                        + CASE WHEN NULLIF(target.external_contact_id, '') IS NOT NULL AND c.external_contact_id = target.external_contact_id THEN 45 ELSE 0 END
                        + CASE WHEN NULLIF(target.display_name, '') IS NOT NULL AND LOWER(c.display_name) = LOWER(target.display_name) THEN 30 ELSE 0 END
                        + CASE
                            WHEN NULLIF(target.profile_json->>'email', '') IS NOT NULL
                             AND LOWER(COALESCE(c.profile_json->>'email', '')) = LOWER(target.profile_json->>'email')
                            THEN 65 ELSE 0
                          END
                    )::int AS match_score,
                    array_remove(ARRAY[
                        CASE WHEN NULLIF(target.phone, '') IS NOT NULL AND c.phone = target.phone THEN 'phone' ELSE NULL END,
                        CASE WHEN NULLIF(target.external_contact_id, '') IS NOT NULL AND c.external_contact_id = target.external_contact_id THEN 'external_contact_id' ELSE NULL END,
                        CASE WHEN NULLIF(target.display_name, '') IS NOT NULL AND LOWER(c.display_name) = LOWER(target.display_name) THEN 'display_name' ELSE NULL END,
                        CASE
                            WHEN NULLIF(target.profile_json->>'email', '') IS NOT NULL
                             AND LOWER(COALESCE(c.profile_json->>'email', '')) = LOWER(target.profile_json->>'email')
                            THEN 'email' ELSE NULL
                          END
                    ], NULL) AS reasons
                FROM saas_conversations c
                CROSS JOIN target
                WHERE c.tenant_id = CAST(:tenant_id AS uuid)
                  AND c.id <> CAST(:conversation_id AS uuid)
                  AND (
                    (NULLIF(target.phone, '') IS NOT NULL AND c.phone = target.phone)
                    OR (NULLIF(target.external_contact_id, '') IS NOT NULL AND c.external_contact_id = target.external_contact_id)
                    OR (NULLIF(target.display_name, '') IS NOT NULL AND LOWER(c.display_name) = LOWER(target.display_name))
                    OR (
                        NULLIF(target.profile_json->>'email', '') IS NOT NULL
                        AND LOWER(COALESCE(c.profile_json->>'email', '')) = LOWER(target.profile_json->>'email')
                    )
                  )
                ORDER BY match_score DESC, c.updated_at DESC
                LIMIT :limit
                """
            ),
            {"tenant_id": ctx.tenant_id, "conversation_id": conversation_id, "limit": limit},
        ).mappings().all()
    return {"tenant_id": ctx.tenant_id, "candidates": [dict(row) for row in rows]}


@router.post("/customers/{target_conversation_id}/merge")
def merge_customer(
    target_conversation_id: str,
    payload: CustomerMergeIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    source_id = _clean_optional_uuid(payload.source_conversation_id)
    target_id = _clean_optional_uuid(target_conversation_id)
    if not source_id or not target_id or source_id == target_id:
        raise HTTPException(status_code=400, detail="invalid_merge_source_target")

    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        rows = conn.execute(
            text(
                f"""
                {CUSTOMER_SELECT}
                WHERE c.tenant_id = CAST(:tenant_id AS uuid)
                  AND c.id IN (CAST(:source_id AS uuid), CAST(:target_id AS uuid))
                """
            ),
            {"tenant_id": ctx.tenant_id, "source_id": source_id, "target_id": target_id},
        ).mappings().all()
        by_id = {str(row["id"]): _customer_row(row) for row in rows}
        source = by_id.get(source_id)
        target = by_id.get(target_id)
        if not source or not target:
            raise HTTPException(status_code=404, detail="merge_customer_not_found")

        source_profile = _json_object(source.get("profile_json"))
        target_profile = _json_object(target.get("profile_json"))
        source_custom = source_profile.get("custom_fields") if isinstance(source_profile.get("custom_fields"), dict) else {}
        target_custom = target_profile.get("custom_fields") if isinstance(target_profile.get("custom_fields"), dict) else {}
        existing_merges = target_profile.get("merged_from") if isinstance(target_profile.get("merged_from"), list) else []
        merged_profile = {**source_profile, **target_profile}
        merged_profile["custom_fields"] = {**source_custom, **target_custom}
        merged_profile["merged_from"] = [
            *existing_merges,
            {
                "conversation_id": source_id,
                "channel": source.get("channel"),
                "external_contact_id": source.get("external_contact_id"),
            },
        ]

        merged_tags = _tags_csv(_normalize_tags([*(_normalize_tags(target.get("tags"))), *(_normalize_tags(source.get("tags")))]))
        target_notes = _clean_text(target.get("notes"), 4000)
        source_notes = _clean_text(source.get("notes"), 4000)
        merged_notes = target_notes
        if source_notes and source_notes.lower() not in target_notes.lower():
            merged_notes = (f"{target_notes}\nMerge {source.get('display_name') or source.get('external_contact_id')}: {source_notes}" if target_notes else source_notes)[:4000]
        lead_score = max(int(target.get("lead_score") or 0), int(source.get("lead_score") or 0))
        lead_temperature = _temperature_from_score(lead_score, target.get("lead_temperature") or source.get("lead_temperature"))

        conn.execute(
            text(
                """
                INSERT INTO saas_crm_merge_events (
                    tenant_id,
                    source_conversation_id,
                    target_conversation_id,
                    merged_by_user_id,
                    reason,
                    source_snapshot_json,
                    target_snapshot_json
                )
                VALUES (
                    CAST(:tenant_id AS uuid),
                    CAST(:source_id AS uuid),
                    CAST(:target_id AS uuid),
                    CAST(NULLIF(:user_id, '') AS uuid),
                    :reason,
                    CAST(:source_snapshot AS jsonb),
                    CAST(:target_snapshot AS jsonb)
                )
                """
            ),
            {
                "tenant_id": ctx.tenant_id,
                "source_id": source_id,
                "target_id": target_id,
                "user_id": ctx.user_id,
                "reason": _clean_text(payload.reason, 500),
                "source_snapshot": json.dumps(source, default=str),
                "target_snapshot": json.dumps(target, default=str),
            },
        )

        conn.execute(
            text(
                """
                UPDATE saas_conversations
                SET
                    phone = COALESCE(NULLIF(phone, ''), :source_phone),
                    display_name = COALESCE(NULLIF(display_name, ''), :source_display_name),
                    first_name = COALESCE(NULLIF(first_name, ''), :source_first_name),
                    last_name = COALESCE(NULLIF(last_name, ''), :source_last_name),
                    city = COALESCE(NULLIF(city, ''), :source_city),
                    customer_type = COALESCE(NULLIF(customer_type, ''), :source_customer_type),
                    interests = COALESCE(NULLIF(interests, ''), :source_interests),
                    payment_status = COALESCE(NULLIF(payment_status, ''), :source_payment_status),
                    payment_reference = COALESCE(NULLIF(payment_reference, ''), :source_payment_reference),
                    crm_stage = COALESCE(NULLIF(crm_stage, ''), :source_crm_stage),
                    intent = COALESCE(NULLIF(intent, ''), :source_intent),
                    assigned_user_id = COALESCE(assigned_user_id, CAST(NULLIF(:source_assigned_user_id, '') AS uuid)),
                    tags = :tags,
                    notes = :notes,
                    lead_score = :lead_score,
                    lead_temperature = :lead_temperature,
                    profile_json = CAST(:profile_json AS jsonb),
                    updated_at = NOW()
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:target_id AS uuid)
                """
            ),
            {
                "tenant_id": ctx.tenant_id,
                "target_id": target_id,
                "source_phone": _clean_text(source.get("phone"), 80),
                "source_display_name": _clean_text(source.get("display_name"), 160),
                "source_first_name": _clean_text(source.get("first_name"), 100),
                "source_last_name": _clean_text(source.get("last_name"), 100),
                "source_city": _clean_text(source.get("city"), 120),
                "source_customer_type": _clean_text(source.get("customer_type"), 80),
                "source_interests": _clean_text(source.get("interests"), 800),
                "source_payment_status": _clean_text(source.get("payment_status"), 80),
                "source_payment_reference": _clean_text(source.get("payment_reference"), 160),
                "source_crm_stage": _clean_text(source.get("crm_stage"), 80),
                "source_intent": _clean_text(source.get("intent"), 120),
                "source_assigned_user_id": _clean_optional_uuid(source.get("assigned_user_id")),
                "tags": merged_tags,
                "notes": merged_notes,
                "lead_score": lead_score,
                "lead_temperature": lead_temperature,
                "profile_json": json.dumps(merged_profile),
            },
        )

        conn.execute(
            text(
                """
                INSERT INTO saas_conversation_labels (tenant_id, conversation_id, label_id)
                SELECT tenant_id, CAST(:target_id AS uuid), label_id
                FROM saas_conversation_labels
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND conversation_id = CAST(:source_id AS uuid)
                ON CONFLICT DO NOTHING
                """
            ),
            {"tenant_id": ctx.tenant_id, "source_id": source_id, "target_id": target_id},
        )
        conn.execute(
            text(
                """
                DELETE FROM saas_conversation_labels
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND conversation_id = CAST(:source_id AS uuid)
                """
            ),
            {"tenant_id": ctx.tenant_id, "source_id": source_id},
        )

        if _table_exists(conn, "saas_conversation_memory"):
            conn.execute(
                text(
                    """
                    INSERT INTO saas_conversation_memory (
                        tenant_id,
                        conversation_id,
                        summary,
                        facts_json,
                        last_message_id
                    )
                    SELECT tenant_id, CAST(:target_id AS uuid), summary, facts_json, last_message_id
                    FROM saas_conversation_memory
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND conversation_id = CAST(:source_id AS uuid)
                    ON CONFLICT (tenant_id, conversation_id)
                    DO UPDATE SET
                        summary = LEFT(TRIM(BOTH E'\n' FROM CONCAT_WS(E'\n', saas_conversation_memory.summary, EXCLUDED.summary)), 5000),
                        facts_json = saas_conversation_memory.facts_json || EXCLUDED.facts_json,
                        last_message_id = COALESCE(EXCLUDED.last_message_id, saas_conversation_memory.last_message_id),
                        updated_at = NOW()
                    """
                ),
                {"tenant_id": ctx.tenant_id, "source_id": source_id, "target_id": target_id},
            )
            conn.execute(
                text(
                    """
                    DELETE FROM saas_conversation_memory
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND conversation_id = CAST(:source_id AS uuid)
                    """
                ),
                {"tenant_id": ctx.tenant_id, "source_id": source_id},
            )

        for table_name, unique_column in (
            ("saas_broadcast_recipients", "broadcast_id"),
            ("saas_remarketing_enrollments", "flow_id"),
        ):
            if _table_exists(conn, table_name):
                conn.execute(
                    text(
                        f"""
                        DELETE FROM {table_name} source_row
                        USING {table_name} target_row
                        WHERE source_row.tenant_id = CAST(:tenant_id AS uuid)
                          AND target_row.tenant_id = CAST(:tenant_id AS uuid)
                          AND source_row.conversation_id = CAST(:source_id AS uuid)
                          AND target_row.conversation_id = CAST(:target_id AS uuid)
                          AND source_row.{unique_column} = target_row.{unique_column}
                        """
                    ),
                    {"tenant_id": ctx.tenant_id, "source_id": source_id, "target_id": target_id},
                )
                _update_conversation_reference(conn, table_name, ctx.tenant_id, source_id, target_id)

        if _table_exists(conn, "saas_ai_pending_replies"):
            conn.execute(
                text(
                    """
                    DELETE FROM saas_ai_pending_replies source_row
                    USING saas_ai_pending_replies target_row
                    WHERE source_row.tenant_id = CAST(:tenant_id AS uuid)
                      AND target_row.tenant_id = CAST(:tenant_id AS uuid)
                      AND source_row.conversation_id = CAST(:source_id AS uuid)
                      AND target_row.conversation_id = CAST(:target_id AS uuid)
                    """
                ),
                {"tenant_id": ctx.tenant_id, "source_id": source_id, "target_id": target_id},
            )
            _update_conversation_reference(conn, "saas_ai_pending_replies", ctx.tenant_id, source_id, target_id)

        moved_counts = {}
        for table_name in (
            "saas_messages",
            "saas_outbound_messages",
            "saas_crm_tasks",
            "saas_message_status_events",
            "saas_trigger_executions",
            "saas_trigger_scheduled_messages",
            "saas_ad_leads",
            "saas_social_comments",
            "saas_ai_runs",
            "saas_crm_timeline_events",
        ):
            moved_counts[table_name] = _update_conversation_reference(conn, table_name, ctx.tenant_id, source_id, target_id)

        latest = conn.execute(
            text(
                """
                SELECT text, created_at
                FROM saas_messages
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND conversation_id = CAST(:target_id AS uuid)
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id, "target_id": target_id},
        ).mappings().first()
        if latest:
            conn.execute(
                text(
                    """
                    UPDATE saas_conversations
                    SET last_message_text = :last_message_text,
                        last_message_at = :last_message_at,
                        updated_at = NOW()
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND id = CAST(:target_id AS uuid)
                    """
                ),
                {
                    "tenant_id": ctx.tenant_id,
                    "target_id": target_id,
                    "last_message_text": _clean_text(latest.get("text"), 1000),
                    "last_message_at": latest.get("created_at"),
                },
            )

        _record_timeline_event(
            conn,
            ctx.tenant_id,
            target_id,
            "crm_merged",
            "Cliente duplicado fusionado",
            source.get("display_name") or source.get("phone") or source.get("external_contact_id") or source_id,
            ctx.user_id,
            {"source_conversation_id": source_id, "moved_counts": moved_counts},
        )

        conn.execute(
            text(
                """
                DELETE FROM saas_conversations
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:source_id AS uuid)
                """
            ),
            {"tenant_id": ctx.tenant_id, "source_id": source_id},
        )

        updated = conn.execute(
            text(
                f"""
                {CUSTOMER_SELECT}
                WHERE c.tenant_id = CAST(:tenant_id AS uuid)
                  AND c.id = CAST(:target_id AS uuid)
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id, "target_id": target_id},
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
    channel: str = Query("", max_length=40),
    queue: str = Query("all", max_length=40),
    agent_id: str = Query("", max_length=80),
    limit: int = Query(100, ge=1, le=500),
    ctx: AuthContext = Depends(get_current_user),
):
    term = str(search or "").strip().lower()
    channel_filter = _clean_text(channel, 40).lower()
    queue_filter = _clean_text(queue, 40).lower() or "all"
    ai_agent_filter = _clean_optional_uuid(agent_id)
    where = ["c.tenant_id = CAST(:tenant_id AS uuid)"]
    params: dict[str, Any] = {"tenant_id": ctx.tenant_id, "limit": limit}
    if term:
        where.append(
            """
            (
                LOWER(c.phone) LIKE :term
                OR LOWER(c.display_name) LIKE :term
                OR LOWER(COALESCE(c.tags, '')) LIKE :term
                OR LOWER(c.external_contact_id) LIKE :term
            )
            """
        )
        params["term"] = f"%{term}%"
    if channel_filter and channel_filter != "all":
        where.append("LOWER(c.channel) = :channel")
        params["channel"] = channel_filter
    if ai_agent_filter:
        where.append("c.assigned_ai_agent_id = CAST(:agent_id AS uuid)")
        params["agent_id"] = ai_agent_filter
    if queue_filter == "unread":
        where.append("c.unread_count > 0")
    elif queue_filter == "mine":
        where.append("c.assigned_user_id = CAST(:user_id AS uuid)")
        params["user_id"] = ctx.user_id
    elif queue_filter == "unassigned":
        where.append("c.assigned_user_id IS NULL")
    elif queue_filter == "sla":
        where.append(
            """
            (
                (c.sla_due_at IS NOT NULL AND c.sla_due_at < NOW())
                OR (c.first_response_due_at IS NOT NULL AND c.first_response_due_at < NOW())
            )
            """
        )
    elif queue_filter == "hot":
        where.append("(c.lead_score >= 75 OR LOWER(c.lead_temperature) = 'hot')")
    elif queue_filter == "churn":
        where.append("((c.last_message_at IS NOT NULL AND c.last_message_at < NOW() - INTERVAL '14 days') OR COALESCE(pred_churn.score, 0) >= 70)")
    elif queue_filter == "human":
        where.append("c.takeover = TRUE")
    elif queue_filter == "ai":
        where.append("c.takeover = FALSE")
    elif queue_filter != "all":
        raise HTTPException(status_code=400, detail="invalid_conversation_queue_filter")

    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_ai_assignment_columns(conn)
        rows = conn.execute(
            text(
                f"""
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
                    c.assigned_user_id::text,
                    au.full_name AS assigned_user_name,
                    au.email AS assigned_user_email,
                    c.assigned_ai_agent_id::text,
                    aa.name AS assigned_ai_agent_name,
                    aa.agent_type AS assigned_ai_agent_type,
                    c.ai_owner_mode,
                    c.ai_owner_locked_at::text,
                    c.priority,
                    c.sla_due_at::text,
                    c.first_response_due_at::text,
                    c.lead_score,
                    c.lead_temperature,
                    c.last_customer_message_at::text,
                    c.last_agent_message_at::text,
                    pred_lead.score AS predictive_lead_score,
                    pred_lead.label AS predictive_lead_label,
                    pred_lead.confidence AS predictive_lead_confidence,
                    pred_lead.status AS predictive_lead_status,
                    pred_lead.output_json AS predictive_lead_output_json,
                    pred_lead.created_at::text AS predictive_lead_created_at,
                    pred_churn.score AS predictive_churn_score,
                    pred_churn.label AS predictive_churn_label,
                    pred_churn.confidence AS predictive_churn_confidence,
                    pred_churn.status AS predictive_churn_status,
                    pred_churn.output_json AS predictive_churn_output_json,
                    pred_churn.created_at::text AS predictive_churn_created_at,
                    pred_remarketing.score AS predictive_remarketing_score,
                    pred_remarketing.label AS predictive_remarketing_label,
                    pred_remarketing.confidence AS predictive_remarketing_confidence,
                    pred_remarketing.status AS predictive_remarketing_status,
                    pred_remarketing.output_json AS predictive_remarketing_output_json,
                    pred_remarketing.created_at::text AS predictive_remarketing_created_at,
                    c.profile_json,
                    c.updated_at::text
                FROM saas_conversations c
                LEFT JOIN saas_users au ON au.id = c.assigned_user_id
                LEFT JOIN saas_ai_agents aa ON aa.id = c.assigned_ai_agent_id AND aa.tenant_id = c.tenant_id
                LEFT JOIN LATERAL (
                    SELECT score, label, confidence, status, output_json, created_at
                    FROM saas_intelligence_predictions p
                    WHERE p.tenant_id = c.tenant_id
                      AND p.subject_type = 'conversation'
                      AND p.subject_id = c.id::text
                      AND p.prediction_type = 'lead_scoring'
                    ORDER BY p.created_at DESC
                    LIMIT 1
                ) pred_lead ON TRUE
                LEFT JOIN LATERAL (
                    SELECT score, label, confidence, status, output_json, created_at
                    FROM saas_intelligence_predictions p
                    WHERE p.tenant_id = c.tenant_id
                      AND p.subject_type = 'conversation'
                      AND p.subject_id = c.id::text
                      AND p.prediction_type = 'churn_prediction'
                    ORDER BY p.created_at DESC
                    LIMIT 1
                ) pred_churn ON TRUE
                LEFT JOIN LATERAL (
                    SELECT score, label, confidence, status, output_json, created_at
                    FROM saas_intelligence_predictions p
                    WHERE p.tenant_id = c.tenant_id
                      AND p.subject_type = 'conversation'
                      AND p.subject_id = c.id::text
                      AND p.prediction_type = 'smart_remarketing'
                    ORDER BY p.created_at DESC
                    LIMIT 1
                ) pred_remarketing ON TRUE
                WHERE {" AND ".join(where)}
                ORDER BY c.updated_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
    return {"tenant_id": ctx.tenant_id, "conversations": [_customer_row(row) for row in rows]}


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


@router.get("/conversations/{conversation_id}/tasks")
def list_conversation_tasks(
    conversation_id: str,
    status: str = Query("", max_length=40),
    ctx: AuthContext = Depends(get_current_user),
):
    status_filter = _clean_text(status, 40).lower()
    where = [
        "tenant_id = CAST(:tenant_id AS uuid)",
        "conversation_id = CAST(:conversation_id AS uuid)",
    ]
    params: dict[str, Any] = {"tenant_id": ctx.tenant_id, "conversation_id": conversation_id}
    if status_filter:
        where.append("status = :status")
        params["status"] = status_filter
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        rows = conn.execute(
            text(
                f"""
                SELECT
                    id::text,
                    conversation_id::text,
                    assigned_user_id::text,
                    title,
                    description,
                    status,
                    priority,
                    due_at::text,
                    completed_at::text,
                    created_at::text,
                    updated_at::text,
                    (due_at IS NOT NULL AND due_at < NOW() AND status IN ('open', 'in_progress')) AS is_overdue
                FROM saas_crm_tasks
                WHERE {" AND ".join(where)}
                ORDER BY
                    CASE WHEN status IN ('open', 'in_progress') THEN 0 ELSE 1 END,
                    due_at NULLS LAST,
                    updated_at DESC
                LIMIT 100
                """
            ),
            params,
        ).mappings().all()
    return {"tenant_id": ctx.tenant_id, "tasks": [_task_row(row) for row in rows]}


@router.get("/crm/tasks")
def list_crm_tasks(
    status: str = Query("open", max_length=40),
    limit: int = Query(80, ge=1, le=250),
    ctx: AuthContext = Depends(get_current_user),
):
    status_filter = _clean_text(status, 40).lower()
    where = ["t.tenant_id = CAST(:tenant_id AS uuid)"]
    params: dict[str, Any] = {"tenant_id": ctx.tenant_id, "limit": limit}
    if status_filter and status_filter != "all":
        if status_filter == "open":
            where.append("t.status IN ('open', 'in_progress')")
        else:
            where.append("t.status = :status")
            params["status"] = status_filter
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        rows = conn.execute(
            text(
                f"""
                SELECT
                    t.id::text,
                    t.conversation_id::text,
                    t.assigned_user_id::text,
                    t.title,
                    t.description,
                    t.status,
                    t.priority,
                    t.due_at::text,
                    t.completed_at::text,
                    t.created_at::text,
                    t.updated_at::text,
                    (t.due_at IS NOT NULL AND t.due_at < NOW() AND t.status IN ('open', 'in_progress')) AS is_overdue,
                    c.display_name,
                    c.phone,
                    c.external_contact_id,
                    c.channel
                FROM saas_crm_tasks t
                JOIN saas_conversations c ON c.id = t.conversation_id
                WHERE {" AND ".join(where)}
                ORDER BY
                    CASE WHEN t.status IN ('open', 'in_progress') THEN 0 ELSE 1 END,
                    t.due_at NULLS LAST,
                    t.updated_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
    return {"tenant_id": ctx.tenant_id, "tasks": [_task_row(row) for row in rows]}


@router.post("/conversations/{conversation_id}/tasks")
def create_conversation_task(
    conversation_id: str,
    payload: CrmTaskCreateIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor", "agent")),
):
    title = _clean_text(payload.title, 180)
    if not title:
        raise HTTPException(status_code=400, detail="task_title_required")
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        exists = conn.execute(
            text(
                """
                SELECT id::text
                FROM saas_conversations
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:conversation_id AS uuid)
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id, "conversation_id": conversation_id},
        ).mappings().first()
        if not exists:
            raise HTTPException(status_code=404, detail="conversation_not_found")
        row = conn.execute(
            text(
                """
                INSERT INTO saas_crm_tasks (
                    tenant_id,
                    conversation_id,
                    assigned_user_id,
                    title,
                    description,
                    priority,
                    due_at,
                    created_by_user_id
                )
                VALUES (
                    CAST(:tenant_id AS uuid),
                    CAST(:conversation_id AS uuid),
                    CAST(NULLIF(:assigned_user_id, '') AS uuid),
                    :title,
                    :description,
                    :priority,
                    CAST(NULLIF(:due_at, '') AS timestamp),
                    CAST(:user_id AS uuid)
                )
                RETURNING
                    id::text,
                    conversation_id::text,
                    assigned_user_id::text,
                    title,
                    description,
                    status,
                    priority,
                    due_at::text,
                    completed_at::text,
                    created_at::text,
                    updated_at::text,
                    false AS is_overdue
                """
            ),
            {
                "tenant_id": ctx.tenant_id,
                "conversation_id": conversation_id,
                "assigned_user_id": _clean_optional_uuid(payload.assigned_user_id),
                "title": title,
                "description": _clean_text(payload.description, 1200),
                "priority": _normalize_priority(payload.priority),
                "due_at": _clean_optional_timestamp(payload.due_at),
                "user_id": ctx.user_id,
            },
        ).mappings().first()
        _record_timeline_event(
            conn,
            ctx.tenant_id,
            conversation_id,
            "crm_task_created",
            "Tarea CRM creada",
            title,
            ctx.user_id,
            {"task_id": row["id"], "priority": row["priority"], "due_at": row["due_at"]},
        )
    return {"ok": True, "tenant_id": ctx.tenant_id, "task": _task_row(row)}


@router.patch("/crm/tasks/{task_id}")
def patch_crm_task(
    task_id: str,
    payload: CrmTaskPatchIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor", "agent")),
):
    raw = payload.model_dump(exclude_unset=True)
    assignments: list[str] = []
    params: dict[str, Any] = {"tenant_id": ctx.tenant_id, "task_id": task_id}
    if "title" in raw and raw["title"] is not None:
        params["title"] = _clean_text(raw["title"], 180)
        assignments.append("title = :title")
    if "description" in raw and raw["description"] is not None:
        params["description"] = _clean_text(raw["description"], 1200)
        assignments.append("description = :description")
    if "assigned_user_id" in raw:
        params["assigned_user_id"] = _clean_optional_uuid(raw.get("assigned_user_id"))
        assignments.append("assigned_user_id = CAST(NULLIF(:assigned_user_id, '') AS uuid)")
    if "priority" in raw and raw["priority"] is not None:
        params["priority"] = _normalize_priority(raw["priority"])
        assignments.append("priority = :priority")
    if "due_at" in raw:
        params["due_at"] = _clean_optional_timestamp(raw.get("due_at"))
        assignments.append("due_at = CAST(NULLIF(:due_at, '') AS timestamp)")
    if "status" in raw and raw["status"] is not None:
        status = _clean_text(raw["status"], 40).lower()
        if status not in TASK_STATUS_VALUES:
            raise HTTPException(status_code=400, detail="invalid_task_status")
        params["status"] = status
        assignments.append("status = :status")
        assignments.append("completed_at = CASE WHEN :status = 'done' THEN NOW() ELSE NULL END")
    if not assignments:
        raise HTTPException(status_code=400, detail="task_patch_required")
    assignments.append("updated_at = NOW()")
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        row = conn.execute(
            text(
                f"""
                UPDATE saas_crm_tasks
                SET {", ".join(assignments)}
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:task_id AS uuid)
                RETURNING
                    id::text,
                    conversation_id::text,
                    assigned_user_id::text,
                    title,
                    description,
                    status,
                    priority,
                    due_at::text,
                    completed_at::text,
                    created_at::text,
                    updated_at::text,
                    (due_at IS NOT NULL AND due_at < NOW() AND status IN ('open', 'in_progress')) AS is_overdue
                """
            ),
            params,
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="task_not_found")
        _record_timeline_event(
            conn,
            ctx.tenant_id,
            row["conversation_id"],
            "crm_task_updated",
            "Tarea CRM actualizada",
            row["title"],
            ctx.user_id,
            {"task_id": row["id"], "status": row["status"], "priority": row["priority"]},
        )
    return {"ok": True, "tenant_id": ctx.tenant_id, "task": _task_row(row)}


@router.post("/conversations/{conversation_id}/score")
def recompute_conversation_score(
    conversation_id: str,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor", "agent")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        current = conn.execute(
            text(
                """
                SELECT
                    id::text,
                    crm_stage,
                    payment_status,
                    tags,
                    interests,
                    last_message_text,
                    unread_count,
                    lead_temperature
                FROM saas_conversations
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:conversation_id AS uuid)
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id, "conversation_id": conversation_id},
        ).mappings().first()
        if not current:
            raise HTTPException(status_code=404, detail="conversation_not_found")
        score, temperature = _infer_lead_score(dict(current))
        conn.execute(
            text(
                """
                UPDATE saas_conversations
                SET lead_score = :lead_score,
                    lead_temperature = :lead_temperature,
                    updated_at = NOW()
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:conversation_id AS uuid)
                """
            ),
            {
                "tenant_id": ctx.tenant_id,
                "conversation_id": conversation_id,
                "lead_score": score,
                "lead_temperature": temperature,
            },
        )
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


@router.get("/conversations/{conversation_id}/status-events")
def list_conversation_status_events(
    conversation_id: str,
    limit: int = Query(50, ge=1, le=200),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        rows = conn.execute(
            text(
                """
                SELECT
                    id::text,
                    conversation_id::text,
                    message_id::text,
                    provider_message_id,
                    status,
                    error,
                    payload_json,
                    occurred_at::text,
                    created_at::text
                FROM saas_message_status_events
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND conversation_id = CAST(:conversation_id AS uuid)
                ORDER BY occurred_at DESC, created_at DESC
                LIMIT :limit
                """
            ),
            {"tenant_id": ctx.tenant_id, "conversation_id": conversation_id, "limit": limit},
        ).mappings().all()
    return {"tenant_id": ctx.tenant_id, "events": [dict(row) for row in rows]}


@router.get("/conversations/{conversation_id}/timeline")
def list_conversation_timeline(
    conversation_id: str,
    limit: int = Query(80, ge=1, le=250),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        exists = conn.execute(
            text(
                """
                SELECT id::text
                FROM saas_conversations
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:conversation_id AS uuid)
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id, "conversation_id": conversation_id},
        ).mappings().first()
        if not exists:
            raise HTTPException(status_code=404, detail="conversation_not_found")
        rows = conn.execute(
            text(
                """
                WITH timeline AS (
                    SELECT
                        m.id::text AS id,
                        'message' AS event_type,
                        CASE WHEN m.direction = 'in' THEN 'Mensaje recibido' ELSE 'Mensaje enviado' END AS title,
                        LEFT(COALESCE(NULLIF(m.text, ''), '[' || m.msg_type || ']'), 600) AS description,
                        jsonb_build_object(
                            'direction', m.direction,
                            'msg_type', m.msg_type,
                            'channel', m.channel,
                            'external_message_id', m.external_message_id
                        ) AS metadata_json,
                        m.created_at AS occurred_at,
                        m.created_at AS created_at
                    FROM saas_messages m
                    WHERE m.tenant_id = CAST(:tenant_id AS uuid)
                      AND m.conversation_id = CAST(:conversation_id AS uuid)

                    UNION ALL

                    SELECT
                        t.id::text AS id,
                        'task' AS event_type,
                        'Tarea CRM: ' || t.title AS title,
                        COALESCE(NULLIF(t.description, ''), t.status) AS description,
                        jsonb_build_object(
                            'status', t.status,
                            'priority', t.priority,
                            'due_at', t.due_at::text,
                            'completed_at', t.completed_at::text
                        ) AS metadata_json,
                        COALESCE(t.completed_at, t.due_at, t.created_at) AS occurred_at,
                        t.created_at AS created_at
                    FROM saas_crm_tasks t
                    WHERE t.tenant_id = CAST(:tenant_id AS uuid)
                      AND t.conversation_id = CAST(:conversation_id AS uuid)

                    UNION ALL

                    SELECT
                        e.id::text AS id,
                        'message_status' AS event_type,
                        'Estado de mensaje: ' || e.status AS title,
                        e.error AS description,
                        jsonb_build_object(
                            'message_id', e.message_id::text,
                            'provider_message_id', e.provider_message_id,
                            'payload_json', e.payload_json
                        ) AS metadata_json,
                        e.occurred_at AS occurred_at,
                        e.created_at AS created_at
                    FROM saas_message_status_events e
                    WHERE e.tenant_id = CAST(:tenant_id AS uuid)
                      AND e.conversation_id = CAST(:conversation_id AS uuid)

                    UNION ALL

                    SELECT
                        te.id::text AS id,
                        te.event_type,
                        te.title,
                        te.description,
                        te.metadata_json,
                        te.occurred_at,
                        te.created_at
                    FROM saas_crm_timeline_events te
                    WHERE te.tenant_id = CAST(:tenant_id AS uuid)
                      AND te.conversation_id = CAST(:conversation_id AS uuid)
                )
                SELECT
                    id,
                    event_type,
                    title,
                    description,
                    metadata_json,
                    occurred_at::text,
                    created_at::text
                FROM timeline
                ORDER BY occurred_at DESC, created_at DESC
                LIMIT :limit
                """
            ),
            {"tenant_id": ctx.tenant_id, "conversation_id": conversation_id, "limit": limit},
        ).mappings().all()
    return {"tenant_id": ctx.tenant_id, "events": [dict(row) for row in rows]}


@router.post("/conversations/{conversation_id}/messages")
def send_message(
    conversation_id: str,
    payload: SendMessageIn,
    request: Request,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor", "agent")),
):
    incoming_payload = payload.payload_json if isinstance(payload.payload_json, dict) else {}
    product_card = _safe_product_card(incoming_payload.get("product_card") or incoming_payload.get("product") or {})
    note_text = _clean_text(incoming_payload.get("message_note"), 900)
    body_text = payload.text.strip()
    requested_media_id = payload.media_id.strip()
    requested_type = payload.msg_type.strip().lower() or ("file" if requested_media_id else "text")
    allowed_types = {"text", "image", "video", "audio", "document", "file", "product"}
    if requested_type not in allowed_types:
        raise HTTPException(status_code=400, detail="unsupported_message_type")
    if requested_type == "product" and product_card:
        body_text = body_text or _product_caption(product_card, note_text)
    if not body_text and not requested_media_id and not product_card:
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
        if product_card:
            message_payload.update({
                "product_card": product_card,
                "message_note": note_text,
                "cta_url": product_card.get("permalink") or "",
                "cta_text": "Ver producto",
            })
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
                    created_at::text,
                    payload_json
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
                    **({
                        "product_card": product_card,
                        "message_note": note_text,
                        "cta_url": product_card.get("permalink") or "",
                        "cta_text": "Ver producto",
                    } if product_card else {}),
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
                    last_agent_message_at = NOW(),
                    sla_due_at = NULL,
                    first_response_due_at = NULL,
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
                INSERT INTO saas_message_status_events (
                    tenant_id,
                    conversation_id,
                    message_id,
                    provider_message_id,
                    status,
                    payload_json
                )
                VALUES (
                    CAST(:tenant_id AS uuid),
                    CAST(:conversation_id AS uuid),
                    CAST(:message_id AS uuid),
                    :provider_message_id,
                    'queued',
                    CAST(:payload_json AS jsonb)
                )
                """
            ),
            {
                "tenant_id": ctx.tenant_id,
                "conversation_id": conversation_id,
                "message_id": message["id"],
                "provider_message_id": local_external_id,
                "payload_json": json.dumps({"source": "saas_console"}),
            },
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
        record_inline_event(
            conn,
            ctx.tenant_id,
            event_type="message.sent",
            source="saas_messages",
            channel=channel,
            entity_type="message",
            entity_id=message["id"],
            conversation_id=conversation_id,
            customer_key=str(conversation["external_contact_id"] or conversation["phone"] or ""),
            occurred_at=message["created_at"],
            payload_json={
                "direction": "out",
                "msg_type": message_type,
                "external_message_id": local_external_id,
                "has_media": bool(media_id),
                "mime_type": mime_type,
                "text_preview": last_preview[:280],
                "outbound_id": outbound["id"],
                "actor_user_id": ctx.user_id,
                "dispatch_status": "queued",
            },
            correlation_id=str(getattr(request.state, "correlation_id", "") or "")[:120],
            replay_key=f"message:{message['id']}",
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


@router.patch("/conversations/{conversation_id}/ai-agent")
def set_conversation_ai_agent(
    conversation_id: str,
    agent_id: str = Query("", max_length=80),
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor", "agent")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_ai_assignment_columns(conn)
        assignment = assign_conversation_ai_agent(
            conn,
            ctx.tenant_id,
            conversation_id,
            _clean_optional_uuid(agent_id),
            source="manual",
            user_id=ctx.user_id,
        )
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
        return {"ok": True, "assignment": assignment, "customer": _customer_row(updated or {})}
