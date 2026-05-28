from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app_saas.agents.service import _ensure_governance_tables, create_collective_memory, get_agent
from app_saas.intelligence.service import ensure_intelligence_tables, record_event, record_intelligence_usage, resolve_intelligence_access
from app_saas.knowledge.router import _insert_source, ensure_knowledge_tables


MEMORY_FEATURE_KEYS = ("multimodal_memory_events", "multimodal_agent_memory", "ai_premium")
TRAINING_FEATURE_KEYS = ("multimodal_training_events", "ml_predictions", "ai_premium")
RAG_FEATURE_KEYS = ("multimodal_rag_materialization", "external_source_assist", "ai_premium")


def _clean(value: Any, limit: int = 4000) -> str:
    return str(value or "").strip()[:limit]


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def _safe_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _safe_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _uuid_or_400(value: str, detail: str = "invalid_uuid") -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=detail)


def _hash_text(value: str) -> str:
    return hashlib.sha256(_clean(value, 50000).encode("utf-8", errors="ignore")).hexdigest()


def _table_exists(conn: Connection, table_name: str) -> bool:
    return bool(conn.execute(text("SELECT to_regclass(:table_name) IS NOT NULL"), {"table_name": table_name}).scalar())


def _table_has_columns(conn: Connection, table_name: str, required_columns: tuple[str, ...]) -> bool:
    if not required_columns:
        return True
    rows = conn.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = :table_name
            """
        ),
        {"table_name": table_name},
    ).scalars().all()
    return set(rows) >= set(required_columns)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _sentiment_score(sentiment: Any, explicit: Any = None) -> float:
    if explicit is not None:
        return max(-1.0, min(1.0, _to_float(explicit)))
    clean = _clean(sentiment, 40).lower()
    if clean in {"positive", "positivo", "happy", "satisfied"}:
        return 0.75
    if clean in {"negative", "negativo", "angry", "frustrated"}:
        return -0.75
    return 0.0


def _urgency_score(value: Any) -> float:
    clean = _clean(value, 40).lower()
    return {"critical": 1.0, "high": 0.8, "medium": 0.45, "low": 0.15}.get(clean, 0.0)


def _feature_access(conn: Connection, tenant_id: str, keys: tuple[str, ...]) -> dict[str, Any]:
    last_detail: Any = None
    for key in keys:
        try:
            access = dict(resolve_intelligence_access(conn, tenant_id, key, allow_demo=True))
            access["resolved_feature_key"] = key
            return access
        except HTTPException as exc:
            last_detail = exc.detail
    raise HTTPException(status_code=403, detail={"code": "multimodal_memory_feature_not_enabled", "features": list(keys), "last_error": last_detail})


def ensure_multimodal_memory_tables(conn: Connection) -> None:
    ensure_intelligence_tables(conn)
    ensure_knowledge_tables(conn)
    _ensure_governance_tables(conn)
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_multimodal_memory_events (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                conversation_id UUID NULL REFERENCES saas_conversations(id) ON DELETE SET NULL,
                message_id UUID NULL REFERENCES saas_messages(id) ON DELETE SET NULL,
                agent_id UUID NULL REFERENCES saas_ai_agents(id) ON DELETE SET NULL,
                source_kind TEXT NOT NULL DEFAULT '',
                source_id TEXT NOT NULL DEFAULT '',
                event_type TEXT NOT NULL DEFAULT '',
                channel TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'ready',
                privacy_level TEXT NOT NULL DEFAULT 'tenant_private',
                approval_status TEXT NOT NULL DEFAULT 'not_required',
                eligible_for_training BOOLEAN NOT NULL DEFAULT TRUE,
                eligible_for_rag BOOLEAN NOT NULL DEFAULT FALSE,
                eligible_for_agent_memory BOOLEAN NOT NULL DEFAULT TRUE,
                memory_text TEXT NOT NULL DEFAULT '',
                rag_text TEXT NOT NULL DEFAULT '',
                training_features_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                training_labels_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                source_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                safety_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                intelligence_event_id UUID NULL REFERENCES saas_intelligence_events(id) ON DELETE SET NULL,
                knowledge_source_id UUID NULL REFERENCES saas_knowledge_sources(id) ON DELETE SET NULL,
                collective_memory_id UUID NULL REFERENCES saas_ai_agent_collective_memory(id) ON DELETE SET NULL,
                created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                materialized_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                materialized_at TIMESTAMP NULL,
                replay_key TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            """
            ALTER TABLE saas_multimodal_memory_events
              ADD COLUMN IF NOT EXISTS tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
              ADD COLUMN IF NOT EXISTS conversation_id UUID NULL REFERENCES saas_conversations(id) ON DELETE SET NULL,
              ADD COLUMN IF NOT EXISTS message_id UUID NULL REFERENCES saas_messages(id) ON DELETE SET NULL,
              ADD COLUMN IF NOT EXISTS agent_id UUID NULL REFERENCES saas_ai_agents(id) ON DELETE SET NULL,
              ADD COLUMN IF NOT EXISTS source_kind TEXT NOT NULL DEFAULT '',
              ADD COLUMN IF NOT EXISTS source_id TEXT NOT NULL DEFAULT '',
              ADD COLUMN IF NOT EXISTS event_type TEXT NOT NULL DEFAULT '',
              ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT '',
              ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'ready',
              ADD COLUMN IF NOT EXISTS privacy_level TEXT NOT NULL DEFAULT 'tenant_private',
              ADD COLUMN IF NOT EXISTS approval_status TEXT NOT NULL DEFAULT 'not_required',
              ADD COLUMN IF NOT EXISTS eligible_for_training BOOLEAN NOT NULL DEFAULT TRUE,
              ADD COLUMN IF NOT EXISTS eligible_for_rag BOOLEAN NOT NULL DEFAULT FALSE,
              ADD COLUMN IF NOT EXISTS eligible_for_agent_memory BOOLEAN NOT NULL DEFAULT TRUE,
              ADD COLUMN IF NOT EXISTS memory_text TEXT NOT NULL DEFAULT '',
              ADD COLUMN IF NOT EXISTS rag_text TEXT NOT NULL DEFAULT '',
              ADD COLUMN IF NOT EXISTS training_features_json JSONB NOT NULL DEFAULT '{}'::jsonb,
              ADD COLUMN IF NOT EXISTS training_labels_json JSONB NOT NULL DEFAULT '{}'::jsonb,
              ADD COLUMN IF NOT EXISTS source_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
              ADD COLUMN IF NOT EXISTS safety_json JSONB NOT NULL DEFAULT '{}'::jsonb,
              ADD COLUMN IF NOT EXISTS intelligence_event_id UUID NULL REFERENCES saas_intelligence_events(id) ON DELETE SET NULL,
              ADD COLUMN IF NOT EXISTS knowledge_source_id UUID NULL REFERENCES saas_knowledge_sources(id) ON DELETE SET NULL,
              ADD COLUMN IF NOT EXISTS collective_memory_id UUID NULL REFERENCES saas_ai_agent_collective_memory(id) ON DELETE SET NULL,
              ADD COLUMN IF NOT EXISTS created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
              ADD COLUMN IF NOT EXISTS materialized_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
              ADD COLUMN IF NOT EXISTS materialized_at TIMESTAMP NULL,
              ADD COLUMN IF NOT EXISTS replay_key TEXT NOT NULL DEFAULT '',
              ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT NOW(),
              ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            """
        )
    )
    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_saas_multimodal_memory_events_replay ON saas_multimodal_memory_events (tenant_id, replay_key) WHERE replay_key <> ''"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_multimodal_memory_events_tenant_created ON saas_multimodal_memory_events (tenant_id, created_at DESC)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_multimodal_memory_events_conversation ON saas_multimodal_memory_events (tenant_id, conversation_id, updated_at DESC) WHERE conversation_id IS NOT NULL"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_multimodal_memory_events_agent ON saas_multimodal_memory_events (tenant_id, agent_id, updated_at DESC) WHERE agent_id IS NOT NULL"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_multimodal_memory_events_training ON saas_multimodal_memory_events (tenant_id, eligible_for_training, event_type, updated_at DESC)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_multimodal_memory_events_rag ON saas_multimodal_memory_events (tenant_id, eligible_for_rag, approval_status, updated_at DESC)"))


def _row(row: Any) -> dict[str, Any]:
    data = dict(row or {})
    for key in ("training_features_json", "training_labels_json", "source_payload_json", "safety_json"):
        data[key] = _safe_dict(data.get(key))
    for key in ("eligible_for_training", "eligible_for_rag", "eligible_for_agent_memory"):
        data[key] = bool(data.get(key))
    return data


def _conversation_filters(prefix: str, payload: dict[str, Any], params: dict[str, Any]) -> list[str]:
    filters: list[str] = []
    conversation_id = _clean(payload.get("conversation_id"), 80)
    message_id = _clean(payload.get("message_id"), 80)
    if conversation_id:
        filters.append(f"{prefix}.conversation_id = CAST(:conversation_id AS uuid)")
        params["conversation_id"] = _uuid_or_400(conversation_id, "invalid_conversation_id")
    if message_id:
        filters.append(f"{prefix}.message_id = CAST(:message_id AS uuid)")
        params["message_id"] = _uuid_or_400(message_id, "invalid_message_id")
    return filters


def _voice_candidates(conn: Connection, tenant_id: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not _table_exists(conn, "saas_voice_intelligence_analyses"):
        return []
    params: dict[str, Any] = {"tenant_id": tenant_id, "limit": payload["limit"], "lookback_days": payload["lookback_days"]}
    filters = ["v.tenant_id = CAST(:tenant_id AS uuid)", "v.updated_at >= NOW() - (:lookback_days * INTERVAL '1 day')"]
    filters.extend(_conversation_filters("v", payload, params))
    rows = conn.execute(
        text(
            f"""
            SELECT v.id::text, v.conversation_id::text, v.message_id::text,
                   COALESCE(c.channel, '') AS channel, v.summary, v.transcript,
                   v.sentiment, v.sentiment_score, v.intent, v.intent_label, v.urgency,
                   v.language, v.confidence, v.provider_code, v.model, v.updated_at::text
            FROM saas_voice_intelligence_analyses v
            LEFT JOIN saas_conversations c ON c.id = v.conversation_id AND c.tenant_id = v.tenant_id
            WHERE {" AND ".join(filters)}
            ORDER BY v.updated_at DESC
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()
    items: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        summary = _clean(data.get("summary"), 1600)
        transcript = _clean(data.get("transcript"), 5000)
        memory_text = _clean(
            f"Audio analizado. Resumen: {summary}\n"
            f"Sentimiento: {_clean(data.get('sentiment'), 40)}. Intencion: {_clean(data.get('intent_label') or data.get('intent'), 120)}. "
            f"Urgencia: {_clean(data.get('urgency'), 40)}.\n"
            f"Transcripcion util: {transcript}",
            7000,
        )
        items.append(
            {
                "source_kind": "voice_analysis",
                "source_id": data["id"],
                "event_type": "multimodal.voice.analysis_ready",
                "conversation_id": data.get("conversation_id") or "",
                "message_id": data.get("message_id") or "",
                "agent_id": "",
                "channel": data.get("channel") or "",
                "approval_status": "not_required",
                "privacy_level": "tenant_private",
                "eligible_for_training": True,
                "eligible_for_rag": False,
                "eligible_for_agent_memory": True,
                "memory_text": memory_text,
                "rag_text": _clean(f"{summary}\n\nTranscripcion:\n{transcript}", 12000),
                "training_features_json": {
                    "source_kind": "voice_analysis",
                    "confidence": _to_float(data.get("confidence")),
                    "sentiment_score": _sentiment_score(data.get("sentiment"), data.get("sentiment_score")),
                    "urgency_score": _urgency_score(data.get("urgency")),
                    "text_chars": len(transcript),
                    "has_transcript": bool(transcript),
                },
                "training_labels_json": {
                    "candidate_intent": _clean(data.get("intent"), 80),
                    "candidate_sentiment": _clean(data.get("sentiment"), 40),
                    "candidate_urgency": _clean(data.get("urgency"), 40),
                    "label_policy": "advisory_multimodal_signal_not_outcome_label",
                },
                "source_payload_json": {
                    "provider_code": _clean(data.get("provider_code"), 80),
                    "model": _clean(data.get("model"), 240),
                    "summary_hash": _hash_text(summary),
                    "transcript_chars": len(transcript),
                },
                "safety_json": {
                    "raw_media_stored": False,
                    "base64_stored": False,
                    "contains_customer_content": True,
                    "rag_materialization_requires_allow_customer_content": True,
                },
            }
        )
    return items


