from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app_saas.agents.orchestrator import enqueue_orchestration_event, ensure_orchestrator_tables, orchestration_overview
from app_saas.agents.service import (
    AGENT_TEMPLATES,
    AI_PROVIDER_CATALOG,
    PROVIDER_ROUTE_CATALOG,
    TOOL_CATALOG,
    _audit,
    _clean,
    _ensure_governance_tables,
    _json,
    _json_value,
    _uuid,
    create_agent_action_draft,
    get_agent,
    list_agents,
    plan_limits,
)
from app_saas.billing.limits import tenant_entitlements
from app_saas.intelligence.service import ensure_intelligence_tables


AGENT_OS_VERSION = "phase_11_multi_agent_operating_system"
MULTIMODAL_TOOL_CODES = {"media.voice_analyze", "media.vision_analyze", "media.web_image_search"}

REQUIRED_AGENT_TYPES: list[str] = [
    "advisor",
    "sales",
    "crm_intelligence",
    "retention",
    "campaign_strategist",
    "operations",
    "executive_summary",
    "knowledge",
    "workflow_architect",
]

DEFAULT_EVENT_SUBSCRIPTIONS: list[dict[str, Any]] = [
    {"event_type": "lead.hot_detected", "agent_type": "sales", "priority": 88, "mode": "queue"},
    {"event_type": "lead.created", "agent_type": "crm_intelligence", "priority": 62, "mode": "observe"},
    {"event_type": "churn.detected", "agent_type": "retention", "priority": 92, "mode": "queue"},
    {"event_type": "customer.inactive", "agent_type": "retention", "priority": 74, "mode": "queue"},
    {"event_type": "campaign.low_performance", "agent_type": "campaign_strategist", "priority": 78, "mode": "queue"},
    {"event_type": "remarketing.optimization_detected", "agent_type": "campaign_strategist", "priority": 72, "mode": "queue"},
    {"event_type": "webhook.failed", "agent_type": "operations", "priority": 90, "mode": "queue"},
    {"event_type": "operations.anomaly_detected", "agent_type": "operations", "priority": 94, "mode": "queue"},
    {"event_type": "ai.recommendation.generated", "agent_type": "advisor", "priority": 68, "mode": "advise"},
    {"event_type": "workflow.optimization_detected", "agent_type": "workflow_architect", "priority": 76, "mode": "queue"},
]


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _as_dict(value: Any) -> dict[str, Any]:
    parsed = _json_value(value, {}) if isinstance(value, str) else value
    return parsed if isinstance(parsed, dict) else {}


def _as_list(value: Any) -> list[Any]:
    parsed = _json_value(value, []) if isinstance(value, str) else value
    return parsed if isinstance(parsed, list) else []


def _safe_int(value: Any, default: int, *, minimum: int = 1, maximum: int = 10_000) -> int:
    try:
        parsed = int(value if value is not None else default)
    except Exception:
        parsed = default
    return max(minimum, min(parsed, maximum))


def _score100(value: Any) -> float:
    try:
        score = float(value or 0)
    except Exception:
        return 0.0
    if 0 < score <= 1:
        score *= 100
    return max(0.0, min(score, 100.0))


