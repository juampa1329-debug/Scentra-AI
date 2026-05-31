from __future__ import annotations

import csv
import difflib
import hashlib
import ipaddress
import io
import json
import math
import re
import socket
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
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
    semantic_description: str = Field(default="", max_length=1200)
    tags: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)


class KnowledgeSearchIn(BaseModel):
    query: str = Field(min_length=2, max_length=1200)
    limit: int = Field(default=6, ge=1, le=20)
    min_score: float = Field(default=0, ge=0, le=1000)


class KnowledgeEvaluationIn(BaseModel):
    query: str = Field(min_length=2, max_length=1200)
    expected_answer: str = Field(default="", max_length=4000)
    expected_sources: list[str] = Field(default_factory=list)
    limit: int = Field(default=6, ge=1, le=20)
    min_quality_score: int = Field(default=55, ge=0, le=100)


class KnowledgeSourceUpdateIn(BaseModel):
    title: str | None = Field(default=None, max_length=240)
    semantic_description: str | None = Field(default=None, max_length=1200)
    tags: list[str] | None = None
    aliases: list[str] | None = None
    reindex: bool = True


def _clean(value: Any, limit: int = 20000) -> str:
    return str(value or "").strip()[:limit]


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def _json_value(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if parsed is not None else fallback
        except json.JSONDecodeError:
            return fallback
    return value


def _content_hash(value: str) -> str:
    return hashlib.sha256(_clean(value, 500000).encode("utf-8", errors="ignore")).hexdigest()


def _normalize_for_search(value: Any, limit: int = 30000) -> str:
    raw = unicodedata.normalize("NFKD", _clean(value, limit).lower())
    raw = "".join(char for char in raw if not unicodedata.combining(char))
    raw = re.sub(r"[^\w\s]+", " ", raw, flags=re.UNICODE)
    raw = re.sub(r"_+", " ", raw)
    return re.sub(r"\s+", " ", raw).strip()


def _compact_for_search(value: Any, limit: int = 30000) -> str:
    return re.sub(r"[^a-z0-9]+", "", _normalize_for_search(value, limit))


def _legacy_tokenize(value: str) -> list[str]:
    words = re.findall(r"[a-zA-ZáéíóúÁÉÍÓÚñÑ0-9]{3,}", _clean(value, 4000).lower())
    stop = {
        "que", "con", "para", "por", "los", "las", "del", "una", "uno", "como", "sobre", "este",
        "esta", "esto", "hay", "tiene", "tengo", "cual", "cuales", "cuando", "donde", "puede",
        "pueden", "quiero", "necesito", "hola", "buenas",
    }
    out: list[str] = []
    for word in words:
        if word not in stop and word not in out:
            out.append(word)
    return out[:18]


STOP_WORDS = {
    "que", "con", "para", "por", "los", "las", "del", "una", "uno", "como", "sobre", "este",
    "esta", "esto", "hay", "tiene", "tengo", "cual", "cuales", "cuando", "donde", "puede",
    "pueden", "quiero", "necesito", "hola", "buenas", "sus", "mas", "muy", "sin",
    "the", "and", "for", "you", "your", "from", "this", "that", "are", "was", "were", "have",
}


def _token_stream(value: str, *, limit: int = 800) -> list[str]:
    words = re.findall(r"[a-z0-9]{3,}", _normalize_for_search(value, 30000), flags=re.UNICODE)
    return [word for word in words if word not in STOP_WORDS][:limit]


def _tokenize(value: str) -> list[str]:
    out: list[str] = []
    for word in _token_stream(value, limit=200):
        if word not in out:
            out.append(word)
    return out[:18]


def _sparse_vector(value: str, *, max_terms: int = 96) -> dict[str, float]:
    counts: dict[str, int] = {}
    for word in _token_stream(value, limit=1200):
        counts[word] = counts.get(word, 0) + 1
    if not counts:
        return {}
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:max_terms]
    norm = math.sqrt(sum(count * count for _, count in ranked)) or 1.0
    return {word: round(count / norm, 5) for word, count in ranked}


def _cosine_sparse(left: dict[str, Any], right: dict[str, Any]) -> float:
    if not left or not right:
        return 0.0
    score = 0.0
    for word, weight in left.items():
        try:
            score += float(weight) * float(right.get(word, 0) or 0)
        except (TypeError, ValueError):
            continue
    return round(max(0.0, min(1.0, score)), 5)


def _keywords_from_vector(vector: dict[str, float], *, limit: int = 16) -> list[str]:
    return [word for word, _ in sorted(vector.items(), key=lambda item: (-float(item[1]), item[0]))[:limit]]


def _metadata_terms(metadata: Any, *, limit: int = 48) -> list[str]:
    data = metadata if isinstance(metadata, dict) else {}
    values: list[str] = []
    for key in ("semantic_description", "description", "purpose", "notes", "fetched_title", "source_label"):
        value = _clean(data.get(key), 1200)
        if value:
            values.append(value)
    for key in ("tags", "labels", "aliases", "query_aliases", "keywords"):
        raw = data.get(key)
        if isinstance(raw, list):
            values.extend(_clean(item, 160) for item in raw if _clean(item, 160))
        elif isinstance(raw, str):
            values.extend(_clean(item, 160) for item in re.split(r"[\n,;|]+", raw) if _clean(item, 160))
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = _clean(value, 180)
        key = _normalize_for_search(clean, 180)
        if clean and key and key not in seen:
            seen.add(key)
            out.append(clean)
        if len(out) >= limit:
            break
    return out