def _vision_candidates(conn: Connection, tenant_id: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not _table_exists(conn, "saas_vision_intelligence_analyses"):
        return []
    params: dict[str, Any] = {"tenant_id": tenant_id, "limit": payload["limit"], "lookback_days": payload["lookback_days"]}
    filters = ["v.tenant_id = CAST(:tenant_id AS uuid)", "v.updated_at >= NOW() - (:lookback_days * INTERVAL '1 day')"]
    filters.extend(_conversation_filters("v", payload, params))
    rows = conn.execute(
        text(
            f"""
            SELECT v.id::text, v.conversation_id::text, v.message_id::text,
                   COALESCE(c.channel, '') AS channel, v.media_kind, v.visual_description,
                   v.extracted_text, v.summary, v.document_type, v.sentiment, v.sentiment_score,
                   v.intent, v.intent_label, v.urgency, v.language, v.confidence,
                   v.provider_code, v.model, v.topics_json, v.product_hints_json, v.updated_at::text
            FROM saas_vision_intelligence_analyses v
            LEFT JOIN saas_conversations c ON c.id = v.conversation_id AND c.tenant_id = v.tenant_id
            WHERE {" AND ".join(filters)}
            ORDER BY v.updated_at DESC
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()
    items: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        summary = _clean(data.get("summary"), 1600)
        visual = _clean(data.get("visual_description"), 3000)
        extracted = _clean(data.get("extracted_text"), 7000)
        memory_text = _clean(
            f"Imagen/documento analizado. Resumen: {summary}\n"
            f"Tipo: {_clean(data.get('document_type'), 80)}. Intencion: {_clean(data.get('intent_label') or data.get('intent'), 120)}. "
            f"Urgencia: {_clean(data.get('urgency'), 40)}.\n"
            f"Descripcion: {visual}\nTexto extraido util: {extracted}",
            9000,
        )
        items.append(
            {
                "source_kind": "vision_analysis",
                "source_id": data["id"],
                "event_type": "multimodal.vision.analysis_ready",
                "conversation_id": data.get("conversation_id") or "",
                "message_id": data.get("message_id") or "",
                "agent_id": "",
                "channel": data.get("channel") or "",
                "approval_status": "not_required",
                "privacy_level": "tenant_private",
                "eligible_for_training": True,
                "eligible_for_rag": False,
                "eligible_for_agent_memory": True,
                "memory_text": memory_text,
                "rag_text": _clean(f"{summary}\n\nDescripcion visual:\n{visual}\n\nTexto extraido:\n{extracted}", 14000),
                "training_features_json": {
                    "source_kind": "vision_analysis",
                    "confidence": _to_float(data.get("confidence")),
                    "sentiment_score": _sentiment_score(data.get("sentiment"), data.get("sentiment_score")),
                    "urgency_score": _urgency_score(data.get("urgency")),
                    "text_chars": len(extracted),
                    "visual_chars": len(visual),
                    "document_type": _clean(data.get("document_type"), 80),
                },
                "training_labels_json": {
                    "candidate_intent": _clean(data.get("intent"), 80),
                    "candidate_sentiment": _clean(data.get("sentiment"), 40),
                    "candidate_urgency": _clean(data.get("urgency"), 40),
                    "label_policy": "advisory_multimodal_signal_not_outcome_label",
                },
                "source_payload_json": {
                    "provider_code": _clean(data.get("provider_code"), 80),
                    "model": _clean(data.get("model"), 240),
                    "media_kind": _clean(data.get("media_kind"), 40),
                    "topics": _safe_list(data.get("topics_json"))[:12],
                    "product_hints": _safe_dict(data.get("product_hints_json")),
                    "content_hash": _hash_text(f"{summary}\n{visual}\n{extracted}"),
                },
                "safety_json": {
                    "raw_media_stored": False,
                    "base64_stored": False,
                    "contains_customer_content": True,
                    "rag_materialization_requires_allow_customer_content": True,
                },
            }
        )
    return items


def _search_candidates(conn: Connection, tenant_id: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not _table_exists(conn, "saas_web_search_intelligence_results"):
        return []
    params: dict[str, Any] = {"tenant_id": tenant_id, "limit": payload["limit"], "lookback_days": payload["lookback_days"]}
    filters = [
        "r.tenant_id = CAST(:tenant_id AS uuid)",
        "r.updated_at >= NOW() - (:lookback_days * INTERVAL '1 day')",
        "r.approval_status = 'approved'",
        "r.safety_status <> 'blocked'",
    ]
    conversation_id = _clean(payload.get("conversation_id"), 80)
    message_id = _clean(payload.get("message_id"), 80)
    if conversation_id:
        filters.append("run.conversation_id = CAST(:conversation_id AS uuid)")
        params["conversation_id"] = _uuid_or_400(conversation_id, "invalid_conversation_id")
    if message_id:
        filters.append("run.message_id = CAST(:message_id AS uuid)")
        params["message_id"] = _uuid_or_400(message_id, "invalid_message_id")
    rows = conn.execute(
        text(
            f"""
            SELECT r.id::text, r.run_id::text, run.conversation_id::text, run.message_id::text,
                   COALESCE(c.channel, 'web') AS channel, run.query, run.provider_code,
                   r.result_type, r.title, r.url, r.display_url, r.snippet, r.source_name,
                   r.image_url, r.thumbnail_url, r.license_label, r.rank, r.safety_status,
                   r.approval_status, r.updated_at::text
            FROM saas_web_search_intelligence_results r
            JOIN saas_web_search_intelligence_runs run ON run.id = r.run_id AND run.tenant_id = r.tenant_id
            LEFT JOIN saas_conversations c ON c.id = run.conversation_id AND c.tenant_id = run.tenant_id
            WHERE {" AND ".join(filters)}
            ORDER BY r.updated_at DESC, r.rank ASC
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()
    items: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        title = _clean(data.get("title"), 240)
        snippet = _clean(data.get("snippet"), 1400)
        url = _clean(data.get("url"), 1000)
        memory_text = _clean(
            f"Fuente externa aprobada para apoyo del agente.\nTitulo: {title}\nFuente: {_clean(data.get('source_name'), 160)}\nURL: {url}\nResumen: {snippet}",
            5000,
        )
        items.append(
            {
                "source_kind": "web_search_result",
                "source_id": data["id"],
                "event_type": "multimodal.external_source.approved",
                "conversation_id": data.get("conversation_id") or "",
                "message_id": data.get("message_id") or "",
                "agent_id": "",
                "channel": data.get("channel") or "web",
                "approval_status": "approved",
                "privacy_level": "external_approved",
                "eligible_for_training": True,
                "eligible_for_rag": True,
                "eligible_for_agent_memory": True,
                "memory_text": memory_text,
                "rag_text": memory_text,
                "training_features_json": {
                    "source_kind": "web_search_result",
                    "approved_source": True,
                    "rank": int(data.get("rank") or 0),
                    "has_image": bool(data.get("image_url") or data.get("thumbnail_url")),
                    "text_chars": len(snippet),
                },
                "training_labels_json": {
                    "source_approved": True,
                    "source_type": _clean(data.get("result_type"), 20),
                    "label_policy": "human_approved_external_source",
                },
                "source_payload_json": {
                    "run_id": _clean(data.get("run_id"), 80),
                    "query": _clean(data.get("query"), 280),
                    "provider_code": _clean(data.get("provider_code"), 80),
                    "result_type": _clean(data.get("result_type"), 20),
                    "url": url,
                    "image_url_present": bool(data.get("image_url")),
                    "thumbnail_url_present": bool(data.get("thumbnail_url")),
                    "license_label": _clean(data.get("license_label"), 160),
                },
                "safety_json": {
                    "approved_by_human": True,
                    "blocked_source": False,
                    "raw_media_stored": False,
                    "customer_content": False,
                    "copyright_review_required_before_customer_send": True,
                },
            }
        )
    return items


def _tool_run_candidates(conn: Connection, tenant_id: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not _table_exists(conn, "saas_ai_agent_tool_runs"):
        return []
    params: dict[str, Any] = {"tenant_id": tenant_id, "limit": payload["limit"], "lookback_days": payload["lookback_days"]}
    filters = [
        "r.tenant_id = CAST(:tenant_id AS uuid)",
        "r.status = 'completed'",
        "r.tool_code IN ('media.voice_analyze', 'media.vision_analyze', 'media.web_image_search')",
        "r.updated_at >= NOW() - (:lookback_days * INTERVAL '1 day')",
    ]
    agent_id = _clean(payload.get("agent_id"), 80)
    conversation_id = _clean(payload.get("conversation_id"), 80)
    message_id = _clean(payload.get("message_id"), 80)
    if agent_id:
        filters.append("r.agent_id = CAST(:agent_id AS uuid)")
        params["agent_id"] = _uuid_or_400(agent_id, "invalid_agent_id")
    if conversation_id:
        filters.append("(r.input_json->>'conversation_id' = :conversation_id OR r.output_json->>'conversation_id' = :conversation_id)")
        params["conversation_id"] = _uuid_or_400(conversation_id, "invalid_conversation_id")
    if message_id:
        filters.append("(r.input_json->>'message_id' = :message_id OR r.output_json->>'message_id' = :message_id)")
        params["message_id"] = _uuid_or_400(message_id, "invalid_message_id")
    rows = conn.execute(
        text(
            f"""
            SELECT r.id::text, r.agent_id::text, r.tool_code, r.input_json, r.output_json,
                   r.approval_status, r.updated_at::text, a.agent_type, a.name AS agent_name
            FROM saas_ai_agent_tool_runs r
            LEFT JOIN saas_ai_agents a ON a.id = r.agent_id AND a.tenant_id = r.tenant_id
            WHERE {" AND ".join(filters)}
            ORDER BY r.updated_at DESC
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()
    items: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        output = _safe_dict(data.get("output_json"))
        input_json = _safe_dict(data.get("input_json"))
        tool_code = _clean(data.get("tool_code"), 120)
        conversation_id = _clean(output.get("conversation_id") or input_json.get("conversation_id"), 80)
        message_id = _clean(output.get("message_id") or input_json.get("message_id"), 80)
        summary_parts = [
            _clean(output.get("summary"), 1200),
            _clean(output.get("visual_description"), 1200),
            _clean(output.get("recommended_action"), 600),
            _clean(output.get("query"), 280),
        ]
        memory_text = _clean(
            f"Herramienta multimodal ejecutada por agente {_clean(data.get('agent_name'), 160) or _clean(data.get('agent_type'), 80)}.\n"
            f"Tool: {tool_code}.\nResultado: {' | '.join(part for part in summary_parts if part)}",
            5000,
        )
        items.append(
            {
                "source_kind": "agent_tool_run",
                "source_id": data["id"],
                "event_type": "multimodal.agent_tool.completed",
                "conversation_id": conversation_id,
                "message_id": message_id,
                "agent_id": _clean(data.get("agent_id"), 80),
                "channel": "",
                "approval_status": _clean(data.get("approval_status"), 40) or "not_required",
                "privacy_level": "tenant_private",
                "eligible_for_training": True,
                "eligible_for_rag": False,
                "eligible_for_agent_memory": True,
                "memory_text": memory_text,
                "rag_text": "",
                "training_features_json": {
                    "source_kind": "agent_tool_run",
                    "tool_code": tool_code,
                    "confidence": _to_float(output.get("confidence")),
                    "sentiment_score": _sentiment_score(output.get("sentiment")),
                    "urgency_score": _urgency_score(output.get("urgency")),
                    "result_count": int(output.get("result_count") or 0),
                    "approved_count": int(output.get("approved_count") or 0),
                },
                "training_labels_json": {
                    "tool_code": tool_code,
                    "tool_completed": True,
                    "label_policy": "agent_tool_trace",
                },
                "source_payload_json": {
                    "agent_type": _clean(data.get("agent_type"), 80),
                    "agent_name": _clean(data.get("agent_name"), 160),
                    "tool_code": tool_code,
                    "output_state": _clean(output.get("state"), 40),
                    "search_run_id": _clean(output.get("search_run_id"), 80),
                },
                "safety_json": {
                    "raw_media_stored": False,
                    "base64_stored": False,
                    "customer_send_executed": False,
                    "crm_mutation_executed": False,
                },
            }
        )
    return items


def _upsert_feature_value(
    conn: Connection,
    tenant_id: str,
    *,
    subject_type: str,
    subject_id: str,
    feature_key: str,
    value_numeric: float,
    value_json: dict[str, Any],
    source: str = "multimodal_memory_events",
) -> None:
    if not subject_id:
        return
    conn.execute(
        text(
            """
            INSERT INTO saas_intelligence_feature_values (
                tenant_id, subject_type, subject_id, feature_key, window_key,
                value_numeric, value_text, value_json, source, feature_set_key,
                feature_version, quality_json, updated_at, computed_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), :subject_type, :subject_id, :feature_key, 'latest',
                :value_numeric, '', CAST(:value_json AS jsonb), :source,
                'multimodal_features_v1', 'v1',
                CAST(:quality_json AS jsonb), NOW(), NOW()
            )
            ON CONFLICT (tenant_id, subject_type, subject_id, feature_key, window_key)
            DO UPDATE SET
                value_numeric = EXCLUDED.value_numeric,
                value_json = EXCLUDED.value_json,
                source = EXCLUDED.source,
                feature_set_key = EXCLUDED.feature_set_key,
                feature_version = EXCLUDED.feature_version,
                quality_json = EXCLUDED.quality_json,
                computed_at = NOW(),
                updated_at = NOW()
            """
        ),
        {
            "tenant_id": tenant_id,
            "subject_type": _clean(subject_type, 80),
            "subject_id": _clean(subject_id, 160),
            "feature_key": _clean(feature_key, 120),
            "value_numeric": float(value_numeric or 0),
            "value_json": _json(value_json),
            "source": _clean(source, 80),
            "quality_json": _json({"raw_media_used": False, "source": source}),
        },
    )


def _refresh_conversation_multimodal_features(conn: Connection, tenant_id: str, conversation_id: str) -> None:
    if not conversation_id:
        return
    row = conn.execute(
        text(
            """
            SELECT COUNT(*)::int AS event_count,
                   COUNT(*) FILTER (WHERE source_kind = 'web_search_result' AND approval_status = 'approved')::int AS approved_external_sources,
                   COALESCE(AVG((training_features_json->>'confidence')::numeric), 0)::numeric(10,4) AS avg_confidence,
                   COALESCE(AVG((training_features_json->>'sentiment_score')::numeric), 0)::numeric(10,4) AS avg_sentiment_score,
                   COALESCE(MAX((training_features_json->>'urgency_score')::numeric), 0)::numeric(10,4) AS max_urgency_score,
                   COALESCE(SUM((training_features_json->>'text_chars')::numeric), 0)::numeric(18,2) AS text_chars
            FROM saas_multimodal_memory_events
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND conversation_id = CAST(:conversation_id AS uuid)
              AND status = 'ready'
            """
        ),
        {"tenant_id": tenant_id, "conversation_id": conversation_id},
    ).mappings().first() or {}
    metrics = {
        "multimodal_event_count": float(row.get("event_count") or 0),
        "approved_external_sources_count": float(row.get("approved_external_sources") or 0),
        "multimodal_avg_confidence": float(row.get("avg_confidence") or 0),
        "multimodal_sentiment_score": float(row.get("avg_sentiment_score") or 0),
        "multimodal_urgency_score": float(row.get("max_urgency_score") or 0),
        "multimodal_text_chars": float(row.get("text_chars") or 0),
    }
    for key, value in metrics.items():
        _upsert_feature_value(
            conn,
            tenant_id,
            subject_type="conversation",
            subject_id=conversation_id,
            feature_key=key,
            value_numeric=value,
            value_json={"value": value, "source": "phase24_6"},
        )


def _upsert_memory_event(conn: Connection, tenant_id: str, user_id: str, candidate: dict[str, Any]) -> dict[str, Any]:
    replay_key = f"multimodal-memory:{candidate['source_kind']}:{candidate['source_id']}"
    intelligence = record_event(
        conn,
        tenant_id,
        {
            "event_type": candidate["event_type"],
            "source": "multimodal_memory",
            "channel": candidate.get("channel") or "",
            "entity_type": candidate["source_kind"],
            "entity_id": candidate["source_id"],
            "conversation_id": candidate.get("conversation_id") or "",
            "payload_json": {
                "source_kind": candidate["source_kind"],
                "approval_status": candidate.get("approval_status") or "",
                "eligible_for_training": bool(candidate.get("eligible_for_training")),
                "eligible_for_rag": bool(candidate.get("eligible_for_rag")),
                "features": candidate.get("training_features_json") or {},
                "raw_media_used": False,
            },
            "replay_key": replay_key,
        },
    )
    row = conn.execute(
        text(
            """
            INSERT INTO saas_multimodal_memory_events (
                tenant_id, conversation_id, message_id, agent_id, source_kind, source_id,
                event_type, channel, status, privacy_level, approval_status,
                eligible_for_training, eligible_for_rag, eligible_for_agent_memory,
                memory_text, rag_text, training_features_json, training_labels_json,
                source_payload_json, safety_json, intelligence_event_id, created_by_user_id,
                replay_key, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), CAST(NULLIF(:conversation_id, '') AS uuid),
                CAST(NULLIF(:message_id, '') AS uuid), CAST(NULLIF(:agent_id, '') AS uuid),
                :source_kind, :source_id, :event_type, :channel, 'ready',
                :privacy_level, :approval_status, :eligible_for_training, :eligible_for_rag,
                :eligible_for_agent_memory, :memory_text, :rag_text,
                CAST(:training_features_json AS jsonb), CAST(:training_labels_json AS jsonb),
                CAST(:source_payload_json AS jsonb), CAST(:safety_json AS jsonb),
                CAST(NULLIF(:intelligence_event_id, '') AS uuid),
                CAST(NULLIF(:created_by_user_id, '') AS uuid), :replay_key, NOW()
            )
            ON CONFLICT (tenant_id, replay_key) WHERE replay_key <> ''
            DO UPDATE SET
                conversation_id = EXCLUDED.conversation_id,
                message_id = EXCLUDED.message_id,
                agent_id = COALESCE(EXCLUDED.agent_id, saas_multimodal_memory_events.agent_id),
                event_type = EXCLUDED.event_type,
                channel = EXCLUDED.channel,
                status = EXCLUDED.status,
                privacy_level = EXCLUDED.privacy_level,
                approval_status = EXCLUDED.approval_status,
                eligible_for_training = EXCLUDED.eligible_for_training,
                eligible_for_rag = EXCLUDED.eligible_for_rag,
                eligible_for_agent_memory = EXCLUDED.eligible_for_agent_memory,
                memory_text = EXCLUDED.memory_text,
                rag_text = EXCLUDED.rag_text,
                training_features_json = EXCLUDED.training_features_json,
                training_labels_json = EXCLUDED.training_labels_json,
                source_payload_json = EXCLUDED.source_payload_json,
                safety_json = EXCLUDED.safety_json,
                intelligence_event_id = COALESCE(EXCLUDED.intelligence_event_id, saas_multimodal_memory_events.intelligence_event_id),
                updated_at = NOW()
            RETURNING id::text, tenant_id::text, COALESCE(conversation_id::text, '') AS conversation_id,
                      COALESCE(message_id::text, '') AS message_id, COALESCE(agent_id::text, '') AS agent_id,
                      source_kind, source_id, event_type, channel, status, privacy_level, approval_status,
                      eligible_for_training, eligible_for_rag, eligible_for_agent_memory,
                      memory_text, rag_text, training_features_json, training_labels_json,
                      source_payload_json, safety_json, COALESCE(intelligence_event_id::text, '') AS intelligence_event_id,
                      COALESCE(knowledge_source_id::text, '') AS knowledge_source_id,
                      COALESCE(collective_memory_id::text, '') AS collective_memory_id,
                      COALESCE(created_by_user_id::text, '') AS created_by_user_id,
                      COALESCE(materialized_by_user_id::text, '') AS materialized_by_user_id,
                      COALESCE(materialized_at::text, '') AS materialized_at,
                      replay_key, created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "conversation_id": _clean(candidate.get("conversation_id"), 80),
            "message_id": _clean(candidate.get("message_id"), 80),
            "agent_id": _clean(candidate.get("agent_id"), 80),
            "source_kind": _clean(candidate.get("source_kind"), 80),
            "source_id": _clean(candidate.get("source_id"), 160),
            "event_type": _clean(candidate.get("event_type"), 160),
            "channel": _clean(candidate.get("channel"), 80),
            "privacy_level": _clean(candidate.get("privacy_level"), 60) or "tenant_private",
            "approval_status": _clean(candidate.get("approval_status"), 60) or "not_required",
            "eligible_for_training": bool(candidate.get("eligible_for_training")),
            "eligible_for_rag": bool(candidate.get("eligible_for_rag")),
            "eligible_for_agent_memory": bool(candidate.get("eligible_for_agent_memory")),
            "memory_text": _clean(candidate.get("memory_text"), 12000),
            "rag_text": _clean(candidate.get("rag_text"), 20000),
            "training_features_json": _json(candidate.get("training_features_json") or {}),
            "training_labels_json": _json(candidate.get("training_labels_json") or {}),
            "source_payload_json": _json(candidate.get("source_payload_json") or {}),
            "safety_json": _json(candidate.get("safety_json") or {}),
            "intelligence_event_id": _clean(intelligence.get("id"), 80),
            "created_by_user_id": _clean(user_id, 80),
            "replay_key": replay_key,
        },
    ).mappings().first()
    saved = _row(row)
    if saved.get("conversation_id"):
        _refresh_conversation_multimodal_features(conn, tenant_id, saved["conversation_id"])
    return saved


def list_multimodal_memory_events(
    conn: Connection,
    tenant_id: str,
    *,
    conversation_id: str = "",
    agent_id: str = "",
    source_kind: str = "",
    limit: int = 80,
) -> list[dict[str, Any]]:
    required_columns = (
        "tenant_id",
        "conversation_id",
        "message_id",
        "agent_id",
        "source_kind",
        "source_id",
        "event_type",
        "channel",
        "status",
        "privacy_level",
        "approval_status",
        "eligible_for_training",
        "eligible_for_rag",
        "eligible_for_agent_memory",
        "memory_text",
        "rag_text",
        "training_features_json",
        "training_labels_json",
        "source_payload_json",
        "safety_json",
        "intelligence_event_id",
        "knowledge_source_id",
        "collective_memory_id",
        "created_by_user_id",
        "materialized_by_user_id",
        "materialized_at",
        "replay_key",
        "created_at",
        "updated_at",
    )
    if not _table_exists(conn, "saas_multimodal_memory_events"):
        return []
    if not _table_has_columns(conn, "saas_multimodal_memory_events", required_columns):
        return []
    where = ["e.tenant_id = CAST(:tenant_id AS uuid)"]
    params: dict[str, Any] = {"tenant_id": tenant_id, "limit": max(1, min(int(limit or 80), 200))}
    if conversation_id:
        where.append("e.conversation_id = CAST(:conversation_id AS uuid)")
        params["conversation_id"] = _uuid_or_400(conversation_id, "invalid_conversation_id")
    if agent_id:
        where.append("e.agent_id = CAST(:agent_id AS uuid)")
        params["agent_id"] = _uuid_or_400(agent_id, "invalid_agent_id")
    if source_kind:
        where.append("e.source_kind = :source_kind")
        params["source_kind"] = _clean(source_kind, 80)
    rows = conn.execute(
        text(
            f"""
            SELECT e.id::text, e.tenant_id::text, COALESCE(e.conversation_id::text, '') AS conversation_id,
                   COALESCE(e.message_id::text, '') AS message_id, COALESCE(e.agent_id::text, '') AS agent_id,
                   COALESCE(a.name, '') AS agent_name, e.source_kind, e.source_id, e.event_type,
                   e.channel, e.status, e.privacy_level, e.approval_status,
                   e.eligible_for_training, e.eligible_for_rag, e.eligible_for_agent_memory,
                   e.memory_text, e.rag_text, e.training_features_json, e.training_labels_json,
                   e.source_payload_json, e.safety_json, COALESCE(e.intelligence_event_id::text, '') AS intelligence_event_id,
                   COALESCE(e.knowledge_source_id::text, '') AS knowledge_source_id,
                   COALESCE(e.collective_memory_id::text, '') AS collective_memory_id,
                   COALESCE(e.created_by_user_id::text, '') AS created_by_user_id,
                   COALESCE(e.materialized_by_user_id::text, '') AS materialized_by_user_id,
                   COALESCE(e.materialized_at::text, '') AS materialized_at,
                   e.replay_key, e.created_at::text, e.updated_at::text
            FROM saas_multimodal_memory_events e
            LEFT JOIN saas_ai_agents a ON a.id = e.agent_id AND a.tenant_id = e.tenant_id
            WHERE {" AND ".join(where)}
            ORDER BY e.updated_at DESC
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()
    return [_row(row) for row in rows]


def sync_multimodal_memory_events(
    conn: Connection,
    tenant_id: str,
    user_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ensure_multimodal_memory_tables(conn)
    data = dict(payload or {})
    access = _feature_access(conn, tenant_id, MEMORY_FEATURE_KEYS)
    training_access: dict[str, Any] | None = None
    try:
        training_access = _feature_access(conn, tenant_id, TRAINING_FEATURE_KEYS)
    except HTTPException:
        training_access = None
    training_remaining: int | None = None
    if training_access:
        quota = int(training_access.get("quota_monthly") or 0)
        used = int(training_access.get("quota_used") or 0)
        if quota > 0:
            training_remaining = max(0, quota - used)
            if training_remaining <= 0:
                training_access = None
    record_intelligence_usage(
        conn,
        tenant_id,
        str(access.get("resolved_feature_key") or "multimodal_memory_events"),
        usage_metric="multimodal_memory_syncs",
        metadata={"source": "phase24_6", "conversation_id": _clean(data.get("conversation_id"), 80), "agent_id": _clean(data.get("agent_id"), 80)},
    )
    normalized = {
        "conversation_id": _clean(data.get("conversation_id"), 80),
        "message_id": _clean(data.get("message_id"), 80),
        "agent_id": _clean(data.get("agent_id"), 80),
        "lookback_days": max(1, min(int(data.get("lookback_days") or 30), 365)),
        "limit": max(1, min(int(data.get("limit") or 60), 200)),
        "include_voice": bool(data.get("include_voice", True)),
        "include_vision": bool(data.get("include_vision", True)),
        "include_search": bool(data.get("include_search", True)),
        "include_agent_runs": bool(data.get("include_agent_runs", True)),
    }
    if normalized["agent_id"]:
        get_agent(conn, tenant_id, normalized["agent_id"])
    candidates: list[dict[str, Any]] = []
    if normalized["include_voice"]:
        candidates.extend(_voice_candidates(conn, tenant_id, normalized))
    if normalized["include_vision"]:
        candidates.extend(_vision_candidates(conn, tenant_id, normalized))
    if normalized["include_search"]:
        candidates.extend(_search_candidates(conn, tenant_id, normalized))
    if normalized["include_agent_runs"]:
        candidates.extend(_tool_run_candidates(conn, tenant_id, normalized))
    for candidate in candidates:
        if not candidate.get("eligible_for_training"):
            continue
        if not training_access:
            candidate["eligible_for_training"] = False
            labels = _safe_dict(candidate.get("training_labels_json"))
            labels["training_gate"] = "disabled"
            candidate["training_labels_json"] = labels
            continue
        if training_remaining is not None:
            if training_remaining <= 0:
                candidate["eligible_for_training"] = False
                labels = _safe_dict(candidate.get("training_labels_json"))
                labels["training_gate"] = "quota_exhausted"
                candidate["training_labels_json"] = labels
            else:
                training_remaining -= 1
    saved: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for candidate in candidates[: normalized["limit"]]:
        item = _upsert_memory_event(conn, tenant_id, user_id, candidate)
        saved.append(item)
        counts[item["source_kind"]] = counts.get(item["source_kind"], 0) + 1
    training_ready = sum(1 for item in saved if item.get("eligible_for_training"))
    if training_access and training_ready:
        record_intelligence_usage(
            conn,
            tenant_id,
            str(training_access.get("resolved_feature_key") or "multimodal_training_events"),
            quantity=training_ready,
            usage_metric="multimodal_training_events_written",
            metadata={"source": "phase24_6", "conversation_id": normalized["conversation_id"], "agent_id": normalized["agent_id"]},
        )
    return {
        "access": access,
        "training_access": training_access or {"enabled": False, "mode": "disabled"},
        "filters": normalized,
        "candidates": len(candidates),
        "synced": len(saved),
        "training_ready": training_ready,
        "counts": counts,
        "events": saved[:50],
        "safety": {
            "raw_media_stored": False,
            "base64_stored": False,
            "auto_customer_send": False,
            "auto_model_training": False,
            "external_sources_require_approval": True,
            "training_requires_feature": True,
        },
    }


def materialize_multimodal_memory_event(
    conn: Connection,
    tenant_id: str,
    user_id: str,
    event_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ensure_multimodal_memory_tables(conn)
    data = dict(payload or {})
    destination = _clean(data.get("destination") or "knowledge", 40).lower()
    if destination not in {"knowledge", "collective_memory", "both"}:
        raise HTTPException(status_code=400, detail={"code": "invalid_materialization_destination"})
    event_uuid = _uuid_or_400(event_id, "invalid_multimodal_memory_event_id")
    event = conn.execute(
        text(
            """
            SELECT id::text, COALESCE(conversation_id::text, '') AS conversation_id,
                   COALESCE(message_id::text, '') AS message_id, COALESCE(agent_id::text, '') AS agent_id,
                   source_kind, source_id, event_type, channel, status, privacy_level, approval_status,
                   eligible_for_training, eligible_for_rag, eligible_for_agent_memory,
                   memory_text, rag_text, training_features_json, training_labels_json,
                   source_payload_json, safety_json, COALESCE(knowledge_source_id::text, '') AS knowledge_source_id,
                   COALESCE(collective_memory_id::text, '') AS collective_memory_id
            FROM saas_multimodal_memory_events
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:event_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "event_id": event_uuid},
    ).mappings().first()
    if not event:
        raise HTTPException(status_code=404, detail="multimodal_memory_event_not_found")
    item = _row(event)
    allow_customer_content = bool(data.get("allow_customer_content"))
    source_kind = _clean(item.get("source_kind"), 80)
    contains_customer_content = bool(_safe_dict(item.get("safety_json")).get("contains_customer_content"))
    if contains_customer_content and not allow_customer_content:
        raise HTTPException(
            status_code=400,
            detail={"code": "customer_content_requires_explicit_materialization_approval", "source_kind": source_kind},
        )
    knowledge_source: dict[str, Any] | None = None
    collective_memory: dict[str, Any] | None = None
    if destination in {"knowledge", "both"}:
        _feature_access(conn, tenant_id, RAG_FEATURE_KEYS)
        if not item.get("eligible_for_rag") and not allow_customer_content:
            raise HTTPException(status_code=400, detail={"code": "event_not_rag_eligible_without_override", "source_kind": source_kind})
        content = _clean(data.get("content_override") or item.get("rag_text") or item.get("memory_text"), 50000)
        if len(content) < 8:
            raise HTTPException(status_code=400, detail={"code": "event_has_no_rag_content"})
        title = _clean(data.get("title") or f"Multimodal {source_kind}: {item.get('source_id')}", 240)
        knowledge_source = _insert_source(
            conn,
            tenant_id=tenant_id,
            source_type="multimodal_memory",
            title=title,
            content=content,
            url=_clean(_safe_dict(item.get("source_payload_json")).get("url"), 1000),
            metadata={
                "source": "phase24_6_multimodal_memory",
                "event_id": item["id"],
                "source_kind": source_kind,
                "conversation_id": item.get("conversation_id") or "",
                "message_id": item.get("message_id") or "",
                "agent_id": item.get("agent_id") or "",
                "customer_content_approved": allow_customer_content,
            },
        )
    if destination in {"collective_memory", "both"}:
        _feature_access(conn, tenant_id, MEMORY_FEATURE_KEYS)
        if not item.get("eligible_for_agent_memory"):
            raise HTTPException(status_code=400, detail={"code": "event_not_agent_memory_eligible"})
        content = _clean(data.get("content_override") or item.get("memory_text"), 4000)
        if len(content) < 8:
            raise HTTPException(status_code=400, detail={"code": "event_has_no_memory_content"})
        title = _clean(data.get("title") or f"Memoria multimodal: {source_kind}", 180)
        collective_memory = create_collective_memory(
            conn,
            tenant_id,
            user_id,
            {
                "source_agent_id": item.get("agent_id") or "",
                "source_agent_type": "",
                "memory_scope": "tenant",
                "memory_type": "insight",
                "title": title,
                "content": content,
                "confidence_score": int(data.get("confidence_score") or 82),
                "visibility": "agents",
                "tags_json": ["multimodal", source_kind, "phase24_6"],
            },
        )
    conn.execute(
        text(
            """
            UPDATE saas_multimodal_memory_events
            SET knowledge_source_id = COALESCE(CAST(NULLIF(:knowledge_source_id, '') AS uuid), knowledge_source_id),
                collective_memory_id = COALESCE(CAST(NULLIF(:collective_memory_id, '') AS uuid), collective_memory_id),
                materialized_by_user_id = CAST(NULLIF(:user_id, '') AS uuid),
                materialized_at = NOW(),
                updated_at = NOW()
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:event_id AS uuid)
            """
        ),
        {
            "tenant_id": tenant_id,
            "event_id": event_uuid,
            "knowledge_source_id": (knowledge_source or {}).get("id") or "",
            "collective_memory_id": (collective_memory or {}).get("id") or "",
            "user_id": user_id,
        },
    )
    record_event(
        conn,
        tenant_id,
        {
            "event_type": "multimodal.memory.materialized",
            "source": "multimodal_memory",
            "entity_type": "multimodal_memory_event",
            "entity_id": item["id"],
            "conversation_id": item.get("conversation_id") or "",
            "payload_json": {
                "destination": destination,
                "source_kind": source_kind,
                "knowledge_source_id": (knowledge_source or {}).get("id") or "",
                "collective_memory_id": (collective_memory or {}).get("id") or "",
                "customer_content_approved": allow_customer_content,
            },
            "replay_key": f"multimodal-memory-materialized:{item['id']}:{destination}",
        },
    )
    refreshed_row = conn.execute(
        text(
            """
            SELECT id::text, tenant_id::text, COALESCE(conversation_id::text, '') AS conversation_id,
                   COALESCE(message_id::text, '') AS message_id, COALESCE(agent_id::text, '') AS agent_id,
                   source_kind, source_id, event_type, channel, status, privacy_level, approval_status,
                   eligible_for_training, eligible_for_rag, eligible_for_agent_memory,
                   memory_text, rag_text, training_features_json, training_labels_json,
                   source_payload_json, safety_json, COALESCE(intelligence_event_id::text, '') AS intelligence_event_id,
                   COALESCE(knowledge_source_id::text, '') AS knowledge_source_id,
                   COALESCE(collective_memory_id::text, '') AS collective_memory_id,
                   COALESCE(created_by_user_id::text, '') AS created_by_user_id,
                   COALESCE(materialized_by_user_id::text, '') AS materialized_by_user_id,
                   COALESCE(materialized_at::text, '') AS materialized_at,
                   replay_key, created_at::text, updated_at::text
            FROM saas_multimodal_memory_events
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:event_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "event_id": event_uuid},
    ).mappings().first()
    return {
        "event": _row(refreshed_row) if refreshed_row else item,
        "knowledge_source": knowledge_source,
        "collective_memory": collective_memory,
        "destination": destination,
        "safety": {
            "customer_content_approved": allow_customer_content,
            "raw_media_stored": False,
            "auto_customer_send": False,
            "auto_model_training": False,
        },
    }