def _row(row: dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    for key in ("payload_json", "metadata_json", "input_json", "output_json", "filters_json", "action_json", "evidence_json"):
        if key in data:
            data[key] = _json_value(data.get(key), {})
    return {key: _jsonable(value) for key, value in data.items()}


def _table_exists(conn: Connection, table_name: str) -> bool:
    return bool(conn.execute(text("SELECT to_regclass(:table_name) IS NOT NULL"), {"table_name": table_name}).scalar())


def _table_count(conn: Connection, table_name: str, tenant_id: str, where_sql: str = "") -> int:
    if not _table_exists(conn, table_name):
        return 0
    sql = f"SELECT COUNT(*)::int FROM {table_name} WHERE tenant_id = CAST(:tenant_id AS uuid) {where_sql}"
    return int(conn.execute(text(sql), {"tenant_id": tenant_id}).scalar() or 0)


def ensure_agent_os_tables(conn: Connection) -> None:
    ensure_orchestrator_tables(conn)
    _ensure_governance_tables(conn)
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_agent_messages (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                source_agent_id UUID NULL REFERENCES saas_ai_agents(id) ON DELETE SET NULL,
                target_agent_id UUID NULL REFERENCES saas_ai_agents(id) ON DELETE SET NULL,
                job_id UUID NULL REFERENCES saas_ai_agent_orchestration_jobs(id) ON DELETE SET NULL,
                message_type TEXT NOT NULL DEFAULT 'context',
                subject TEXT NOT NULL DEFAULT '',
                body TEXT NOT NULL DEFAULT '',
                priority INTEGER NOT NULL DEFAULT 50,
                status TEXT NOT NULL DEFAULT 'open',
                payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_agent_messages_tenant_status ON saas_ai_agent_messages (tenant_id, status, priority DESC, created_at DESC)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_agent_messages_agents ON saas_ai_agent_messages (tenant_id, source_agent_id, target_agent_id, created_at DESC)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_agent_runtime_traces (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                agent_id UUID NULL REFERENCES saas_ai_agents(id) ON DELETE SET NULL,
                job_id UUID NULL REFERENCES saas_ai_agent_orchestration_jobs(id) ON DELETE SET NULL,
                trace_type TEXT NOT NULL DEFAULT 'reasoning',
                trace_status TEXT NOT NULL DEFAULT 'completed',
                step_key TEXT NOT NULL DEFAULT '',
                provider_code TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                latency_ms INTEGER NOT NULL DEFAULT 0,
                tokens_total INTEGER NOT NULL DEFAULT 0,
                input_summary TEXT NOT NULL DEFAULT '',
                output_summary TEXT NOT NULL DEFAULT '',
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_agent_runtime_traces_agent ON saas_ai_agent_runtime_traces (tenant_id, agent_id, created_at DESC)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_agent_runtime_traces_type ON saas_ai_agent_runtime_traces (tenant_id, trace_type, trace_status, created_at DESC)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_agent_tool_runs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                agent_id UUID NOT NULL REFERENCES saas_ai_agents(id) ON DELETE CASCADE,
                action_draft_id UUID NULL REFERENCES saas_advisor_actions(id) ON DELETE SET NULL,
                tool_code TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending_approval',
                approval_status TEXT NOT NULL DEFAULT 'required',
                risk_level TEXT NOT NULL DEFAULT 'medium',
                input_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                output_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                error_text TEXT NOT NULL DEFAULT '',
                created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                completed_at TIMESTAMP NULL
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_agent_tool_runs_agent ON saas_ai_agent_tool_runs (tenant_id, agent_id, status, created_at DESC)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_agent_tool_runs_tool ON saas_ai_agent_tool_runs (tenant_id, tool_code, created_at DESC)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_agent_event_subscriptions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                event_type TEXT NOT NULL,
                agent_type TEXT NOT NULL DEFAULT '',
                target_agent_id UUID NULL REFERENCES saas_ai_agents(id) ON DELETE SET NULL,
                channel TEXT NOT NULL DEFAULT 'global',
                mode TEXT NOT NULL DEFAULT 'queue',
                priority INTEGER NOT NULL DEFAULT 50,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                filters_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, event_type, agent_type, channel)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_agent_event_subscriptions_enabled ON saas_ai_agent_event_subscriptions (tenant_id, enabled, event_type, priority DESC)"))


def seed_agent_os_defaults(conn: Connection, tenant_id: str) -> None:
    ensure_agent_os_tables(conn)
    for item in DEFAULT_EVENT_SUBSCRIPTIONS:
        conn.execute(
            text(
                """
                INSERT INTO saas_ai_agent_event_subscriptions (
                    tenant_id, event_type, agent_type, channel, mode, priority, enabled, filters_json, updated_at
                )
                VALUES (
                    CAST(:tenant_id AS uuid), :event_type, :agent_type, :channel, :mode, :priority, TRUE,
                    CAST(:filters_json AS jsonb), NOW()
                )
                ON CONFLICT (tenant_id, event_type, agent_type, channel)
                DO UPDATE SET
                    mode = EXCLUDED.mode,
                    priority = GREATEST(saas_ai_agent_event_subscriptions.priority, EXCLUDED.priority),
                    filters_json = saas_ai_agent_event_subscriptions.filters_json || EXCLUDED.filters_json,
                    updated_at = NOW()
                """
            ),
            {
                "tenant_id": tenant_id,
                "event_type": item["event_type"],
                "agent_type": item["agent_type"],
                "channel": item.get("channel") or "global",
                "mode": item.get("mode") or "queue",
                "priority": int(item.get("priority") or 50),
                "filters_json": _json(item.get("filters_json") or {}),
            },
        )


def _premium_status(conn: Connection, tenant_id: str) -> dict[str, Any]:
    entitlements = tenant_entitlements(conn, tenant_id)
    features = _as_dict(entitlements.get("features"))
    full = bool(features.get("multi_agent_os") or features.get("event_driven_agents") or features.get("ai_premium"))
    demo = bool(features.get("intelligence_demo") or entitlements.get("tenant_status") == "trial")
    mode = "full" if full else "demo" if demo else "disabled"
    return {
        "mode": mode,
        "enabled": mode == "full",
        "demo_mode": mode == "demo",
        "feature_flags": {
            "ai_agents": bool(features.get("ai_agents")),
            "ai_premium": bool(features.get("ai_premium")),
            "multi_agent_os": bool(features.get("multi_agent_os")),
            "event_driven_agents": bool(features.get("event_driven_agents")),
            "agent_tool_tracing": bool(features.get("agent_tool_tracing")),
            "predictive_recommendations": bool(features.get("predictive_recommendations")),
        },
        "plan": entitlements.get("plan", {}),
    }


def _latest_messages(conn: Connection, tenant_id: str, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT m.id::text, m.source_agent_id::text, m.target_agent_id::text, m.job_id::text,
                   sa.name AS source_agent_name, ta.name AS target_agent_name,
                   m.message_type, m.subject, m.body, m.priority, m.status, m.payload_json,
                   m.created_by_user_id::text, m.created_at::text, m.updated_at::text
            FROM saas_ai_agent_messages m
            LEFT JOIN saas_ai_agents sa ON sa.id = m.source_agent_id AND sa.tenant_id = m.tenant_id
            LEFT JOIN saas_ai_agents ta ON ta.id = m.target_agent_id AND ta.tenant_id = m.tenant_id
            WHERE m.tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY m.created_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "limit": max(1, min(int(limit or 30), 100))},
    ).mappings().all()
    return [_row(dict(item)) for item in rows]


def _latest_traces(conn: Connection, tenant_id: str, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT t.id::text, t.agent_id::text, t.job_id::text, a.name AS agent_name, a.agent_type,
                   t.trace_type, t.trace_status, t.step_key, t.provider_code, t.model,
                   t.latency_ms, t.tokens_total, t.input_summary, t.output_summary,
                   t.metadata_json, t.created_at::text
            FROM saas_ai_agent_runtime_traces t
            LEFT JOIN saas_ai_agents a ON a.id = t.agent_id AND a.tenant_id = t.tenant_id
            WHERE t.tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY t.created_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "limit": max(1, min(int(limit or 30), 100))},
    ).mappings().all()
    return [_row(dict(item)) for item in rows]