def _term_list(values: Any, *, limit: int = 24, item_limit: int = 80) -> list[str]:
    if isinstance(values, str):
        raw_items = re.split(r"[\n,;|]+", values)
    elif isinstance(values, list):
        raw_items = values
    else:
        raw_items = []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        clean = _clean(item, item_limit)
        key = _normalize_for_search(clean, item_limit)
        if clean and key and key not in seen:
            seen.add(key)
            out.append(clean)
        if len(out) >= limit:
            break
    return out


def _source_cover_text(row: dict[str, Any]) -> str:
    metadata = _json_value(row.get("metadata_json"), {})
    parts = [
        row.get("title"),
        row.get("filename"),
        row.get("url"),
        row.get("source_type"),
        *_metadata_terms(metadata),
    ]
    return " ".join(_clean(part, 1200) for part in parts if _clean(part, 1200))


def _compact_windows(value: str, *, max_windows: int = 180) -> list[tuple[str, str]]:
    tokens = _token_stream(value, limit=180)
    windows: list[tuple[str, str]] = []
    seen: set[str] = set()
    for size in (1, 2, 3):
        for idx in range(0, max(0, len(tokens) - size + 1)):
            words = tokens[idx : idx + size]
            compact = "".join(words)
            if len(compact) < 5 or len(compact) > 42 or compact in seen:
                continue
            seen.add(compact)
            windows.append((compact, " ".join(words)))
            if len(windows) >= max_windows:
                return windows
    return windows


def _uuid_or_400(value: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="invalid_knowledge_source_id")


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
                content_hash TEXT NOT NULL DEFAULT '',
                chunk_count INTEGER NOT NULL DEFAULT 0,
                last_indexed_at TIMESTAMP NULL,
                expires_at TIMESTAMP NULL,
                error TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            """
            ALTER TABLE saas_knowledge_sources
              ADD COLUMN IF NOT EXISTS content_hash TEXT NOT NULL DEFAULT '',
              ADD COLUMN IF NOT EXISTS chunk_count INTEGER NOT NULL DEFAULT 0,
              ADD COLUMN IF NOT EXISTS last_indexed_at TIMESTAMP NULL,
              ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP NULL,
              ADD COLUMN IF NOT EXISTS error TEXT NOT NULL DEFAULT ''
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
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_knowledge_chunks (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                source_id UUID NOT NULL REFERENCES saas_knowledge_sources(id) ON DELETE CASCADE,
                chunk_index INTEGER NOT NULL DEFAULT 0,
                content TEXT NOT NULL DEFAULT '',
                token_estimate INTEGER NOT NULL DEFAULT 0,
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                vector_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                keywords_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                content_hash TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (source_id, chunk_index)
            )
            """
        )
    )
    conn.execute(
        text(
            """
            ALTER TABLE saas_knowledge_chunks
              ADD COLUMN IF NOT EXISTS vector_json JSONB NOT NULL DEFAULT '{}'::jsonb,
              ADD COLUMN IF NOT EXISTS keywords_json JSONB NOT NULL DEFAULT '[]'::jsonb
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_knowledge_chunks_tenant_source
            ON saas_knowledge_chunks (tenant_id, source_id, chunk_index)
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_knowledge_chunks_tenant_updated
            ON saas_knowledge_chunks (tenant_id, updated_at DESC)
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_knowledge_retrieval_logs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                query TEXT NOT NULL DEFAULT '',
                result_count INTEGER NOT NULL DEFAULT 0,
                top_score NUMERIC NOT NULL DEFAULT 0,
                used_by TEXT NOT NULL DEFAULT '',
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_knowledge_retrieval_logs_tenant_created
            ON saas_knowledge_retrieval_logs (tenant_id, created_at DESC)
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_knowledge_evaluations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                query TEXT NOT NULL DEFAULT '',
                expected_answer TEXT NOT NULL DEFAULT '',
                expected_sources_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                result_count INTEGER NOT NULL DEFAULT 0,
                top_score NUMERIC NOT NULL DEFAULT 0,
                confidence INTEGER NOT NULL DEFAULT 0,
                answerability TEXT NOT NULL DEFAULT 'unknown',
                quality_score INTEGER NOT NULL DEFAULT 0,
                passed BOOLEAN NOT NULL DEFAULT FALSE,
                citations_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_knowledge_evaluations_tenant_created
            ON saas_knowledge_evaluations (tenant_id, created_at DESC)
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_knowledge_evaluations_tenant_passed
            ON saas_knowledge_evaluations (tenant_id, passed, created_at DESC)
            """
        )
    )


def _safe_row(row: dict[str, Any]) -> dict[str, Any]:
    content = _clean(row.get("content"), 200000)
    metadata = _json_value(row.get("metadata_json"), {})
    metadata_obj = metadata if isinstance(metadata, dict) else {}
    return {
        "id": str(row.get("id") or ""),
        "source_type": str(row.get("source_type") or ""),
        "title": str(row.get("title") or ""),
        "url": str(row.get("url") or ""),
        "filename": str(row.get("filename") or ""),
        "status": str(row.get("status") or ""),
        "content_preview": content[:360],
        "content_chars": len(content),
        "metadata_json": metadata_obj,
        "semantic_description": _clean(metadata_obj.get("semantic_description") or metadata_obj.get("description"), 1200),
        "tags": _term_list(metadata_obj.get("tags")),
        "aliases": _term_list(metadata_obj.get("aliases")),
        "content_hash": str(row.get("content_hash") or ""),
        "chunk_count": int(row.get("chunk_count") or 0),
        "last_indexed_at": str(row.get("last_indexed_at") or ""),
        "expires_at": str(row.get("expires_at") or ""),
        "error": str(row.get("error") or ""),
        "updated_at": str(row.get("updated_at") or ""),
    }


