from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import csv
import io
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import text

from app_saas.billing.limits import ensure_broadcast_quota, ensure_feature_enabled, ensure_monthly_message_quota
from app_saas.broadcasts.schemas import (
    BroadcastCreateIn,
    BroadcastEnqueueIn,
    BroadcastPatchIn,
    BroadcastPreviewIn,
    MetaTemplateCreateIn,
    MetaTemplatePatchIn,
)
from app_saas.db import db_session, set_tenant_context
from app_saas.shared.secrets import decrypt_secret
from app_saas.shared.security import AuthContext, get_current_user, require_role
from app_saas.workers.dispatch import process_due_outbound_messages

router = APIRouter(prefix="/broadcasts", tags=["saas-broadcasts"])


def _period_yyyymm() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m")


def _clean_text(value: object, max_len: int = 4000) -> str:
    return str(value or "").strip()[:max_len]


def _clean_channel(value: object) -> str:
    return _clean_text(value, 40).lower() or "whatsapp"


def _clean_id(value: object) -> str:
    return _clean_text(value, 80)


def _ensure_broadcast(conn, tenant_id: str) -> None:
    ensure_feature_enabled(conn, tenant_id, "broadcast")


def _normalize_meta_template_name(raw_name: object) -> str:
    name = _clean_text(raw_name, 200).lower()
    name = re.sub(r"[^a-z0-9_]+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name[:200]


def _integration_config(integration: dict[str, Any] | None) -> dict[str, Any]:
    if not integration:
        return {}
    raw = integration.get("config_json") or {}
    return raw if isinstance(raw, dict) else {}


def _load_meta_integration(conn, tenant_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            """
            SELECT provider, channel, status, secret_ref, config_json
            FROM saas_integrations
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND channel = 'whatsapp'
              AND status = 'connected'
              AND provider IN ('meta', 'whatsapp', 'whatsapp_cloud')
            ORDER BY
                CASE WHEN provider = 'meta' THEN 0 ELSE 1 END,
                updated_at DESC
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    return dict(row) if row else None


def _secret_from_integration(config: dict[str, Any], integration: dict[str, Any] | None) -> str:
    inline_token = _clean_text(decrypt_secret(config.get("access_token") or config.get("token")), 2000)
    if inline_token:
        return inline_token
    env_name = _clean_text(config.get("access_token_env"), 120)
    secret_ref = _clean_text((integration or {}).get("secret_ref"), 200)
    if not env_name and secret_ref.lower().startswith("env:"):
        env_name = secret_ref.split(":", 1)[1].strip()
    if env_name:
        return _clean_text(os.getenv(env_name), 2000)
    return ""


def _meta_access_token(integration: dict[str, Any] | None = None) -> str:
    config = _integration_config(integration)
    return (
        _secret_from_integration(config, integration)
        or os.getenv("SCENTRA_META_ACCESS_TOKEN")
        or os.getenv("SCENTRA_WHATSAPP_ACCESS_TOKEN")
        or os.getenv("WHATSAPP_PERMANENT_TOKEN")
        or os.getenv("WHATSAPP_TOKEN")
        or os.getenv("META_ACCESS_TOKEN")
        or ""
    ).strip()


def _meta_waba_id(integration: dict[str, Any] | None = None) -> str:
    config = _integration_config(integration)
    return (
        _clean_text(
            config.get("waba_id")
            or config.get("whatsapp_business_account_id")
            or config.get("business_account_id"),
            120,
        )
        or os.getenv("SCENTRA_WHATSAPP_BUSINESS_ACCOUNT_ID")
        or os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID")
        or os.getenv("WABA_ID")
        or ""
    ).strip()


def _meta_graph_version(integration: dict[str, Any] | None = None) -> str:
    config = _integration_config(integration)
    version = (
        _clean_text(config.get("graph_api_version") or config.get("graph_version"), 20)
        or os.getenv("SCENTRA_META_GRAPH_VERSION")
        or os.getenv("META_GRAPH_VERSION")
        or "v22.0"
    ).strip() or "v22.0"
    return version if version.startswith("v") else f"v{version}"


def _extract_meta_template_body(components: Any) -> str:
    for comp in components if isinstance(components, list) else []:
        if isinstance(comp, dict) and str(comp.get("type") or "").upper() == "BODY":
            return _clean_text(comp.get("text"), 1024)
    return ""


def _meta_sample_for_token(token: str) -> str:
    catalog = {
        "customer_name": "Juan Perez",
        "customer_first_name": "Juan",
        "customer_phone": "+573001112233",
        "customer_email": "juan@email.com",
        "customer_city": "Bogota",
        "business_name": "Scentra +AI",
        "assistant_name": "Laura",
        "campaign_name": "Promo mayo",
    }
    key = str(token or "").strip().lower().replace("-", "_")
    if key in catalog:
        return catalog[key]
    if key.isdigit():
        return "Juan" if key == "1" else "valor"
    return "valor"


def _normalize_meta_placeholders(raw_text: str) -> tuple[str, list[str]]:
    tokens: dict[str, int] = {}
    examples: list[str] = []

    def repl(match: re.Match[str]) -> str:
        token = str(match.group(1) or "").strip()
        if not token:
            return match.group(0)
        if token not in tokens:
            tokens[token] = len(tokens) + 1
            examples.append(_meta_sample_for_token(token))
        return f"{{{{{tokens[token]}}}}}"

    normalized = re.sub(r"\{\{\s*([^{}]+?)\s*\}\}", repl, str(raw_text or ""))
    return normalized, examples


def _build_meta_components(payload: MetaTemplateCreateIn) -> list[dict[str, Any]]:
    body_text, body_examples = _normalize_meta_placeholders(payload.body_text)
    body_text = _clean_text(body_text, 1024)
    if not body_text:
        raise HTTPException(status_code=400, detail="meta_template_body_required")
    components: list[dict[str, Any]] = [{"type": "BODY", "text": body_text}]
    if body_examples:
        components[0]["example"] = {"body_text": [body_examples]}

    header_type = _clean_text(payload.header_type, 40).upper()
    if header_type and header_type not in {"TEXT", "IMAGE", "VIDEO", "DOCUMENT"}:
        raise HTTPException(status_code=400, detail="invalid_header_type")
    if header_type == "TEXT":
        header_text, header_examples = _normalize_meta_placeholders(payload.header_text)
        header_text = _clean_text(header_text, 60)
        if not header_text:
            raise HTTPException(status_code=400, detail="header_text_required")
        comp: dict[str, Any] = {"type": "HEADER", "format": "TEXT", "text": header_text}
        if header_examples:
            comp["example"] = {"header_text": header_examples}
        components.append(comp)
    elif header_type in {"IMAGE", "VIDEO", "DOCUMENT"}:
        handle = _clean_text(payload.header_media_handle, 500)
        if not handle:
            raise HTTPException(status_code=400, detail="header_media_handle_required")
        components.append({"type": "HEADER", "format": header_type, "example": {"header_handle": [handle]}})

    footer = _clean_text(payload.footer_text, 60)
    if footer:
        components.append({"type": "FOOTER", "text": footer})

    buttons: list[dict[str, Any]] = []
    for btn in (payload.buttons or [])[:3]:
        btn_type = _clean_text(btn.type, 40).upper() or "QUICK_REPLY"
        text_value = _clean_text(btn.text, 25)
        if not text_value:
            continue
        if btn_type == "URL":
            url = _clean_text(btn.url, 2000)
            if url:
                buttons.append({"type": "URL", "text": text_value, "url": url})
        elif btn_type == "PHONE_NUMBER":
            phone = _clean_text(btn.phone_number, 80)
            if phone:
                buttons.append({"type": "PHONE_NUMBER", "text": text_value, "phone_number": phone})
        else:
            buttons.append({"type": "QUICK_REPLY", "text": text_value})
    if buttons:
        components.append({"type": "BUTTONS", "buttons": buttons})
    return components


def _map_meta_row(row: dict[str, Any]) -> dict[str, Any]:
    components = row.get("components") if isinstance(row.get("components"), list) else []
    quality = row.get("quality_score")
    quality_value = ""
    if isinstance(quality, dict):
        quality_value = _clean_text(quality.get("score") or quality.get("quality_score"), 80)
    elif quality:
        quality_value = _clean_text(quality, 80)
    return {
        "provider": "meta",
        "meta_template_id": _clean_text(row.get("id"), 240),
        "name": _normalize_meta_template_name(row.get("name")),
        "language": _clean_text(row.get("language"), 20) or "es",
        "category": _clean_text(row.get("category"), 40).upper() or "MARKETING",
        "status": _clean_text(row.get("status"), 40).lower() or "pending",
        "quality_score": quality_value,
        "body_text": _extract_meta_template_body(components),
        "components_json": components,
        "provider_response_json": row,
    }


def _meta_template_select() -> str:
    return """
        SELECT
            id::text,
            provider,
            meta_template_id,
            name,
            language,
            category,
            status,
            quality_score,
            header_type,
            header_text,
            header_media_handle,
            body_text,
            footer_text,
            buttons_json,
            components_json,
            allow_category_change,
            provider_response_json,
            rejection_reason,
            submitted_at::text,
            approved_at::text,
            rejected_at::text,
            last_sync_at::text,
            created_at::text,
            updated_at::text
        FROM saas_meta_message_templates
    """


def _upsert_meta_template(conn, tenant_id: str, data: dict[str, Any], user_id: str | None = None) -> dict:
    status = _clean_text(data.get("status"), 40).lower() or "pending"
    row = conn.execute(
        text(
            """
            INSERT INTO saas_meta_message_templates (
                tenant_id, provider, meta_template_id, name, language, category, status, quality_score,
                header_type, header_text, header_media_handle, body_text, footer_text, buttons_json,
                components_json, allow_category_change, provider_response_json, rejection_reason,
                submitted_at, approved_at, rejected_at, last_sync_at, created_by_user_id
            )
            VALUES (
                CAST(:tenant_id AS uuid), :provider, :meta_template_id, :name, :language, :category, :status, :quality_score,
                :header_type, :header_text, :header_media_handle, :body_text, :footer_text, CAST(:buttons_json AS jsonb),
                CAST(:components_json AS jsonb), :allow_category_change, CAST(:provider_response_json AS jsonb), :rejection_reason,
                CASE WHEN :submitted THEN NOW() ELSE NULL END,
                CASE WHEN :approved THEN NOW() ELSE NULL END,
                CASE WHEN :rejected THEN NOW() ELSE NULL END,
                NOW(),
                CAST(NULLIF(:user_id, '') AS uuid)
            )
            ON CONFLICT (tenant_id, provider, name, language)
            DO UPDATE SET
                meta_template_id = COALESCE(NULLIF(EXCLUDED.meta_template_id, ''), saas_meta_message_templates.meta_template_id),
                category = EXCLUDED.category,
                status = EXCLUDED.status,
                quality_score = EXCLUDED.quality_score,
                header_type = COALESCE(NULLIF(EXCLUDED.header_type, ''), saas_meta_message_templates.header_type),
                header_text = COALESCE(NULLIF(EXCLUDED.header_text, ''), saas_meta_message_templates.header_text),
                header_media_handle = COALESCE(NULLIF(EXCLUDED.header_media_handle, ''), saas_meta_message_templates.header_media_handle),
                body_text = COALESCE(NULLIF(EXCLUDED.body_text, ''), saas_meta_message_templates.body_text),
                footer_text = COALESCE(NULLIF(EXCLUDED.footer_text, ''), saas_meta_message_templates.footer_text),
                buttons_json = CASE WHEN EXCLUDED.buttons_json = '[]'::jsonb THEN saas_meta_message_templates.buttons_json ELSE EXCLUDED.buttons_json END,
                components_json = CASE WHEN EXCLUDED.components_json = '[]'::jsonb THEN saas_meta_message_templates.components_json ELSE EXCLUDED.components_json END,
                provider_response_json = saas_meta_message_templates.provider_response_json || EXCLUDED.provider_response_json,
                rejection_reason = EXCLUDED.rejection_reason,
                submitted_at = COALESCE(saas_meta_message_templates.submitted_at, EXCLUDED.submitted_at),
                approved_at = CASE WHEN EXCLUDED.status = 'approved' THEN COALESCE(saas_meta_message_templates.approved_at, NOW()) ELSE saas_meta_message_templates.approved_at END,
                rejected_at = CASE WHEN EXCLUDED.status = 'rejected' THEN COALESCE(saas_meta_message_templates.rejected_at, NOW()) ELSE saas_meta_message_templates.rejected_at END,
                last_sync_at = NOW(),
                updated_at = NOW()
            RETURNING id::text, provider, meta_template_id, name, language, category, status, quality_score,
                      header_type, header_text, header_media_handle, body_text, footer_text, buttons_json,
                      components_json, allow_category_change, provider_response_json, rejection_reason,
                      submitted_at::text, approved_at::text, rejected_at::text, last_sync_at::text,
                      created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "user_id": user_id or "",
            "provider": _clean_text(data.get("provider"), 40).lower() or "meta",
            "meta_template_id": _clean_text(data.get("meta_template_id"), 240),
            "name": _normalize_meta_template_name(data.get("name")),
            "language": _clean_text(data.get("language"), 20) or "es",
            "category": _clean_text(data.get("category"), 40).upper() or "MARKETING",
            "status": status,
            "quality_score": _clean_text(data.get("quality_score"), 80),
            "header_type": _clean_text(data.get("header_type"), 40).upper(),
            "header_text": _clean_text(data.get("header_text"), 60),
            "header_media_handle": _clean_text(data.get("header_media_handle"), 500),
            "body_text": _clean_text(data.get("body_text"), 1024),
            "footer_text": _clean_text(data.get("footer_text"), 60),
            "buttons_json": json.dumps(data.get("buttons_json") or [], ensure_ascii=False),
            "components_json": json.dumps(data.get("components_json") or [], ensure_ascii=False),
            "allow_category_change": bool(data.get("allow_category_change", True)),
            "provider_response_json": json.dumps(data.get("provider_response_json") or {}, ensure_ascii=False),
            "rejection_reason": _clean_text(data.get("rejection_reason"), 1000),
            "submitted": status in {"pending", "approved", "rejected"},
            "approved": status == "approved",
            "rejected": status == "rejected",
        },
    ).mappings().first()
    return dict(row)