def _latest_tool_runs(conn: Connection, tenant_id: str, agent_id: str = "", limit: int = 30) -> list[dict[str, Any]]:
    where_agent = "AND r.agent_id = CAST(:agent_id AS uuid)" if agent_id else ""
    rows = conn.execute(
        text(
            f"""
            SELECT r.id::text, r.agent_id::text, a.name AS agent_name, a.agent_type,
                   r.action_draft_id::text, r.tool_code, r.status, r.approval_status, r.risk_level,
                   r.input_json, r.output_json, r.error_text, r.created_by_user_id::text,
                   r.created_at::text, r.updated_at::text, r.completed_at::text
            FROM saas_ai_agent_tool_runs r
            JOIN saas_ai_agents a ON a.id = r.agent_id AND a.tenant_id = r.tenant_id
            WHERE r.tenant_id = CAST(:tenant_id AS uuid)
              {where_agent}
            ORDER BY r.created_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "agent_id": agent_id or "", "limit": max(1, min(int(limit or 30), 100))},
    ).mappings().all()
    return [_row(dict(item)) for item in rows]


def _subscriptions(conn: Connection, tenant_id: str, limit: int = 100) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT id::text, event_type, agent_type, target_agent_id::text, channel, mode,
                   priority, enabled, filters_json, created_by_user_id::text,
                   created_at::text, updated_at::text
            FROM saas_ai_agent_event_subscriptions
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY enabled DESC, priority DESC, event_type ASC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "limit": max(1, min(int(limit or 100), 200))},
    ).mappings().all()
    return [_row(dict(item)) for item in rows]


def _memory_layers(conn: Connection, tenant_id: str) -> dict[str, Any]:
    return {
        "short_term": {
            "status": "enabled",
            "source": "saas_conversation_memory",
            "records": _table_count(conn, "saas_conversation_memory", tenant_id),
        },
        "long_term": {
            "status": "enabled",
            "source": "saas_ai_agent_memory_archives",
            "records": _table_count(conn, "saas_ai_agent_memory_archives", tenant_id),
        },
        "semantic": {
            "status": "enabled" if _table_exists(conn, "saas_knowledge_chunks") else "not_initialized",
            "source": "saas_knowledge_chunks",
            "records": _table_count(conn, "saas_knowledge_chunks", tenant_id),
            "vectorized": _table_count(conn, "saas_knowledge_chunks", tenant_id, "AND vector_json <> '{}'::jsonb") if _table_exists(conn, "saas_knowledge_chunks") else 0,
        },
        "episodic": {
            "status": "enabled",
            "source": "agent_events_orchestration_jobs_tool_runs",
            "records": (
                _table_count(conn, "saas_ai_agent_events", tenant_id)
                + _table_count(conn, "saas_ai_agent_orchestration_jobs", tenant_id)
                + _table_count(conn, "saas_ai_agent_tool_runs", tenant_id)
            ),
        },
        "collective": {
            "status": "enabled",
            "source": "saas_ai_agent_collective_memory",
            "records": _table_count(conn, "saas_ai_agent_collective_memory", tenant_id),
        },
        "multimodal": {
            "status": "enabled" if _table_exists(conn, "saas_multimodal_memory_events") else "not_initialized",
            "source": "saas_multimodal_memory_events",
            "records": _table_count(conn, "saas_multimodal_memory_events", tenant_id),
            "training_ready": _table_count(conn, "saas_multimodal_memory_events", tenant_id, "AND eligible_for_training = TRUE"),
            "rag_candidates": _table_count(conn, "saas_multimodal_memory_events", tenant_id, "AND eligible_for_rag = TRUE"),
        },
    }


def multi_agent_os_overview(conn: Connection, tenant_id: str, *, limit: int = 30) -> dict[str, Any]:
    ensure_agent_os_tables(conn)
    seed_agent_os_defaults(conn, tenant_id)
    agents = list_agents(conn, tenant_id)
    active_agents = [item for item in agents if item.get("status") == "active"]
    active_types = {str(item.get("agent_type") or "") for item in active_agents}
    coverage = [
        {
            "agent_type": agent_type,
            "label": str((AGENT_TEMPLATES.get(agent_type) or {}).get("name") or agent_type),
            "active": agent_type in active_types,
            "configured": any(str(item.get("agent_type") or "") == agent_type and item.get("status") != "archived" for item in agents),
        }
        for agent_type in REQUIRED_AGENT_TYPES
    ]
    counts = conn.execute(
        text(
            """
            SELECT
              (SELECT COUNT(*)::int FROM saas_ai_agents WHERE tenant_id = CAST(:tenant_id AS uuid) AND status = 'active') AS active_agents,
              (SELECT COUNT(*)::int FROM saas_ai_agents WHERE tenant_id = CAST(:tenant_id AS uuid) AND is_custom = TRUE AND status <> 'archived') AS custom_agents,
              (SELECT COUNT(*)::int FROM saas_ai_agent_messages WHERE tenant_id = CAST(:tenant_id AS uuid) AND created_at >= NOW() - INTERVAL '7 days') AS messages_7d,
              (SELECT COUNT(*)::int FROM saas_ai_agent_tool_runs WHERE tenant_id = CAST(:tenant_id AS uuid) AND created_at >= NOW() - INTERVAL '7 days') AS tool_runs_7d,
              (SELECT COUNT(*)::int FROM saas_ai_agent_tool_runs WHERE tenant_id = CAST(:tenant_id AS uuid) AND tool_code IN ('media.voice_analyze', 'media.vision_analyze', 'media.web_image_search') AND created_at >= NOW() - INTERVAL '7 days') AS multimodal_tool_runs_7d,
              (SELECT COUNT(*)::int FROM saas_ai_agent_tool_runs WHERE tenant_id = CAST(:tenant_id AS uuid) AND status = 'pending_approval') AS pending_tool_runs,
              (SELECT COUNT(*)::int FROM saas_ai_agent_runtime_traces WHERE tenant_id = CAST(:tenant_id AS uuid) AND created_at >= NOW() - INTERVAL '7 days') AS traces_7d,
              (SELECT COUNT(*)::int FROM saas_ai_agent_event_subscriptions WHERE tenant_id = CAST(:tenant_id AS uuid) AND enabled = TRUE) AS active_subscriptions
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    counts_data = {key: int(value or 0) for key, value in dict(counts or {}).items()}
    counts_data["multimodal_memory_events"] = _table_count(conn, "saas_multimodal_memory_events", tenant_id)
    counts_data["multimodal_training_events"] = _table_count(conn, "saas_multimodal_memory_events", tenant_id, "AND eligible_for_training = TRUE")
    counts_data["multimodal_rag_candidates"] = _table_count(conn, "saas_multimodal_memory_events", tenant_id, "AND eligible_for_rag = TRUE")
    premium = _premium_status(conn, tenant_id)
    orchestrator = orchestration_overview(conn, tenant_id, limit=limit)
    return {
        "version": AGENT_OS_VERSION,
        "tenant_id": tenant_id,
        "premium": premium,
        "counts": counts_data,
        "coverage": coverage,
        "readiness": {
            "score": round((sum(1 for item in coverage if item["active"]) / max(1, len(coverage))) * 100),
            "missing_core_agents": [item["agent_type"] for item in coverage if not item["active"]],
            "single_ai_owner": "enabled",
            "human_approval": "required_for_tool_runs",
            "runtime_mode": "full" if premium["enabled"] else premium["mode"],
        },
        "memory_layers": _memory_layers(conn, tenant_id),
        "communication": {
            "messages": _latest_messages(conn, tenant_id, limit=limit),
            "patterns": ["delegation", "context_share", "handoff", "risk_alert", "recommendation"],
        },
        "tooling": {
            "catalog": TOOL_CATALOG,
            "multimodal_tools": [item for item in TOOL_CATALOG if str(item.get("code") or "").lower() in MULTIMODAL_TOOL_CODES],
            "recent_runs": _latest_tool_runs(conn, tenant_id, limit=limit),
            "policy": "trace_or_action_draft_only_until_human_approval",
            "multimodal_policy": "read_only_agent_tools_reuse_voice_vision_search_with_no_customer_send",
            "multimodal_memory": {
                "source": "saas_multimodal_memory_events",
                "events": counts_data["multimodal_memory_events"],
                "training_events": counts_data["multimodal_training_events"],
                "rag_candidates": counts_data["multimodal_rag_candidates"],
                "policy": "manual_materialization_for_rag_or_collective_memory",
            },
        },
        "event_driven": {
            "enabled": premium["enabled"],
            "demo_mode": premium["demo_mode"],
            "subscriptions": _subscriptions(conn, tenant_id),
            "source": "saas_intelligence_predictions_and_recommendations",
        },
        "observability": {
            "traces": _latest_traces(conn, tenant_id, limit=limit),
            "metrics": ["latency_ms", "tokens_total", "tool_status", "approval_status", "job_status"],
        },
        "governance": {
            "tenant_isolation": "tenant_id_required_on_all_agent_os_tables",
            "tool_execution": "no_direct_side_effects_from_agent_os",
            "approval": "advisor_action_drafts_for_sensitive_tools",
            "audit": "saas_ai_agent_events_and_runtime_traces",
        },
        "model_routing": {
            "routes": PROVIDER_ROUTE_CATALOG,
            "providers": AI_PROVIDER_CATALOG,
            "recommended": {
                "google": "summaries_advisor_insights",
                "kimi": "deep_reasoning_strategic_analysis",
                "mistral": "fast_classification_low_cost",
                "openrouter": "fallback_dynamic_provider",
            },
        },
        "orchestrator": orchestrator,
        "limits": plan_limits(conn, tenant_id),
    }


def list_agent_os_messages(conn: Connection, tenant_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    ensure_agent_os_tables(conn)
    return _latest_messages(conn, tenant_id, limit=limit)


def create_agent_os_message(conn: Connection, tenant_id: str, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    ensure_agent_os_tables(conn)
    source_agent_id = _clean(payload.get("source_agent_id"), 80)
    target_agent_id = _clean(payload.get("target_agent_id"), 80)
    if source_agent_id:
        get_agent(conn, tenant_id, source_agent_id)
    if target_agent_id:
        get_agent(conn, tenant_id, target_agent_id)
    message_type = _clean(payload.get("message_type"), 80).lower() or "context"
    if message_type not in {"context", "delegation", "handoff", "risk_alert", "recommendation", "observation"}:
        message_type = "context"
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_agent_messages (
                tenant_id, source_agent_id, target_agent_id, message_type, subject, body,
                priority, status, payload_json, created_by_user_id, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid),
                CAST(NULLIF(:source_agent_id, '') AS uuid),
                CAST(NULLIF(:target_agent_id, '') AS uuid),
                :message_type,
                :subject,
                :body,
                :priority,
                'open',
                CAST(:payload_json AS jsonb),
                CAST(NULLIF(:created_by_user_id, '') AS uuid),
                NOW()
            )
            RETURNING id::text, source_agent_id::text, target_agent_id::text, job_id::text,
                      message_type, subject, body, priority, status, payload_json,
                      created_by_user_id::text, created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "source_agent_id": source_agent_id,
            "target_agent_id": target_agent_id,
            "message_type": message_type,
            "subject": _clean(payload.get("subject"), 180),
            "body": _clean(payload.get("body"), 4000),
            "priority": max(1, min(int(payload.get("priority") or 50), 100)),
            "payload_json": _json(payload.get("payload_json") if isinstance(payload.get("payload_json"), dict) else {}),
            "created_by_user_id": user_id or "",
        },
    ).mappings().first()
    message = _row(dict(row))
    _audit(
        conn,
        tenant_id=tenant_id,
        agent_id=source_agent_id or target_agent_id or None,
        actor_user_id=user_id,
        event_type="agent.os_message_created",
        summary=f"Mensaje Agent OS creado: {message['subject'] or message['message_type']}",
        details={"message_id": message["id"], "target_agent_id": target_agent_id, "message_type": message_type},
    )
    return message


def list_agent_tool_runs(conn: Connection, tenant_id: str, agent_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    ensure_agent_os_tables(conn)
    get_agent(conn, tenant_id, agent_id)
    return _latest_tool_runs(conn, tenant_id, agent_id=agent_id, limit=limit)


def create_agent_tool_run(conn: Connection, tenant_id: str, user_id: str, agent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    ensure_agent_os_tables(conn)
    agent = get_agent(conn, tenant_id, agent_id)
    tool_code = _clean(payload.get("tool_code"), 120).lower()
    if not tool_code:
        raise HTTPException(status_code=400, detail={"code": "tool_code_required"})
    catalog_codes = {str(item.get("code") or "").lower() for item in TOOL_CATALOG}
    if tool_code not in catalog_codes:
        raise HTTPException(status_code=400, detail={"code": "unknown_tool_code", "tool_code": tool_code})
    allowed_tools = {str(item or "").strip().lower() for item in _as_list(agent.get("tools_json"))}
    if allowed_tools and tool_code not in allowed_tools:
        raise HTTPException(status_code=403, detail={"code": "agent_tool_not_allowed", "tool_code": tool_code, "agent_id": agent_id})
    risk_level = _clean(payload.get("risk_level"), 40).lower() or "medium"
    if risk_level not in {"low", "medium", "high", "critical"}:
        risk_level = "medium"
    action = None
    if bool(payload.get("create_action_draft", True)):
        action = create_agent_action_draft(
            conn,
            tenant_id,
            user_id,
            agent_id,
            {
                "title": _clean(payload.get("title"), 180) or f"Tool call pendiente: {tool_code}",
                "description": _clean(payload.get("description"), 1200) or "Solicitud de herramienta generada desde Agent OS para revision humana.",
                "tool_code": tool_code,
                "action_type": tool_code,
                "target_module": tool_code.split(".", 1)[0],
                "impact": payload.get("impact") or "medium",
                "risk_level": risk_level,
                "payload_json": {
                    "agent_os_tool_run": True,
                    "input": payload.get("input_json") if isinstance(payload.get("input_json"), dict) else {},
                },
            },
        )
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_agent_tool_runs (
                tenant_id, agent_id, action_draft_id, tool_code, status, approval_status,
                risk_level, input_json, output_json, created_by_user_id, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), CAST(:agent_id AS uuid),
                CAST(NULLIF(:action_draft_id, '') AS uuid), :tool_code,
                'pending_approval', 'required', :risk_level,
                CAST(:input_json AS jsonb), CAST(:output_json AS jsonb),
                CAST(NULLIF(:created_by_user_id, '') AS uuid), NOW()
            )
            RETURNING id::text, agent_id::text, action_draft_id::text, tool_code, status,
                      approval_status, risk_level, input_json, output_json, error_text,
                      created_by_user_id::text, created_at::text, updated_at::text, completed_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "action_draft_id": (action or {}).get("id", ""),
            "tool_code": tool_code,
            "risk_level": risk_level,
            "input_json": _json(payload.get("input_json") if isinstance(payload.get("input_json"), dict) else {}),
            "output_json": _json({"state": "awaiting_human_approval", "action_draft_id": (action or {}).get("id", "")}),
            "created_by_user_id": user_id or "",
        },
    ).mappings().first()
    tool_run = _row(dict(row))
    _audit(
        conn,
        tenant_id=tenant_id,
        agent_id=agent_id,
        actor_user_id=user_id,
        event_type="agent.tool_run_requested",
        summary=f"Tool run pendiente de aprobacion: {tool_code}",
        details={"tool_run_id": tool_run["id"], "tool_code": tool_code, "action_draft_id": tool_run.get("action_draft_id", "")},
    )
    return {"tool_run": tool_run, "action": action}


