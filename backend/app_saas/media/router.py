from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import text

from app_saas.ai_agent.service import get_settings
from app_saas.ai_gateway.providers.http import estimate_tokens
from app_saas.ai_gateway.service import ensure_ai_gateway_tables, generate_with_gateway
from app_saas.billing.limits import ensure_ai_token_quota
from app_saas.db import db_session, set_tenant_context
from app_saas.intelligence.capture import record_inline_event
from app_saas.intelligence.multimodal_observability import apply_multimodal_safe_rollout
from app_saas.intelligence.premium import assert_provider_enabled
from app_saas.intelligence.service import record_intelligence_usage, resolve_intelligence_access
from app_saas.shared.secrets import decrypt_secret
from app_saas.shared.security import AuthContext, decode_token, get_current_user, require_role

router = APIRouter(prefix="/media", tags=["saas-media"])

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_VOICE_ANALYSIS_BYTES = 20 * 1024 * 1024
MAX_VOICE_DEMO_BYTES = 6 * 1024 * 1024
MAX_VISION_ANALYSIS_BYTES = 16 * 1024 * 1024
MAX_VISION_DEMO_BYTES = 5 * 1024 * 1024
ALLOWED_KINDS = {"image", "video", "audio", "document", "file"}
DEFAULT_META_GRAPH_VERSION = "v24.0"
VOICE_INTELLIGENCE_FEATURE = "voice_intelligence"
VOICE_ACCESS_FEATURES = ("voice_intelligence", "voice_transcription", "voice_sentiment_intent", "ai_premium")
VISION_INTELLIGENCE_FEATURE = "vision_intelligence"
VISION_ACCESS_FEATURES = ("vision_intelligence", "image_understanding", "document_ocr", "ai_premium")
VISION_IMAGE_PROVIDERS = {"google", "openrouter", "kimi"}
VISION_DOCUMENT_MIME_TYPES = {"application/pdf", "text/plain", "text/csv", "application/csv", "application/json"}
WEB_SEARCH_FEATURE = "web_search_intelligence"
IMAGE_SEARCH_FEATURE = "image_search_intelligence"
EXTERNAL_SOURCE_FEATURE = "external_source_assist"
WEB_SEARCH_ACCESS_FEATURES = (WEB_SEARCH_FEATURE, EXTERNAL_SOURCE_FEATURE, "ai_premium")
IMAGE_SEARCH_ACCESS_FEATURES = (IMAGE_SEARCH_FEATURE, EXTERNAL_SOURCE_FEATURE, "ai_premium")
MIXED_SEARCH_ACCESS_FEATURES = (EXTERNAL_SOURCE_FEATURE, "ai_premium")
SEARCH_PROVIDER_KEYS = {
    "tavily": "TAVILY_API_KEY",
    "brave_search": "BRAVE_SEARCH_API_KEY",
    "serpapi": "SERPAPI_API_KEY",
}
SEARCH_TYPES = {"web", "image", "mixed"}
SEARCH_APPROVAL_STATUSES = {"pending", "approved", "rejected"}
MAX_SEARCH_LIMIT = 12
MAX_SEARCH_DEMO_LIMIT = 4


class WebImageSearchIn(BaseModel):
    query: str = Field(min_length=2, max_length=280)
    search_type: str = Field(default="mixed", max_length=20)
    provider_code: str = Field(default="", max_length=80)
    conversation_id: str = Field(default="", max_length=80)
    message_id: str = Field(default="", max_length=80)
    limit: int = Field(default=6, ge=1, le=MAX_SEARCH_LIMIT)


class WebImageSearchApprovalIn(BaseModel):
    approval_status: str = Field(default="approved", max_length=20)
    reason: str = Field(default="", max_length=500)


class WebImageSearchReferenceIn(BaseModel):
    conversation_id: str = Field(default="", max_length=80)
    note: str = Field(default="", max_length=700)
    include_source_url: bool = True
    include_image_url: bool = True


def _clean(value: object, limit: int = 240) -> str:
    return str(value or "").strip()[:limit]


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _safe_kind(value: object) -> str:
    kind = re.sub(r"[^a-z0-9_-]+", "", _clean(value, 40).lower())
    return kind if kind in ALLOWED_KINDS else "file"


def _period_yyyymm() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m")


def _safe_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _base_mime(value: object) -> str:
    return _clean(value, 160).split(";", 1)[0].strip().lower()


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


def _meta_error_payload(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw or "{}")
    except Exception:
        payload = {"error": {"message": raw[:700]}}
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return {"message": raw[:700], "type": "", "code": 0, "subcode": 0, "fbtrace_id": ""}
    return {
        "message": _clean(error.get("message"), 700),
        "type": _clean(error.get("type"), 120),
        "code": int(error.get("code") or 0) if str(error.get("code") or "").isdigit() else 0,
        "subcode": int(error.get("error_subcode") or 0) if str(error.get("error_subcode") or "").isdigit() else 0,
        "fbtrace_id": _clean(error.get("fbtrace_id"), 120),
    }


def _raise_meta_media_error(raw: str, fallback_code: str) -> None:
    meta = _meta_error_payload(raw)
    message = str(meta.get("message") or "").lower()
    code = int(meta.get("code") or 0)
    status_code = 502
    error_code = fallback_code
    hint = "Meta rechazo la descarga del medio. Revisa token, permisos y WABA/Phone Number ID."
    if code == 190 or "invalid oauth" in message or "access token" in message or "expired" in message:
        status_code = 401
        error_code = "meta_media_token_expired_or_invalid"
        hint = "El token permanente de Meta es invalido, expiro, fue revocado o se pego incompleto."
    elif code in {10, 200} or "permission" in message or "not have access" in message:
        status_code = 403
        error_code = "meta_media_insufficient_permissions"
        hint = "El token no tiene permisos para este WABA o numero. Revisa whatsapp_business_messaging y acceso al activo."
    elif code in {100, 803} or "does not exist" in message or "cannot be loaded" in message:
        status_code = 404
        error_code = "meta_media_not_found_or_not_accessible"
        hint = "El media ID no existe, expiro, pertenece a otro WABA o el token no puede verlo."
    raise HTTPException(status_code=status_code, detail={"code": error_code, "meta": meta, "hint": hint})


def _graph_get_json(url: str, token: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:1200]
        _raise_meta_media_error(body, "meta_media_error")
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"code": "meta_media_unavailable", "message": str(exc)[:300]})


def _graph_get_bytes(url: str, token: str) -> tuple[bytes, str]:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read(), str(response.headers.get("content-type") or "application/octet-stream")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:1200]
        _raise_meta_media_error(body, "meta_media_download_error")
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"code": "meta_media_download_unavailable", "message": str(exc)[:300]})


def _ensure_voice_intelligence_tables(conn) -> None:
    ensure_ai_gateway_tables(conn)
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_voice_intelligence_analyses (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                conversation_id UUID NOT NULL REFERENCES saas_conversations(id) ON DELETE CASCADE,
                message_id UUID NOT NULL REFERENCES saas_messages(id) ON DELETE CASCADE,
                created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                media_id TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'inbox_audio',
                provider_code TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                ai_gateway_run_id UUID NULL REFERENCES saas_ai_runs(id) ON DELETE SET NULL,
                status TEXT NOT NULL DEFAULT 'completed',
                transcript TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                sentiment TEXT NOT NULL DEFAULT 'neutral',
                sentiment_score NUMERIC(6,4) NOT NULL DEFAULT 0,
                intent TEXT NOT NULL DEFAULT 'other',
                intent_label TEXT NOT NULL DEFAULT '',
                urgency TEXT NOT NULL DEFAULT 'low',
                language TEXT NOT NULL DEFAULT '',
                confidence NUMERIC(6,4) NOT NULL DEFAULT 0,
                analysis_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, message_id)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_voice_intel_tenant_created ON saas_voice_intelligence_analyses (tenant_id, created_at DESC)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_voice_intel_conversation ON saas_voice_intelligence_analyses (tenant_id, conversation_id, updated_at DESC)"))


def _ensure_vision_intelligence_tables(conn) -> None:
    ensure_ai_gateway_tables(conn)
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_vision_intelligence_analyses (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                conversation_id UUID NOT NULL REFERENCES saas_conversations(id) ON DELETE CASCADE,
                message_id UUID NOT NULL REFERENCES saas_messages(id) ON DELETE CASCADE,
                created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                media_id TEXT NOT NULL DEFAULT '',
                media_kind TEXT NOT NULL DEFAULT 'image',
                source TEXT NOT NULL DEFAULT 'inbox_media',
                provider_code TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                ai_gateway_run_id UUID NULL REFERENCES saas_ai_runs(id) ON DELETE SET NULL,
                status TEXT NOT NULL DEFAULT 'completed',
                visual_description TEXT NOT NULL DEFAULT '',
                extracted_text TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                document_type TEXT NOT NULL DEFAULT 'unknown',
                sentiment TEXT NOT NULL DEFAULT 'neutral',
                sentiment_score NUMERIC(6,4) NOT NULL DEFAULT 0,
                intent TEXT NOT NULL DEFAULT 'other',
                intent_label TEXT NOT NULL DEFAULT '',
                urgency TEXT NOT NULL DEFAULT 'low',
                language TEXT NOT NULL DEFAULT '',
                confidence NUMERIC(6,4) NOT NULL DEFAULT 0,
                entities_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                topics_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                product_hints_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                moderation_flags_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                analysis_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, message_id)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_vision_intel_tenant_created ON saas_vision_intelligence_analyses (tenant_id, created_at DESC)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_vision_intel_conversation ON saas_vision_intelligence_analyses (tenant_id, conversation_id, updated_at DESC)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_vision_intel_doc_type ON saas_vision_intelligence_analyses (tenant_id, document_type, urgency, updated_at DESC)"))


def _ensure_web_image_search_tables(conn) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_web_search_intelligence_runs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                conversation_id UUID NULL REFERENCES saas_conversations(id) ON DELETE SET NULL,
                message_id UUID NULL REFERENCES saas_messages(id) ON DELETE SET NULL,
                created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                query TEXT NOT NULL DEFAULT '',
                search_type TEXT NOT NULL DEFAULT 'mixed',
                provider_code TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'completed',
                access_mode TEXT NOT NULL DEFAULT 'demo',
                result_count INTEGER NOT NULL DEFAULT 0,
                approved_count INTEGER NOT NULL DEFAULT 0,
                blocked_count INTEGER NOT NULL DEFAULT 0,
                summary TEXT NOT NULL DEFAULT '',
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
            CREATE TABLE IF NOT EXISTS saas_web_search_intelligence_results (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                run_id UUID NOT NULL REFERENCES saas_web_search_intelligence_runs(id) ON DELETE CASCADE,
                result_type TEXT NOT NULL DEFAULT 'web',
                title TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                display_url TEXT NOT NULL DEFAULT '',
                snippet TEXT NOT NULL DEFAULT '',
                source_name TEXT NOT NULL DEFAULT '',
                image_url TEXT NOT NULL DEFAULT '',
                thumbnail_url TEXT NOT NULL DEFAULT '',
                license_label TEXT NOT NULL DEFAULT '',
                license_details_url TEXT NOT NULL DEFAULT '',
                width INTEGER NOT NULL DEFAULT 0,
                height INTEGER NOT NULL DEFAULT 0,
                rank INTEGER NOT NULL DEFAULT 0,
                safety_status TEXT NOT NULL DEFAULT 'pending_review',
                approval_status TEXT NOT NULL DEFAULT 'pending',
                approved_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                approved_at TIMESTAMP NULL,
                rejected_reason TEXT NOT NULL DEFAULT '',
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_web_search_runs_tenant_created ON saas_web_search_intelligence_runs (tenant_id, created_at DESC)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_web_search_runs_conversation ON saas_web_search_intelligence_runs (tenant_id, conversation_id, created_at DESC)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_web_search_results_run_rank ON saas_web_search_intelligence_results (run_id, rank ASC)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_web_search_results_tenant_approval ON saas_web_search_intelligence_results (tenant_id, approval_status, updated_at DESC)"))


def _extract_json_object(raw: str) -> dict[str, Any]:
    text_value = str(raw or "").strip()
    if not text_value:
        return {}
    try:
        parsed = json.loads(text_value)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text_value, flags=re.S)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _bounded_float(value: Any, default: float = 0.0, minimum: float = -1.0, maximum: float = 1.0) -> float:
    try:
        out = float(value)
    except Exception:
        out = default
    return max(minimum, min(maximum, out))


