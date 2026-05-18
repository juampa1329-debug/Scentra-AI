from __future__ import annotations

import json
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app_saas.billing.limits import ensure_integration_quota
from app_saas.config import settings
from app_saas.db import db_session, set_tenant_context
from app_saas.integrations.instagram_graph import (
    INSTAGRAM_OAUTH_SCOPES,
    INSTAGRAM_SUBSCRIBED_FIELDS,
    classify_meta_error,
    discover_instagram_assets,
    ensure_instagram_log_tables,
    ensure_instagram_page_subscription,
    graph_request,
    meta_error,
    request_with_retry,
    token_hint,
    utc_now,
)
from app_saas.shared.secrets import decrypt_secret, encrypt_secret, mask_secret
from app_saas.shared.security import AuthContext, hash_secret, new_secret, require_role, verify_secret
from app_saas.webhooks.router import _normalize_endpoint_key

router = APIRouter(prefix="/integrations/instagram", tags=["saas-instagram"])


def _graph_version() -> str:
    version = str(settings.scentra_meta_graph_version or "v24.0").strip()
    return version if version.startswith("v") else f"v{version}"


def _app_id() -> str:
    return str(settings.scentra_meta_app_id or "").strip()


def _app_secret() -> str:
    return str(settings.scentra_meta_app_secret or "").strip()


def _api_public_url() -> str:
    return str(settings.scentra_api_public_url or "https://api.scentra-ai.online").strip().rstrip("/")


def _app_public_url() -> str:
    return str(settings.scentra_app_public_url or "https://app.scentra-ai.online").strip().rstrip("/")


def _oauth_redirect_uri() -> str:
    return f"{_api_public_url()}/saas/v1/integrations/instagram/oauth/callback"


def _safe_state_row(row: dict[str, Any]) -> dict[str, Any]:
    result = row.get("result_json") if isinstance(row.get("result_json"), dict) else {}
    assets = result.get("assets") if isinstance(result.get("assets"), list) else []
    return {
        "status": row.get("status") or "",
        "error": row.get("error") or "",
        "expires_at": row.get("expires_at") or "",
        "assets": assets,
        "businesses": result.get("businesses") if isinstance(result.get("businesses"), list) else [],
        "checked_at": result.get("checked_at") or "",
    }


def _load_state(conn, state: str, ctx: AuthContext | None = None) -> dict[str, Any]:
    filters = ["state_hash = :state_hash"]
    params = {"state_hash": hash_secret(state)}
    if ctx is not None:
        filters.append("tenant_id = CAST(:tenant_id AS uuid)")
        filters.append("user_id = CAST(:user_id AS uuid)")
        params["tenant_id"] = ctx.tenant_id
        params["user_id"] = ctx.user_id
    row = conn.execute(
        text(
            f"""
            SELECT id::text, tenant_id::text, user_id::text, state_hash, redirect_uri, result_json, status, error, expires_at::text
            FROM saas_instagram_oauth_states
            WHERE {' AND '.join(filters)}
            LIMIT 1
            """
        ),
        params,
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="instagram_oauth_state_not_found")
    return dict(row)


def _exchange_code(code: str, redirect_uri: str) -> dict[str, Any]:
    app_id = _app_id()
    app_secret = _app_secret()
    if not app_id or not app_secret:
        raise HTTPException(status_code=500, detail="meta_app_credentials_missing")
    status, payload = graph_request(
        "GET",
        "/oauth/access_token",
        "",
        graph_version=_graph_version(),
        params={
            "client_id": app_id,
            "client_secret": app_secret,
            "redirect_uri": redirect_uri,
            "code": code,
        },
    )
    if status >= 400 or meta_error(payload):
        raise HTTPException(status_code=502, detail={"code": "meta_oauth_exchange_failed", "meta": payload})
    short_token = str(payload.get("access_token") or "").strip()
    status2, payload2 = graph_request(
        "GET",
        "/oauth/access_token",
        "",
        graph_version=_graph_version(),
        params={
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": short_token,
        },
    )
    if status2 < 400 and not meta_error(payload2) and payload2.get("access_token"):
        return {**payload2, "short_lived_token_hint": token_hint(short_token)}
    return {**payload, "exchange_warning": payload2}


def _asset_by_page(result: dict[str, Any], page_id: str, instagram_business_account_id: str = "") -> dict[str, Any]:
    raw_pages = result.get("raw_pages") if isinstance(result.get("raw_pages"), list) else []
    for page in raw_pages:
        if not isinstance(page, dict):
            continue
        ig = page.get("instagram_business_account") if isinstance(page.get("instagram_business_account"), dict) else {}
        if str(page.get("id") or "") == str(page_id) and (not instagram_business_account_id or str(ig.get("id") or "") == str(instagram_business_account_id)):
            return page
    raise HTTPException(status_code=404, detail="instagram_asset_not_found_in_oauth_result")


