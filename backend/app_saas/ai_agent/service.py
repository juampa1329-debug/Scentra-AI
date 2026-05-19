from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app_saas.ai_gateway.service import generate_with_gateway
from app_saas.api_credentials.router import _ensure_api_credentials_table
from app_saas.billing.limits import ensure_ai_token_quota, ensure_monthly_message_quota
from app_saas.db import db_session, set_tenant_context
from app_saas.knowledge.router import ensure_knowledge_tables
from app_saas.shared.secrets import decrypt_secret
from app_saas.workers.dispatch import (
    DispatchPermanentError,
    DispatchTransientError,
    _integration_config,
    _load_connected_integration,
    _meta_graph_version,
    _post_json,
    _secret_from_env,
)

DEFAULT_AGENT_PROMPT = """Eres el agente comercial de Scentra +AI para WhatsApp y CRM.
Tu trabajo es vender con tono humano, claro y consultivo, mantener el contexto de la conversacion y actualizar la ficha CRM.
No inventes precios, disponibilidad, politicas, enlaces ni promesas si no aparecen en el contexto. Si falta informacion, pregunta de forma breve.
Cuando el cliente comparta datos utiles, extraelos para CRM: nombre, apellido, ciudad, intereses, etiquetas, etapa comercial, estado de pago, intencion y notas.
Responde siempre en el idioma del cliente, normalmente espanol colombiano, con frases naturales y cortas."""

PROVIDER_CREDENTIAL_KEYS = {
    "google": "GOOGLE_AI_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "kimi": "KIMI_API_KEY",
}

PROVIDER_DEFAULT_MODELS = {
    "google": "gemini-2.5-flash",
    "groq": "llama-3.1-8b-instant",
    "mistral": "mistral-small-latest",
    "openrouter": "google/gemini-2.5-flash",
    "kimi": "kimi-k2.6",
}

CRM_FIELDS = {
    "display_name",
    "first_name",
    "last_name",
    "city",
    "customer_type",
    "interests",
    "tags",
    "notes",
    "payment_status",
    "crm_stage",
    "intent",
}


def _clean(value: Any, limit: int = 4000) -> str:
    return str(value or "").strip()[:limit]


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _period_yyyymm() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m")


def estimate_tokens(*parts: Any) -> int:
    size = sum(len(str(part or "")) for part in parts)
    return max(1, int(size / 4) + 120)