def _choice(value: Any, allowed: set[str], default: str) -> str:
    clean = re.sub(r"[^a-z0-9_-]+", "_", _clean(value, 80).lower()).strip("_")
    return clean if clean in allowed else default


def _normalize_voice_analysis(parsed: dict[str, Any], raw: str) -> dict[str, Any]:
    transcript = _clean(parsed.get("transcript") or parsed.get("transcription") or parsed.get("text") or "", 12000)
    summary = _clean(parsed.get("summary") or parsed.get("resumen") or "", 3000)
    if not transcript and raw:
        transcript = _clean(raw, 12000)
    if not summary and transcript:
        summary = _clean(transcript, 700)
    action_items = parsed.get("action_items")
    if not isinstance(action_items, list):
        action_items = []
    safety_flags = parsed.get("safety_flags")
    if not isinstance(safety_flags, list):
        safety_flags = []
    crm_hints = parsed.get("crm_hints") if isinstance(parsed.get("crm_hints"), dict) else {}
    sentiment_score = _bounded_float(parsed.get("sentiment_score"), 0.0, -1.0, 1.0)
    confidence = _bounded_float(parsed.get("confidence"), 0.0, 0.0, 1.0)
    analysis = {
        "transcript": transcript,
        "summary": summary,
        "sentiment": _choice(parsed.get("sentiment"), {"positive", "neutral", "negative", "mixed"}, "neutral"),
        "sentiment_score": sentiment_score,
        "intent": _choice(parsed.get("intent"), {"pricing", "purchase", "support", "complaint", "appointment", "lead_qualification", "follow_up", "other"}, "other"),
        "intent_label": _clean(parsed.get("intent_label") or parsed.get("intencion") or "", 120),
        "urgency": _choice(parsed.get("urgency"), {"low", "medium", "high"}, "low"),
        "language": _clean(parsed.get("language") or parsed.get("idioma") or "", 60),
        "confidence": confidence,
        "recommended_action": _clean(parsed.get("recommended_action") or parsed.get("accion_recomendada") or "", 700),
        "action_items": [_clean(item, 240) for item in action_items if _clean(item, 240)][:8],
        "crm_hints": {str(key): _clean(value, 400) for key, value in crm_hints.items() if _clean(value, 400)},
        "safety_flags": [_clean(item, 100) for item in safety_flags if _clean(item, 100)][:8],
    }
    if not analysis["intent_label"]:
        analysis["intent_label"] = analysis["intent"].replace("_", " ").title()
    return analysis


def _voice_compact(analysis: dict[str, Any], row: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "analysis_id": str((row or {}).get("id") or analysis.get("analysis_id") or ""),
        "status": str((row or {}).get("status") or analysis.get("status") or "completed"),
        "transcript": _clean(analysis.get("transcript"), 12000),
        "summary": _clean(analysis.get("summary"), 3000),
        "sentiment": _clean(analysis.get("sentiment") or "neutral", 40),
        "sentiment_score": _bounded_float(analysis.get("sentiment_score"), 0.0, -1.0, 1.0),
        "intent": _clean(analysis.get("intent") or "other", 80),
        "intent_label": _clean(analysis.get("intent_label") or "", 120),
        "urgency": _clean(analysis.get("urgency") or "low", 40),
        "language": _clean(analysis.get("language") or "", 60),
        "confidence": _bounded_float(analysis.get("confidence"), 0.0, 0.0, 1.0),
        "recommended_action": _clean(analysis.get("recommended_action") or "", 700),
        "action_items": analysis.get("action_items") if isinstance(analysis.get("action_items"), list) else [],
        "created_at": str((row or {}).get("created_at") or ""),
        "updated_at": str((row or {}).get("updated_at") or ""),
    }


def _analysis_row(row: Any) -> dict[str, Any]:
    data = dict(row or {})
    analysis = _safe_payload(data.get("analysis_json"))
    data["sentiment_score"] = _bounded_float(data.get("sentiment_score"), 0.0, -1.0, 1.0)
    data["confidence"] = _bounded_float(data.get("confidence"), 0.0, 0.0, 1.0)
    data["analysis_json"] = analysis
    data["metadata_json"] = _safe_payload(data.get("metadata_json"))
    data["voice_intelligence"] = _voice_compact({**analysis, **data}, data)
    return data


def _clean_list(value: Any, limit: int = 160, max_items: int = 12) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_clean(item, limit) for item in value if _clean(item, limit)][:max_items]


def _normalize_vision_analysis(parsed: dict[str, Any], raw: str) -> dict[str, Any]:
    visual_description = _clean(parsed.get("visual_description") or parsed.get("description") or parsed.get("descripcion") or "", 5000)
    extracted_text = _clean(parsed.get("extracted_text") or parsed.get("ocr_text") or parsed.get("text") or "", 16000)
    summary = _clean(parsed.get("summary") or parsed.get("resumen") or "", 3000)
    if not visual_description and raw:
        visual_description = _clean(raw, 5000)
    if not summary:
        summary = _clean(extracted_text or visual_description, 900)
    product_hints = parsed.get("product_hints") if isinstance(parsed.get("product_hints"), dict) else {}
    product_hints = {str(key): _clean(value, 500) for key, value in product_hints.items() if _clean(value, 500)}
    sentiment_score = _bounded_float(parsed.get("sentiment_score"), 0.0, -1.0, 1.0)
    confidence = _bounded_float(parsed.get("confidence"), 0.0, 0.0, 1.0)
    analysis = {
        "visual_description": visual_description,
        "extracted_text": extracted_text,
        "summary": summary,
        "document_type": _choice(
            parsed.get("document_type"),
            {"photo", "screenshot", "receipt", "invoice", "catalog", "product_image", "identity_document", "contract", "form", "report", "message_screenshot", "unknown"},
            "unknown",
        ),
        "sentiment": _choice(parsed.get("sentiment"), {"positive", "neutral", "negative", "mixed"}, "neutral"),
        "sentiment_score": sentiment_score,
        "intent": _choice(
            parsed.get("intent"),
            {"pricing", "purchase", "support", "complaint", "appointment", "lead_qualification", "document_review", "product_interest", "follow_up", "other"},
            "other",
        ),
        "intent_label": _clean(parsed.get("intent_label") or parsed.get("intencion") or "", 120),
        "urgency": _choice(parsed.get("urgency"), {"low", "medium", "high"}, "low"),
        "language": _clean(parsed.get("language") or parsed.get("idioma") or "", 60),
        "confidence": confidence,
        "entities": _clean_list(parsed.get("entities"), 160, 16),
        "topics": _clean_list(parsed.get("topics"), 120, 12),
        "product_hints": product_hints,
        "moderation_flags": _clean_list(parsed.get("moderation_flags") or parsed.get("safety_flags"), 120, 12),
        "recommended_action": _clean(parsed.get("recommended_action") or parsed.get("accion_recomendada") or "", 700),
        "action_items": _clean_list(parsed.get("action_items"), 240, 8),
    }
    if not analysis["intent_label"]:
        analysis["intent_label"] = analysis["intent"].replace("_", " ").title()
    return analysis


def _vision_compact(analysis: dict[str, Any], row: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "analysis_id": str((row or {}).get("id") or analysis.get("analysis_id") or ""),
        "status": str((row or {}).get("status") or analysis.get("status") or "completed"),
        "media_kind": _clean((row or {}).get("media_kind") or analysis.get("media_kind") or "image", 40),
        "visual_description": _clean(analysis.get("visual_description"), 5000),
        "extracted_text": _clean(analysis.get("extracted_text"), 16000),
        "summary": _clean(analysis.get("summary"), 3000),
        "document_type": _clean(analysis.get("document_type") or "unknown", 80),
        "sentiment": _clean(analysis.get("sentiment") or "neutral", 40),
        "sentiment_score": _bounded_float(analysis.get("sentiment_score"), 0.0, -1.0, 1.0),
        "intent": _clean(analysis.get("intent") or "other", 80),
        "intent_label": _clean(analysis.get("intent_label") or "", 120),
        "urgency": _clean(analysis.get("urgency") or "low", 40),
        "language": _clean(analysis.get("language") or "", 60),
        "confidence": _bounded_float(analysis.get("confidence"), 0.0, 0.0, 1.0),
        "entities": analysis.get("entities") if isinstance(analysis.get("entities"), list) else [],
        "topics": analysis.get("topics") if isinstance(analysis.get("topics"), list) else [],
        "product_hints": analysis.get("product_hints") if isinstance(analysis.get("product_hints"), dict) else {},
        "moderation_flags": analysis.get("moderation_flags") if isinstance(analysis.get("moderation_flags"), list) else [],
        "recommended_action": _clean(analysis.get("recommended_action") or "", 700),
        "action_items": analysis.get("action_items") if isinstance(analysis.get("action_items"), list) else [],
        "created_at": str((row or {}).get("created_at") or ""),
        "updated_at": str((row or {}).get("updated_at") or ""),
    }


def _vision_analysis_row(row: Any) -> dict[str, Any]:
    data = dict(row or {})
    analysis = _safe_payload(data.get("analysis_json"))
    data["sentiment_score"] = _bounded_float(data.get("sentiment_score"), 0.0, -1.0, 1.0)
    data["confidence"] = _bounded_float(data.get("confidence"), 0.0, 0.0, 1.0)
    data["entities_json"] = data.get("entities_json") if isinstance(data.get("entities_json"), list) else []
    data["topics_json"] = data.get("topics_json") if isinstance(data.get("topics_json"), list) else []
    data["product_hints_json"] = _safe_payload(data.get("product_hints_json"))
    data["moderation_flags_json"] = data.get("moderation_flags_json") if isinstance(data.get("moderation_flags_json"), list) else []
    analysis = {
        **analysis,
        "entities": analysis.get("entities") if isinstance(analysis.get("entities"), list) else data["entities_json"],
        "topics": analysis.get("topics") if isinstance(analysis.get("topics"), list) else data["topics_json"],
        "product_hints": analysis.get("product_hints") if isinstance(analysis.get("product_hints"), dict) else data["product_hints_json"],
        "moderation_flags": analysis.get("moderation_flags") if isinstance(analysis.get("moderation_flags"), list) else data["moderation_flags_json"],
    }
    data["analysis_json"] = analysis
    data["metadata_json"] = _safe_payload(data.get("metadata_json"))
    data["vision_intelligence"] = _vision_compact({**analysis, **data}, data)
    return data


def _load_voice_analysis(conn, tenant_id: str, message_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            """
            SELECT id::text, tenant_id::text, conversation_id::text, message_id::text,
                   COALESCE(created_by_user_id::text, '') AS created_by_user_id,
                   media_id, source, provider_code, model,
                   COALESCE(ai_gateway_run_id::text, '') AS ai_gateway_run_id,
                   status, transcript, summary, sentiment, sentiment_score,
                   intent, intent_label, urgency, language, confidence,
                   analysis_json, metadata_json, created_at::text, updated_at::text
            FROM saas_voice_intelligence_analyses
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND message_id = CAST(:message_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "message_id": message_id},
    ).mappings().first()
    return _analysis_row(row) if row else None


def _load_vision_analysis(conn, tenant_id: str, message_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            """
            SELECT id::text, tenant_id::text, conversation_id::text, message_id::text,
                   COALESCE(created_by_user_id::text, '') AS created_by_user_id,
                   media_id, media_kind, source, provider_code, model,
                   COALESCE(ai_gateway_run_id::text, '') AS ai_gateway_run_id,
                   status, visual_description, extracted_text, summary, document_type,
                   sentiment, sentiment_score, intent, intent_label, urgency, language,
                   confidence, entities_json, topics_json, product_hints_json,
                   moderation_flags_json, analysis_json, metadata_json,
                   created_at::text, updated_at::text
            FROM saas_vision_intelligence_analyses
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND message_id = CAST(:message_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "message_id": message_id},
    ).mappings().first()
    return _vision_analysis_row(row) if row else None


