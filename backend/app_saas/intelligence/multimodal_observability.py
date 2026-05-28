from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app_saas.intelligence.premium import provider_policy_for
from app_saas.intelligence.service import resolve_intelligence_access

OBSERVABILITY_FEATURE_KEYS = (
    "multimodal_observability",
    "multimodal_cost_observability",
    "multimodal_quality_monitoring",
    "ai_premium",
)
ROLLOUT_FEATURE_KEYS = ("multimodal_safe_rollout", "multimodal_canary", "ai_premium")
VALID_MODALITIES = {"all", "voice", "vision", "web_search", "image_search", "mixed_search", "agent_tool", "memory"}
VALID_ROLLOUT_MODES = {"off", "demo", "canary", "full"}
WINDOWS = {
    "24h": "INTERVAL '24 hours'",
    "7d": "INTERVAL '7 days'",
    "30d": "INTERVAL '30 days'",
    "90d": "INTERVAL '90 days'",
}


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


def _num(value: Any) -> float:
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _table_exists(conn: Connection, table_name: str) -> bool:
    return bool(conn.execute(text("SELECT to_regclass(:table_name)"), {"table_name": table_name}).scalar())


def _window_interval(window_key: str) -> tuple[str, str]:
    key = _clean(window_key, 20).lower() or "30d"
    return (key if key in WINDOWS else "30d", WINDOWS.get(key, WINDOWS["30d"]))


def _normalize_modality(value: Any) -> str:
    clean = _clean(value, 40).lower().replace("-", "_")
    return clean if clean in VALID_MODALITIES else "all"


def _normalize_rollout_mode(value: Any, *, enabled: bool) -> str:
    if not enabled:
        return "off"
    clean = _clean(value, 40).lower().replace("-", "_")
    return clean if clean in VALID_ROLLOUT_MODES else "demo"


def _resolve_any_access(conn: Connection, tenant_id: str, keys: tuple[str, ...], *, allow_demo: bool = True) -> dict[str, Any]:
    last_detail: Any = None
    for feature_key in keys:
        try:
            access = dict(resolve_intelligence_access(conn, tenant_id, feature_key, allow_demo=allow_demo))
            access["resolved_feature_key"] = feature_key
            return access
        except HTTPException as exc:
            last_detail = exc.detail
    raise HTTPException(status_code=403, detail={"code": "multimodal_feature_not_enabled", "features": list(keys), "last_error": last_detail})


