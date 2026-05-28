from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app_saas.ai_agent.service import ensure_ai_tables, get_settings, process_due_ai_replies
from app_saas.api_credentials.router import _ensure_api_credentials_table
from app_saas.config import settings
from app_saas.db import db_session, set_tenant_context
from app_saas.integrations.router import _instagram_page_token, _integration_token, _safe_config_for_output
from app_saas.integrations.whatsapp_subscription import ensure_whatsapp_subscription_log_table
from app_saas.knowledge.router import ensure_knowledge_tables
from app_saas.shared.security import AuthContext, get_current_user, require_role
from app_saas.social.service import ensure_social_tables
from app_saas.workers.dispatch import process_due_outbound_messages
from app_saas.workers.ingest import process_due_webhook_events

router = APIRouter(prefix="/diagnostics", tags=["saas-diagnostics"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class WhatsappInboundSimulationIn(BaseModel):
    from_phone: str = Field(default="573001112233", max_length=40)
    message: str = Field(default="Mensaje de prueba desde diagnostico Scentra", max_length=1000)
    contact_name: str = Field(default="Cliente Debug", max_length=120)


def _table_exists(conn: Connection, table_name: str) -> bool:
    return bool(conn.execute(text("SELECT to_regclass(:table_name) IS NOT NULL"), {"table_name": table_name}).scalar())


def _status_counts(conn: Connection, table_name: str, tenant_id: str) -> list[dict[str, Any]]:
    if not _table_exists(conn, table_name):
        return []
    rows = conn.execute(
        text(
            f"""
            SELECT status, COUNT(*)::int AS total
            FROM {table_name}
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            GROUP BY status
            ORDER BY status ASC
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().all()
    return [dict(row) for row in rows]


def _recent_rows(conn: Connection, sql: str, tenant_id: str, limit: int = 5) -> list[dict[str, Any]]:
    rows = conn.execute(text(sql), {"tenant_id": tenant_id, "limit": limit}).mappings().all()
    return [dict(row) for row in rows]


def _load_debug_whatsapp_integration(conn: Connection, tenant_id: str) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            SELECT provider, channel, status, config_json
            FROM saas_integrations
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND channel = 'whatsapp'
            ORDER BY
              CASE WHEN provider = 'meta' THEN 0 ELSE 1 END,
              updated_at DESC NULLS LAST
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=400, detail="whatsapp_integration_missing")
    data = dict(row)
    config = data.get("config_json") if isinstance(data.get("config_json"), dict) else {}
    return {**data, "config_json": config, "safe_config": _safe_config_for_output(config), "has_token": bool(_integration_token(config))}


def _load_debug_webhook_endpoint(conn: Connection, tenant_id: str) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            SELECT id::text, provider, endpoint_key, is_active, signature_required, last_seen_at::text
            FROM saas_webhook_endpoints
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND provider IN ('whatsapp', 'meta')
              AND is_active = TRUE
            ORDER BY
              CASE WHEN provider = 'whatsapp' THEN 0 ELSE 1 END,
              updated_at DESC NULLS LAST
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=400, detail="active_whatsapp_webhook_missing")
    return dict(row)


def _safe_phone(value: str) -> str:
    clean = "".join(ch for ch in str(value or "").strip() if ch.isdigit())
    return clean[:40] or "573001112233"


def _whatsapp_webhook_signal(conn: Connection, tenant_id: str) -> dict[str, Any]:
    if not _table_exists(conn, "saas_webhook_events"):
        return {
            "status_events_24h": 0,
            "inbound_events_24h": 0,
            "statuses_without_inbound": False,
            "recommendation": "",
        }
    row = conn.execute(
        text(
            """
            SELECT
              COUNT(*) FILTER (
                WHERE payload_json::text ILIKE '%"statuses"%'
                  AND received_at >= NOW() - INTERVAL '24 hours'
              )::int AS status_events_24h,
              COUNT(*) FILTER (
                WHERE payload_json::text ILIKE '%"messages"%'
                  AND received_at >= NOW() - INTERVAL '24 hours'
              )::int AS inbound_events_24h,
              COUNT(*) FILTER (
                WHERE payload_json::text ILIKE '%"statuses"%'
                  AND received_at >= NOW() - INTERVAL '7 days'
              )::int AS status_events_7d,
              COUNT(*) FILTER (
                WHERE payload_json::text ILIKE '%"messages"%'
                  AND received_at >= NOW() - INTERVAL '7 days'
              )::int AS inbound_events_7d
            FROM saas_webhook_events
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND provider IN ('whatsapp', 'meta')
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    data = dict(row or {})
    symptom = int(data.get("status_events_24h") or 0) > 0 and int(data.get("inbound_events_24h") or 0) == 0
    if not symptom:
        symptom = int(data.get("status_events_7d") or 0) > 0 and int(data.get("inbound_events_7d") or 0) == 0
    data["statuses_without_inbound"] = bool(symptom)
    data["recommendation"] = (
        "Llegan statuses de Meta, pero no llegan mensajes entrantes. Verifica WABA subscribed_apps, callback URL, token de verificacion y campo messages en la app de Meta."
        if symptom
        else ""
    )
    return data


def _recent_subscription_checks(conn: Connection, tenant_id: str, limit: int = 5) -> list[dict[str, Any]]:
    ensure_whatsapp_subscription_log_table(conn)
    rows = conn.execute(
        text(
            """
            SELECT
                waba_id,
                app_id,
                status,
                already_subscribed,
                auto_subscribe_attempted,
                final_subscribed,
                http_status,
                meta_code,
                meta_error_type,
                meta_error_message,
                error,
                created_at::text
            FROM saas_whatsapp_subscription_checks
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "limit": limit},
    ).mappings().all()
    return [dict(row) for row in rows]


def _social_meta_diagnostics(conn: Connection, tenant_id: str) -> dict[str, Any]:
    ensure_social_tables(conn)
    comments = _recent_rows(
        conn,
        """
        SELECT c.channel, c.status, c.author_name, c.author_username, c.message, c.updated_at::text,
               p.external_post_id, p.permalink_url
        FROM social_comments c
        LEFT JOIN social_posts p ON p.id = c.post_id
        WHERE c.tenant_id = CAST(:tenant_id AS uuid)
        ORDER BY c.updated_at DESC
        LIMIT :limit
        """,
        tenant_id,
        limit=5,
    )
    dms = _recent_rows(
        conn,
        """
        SELECT channel, external_contact_id, display_name, last_message_text, updated_at::text
        FROM saas_conversations
        WHERE tenant_id = CAST(:tenant_id AS uuid)
          AND channel IN ('facebook', 'instagram')
        ORDER BY updated_at DESC
        LIMIT :limit
        """,
        tenant_id,
        limit=5,
    ) if _table_exists(conn, "saas_conversations") else []
    webhook_signal = conn.execute(
        text(
            """
            SELECT
              COUNT(*) FILTER (WHERE provider IN ('facebook','instagram') AND received_at >= NOW() - INTERVAL '24 hours')::int AS meta_events_24h,
              COUNT(*) FILTER (WHERE provider IN ('facebook','instagram') AND payload_json::text ILIKE '%comment%' AND received_at >= NOW() - INTERVAL '24 hours')::int AS comment_events_24h,
              COUNT(*) FILTER (WHERE provider IN ('facebook','instagram') AND payload_json::text ILIKE '%messaging%' AND received_at >= NOW() - INTERVAL '24 hours')::int AS dm_events_24h
            FROM saas_webhook_events
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first() if _table_exists(conn, "saas_webhook_events") else {}
    endpoints = _recent_rows(
        conn,
        """
        SELECT provider, endpoint_key, is_active, signature_required, last_seen_at::text
        FROM saas_webhook_endpoints
        WHERE tenant_id = CAST(:tenant_id AS uuid)
          AND provider IN ('facebook','instagram')
        ORDER BY updated_at DESC
        LIMIT :limit
        """,
        tenant_id,
        limit=10,
    ) if _table_exists(conn, "saas_webhook_endpoints") else []
    return {
        "webhook_signal": dict(webhook_signal or {}),
        "endpoints": endpoints,
        "last_comments": comments,
        "last_dms": dms,
        "recommendation": (
            "Si no llegan comentarios o DMs, revisa permisos pages_messaging, pages_manage_metadata, pages_read_engagement, instagram_manage_messages y subscribed_apps de la Page."
            if not comments and not dms
            else ""
        ),
    }


@router.get("/overview")
def diagnostics_overview(ctx: AuthContext = Depends(get_current_user)):
    generated_at = _now_iso()
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_api_credentials_table(conn)
        ensure_ai_tables(conn)
        ensure_knowledge_tables(conn)
        tenant = conn.execute(
            text(
                """
                SELECT id::text, name, slug, status, plan_code
                FROM saas_tenants
                WHERE id = CAST(:tenant_id AS uuid)
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().first()
        ai_settings = get_settings(conn, ctx.tenant_id)
        credentials = conn.execute(
            text(
                """
                SELECT category, provider_code, credential_key, secret_hint, metadata_json, updated_at::text
                FROM saas_api_credentials
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                ORDER BY category, provider_code, credential_key
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().all()
        integrations = conn.execute(
            text(
                """
                SELECT provider, channel, status, config_json, last_sync_at::text
                FROM saas_integrations
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                ORDER BY provider, channel
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().all()
        integration_rows = []
        for row in integrations:
            data = dict(row)
            config = data.get("config_json") if isinstance(data.get("config_json"), dict) else {}
            safe_config = _safe_config_for_output(config)
            channel = str(data.get("channel") or "").lower()
            has_token = bool(_instagram_page_token(config)) if channel in {"instagram", "facebook"} else bool(_integration_token(config))
            integration_rows.append(
                {
                    "provider": data.get("provider"),
                    "channel": data.get("channel"),
                    "status": data.get("status"),
                    "dispatch_mode": safe_config.get("dispatch_mode", ""),
                    "phone_number_id": safe_config.get("phone_number_id", ""),
                    "business_account_id": safe_config.get("business_account_id", ""),
                    "page_id": safe_config.get("page_id", ""),
                    "instagram_business_account_id": safe_config.get("instagram_business_account_id", ""),
                    "instagram_username": safe_config.get("instagram_username", ""),
                    "app_id": safe_config.get("app_id", ""),
                    "has_token": has_token,
                    "last_sync_at": data.get("last_sync_at") or "",
                }
            )
        webhooks = _recent_rows(
            conn,
            """
            SELECT provider, endpoint_key, is_active, signature_required, last_seen_at::text
            FROM saas_webhook_endpoints
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY updated_at DESC
            LIMIT :limit
            """,
            ctx.tenant_id,
        ) if _table_exists(conn, "saas_webhook_endpoints") else []
        api_public_url = str(settings.scentra_api_public_url or "").strip().rstrip("/")
        for endpoint in webhooks:
            endpoint["callback_url"] = (
                f"{api_public_url}/saas/v1/webhooks/{endpoint.get('provider')}/{endpoint.get('endpoint_key')}"
                if api_public_url and endpoint.get("provider") and endpoint.get("endpoint_key")
                else ""
            )
            endpoint["legacy_callback_url"] = (
                f"{api_public_url}/saas/v1/webhooks/{endpoint.get('provider')}"
                if api_public_url and endpoint.get("provider") in {"whatsapp", "meta"}
                else ""
            )
        last_events = _recent_rows(
            conn,
            """
            SELECT ev.provider, ev.status, ev.received_at::text, ev.processed_at::text, ev.error,
                   COALESCE(ev.headers_json->>'x-scentra-endpoint-fallback', '') AS endpoint_fallback,
                   COALESCE(ep.endpoint_key, '') AS endpoint_key,
                   COALESCE(ep.last_seen_at::text, '') AS endpoint_last_seen_at
            FROM saas_webhook_events ev
            LEFT JOIN saas_webhook_endpoints ep ON ep.id = ev.endpoint_id
            WHERE ev.tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY ev.received_at DESC
            LIMIT :limit
            """,
            ctx.tenant_id,
        ) if _table_exists(conn, "saas_webhook_events") else []
        outbound_errors = _recent_rows(
            conn,
            """
            SELECT status, channel, recipient_external_id, attempts, error, updated_at::text
            FROM saas_outbound_messages
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND COALESCE(error, '') <> ''
            ORDER BY updated_at DESC
            LIMIT :limit
            """,
            ctx.tenant_id,
        ) if _table_exists(conn, "saas_outbound_messages") else []
        totals = conn.execute(
            text(
                """
                SELECT
                  (SELECT COUNT(*) FROM saas_conversations WHERE tenant_id = CAST(:tenant_id AS uuid))::int AS conversations,
                  (SELECT COUNT(*) FROM saas_messages WHERE tenant_id = CAST(:tenant_id AS uuid))::int AS messages,
                  (SELECT COUNT(*) FROM saas_knowledge_sources WHERE tenant_id = CAST(:tenant_id AS uuid) AND status = 'active')::int AS knowledge_sources
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().first()
        webhook_counts = _status_counts(conn, "saas_webhook_events", ctx.tenant_id)
        outbound_counts = _status_counts(conn, "saas_outbound_messages", ctx.tenant_id)
        ai_pending_counts = _status_counts(conn, "saas_ai_pending_replies", ctx.tenant_id)
        whatsapp_signal = _whatsapp_webhook_signal(conn, ctx.tenant_id)
        subscription_checks = _recent_subscription_checks(conn, ctx.tenant_id)
        social_meta = _social_meta_diagnostics(conn, ctx.tenant_id)
    return {
        "generated_at": generated_at,
        "diagnostic_type": "overview",
        "tenant": dict(tenant or {}),
        "runtime": {
            "api_ok": True,
            "embedded_worker_enabled": settings.saas_embedded_worker_enabled,
            "worker_idle_sec": settings.saas_worker_idle_sec,
            "meta_token_refresh_enabled": settings.saas_meta_token_refresh_enabled,
            "meta_token_refresh_interval_hours": settings.saas_meta_token_refresh_interval_hours,
            "cors_origins": settings.cors_origins,
        },
        "ai": {
            "enabled": bool(ai_settings.get("enabled")),
            "provider": ai_settings.get("provider_code"),
            "active_model": ai_settings.get("active_model"),
            "fallback_provider": ai_settings.get("fallback_provider_code"),
            "fallback_model": ai_settings.get("fallback_model"),
        },
        "credentials": [
            {
                "category": row["category"],
                "provider_code": row["provider_code"],
                "credential_key": row["credential_key"],
                "has_secret": bool(str(row.get("secret_hint") or "").strip()),
                "selected_model": (row.get("metadata_json") or {}).get("selected_model", "") if isinstance(row.get("metadata_json"), dict) else "",
                "updated_at": row["updated_at"],
            }
            for row in credentials
        ],
        "integrations": integration_rows,
        "webhooks": {"endpoints": webhooks, "events": webhook_counts, "last_events": last_events},
        "whatsapp_symptoms": whatsapp_signal,
        "whatsapp_subscription_checks": subscription_checks,
        "meta_social": social_meta,
        "queues": {
            "outbound": outbound_counts,
            "ai_pending": ai_pending_counts,
            "outbound_errors": outbound_errors,
        },
        "totals": dict(totals or {}),
    }


@router.post("/run")
def run_diagnostics_processors(
    limit: int = Query(25, ge=1, le=200),
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    started_at = _now_iso()
    result = {
        "webhooks": process_due_webhook_events(limit=limit, tenant_id=ctx.tenant_id),
        "ai": process_due_ai_replies(limit=limit, tenant_id=ctx.tenant_id),
        "outbound": process_due_outbound_messages(limit=limit, tenant_id=ctx.tenant_id),
    }
    return {
        "ok": True,
        "diagnostic_type": "processors",
        "started_at": started_at,
        "finished_at": _now_iso(),
        **result,
    }


@router.post("/whatsapp/simulate-inbound")
def simulate_whatsapp_inbound(
    payload: WhatsappInboundSimulationIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    started_at = _now_iso()
    from_phone = _safe_phone(payload.from_phone)
    body = str(payload.message or "").strip()[:1000] or "Mensaje de prueba desde diagnostico Scentra"
    contact_name = str(payload.contact_name or "").strip()[:120] or "Cliente Debug"
    now = int(time.time())
    provider_message_id = f"wamid.debug.{uuid4().hex}"

    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        integration = _load_debug_whatsapp_integration(conn, ctx.tenant_id)
        endpoint = _load_debug_webhook_endpoint(conn, ctx.tenant_id)
        safe_config = integration["safe_config"]
        phone_number_id = str(safe_config.get("phone_number_id") or "").strip()
        waba_id = str(safe_config.get("business_account_id") or "").strip()
        if not phone_number_id:
            raise HTTPException(status_code=400, detail="phone_number_id_missing")
        if not waba_id:
            raise HTTPException(status_code=400, detail="waba_id_missing")

        webhook_payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": waba_id,
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "display_phone_number": "debug",
                                    "phone_number_id": phone_number_id,
                                },
                                "contacts": [
                                    {
                                        "profile": {"name": contact_name},
                                        "wa_id": from_phone,
                                    }
                                ],
                                "messages": [
                                    {
                                        "from": from_phone,
                                        "id": provider_message_id,
                                        "timestamp": str(now),
                                        "text": {"body": body},
                                        "type": "text",
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }
        raw = json.dumps(webhook_payload, sort_keys=True).encode("utf-8")
        raw_sha256 = hashlib.sha256(raw).hexdigest()
        event_id = f"debug:{provider_message_id}"
        result = conn.execute(
            text(
                """
                INSERT INTO saas_webhook_events (
                    tenant_id,
                    endpoint_id,
                    provider,
                    event_id,
                    status,
                    headers_json,
                    payload_json,
                    raw_sha256
                )
                VALUES (
                    CAST(:tenant_id AS uuid),
                    CAST(:endpoint_id AS uuid),
                    :provider,
                    :event_id,
                    'received',
                    CAST(:headers_json AS jsonb),
                    CAST(:payload_json AS jsonb),
                    :raw_sha256
                )
                ON CONFLICT (tenant_id, provider, event_id) DO NOTHING
                """
            ),
            {
                "tenant_id": ctx.tenant_id,
                "endpoint_id": endpoint["id"],
                "provider": endpoint["provider"],
                "event_id": event_id,
                "headers_json": json.dumps({"x-scentra-debug": "simulate-inbound"}),
                "payload_json": json.dumps(webhook_payload),
                "raw_sha256": raw_sha256,
            },
        )
        inserted = int(result.rowcount or 0) > 0

    process_result = process_due_webhook_events(limit=10, tenant_id=ctx.tenant_id)

    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        conversation = conn.execute(
            text(
                """
                SELECT id::text, channel, external_contact_id, phone, display_name, last_message_text, unread_count, updated_at::text
                FROM saas_conversations
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND channel = 'whatsapp'
                  AND external_contact_id = :from_phone
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id, "from_phone": from_phone},
        ).mappings().first()
        message = conn.execute(
            text(
                """
                SELECT id::text, direction, msg_type, text, created_at::text
                FROM saas_messages
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND external_message_id = :provider_message_id
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id, "provider_message_id": provider_message_id},
        ).mappings().first()

    return {
        "ok": bool(message),
        "diagnostic_type": "whatsapp_simulate_inbound",
        "started_at": started_at,
        "finished_at": _now_iso(),
        "inserted_event": inserted,
        "tenant_id": ctx.tenant_id,
        "provider": endpoint["provider"],
        "endpoint_key": endpoint["endpoint_key"],
        "phone_number_id": phone_number_id,
        "waba_id": waba_id,
        "from_phone": from_phone,
        "provider_message_id": provider_message_id,
        "process_result": process_result,
        "conversation": dict(conversation or {}),
        "message": dict(message or {}),
        "interpretation": "scentra_pipeline_ok_meta_webhook_pending" if message else "scentra_pipeline_failed",
    }
