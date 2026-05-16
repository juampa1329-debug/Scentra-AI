from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection


TRANSIENT_META_CODES = {1, 2, 4, 17, 32, 613}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: Any, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _token_hint(access_token: str) -> str:
    token = _clean(access_token, 4000)
    if not token:
        return ""
    if len(token) <= 12:
        return f"{token[:3]}...{token[-3:]}"
    return f"{token[:6]}...{token[-6:]}"


def ensure_whatsapp_subscription_log_table(conn: Connection) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_whatsapp_subscription_checks (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                integration_id UUID NULL REFERENCES saas_integrations(id) ON DELETE SET NULL,
                waba_id TEXT NOT NULL,
                app_id TEXT NOT NULL DEFAULT '',
                access_token_hint TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'unknown',
                already_subscribed BOOLEAN NOT NULL DEFAULT FALSE,
                auto_subscribe_attempted BOOLEAN NOT NULL DEFAULT FALSE,
                final_subscribed BOOLEAN NOT NULL DEFAULT FALSE,
                http_status INTEGER NULL,
                meta_code INTEGER NULL,
                meta_error_type TEXT NOT NULL DEFAULT '',
                meta_error_message TEXT NOT NULL DEFAULT '',
                request_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                response_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                error TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_whatsapp_subscription_checks_tenant_created
            ON saas_whatsapp_subscription_checks (tenant_id, created_at DESC)
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_whatsapp_subscription_checks_waba_created
            ON saas_whatsapp_subscription_checks (waba_id, created_at DESC)
            """
        )
    )


def _graph_request(method: str, url: str, access_token: str, *, timeout_sec: int = 20) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        url,
        data=b"" if method.upper() in {"POST", "DELETE"} else None,
        method=method.upper(),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "ScentraAI/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return int(response.status or 200), json.loads(raw or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw or "{}")
        except Exception:
            payload = {"error": {"message": raw[:1000]}}
        return int(exc.code or 500), payload
    except Exception as exc:
        return 0, {"error": {"message": str(exc), "type": "NetworkError"}}


def _meta_error(payload: dict[str, Any]) -> dict[str, Any]:
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return {}
    return {
        "message": _clean(error.get("message"), 1200),
        "type": _clean(error.get("type"), 120),
        "code": int(error.get("code") or 0) if str(error.get("code") or "").isdigit() else 0,
        "subcode": int(error.get("error_subcode") or 0) if str(error.get("error_subcode") or "").isdigit() else 0,
        "is_transient": bool(error.get("is_transient")),
        "fbtrace_id": _clean(error.get("fbtrace_id"), 120),
    }


def _is_transient(status_code: int, payload: dict[str, Any]) -> bool:
    error = _meta_error(payload)
    return status_code in {0, 429, 500, 502, 503, 504} or bool(error.get("is_transient")) or int(error.get("code") or 0) in TRANSIENT_META_CODES


def _classify_error(status_code: int, payload: dict[str, Any]) -> str:
    error = _meta_error(payload)
    code = int(error.get("code") or 0)
    message = _clean(error.get("message"), 1200).lower()
    if status_code == 429 or code in {4, 17, 32, 613}:
        return "rate_limited"
    if code == 190 or "expired" in message or "invalid oauth" in message:
        return "token_expired_or_invalid"
    if code in {10, 200} or "permission" in message or "not have access" in message:
        return "insufficient_permissions"
    if code in {100, 803} or "does not exist" in message or "cannot be loaded" in message:
        return "waba_not_found_or_not_accessible"
    if error:
        return "meta_oauthexception"
    return "network_or_unknown_error"


def _sleep_before_retry(attempt: int) -> None:
    time.sleep(min(4, 0.5 * (2 ** max(0, attempt - 1))))


def _request_with_retry(method: str, url: str, access_token: str, *, retries: int, timeout_sec: int) -> tuple[int, dict[str, Any], int]:
    attempts = max(1, int(retries or 0) + 1)
    last_status = 0
    last_payload: dict[str, Any] = {}
    for attempt in range(1, attempts + 1):
        status, payload = _graph_request(method, url, access_token, timeout_sec=timeout_sec)
        last_status, last_payload = status, payload
        if status < 400 and not _meta_error(payload):
            return status, payload, attempt
        if attempt < attempts and _is_transient(status, payload):
            _sleep_before_retry(attempt)
            continue
        return status, payload, attempt
    return last_status, last_payload, attempts


def _subscription_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data") if isinstance(payload, dict) else []
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def _subscription_app_candidates(item: dict[str, Any]) -> set[str]:
    candidates = {
        _clean(item.get("id") or item.get("app_id") or item.get("application_id"), 80),
    }
    nested = item.get("whatsapp_business_api_data")
    if isinstance(nested, dict):
        candidates.add(_clean(nested.get("id") or nested.get("app_id") or nested.get("application_id"), 80))
    return {candidate for candidate in candidates if candidate}


def _is_subscribed(payload: dict[str, Any], app_id: str = "") -> bool:
    subscriptions = _subscription_list(payload)
    if not subscriptions:
        return False
    clean_app_id = _clean(app_id, 80)
    if not clean_app_id:
        return True
    for item in subscriptions:
        if clean_app_id in _subscription_app_candidates(item):
            return True
    return False


def _log_subscription_check(
    conn: Connection | None,
    *,
    tenant_id: str | None,
    integration_id: str | None,
    waba_id: str,
    app_id: str = "",
    access_token: str = "",
    result: dict[str, Any],
) -> None:
    if conn is None:
        return
    ensure_whatsapp_subscription_log_table(conn)
    error = _meta_error(result.get("last_response") or {})
    conn.execute(
        text(
            """
            INSERT INTO saas_whatsapp_subscription_checks (
                tenant_id, integration_id, waba_id, app_id, access_token_hint, status,
                already_subscribed, auto_subscribe_attempted, final_subscribed, http_status,
                meta_code, meta_error_type, meta_error_message, request_json, response_json, error
            )
            VALUES (
                CASE WHEN :tenant_id = '' THEN NULL ELSE CAST(:tenant_id AS uuid) END,
                CASE WHEN :integration_id = '' THEN NULL ELSE CAST(:integration_id AS uuid) END,
                :waba_id, :app_id, :access_token_hint, :status,
                :already_subscribed, :auto_subscribe_attempted, :final_subscribed, :http_status,
                :meta_code, :meta_error_type, :meta_error_message,
                CAST(:request_json AS jsonb), CAST(:response_json AS jsonb), :error
            )
            """
        ),
        {
            "tenant_id": tenant_id or "",
            "integration_id": integration_id or "",
            "waba_id": waba_id,
            "app_id": app_id or "",
            "access_token_hint": _token_hint(access_token),
            "status": _clean(result.get("status"), 80),
            "already_subscribed": bool(result.get("already_subscribed")),
            "auto_subscribe_attempted": bool(result.get("auto_subscribe_attempted")),
            "final_subscribed": bool(result.get("final_subscribed")),
            "http_status": int(result.get("http_status") or 0) or None,
            "meta_code": int(error.get("code") or 0) or None,
            "meta_error_type": _clean(error.get("type"), 120),
            "meta_error_message": _clean(error.get("message"), 1200),
            "request_json": json.dumps(result.get("request") or {}),
            "response_json": json.dumps(result.get("last_response") or {}),
            "error": _clean(result.get("error"), 1500),
        },
    )


def ensure_webhook_subscription(
    waba_id: str,
    access_token: str,
    *,
    graph_version: str = "v24.0",
    app_id: str = "",
    auto_subscribe: bool = True,
    retries: int = 2,
    timeout_sec: int = 20,
    conn: Connection | None = None,
    tenant_id: str | None = None,
    integration_id: str | None = None,
) -> dict[str, Any]:
    clean_waba_id = _clean(waba_id, 80)
    clean_token = _clean(access_token, 4000)
    version = _clean(graph_version, 20) or "v24.0"
    clean_app_id = _clean(app_id, 80)
    base_url = f"https://graph.facebook.com/{version}/{urllib.parse.quote(clean_waba_id)}"
    result: dict[str, Any] = {
        "ok": False,
        "status": "not_checked",
        "waba_id": clean_waba_id,
        "app_id": clean_app_id,
        "graph_version": version,
        "already_subscribed": False,
        "auto_subscribe_attempted": False,
        "final_subscribed": False,
        "subscribed_apps": [],
        "request": {"get": f"/{clean_waba_id}/subscribed_apps", "post": f"/{clean_waba_id}/subscribed_apps"},
        "last_response": {},
        "http_status": 0,
        "attempts": {"get": 0, "post": 0, "verify": 0},
        "checked_at": _utc_now(),
    }
    if not clean_waba_id:
        result.update({"status": "missing_waba_id", "error": "waba_id_required"})
        _log_subscription_check(conn, tenant_id=tenant_id, integration_id=integration_id, waba_id=clean_waba_id, app_id=clean_app_id, access_token=clean_token, result=result)
        return result
    if not clean_token:
        result.update({"status": "missing_access_token", "error": "meta_access_token_required"})
        _log_subscription_check(conn, tenant_id=tenant_id, integration_id=integration_id, waba_id=clean_waba_id, app_id=clean_app_id, access_token=clean_token, result=result)
        return result

    print(f"[WhatsApp] Checking subscribed_apps for WABA {clean_waba_id}", flush=True)
    get_url = f"{base_url}/subscribed_apps"
    status, payload, attempts = _request_with_retry("GET", get_url, clean_token, retries=retries, timeout_sec=timeout_sec)
    result["http_status"] = status
    result["last_response"] = payload
    result["attempts"]["get"] = attempts
    if status >= 400 or _meta_error(payload):
        error_status = _classify_error(status, payload)
        result.update({"status": error_status, "error": _clean((_meta_error(payload) or {}).get("message") or payload, 1500)})
        _log_subscription_check(conn, tenant_id=tenant_id, integration_id=integration_id, waba_id=clean_waba_id, app_id=clean_app_id, access_token=clean_token, result=result)
        return result

    subscriptions = _subscription_list(payload)
    result["subscribed_apps"] = subscriptions
    already_subscribed = _is_subscribed(payload, clean_app_id)
    result["already_subscribed"] = already_subscribed
    if already_subscribed:
        print("[WhatsApp] Already subscribed.", flush=True)
        result.update({"ok": True, "status": "already_subscribed", "final_subscribed": True})
        _log_subscription_check(conn, tenant_id=tenant_id, integration_id=integration_id, waba_id=clean_waba_id, app_id=clean_app_id, access_token=clean_token, result=result)
        return result

    if not auto_subscribe:
        result.update({"ok": True, "status": "not_subscribed", "final_subscribed": False})
        _log_subscription_check(conn, tenant_id=tenant_id, integration_id=integration_id, waba_id=clean_waba_id, app_id=clean_app_id, access_token=clean_token, result=result)
        return result

    print("[WhatsApp] WABA not subscribed. Auto-subscribing...", flush=True)
    result["auto_subscribe_attempted"] = True
    post_status, post_payload, post_attempts = _request_with_retry("POST", get_url, clean_token, retries=retries, timeout_sec=timeout_sec)
    result["http_status"] = post_status
    result["last_response"] = post_payload
    result["attempts"]["post"] = post_attempts
    if post_status >= 400 or _meta_error(post_payload):
        error_status = _classify_error(post_status, post_payload)
        result.update({"status": error_status, "error": _clean((_meta_error(post_payload) or {}).get("message") or post_payload, 1500)})
        _log_subscription_check(conn, tenant_id=tenant_id, integration_id=integration_id, waba_id=clean_waba_id, app_id=clean_app_id, access_token=clean_token, result=result)
        return result

    verify_status, verify_payload, verify_attempts = _request_with_retry("GET", get_url, clean_token, retries=retries, timeout_sec=timeout_sec)
    result["http_status"] = verify_status
    result["last_response"] = verify_payload
    result["attempts"]["verify"] = verify_attempts
    final_subscribed = verify_status < 400 and not _meta_error(verify_payload) and _is_subscribed(verify_payload, clean_app_id)
    result["subscribed_apps"] = _subscription_list(verify_payload)
    result["final_subscribed"] = final_subscribed
    result["ok"] = final_subscribed
    result["status"] = "subscription_successful" if final_subscribed else "subscription_not_confirmed"
    if final_subscribed:
        print("[WhatsApp] Subscription successful.", flush=True)
    else:
        print("[WhatsApp] Subscription not confirmed after POST.", flush=True)
        result["error"] = _clean((_meta_error(verify_payload) or {}).get("message") or "subscription_not_confirmed", 1500)
    _log_subscription_check(conn, tenant_id=tenant_id, integration_id=integration_id, waba_id=clean_waba_id, app_id=clean_app_id, access_token=clean_token, result=result)
    return result


def list_waba_phone_numbers(waba_id: str, access_token: str, *, graph_version: str = "v24.0", retries: int = 1, timeout_sec: int = 20) -> dict[str, Any]:
    clean_waba_id = _clean(waba_id, 80)
    version = _clean(graph_version, 20) or "v24.0"
    fields = "id,display_phone_number,verified_name,quality_rating,code_verification_status,name_status,platform_type"
    query = urllib.parse.urlencode({"fields": fields})
    url = f"https://graph.facebook.com/{version}/{urllib.parse.quote(clean_waba_id)}/phone_numbers?{query}"
    status, payload, attempts = _request_with_retry("GET", url, access_token, retries=retries, timeout_sec=timeout_sec)
    phones = payload.get("data") if isinstance(payload, dict) else []
    return {
        "ok": status < 400 and not _meta_error(payload),
        "http_status": status,
        "attempts": attempts,
        "phone_numbers": phones if isinstance(phones, list) else [],
        "response": payload,
        "error": _clean((_meta_error(payload) or {}).get("message"), 1200),
    }


ensureWebhookSubscription = ensure_webhook_subscription