def ensure_ai_tables(conn: Connection) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_settings (
                tenant_id UUID PRIMARY KEY REFERENCES saas_tenants(id) ON DELETE CASCADE,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                provider_code TEXT NOT NULL DEFAULT 'google',
                fallback_provider_code TEXT NOT NULL DEFAULT '',
                system_prompt TEXT NOT NULL DEFAULT '',
                max_tokens INTEGER NOT NULL DEFAULT 1800,
                temperature NUMERIC(4,2) NOT NULL DEFAULT 0.5,
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
            CREATE TABLE IF NOT EXISTS saas_conversation_memory (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                conversation_id UUID NOT NULL REFERENCES saas_conversations(id) ON DELETE CASCADE,
                summary TEXT NOT NULL DEFAULT '',
                facts_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                last_message_id UUID NULL REFERENCES saas_messages(id) ON DELETE SET NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, conversation_id)
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_conversation_memory_tenant_updated
            ON saas_conversation_memory (tenant_id, updated_at DESC)
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_pending_replies (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                conversation_id UUID NOT NULL REFERENCES saas_conversations(id) ON DELETE CASCADE,
                last_message_id UUID NULL REFERENCES saas_messages(id) ON DELETE SET NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                scheduled_at TIMESTAMP NOT NULL DEFAULT NOW(),
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, conversation_id)
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_ai_pending_due
            ON saas_ai_pending_replies (tenant_id, status, scheduled_at)
            """
        )
    )


def default_settings(tenant_id: str) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "enabled": True,
        "provider_code": "google",
        "fallback_provider_code": "groq",
        "system_prompt": DEFAULT_AGENT_PROMPT,
        "max_tokens": 1800,
        "temperature": 0.5,
        "metadata_json": {},
        "updated_at": "",
        "active_model": "",
        "fallback_model": "",
    }


def _provider_model_from_credentials(conn: Connection, tenant_id: str, provider_code: str) -> tuple[str, str, str]:
    provider = _clean(provider_code, 80).lower()
    if not provider:
        return "", "", ""
    _ensure_api_credentials_table(conn)
    preferred_key = PROVIDER_CREDENTIAL_KEYS.get(provider, "")
    filters = [
        "tenant_id = CAST(:tenant_id AS uuid)",
        "provider_code = :provider_code",
        "category = 'ai'",
    ]
    params: dict[str, Any] = {"tenant_id": tenant_id, "provider_code": provider}
    order = "updated_at DESC"
    if preferred_key:
        order = "CASE WHEN credential_key = :preferred_key THEN 0 ELSE 1 END, updated_at DESC"
        params["preferred_key"] = preferred_key
    row = conn.execute(
        text(
            f"""
            SELECT credential_key, secret_value, metadata_json
            FROM saas_api_credentials
            WHERE {" AND ".join(filters)}
            ORDER BY {order}
            LIMIT 1
            """
        ),
        params,
    ).mappings().first()
    if not row:
        return "", PROVIDER_DEFAULT_MODELS.get(provider, ""), preferred_key
    metadata = row.get("metadata_json") if isinstance(row.get("metadata_json"), dict) else {}
    return (
        decrypt_secret(str(row.get("secret_value") or "")),
        _clean(metadata.get("selected_model") or PROVIDER_DEFAULT_MODELS.get(provider, ""), 240),
        str(row.get("credential_key") or preferred_key),
    )


def get_settings(conn: Connection, tenant_id: str) -> dict[str, Any]:
    ensure_ai_tables(conn)
    row = conn.execute(
        text(
            """
            SELECT tenant_id::text, enabled, provider_code, fallback_provider_code,
                   system_prompt, max_tokens, temperature, metadata_json, updated_at::text
            FROM saas_ai_settings
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    data = dict(row) if row else default_settings(tenant_id)
    if not _clean(data.get("system_prompt")):
        data["system_prompt"] = DEFAULT_AGENT_PROMPT
    _, active_model, _ = _provider_model_from_credentials(conn, tenant_id, str(data.get("provider_code") or ""))
    _, fallback_model, _ = _provider_model_from_credentials(conn, tenant_id, str(data.get("fallback_provider_code") or ""))
    data["active_model"] = active_model
    data["fallback_model"] = fallback_model
    data["max_tokens"] = int(data.get("max_tokens") or 1800)
    data["temperature"] = float(data.get("temperature") or 0.5)
    data["metadata_json"] = data.get("metadata_json") if isinstance(data.get("metadata_json"), dict) else {}
    return data


def upsert_settings(conn: Connection, tenant_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    ensure_ai_tables(conn)
    provider = _clean(payload.get("provider_code") or "google", 80).lower()
    fallback = _clean(payload.get("fallback_provider_code") or "", 80).lower()
    system_prompt = _clean(payload.get("system_prompt") or DEFAULT_AGENT_PROMPT, 20000)
    metadata = payload.get("metadata_json") if isinstance(payload.get("metadata_json"), dict) else {}
    conn.execute(
        text(
            """
            INSERT INTO saas_ai_settings (
                tenant_id, enabled, provider_code, fallback_provider_code, system_prompt,
                max_tokens, temperature, metadata_json, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), :enabled, :provider_code, :fallback_provider_code, :system_prompt,
                :max_tokens, :temperature, CAST(:metadata_json AS jsonb), NOW()
            )
            ON CONFLICT (tenant_id)
            DO UPDATE SET
                enabled = EXCLUDED.enabled,
                provider_code = EXCLUDED.provider_code,
                fallback_provider_code = EXCLUDED.fallback_provider_code,
                system_prompt = EXCLUDED.system_prompt,
                max_tokens = EXCLUDED.max_tokens,
                temperature = EXCLUDED.temperature,
                metadata_json = EXCLUDED.metadata_json,
                updated_at = NOW()
            """
        ),
        {
            "tenant_id": tenant_id,
            "enabled": bool(payload.get("enabled", True)),
            "provider_code": provider,
            "fallback_provider_code": fallback,
            "system_prompt": system_prompt,
            "max_tokens": int(payload.get("max_tokens") or 1800),
            "temperature": float(payload.get("temperature") or 0.5),
            "metadata_json": _json(metadata),
        },
    )
    return get_settings(conn, tenant_id)


def get_memory(conn: Connection, tenant_id: str, conversation_id: str) -> dict[str, Any]:
    ensure_ai_tables(conn)
    row = conn.execute(
        text(
            """
            SELECT tenant_id::text, conversation_id::text, summary, facts_json,
                   COALESCE(last_message_id::text, '') AS last_message_id,
                   updated_at::text
            FROM saas_conversation_memory
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND conversation_id = CAST(:conversation_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "conversation_id": conversation_id},
    ).mappings().first()
    if row:
        data = dict(row)
        data["facts_json"] = data.get("facts_json") if isinstance(data.get("facts_json"), dict) else {}
        return data
    return {
        "tenant_id": tenant_id,
        "conversation_id": conversation_id,
        "summary": "",
        "facts_json": {},
        "last_message_id": "",
        "updated_at": "",
    }


def _conversation(conn: Connection, tenant_id: str, conversation_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            """
            SELECT id::text, tenant_id::text, channel, external_contact_id, phone, display_name,
                   first_name, last_name, city, customer_type, interests, takeover,
                   last_message_text, unread_count, tags, notes, payment_status,
                   payment_reference, crm_stage, intent, profile_json, updated_at::text
            FROM saas_conversations
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:conversation_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "conversation_id": conversation_id},
    ).mappings().first()
    return dict(row) if row else None


def _recent_messages(conn: Connection, tenant_id: str, conversation_id: str, limit: int = 24) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT id::text, direction, msg_type, text, media_id, mime_type, payload_json, created_at::text
            FROM saas_messages
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND conversation_id = CAST(:conversation_id AS uuid)
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "conversation_id": conversation_id, "limit": limit},
    ).mappings().all()
    messages = [dict(row) for row in rows]
    messages.reverse()
    return messages


