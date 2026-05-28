from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app_saas.intelligence.service import ensure_intelligence_tables, intelligence_feature_state, record_event, record_intelligence_usage


MEMORY_FEATURE_KEYS = (
    "enterprise_memory_network",
    "memory_graph",
    "memory_governance",
    "cross_agent_memory_routing",
    "memory_quality_scoring",
)
MEMORY_FULL_KEYS = ("enterprise_memory_network", "ai_premium")
ALLOWED_REVIEW_STATUSES = {"candidate", "published", "rejected", "archived"}
ALLOWED_MEMORY_SCOPES = {"tenant", "agent", "customer", "knowledge", "workflow"}
ALLOWED_PRIVACY_MODES = {"tenant_private", "tenant_restricted", "aggregate_only"}


def _clean(value: Any, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def _json_value(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return fallback


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _row(row: dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    for key in (
        "allowed_scopes_json",
        "settings_json",
        "source_json",
        "tags_json",
        "review_json",
        "evidence_json",
        "source_counts_json",
        "findings_json",
        "metadata_json",
    ):
        if key in data:
            data[key] = _json_value(data.get(key), [] if key in {"allowed_scopes_json", "tags_json", "findings_json"} else {})
    return {key: _jsonable(value) for key, value in data.items()}


def _hash(text_value: str) -> str:
    return hashlib.sha256((text_value or "").encode("utf-8")).hexdigest()


def _memory_scopes(value: Any) -> list[str]:
    raw_items = value if isinstance(value, list) else []
    scopes = []
    for item in raw_items:
        clean = _clean(item, 40).lower()
        if clean in ALLOWED_MEMORY_SCOPES and clean not in scopes:
            scopes.append(clean)
    return scopes or ["tenant", "agent", "customer", "knowledge", "workflow"]


def _policy_retention_days(policy: dict[str, Any]) -> int:
    try:
        return max(1, min(int(policy.get("retention_days") or 365), 3650))
    except (TypeError, ValueError):
        return 365


def _score(value: Any, default: float = 0) -> float:
    try:
        return min(100, max(0, float(value if value is not None else default)))
    except (TypeError, ValueError):
        return default


def _apply_memory_policy(candidate: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any] | None:
    scoped = dict(candidate)
    memory_scope = _clean(scoped.get("memory_scope"), 80).lower() or "tenant"
    allowed_scopes = set(_memory_scopes(policy.get("allowed_scopes_json")))
    if memory_scope not in allowed_scopes:
        return None

    source_json = _json_value(scoped.get("source_json"), {})
    privacy_mode = _clean(policy.get("privacy_mode") or "tenant_private", 40).lower()
    if privacy_mode == "aggregate_only":
        scoped["privacy_level"] = "aggregate_only"
    elif privacy_mode in {"tenant_private", "tenant_restricted"} and scoped.get("privacy_level") != "aggregate_only":
        scoped["privacy_level"] = privacy_mode

    is_customer_content = memory_scope == "customer" or _clean(scoped.get("sensitivity"), 80).lower() == "customer_content"
    if bool(policy.get("require_review_for_customer_content", True)) and is_customer_content:
        if scoped.get("status") == "published":
            source_json = {**source_json, "policy_forced_review": True}
        scoped["status"] = "candidate"
        scoped["sensitivity"] = "customer_content"

    scoped["source_json"] = source_json
    scoped["retention_days"] = _policy_retention_days(policy)
    return scoped


def _record_memory_access(
    conn: Connection,
    tenant_id: str,
    *,
    node_id: str = "",
    accessor_type: str = "user",
    accessor_id: str = "",
    purpose: str = "",
    result_status: str = "allowed",
    metadata: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        text(
            """
            INSERT INTO saas_enterprise_memory_access_logs (
                tenant_id, node_id, accessor_type, accessor_id, purpose, result_status, metadata_json
            )
            VALUES (
                CAST(:tenant_id AS uuid), CAST(NULLIF(:node_id, '') AS uuid),
                :accessor_type, :accessor_id, :purpose, :result_status,
                CAST(:metadata_json AS jsonb)
            )
            """
        ),
        {
            "tenant_id": tenant_id,
            "node_id": node_id,
            "accessor_type": _clean(accessor_type, 80),
            "accessor_id": _clean(accessor_id, 160),
            "purpose": _clean(purpose, 160),
            "result_status": _clean(result_status, 40) or "allowed",
            "metadata_json": _json(metadata or {}),
        },
    )


def _feature_map(conn: Connection, tenant_id: str) -> dict[str, dict[str, Any]]:
    state = intelligence_feature_state(conn, tenant_id)
    return {str(item.get("key") or ""): item for item in state.get("features", [])}


def memory_network_access(conn: Connection, tenant_id: str) -> dict[str, Any]:
    features = _feature_map(conn, tenant_id)
    items = {key: features.get(key, {"key": key, "enabled": False, "mode": "disabled"}) for key in MEMORY_FEATURE_KEYS}
    full = any(bool((features.get(key) or {}).get("enabled")) and str((features.get(key) or {}).get("mode") or "") == "full" for key in MEMORY_FULL_KEYS)
    enabled = full or any(bool(item.get("enabled")) for item in items.values())
    mode = "full" if full else "demo" if enabled else "disabled"
    return {"enabled": enabled, "full": full, "mode": mode, "features": items}


def _require_memory_access(conn: Connection, tenant_id: str, *, allow_demo: bool) -> dict[str, Any]:
    access = memory_network_access(conn, tenant_id)
    if not access.get("enabled"):
        raise HTTPException(status_code=403, detail={"code": "intelligence_feature_not_enabled", "feature": "enterprise_memory_network"})
    if not allow_demo and not access.get("full"):
        raise HTTPException(status_code=403, detail={"code": "intelligence_feature_requires_full", "feature": "enterprise_memory_network"})
    return access


def ensure_memory_network_tables(conn: Connection) -> None:
    ensure_intelligence_tables(conn)
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_enterprise_memory_policies (
                tenant_id UUID PRIMARY KEY REFERENCES saas_tenants(id) ON DELETE CASCADE,
                privacy_mode TEXT NOT NULL DEFAULT 'tenant_private',
                retention_days INTEGER NOT NULL DEFAULT 365,
                auto_capture_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                require_review_for_customer_content BOOLEAN NOT NULL DEFAULT TRUE,
                allow_cross_agent_retrieval BOOLEAN NOT NULL DEFAULT TRUE,
                allowed_scopes_json JSONB NOT NULL DEFAULT '["tenant","agent","customer","knowledge","workflow"]'::jsonb,
                settings_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                updated_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_enterprise_memory_nodes (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                node_key TEXT NOT NULL,
                memory_scope TEXT NOT NULL DEFAULT 'tenant',
                node_type TEXT NOT NULL DEFAULT 'fact',
                title TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                content_hash TEXT NOT NULL DEFAULT '',
                privacy_level TEXT NOT NULL DEFAULT 'tenant_private',
                sensitivity TEXT NOT NULL DEFAULT 'normal',
                confidence NUMERIC(8,4) NOT NULL DEFAULT 0,
                quality_score NUMERIC(8,4) NOT NULL DEFAULT 0,
                source_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                tags_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                review_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                status TEXT NOT NULL DEFAULT 'candidate',
                created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                reviewed_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                reviewed_at TIMESTAMP NULL,
                expires_at TIMESTAMP NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, node_key)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_enterprise_memory_nodes_tenant_status ON saas_enterprise_memory_nodes (tenant_id, status, memory_scope, updated_at DESC)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_enterprise_memory_nodes_type ON saas_enterprise_memory_nodes (tenant_id, node_type, quality_score DESC, updated_at DESC)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_enterprise_memory_edges (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                source_node_id UUID NOT NULL REFERENCES saas_enterprise_memory_nodes(id) ON DELETE CASCADE,
                target_node_id UUID NOT NULL REFERENCES saas_enterprise_memory_nodes(id) ON DELETE CASCADE,
                relation_type TEXT NOT NULL DEFAULT 'related_to',
                weight NUMERIC(8,4) NOT NULL DEFAULT 1,
                evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, source_node_id, target_node_id, relation_type)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_enterprise_memory_edges_tenant_source ON saas_enterprise_memory_edges (tenant_id, source_node_id, relation_type)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_enterprise_memory_sync_runs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                sync_type TEXT NOT NULL DEFAULT 'manual',
                status TEXT NOT NULL DEFAULT 'completed',
                source_counts_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                nodes_scanned INTEGER NOT NULL DEFAULT 0,
                nodes_created INTEGER NOT NULL DEFAULT 0,
                nodes_updated INTEGER NOT NULL DEFAULT 0,
                edges_created INTEGER NOT NULL DEFAULT 0,
                findings_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                started_at TIMESTAMP NOT NULL DEFAULT NOW(),
                completed_at TIMESTAMP NULL,
                created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_enterprise_memory_sync_runs_tenant ON saas_enterprise_memory_sync_runs (tenant_id, created_at DESC)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_enterprise_memory_access_logs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                node_id UUID NULL REFERENCES saas_enterprise_memory_nodes(id) ON DELETE SET NULL,
                accessor_type TEXT NOT NULL DEFAULT 'user',
                accessor_id TEXT NOT NULL DEFAULT '',
                purpose TEXT NOT NULL DEFAULT '',
                result_status TEXT NOT NULL DEFAULT 'allowed',
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_enterprise_memory_access_logs_tenant ON saas_enterprise_memory_access_logs (tenant_id, created_at DESC)"))


def memory_policy(conn: Connection, tenant_id: str) -> dict[str, Any]:
    ensure_memory_network_tables(conn)
    conn.execute(text("INSERT INTO saas_enterprise_memory_policies (tenant_id) VALUES (CAST(:tenant_id AS uuid)) ON CONFLICT (tenant_id) DO NOTHING"), {"tenant_id": tenant_id})
    row = conn.execute(
        text(
            """
            SELECT tenant_id::text, privacy_mode, retention_days, auto_capture_enabled,
                   require_review_for_customer_content, allow_cross_agent_retrieval,
                   allowed_scopes_json, settings_json, COALESCE(updated_by_user_id::text, '') AS updated_by_user_id,
                   created_at::text, updated_at::text
            FROM saas_enterprise_memory_policies
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    return _row(dict(row or {}))


def update_memory_policy(conn: Connection, tenant_id: str, actor_user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    ensure_memory_network_tables(conn)
    _require_memory_access(conn, tenant_id, allow_demo=False)
    privacy_mode = _clean(payload.get("privacy_mode") or "tenant_private", 40).lower()
    if privacy_mode not in ALLOWED_PRIVACY_MODES:
        privacy_mode = "tenant_private"
    allowed_scopes = _memory_scopes(payload.get("allowed_scopes_json") or ["tenant", "agent", "customer", "knowledge", "workflow"])
    retention_days = max(1, min(int(payload.get("retention_days") or 365), 3650))
    row = conn.execute(
        text(
            """
            INSERT INTO saas_enterprise_memory_policies (
                tenant_id, privacy_mode, retention_days, auto_capture_enabled,
                require_review_for_customer_content, allow_cross_agent_retrieval,
                allowed_scopes_json, settings_json, updated_by_user_id, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), :privacy_mode, :retention_days, :auto_capture_enabled,
                :require_review_for_customer_content, :allow_cross_agent_retrieval,
                CAST(:allowed_scopes_json AS jsonb), CAST(:settings_json AS jsonb),
                CAST(NULLIF(:actor_user_id, '') AS uuid), NOW()
            )
            ON CONFLICT (tenant_id)
            DO UPDATE SET
                privacy_mode = EXCLUDED.privacy_mode,
                retention_days = EXCLUDED.retention_days,
                auto_capture_enabled = EXCLUDED.auto_capture_enabled,
                require_review_for_customer_content = EXCLUDED.require_review_for_customer_content,
                allow_cross_agent_retrieval = EXCLUDED.allow_cross_agent_retrieval,
                allowed_scopes_json = EXCLUDED.allowed_scopes_json,
                settings_json = EXCLUDED.settings_json,
                updated_by_user_id = EXCLUDED.updated_by_user_id,
                updated_at = NOW()
            RETURNING tenant_id::text, privacy_mode, retention_days, auto_capture_enabled,
                      require_review_for_customer_content, allow_cross_agent_retrieval,
                      allowed_scopes_json, settings_json, COALESCE(updated_by_user_id::text, '') AS updated_by_user_id,
                      created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "actor_user_id": actor_user_id,
            "privacy_mode": privacy_mode,
            "retention_days": retention_days,
            "auto_capture_enabled": bool(payload.get("auto_capture_enabled")),
            "require_review_for_customer_content": bool(payload.get("require_review_for_customer_content", True)),
            "allow_cross_agent_retrieval": bool(payload.get("allow_cross_agent_retrieval", True)),
            "allowed_scopes_json": _json(allowed_scopes),
            "settings_json": _json(payload.get("settings_json") or {}),
        },
    ).mappings().first()
    policy = _row(dict(row or {}))
    _enforce_policy_on_existing_nodes(conn, tenant_id, policy)
    return policy


def _enforce_policy_on_existing_nodes(conn: Connection, tenant_id: str, policy: dict[str, Any]) -> None:
    allowed_scopes = _memory_scopes(policy.get("allowed_scopes_json"))
    retention_days = _policy_retention_days(policy)
    privacy_mode = _clean(policy.get("privacy_mode") or "tenant_private", 40).lower()
    conn.execute(
        text(
            """
            UPDATE saas_enterprise_memory_nodes
            SET status = 'archived',
                review_json = review_json || CAST(:review_json AS jsonb),
                updated_at = NOW()
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND status NOT IN ('archived', 'rejected')
              AND memory_scope NOT IN (
                  SELECT jsonb_array_elements_text(CAST(:allowed_scopes_json AS jsonb))
              )
            """
        ),
        {
            "tenant_id": tenant_id,
            "allowed_scopes_json": _json(allowed_scopes),
            "review_json": _json({"policy_enforced": "scope_archived", "at": datetime.now(timezone.utc).isoformat()}),
        },
    )
    if bool(policy.get("require_review_for_customer_content", True)):
        conn.execute(
            text(
                """
                UPDATE saas_enterprise_memory_nodes
                SET status = 'candidate',
                    sensitivity = 'customer_content',
                    review_json = review_json || CAST(:review_json AS jsonb),
                    updated_at = NOW()
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND status = 'published'
                  AND (memory_scope = 'customer' OR sensitivity = 'customer_content')
                """
            ),
            {
                "tenant_id": tenant_id,
                "review_json": _json({"policy_enforced": "customer_review_required", "at": datetime.now(timezone.utc).isoformat()}),
            },
        )
    conn.execute(
        text(
            """
            UPDATE saas_enterprise_memory_nodes
            SET expires_at = NOW() + (:retention_days * INTERVAL '1 day'),
                privacy_level = CASE
                    WHEN :privacy_mode = 'aggregate_only' THEN 'aggregate_only'
                    WHEN privacy_level = 'aggregate_only' THEN privacy_level
                    ELSE :privacy_mode
                END,
                updated_at = NOW()
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND status != 'archived'
            """
        ),
        {"tenant_id": tenant_id, "retention_days": retention_days, "privacy_mode": privacy_mode},
    )


def _source_candidates(conn: Connection, tenant_id: str, *, limit: int, source_types: set[str]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    max_rows = max(1, min(int(limit or 80), 300))

    if not source_types or "collective_memory" in source_types:
        rows = conn.execute(
            text(
                """
                SELECT id::text, memory_scope, memory_type, title, content, confidence_score,
                       visibility, tags_json, created_at::text, updated_at::text
                FROM saas_ai_agent_collective_memory
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                ORDER BY updated_at DESC
                LIMIT :limit
                """
            ),
            {"tenant_id": tenant_id, "limit": max_rows},
        ).mappings().all()
        for row in rows:
            data = _row(dict(row))
            summary = _clean(data.get("content"), 900)
            candidates.append({
                "node_key": f"collective:{data['id']}",
                "memory_scope": data.get("memory_scope") or "tenant",
                "node_type": data.get("memory_type") or "fact",
                "title": data.get("title") or "Memoria colectiva",
                "summary": summary,
                "privacy_level": "tenant_private",
                "sensitivity": "normal",
                "confidence": float(data.get("confidence_score") or 80),
                "quality_score": min(100, 55 + len(summary) / 30),
                "source_json": {"source": "saas_ai_agent_collective_memory", "id": data["id"], "visibility": data.get("visibility")},
                "tags_json": data.get("tags_json") or [],
                "status": "published",
            })

    if not source_types or "multimodal" in source_types:
        rows = conn.execute(
            text(
                """
                SELECT id::text, source_kind, source_id, event_type, channel, status,
                       privacy_level, approval_status, eligible_for_training, eligible_for_rag,
                       eligible_for_agent_memory, memory_text, rag_text, training_features_json,
                       created_at::text, updated_at::text
                FROM saas_multimodal_memory_events
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND status IN ('ready', 'materialized')
                ORDER BY updated_at DESC
                LIMIT :limit
                """
            ),
            {"tenant_id": tenant_id, "limit": max_rows},
        ).mappings().all()
        for row in rows:
            data = _row(dict(row))
            text_value = data.get("memory_text") or data.get("rag_text") or ""
            approval = str(data.get("approval_status") or "not_required")
            candidates.append({
                "node_key": f"multimodal:{data['id']}",
                "memory_scope": "customer" if data.get("source_kind") in {"voice", "vision", "web_search"} else "tenant",
                "node_type": data.get("event_type") or "multimodal_signal",
                "title": f"Senal multimodal: {data.get('event_type') or data.get('source_kind')}",
                "summary": _clean(text_value, 900),
                "privacy_level": data.get("privacy_level") or "tenant_private",
                "sensitivity": "customer_content" if data.get("privacy_level") == "tenant_private" else "normal",
                "confidence": 80 if approval in {"approved", "not_required"} else 55,
                "quality_score": 85 if approval == "approved" else 62,
                "source_json": {"source": "saas_multimodal_memory_events", "id": data["id"], "approval_status": approval, "channel": data.get("channel")},
                "tags_json": [data.get("source_kind"), data.get("event_type")],
                "status": "published" if approval == "approved" else "candidate",
            })

    if not source_types or "knowledge" in source_types:
        rows = conn.execute(
            text(
                """
                SELECT id::text, name, source_type, status, content, metadata_json, created_at::text, updated_at::text
                FROM saas_knowledge_sources
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND status IN ('ready', 'processed', 'indexed', 'active')
                ORDER BY updated_at DESC
                LIMIT :limit
                """
            ),
            {"tenant_id": tenant_id, "limit": max_rows},
        ).mappings().all()
        for row in rows:
            data = _row(dict(row))
            candidates.append({
                "node_key": f"knowledge:{data['id']}",
                "memory_scope": "knowledge",
                "node_type": data.get("source_type") or "knowledge_source",
                "title": data.get("name") or "Fuente Knowledge",
                "summary": _clean(data.get("content"), 900),
                "privacy_level": "tenant_private",
                "sensitivity": "normal",
                "confidence": 78,
                "quality_score": 75,
                "source_json": {"source": "saas_knowledge_sources", "id": data["id"], "status": data.get("status")},
                "tags_json": ["knowledge", data.get("source_type")],
                "status": "candidate",
            })

    if not source_types or "vertical_insights" in source_types:
        rows = conn.execute(
            text(
                """
                SELECT id::text, industry_code, insight_key, insight_type, title, description,
                       severity, confidence, kpi_key, status, created_at::text, updated_at::text
                FROM saas_ai_vertical_insights
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND status = 'open'
                ORDER BY updated_at DESC
                LIMIT :limit
                """
            ),
            {"tenant_id": tenant_id, "limit": max_rows},
        ).mappings().all()
        for row in rows:
            data = _row(dict(row))
            candidates.append({
                "node_key": f"vertical_insight:{data['id']}",
                "memory_scope": "tenant",
                "node_type": data.get("insight_type") or "vertical_insight",
                "title": data.get("title") or "Insight vertical",
                "summary": _clean(data.get("description"), 900),
                "privacy_level": "aggregate_only",
                "sensitivity": "normal",
                "confidence": float(data.get("confidence") or 70),
                "quality_score": 80,
                "source_json": {"source": "saas_ai_vertical_insights", "id": data["id"], "industry_code": data.get("industry_code"), "kpi_key": data.get("kpi_key")},
                "tags_json": ["vertical", data.get("industry_code"), data.get("kpi_key")],
                "status": "published",
            })

    return candidates[:max_rows]


def _upsert_node(conn: Connection, tenant_id: str, candidate: dict[str, Any], *, actor_user_id: str) -> tuple[dict[str, Any], bool]:
    existing = conn.execute(
        text(
            """
            SELECT id::text
            FROM saas_enterprise_memory_nodes
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND node_key = :node_key
            """
        ),
        {"tenant_id": tenant_id, "node_key": candidate["node_key"]},
    ).first()
    created = not bool(existing)
    summary = _clean(candidate.get("summary"), 1200)
    row = conn.execute(
        text(
            """
            INSERT INTO saas_enterprise_memory_nodes (
                tenant_id, node_key, memory_scope, node_type, title, summary, content_hash,
                privacy_level, sensitivity, confidence, quality_score, source_json, tags_json,
                status, expires_at, created_by_user_id, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), :node_key, :memory_scope, :node_type, :title, :summary, :content_hash,
                :privacy_level, :sensitivity, :confidence, :quality_score, CAST(:source_json AS jsonb),
                CAST(:tags_json AS jsonb), :status,
                NOW() + (:retention_days * INTERVAL '1 day'),
                CAST(NULLIF(:actor_user_id, '') AS uuid), NOW()
            )
            ON CONFLICT (tenant_id, node_key)
            DO UPDATE SET
                memory_scope = EXCLUDED.memory_scope,
                node_type = EXCLUDED.node_type,
                title = EXCLUDED.title,
                summary = EXCLUDED.summary,
                content_hash = EXCLUDED.content_hash,
                privacy_level = EXCLUDED.privacy_level,
                sensitivity = EXCLUDED.sensitivity,
                confidence = EXCLUDED.confidence,
                quality_score = EXCLUDED.quality_score,
                source_json = EXCLUDED.source_json,
                tags_json = EXCLUDED.tags_json,
                status = CASE
                    WHEN saas_enterprise_memory_nodes.status IN ('archived', 'rejected')
                    THEN saas_enterprise_memory_nodes.status
                    ELSE EXCLUDED.status
                END,
                expires_at = EXCLUDED.expires_at,
                updated_at = NOW()
            RETURNING id::text, tenant_id::text, node_key, memory_scope, node_type, title, summary, content_hash,
                      privacy_level, sensitivity, confidence, quality_score, source_json, tags_json,
                      review_json, status, COALESCE(created_by_user_id::text, '') AS created_by_user_id,
                      COALESCE(reviewed_by_user_id::text, '') AS reviewed_by_user_id,
                      reviewed_at::text, expires_at::text, created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "actor_user_id": actor_user_id,
            "node_key": _clean(candidate.get("node_key"), 240),
            "memory_scope": _clean(candidate.get("memory_scope"), 80) or "tenant",
            "node_type": _clean(candidate.get("node_type"), 80) or "fact",
            "title": _clean(candidate.get("title"), 240) or "Memoria",
            "summary": summary,
            "content_hash": _hash(summary),
            "privacy_level": _clean(candidate.get("privacy_level"), 80) or "tenant_private",
            "sensitivity": _clean(candidate.get("sensitivity"), 80) or "normal",
            "confidence": _score(candidate.get("confidence"), 0),
            "quality_score": _score(candidate.get("quality_score"), 0),
            "source_json": _json(candidate.get("source_json") or {}),
            "tags_json": _json([item for item in (candidate.get("tags_json") or []) if item]),
            "status": _clean(candidate.get("status"), 40) or "candidate",
            "retention_days": _policy_retention_days(candidate),
        },
    ).mappings().first()
    return _row(dict(row or {})), created


def _ensure_root_node(conn: Connection, tenant_id: str) -> dict[str, Any]:
    node, _ = _upsert_node(
        conn,
        tenant_id,
        {
            "node_key": f"tenant_memory_root:{tenant_id}",
            "memory_scope": "tenant",
            "node_type": "root",
            "title": "Memoria empresarial del tenant",
            "summary": "Nodo raiz para relacionar memorias tenant-scoped, agentes, Knowledge y senales multimodales.",
            "privacy_level": "tenant_private",
            "sensitivity": "normal",
            "confidence": 100,
            "quality_score": 100,
            "source_json": {"source": "system"},
            "tags_json": ["root", "tenant_memory"],
            "status": "published",
        },
        actor_user_id="",
    )
    return node


def _link_root(conn: Connection, tenant_id: str, root_id: str, target_id: str, relation_type: str = "contains") -> bool:
    row = conn.execute(
        text(
            """
            INSERT INTO saas_enterprise_memory_edges (
                tenant_id, source_node_id, target_node_id, relation_type, weight, evidence_json, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), CAST(:root_id AS uuid), CAST(:target_id AS uuid),
                :relation_type, 1, '{"source":"sync"}'::jsonb, NOW()
            )
            ON CONFLICT (tenant_id, source_node_id, target_node_id, relation_type)
            DO NOTHING
            RETURNING id::text
            """
        ),
        {"tenant_id": tenant_id, "root_id": root_id, "target_id": target_id, "relation_type": relation_type},
    ).first()
    return bool(row)


def sync_enterprise_memory_network(
    conn: Connection,
    tenant_id: str,
    *,
    actor_user_id: str = "",
    dry_run: bool = False,
    limit: int = 80,
    source_types: list[str] | None = None,
    source: str = "manual",
) -> dict[str, Any]:
    ensure_memory_network_tables(conn)
    access = _require_memory_access(conn, tenant_id, allow_demo=dry_run)
    policy = memory_policy(conn, tenant_id)
    source_filter = {str(item or "").strip().lower() for item in (source_types or []) if str(item or "").strip()}
    raw_candidates = _source_candidates(conn, tenant_id, limit=limit, source_types=source_filter)
    candidates = [
        scoped
        for item in raw_candidates
        if (scoped := _apply_memory_policy(item, policy)) is not None
    ]
    source_counts: dict[str, int] = {}
    for item in candidates:
        source_name = str((item.get("source_json") or {}).get("source") or "unknown")
        source_counts[source_name] = source_counts.get(source_name, 0) + 1
    if dry_run:
        return {
            "dry_run": True,
            "access": access,
            "candidate_nodes": candidates,
            "created_nodes": [],
            "updated_nodes": [],
            "source_counts": source_counts,
            "sync_run": None,
        }
    record_intelligence_usage(conn, tenant_id, "enterprise_memory_network", usage_metric="memory_sync", metadata={"source": source})
    root = _ensure_root_node(conn, tenant_id)
    created_nodes: list[dict[str, Any]] = []
    updated_nodes: list[dict[str, Any]] = []
    edges_created = 0
    for candidate in candidates:
        node, created = _upsert_node(conn, tenant_id, candidate, actor_user_id=actor_user_id)
        if created:
            created_nodes.append(node)
        else:
            updated_nodes.append(node)
        if node.get("id") and root.get("id") and node["id"] != root["id"]:
            edges_created += 1 if _link_root(conn, tenant_id, root["id"], node["id"]) else 0
    run = conn.execute(
        text(
            """
            INSERT INTO saas_enterprise_memory_sync_runs (
                tenant_id, sync_type, status, source_counts_json, nodes_scanned,
                nodes_created, nodes_updated, edges_created, findings_json,
                completed_at, created_by_user_id
            )
            VALUES (
                CAST(:tenant_id AS uuid), :sync_type, 'completed', CAST(:source_counts_json AS jsonb),
                :nodes_scanned, :nodes_created, :nodes_updated, :edges_created,
                CAST(:findings_json AS jsonb), NOW(), CAST(NULLIF(:actor_user_id, '') AS uuid)
            )
            RETURNING id::text, tenant_id::text, sync_type, status, source_counts_json,
                      nodes_scanned, nodes_created, nodes_updated, edges_created,
                      findings_json, started_at::text, completed_at::text,
                      COALESCE(created_by_user_id::text, '') AS created_by_user_id, created_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "actor_user_id": actor_user_id,
            "sync_type": source,
            "source_counts_json": _json(source_counts),
            "nodes_scanned": len(candidates),
            "nodes_created": len(created_nodes),
            "nodes_updated": len(updated_nodes),
            "edges_created": edges_created,
            "findings_json": _json([{"key": "requires_review", "value": sum(1 for item in candidates if item.get("status") == "candidate")}]),
        },
    ).mappings().first()
    event = record_event(
        conn,
        tenant_id,
        {
            "event_type": "memory.network_synced",
            "source": "enterprise_memory_network",
            "entity_type": "tenant",
            "entity_id": tenant_id,
            "payload_json": {"nodes_created": len(created_nodes), "nodes_updated": len(updated_nodes), "edges_created": edges_created, "source_counts": source_counts},
            "replay_key": f"memory_network:sync:{tenant_id}:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}",
        },
    )
    return {
        "dry_run": False,
        "access": access,
        "candidate_nodes": candidates,
        "created_nodes": created_nodes,
        "updated_nodes": updated_nodes,
        "source_counts": source_counts,
        "sync_run": _row(dict(run or {})),
        "event": event,
    }


def export_memory_network(conn: Connection, tenant_id: str, actor_user_id: str, *, include_archived: bool = False, limit: int = 300) -> dict[str, Any]:
    ensure_memory_network_tables(conn)
    _require_memory_access(conn, tenant_id, allow_demo=False)
    nodes = _list_nodes(conn, tenant_id, status="all", limit=limit)
    if not include_archived:
        nodes = [node for node in nodes if node.get("status") != "archived"]
    node_ids = {node.get("id") for node in nodes}
    edges = [edge for edge in _list_edges(conn, tenant_id, limit=limit) if edge.get("source_node_id") in node_ids and edge.get("target_node_id") in node_ids]
    _record_memory_access(
        conn,
        tenant_id,
        accessor_id=actor_user_id,
        purpose="memory_network_export",
        metadata={"nodes": len(nodes), "edges": len(edges), "include_archived": include_archived},
    )
    return {
        "phase": "20",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "tenant_id": tenant_id,
        "policy": memory_policy(conn, tenant_id),
        "nodes": nodes,
        "edges": edges,
        "safety": {
            "contains_raw_media": False,
            "contains_cross_tenant_raw_content": False,
            "content_type": "bounded_summaries_metadata_hashes",
        },
    }


def import_memory_network(conn: Connection, tenant_id: str, actor_user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    ensure_memory_network_tables(conn)
    access = _require_memory_access(conn, tenant_id, allow_demo=bool(payload.get("dry_run")))
    policy = memory_policy(conn, tenant_id)
    raw_nodes = payload.get("nodes_json") if isinstance(payload.get("nodes_json"), list) else []
    if len(raw_nodes) > 200:
        raise HTTPException(status_code=400, detail={"code": "memory_import_too_large", "max_nodes": 200})
    candidates: list[dict[str, Any]] = []
    for raw in raw_nodes:
        if not isinstance(raw, dict):
            continue
        summary = _clean(raw.get("summary") or raw.get("content") or "", 1200)
        title = _clean(raw.get("title") or "Memoria importada", 240)
        if not summary and not title:
            continue
        source_json = _json_value(raw.get("source_json"), {})
        candidate = {
            "node_key": _clean(raw.get("node_key"), 240) or f"import:{_hash(title + ':' + summary)[:24]}",
            "memory_scope": _clean(raw.get("memory_scope"), 80).lower() or "tenant",
            "node_type": _clean(raw.get("node_type"), 80) or "imported_memory",
            "title": title,
            "summary": summary,
            "privacy_level": _clean(raw.get("privacy_level"), 80) or "tenant_private",
            "sensitivity": _clean(raw.get("sensitivity"), 80) or "normal",
            "confidence": _score(raw.get("confidence"), 60),
            "quality_score": _score(raw.get("quality_score"), 60),
            "source_json": {"source": "enterprise_memory_import", "imported_source": source_json},
            "tags_json": [item for item in (raw.get("tags_json") or ["imported"]) if item],
            "status": "candidate",
        }
        scoped = _apply_memory_policy(candidate, policy)
        if scoped is not None:
            candidates.append(scoped)
    if payload.get("dry_run"):
        return {"dry_run": True, "access": access, "candidate_nodes": candidates, "created_nodes": [], "updated_nodes": []}
    record_intelligence_usage(conn, tenant_id, "enterprise_memory_network", usage_metric="memory_import", metadata={"nodes": len(candidates)})
    created_nodes: list[dict[str, Any]] = []
    updated_nodes: list[dict[str, Any]] = []
    for candidate in candidates:
        node, created = _upsert_node(conn, tenant_id, candidate, actor_user_id=actor_user_id)
        if created:
            created_nodes.append(node)
        else:
            updated_nodes.append(node)
    _record_memory_access(
        conn,
        tenant_id,
        accessor_id=actor_user_id,
        purpose="memory_network_import",
        metadata={"created": len(created_nodes), "updated": len(updated_nodes)},
    )
    record_event(
        conn,
        tenant_id,
        {
            "event_type": "memory.network_imported",
            "source": "enterprise_memory_network",
            "entity_type": "tenant",
            "entity_id": tenant_id,
            "payload_json": {"created": len(created_nodes), "updated": len(updated_nodes)},
            "replay_key": f"memory_network:import:{tenant_id}:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        },
    )
    return {"dry_run": False, "access": access, "candidate_nodes": candidates, "created_nodes": created_nodes, "updated_nodes": updated_nodes}


def _list_nodes(conn: Connection, tenant_id: str, *, status: str = "all", limit: int = 80) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT id::text, tenant_id::text, node_key, memory_scope, node_type, title, summary,
                   content_hash, privacy_level, sensitivity, confidence, quality_score, source_json,
                   tags_json, review_json, status, COALESCE(created_by_user_id::text, '') AS created_by_user_id,
                   COALESCE(reviewed_by_user_id::text, '') AS reviewed_by_user_id,
                   reviewed_at::text, expires_at::text, created_at::text, updated_at::text
            FROM saas_enterprise_memory_nodes
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND (:status = 'all' OR status = :status)
            ORDER BY quality_score DESC, updated_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "status": _clean(status, 40).lower() or "all", "limit": max(1, min(int(limit or 80), 300))},
    ).mappings().all()
    return [_row(dict(row)) for row in rows]


def _list_edges(conn: Connection, tenant_id: str, *, limit: int = 80) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT e.id::text, e.tenant_id::text, e.source_node_id::text, e.target_node_id::text,
                   e.relation_type, e.weight, e.evidence_json, e.created_at::text, e.updated_at::text,
                   s.title AS source_title, t.title AS target_title
            FROM saas_enterprise_memory_edges e
            JOIN saas_enterprise_memory_nodes s ON s.id = e.source_node_id AND s.tenant_id = e.tenant_id
            JOIN saas_enterprise_memory_nodes t ON t.id = e.target_node_id AND t.tenant_id = e.tenant_id
            WHERE e.tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY e.updated_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "limit": max(1, min(int(limit or 80), 300))},
    ).mappings().all()
    return [_row(dict(row)) for row in rows]


def _list_sync_runs(conn: Connection, tenant_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT id::text, tenant_id::text, sync_type, status, source_counts_json,
                   nodes_scanned, nodes_created, nodes_updated, edges_created,
                   findings_json, started_at::text, completed_at::text,
                   COALESCE(created_by_user_id::text, '') AS created_by_user_id, created_at::text
            FROM saas_enterprise_memory_sync_runs
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "limit": max(1, min(int(limit or 20), 100))},
    ).mappings().all()
    return [_row(dict(row)) for row in rows]


