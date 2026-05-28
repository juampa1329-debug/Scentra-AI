from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app_saas.intelligence.service import (
    ensure_intelligence_tables,
    intelligence_feature_state,
    list_feature_values,
    list_model_metrics,
    list_predictions,
    list_recommendations,
    record_intelligence_usage,
    resolve_intelligence_access,
)

BASE_FEATURE = "realtime_intelligence_layer"
STREAM_FEATURE = "realtime_event_stream"
ALERTS_FEATURE = "realtime_ai_alerts"
DASHBOARD_FEATURE = "realtime_intelligence_dashboard"

SENSITIVE_PAYLOAD_FRAGMENTS = (
    "body",
    "content",
    "email",
    "message",
    "password",
    "phone",
    "secret",
    "text",
    "token",
)


def _clean(value: Any, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _rows(rows: Any) -> list[dict[str, Any]]:
    return [_json_safe(dict(row)) for row in rows]


def _safe_payload(value: Any) -> dict[str, Any]:
    raw = _json_object(value)
    safe: dict[str, Any] = {}
    for key, item in list(raw.items())[:32]:
        clean_key = str(key or "")[:120]
        lowered = clean_key.lower()
        if any(fragment in lowered for fragment in SENSITIVE_PAYLOAD_FRAGMENTS):
            safe[clean_key] = "[redacted]"
            continue
        if isinstance(item, (dict, list)):
            safe[clean_key] = {"type": type(item).__name__, "size": len(item)}
        else:
            safe[clean_key] = _clean(item, 180)
    return safe


def ensure_realtime_tables(conn: Connection) -> None:
    ensure_intelligence_tables(conn)
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_realtime_intelligence_sessions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                user_id UUID NOT NULL REFERENCES saas_users(id) ON DELETE CASCADE,
                session_key TEXT NOT NULL,
                channel TEXT NOT NULL DEFAULT 'tenant',
                status TEXT NOT NULL DEFAULT 'active',
                last_event_id TEXT NOT NULL DEFAULT '',
                filters_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                client_meta_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                connected_at TIMESTAMP NOT NULL DEFAULT NOW(),
                last_seen_at TIMESTAMP NOT NULL DEFAULT NOW(),
                closed_at TIMESTAMP NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, user_id, session_key)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_realtime_sessions_tenant_status ON saas_realtime_intelligence_sessions (tenant_id, status, last_seen_at DESC)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_realtime_sessions_user ON saas_realtime_intelligence_sessions (tenant_id, user_id, updated_at DESC)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_realtime_intelligence_cursors (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                user_id UUID NOT NULL REFERENCES saas_users(id) ON DELETE CASCADE,
                cursor_key TEXT NOT NULL DEFAULT 'default',
                last_event_id TEXT NOT NULL DEFAULT '',
                last_event_at TIMESTAMP NULL,
                filters_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                last_seen_at TIMESTAMP NOT NULL DEFAULT NOW(),
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, user_id, cursor_key)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_realtime_cursors_tenant_user ON saas_realtime_intelligence_cursors (tenant_id, user_id, updated_at DESC)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_realtime_intelligence_metrics (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                metric_key TEXT NOT NULL,
                metric_value NUMERIC(18,6) NOT NULL DEFAULT 0,
                window_seconds INTEGER NOT NULL DEFAULT 900,
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                measured_at TIMESTAMP NOT NULL DEFAULT NOW(),
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_realtime_metrics_tenant_key_time ON saas_realtime_intelligence_metrics (tenant_id, metric_key, measured_at DESC)"))


def _table_exists(conn: Connection, table_name: str) -> bool:
    return bool(conn.execute(text("SELECT to_regclass(:table_name) IS NOT NULL"), {"table_name": table_name}).scalar())


def _optional_access(conn: Connection, tenant_id: str, feature_key: str, *, allow_demo: bool = True) -> dict[str, Any]:
    try:
        return dict(resolve_intelligence_access(conn, tenant_id, feature_key, allow_demo=allow_demo))
    except HTTPException:
        return {
            "key": feature_key,
            "enabled": False,
            "mode": "disabled",
            "quota_monthly": 0,
            "quota_used": 0,
            "source": "disabled",
        }


def _access_bundle(conn: Connection, tenant_id: str) -> dict[str, Any]:
    base = resolve_intelligence_access(conn, tenant_id, BASE_FEATURE, allow_demo=True)
    return {
        "base": dict(base),
        "dashboard": _optional_access(conn, tenant_id, DASHBOARD_FEATURE, allow_demo=True),
        "stream": _optional_access(conn, tenant_id, STREAM_FEATURE, allow_demo=True),
        "alerts": _optional_access(conn, tenant_id, ALERTS_FEATURE, allow_demo=True),
        "mode": str(base.get("mode") or "disabled"),
    }


def list_realtime_events(conn: Connection, tenant_id: str, *, limit: int = 60, since_event_id: str = "") -> list[dict[str, Any]]:
    ensure_realtime_tables(conn)
    params: dict[str, Any] = {"tenant_id": tenant_id, "limit": max(1, min(int(limit or 60), 200))}
    where = ["tenant_id = CAST(:tenant_id AS uuid)"]
    clean_since = _clean(since_event_id, 80)
    if clean_since:
        since_at = conn.execute(
            text(
                """
                SELECT occurred_at
                FROM saas_intelligence_events
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id::text = :since_event_id
                LIMIT 1
                """
            ),
            {"tenant_id": tenant_id, "since_event_id": clean_since},
        ).scalar()
        if since_at:
            where.append("occurred_at > CAST(:since_at AS timestamp)")
            params["since_at"] = since_at
    rows = conn.execute(
        text(
            f"""
            SELECT id::text, event_type, source, channel, entity_type, entity_id,
                   COALESCE(conversation_id::text, '') AS conversation_id,
                   customer_key, occurred_at::text, correlation_id, replay_key,
                   payload_json, created_at::text
            FROM saas_intelligence_events
            WHERE {" AND ".join(where)}
            ORDER BY occurred_at DESC, created_at DESC
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()
    events = _rows(rows)
    for event in events:
        event["payload_json"] = _safe_payload(event.get("payload_json"))
    return events


def _current_cursor(conn: Connection, tenant_id: str, user_id: str, *, cursor_key: str = "default") -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            SELECT id::text, cursor_key, last_event_id, last_event_at::text,
                   filters_json, last_seen_at::text, updated_at::text
            FROM saas_realtime_intelligence_cursors
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND user_id = CAST(:user_id AS uuid)
              AND cursor_key = :cursor_key
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "user_id": user_id, "cursor_key": _clean(cursor_key, 80) or "default"},
    ).mappings().first()
    return _json_safe(dict(row)) if row else {"cursor_key": cursor_key, "last_event_id": "", "last_event_at": "", "filters_json": {}}


def _live_metrics(conn: Connection, tenant_id: str) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            SELECT
                COALESCE((SELECT COUNT(*)::int FROM saas_intelligence_events e WHERE e.tenant_id = CAST(:tenant_id AS uuid) AND e.occurred_at >= NOW() - INTERVAL '15 minutes'), 0) AS events_15m,
                COALESCE((SELECT COUNT(*)::int FROM saas_intelligence_events e WHERE e.tenant_id = CAST(:tenant_id AS uuid) AND e.occurred_at >= NOW() - INTERVAL '1 hour'), 0) AS events_1h,
                COALESCE((SELECT COUNT(*)::int FROM saas_intelligence_predictions p WHERE p.tenant_id = CAST(:tenant_id AS uuid) AND p.created_at >= NOW() - INTERVAL '1 hour'), 0) AS predictions_1h,
                COALESCE((SELECT COUNT(*)::int FROM saas_intelligence_recommendations r WHERE r.tenant_id = CAST(:tenant_id AS uuid) AND r.status = 'open'), 0) AS open_recommendations,
                COALESCE((SELECT COUNT(*)::int FROM saas_realtime_intelligence_sessions s WHERE s.tenant_id = CAST(:tenant_id AS uuid) AND s.status = 'active' AND s.last_seen_at >= NOW() - INTERVAL '5 minutes'), 0) AS active_sessions,
                COALESCE((SELECT MAX(occurred_at)::text FROM saas_intelligence_events e WHERE e.tenant_id = CAST(:tenant_id AS uuid)), '') AS latest_event_at,
                COALESCE((SELECT MAX(created_at)::text FROM saas_intelligence_predictions p WHERE p.tenant_id = CAST(:tenant_id AS uuid)), '') AS latest_prediction_at,
                COALESCE((SELECT MAX(updated_at)::text FROM saas_intelligence_recommendations r WHERE r.tenant_id = CAST(:tenant_id AS uuid)), '') AS latest_recommendation_at
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first() or {}
    metrics = _json_safe(dict(row))
    if _table_exists(conn, "saas_ai_operation_anomalies"):
        ops = conn.execute(
            text(
                """
                SELECT COUNT(*) FILTER (WHERE status = 'open')::int AS open_anomalies,
                       COUNT(*) FILTER (WHERE status = 'open' AND severity IN ('high','critical'))::int AS high_anomalies
                FROM saas_ai_operation_anomalies
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().first() or {}
        metrics.update(_json_safe(dict(ops)))
    else:
        metrics.update({"open_anomalies": 0, "high_anomalies": 0})
    if _table_exists(conn, "saas_ai_governance_incidents"):
        trust = conn.execute(
            text(
                """
                SELECT COUNT(*) FILTER (WHERE status IN ('open','investigating'))::int AS open_trust_incidents,
                       COUNT(*) FILTER (WHERE status IN ('open','investigating') AND severity IN ('high','critical'))::int AS high_trust_incidents
                FROM saas_ai_governance_incidents
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().first() or {}
        metrics.update(_json_safe(dict(trust)))
    else:
        metrics.update({"open_trust_incidents": 0, "high_trust_incidents": 0})
    high = int(metrics.get("high_anomalies") or 0) + int(metrics.get("high_trust_incidents") or 0)
    metrics["status"] = "critical" if high else ("watch" if int(metrics.get("open_recommendations") or 0) else "ok")
    return metrics


def _event_type_counts(conn: Connection, tenant_id: str, *, window_minutes: int = 60) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT event_type, COUNT(*)::int AS total,
                   MAX(occurred_at)::text AS latest_at
            FROM saas_intelligence_events
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND occurred_at >= NOW() - (:window_minutes * INTERVAL '1 minute')
            GROUP BY event_type
            ORDER BY total DESC, latest_at DESC
            LIMIT 20
            """
        ),
        {"tenant_id": tenant_id, "window_minutes": max(5, min(int(window_minutes or 60), 1440))},
    ).mappings().all()
    return _rows(rows)


def _recent_operations(conn: Connection, tenant_id: str, *, limit: int) -> dict[str, Any]:
    if not _table_exists(conn, "saas_ai_operation_anomalies"):
        return {"anomalies": [], "actions": []}
    anomalies = conn.execute(
        text(
            """
            SELECT id::text, anomaly_type, source, entity_type, entity_id, severity,
                   confidence, status, title, description, recommended_playbook_key,
                   last_seen_at::text, updated_at::text
            FROM saas_ai_operation_anomalies
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND status = 'open'
            ORDER BY CASE severity WHEN 'critical' THEN 4 WHEN 'high' THEN 3 WHEN 'warning' THEN 2 ELSE 1 END DESC,
                     last_seen_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "limit": max(1, min(int(limit or 30), 80))},
    ).mappings().all()
    actions = []
    if _table_exists(conn, "saas_ai_operation_actions"):
        actions = conn.execute(
            text(
                """
                SELECT id::text, anomaly_id::text, playbook_key, action_type, title,
                       description, risk_level, status, approval_required, autonomy_level,
                       confidence, created_at::text, updated_at::text
                FROM saas_ai_operation_actions
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND status IN ('suggested','pending_approval','approved')
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            {"tenant_id": tenant_id, "limit": max(1, min(int(limit or 30), 80))},
        ).mappings().all()
    return {"anomalies": _rows(anomalies), "actions": _rows(actions)}


def _recent_trust(conn: Connection, tenant_id: str, *, limit: int) -> dict[str, Any]:
    if not _table_exists(conn, "saas_ai_governance_incidents"):
        return {"incidents": [], "risks": []}
    incidents = conn.execute(
        text(
            """
            SELECT id::text, incident_type, severity, status, title,
                   description AS summary, created_at::text AS detected_at,
                   updated_at::text
            FROM saas_ai_governance_incidents
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND status IN ('open','investigating','mitigating')
            ORDER BY CASE severity WHEN 'critical' THEN 4 WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END DESC,
                     updated_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "limit": max(1, min(int(limit or 20), 50))},
    ).mappings().all()
    risks = []
    if _table_exists(conn, "saas_ai_risk_assessments"):
        risks = conn.execute(
            text(
                """
                SELECT id::text, entity_type AS scope, risk_level, status, title,
                       COALESCE(findings_json::text, '') AS summary,
                       score AS confidence, reviewed_at::text, updated_at::text
                FROM saas_ai_risk_assessments
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND status IN ('open','needs_review','mitigating')
                ORDER BY CASE risk_level WHEN 'critical' THEN 4 WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END DESC,
                         updated_at DESC
                LIMIT :limit
                """
            ),
            {"tenant_id": tenant_id, "limit": max(1, min(int(limit or 20), 50))},
        ).mappings().all()
    return {"incidents": _rows(incidents), "risks": _rows(risks)}


def _build_alerts(
    *,
    recommendations: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    operations: dict[str, Any],
    trust: dict[str, Any],
    metrics: dict[str, Any],
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    for item in recommendations:
        if str(item.get("severity") or "").lower() in {"high", "critical", "warning"}:
            alerts.append(
                {
                    "kind": "recommendation",
                    "severity": item.get("severity") or "info",
                    "title": item.get("title") or "Recomendacion abierta",
                    "description": item.get("description") or "",
                    "source_id": item.get("id") or "",
                    "created_at": item.get("updated_at") or item.get("created_at") or "",
                }
            )
    for item in predictions:
        label = str(item.get("label") or "").lower()
        if label in {"hot", "high_risk", "degraded", "critical"} or float(item.get("score") or 0) >= 80:
            alerts.append(
                {
                    "kind": "prediction",
                    "severity": "warning" if label != "critical" else "critical",
                    "title": f"{item.get('prediction_type') or 'prediction'}: {item.get('label') or 'senal'}",
                    "description": f"Score {float(item.get('score') or 0):.1f} / confianza {float(item.get('confidence') or 0):.1f}",
                    "source_id": item.get("id") or "",
                    "created_at": item.get("created_at") or "",
                }
            )
    for item in operations.get("anomalies", []):
        alerts.append(
            {
                "kind": "operation_anomaly",
                "severity": item.get("severity") or "warning",
                "title": item.get("title") or "Anomalia operacional",
                "description": item.get("description") or "",
                "source_id": item.get("id") or "",
                "created_at": item.get("last_seen_at") or item.get("updated_at") or "",
            }
        )
    for item in trust.get("incidents", []):
        alerts.append(
            {
                "kind": "trust_incident",
                "severity": item.get("severity") or "warning",
                "title": item.get("title") or "Incidente Trust AI",
                "description": item.get("summary") or "",
                "source_id": item.get("id") or "",
                "created_at": item.get("updated_at") or item.get("detected_at") or "",
            }
        )
    if int(metrics.get("events_15m") or 0) == 0:
        alerts.append(
            {
                "kind": "freshness",
                "severity": "info",
                "title": "Sin eventos Intelligence en 15 minutos",
                "description": "Puede ser normal en tenants sin trafico reciente; revisa webhooks/worker si esperabas actividad.",
                "source_id": "",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    severity_weight = {"critical": 4, "high": 3, "warning": 2, "medium": 2, "info": 1}
    alerts.sort(key=lambda item: (severity_weight.get(str(item.get("severity") or "info").lower(), 1), str(item.get("created_at") or "")), reverse=True)
    return alerts[:30]


def realtime_intelligence_center(
    conn: Connection,
    tenant_id: str,
    user_id: str,
    *,
    limit: int = 60,
    since_event_id: str = "",
    cursor_key: str = "default",
) -> dict[str, Any]:
    ensure_realtime_tables(conn)
    max_limit = max(5, min(int(limit or 60), 120))
    access = _access_bundle(conn, tenant_id)
    events = list_realtime_events(conn, tenant_id, limit=max_limit, since_event_id=since_event_id)
    predictions = list_predictions(conn, tenant_id, limit=max_limit)
    recommendations = list_recommendations(conn, tenant_id, status="open", limit=max_limit)
    features = list_feature_values(conn, tenant_id, subject_type="tenant", subject_id=tenant_id, limit=40)
    model_metrics = list_model_metrics(conn, tenant_id=tenant_id, limit=40)
    metrics = _live_metrics(conn, tenant_id)
    operations = _recent_operations(conn, tenant_id, limit=max_limit)
    trust = _recent_trust(conn, tenant_id, limit=max_limit)
    alerts = _build_alerts(
        recommendations=recommendations,
        predictions=predictions,
        operations=operations,
        trust=trust,
        metrics=metrics,
    )
    if not access["alerts"].get("enabled"):
        alerts = []
    latest_event_id = events[0]["id"] if events else ""
    return {
        "tenant_id": tenant_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "access": access,
        "stream": {
            "enabled": bool(access["stream"].get("enabled")),
            "transport": "sse_optional_polling_fallback",
            "poll_interval_seconds": 8,
            "snapshot_ttl_seconds": 20,
            "latest_event_id": latest_event_id,
            "cursor": _current_cursor(conn, tenant_id, user_id, cursor_key=cursor_key),
        },
        "metrics": metrics,
        "event_type_counts": _event_type_counts(conn, tenant_id, window_minutes=60),
        "events": events,
        "alerts": alerts,
        "predictions": predictions[:max_limit],
        "recommendations": recommendations[:max_limit],
        "features": features,
        "model_metrics": model_metrics,
        "operations": operations,
        "trust": trust,
    }


def register_realtime_session(conn: Connection, tenant_id: str, user_id: str, payload: Any) -> dict[str, Any]:
    ensure_realtime_tables(conn)
    resolve_intelligence_access(conn, tenant_id, STREAM_FEATURE, allow_demo=True)
    data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload or {})
    session_key = _clean(data.get("session_key"), 120) or str(uuid.uuid4())
    record_intelligence_usage(
        conn,
        tenant_id,
        STREAM_FEATURE,
        usage_metric="realtime_sessions",
        metadata={"session_key": session_key, "channel": _clean(data.get("channel"), 80) or "tenant"},
    )
    row = conn.execute(
        text(
            """
            INSERT INTO saas_realtime_intelligence_sessions (
                tenant_id, user_id, session_key, channel, status, last_event_id,
                filters_json, client_meta_json, connected_at, last_seen_at, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), CAST(:user_id AS uuid), :session_key, :channel,
                'active', :last_event_id, CAST(:filters_json AS jsonb),
                CAST(:client_meta_json AS jsonb), NOW(), NOW(), NOW()
            )
            ON CONFLICT (tenant_id, user_id, session_key)
            DO UPDATE SET
                channel = EXCLUDED.channel,
                status = 'active',
                last_event_id = EXCLUDED.last_event_id,
                filters_json = EXCLUDED.filters_json,
                client_meta_json = EXCLUDED.client_meta_json,
                last_seen_at = NOW(),
                closed_at = NULL,
                updated_at = NOW()
            RETURNING id::text, session_key, channel, status, last_event_id,
                      filters_json, client_meta_json, connected_at::text,
                      last_seen_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "session_key": session_key,
            "channel": _clean(data.get("channel"), 80) or "tenant",
            "last_event_id": _clean(data.get("last_event_id"), 80),
            "filters_json": _json(data.get("filters_json") or {}),
            "client_meta_json": _json(data.get("client_meta_json") or {}),
        },
    ).mappings().first()
    return _json_safe(dict(row or {}))


def update_realtime_cursor(conn: Connection, tenant_id: str, user_id: str, payload: Any) -> dict[str, Any]:
    ensure_realtime_tables(conn)
    resolve_intelligence_access(conn, tenant_id, STREAM_FEATURE, allow_demo=True)
    data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload or {})
    cursor_key = _clean(data.get("cursor_key"), 80) or "default"
    last_event_id = _clean(data.get("last_event_id"), 80)
    last_event_at = None
    if last_event_id:
        last_event_at = conn.execute(
            text(
                """
                SELECT occurred_at
                FROM saas_intelligence_events
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id::text = :last_event_id
                LIMIT 1
                """
            ),
            {"tenant_id": tenant_id, "last_event_id": last_event_id},
        ).scalar()
    row = conn.execute(
        text(
            """
            INSERT INTO saas_realtime_intelligence_cursors (
                tenant_id, user_id, cursor_key, last_event_id, last_event_at,
                filters_json, last_seen_at, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), CAST(:user_id AS uuid), :cursor_key,
                :last_event_id, CAST(NULLIF(:last_event_at, '') AS timestamp),
                CAST(:filters_json AS jsonb), NOW(), NOW()
            )
            ON CONFLICT (tenant_id, user_id, cursor_key)
            DO UPDATE SET
                last_event_id = EXCLUDED.last_event_id,
                last_event_at = EXCLUDED.last_event_at,
                filters_json = EXCLUDED.filters_json,
                last_seen_at = NOW(),
                updated_at = NOW()
            RETURNING id::text, cursor_key, last_event_id, last_event_at::text,
                      filters_json, last_seen_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "cursor_key": cursor_key,
            "last_event_id": last_event_id,
            "last_event_at": last_event_at.isoformat() if isinstance(last_event_at, datetime) else "",
            "filters_json": _json(data.get("filters_json") or {}),
        },
    ).mappings().first()
    return _json_safe(dict(row or {}))


def close_realtime_session(conn: Connection, tenant_id: str, user_id: str, session_id: str) -> dict[str, Any]:
    ensure_realtime_tables(conn)
    row = conn.execute(
        text(
            """
            UPDATE saas_realtime_intelligence_sessions
            SET status = 'closed', closed_at = NOW(), last_seen_at = NOW(), updated_at = NOW()
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND user_id = CAST(:user_id AS uuid)
              AND id::text = :session_id
            RETURNING id::text, session_key, channel, status, closed_at::text, updated_at::text
            """
        ),
        {"tenant_id": tenant_id, "user_id": user_id, "session_id": _clean(session_id, 80)},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail={"code": "realtime_session_not_found"})
    return _json_safe(dict(row))


def store_realtime_metric_snapshot(conn: Connection, tenant_id: str, *, window_seconds: int = 900) -> list[dict[str, Any]]:
    ensure_realtime_tables(conn)
    metrics = _live_metrics(conn, tenant_id)
    rows: list[dict[str, Any]] = []
    for key in ("events_15m", "events_1h", "predictions_1h", "open_recommendations", "active_sessions", "open_anomalies", "high_anomalies", "open_trust_incidents"):
        value = float(metrics.get(key) or 0)
        row = conn.execute(
            text(
                """
                INSERT INTO saas_realtime_intelligence_metrics (
                    tenant_id, metric_key, metric_value, window_seconds, metadata_json, measured_at
                )
                VALUES (
                    CAST(:tenant_id AS uuid), :metric_key, :metric_value, :window_seconds,
                    CAST(:metadata_json AS jsonb), NOW()
                )
                RETURNING id::text, metric_key, metric_value, window_seconds, metadata_json,
                          measured_at::text, created_at::text
                """
            ),
            {
                "tenant_id": tenant_id,
                "metric_key": key,
                "metric_value": value,
                "window_seconds": max(60, min(int(window_seconds or 900), 86400)),
                "metadata_json": _json({"source": "phase16_realtime_snapshot", "status": metrics.get("status") or "unknown"}),
            },
        ).mappings().first()
        if row:
            rows.append(_json_safe(dict(row)))
    return rows


def admin_realtime_overview(conn: Connection, *, tenant_id: str = "", limit: int = 80) -> dict[str, Any]:
    ensure_realtime_tables(conn)
    clean_tenant = _clean(tenant_id, 80)
    params = {"tenant_id": clean_tenant, "limit": max(1, min(int(limit or 80), 200))}
    rows = conn.execute(
        text(
            """
            SELECT t.id::text AS tenant_id, t.name AS tenant_name, t.slug AS tenant_slug,
                   t.status, t.plan_code,
                   COALESCE((SELECT COUNT(*)::int FROM saas_intelligence_events e WHERE e.tenant_id = t.id AND e.occurred_at >= NOW() - INTERVAL '15 minutes'), 0) AS events_15m,
                   COALESCE((SELECT COUNT(*)::int FROM saas_intelligence_predictions p WHERE p.tenant_id = t.id AND p.created_at >= NOW() - INTERVAL '1 hour'), 0) AS predictions_1h,
                   COALESCE((SELECT COUNT(*)::int FROM saas_intelligence_recommendations r WHERE r.tenant_id = t.id AND r.status = 'open'), 0) AS open_recommendations,
                   COALESCE((SELECT COUNT(*)::int FROM saas_realtime_intelligence_sessions s WHERE s.tenant_id = t.id AND s.status = 'active' AND s.last_seen_at >= NOW() - INTERVAL '5 minutes'), 0) AS active_sessions,
                   COALESCE((SELECT MAX(occurred_at)::text FROM saas_intelligence_events e WHERE e.tenant_id = t.id), '') AS latest_event_at,
                   COALESCE((SELECT MAX(measured_at)::text FROM saas_realtime_intelligence_metrics m WHERE m.tenant_id = t.id), '') AS latest_metric_at
            FROM saas_tenants t
            WHERE (CAST(NULLIF(:tenant_id, '') AS uuid) IS NULL OR t.id = CAST(NULLIF(:tenant_id, '') AS uuid))
            ORDER BY events_15m DESC, predictions_1h DESC, t.updated_at DESC
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()
    tenants = _rows(rows)
    totals = {
        "tenants": len(tenants),
        "events_15m": sum(int(item.get("events_15m") or 0) for item in tenants),
        "predictions_1h": sum(int(item.get("predictions_1h") or 0) for item in tenants),
        "open_recommendations": sum(int(item.get("open_recommendations") or 0) for item in tenants),
        "active_sessions": sum(int(item.get("active_sessions") or 0) for item in tenants),
    }
    feature_rows = []
    for item in tenants[:20]:
        state = intelligence_feature_state(conn, str(item.get("tenant_id") or ""))
        features = {feature["key"]: feature for feature in state.get("features", []) if feature.get("key") in {BASE_FEATURE, STREAM_FEATURE, ALERTS_FEATURE, DASHBOARD_FEATURE}}
        item["realtime_features"] = features
        feature_rows.append(features)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "totals": totals,
        "tenants": tenants,
        "feature_keys": [BASE_FEATURE, STREAM_FEATURE, ALERTS_FEATURE, DASHBOARD_FEATURE],
    }


def admin_refresh_realtime_metrics(conn: Connection, *, tenant_id: str = "", limit: int = 80) -> dict[str, Any]:
    ensure_realtime_tables(conn)
    clean_tenant = _clean(tenant_id, 80)
    rows = conn.execute(
        text(
            """
            SELECT id::text
            FROM saas_tenants
            WHERE status IN ('active','trial')
              AND (CAST(NULLIF(:tenant_id, '') AS uuid) IS NULL OR id = CAST(NULLIF(:tenant_id, '') AS uuid))
            ORDER BY updated_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": clean_tenant, "limit": max(1, min(int(limit or 80), 200))},
    ).mappings().all()
    snapshots: list[dict[str, Any]] = []
    for row in rows:
        snapshots.extend(store_realtime_metric_snapshot(conn, str(row["id"])))
    return {"tenant_id": clean_tenant, "snapshots_written": len(snapshots), "snapshots": snapshots[:200]}