def _knowledge_context(conn: Connection, tenant_id: str, messages: list[dict[str, Any]]) -> str:
    ensure_knowledge_tables(conn)
    last_text = " ".join(_clean(message.get("text"), 500) for message in messages[-6:] if str(message.get("direction")).lower() == "in")
    words = [word.lower() for word in re.findall(r"[a-zA-ZáéíóúÁÉÍÓÚñÑ0-9]{4,}", last_text)[:10]]
    rows = conn.execute(
        text(
            """
            SELECT title, url, filename, content
            FROM saas_knowledge_sources
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND status = 'active'
            ORDER BY
              CASE
                WHEN :needle <> '' AND LOWER(content || ' ' || title) LIKE :needle THEN 0
                ELSE 1
              END,
              updated_at DESC
            LIMIT 8
            """
        ),
        {"tenant_id": tenant_id, "needle": f"%{words[0]}%" if words else ""},
    ).mappings().all()
    snippets = []
    for row in rows:
        content = _clean(row.get("content"), 1800)
        if words:
            lowered = content.lower()
            hit = next((word for word in words if word in lowered), "")
            if hit:
                pos = max(0, lowered.find(hit) - 420)
                content = content[pos : pos + 1800]
        title = _clean(row.get("title") or row.get("filename") or row.get("url") or "Fuente", 240)
        source = _clean(row.get("url") or row.get("filename"), 320)
        snippets.append(f"Fuente: {title}{f' ({source})' if source else ''}\n{content}")
    return "\n\n---\n\n".join(snippets)


def _prompt(settings: dict[str, Any], conversation: dict[str, Any], memory: dict[str, Any], messages: list[dict[str, Any]], knowledge_context: str = "") -> tuple[str, str]:
    system_prompt = _clean(settings.get("system_prompt") or DEFAULT_AGENT_PROMPT, 20000)
    facts = memory.get("facts_json") if isinstance(memory.get("facts_json"), dict) else {}
    transcript_lines = []
    for message in messages:
        role = "NEGOCIO" if str(message.get("direction")).lower() == "out" else "CLIENTE"
        msg_type = _clean(message.get("msg_type") or "text", 40)
        text_value = _clean(message.get("text") or f"[{msg_type}]", 4000)
        transcript_lines.append(f"{role} ({msg_type}): {text_value}")
    crm_context = {
        "display_name": conversation.get("display_name"),
        "first_name": conversation.get("first_name"),
        "last_name": conversation.get("last_name"),
        "phone": conversation.get("phone") or conversation.get("external_contact_id"),
        "city": conversation.get("city"),
        "customer_type": conversation.get("customer_type"),
        "interests": conversation.get("interests"),
        "tags": conversation.get("tags"),
        "notes": conversation.get("notes"),
        "payment_status": conversation.get("payment_status"),
        "payment_reference": conversation.get("payment_reference"),
        "crm_stage": conversation.get("crm_stage"),
        "intent": conversation.get("intent"),
    }
    user_prompt = f"""
Contexto CRM actual:
{json.dumps(crm_context, ensure_ascii=False)}

Memoria resumida de la conversacion:
{memory.get("summary") or "Sin memoria todavia."}

Hechos guardados:
{json.dumps(facts, ensure_ascii=False)}

Base de conocimiento disponible:
{knowledge_context or "Sin fuentes activas. Si falta informacion, pregunta o indica que se debe verificar."}

Conversacion reciente:
{chr(10).join(transcript_lines[-24:])}

Tarea:
1. Responde al ultimo mensaje del cliente si corresponde.
2. Extrae o mejora los campos CRM solo con datos razonables de la conversacion.
3. Actualiza una memoria breve para continuar el seguimiento comercial.

Devuelve UNICAMENTE JSON valido con esta forma:
{{
  "reply": "respuesta para enviar por WhatsApp, o texto vacio si no debes responder",
  "memory_summary": "resumen breve de contexto y siguiente paso",
  "facts": {{"need": "", "budget": "", "product_interest": "", "objections": "", "next_step": ""}},
  "crm": {{
    "display_name": "",
    "first_name": "",
    "last_name": "",
    "city": "",
    "customer_type": "",
    "interests": "",
    "tags": ["tag1", "tag2"],
    "notes": "",
    "payment_status": "",
    "crm_stage": "",
    "intent": ""
  }}
}}
"""
    return system_prompt, user_prompt


def _post_json(url: str, payload: dict[str, Any], *, headers: dict[str, str] | None = None, timeout: int = 45) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw or "{}")
            return parsed if isinstance(parsed, dict) else {"data": parsed}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ai_provider_http_{exc.code}:{raw[:500]}") from exc
    except Exception as exc:
        raise RuntimeError(f"ai_provider_unavailable:{str(exc)[:300]}") from exc


def _call_google(token: str, model: str, system_prompt: str, user_prompt: str, settings: dict[str, Any]) -> str:
    query = urllib.parse.urlencode({"key": token})
    safe_model = urllib.parse.quote(model or PROVIDER_DEFAULT_MODELS["google"], safe="")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{safe_model}:generateContent?{query}"
    data = _post_json(
        url,
        {
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "generationConfig": {
                "temperature": float(settings.get("temperature") or 0.5),
                "maxOutputTokens": int(settings.get("max_tokens") or 1800),
                "responseMimeType": "application/json",
            },
        },
    )
    candidates = data.get("candidates") if isinstance(data.get("candidates"), list) else []
    if not candidates:
        return ""
    parts = (((candidates[0] or {}).get("content") or {}).get("parts") or [])
    return "\n".join(str(part.get("text") or "") for part in parts if isinstance(part, dict)).strip()