def memory_network_center(conn: Connection, tenant_id: str, *, limit: int = 80) -> dict[str, Any]:
    ensure_memory_network_tables(conn)
    policy = memory_policy(conn, tenant_id)
    nodes = _list_nodes(conn, tenant_id, status="all", limit=limit)
    edges = _list_edges(conn, tenant_id, limit=limit)
    counts = {
        "nodes": len(nodes),
        "published_nodes": sum(1 for item in nodes if item.get("status") == "published"),
        "candidate_nodes": sum(1 for item in nodes if item.get("status") == "candidate"),
        "edges": len(edges),
        "customer_content_nodes": sum(1 for item in nodes if item.get("sensitivity") == "customer_content"),
    }
    return {
        "phase": "20",
        "access": memory_network_access(conn, tenant_id),
        "policy": policy,
        "counts": counts,
        "nodes": nodes,
        "edges": edges,
        "sync_runs": _list_sync_runs(conn, tenant_id, limit=20),
        "routing": {
            "cross_agent_memory_routing": bool(policy.get("allow_cross_agent_retrieval")),
            "requires_review_for_customer_content": bool(policy.get("require_review_for_customer_content", True)),
            "privacy_mode": policy.get("privacy_mode") or "tenant_private",
            "allowed_scopes": policy.get("allowed_scopes_json") or [],
            "retention_days": policy.get("retention_days") or 365,
        },
        "safety": {
            "tenant_isolated": True,
            "cross_tenant_raw_content": False,
            "raw_media_persisted": False,
            "review_required_for_customer_content": bool(policy.get("require_review_for_customer_content", True)),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def review_memory_node(conn: Connection, tenant_id: str, actor_user_id: str, node_id: str, *, status: str, notes: str = "") -> dict[str, Any]:
    ensure_memory_network_tables(conn)
    _require_memory_access(conn, tenant_id, allow_demo=False)
    clean_status = _clean(status, 40).lower()
    if clean_status not in ALLOWED_REVIEW_STATUSES:
        raise HTTPException(status_code=400, detail={"code": "invalid_memory_node_status", "allowed": sorted(ALLOWED_REVIEW_STATUSES)})
    policy = memory_policy(conn, tenant_id)
    if clean_status == "published":
        existing = conn.execute(
            text(
                """
                SELECT memory_scope, sensitivity
                FROM saas_enterprise_memory_nodes
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:node_id AS uuid)
                """
            ),
            {"tenant_id": tenant_id, "node_id": node_id},
        ).mappings().first()
        if not existing:
            raise HTTPException(status_code=404, detail={"code": "memory_node_not_found"})
        memory_scope = _clean(existing.get("memory_scope"), 80).lower()
        if memory_scope not in set(_memory_scopes(policy.get("allowed_scopes_json"))):
            raise HTTPException(status_code=403, detail={"code": "memory_scope_not_allowed_by_policy", "memory_scope": memory_scope})
    row = conn.execute(
        text(
            """
            UPDATE saas_enterprise_memory_nodes
            SET status = :status,
                reviewed_by_user_id = CAST(NULLIF(:actor_user_id, '') AS uuid),
                reviewed_at = NOW(),
                review_json = review_json || CAST(:review_json AS jsonb),
                updated_at = NOW()
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:node_id AS uuid)
            RETURNING id::text, tenant_id::text, node_key, memory_scope, node_type, title, summary,
                      content_hash, privacy_level, sensitivity, confidence, quality_score, source_json,
                      tags_json, review_json, status, COALESCE(created_by_user_id::text, '') AS created_by_user_id,
                      COALESCE(reviewed_by_user_id::text, '') AS reviewed_by_user_id,
                      reviewed_at::text, expires_at::text, created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "node_id": node_id,
            "actor_user_id": actor_user_id,
            "status": clean_status,
            "review_json": _json({"notes": _clean(notes, 1000), "reviewed_at": datetime.now(timezone.utc).isoformat()}),
        },
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail={"code": "memory_node_not_found"})
    node = _row(dict(row))
    _record_memory_access(
        conn,
        tenant_id,
        node_id=node.get("id", ""),
        accessor_id=actor_user_id,
        purpose=f"memory_node_{clean_status}",
        metadata={"node_type": node.get("node_type"), "memory_scope": node.get("memory_scope")},
    )
    record_event(
        conn,
        tenant_id,
        {
            "event_type": "memory.node_reviewed",
            "source": "enterprise_memory_network",
            "entity_type": "memory_node",
            "entity_id": node.get("id", ""),
            "payload_json": {"status": node.get("status"), "node_type": node.get("node_type")},
            "replay_key": f"memory_node:review:{node.get('id')}:{node.get('updated_at')}",
        },
    )
    return node


def delete_memory_node(conn: Connection, tenant_id: str, actor_user_id: str, node_id: str, *, reason: str = "") -> dict[str, Any]:
    ensure_memory_network_tables(conn)
    _require_memory_access(conn, tenant_id, allow_demo=False)
    row = conn.execute(
        text(
            """
            DELETE FROM saas_enterprise_memory_nodes
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:node_id AS uuid)
            RETURNING id::text, tenant_id::text, node_key, memory_scope, node_type, title,
                      privacy_level, sensitivity, status, created_at::text, updated_at::text
            """
        ),
        {"tenant_id": tenant_id, "node_id": node_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail={"code": "memory_node_not_found"})
    node = _row(dict(row))
    _record_memory_access(
        conn,
        tenant_id,
        node_id="",
        accessor_id=actor_user_id,
        purpose="memory_node_delete",
        result_status="deleted",
        metadata={"node_id": node.get("id"), "node_key": node.get("node_key"), "reason": _clean(reason, 1000)},
    )
    record_event(
        conn,
        tenant_id,
        {
            "event_type": "memory.node_deleted",
            "source": "enterprise_memory_network",
            "entity_type": "memory_node",
            "entity_id": node.get("id", ""),
            "payload_json": {"node_key": node.get("node_key"), "reason": _clean(reason, 1000)},
            "replay_key": f"memory_node:delete:{node.get('id')}:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        },
    )
    return node