def _load_audio_message(conn, tenant_id: str, message_id: str) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            SELECT m.id::text, m.conversation_id::text, m.channel, m.external_message_id,
                   m.direction, m.msg_type, m.text, m.media_id, m.mime_type,
                   m.payload_json, m.created_at::text,
                   c.external_contact_id, c.phone, c.display_name
            FROM saas_messages m
            JOIN saas_conversations c ON c.id = m.conversation_id AND c.tenant_id = m.tenant_id
            WHERE m.tenant_id = CAST(:tenant_id AS uuid)
              AND m.id = CAST(:message_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "message_id": message_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="message_not_found")
    message = dict(row)
    msg_type = _clean(message.get("msg_type"), 40).lower()
    mime_type = _clean(message.get("mime_type"), 160).lower()
    if msg_type != "audio" and not mime_type.startswith("audio/"):
        raise HTTPException(status_code=400, detail="voice_message_required")
    if not _clean(message.get("media_id"), 240):
        raise HTTPException(status_code=400, detail="voice_media_required")
    message["payload_json"] = _safe_payload(message.get("payload_json"))
    return message


def _load_audio_bytes(conn, tenant_id: str, message: dict[str, Any]) -> tuple[bytes, str, dict[str, Any]]:
    media_id = _clean(message.get("media_id"), 240)
    asset = conn.execute(
        text(
            """
            SELECT id::text, kind, filename, content_type, byte_size, data
            FROM saas_media_assets
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id::text = :media_id
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "media_id": media_id},
    ).mappings().first()
    if asset:
        content_type = _clean(asset.get("content_type") or message.get("mime_type") or "audio/webm", 160) or "audio/webm"
        return bytes(asset["data"]), content_type, {
            "source": "saas_media_assets",
            "filename": _clean(asset.get("filename"), 240),
            "byte_size": int(asset.get("byte_size") or 0),
        }

    channel = _clean(message.get("channel"), 40).lower()
    if channel != "whatsapp":
        raise HTTPException(status_code=400, detail={"code": "voice_media_source_unsupported", "channel": channel or "unknown"})
    integration = _load_meta_integration(conn, tenant_id)
    metadata = _graph_get_json(
        f"https://graph.facebook.com/{integration['version']}/{media_id}",
        integration["token"],
    )
    media_url = _clean(metadata.get("url"), 4000)
    if not media_url:
        raise HTTPException(status_code=502, detail="meta_media_url_missing")
    content, content_type = _graph_get_bytes(media_url, integration["token"])
    media_type = _clean(metadata.get("mime_type") or message.get("mime_type") or content_type, 160) or content_type
    return content, media_type, {
        "source": "meta_whatsapp",
        "meta_media_id": media_id,
        "byte_size": len(content),
        "meta_mime_type": _clean(metadata.get("mime_type"), 160),
    }


def _visual_kind_for(mime_type: str, msg_type: str = "") -> str:
    mime = _base_mime(mime_type)
    msg = _clean(msg_type, 40).lower()
    if mime.startswith("image/") or msg == "image":
        return "image"
    return "document"


def _visual_mime_supported(mime_type: str, media_kind: str) -> bool:
    mime = _base_mime(mime_type)
    if media_kind == "image":
        return mime.startswith("image/")
    return mime in VISION_DOCUMENT_MIME_TYPES


def _load_visual_message(conn, tenant_id: str, message_id: str) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            SELECT m.id::text, m.conversation_id::text, m.channel, m.external_message_id,
                   m.direction, m.msg_type, m.text, m.media_id, m.mime_type,
                   m.payload_json, m.created_at::text,
                   c.external_contact_id, c.phone, c.display_name
            FROM saas_messages m
            JOIN saas_conversations c ON c.id = m.conversation_id AND c.tenant_id = m.tenant_id
            WHERE m.tenant_id = CAST(:tenant_id AS uuid)
              AND m.id = CAST(:message_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "message_id": message_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="message_not_found")
    message = dict(row)
    msg_type = _clean(message.get("msg_type"), 40).lower()
    mime_type = _clean(message.get("mime_type"), 160).lower()
    if msg_type not in {"image", "document", "file"} and not mime_type.startswith("image/") and mime_type not in VISION_DOCUMENT_MIME_TYPES:
        raise HTTPException(status_code=400, detail="vision_message_required")
    if not _clean(message.get("media_id"), 240):
        raise HTTPException(status_code=400, detail="vision_media_required")
    message["payload_json"] = _safe_payload(message.get("payload_json"))
    message["media_kind"] = _visual_kind_for(mime_type, msg_type)
    return message


def _load_visual_bytes(conn, tenant_id: str, message: dict[str, Any]) -> tuple[bytes, str, dict[str, Any]]:
    media_id = _clean(message.get("media_id"), 240)
    asset = conn.execute(
        text(
            """
            SELECT id::text, kind, filename, content_type, byte_size, data
            FROM saas_media_assets
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id::text = :media_id
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "media_id": media_id},
    ).mappings().first()
    if asset:
        content_type = _clean(asset.get("content_type") or message.get("mime_type") or "application/octet-stream", 160) or "application/octet-stream"
        return bytes(asset["data"]), content_type, {
            "source": "saas_media_assets",
            "filename": _clean(asset.get("filename"), 240),
            "byte_size": int(asset.get("byte_size") or 0),
        }

    channel = _clean(message.get("channel"), 40).lower()
    if channel != "whatsapp":
        raise HTTPException(status_code=400, detail={"code": "vision_media_source_unsupported", "channel": channel or "unknown"})
    integration = _load_meta_integration(conn, tenant_id)
    metadata = _graph_get_json(
        f"https://graph.facebook.com/{integration['version']}/{media_id}",
        integration["token"],
    )
    media_url = _clean(metadata.get("url"), 4000)
    if not media_url:
        raise HTTPException(status_code=502, detail="meta_media_url_missing")
    content, content_type = _graph_get_bytes(media_url, integration["token"])
    media_type = _clean(metadata.get("mime_type") or message.get("mime_type") or content_type, 160) or content_type
    return content, media_type, {
        "source": "meta_whatsapp",
        "meta_media_id": media_id,
        "byte_size": len(content),
        "meta_mime_type": _clean(metadata.get("mime_type"), 160),
    }


def _voice_provider_chain(settings: dict[str, Any], requested_provider: str = "") -> list[str]:
    metadata = settings.get("metadata_json") if isinstance(settings.get("metadata_json"), dict) else {}
    preferred = _clean(requested_provider or metadata.get("voice_analysis_provider") or "google", 80).lower()
    providers = [preferred, "google"]
    seen: set[str] = set()
    out: list[str] = []
    for provider in providers:
        if provider != "google":
            continue
        if provider not in seen:
            seen.add(provider)
            out.append(provider)
    return out or ["google"]


def _vision_provider_chain(settings: dict[str, Any], requested_provider: str = "", media_kind: str = "image") -> list[str]:
    metadata = settings.get("metadata_json") if isinstance(settings.get("metadata_json"), dict) else {}
    preferred = _clean(requested_provider or metadata.get("vision_analysis_provider") or "google", 80).lower()
    providers = [preferred, "google"]
    seen: set[str] = set()
    out: list[str] = []
    for provider in providers:
        if media_kind != "image" and provider != "google":
            continue
        if media_kind == "image" and provider not in VISION_IMAGE_PROVIDERS:
            continue
        if provider not in seen:
            seen.add(provider)
            out.append(provider)
    return out or ["google"]


def _voice_prompts(message: dict[str, Any], access_mode: str) -> tuple[str, str]:
    system_prompt = (
        "Eres Voice Intelligence de Scentra. Analizas audios de conversaciones comerciales omnicanal. "
        "Transcribe con fidelidad, resume sin inventar y clasifica sentimiento, urgencia e intencion. "
        "Si una parte no es audible, escribe [inaudible]. Devuelve solo JSON valido, sin markdown."
    )
    user_prompt = (
        "Analiza el audio adjunto de este mensaje del Inbox.\n"
        f"Modo de licencia: {access_mode}.\n"
        f"Canal: {message.get('channel') or 'whatsapp'}.\n"
        f"Direccion: {message.get('direction') or ''}.\n"
        f"Cliente: {message.get('display_name') or message.get('phone') or message.get('external_contact_id') or 'cliente'}.\n\n"
        "Devuelve este JSON exacto:\n"
        "{\n"
        '  "transcript": "texto completo en el idioma del audio",\n'
        '  "summary": "resumen ejecutivo breve en espanol",\n'
        '  "sentiment": "positive|neutral|negative|mixed",\n'
        '  "sentiment_score": 0.0,\n'
        '  "intent": "pricing|purchase|support|complaint|appointment|lead_qualification|follow_up|other",\n'
        '  "intent_label": "etiqueta humana breve",\n'
        '  "urgency": "low|medium|high",\n'
        '  "language": "idioma detectado",\n'
        '  "confidence": 0.0,\n'
        '  "recommended_action": "siguiente accion sugerida",\n'
        '  "action_items": ["tarea 1"],\n'
        '  "crm_hints": {"intent": "", "priority": "", "notes": ""},\n'
        '  "safety_flags": []\n'
        "}"
    )
    return system_prompt, user_prompt


def _vision_prompts(message: dict[str, Any], access_mode: str, content_type: str, media_kind: str) -> tuple[str, str]:
    system_prompt = (
        "Eres Vision Intelligence de Scentra. Analizas imagenes y documentos recibidos en conversaciones comerciales. "
        "Describe con precision, extrae texto visible si existe, resume sin inventar y clasifica tipo, sentimiento, urgencia e intencion. "
        "Si una parte no es legible, escribe [ilegible]. Devuelve solo JSON valido, sin markdown."
    )
    user_prompt = (
        "Analiza el adjunto visual/documental de este mensaje del Inbox.\n"
        f"Modo de licencia: {access_mode}.\n"
        f"Tipo de media: {media_kind}.\n"
        f"MIME: {content_type}.\n"
        f"Canal: {message.get('channel') or 'whatsapp'}.\n"
        f"Direccion: {message.get('direction') or ''}.\n"
        f"Cliente: {message.get('display_name') or message.get('phone') or message.get('external_contact_id') or 'cliente'}.\n\n"
        "Devuelve este JSON exacto:\n"
        "{\n"
        '  "visual_description": "descripcion fiel de la imagen/documento",\n'
        '  "extracted_text": "OCR/texto visible completo, o vacio si no hay texto",\n'
        '  "summary": "resumen ejecutivo breve en espanol",\n'
        '  "document_type": "photo|screenshot|receipt|invoice|catalog|product_image|identity_document|contract|form|report|message_screenshot|unknown",\n'
        '  "sentiment": "positive|neutral|negative|mixed",\n'
        '  "sentiment_score": 0.0,\n'
        '  "intent": "pricing|purchase|support|complaint|appointment|lead_qualification|document_review|product_interest|follow_up|other",\n'
        '  "intent_label": "etiqueta humana breve",\n'
        '  "urgency": "low|medium|high",\n'
        '  "language": "idioma detectado",\n'
        '  "confidence": 0.0,\n'
        '  "entities": ["persona/empresa/producto/lugar/numero relevante"],\n'
        '  "topics": ["tema"],\n'
        '  "product_hints": {"product_names": "", "prices": "", "contact_data": "", "order_numbers": ""},\n'
        '  "moderation_flags": [],\n'
        '  "recommended_action": "siguiente accion sugerida",\n'
        '  "action_items": ["tarea 1"]\n'
        "} "
    )
    return system_prompt, user_prompt


def _record_ai_usage(conn, tenant_id: str, tokens: int) -> None:
    conn.execute(
        text(
            """
            INSERT INTO saas_usage_counters (tenant_id, metric_code, period_yyyymm, metric_value)
            VALUES (CAST(:tenant_id AS uuid), 'ai_tokens', :period, :tokens)
            ON CONFLICT (tenant_id, metric_code, period_yyyymm)
            DO UPDATE SET metric_value = saas_usage_counters.metric_value + EXCLUDED.metric_value, updated_at = NOW()
            """
        ),
        {"tenant_id": tenant_id, "period": _period_yyyymm(), "tokens": max(1, int(tokens or 1))},
    )


def _resolve_search_access(conn, tenant_id: str, search_type: str) -> dict[str, Any]:
    clean_type = _clean(search_type, 20).lower()
    features = {
        "web": WEB_SEARCH_ACCESS_FEATURES,
        "image": IMAGE_SEARCH_ACCESS_FEATURES,
        "mixed": MIXED_SEARCH_ACCESS_FEATURES,
    }.get(clean_type, MIXED_SEARCH_ACCESS_FEATURES)
    last_detail: Any = None
    for feature_key in features:
        try:
            access = dict(resolve_intelligence_access(conn, tenant_id, feature_key, allow_demo=True))
            access["resolved_feature_key"] = feature_key
            return access
        except HTTPException as exc:
            last_detail = exc.detail
    raise HTTPException(status_code=403, detail={"code": "web_image_search_not_enabled", "features": list(features), "last_error": last_detail})


