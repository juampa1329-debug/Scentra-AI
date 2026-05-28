from __future__ import annotations

import json
import statistics
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app_saas.observability.service import global_health, queue_snapshot


RETENTION_ALLOWLIST: dict[str, dict[str, str]] = {
    "dead_letter_resolved": {
        "table": "saas_dead_letter_events",
        "timestamp": "resolved_at",
        "condition": "status = 'resolved' AND resolved_at IS NOT NULL",
    },
    "webhook_processed": {
        "table": "saas_webhook_events",
        "timestamp": "processed_at",
        "condition": "status IN ('processed', 'ignored') AND processed_at IS NOT NULL",
    },
    "ai_gateway_runs": {
        "table": "saas_ai_runs",
        "timestamp": "created_at",
        "condition": "created_at IS NOT NULL",
    },
    "intelligence_events": {
        "table": "saas_intelligence_events",
        "timestamp": "occurred_at",
        "condition": "occurred_at IS NOT NULL",
    },
    "ecosystem_traces": {
        "table": "saas_ai_ecosystem_traces",
        "timestamp": "created_at",
        "condition": "created_at IS NOT NULL",
    },
    "operation_reports": {
        "table": "saas_ai_operation_reports",
        "timestamp": "created_at",
        "condition": "created_at IS NOT NULL",
    },
}

