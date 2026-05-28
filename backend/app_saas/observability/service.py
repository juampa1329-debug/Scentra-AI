from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app_saas.config import settings


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_rows(conn, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    try:
        return [dict(row) for row in conn.execute(text(sql), params or {}).mappings().all()]
    except SQLAlchemyError as exc:
        return [{"_query_error": str(exc)[:500]}]


def _safe_one(conn, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    rows = _safe_rows(conn, sql, params)
    return rows[0] if rows else {}


def _total(rows: list[dict[str, Any]], status: str) -> int:
    return sum(int(row.get("total") or 0) for row in rows if str(row.get("status") or "") == status)


def _json_dump(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _uuid_text(value: Any) -> str:
    try:
        return str(UUID(str(value or "")))
    except (TypeError, ValueError):
        return ""


def _payload_dict(row: dict[str, Any]) -> dict[str, Any]:
    payload = _json_value(row.get("payload_json"))
    return payload if isinstance(payload, dict) else {}


def _correlation_id(row: dict[str, Any]) -> str:
    direct = str(row.get("correlation_id") or "").strip()
    if direct:
        return direct[:120]
    payload = _payload_dict(row)
    for key in ("correlation_id", "request_id", "x-correlation-id", "x-request-id"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value[:120]
    headers = payload.get("headers") if isinstance(payload.get("headers"), dict) else {}
    for key in ("x-correlation-id", "x-request-id"):
        value = str(headers.get(key) or "").strip()
        if value:
            return value[:120]
    return ""


def ensure_dead_letter_table(conn) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_dead_letter_events (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                source_type TEXT NOT NULL,
                source_id TEXT NOT NULL,
                provider TEXT NOT NULL DEFAULT '',
                channel TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'open',
                reason TEXT NOT NULL DEFAULT '',
                severity TEXT NOT NULL DEFAULT 'medium',
                payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                first_seen_at TIMESTAMP NOT NULL DEFAULT NOW(),
                last_seen_at TIMESTAMP NOT NULL DEFAULT NOW(),
                resolved_at TIMESTAMP NULL,
                UNIQUE (source_type, source_id)
            )
            """
        )
    )
    conn.execute(text("ALTER TABLE saas_dead_letter_events ADD COLUMN IF NOT EXISTS correlation_id TEXT NOT NULL DEFAULT ''"))
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_dead_letter_status_seen
            ON saas_dead_letter_events (status, last_seen_at DESC)
            """
        )
    )


def ensure_worker_heartbeat_table(conn) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_worker_heartbeats (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                worker_name TEXT NOT NULL UNIQUE,
                worker_type TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'ok',
                last_started_at TIMESTAMP NULL,
                last_seen_at TIMESTAMP NOT NULL DEFAULT NOW(),
                last_result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                last_error TEXT NOT NULL DEFAULT '',
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_worker_heartbeats_seen
            ON saas_worker_heartbeats (last_seen_at DESC)
            """
        )
    )


def record_worker_heartbeat(
    conn,
    *,
    worker_name: str,
    worker_type: str,
    status: str = "ok",
    result: dict[str, Any] | None = None,
    error: str = "",
    started: bool = False,
) -> None:
    ensure_worker_heartbeat_table(conn)
    conn.execute(
        text(
            """
            INSERT INTO saas_worker_heartbeats (
                worker_name, worker_type, status, last_started_at, last_seen_at,
                last_result_json, last_error, updated_at
            )
            VALUES (
                :worker_name, :worker_type, :status,
                CASE WHEN :started THEN NOW() ELSE NULL END,
                NOW(), CAST(:last_result_json AS jsonb), :last_error, NOW()
            )
            ON CONFLICT (worker_name) DO UPDATE SET
                worker_type = EXCLUDED.worker_type,
                status = EXCLUDED.status,
                last_started_at = CASE
                    WHEN :started THEN NOW()
                    ELSE COALESCE(saas_worker_heartbeats.last_started_at, EXCLUDED.last_started_at)
                END,
                last_seen_at = NOW(),
                last_result_json = EXCLUDED.last_result_json,
                last_error = EXCLUDED.last_error,
                updated_at = NOW()
            """
        ),
        {
            "worker_name": str(worker_name or "worker-generic")[:120],
            "worker_type": str(worker_type or "worker")[:80],
            "status": str(status or "ok")[:40],
            "last_result_json": _json_dump(result or {}),
            "last_error": str(error or "")[:1200],
            "started": bool(started),
        },
    )


def worker_snapshot(conn) -> dict[str, Any]:
    ensure_worker_heartbeat_table(conn)
    rows = _safe_rows(
        conn,
        """
        SELECT worker_name, worker_type, status, last_started_at::text,
               last_seen_at::text, last_result_json, last_error,
               EXTRACT(EPOCH FROM (NOW() - last_seen_at))::int AS age_seconds
        FROM saas_worker_heartbeats
        ORDER BY last_seen_at DESC
        """,
    )
    for row in rows:
        row["last_result_json"] = _json_value(row.get("last_result_json"))
    stale_after = max(30, int(settings.saas_worker_idle_sec or 5) * 4 + 10)
    fresh = [row for row in rows if int(row.get("age_seconds") or 999999) <= stale_after and row.get("status") == "ok"]
    stale = [row for row in rows if int(row.get("age_seconds") or 999999) > stale_after]
    status = "ok" if fresh else "unknown"
    signals: list[str] = []
    if not rows:
        signals.append("no_worker_heartbeat_seen")
    if stale:
        status = "degraded"
        signals.append("worker_heartbeat_stale")
    if any(str(row.get("status") or "") == "error" for row in rows):
        status = "degraded"
        signals.append("worker_error_reported")
    return {
        "status": status,
        "stale_after_seconds": stale_after,
        "total": len(rows),
        "fresh": len(fresh),
        "stale": len(stale),
        "signals": signals,
        "workers": rows,
    }
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_dead_letter_tenant_seen
            ON saas_dead_letter_events (tenant_id, last_seen_at DESC)
            """
        )
    )


def queue_snapshot(conn) -> dict[str, list[dict[str, Any]]]:
    outbound = _safe_rows(
        conn,
        """
        SELECT status, COUNT(*)::int AS total,
               COUNT(*) FILTER (WHERE attempts > 0)::int AS retried,
               COUNT(*) FILTER (WHERE attempts >= max_attempts)::int AS max_attempts_reached,
               MIN(next_attempt_at)::text AS oldest_due_at,
               MAX(updated_at)::text AS latest_updated_at,
               MAX(error) FILTER (WHERE COALESCE(error, '') <> '') AS last_error
        FROM saas_outbound_messages
        GROUP BY status
        ORDER BY status ASC
        """,
    )
    webhooks = _safe_rows(
        conn,
        """
        SELECT status, COUNT(*)::int AS total,
               MIN(received_at)::text AS oldest_received_at,
               MAX(received_at)::text AS latest_received_at,
               MAX(error) FILTER (WHERE COALESCE(error, '') <> '') AS last_error
        FROM saas_webhook_events
        GROUP BY status
        ORDER BY status ASC
        """,
    )
    scheduled = _safe_rows(
        conn,
        """
        SELECT status, COUNT(*)::int AS total,
               COUNT(*) FILTER (WHERE attempts > 0)::int AS retried,
               MIN(run_at)::text AS oldest_due_at,
               MAX(updated_at)::text AS latest_updated_at,
               MAX(last_error) FILTER (WHERE COALESCE(last_error, '') <> '') AS last_error
        FROM saas_trigger_scheduled_messages
        GROUP BY status
        ORDER BY status ASC
        """,
    )
    ai_pending = _safe_rows(
        conn,
        """
        SELECT status, COUNT(*)::int AS total,
               COUNT(*) FILTER (WHERE attempts > 0)::int AS retried,
               MIN(scheduled_at)::text AS oldest_due_at,
               MAX(updated_at)::text AS latest_updated_at,
               MAX(last_error) FILTER (WHERE COALESCE(last_error, '') <> '') AS last_error
        FROM saas_ai_pending_replies
        GROUP BY status
        ORDER BY status ASC
        """,
    )
    remarketing = _safe_rows(
        conn,
        """
        SELECT state AS status, COUNT(*)::int AS total,
               MIN(next_run_at)::text AS oldest_due_at,
               MAX(updated_at)::text AS latest_updated_at,
               MAX(last_error) FILTER (WHERE COALESCE(last_error, '') <> '') AS last_error
        FROM saas_remarketing_enrollments
        GROUP BY state
        ORDER BY state ASC
        """,
    )
    agent_orchestrator = _safe_rows(
        conn,
        """
        SELECT status, COUNT(*)::int AS total,
               COUNT(*) FILTER (WHERE attempts > 0)::int AS retried,
               COUNT(*) FILTER (WHERE attempts >= max_attempts)::int AS max_attempts_reached,
               MIN(scheduled_at)::text AS oldest_due_at,
               MAX(updated_at)::text AS latest_updated_at,
               MAX(error) FILTER (WHERE COALESCE(error, '') <> '') AS last_error
        FROM saas_ai_agent_orchestration_jobs
        GROUP BY status
        ORDER BY status ASC
        """,
    )
    return {
        "outbound": outbound,
        "webhooks": webhooks,
        "scheduled_triggers": scheduled,
        "ai_pending": ai_pending,
        "remarketing": remarketing,
        "agent_orchestrator": agent_orchestrator,
    }


def ai_gateway_snapshot(conn) -> dict[str, Any]:
    catalog = _safe_one(
        conn,
        """
        SELECT
            (SELECT COUNT(*)::int FROM saas_ai_providers WHERE is_active = TRUE) AS active_providers,
            (SELECT COUNT(*)::int FROM saas_ai_models WHERE is_active = TRUE) AS active_models,
            (SELECT COUNT(*)::int FROM saas_ai_routes WHERE is_active = TRUE) AS active_routes
        """,
    )
    runs = _safe_one(
        conn,
        """
        SELECT
            COUNT(*)::int AS runs_24h,
            COUNT(*) FILTER (WHERE status = 'success')::int AS success_24h,
            COUNT(*) FILTER (WHERE status IN ('failed', 'skipped'))::int AS failed_24h,
            COALESCE(ROUND(AVG(NULLIF(latency_ms, 0)))::int, 0) AS avg_latency_ms,
            COALESCE(SUM(total_tokens), 0)::bigint AS total_tokens_24h
        FROM saas_ai_runs
        WHERE created_at >= NOW() - INTERVAL '24 hours'
        """,
    )
    latest_error = _safe_one(
        conn,
        """
        SELECT tenant_id::text, provider_code, model, status, error_code, error_message,
               metadata_json, created_at::text
        FROM saas_ai_runs
        WHERE status IN ('failed', 'skipped')
        ORDER BY created_at DESC
        LIMIT 1
        """,
    )
    if catalog.get("_query_error") or runs.get("_query_error"):
        return {"status": "unknown", "catalog": catalog, "runs": runs, "latest_error": latest_error, "signals": ["ai_gateway_query_failed"]}
    failed = int(runs.get("failed_24h") or 0)
    return {
        "status": "degraded" if failed else "ok",
        "catalog": catalog,
        "runs": runs,
        "latest_error": latest_error,
        "signals": ["ai_gateway_failures_24h"] if failed else [],
    }


def meta_snapshot(conn) -> dict[str, Any]:
    integrations = _safe_rows(
        conn,
        """
        SELECT channel,
               COUNT(*)::int AS total,
               COUNT(*) FILTER (WHERE status = 'connected')::int AS connected,
               MAX(last_sync_at)::text AS last_sync_at
        FROM saas_integrations
        WHERE provider = 'meta' OR channel IN ('whatsapp', 'instagram', 'facebook')
        GROUP BY channel
        ORDER BY channel
        """,
    )
    webhooks = _safe_one(
        conn,
        """
        SELECT
            COUNT(*)::int AS events_24h,
            COUNT(*) FILTER (WHERE status = 'error' OR COALESCE(error, '') <> '')::int AS errors_24h,
            MAX(received_at)::text AS last_event_at
        FROM saas_webhook_events
        WHERE provider IN ('meta', 'whatsapp', 'instagram', 'facebook')
          AND received_at >= NOW() - INTERVAL '24 hours'
        """,
    )
    outbound = _safe_one(
        conn,
        """
        SELECT
            COUNT(*) FILTER (WHERE status IN ('failed', 'blocked'))::int AS failed_24h,
            MAX(updated_at)::text AS last_outbound_at,
            MAX(error) FILTER (WHERE COALESCE(error, '') <> '') AS last_error
        FROM saas_outbound_messages
        WHERE (provider = 'meta' OR channel IN ('whatsapp', 'instagram', 'facebook'))
          AND updated_at >= NOW() - INTERVAL '24 hours'
        """,
    )
    whatsapp_subscription_errors = _safe_one(
        conn,
        """
        SELECT COUNT(*)::int AS total, MAX(created_at)::text AS latest_at
        FROM saas_whatsapp_subscription_checks
        WHERE created_at >= NOW() - INTERVAL '7 days'
          AND (
            COALESCE(error, '') <> ''
            OR COALESCE(meta_error_message, '') <> ''
            OR final_subscribed = FALSE
          )
        """,
    )
    instagram_subscription_errors = _safe_one(
        conn,
        """
        SELECT COUNT(*)::int AS total, MAX(created_at)::text AS latest_at
        FROM saas_instagram_subscription_checks
        WHERE created_at >= NOW() - INTERVAL '7 days'
          AND (
            COALESCE(error, '') <> ''
            OR COALESCE(meta_error_message, '') <> ''
            OR final_subscribed = FALSE
          )
        """,
    )
    token_refresh_errors = _safe_one(
        conn,
        """
        SELECT COUNT(*)::int AS total, MAX(updated_at)::text AS latest_at
        FROM saas_integrations
        WHERE provider = 'meta'
          AND COALESCE(config_json #>> '{last_token_refresh,ok}', 'true') = 'false'
        """,
    )
    error_total = (
        int(webhooks.get("errors_24h") or 0)
        + int(outbound.get("failed_24h") or 0)
        + int(whatsapp_subscription_errors.get("total") or 0)
        + int(instagram_subscription_errors.get("total") or 0)
        + int(token_refresh_errors.get("total") or 0)
    )
    signals = ["meta_errors_detected"] if error_total else []
    return {
        "status": "degraded" if error_total else "ok",
        "integrations": integrations,
        "webhooks": webhooks,
        "outbound": outbound,
        "subscription_errors_7d": {
            "whatsapp": whatsapp_subscription_errors,
            "instagram_facebook": instagram_subscription_errors,
        },
        "token_refresh_errors": token_refresh_errors,
        "error_total": error_total,
        "signals": signals,
    }


def meta_error_history(conn, tenant_id: str = "", limit: int = 50) -> list[dict[str, Any]]:
    max_limit = max(1, min(int(limit or 50), 200))
    params: dict[str, Any] = {"limit": max_limit}
    tenant_filter = ""
    if tenant_id:
        tenant_filter = "AND x.tenant_id = :tenant_id"
        params["tenant_id"] = tenant_id

    rows: list[dict[str, Any]] = []
    rows.extend(
        _safe_rows(
            conn,
            f"""
            SELECT * FROM (
                SELECT 'outbound_message' AS source_type, o.id::text AS source_id,
                       o.tenant_id::text AS tenant_id, t.name AS tenant_name, t.slug AS tenant_slug,
                       COALESCE(NULLIF(o.provider, ''), 'meta') AS provider, o.channel,
                       o.status, o.error AS error_message, o.attempts, o.max_attempts,
                       o.correlation_id, o.updated_at AS occurred_at
                FROM saas_outbound_messages o
                LEFT JOIN saas_tenants t ON t.id = o.tenant_id
                WHERE (o.provider = 'meta' OR o.channel IN ('whatsapp', 'instagram', 'facebook'))
                  AND COALESCE(o.error, '') <> ''
            ) x
            WHERE 1=1 {tenant_filter}
            ORDER BY x.occurred_at DESC
            LIMIT :limit
            """,
            params,
        )
    )
    rows.extend(
        _safe_rows(
            conn,
            f"""
            SELECT * FROM (
                SELECT 'webhook_event' AS source_type, w.id::text AS source_id,
                       w.tenant_id::text AS tenant_id, t.name AS tenant_name, t.slug AS tenant_slug,
                       w.provider,
                       CASE
                         WHEN w.provider = 'whatsapp' OR w.payload_json::text ILIKE '%whatsapp_business_account%' THEN 'whatsapp'
                         WHEN w.provider = 'instagram' OR w.payload_json::text ILIKE '%instagram%' THEN 'instagram'
                         WHEN w.provider = 'facebook' OR w.payload_json::text ILIKE '%"page"%' THEN 'facebook'
                         ELSE w.provider
                       END AS channel,
                       w.status, w.error AS error_message, 0 AS attempts, 0 AS max_attempts,
                       w.correlation_id, w.received_at AS occurred_at
                FROM saas_webhook_events w
                LEFT JOIN saas_tenants t ON t.id = w.tenant_id
                WHERE w.provider IN ('meta', 'whatsapp', 'instagram', 'facebook')
                  AND (w.status = 'error' OR COALESCE(w.error, '') <> '')
            ) x
            WHERE 1=1 {tenant_filter}
            ORDER BY x.occurred_at DESC
            LIMIT :limit
            """,
            params,
        )
    )
    rows.extend(
        _safe_rows(
            conn,
            f"""
            SELECT * FROM (
                SELECT 'meta_whatsapp_subscription' AS source_type, c.id::text AS source_id,
                       c.tenant_id::text AS tenant_id, t.name AS tenant_name, t.slug AS tenant_slug,
                       'meta' AS provider, 'whatsapp' AS channel,
                       c.status, COALESCE(NULLIF(c.meta_error_message, ''), NULLIF(c.error, ''), c.status) AS error_message,
                       0 AS attempts, 0 AS max_attempts, '' AS correlation_id, c.created_at AS occurred_at
                FROM saas_whatsapp_subscription_checks c
                LEFT JOIN saas_tenants t ON t.id = c.tenant_id
                WHERE COALESCE(c.error, '') <> ''
                   OR COALESCE(c.meta_error_message, '') <> ''
                   OR c.final_subscribed = FALSE
            ) x
            WHERE 1=1 {tenant_filter}
            ORDER BY x.occurred_at DESC
            LIMIT :limit
            """,
            params,
        )
    )
    rows.extend(
        _safe_rows(
            conn,
            f"""
            SELECT * FROM (
                SELECT 'meta_social_subscription' AS source_type, c.id::text AS source_id,
                       c.tenant_id::text AS tenant_id, t.name AS tenant_name, t.slug AS tenant_slug,
                       'meta' AS provider,
                       CASE WHEN COALESCE(c.instagram_business_account_id, '') <> '' THEN 'instagram' ELSE 'facebook' END AS channel,
                       c.status, COALESCE(NULLIF(c.meta_error_message, ''), NULLIF(c.error, ''), c.status) AS error_message,
                       0 AS attempts, 0 AS max_attempts, '' AS correlation_id, c.created_at AS occurred_at
                FROM saas_instagram_subscription_checks c
                LEFT JOIN saas_tenants t ON t.id = c.tenant_id
                WHERE COALESCE(c.error, '') <> ''
                   OR COALESCE(c.meta_error_message, '') <> ''
                   OR c.final_subscribed = FALSE
            ) x
            WHERE 1=1 {tenant_filter}
            ORDER BY x.occurred_at DESC
            LIMIT :limit
            """,
            params,
        )
    )
    rows.extend(
        _safe_rows(
            conn,
            f"""
            SELECT * FROM (
                SELECT 'meta_token_refresh' AS source_type, i.id::text AS source_id,
                       i.tenant_id::text AS tenant_id, t.name AS tenant_name, t.slug AS tenant_slug,
                       i.provider, i.channel,
                       COALESCE(i.config_json #>> '{{last_token_refresh,status}}', 'token_refresh_failed') AS status,
                       COALESCE(i.config_json #>> '{{last_token_refresh,meta_error,message}}', i.config_json #>> '{{last_token_refresh,status}}', 'token_refresh_failed') AS error_message,
                       COALESCE(NULLIF(i.config_json #>> '{{last_token_refresh,page_attempts}}', '')::int, 0) AS attempts,
                       0 AS max_attempts, '' AS correlation_id, i.updated_at AS occurred_at
                FROM saas_integrations i
                LEFT JOIN saas_tenants t ON t.id = i.tenant_id
                WHERE i.provider = 'meta'
                  AND COALESCE(i.config_json #>> '{{last_token_refresh,ok}}', 'true') = 'false'
            ) x
            WHERE 1=1 {tenant_filter}
            ORDER BY x.occurred_at DESC
            LIMIT :limit
            """,
            params,
        )
    )

    clean_rows = [row for row in rows if not row.get("_query_error")]
    clean_rows.sort(key=lambda row: str(row.get("occurred_at") or ""), reverse=True)
    return clean_rows[:max_limit]


def _diagnosis_for(source_type: str, reason: str, payload: dict[str, Any]) -> dict[str, Any]:
    reason_text = str(reason or "").lower()
    stage = {
        "webhook_event": "webhook_ingest",
        "outbound_message": "outbound_dispatch",
        "scheduled_trigger": "trigger_runtime",
        "ai_pending_reply": "ai_reply",
        "ai_gateway_run": "ai_gateway",
        "remarketing_enrollment": "remarketing",
        "agent_orchestrator_job": "agent_orchestrator",
        "meta_whatsapp_subscription": "meta_subscription",
        "meta_social_subscription": "meta_subscription",
        "meta_token_refresh": "meta_token",
    }.get(source_type, source_type or "unknown")
    root_cause = "unknown"
    suggested_action = "Revisar payload, tenant, canal y logs con correlation_id."
    if "token" in reason_text or "oauth" in reason_text or "190" in reason_text:
        root_cause = "token"
        suggested_action = "Refrescar o reconectar la integracion Meta del tenant."
    elif "permission" in reason_text or "access" in reason_text or "insufficient" in reason_text:
        root_cause = "permissions"
        suggested_action = "Verificar permisos Meta, activos conectados y subscribed_apps."
    elif "integration_not_connected" in reason_text or "missing" in reason_text:
        root_cause = "configuration"
        suggested_action = "Completar configuracion de integracion, credenciales o endpoint."
    elif "rate" in reason_text or "429" in reason_text or "613" in reason_text:
        root_cause = "rate_limit"
        suggested_action = "Esperar cooldown, revisar limites Meta y reintentar."
    elif "ai" in source_type or "gateway" in source_type or "credential" in reason_text:
        root_cause = "ai"
        suggested_action = "Verificar credenciales/modelo AI, cuota y ultimo run del gateway."
    elif "webhook" in source_type:
        root_cause = "webhook_processing"
        suggested_action = "Reprocesar webhooks y validar payload/provider/event_id."
    elif "outbound" in source_type:
        root_cause = "outbound"
        suggested_action = "Reintentar outbound tras validar token, destinatario y plantilla."
    if int(payload.get("attempts") or 0) >= int(payload.get("max_attempts") or 999999):
        suggested_action = f"{suggested_action} El job llego al maximo de intentos."
    return {"stage": stage, "root_cause": root_cause, "suggested_action": suggested_action}


def _retry_info(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "attempts": int(payload.get("attempts") or 0),
        "max_attempts": int(payload.get("max_attempts") or 0),
        "next_attempt_at": payload.get("next_attempt_at") or payload.get("run_at") or payload.get("scheduled_at") or "",
        "retryable": True,
    }


def global_health(conn) -> dict[str, Any]:
    checked_at = _utc_now_text()
    db_probe = _safe_one(conn, "SELECT NOW()::text AS server_time")
    queues = queue_snapshot(conn)
    workers = worker_snapshot(conn)
    ai_gateway = ai_gateway_snapshot(conn)
    meta = meta_snapshot(conn)
    platform = _safe_one(
        conn,
        """
        SELECT
            (SELECT COUNT(*)::int FROM saas_tenants) AS tenants,
            (SELECT COUNT(*)::int FROM saas_tenants WHERE status IN ('active', 'trial')) AS active_tenants,
            (SELECT COUNT(*)::int FROM saas_integrations WHERE status = 'connected') AS connected_integrations,
            (SELECT COUNT(*)::int FROM saas_webhook_endpoints WHERE is_active = TRUE) AS active_webhooks
        """,
    )
    outbound_failed = _total(queues["outbound"], "failed") + _total(queues["outbound"], "blocked")
    webhook_errors = _total(queues["webhooks"], "error")
    trigger_failed = _total(queues["scheduled_triggers"], "failed")
    ai_failed = _total(queues["ai_pending"], "failed") + _total(queues["ai_pending"], "skipped")
    agent_failed = _total(queues["agent_orchestrator"], "failed")
    remarketing_failed = _total(queues["remarketing"], "error")
    backlog = (
        _total(queues["outbound"], "queued")
        + _total(queues["outbound"], "retry")
        + _total(queues["webhooks"], "received")
        + _total(queues["scheduled_triggers"], "pending")
        + _total(queues["ai_pending"], "pending")
        + _total(queues["agent_orchestrator"], "queued")
        + _total(queues["remarketing"], "active")
    )
    error_total = outbound_failed + webhook_errors + trigger_failed + ai_failed + agent_failed + remarketing_failed
    status = "ok"
    signals: list[str] = []
    if db_probe.get("_query_error"):
        status = "down"
        signals.append("database_query_failed")
    if error_total > 0 and status != "down":
        status = "degraded"
        signals.append("dead_letter_candidates_present")
    if backlog > 500 and status == "ok":
        status = "degraded"
        signals.append("queue_backlog_high")
    if workers.get("status") in {"degraded", "unknown"}:
        if status == "ok":
            status = "degraded"
        signals.extend(workers.get("signals") or ["worker_health_unknown"])
    if ai_gateway.get("status") == "degraded":
        if status == "ok":
            status = "degraded"
        signals.extend(ai_gateway.get("signals") or ["ai_gateway_degraded"])
    if meta.get("status") == "degraded":
        if status == "ok":
            status = "degraded"
        signals.extend(meta.get("signals") or ["meta_degraded"])
    return {
        "status": status,
        "checked_at": checked_at,
        "database": {"ok": not bool(db_probe.get("_query_error")), **db_probe},
        "api": {
            "ok": True,
            "environment": settings.saas_env,
            "embedded_worker_enabled": bool(settings.saas_embedded_worker_enabled),
            "worker_batch_size": int(settings.saas_worker_batch_size or 0),
            "worker_idle_sec": int(settings.saas_worker_idle_sec or 0),
        },
        "platform": platform,
        "workers": workers,
        "meta": meta,
        "ai_gateway": ai_gateway,
        "queues": queues,
        "summary": {
            "backlog": backlog,
            "error_total": error_total,
            "outbound_failed_or_blocked": outbound_failed,
            "webhook_errors": webhook_errors,
            "trigger_failed": trigger_failed,
            "ai_failed": ai_failed,
            "agent_failed": agent_failed,
            "remarketing_failed": remarketing_failed,
        },
        "signals": sorted(set(signals)),
    }


def channel_diagnostics(conn) -> list[dict[str, Any]]:
    integrations = _safe_rows(
        conn,
        """
        SELECT provider, channel,
               COUNT(*)::int AS integrations,
               COUNT(*) FILTER (WHERE status = 'connected')::int AS connected,
               MAX(last_sync_at)::text AS last_sync_at
        FROM saas_integrations
        GROUP BY provider, channel
        ORDER BY provider ASC, channel ASC
        """,
    )
    webhooks = _safe_rows(
        conn,
        """
        SELECT provider,
               CASE
                 WHEN provider = 'whatsapp' OR payload_json::text ILIKE '%whatsapp_business_account%' THEN 'whatsapp'
                 WHEN provider = 'instagram' OR payload_json::text ILIKE '%instagram%' THEN 'instagram'
                 WHEN provider = 'facebook' OR payload_json::text ILIKE '%"page"%' THEN 'facebook'
                 ELSE provider
               END AS channel,
               COUNT(*)::int AS events_7d,
               COUNT(*) FILTER (WHERE status = 'error' OR COALESCE(error, '') <> '')::int AS errors_7d,
               MAX(received_at)::text AS last_event_at,
               MAX(processed_at)::text AS last_processed_at
        FROM saas_webhook_events
        WHERE received_at >= NOW() - INTERVAL '7 days'
        GROUP BY provider, channel
        """,
    )
    endpoints = _safe_rows(
        conn,
        """
        SELECT provider,
               COUNT(*) FILTER (WHERE is_active = TRUE)::int AS active_endpoints,
               MAX(last_seen_at)::text AS last_seen_at
        FROM saas_webhook_endpoints
        GROUP BY provider
        """,
    )
    outbound = _safe_rows(
        conn,
        """
        SELECT provider, channel,
               COUNT(*) FILTER (WHERE status = 'queued')::int AS queued,
               COUNT(*) FILTER (WHERE status IN ('failed', 'blocked'))::int AS failed,
               MAX(updated_at)::text AS last_outbound_at
        FROM saas_outbound_messages
        WHERE updated_at >= NOW() - INTERVAL '7 days'
        GROUP BY provider, channel
        """,
    )
    conversations = _safe_rows(
        conn,
        """
        SELECT channel,
               COUNT(*)::int AS conversations,
               COALESCE(SUM(unread_count), 0)::int AS unread,
               MAX(last_message_at)::text AS last_message_at
        FROM saas_conversations
        GROUP BY channel
        """,
    )
    indexed: dict[tuple[str, str], dict[str, Any]] = {}

    def item(provider: str, channel: str) -> dict[str, Any]:
        key = (provider or channel or "unknown", channel or provider or "unknown")
        if key not in indexed:
            indexed[key] = {
                "provider": key[0],
                "channel": key[1],
                "status": "ok",
                "signals": [],
                "integrations": 0,
                "connected": 0,
                "active_endpoints": 0,
                "events_7d": 0,
                "errors_7d": 0,
                "outbound_queued": 0,
                "outbound_failed": 0,
                "conversations": 0,
                "unread": 0,
                "last_event_at": "",
                "last_message_at": "",
                "last_outbound_at": "",
                "last_sync_at": "",
            }
        return indexed[key]

    for baseline_channel in ("whatsapp", "instagram", "facebook"):
        item("meta", baseline_channel)

    for row in integrations:
        if row.get("_query_error"):
            continue
        current = item(str(row.get("provider") or ""), str(row.get("channel") or ""))
        current.update({
            "integrations": int(row.get("integrations") or 0),
            "connected": int(row.get("connected") or 0),
            "last_sync_at": row.get("last_sync_at") or "",
        })
    for row in endpoints:
        if row.get("_query_error"):
            continue
        provider = str(row.get("provider") or "")
        endpoint_channel = "whatsapp" if provider in {"meta", "whatsapp"} else provider
        for current in indexed.values():
            if current["provider"] == provider or current["channel"] == endpoint_channel:
                current["active_endpoints"] = int(row.get("active_endpoints") or 0)
                current["last_seen_at"] = row.get("last_seen_at") or ""
    for row in webhooks:
        if row.get("_query_error"):
            continue
        provider = str(row.get("provider") or "")
        channel = str(row.get("channel") or provider or "")
        target = item(provider or "meta", channel)
        target["events_7d"] = int(row.get("events_7d") or 0)
        target["errors_7d"] = int(row.get("errors_7d") or 0)
        target["last_event_at"] = row.get("last_event_at") or ""
        target["last_processed_at"] = row.get("last_processed_at") or ""
    for row in outbound:
        if row.get("_query_error"):
            continue
        current = item(str(row.get("provider") or ""), str(row.get("channel") or ""))
        current["outbound_queued"] = int(row.get("queued") or 0)
        current["outbound_failed"] = int(row.get("failed") or 0)
        current["last_outbound_at"] = row.get("last_outbound_at") or ""
    for row in conversations:
        if row.get("_query_error"):
            continue
        channel = str(row.get("channel") or "")
        for current in indexed.values():
            if current["channel"] == channel:
                current["conversations"] = int(row.get("conversations") or 0)
                current["unread"] = int(row.get("unread") or 0)
                current["last_message_at"] = row.get("last_message_at") or ""

    for current in indexed.values():
        if current["outbound_failed"] or current["errors_7d"]:
            current["status"] = "degraded"
            current["signals"].append("errors_detected")
        if current["connected"] and not current["active_endpoints"]:
            current["status"] = "degraded"
            current["signals"].append("connected_without_active_endpoint")
        if current["connected"] and not current["events_7d"]:
            current["signals"].append("no_recent_webhook_events")
    return sorted(indexed.values(), key=lambda item: (item["status"] != "degraded", item["provider"], item["channel"]))


def _upsert_dead_letter(conn, item: dict[str, Any]) -> None:
    conn.execute(
        text(
            """
            INSERT INTO saas_dead_letter_events (
                tenant_id, source_type, source_id, provider, channel, status,
                reason, severity, payload_json, correlation_id, first_seen_at, last_seen_at
            )
            VALUES (
                CAST(NULLIF(:tenant_id, '') AS uuid), :source_type, :source_id,
                :provider, :channel, 'open', :reason, :severity,
                CAST(:payload_json AS jsonb), :correlation_id, NOW(), NOW()
            )
            ON CONFLICT (source_type, source_id) DO UPDATE SET
                tenant_id = EXCLUDED.tenant_id,
                provider = EXCLUDED.provider,
                channel = EXCLUDED.channel,
                status = CASE WHEN saas_dead_letter_events.status <> 'open' THEN 'open' ELSE saas_dead_letter_events.status END,
                reason = EXCLUDED.reason,
                severity = EXCLUDED.severity,
                payload_json = EXCLUDED.payload_json,
                correlation_id = EXCLUDED.correlation_id,
                last_seen_at = NOW(),
                resolved_at = NULL
            """
        ),
        {
            "tenant_id": item.get("tenant_id") or "",
            "source_type": item["source_type"],
            "source_id": str(item["source_id"]),
            "provider": str(item.get("provider") or "")[:80],
            "channel": str(item.get("channel") or "")[:80],
            "reason": str(item.get("reason") or "")[:1200],
            "severity": str(item.get("severity") or "medium")[:40],
            "payload_json": _json_dump(item.get("payload_json") or {}),
            "correlation_id": str(item.get("correlation_id") or _correlation_id({"payload_json": item.get("payload_json") or {}}))[:120],
        },
    )


def sync_dead_letters(conn, limit: int = 200) -> dict[str, Any]:
    ensure_dead_letter_table(conn)
    candidates: list[dict[str, Any]] = []
    candidates.extend(
        {
            "tenant_id": row.get("tenant_id"),
            "source_type": "outbound_message",
            "source_id": row.get("id"),
            "provider": row.get("provider"),
            "channel": row.get("channel"),
            "reason": row.get("error") or row.get("status") or "outbound_failed",
            "severity": "high" if row.get("status") in {"failed", "blocked"} else "medium",
            "payload_json": row,
            "correlation_id": row.get("correlation_id") or "",
        }
        for row in _safe_rows(
            conn,
            """
            SELECT id::text, tenant_id::text, provider, channel, status, recipient_external_id,
                   attempts, max_attempts, next_attempt_at::text, error, correlation_id,
                   created_at::text, updated_at::text
            FROM saas_outbound_messages
            WHERE status IN ('failed', 'blocked', 'retry')
               OR (COALESCE(error, '') <> '' AND status NOT IN ('sent', 'delivered', 'read'))
            ORDER BY updated_at DESC
            LIMIT :limit
            """,
            {"limit": limit},
        )
        if not row.get("_query_error")
    )
    candidates.extend(
        {
            "tenant_id": row.get("tenant_id"),
            "source_type": "webhook_event",
            "source_id": row.get("id"),
            "provider": row.get("provider"),
            "channel": row.get("provider"),
            "reason": row.get("error") or row.get("status") or "webhook_error",
            "severity": "high",
            "payload_json": row,
            "correlation_id": row.get("correlation_id") or "",
        }
        for row in _safe_rows(
            conn,
            """
            SELECT id::text, tenant_id::text, provider, event_id, status, error, correlation_id,
                   received_at::text, processed_at::text
            FROM saas_webhook_events
            WHERE status = 'error' OR COALESCE(error, '') <> ''
            ORDER BY received_at DESC
            LIMIT :limit
            """,
            {"limit": limit},
        )
        if not row.get("_query_error")
    )
    candidates.extend(
        {
            "tenant_id": row.get("tenant_id"),
            "source_type": "scheduled_trigger",
            "source_id": row.get("id"),
            "provider": "",
            "channel": row.get("channel"),
            "reason": row.get("last_error") or row.get("status") or "trigger_failed",
            "severity": "medium",
            "payload_json": row,
            "correlation_id": row.get("correlation_id") or "",
        }
        for row in _safe_rows(
            conn,
            """
            SELECT id::text, tenant_id::text, channel, recipient_external_id,
                   status, attempts, last_error, correlation_id, run_at::text, updated_at::text
            FROM saas_trigger_scheduled_messages
            WHERE status = 'failed' OR COALESCE(last_error, '') <> ''
            ORDER BY updated_at DESC
            LIMIT :limit
            """,
            {"limit": limit},
        )
        if not row.get("_query_error")
    )
    candidates.extend(
        {
            "tenant_id": row.get("tenant_id"),
            "source_type": "ai_pending_reply",
            "source_id": row.get("id"),
            "provider": "ai",
            "channel": "ai",
            "reason": row.get("last_error") or row.get("status") or "ai_reply_failed",
            "severity": "medium",
            "payload_json": row,
            "correlation_id": row.get("correlation_id") or "",
        }
        for row in _safe_rows(
            conn,
            """
            SELECT id::text, tenant_id::text, conversation_id::text, status,
                   attempts, last_error, correlation_id, scheduled_at::text, updated_at::text
            FROM saas_ai_pending_replies
            WHERE status = 'failed' OR COALESCE(last_error, '') <> ''
            ORDER BY updated_at DESC
            LIMIT :limit
            """,
            {"limit": limit},
        )
        if not row.get("_query_error")
    )
    candidates.extend(
        {
            "tenant_id": row.get("tenant_id"),
            "source_type": "remarketing_enrollment",
            "source_id": row.get("id"),
            "provider": "",
            "channel": row.get("channel"),
            "reason": row.get("last_error") or row.get("state") or "remarketing_error",
            "severity": "medium",
            "payload_json": row,
        }
        for row in _safe_rows(
            conn,
            """
            SELECT id::text, tenant_id::text, flow_id::text, conversation_id::text,
                   channel, recipient_external_id, state, next_run_at::text,
                   last_error, updated_at::text
            FROM saas_remarketing_enrollments
            WHERE state = 'error' OR COALESCE(last_error, '') <> ''
            ORDER BY updated_at DESC
            LIMIT :limit
            """,
            {"limit": limit},
        )
        if not row.get("_query_error")
    )
    candidates.extend(
        {
            "tenant_id": row.get("tenant_id"),
            "source_type": "agent_orchestrator_job",
            "source_id": row.get("id"),
            "provider": "ai",
            "channel": row.get("channel") or "ai",
            "reason": row.get("error") or row.get("status") or "agent_orchestrator_failed",
            "severity": "medium",
            "payload_json": row,
        }
        for row in _safe_rows(
            conn,
            """
            SELECT id::text, tenant_id::text, source, event_type, entity_type, entity_id,
                   channel, status, attempts, max_attempts, scheduled_at::text,
                   error, updated_at::text
            FROM saas_ai_agent_orchestration_jobs
            WHERE status = 'failed' OR COALESCE(error, '') <> ''
            ORDER BY updated_at DESC
            LIMIT :limit
            """,
            {"limit": limit},
        )
        if not row.get("_query_error")
    )
    candidates.extend(
        {
            "tenant_id": row.get("tenant_id"),
            "source_type": "ai_gateway_run",
            "source_id": row.get("id"),
            "provider": row.get("provider_code") or "ai",
            "channel": "ai",
            "reason": row.get("error_message") or row.get("error_code") or row.get("status") or "ai_gateway_failed",
            "severity": "medium",
            "payload_json": row,
        }
        for row in _safe_rows(
            conn,
            """
            SELECT id::text, tenant_id::text, conversation_id::text, agent_type,
                   task_type, route_code, provider_code, model, status, error_code,
                   error_message, metadata_json, created_at::text
            FROM saas_ai_runs
            WHERE status = 'failed'
              AND created_at >= NOW() - INTERVAL '7 days'
            ORDER BY created_at DESC
            LIMIT :limit
            """,
            {"limit": limit},
        )
        if not row.get("_query_error")
    )
    for row in meta_error_history(conn, limit=limit):
        candidates.append(
            {
                "tenant_id": row.get("tenant_id"),
                "source_type": row.get("source_type"),
                "source_id": row.get("source_id"),
                "provider": row.get("provider"),
                "channel": row.get("channel"),
                "reason": row.get("error_message") or row.get("status") or "meta_error",
                "severity": "high",
                "payload_json": row,
                "correlation_id": row.get("correlation_id") or "",
            }
        )
    for candidate in candidates[: max(1, min(limit, 500))]:
        _upsert_dead_letter(conn, candidate)
    return {"synced": len(candidates[: max(1, min(limit, 500))]), "candidates": len(candidates)}


def dead_letter_events(conn, limit: int = 100, status: str = "open", source_type: str = "") -> list[dict[str, Any]]:
    ensure_dead_letter_table(conn)
    where = ["1=1"]
    params: dict[str, Any] = {"limit": max(1, min(limit, 300))}
    if status and status != "all":
        where.append("d.status = :status")
        params["status"] = status
    if source_type and source_type != "all":
        where.append("d.source_type = :source_type")
        params["source_type"] = source_type
    rows = _safe_rows(
        conn,
        f"""
        SELECT d.id::text, d.tenant_id::text, t.name AS tenant_name, t.slug AS tenant_slug,
               d.source_type, d.source_id, d.provider, d.channel, d.status,
               d.reason, d.severity, d.correlation_id, d.payload_json, d.first_seen_at::text,
               d.last_seen_at::text, d.resolved_at::text
        FROM saas_dead_letter_events d
        LEFT JOIN saas_tenants t ON t.id = d.tenant_id
        WHERE {" AND ".join(where)}
        ORDER BY d.last_seen_at DESC
        LIMIT :limit
        """,
        params,
    )
    for row in rows:
        payload = _json_value(row.get("payload_json"))
        payload = payload if isinstance(payload, dict) else {}
        row["payload_json"] = payload
        row["diagnosis"] = _diagnosis_for(str(row.get("source_type") or ""), str(row.get("reason") or ""), payload)
        retry = _retry_info(payload)
        retry["retryable"] = str(row.get("source_type") or "") in {
            "outbound_message",
            "webhook_event",
            "scheduled_trigger",
            "ai_pending_reply",
            "remarketing_enrollment",
            "agent_orchestrator_job",
        }
        row["retry_info"] = retry
    return rows


def retry_dead_letter(conn, event_id: str) -> dict[str, Any]:
    ensure_dead_letter_table(conn)
    event = conn.execute(
        text(
            """
            SELECT id::text, tenant_id::text, source_type, source_id
            FROM saas_dead_letter_events
            WHERE id = CAST(:id AS uuid)
            LIMIT 1
            """
        ),
        {"id": event_id},
    ).mappings().first()
    if not event:
        return {"ok": False, "error": "dead_letter_not_found"}

    source_type = str(event["source_type"] or "")
    source_id = _uuid_text(event["source_id"])
    if not source_id:
        return {"ok": False, "error": "invalid_source_id", "source_type": source_type}

    queue_kind = ""
    result = None
    if source_type == "outbound_message":
        queue_kind = "outbound"
        result = conn.execute(
            text(
                """
                UPDATE saas_outbound_messages
                SET status = 'queued',
                    attempts = 0,
                    error = '',
                    locked_at = NULL,
                    next_attempt_at = NOW(),
                    updated_at = NOW()
                WHERE id = CAST(:source_id AS uuid)
                """
            ),
            {"source_id": source_id},
        )
    elif source_type == "webhook_event":
        queue_kind = "webhooks"
        result = conn.execute(
            text(
                """
                UPDATE saas_webhook_events
                SET status = 'received',
                    error = '',
                    processed_at = NULL
                WHERE id = CAST(:source_id AS uuid)
                """
            ),
            {"source_id": source_id},
        )
    elif source_type == "scheduled_trigger":
        queue_kind = "triggers"
        result = conn.execute(
            text(
                """
                UPDATE saas_trigger_scheduled_messages
                SET status = 'pending',
                    attempts = 0,
                    last_error = '',
                    run_at = NOW(),
                    updated_at = NOW()
                WHERE id = CAST(:source_id AS uuid)
                """
            ),
            {"source_id": source_id},
        )
    elif source_type == "ai_pending_reply":
        queue_kind = "ai"
        result = conn.execute(
            text(
                """
                UPDATE saas_ai_pending_replies
                SET status = 'pending',
                    attempts = 0,
                    last_error = '',
                    scheduled_at = NOW(),
                    updated_at = NOW()
                WHERE id = CAST(:source_id AS uuid)
                """
            ),
            {"source_id": source_id},
        )
    elif source_type == "remarketing_enrollment":
        queue_kind = "remarketing"
        result = conn.execute(
            text(
                """
                UPDATE saas_remarketing_enrollments
                SET state = 'active',
                    last_error = '',
                    next_run_at = NOW(),
                    updated_at = NOW()
                WHERE id = CAST(:source_id AS uuid)
                """
            ),
            {"source_id": source_id},
        )
    elif source_type == "agent_orchestrator_job":
        queue_kind = "agents"
        result = conn.execute(
            text(
                """
                UPDATE saas_ai_agent_orchestration_jobs
                SET status = 'queued',
                    attempts = 0,
                    error = '',
                    locked_by = '',
                    locked_at = NULL,
                    scheduled_at = NOW(),
                    completed_at = NULL,
                    updated_at = NOW()
                WHERE id = CAST(:source_id AS uuid)
                """
            ),
            {"source_id": source_id},
        )
    else:
        return {"ok": False, "error": "source_not_retryable", "source_type": source_type}

    updated = int(getattr(result, "rowcount", 0) or 0)
    if not updated:
        return {"ok": False, "error": "source_not_found", "source_type": source_type, "source_id": source_id}
    conn.execute(
        text(
            """
            UPDATE saas_dead_letter_events
            SET status = 'retrying', last_seen_at = NOW(), resolved_at = NULL
            WHERE id = CAST(:id AS uuid)
            """
        ),
        {"id": event_id},
    )
    return {
        "ok": True,
        "source_type": source_type,
        "source_id": source_id,
        "tenant_id": event.get("tenant_id") or "",
        "queue_kind": queue_kind,
        "updated": updated,
    }


def resolve_dead_letter(conn, event_id: str) -> bool:
    ensure_dead_letter_table(conn)
    result = conn.execute(
        text(
            """
            UPDATE saas_dead_letter_events
            SET status = 'resolved', resolved_at = NOW(), last_seen_at = NOW()
            WHERE id = CAST(:id AS uuid)
            """
        ),
        {"id": event_id},
    )
    return bool(result.rowcount)
