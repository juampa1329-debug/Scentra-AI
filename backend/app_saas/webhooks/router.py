from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import text

from app_saas.config import settings
from app_saas.db import db_session, set_tenant_context
from app_saas.shared.secrets import decrypt_secret
from app_saas.shared.security import (
    AuthContext,
    derive_webhook_signature_secret,
    get_current_user,
    hash_secret,
    new_secret,
    require_role,
    verify_hmac_sha256_signature,
    verify_secret,
)
from app_saas.webhooks.schemas import (
    WebhookEndpointCreateIn,
    WebhookEndpointOut,
    WebhookEndpointPatchIn,
    WebhookEventOut,
)
from app_saas.workers.ingest import process_due_webhook_events

router = APIRouter(prefix="/webhooks", tags=["saas-webhooks"])

META_WEBHOOK_PROVIDERS = {"meta", "whatsapp", "facebook", "instagram"}
META_WEBHOOK_OBJECTS = {"whatsapp_business_account", "page", "instagram"}


def _normalize_provider(value: str) -> str:
    provider = re.sub(r"[^a-z0-9_-]+", "-", str(value or "").strip().lower()).strip("-")
    if not provider:
        raise HTTPException(status_code=400, detail="valid_provider_required")
    return provider[:50]


def _normalize_endpoint_key(value: str) -> str:
    key = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value or "").strip()).strip("-")
    return key[:120]


def _safe_headers(request: Request) -> dict[str, str]:
    keep = {
        "content-type",
        "user-agent",
        "x-request-id",
        "x-hub-signature-256",
        "x-scentra-signature-256",
        "x-scentra-webhook-token",
        "x-verane-signature-256",
        "x-verane-webhook-token",
        "x-forwarded-for",
    }
    return {k.lower(): str(v)[:500] for k, v in request.headers.items() if k.lower() in keep}