def _fetch_meta_templates_from_graph(limit: int, integration: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    token = _meta_access_token(integration)
    waba_id = _meta_waba_id(integration)
    if not token or not waba_id:
        return [], {"mode": "local", "detail": "meta_token_or_waba_missing"}
    graph_version = _meta_graph_version(integration)
    query = urllib.parse.urlencode({"limit": max(1, min(int(limit or 200), 500)), "access_token": token})
    url = f"https://graph.facebook.com/{graph_version}/{urllib.parse.quote(waba_id)}/message_templates?{query}"
    try:
        with urllib.request.urlopen(url, timeout=25) as response:
            payload = json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise HTTPException(status_code=400, detail=f"meta_sync_failed: {body[:700]}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"meta_sync_failed: {str(exc)[:300]}")
    rows = payload.get("data") if isinstance(payload, dict) else []
    return [row for row in rows if isinstance(row, dict)], {"mode": "graph", "waba_id": waba_id, "graph_version": graph_version}


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

    takeover = _clean_text(filters.get("takeover"), 20).lower()
    if takeover in ("on", "true", "human"):
        where.append("takeover = TRUE")
    elif takeover in ("off", "false", "ai"):
        where.append("takeover = FALSE")

    return where


def _load_segment_filters(conn, tenant_id: str, segment_id: str | None) -> dict[str, Any]:
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


def _load_template_body(conn, tenant_id: str, template_id: str | None) -> str:
    if not template_id:
        return ""
    row = conn.execute(
        text(
            """
            SELECT body
            FROM saas_message_templates
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:template_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "template_id": template_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="template_not_found")
    return str(row["body"] or "")


def _load_meta_template(conn, tenant_id: str, meta_template_id: str | None) -> dict[str, Any] | None:
    if not meta_template_id:
        return None
    row = conn.execute(
        text(
            f"""
            {_meta_template_select()}
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:meta_template_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "meta_template_id": meta_template_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="meta_template_not_found")
    return dict(row)


def _conversation_rows(conn, tenant_id: str, filters: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"tenant_id": tenant_id, "limit": int(limit)}
    where = _segment_where(filters, params)
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
                tags,
                payment_status,
                crm_stage,
                intent
            FROM saas_conversations
            WHERE {" AND ".join(where)}
              AND COALESCE(NULLIF(phone, ''), NULLIF(external_contact_id, '')) IS NOT NULL
            ORDER BY updated_at DESC
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()
    return [dict(row) for row in rows]


def _count_conversations(conn, tenant_id: str, filters: dict[str, Any]) -> int:
    params: dict[str, Any] = {"tenant_id": tenant_id}
    where = _segment_where(filters, params)
    return int(
        conn.execute(
            text(
                f"""
                SELECT COUNT(*)
                FROM saas_conversations
                WHERE {" AND ".join(where)}
                  AND COALESCE(NULLIF(phone, ''), NULLIF(external_contact_id, '')) IS NOT NULL
                """
            ),
            params,
        ).scalar_one()
        or 0
    )


def _variables(row: dict[str, Any]) -> dict[str, str]:
    full_name = _clean_text(row.get("display_name")) or f"{_clean_text(row.get('first_name'))} {_clean_text(row.get('last_name'))}".strip()
    phone = _clean_text(row.get("phone")) or _clean_text(row.get("external_contact_id"))
    return {
        "nombre": full_name or phone,
        "customer_name": full_name or phone,
        "first_name": _clean_text(row.get("first_name")),
        "last_name": _clean_text(row.get("last_name")),
        "phone": phone,
        "customer_phone": phone,
        "city": _clean_text(row.get("city")),
        "customer_type": _clean_text(row.get("customer_type")),
        "interests": _clean_text(row.get("interests")),
        "tags": _clean_text(row.get("tags")),
        "payment_status": _clean_text(row.get("payment_status")),
        "crm_stage": _clean_text(row.get("crm_stage")),
        "intent": _clean_text(row.get("intent")),
        "business_name": "Scentra +AI",
        "assistant_name": "Asesor IA",
    }


def _extract_template_tokens(text_value: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for match in re.finditer(r"\{\{\s*([^{}]+?)\s*\}\}", str(text_value or "")):
        token = str(match.group(1) or "").strip()
        if token and token not in seen:
            seen.add(token)
            out.append(token)
    return out


def _value_for_token(token: str, row: dict[str, Any]) -> str:
    values = _variables(row)
    key = str(token or "").strip()
    if key in values:
        return values.get(key, "")
    numeric_defaults = {
        "1": "customer_name",
        "2": "customer_phone",
        "3": "city",
        "4": "business_name",
        "5": "assistant_name",
    }
    mapped = numeric_defaults.get(key)
    if mapped:
        return values.get(mapped, "")
    return f"{{{{{key}}}}}" if key else ""


def _render_body(body: str, row: dict[str, Any]) -> str:
    def repl(match: re.Match[str]) -> str:
        key = str(match.group(1) or "").strip()
        return _value_for_token(key, row) or match.group(0)

    return re.sub(r"\{\{\s*([a-zA-Z0-9_-]+)\s*\}\}", repl, body).strip()


def _template_body_parameters(body: str, row: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"type": "text", "text": _value_for_token(token, row)}
        for token in _extract_template_tokens(body)
    ]


def _broadcast_select() -> str:
    return """
        SELECT
            b.id::text,
            b.name,
            b.channel,
            b.template_id::text,
            b.meta_template_id::text,
            b.meta_template_name,
            b.meta_template_language,
            b.meta_template_category,
            b.meta_template_body,
            b.segment_id::text,
            b.body,
            b.status,
            b.scheduled_at::text,
            b.audience_count,
            b.queued_count,
            b.sent_count,
            b.failed_count,
            b.metrics_json,
            b.created_at::text,
            b.updated_at::text,
            t.name AS template_name,
            s.name AS segment_name
        FROM saas_broadcasts b
        LEFT JOIN saas_message_templates t ON t.id = b.template_id
        LEFT JOIN saas_meta_message_templates mt ON mt.id = b.meta_template_id
        LEFT JOIN saas_segments s ON s.id = b.segment_id
    """


def _pct(value: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(max(0, min(100, (float(value) / float(total)) * 100)), 2)


def _report_status(value: object) -> str:
    status = _clean_text(value, 40).lower()
    allowed = {"queued", "processing", "sent", "delivered", "read", "replied", "failed"}
    return status if status in allowed else "all"


def _load_broadcast_report_base(conn, tenant_id: str, broadcast_id: str) -> dict[str, Any]:
    row = conn.execute(
        text(
            f"""
            {_broadcast_select()}
            WHERE b.tenant_id = CAST(:tenant_id AS uuid)
              AND b.id = CAST(:broadcast_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "broadcast_id": broadcast_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="broadcast_not_found")
    return dict(row)


def _recipient_where(status: str, search: str) -> tuple[list[str], dict[str, Any]]:
    where = ["r.tenant_id = CAST(:tenant_id AS uuid)", "r.broadcast_id = CAST(:broadcast_id AS uuid)"]
    params: dict[str, Any] = {}
    safe_status = _report_status(status)
    if safe_status != "all":
        where.append("r.status = :recipient_status")
        params["recipient_status"] = safe_status
    q = _clean_text(search, 180).lower()
    if q:
        where.append(
            """
            (
                LOWER(COALESCE(r.recipient_external_id, '')) LIKE :search
                OR LOWER(COALESCE(c.display_name, '')) LIKE :search
                OR LOWER(COALESCE(r.provider_message_id, '')) LIKE :search
                OR LOWER(COALESCE(m.external_message_id, '')) LIKE :search
                OR LOWER(COALESCE(r.body_text, '')) LIKE :search
                OR LOWER(COALESCE(r.error, '')) LIKE :search
            )
            """
        )
        params["search"] = f"%{q}%"
    return where, params


def _broadcast_metrics(conn, tenant_id: str, broadcast_id: str, audience_count: int) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            SELECT
                COUNT(*)::int AS total,
                COUNT(*) FILTER (WHERE status = 'queued')::int AS queued,
                COUNT(*) FILTER (WHERE status = 'processing')::int AS processing,
                COUNT(*) FILTER (WHERE status = 'sent')::int AS sent,
                COUNT(*) FILTER (WHERE status = 'delivered')::int AS delivered,
                COUNT(*) FILTER (WHERE status = 'read')::int AS read,
                COUNT(*) FILTER (WHERE status = 'replied')::int AS replied,
                COUNT(*) FILTER (WHERE status = 'failed')::int AS failed
            FROM saas_broadcast_recipients
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND broadcast_id = CAST(:broadcast_id AS uuid)
            """
        ),
        {"tenant_id": tenant_id, "broadcast_id": broadcast_id},
    ).mappings().first()
    counts = dict(row or {})
    total = int(counts.get("total") or 0)
    targeted = max(int(audience_count or 0), total)
    queued = int(counts.get("queued") or 0)
    processing = int(counts.get("processing") or 0)
    sent = int(counts.get("sent") or 0)
    delivered = int(counts.get("delivered") or 0)
    read = int(counts.get("read") or 0)
    replied = int(counts.get("replied") or 0)
    failed = int(counts.get("failed") or 0)
    sent_like = sent + delivered + read + replied
    delivered_like = delivered + read + replied
    read_like = read + replied
    processed = sent_like + failed
    return {
        "targeted": targeted,
        "message_count": 1,
        "total": total,
        "queued": queued,
        "processing": processing,
        "pending": queued + processing,
        "processed": processed,
        "sent": sent_like,
        "delivered": delivered_like,
        "opened": read_like,
        "read": read_like,
        "replied": replied,
        "failed": failed,
        "unreached": failed,
        "processed_pct": _pct(processed, targeted),
        "sent_pct": _pct(sent_like, targeted),
        "delivered_pct": _pct(delivered_like, sent_like),
        "opened_pct": _pct(read_like, delivered_like),
        "read_rate_pct": _pct(read_like, delivered_like),
        "reply_rate_pct": _pct(replied, sent_like),
        "failed_pct": _pct(failed, targeted),
        "coverage_pct": _pct(total, targeted),
    }


def _rules_summary(filters: dict[str, Any]) -> dict[str, Any]:
    safe = filters if isinstance(filters, dict) else {}
    return {
        "included_labels": [safe.get("tag")] if safe.get("tag") else [],
        "excluded_labels": [],
        "channel": safe.get("channel") or "whatsapp",
        "crm_stage": safe.get("crm_stage") or "N/A",
        "payment_status": safe.get("payment_status") or "N/A",
        "city": safe.get("city") or "N/A",
        "customer_type": safe.get("customer_type") or "N/A",
        "intent": safe.get("intent") or "N/A",
        "takeover": safe.get("takeover") or "cualquiera",
    }


def _recipient_rows(
    conn,
    tenant_id: str,
    broadcast_id: str,
    *,
    status: str = "all",
    search: str = "",
    page: int = 1,
    per_page: int = 25,
) -> dict[str, Any]:
    safe_page = max(1, int(page or 1))
    safe_per_page = max(1, min(int(per_page or 25), 500))
    offset = (safe_page - 1) * safe_per_page
    where, filter_params = _recipient_where(status, search)
    params = {
        "tenant_id": tenant_id,
        "broadcast_id": broadcast_id,
        "limit": safe_per_page,
        "offset": offset,
        **filter_params,
    }
    where_sql = " AND ".join(where)
    total = int(
        conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM saas_broadcast_recipients
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND broadcast_id = CAST(:broadcast_id AS uuid)
                """
            ),
            {"tenant_id": tenant_id, "broadcast_id": broadcast_id},
        ).scalar_one()
        or 0
    )
    filtered_total = int(
        conn.execute(
            text(
                f"""
                SELECT COUNT(*)
                FROM saas_broadcast_recipients r
                LEFT JOIN saas_conversations c ON c.id = r.conversation_id
                LEFT JOIN saas_messages m ON m.id = r.message_id
                WHERE {where_sql}
                """
            ),
            params,
        ).scalar_one()
        or 0
    )
    rows = conn.execute(
        text(
            f"""
            SELECT
                r.id::text AS recipient_id,
                r.conversation_id::text,
                r.message_id::text,
                r.outbound_id::text,
                r.recipient_external_id AS chat_id,
                COALESCE(c.display_name, '') AS name,
                r.status,
                r.body_text,
                r.error,
                r.provider_message_id,
                COALESCE(NULLIF(r.provider_message_id, ''), m.external_message_id, '') AS message_id_label,
                r.queued_at::text,
                r.sent_at::text,
                r.delivered_at::text,
                r.read_at::text,
                r.replied_at::text,
                r.failed_at::text,
                r.created_at::text,
                r.updated_at::text
            FROM saas_broadcast_recipients r
            LEFT JOIN saas_conversations c ON c.id = r.conversation_id
            LEFT JOIN saas_messages m ON m.id = r.message_id
            WHERE {where_sql}
            ORDER BY r.created_at DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    ).mappings().all()
    items = []
    for idx, row in enumerate(rows):
        item = dict(row)
        item["index"] = offset + idx + 1
        item["message_id"] = item.pop("message_id_label", "") or item.get("message_id") or ""
        item["opened_at"] = item.get("read_at")
        items.append(item)
    pages = max(1, (filtered_total + safe_per_page - 1) // safe_per_page)
    return {
        "page": safe_page,
        "per_page": safe_per_page,
        "total": total,
        "filtered_total": filtered_total,
        "pages": pages,
        "items": items,
    }


@router.get("/meta/templates")
def list_meta_templates(
    status: str = Query("all", max_length=40),
    limit: int = Query(300, ge=1, le=500),
    ctx: AuthContext = Depends(get_current_user),
):
    params: dict[str, Any] = {"tenant_id": ctx.tenant_id, "limit": int(limit)}
    where = ["tenant_id = CAST(:tenant_id AS uuid)"]
    if status and status != "all":
        where.append("status = :status")
        params["status"] = _clean_text(status, 40).lower()
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_broadcast(conn, ctx.tenant_id)
        rows = conn.execute(
            text(
                f"""
                {_meta_template_select()}
                WHERE {" AND ".join(where)}
                ORDER BY updated_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
    return {"tenant_id": ctx.tenant_id, "templates": [dict(row) for row in rows], "count": len(rows)}


@router.post("/meta/templates/sync")
def sync_meta_templates(
    limit: int = Query(300, ge=1, le=500),
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    synced = 0
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_broadcast(conn, ctx.tenant_id)
        integration = _load_meta_integration(conn, ctx.tenant_id)
        fetched_rows, source = _fetch_meta_templates_from_graph(limit, integration)
        for raw in fetched_rows:
            _upsert_meta_template(conn, ctx.tenant_id, _map_meta_row(raw), user_id=ctx.user_id)
            synced += 1
        if synced:
            conn.execute(
                text(
                    """
                    UPDATE saas_integrations
                    SET last_sync_at = NOW(), updated_at = NOW()
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND channel = 'whatsapp'
                      AND status = 'connected'
                      AND provider IN ('meta', 'whatsapp', 'whatsapp_cloud')
                    """
                ),
                {"tenant_id": ctx.tenant_id},
            )
        rows = conn.execute(
            text(
                f"""
                {_meta_template_select()}
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                ORDER BY updated_at DESC
                LIMIT :limit
                """
            ),
            {"tenant_id": ctx.tenant_id, "limit": int(limit)},
        ).mappings().all()
    return {
        "ok": True,
        "tenant_id": ctx.tenant_id,
        "source": source,
        "synced": synced,
        "templates": [dict(row) for row in rows],
        "count": len(rows),
    }


@router.post("/meta/templates")
def create_meta_template(
    payload: MetaTemplateCreateIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    name = _normalize_meta_template_name(payload.name)
    if not name:
        raise HTTPException(status_code=400, detail="valid_meta_template_name_required")
    category = _clean_text(payload.category, 40).upper() or "MARKETING"
    if category not in {"MARKETING", "UTILITY", "AUTHENTICATION"}:
        raise HTTPException(status_code=400, detail="invalid_meta_template_category")

    components = _build_meta_components(payload)
    provider_response: dict[str, Any] = {"mode": "local_pending"}
    status = "pending"
    meta_template_id = ""

    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_broadcast(conn, ctx.tenant_id)
        integration = _load_meta_integration(conn, ctx.tenant_id)

    token = _meta_access_token(integration)
    waba_id = _meta_waba_id(integration)
    if token and waba_id:
        graph_version = _meta_graph_version(integration)
        request_payload: dict[str, Any] = {
            "name": name,
            "category": category,
            "language": _clean_text(payload.language, 20).lower() or "es",
            "components": components,
        }
        if payload.allow_category_change:
            request_payload["allow_category_change"] = True
        url = f"https://graph.facebook.com/{graph_version}/{urllib.parse.quote(waba_id)}/message_templates"
        data = urllib.parse.urlencode({"access_token": token}).encode("utf-8")
        req = urllib.request.Request(
            f"{url}?{data.decode('utf-8')}",
            data=json.dumps(request_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                provider_response = json.loads(response.read().decode("utf-8") or "{}")
            status = _clean_text(provider_response.get("status"), 40).lower() or "pending"
            meta_template_id = _clean_text(provider_response.get("id"), 240)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            provider_response = {"mode": "graph_error", "error": body[:1200]}
            status = "pending"
        except Exception as exc:
            provider_response = {"mode": "graph_error", "error": str(exc)[:600]}
            status = "pending"

    buttons = []
    for comp in components:
        if comp.get("type") == "BUTTONS":
            buttons = comp.get("buttons") if isinstance(comp.get("buttons"), list) else []

    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_broadcast(conn, ctx.tenant_id)
        row = _upsert_meta_template(
            conn,
            ctx.tenant_id,
            {
                "provider": "meta",
                "meta_template_id": meta_template_id,
                "name": name,
                "language": _clean_text(payload.language, 20).lower() or "es",
                "category": category,
                "status": status,
                "header_type": _clean_text(payload.header_type, 40).upper(),
                "header_text": _clean_text(payload.header_text, 60),
                "header_media_handle": _clean_text(payload.header_media_handle, 500),
                "body_text": _clean_text(payload.body_text, 1024),
                "footer_text": _clean_text(payload.footer_text, 60),
                "buttons_json": buttons,
                "components_json": components,
                "allow_category_change": payload.allow_category_change,
                "provider_response_json": provider_response,
            },
            user_id=ctx.user_id,
        )
    return {"ok": True, "tenant_id": ctx.tenant_id, "template": row, "provider_response": provider_response}


@router.patch("/meta/templates/{template_id}")
def patch_meta_template(
    template_id: str,
    payload: MetaTemplatePatchIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="meta_template_patch_required")
    assignments: list[str] = []
    params: dict[str, Any] = {"tenant_id": ctx.tenant_id, "template_id": template_id}
    if "status" in data:
        status = _clean_text(data["status"], 40).lower()
        if status not in {"pending", "approved", "rejected", "paused", "disabled"}:
            raise HTTPException(status_code=400, detail="invalid_meta_template_status")
        params["status"] = status
        assignments.append("status = :status")
        if status == "approved":
            assignments.append("approved_at = COALESCE(approved_at, NOW())")
        if status == "rejected":
            assignments.append("rejected_at = COALESCE(rejected_at, NOW())")
    if "quality_score" in data:
        params["quality_score"] = _clean_text(data["quality_score"], 80)
        assignments.append("quality_score = :quality_score")
    if "rejection_reason" in data:
        params["rejection_reason"] = _clean_text(data["rejection_reason"], 1000)
        assignments.append("rejection_reason = :rejection_reason")
    assignments.append("updated_at = NOW()")
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_broadcast(conn, ctx.tenant_id)
        row = conn.execute(
            text(
                f"""
                UPDATE saas_meta_message_templates
                SET {", ".join(assignments)}
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:template_id AS uuid)
                RETURNING id::text, provider, meta_template_id, name, language, category, status, quality_score,
                          header_type, header_text, header_media_handle, body_text, footer_text, buttons_json,
                          components_json, allow_category_change, provider_response_json, rejection_reason,
                          submitted_at::text, approved_at::text, rejected_at::text, last_sync_at::text,
                          created_at::text, updated_at::text
                """
            ),
            params,
        ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="meta_template_not_found")
    return {"ok": True, "tenant_id": ctx.tenant_id, "template": dict(row)}


@router.get("")
def list_broadcasts(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_broadcast(conn, ctx.tenant_id)
        rows = conn.execute(
            text(
                f"""
                {_broadcast_select()}
                WHERE b.tenant_id = CAST(:tenant_id AS uuid)
                ORDER BY b.updated_at DESC
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().all()
    return {"tenant_id": ctx.tenant_id, "broadcasts": [dict(row) for row in rows]}


@router.post("/preview")
def preview_broadcast(payload: BroadcastPreviewIn, ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_broadcast(conn, ctx.tenant_id)
        filters = payload.filters_json or _load_segment_filters(conn, ctx.tenant_id, _clean_id(payload.segment_id))
        meta_template = _load_meta_template(conn, ctx.tenant_id, _clean_id(payload.meta_template_id))
        body = (
            _clean_text(payload.body, 8000)
            or _clean_text((meta_template or {}).get("body_text"), 1024)
            or _load_template_body(conn, ctx.tenant_id, _clean_id(payload.template_id))
        )
        if not body:
            raise HTTPException(status_code=400, detail="broadcast_body_or_template_required")
        total = _count_conversations(conn, ctx.tenant_id, filters)
        sample_rows = _conversation_rows(conn, ctx.tenant_id, filters, min(int(payload.limit), 10))

    return {
        "tenant_id": ctx.tenant_id,
        "audience_count": total,
        "sample": [
            {
                "conversation_id": row["id"],
                "display_name": row.get("display_name") or row.get("phone") or row.get("external_contact_id"),
                "recipient": row.get("phone") or row.get("external_contact_id"),
                "body": _render_body(body, row),
            }
            for row in sample_rows
        ],
    }


@router.post("")
def create_broadcast(
    payload: BroadcastCreateIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_broadcast(conn, ctx.tenant_id)
        ensure_broadcast_quota(conn, ctx.tenant_id)
        segment_id = _clean_id(payload.segment_id)
        template_id = _clean_id(payload.template_id)
        meta_template_id = _clean_id(payload.meta_template_id)
        filters = _load_segment_filters(conn, ctx.tenant_id, segment_id) if segment_id else {}
        meta_template = _load_meta_template(conn, ctx.tenant_id, meta_template_id)
        if meta_template and _clean_text(payload.status, 40).lower() in {"scheduled", "queued", "running"} and meta_template["status"] != "approved":
            raise HTTPException(status_code=409, detail="meta_template_must_be_approved_before_scheduling")
        body = (
            _clean_text(payload.body, 8000)
            or _clean_text((meta_template or {}).get("body_text"), 1024)
            or _load_template_body(conn, ctx.tenant_id, template_id)
        )
        if not body:
            raise HTTPException(status_code=400, detail="broadcast_body_or_template_required")
        audience_count = _count_conversations(conn, ctx.tenant_id, filters) if segment_id else 0
        row = conn.execute(
            text(
                """
                INSERT INTO saas_broadcasts (
                    tenant_id, name, channel, template_id, meta_template_id, meta_template_name,
                    meta_template_language, meta_template_category, meta_template_body,
                    segment_id, body, status, scheduled_at, audience_count, created_by_user_id
                )
                VALUES (
                    CAST(:tenant_id AS uuid), :name, :channel,
                    CAST(NULLIF(:template_id, '') AS uuid), CAST(NULLIF(:meta_template_id, '') AS uuid),
                    :meta_template_name, :meta_template_language, :meta_template_category, :meta_template_body,
                    CAST(NULLIF(:segment_id, '') AS uuid),
                    :body, :status, CAST(NULLIF(:scheduled_at, '') AS timestamp), :audience_count, CAST(:user_id AS uuid)
                )
                RETURNING id::text, name, channel, template_id::text, meta_template_id::text, meta_template_name,
                          meta_template_language, meta_template_category, meta_template_body,
                          segment_id::text, body, status, scheduled_at::text, audience_count, queued_count,
                          sent_count, failed_count, metrics_json, created_at::text, updated_at::text
                """
            ),
            {
                "tenant_id": ctx.tenant_id,
                "user_id": ctx.user_id,
                "name": _clean_text(payload.name, 160),
                "channel": _clean_channel(payload.channel),
                "template_id": template_id,
                "meta_template_id": meta_template_id,
                "meta_template_name": _clean_text(payload.meta_template_name, 200) or _clean_text((meta_template or {}).get("name"), 200),
                "meta_template_language": _clean_text(payload.meta_template_language, 20) or _clean_text((meta_template or {}).get("language"), 20),
                "meta_template_category": _clean_text(payload.meta_template_category, 40) or _clean_text((meta_template or {}).get("category"), 40),
                "meta_template_body": _clean_text(payload.meta_template_body, 1024) or _clean_text((meta_template or {}).get("body_text"), 1024),
                "segment_id": segment_id,
                "body": body,
                "status": _clean_text(payload.status, 40).lower() or "draft",
                "scheduled_at": _clean_text(payload.scheduled_at, 60),
                "audience_count": audience_count,
            },
        ).mappings().first()
    return {"ok": True, "tenant_id": ctx.tenant_id, "broadcast": dict(row)}


@router.patch("/{broadcast_id}")
def update_broadcast(
    broadcast_id: str,
    payload: BroadcastPatchIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="broadcast_patch_required")
    assignments: list[str] = []
    params: dict[str, Any] = {"tenant_id": ctx.tenant_id, "broadcast_id": broadcast_id}
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_broadcast(conn, ctx.tenant_id)
        if "segment_id" in data:
            segment_id = _clean_id(data["segment_id"])
            filters = _load_segment_filters(conn, ctx.tenant_id, segment_id) if segment_id else {}
            params["segment_id"] = segment_id
            params["audience_count"] = _count_conversations(conn, ctx.tenant_id, filters) if segment_id else 0
            assignments.append("segment_id = CAST(NULLIF(:segment_id, '') AS uuid)")
            assignments.append("audience_count = :audience_count")
        if "meta_template_id" in data:
            meta_template_id = _clean_id(data["meta_template_id"])
            meta_template = _load_meta_template(conn, ctx.tenant_id, meta_template_id)
            params["meta_template_id"] = meta_template_id
            params["meta_template_name"] = _clean_text((meta_template or {}).get("name"), 200)
            params["meta_template_language"] = _clean_text((meta_template or {}).get("language"), 20)
            params["meta_template_category"] = _clean_text((meta_template or {}).get("category"), 40)
            params["meta_template_body"] = _clean_text((meta_template or {}).get("body_text"), 1024)
            assignments.append("meta_template_id = CAST(NULLIF(:meta_template_id, '') AS uuid)")
            assignments.append("meta_template_name = :meta_template_name")
            assignments.append("meta_template_language = :meta_template_language")
            assignments.append("meta_template_category = :meta_template_category")
            assignments.append("meta_template_body = :meta_template_body")
            if meta_template and not _clean_text(data.get("body"), 8000):
                params["body"] = params["meta_template_body"]
                assignments.append("body = :body")
        for key in ("name", "channel", "template_id", "body", "status", "scheduled_at", "meta_template_name", "meta_template_language", "meta_template_category", "meta_template_body"):
            if key not in data:
                continue
            if key == "channel":
                params[key] = _clean_channel(data[key])
                assignments.append("channel = :channel")
            elif key == "template_id":
                params[key] = _clean_id(data[key])
                assignments.append("template_id = CAST(NULLIF(:template_id, '') AS uuid)")
            elif key == "scheduled_at":
                params[key] = _clean_text(data[key], 60)
                assignments.append("scheduled_at = CAST(NULLIF(:scheduled_at, '') AS timestamp)")
            else:
                params[key] = _clean_text(data[key], 8000 if key == "body" else 1024 if key == "meta_template_body" else 200)
                assignments.append(f"{key} = :{key}")
        assignments.append("updated_at = NOW()")
        row = conn.execute(
            text(
                f"""
                UPDATE saas_broadcasts
                SET {", ".join(assignments)}
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:broadcast_id AS uuid)
                RETURNING id::text, name, channel, template_id::text, meta_template_id::text, meta_template_name,
                          meta_template_language, meta_template_category, meta_template_body,
                          segment_id::text, body, status, scheduled_at::text, audience_count, queued_count,
                          sent_count, failed_count, metrics_json, created_at::text, updated_at::text
                """
            ),
            params,
        ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="broadcast_not_found")
    return {"ok": True, "tenant_id": ctx.tenant_id, "broadcast": dict(row)}


@router.post("/{broadcast_id}/enqueue")
def enqueue_broadcast(
    broadcast_id: str,
    payload: BroadcastEnqueueIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_broadcast(conn, ctx.tenant_id)
        broadcast = conn.execute(
            text(
                """
                SELECT b.id::text, b.name, b.channel, b.template_id::text, b.meta_template_id::text,
                       b.segment_id::text, b.body, b.status, b.queued_count,
                       COALESCE(mt.status, '') AS meta_template_status,
                       COALESCE(mt.meta_template_id, '') AS provider_meta_template_id,
                       COALESCE(mt.name, b.meta_template_name, '') AS resolved_meta_template_name,
                       COALESCE(mt.language, b.meta_template_language, 'es') AS resolved_meta_template_language,
                       COALESCE(mt.category, b.meta_template_category, '') AS resolved_meta_template_category,
                       COALESCE(mt.body_text, b.meta_template_body, b.body, '') AS resolved_meta_template_body,
                       COALESCE(mt.components_json, '[]'::jsonb) AS resolved_meta_components
                FROM saas_broadcasts b
                LEFT JOIN saas_meta_message_templates mt ON mt.id = b.meta_template_id
                WHERE b.tenant_id = CAST(:tenant_id AS uuid)
                  AND b.id = CAST(:broadcast_id AS uuid)
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id, "broadcast_id": broadcast_id},
        ).mappings().first()
        if not broadcast:
            raise HTTPException(status_code=404, detail="broadcast_not_found")
        if int(broadcast["queued_count"] or 0) > 0:
            raise HTTPException(status_code=409, detail="broadcast_already_enqueued")
        if broadcast["meta_template_id"] and broadcast["meta_template_status"] != "approved":
            raise HTTPException(status_code=409, detail="meta_template_must_be_approved_before_enqueue")

        segment_id = _clean_id(broadcast["segment_id"])
        filters = _load_segment_filters(conn, ctx.tenant_id, segment_id) if segment_id else {}
        rows = _conversation_rows(conn, ctx.tenant_id, filters, int(payload.limit))
        if not rows:
            raise HTTPException(status_code=400, detail="broadcast_audience_empty")

        ensure_monthly_message_quota(conn, ctx.tenant_id, requested=len(rows))

        queued = 0
        for row in rows:
            rendered = _render_body(str(broadcast["body"] or ""), row)
            if not rendered:
                continue
            recipient = _clean_text(row.get("external_contact_id")) or _clean_text(row.get("phone"))
            local_external_id = f"broadcast:{broadcast_id}:{row['id']}:{uuid4().hex}"
            message_payload = {
                "source": "saas_broadcast",
                "actor_user_id": ctx.user_id,
                "broadcast_id": broadcast_id,
                "dispatch_status": "queued",
            }
            outbound_payload = {
                "broadcast_id": broadcast_id,
                "local_external_message_id": local_external_id,
            }
            if broadcast["meta_template_id"]:
                template_body = _clean_text(broadcast["resolved_meta_template_body"], 1024) or str(broadcast["body"] or "")
                template_payload = {
                    "message_type": "template",
                    "provider_meta_template_id": _clean_text(broadcast["provider_meta_template_id"], 240),
                    "meta_template_name": _clean_text(broadcast["resolved_meta_template_name"], 200),
                    "meta_template_language": _clean_text(broadcast["resolved_meta_template_language"], 20) or "es",
                    "meta_template_category": _clean_text(broadcast["resolved_meta_template_category"], 40),
                    "meta_template_body": template_body,
                    "template_body_parameters": _template_body_parameters(template_body, row),
                    "template_components": broadcast["resolved_meta_components"] if isinstance(broadcast["resolved_meta_components"], list) else [],
                }
                message_payload.update(template_payload)
                outbound_payload.update(template_payload)
            message = conn.execute(
                text(
                    """
                    INSERT INTO saas_messages (
                        tenant_id, conversation_id, channel, external_message_id, direction, msg_type, text, payload_json
                    )
                    VALUES (
                        CAST(:tenant_id AS uuid), CAST(:conversation_id AS uuid), :channel, :external_message_id,
                        'out', 'text', :body_text, CAST(:payload_json AS jsonb)
                    )
                    RETURNING id::text
                    """
                ),
                {
                    "tenant_id": ctx.tenant_id,
                    "conversation_id": row["id"],
                    "channel": str(broadcast["channel"] or "whatsapp"),
                    "external_message_id": local_external_id,
                    "body_text": rendered,
                    "payload_json": json.dumps(message_payload),
                },
            ).mappings().first()
            outbound = conn.execute(
                text(
                    """
                    INSERT INTO saas_outbound_messages (
                        tenant_id, conversation_id, message_id, channel, recipient_external_id, body_text, payload_json
                    )
                    VALUES (
                        CAST(:tenant_id AS uuid), CAST(:conversation_id AS uuid), CAST(:message_id AS uuid),
                        :channel, :recipient_external_id, :body_text, CAST(:payload_json AS jsonb)
                    )
                    RETURNING id::text
                    """
                ),
                {
                    "tenant_id": ctx.tenant_id,
                    "conversation_id": row["id"],
                    "message_id": message["id"],
                    "channel": str(broadcast["channel"] or "whatsapp"),
                    "recipient_external_id": recipient,
                    "body_text": rendered,
                    "payload_json": json.dumps(outbound_payload, ensure_ascii=False),
                },
            ).mappings().first()
            conn.execute(
                text(
                    """
                    INSERT INTO saas_broadcast_recipients (
                        tenant_id, broadcast_id, conversation_id, message_id, outbound_id, channel, recipient_external_id, body_text, status, queued_at
                    )
                    VALUES (
                        CAST(:tenant_id AS uuid), CAST(:broadcast_id AS uuid), CAST(:conversation_id AS uuid),
                        CAST(:message_id AS uuid), CAST(:outbound_id AS uuid), :channel, :recipient_external_id, :body_text, 'queued', NOW()
                    )
                    ON CONFLICT (tenant_id, broadcast_id, conversation_id) DO NOTHING
                    """
                ),
                {
                    "tenant_id": ctx.tenant_id,
                    "broadcast_id": broadcast_id,
                    "conversation_id": row["id"],
                    "message_id": message["id"],
                    "outbound_id": outbound["id"],
                    "channel": str(broadcast["channel"] or "whatsapp"),
                    "recipient_external_id": recipient,
                    "body_text": rendered,
                },
            )
            conn.execute(
                text(
                    """
                    UPDATE saas_conversations
                    SET last_message_text = :body_text,
                        last_message_at = NOW(),
                        updated_at = NOW()
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND id = CAST(:conversation_id AS uuid)
                    """
                ),
                {"tenant_id": ctx.tenant_id, "conversation_id": row["id"], "body_text": rendered},
            )
            queued += 1

        if queued <= 0:
            raise HTTPException(status_code=400, detail="broadcast_rendered_empty")

        conn.execute(
            text(
                """
                UPDATE saas_broadcasts
                SET status = 'queued',
                    queued_count = :queued,
                    audience_count = :queued,
                    updated_at = NOW()
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:broadcast_id AS uuid)
                """
            ),
            {"tenant_id": ctx.tenant_id, "broadcast_id": broadcast_id, "queued": queued},
        )
        conn.execute(
            text(
                """
                INSERT INTO saas_usage_counters (tenant_id, metric_code, period_yyyymm, metric_value)
                VALUES (CAST(:tenant_id AS uuid), 'outbound_messages_queued', :period, :queued)
                ON CONFLICT (tenant_id, metric_code, period_yyyymm)
                DO UPDATE SET
                    metric_value = saas_usage_counters.metric_value + EXCLUDED.metric_value,
                    updated_at = NOW()
                """
            ),
            {"tenant_id": ctx.tenant_id, "period": _period_yyyymm(), "queued": queued},
        )

    process_result = None
    if payload.process_now:
        process_result = process_due_outbound_messages(limit=min(queued, 200), tenant_id=ctx.tenant_id)
    return {"ok": True, "tenant_id": ctx.tenant_id, "queued": queued, "process_result": process_result}


@router.get("/{broadcast_id}/report")
def broadcast_report(
    broadcast_id: str,
    status: str = Query("all", max_length=40),
    search: str = Query("", max_length=180),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=500),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_broadcast(conn, ctx.tenant_id)
        broadcast = _load_broadcast_report_base(conn, ctx.tenant_id, broadcast_id)
        segment_id = _clean_id(broadcast.get("segment_id"))
        filters = _load_segment_filters(conn, ctx.tenant_id, segment_id) if segment_id else {}
        metrics = _broadcast_metrics(conn, ctx.tenant_id, broadcast_id, int(broadcast.get("audience_count") or 0))
        recipients = _recipient_rows(
            conn,
            ctx.tenant_id,
            broadcast_id,
            status=status,
            search=search,
            page=page,
            per_page=per_page,
        )
    campaign = {
        "id": broadcast["id"],
        "name": broadcast.get("name") or "",
        "channel": broadcast.get("channel") or "whatsapp",
        "status": broadcast.get("status") or "draft",
        "scheduled_at": broadcast.get("scheduled_at"),
        "template_id": broadcast.get("template_id"),
        "template_name": broadcast.get("template_name") or "",
        "meta_template_id": broadcast.get("meta_template_id"),
        "meta_template_name": broadcast.get("meta_template_name") or "",
        "meta_template_language": broadcast.get("meta_template_language") or "",
        "meta_template_category": broadcast.get("meta_template_category") or "",
        "meta_template_body": broadcast.get("meta_template_body") or "",
        "segment_id": broadcast.get("segment_id"),
        "segment_name": broadcast.get("segment_name") or "",
        "audience_count": broadcast.get("audience_count") or 0,
        "queued_count": broadcast.get("queued_count") or 0,
        "sent_count": broadcast.get("sent_count") or 0,
        "failed_count": broadcast.get("failed_count") or 0,
        "created_at": broadcast.get("created_at"),
        "updated_at": broadcast.get("updated_at"),
    }
    return {
        "tenant_id": ctx.tenant_id,
        "campaign": campaign,
        "rules_summary": _rules_summary(filters),
        "metrics": {"status": campaign["status"], **metrics},
        "recipients": recipients,
    }


@router.get("/{broadcast_id}/export.csv")
def export_broadcast_csv(
    broadcast_id: str,
    status: str = Query("all", max_length=40),
    search: str = Query("", max_length=180),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_broadcast(conn, ctx.tenant_id)
        broadcast = _load_broadcast_report_base(conn, ctx.tenant_id, broadcast_id)
        recipients = _recipient_rows(
            conn,
            ctx.tenant_id,
            broadcast_id,
            status=status,
            search=search,
            page=1,
            per_page=500,
        )
        all_items = list(recipients["items"])
        for next_page in range(2, int(recipients["pages"] or 1) + 1):
            page_payload = _recipient_rows(
                conn,
                ctx.tenant_id,
                broadcast_id,
                status=status,
                search=search,
                page=next_page,
                per_page=500,
            )
            all_items.extend(page_payload["items"])

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "#",
        "Chat ID",
        "Nombre",
        "Status",
        "Queued at",
        "Sent at",
        "Delivered at",
        "Opened at",
        "Replied at",
        "Failed at",
        "Message ID",
        "Error",
        "Body",
    ])
    for item in all_items:
        writer.writerow([
            item.get("index") or "",
            item.get("chat_id") or "",
            item.get("name") or "",
            item.get("status") or "",
            item.get("queued_at") or "",
            item.get("sent_at") or "",
            item.get("delivered_at") or "",
            item.get("opened_at") or "",
            item.get("replied_at") or "",
            item.get("failed_at") or "",
            item.get("message_id") or "",
            item.get("error") or "",
            item.get("body_text") or "",
        ])
    filename = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(broadcast.get("name") or "broadcast")).strip("_") or "broadcast"
    return Response(
        content=out.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}_report.csv"'},
    )


@router.post("/{broadcast_id}/retry-failed")
def retry_failed_recipients(
    broadcast_id: str,
    limit: int = Query(200, ge=1, le=500),
    process_now: bool = Query(False),
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_broadcast(conn, ctx.tenant_id)
        _load_broadcast_report_base(conn, ctx.tenant_id, broadcast_id)
        rows = conn.execute(
            text(
                """
                SELECT id::text, outbound_id::text
                FROM saas_broadcast_recipients
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND broadcast_id = CAST(:broadcast_id AS uuid)
                  AND status = 'failed'
                  AND outbound_id IS NOT NULL
                ORDER BY updated_at ASC
                LIMIT :limit
                FOR UPDATE SKIP LOCKED
                """
            ),
            {"tenant_id": ctx.tenant_id, "broadcast_id": broadcast_id, "limit": int(limit)},
        ).mappings().all()
        retry_count = len(rows)
        if retry_count:
            ensure_monthly_message_quota(conn, ctx.tenant_id, requested=retry_count)
        for row in rows:
            conn.execute(
                text(
                    """
                    UPDATE saas_broadcast_recipients
                    SET status = 'queued',
                        error = '',
                        failed_at = NULL,
                        queued_at = COALESCE(queued_at, NOW()),
                        updated_at = NOW()
                    WHERE id = CAST(:recipient_id AS uuid)
                    """
                ),
                {"recipient_id": row["id"]},
            )
            conn.execute(
                text(
                    """
                    UPDATE saas_outbound_messages
                    SET status = 'queued',
                        attempts = 0,
                        locked_at = NULL,
                        next_attempt_at = NOW(),
                        error = '',
                        updated_at = NOW()
                    WHERE id = CAST(:outbound_id AS uuid)
                    """
                ),
                {"outbound_id": row["outbound_id"]},
            )
        if retry_count:
            conn.execute(
                text(
                    """
                    UPDATE saas_broadcasts
                    SET status = 'queued', updated_at = NOW()
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND id = CAST(:broadcast_id AS uuid)
                    """
                ),
                {"tenant_id": ctx.tenant_id, "broadcast_id": broadcast_id},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO saas_usage_counters (tenant_id, metric_code, period_yyyymm, metric_value)
                    VALUES (CAST(:tenant_id AS uuid), 'outbound_messages_queued', :period, :queued)
                    ON CONFLICT (tenant_id, metric_code, period_yyyymm)
                    DO UPDATE SET
                        metric_value = saas_usage_counters.metric_value + EXCLUDED.metric_value,
                        updated_at = NOW()
                    """
                ),
                {"tenant_id": ctx.tenant_id, "period": _period_yyyymm(), "queued": retry_count},
            )
    process_result = None
    if process_now and retry_count:
        process_result = process_due_outbound_messages(limit=min(retry_count, 200), tenant_id=ctx.tenant_id)
    return {"ok": True, "tenant_id": ctx.tenant_id, "retried": retry_count, "process_result": process_result}


@router.get("/{broadcast_id}/recipients")
def list_broadcast_recipients(
    broadcast_id: str,
    limit: int = Query(200, ge=1, le=500),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_broadcast(conn, ctx.tenant_id)
        rows = conn.execute(
            text(
                """
                SELECT
                    id::text,
                    conversation_id::text,
                    message_id::text,
                    outbound_id::text,
                    channel,
                    recipient_external_id,
                    body_text,
                    status,
                    error,
                    queued_at::text,
                    sent_at::text,
                    created_at::text,
                    updated_at::text
                FROM saas_broadcast_recipients
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND broadcast_id = CAST(:broadcast_id AS uuid)
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            {"tenant_id": ctx.tenant_id, "broadcast_id": broadcast_id, "limit": limit},
        ).mappings().all()
    return {"tenant_id": ctx.tenant_id, "recipients": [dict(row) for row in rows]}
