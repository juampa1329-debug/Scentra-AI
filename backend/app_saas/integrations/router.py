from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from app_saas.billing.limits import ensure_integration_quota
from app_saas.db import db_session, set_tenant_context
from app_saas.integrations.schemas import IntegrationOut, IntegrationUpsertIn, WhatsappPhoneRegisterIn
from app_saas.integrations.whatsapp_subscription import ensure_webhook_subscription
from app_saas.shared.security import AuthContext, get_current_user, require_role, verify_password
from app_saas.shared.secrets import decrypt_secret, encrypt_secret, is_masked_secret, mask_secret

router = APIRouter(prefix="/integrations", tags=["saas-integrations"])

SENSITIVE_CONFIG_KEYS = {"access_token", "token", "permanent_token", "app_secret", "meta_app_secret", "client_secret"}
DEFAULT_ACCESS_TOKEN_ENV = "SCENTRA_META_ACCESS_TOKEN"
ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")


def _secret_hint(value: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        return ""
    if len(clean) <= 10:
        return f"{clean[:2]}...{clean[-2:]}"
    return f"{clean[:4]}...{clean[-4:]}"


def _looks_like_env_name(value: str) -> bool:
    return bool(ENV_NAME_RE.fullmatch(str(value or "").strip()))


def _looks_like_secret_value(value: str) -> bool:
    clean = str(value or "").strip()
    if not clean or is_masked_secret(clean) or clean.startswith("enc:v1:"):
        return False
    if _looks_like_env_name(clean):
        return False
    return len(clean) >= 32 or clean.startswith(("EAA", "EAAG", "EAAB"))


def _normalize_secret_config(config: dict, existing: dict | None = None) -> tuple[dict, bool]:
    next_config = dict(config or {})
    existing_config = dict(existing or {})
    changed = False
    env_value = str(next_config.get("access_token_env") or "").strip()
    if _looks_like_secret_value(env_value):
        if not next_config.get("access_token"):
            next_config["access_token"] = env_value
        preserved_env = str(existing_config.get("access_token_env") or "").strip()
        next_config["access_token_env"] = preserved_env if _looks_like_env_name(preserved_env) else DEFAULT_ACCESS_TOKEN_ENV
        changed = True

    for key in SENSITIVE_CONFIG_KEYS:
        incoming_value = str(next_config.get(key) or "").strip()
        if incoming_value and not is_masked_secret(incoming_value) and not incoming_value.startswith("enc:v1:"):
            next_config[f"{key}_hint"] = _secret_hint(incoming_value)
            next_config[key] = encrypt_secret(incoming_value)
            changed = True
    return next_config, changed


def _safe_config_for_output(raw: dict | None) -> dict:
    config, _changed = _normalize_secret_config(dict(raw or {}))
    for key in SENSITIVE_CONFIG_KEYS:
        value = str(config.get(key) or "").strip()
        if value:
            config[key] = mask_secret(value)
            config[f"has_{key}"] = True
    env_value = str(config.get("access_token_env") or "").strip()
    if _looks_like_secret_value(env_value):
        config["access_token_env"] = DEFAULT_ACCESS_TOKEN_ENV
        config["has_access_token"] = True
        config["access_token_hint"] = _secret_hint(env_value)
    return config


def _merge_secret_config(incoming: dict, existing: dict | None) -> dict:
    next_config = dict(incoming or {})
    existing_config = dict(existing or {})
    env_value = str(next_config.get("access_token_env") or "").strip()
    if _looks_like_secret_value(env_value):
        if not next_config.get("access_token"):
            next_config["access_token"] = env_value
        preserved_env = str(existing_config.get("access_token_env") or "").strip()
        next_config["access_token_env"] = preserved_env if _looks_like_env_name(preserved_env) else DEFAULT_ACCESS_TOKEN_ENV
    for key in SENSITIVE_CONFIG_KEYS:
        incoming_value = str(next_config.get(key) or "").strip()
        if incoming_value and not is_masked_secret(incoming_value):
            next_config[f"{key}_hint"] = _secret_hint(incoming_value)
            next_config[key] = encrypt_secret(incoming_value)
            continue
        if existing_config.get(f"{key}_hint"):
            next_config[f"{key}_hint"] = existing_config[f"{key}_hint"]
        if existing_config.get(key):
            next_config[key] = existing_config[key]
        elif key in next_config:
            next_config.pop(key, None)
    return next_config


def _has_plain_secret_update(config: dict | None) -> bool:
    candidate = dict(config or {})
    env_value = str(candidate.get("access_token_env") or "").strip()
    if _looks_like_secret_value(env_value):
        return True
    for key in SENSITIVE_CONFIG_KEYS:
        value = str(candidate.get(key) or "").strip()
        if value and not is_masked_secret(value) and not value.startswith("enc:v1:"):
            return True
    return False


def _require_current_password(conn, user_id: str, current_password: str | None) -> None:
    password = str(current_password or "").strip()
    if not password:
        raise HTTPException(status_code=403, detail="current_password_required")
    user = conn.execute(
        text(
            """
            SELECT password_hash, status
            FROM saas_users
            WHERE id = CAST(:user_id AS uuid)
            LIMIT 1
            """
        ),
        {"user_id": user_id},
    ).mappings().first()
    if not user or user["status"] != "active" or not verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=403, detail="invalid_current_password")