def _prediction_candidates(conn: Connection, tenant_id: str, *, limit: int, lookback_days: int) -> list[dict[str, Any]]:
    ensure_intelligence_tables(conn)
    rows = conn.execute(
        text(
            """
            SELECT id::text, subject_type, subject_id, prediction_type, model_key, model_version,
                   mode, score, label, confidence, status, explanation_json, output_json, created_at::text
            FROM saas_intelligence_predictions
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND status = 'ready'
              AND created_at >= NOW() - (:lookback_days * INTERVAL '1 day')
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "limit": max(1, min(int(limit or 50), 250)), "lookback_days": max(1, min(int(lookback_days or 7), 90))},
    ).mappings().all()
    candidates: list[dict[str, Any]] = []
    for raw in rows:
        item = _row(dict(raw))
        prediction_type = str(item.get("prediction_type") or "")
        score = _score100(item.get("score"))
        label = str(item.get("label") or "").lower()
        output = _as_dict(item.get("output_json"))
        subject_type = str(item.get("subject_type") or "tenant")
        subject_id = str(item.get("subject_id") or tenant_id)
        candidate: dict[str, Any] | None = None
        if prediction_type == "lead_scoring" and (score >= 70 or label in {"hot", "high", "hot_lead"}):
            candidate = {
                "event_type": "lead.hot_detected",
                "entity_type": subject_type,
                "entity_id": subject_id,
                "priority": max(70, min(98, round(score))),
                "target_agent_type": "sales",
                "summary": f"Lead caliente detectado ({round(score)}).",
            }
        elif prediction_type == "churn_prediction" and (score >= 65 or label in {"high", "critical", "risk"}):
            candidate = {
                "event_type": "churn.detected",
                "entity_type": subject_type,
                "entity_id": subject_id,
                "priority": max(75, min(99, round(score))),
                "target_agent_type": "retention",
                "summary": f"Riesgo de abandono detectado ({round(score)}).",
            }
        elif prediction_type == "smart_remarketing" and score >= 55:
            candidate = {
                "event_type": "remarketing.optimization_detected",
                "entity_type": subject_type,
                "entity_id": subject_id,
                "priority": max(60, min(92, round(score))),
                "target_agent_type": "campaign_strategist",
                "summary": f"Oportunidad de remarketing detectada ({round(score)}).",
            }
        elif prediction_type == "operational_anomaly" and (score >= 50 or label in {"warning", "critical", "anomaly"}):
            candidate = {
                "event_type": "operations.anomaly_detected",
                "entity_type": subject_type,
                "entity_id": subject_id,
                "priority": max(82, min(100, round(score))),
                "target_agent_type": "operations",
                "summary": f"Anomalia operacional detectada ({round(score)}).",
            }
        if candidate:
            candidate["channel"] = _clean(output.get("best_channel") or output.get("channel"), 40).lower() or "global"
            candidate["payload_json"] = {"prediction": item, "source": "intelligence_engine", "agent_os": True}
            candidates.append(candidate)
    return candidates


def _recommendation_candidates(conn: Connection, tenant_id: str, *, limit: int, lookback_days: int) -> list[dict[str, Any]]:
    ensure_intelligence_tables(conn)
    rows = conn.execute(
        text(
            """
            SELECT id::text, recommendation_type, source_prediction_id::text, title, description,
                   severity, confidence, action_json, evidence_json, status, created_at::text, updated_at::text
            FROM saas_intelligence_recommendations
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND status = 'open'
              AND created_at >= NOW() - (:lookback_days * INTERVAL '1 day')
            ORDER BY updated_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "limit": max(1, min(int(limit or 50), 250)), "lookback_days": max(1, min(int(lookback_days or 7), 90))},
    ).mappings().all()
    severity_priority = {"critical": 96, "warning": 84, "high": 88, "medium": 72, "info": 58, "low": 45}
    target_by_type = {
        "lead_scoring": "sales",
        "churn_prediction": "retention",
        "smart_remarketing": "campaign_strategist",
        "operational_anomaly": "operations",
    }
    candidates: list[dict[str, Any]] = []
    for raw in rows:
        item = _row(dict(raw))
        rec_type = str(item.get("recommendation_type") or "")
        severity = str(item.get("severity") or "info").lower()
        candidates.append(
            {
                "event_type": "ai.recommendation.generated",
                "entity_type": "recommendation",
                "entity_id": str(item.get("id") or ""),
                "channel": "global",
                "priority": severity_priority.get(severity, 60),
                "target_agent_type": target_by_type.get(rec_type, "advisor"),
                "summary": str(item.get("title") or "Recomendacion predictiva"),
                "payload_json": {"recommendation": item, "source": "intelligence_engine", "agent_os": True},
            }
        )
    return candidates