def _safe_json(raw: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads((raw or b"{}").decode("utf-8", errors="ignore") or "{}")
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def _is_meta_webhook_payload(provider: str, payload: dict[str, Any]) -> bool:
    if provider not in META_WEBHOOK_PROVIDERS:
        return False
    if str(payload.get("object") or "").strip().lower() in META_WEBHOOK_OBJECTS:
        return True
    entries = payload.get("entry")
    return isinstance(entries, list) and bool(entries)


def _extract_event_id(provider: str, payload: dict[str, Any], raw_sha256: str) -> str:
    for key in ("event_id", "id", "message_id", "wa_message_id"):
        if payload.get(key):
            return str(payload[key])[:240]

    entries = payload.get("entry")
    if isinstance(entries, list) and entries:
        first = entries[0] if isinstance(entries[0], dict) else {}
        entry_id = str(first.get("id") or "").strip()
        changes = first.get("changes")
        change_key = ""
        if isinstance(changes, list) and changes:
            first_change = changes[0] if isinstance(changes[0], dict) else {}
            value = first_change.get("value") if isinstance(first_change, dict) else {}
            if isinstance(value, dict):
                messages = value.get("messages")
                statuses = value.get("statuses")
                if isinstance(messages, list) and messages:
                    change_key = str((messages[0] or {}).get("id") or (messages[0] or {}).get("from") or "")
                elif isinstance(statuses, list) and statuses:
                    change_key = str((statuses[0] or {}).get("id") or "")
            if not change_key:
                change_key = str(first_change.get("field") or "")
        if entry_id or change_key:
            return f"{provider}:{entry_id}:{change_key}:{raw_sha256[:16]}"[:240]

    return f"{provider}:{raw_sha256}"[:240]


def _period_yyyymm() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m")


def _signature_header(request: Request) -> str:
    return str(
        request.headers.get("x-scentra-signature-256")
        or request.headers.get("x-verane-signature-256")
        or request.headers.get("x-hub-signature-256")
        or ""
    ).strip()


def _endpoint_signature_secret(endpoint: dict) -> str:
    salt = str(endpoint.get("signature_secret_salt") or "").strip()
    if not salt:
        return ""
    return derive_webhook_signature_secret(
        tenant_id=str(endpoint["tenant_id"]),
        provider=str(endpoint["provider"]),
        endpoint_key=str(endpoint["endpoint_key"]),
        salt=salt,
    )


def _verify_endpoint_signature(endpoint: dict, raw: bytes, request: Request) -> bool:
    signature_secret = _endpoint_signature_secret(endpoint)
    if not verify_secret(signature_secret, str(endpoint.get("signature_secret_hash") or "")):
        return False
    return verify_hmac_sha256_signature(
        secret_value=signature_secret,
        raw_body=raw,
        signature_header=_signature_header(request),
    )


def _load_meta_app_secret(conn, tenant_id: str) -> str:
    rows = conn.execute(
        text(
            """
            SELECT config_json
            FROM saas_integrations
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND (
                provider IN ('meta', 'whatsapp', 'facebook', 'instagram')
                OR channel IN ('whatsapp', 'facebook', 'instagram')
              )
            ORDER BY
              CASE WHEN provider = 'meta' THEN 0 ELSE 1 END,
              updated_at DESC NULLS LAST
            LIMIT 10
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().all()
    for row in rows:
        config = dict(row["config_json"] or {})
        for key in ("app_secret", "meta_app_secret", "client_secret"):
            value = decrypt_secret(str(config.get(key) or "").strip())
            if value:
                return value
    return ""


def _verify_meta_app_signature(conn, endpoint: dict, raw: bytes, request: Request) -> tuple[bool, bool]:
    if str(endpoint.get("provider") or "").lower() not in META_WEBHOOK_PROVIDERS:
        return False, False
    signature = _signature_header(request)
    app_secret = _load_meta_app_secret(conn, str(endpoint["tenant_id"]))
    if not app_secret:
        return False, False
    if not signature:
        return False, True
    return (
        verify_hmac_sha256_signature(
            secret_value=app_secret,
            raw_body=raw,
            signature_header=signature,
        ),
        True,
    )


def _load_endpoint(conn, provider: str, endpoint_key: str) -> dict:
    row = conn.execute(
        text(
            """
            SELECT
                id::text,
                tenant_id::text,
                provider,
                endpoint_key,
                verify_token_hash,
                signature_secret_hash,
                signature_secret_salt,
                signature_required,
                is_active
            FROM saas_webhook_endpoints
            WHERE provider = :provider
              AND endpoint_key = :endpoint_key
            LIMIT 1
            """
        ),
        {"provider": provider, "endpoint_key": endpoint_key},
    ).mappings().first()
    if not row or not bool(row["is_active"]):
        raise HTTPException(status_code=404, detail="webhook_endpoint_not_found")
    return dict(row)


def _instagram_lookup_ids(payload: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for entry in payload.get("entry") if isinstance(payload.get("entry"), list) else []:
        if not isinstance(entry, dict):
            continue
        for value in (
            entry.get("id"),
            ((entry.get("messaging") or [{}])[0] if isinstance(entry.get("messaging"), list) and entry.get("messaging") else {}).get("recipient", {}).get("id"),
        ):
            clean = str(value or "").strip()
            if clean and clean not in ids:
                ids.append(clean)
        for change in entry.get("changes") if isinstance(entry.get("changes"), list) else []:
            value = change.get("value") if isinstance(change, dict) else {}
            if isinstance(value, dict):
                for candidate in (value.get("id"), value.get("page_id"), value.get("instagram_business_account_id")):
                    clean = str(candidate or "").strip()
                    if clean and clean not in ids:
                        ids.append(clean)
    return ids


def _load_instagram_target(conn, payload: dict[str, Any]) -> dict[str, Any] | None:
    ids = _instagram_lookup_ids(payload)
    if not ids:
        return None
    row = conn.execute(
        text(
            """
            SELECT
                i.tenant_id::text,
                i.id::text AS integration_id,
                e.id::text AS endpoint_id,
                e.endpoint_key
            FROM saas_integrations i
            JOIN saas_webhook_endpoints e
              ON e.tenant_id = i.tenant_id
             AND e.provider = 'instagram'
             AND e.is_active = TRUE
            WHERE i.provider = 'meta'
              AND i.channel = 'instagram'
              AND i.status = 'connected'
              AND (
                i.config_json->>'instagram_business_account_id' = ANY(CAST(:ids AS text[]))
                OR i.config_json->>'page_id' = ANY(CAST(:ids AS text[]))
              )
            ORDER BY i.updated_at DESC
            LIMIT 1
            """
        ),
        {"ids": ids},
    ).mappings().first()
    return dict(row) if row else None


@router.get("/endpoints", response_model=list[WebhookEndpointOut])
def list_endpoints(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        rows = conn.execute(
            text(
                """
                SELECT
                    id::text,
                    tenant_id::text,
                    provider,
                    endpoint_key,
                    is_active,
                    signature_required,
                    last_seen_at::text
                FROM saas_webhook_endpoints
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND is_active = TRUE
                ORDER BY provider ASC
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().all()
    return [
        WebhookEndpointOut(
            **dict(row),
            url_path=f"/saas/v1/webhooks/{row['provider']}/{row['endpoint_key']}",
        )
        for row in rows
    ]


@router.post("/endpoints", response_model=WebhookEndpointOut)
def create_endpoint(
    payload: WebhookEndpointCreateIn,
    ctx: AuthContext = Depends(require_role("owner", "admin")),
):
    provider = _normalize_provider(payload.provider)
    endpoint_key = _normalize_endpoint_key(payload.endpoint_key or new_secret("whkey"))
    verify_token = new_secret(f"{provider}_verify")
    signature_salt = new_secret("sig_salt")
    signature_secret = derive_webhook_signature_secret(
        tenant_id=ctx.tenant_id,
        provider=provider,
        endpoint_key=endpoint_key,
        salt=signature_salt,
    )

    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        row = conn.execute(
            text(
                """
                INSERT INTO saas_webhook_endpoints (
                    tenant_id,
                    provider,
                    endpoint_key,
                    verify_secret_ref,
                    verify_token_hash,
                    signature_secret_hash,
                    signature_secret_salt,
                    signature_required,
                    is_active
                )
                VALUES (
                    CAST(:tenant_id AS uuid),
                    :provider,
                    :endpoint_key,
                    :verify_secret_ref,
                    :verify_token_hash,
                    :signature_secret_hash,
                    :signature_secret_salt,
                    :signature_required,
                    :is_active
                )
                ON CONFLICT (tenant_id, provider)
                DO UPDATE SET
                    endpoint_key = EXCLUDED.endpoint_key,
                    verify_secret_ref = EXCLUDED.verify_secret_ref,
                    verify_token_hash = EXCLUDED.verify_token_hash,
                    signature_secret_hash = EXCLUDED.signature_secret_hash,
                    signature_secret_salt = EXCLUDED.signature_secret_salt,
                    signature_required = EXCLUDED.signature_required,
                    is_active = EXCLUDED.is_active,
                    updated_at = NOW()
                RETURNING
                    id::text,
                    tenant_id::text,
                    provider,
                    endpoint_key,
                    is_active,
                    signature_required,
                    last_seen_at::text
                """
            ),
            {
                "tenant_id": ctx.tenant_id,
                "provider": provider,
                "endpoint_key": endpoint_key,
                "verify_secret_ref": f"local:{provider}:{endpoint_key}",
                "verify_token_hash": hash_secret(verify_token),
                "signature_secret_hash": hash_secret(signature_secret),
                "signature_secret_salt": signature_salt,
                "signature_required": bool(payload.signature_required),
                "is_active": bool(payload.is_active),
            },
        ).mappings().first()

    return WebhookEndpointOut(
        **dict(row),
        url_path=f"/saas/v1/webhooks/{provider}/{endpoint_key}",
        verify_token_once=verify_token,
        signature_secret_once=signature_secret,
    )


@router.post("/endpoints/{endpoint_id}/rotate-token", response_model=WebhookEndpointOut)
def rotate_endpoint_token(
    endpoint_id: str,
    ctx: AuthContext = Depends(require_role("owner", "admin")),
):
    verify_token = new_secret("webhook_verify")
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        row = conn.execute(
            text(
                """
                UPDATE saas_webhook_endpoints
                SET verify_token_hash = :verify_token_hash, updated_at = NOW()
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:endpoint_id AS uuid)
                RETURNING
                    id::text,
                    tenant_id::text,
                    provider,
                    endpoint_key,
                    is_active,
                    signature_required,
                    last_seen_at::text
                """
            ),
            {
                "tenant_id": ctx.tenant_id,
                "endpoint_id": endpoint_id,
                "verify_token_hash": hash_secret(verify_token),
            },
        ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="webhook_endpoint_not_found")
    return WebhookEndpointOut(
        **dict(row),
        url_path=f"/saas/v1/webhooks/{row['provider']}/{row['endpoint_key']}",
        verify_token_once=verify_token,
    )


@router.post("/endpoints/{endpoint_id}/rotate-signature", response_model=WebhookEndpointOut)
def rotate_endpoint_signature(
    endpoint_id: str,
    ctx: AuthContext = Depends(require_role("owner", "admin")),
):
    signature_salt = new_secret("sig_salt")
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        current = conn.execute(
            text(
                """
                SELECT provider, endpoint_key
                FROM saas_webhook_endpoints
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:endpoint_id AS uuid)
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id, "endpoint_id": endpoint_id},
        ).mappings().first()
        if not current:
            raise HTTPException(status_code=404, detail="webhook_endpoint_not_found")
        signature_secret = derive_webhook_signature_secret(
            tenant_id=ctx.tenant_id,
            provider=current["provider"],
            endpoint_key=current["endpoint_key"],
            salt=signature_salt,
        )
        row = conn.execute(
            text(
                """
                UPDATE saas_webhook_endpoints
                SET
                    signature_secret_hash = :signature_secret_hash,
                    signature_secret_salt = :signature_secret_salt,
                    updated_at = NOW()
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:endpoint_id AS uuid)
                RETURNING
                    id::text,
                    tenant_id::text,
                    provider,
                    endpoint_key,
                    is_active,
                    signature_required,
                    last_seen_at::text
                """
            ),
            {
                "tenant_id": ctx.tenant_id,
                "endpoint_id": endpoint_id,
                "signature_secret_hash": hash_secret(signature_secret),
                "signature_secret_salt": signature_salt,
            },
        ).mappings().first()
    return WebhookEndpointOut(
        **dict(row),
        url_path=f"/saas/v1/webhooks/{row['provider']}/{row['endpoint_key']}",
        signature_secret_once=signature_secret,
    )


@router.patch("/endpoints/{endpoint_id}", response_model=WebhookEndpointOut)
def update_endpoint(
    endpoint_id: str,
    payload: WebhookEndpointPatchIn,
    ctx: AuthContext = Depends(require_role("owner", "admin")),
):
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="webhook_endpoint_update_required")

    set_parts = []
    params: dict[str, Any] = {
        "tenant_id": ctx.tenant_id,
        "endpoint_id": endpoint_id,
    }
    if "is_active" in updates:
        set_parts.append("is_active = :is_active")
        params["is_active"] = bool(updates["is_active"])
    if "signature_required" in updates:
        set_parts.append("signature_required = :signature_required")
        params["signature_required"] = bool(updates["signature_required"])
    set_parts.append("updated_at = NOW()")

    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        row = conn.execute(
            text(
                f"""
                UPDATE saas_webhook_endpoints
                SET {", ".join(set_parts)}
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:endpoint_id AS uuid)
                RETURNING
                    id::text,
                    tenant_id::text,
                    provider,
                    endpoint_key,
                    is_active,
                    signature_required,
                    last_seen_at::text
                """
            ),
            params,
        ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="webhook_endpoint_not_found")
    return WebhookEndpointOut(
        **dict(row),
        url_path=f"/saas/v1/webhooks/{row['provider']}/{row['endpoint_key']}",
    )


@router.delete("/endpoints/{endpoint_id}")
def delete_endpoint(
    endpoint_id: str,
    ctx: AuthContext = Depends(require_role("owner", "admin")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        row = conn.execute(
            text(
                """
                UPDATE saas_webhook_endpoints
                SET is_active = FALSE, updated_at = NOW()
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:endpoint_id AS uuid)
                RETURNING id::text, provider, endpoint_key
                """
            ),
            {"tenant_id": ctx.tenant_id, "endpoint_id": endpoint_id},
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="webhook_endpoint_not_found")
        conn.execute(
            text(
                """
                INSERT INTO saas_audit_events (
                    tenant_id, actor_user_id, action, resource_type, resource_id, details_json
                )
                VALUES (
                    CAST(:tenant_id AS uuid), CAST(:user_id AS uuid), 'webhook_endpoint.deleted',
                    'webhook_endpoint', :resource_id, CAST(:details_json AS jsonb)
                )
                """
            ),
            {
                "tenant_id": ctx.tenant_id,
                "user_id": ctx.user_id,
                "resource_id": row["id"],
                "details_json": json.dumps({"provider": row["provider"], "endpoint_key": row["endpoint_key"]}),
            },
        )
    return {"ok": True, "deleted_id": row["id"], "provider": row["provider"], "endpoint_key": row["endpoint_key"]}


@router.get("/endpoints/{endpoint_id}/verify")
def verify_endpoint_setup(
    endpoint_id: str,
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        endpoint = conn.execute(
            text(
                """
                SELECT id::text, tenant_id::text, provider, endpoint_key, is_active, signature_required, last_seen_at::text
                FROM saas_webhook_endpoints
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:endpoint_id AS uuid)
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id, "endpoint_id": endpoint_id},
        ).mappings().first()
        if not endpoint:
            raise HTTPException(status_code=404, detail="webhook_endpoint_not_found")
        integration = conn.execute(
            text(
                """
                SELECT id::text, status, updated_at::text
                FROM saas_integrations
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND (channel = :provider OR provider = :provider)
                ORDER BY updated_at DESC
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id, "provider": endpoint["provider"]},
        ).mappings().first()
        recent_events = conn.execute(
            text(
                """
                SELECT status, error, received_at::text
                FROM saas_webhook_events
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND provider = :provider
                ORDER BY received_at DESC
                LIMIT 5
                """
            ),
            {"tenant_id": ctx.tenant_id, "provider": endpoint["provider"]},
        ).mappings().all()
    callback_url = f"{str(settings.scentra_api_public_url or '').strip().rstrip('/')}/saas/v1/webhooks/{endpoint['provider']}/{endpoint['endpoint_key']}"
    checks = [
        {"code": "endpoint_active", "ok": bool(endpoint["is_active"]), "label": "Endpoint activo"},
        {"code": "integration_present", "ok": bool(integration), "label": "Integracion del canal existe"},
        {"code": "events_received", "ok": bool(endpoint["last_seen_at"]), "label": "Meta ya envio al menos un evento"},
    ]
    return {
        "ok": all(item["ok"] for item in checks[:2]),
        "endpoint": dict(endpoint),
        "callback_url": callback_url,
        "integration": dict(integration or {}),
        "recent_events": [dict(row) for row in recent_events],
        "checks": checks,
        "next_steps": [
            "Copia Callback URL y Verify token en Meta Developers si acabas de rotar o recrear el endpoint.",
            "En Meta, confirma que el objeto correcto este suscrito: Page para Facebook/Instagram o WhatsApp Business Account para WhatsApp.",
            "Envia un mensaje o comentario de prueba y vuelve a verificar para confirmar last_seen_at.",
        ],
    }


@router.get("/events", response_model=list[WebhookEventOut])
def list_events(
    provider: str = Query(""),
    limit: int = Query(100, ge=1, le=500),
    ctx: AuthContext = Depends(get_current_user),
):
    filters = ["tenant_id = CAST(:tenant_id AS uuid)"]
    params: dict[str, Any] = {"tenant_id": ctx.tenant_id, "limit": limit}
    if provider:
        filters.append("provider = :provider")
        params["provider"] = _normalize_provider(provider)

    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        rows = conn.execute(
            text(
                f"""
                SELECT id::text, provider, event_id, status, received_at::text, error
                FROM saas_webhook_events
                WHERE {" AND ".join(filters)}
                ORDER BY received_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
    return [WebhookEventOut(**dict(row)) for row in rows]


@router.post("/events/process")
def process_events_now(
    limit: int = Query(25, ge=1, le=200),
    ctx: AuthContext = Depends(require_role("owner", "admin")),
):
    result = process_due_webhook_events(limit=limit, tenant_id=ctx.tenant_id)
    return {"ok": True, "tenant_id": ctx.tenant_id, "result": result}


@router.get("/instagram")
def verify_global_instagram_webhook(
    mode: str = Query("", alias="hub.mode"),
    verify_token: str = Query("", alias="hub.verify_token"),
    challenge: str = Query("", alias="hub.challenge"),
):
    expected = str(settings.scentra_instagram_webhook_verify_token or "").strip()
    if mode == "subscribe" and challenge and expected and verify_token == expected:
        return Response(content=str(challenge), media_type="text/plain")
    raise HTTPException(status_code=403, detail="instagram_webhook_verification_failed")


@router.post("/instagram")
async def receive_global_instagram_webhook(request: Request):
    raw = await request.body()
    raw_sha256 = hashlib.sha256(raw or b"").hexdigest()
    payload = _safe_json(raw)
    if not _is_meta_webhook_payload("instagram", payload):
        raise HTTPException(status_code=400, detail="invalid_instagram_webhook_payload")

    app_secret = str(settings.scentra_meta_app_secret or "").strip()
    if app_secret:
        signature_ok = verify_hmac_sha256_signature(
            secret_value=app_secret,
            raw_body=raw,
            signature_header=_signature_header(request),
        )
        if not signature_ok:
            raise HTTPException(status_code=403, detail="invalid_instagram_webhook_signature")

    event_id = _extract_event_id("instagram", payload, raw_sha256)
    with db_session() as conn:
        target = _load_instagram_target(conn, payload)
        if not target:
            # Meta expects a fast 200; returning ok:false prevents retries while making the issue visible in API logs.
            return {"ok": False, "provider": "instagram", "event_id": event_id, "stored": False, "reason": "instagram_tenant_not_matched"}
        set_tenant_context(conn, target["tenant_id"])
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
                    'instagram',
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
                "tenant_id": target["tenant_id"],
                "endpoint_id": target["endpoint_id"],
                "event_id": event_id,
                "headers_json": json.dumps(_safe_headers(request)),
                "payload_json": json.dumps(payload),
                "raw_sha256": raw_sha256,
            },
        )
        inserted = int(result.rowcount or 0) > 0
        conn.execute(
            text(
                """
                UPDATE saas_webhook_endpoints
                SET last_seen_at = NOW(), updated_at = NOW()
                WHERE id = CAST(:endpoint_id AS uuid)
                """
            ),
            {"endpoint_id": target["endpoint_id"]},
        )
    process_result: dict[str, Any] = {}
    if inserted:
        try:
            process_result = process_due_webhook_events(limit=10, tenant_id=target["tenant_id"])
        except Exception as exc:
            process_result = {"errors": 1, "error": str(exc)[:300]}
    return {
        "ok": True,
        "tenant_id": target["tenant_id"],
        "provider": "instagram",
        "event_id": event_id,
        "duplicate": not inserted,
        "process_result": process_result,
    }