def _graph_request(method: str, url: str, token: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method=method.upper(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw)
        except Exception:
            detail = raw[:500]
        raise HTTPException(status_code=502, detail={"code": "meta_graph_error", "meta": detail})
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"code": "meta_graph_unavailable", "message": str(exc)[:300]})


def _load_whatsapp_integration(conn, tenant_id: str) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            SELECT id::text, config_json
            FROM saas_integrations
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND provider = 'meta'
              AND channel = 'whatsapp'
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="meta_whatsapp_integration_not_found")
    config = dict(row["config_json"] or {})
    normalized, changed = _normalize_secret_config(config)
    if changed:
        conn.execute(
            text(
                """
                UPDATE saas_integrations
                SET config_json = CAST(:config_json AS jsonb), updated_at = NOW()
                WHERE id = CAST(:integration_id AS uuid)
                """
            ),
            {"integration_id": row["id"], "config_json": json.dumps(normalized)},
        )
    return {"id": row["id"], "config": normalized}


def _integration_token(config: dict[str, Any]) -> str:
    token = decrypt_secret(str(config.get("access_token") or config.get("token") or "").strip())
    if token:
        return token
    env_value = str(config.get("access_token_env") or "").strip()
    if _looks_like_secret_value(env_value):
        return env_value
    if _looks_like_env_name(env_value):
        return os.getenv(env_value, "").strip()
    return ""


def _waba_id_from_config(config: dict[str, Any]) -> str:
    return str(
        config.get("business_account_id")
        or config.get("waba_id")
        or config.get("whatsapp_business_account_id")
        or ""
    ).strip()


def _maybe_ensure_whatsapp_subscription(conn, *, tenant_id: str, integration_id: str, config: dict[str, Any]) -> dict[str, Any] | None:
    token = _integration_token(config)
    waba_id = _waba_id_from_config(config)
    if not token or not waba_id:
        return None
    result = ensure_webhook_subscription(
        waba_id,
        token,
        graph_version=str(config.get("graph_api_version") or "v24.0").strip(),
        app_id=str(config.get("app_id") or "").strip(),
        auto_subscribe=True,
        retries=2,
        conn=conn,
        tenant_id=tenant_id,
        integration_id=integration_id,
    )
    return result


