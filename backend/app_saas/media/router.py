from __future__ import annotations

import re

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import text

from app_saas.db import db_session, set_tenant_context
from app_saas.shared.security import AuthContext, decode_token, get_current_user, require_role

router = APIRouter(prefix="/media", tags=["saas-media"])

MAX_UPLOAD_BYTES = 12 * 1024 * 1024
ALLOWED_KINDS = {"image", "video", "audio", "document", "file"}


def _clean(value: object, limit: int = 240) -> str:
    return str(value or "").strip()[:limit]


def _safe_kind(value: object) -> str:
    kind = re.sub(r"[^a-z0-9_-]+", "", _clean(value, 40).lower())
    return kind if kind in ALLOWED_KINDS else "file"


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
