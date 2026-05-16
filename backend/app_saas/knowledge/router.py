from __future__ import annotations

import io
import json
import re
import urllib.request
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app_saas.db import db_session, set_tenant_context
from app_saas.shared.security import AuthContext, get_current_user, require_role

router = APIRouter(prefix="/knowledge", tags=["saas-knowledge"])


class KnowledgeUrlIn(BaseModel):
    url: str = Field(min_length=8, max_length=1000)
    title: str = Field(default="", max_length=240)
    notes: str = Field(default="", max_length=1000)


def _clean(value: Any, limit: int = 20000) -> str:
    return str(value or "").strip()[:limit]


def ensure_knowledge_tables(conn: Connection) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_knowledge_sources (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                source_type TEXT NOT NULL DEFAULT 'note',
                title TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                filename TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_knowledge_tenant_status
            ON saas_knowledge_sources (tenant_id, status, updated_at DESC)
            """
        )
    )


def _safe_row(row: dict[str, Any]) -> dict[str, Any]:
    content = _clean(row.get("content"), 200000)
    return {
        "id": str(row.get("id") or ""),
        "source_type": str(row.get("source_type") or ""),
        "title": str(row.get("title") or ""),
        "url": str(row.get("url") or ""),
        "filename": str(row.get("filename") or ""),
        "status": str(row.get("status") or ""),
        "content_preview": content[:360],
        "content_chars": len(content),
        "metadata_json": row.get("metadata_json") if isinstance(row.get("metadata_json"), dict) else {},
        "updated_at": str(row.get("updated_at") or ""),
    }


def _insert_source(
    conn: Connection,
    *,
    tenant_id: str,
    source_type: str,
    title: str,
    content: str,
    url: str = "",
    filename: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    clean_content = _clean(content, 250000)
    if len(clean_content) < 8:
        raise HTTPException(status_code=400, detail="knowledge_content_too_short")
    row = conn.execute(
        text(
            """
            INSERT INTO saas_knowledge_sources (
                tenant_id, source_type, title, url, filename, content, status, metadata_json, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), :source_type, :title, :url, :filename, :content,
                'active', CAST(:metadata_json AS jsonb), NOW()
            )
            RETURNING id::text, source_type, title, url, filename, content, status, metadata_json, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "source_type": source_type,
            "title": _clean(title, 240) or _clean(filename or url or "Fuente", 240),
            "url": _clean(url, 1000),
            "filename": _clean(filename, 240),
            "content": clean_content,
            "metadata_json": json.dumps(metadata or {}, ensure_ascii=False),
        },
    ).mappings().first()
    return _safe_row(dict(row))


def _extract_pdf_text(raw: bytes) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw))
        pages = [page.extract_text() or "" for page in reader.pages[:80]]
        return "\n\n".join(page.strip() for page in pages if page.strip())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"pdf_text_extract_failed:{str(exc)[:160]}")


def _extract_file_text(filename: str, content_type: str, raw: bytes) -> str:
    name = filename.lower()
    mime = content_type.lower()
    if name.endswith(".pdf") or mime == "application/pdf":
        return _extract_pdf_text(raw)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1", errors="ignore")


def _extract_url_text(url: str) -> tuple[str, str]:
    clean_url = _clean(url, 1000)
    if not clean_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="valid_url_required")
    request = urllib.request.Request(clean_url, headers={"User-Agent": "ScentraAI-Knowledge/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read(1_000_000).decode("utf-8", errors="ignore")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"url_fetch_failed:{str(exc)[:200]}")
    title_match = re.search(r"<title[^>]*>(.*?)</title>", raw, flags=re.I | re.S)
    title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else clean_url
    raw = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", raw)
    text_value = re.sub(r"(?s)<[^>]+>", " ", raw)
    text_value = re.sub(r"\s+", " ", text_value).strip()
    return title, text_value


@router.get("/sources")
def list_sources(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        ensure_knowledge_tables(conn)
        set_tenant_context(conn, ctx.tenant_id)
        rows = conn.execute(
            text(
                """
                SELECT id::text, source_type, title, url, filename, content, status, metadata_json, updated_at::text
                FROM saas_knowledge_sources
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                ORDER BY updated_at DESC
                LIMIT 100
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().all()
    return [_safe_row(dict(row)) for row in rows]


@router.post("/upload")
async def upload_source(
    file: UploadFile = File(...),
    title: str = Form(default=""),
    notes: str = Form(default=""),
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="knowledge_file_required")
    if len(raw) > 8_000_000:
        raise HTTPException(status_code=413, detail="knowledge_file_too_large")
    content = _extract_file_text(file.filename or "archivo", file.content_type or "", raw)
    if notes.strip():
        content = f"{notes.strip()}\n\n{content}"
    with db_session() as conn:
        ensure_knowledge_tables(conn)
        set_tenant_context(conn, ctx.tenant_id)
        return _insert_source(
            conn,
            tenant_id=ctx.tenant_id,
            source_type="file",
            title=title or file.filename or "Archivo KB",
            filename=file.filename or "",
            content=content,
            metadata={"content_type": file.content_type or "", "bytes": len(raw)},
        )


@router.post("/url")
def add_url_source(payload: KnowledgeUrlIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    fetched_title, content = _extract_url_text(payload.url)
    if payload.notes.strip():
        content = f"{payload.notes.strip()}\n\n{content}"
    with db_session() as conn:
        ensure_knowledge_tables(conn)
        set_tenant_context(conn, ctx.tenant_id)
        return _insert_source(
            conn,
            tenant_id=ctx.tenant_id,
            source_type="url",
            title=payload.title or fetched_title,
            url=payload.url,
            content=content,
            metadata={"fetched_title": fetched_title},
        )


@router.delete("/sources/{source_id}")
def delete_source(source_id: str, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    with db_session() as conn:
        ensure_knowledge_tables(conn)
        set_tenant_context(conn, ctx.tenant_id)
        result = conn.execute(
            text(
                """
                DELETE FROM saas_knowledge_sources
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:source_id AS uuid)
                """
            ),
            {"tenant_id": ctx.tenant_id, "source_id": source_id},
        )
    return {"ok": True, "deleted": int(result.rowcount or 0)}