def _split_chunks(content: str, *, max_chars: int = 1400, overlap: int = 180) -> list[str]:
    clean = re.sub(r"\r\n?", "\n", _clean(content, 500000))
    clean = re.sub(r"[ \t]+", " ", clean)
    blocks = [part.strip() for part in re.split(r"\n{2,}", clean) if part.strip()]
    if not blocks:
        blocks = [clean.strip()] if clean.strip() else []
    chunks: list[str] = []
    current = ""
    for block in blocks:
        if len(block) > max_chars:
            sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", block) if part.strip()]
        else:
            sentences = [block]
        for sentence in sentences:
            if len(sentence) > max_chars:
                for start in range(0, len(sentence), max_chars - overlap):
                    piece = sentence[start : start + max_chars].strip()
                    if piece:
                        chunks.append(piece)
                continue
            if current and len(current) + len(sentence) + 2 > max_chars:
                chunks.append(current.strip())
                tail = current[-overlap:].strip()
                current = f"{tail}\n{sentence}" if tail else sentence
            else:
                current = f"{current}\n{sentence}".strip() if current else sentence
    if current.strip():
        chunks.append(current.strip())
    return [chunk for chunk in chunks if len(chunk) >= 20][:400]


def _index_source(conn: Connection, tenant_id: str, source_id: str, content: str, metadata: dict[str, Any] | None = None) -> int:
    ensure_knowledge_tables(conn)
    chunks = _split_chunks(content)
    source_row = conn.execute(
        text(
            """
            SELECT source_type, title, filename, url, metadata_json
            FROM saas_knowledge_sources
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:source_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "source_id": source_id},
    ).mappings().first()
    source_title = _clean((source_row or {}).get("title") or (source_row or {}).get("filename") or (source_row or {}).get("url"), 500)
    source_cover = _source_cover_text(dict(source_row or {}) | {"metadata_json": metadata or (source_row or {}).get("metadata_json")})
    conn.execute(
        text(
            """
            DELETE FROM saas_knowledge_chunks
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND source_id = CAST(:source_id AS uuid)
            """
        ),
        {"tenant_id": tenant_id, "source_id": source_id},
    )
    for idx, chunk in enumerate(chunks):
        vector = _sparse_vector(f"{source_cover or source_title}\n{chunk}")
        conn.execute(
            text(
                """
                INSERT INTO saas_knowledge_chunks (
                    tenant_id, source_id, chunk_index, content, token_estimate,
                    metadata_json, vector_json, keywords_json, content_hash, updated_at
                )
                VALUES (
                    CAST(:tenant_id AS uuid), CAST(:source_id AS uuid), :chunk_index, :content,
                    :token_estimate, CAST(:metadata_json AS jsonb), CAST(:vector_json AS jsonb),
                    CAST(:keywords_json AS jsonb), :content_hash, NOW()
                )
                """
            ),
            {
                "tenant_id": tenant_id,
                "source_id": source_id,
                "chunk_index": idx,
                "content": chunk,
                "token_estimate": max(1, int(len(chunk) / 4)),
                "metadata_json": _json(metadata or {}),
                "vector_json": _json(vector),
                "keywords_json": _json(_keywords_from_vector(vector)),
                "content_hash": _content_hash(chunk),
            },
        )
    conn.execute(
        text(
            """
            UPDATE saas_knowledge_sources
            SET chunk_count = :chunk_count,
                content_hash = :content_hash,
                last_indexed_at = NOW(),
                status = CASE WHEN :chunk_count > 0 THEN 'active' ELSE 'error' END,
                error = CASE WHEN :chunk_count > 0 THEN '' ELSE 'no_indexable_chunks' END,
                updated_at = NOW()
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:source_id AS uuid)
            """
        ),
        {
            "tenant_id": tenant_id,
            "source_id": source_id,
            "chunk_count": len(chunks),
            "content_hash": _content_hash(content),
        },
    )
    return len(chunks)


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
                tenant_id, source_type, title, url, filename, content, status, metadata_json,
                content_hash, chunk_count, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), :source_type, :title, :url, :filename, :content,
                'indexing', CAST(:metadata_json AS jsonb), :content_hash, 0, NOW()
            )
            RETURNING id::text, source_type, title, url, filename, content, status, metadata_json,
                      content_hash, chunk_count, last_indexed_at::text, expires_at::text, error, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "source_type": source_type,
            "title": _clean(title, 240) or _clean(filename or url or "Fuente", 240),
            "url": _clean(url, 1000),
            "filename": _clean(filename, 240),
            "content": clean_content,
            "metadata_json": _json(metadata or {}),
            "content_hash": _content_hash(clean_content),
        },
    ).mappings().first()
    source_id = str(row["id"])
    _index_source(conn, tenant_id, source_id, clean_content, metadata=metadata or {})
    refreshed = conn.execute(
        text(
            """
            SELECT id::text, source_type, title, url, filename, content, status, metadata_json,
                   content_hash, chunk_count, last_indexed_at::text, expires_at::text, error, updated_at::text
            FROM saas_knowledge_sources
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:source_id AS uuid)
            """
        ),
        {"tenant_id": tenant_id, "source_id": source_id},
    ).mappings().first()
    return _safe_row(dict(refreshed or row))


def _score_chunk(query: str, terms: list[str], query_vector: dict[str, float], row: dict[str, Any]) -> dict[str, Any]:
    content = _clean(row.get("content"), 8000)
    source_cover = _source_cover_text(row)
    title = _clean(row.get("title"), 500)
    haystack_raw = f"{source_cover or title} {content}"
    haystack = _normalize_for_search(haystack_raw, 12000)
    cover_haystack = _normalize_for_search(source_cover or title, 4000)
    compact_query = _compact_for_search(query, 1200)
    compact_haystack = _compact_for_search(haystack_raw, 12000)
    compact_cover = _compact_for_search(source_cover or title, 4000)
    lexical_score = 0.0
    clean_query = _normalize_for_search(query, 1200)
    if clean_query and clean_query in haystack:
        lexical_score += 45
        if clean_query in cover_haystack:
            lexical_score += 18
    compact_exact = False
    if len(compact_query) >= 6 and compact_query in compact_haystack:
        compact_exact = True
        lexical_score += 58
        if compact_query in compact_cover:
            lexical_score += 18
    matched_terms: list[str] = []
    for term in terms:
        count = haystack.count(term)
        if count:
            matched_terms.append(term)
            lexical_score += min(28, 6 + (count * 2.2))
            if term in cover_haystack:
                lexical_score += 10
    if len(compact_query) >= 6 and not compact_exact:
        best_ratio = 0.0
        best_label = ""
        for compact, label in _compact_windows(haystack_raw):
            if abs(len(compact) - len(compact_query)) > max(3, int(len(compact_query) * 0.25)):
                continue
            ratio = difflib.SequenceMatcher(None, compact_query, compact).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_label = label
        if best_ratio >= 0.86:
            lexical_score += 34 * best_ratio
            if best_label:
                matched_terms.append(f"~{best_label}")
    for meta_term in _metadata_terms(_json_value(row.get("metadata_json"), {}), limit=16):
        meta_norm = _normalize_for_search(meta_term, 240)
        meta_compact = _compact_for_search(meta_term, 240)
        if not meta_norm:
            continue
        if clean_query and (clean_query in meta_norm or meta_norm in clean_query):
            lexical_score += 24
            matched_terms.append(meta_term)
        elif compact_query and len(compact_query) >= 5 and (compact_query in meta_compact or meta_compact in compact_query):
            lexical_score += 18
            matched_terms.append(meta_term)
    if row.get("source_type") == "file":
        lexical_score += 2
    if str(row.get("url") or "").strip():
        lexical_score += 1
    vector = _json_value(row.get("vector_json"), {})
    vector_score = _cosine_sparse(query_vector, vector if isinstance(vector, dict) else {}) * 100
    score = lexical_score + (vector_score * 0.72)
    return {
        "score": round(score, 2),
        "lexical_score": round(lexical_score, 2),
        "vector_score": round(vector_score, 2),
        "matched_terms": matched_terms[:12],
    }


def search_knowledge(
    conn: Connection,
    tenant_id: str,
    query: str,
    *,
    limit: int = 6,
    min_score: float = 0,
    used_by: str = "api",
) -> dict[str, Any]:
    ensure_knowledge_tables(conn)
    clean_query = _clean(query, 1200)
    terms = _tokenize(clean_query)
    query_vector = _sparse_vector(clean_query)
    if not terms and len(clean_query) < 2:
        return {
            "query": clean_query,
            "terms": [],
            "results": [],
            "context": "",
            "citations": [],
            "confidence": 0,
            "retrieval_mode": "semantic_cover_sparse_vector_lexical",
        }
    rows = conn.execute(
        text(
            """
            SELECT c.id::text AS chunk_id, c.source_id::text, c.chunk_index, c.content,
                   c.token_estimate, c.vector_json, c.keywords_json, s.source_type, s.title, s.url, s.filename,
                   s.metadata_json, s.updated_at::text, s.last_indexed_at::text
            FROM saas_knowledge_chunks c
            JOIN saas_knowledge_sources s ON s.id = c.source_id
            WHERE c.tenant_id = CAST(:tenant_id AS uuid)
              AND s.tenant_id = CAST(:tenant_id AS uuid)
              AND s.status = 'active'
              AND (s.expires_at IS NULL OR s.expires_at > NOW())
            ORDER BY s.updated_at DESC, c.chunk_index ASC
            LIMIT 1200
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().all()
    scored: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        score_data = _score_chunk(clean_query, terms, query_vector, item)
        score = float(score_data["score"])
        if score >= float(min_score or 0):
            title = _clean(item.get("title") or item.get("filename") or item.get("url") or "Fuente", 240)
            source_label = _clean(item.get("url") or item.get("filename") or title, 500)
            source_metadata = _json_value(item.get("metadata_json"), {})
            source_metadata = source_metadata if isinstance(source_metadata, dict) else {}
            confidence = min(98, int(score * 1.35))
            scored.append(
                {
                    "chunk_id": item["chunk_id"],
                    "source_id": item["source_id"],
                    "chunk_index": int(item.get("chunk_index") or 0),
                    "source_type": str(item.get("source_type") or ""),
                    "title": title,
                    "url": str(item.get("url") or ""),
                    "filename": str(item.get("filename") or ""),
                    "source_label": source_label,
                    "content": _clean(item.get("content"), 1800),
                    "semantic_description": _clean(source_metadata.get("semantic_description") or source_metadata.get("description"), 600),
                    "tags": _term_list(source_metadata.get("tags")),
                    "aliases": _term_list(source_metadata.get("aliases")),
                    "score": score,
                    "lexical_score": score_data["lexical_score"],
                    "vector_score": score_data["vector_score"],
                    "matched_terms": score_data["matched_terms"],
                    "keywords": _json_value(item.get("keywords_json"), []),
                    "confidence": confidence,
                    "updated_at": str(item.get("updated_at") or ""),
                    "last_indexed_at": str(item.get("last_indexed_at") or ""),
                }
            )
    scored.sort(key=lambda item: item["score"], reverse=True)
    results = scored[: max(1, min(int(limit or 6), 20))]
    citations = [
        {
            "source_id": item["source_id"],
            "chunk_id": item["chunk_id"],
            "title": item["title"],
            "source": item["source_label"],
            "score": item["score"],
            "vector_score": item.get("vector_score", 0),
            "confidence": item["confidence"],
            "tags": item.get("tags") or [],
            "aliases": item.get("aliases") or [],
        }
        for item in results
    ]
    context_parts = []
    for idx, item in enumerate(results, start=1):
        source = item["source_label"]
        context_parts.append(
            f"[Fuente {idx}] {item['title']}{f' ({source})' if source else ''}\n"
            f"Descripcion/uso: {item.get('semantic_description') or 'sin descripcion'}\n"
            f"Etiquetas: {', '.join(item.get('tags') or []) or 'sin etiquetas'} / Alias: {', '.join(item.get('aliases') or []) or 'sin alias'}\n"
            f"Score: {item['score']} / Vector: {item.get('vector_score', 0)} / Confianza: {item['confidence']}%\n"
            f"{item['content']}"
        )
    top_score = float(results[0]["score"]) if results else 0.0
    confidence = min(98, int(top_score * 1.35)) if results else 0
    conn.execute(
        text(
            """
            INSERT INTO saas_knowledge_retrieval_logs (
                tenant_id, query, result_count, top_score, used_by, metadata_json
            )
            VALUES (
                CAST(:tenant_id AS uuid), :query, :result_count, :top_score, :used_by, CAST(:metadata_json AS jsonb)
            )
            """
        ),
        {
            "tenant_id": tenant_id,
            "query": clean_query,
            "result_count": len(results),
            "top_score": top_score,
            "used_by": _clean(used_by, 80),
            "metadata_json": _json({"terms": terms, "citations": citations[:8], "retrieval_mode": "semantic_cover_sparse_vector_lexical"}),
        },
    )
    return {
        "query": clean_query,
        "terms": terms,
        "results": results,
        "citations": citations,
        "context": "\n\n---\n\n".join(context_parts),
        "confidence": confidence,
        "retrieval_mode": "semantic_cover_sparse_vector_lexical",
    }