def _recent_job_exists(conn: Connection, tenant_id: str, candidate: dict[str, Any]) -> bool:
    return bool(
        conn.execute(
            text(
                """
                SELECT 1
                FROM saas_ai_agent_orchestration_jobs
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND source = 'agent_os'
                  AND event_type = :event_type
                  AND entity_type = :entity_type
                  AND entity_id = :entity_id
                  AND created_at >= NOW() - INTERVAL '7 days'
                LIMIT 1
                """
            ),
            {
                "tenant_id": tenant_id,
                "event_type": candidate.get("event_type") or "",
                "entity_type": candidate.get("entity_type") or "",
                "entity_id": candidate.get("entity_id") or "",
            },
        ).first()
    )


def _trace_event_sync(conn: Connection, tenant_id: str, result: dict[str, Any]) -> None:
    conn.execute(
        text(
            """
            INSERT INTO saas_ai_agent_runtime_traces (
                tenant_id, trace_type, trace_status, step_key, input_summary, output_summary, metadata_json
            )
            VALUES (
                CAST(:tenant_id AS uuid), 'event_sync', :trace_status, 'intelligence_to_agent_os',
                :input_summary, :output_summary, CAST(:metadata_json AS jsonb)
            )
            """
        ),
        {
            "tenant_id": tenant_id,
            "trace_status": "completed" if not result.get("errors") else "warning",
            "input_summary": f"{result.get('candidates', 0)} candidates from intelligence",
            "output_summary": f"{result.get('created', 0)} orchestration jobs created",
            "metadata_json": _json(result),
        },
    )