def _call_chat_completions(provider: str, token: str, model: str, system_prompt: str, user_prompt: str, settings: dict[str, Any]) -> str:
    endpoints = {
        "groq": "https://api.groq.com/openai/v1/chat/completions",
        "mistral": "https://api.mistral.ai/v1/chat/completions",
        "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    }
    headers = {"Authorization": f"Bearer {token}"}
    if provider == "openrouter":
        headers.update({"HTTP-Referer": "https://app.scentra-ai.online", "X-Title": "Scentra +AI"})
    data = _post_json(
        endpoints[provider],
        {
            "model": model or PROVIDER_DEFAULT_MODELS.get(provider, ""),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": float(settings.get("temperature") or 0.5),
            "max_tokens": int(settings.get("max_tokens") or 1800),
            "response_format": {"type": "json_object"},
        },
        headers=headers,
    )
    choices = data.get("choices") if isinstance(data.get("choices"), list) else []
    if not choices:
        return ""
    message = (choices[0] or {}).get("message") or {}
    return str(message.get("content") or "").strip()


def _extract_json(raw: str) -> dict[str, Any]:
    text_value = _clean(raw, 50000)
    if not text_value:
        return {}
    try:
        parsed = json.loads(text_value)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        start = text_value.find("{")
        end = text_value.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(text_value[start : end + 1])
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {"reply": text_value}
    return {"reply": text_value}


def generate_agent_result(conn: Connection, tenant_id: str, conversation: dict[str, Any], messages: list[dict[str, Any]]) -> dict[str, Any]:
    settings = get_settings(conn, tenant_id)
    if not bool(settings.get("enabled")):
        return {"ok": False, "skipped": "ai_disabled"}

    providers = [_clean(settings.get("provider_code"), 80).lower()]
    fallback = _clean(settings.get("fallback_provider_code"), 80).lower()
    if fallback and fallback not in providers:
        providers.append(fallback)
    memory = get_memory(conn, tenant_id, str(conversation["id"]))
    knowledge_context = _knowledge_context(conn, tenant_id, messages)
    system_prompt, user_prompt = _prompt(settings, conversation, memory, messages, knowledge_context)
    requested_tokens = estimate_tokens(system_prompt, user_prompt)
    ensure_ai_token_quota(conn, tenant_id, requested=requested_tokens)

    gateway = generate_with_gateway(
        conn,
        tenant_id=tenant_id,
        task_type="conversation_reply",
        agent_type="sales_agent",
        route_code="conversation.sales",
        conversation_id=str(conversation["id"]),
        provider_chain=providers,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        settings=settings,
    )
    if not gateway.get("ok"):
        return {"ok": False, "skipped": gateway.get("skipped") or "ai_unavailable"}
    raw = _clean(gateway.get("raw"), 50000)
    parsed = _extract_json(raw)
    parsed["provider_code"] = gateway.get("provider_code") or ""
    parsed["model"] = gateway.get("model") or ""
    parsed["estimated_tokens"] = int(gateway.get("estimated_tokens") or estimate_tokens(system_prompt, user_prompt, raw))
    parsed["ai_gateway_run_id"] = gateway.get("run_id") or ""
    parsed["fallback_used"] = bool(gateway.get("fallback_used"))
    return {"ok": True, "result": parsed, "raw": raw}


def _split_tags(value: Any) -> list[str]:
    raw = value
    if isinstance(raw, str):
        raw = raw.replace("\n", ",").split(",")
    if not isinstance(raw, list):
        return []
    seen: set[str] = set()
    tags: list[str] = []
    for item in raw:
        tag = _clean(item, 60)
        key = tag.lower()
        if tag and key not in seen:
            seen.add(key)
            tags.append(tag)
    return tags


def _merge_crm_patch(conversation: dict[str, Any], crm: dict[str, Any]) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    for field in CRM_FIELDS:
        if field == "tags":
            existing = _split_tags(conversation.get("tags"))
            incoming = _split_tags(crm.get("tags"))
            merged = existing[:]
            keys = {item.lower() for item in merged}
            for tag in incoming:
                if tag.lower() not in keys:
                    merged.append(tag)
                    keys.add(tag.lower())
            if merged and ", ".join(merged) != _clean(conversation.get("tags")):
                patch["tags"] = ", ".join(merged[:40])
            continue
        value = _clean(crm.get(field), 4000)
        if not value:
            continue
        if field == "notes":
            existing = _clean(conversation.get("notes"), 5000)
            if value and value.lower() not in existing.lower():
                patch["notes"] = (f"{existing}\nIA: {value}" if existing else f"IA: {value}")[:5000]
            continue
        if not _clean(conversation.get(field)) or field in {"interests", "customer_type", "payment_status", "crm_stage", "intent"}:
            patch[field] = value[:4000]
    if patch.get("first_name") and not patch.get("display_name") and not _clean(conversation.get("display_name")):
        patch["display_name"] = " ".join([patch.get("first_name", ""), patch.get("last_name", "")]).strip()
    return patch


def _update_crm(conn: Connection, tenant_id: str, conversation: dict[str, Any], crm: dict[str, Any], facts: dict[str, Any]) -> dict[str, Any]:
    patch = _merge_crm_patch(conversation, crm)
    profile = conversation.get("profile_json") if isinstance(conversation.get("profile_json"), dict) else {}
    profile = {**profile, "ai_facts": facts, "ai_last_update": datetime.now(timezone.utc).isoformat()}
    patch["profile_json"] = profile
    assignments = []
    params: dict[str, Any] = {"tenant_id": tenant_id, "conversation_id": conversation["id"]}
    for key, value in patch.items():
        if key == "profile_json":
            assignments.append("profile_json = CAST(:profile_json AS jsonb)")
            params["profile_json"] = _json(value)
        else:
            assignments.append(f"{key} = :{key}")
            params[key] = value
    assignments.append("last_profiled_at = NOW()")
    assignments.append("updated_at = NOW()")
    conn.execute(
        text(
            f"""
            UPDATE saas_conversations
            SET {", ".join(assignments)}
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:conversation_id AS uuid)
            """
        ),
        params,
    )
    return patch


def _upsert_memory(conn: Connection, tenant_id: str, conversation_id: str, message_id: str, summary: str, facts: dict[str, Any]) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            INSERT INTO saas_conversation_memory (
                tenant_id, conversation_id, summary, facts_json, last_message_id, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), CAST(:conversation_id AS uuid), :summary,
                CAST(:facts_json AS jsonb), CAST(:message_id AS uuid), NOW()
            )
            ON CONFLICT (tenant_id, conversation_id)
            DO UPDATE SET
                summary = COALESCE(NULLIF(EXCLUDED.summary, ''), saas_conversation_memory.summary),
                facts_json = saas_conversation_memory.facts_json || EXCLUDED.facts_json,
                last_message_id = EXCLUDED.last_message_id,
                updated_at = NOW()
            RETURNING tenant_id::text, conversation_id::text, summary, facts_json,
                      COALESCE(last_message_id::text, '') AS last_message_id, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "summary": _clean(summary, 5000),
            "facts_json": _json(facts),
        },
    ).mappings().first()
    return dict(row) if row else get_memory(conn, tenant_id, conversation_id)