@router.get("", response_model=list[IntegrationOut])
def list_integrations(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        rows = conn.execute(
            text(
                """
                SELECT
                    id::text,
                    provider,
                    channel,
                    status,
                    secret_ref,
                    config_json,
                    last_sync_at::text
                FROM saas_integrations
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                ORDER BY provider ASC, channel ASC
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().all()
        items = []
        for row in rows:
            raw_row = dict(row)
            normalized, changed = _normalize_secret_config(dict(raw_row.get("config_json") or {}))
            if changed:
                conn.execute(
                    text(
                        """
                        UPDATE saas_integrations
                        SET config_json = CAST(:config_json AS jsonb), updated_at = NOW()
                        WHERE id = CAST(:integration_id AS uuid)
                        """
                    ),
                    {"integration_id": raw_row["id"], "config_json": json.dumps(normalized)},
                )
            items.append(IntegrationOut(**{**raw_row, "config_json": _safe_config_for_output(normalized)}))
    return items


@router.post("", response_model=IntegrationOut)
def upsert_integration(
    payload: IntegrationUpsertIn,
    ctx: AuthContext = Depends(require_role("owner", "admin")),
):
    provider = payload.provider.strip().lower()
    channel = payload.channel.strip().lower()
    status = payload.status.strip().lower()
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        if status != "disconnected":
            ensure_integration_quota(conn, ctx.tenant_id, provider, channel)
        existing = conn.execute(
            text(
                """
                SELECT config_json
                FROM saas_integrations
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND provider = :provider
                  AND channel = :channel
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id, "provider": provider, "channel": channel},
        ).mappings().first()
        if existing and _has_plain_secret_update(payload.config_json):
            _require_current_password(conn, ctx.user_id, payload.current_password)
        config_json = _merge_secret_config(payload.config_json or {}, dict(existing["config_json"] or {}) if existing else {})
        row = conn.execute(
            text(
                """
                INSERT INTO saas_integrations (
                    tenant_id, provider, channel, status, secret_ref, config_json, updated_at
                )
                VALUES (
                    CAST(:tenant_id AS uuid), :provider, :channel, :status, :secret_ref,
                    CAST(:config_json AS jsonb), NOW()
                )
                ON CONFLICT (tenant_id, provider, channel)
                DO UPDATE SET
                    status = EXCLUDED.status,
                    secret_ref = COALESCE(NULLIF(EXCLUDED.secret_ref, ''), saas_integrations.secret_ref),
                    config_json = EXCLUDED.config_json,
                    updated_at = NOW()
                RETURNING
                    id::text,
                    provider,
                    channel,
                    status,
                    secret_ref,
                    config_json,
                    last_sync_at::text
                """
            ),
            {
                "tenant_id": ctx.tenant_id,
                "provider": provider,
                "channel": channel,
                "status": status,
                "secret_ref": str(payload.secret_ref or "").strip(),
                "config_json": json.dumps(config_json),
            },
        ).mappings().first()
        row_data = dict(row)
        saved_config = dict(row_data.get("config_json") or {})
        if provider == "meta" and channel == "whatsapp" and status == "connected":
            subscription_result = _maybe_ensure_whatsapp_subscription(conn, tenant_id=ctx.tenant_id, integration_id=row_data["id"], config=saved_config)
            if subscription_result is not None:
                saved_config["last_webhook_subscription_check"] = {
                    "status": subscription_result.get("status"),
                    "ok": bool(subscription_result.get("ok")),
                    "final_subscribed": bool(subscription_result.get("final_subscribed")),
                    "auto_subscribe_attempted": bool(subscription_result.get("auto_subscribe_attempted")),
                    "checked_at": subscription_result.get("checked_at"),
                    "error": str(subscription_result.get("error") or "")[:500],
                }
                conn.execute(
                    text(
                        """
                        UPDATE saas_integrations
                        SET config_json = CAST(:config_json AS jsonb), last_sync_at = NOW(), updated_at = NOW()
                        WHERE id = CAST(:integration_id AS uuid)
                        """
                    ),
                    {"integration_id": row_data["id"], "config_json": json.dumps(saved_config)},
                )
                row_data["config_json"] = saved_config
                row_data["last_sync_at"] = row_data.get("last_sync_at") or ""
    return IntegrationOut(**{**row_data, "config_json": _safe_config_for_output(row_data.get("config_json"))})


@router.get("/meta/whatsapp/phone-numbers")
def list_whatsapp_phone_numbers(ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        integration = _load_whatsapp_integration(conn, ctx.tenant_id)
        config = integration["config"]
        token = _integration_token(config)
        waba_id = str(config.get("business_account_id") or config.get("waba_id") or "").strip()
        version = str(config.get("graph_api_version") or "v24.0").strip()
        if not token:
            raise HTTPException(status_code=400, detail="meta_access_token_required")
        if not waba_id:
            raise HTTPException(status_code=400, detail="waba_id_required")

        subscription_result = ensure_webhook_subscription(
            waba_id,
            token,
            graph_version=version,
            app_id=str(config.get("app_id") or "").strip(),
            auto_subscribe=True,
            retries=2,
            conn=conn,
            tenant_id=ctx.tenant_id,
            integration_id=integration["id"],
        )

        fields = "id,display_phone_number,verified_name,quality_rating,code_verification_status,name_status,platform_type"
        query = urllib.parse.urlencode({"fields": fields})
        data = _graph_request("GET", f"https://graph.facebook.com/{version}/{waba_id}/phone_numbers?{query}", token)
        phone_numbers = data.get("data") if isinstance(data, dict) else []
        if not isinstance(phone_numbers, list):
            phone_numbers = []

        config["phone_numbers"] = phone_numbers
        config["last_phone_sync_status"] = "ok"
        config["last_webhook_subscription_check"] = {
            "status": subscription_result.get("status"),
            "ok": bool(subscription_result.get("ok")),
            "final_subscribed": bool(subscription_result.get("final_subscribed")),
            "auto_subscribe_attempted": bool(subscription_result.get("auto_subscribe_attempted")),
            "checked_at": subscription_result.get("checked_at"),
            "error": str(subscription_result.get("error") or "")[:500],
        }
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
    return {"ok": True, "tenant_id": ctx.tenant_id, "phone_numbers": phone_numbers, "subscription": subscription_result}


@router.post("/meta/whatsapp/register-phone")
def register_whatsapp_phone(
    payload: WhatsappPhoneRegisterIn,
    ctx: AuthContext = Depends(require_role("owner", "admin")),
):
    phone_number_id = payload.phone_number_id.strip()
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        integration = _load_whatsapp_integration(conn, ctx.tenant_id)
        config = integration["config"]
        token = _integration_token(config)
        version = str(config.get("graph_api_version") or "v24.0").strip()
        if not token:
            raise HTTPException(status_code=400, detail="meta_access_token_required")

        result = _graph_request(
            "POST",
            f"https://graph.facebook.com/{version}/{phone_number_id}/register",
            token,
            {"messaging_product": "whatsapp", "pin": payload.pin},
        )
        config["phone_number_id"] = phone_number_id
        config["phone_registration_status"] = "registered" if result.get("success") else "unknown"
        config["last_phone_register_response"] = result
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
    return {"ok": True, "tenant_id": ctx.tenant_id, "phone_number_id": phone_number_id, "result": result}
