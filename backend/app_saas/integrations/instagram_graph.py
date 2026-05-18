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

INSTAGRAM_OAUTH_SCOPES = [
    "instagram_basic",
    "instagram_manage_messages",
    "pages_manage_metadata",
    "pages_messaging",
    "pages_read_engagement",
    "business_management",
]

INSTAGRAM_SUBSCRIBED_FIELDS = ["messages", "messaging_postbacks", "comments", "mentions"]
TRANSIENT_META_CODES = {1, 2, 4, 17, 32, 613}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean(value: Any, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def token_hint(access_token: str) -> str:
    token = clean(access_token, 4000)
    if not token:
        return ""
    if len(token) <= 12:
        return f"{token[:3]}...{token[-3:]}"
    return f"{token[:6]}...{token[-6:]}"


def ensure_instagram_log_tables(conn: Connection) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_instagram_oauth_states (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                user_id UUID NOT NULL REFERENCES saas_users(id) ON DELETE CASCADE,
                state_hash TEXT NOT NULL UNIQUE,
                redirect_uri TEXT NOT NULL DEFAULT '',
                result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                status TEXT NOT NULL DEFAULT 'pending',
                error TEXT NOT NULL DEFAULT '',
                expires_at TIMESTAMP NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_instagram_oauth_states_tenant_created
            ON saas_instagram_oauth_states (tenant_id, created_at DESC)
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_instagram_subscription_checks (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                integration_id UUID NULL REFERENCES saas_integrations(id) ON DELETE SET NULL,
                page_id TEXT NOT NULL,
                instagram_business_account_id TEXT NOT NULL DEFAULT '',
                app_id TEXT NOT NULL DEFAULT '',
                access_token_hint TEXT NOT NULL DEFAULT '',
                subscribed_fields TEXT NOT NULL DEFAULT '',
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
            CREATE INDEX IF NOT EXISTS idx_saas_instagram_subscription_checks_tenant_created
            ON saas_instagram_subscription_checks (tenant_id, created_at DESC)
            """
        )
    )


def graph_request(
    method: str,
    path_or_url: str,
    access_token: str = "",
    *,
    graph_version: str = "v24.0",
    params: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    timeout_sec: int = 20,
) -> tuple[int, dict[str, Any]]:
    version = clean(graph_version, 20) or "v24.0"
    base = "https://graph.facebook.com"
    url = path_or_url if path_or_url.startswith("http") else f"{base}/{version}/{path_or_url.lstrip('/')}"
    query = dict(params or {})
    if access_token:
        query["access_token"] = access_token
    if query:
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}{urllib.parse.urlencode(query)}"
    body = None
    headers = {"Accept": "application/json", "User-Agent": "ScentraAI/1.0"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif method.upper() in {"POST", "DELETE"}:
        body = b""
    request = urllib.request.Request(url, data=body, method=method.upper(), headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return int(response.status or 200), json.loads(raw or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw or "{}")
        except Exception:
            parsed = {"error": {"message": raw[:1000]}}
        return int(exc.code or 500), parsed
    except Exception as exc:
        return 0, {"error": {"type": "NetworkError", "message": str(exc)}}


def meta_error(payload: dict[str, Any]) -> dict[str, Any]:
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return {}
    code_raw = error.get("code")
    subcode_raw = error.get("error_subcode")
    return {
        "message": clean(error.get("message"), 1200),
        "type": clean(error.get("type"), 120),
        "code": int(code_raw or 0) if str(code_raw or "").isdigit() else 0,
        "subcode": int(subcode_raw or 0) if str(subcode_raw or "").isdigit() else 0,
        "is_transient": bool(error.get("is_transient")),
        "fbtrace_id": clean(error.get("fbtrace_id"), 120),
    }


def is_transient(status_code: int, payload: dict[str, Any]) -> bool:
    error = meta_error(payload)
    return status_code in {0, 429, 500, 502, 503, 504} or bool(error.get("is_transient")) or int(error.get("code") or 0) in TRANSIENT_META_CODES


def classify_meta_error(status_code: int, payload: dict[str, Any]) -> str:
    error = meta_error(payload)
    code = int(error.get("code") or 0)
    message = clean(error.get("message"), 1200).lower()
    if status_code == 429 or code in {4, 17, 32, 613}:
        return "rate_limited"
    if code == 190 or "expired" in message or "invalid oauth" in message:
        return "token_expired_or_invalid"
    if code in {10, 200} or "permission" in message or "not have access" in message:
        return "insufficient_permissions"
    if code in {100, 803} or "does not exist" in message or "cannot be loaded" in message:
        return "asset_not_found_or_not_accessible"
    if error:
        return "meta_oauthexception"
    return "network_or_unknown_error"


def request_with_retry(method: str, path_or_url: str, access_token: str = "", *, graph_version: str = "v24.0", params: dict[str, Any] | None = None, payload: dict[str, Any] | None = None, retries: int = 2, timeout_sec: int = 20) -> tuple[int, dict[str, Any], int]:
    attempts = max(1, int(retries or 0) + 1)
    last_status = 0
    last_payload: dict[str, Any] = {}
    for attempt in range(1, attempts + 1):
        status, response = graph_request(method, path_or_url, access_token, graph_version=graph_version, params=params, payload=payload, timeout_sec=timeout_sec)
        last_status, last_payload = status, response
        if status < 400 and not meta_error(response):
            return status, response, attempt
        if attempt < attempts and is_transient(status, response):
            time.sleep(min(4, 0.5 * (2 ** max(0, attempt - 1))))
            continue
        return status, response, attempt
    return last_status, last_payload, attempts


def _subscription_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data") if isinstance(payload, dict) else []
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def _is_page_subscribed(payload: dict[str, Any], app_id: str = "") -> bool:
    items = _subscription_items(payload)
    if not items:
        return False
    clean_app_id = clean(app_id, 80)
    if not clean_app_id:
        return True
    return any(clean(item.get("id") or item.get("app_id") or item.get("application_id"), 80) == clean_app_id for item in items)


def _log_subscription_check(conn: Connection | None, *, tenant_id: str | None, integration_id: str | None, page_id: str, instagram_business_account_id: str = "", app_id: str = "", page_access_token: str = "", result: dict[str, Any]) -> None:
    if conn is None:
        return
    ensure_instagram_log_tables(conn)
    error = meta_error(result.get("last_response") or {})
    conn.execute(
        text(
            """
            INSERT INTO saas_instagram_subscription_checks (
                tenant_id, integration_id, page_id, instagram_business_account_id, app_id, access_token_hint,
                subscribed_fields, status, already_subscribed, auto_subscribe_attempted, final_subscribed,
                http_status, meta_code, meta_error_type, meta_error_message, request_json, response_json, error
            )
            VALUES (
                CASE WHEN :tenant_id = '' THEN NULL ELSE CAST(:tenant_id AS uuid) END,
                CASE WHEN :integration_id = '' THEN NULL ELSE CAST(:integration_id AS uuid) END,
                :page_id, :instagram_business_account_id, :app_id, :access_token_hint,
                :subscribed_fields, :status, :already_subscribed, :auto_subscribe_attempted, :final_subscribed,
                :http_status, :meta_code, :meta_error_type, :meta_error_message,
                CAST(:request_json AS jsonb), CAST(:response_json AS jsonb), :error
            )
            """
        ),
        {
            "tenant_id": tenant_id or "",
            "integration_id": integration_id or "",
            "page_id": page_id,
            "instagram_business_account_id": instagram_business_account_id,
            "app_id": app_id,
            "access_token_hint": token_hint(page_access_token),
            "subscribed_fields": ",".join(result.get("subscribed_fields") or []),
            "status": clean(result.get("status"), 80),
            "already_subscribed": bool(result.get("already_subscribed")),
            "auto_subscribe_attempted": bool(result.get("auto_subscribe_attempted")),
            "final_subscribed": bool(result.get("final_subscribed")),
            "http_status": int(result.get("http_status") or 0) or None,
            "meta_code": int(error.get("code") or 0) or None,
            "meta_error_type": clean(error.get("type"), 120),
            "meta_error_message": clean(error.get("message"), 1200),
            "request_json": json.dumps(result.get("request") or {}),
            "response_json": json.dumps(result.get("last_response") or {}),
            "error": clean(result.get("error"), 1500),
        },
    )


def ensure_instagram_page_subscription(
    page_id: str,
    page_access_token: str,
    *,
    graph_version: str = "v24.0",
    app_id: str = "",
    instagram_business_account_id: str = "",
    subscribed_fields: list[str] | None = None,
    auto_subscribe: bool = True,
    retries: int = 2,
    conn: Connection | None = None,
    tenant_id: str | None = None,
    integration_id: str | None = None,
) -> dict[str, Any]:
    clean_page_id = clean(page_id, 80)
    clean_token = clean(page_access_token, 4000)
    fields = subscribed_fields or INSTAGRAM_SUBSCRIBED_FIELDS
    result: dict[str, Any] = {
        "ok": False,
        "status": "not_checked",
        "page_id": clean_page_id,
        "instagram_business_account_id": clean(instagram_business_account_id, 80),
        "app_id": clean(app_id, 80),
        "subscribed_fields": fields,
        "already_subscribed": False,
        "auto_subscribe_attempted": False,
        "final_subscribed": False,
        "subscribed_apps": [],
        "request": {"get": f"/{clean_page_id}/subscribed_apps", "post": f"/{clean_page_id}/subscribed_apps"},
        "last_response": {},
        "http_status": 0,
        "checked_at": utc_now(),
    }
    if not clean_page_id:
        result.update({"status": "missing_page_id", "error": "page_id_required"})
        _log_subscription_check(conn, tenant_id=tenant_id, integration_id=integration_id, page_id=clean_page_id, instagram_business_account_id=instagram_business_account_id, app_id=app_id, page_access_token=clean_token, result=result)
        return result
    if not clean_token:
        result.update({"status": "missing_page_access_token", "error": "page_access_token_required"})
        _log_subscription_check(conn, tenant_id=tenant_id, integration_id=integration_id, page_id=clean_page_id, instagram_business_account_id=instagram_business_account_id, app_id=app_id, page_access_token=clean_token, result=result)
        return result

    print(f"[Instagram] Checking Page subscribed_apps for Page {clean_page_id}", flush=True)
    status, payload, attempts = request_with_retry("GET", f"/{clean_page_id}/subscribed_apps", clean_token, graph_version=graph_version, retries=retries)
    result["http_status"] = status
    result["last_response"] = payload
    result["attempts"] = {"get": attempts, "post": 0, "verify": 0}
    if status >= 400 or meta_error(payload):
        result.update({"status": classify_meta_error(status, payload), "error": clean((meta_error(payload) or {}).get("message") or payload, 1500)})
        _log_subscription_check(conn, tenant_id=tenant_id, integration_id=integration_id, page_id=clean_page_id, instagram_business_account_id=instagram_business_account_id, app_id=app_id, page_access_token=clean_token, result=result)
        return result

    result["subscribed_apps"] = _subscription_items(payload)
    already = _is_page_subscribed(payload, app_id)
    result["already_subscribed"] = already
    if already:
        print("[Instagram] Already subscribed.", flush=True)
        result.update({"ok": True, "status": "already_subscribed", "final_subscribed": True})
        _log_subscription_check(conn, tenant_id=tenant_id, integration_id=integration_id, page_id=clean_page_id, instagram_business_account_id=instagram_business_account_id, app_id=app_id, page_access_token=clean_token, result=result)
        return result
    if not auto_subscribe:
        result.update({"ok": True, "status": "not_subscribed", "final_subscribed": False})
        _log_subscription_check(conn, tenant_id=tenant_id, integration_id=integration_id, page_id=clean_page_id, instagram_business_account_id=instagram_business_account_id, app_id=app_id, page_access_token=clean_token, result=result)
        return result

    print("[Instagram] Page not subscribed. Auto-subscribing...", flush=True)
    result["auto_subscribe_attempted"] = True
    post_status, post_payload, post_attempts = request_with_retry(
        "POST",
        f"/{clean_page_id}/subscribed_apps",
        clean_token,
        graph_version=graph_version,
        params={"subscribed_fields": ",".join(fields)},
        retries=retries,
    )
    result["http_status"] = post_status
    result["last_response"] = post_payload
    result["attempts"]["post"] = post_attempts
    if post_status >= 400 or meta_error(post_payload):
        result.update({"status": classify_meta_error(post_status, post_payload), "error": clean((meta_error(post_payload) or {}).get("message") or post_payload, 1500)})
        _log_subscription_check(conn, tenant_id=tenant_id, integration_id=integration_id, page_id=clean_page_id, instagram_business_account_id=instagram_business_account_id, app_id=app_id, page_access_token=clean_token, result=result)
        return result

    verify_status, verify_payload, verify_attempts = request_with_retry("GET", f"/{clean_page_id}/subscribed_apps", clean_token, graph_version=graph_version, retries=retries)
    result["http_status"] = verify_status
    result["last_response"] = verify_payload
    result["attempts"]["verify"] = verify_attempts
    final = verify_status < 400 and not meta_error(verify_payload) and _is_page_subscribed(verify_payload, app_id)
    result["subscribed_apps"] = _subscription_items(verify_payload)
    result["final_subscribed"] = final
    result["ok"] = final
    result["status"] = "subscription_successful" if final else "subscription_not_confirmed"
    if final:
        print("[Instagram] Subscription successful.", flush=True)
    else:
        result["error"] = clean((meta_error(verify_payload) or {}).get("message") or "subscription_not_confirmed", 1500)
    _log_subscription_check(conn, tenant_id=tenant_id, integration_id=integration_id, page_id=clean_page_id, instagram_business_account_id=instagram_business_account_id, app_id=app_id, page_access_token=clean_token, result=result)
    return result


def discover_instagram_assets(user_access_token: str, *, graph_version: str = "v24.0") -> dict[str, Any]:
    businesses_status, businesses_payload, _ = request_with_retry("GET", "/me/businesses", user_access_token, graph_version=graph_version, params={"fields": "id,name"}, retries=1)
    businesses = businesses_payload.get("data") if isinstance(businesses_payload, dict) else []
    businesses = businesses if isinstance(businesses, list) else []
    pages_by_id: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, Any]] = []
    for business in businesses:
        business_id = clean((business or {}).get("id"), 80)
        if not business_id:
            continue
        page_status, page_payload, _ = request_with_retry(
            "GET",
            f"/{business_id}/owned_pages",
            user_access_token,
            graph_version=graph_version,
            params={"fields": "id,name,access_token,instagram_business_account{id,username,name,profile_picture_url}"},
            retries=1,
        )
        if page_status >= 400 or meta_error(page_payload):
            errors.append({"business_id": business_id, "status": page_status, "error": page_payload})
            continue
        for raw_page in page_payload.get("data") if isinstance(page_payload.get("data"), list) else []:
            page = dict(raw_page or {})
            page["business_id"] = business_id
            page["business_name"] = clean((business or {}).get("name"), 180)
            pages_by_id[clean(page.get("id"), 80)] = page

    # Fallback useful for businesses where /owned_pages is restricted but /me/accounts returns administered pages.
    account_status, account_payload, _ = request_with_retry(
        "GET",
        "/me/accounts",
        user_access_token,
        graph_version=graph_version,
        params={"fields": "id,name,access_token,instagram_business_account{id,username,name,profile_picture_url}"},
        retries=1,
    )
    if account_status < 400 and not meta_error(account_payload):
        for raw_page in account_payload.get("data") if isinstance(account_payload.get("data"), list) else []:
            page = dict(raw_page or {})
            page.setdefault("business_id", "")
            page.setdefault("business_name", "")
            pages_by_id[clean(page.get("id"), 80)] = page
    else:
        errors.append({"source": "me/accounts", "status": account_status, "error": account_payload})

    assets: list[dict[str, Any]] = []
    for page in pages_by_id.values():
        ig = page.get("instagram_business_account") if isinstance(page.get("instagram_business_account"), dict) else {}
        assets.append(
            {
                "page_id": clean(page.get("id"), 80),
                "page_name": clean(page.get("name"), 180),
                "business_id": clean(page.get("business_id"), 80),
                "business_name": clean(page.get("business_name"), 180),
                "has_page_token": bool(clean(page.get("access_token"), 4000)),
                "instagram_business_account_id": clean(ig.get("id"), 80),
                "instagram_username": clean(ig.get("username") or ig.get("name"), 180),
                "instagram_profile_picture_url": clean(ig.get("profile_picture_url"), 600),
                "connected": bool(clean(ig.get("id"), 80)),
            }
        )
    return {
        "ok": businesses_status < 400 or bool(assets),
        "businesses": [{"id": clean(item.get("id"), 80), "name": clean(item.get("name"), 180)} for item in businesses if isinstance(item, dict)],
        "assets": assets,
        "raw_pages": list(pages_by_id.values()),
        "errors": errors,
        "checked_at": utc_now(),
    }
