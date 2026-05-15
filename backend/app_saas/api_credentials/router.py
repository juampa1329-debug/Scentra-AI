from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from app_saas.db import db_session, set_tenant_context
from app_saas.shared.security import AuthContext, get_current_user, require_role
from app_saas.shared.secrets import decrypt_secret, encrypt_secret

router = APIRouter(prefix="/api-credentials", tags=["saas-api-credentials"])


class ApiCredentialUpsertIn(BaseModel):
    category: str = Field(default="ai", max_length=40)
    provider_code: str = Field(min_length=2, max_length=80)
    credential_key: str = Field(min_length=3, max_length=120)
    display_name: str = Field(default="", max_length=160)
    value: str = Field(default="", max_length=12000)
    selected_model: str = Field(default="", max_length=240)
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class ApiCredentialOut(BaseModel):
    id: str
    category: str
    provider_code: str
    credential_key: str
    display_name: str
    has_secret: bool
    secret_hint: str = ""
    selected_model: str = ""
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    updated_at: str


def _clean(value: Any, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _secret_hint(value: str) -> str:
    clean = _clean(value, 12000)
    if not clean:
        return ""
    if len(clean) <= 10:
        return f"{clean[:2]}...{clean[-2:]}"
    return f"{clean[:4]}...{clean[-4:]}"


def _safe_row(row: dict[str, Any]) -> ApiCredentialOut:
    metadata = row.get("metadata_json") if isinstance(row.get("metadata_json"), dict) else {}
    return ApiCredentialOut(
        id=str(row["id"]),
        category=str(row["category"] or ""),
        provider_code=str(row["provider_code"] or ""),
        credential_key=str(row["credential_key"] or ""),
        display_name=str(row["display_name"] or ""),
        has_secret=bool(str(row.get("secret_value") or "").strip()),
        secret_hint=str(row.get("secret_hint") or ""),
        selected_model=str(metadata.get("selected_model") or ""),
        metadata_json=metadata,
        updated_at=str(row.get("updated_at") or ""),
    )


def _load_credential(conn, tenant_id: str, provider_code: str, credential_key: str) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            """
            SELECT id::text, category, provider_code, credential_key, display_name,
                   secret_value, secret_hint, metadata_json, updated_at::text
            FROM saas_api_credentials
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND provider_code = :provider_code
              AND credential_key = :credential_key
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "provider_code": provider_code, "credential_key": credential_key},
    ).mappings().first()
    return dict(row) if row else None


def _request_json(url: str, *, token: str = "", headers: dict[str, str] | None = None, timeout: int = 20) -> dict[str, Any]:
    request_headers = dict(headers or {})
    if token:
        request_headers.setdefault("Authorization", f"Bearer {token}")
    request = urllib.request.Request(url, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw or "{}")
            return parsed if isinstance(parsed, dict) else {"data": parsed}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=502, detail={"code": "provider_models_error", "message": raw[:500]})
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"code": "provider_models_unavailable", "message": str(exc)[:300]})


def _static_models(provider_code: str) -> list[dict[str, str]]:
    defaults = {
        "google": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-flash", "gemini-1.5-pro"],
        "groq": ["llama-3.1-8b-instant", "llama-3.1-70b-versatile", "llama-3.3-70b-versatile"],
        "mistral": ["mistral-small-latest", "mistral-medium-latest", "mistral-large-latest"],
        "openrouter": ["google/gemini-2.5-flash", "openai/gpt-4o-mini", "meta-llama/llama-3.1-8b-instruct"],
        "elevenlabs": ["eleven_v3", "eleven_multilingual_v2", "eleven_turbo_v2_5"],
        "google_tts": ["es-CO-Standard-A", "es-CO-Standard-B", "es-US-Standard-A"],
    }
    return [{"id": item, "label": item} for item in defaults.get(provider_code, [])]


def _models_from_provider(provider_code: str, token: str) -> list[dict[str, str]]:
    if provider_code == "google":
        query = urllib.parse.urlencode({"key": token})
        data = _request_json(f"https://generativelanguage.googleapis.com/v1beta/models?{query}")
        models = data.get("models") if isinstance(data.get("models"), list) else []
        return [
            {
                "id": str(item.get("name") or "").replace("models/", ""),
                "label": str(item.get("displayName") or item.get("name") or "").replace("models/", ""),
            }
            for item in models
            if isinstance(item, dict) and item.get("name")
        ]
    if provider_code == "groq":
        data = _request_json("https://api.groq.com/openai/v1/models", token=token)
        models = data.get("data") if isinstance(data.get("data"), list) else []
        return [{"id": str(item.get("id") or ""), "label": str(item.get("id") or "")} for item in models if isinstance(item, dict) and item.get("id")]
    if provider_code == "mistral":
        data = _request_json("https://api.mistral.ai/v1/models", token=token)
        models = data.get("data") if isinstance(data.get("data"), list) else []
        return [{"id": str(item.get("id") or ""), "label": str(item.get("id") or "")} for item in models if isinstance(item, dict) and item.get("id")]
    if provider_code == "openrouter":
        data = _request_json("https://openrouter.ai/api/v1/models", token=token)
        models = data.get("data") if isinstance(data.get("data"), list) else []
        return [{"id": str(item.get("id") or ""), "label": str(item.get("name") or item.get("id") or "")} for item in models if isinstance(item, dict) and item.get("id")]
    if provider_code == "elevenlabs":
        voices = _request_json("https://api.elevenlabs.io/v1/voices", headers={"xi-api-key": token})
        rows = voices.get("voices") if isinstance(voices.get("voices"), list) else []
        return [{"id": str(item.get("voice_id") or ""), "label": str(item.get("name") or item.get("voice_id") or "")} for item in rows if isinstance(item, dict) and item.get("voice_id")]
    if provider_code == "google_tts":
        query = urllib.parse.urlencode({"key": token})
        data = _request_json(f"https://texttospeech.googleapis.com/v1/voices?{query}")
        voices = data.get("voices") if isinstance(data.get("voices"), list) else []
        out: list[dict[str, str]] = []
        for item in voices:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "")
            languages = item.get("languageCodes") if isinstance(item.get("languageCodes"), list) else []
            if name and any(str(lang).lower().startswith("es") for lang in languages):
                out.append({"id": name, "label": f"{name} / {', '.join(map(str, languages[:2]))}"})
        return out
    return _static_models(provider_code)


@router.get("", response_model=list[ApiCredentialOut])
def list_api_credentials(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        rows = conn.execute(
            text(
                """
                SELECT id::text, category, provider_code, credential_key, display_name,
                       secret_value, secret_hint, metadata_json, updated_at::text
                FROM saas_api_credentials
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                ORDER BY category ASC, provider_code ASC, credential_key ASC
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().all()
    return [_safe_row(dict(row)) for row in rows]


@router.post("", response_model=ApiCredentialOut)
def upsert_api_credential(payload: ApiCredentialUpsertIn, ctx: AuthContext = Depends(require_role("owner", "admin"))):
    provider_code = _clean(payload.provider_code, 80).lower()
    credential_key = _clean(payload.credential_key, 120).upper()
    category = _clean(payload.category, 40).lower() or "ai"
    display_name = _clean(payload.display_name, 160)
    incoming_value = _clean(payload.value, 12000)
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        existing = _load_credential(conn, ctx.tenant_id, provider_code, credential_key)
        if not existing and not incoming_value and not payload.selected_model.strip():
            raise HTTPException(status_code=400, detail="credential_value_required")

        metadata = dict(existing.get("metadata_json") or {}) if existing else {}
        metadata.update(payload.metadata_json or {})
        if payload.selected_model.strip():
            metadata["selected_model"] = payload.selected_model.strip()

        secret_value = str(existing.get("secret_value") or "") if existing else ""
        secret_hint = str(existing.get("secret_hint") or "") if existing else ""
        if incoming_value:
            secret_value = encrypt_secret(incoming_value)
            secret_hint = _secret_hint(incoming_value)

        row = conn.execute(
            text(
                """
                INSERT INTO saas_api_credentials (
                    tenant_id, category, provider_code, credential_key, display_name,
                    secret_value, secret_hint, metadata_json, updated_at
                )
                VALUES (
                    CAST(:tenant_id AS uuid), :category, :provider_code, :credential_key, :display_name,
                    :secret_value, :secret_hint, CAST(:metadata_json AS jsonb), NOW()
                )
                ON CONFLICT (tenant_id, credential_key)
                DO UPDATE SET
                    category = EXCLUDED.category,
                    provider_code = EXCLUDED.provider_code,
                    display_name = COALESCE(NULLIF(EXCLUDED.display_name, ''), saas_api_credentials.display_name),
                    secret_value = EXCLUDED.secret_value,
                    secret_hint = EXCLUDED.secret_hint,
                    metadata_json = EXCLUDED.metadata_json,
                    updated_at = NOW()
                RETURNING id::text, category, provider_code, credential_key, display_name,
                          secret_value, secret_hint, metadata_json, updated_at::text
                """
            ),
            {
                "tenant_id": ctx.tenant_id,
                "category": category,
                "provider_code": provider_code,
                "credential_key": credential_key,
                "display_name": display_name,
                "secret_value": secret_value,
                "secret_hint": secret_hint,
                "metadata_json": json.dumps(metadata),
            },
        ).mappings().first()
    return _safe_row(dict(row))


@router.get("/{provider_code}/models")
def list_provider_models(
    provider_code: str,
    credential_key: str = Query("", max_length=120),
    ctx: AuthContext = Depends(get_current_user),
):
    provider = _clean(provider_code, 80).lower()
    key = _clean(credential_key, 120).upper()
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        credential = _load_credential(conn, ctx.tenant_id, provider, key) if key else None
    token = decrypt_secret(str((credential or {}).get("secret_value") or ""))
    if not token and provider not in {"openrouter", "piper"}:
        return {"ok": False, "source": "static", "detail": "credential_required", "models": _static_models(provider)}

    models = _models_from_provider(provider, token)
    return {"ok": True, "source": "provider" if token else "static", "models": models or _static_models(provider)}
