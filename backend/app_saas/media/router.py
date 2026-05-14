from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import text

from app_saas.db import db_session, set_tenant_context
from app_saas.shared.secrets import decrypt_secret
from app_saas.shared.security import AuthContext, decode_token, get_current_user, require_role

router = APIRouter(prefix="/media", tags=["saas-media"])

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
ALLOWED_KINDS = {"image", "video", "audio", "document", "file"}
DEFAULT_META_GRAPH_VERSION = "v24.0"


def _clean(value: object, limit: int = 240) -> str:
    return str(value or "").strip()[:limit]


def _safe_kind(value: object) -> str:
    kind = re.sub(r"[^a-z0-9_-]+", "", _clean(value, 40).lower())
    return kind if kind in ALLOWED_KINDS else "file"


def _load_meta_integration(conn, tenant_id: str) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            SELECT config_json, secret_ref
            FROM saas_integrations
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND channel = 'whatsapp'
              AND provider IN ('meta', 'whatsapp', 'whatsapp_cloud')
              AND status = 'connected'
            ORDER BY updated_at DESC
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="meta_whatsapp_integration_not_found")
    config = dict(row["config_json"] or {})
    token = decrypt_secret(str(config.get("access_token") or config.get("token") or "").strip())
    env_name = _clean(config.get("access_token_env"), 120)
    secret_ref = _clean(row.get("secret_ref"), 200)
    if not env_name and secret_ref.lower().startswith("env:"):
        env_name = secret_ref.split(":", 1)[1].strip()
    if not token and env_name:
        token = _clean(os.getenv(env_name), 3000)
    if not token:
        token = _clean(os.getenv("SCENTRA_META_ACCESS_TOKEN"), 3000)
    if not token:
        raise HTTPException(status_code=400, detail="meta_access_token_required")
    version = _clean(config.get("graph_api_version") or os.getenv("SCENTRA_META_GRAPH_VERSION"), 20) or DEFAULT_META_GRAPH_VERSION
    if not version.startswith("v"):
        version = f"v{version}"
    return {"token": token, "version": version}


def _graph_get_json(url: str, token: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:700]
        raise HTTPException(status_code=502, detail={"code": "meta_media_error", "meta": body})
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"code": "meta_media_unavailable", "message": str(exc)[:300]})


def _graph_get_bytes(url: str, token: str) -> tuple[bytes, str]:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read(), str(response.headers.get("content-type") or "application/octet-stream")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:700]
        raise HTTPException(status_code=502, detail={"code": "meta_media_download_error", "meta": body})
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"code": "meta_media_download_unavailable", "message": str(exc)[:300]})


@router.post("/upload")
async def upload_media(
    kind: str = "file",
    file: UploadFile = File(...),
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor", "agent")),
):
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="media_file_required")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="media_file_too_large")

    media_kind = _safe_kind(kind)
    filename = _clean(file.filename, 240)
    content_type = _clean(file.content_type, 120) or "application/octet-stream"

    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        row = conn.execute(
            text(
                """
                INSERT INTO saas_media_assets (
                    tenant_id, created_by_user_id, kind, filename, content_type, byte_size, data
                )
                VALUES (
                    CAST(:tenant_id AS uuid), CAST(:user_id AS uuid), :kind, :filename, :content_type, :byte_size, :data
                )
                RETURNING id::text, kind, filename, content_type, byte_size, created_at::text
                """
            ),
            {
                "tenant_id": ctx.tenant_id,
                "user_id": ctx.user_id,
                "kind": media_kind,
                "filename": filename,
                "content_type": content_type,
                "byte_size": len(data),
                "data": data,
            },
        ).mappings().first()

    return {
        "ok": True,
        "tenant_id": ctx.tenant_id,
        "media": dict(row),
        "media_id": row["id"],
        "url": f"/saas/v1/media/{row['id']}",
    }


@router.get("/{media_id}")
def get_media(media_id: str, token: str = Query("")):
    decoded = decode_token(token, "access")
    tenant_id = str(decoded.get("tenant_id") or "")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="tenant_context_required")
    with db_session() as conn:
        set_tenant_context(conn, tenant_id)
        row = conn.execute(
            text(
                """
                SELECT filename, content_type, data
                FROM saas_media_assets
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:media_id AS uuid)
                LIMIT 1
                """
            ),
            {"tenant_id": tenant_id, "media_id": media_id},
        ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="media_not_found")

    headers = {}
    filename = _clean(row["filename"], 240)
    if filename:
        headers["Content-Disposition"] = f'inline; filename="{filename}"'
    return Response(content=bytes(row["data"]), media_type=row["content_type"], headers=headers)


@router.get("/whatsapp/{media_id}")
def get_whatsapp_media(media_id: str, token: str = Query("")):
    decoded = decode_token(token, "access")
    tenant_id = str(decoded.get("tenant_id") or "")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="tenant_context_required")
    clean_media_id = _clean(media_id, 240)
    with db_session() as conn:
        set_tenant_context(conn, tenant_id)
        message = conn.execute(
            text(
                """
                SELECT mime_type, msg_type
                FROM saas_messages
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND media_id = :media_id
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"tenant_id": tenant_id, "media_id": clean_media_id},
        ).mappings().first()
        if not message:
            raise HTTPException(status_code=404, detail="media_message_not_found")
        integration = _load_meta_integration(conn, tenant_id)

    metadata = _graph_get_json(
        f"https://graph.facebook.com/{integration['version']}/{clean_media_id}",
        integration["token"],
    )
    media_url = _clean(metadata.get("url"), 4000)
    if not media_url:
        raise HTTPException(status_code=502, detail="meta_media_url_missing")
    content, content_type = _graph_get_bytes(media_url, integration["token"])
    media_type = _clean(metadata.get("mime_type") or message.get("mime_type") or content_type, 120) or content_type
    filename = f"whatsapp-{clean_media_id}"
    headers = {"Content-Disposition": f'inline; filename="{filename}"'}
    return Response(content=content, media_type=media_type, headers=headers)