def knowledge_context_for_query(conn: Connection, tenant_id: str, query: str, *, limit: int = 6, used_by: str = "ai_agent") -> str:
    result = search_knowledge(conn, tenant_id, query, limit=limit, min_score=1, used_by=used_by)
    context = _clean(result.get("context"), 9000)
    if not context:
        return ""
    citation_lines = [
        f"- Fuente {idx}: {item['title']} ({item['source']}) score {item['score']} etiquetas={', '.join(item.get('tags') or []) or 'sin etiquetas'}"
        for idx, item in enumerate(result.get("citations") or [], start=1)
    ]
    return (
        "Knowledge Base recuperada por RAG con portada semantica, sparse-vector y busqueda lexical tolerante. Usa estas fuentes como verdad primaria; "
        "si la informacion no esta aqui, pregunta o indica que debe verificarse. Cuando respondas con datos de la base, apoya la respuesta en las citas internas.\n\n"
        f"{context}\n\nCitas internas:\n" + "\n".join(citation_lines)
    )


def _extract_pdf_text(raw: bytes) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw))
        pages = [page.extract_text() or "" for page in reader.pages[:80]]
        return "\n\n".join(page.strip() for page in pages if page.strip())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"pdf_text_extract_failed:{str(exc)[:160]}")


def _decode_text(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1", errors="ignore")


def _extract_csv_text(raw: bytes) -> str:
    decoded = _decode_text(raw)
    sample = decoded[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(decoded), dialect)
    rows = [[_clean(cell, 600) for cell in row] for row in reader if any(_clean(cell, 600) for cell in row)]
    if not rows:
        return ""
    header = rows[0]
    body = rows[1:251]
    lines = ["CSV columns: " + " | ".join(header[:40])]
    for idx, row in enumerate(body, start=1):
        if header and len(row) == len(header):
            values = [f"{header[col_idx]}={row[col_idx]}" for col_idx in range(min(len(row), 40))]
        else:
            values = row[:40]
        lines.append(f"Row {idx}: " + " | ".join(values))
    return "\n".join(lines)


def _extract_file_text(filename: str, content_type: str, raw: bytes) -> str:
    name = filename.lower()
    mime = content_type.lower()
    if name.endswith(".pdf") or mime == "application/pdf":
        return _extract_pdf_text(raw)
    if name.endswith(".csv") or mime in {"text/csv", "application/csv", "application/vnd.ms-excel"}:
        return _extract_csv_text(raw)
    return _decode_text(raw)


def _validate_fetch_url(url: str) -> str:
    clean_url = _clean(url, 1000)
    parsed = urllib.parse.urlparse(clean_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=400, detail="valid_url_required")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="url_credentials_not_allowed")
    hostname = parsed.hostname.strip().lower()
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".localhost"):
        raise HTTPException(status_code=400, detail="private_url_not_allowed")
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise HTTPException(status_code=400, detail=f"url_dns_failed:{str(exc)[:120]}")
    for info in infos:
        host = info[4][0]
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            continue
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            raise HTTPException(status_code=400, detail="private_url_not_allowed")
    return urllib.parse.urlunparse(parsed)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