def _metadata_int(metadata: dict[str, Any], key: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(metadata.get(key, default))
    except Exception:
        value = default
    return max(minimum, min(maximum, value))


def _split_reply_chunks(body: str, max_chars: int) -> list[str]:
    clean = _clean(body, 8000)
    if not clean:
        return []
    if max_chars <= 0 or len(clean) <= max_chars:
        return [clean]
    paragraphs = [part.strip() for part in re.split(r"\n{2,}", clean) if part.strip()]
    units: list[str] = []
    for paragraph in paragraphs or [clean]:
        if len(paragraph) <= max_chars:
            units.append(paragraph)
            continue
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", paragraph) if part.strip()]
        units.extend(sentences or [paragraph])

    chunks: list[str] = []
    current = ""
    for unit in units:
        if len(unit) > max_chars:
            if current:
                chunks.append(current.strip())
                current = ""
            for idx in range(0, len(unit), max_chars):
                chunks.append(unit[idx : idx + max_chars].strip())
            continue
        candidate = f"{current}\n\n{unit}".strip() if current else unit
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current.strip())
            current = unit
    if current:
        chunks.append(current.strip())
    return [chunk for chunk in chunks if chunk][:8]


def _latest_inbound_message(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    for message in reversed(messages):
        if str(message.get("direction") or "").lower() == "in":
            return message
    return None


def _maybe_send_typing_indicator(
    conn: Connection,
    tenant_id: str,
    conversation: dict[str, Any],
    latest_inbound: dict[str, Any] | None,
    settings: dict[str, Any],
) -> dict[str, Any]:
    metadata = settings.get("metadata_json") if isinstance(settings.get("metadata_json"), dict) else {}
    if metadata.get("typing_indicator_enabled", True) is False:
        return {"ok": False, "skipped": "typing_indicator_disabled"}
    message_id = _clean((latest_inbound or {}).get("external_message_id"), 240)
    if not message_id or message_id.startswith("local:"):
        return {"ok": False, "skipped": "provider_message_id_missing"}
    integration = _load_connected_integration(conn, tenant_id, _clean(conversation.get("channel"), 40) or "whatsapp")
    if not integration:
        return {"ok": False, "skipped": "integration_not_connected"}
    config = _integration_config(integration)
    if str(config.get("dispatch_mode") or "stub").strip().lower() not in {"meta_cloud", "whatsapp_cloud"}:
        return {"ok": False, "skipped": "dispatch_mode_not_meta_cloud"}
    phone_number_id = _clean(config.get("phone_number_id"), 80)
    access_token = _secret_from_env(config, integration)
    if not phone_number_id or not access_token:
        return {"ok": False, "skipped": "meta_credentials_missing"}
    base_url = str(config.get("graph_base_url") or "https://graph.facebook.com").rstrip("/")
    version = _meta_graph_version(config)
    timeout_sec = int(config.get("timeout_sec") or 15)
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
        "typing_indicator": {"type": "text"},
    }
    try:
        response = _post_json(f"{base_url}/{version}/{phone_number_id}/messages", payload, access_token, timeout_sec)
        return {"ok": True, "response": response}
    except (DispatchPermanentError, DispatchTransientError) as exc:
        return {"ok": False, "error": str(exc)[:300]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}