def _resolve_any_search_access(conn, tenant_id: str) -> dict[str, Any]:
    last_detail: Any = None
    for feature_key in (EXTERNAL_SOURCE_FEATURE, WEB_SEARCH_FEATURE, IMAGE_SEARCH_FEATURE, "ai_premium"):
        try:
            access = dict(resolve_intelligence_access(conn, tenant_id, feature_key, allow_demo=True))
            access["resolved_feature_key"] = feature_key
            return access
        except HTTPException as exc:
            last_detail = exc.detail
    raise HTTPException(status_code=403, detail={"code": "web_image_search_not_enabled", "features": [EXTERNAL_SOURCE_FEATURE, WEB_SEARCH_FEATURE, IMAGE_SEARCH_FEATURE, "ai_premium"], "last_error": last_detail})


def _search_provider_order(settings: dict[str, Any], requested_provider: str = "") -> list[str]:
    metadata = settings.get("metadata_json") if isinstance(settings.get("metadata_json"), dict) else {}
    preferred = _clean(requested_provider or metadata.get("web_image_search_provider") or "tavily", 80).lower()
    values = [preferred, "tavily", "brave_search", "serpapi"]
    out: list[str] = []
    for value in values:
        if value in SEARCH_PROVIDER_KEYS and value not in out:
            out.append(value)
    return out


def _load_search_credential(conn, tenant_id: str, provider_code: str) -> dict[str, Any] | None:
    credential_key = SEARCH_PROVIDER_KEYS.get(provider_code)
    if not credential_key:
        return None
    row = conn.execute(
        text(
            """
            SELECT id::text, provider_code, credential_key, secret_value, secret_hint, metadata_json
            FROM saas_api_credentials
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND provider_code = :provider_code
              AND credential_key = :credential_key
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "provider_code": provider_code, "credential_key": credential_key},
    ).mappings().first()
    if not row:
        return None
    data = dict(row)
    token = decrypt_secret(str(data.get("secret_value") or ""))
    if not token:
        return None
    data["token"] = token
    data["metadata_json"] = _safe_payload(data.get("metadata_json"))
    return data


def _public_url_status(value: Any) -> tuple[str, str, str]:
    raw = _clean(value, 2000)
    if not raw:
        return "", "blocked", "empty_url"
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return "", "blocked", "invalid_public_url"
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return "", "blocked", "missing_host"
    blocked_hosts = {"localhost", "0.0.0.0", "127.0.0.1", "::1"}
    if host in blocked_hosts or host.endswith(".local") or host.endswith(".internal") or host.endswith(".localhost"):
        return "", "blocked", "non_public_host"
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return "", "blocked", "non_public_ip"
    except ValueError:
        pass
    cleaned = urllib.parse.urlunparse(parsed._replace(fragment=""))
    return cleaned, "pending_review", ""


def _display_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc or parsed.path
    path = parsed.path if parsed.netloc else ""
    value = f"{host}{path}"[:120].strip("/")
    return value or url[:120]


def _as_int(value: Any) -> int:
    try:
        return max(0, int(float(str(value or "0"))))
    except Exception:
        return 0


def _search_result(
    *,
    result_type: str,
    title: Any,
    url: Any,
    snippet: Any = "",
    source_name: Any = "",
    image_url: Any = "",
    thumbnail_url: Any = "",
    license_label: Any = "",
    license_details_url: Any = "",
    width: Any = 0,
    height: Any = 0,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    clean_url, safety_status, safety_reason = _public_url_status(url)
    clean_image_url, image_safety, image_reason = _public_url_status(image_url)
    clean_thumbnail_url, thumb_safety, thumb_reason = _public_url_status(thumbnail_url)
    clean_license_url, license_safety, license_reason = _public_url_status(license_details_url)
    clean_type = "image" if _clean(result_type, 20).lower() == "image" else "web"
    if clean_type == "image" and not clean_url and clean_image_url:
        clean_url = clean_image_url
        safety_status = image_safety
        safety_reason = image_reason
    blocked_reasons = [item for item in [safety_reason, image_reason if image_url and image_safety == "blocked" else "", thumb_reason if thumbnail_url and thumb_safety == "blocked" else "", license_reason if license_details_url and license_safety == "blocked" else ""] if item]
    if not clean_url:
        safety_status = "blocked"
        blocked_reasons.append(safety_reason or "missing_public_target")
    approval_status = "rejected" if safety_status == "blocked" else "pending"
    return {
        "result_type": clean_type,
        "title": _clean(title, 400),
        "url": clean_url,
        "display_url": _display_url(clean_url) if clean_url else _clean(url, 240),
        "snippet": _clean(snippet, 1400),
        "source_name": _clean(source_name, 240),
        "image_url": clean_image_url if image_safety != "blocked" else "",
        "thumbnail_url": clean_thumbnail_url if thumb_safety != "blocked" else "",
        "license_label": _clean(license_label, 160),
        "license_details_url": clean_license_url if license_safety != "blocked" else "",
        "width": _as_int(width),
        "height": _as_int(height),
        "safety_status": safety_status,
        "approval_status": approval_status,
        "rejected_reason": ", ".join(sorted(set(blocked_reasons)))[:500] if approval_status == "rejected" else "",
        "metadata_json": {**(metadata or {}), "safety_reasons": blocked_reasons},
    }


def _search_http_json(
    url: str,
    *,
    provider_code: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 18,
) -> dict[str, Any]:
    data = None
    request_headers = {"Accept": "application/json", **(headers or {})}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw or "{}")
            return parsed if isinstance(parsed, dict) else {"data": parsed}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=502, detail={"code": "search_provider_error", "provider": provider_code, "status": exc.code, "message": raw[:700]})
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"code": "search_provider_unavailable", "provider": provider_code, "message": str(exc)[:300]})


def _tavily_results(token: str, query: str, search_type: str, limit: int) -> list[dict[str, Any]]:
    payload = {
        "query": query,
        "search_depth": "basic",
        "max_results": limit,
        "include_answer": False,
        "include_raw_content": False,
        "include_images": search_type in {"image", "mixed"},
        "include_image_descriptions": search_type in {"image", "mixed"},
    }
    data = _search_http_json(
        "https://api.tavily.com/search",
        provider_code="tavily",
        method="POST",
        payload=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    results: list[dict[str, Any]] = []
    if search_type in {"web", "mixed"}:
        for item in data.get("results") if isinstance(data.get("results"), list) else []:
            if not isinstance(item, dict):
                continue
            results.append(_search_result(result_type="web", title=item.get("title"), url=item.get("url"), snippet=item.get("content"), source_name=urllib.parse.urlparse(str(item.get("url") or "")).netloc, metadata={"provider": "tavily", "score": item.get("score")}))
    if search_type in {"image", "mixed"}:
        images = data.get("images") if isinstance(data.get("images"), list) else []
        for item in images[:limit]:
            if isinstance(item, str):
                image_url = item
                title = query
            elif isinstance(item, dict):
                image_url = item.get("url") or item.get("image_url") or item.get("src")
                title = item.get("description") or item.get("title") or query
            else:
                continue
            results.append(_search_result(result_type="image", title=title, url=image_url, image_url=image_url, thumbnail_url=image_url, source_name=urllib.parse.urlparse(str(image_url or "")).netloc, metadata={"provider": "tavily"}))
    return results


def _brave_results(token: str, query: str, search_type: str, limit: int) -> list[dict[str, Any]]:
    headers = {"X-Subscription-Token": token}
    results: list[dict[str, Any]] = []
    if search_type in {"web", "mixed"}:
        params = urllib.parse.urlencode({"q": query, "count": limit, "safesearch": "moderate", "text_decorations": "false"})
        data = _search_http_json(f"https://api.search.brave.com/res/v1/web/search?{params}", provider_code="brave_search", headers=headers)
        web = data.get("web") if isinstance(data.get("web"), dict) else {}
        for item in web.get("results") if isinstance(web.get("results"), list) else []:
            if not isinstance(item, dict):
                continue
            profile = item.get("profile") if isinstance(item.get("profile"), dict) else {}
            results.append(_search_result(result_type="web", title=item.get("title"), url=item.get("url"), snippet=item.get("description"), source_name=profile.get("name") or urllib.parse.urlparse(str(item.get("url") or "")).netloc, metadata={"provider": "brave_search", "age": item.get("age"), "page_age": item.get("page_age")}))
    if search_type in {"image", "mixed"}:
        params = urllib.parse.urlencode({"q": query, "count": limit, "safesearch": "strict"})
        data = _search_http_json(f"https://api.search.brave.com/res/v1/images/search?{params}", provider_code="brave_search", headers=headers)
        for item in data.get("results") if isinstance(data.get("results"), list) else []:
            if not isinstance(item, dict):
                continue
            props = item.get("properties") if isinstance(item.get("properties"), dict) else {}
            thumbnail = item.get("thumbnail") if isinstance(item.get("thumbnail"), dict) else {}
            meta_url = item.get("meta_url") if isinstance(item.get("meta_url"), dict) else {}
            source_url = item.get("url") or meta_url.get("url") or props.get("url") or props.get("src")
            image_url = props.get("url") or item.get("image_url") or item.get("url")
            results.append(_search_result(result_type="image", title=item.get("title") or query, url=source_url, snippet=item.get("description"), source_name=item.get("source") or meta_url.get("netloc") or urllib.parse.urlparse(str(source_url or "")).netloc, image_url=image_url, thumbnail_url=thumbnail.get("src") or image_url, width=props.get("width"), height=props.get("height"), metadata={"provider": "brave_search"}))
    return results


def _serpapi_results(token: str, query: str, search_type: str, limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if search_type in {"web", "mixed"}:
        params = urllib.parse.urlencode({"engine": "google", "q": query, "num": limit, "hl": "es", "gl": "co", "safe": "active", "api_key": token})
        data = _search_http_json(f"https://serpapi.com/search.json?{params}", provider_code="serpapi")
        for item in data.get("organic_results") if isinstance(data.get("organic_results"), list) else []:
            if not isinstance(item, dict):
                continue
            results.append(_search_result(result_type="web", title=item.get("title"), url=item.get("link"), snippet=item.get("snippet"), source_name=item.get("source") or item.get("displayed_link"), metadata={"provider": "serpapi", "position": item.get("position")}))
    if search_type in {"image", "mixed"}:
        params = urllib.parse.urlencode({"engine": "google_images", "q": query, "ijn": 0, "hl": "es", "gl": "co", "safe": "active", "api_key": token})
        data = _search_http_json(f"https://serpapi.com/search.json?{params}", provider_code="serpapi")
        for item in (data.get("images_results") if isinstance(data.get("images_results"), list) else [])[:limit]:
            if not isinstance(item, dict):
                continue
            results.append(_search_result(result_type="image", title=item.get("title") or query, url=item.get("source") or item.get("link") or item.get("original"), snippet=item.get("snippet"), source_name=item.get("source") or urllib.parse.urlparse(str(item.get("link") or "")).netloc, image_url=item.get("original") or item.get("thumbnail"), thumbnail_url=item.get("thumbnail") or item.get("original"), width=item.get("original_width") or item.get("width"), height=item.get("original_height") or item.get("height"), metadata={"provider": "serpapi", "position": item.get("position")}))
    return results


def _run_provider_search(provider_code: str, token: str, query: str, search_type: str, limit: int) -> list[dict[str, Any]]:
    if provider_code == "tavily":
        return _tavily_results(token, query, search_type, limit)
    if provider_code == "brave_search":
        return _brave_results(token, query, search_type, limit)
    if provider_code == "serpapi":
        return _serpapi_results(token, query, search_type, limit)
    raise HTTPException(status_code=400, detail={"code": "search_provider_unsupported", "provider": provider_code})


def _dedupe_search_results(results: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in results:
        key = (item.get("url") or item.get("image_url") or item.get("thumbnail_url") or item.get("title") or "").lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def _validate_search_context(conn, tenant_id: str, conversation_id: str = "", message_id: str = "") -> dict[str, str]:
    clean_conversation_id = _clean(conversation_id, 80)
    clean_message_id = _clean(message_id, 80)
    if clean_message_id:
        row = conn.execute(
            text(
                """
                SELECT id::text, conversation_id::text
                FROM saas_messages
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:message_id AS uuid)
                LIMIT 1
                """
            ),
            {"tenant_id": tenant_id, "message_id": clean_message_id},
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="search_message_not_found")
        message_conversation_id = str(row["conversation_id"] or "")
        if clean_conversation_id and clean_conversation_id != message_conversation_id:
            raise HTTPException(status_code=400, detail="search_context_mismatch")
        clean_conversation_id = message_conversation_id
    if clean_conversation_id:
        row = conn.execute(
            text(
                """
                SELECT id::text
                FROM saas_conversations
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:conversation_id AS uuid)
                LIMIT 1
                """
            ),
            {"tenant_id": tenant_id, "conversation_id": clean_conversation_id},
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="search_conversation_not_found")
    return {"conversation_id": clean_conversation_id, "message_id": clean_message_id}


def _search_result_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    data["metadata_json"] = _safe_payload(data.get("metadata_json"))
    return data


def _build_search_reference_message(row: dict[str, Any], payload: WebImageSearchReferenceIn) -> dict[str, Any]:
    title = _clean(row.get("title") or "Referencia externa revisada", 220)
    snippet = _clean(row.get("snippet"), 520)
    source_name = _clean(row.get("source_name") or row.get("display_url"), 180)
    url, url_safety, _ = _public_url_status(row.get("url"))
    image_url, image_safety, _ = _public_url_status(row.get("image_url") or row.get("thumbnail_url"))
    if url_safety == "blocked" or not url:
        raise HTTPException(status_code=400, detail={"code": "search_reference_source_not_public"})
    lines: list[str] = []
    note = _clean(payload.note, 700)
    if note:
        lines.append(note)
        lines.append("")
    lines.append("Te comparto una referencia revisada:")
    lines.append(title)
    if snippet:
        lines.append(snippet)
    if payload.include_source_url:
        label = f"Fuente ({source_name})" if source_name else "Fuente"
        lines.append(f"{label}: {url}")
    if payload.include_image_url and image_url and image_safety != "blocked":
        lines.append(f"Imagen de referencia: {image_url}")
    license_label = _clean(row.get("license_label"), 160)
    license_url, license_safety, _ = _public_url_status(row.get("license_details_url"))
    if license_label:
        lines.append(f"Licencia: {license_label}")
    if license_url and license_safety != "blocked":
        lines.append(f"Detalles licencia: {license_url}")
    message_text = "\n".join(line for line in lines if line is not None).strip()[:3900]
    return {
        "message_text": message_text,
        "title": title,
        "source_url": url,
        "visual_url": image_url if payload.include_image_url and image_safety != "blocked" else "",
        "source_name": source_name,
        "has_visual_reference": bool(image_url and image_safety != "blocked"),
    }


def _search_run_row(row: Any, results: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    data = dict(row)
    data["metadata_json"] = _safe_payload(data.get("metadata_json"))
    data["results"] = results or []
    return data


def _insert_search_run(
    conn,
    *,
    tenant_id: str,
    user_id: str,
    context: dict[str, str],
    query: str,
    search_type: str,
    provider_code: str,
    access_mode: str,
    results: list[dict[str, Any]],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    run = conn.execute(
        text(
            """
            INSERT INTO saas_web_search_intelligence_runs (
                tenant_id, conversation_id, message_id, created_by_user_id,
                query, search_type, provider_code, status, access_mode, summary, metadata_json, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), CAST(NULLIF(:conversation_id, '') AS uuid),
                CAST(NULLIF(:message_id, '') AS uuid), CAST(:user_id AS uuid),
                :query, :search_type, :provider_code, 'completed', :access_mode, :summary,
                CAST(:metadata_json AS jsonb), NOW()
            )
            RETURNING id::text, tenant_id::text, COALESCE(conversation_id::text, '') AS conversation_id,
                      COALESCE(message_id::text, '') AS message_id,
                      COALESCE(created_by_user_id::text, '') AS created_by_user_id,
                      query, search_type, provider_code, status, access_mode,
                      result_count, approved_count, blocked_count, summary, metadata_json,
                      created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "conversation_id": context.get("conversation_id") or "",
            "message_id": context.get("message_id") or "",
            "user_id": user_id,
            "query": query,
            "search_type": search_type,
            "provider_code": provider_code,
            "access_mode": access_mode,
            "summary": f"{len(results)} resultados de referencia. Requieren aprobacion humana antes de usarse con clientes.",
            "metadata_json": _json(metadata),
        },
    ).mappings().first()
    run_id = str(run["id"])
    saved_results: list[dict[str, Any]] = []
    for rank, item in enumerate(results, start=1):
        row = conn.execute(
            text(
                """
                INSERT INTO saas_web_search_intelligence_results (
                    tenant_id, run_id, result_type, title, url, display_url, snippet,
                    source_name, image_url, thumbnail_url, license_label, license_details_url,
                    width, height, rank, safety_status, approval_status,
                    rejected_reason, metadata_json, updated_at
                )
                VALUES (
                    CAST(:tenant_id AS uuid), CAST(:run_id AS uuid), :result_type, :title,
                    :url, :display_url, :snippet, :source_name, :image_url, :thumbnail_url,
                    :license_label, :license_details_url, :width, :height, :rank,
                    :safety_status, :approval_status, :rejected_reason, CAST(:metadata_json AS jsonb), NOW()
                )
                RETURNING id::text, tenant_id::text, run_id::text, result_type, title, url,
                          display_url, snippet, source_name, image_url, thumbnail_url,
                          license_label, license_details_url, width, height, rank,
                          safety_status, approval_status,
                          COALESCE(approved_by_user_id::text, '') AS approved_by_user_id,
                          COALESCE(approved_at::text, '') AS approved_at,
                          rejected_reason, metadata_json, created_at::text, updated_at::text
                """
            ),
            {
                "tenant_id": tenant_id,
                "run_id": run_id,
                "result_type": item.get("result_type") or "web",
                "title": _clean(item.get("title"), 400),
                "url": _clean(item.get("url"), 2000),
                "display_url": _clean(item.get("display_url"), 240),
                "snippet": _clean(item.get("snippet"), 1400),
                "source_name": _clean(item.get("source_name"), 240),
                "image_url": _clean(item.get("image_url"), 2000),
                "thumbnail_url": _clean(item.get("thumbnail_url"), 2000),
                "license_label": _clean(item.get("license_label"), 160),
                "license_details_url": _clean(item.get("license_details_url"), 2000),
                "width": _as_int(item.get("width")),
                "height": _as_int(item.get("height")),
                "rank": rank,
                "safety_status": _clean(item.get("safety_status") or "pending_review", 40),
                "approval_status": _clean(item.get("approval_status") or "pending", 40),
                "rejected_reason": _clean(item.get("rejected_reason"), 500),
                "metadata_json": _json(item.get("metadata_json") if isinstance(item.get("metadata_json"), dict) else {}),
            },
        ).mappings().first()
        saved_results.append(_search_result_row(row))
    updated = conn.execute(
        text(
            """
            UPDATE saas_web_search_intelligence_runs r
            SET result_count = counts.result_count,
                approved_count = counts.approved_count,
                blocked_count = counts.blocked_count,
                updated_at = NOW()
            FROM (
                SELECT
                    COUNT(*)::int AS result_count,
                    COUNT(*) FILTER (WHERE approval_status = 'approved')::int AS approved_count,
                    COUNT(*) FILTER (WHERE safety_status = 'blocked')::int AS blocked_count
                FROM saas_web_search_intelligence_results
                WHERE run_id = CAST(:run_id AS uuid)
            ) counts
            WHERE r.tenant_id = CAST(:tenant_id AS uuid)
              AND r.id = CAST(:run_id AS uuid)
            RETURNING r.id::text, r.tenant_id::text, COALESCE(r.conversation_id::text, '') AS conversation_id,
                      COALESCE(r.message_id::text, '') AS message_id,
                      COALESCE(r.created_by_user_id::text, '') AS created_by_user_id,
                      r.query, r.search_type, r.provider_code, r.status, r.access_mode,
                      r.result_count, r.approved_count, r.blocked_count, r.summary, r.metadata_json,
                      r.created_at::text, r.updated_at::text
            """
        ),
        {"tenant_id": tenant_id, "run_id": run_id},
    ).mappings().first()
    return _search_run_row(updated or run, saved_results)