def _fetch_public_url(url: str, *, max_redirects: int = 4) -> tuple[str, bytes]:
    current = _validate_fetch_url(url)
    opener = urllib.request.build_opener(_NoRedirectHandler)
    for _ in range(max_redirects + 1):
        request = urllib.request.Request(current, headers={"User-Agent": "ScentraAI-Knowledge/1.0"})
        try:
            with opener.open(request, timeout=20) as response:
                return current, response.read(1_000_000)
        except urllib.error.HTTPError as exc:
            if exc.code in {301, 302, 303, 307, 308}:
                location = exc.headers.get("Location", "")
                if not location:
                    raise HTTPException(status_code=502, detail="url_redirect_missing_location")
                current = _validate_fetch_url(urllib.parse.urljoin(current, location))
                continue
            raise HTTPException(status_code=502, detail=f"url_fetch_failed:{str(exc)[:200]}")
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"url_fetch_failed:{str(exc)[:200]}")
    raise HTTPException(status_code=502, detail="url_redirect_limit_exceeded")


def _extract_url_text(url: str) -> tuple[str, str]:
    clean_url, raw_bytes = _fetch_public_url(url)
    raw = raw_bytes.decode("utf-8", errors="ignore")
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
                SELECT id::text, source_type, title, url, filename, content, status, metadata_json,
                       content_hash, chunk_count, last_indexed_at::text, expires_at::text, error, updated_at::text
                FROM saas_knowledge_sources
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                ORDER BY updated_at DESC
                LIMIT 100
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().all()
    return [_safe_row(dict(row)) for row in rows]