def _queue_ai_reply(conn: Connection, tenant_id: str, conversation: dict[str, Any], body_text: str, ai_result: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    body = _clean(body_text, 4000)
    if not body:
        return {"ok": False, "skipped": "empty_ai_reply"}
    metadata = settings.get("metadata_json") if isinstance(settings.get("metadata_json"), dict) else {}
    chunk_chars = _metadata_int(metadata, "reply_chunk_chars", 480, 0, 2000)
    initial_delay_ms = _metadata_int(metadata, "reply_initial_delay_ms", 4000, 0, 240000)
    chunk_delay_ms = _metadata_int(metadata, "reply_chunk_delay_ms", 4000, 0, 240000)
    chunks = _split_reply_chunks(body, chunk_chars)
    if not chunks:
        return {"ok": False, "skipped": "empty_ai_reply"}
    ensure_monthly_message_quota(conn, tenant_id, requested=len(chunks))
    channel = _clean(conversation.get("channel"), 40) or "whatsapp"
    conversation_id = str(conversation["id"])
    queued: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks):
        local_external_id = f"local:ai:{uuid4().hex}"
        delay_seconds = int(round((initial_delay_ms + (index * chunk_delay_ms)) / 1000))
        payload = {
            "source": "ai_agent",
            "dispatch_status": "queued",
            "ai_provider": ai_result.get("provider_code") or "",
            "ai_model": ai_result.get("model") or "",
            "reply_chunk_index": index + 1,
            "reply_chunk_total": len(chunks),
            "reply_delay_seconds": delay_seconds,
        }
        message = conn.execute(
            text(
                """
                INSERT INTO saas_messages (
                    tenant_id, conversation_id, channel, external_message_id, direction, msg_type, text, payload_json
                )
                VALUES (
                    CAST(:tenant_id AS uuid), CAST(:conversation_id AS uuid), :channel, :external_message_id,
                    'out', 'text', :body_text, CAST(:payload_json AS jsonb)
                )
                RETURNING id::text
                """
            ),
            {
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "channel": channel,
                "external_message_id": local_external_id,
                "body_text": chunk,
                "payload_json": _json(payload),
            },
        ).mappings().first()
        outbound = conn.execute(
            text(
                """
                INSERT INTO saas_outbound_messages (
                    tenant_id, conversation_id, message_id, channel, recipient_external_id,
                    body_text, payload_json, next_attempt_at
                )
                VALUES (
                    CAST(:tenant_id AS uuid), CAST(:conversation_id AS uuid), CAST(:message_id AS uuid),
                    :channel, :recipient_external_id, :body_text, CAST(:payload_json AS jsonb),
                    NOW() + (:delay_seconds * INTERVAL '1 second')
                )
                RETURNING id::text, status, next_attempt_at::text
                """
            ),
            {
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "message_id": message["id"],
                "channel": channel,
                "recipient_external_id": _clean(conversation.get("external_contact_id") or conversation.get("phone"), 180),
                "body_text": chunk,
                "payload_json": _json({"local_external_message_id": local_external_id, **payload}),
                "delay_seconds": delay_seconds,
            },
        ).mappings().first()
        queued.append({"message_id": message["id"], "outbound_id": outbound["id"], "status": outbound["status"], "next_attempt_at": outbound["next_attempt_at"]})
    conn.execute(
        text(
            """
            UPDATE saas_conversations
            SET last_message_text = :body_text,
                last_message_at = NOW(),
                updated_at = NOW()
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:conversation_id AS uuid)
            """
        ),
        {"tenant_id": tenant_id, "conversation_id": conversation_id, "body_text": chunks[-1]},
    )
    conn.execute(
        text(
            """
            INSERT INTO saas_usage_counters (tenant_id, metric_code, period_yyyymm, metric_value)
            VALUES (CAST(:tenant_id AS uuid), 'outbound_messages_queued', :period, :count)
            ON CONFLICT (tenant_id, metric_code, period_yyyymm)
            DO UPDATE SET metric_value = saas_usage_counters.metric_value + EXCLUDED.metric_value, updated_at = NOW()
            """
        ),
        {"tenant_id": tenant_id, "period": _period_yyyymm(), "count": len(chunks)},
    )
    return {"ok": True, "queued_messages": len(queued), "chunks": queued}


def _record_ai_usage(conn: Connection, tenant_id: str, tokens: int) -> None:
    conn.execute(
        text(
            """
            INSERT INTO saas_usage_counters (tenant_id, metric_code, period_yyyymm, metric_value)
            VALUES (CAST(:tenant_id AS uuid), 'ai_tokens', :period, :tokens)
            ON CONFLICT (tenant_id, metric_code, period_yyyymm)
            DO UPDATE SET metric_value = saas_usage_counters.metric_value + EXCLUDED.metric_value, updated_at = NOW()
            """
        ),
        {"tenant_id": tenant_id, "period": _period_yyyymm(), "tokens": int(max(1, tokens))},
    )