def _load_search_runs(conn, tenant_id: str, conversation_id: str = "", limit: int = 10) -> list[dict[str, Any]]:
    clean_limit = min(max(1, int(limit or 10)), 30)
    params = {"tenant_id": tenant_id, "limit": clean_limit}
    where = ["tenant_id = CAST(:tenant_id AS uuid)"]
    if _clean(conversation_id, 80):
        where.append("conversation_id = CAST(:conversation_id AS uuid)")
        params["conversation_id"] = _clean(conversation_id, 80)
    rows = conn.execute(
        text(
            f"""
            SELECT id::text, tenant_id::text, COALESCE(conversation_id::text, '') AS conversation_id,
                   COALESCE(message_id::text, '') AS message_id,
                   COALESCE(created_by_user_id::text, '') AS created_by_user_id,
                   query, search_type, provider_code, status, access_mode,
                   result_count, approved_count, blocked_count, summary, metadata_json,
                   created_at::text, updated_at::text
            FROM saas_web_search_intelligence_runs
            WHERE {' AND '.join(where)}
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()
    runs: list[dict[str, Any]] = []
    for row in rows:
        result_rows = conn.execute(
            text(
                """
                SELECT id::text, tenant_id::text, run_id::text, result_type, title, url,
                       display_url, snippet, source_name, image_url, thumbnail_url,
                       license_label, license_details_url, width, height, rank,
                       safety_status, approval_status,
                       COALESCE(approved_by_user_id::text, '') AS approved_by_user_id,
                       COALESCE(approved_at::text, '') AS approved_at,
                       rejected_reason, metadata_json, created_at::text, updated_at::text
                FROM saas_web_search_intelligence_results
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND run_id = CAST(:run_id AS uuid)
                ORDER BY rank ASC, created_at ASC
                """
            ),
            {"tenant_id": tenant_id, "run_id": str(row["id"])},
        ).mappings().all()
        runs.append(_search_run_row(row, [_search_result_row(item) for item in result_rows]))
    return runs


def _resolve_voice_access(conn, tenant_id: str) -> dict[str, Any]:
    last_detail: Any = None
    for feature_key in VOICE_ACCESS_FEATURES:
        try:
            access = dict(resolve_intelligence_access(conn, tenant_id, feature_key, allow_demo=True))
            access["resolved_feature_key"] = feature_key
            return access
        except HTTPException as exc:
            last_detail = exc.detail
    raise HTTPException(status_code=403, detail={"code": "voice_intelligence_not_enabled", "features": list(VOICE_ACCESS_FEATURES), "last_error": last_detail})


def _resolve_vision_access(conn, tenant_id: str, media_kind: str = "image") -> dict[str, Any]:
    last_detail: Any = None
    media_feature = "image_understanding" if media_kind == "image" else "document_ocr"
    for feature_key in (VISION_INTELLIGENCE_FEATURE, media_feature, "ai_premium"):
        try:
            access = dict(resolve_intelligence_access(conn, tenant_id, feature_key, allow_demo=True))
            access["resolved_feature_key"] = feature_key
            return access
        except HTTPException as exc:
            last_detail = exc.detail
    raise HTTPException(status_code=403, detail={"code": "vision_intelligence_not_enabled", "features": list(VISION_ACCESS_FEATURES), "last_error": last_detail})


def _try_sync_multimodal_memory(conn, tenant_id: str, user_id: str, payload: dict[str, Any]) -> None:
    try:
        from app_saas.agents.multimodal_memory import sync_multimodal_memory_events

        sync_multimodal_memory_events(conn, tenant_id, user_id, payload)
    except Exception:
        # Multimodal memory is a secondary premium bridge. It must never break
        # voice/vision/search analysis when disabled or unavailable.
        return


def _upsert_voice_analysis(
    conn,
    *,
    tenant_id: str,
    user_id: str,
    message: dict[str, Any],
    analysis: dict[str, Any],
    provider_code: str,
    model: str,
    run_id: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            INSERT INTO saas_voice_intelligence_analyses (
                tenant_id, conversation_id, message_id, created_by_user_id, media_id,
                source, provider_code, model, ai_gateway_run_id, status,
                transcript, summary, sentiment, sentiment_score, intent, intent_label,
                urgency, language, confidence, analysis_json, metadata_json, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), CAST(:conversation_id AS uuid), CAST(:message_id AS uuid),
                CAST(:user_id AS uuid), :media_id, :source, :provider_code, :model,
                CAST(NULLIF(:run_id, '') AS uuid), 'completed',
                :transcript, :summary, :sentiment, :sentiment_score, :intent, :intent_label,
                :urgency, :language, :confidence, CAST(:analysis_json AS jsonb), CAST(:metadata_json AS jsonb), NOW()
            )
            ON CONFLICT (tenant_id, message_id)
            DO UPDATE SET
                created_by_user_id = EXCLUDED.created_by_user_id,
                media_id = EXCLUDED.media_id,
                source = EXCLUDED.source,
                provider_code = EXCLUDED.provider_code,
                model = EXCLUDED.model,
                ai_gateway_run_id = EXCLUDED.ai_gateway_run_id,
                status = EXCLUDED.status,
                transcript = EXCLUDED.transcript,
                summary = EXCLUDED.summary,
                sentiment = EXCLUDED.sentiment,
                sentiment_score = EXCLUDED.sentiment_score,
                intent = EXCLUDED.intent,
                intent_label = EXCLUDED.intent_label,
                urgency = EXCLUDED.urgency,
                language = EXCLUDED.language,
                confidence = EXCLUDED.confidence,
                analysis_json = EXCLUDED.analysis_json,
                metadata_json = saas_voice_intelligence_analyses.metadata_json || EXCLUDED.metadata_json,
                updated_at = NOW()
            RETURNING id::text, tenant_id::text, conversation_id::text, message_id::text,
                      COALESCE(created_by_user_id::text, '') AS created_by_user_id,
                      media_id, source, provider_code, model,
                      COALESCE(ai_gateway_run_id::text, '') AS ai_gateway_run_id,
                      status, transcript, summary, sentiment, sentiment_score,
                      intent, intent_label, urgency, language, confidence,
                      analysis_json, metadata_json, created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "conversation_id": message["conversation_id"],
            "message_id": message["id"],
            "user_id": user_id,
            "media_id": _clean(message.get("media_id"), 240),
            "source": metadata.get("source") or "inbox_audio",
            "provider_code": _clean(provider_code, 80),
            "model": _clean(model, 240),
            "run_id": _clean(run_id, 80),
            "transcript": _clean(analysis.get("transcript"), 12000),
            "summary": _clean(analysis.get("summary"), 3000),
            "sentiment": _clean(analysis.get("sentiment") or "neutral", 40),
            "sentiment_score": _bounded_float(analysis.get("sentiment_score"), 0.0, -1.0, 1.0),
            "intent": _clean(analysis.get("intent") or "other", 80),
            "intent_label": _clean(analysis.get("intent_label") or "", 120),
            "urgency": _clean(analysis.get("urgency") or "low", 40),
            "language": _clean(analysis.get("language") or "", 60),
            "confidence": _bounded_float(analysis.get("confidence"), 0.0, 0.0, 1.0),
            "analysis_json": _json(analysis),
            "metadata_json": _json(metadata),
        },
    ).mappings().first()
    saved = _analysis_row(row)
    compact = _voice_compact(saved["analysis_json"], saved)
    conn.execute(
        text(
            """
            UPDATE saas_messages
            SET payload_json = COALESCE(payload_json, '{}'::jsonb)
                || jsonb_build_object('voice_intelligence', CAST(:voice_json AS jsonb))
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:message_id AS uuid)
            """
        ),
        {"tenant_id": tenant_id, "message_id": message["id"], "voice_json": _json(compact)},
    )
    saved["voice_intelligence"] = compact
    return saved


def _upsert_vision_analysis(
    conn,
    *,
    tenant_id: str,
    user_id: str,
    message: dict[str, Any],
    analysis: dict[str, Any],
    provider_code: str,
    model: str,
    run_id: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            INSERT INTO saas_vision_intelligence_analyses (
                tenant_id, conversation_id, message_id, created_by_user_id, media_id, media_kind,
                source, provider_code, model, ai_gateway_run_id, status,
                visual_description, extracted_text, summary, document_type,
                sentiment, sentiment_score, intent, intent_label, urgency, language, confidence,
                entities_json, topics_json, product_hints_json, moderation_flags_json,
                analysis_json, metadata_json, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), CAST(:conversation_id AS uuid), CAST(:message_id AS uuid),
                CAST(:user_id AS uuid), :media_id, :media_kind, :source, :provider_code, :model,
                CAST(NULLIF(:run_id, '') AS uuid), 'completed',
                :visual_description, :extracted_text, :summary, :document_type,
                :sentiment, :sentiment_score, :intent, :intent_label, :urgency, :language, :confidence,
                CAST(:entities_json AS jsonb), CAST(:topics_json AS jsonb), CAST(:product_hints_json AS jsonb),
                CAST(:moderation_flags_json AS jsonb), CAST(:analysis_json AS jsonb), CAST(:metadata_json AS jsonb), NOW()
            )
            ON CONFLICT (tenant_id, message_id)
            DO UPDATE SET
                created_by_user_id = EXCLUDED.created_by_user_id,
                media_id = EXCLUDED.media_id,
                media_kind = EXCLUDED.media_kind,
                source = EXCLUDED.source,
                provider_code = EXCLUDED.provider_code,
                model = EXCLUDED.model,
                ai_gateway_run_id = EXCLUDED.ai_gateway_run_id,
                status = EXCLUDED.status,
                visual_description = EXCLUDED.visual_description,
                extracted_text = EXCLUDED.extracted_text,
                summary = EXCLUDED.summary,
                document_type = EXCLUDED.document_type,
                sentiment = EXCLUDED.sentiment,
                sentiment_score = EXCLUDED.sentiment_score,
                intent = EXCLUDED.intent,
                intent_label = EXCLUDED.intent_label,
                urgency = EXCLUDED.urgency,
                language = EXCLUDED.language,
                confidence = EXCLUDED.confidence,
                entities_json = EXCLUDED.entities_json,
                topics_json = EXCLUDED.topics_json,
                product_hints_json = EXCLUDED.product_hints_json,
                moderation_flags_json = EXCLUDED.moderation_flags_json,
                analysis_json = EXCLUDED.analysis_json,
                metadata_json = saas_vision_intelligence_analyses.metadata_json || EXCLUDED.metadata_json,
                updated_at = NOW()
            RETURNING id::text, tenant_id::text, conversation_id::text, message_id::text,
                      COALESCE(created_by_user_id::text, '') AS created_by_user_id,
                      media_id, media_kind, source, provider_code, model,
                      COALESCE(ai_gateway_run_id::text, '') AS ai_gateway_run_id,
                      status, visual_description, extracted_text, summary, document_type,
                      sentiment, sentiment_score, intent, intent_label, urgency, language, confidence,
                      entities_json, topics_json, product_hints_json, moderation_flags_json,
                      analysis_json, metadata_json, created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "conversation_id": message["conversation_id"],
            "message_id": message["id"],
            "user_id": user_id,
            "media_id": _clean(message.get("media_id"), 240),
            "media_kind": _clean(message.get("media_kind") or "image", 40),
            "source": metadata.get("source") or "inbox_media",
            "provider_code": _clean(provider_code, 80),
            "model": _clean(model, 240),
            "run_id": _clean(run_id, 80),
            "visual_description": _clean(analysis.get("visual_description"), 5000),
            "extracted_text": _clean(analysis.get("extracted_text"), 16000),
            "summary": _clean(analysis.get("summary"), 3000),
            "document_type": _clean(analysis.get("document_type") or "unknown", 80),
            "sentiment": _clean(analysis.get("sentiment") or "neutral", 40),
            "sentiment_score": _bounded_float(analysis.get("sentiment_score"), 0.0, -1.0, 1.0),
            "intent": _clean(analysis.get("intent") or "other", 80),
            "intent_label": _clean(analysis.get("intent_label") or "", 120),
            "urgency": _clean(analysis.get("urgency") or "low", 40),
            "language": _clean(analysis.get("language") or "", 60),
            "confidence": _bounded_float(analysis.get("confidence"), 0.0, 0.0, 1.0),
            "entities_json": _json(analysis.get("entities") if isinstance(analysis.get("entities"), list) else []),
            "topics_json": _json(analysis.get("topics") if isinstance(analysis.get("topics"), list) else []),
            "product_hints_json": _json(analysis.get("product_hints") if isinstance(analysis.get("product_hints"), dict) else {}),
            "moderation_flags_json": _json(analysis.get("moderation_flags") if isinstance(analysis.get("moderation_flags"), list) else []),
            "analysis_json": _json(analysis),
            "metadata_json": _json(metadata),
        },
    ).mappings().first()
    saved = _vision_analysis_row(row)
    compact = _vision_compact(saved["analysis_json"], saved)
    conn.execute(
        text(
            """
            UPDATE saas_messages
            SET payload_json = COALESCE(payload_json, '{}'::jsonb)
                || jsonb_build_object('vision_intelligence', CAST(:vision_json AS jsonb))
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:message_id AS uuid)
            """
        ),
        {"tenant_id": tenant_id, "message_id": message["id"], "vision_json": _json(compact)},
    )
    saved["vision_intelligence"] = compact
    return saved


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


@router.post("/messages/{message_id}/voice/analyze")
def analyze_voice_message(
    message_id: str,
    force: bool = Query(False),
    provider_code: str = Query("", max_length=80),
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor", "agent")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_voice_intelligence_tables(conn)
        access = _resolve_voice_access(conn, ctx.tenant_id)
        message = _load_audio_message(conn, ctx.tenant_id, message_id)
        access = apply_multimodal_safe_rollout(
            conn,
            ctx.tenant_id,
            access=access,
            feature_key=str(access.get("resolved_feature_key") or VOICE_INTELLIGENCE_FEATURE),
            modality="voice",
            subject_type="message",
            subject_id=message_id,
            metadata={"route": "media.voice_analyze", "force": bool(force)},
        )
        cached = _load_voice_analysis(conn, ctx.tenant_id, message_id)
        if cached and str(cached.get("status") or "") == "completed" and not force:
            conn.execute(
                text(
                    """
                    UPDATE saas_messages
                    SET payload_json = COALESCE(payload_json, '{}'::jsonb)
                        || jsonb_build_object('voice_intelligence', CAST(:voice_json AS jsonb))
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND id = CAST(:message_id AS uuid)
                    """
                ),
                {"tenant_id": ctx.tenant_id, "message_id": message_id, "voice_json": _json(cached.get("voice_intelligence") or {})},
            )
            _try_sync_multimodal_memory(
                conn,
                ctx.tenant_id,
                ctx.user_id,
                {"message_id": message_id, "conversation_id": cached.get("conversation_id") or "", "include_voice": True, "include_vision": False, "include_search": False, "include_agent_runs": False, "limit": 3},
            )
            return {"ok": True, "tenant_id": ctx.tenant_id, "cached": True, "access": access, "analysis": cached}

        content, content_type, media_metadata = _load_audio_bytes(conn, ctx.tenant_id, message)
        byte_size = len(content)
        max_bytes = MAX_VOICE_DEMO_BYTES if str(access.get("mode") or "") == "demo" else MAX_VOICE_ANALYSIS_BYTES
        if byte_size > max_bytes:
            raise HTTPException(
                status_code=413,
                detail={
                    "code": "voice_audio_too_large",
                    "limit_bytes": max_bytes,
                    "byte_size": byte_size,
                    "mode": access.get("mode") or "demo",
                },
            )

        settings = get_settings(conn, ctx.tenant_id)
        providers = _voice_provider_chain(settings, requested_provider=provider_code)
        system_prompt, user_prompt = _voice_prompts(message, str(access.get("mode") or "demo"))
        estimated_prompt_tokens = estimate_tokens(system_prompt, user_prompt) + max(120, int(byte_size / 512))
        ensure_ai_token_quota(conn, ctx.tenant_id, requested=estimated_prompt_tokens)
        record_intelligence_usage(
            conn,
            ctx.tenant_id,
            str(access.get("resolved_feature_key") or VOICE_INTELLIGENCE_FEATURE),
            usage_metric="voice_analysis_requests",
            metadata={
                "message_id": message["id"],
                "conversation_id": message["conversation_id"],
                "media_id": message.get("media_id") or "",
                "byte_size": byte_size,
                "mime_type": content_type,
                "mode": access.get("mode") or "demo",
            },
        )

        gateway = generate_with_gateway(
            conn,
            tenant_id=ctx.tenant_id,
            task_type="voice_intelligence",
            agent_type="voice_intelligence_agent",
            route_code="voice.intelligence",
            conversation_id=message["conversation_id"],
            provider_chain=providers,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            settings={
                **settings,
                "temperature": 0.2,
                "max_tokens": min(int(settings.get("max_tokens") or 1800), 2600),
                "metadata_json": {
                    "phase": "24.2",
                    "feature_key": VOICE_INTELLIGENCE_FEATURE,
                    "message_id": message["id"],
                    "media_id": message.get("media_id") or "",
                    "byte_size": byte_size,
                    "mime_type": content_type,
                    "voice_access_mode": access.get("mode") or "demo",
                    "provider_policy": providers,
                },
            },
            attachments=[
                {
                    "kind": "audio",
                    "mime_type": content_type or "audio/webm",
                    "data_base64": base64.b64encode(content).decode("ascii"),
                    "name": _clean(message.get("media_id"), 80) or "voice-message",
                    "metadata": {
                        "message_id": message["id"],
                        "conversation_id": message["conversation_id"],
                        "byte_size": byte_size,
                    },
                }
            ],
        )
        if not gateway.get("ok"):
            raise HTTPException(status_code=409, detail={"code": "voice_ai_unavailable", "reason": gateway.get("skipped") or "ai_unavailable"})

        raw = _clean(gateway.get("raw"), 50000)
        analysis = _normalize_voice_analysis(_extract_json_object(raw), raw)
        if str(access.get("mode") or "") == "demo":
            analysis["demo_limited"] = True
            analysis["limit_note"] = "Modo demo: analisis limitado. Activa Voice Intelligence full para mayor cuota e historial operacional."
        metadata = {
            **media_metadata,
            "source": media_metadata.get("source") or "inbox_audio",
            "content_type": content_type,
            "byte_size": byte_size,
            "access_mode": access.get("mode") or "demo",
            "provider_policy": providers,
            "estimated_prompt_tokens": estimated_prompt_tokens,
            "gateway_estimated_tokens": int(gateway.get("estimated_tokens") or 0),
        }
        saved = _upsert_voice_analysis(
            conn,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            message=message,
            analysis=analysis,
            provider_code=str(gateway.get("provider_code") or ""),
            model=str(gateway.get("model") or ""),
            run_id=str(gateway.get("run_id") or ""),
            metadata=metadata,
        )
        _record_ai_usage(conn, ctx.tenant_id, int(gateway.get("estimated_tokens") or estimated_prompt_tokens))
        record_inline_event(
            conn,
            ctx.tenant_id,
            event_type="message.audio.analyzed",
            source="voice_intelligence",
            channel=str(message.get("channel") or ""),
            entity_type="message",
            entity_id=message["id"],
            conversation_id=message["conversation_id"],
            customer_key=str(message.get("external_contact_id") or message.get("phone") or ""),
            occurred_at=datetime.now(timezone.utc).isoformat(),
            payload_json={
                "sentiment": saved.get("sentiment"),
                "intent": saved.get("intent"),
                "urgency": saved.get("urgency"),
                "confidence": float(saved.get("confidence") or 0),
                "analysis_id": saved.get("id"),
                "provider": saved.get("provider_code"),
                "model": saved.get("model"),
                "byte_size": byte_size,
            },
            correlation_id="",
            replay_key=f"voice-intelligence:{saved.get('id') or message['id']}",
        )
        _try_sync_multimodal_memory(
            conn,
            ctx.tenant_id,
            ctx.user_id,
            {"message_id": message["id"], "conversation_id": message["conversation_id"], "include_voice": True, "include_vision": False, "include_search": False, "include_agent_runs": False, "limit": 3},
        )

    return {
        "ok": True,
        "tenant_id": ctx.tenant_id,
        "cached": False,
        "access": access,
        "analysis": saved,
    }


@router.post("/messages/{message_id}/vision/analyze")
def analyze_vision_message(
    message_id: str,
    force: bool = Query(False),
    provider_code: str = Query("", max_length=80),
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor", "agent")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_vision_intelligence_tables(conn)
        message = _load_visual_message(conn, ctx.tenant_id, message_id)
        access = _resolve_vision_access(conn, ctx.tenant_id, str(message.get("media_kind") or "image"))
        access = apply_multimodal_safe_rollout(
            conn,
            ctx.tenant_id,
            access=access,
            feature_key=str(access.get("resolved_feature_key") or VISION_INTELLIGENCE_FEATURE),
            modality="vision",
            subject_type="message",
            subject_id=message_id,
            provider_code=_clean(provider_code, 80),
            metadata={"route": "media.vision_analyze", "force": bool(force), "media_kind": message.get("media_kind") or "image"},
        )
        cached = _load_vision_analysis(conn, ctx.tenant_id, message_id)
        if cached and str(cached.get("status") or "") == "completed" and not force:
            conn.execute(
                text(
                    """
                    UPDATE saas_messages
                    SET payload_json = COALESCE(payload_json, '{}'::jsonb)
                        || jsonb_build_object('vision_intelligence', CAST(:vision_json AS jsonb))
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND id = CAST(:message_id AS uuid)
                    """
                ),
                {"tenant_id": ctx.tenant_id, "message_id": message_id, "vision_json": _json(cached.get("vision_intelligence") or {})},
            )
            _try_sync_multimodal_memory(
                conn,
                ctx.tenant_id,
                ctx.user_id,
                {"message_id": message_id, "conversation_id": cached.get("conversation_id") or "", "include_voice": False, "include_vision": True, "include_search": False, "include_agent_runs": False, "limit": 3},
            )
            return {"ok": True, "tenant_id": ctx.tenant_id, "cached": True, "access": access, "analysis": cached}

        content, content_type, media_metadata = _load_visual_bytes(conn, ctx.tenant_id, message)
        content_type = _base_mime(content_type) or "application/octet-stream"
        media_kind = _visual_kind_for(content_type, str(message.get("msg_type") or ""))
        message["media_kind"] = media_kind
        if not _visual_mime_supported(content_type, media_kind):
            raise HTTPException(
                status_code=415,
                detail={
                    "code": "vision_media_type_unsupported",
                    "mime_type": content_type,
                    "media_kind": media_kind,
                    "supported": ["image/*", *sorted(VISION_DOCUMENT_MIME_TYPES)],
                },
            )
        byte_size = len(content)
        max_bytes = MAX_VISION_DEMO_BYTES if str(access.get("mode") or "") == "demo" else MAX_VISION_ANALYSIS_BYTES
        if byte_size > max_bytes:
            raise HTTPException(
                status_code=413,
                detail={
                    "code": "vision_media_too_large",
                    "limit_bytes": max_bytes,
                    "byte_size": byte_size,
                    "mode": access.get("mode") or "demo",
                },
            )

        settings = get_settings(conn, ctx.tenant_id)
        providers = _vision_provider_chain(settings, requested_provider=provider_code, media_kind=media_kind)
        system_prompt, user_prompt = _vision_prompts(message, str(access.get("mode") or "demo"), content_type, media_kind)
        estimated_prompt_tokens = estimate_tokens(system_prompt, user_prompt) + max(180, int(byte_size / 768))
        ensure_ai_token_quota(conn, ctx.tenant_id, requested=estimated_prompt_tokens)
        record_intelligence_usage(
            conn,
            ctx.tenant_id,
            str(access.get("resolved_feature_key") or VISION_INTELLIGENCE_FEATURE),
            usage_metric="vision_analysis_requests",
            metadata={
                "message_id": message["id"],
                "conversation_id": message["conversation_id"],
                "media_id": message.get("media_id") or "",
                "media_kind": media_kind,
                "byte_size": byte_size,
                "mime_type": content_type,
                "mode": access.get("mode") or "demo",
            },
        )

        gateway = generate_with_gateway(
            conn,
            tenant_id=ctx.tenant_id,
            task_type="vision_intelligence",
            agent_type="vision_intelligence_agent",
            route_code="vision.intelligence",
            conversation_id=message["conversation_id"],
            provider_chain=providers,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            settings={
                **settings,
                "temperature": 0.15,
                "max_tokens": min(int(settings.get("max_tokens") or 2200), 3200),
                "metadata_json": {
                    "phase": "24.3",
                    "feature_key": VISION_INTELLIGENCE_FEATURE,
                    "message_id": message["id"],
                    "media_id": message.get("media_id") or "",
                    "media_kind": media_kind,
                    "byte_size": byte_size,
                    "mime_type": content_type,
                    "vision_access_mode": access.get("mode") or "demo",
                    "provider_policy": providers,
                },
            },
            attachments=[
                {
                    "kind": media_kind,
                    "mime_type": content_type,
                    "data_base64": base64.b64encode(content).decode("ascii"),
                    "name": _clean(message.get("media_id"), 80) or f"{media_kind}-message",
                    "metadata": {
                        "message_id": message["id"],
                        "conversation_id": message["conversation_id"],
                        "byte_size": byte_size,
                        "media_kind": media_kind,
                    },
                }
            ],
        )
        if not gateway.get("ok"):
            raise HTTPException(status_code=409, detail={"code": "vision_ai_unavailable", "reason": gateway.get("skipped") or "ai_unavailable"})

        raw = _clean(gateway.get("raw"), 60000)
        analysis = _normalize_vision_analysis(_extract_json_object(raw), raw)
        analysis["media_kind"] = media_kind
        if str(access.get("mode") or "") == "demo":
            analysis["demo_limited"] = True
            analysis["limit_note"] = "Modo demo: analisis visual limitado. Activa Vision Intelligence full para mayor cuota e historial operacional."
        metadata = {
            **media_metadata,
            "source": media_metadata.get("source") or "inbox_media",
            "content_type": content_type,
            "media_kind": media_kind,
            "byte_size": byte_size,
            "access_mode": access.get("mode") or "demo",
            "provider_policy": providers,
            "estimated_prompt_tokens": estimated_prompt_tokens,
            "gateway_estimated_tokens": int(gateway.get("estimated_tokens") or 0),
        }
        saved = _upsert_vision_analysis(
            conn,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            message=message,
            analysis=analysis,
            provider_code=str(gateway.get("provider_code") or ""),
            model=str(gateway.get("model") or ""),
            run_id=str(gateway.get("run_id") or ""),
            metadata=metadata,
        )
        _record_ai_usage(conn, ctx.tenant_id, int(gateway.get("estimated_tokens") or estimated_prompt_tokens))
        record_inline_event(
            conn,
            ctx.tenant_id,
            event_type="message.visual.analyzed",
            source="vision_intelligence",
            channel=str(message.get("channel") or ""),
            entity_type="message",
            entity_id=message["id"],
            conversation_id=message["conversation_id"],
            customer_key=str(message.get("external_contact_id") or message.get("phone") or ""),
            occurred_at=datetime.now(timezone.utc).isoformat(),
            payload_json={
                "media_kind": media_kind,
                "document_type": saved.get("document_type"),
                "sentiment": saved.get("sentiment"),
                "intent": saved.get("intent"),
                "urgency": saved.get("urgency"),
                "confidence": float(saved.get("confidence") or 0),
                "analysis_id": saved.get("id"),
                "provider": saved.get("provider_code"),
                "model": saved.get("model"),
                "byte_size": byte_size,
            },
            correlation_id="",
            replay_key=f"vision-intelligence:{saved.get('id') or message['id']}",
        )
        _try_sync_multimodal_memory(
            conn,
            ctx.tenant_id,
            ctx.user_id,
            {"message_id": message["id"], "conversation_id": message["conversation_id"], "include_voice": False, "include_vision": True, "include_search": False, "include_agent_runs": False, "limit": 3},
        )

    return {
        "ok": True,
        "tenant_id": ctx.tenant_id,
        "cached": False,
        "access": access,
        "analysis": saved,
    }


@router.post("/search")
def create_web_image_search(
    payload: WebImageSearchIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor", "agent")),
):
    query = _clean(payload.query, 280)
    search_type = _clean(payload.search_type, 20).lower()
    if search_type not in SEARCH_TYPES:
        raise HTTPException(status_code=400, detail={"code": "invalid_search_type", "allowed": sorted(SEARCH_TYPES)})
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_web_image_search_tables(conn)
        context = _validate_search_context(conn, ctx.tenant_id, payload.conversation_id, payload.message_id)
        access = _resolve_search_access(conn, ctx.tenant_id, search_type)
        access = apply_multimodal_safe_rollout(
            conn,
            ctx.tenant_id,
            access=access,
            feature_key=str(access.get("resolved_feature_key") or EXTERNAL_SOURCE_FEATURE),
            modality="image_search" if search_type == "image" else "web_search" if search_type == "web" else "mixed_search",
            subject_type="conversation" if context.get("conversation_id") else "search_query",
            subject_id=context.get("conversation_id") or hashlib.sha256(query.encode("utf-8", errors="ignore")).hexdigest()[:24],
            provider_code=_clean(payload.provider_code, 80),
            metadata={"route": "media.web_image_search", "search_type": search_type, "query_length": len(query)},
        )
        limit = min(max(1, int(payload.limit or 6)), MAX_SEARCH_DEMO_LIMIT if str(access.get("mode") or "") == "demo" else MAX_SEARCH_LIMIT)
        settings = get_settings(conn, ctx.tenant_id)
        providers = _search_provider_order(settings, payload.provider_code)
        last_error: Any = None
        provider_code = ""
        raw_results: list[dict[str, Any]] = []
        last_error_status = 409
        for candidate in providers:
            try:
                provider_policy = assert_provider_enabled(conn, ctx.tenant_id, "search", candidate, "")
            except HTTPException as exc:
                last_error = exc.detail
                last_error_status = exc.status_code
                continue
            credential = _load_search_credential(conn, ctx.tenant_id, candidate)
            if not credential:
                last_error = {"code": "search_provider_credential_required", "provider": candidate, "credential_key": SEARCH_PROVIDER_KEYS.get(candidate)}
                last_error_status = 409
                continue
            try:
                raw_results = _run_provider_search(candidate, str(credential.get("token") or ""), query, search_type, limit)
                provider_code = candidate
                break
            except HTTPException as exc:
                last_error = exc.detail
                last_error_status = exc.status_code
                continue
        if not provider_code:
            raise HTTPException(status_code=last_error_status, detail=last_error or {"code": "search_provider_required", "providers": providers})

        results = _dedupe_search_results(raw_results, limit)
        record_intelligence_usage(
            conn,
            ctx.tenant_id,
            str(access.get("resolved_feature_key") or EXTERNAL_SOURCE_FEATURE),
            usage_metric="web_image_search_requests",
            metadata={
                "query_length": len(query),
                "search_type": search_type,
                "provider_code": provider_code,
                "result_count": len(results),
                "mode": access.get("mode") or "demo",
                "conversation_id": context.get("conversation_id") or "",
                "message_id": context.get("message_id") or "",
            },
        )
        saved = _insert_search_run(
            conn,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            context=context,
            query=query,
            search_type=search_type,
            provider_code=provider_code,
            access_mode=str(access.get("mode") or "demo"),
            results=results,
            metadata={
                "phase": "24.4",
                "provider_policy": providers,
                "provider_policy_scope": provider_policy.get("resolved_scope", ""),
                "requested_provider": _clean(payload.provider_code, 80),
                "limit": limit,
                "feature_key": access.get("resolved_feature_key") or EXTERNAL_SOURCE_FEATURE,
                "human_approval_required": True,
                "copyright_note": "Los resultados son referencias externas; revisar fuente/licencia antes de enviarlos a clientes.",
            },
        )
        record_inline_event(
            conn,
            ctx.tenant_id,
            event_type="external_search.executed",
            source="web_image_search",
            channel="web",
            entity_type="web_search_run",
            entity_id=saved.get("id") or "",
            conversation_id=context.get("conversation_id") or "",
            customer_key="",
            occurred_at=datetime.now(timezone.utc).isoformat(),
            payload_json={
                "search_type": search_type,
                "provider_code": provider_code,
                "result_count": saved.get("result_count"),
                "blocked_count": saved.get("blocked_count"),
                "approval_required": True,
            },
            correlation_id="",
            replay_key=f"web-image-search:{saved.get('id')}",
        )

    return {"ok": True, "tenant_id": ctx.tenant_id, "access": access, "run": saved}


@router.get("/search/runs")
def list_web_image_search_runs(
    conversation_id: str = Query("", max_length=80),
    limit: int = Query(10, ge=1, le=30),
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor", "agent")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_web_image_search_tables(conn)
        _resolve_any_search_access(conn, ctx.tenant_id)
        if conversation_id:
            _validate_search_context(conn, ctx.tenant_id, conversation_id, "")
        runs = _load_search_runs(conn, ctx.tenant_id, conversation_id, limit)
    return {"ok": True, "tenant_id": ctx.tenant_id, "runs": runs}


@router.post("/search/results/{result_id}/approval")
def review_web_image_search_result(
    result_id: str,
    payload: WebImageSearchApprovalIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor", "agent")),
):
    status = _clean(payload.approval_status, 20).lower()
    if status not in SEARCH_APPROVAL_STATUSES:
        raise HTTPException(status_code=400, detail={"code": "invalid_approval_status", "allowed": sorted(SEARCH_APPROVAL_STATUSES)})
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_web_image_search_tables(conn)
        _resolve_any_search_access(conn, ctx.tenant_id)
        existing = conn.execute(
            text(
                """
                SELECT r.id::text, r.run_id::text, r.safety_status, r.approval_status, run.conversation_id::text
                FROM saas_web_search_intelligence_results r
                JOIN saas_web_search_intelligence_runs run ON run.id = r.run_id AND run.tenant_id = r.tenant_id
                WHERE r.tenant_id = CAST(:tenant_id AS uuid)
                  AND r.id = CAST(:result_id AS uuid)
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id, "result_id": result_id},
        ).mappings().first()
        if not existing:
            raise HTTPException(status_code=404, detail="search_result_not_found")
        if status == "approved" and str(existing.get("safety_status") or "") == "blocked":
            raise HTTPException(status_code=400, detail={"code": "blocked_source_cannot_be_approved"})
        row = conn.execute(
            text(
                """
                UPDATE saas_web_search_intelligence_results
                SET approval_status = :approval_status,
                    approved_by_user_id = CASE WHEN :approval_status = 'approved' THEN CAST(:user_id AS uuid) ELSE NULL END,
                    approved_at = CASE WHEN :approval_status = 'approved' THEN NOW() ELSE NULL END,
                    rejected_reason = CASE WHEN :approval_status = 'rejected' THEN :reason ELSE '' END,
                    updated_at = NOW()
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:result_id AS uuid)
                RETURNING id::text, tenant_id::text, run_id::text, result_type, title, url,
                          display_url, snippet, source_name, image_url, thumbnail_url,
                          license_label, license_details_url, width, height, rank,
                          safety_status, approval_status,
                          COALESCE(approved_by_user_id::text, '') AS approved_by_user_id,
                          COALESCE(approved_at::text, '') AS approved_at,
                          rejected_reason, metadata_json, created_at::text, updated_at::text
                """
            ),
            {
                "tenant_id": ctx.tenant_id,
                "result_id": result_id,
                "user_id": ctx.user_id,
                "approval_status": status,
                "reason": _clean(payload.reason, 500),
            },
        ).mappings().first()
        conn.execute(
            text(
                """
                UPDATE saas_web_search_intelligence_runs r
                SET approved_count = counts.approved_count,
                    blocked_count = counts.blocked_count,
                    updated_at = NOW()
                FROM (
                    SELECT
                        COUNT(*) FILTER (WHERE approval_status = 'approved')::int AS approved_count,
                        COUNT(*) FILTER (WHERE safety_status = 'blocked')::int AS blocked_count
                    FROM saas_web_search_intelligence_results
                    WHERE run_id = CAST(:run_id AS uuid)
                ) counts
                WHERE r.tenant_id = CAST(:tenant_id AS uuid)
                  AND r.id = CAST(:run_id AS uuid)
                """
            ),
            {"tenant_id": ctx.tenant_id, "run_id": str(existing["run_id"])},
        )
        record_inline_event(
            conn,
            ctx.tenant_id,
            event_type="external_search.result_reviewed",
            source="web_image_search",
            channel="web",
            entity_type="web_search_result",
            entity_id=result_id,
            conversation_id=str(existing.get("conversation_id") or ""),
            customer_key="",
            occurred_at=datetime.now(timezone.utc).isoformat(),
            payload_json={"approval_status": status, "safety_status": row.get("safety_status"), "run_id": str(existing["run_id"])},
            correlation_id="",
            replay_key=f"web-image-search-review:{result_id}:{status}:{row.get('updated_at')}",
        )
        if status == "approved":
            _try_sync_multimodal_memory(
                conn,
                ctx.tenant_id,
                ctx.user_id,
                {
                    "conversation_id": str(existing.get("conversation_id") or ""),
                    "include_voice": False,
                    "include_vision": False,
                    "include_search": True,
                    "include_agent_runs": False,
                    "limit": 12,
                },
            )
    return {"ok": True, "tenant_id": ctx.tenant_id, "result": _search_result_row(row)}