@router.get("/{provider}/{endpoint_key}")
def verify_webhook(
    provider: str,
    endpoint_key: str,
    mode: str = Query("", alias="hub.mode"),
    verify_token: str = Query("", alias="hub.verify_token"),
    challenge: str = Query("", alias="hub.challenge"),
):
    provider_clean = _normalize_provider(provider)
    key_clean = _normalize_endpoint_key(endpoint_key)
    with db_session() as conn:
        endpoint = _load_endpoint(conn, provider_clean, key_clean)

    if mode == "subscribe" and challenge and verify_secret(verify_token, endpoint["verify_token_hash"]):
        return Response(content=str(challenge), media_type="text/plain")
    raise HTTPException(status_code=403, detail="webhook_verification_failed")


@router.post("/{provider}/{endpoint_key}")
async def receive_webhook(provider: str, endpoint_key: str, request: Request):
    provider_clean = _normalize_provider(provider)
    key_clean = _normalize_endpoint_key(endpoint_key)
    raw = await request.body()
    raw_sha256 = hashlib.sha256(raw or b"").hexdigest()
    payload = _safe_json(raw)
    event_id = _extract_event_id(provider_clean, payload, raw_sha256)
    meta_post_ok = _is_meta_webhook_payload(provider_clean, payload)
    supplied_token = str(
        request.headers.get("x-scentra-webhook-token")
        or request.headers.get("x-verane-webhook-token")
        or ""
    ).strip()

    with db_session() as conn:
        endpoint = _load_endpoint(conn, provider_clean, key_clean)
        token_ok = verify_secret(supplied_token, endpoint["verify_token_hash"])
        signature_ok = _verify_endpoint_signature(endpoint, raw, request)
        meta_app_secret_configured = False
        if not signature_ok:
            meta_signature_ok, meta_app_secret_configured = _verify_meta_app_signature(conn, endpoint, raw, request)
            signature_ok = meta_signature_ok
        if bool(endpoint.get("signature_required")) and not signature_ok:
            if not (meta_post_ok and not meta_app_secret_configured):
                raise HTTPException(status_code=403, detail="invalid_webhook_signature")
        if not bool(endpoint.get("signature_required")) and not (token_ok or signature_ok or meta_post_ok):
            raise HTTPException(status_code=403, detail="invalid_webhook_auth")

        set_tenant_context(conn, endpoint["tenant_id"])
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
                "tenant_id": endpoint["tenant_id"],
                "endpoint_id": endpoint["id"],
                "provider": provider_clean,
                "event_id": event_id,
                "headers_json": json.dumps(_safe_headers(request)),
                "payload_json": json.dumps(payload),
                "raw_sha256": raw_sha256,
            },
        )
        inserted = int(result.rowcount or 0) > 0
        conn.execute(
            text(
                """
                UPDATE saas_webhook_endpoints
                SET last_seen_at = NOW(), updated_at = NOW()
                WHERE id = CAST(:endpoint_id AS uuid)
                """
            ),
            {"endpoint_id": endpoint["id"]},
        )
        if inserted:
            conn.execute(
                text(
                    """
                    INSERT INTO saas_usage_counters (tenant_id, metric_code, period_yyyymm, metric_value)
                    VALUES (CAST(:tenant_id AS uuid), 'webhook_events', :period, 1)
                    ON CONFLICT (tenant_id, metric_code, period_yyyymm)
                    DO UPDATE SET
                        metric_value = saas_usage_counters.metric_value + 1,
                        updated_at = NOW()
                    """
                ),
                {"tenant_id": endpoint["tenant_id"], "period": _period_yyyymm()},
            )

    process_result: dict[str, Any] = {}
    if inserted:
        try:
            process_result = process_due_webhook_events(limit=10, tenant_id=endpoint["tenant_id"])
        except Exception as exc:
            process_result = {"errors": 1, "error": str(exc)[:300]}

    return {
        "ok": True,
        "tenant_id": endpoint["tenant_id"],
        "provider": provider_clean,
        "event_id": event_id,
        "duplicate": not inserted,
        "process_result": process_result,
    }
