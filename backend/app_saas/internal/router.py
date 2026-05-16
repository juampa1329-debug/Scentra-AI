from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text

from app_saas.db import db_session, set_tenant_context
from app_saas.integrations.router import _integration_token, _safe_config_for_output, _waba_id_from_config
from app_saas.integrations.whatsapp_subscription import (
    ensure_webhook_subscription,
    ensure_whatsapp_subscription_log_table,
    list_waba_phone_numbers,
)
from app_saas.shared.security import AuthContext, require_role

router = APIRouter(prefix="/internal", tags=["saas-internal"])


def _as_config(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _load_meta_whatsapp_integration(conn, tenant_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            """
            SELECT id::text, provider, channel, status, config_json, last_sync_at::text
            FROM saas_integrations
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND provider = 'meta'
              AND channel = 'whatsapp'
            ORDER BY updated_at DESC NULLS LAST
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    return dict(row) if row else None


def _active_whatsapp_webhook(conn, tenant_id: str) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            SELECT id::text, provider, endpoint_key, is_active, signature_required, last_seen_at::text, updated_at::text
            FROM saas_webhook_endpoints
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND provider IN ('whatsapp', 'meta')
            ORDER BY is_active DESC, updated_at DESC NULLS LAST
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    return dict(row or {})


def _last_subscription_logs(conn, tenant_id: str, waba_id: str) -> list[dict[str, Any]]:
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
              AND waba_id = :waba_id
            ORDER BY created_at DESC
            LIMIT 10
            """
        ),
        {"tenant_id": tenant_id, "waba_id": waba_id},
    ).mappings().all()
    return [dict(row) for row in rows]


@router.get("/whatsapp/check-subscription")
def check_whatsapp_subscription(
    wabaId: str = Query("", max_length=80),
    autoSubscribe: bool = Query(True),
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        integration = _load_meta_whatsapp_integration(conn, ctx.tenant_id)
        if not integration:
            return {"ok": False, "status": "meta_whatsapp_integration_missing", "subscription": None}
        config = _as_config(integration.get("config_json"))
        token = _integration_token(config)
        waba_id = str(wabaId or "").strip() or _waba_id_from_config(config)
        version = str(config.get("graph_api_version") or "v24.0").strip() or "v24.0"
        app_id = str(config.get("app_id") or "").strip()
        subscription = ensure_webhook_subscription(
            waba_id,
            token,
            graph_version=version,
            app_id=app_id,
            auto_subscribe=autoSubscribe,
            retries=2,
            conn=conn,
            tenant_id=ctx.tenant_id,
            integration_id=integration["id"],
        )
        phones = list_waba_phone_numbers(waba_id, token, graph_version=version, retries=1) if token and waba_id else {"ok": False, "phone_numbers": [], "error": "token_or_waba_missing"}
        webhook = _active_whatsapp_webhook(conn, ctx.tenant_id)
        config["last_webhook_subscription_check"] = {
            "status": subscription.get("status"),
            "ok": bool(subscription.get("ok")),
            "final_subscribed": bool(subscription.get("final_subscribed")),
            "auto_subscribe_attempted": bool(subscription.get("auto_subscribe_attempted")),
            "checked_at": subscription.get("checked_at"),
            "error": str(subscription.get("error") or "")[:500],
        }
        if phones.get("ok"):
            config["phone_numbers"] = phones.get("phone_numbers") or []
        conn.execute(
            text(
                """
                UPDATE saas_integrations
                SET config_json = CAST(:config_json AS jsonb), last_sync_at = NOW(), updated_at = NOW()
                WHERE id = CAST(:integration_id AS uuid)
                """
            ),
            {"integration_id": integration["id"], "config_json": json.dumps(config)},
        )
        logs = _last_subscription_logs(conn, ctx.tenant_id, waba_id)
        safe_config = _safe_config_for_output(config)

    return {
        "ok": bool(subscription.get("ok")),
        "status": subscription.get("status"),
        "waba_id": waba_id,
        "app_id": app_id,
        "graph_version": version,
        "is_subscribed": bool(subscription.get("final_subscribed")),
        "auto_subscribe_attempted": bool(subscription.get("auto_subscribe_attempted")),
        "subscription": subscription,
        "phone_numbers": phones.get("phone_numbers") or [],
        "phone_numbers_status": {"ok": bool(phones.get("ok")), "error": phones.get("error") or "", "http_status": phones.get("http_status")},
        "webhook_status": {
            "configured": bool(webhook),
            "active": bool(webhook.get("is_active")),
            "provider": webhook.get("provider") or "",
            "endpoint_key": webhook.get("endpoint_key") or "",
            "last_seen_at": webhook.get("last_seen_at") or "",
            "signature_required": bool(webhook.get("signature_required")),
        },
        "connected_app_id": safe_config.get("app_id") or app_id,
        "last_logs": logs,
    }