EXPECTED_INDEXES: list[dict[str, str]] = [
    {"index_name": "idx_saas_webhook_events_status_received", "table_name": "saas_webhook_events", "purpose": "webhook queue scans by status/time"},
    {"index_name": "idx_saas_webhook_events_provider_status_received", "table_name": "saas_webhook_events", "purpose": "provider diagnostics and Meta error history"},
    {"index_name": "idx_saas_outbound_status_next", "table_name": "saas_outbound_messages", "purpose": "outbound dispatch due scans"},
    {"index_name": "idx_saas_outbound_channel_status_updated", "table_name": "saas_outbound_messages", "purpose": "channel diagnostics"},
    {"index_name": "idx_saas_trigger_sched_status_due", "table_name": "saas_trigger_scheduled_messages", "purpose": "scheduled trigger due scans"},
    {"index_name": "idx_saas_ai_pending_status_due", "table_name": "saas_ai_pending_replies", "purpose": "pending AI reply scans"},
    {"index_name": "idx_saas_rmk_enroll_state_due", "table_name": "saas_remarketing_enrollments", "purpose": "remarketing due scans"},
    {"index_name": "idx_saas_agent_orch_status_due", "table_name": "saas_ai_agent_orchestration_jobs", "purpose": "agent orchestration due scans"},
    {"index_name": "idx_saas_conversations_tenant_priority_updated", "table_name": "saas_conversations", "purpose": "inbox filters by tenant/priority"},
    {"index_name": "idx_saas_messages_tenant_direction_created", "table_name": "saas_messages", "purpose": "message analytics and dashboards"},
    {"index_name": "idx_saas_intelligence_events_time", "table_name": "saas_intelligence_events", "purpose": "event retention and analytics windows"},
    {"index_name": "idx_saas_audit_created", "table_name": "saas_audit_events", "purpose": "platform audit reads"},
]


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dump(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _safe_rows(conn, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    try:
        return [dict(row) for row in conn.execute(text(sql), params or {}).mappings().all()]
    except SQLAlchemyError as exc:
        return [{"_query_error": str(exc)[:500]}]


def _safe_one(conn, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    rows = _safe_rows(conn, sql, params)
    return rows[0] if rows else {}


def ensure_reliability_tables(conn) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_reliability_slo_policies (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                metric_key TEXT NOT NULL UNIQUE,
                label TEXT NOT NULL DEFAULT '',
                comparison TEXT NOT NULL DEFAULT 'lte',
                target_value NUMERIC(18,6) NOT NULL DEFAULT 0,
                warn_threshold NUMERIC(18,6) NOT NULL DEFAULT 0,
                critical_threshold NUMERIC(18,6) NOT NULL DEFAULT 0,
                window_minutes INTEGER NOT NULL DEFAULT 15,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                source TEXT NOT NULL DEFAULT 'system',
                notes TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_reliability_backpressure_policies (
                queue_key TEXT PRIMARY KEY,
                warn_backlog INTEGER NOT NULL DEFAULT 100,
                critical_backlog INTEGER NOT NULL DEFAULT 500,
                max_batch_size INTEGER NOT NULL DEFAULT 50,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                notes TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_reliability_retention_policies (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                policy_key TEXT NOT NULL UNIQUE,
                table_name TEXT NOT NULL,
                timestamp_column TEXT NOT NULL,
                retention_days INTEGER NOT NULL DEFAULT 180,
                batch_limit INTEGER NOT NULL DEFAULT 1000,
                enabled BOOLEAN NOT NULL DEFAULT FALSE,
                dry_run_default BOOLEAN NOT NULL DEFAULT TRUE,
                last_run_at TIMESTAMP NULL,
                last_deleted_count INTEGER NOT NULL DEFAULT 0,
                notes TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_reliability_cleanup_runs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                policy_key TEXT NOT NULL,
                table_name TEXT NOT NULL,
                dry_run BOOLEAN NOT NULL DEFAULT TRUE,
                status TEXT NOT NULL DEFAULT 'ok',
                matched_count INTEGER NOT NULL DEFAULT 0,
                deleted_count INTEGER NOT NULL DEFAULT 0,
                details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                started_at TIMESTAMP NOT NULL DEFAULT NOW(),
                finished_at TIMESTAMP NULL
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_reliability_snapshots (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                snapshot_key TEXT NOT NULL DEFAULT 'manual',
                status TEXT NOT NULL DEFAULT 'ok',
                slo_status TEXT NOT NULL DEFAULT 'ok',
                summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                queues_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                signals_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_reliability_drills (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                drill_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ok',
                result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                initiated_by TEXT NOT NULL DEFAULT '',
                started_at TIMESTAMP NOT NULL DEFAULT NOW(),
                finished_at TIMESTAMP NULL
            )
            """
        )
    )


def seed_reliability_defaults(conn) -> None:
    ensure_reliability_tables(conn)
    conn.execute(
        text(
            """
            INSERT INTO saas_reliability_slo_policies (
                metric_key, label, comparison, target_value, warn_threshold, critical_threshold, window_minutes, notes
            )
            VALUES
                ('db_probe_ms', 'DB probe latency', 'lte', 200, 500, 1500, 5, 'Readiness query latency in milliseconds.'),
                ('queue_backlog', 'Queue backlog', 'lte', 100, 500, 1500, 15, 'Total queued/pending runtime jobs.'),
                ('queue_error_total', 'Queue errors', 'lte', 0, 10, 50, 15, 'Failed/error/blocked runtime jobs.'),
                ('worker_fresh_ratio', 'Worker fresh ratio', 'gte', 1.0, 0.5, 0.1, 5, 'Fresh workers divided by total seen workers.'),
                ('ai_failure_rate_24h', 'AI failure rate 24h', 'lte', 0.02, 0.08, 0.20, 1440, 'AI Gateway failed runs divided by total runs.'),
                ('meta_error_total', 'Meta error total', 'lte', 0, 10, 50, 1440, 'Meta webhook/outbound/subscription/token error signals.')
            ON CONFLICT (metric_key) DO NOTHING
            """
        )
    )
    conn.execute(
        text(
            """
            INSERT INTO saas_reliability_backpressure_policies (
                queue_key, warn_backlog, critical_backlog, max_batch_size, notes
            )
            VALUES
                ('outbound', 100, 500, 50, 'Outbound provider delivery queue.'),
                ('webhooks', 100, 500, 50, 'Inbound webhook ingestion queue.'),
                ('scheduled_triggers', 100, 500, 50, 'Scheduled trigger queue.'),
                ('ai_pending', 50, 250, 25, 'Pending AI replies queue.'),
                ('remarketing', 100, 500, 50, 'Remarketing enrollments due queue.'),
                ('agent_orchestrator', 50, 250, 25, 'Agent orchestration queue.')
            ON CONFLICT (queue_key) DO NOTHING
            """
        )
    )
    for key, meta in RETENTION_ALLOWLIST.items():
        conn.execute(
            text(
                """
                INSERT INTO saas_reliability_retention_policies (
                    policy_key, table_name, timestamp_column, retention_days, batch_limit, enabled, dry_run_default, notes
                )
                VALUES (:policy_key, :table_name, :timestamp_column, :retention_days, :batch_limit, FALSE, TRUE, :notes)
                ON CONFLICT (policy_key) DO NOTHING
                """
            ),
            {
                "policy_key": key,
                "table_name": meta["table"],
                "timestamp_column": meta["timestamp"],
                "retention_days": 180 if key not in {"dead_letter_resolved", "intelligence_events"} else (90 if key == "dead_letter_resolved" else 365),
                "batch_limit": 1000,
                "notes": "Allowlisted Phase 12 retention policy. Manual enablement required for destructive cleanup.",
            },
        )


def _metric_status(value: float, policy: dict[str, Any]) -> str:
    comparison = str(policy.get("comparison") or "lte")
    warn = float(policy.get("warn_threshold") or 0)
    critical = float(policy.get("critical_threshold") or 0)
    if comparison == "gte":
        if value <= critical:
            return "critical"
        if value <= warn:
            return "warning"
        return "ok"
    if value >= critical:
        return "critical"
    if value >= warn:
        return "warning"
    return "ok"


def _overall_status(statuses: list[str]) -> str:
    if "critical" in statuses:
        return "critical"
    if "warning" in statuses:
        return "warning"
    return "ok"


def slo_status(conn) -> dict[str, Any]:
    seed_reliability_defaults(conn)
    started = time.perf_counter()
    conn.execute(text("SELECT 1"))
    db_probe_ms = (time.perf_counter() - started) * 1000
    health = global_health(conn)
    summary = health.get("summary") or {}
    workers = health.get("workers") or {}
    ai_runs = ((health.get("ai_gateway") or {}).get("runs") or {})
    meta = health.get("meta") or {}
    ai_total = max(0, int(ai_runs.get("runs_24h") or 0))
    ai_failed = max(0, int(ai_runs.get("failed_24h") or 0))
    values = {
        "db_probe_ms": round(db_probe_ms, 2),
        "queue_backlog": float(summary.get("backlog") or 0),
        "queue_error_total": float(summary.get("error_total") or 0),
        "worker_fresh_ratio": (float(workers.get("fresh") or 0) / float(workers.get("total") or 1)),
        "ai_failure_rate_24h": (float(ai_failed) / float(ai_total or 1)),
        "meta_error_total": float(meta.get("error_total") or 0),
    }
    policies = _safe_rows(
        conn,
        """
        SELECT metric_key, label, comparison, target_value, warn_threshold, critical_threshold,
               window_minutes, is_active, notes
        FROM saas_reliability_slo_policies
        WHERE is_active = TRUE
        ORDER BY metric_key
        """,
    )
    metrics: list[dict[str, Any]] = []
    for policy in policies:
        if policy.get("_query_error"):
            continue
        key = str(policy.get("metric_key") or "")
        value = float(values.get(key, 0))
        status = _metric_status(value, policy)
        metrics.append({**policy, "value": value, "status": status})
    return {
        "status": _overall_status([str(item.get("status")) for item in metrics]),
        "checked_at": _utc_now_text(),
        "metrics": metrics,
    }


def backpressure_status(conn) -> dict[str, Any]:
    seed_reliability_defaults(conn)
    queues = queue_snapshot(conn)
    policies = {
        row["queue_key"]: row
        for row in _safe_rows(
            conn,
            """
            SELECT queue_key, warn_backlog, critical_backlog, max_batch_size, is_active, notes
            FROM saas_reliability_backpressure_policies
            ORDER BY queue_key
            """,
        )
        if not row.get("_query_error")
    }
    pending_statuses = {
        "outbound": {"queued", "retry"},
        "webhooks": {"received"},
        "scheduled_triggers": {"pending"},
        "ai_pending": {"pending"},
        "remarketing": {"active"},
        "agent_orchestrator": {"queued"},
    }
    error_statuses = {
        "outbound": {"failed", "blocked"},
        "webhooks": {"error"},
        "scheduled_triggers": {"failed"},
        "ai_pending": {"failed", "skipped"},
        "remarketing": {"error"},
        "agent_orchestrator": {"failed"},
    }
    items: list[dict[str, Any]] = []
    for queue_key, rows in queues.items():
        policy = policies.get(queue_key) or {}
        pending = sum(int(row.get("total") or 0) for row in rows if str(row.get("status") or "") in pending_statuses.get(queue_key, set()))
        errors = sum(int(row.get("total") or 0) for row in rows if str(row.get("status") or "") in error_statuses.get(queue_key, set()))
        warn = int(policy.get("warn_backlog") or 100)
        critical = int(policy.get("critical_backlog") or 500)
        status = "critical" if pending >= critical or errors >= max(10, critical // 10) else "warning" if pending >= warn or errors else "ok"
        actions = []
        if status == "critical":
            actions.extend(["scale_worker", "process_queue_now", "pause_high_volume_senders_if_applicable"])
        elif status == "warning":
            actions.extend(["monitor", "process_queue_now"])
        items.append(
            {
                "queue_key": queue_key,
                "status": status,
                "pending": pending,
                "errors": errors,
                "warn_backlog": warn,
                "critical_backlog": critical,
                "max_batch_size": int(policy.get("max_batch_size") or 50),
                "is_active": bool(policy.get("is_active", True)),
                "recommended_actions": actions,
                "rows": rows,
            }
        )
    return {"status": _overall_status([item["status"] for item in items]), "queues": items}


def index_audit(conn) -> dict[str, Any]:
    present = {
        row["indexname"]
        for row in _safe_rows(
            conn,
            """
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = 'public'
            """
        )
        if row.get("indexname")
    }
    table_stats = {
        row["relname"]: row
        for row in _safe_rows(
            conn,
            """
            SELECT relname,
                   COALESCE(n_live_tup, 0)::bigint AS live_rows,
                   COALESCE(seq_scan, 0)::bigint AS seq_scan,
                   COALESCE(idx_scan, 0)::bigint AS idx_scan,
                   COALESCE(n_dead_tup, 0)::bigint AS dead_rows
            FROM pg_stat_user_tables
            """
        )
        if row.get("relname")
    }
    indexes = []
    for expected in EXPECTED_INDEXES:
        table_name = expected["table_name"]
        stats = table_stats.get(table_name, {})
        indexes.append(
            {
                **expected,
                "present": expected["index_name"] in present,
                "live_rows": int(stats.get("live_rows") or 0),
                "seq_scan": int(stats.get("seq_scan") or 0),
                "idx_scan": int(stats.get("idx_scan") or 0),
                "dead_rows": int(stats.get("dead_rows") or 0),
            }
        )
    missing = [item for item in indexes if not item["present"]]
    return {
        "status": "ok" if not missing else "warning",
        "expected": len(indexes),
        "present": len(indexes) - len(missing),
        "missing": len(missing),
        "indexes": indexes,
    }


def retention_policies(conn) -> list[dict[str, Any]]:
    seed_reliability_defaults(conn)
    rows = _safe_rows(
        conn,
        """
        SELECT policy_key, table_name, timestamp_column, retention_days, batch_limit,
               enabled, dry_run_default, last_run_at::text, last_deleted_count,
               notes, updated_at::text
        FROM saas_reliability_retention_policies
        ORDER BY policy_key
        """,
    )
    return rows


def update_retention_policy(conn, policy_key: str, patch: dict[str, Any]) -> dict[str, Any]:
    seed_reliability_defaults(conn)
    if policy_key not in RETENTION_ALLOWLIST:
        raise ValueError("retention_policy_not_allowlisted")
    allowed: dict[str, Any] = {}
    for key in ("retention_days", "batch_limit", "enabled", "dry_run_default", "notes"):
        if key in patch and patch[key] is not None:
            allowed[key] = patch[key]
    if not allowed:
        return {"updated": False, "policy": _safe_one(conn, "SELECT * FROM saas_reliability_retention_policies WHERE policy_key = :policy_key", {"policy_key": policy_key})}
    assignments = ", ".join(f"{key} = :{key}" for key in allowed)
    params = {"policy_key": policy_key, **allowed}
    row = conn.execute(
        text(
            f"""
            UPDATE saas_reliability_retention_policies
            SET {assignments}, updated_at = NOW()
            WHERE policy_key = :policy_key
            RETURNING policy_key, table_name, timestamp_column, retention_days, batch_limit,
                      enabled, dry_run_default, last_run_at::text, last_deleted_count, notes
            """
        ),
        params,
    ).mappings().first()
    return {"updated": True, "policy": dict(row or {})}


def _retention_count(conn, policy: dict[str, Any], meta: dict[str, str], limit: int) -> int:
    sql = f"""
        SELECT COUNT(*)::int AS total
        FROM (
            SELECT id
            FROM {meta["table"]}
            WHERE {meta["condition"]}
              AND {meta["timestamp"]} < NOW() - (:retention_days || ' days')::interval
            LIMIT :limit
        ) x
    """
    return int(conn.execute(text(sql), {"retention_days": int(policy["retention_days"]), "limit": limit}).scalar() or 0)


def _retention_delete(conn, policy: dict[str, Any], meta: dict[str, str], limit: int) -> int:
    sql = f"""
        WITH doomed AS (
            SELECT id
            FROM {meta["table"]}
            WHERE {meta["condition"]}
              AND {meta["timestamp"]} < NOW() - (:retention_days || ' days')::interval
            LIMIT :limit
        )
        DELETE FROM {meta["table"]}
        WHERE id IN (SELECT id FROM doomed)
    """
    result = conn.execute(text(sql), {"retention_days": int(policy["retention_days"]), "limit": limit})
    return int(getattr(result, "rowcount", 0) or 0)


def run_retention(conn, *, dry_run: bool = True, policy_key: str = "", include_disabled: bool = False) -> dict[str, Any]:
    seed_reliability_defaults(conn)
    where = ["1=1"]
    params: dict[str, Any] = {}
    if policy_key:
        where.append("policy_key = :policy_key")
        params["policy_key"] = policy_key
    if not include_disabled:
        where.append("enabled = TRUE")
    policies = _safe_rows(
        conn,
        f"""
        SELECT policy_key, table_name, timestamp_column, retention_days, batch_limit,
               enabled, dry_run_default
        FROM saas_reliability_retention_policies
        WHERE {" AND ".join(where)}
        ORDER BY policy_key
        """,
        params,
    )
    runs = []
    for policy in policies:
        key = str(policy.get("policy_key") or "")
        meta = RETENTION_ALLOWLIST.get(key)
        if not meta:
            continue
        started = time.perf_counter()
        limit = max(1, min(int(policy.get("batch_limit") or 1000), 10000))
        matched = _retention_count(conn, policy, meta, limit)
        deleted = 0 if dry_run else _retention_delete(conn, policy, meta, limit)
        status = "dry_run" if dry_run else "ok"
        details = {
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "allowlisted": True,
            "enabled": bool(policy.get("enabled")),
            "condition": meta["condition"],
        }
        conn.execute(
            text(
                """
                INSERT INTO saas_reliability_cleanup_runs (
                    policy_key, table_name, dry_run, status, matched_count, deleted_count,
                    details_json, started_at, finished_at
                )
                VALUES (
                    :policy_key, :table_name, :dry_run, :status, :matched_count,
                    :deleted_count, CAST(:details_json AS jsonb), NOW(), NOW()
                )
                """
            ),
            {
                "policy_key": key,
                "table_name": meta["table"],
                "dry_run": dry_run,
                "status": status,
                "matched_count": matched,
                "deleted_count": deleted,
                "details_json": _json_dump(details),
            },
        )
        conn.execute(
            text(
                """
                UPDATE saas_reliability_retention_policies
                SET last_run_at = NOW(), last_deleted_count = :deleted_count, updated_at = NOW()
                WHERE policy_key = :policy_key
                """
            ),
            {"policy_key": key, "deleted_count": deleted},
        )
        runs.append({"policy_key": key, "table_name": meta["table"], "dry_run": dry_run, "matched": matched, "deleted": deleted, **details})
    return {"ok": True, "dry_run": dry_run, "policy_key": policy_key or "all", "runs": runs, "total_matched": sum(item["matched"] for item in runs), "total_deleted": sum(item["deleted"] for item in runs)}


def recent_cleanup_runs(conn, limit: int = 20) -> list[dict[str, Any]]:
    rows = _safe_rows(
        conn,
        """
        SELECT id::text, policy_key, table_name, dry_run, status, matched_count,
               deleted_count, details_json, started_at::text, finished_at::text
        FROM saas_reliability_cleanup_runs
        ORDER BY started_at DESC
        LIMIT :limit
        """,
        {"limit": max(1, min(limit, 100))},
    )
    for row in rows:
        row["details_json"] = _json_value(row.get("details_json"))
    return rows


def record_reliability_snapshot(conn, snapshot_key: str = "manual") -> dict[str, Any]:
    seed_reliability_defaults(conn)
    health = global_health(conn)
    slo = slo_status(conn)
    backpressure = backpressure_status(conn)
    status = "critical" if health.get("status") == "down" or slo.get("status") == "critical" or backpressure.get("status") == "critical" else "warning" if health.get("status") == "degraded" or slo.get("status") == "warning" or backpressure.get("status") == "warning" else "ok"
    summary = {
        "health_status": health.get("status"),
        "slo_status": slo.get("status"),
        "backpressure_status": backpressure.get("status"),
        "summary": health.get("summary") or {},
        "workers": health.get("workers") or {},
        "api": health.get("api") or {},
    }
    signals = sorted(set((health.get("signals") or []) + [f"slo_{item['metric_key']}_{item['status']}" for item in slo.get("metrics", []) if item.get("status") != "ok"]))
    row = conn.execute(
        text(
            """
            INSERT INTO saas_reliability_snapshots (
                snapshot_key, status, slo_status, summary_json, queues_json, signals_json, created_at
            )
            VALUES (
                :snapshot_key, :status, :slo_status, CAST(:summary_json AS jsonb),
                CAST(:queues_json AS jsonb), CAST(:signals_json AS jsonb), NOW()
            )
            RETURNING id::text, created_at::text
            """
        ),
        {
            "snapshot_key": str(snapshot_key or "manual")[:80],
            "status": status,
            "slo_status": str(slo.get("status") or "unknown"),
            "summary_json": _json_dump(summary),
            "queues_json": _json_dump(backpressure),
            "signals_json": _json_dump(signals),
        },
    ).mappings().first()
    return {"id": row["id"], "created_at": row["created_at"], "status": status, "slo_status": slo.get("status"), "signals": signals}


def recent_snapshots(conn, limit: int = 20) -> list[dict[str, Any]]:
    rows = _safe_rows(
        conn,
        """
        SELECT id::text, snapshot_key, status, slo_status, summary_json, queues_json,
               signals_json, created_at::text
        FROM saas_reliability_snapshots
        ORDER BY created_at DESC
        LIMIT :limit
        """,
        {"limit": max(1, min(limit, 100))},
    )
    for row in rows:
        row["summary_json"] = _json_value(row.get("summary_json"))
        row["queues_json"] = _json_value(row.get("queues_json"))
        row["signals_json"] = _json_value(row.get("signals_json"))
    return rows


def _load_smoke(conn) -> dict[str, Any]:
    probes = [
        ("db_now", "SELECT NOW()"),
        ("tenant_count", "SELECT COUNT(*) FROM saas_tenants"),
        ("queue_outbound", "SELECT COUNT(*) FROM saas_outbound_messages WHERE status IN ('queued', 'retry')"),
        ("webhook_received", "SELECT COUNT(*) FROM saas_webhook_events WHERE status = 'received'"),
        ("intelligence_recent", "SELECT COUNT(*) FROM saas_intelligence_events WHERE occurred_at >= NOW() - INTERVAL '24 hours'"),
    ]
    results = []
    for key, sql in probes:
        started = time.perf_counter()
        value = conn.execute(text(sql)).scalar()
        results.append({"key": key, "value": int(value or 0) if key != "db_now" else str(value), "latency_ms": round((time.perf_counter() - started) * 1000, 2)})
    latencies = [float(item["latency_ms"]) for item in results]
    p95 = max(latencies) if len(latencies) < 2 else statistics.quantiles(latencies, n=20)[18]
    return {"status": "ok" if p95 < 1000 else "warning", "p95_ms": round(p95, 2), "probes": results}


def _backup_readiness(conn) -> dict[str, Any]:
    latest = _safe_one(
        conn,
        """
        SELECT file_name, applied_at::text
        FROM saas_schema_migrations
        ORDER BY file_name DESC
        LIMIT 1
        """
    )
    stats = _safe_one(
        conn,
        """
        SELECT current_database() AS database_name,
               pg_database_size(current_database())::bigint AS database_bytes,
               (SELECT COUNT(*)::int FROM information_schema.tables WHERE table_schema = 'public') AS public_tables,
               (SELECT COUNT(*)::int FROM saas_schema_migrations) AS migrations_applied
        """
    )
    return {
        "status": "ok" if str(latest.get("file_name") or "") >= "055" else "warning",
        "latest_migration": latest,
        "database": stats,
        "notes": "Readiness check only. Actual backup/restore must be executed by deployment infrastructure or database tooling.",
    }


def run_reliability_drill(conn, drill_type: str, initiated_by: str = "") -> dict[str, Any]:
    seed_reliability_defaults(conn)
    clean_type = str(drill_type or "slo_snapshot").strip().lower()
    started_at = _utc_now_text()
    if clean_type == "load_smoke":
        result = _load_smoke(conn)
    elif clean_type == "backup_readiness":
        result = _backup_readiness(conn)
    elif clean_type == "retention_dry_run":
        result = run_retention(conn, dry_run=True, include_disabled=True)
        result["status"] = "ok"
    elif clean_type == "slo_snapshot":
        result = record_reliability_snapshot(conn, snapshot_key="drill")
        result["status"] = result.get("status") or "ok"
    else:
        raise ValueError("unsupported_reliability_drill")
    status = str(result.get("status") or "ok")
    row = conn.execute(
        text(
            """
            INSERT INTO saas_reliability_drills (
                drill_type, status, result_json, initiated_by, started_at, finished_at
            )
            VALUES (:drill_type, :status, CAST(:result_json AS jsonb), :initiated_by, NOW(), NOW())
            RETURNING id::text, started_at::text, finished_at::text
            """
        ),
        {
            "drill_type": clean_type,
            "status": status,
            "result_json": _json_dump(result),
            "initiated_by": str(initiated_by or "")[:240],
        },
    ).mappings().first()
    return {"id": row["id"], "drill_type": clean_type, "status": status, "started_at": started_at, "finished_at": row["finished_at"], "result": result}


def recent_drills(conn, limit: int = 20) -> list[dict[str, Any]]:
    rows = _safe_rows(
        conn,
        """
        SELECT id::text, drill_type, status, result_json, initiated_by,
               started_at::text, finished_at::text
        FROM saas_reliability_drills
        ORDER BY started_at DESC
        LIMIT :limit
        """,
        {"limit": max(1, min(limit, 100))},
    )
    for row in rows:
        row["result_json"] = _json_value(row.get("result_json"))
    return rows


def reliability_overview(conn) -> dict[str, Any]:
    seed_reliability_defaults(conn)
    health = global_health(conn)
    slo = slo_status(conn)
    backpressure = backpressure_status(conn)
    indexes = index_audit(conn)
    cleanup_runs = recent_cleanup_runs(conn, limit=20)
    drills = recent_drills(conn, limit=20)
    snapshots = recent_snapshots(conn, limit=20)
    retention = retention_policies(conn)
    status = _overall_status([
        "critical" if health.get("status") == "down" else "warning" if health.get("status") == "degraded" else "ok",
        str(slo.get("status") or "ok"),
        str(backpressure.get("status") or "ok"),
        str(indexes.get("status") or "ok"),
    ])
    return {
        "status": status,
        "checked_at": _utc_now_text(),
        "health_summary": health.get("summary") or {},
        "slo": slo,
        "backpressure": backpressure,
        "index_audit": indexes,
        "retention_policies": retention,
        "cleanup_runs": cleanup_runs,
        "drills": drills,
        "snapshots": snapshots,
        "backup_readiness": _backup_readiness(conn),
    }


def process_due_reliability(conn) -> dict[str, Any]:
    seed_reliability_defaults(conn)
    last = _safe_one(
        conn,
        """
        SELECT created_at
        FROM saas_reliability_snapshots
        WHERE snapshot_key = 'worker'
          AND created_at >= NOW() - INTERVAL '15 minutes'
        ORDER BY created_at DESC
        LIMIT 1
        """,
    )
    if last.get("created_at"):
        return {"ok": True, "skipped": True, "reason": "recent_snapshot_exists"}
    snapshot = record_reliability_snapshot(conn, snapshot_key="worker")
    retention = run_retention(conn, dry_run=True, include_disabled=False)
    return {"ok": True, "snapshot": snapshot, "retention": retention}