def _ensure_instagram_endpoint(conn, tenant_id: str) -> dict[str, Any]:
    existing = conn.execute(
        text(
            """
            SELECT id::text, provider, endpoint_key, is_active, signature_required, last_seen_at::text
            FROM saas_webhook_endpoints
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND provider = 'instagram'
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    if existing:
        return dict(existing)
    endpoint_key = _normalize_endpoint_key(new_secret("igwh"))
    # The global route is used by Meta's app-level webhook; this tenant endpoint is kept for local observability/FK consistency.
    row = conn.execute(
        text(
            """
            INSERT INTO saas_webhook_endpoints (
                tenant_id, provider, endpoint_key, verify_secret_ref, verify_token_hash,
                signature_required, is_active
            )
            VALUES (
                CAST(:tenant_id AS uuid), 'instagram', :endpoint_key, 'platform:instagram-global', '', FALSE, TRUE
            )
            RETURNING id::text, provider, endpoint_key, is_active, signature_required, last_seen_at::text
            """
        ),
        {"tenant_id": tenant_id, "endpoint_key": endpoint_key},
    ).mappings().first()
    return dict(row)


@router.post("/oauth/start")
def start_instagram_oauth(ctx: AuthContext = Depends(require_role("owner", "admin"))):
    app_id = _app_id()
    if not app_id:
        raise HTTPException(status_code=500, detail="SCENTRA_META_APP_ID_missing")
    state = new_secret("igstate")
    redirect_uri = _oauth_redirect_uri()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        ensure_instagram_log_tables(conn)
        conn.execute(
            text(
                """
                INSERT INTO saas_instagram_oauth_states (tenant_id, user_id, state_hash, redirect_uri, expires_at)
                VALUES (CAST(:tenant_id AS uuid), CAST(:user_id AS uuid), :state_hash, :redirect_uri, :expires_at)
                """
            ),
            {"tenant_id": ctx.tenant_id, "user_id": ctx.user_id, "state_hash": hash_secret(state), "redirect_uri": redirect_uri, "expires_at": expires_at.replace(tzinfo=None)},
        )
    params = urllib.parse.urlencode(
        {
            "client_id": app_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "response_type": "code",
            "scope": ",".join(INSTAGRAM_OAUTH_SCOPES),
        }
    )
    return {
        "ok": True,
        "state": state,
        "auth_url": f"https://www.facebook.com/{_graph_version()}/dialog/oauth?{params}",
        "scopes": INSTAGRAM_OAUTH_SCOPES,
        "callback_url": redirect_uri,
    }


@router.get("/oauth/callback")
def instagram_oauth_callback(code: str = Query(""), state: str = Query(""), error: str = Query(""), error_description: str = Query("")):
    frontend = _app_public_url()
    if not state:
        return {"ok": False, "error": "state_required"}
    with db_session() as conn:
        ensure_instagram_log_tables(conn)
        try:
            row = _load_state(conn, state)
        except HTTPException:
            return {"ok": False, "error": "invalid_state"}
        if error:
            conn.execute(text("UPDATE saas_instagram_oauth_states SET status = 'error', error = :error, updated_at = NOW() WHERE id = CAST(:id AS uuid)"), {"id": row["id"], "error": f"{error}:{error_description}"[:1000]})
            return {"ok": False, "error": error, "error_description": error_description}
        if not code:
            return {"ok": False, "error": "code_required"}
        try:
            token_payload = _exchange_code(code, row["redirect_uri"])
            user_access_token = str(token_payload.get("access_token") or "").strip()
            discovery = discover_instagram_assets(user_access_token, graph_version=_graph_version())
            secured_discovery = dict(discovery)
            secured_pages: list[dict[str, Any]] = []
            for raw_page in discovery.get("raw_pages") if isinstance(discovery.get("raw_pages"), list) else []:
                page = dict(raw_page or {})
                page_token = str(page.get("access_token") or "").strip()
                if page_token:
                    page["access_token"] = encrypt_secret(page_token)
                    page["access_token_hint"] = token_hint(page_token)
                secured_pages.append(page)
            secured_discovery["raw_pages"] = secured_pages
            result = {
                **secured_discovery,
                "user_access_token": encrypt_secret(user_access_token),
                "user_access_token_hint": token_hint(user_access_token),
                "token_expires_in": token_payload.get("expires_in"),
                "oauth_completed_at": utc_now(),
            }
            conn.execute(
                text(
                    """
                    UPDATE saas_instagram_oauth_states
                    SET result_json = CAST(:result_json AS jsonb), status = 'ready', error = '', updated_at = NOW()
                    WHERE id = CAST(:id AS uuid)
                    """
                ),
                {"id": row["id"], "result_json": json.dumps(result)},
            )
        except Exception as exc:
            conn.execute(text("UPDATE saas_instagram_oauth_states SET status = 'error', error = :error, updated_at = NOW() WHERE id = CAST(:id AS uuid)"), {"id": row["id"], "error": str(exc)[:1000]})
            return {"ok": False, "error": str(exc)[:500]}
    return {"ok": True, "message": "Instagram conectado. Puedes volver a Scentra y seleccionar la cuenta.", "return_to": f"{frontend}/?instagram_oauth=success"}


@router.get("/oauth/assets")
def instagram_oauth_assets(state: str = Query(""), ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        ensure_instagram_log_tables(conn)
        row = _load_state(conn, state, ctx)
    return {"ok": row.get("status") == "ready", **_safe_state_row(row)}


@router.post("/connect")
def connect_instagram_asset(payload: dict[str, Any], ctx: AuthContext = Depends(require_role("owner", "admin"))):
    state = str(payload.get("state") or "").strip()
    page_id = str(payload.get("page_id") or "").strip()
    instagram_id = str(payload.get("instagram_business_account_id") or "").strip()
    if not state or not page_id or not instagram_id:
        raise HTTPException(status_code=400, detail="state_page_id_and_instagram_business_account_id_required")
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        ensure_instagram_log_tables(conn)
        ensure_integration_quota(conn, ctx.tenant_id, "meta", "instagram")
        row = _load_state(conn, state, ctx)
        if row.get("status") != "ready":
            raise HTTPException(status_code=409, detail="instagram_oauth_not_ready")
        result = row.get("result_json") if isinstance(row.get("result_json"), dict) else {}
        page = _asset_by_page(result, page_id, instagram_id)
        ig = page.get("instagram_business_account") if isinstance(page.get("instagram_business_account"), dict) else {}
        page_access_token = decrypt_secret(str(page.get("access_token") or "").strip()) or str(page.get("access_token") or "").strip()
        if not page_access_token:
            raise HTTPException(status_code=400, detail="page_access_token_missing")
        endpoint = _ensure_instagram_endpoint(conn, ctx.tenant_id)
        config = {
            "dispatch_mode": "instagram_graph",
            "page_id": page_id,
            "page_name": str(page.get("name") or ""),
            "business_id": str(page.get("business_id") or ""),
            "business_name": str(page.get("business_name") or ""),
            "instagram_business_account_id": instagram_id,
            "instagram_username": str(ig.get("username") or ig.get("name") or ""),
            "instagram_profile_picture_url": str(ig.get("profile_picture_url") or ""),
            "app_id": _app_id(),
            "graph_api_version": _graph_version(),
            "page_access_token": encrypt_secret(page_access_token),
            "page_access_token_hint": token_hint(page_access_token),
            "user_access_token": result.get("user_access_token") or "",
            "user_access_token_hint": result.get("user_access_token_hint") or "",
            "webhook_callback_url": f"{_api_public_url()}/saas/v1/webhooks/instagram",
            "webhook_endpoint_key": endpoint.get("endpoint_key") or "",
            "subscribed_fields": INSTAGRAM_SUBSCRIBED_FIELDS,
        }
        integration = conn.execute(
            text(
                """
                INSERT INTO saas_integrations (tenant_id, provider, channel, status, secret_ref, config_json, updated_at)
                VALUES (CAST(:tenant_id AS uuid), 'meta', 'instagram', 'connected', 'tenant:meta:instagram', CAST(:config_json AS jsonb), NOW())
                ON CONFLICT (tenant_id, provider, channel)
                DO UPDATE SET status = 'connected', secret_ref = EXCLUDED.secret_ref, config_json = EXCLUDED.config_json, updated_at = NOW()
                RETURNING id::text, provider, channel, status, config_json, last_sync_at::text
                """
            ),
            {"tenant_id": ctx.tenant_id, "config_json": json.dumps(config)},
        ).mappings().first()
        subscription = ensure_instagram_page_subscription(
            page_id,
            page_access_token,
            graph_version=_graph_version(),
            app_id=_app_id(),
            instagram_business_account_id=instagram_id,
            auto_subscribe=True,
            conn=conn,
            tenant_id=ctx.tenant_id,
            integration_id=integration["id"],
        )
        config["last_instagram_subscription_check"] = {
            "status": subscription.get("status"),
            "ok": bool(subscription.get("ok")),
            "final_subscribed": bool(subscription.get("final_subscribed")),
            "auto_subscribe_attempted": bool(subscription.get("auto_subscribe_attempted")),
            "checked_at": subscription.get("checked_at"),
            "error": str(subscription.get("error") or "")[:500],
        }
        conn.execute(text("UPDATE saas_integrations SET config_json = CAST(:config_json AS jsonb), last_sync_at = NOW(), updated_at = NOW() WHERE id = CAST(:id AS uuid)"), {"id": integration["id"], "config_json": json.dumps(config)})
        conn.execute(text("UPDATE saas_instagram_oauth_states SET status = 'connected', updated_at = NOW() WHERE id = CAST(:id AS uuid)"), {"id": row["id"]})
    return {"ok": True, "integration_id": integration["id"], "page_id": page_id, "instagram_business_account_id": instagram_id, "subscription": subscription}


@router.get("/diagnostics")
def instagram_diagnostics(ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        ensure_instagram_log_tables(conn)
        integration = conn.execute(
            text(
                """
                SELECT id::text, provider, channel, status, config_json, last_sync_at::text
                FROM saas_integrations
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND provider = 'meta'
                  AND channel = 'instagram'
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().first()
        if not integration:
            return {"ok": False, "status": "instagram_not_connected"}
        config = integration.get("config_json") if isinstance(integration.get("config_json"), dict) else {}
        page_token = decrypt_secret(str(config.get("page_access_token") or ""))
        page_id = str(config.get("page_id") or "")
        instagram_id = str(config.get("instagram_business_account_id") or "")
        subscription = ensure_instagram_page_subscription(
            page_id,
            page_token,
            graph_version=str(config.get("graph_api_version") or _graph_version()),
            app_id=str(config.get("app_id") or _app_id()),
            instagram_business_account_id=instagram_id,
            auto_subscribe=True,
            conn=conn,
            tenant_id=ctx.tenant_id,
            integration_id=integration["id"],
        )
        permissions_status, permissions_payload, _ = request_with_retry("GET", "/me/permissions", page_token, graph_version=str(config.get("graph_api_version") or _graph_version()), retries=1) if page_token else (0, {"error": "page_token_missing"}, 0)
        last_message = conn.execute(
            text(
                """
                SELECT id::text, external_contact_id, display_name, last_message_text, last_message_at::text, unread_count
                FROM saas_conversations
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND channel = 'instagram'
                ORDER BY last_message_at DESC NULLS LAST, updated_at DESC
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().first()
        webhook = conn.execute(
            text(
                """
                SELECT endpoint_key, is_active, signature_required, last_seen_at::text
                FROM saas_webhook_endpoints
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND provider = 'instagram'
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().first()
        recent_errors = conn.execute(
            text(
                """
                SELECT provider, event_id, status, error, received_at::text
                FROM saas_webhook_events
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND provider = 'instagram'
                  AND COALESCE(error, '') <> ''
                ORDER BY received_at DESC
                LIMIT 10
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().all()
        checks = conn.execute(
            text(
                """
                SELECT page_id, instagram_business_account_id, status, final_subscribed, auto_subscribe_attempted, http_status, meta_error_type, meta_error_message, error, created_at::text
                FROM saas_instagram_subscription_checks
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                ORDER BY created_at DESC
                LIMIT 10
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().all()
    safe_config = dict(config)
    for key in ("page_access_token", "user_access_token"):
        if safe_config.get(key):
            safe_config[key] = mask_secret(str(safe_config[key]))
            safe_config[f"has_{key}"] = True
    return {
        "ok": True,
        "status": integration["status"],
        "page_id": page_id,
        "page_name": config.get("page_name") or "",
        "instagram_business_account_id": instagram_id,
        "instagram_username": config.get("instagram_username") or "",
        "app_id": config.get("app_id") or _app_id(),
        "graph_version": config.get("graph_api_version") or _graph_version(),
        "webhook_callback_url": f"{_api_public_url()}/saas/v1/webhooks/instagram",
        "webhook_status": dict(webhook or {}),
        "subscription": subscription,
        "permissions": {"ok": permissions_status < 400 and not meta_error(permissions_payload), "response": permissions_payload, "error_status": classify_meta_error(permissions_status, permissions_payload) if permissions_status >= 400 or meta_error(permissions_payload) else ""},
        "last_message": dict(last_message or {}),
        "recent_errors": [dict(row) for row in recent_errors],
        "subscription_checks": [dict(row) for row in checks],
        "config": safe_config,
    }