def process_conversation_ai(conn: Connection, tenant_id: str, conversation_id: str, message_id: str = "") -> dict[str, Any]:
    ensure_ai_tables(conn)
    settings = get_settings(conn, tenant_id)
    conversation = _conversation(conn, tenant_id, conversation_id)
    if not conversation:
        return {"ok": False, "skipped": "conversation_not_found"}
    if bool(conversation.get("takeover")):
        return {"ok": False, "skipped": "takeover_human_on"}
    messages = _recent_messages(conn, tenant_id, conversation_id)
    if not messages:
        return {"ok": False, "skipped": "no_messages"}
    latest = messages[-1]
    if str(latest.get("direction") or "").lower() != "in":
        return {"ok": False, "skipped": "latest_not_inbound"}
    if message_id and str(latest.get("id")) != str(message_id):
        inbound_ids = {str(item.get("id")) for item in messages if str(item.get("direction")).lower() == "in"}
        if str(message_id) not in inbound_ids:
            return {"ok": False, "skipped": "message_not_inbound"}
    typing = _maybe_send_typing_indicator(conn, tenant_id, conversation, _latest_inbound_message(messages), settings)

    try:
        generated = generate_agent_result(conn, tenant_id, conversation, messages)
    except HTTPException as exc:
        return {"ok": False, "skipped": "quota_or_feature_blocked", "detail": exc.detail}
    except Exception as exc:
        return {"ok": False, "skipped": "ai_generation_error", "detail": str(exc)[:500]}

    if not generated.get("ok"):
        return generated
    result = generated.get("result") or {}
    crm = result.get("crm") if isinstance(result.get("crm"), dict) else {}
    facts = result.get("facts") if isinstance(result.get("facts"), dict) else {}
    try:
        crm_patch = _update_crm(conn, tenant_id, conversation, crm, facts)
        memory = _upsert_memory(
            conn,
            tenant_id,
            conversation_id,
            str(latest["id"]),
            _clean(result.get("memory_summary") or "", 5000),
            facts,
        )
        tokens = int(result.get("estimated_tokens") or estimate_tokens(generated.get("raw") or ""))
        _record_ai_usage(conn, tenant_id, tokens)
        outbound = _queue_ai_reply(conn, tenant_id, conversation, _clean(result.get("reply"), 4000), result, settings)
    except HTTPException as exc:
        return {"ok": False, "skipped": "ai_postprocess_blocked", "detail": exc.detail}
    except Exception as exc:
        return {"ok": False, "skipped": "ai_postprocess_error", "detail": str(exc)[:500]}
    return {"ok": True, "crm_patch": crm_patch, "memory": memory, "outbound": outbound, "typing": typing, "ai": {"provider": result.get("provider_code"), "model": result.get("model"), "tokens": tokens}}