def ensure_multimodal_observability_tables(conn: Connection) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_multimodal_observability_snapshots (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                window_key TEXT NOT NULL DEFAULT '30d',
                modality TEXT NOT NULL DEFAULT 'all',
                provider_code TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'ok',
                request_count INTEGER NOT NULL DEFAULT 0,
                success_count INTEGER NOT NULL DEFAULT 0,
                error_count INTEGER NOT NULL DEFAULT 0,
                cached_count INTEGER NOT NULL DEFAULT 0,
                avg_latency_ms NUMERIC(18,4) NOT NULL DEFAULT 0,
                p95_latency_ms NUMERIC(18,4) NOT NULL DEFAULT 0,
                estimated_cost_cents NUMERIC(18,6) NOT NULL DEFAULT 0,
                avg_quality_score NUMERIC(8,4) NOT NULL DEFAULT 0,
                source_count INTEGER NOT NULL DEFAULT 0,
                approved_source_count INTEGER NOT NULL DEFAULT 0,
                blocked_source_count INTEGER NOT NULL DEFAULT 0,
                metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                cost_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                quality_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                sources_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                computed_at TIMESTAMP NOT NULL DEFAULT NOW(),
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, window_key, modality, provider_code)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_multimodal_obs_snapshots_tenant ON saas_multimodal_observability_snapshots (tenant_id, window_key, modality, updated_at DESC)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_multimodal_rollout_policies (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                feature_key TEXT NOT NULL DEFAULT 'multimodal_safe_rollout',
                modality TEXT NOT NULL DEFAULT 'all',
                provider_code TEXT NOT NULL DEFAULT '',
                enabled BOOLEAN NOT NULL DEFAULT FALSE,
                mode TEXT NOT NULL DEFAULT 'off',
                demo_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                canary_percent INTEGER NOT NULL DEFAULT 0,
                max_error_rate NUMERIC(8,4) NOT NULL DEFAULT 0,
                max_latency_p95_ms INTEGER NOT NULL DEFAULT 0,
                min_quality_score NUMERIC(8,4) NOT NULL DEFAULT 0,
                monthly_cost_limit_cents INTEGER NOT NULL DEFAULT 0,
                allowed_roles_json JSONB NOT NULL DEFAULT '["owner","admin","supervisor"]'::jsonb,
                settings_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                updated_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, feature_key, modality, provider_code)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_multimodal_rollout_policies_tenant ON saas_multimodal_rollout_policies (tenant_id, feature_key, modality, provider_code)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_multimodal_rollout_events (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                policy_id UUID NULL REFERENCES saas_multimodal_rollout_policies(id) ON DELETE SET NULL,
                feature_key TEXT NOT NULL DEFAULT '',
                modality TEXT NOT NULL DEFAULT '',
                provider_code TEXT NOT NULL DEFAULT '',
                subject_type TEXT NOT NULL DEFAULT '',
                subject_id TEXT NOT NULL DEFAULT '',
                decision TEXT NOT NULL DEFAULT 'allow',
                mode TEXT NOT NULL DEFAULT 'off',
                canary_bucket INTEGER NOT NULL DEFAULT 0,
                canary_percent INTEGER NOT NULL DEFAULT 0,
                reason TEXT NOT NULL DEFAULT '',
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_multimodal_rollout_events_tenant ON saas_multimodal_rollout_events (tenant_id, created_at DESC)"))


def _estimated_ai_cost_cents(conn: Connection, tenant_id: str, provider_code: str, model: str, requests: int, input_tokens: int, output_tokens: int) -> float:
    if not provider_code:
        return 0.0
    policy = provider_policy_for(conn, tenant_id, "ai", provider_code, model)
    return round(
        (_num(input_tokens) / 1000.0) * _num(policy.get("input_cost_cents_per_1k"))
        + (_num(output_tokens) / 1000.0) * _num(policy.get("output_cost_cents_per_1k"))
        + _num(requests) * _num(policy.get("request_cost_cents")),
        6,
    )


def _estimated_search_cost_cents(conn: Connection, tenant_id: str, provider_code: str, requests: int) -> float:
    if not provider_code:
        return 0.0
    policy = provider_policy_for(conn, tenant_id, "search", provider_code, "")
    return round(_num(requests) * _num(policy.get("request_cost_cents")), 6)


def _ai_task_metrics(conn: Connection, tenant_id: str, window_key: str, interval_sql: str, *, modality: str, task_type: str) -> list[dict[str, Any]]:
    if not _table_exists(conn, "saas_ai_runs"):
        return []
    rows = conn.execute(
        text(
            f"""
            SELECT provider_code, model,
                   COUNT(*)::int AS request_count,
                   COUNT(*) FILTER (WHERE status = 'success')::int AS success_count,
                   COUNT(*) FILTER (WHERE status IN ('failed', 'skipped'))::int AS error_count,
                   COALESCE(AVG(NULLIF(latency_ms, 0)), 0)::numeric(18,4) AS avg_latency_ms,
                   COALESCE(percentile_cont(0.95) WITHIN GROUP (ORDER BY NULLIF(latency_ms, 0)), 0)::numeric(18,4) AS p95_latency_ms,
                   COALESCE(SUM(input_tokens), 0)::int AS input_tokens,
                   COALESCE(SUM(output_tokens), 0)::int AS output_tokens,
                   COALESCE(SUM(total_tokens), 0)::int AS total_tokens,
                   COUNT(*) FILTER (WHERE fallback_used = TRUE)::int AS fallback_count,
                   COUNT(*) FILTER (WHERE error_code <> '')::int AS provider_error_count
            FROM saas_ai_runs
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND task_type = :task_type
              AND created_at >= NOW() - {interval_sql}
            GROUP BY provider_code, model
            ORDER BY request_count DESC, provider_code ASC
            LIMIT 80
            """
        ),
        {"tenant_id": tenant_id, "task_type": task_type},
    ).mappings().all()
    quality = _quality_by_provider(conn, tenant_id, interval_sql, modality)
    output: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        provider = _clean(item.get("provider_code"), 80)
        model = _clean(item.get("model"), 240)
        requests = int(item.get("request_count") or 0)
        item["window_key"] = window_key
        item["modality"] = modality
        item["estimated_cost_cents"] = _estimated_ai_cost_cents(
            conn,
            tenant_id,
            provider,
            model,
            requests,
            int(item.get("input_tokens") or 0),
            int(item.get("output_tokens") or 0),
        )
        item["avg_quality_score"] = quality.get(f"{provider}:{model}", quality.get(provider, 0.0))
        item["source_count"] = 0
        item["approved_source_count"] = 0
        item["blocked_source_count"] = 0
        item["status"] = _status_for(item)
        output.append(item)
    return output


def _quality_by_provider(conn: Connection, tenant_id: str, interval_sql: str, modality: str) -> dict[str, float]:
    table = "saas_voice_intelligence_analyses" if modality == "voice" else "saas_vision_intelligence_analyses"
    if not _table_exists(conn, table):
        return {}
    rows = conn.execute(
        text(
            f"""
            SELECT provider_code, model,
                   COALESCE(AVG(confidence), 0)::numeric(8,4) AS avg_confidence
            FROM {table}
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND created_at >= NOW() - {interval_sql}
            GROUP BY provider_code, model
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().all()
    out: dict[str, float] = {}
    for row in rows:
        provider = _clean(row.get("provider_code"), 80)
        model = _clean(row.get("model"), 240)
        score = round(_num(row.get("avg_confidence")) * 100.0, 2)
        out[f"{provider}:{model}"] = score
        out[provider] = max(out.get(provider, 0.0), score)
    return out


def _search_metrics(conn: Connection, tenant_id: str, window_key: str, interval_sql: str) -> list[dict[str, Any]]:
    if not _table_exists(conn, "saas_web_search_intelligence_runs"):
        return []
    rows = conn.execute(
        text(
            f"""
            SELECT provider_code, search_type,
                   COUNT(*)::int AS request_count,
                   COUNT(*) FILTER (WHERE status = 'completed')::int AS success_count,
                   COUNT(*) FILTER (WHERE status NOT IN ('completed'))::int AS error_count,
                   COALESCE(SUM(result_count), 0)::int AS source_count,
                   COALESCE(SUM(approved_count), 0)::int AS approved_source_count,
                   COALESCE(SUM(blocked_count), 0)::int AS blocked_source_count
            FROM saas_web_search_intelligence_runs
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND created_at >= NOW() - {interval_sql}
            GROUP BY provider_code, search_type
            ORDER BY request_count DESC, provider_code ASC
            LIMIT 80
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().all()
    output: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        requests = int(item.get("request_count") or 0)
        source_count = int(item.get("source_count") or 0)
        approved = int(item.get("approved_source_count") or 0)
        search_type = _clean(item.get("search_type"), 40)
        item["window_key"] = window_key
        item["modality"] = "image_search" if search_type == "image" else "web_search" if search_type == "web" else "mixed_search"
        item["model"] = ""
        item["cached_count"] = 0
        item["avg_latency_ms"] = 0
        item["p95_latency_ms"] = 0
        item["input_tokens"] = 0
        item["output_tokens"] = 0
        item["total_tokens"] = 0
        item["estimated_cost_cents"] = _estimated_search_cost_cents(conn, tenant_id, _clean(item.get("provider_code"), 80), requests)
        item["avg_quality_score"] = round((approved / source_count) * 100.0, 2) if source_count else 0
        item["fallback_count"] = 0
        item["provider_error_count"] = int(item.get("error_count") or 0)
        item["status"] = _status_for(item)
        output.append(item)
    return output


def _agent_tool_metrics(conn: Connection, tenant_id: str, window_key: str, interval_sql: str) -> list[dict[str, Any]]:
    if not _table_exists(conn, "saas_ai_agent_tool_runs"):
        return []
    rows = conn.execute(
        text(
            f"""
            SELECT tool_code,
                   COUNT(*)::int AS request_count,
                   COUNT(*) FILTER (WHERE status = 'completed')::int AS success_count,
                   COUNT(*) FILTER (WHERE status = 'failed')::int AS error_count,
                   COUNT(*) FILTER (WHERE approval_status = 'approved')::int AS approved_source_count
            FROM saas_ai_agent_tool_runs
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND tool_code IN ('media.voice_analyze', 'media.vision_analyze', 'media.web_image_search')
              AND created_at >= NOW() - {interval_sql}
            GROUP BY tool_code
            ORDER BY request_count DESC, tool_code ASC
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().all()
    output = []
    for row in rows:
        item = dict(row)
        item["window_key"] = window_key
        item["modality"] = "agent_tool"
        item["provider_code"] = _clean(item.get("tool_code"), 120)
        item["model"] = ""
        item["cached_count"] = 0
        item["avg_latency_ms"] = 0
        item["p95_latency_ms"] = 0
        item["estimated_cost_cents"] = 0
        item["avg_quality_score"] = round((int(item.get("success_count") or 0) / max(1, int(item.get("request_count") or 1))) * 100.0, 2)
        item["source_count"] = int(item.get("approved_source_count") or 0)
        item["blocked_source_count"] = 0
        item["fallback_count"] = 0
        item["provider_error_count"] = int(item.get("error_count") or 0)
        item["status"] = _status_for(item)
        output.append(item)
    return output


def _memory_metrics(conn: Connection, tenant_id: str, window_key: str, interval_sql: str) -> list[dict[str, Any]]:
    if not _table_exists(conn, "saas_multimodal_memory_events"):
        return []
    row = conn.execute(
        text(
            f"""
            SELECT COUNT(*)::int AS request_count,
                   COUNT(*) FILTER (WHERE status = 'ready')::int AS success_count,
                   COUNT(*) FILTER (WHERE status <> 'ready')::int AS error_count,
                   COUNT(*) FILTER (WHERE approval_status = 'approved')::int AS approved_source_count,
                   COUNT(*) FILTER (WHERE source_kind = 'web_search_result')::int AS source_count,
                   COALESCE(AVG(confidence), 0)::numeric(8,4) AS avg_confidence
            FROM saas_multimodal_memory_events
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND created_at >= NOW() - {interval_sql}
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    if not row or int(row.get("request_count") or 0) <= 0:
        return []
    item = dict(row)
    item.update(
        {
            "window_key": window_key,
            "modality": "memory",
            "provider_code": "multimodal_memory",
            "model": "",
            "cached_count": 0,
            "avg_latency_ms": 0,
            "p95_latency_ms": 0,
            "estimated_cost_cents": 0,
            "avg_quality_score": round(_num(item.get("avg_confidence")) * 100.0, 2),
            "blocked_source_count": 0,
            "fallback_count": 0,
            "provider_error_count": int(item.get("error_count") or 0),
        }
    )
    item["status"] = _status_for(item)
    return [item]


def _status_for(item: dict[str, Any]) -> str:
    requests = max(1, int(item.get("request_count") or 0))
    error_rate = int(item.get("error_count") or 0) / requests
    p95 = _num(item.get("p95_latency_ms"))
    quality = _num(item.get("avg_quality_score"))
    if error_rate >= 0.2 or p95 >= 30000:
        return "critical"
    if error_rate >= 0.08 or p95 >= 15000 or (quality and quality < 45):
        return "watch"
    return "ok"


def _aggregate_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    requests = sum(int(item.get("request_count") or 0) for item in rows)
    success = sum(int(item.get("success_count") or 0) for item in rows)
    errors = sum(int(item.get("error_count") or 0) for item in rows)
    cost = sum(_num(item.get("estimated_cost_cents")) for item in rows)
    source_count = sum(int(item.get("source_count") or 0) for item in rows)
    approved_sources = sum(int(item.get("approved_source_count") or 0) for item in rows)
    blocked_sources = sum(int(item.get("blocked_source_count") or 0) for item in rows)
    weighted_latency = sum(_num(item.get("avg_latency_ms")) * int(item.get("request_count") or 0) for item in rows)
    weighted_quality = sum(_num(item.get("avg_quality_score")) * int(item.get("request_count") or 0) for item in rows)
    return {
        "request_count": requests,
        "success_count": success,
        "error_count": errors,
        "error_rate": round(errors / requests, 4) if requests else 0,
        "success_rate": round(success / requests, 4) if requests else 0,
        "estimated_cost_cents": round(cost, 6),
        "estimated_cost_usd": round(cost / 100.0, 6),
        "avg_latency_ms": round(weighted_latency / requests, 2) if requests else 0,
        "p95_latency_ms": round(max((_num(item.get("p95_latency_ms")) for item in rows), default=0), 2),
        "avg_quality_score": round(weighted_quality / requests, 2) if requests else 0,
        "source_count": source_count,
        "approved_source_count": approved_sources,
        "blocked_source_count": blocked_sources,
        "fallback_count": sum(int(item.get("fallback_count") or 0) for item in rows),
        "provider_error_count": sum(int(item.get("provider_error_count") or 0) for item in rows),
        "status": "critical" if any(item.get("status") == "critical" for item in rows) else "watch" if any(item.get("status") == "watch" for item in rows) else "ok",
    }


def _source_domains(conn: Connection, tenant_id: str, interval_sql: str, limit: int) -> list[dict[str, Any]]:
    if not _table_exists(conn, "saas_web_search_intelligence_results"):
        return []
    rows = conn.execute(
        text(
            f"""
            SELECT COALESCE(NULLIF(source_name, ''), NULLIF(display_url, ''), 'external') AS source,
                   COUNT(*)::int AS total,
                   COUNT(*) FILTER (WHERE approval_status = 'approved')::int AS approved,
                   COUNT(*) FILTER (WHERE safety_status = 'blocked')::int AS blocked,
                   MAX(updated_at)::text AS last_seen_at
            FROM saas_web_search_intelligence_results
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND created_at >= NOW() - {interval_sql}
            GROUP BY COALESCE(NULLIF(source_name, ''), NULLIF(display_url, ''), 'external')
            ORDER BY approved DESC, total DESC, source ASC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "limit": max(1, min(int(limit or 20), 80))},
    ).mappings().all()
    return [dict(row) for row in rows]


def _rollout_policies(conn: Connection, tenant_id: str) -> list[dict[str, Any]]:
    ensure_multimodal_observability_tables(conn)
    rows = conn.execute(
        text(
            """
            SELECT id::text, tenant_id::text, feature_key, modality, provider_code,
                   enabled, mode, demo_enabled, canary_percent, max_error_rate,
                   max_latency_p95_ms, min_quality_score, monthly_cost_limit_cents,
                   allowed_roles_json, settings_json,
                   COALESCE(updated_by_user_id::text, '') AS updated_by_user_id,
                   created_at::text, updated_at::text
            FROM saas_multimodal_rollout_policies
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY feature_key ASC, modality ASC, provider_code ASC
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().all()
    return [dict(row) for row in rows]


def _rollout_events(conn: Connection, tenant_id: str, limit: int = 20) -> list[dict[str, Any]]:
    ensure_multimodal_observability_tables(conn)
    rows = conn.execute(
        text(
            """
            SELECT id::text, COALESCE(policy_id::text, '') AS policy_id,
                   feature_key, modality, provider_code, subject_type, subject_id,
                   decision, mode, canary_bucket, canary_percent, reason,
                   metadata_json, created_at::text
            FROM saas_multimodal_rollout_events
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "limit": max(1, min(int(limit or 20), 100))},
    ).mappings().all()
    return [dict(row) for row in rows]


def collect_multimodal_metrics(conn: Connection, tenant_id: str, *, window_key: str = "30d", limit: int = 20) -> dict[str, Any]:
    clean_window, interval_sql = _window_interval(window_key)
    rows: list[dict[str, Any]] = []
    rows.extend(_ai_task_metrics(conn, tenant_id, clean_window, interval_sql, modality="voice", task_type="voice_intelligence"))
    rows.extend(_ai_task_metrics(conn, tenant_id, clean_window, interval_sql, modality="vision", task_type="vision_intelligence"))
    rows.extend(_search_metrics(conn, tenant_id, clean_window, interval_sql))
    rows.extend(_agent_tool_metrics(conn, tenant_id, clean_window, interval_sql))
    rows.extend(_memory_metrics(conn, tenant_id, clean_window, interval_sql))
    modalities: dict[str, dict[str, Any]] = {}
    for item in rows:
        modality = str(item.get("modality") or "all")
        group_rows = [*modalities.get(modality, {}).get("_rows", []), item]
        modalities[modality] = _aggregate_metrics(group_rows)
        modalities[modality]["_rows"] = group_rows
    for item in modalities.values():
        item.pop("_rows", None)
    return {
        "window_key": clean_window,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": _aggregate_metrics(rows),
        "modalities": modalities,
        "providers": rows,
        "sources": _source_domains(conn, tenant_id, interval_sql, limit),
    }


def persist_multimodal_snapshots(conn: Connection, tenant_id: str, metrics: dict[str, Any]) -> list[dict[str, Any]]:
    ensure_multimodal_observability_tables(conn)
    saved: list[dict[str, Any]] = []
    window_key = _clean(metrics.get("window_key") or "30d", 20)
    for item in metrics.get("providers") or []:
        row = conn.execute(
            text(
                """
                INSERT INTO saas_multimodal_observability_snapshots (
                    tenant_id, window_key, modality, provider_code, status,
                    request_count, success_count, error_count, cached_count,
                    avg_latency_ms, p95_latency_ms, estimated_cost_cents,
                    avg_quality_score, source_count, approved_source_count,
                    blocked_source_count, metrics_json, cost_json, quality_json,
                    sources_json, computed_at, updated_at
                )
                VALUES (
                    CAST(:tenant_id AS uuid), :window_key, :modality, :provider_code, :status,
                    :request_count, :success_count, :error_count, :cached_count,
                    :avg_latency_ms, :p95_latency_ms, :estimated_cost_cents,
                    :avg_quality_score, :source_count, :approved_source_count,
                    :blocked_source_count, CAST(:metrics_json AS jsonb),
                    CAST(:cost_json AS jsonb), CAST(:quality_json AS jsonb),
                    CAST(:sources_json AS jsonb), NOW(), NOW()
                )
                ON CONFLICT (tenant_id, window_key, modality, provider_code)
                DO UPDATE SET
                    status = EXCLUDED.status,
                    request_count = EXCLUDED.request_count,
                    success_count = EXCLUDED.success_count,
                    error_count = EXCLUDED.error_count,
                    cached_count = EXCLUDED.cached_count,
                    avg_latency_ms = EXCLUDED.avg_latency_ms,
                    p95_latency_ms = EXCLUDED.p95_latency_ms,
                    estimated_cost_cents = EXCLUDED.estimated_cost_cents,
                    avg_quality_score = EXCLUDED.avg_quality_score,
                    source_count = EXCLUDED.source_count,
                    approved_source_count = EXCLUDED.approved_source_count,
                    blocked_source_count = EXCLUDED.blocked_source_count,
                    metrics_json = EXCLUDED.metrics_json,
                    cost_json = EXCLUDED.cost_json,
                    quality_json = EXCLUDED.quality_json,
                    sources_json = EXCLUDED.sources_json,
                    computed_at = NOW(),
                    updated_at = NOW()
                RETURNING id::text, window_key, modality, provider_code, status,
                          request_count, success_count, error_count, estimated_cost_cents,
                          avg_quality_score, computed_at::text, updated_at::text
                """
            ),
            {
                "tenant_id": tenant_id,
                "window_key": window_key,
                "modality": _clean(item.get("modality"), 40),
                "provider_code": _clean(item.get("provider_code") or item.get("tool_code") or "internal", 120),
                "status": _clean(item.get("status") or "ok", 40),
                "request_count": int(item.get("request_count") or 0),
                "success_count": int(item.get("success_count") or 0),
                "error_count": int(item.get("error_count") or 0),
                "cached_count": int(item.get("cached_count") or 0),
                "avg_latency_ms": _num(item.get("avg_latency_ms")),
                "p95_latency_ms": _num(item.get("p95_latency_ms")),
                "estimated_cost_cents": _num(item.get("estimated_cost_cents")),
                "avg_quality_score": _num(item.get("avg_quality_score")),
                "source_count": int(item.get("source_count") or 0),
                "approved_source_count": int(item.get("approved_source_count") or 0),
                "blocked_source_count": int(item.get("blocked_source_count") or 0),
                "metrics_json": _json(item),
                "cost_json": _json({"estimated_cost_cents": _num(item.get("estimated_cost_cents")), "currency": "USD"}),
                "quality_json": _json({"avg_quality_score": _num(item.get("avg_quality_score")), "status": item.get("status")}),
                "sources_json": _json({"source_count": int(item.get("source_count") or 0)}),
            },
        ).mappings().first()
        saved.append(dict(row or {}))
    return saved


def multimodal_observability_center(conn: Connection, tenant_id: str, *, window_key: str = "30d", limit: int = 20) -> dict[str, Any]:
    ensure_multimodal_observability_tables(conn)
    access = _resolve_any_access(conn, tenant_id, OBSERVABILITY_FEATURE_KEYS, allow_demo=True)
    metrics = collect_multimodal_metrics(conn, tenant_id, window_key=window_key, limit=limit)
    if str(access.get("mode") or "") == "demo":
        metrics["providers"] = (metrics.get("providers") or [])[:8]
        metrics["sources"] = (metrics.get("sources") or [])[:8]
        metrics["demo_limited"] = True
    return {
        "access": access,
        "metrics": metrics,
        "rollout": multimodal_rollout_center(conn, tenant_id, include_access=False),
        "safety": {
            "raw_media_logged": False,
            "external_sources_require_approval": True,
            "runtime_enforcement_requires_policy_enabled": True,
        },
    }


def refresh_multimodal_observability(
    conn: Connection,
    tenant_id: str,
    *,
    actor_user_id: str,
    window_key: str = "30d",
    dry_run: bool = False,
    limit: int = 20,
) -> dict[str, Any]:
    access = _resolve_any_access(conn, tenant_id, OBSERVABILITY_FEATURE_KEYS, allow_demo=True)
    metrics = collect_multimodal_metrics(conn, tenant_id, window_key=window_key, limit=limit)
    saved: list[dict[str, Any]] = []
    if not dry_run and str(access.get("mode") or "") == "full":
        saved = persist_multimodal_snapshots(conn, tenant_id, metrics)
    return {
        "access": access,
        "dry_run": bool(dry_run),
        "persisted": bool(saved),
        "saved_snapshots": saved,
        "metrics": metrics,
        "actor_user_id": actor_user_id,
    }


def _default_policy(tenant_id: str) -> dict[str, Any]:
    return {
        "id": "",
        "tenant_id": tenant_id,
        "feature_key": "multimodal_safe_rollout",
        "modality": "all",
        "provider_code": "",
        "enabled": False,
        "mode": "off",
        "demo_enabled": True,
        "canary_percent": 0,
        "max_error_rate": 0,
        "max_latency_p95_ms": 0,
        "min_quality_score": 0,
        "monthly_cost_limit_cents": 0,
        "allowed_roles_json": ["owner", "admin", "supervisor"],
        "settings_json": {},
        "updated_by_user_id": "",
        "created_at": "",
        "updated_at": "",
    }


def _matching_rollout_policy(conn: Connection, tenant_id: str, feature_key: str, modality: str, provider_code: str = "") -> dict[str, Any] | None:
    clean_feature = _clean(feature_key, 120).lower().replace("-", "_")
    clean_modality = _normalize_modality(modality)
    clean_provider = _clean(provider_code, 120).lower().replace("-", "_")
    candidates = [
        (clean_feature, clean_modality, clean_provider),
        (clean_feature, clean_modality, ""),
        (clean_feature, "all", ""),
        ("multimodal_safe_rollout", clean_modality, clean_provider),
        ("multimodal_safe_rollout", clean_modality, ""),
        ("multimodal_safe_rollout", "all", ""),
    ]
    for candidate_feature, candidate_modality, candidate_provider in candidates:
        row = conn.execute(
            text(
                """
                SELECT id::text, tenant_id::text, feature_key, modality, provider_code,
                       enabled, mode, demo_enabled, canary_percent, max_error_rate,
                       max_latency_p95_ms, min_quality_score, monthly_cost_limit_cents,
                       allowed_roles_json, settings_json,
                       COALESCE(updated_by_user_id::text, '') AS updated_by_user_id,
                       created_at::text, updated_at::text
                FROM saas_multimodal_rollout_policies
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND feature_key = :feature_key
                  AND modality = :modality
                  AND provider_code = :provider_code
                LIMIT 1
                """
            ),
            {
                "tenant_id": tenant_id,
                "feature_key": candidate_feature,
                "modality": candidate_modality,
                "provider_code": candidate_provider,
            },
        ).mappings().first()
        if row:
            return dict(row)
    return None


def multimodal_rollout_center(conn: Connection, tenant_id: str, *, include_access: bool = True) -> dict[str, Any]:
    ensure_multimodal_observability_tables(conn)
    access: dict[str, Any] | None = None
    if include_access:
        access = _resolve_any_access(conn, tenant_id, ROLLOUT_FEATURE_KEYS, allow_demo=True)
    policies = _rollout_policies(conn, tenant_id)
    active_policy = next((item for item in policies if item.get("enabled")), None) or _default_policy(tenant_id)
    return {
        "access": access,
        "policy": active_policy,
        "policies": policies,
        "events": _rollout_events(conn, tenant_id, limit=30),
        "modes": sorted(VALID_ROLLOUT_MODES),
        "modalities": sorted(VALID_MODALITIES),
        "default_state": {
            "feature_flag_default": "disabled",
            "policy_default": "off",
            "enforcement_without_policy": False,
            "demo_fallback_supported": True,
            "canary_assignment": "deterministic_hash_tenant_subject_feature",
        },
    }


def update_multimodal_rollout_policy(conn: Connection, tenant_id: str, actor_user_id: str, payload: Any) -> dict[str, Any]:
    ensure_multimodal_observability_tables(conn)
    access = _resolve_any_access(conn, tenant_id, ROLLOUT_FEATURE_KEYS, allow_demo=True)
    data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload or {})
    feature_key = _clean(data.get("feature_key") or "multimodal_safe_rollout", 120).lower().replace("-", "_")
    modality = _normalize_modality(data.get("modality") or "all")
    provider_code = _clean(data.get("provider_code"), 120).lower().replace("-", "_")
    mode = _normalize_rollout_mode(data.get("mode") or "demo", enabled=bool(data.get("enabled", True)))
    if str(access.get("mode") or "") == "demo" and mode not in {"off", "demo"}:
        raise HTTPException(status_code=403, detail={"code": "multimodal_rollout_full_required", "requested_mode": mode, "current_mode": "demo"})
    row = conn.execute(
        text(
            """
            INSERT INTO saas_multimodal_rollout_policies (
                tenant_id, feature_key, modality, provider_code,
                enabled, mode, demo_enabled, canary_percent,
                max_error_rate, max_latency_p95_ms, min_quality_score,
                monthly_cost_limit_cents, allowed_roles_json, settings_json,
                updated_by_user_id, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), :feature_key, :modality, :provider_code,
                :enabled, :mode, :demo_enabled, :canary_percent,
                :max_error_rate, :max_latency_p95_ms, :min_quality_score,
                :monthly_cost_limit_cents, CAST(:allowed_roles_json AS jsonb),
                CAST(:settings_json AS jsonb), CAST(:actor_user_id AS uuid), NOW()
            )
            ON CONFLICT (tenant_id, feature_key, modality, provider_code)
            DO UPDATE SET
                enabled = EXCLUDED.enabled,
                mode = EXCLUDED.mode,
                demo_enabled = EXCLUDED.demo_enabled,
                canary_percent = EXCLUDED.canary_percent,
                max_error_rate = EXCLUDED.max_error_rate,
                max_latency_p95_ms = EXCLUDED.max_latency_p95_ms,
                min_quality_score = EXCLUDED.min_quality_score,
                monthly_cost_limit_cents = EXCLUDED.monthly_cost_limit_cents,
                allowed_roles_json = EXCLUDED.allowed_roles_json,
                settings_json = EXCLUDED.settings_json,
                updated_by_user_id = EXCLUDED.updated_by_user_id,
                updated_at = NOW()
            RETURNING id::text, tenant_id::text, feature_key, modality, provider_code,
                      enabled, mode, demo_enabled, canary_percent, max_error_rate,
                      max_latency_p95_ms, min_quality_score, monthly_cost_limit_cents,
                      allowed_roles_json, settings_json,
                      COALESCE(updated_by_user_id::text, '') AS updated_by_user_id,
                      created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "feature_key": feature_key,
            "modality": modality,
            "provider_code": provider_code,
            "enabled": mode != "off",
            "mode": mode,
            "demo_enabled": bool(data.get("demo_enabled", True)),
            "canary_percent": max(0, min(100, int(data.get("canary_percent") or 0))),
            "max_error_rate": max(0.0, min(1.0, _num(data.get("max_error_rate")))),
            "max_latency_p95_ms": max(0, int(data.get("max_latency_p95_ms") or 0)),
            "min_quality_score": max(0.0, min(100.0, _num(data.get("min_quality_score")))),
            "monthly_cost_limit_cents": max(0, int(data.get("monthly_cost_limit_cents") or 0)),
            "allowed_roles_json": _json(data.get("allowed_roles_json") if isinstance(data.get("allowed_roles_json"), list) else ["owner", "admin", "supervisor"]),
            "settings_json": _json(data.get("settings_json") if isinstance(data.get("settings_json"), dict) else {}),
            "actor_user_id": actor_user_id,
        },
    ).mappings().first()
    return dict(row or {})


def _canary_bucket(tenant_id: str, feature_key: str, subject_id: str, provider_code: str = "") -> int:
    raw = f"{tenant_id}:{feature_key}:{subject_id}:{provider_code}".encode("utf-8", errors="ignore")
    return int(hashlib.sha256(raw).hexdigest()[:8], 16) % 100


def _record_rollout_event(
    conn: Connection,
    tenant_id: str,
    *,
    policy: dict[str, Any] | None,
    feature_key: str,
    modality: str,
    provider_code: str,
    subject_type: str,
    subject_id: str,
    decision: str,
    mode: str,
    canary_bucket: int,
    canary_percent: int,
    reason: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    ensure_multimodal_observability_tables(conn)
    conn.execute(
        text(
            """
            INSERT INTO saas_multimodal_rollout_events (
                tenant_id, policy_id, feature_key, modality, provider_code,
                subject_type, subject_id, decision, mode, canary_bucket,
                canary_percent, reason, metadata_json
            )
            VALUES (
                CAST(:tenant_id AS uuid), CAST(NULLIF(:policy_id, '') AS uuid),
                :feature_key, :modality, :provider_code, :subject_type, :subject_id,
                :decision, :mode, :canary_bucket, :canary_percent, :reason,
                CAST(:metadata_json AS jsonb)
            )
            """
        ),
        {
            "tenant_id": tenant_id,
            "policy_id": str((policy or {}).get("id") or ""),
            "feature_key": _clean(feature_key, 120),
            "modality": _normalize_modality(modality),
            "provider_code": _clean(provider_code, 120),
            "subject_type": _clean(subject_type, 80),
            "subject_id": _clean(subject_id, 180),
            "decision": _clean(decision, 80),
            "mode": _clean(mode, 40),
            "canary_bucket": int(canary_bucket or 0),
            "canary_percent": int(canary_percent or 0),
            "reason": _clean(reason, 500),
            "metadata_json": _json(metadata or {}),
        },
    )


def apply_multimodal_safe_rollout(
    conn: Connection,
    tenant_id: str,
    *,
    access: dict[str, Any],
    feature_key: str,
    modality: str,
    subject_type: str,
    subject_id: str,
    provider_code: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply optional Phase 24.10 rollout policy to a runtime access object.

    Compatibility rule: if the safe-rollout feature is disabled or no explicit
    enabled policy exists, existing Phase 24 runtime behavior is unchanged.
    """
    ensure_multimodal_observability_tables(conn)
    try:
        safe_access = _resolve_any_access(conn, tenant_id, ROLLOUT_FEATURE_KEYS, allow_demo=True)
    except HTTPException:
        enriched = dict(access)
        enriched["rollout"] = {"enforced": False, "reason": "safe_rollout_feature_disabled"}
        return enriched
    policy = _matching_rollout_policy(conn, tenant_id, feature_key, modality, provider_code)
    if not policy or not bool(policy.get("enabled")):
        enriched = dict(access)
        enriched["rollout"] = {
            "enforced": False,
            "reason": "no_enabled_policy",
            "safe_rollout_access": safe_access.get("mode") or "demo",
        }
        return enriched

    mode = _normalize_rollout_mode(policy.get("mode"), enabled=True)
    if str(safe_access.get("mode") or "") == "demo" and mode not in {"off", "demo"}:
        mode = "demo"
    bucket = _canary_bucket(tenant_id, feature_key, subject_id or tenant_id, provider_code)
    canary_percent = max(0, min(100, int(policy.get("canary_percent") or 0)))
    decision = "allow"
    reason = "policy_full"
    effective_access = dict(access)

    if mode == "off":
        decision = "deny"
        reason = "policy_off"
    elif mode == "demo":
        decision = "demo"
        reason = "policy_demo"
        effective_access["mode"] = "demo"
    elif mode == "canary":
        if bucket < canary_percent:
            decision = "allow"
            reason = "canary_selected"
        elif bool(policy.get("demo_enabled", True)):
            decision = "demo"
            reason = "canary_demo_fallback"
            effective_access["mode"] = "demo"
        else:
            decision = "deny"
            reason = "canary_not_selected"
    else:
        decision = "allow"
        reason = "policy_full"

    _record_rollout_event(
        conn,
        tenant_id,
        policy=policy,
        feature_key=feature_key,
        modality=modality,
        provider_code=provider_code,
        subject_type=subject_type,
        subject_id=subject_id,
        decision=decision,
        mode=mode,
        canary_bucket=bucket,
        canary_percent=canary_percent,
        reason=reason,
        metadata={
            **(metadata or {}),
            "runtime_feature_mode": access.get("mode"),
            "safe_rollout_access_mode": safe_access.get("mode"),
        },
    )
    if decision == "deny":
        raise HTTPException(
            status_code=403,
            detail={
                "code": "multimodal_safe_rollout_blocked",
                "feature_key": feature_key,
                "modality": modality,
                "mode": mode,
                "reason": reason,
                "canary_bucket": bucket,
                "canary_percent": canary_percent,
            },
        )
    effective_access["rollout"] = {
        "enforced": True,
        "policy_id": policy.get("id") or "",
        "mode": mode,
        "decision": decision,
        "reason": reason,
        "canary_bucket": bucket,
        "canary_percent": canary_percent,
        "demo_fallback": decision == "demo",
    }
    return effective_access
