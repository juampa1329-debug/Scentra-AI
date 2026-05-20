from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app_saas.ai_agent.service import get_settings
from app_saas.ai_gateway.service import generate_with_gateway
from app_saas.shared.secrets import decrypt_secret


@dataclass
class NormalizedSocialComment:
    channel: str
    provider: str
    external_comment_id: str
    external_post_id: str
    author_external_id: str
    message: str
    author_name: str = ""
    author_username: str = ""
    author_profile_pic: str = ""
    parent_comment_id: str = ""
    post_caption: str = ""
    post_permalink: str = ""
    post_media_url: str = ""
    post_type: str = ""
    external_created_time: str = ""
    payload: dict[str, Any] | None = None


def _clean(value: Any, limit: int = 1000) -> str:
    return str(value or "").strip()[:limit]


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _ts(value: Any) -> str:
    raw = _clean(value, 80)
    if raw.isdigit():
        try:
            return datetime.fromtimestamp(int(raw), tz=timezone.utc).isoformat()
        except Exception:
            return raw
    return raw


def ensure_social_tables(conn: Connection) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS social_posts (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                provider TEXT NOT NULL DEFAULT 'meta',
                channel TEXT NOT NULL DEFAULT 'instagram',
                external_post_id TEXT NOT NULL,
                page_id TEXT NOT NULL DEFAULT '',
                instagram_business_account_id TEXT NOT NULL DEFAULT '',
                author_external_id TEXT NOT NULL DEFAULT '',
                caption TEXT NOT NULL DEFAULT '',
                post_type TEXT NOT NULL DEFAULT '',
                permalink_url TEXT NOT NULL DEFAULT '',
                media_url TEXT NOT NULL DEFAULT '',
                thumbnail_url TEXT NOT NULL DEFAULT '',
                payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                external_created_time TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, channel, external_post_id)
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS social_comments (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                post_id UUID NULL REFERENCES social_posts(id) ON DELETE SET NULL,
                provider TEXT NOT NULL DEFAULT 'meta',
                channel TEXT NOT NULL DEFAULT 'instagram',
                external_comment_id TEXT NOT NULL,
                parent_comment_id TEXT NOT NULL DEFAULT '',
                author_external_id TEXT NOT NULL DEFAULT '',
                author_name TEXT NOT NULL DEFAULT '',
                author_username TEXT NOT NULL DEFAULT '',
                author_profile_pic TEXT NOT NULL DEFAULT '',
                message TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'open',
                ai_status TEXT NOT NULL DEFAULT '',
                ai_suggestion TEXT NOT NULL DEFAULT '',
                last_reply_text TEXT NOT NULL DEFAULT '',
                last_reply_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                external_created_time TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, channel, external_comment_id)
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS comment_ai_settings (
                tenant_id UUID PRIMARY KEY REFERENCES saas_tenants(id) ON DELETE CASCADE,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                auto_generate BOOLEAN NOT NULL DEFAULT FALSE,
                auto_reply BOOLEAN NOT NULL DEFAULT FALSE,
                tone TEXT NOT NULL DEFAULT 'calido, breve y util',
                instructions TEXT NOT NULL DEFAULT '',
                blocked_words_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                escalation_keywords_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                provider_policy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_social_comments_tenant_status ON social_comments (tenant_id, status, updated_at DESC)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_social_posts_tenant_updated ON social_posts (tenant_id, updated_at DESC)"))


def normalize_social_comments(provider: str, payload: dict[str, Any], fallback_event_id: str) -> list[NormalizedSocialComment]:
    provider_clean = _clean(provider, 50).lower()
    comments: list[NormalizedSocialComment] = []
    for entry in _as_list(payload.get("entry")):
        entry_dict = _as_dict(entry)
        page_or_ig_id = _clean(entry_dict.get("id"), 120)
        for change in _as_list(entry_dict.get("changes")):
            change_dict = _as_dict(change)
            field = _clean(change_dict.get("field"), 80).lower()
            value = _as_dict(change_dict.get("value"))
            if field not in {"comments", "comment", "mentions", "feed"}:
                continue
            verb = _clean(value.get("verb"), 80).lower()
            item = _clean(value.get("item"), 80).lower()
            if field == "feed" and item != "comment":
                continue
            if verb in {"remove", "hide"}:
                continue
            author = _as_dict(value.get("from"))
            channel = "facebook" if provider_clean == "facebook" or field == "feed" else "instagram"
            comment_id = _clean(value.get("comment_id") or value.get("id"), 240) or fallback_event_id
            post_id = _clean(value.get("post_id") or value.get("media_id") or value.get("parent_id") or page_or_ig_id, 240)
            comments.append(
                NormalizedSocialComment(
                    channel=channel,
                    provider=provider_clean or "meta",
                    external_comment_id=comment_id,
                    external_post_id=post_id,
                    parent_comment_id=_clean(value.get("parent_id"), 240),
                    author_external_id=_clean(author.get("id") or value.get("sender_id") or value.get("user_id"), 180),
                    author_name=_clean(author.get("name"), 180),
                    author_username=_clean(author.get("username"), 180),
                    author_profile_pic=_clean(author.get("profile_pic") or author.get("profile_picture"), 1000),
                    message=_clean(value.get("message") or value.get("text") or "", 4000),
                    post_caption=_clean(value.get("caption") or value.get("post_caption"), 4000),
                    post_permalink=_clean(value.get("permalink_url") or value.get("permalink"), 1000),
                    post_media_url=_clean(value.get("media_url") or value.get("photo") or value.get("image_url"), 1000),
                    post_type=_clean(value.get("media_type") or value.get("post_type") or item, 80),
                    external_created_time=_ts(value.get("created_time") or value.get("timestamp")),
                    payload=value,
                )
            )
    return comments


def store_social_comment(conn: Connection, tenant_id: str, comment: NormalizedSocialComment) -> dict[str, Any]:
    ensure_social_tables(conn)
    post = conn.execute(
        text(
            """
            INSERT INTO social_posts (
                tenant_id, provider, channel, external_post_id, caption, post_type,
                permalink_url, media_url, payload_json, external_created_time, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), :provider, :channel, :external_post_id, :caption, :post_type,
                :permalink_url, :media_url, CAST(:payload_json AS jsonb), :external_created_time, NOW()
            )
            ON CONFLICT (tenant_id, channel, external_post_id)
            DO UPDATE SET
                caption = COALESCE(NULLIF(EXCLUDED.caption, ''), social_posts.caption),
                post_type = COALESCE(NULLIF(EXCLUDED.post_type, ''), social_posts.post_type),
                permalink_url = COALESCE(NULLIF(EXCLUDED.permalink_url, ''), social_posts.permalink_url),
                media_url = COALESCE(NULLIF(EXCLUDED.media_url, ''), social_posts.media_url),
                payload_json = social_posts.payload_json || EXCLUDED.payload_json,
                updated_at = NOW()
            RETURNING id::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "provider": comment.provider,
            "channel": comment.channel,
            "external_post_id": comment.external_post_id,
            "caption": comment.post_caption,
            "post_type": comment.post_type,
            "permalink_url": comment.post_permalink,
            "media_url": comment.post_media_url,
            "payload_json": _json(comment.payload or {}),
            "external_created_time": comment.external_created_time,
        },
    ).mappings().first()
    row = conn.execute(
        text(
            """
            INSERT INTO social_comments (
                tenant_id, post_id, provider, channel, external_comment_id, parent_comment_id,
                author_external_id, author_name, author_username, author_profile_pic,
                message, payload_json, external_created_time, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), CAST(:post_id AS uuid), :provider, :channel,
                :external_comment_id, :parent_comment_id, :author_external_id, :author_name,
                :author_username, :author_profile_pic, :message, CAST(:payload_json AS jsonb),
                :external_created_time, NOW()
            )
            ON CONFLICT (tenant_id, channel, external_comment_id)
            DO UPDATE SET
                author_name = COALESCE(NULLIF(EXCLUDED.author_name, ''), social_comments.author_name),
                author_username = COALESCE(NULLIF(EXCLUDED.author_username, ''), social_comments.author_username),
                author_profile_pic = COALESCE(NULLIF(EXCLUDED.author_profile_pic, ''), social_comments.author_profile_pic),
                message = COALESCE(NULLIF(EXCLUDED.message, ''), social_comments.message),
                payload_json = social_comments.payload_json || EXCLUDED.payload_json,
                updated_at = NOW()
            RETURNING id::text, status
            """
        ),
        {
            "tenant_id": tenant_id,
            "post_id": post["id"],
            "provider": comment.provider,
            "channel": comment.channel,
            "external_comment_id": comment.external_comment_id,
            "parent_comment_id": comment.parent_comment_id,
            "author_external_id": comment.author_external_id,
            "author_name": comment.author_name,
            "author_username": comment.author_username,
            "author_profile_pic": comment.author_profile_pic,
            "message": comment.message,
            "payload_json": _json(comment.payload or {}),
            "external_created_time": comment.external_created_time,
        },
    ).mappings().first()
    return {"id": str(row["id"]), "post_id": str(post["id"]), "status": str(row["status"])}


def default_comment_ai_settings(tenant_id: str) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "enabled": True,
        "auto_generate": False,
        "auto_reply": False,
        "tone": "calido, breve y util",
        "instructions": "Responde comentarios con tono humano. Si preguntan precio, disponibilidad o envio, invita a continuar por DM cuando haga falta.",
        "blocked_words_json": [],
        "escalation_keywords_json": ["queja", "reclamo", "demanda", "estafa", "malo", "horrible"],
        "provider_policy_json": {"preferred": "google", "fallback": "openrouter"},
        "updated_at": "",
    }


def get_comment_ai_settings(conn: Connection, tenant_id: str) -> dict[str, Any]:
    ensure_social_tables(conn)
    row = conn.execute(
        text(
            """
            SELECT tenant_id::text, enabled, auto_generate, auto_reply, tone, instructions,
                   blocked_words_json, escalation_keywords_json, provider_policy_json, updated_at::text
            FROM comment_ai_settings
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    return dict(row) if row else default_comment_ai_settings(tenant_id)


def upsert_comment_ai_settings(conn: Connection, tenant_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    ensure_social_tables(conn)
    current = get_comment_ai_settings(conn, tenant_id)
    data = {**current, **payload}
    conn.execute(
        text(
            """
            INSERT INTO comment_ai_settings (
                tenant_id, enabled, auto_generate, auto_reply, tone, instructions,
                blocked_words_json, escalation_keywords_json, provider_policy_json, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), :enabled, :auto_generate, :auto_reply, :tone, :instructions,
                CAST(:blocked AS jsonb), CAST(:escalation AS jsonb), CAST(:provider_policy AS jsonb), NOW()
            )
            ON CONFLICT (tenant_id)
            DO UPDATE SET
                enabled = EXCLUDED.enabled,
                auto_generate = EXCLUDED.auto_generate,
                auto_reply = EXCLUDED.auto_reply,
                tone = EXCLUDED.tone,
                instructions = EXCLUDED.instructions,
                blocked_words_json = EXCLUDED.blocked_words_json,
                escalation_keywords_json = EXCLUDED.escalation_keywords_json,
                provider_policy_json = EXCLUDED.provider_policy_json,
                updated_at = NOW()
            """
        ),
        {
            "tenant_id": tenant_id,
            "enabled": bool(data.get("enabled", True)),
            "auto_generate": bool(data.get("auto_generate", False)),
            "auto_reply": bool(data.get("auto_reply", False)),
            "tone": _clean(data.get("tone"), 240),
            "instructions": _clean(data.get("instructions"), 4000),
            "blocked": _json(data.get("blocked_words_json") if isinstance(data.get("blocked_words_json"), list) else []),
            "escalation": _json(data.get("escalation_keywords_json") if isinstance(data.get("escalation_keywords_json"), list) else []),
            "provider_policy": _json(data.get("provider_policy_json") if isinstance(data.get("provider_policy_json"), dict) else {}),
        },
    )
    return get_comment_ai_settings(conn, tenant_id)


def list_social_comments(conn: Connection, tenant_id: str, *, channel: str = "", status: str = "", limit: int = 50) -> list[dict[str, Any]]:
    ensure_social_tables(conn)
    filters = ["c.tenant_id = CAST(:tenant_id AS uuid)"]
    params: dict[str, Any] = {"tenant_id": tenant_id, "limit": max(1, min(int(limit or 50), 200))}
    if channel:
        filters.append("c.channel = :channel")
        params["channel"] = _clean(channel, 40).lower()
    if status:
        filters.append("c.status = :status")
        params["status"] = _clean(status, 40).lower()
    rows = conn.execute(
        text(
            f"""
            SELECT c.id::text, c.provider, c.channel, c.external_comment_id, c.parent_comment_id,
                   c.author_external_id, c.author_name, c.author_username, c.author_profile_pic,
                   c.message, c.status, c.ai_status, c.ai_suggestion, c.last_reply_text,
                   c.last_reply_payload, c.payload_json, c.external_created_time,
                   c.created_at::text, c.updated_at::text,
                   p.id::text AS post_id, p.external_post_id, p.caption AS post_caption,
                   p.post_type, p.permalink_url, p.media_url, p.thumbnail_url
            FROM social_comments c
            LEFT JOIN social_posts p ON p.id = c.post_id
            WHERE {" AND ".join(filters)}
            ORDER BY c.updated_at DESC
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()
    return [dict(row) for row in rows]


def _load_comment(conn: Connection, tenant_id: str, comment_id: str) -> dict[str, Any]:
    ensure_social_tables(conn)
    row = conn.execute(
        text(
            """
            SELECT c.id::text, c.provider, c.channel, c.external_comment_id, c.parent_comment_id,
                   c.author_external_id, c.author_name, c.author_username, c.author_profile_pic,
                   c.message, c.status, c.ai_status, c.ai_suggestion, c.last_reply_text,
                   c.last_reply_payload, c.payload_json, c.external_created_time,
                   c.created_at::text, c.updated_at::text,
                   p.id::text AS post_id, p.external_post_id, p.caption AS post_caption,
                   p.post_type, p.permalink_url, p.media_url, p.thumbnail_url
            FROM social_comments c
            LEFT JOIN social_posts p ON p.id = c.post_id
            WHERE c.tenant_id = CAST(:tenant_id AS uuid)
              AND c.id = CAST(:comment_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "comment_id": comment_id},
    ).mappings().first()
    if row:
        return dict(row)
    raise HTTPException(status_code=404, detail="social_comment_not_found")


def _integration_for_channel(conn: Connection, tenant_id: str, channel: str) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            """
            SELECT provider, channel, status, config_json
            FROM saas_integrations
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND channel = :channel
              AND status = 'connected'
            ORDER BY updated_at DESC NULLS LAST
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "channel": channel},
    ).mappings().first()
    return dict(row) if row else None


def _page_token(config: dict[str, Any]) -> str:
    for key in ("page_access_token", "facebook_page_access_token", "instagram_page_access_token", "access_token", "token"):
        value = decrypt_secret(str(config.get(key) or "").strip())
        if value:
            return value
    return ""


def _graph_post_form(url: str, token: str, payload: dict[str, Any], timeout: int = 20) -> dict[str, Any]:
    body = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            meta = json.loads(raw)
        except Exception:
            meta = {"raw": raw[:600]}
        raise HTTPException(status_code=502, detail={"code": "meta_comment_reply_failed", "meta": meta})


def reply_to_social_comment(conn: Connection, tenant_id: str, comment_id: str, body: str) -> dict[str, Any]:
    ensure_social_tables(conn)
    comment = _load_comment(conn, tenant_id, comment_id)
    text_body = _clean(body, 1000)
    if not text_body:
        raise HTTPException(status_code=400, detail="comment_reply_required")
    integration = _integration_for_channel(conn, tenant_id, str(comment["channel"]))
    config = dict((integration or {}).get("config_json") or {})
    mode = str(config.get("dispatch_mode") or "stub").lower()
    response: dict[str, Any] = {"mode": "stub", "id": f"stub:{uuid4().hex}"}
    if mode not in {"stub", "local", "disabled"}:
        token = _page_token(config)
        if not token:
            raise HTTPException(status_code=400, detail="page_access_token_required")
        version = _clean(config.get("graph_api_version") or "v24.0", 20)
        base_url = _clean(config.get("graph_base_url") or "https://graph.facebook.com", 200).rstrip("/")
        external_comment_id = urllib.parse.quote(str(comment["external_comment_id"]), safe="")
        edge = "replies" if str(comment["channel"]) == "instagram" else "comments"
        response = _graph_post_form(f"{base_url}/{version}/{external_comment_id}/{edge}", token, {"message": text_body})
    conn.execute(
        text(
            """
            UPDATE social_comments
            SET status = 'replied',
                last_reply_text = :reply,
                last_reply_payload = CAST(:payload AS jsonb),
                updated_at = NOW()
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:comment_id AS uuid)
            """
        ),
        {"tenant_id": tenant_id, "comment_id": comment_id, "reply": text_body, "payload": _json(response)},
    )
    return {"ok": True, "comment_id": comment_id, "reply": text_body, "provider_response": response}


def generate_social_comment_reply(conn: Connection, tenant_id: str, comment_id: str) -> dict[str, Any]:
    comment = _load_comment(conn, tenant_id, comment_id)
    settings = get_comment_ai_settings(conn, tenant_id)
    if not bool(settings.get("enabled", True)):
        raise HTTPException(status_code=409, detail="comment_ai_disabled")
    ai_settings = get_settings(conn, tenant_id)
    provider_policy = settings.get("provider_policy_json") if isinstance(settings.get("provider_policy_json"), dict) else {}
    provider_chain = [
        _clean(provider_policy.get("preferred") or ai_settings.get("provider_code") or "google", 80).lower(),
        _clean(provider_policy.get("fallback") or ai_settings.get("fallback_provider_code") or "openrouter", 80).lower(),
    ]
    system_prompt = (
        "Eres un asistente de social media de Scentra. Responde comentarios publicos con tono humano, breve y seguro. "
        "No inventes precios, disponibilidad ni politicas. Si falta contexto, invita a continuar por DM. "
        f"Tono: {settings.get('tone') or 'calido'}.\nInstrucciones del negocio: {settings.get('instructions') or ''}"
    )
    user_prompt = (
        f"Canal: {comment.get('channel')}\n"
        f"Autor: {comment.get('author_name') or comment.get('author_username') or comment.get('author_external_id')}\n"
        f"Publicacion: {comment.get('post_caption') or '[sin caption]'}\n"
        f"Comentario: {comment.get('message')}\n\n"
        "Devuelve solo el texto sugerido para responder el comentario. Maximo 500 caracteres."
    )
    gateway = generate_with_gateway(
        conn,
        tenant_id=tenant_id,
        task_type="social_comment_reply",
        agent_type="comment_ai_agent",
        route_code="social.comments",
        conversation_id="",
        provider_chain=provider_chain,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        settings={**ai_settings, "metadata_json": {"comment_id": comment_id, "channel": comment.get("channel")}},
    )
    if not gateway.get("ok"):
        raise HTTPException(status_code=409, detail=gateway.get("skipped") or "comment_ai_unavailable")
    suggestion = _clean(gateway.get("raw"), 1000).strip().strip('"')
    conn.execute(
        text(
            """
            UPDATE social_comments
            SET ai_status = 'suggested',
                ai_suggestion = :suggestion,
                updated_at = NOW()
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:comment_id AS uuid)
            """
        ),
        {"tenant_id": tenant_id, "comment_id": comment_id, "suggestion": suggestion},
    )
    return {"ok": True, "comment_id": comment_id, "suggestion": suggestion, "ai": gateway}