@router.post("/search")
def search_sources(payload: KnowledgeSearchIn, ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        ensure_knowledge_tables(conn)
        set_tenant_context(conn, ctx.tenant_id)
        return search_knowledge(
            conn,
            ctx.tenant_id,
            payload.query,
            limit=payload.limit,
            min_score=payload.min_score,
            used_by="knowledge_ui",
        )


def _evaluate_quality(result: dict[str, Any], expected_answer: str, expected_sources: list[str]) -> dict[str, Any]:
    results = result.get("results") if isinstance(result.get("results"), list) else []
    citations = result.get("citations") if isinstance(result.get("citations"), list) else []
    confidence = int(result.get("confidence") or 0)
    expected_terms = _tokenize(expected_answer)[:20]
    combined_content = " ".join(_clean(item.get("content"), 1800).lower() for item in results if isinstance(item, dict))
    if expected_terms:
        covered = sum(1 for term in expected_terms if term in combined_content)
        answer_overlap = int(round((covered / max(1, len(expected_terms))) * 100))
    else:
        answer_overlap = confidence if results else 0
    expected_source_terms = [_clean(item, 240).lower() for item in expected_sources if _clean(item, 240)]
    if expected_source_terms:
        citation_text = " ".join(
            f"{citation.get('title', '')} {citation.get('source', '')}".lower()
            for citation in citations
            if isinstance(citation, dict)
        )
        source_hits = sum(1 for item in expected_source_terms if item in citation_text)
        source_coverage = int(round((source_hits / max(1, len(expected_source_terms))) * 100))
    else:
        source_coverage = 100 if citations else 0
    quality_score = int(round((confidence * 0.45) + (answer_overlap * 0.35) + (source_coverage * 0.20)))
    answerability = "grounded" if results and quality_score >= 70 else "partial" if results and quality_score >= 45 else "weak"
    return {
        "answer_overlap": answer_overlap,
        "source_coverage": source_coverage,
        "quality_score": max(0, min(100, quality_score)),
        "answerability": answerability,
    }


@router.post("/evaluate")
def evaluate_knowledge(payload: KnowledgeEvaluationIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    expected_sources = [_clean(item, 240) for item in payload.expected_sources[:12] if _clean(item, 240)]
    with db_session() as conn:
        ensure_knowledge_tables(conn)
        set_tenant_context(conn, ctx.tenant_id)
        result = search_knowledge(
            conn,
            ctx.tenant_id,
            payload.query,
            limit=payload.limit,
            min_score=1,
            used_by="rag_evaluation",
        )
        quality = _evaluate_quality(result, payload.expected_answer, expected_sources)
        top_score = float(result["results"][0]["score"]) if result.get("results") else 0.0
        passed = bool(result.get("results")) and int(quality["quality_score"]) >= int(payload.min_quality_score)
        row = conn.execute(
            text(
                """
                INSERT INTO saas_knowledge_evaluations (
                    tenant_id, query, expected_answer, expected_sources_json, result_count,
                    top_score, confidence, answerability, quality_score, passed,
                    citations_json, metadata_json
                )
                VALUES (
                    CAST(:tenant_id AS uuid), :query, :expected_answer, CAST(:expected_sources_json AS jsonb),
                    :result_count, :top_score, :confidence, :answerability, :quality_score, :passed,
                    CAST(:citations_json AS jsonb), CAST(:metadata_json AS jsonb)
                )
                RETURNING id::text, created_at::text
                """
            ),
            {
                "tenant_id": ctx.tenant_id,
                "query": _clean(payload.query, 1200),
                "expected_answer": _clean(payload.expected_answer, 4000),
                "expected_sources_json": _json(expected_sources),
                "result_count": len(result.get("results") or []),
                "top_score": top_score,
                "confidence": int(result.get("confidence") or 0),
                "answerability": quality["answerability"],
                "quality_score": int(quality["quality_score"]),
                "passed": passed,
                "citations_json": _json(result.get("citations") or []),
                "metadata_json": _json({
                    "answer_overlap": quality["answer_overlap"],
                    "source_coverage": quality["source_coverage"],
                    "min_quality_score": payload.min_quality_score,
                    "retrieval_mode": result.get("retrieval_mode") or "semantic_cover_sparse_vector_lexical",
                }),
            },
        ).mappings().first()
    return {
        "ok": True,
        "evaluation": {
            "id": str((row or {}).get("id") or ""),
            "created_at": str((row or {}).get("created_at") or ""),
            "query": _clean(payload.query, 1200),
            "result_count": len(result.get("results") or []),
            "top_score": top_score,
            "confidence": int(result.get("confidence") or 0),
            "answerability": quality["answerability"],
            "quality_score": int(quality["quality_score"]),
            "passed": passed,
            "answer_overlap": int(quality["answer_overlap"]),
            "source_coverage": int(quality["source_coverage"]),
        },
        "search": {
            "results": result.get("results") or [],
            "citations": result.get("citations") or [],
            "retrieval_mode": result.get("retrieval_mode") or "semantic_cover_sparse_vector_lexical",
        },
    }


@router.get("/evaluations")
def list_evaluations(
    limit: int = Query(default=20, ge=1, le=100),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        ensure_knowledge_tables(conn)
        set_tenant_context(conn, ctx.tenant_id)
        rows = conn.execute(
            text(
                """
                SELECT id::text, query, expected_answer, expected_sources_json, result_count,
                       top_score, confidence, answerability, quality_score, passed,
                       citations_json, metadata_json, created_at::text
                FROM saas_knowledge_evaluations
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            {"tenant_id": ctx.tenant_id, "limit": limit},
        ).mappings().all()
    out = []
    for row in rows:
        item = dict(row)
        out.append({
            **item,
            "top_score": float(item.get("top_score") or 0),
            "confidence": int(item.get("confidence") or 0),
            "quality_score": int(item.get("quality_score") or 0),
            "passed": bool(item.get("passed")),
            "expected_sources": _json_value(item.get("expected_sources_json"), []),
            "citations": _json_value(item.get("citations_json"), []),
            "metadata_json": _json_value(item.get("metadata_json"), {}),
        })
    return out


@router.get("/health")
def knowledge_health(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        ensure_knowledge_tables(conn)
        set_tenant_context(conn, ctx.tenant_id)
        totals = conn.execute(
            text(
                """
                SELECT
                  COUNT(*)::int AS total_sources,
                  COUNT(*) FILTER (WHERE status = 'active')::int AS active_sources,
                  COUNT(*) FILTER (WHERE status = 'indexing')::int AS indexing_sources,
                  COUNT(*) FILTER (WHERE status = 'error')::int AS error_sources,
                  COALESCE(SUM(chunk_count), 0)::int AS source_chunks,
                  (SELECT COUNT(*)::int FROM saas_knowledge_chunks WHERE tenant_id = CAST(:tenant_id AS uuid)) AS chunks,
                  (SELECT COUNT(*)::int FROM saas_knowledge_chunks WHERE tenant_id = CAST(:tenant_id AS uuid) AND vector_json <> '{}'::jsonb) AS vectorized_chunks
                FROM saas_knowledge_sources
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().first()
        logs = conn.execute(
            text(
                """
                SELECT query, result_count, top_score, used_by, created_at::text
                FROM saas_knowledge_retrieval_logs
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                ORDER BY created_at DESC
                LIMIT 8
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().all()
        quality = conn.execute(
            text(
                """
                SELECT
                  COUNT(*)::int AS total_evaluations,
                  COUNT(*) FILTER (WHERE passed = TRUE)::int AS passed_evaluations,
                  COALESCE(ROUND(AVG(quality_score)), 0)::int AS avg_quality_score,
                  MAX(created_at)::text AS last_evaluated_at
                FROM saas_knowledge_evaluations
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().first()
    data = dict(totals or {})
    chunks = int(data.get("chunks") or 0)
    active = int(data.get("active_sources") or 0)
    vectorized = int(data.get("vectorized_chunks") or 0)
    status = "empty" if not active else "ready" if chunks and vectorized >= chunks else "needs_reindex"
    return {
        "ok": True,
        "totals": {key: int(value or 0) for key, value in data.items()},
        "status": status,
        "retrieval_mode": "semantic_cover_sparse_vector_lexical",
        "quality": {
            "total_evaluations": int((quality or {}).get("total_evaluations") or 0),
            "passed_evaluations": int((quality or {}).get("passed_evaluations") or 0),
            "avg_quality_score": int((quality or {}).get("avg_quality_score") or 0),
            "last_evaluated_at": str((quality or {}).get("last_evaluated_at") or ""),
        },
        "recent_retrievals": [
            {
                **dict(row),
                "top_score": float(row.get("top_score") or 0),
                "result_count": int(row.get("result_count") or 0),
            }
            for row in logs
        ],
    }


@router.post("/upload")
async def upload_source(
    file: UploadFile = File(...),
    title: str = Form(default=""),
    notes: str = Form(default=""),
    semantic_description: str = Form(default=""),
    tags: str = Form(default=""),
    aliases: str = Form(default=""),
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="knowledge_file_required")
    if len(raw) > 8_000_000:
        raise HTTPException(status_code=413, detail="knowledge_file_too_large")
    content = _extract_file_text(file.filename or "archivo", file.content_type or "", raw)
    name = (file.filename or "").lower()
    mime = (file.content_type or "").lower()
    parser = "pdf" if name.endswith(".pdf") or mime == "application/pdf" else "csv" if name.endswith(".csv") or mime in {"text/csv", "application/csv", "application/vnd.ms-excel"} else "text"
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
            metadata={
                "content_type": file.content_type or "",
                "bytes": len(raw),
                "parser": parser,
                "semantic_description": _clean(semantic_description, 1200),
                "tags": _term_list(tags, limit=24, item_limit=80),
                "aliases": _term_list(aliases, limit=32, item_limit=120),
            },
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
            metadata={
                "fetched_title": fetched_title,
                "semantic_description": _clean(payload.semantic_description, 1200),
                "tags": _term_list(payload.tags, limit=24, item_limit=80),
                "aliases": _term_list(payload.aliases, limit=32, item_limit=120),
            },
        )


@router.patch("/sources/{source_id}")
def update_source(source_id: str, payload: KnowledgeSourceUpdateIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    source_id = _uuid_or_400(source_id)
    with db_session() as conn:
        ensure_knowledge_tables(conn)
        set_tenant_context(conn, ctx.tenant_id)
        row = conn.execute(
            text(
                """
                SELECT id::text, source_type, title, url, filename, content, status, metadata_json,
                       content_hash, chunk_count, last_indexed_at::text, expires_at::text, error, updated_at::text
                FROM saas_knowledge_sources
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:source_id AS uuid)
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id, "source_id": source_id},
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="knowledge_source_not_found")
        current = dict(row)
        metadata = _json_value(current.get("metadata_json"), {})
        metadata = metadata if isinstance(metadata, dict) else {}
        if payload.semantic_description is not None:
            metadata["semantic_description"] = _clean(payload.semantic_description, 1200)
        if payload.tags is not None:
            metadata["tags"] = _term_list(payload.tags, limit=24, item_limit=80)
        if payload.aliases is not None:
            metadata["aliases"] = _term_list(payload.aliases, limit=32, item_limit=120)
        new_title = _clean(payload.title, 240) if payload.title is not None else _clean(current.get("title"), 240)
        if not new_title:
            new_title = _clean(current.get("filename") or current.get("url") or "Fuente", 240)
        conn.execute(
            text(
                """
                UPDATE saas_knowledge_sources
                SET title = :title,
                    metadata_json = CAST(:metadata_json AS jsonb),
                    updated_at = NOW()
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:source_id AS uuid)
                """
            ),
            {
                "tenant_id": ctx.tenant_id,
                "source_id": source_id,
                "title": new_title,
                "metadata_json": _json(metadata),
            },
        )
        if payload.reindex:
            _index_source(conn, ctx.tenant_id, source_id, _clean(current.get("content"), 250000), metadata=metadata)
        refreshed = conn.execute(
            text(
                """
                SELECT id::text, source_type, title, url, filename, content, status, metadata_json,
                       content_hash, chunk_count, last_indexed_at::text, expires_at::text, error, updated_at::text
                FROM saas_knowledge_sources
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:source_id AS uuid)
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id, "source_id": source_id},
        ).mappings().first()
    return {"ok": True, "source": _safe_row(dict(refreshed or current))}


@router.post("/sources/{source_id}/reindex")
def reindex_source(source_id: str, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    source_id = _uuid_or_400(source_id)
    with db_session() as conn:
        ensure_knowledge_tables(conn)
        set_tenant_context(conn, ctx.tenant_id)
        row = conn.execute(
            text(
                """
                SELECT id::text, source_type, title, url, filename, content, status, metadata_json,
                       content_hash, chunk_count, last_indexed_at::text, expires_at::text, error, updated_at::text
                FROM saas_knowledge_sources
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:source_id AS uuid)
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id, "source_id": source_id},
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="knowledge_source_not_found")
        chunk_count = _index_source(
            conn,
            ctx.tenant_id,
            source_id,
            str(row.get("content") or ""),
            metadata=_json_value(row.get("metadata_json"), {}),
        )
        refreshed = conn.execute(
            text(
                """
                SELECT id::text, source_type, title, url, filename, content, status, metadata_json,
                       content_hash, chunk_count, last_indexed_at::text, expires_at::text, error, updated_at::text
                FROM saas_knowledge_sources
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:source_id AS uuid)
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id, "source_id": source_id},
        ).mappings().first()
    return {"ok": True, "chunk_count": chunk_count, "source": _safe_row(dict(refreshed or row))}


@router.post("/reindex")
def reindex_all_sources(
    limit: int = Query(default=50, ge=1, le=200),
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        ensure_knowledge_tables(conn)
        set_tenant_context(conn, ctx.tenant_id)
        rows = conn.execute(
            text(
                """
                SELECT id::text, content, metadata_json
                FROM saas_knowledge_sources
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND status IN ('active', 'error', 'indexing')
                ORDER BY updated_at DESC
                LIMIT :limit
                """
            ),
            {"tenant_id": ctx.tenant_id, "limit": limit},
        ).mappings().all()
        indexed = 0
        chunks = 0
        for row in rows:
            chunks += _index_source(
                conn,
                ctx.tenant_id,
                str(row["id"]),
                str(row.get("content") or ""),
                metadata=_json_value(row.get("metadata_json"), {}),
            )
            indexed += 1
    return {"ok": True, "indexed_sources": indexed, "chunks": chunks}


@router.delete("/sources/{source_id}")
def delete_source(source_id: str, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    source_id = _uuid_or_400(source_id)
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