def schedule_conversation_ai(
    conn: Connection,
    tenant_id: str,
    conversation_id: str,
    message_id: str,
    delay_seconds: int | None = None,
) -> dict[str, Any]:
    ensure_ai_tables(conn)
    settings = get_settings(conn, tenant_id)
    metadata = settings.get("metadata_json") if isinstance(settings.get("metadata_json"), dict) else {}
    if delay_seconds is None:
        delay_seconds = _metadata_int(metadata, "inbound_cooldown_seconds", 6, 0, 3600)
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_pending_replies (
                tenant_id, conversation_id, last_message_id, status, scheduled_at, attempts, last_error, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), CAST(:conversation_id AS uuid), CAST(:message_id AS uuid),
                'pending', NOW() + (:delay_seconds * INTERVAL '1 second'), 0, '', NOW()
            )
            ON CONFLICT (tenant_id, conversation_id)
            DO UPDATE SET
                last_message_id = EXCLUDED.last_message_id,
                status = 'pending',
                scheduled_at = EXCLUDED.scheduled_at,
                last_error = '',
                updated_at = NOW()
            RETURNING id::text, scheduled_at::text, status
            """
        ),
        {
            "tenant_id": tenant_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "delay_seconds": max(0, int(delay_seconds or 0)),
        },
    ).mappings().first()
    return {"ok": True, "pending": dict(row or {}), "delay_seconds": max(0, int(delay_seconds or 0))}


def _due_ai_jobs(conn: Connection, tenant_id: str | None, limit: int) -> list[dict[str, Any]]:
    filters = ["status = 'pending'", "scheduled_at <= NOW()"]
    params: dict[str, Any] = {"limit": max(1, min(int(limit or 25), 200))}
    if tenant_id:
        filters.append("tenant_id = CAST(:tenant_id AS uuid)")
        params["tenant_id"] = tenant_id
    rows = conn.execute(
        text(
            f"""
            WITH due AS (
                SELECT id
                FROM saas_ai_pending_replies
                WHERE {" AND ".join(filters)}
                ORDER BY scheduled_at ASC, updated_at ASC
                LIMIT :limit
                FOR UPDATE SKIP LOCKED
            )
            UPDATE saas_ai_pending_replies p
            SET status = 'processing',
                attempts = attempts + 1,
                updated_at = NOW()
            FROM due
            WHERE p.id = due.id
            RETURNING p.id::text, p.tenant_id::text, p.conversation_id::text,
                      COALESCE(p.last_message_id::text, '') AS last_message_id,
                      p.attempts
            """
        ),
        params,
    ).mappings().all()
    return [dict(row) for row in rows]


def process_due_ai_replies(limit: int = 25, tenant_id: str | None = None) -> dict[str, Any]:
    stats: dict[str, Any] = {"picked": 0, "queued": 0, "skipped": 0, "failed": 0, "errors": []}
    with db_session() as conn:
        ensure_ai_tables(conn)
        if tenant_id:
            set_tenant_context(conn, tenant_id)
        jobs = _due_ai_jobs(conn, tenant_id, limit)
        stats["picked"] = len(jobs)
        for job in jobs:
            set_tenant_context(conn, str(job["tenant_id"]))
            result = process_conversation_ai(
                conn,
                str(job["tenant_id"]),
                str(job["conversation_id"]),
                str(job.get("last_message_id") or ""),
            )
            if result.get("ok"):
                queued = int((result.get("outbound") or {}).get("queued_messages") or 0)
                stats["queued"] += queued
                conn.execute(
                    text(
                        """
                        UPDATE saas_ai_pending_replies
                        SET status = 'completed',
                            last_error = '',
                            updated_at = NOW()
                        WHERE id = CAST(:id AS uuid)
                        """
                    ),
                    {"id": job["id"]},
                )
                continue
            skipped = str(result.get("skipped") or "ai_skipped")
            retryable = skipped in {"ai_generation_error", "quota_or_feature_blocked", "ai_postprocess_error", "ai_postprocess_blocked"}
            if retryable and int(job.get("attempts") or 0) < 3:
                conn.execute(
                    text(
                        """
                        UPDATE saas_ai_pending_replies
                        SET status = 'pending',
                            scheduled_at = NOW() + INTERVAL '5 minutes',
                            last_error = :error,
                            updated_at = NOW()
                        WHERE id = CAST(:id AS uuid)
                        """
                    ),
                    {"id": job["id"], "error": json.dumps(result, ensure_ascii=False)[:900]},
                )
                stats["failed"] += 1
            else:
                conn.execute(
                    text(
                        """
                        UPDATE saas_ai_pending_replies
                        SET status = 'skipped',
                            last_error = :error,
                            updated_at = NOW()
                        WHERE id = CAST(:id AS uuid)
                        """
                    ),
                    {"id": job["id"], "error": json.dumps(result, ensure_ascii=False)[:900]},
                )
                stats["skipped"] += 1
            stats["errors"].append({"id": job["id"], "conversation_id": job["conversation_id"], "result": result})
    return stats


def test_agent(conn: Connection, tenant_id: str, phone: str, message: str) -> dict[str, Any]:
    pseudo_conversation = {
        "id": "00000000-0000-0000-0000-000000000000",
        "channel": "whatsapp",
        "external_contact_id": _clean(phone, 120) or "test",
        "phone": _clean(phone, 120),
        "display_name": "",
        "first_name": "",
        "last_name": "",
        "city": "",
        "customer_type": "",
        "interests": "",
        "takeover": False,
        "last_message_text": _clean(message, 4000),
        "unread_count": 1,
        "tags": "",
        "notes": "",
        "payment_status": "",
        "payment_reference": "",
        "crm_stage": "contactado",
        "intent": "",
        "profile_json": {},
    }
    pseudo_messages = [
        {
            "id": "test-message",
            "direction": "in",
            "msg_type": "text",
            "text": _clean(message, 4000),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    ]
    settings = get_settings(conn, tenant_id)
    if not bool(settings.get("enabled")):
        raise HTTPException(status_code=409, detail="ai_disabled")
    # The test path uses the regular provider call but does not write CRM, memory or outbound.
    memory = {
        "tenant_id": tenant_id,
        "conversation_id": pseudo_conversation["id"],
        "summary": "",
        "facts_json": {},
        "last_message_id": "",
        "updated_at": "",
    }
    knowledge_context = _knowledge_context(conn, tenant_id, pseudo_messages)
    system_prompt, user_prompt = _prompt(settings, pseudo_conversation, memory, pseudo_messages, knowledge_context)
    ensure_ai_token_quota(conn, tenant_id, requested=estimate_tokens(system_prompt, user_prompt))
    providers = [_clean(settings.get("provider_code"), 80).lower(), _clean(settings.get("fallback_provider_code"), 80).lower()]
    provider_chain = [item for idx, item in enumerate(providers) if item and item not in providers[:idx]]
    gateway = generate_with_gateway(
        conn,
        tenant_id=tenant_id,
        task_type="conversation_test",
        agent_type="sales_agent",
        route_code="conversation.sales",
        conversation_id="",
        provider_chain=provider_chain,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        settings=settings,
    )
    if not gateway.get("ok"):
        raise HTTPException(status_code=409, detail=gateway.get("skipped") or "ai_unavailable")
    raw = _clean(gateway.get("raw"), 50000)
    parsed = _extract_json(raw)
    parsed["provider_code"] = gateway.get("provider_code") or ""
    parsed["model"] = gateway.get("model") or ""
    parsed["ai_gateway_run_id"] = gateway.get("run_id") or ""
    parsed["fallback_used"] = bool(gateway.get("fallback_used"))
    _record_ai_usage(conn, tenant_id, estimate_tokens(system_prompt, user_prompt, raw))
    return {"ok": True, "result": parsed}