def sync_event_driven_agent_jobs(
    conn: Connection,
    tenant_id: str,
    *,
    limit: int = 50,
    lookback_days: int = 7,
    dry_run: bool = False,
    source: str = "manual",
) -> dict[str, Any]:
    ensure_agent_os_tables(conn)
    seed_agent_os_defaults(conn, tenant_id)
    premium = _premium_status(conn, tenant_id)
    safe_limit = _safe_int(limit, 50, minimum=1, maximum=250)
    candidates = [
        *_prediction_candidates(conn, tenant_id, limit=safe_limit, lookback_days=lookback_days),
        *_recommendation_candidates(conn, tenant_id, limit=safe_limit, lookback_days=lookback_days),
    ][:safe_limit]
    effective_dry_run = bool(dry_run or not premium["enabled"])
    created = 0
    skipped = {"dry_run": 0, "duplicate": 0}
    jobs: list[dict[str, Any]] = []
    errors: list[str] = []
    for candidate in candidates:
        try:
            if effective_dry_run:
                skipped["dry_run"] += 1
                continue
            if _recent_job_exists(conn, tenant_id, candidate):
                skipped["duplicate"] += 1
                continue
            payload = _as_dict(candidate.get("payload_json"))
            payload.update(
                {
                    "summary": candidate.get("summary") or "",
                    "target_agent_type": candidate.get("target_agent_type") or "",
                    "agent_os_source": source,
                }
            )
            result = enqueue_orchestration_event(
                conn,
                tenant_id,
                source="agent_os",
                event_type=str(candidate.get("event_type") or "ai.recommendation.generated"),
                entity_type=str(candidate.get("entity_type") or "intelligence"),
                entity_id=str(candidate.get("entity_id") or _uuid()),
                channel=str(candidate.get("channel") or "global"),
                payload=payload,
                priority=max(1, min(int(candidate.get("priority") or 60), 100)),
            )
            if result.get("created"):
                created += 1
            jobs.append(result.get("job") or {})
        except Exception as exc:
            errors.append(str(exc)[:500])
    result = {
        "mode": premium["mode"],
        "dry_run": effective_dry_run,
        "candidates": len(candidates),
        "created": created,
        "skipped": skipped,
        "jobs": jobs[:20],
        "errors": errors[:5],
    }
    if not effective_dry_run:
        _trace_event_sync(conn, tenant_id, result)
    return result