@router.post("/search/results/{result_id}/reference")
def prepare_web_image_search_reference(
    result_id: str,
    payload: WebImageSearchReferenceIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor", "agent")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_web_image_search_tables(conn)
        access = _resolve_any_search_access(conn, ctx.tenant_id)
        row = conn.execute(
            text(
                """
                SELECT r.id::text, r.tenant_id::text, r.run_id::text, r.result_type, r.title, r.url,
                       r.display_url, r.snippet, r.source_name, r.image_url, r.thumbnail_url,
                       r.license_label, r.license_details_url, r.width, r.height, r.rank,
                       r.safety_status, r.approval_status,
                       COALESCE(r.approved_by_user_id::text, '') AS approved_by_user_id,
                       COALESCE(r.approved_at::text, '') AS approved_at,
                       r.rejected_reason, r.metadata_json, r.created_at::text, r.updated_at::text,
                       COALESCE(run.conversation_id::text, '') AS run_conversation_id,
                       run.query, run.search_type, run.provider_code
                FROM saas_web_search_intelligence_results r
                JOIN saas_web_search_intelligence_runs run ON run.id = r.run_id AND run.tenant_id = r.tenant_id
                WHERE r.tenant_id = CAST(:tenant_id AS uuid)
                  AND r.id = CAST(:result_id AS uuid)
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id, "result_id": result_id},
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="search_result_not_found")
        result = _search_result_row(row)
        if str(result.get("safety_status") or "") == "blocked":
            raise HTTPException(status_code=400, detail={"code": "blocked_source_cannot_be_used"})
        if str(result.get("approval_status") or "") != "approved":
            raise HTTPException(status_code=400, detail={"code": "search_result_requires_human_approval"})
        conversation_id = _clean(payload.conversation_id or result.get("run_conversation_id"), 80)
        run_conversation_id = _clean(result.get("run_conversation_id"), 80)
        if conversation_id:
            _validate_search_context(conn, ctx.tenant_id, conversation_id, "")
        if run_conversation_id and conversation_id and run_conversation_id != conversation_id:
            raise HTTPException(status_code=400, detail={"code": "search_reference_conversation_mismatch"})
        reference = _build_search_reference_message(result, payload)
        record_inline_event(
            conn,
            ctx.tenant_id,
            event_type="external_search.reference_prepared",
            source="web_image_search",
            channel="web",
            entity_type="web_search_result",
            entity_id=result_id,
            conversation_id=conversation_id,
            customer_key="",
            occurred_at=datetime.now(timezone.utc).isoformat(),
            payload_json={
                "result_id": result_id,
                "run_id": result.get("run_id"),
                "query": result.get("query"),
                "result_type": result.get("result_type"),
                "has_visual_reference": reference["has_visual_reference"],
                "access_mode": access.get("mode"),
                "human_send_required": True,
            },
            correlation_id="",
            replay_key=f"web-image-search-reference:{result_id}:{datetime.now(timezone.utc).isoformat()}",
        )
    return {
        "ok": True,
        "tenant_id": ctx.tenant_id,
        "result": result,
        "reference": {
            **reference,
            "conversation_id": conversation_id,
            "search_result_id": result_id,
            "approval_status": result.get("approval_status"),
            "safety_status": result.get("safety_status"),
            "can_send": True,
            "auto_sent": False,
        },
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
