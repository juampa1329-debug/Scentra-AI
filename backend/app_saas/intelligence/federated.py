from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from statistics import median
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app_saas.intelligence.service import ensure_intelligence_tables, intelligence_feature_state, record_event, record_intelligence_usage, resolve_intelligence_access

FEDERATED_FEATURE_KEYS = (
    "federated_learning",
    "federated_model_updates",
    "privacy_safe_model_aggregation",
    "global_intelligence",
    "federated_benchmarking",
)
FEDERATED_FULL_KEYS = ("federated_learning", "federated_model_updates", "privacy_safe_model_aggregation", "ai_premium")
FEDERATED_READ_KEYS = ("federated_learning", "global_intelligence", "federated_benchmarking", "cross_tenant_intelligence", "intelligence_demo", "ai_premium")

VALID_TASKS = ("lead_scoring", "churn_prediction", "smart_remarketing", "operational_anomaly")
VALID_PRIVACY_MODES = {"aggregate_only", "differential_privacy", "secure_aggregation_ready"}
VALID_ROUND_STATUSES = {"open", "aggregating", "aggregated", "insufficient_sample", "closed"}

TASK_DEFINITIONS: dict[str, dict[str, Any]] = {
    "lead_scoring": {
        "label": "Lead scoring federado",
        "model_key": "scentra_federated_lead_scoring_v1",
        "metrics": ("avg_lead_score", "hot_lead_rate", "conversion_rate", "avg_response_time_minutes"),
        "importance": {"lead_score": 0.32, "message_engagement": 0.24, "response_time": 0.18, "crm_stage": 0.16, "payment_status": 0.10},
    },
    "churn_prediction": {
        "label": "Churn federado",
        "model_key": "scentra_federated_churn_v1",
        "metrics": ("inactive_14d_rate", "unread_rate", "avg_response_time_minutes", "negative_signal_rate"),
        "importance": {"inactivity_days": 0.34, "unread_count": 0.22, "negative_signals": 0.18, "response_time": 0.16, "channel_mix": 0.10},
    },
    "smart_remarketing": {
        "label": "Smart remarketing federado",
        "model_key": "scentra_federated_remarketing_v1",
        "metrics": ("campaign_positive_rate", "campaign_volume", "remarketing_active_rate", "conversion_rate"),
        "importance": {"campaign_response_rate": 0.30, "best_channel": 0.22, "followup_timing": 0.20, "segment_quality": 0.18, "template_quality": 0.10},
    },
    "operational_anomaly": {
        "label": "Operaciones federadas",
        "model_key": "scentra_federated_operations_v1",
        "metrics": ("webhook_failure_rate", "outbound_failure_rate", "ai_failure_rate", "trigger_failure_rate"),
        "importance": {"webhook_errors": 0.30, "queue_failures": 0.25, "ai_gateway_errors": 0.20, "trigger_failures": 0.15, "latency": 0.10},
    },
}


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def _clean(value: Any, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _num(value: Any, default: float = 0.0) -> float:
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _period_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m")


def _round_period() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _safe_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _safe_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _weighted_average(items: list[tuple[float, int]]) -> float:
    total_weight = sum(max(0, int(weight or 0)) for _, weight in items)
    if total_weight <= 0:
        return 0.0
    return sum(_num(value) * max(0, int(weight or 0)) for value, weight in items) / total_weight


def _hash_update(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _record_usage_any(conn: Connection, tenant_id: str, feature_keys: tuple[str, ...], *, quantity: int, usage_metric: str, metadata: dict[str, Any]) -> None:
    last_error: Exception | None = None
    for feature_key in feature_keys:
        try:
            record_intelligence_usage(conn, tenant_id, feature_key, quantity=quantity, usage_metric=usage_metric, metadata=metadata)
            return
        except HTTPException as exc:
            last_error = exc
    if last_error:
        raise last_error


def _normalize_task(task_type: str) -> str:
    clean = _clean(task_type, 120).lower().replace("-", "_")
    return clean if clean in TASK_DEFINITIONS else "lead_scoring"


def ensure_federated_learning_tables(conn: Connection) -> None:
    ensure_intelligence_tables(conn)
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_federated_learning_policies (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                opt_in_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                auto_participation_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                privacy_mode TEXT NOT NULL DEFAULT 'aggregate_only',
                min_local_samples INTEGER NOT NULL DEFAULT 25,
                min_cohort_tenants INTEGER NOT NULL DEFAULT 3,
                allowed_task_types_json JSONB NOT NULL DEFAULT '["lead_scoring","churn_prediction","smart_remarketing","operational_anomaly"]'::jsonb,
                differential_privacy_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                noise_multiplier NUMERIC(12,6) NOT NULL DEFAULT 0,
                clipping_norm NUMERIC(12,6) NOT NULL DEFAULT 1,
                share_model_metrics BOOLEAN NOT NULL DEFAULT TRUE,
                share_feature_importance BOOLEAN NOT NULL DEFAULT TRUE,
                settings_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                updated_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_federated_policies_tenant ON saas_federated_learning_policies (tenant_id, opt_in_enabled, updated_at DESC)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_federated_learning_rounds (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                round_key TEXT NOT NULL,
                task_type TEXT NOT NULL,
                model_key TEXT NOT NULL DEFAULT 'scentra_global_v1',
                model_version TEXT NOT NULL DEFAULT 'v1',
                industry_code TEXT NOT NULL DEFAULT 'general',
                cohort_key TEXT NOT NULL DEFAULT 'industry',
                window_key TEXT NOT NULL DEFAULT '90d',
                status TEXT NOT NULL DEFAULT 'open',
                min_participants INTEGER NOT NULL DEFAULT 3,
                min_total_samples INTEGER NOT NULL DEFAULT 100,
                aggregation_strategy TEXT NOT NULL DEFAULT 'weighted_average',
                privacy_budget_epsilon NUMERIC(12,6) NOT NULL DEFAULT 0,
                created_by_tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE SET NULL,
                created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                opened_at TIMESTAMP NOT NULL DEFAULT NOW(),
                closed_at TIMESTAMP NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (round_key)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_federated_rounds_lookup ON saas_federated_learning_rounds (industry_code, task_type, status, updated_at DESC)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_federated_learning_updates (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                round_id UUID NOT NULL REFERENCES saas_federated_learning_rounds(id) ON DELETE CASCADE,
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                update_key TEXT NOT NULL,
                task_type TEXT NOT NULL,
                model_key TEXT NOT NULL DEFAULT 'scentra_global_v1',
                model_version TEXT NOT NULL DEFAULT 'v1',
                industry_code TEXT NOT NULL DEFAULT 'general',
                window_key TEXT NOT NULL DEFAULT '90d',
                sample_count INTEGER NOT NULL DEFAULT 0,
                metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                feature_stats_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                feature_importance_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                privacy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                update_hash TEXT NOT NULL DEFAULT '',
                quality_score NUMERIC(8,4) NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'submitted',
                submitted_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                submitted_at TIMESTAMP NOT NULL DEFAULT NOW(),
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (round_id, tenant_id),
                UNIQUE (update_key)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_federated_updates_round ON saas_federated_learning_updates (round_id, status, submitted_at DESC)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_federated_updates_tenant ON saas_federated_learning_updates (tenant_id, task_type, updated_at DESC)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_federated_learning_aggregates (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                round_id UUID NOT NULL REFERENCES saas_federated_learning_rounds(id) ON DELETE CASCADE,
                task_type TEXT NOT NULL,
                model_key TEXT NOT NULL DEFAULT 'scentra_global_v1',
                model_version TEXT NOT NULL DEFAULT 'v1',
                industry_code TEXT NOT NULL DEFAULT 'general',
                window_key TEXT NOT NULL DEFAULT '90d',
                participant_count INTEGER NOT NULL DEFAULT 0,
                total_samples INTEGER NOT NULL DEFAULT 0,
                aggregate_metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                aggregate_feature_importance_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                benchmark_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                global_signal_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                privacy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                status TEXT NOT NULL DEFAULT 'candidate',
                created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                computed_at TIMESTAMP NOT NULL DEFAULT NOW(),
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (round_id)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_federated_aggregates_lookup ON saas_federated_learning_aggregates (industry_code, task_type, status, computed_at DESC)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_global_intelligence_signals (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                signal_key TEXT NOT NULL,
                signal_type TEXT NOT NULL DEFAULT 'federated_aggregate',
                industry_code TEXT NOT NULL DEFAULT 'general',
                task_type TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                confidence NUMERIC(8,4) NOT NULL DEFAULT 0,
                aggregate_id UUID NULL REFERENCES saas_federated_learning_aggregates(id) ON DELETE SET NULL,
                source_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                privacy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (signal_key)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_global_intelligence_signals_lookup ON saas_global_intelligence_signals (industry_code, task_type, status, updated_at DESC)"))


def _resolve_federated_access(conn: Connection, tenant_id: str, *, require_full: bool = False, allow_demo: bool = True) -> dict[str, Any]:
    candidates = FEDERATED_FULL_KEYS if require_full else FEDERATED_READ_KEYS
    last_detail: Any = None
    for key in candidates:
        try:
            access = resolve_intelligence_access(conn, tenant_id, key, allow_demo=allow_demo and not require_full)
            access = dict(access)
            access["access_feature"] = key
            access["federated_enabled"] = True
            return access
        except HTTPException as exc:
            last_detail = exc.detail
    if require_full:
        raise HTTPException(status_code=403, detail={"code": "federated_learning_requires_full", "features": list(candidates), "last_error": last_detail})
    return {
        "federated_enabled": False,
        "enabled": False,
        "mode": "disabled",
        "access_feature": "",
        "reason": "federated_learning_not_enabled",
        "last_error": last_detail,
    }


def _tenant_profile(conn: Connection, tenant_id: str) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            SELECT id::text AS tenant_id, name, slug, status, plan_code,
                   COALESCE(NULLIF(industry_code, ''), 'general') AS industry_code
            FROM saas_tenants
            WHERE id = CAST(:tenant_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="tenant_not_found")
    item = dict(row)
    item["industry_code"] = _clean(item.get("industry_code"), 80).lower().replace("-", "_") or "general"
    return item


def _normalize_allowed_tasks(value: Any) -> list[str]:
    items = [str(item or "").strip().lower().replace("-", "_") for item in _safe_list(value)]
    clean = [item for item in items if item in TASK_DEFINITIONS]
    return clean or list(VALID_TASKS)


def federated_policy(conn: Connection, tenant_id: str) -> dict[str, Any]:
    ensure_federated_learning_tables(conn)
    conn.execute(
        text(
            """
            INSERT INTO saas_federated_learning_policies (tenant_id)
            VALUES (CAST(:tenant_id AS uuid))
            ON CONFLICT (tenant_id) DO NOTHING
            """
        ),
        {"tenant_id": tenant_id},
    )
    row = conn.execute(
        text(
            """
            SELECT id::text, tenant_id::text, opt_in_enabled, auto_participation_enabled,
                   privacy_mode, min_local_samples, min_cohort_tenants, allowed_task_types_json,
                   differential_privacy_enabled, noise_multiplier, clipping_norm,
                   share_model_metrics, share_feature_importance, settings_json,
                   COALESCE(updated_by_user_id::text, '') AS updated_by_user_id,
                   created_at::text, updated_at::text
            FROM saas_federated_learning_policies
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    policy = dict(row or {})
    policy["allowed_task_types_json"] = _normalize_allowed_tasks(policy.get("allowed_task_types_json"))
    policy["settings_json"] = _safe_dict(policy.get("settings_json"))
    return policy


def update_federated_policy(conn: Connection, tenant_id: str, actor_user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    ensure_federated_learning_tables(conn)
    _resolve_federated_access(conn, tenant_id, require_full=True)
    privacy_mode = _clean(payload.get("privacy_mode") or "aggregate_only", 60).lower()
    if privacy_mode not in VALID_PRIVACY_MODES:
        privacy_mode = "aggregate_only"
    allowed_tasks = _normalize_allowed_tasks(payload.get("allowed_task_types_json"))
    params = {
        "tenant_id": tenant_id,
        "opt_in_enabled": bool(payload.get("opt_in_enabled")),
        "auto_participation_enabled": bool(payload.get("auto_participation_enabled")),
        "privacy_mode": privacy_mode,
        "min_local_samples": max(1, min(int(payload.get("min_local_samples") or 25), 1000000)),
        "min_cohort_tenants": max(3, min(int(payload.get("min_cohort_tenants") or 3), 10000)),
        "allowed_task_types_json": _json(allowed_tasks),
        "differential_privacy_enabled": bool(payload.get("differential_privacy_enabled", True)),
        "noise_multiplier": max(0.0, min(_num(payload.get("noise_multiplier")), 100.0)),
        "clipping_norm": max(0.0, min(_num(payload.get("clipping_norm"), 1.0), 1000000.0)),
        "share_model_metrics": bool(payload.get("share_model_metrics", True)),
        "share_feature_importance": bool(payload.get("share_feature_importance", True)),
        "settings_json": _json(payload.get("settings_json") or {}),
        "actor_user_id": actor_user_id,
    }
    row = conn.execute(
        text(
            """
            INSERT INTO saas_federated_learning_policies (
                tenant_id, opt_in_enabled, auto_participation_enabled, privacy_mode,
                min_local_samples, min_cohort_tenants, allowed_task_types_json,
                differential_privacy_enabled, noise_multiplier, clipping_norm,
                share_model_metrics, share_feature_importance, settings_json,
                updated_by_user_id, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), :opt_in_enabled, :auto_participation_enabled, :privacy_mode,
                :min_local_samples, :min_cohort_tenants, CAST(:allowed_task_types_json AS jsonb),
                :differential_privacy_enabled, :noise_multiplier, :clipping_norm,
                :share_model_metrics, :share_feature_importance, CAST(:settings_json AS jsonb),
                CAST(:actor_user_id AS uuid), NOW()
            )
            ON CONFLICT (tenant_id)
            DO UPDATE SET
                opt_in_enabled = EXCLUDED.opt_in_enabled,
                auto_participation_enabled = EXCLUDED.auto_participation_enabled,
                privacy_mode = EXCLUDED.privacy_mode,
                min_local_samples = EXCLUDED.min_local_samples,
                min_cohort_tenants = EXCLUDED.min_cohort_tenants,
                allowed_task_types_json = EXCLUDED.allowed_task_types_json,
                differential_privacy_enabled = EXCLUDED.differential_privacy_enabled,
                noise_multiplier = EXCLUDED.noise_multiplier,
                clipping_norm = EXCLUDED.clipping_norm,
                share_model_metrics = EXCLUDED.share_model_metrics,
                share_feature_importance = EXCLUDED.share_feature_importance,
                settings_json = EXCLUDED.settings_json,
                updated_by_user_id = EXCLUDED.updated_by_user_id,
                updated_at = NOW()
            RETURNING id::text, tenant_id::text, opt_in_enabled, auto_participation_enabled,
                      privacy_mode, min_local_samples, min_cohort_tenants, allowed_task_types_json,
                      differential_privacy_enabled, noise_multiplier, clipping_norm,
                      share_model_metrics, share_feature_importance, settings_json,
                      COALESCE(updated_by_user_id::text, '') AS updated_by_user_id,
                      created_at::text, updated_at::text
            """
        ),
        params,
    ).mappings().first()
    record_event(
        conn,
        tenant_id,
        {
            "event_type": "federated.policy_updated",
            "source": "federated_learning",
            "entity_type": "federated_policy",
            "entity_id": str(row.get("id") if row else ""),
            "payload_json": {"opt_in_enabled": params["opt_in_enabled"], "privacy_mode": privacy_mode, "allowed_tasks": allowed_tasks},
            "replay_key": f"federated:policy:{tenant_id}:{datetime.now(timezone.utc).isoformat()}",
        },
    )
    result = dict(row or {})
    result["allowed_task_types_json"] = _normalize_allowed_tasks(result.get("allowed_task_types_json"))
    result["settings_json"] = _safe_dict(result.get("settings_json"))
    return result


def _feature_values(conn: Connection, tenant_id: str) -> dict[str, float]:
    rows = conn.execute(
        text(
            """
            SELECT feature_key, value_numeric
            FROM saas_intelligence_feature_values
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND subject_type = 'tenant'
              AND subject_id = :tenant_id
            ORDER BY computed_at DESC
            LIMIT 120
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().all()
    return {str(row["feature_key"]): _num(row.get("value_numeric")) for row in rows}


def _local_raw_metrics(conn: Connection, tenant_id: str, window_key: str) -> dict[str, Any]:
    days = 90
    if window_key.endswith("d"):
        try:
            days = max(1, min(int(window_key[:-1]), 365))
        except ValueError:
            days = 90
    row = conn.execute(
        text(
            """
            WITH conv AS (
                SELECT
                    COUNT(*)::int AS conversations,
                    COALESCE(AVG(lead_score), 0)::numeric(18,6) AS avg_lead_score,
                    COUNT(*) FILTER (WHERE lead_score >= 75 OR LOWER(COALESCE(lead_temperature, '')) = 'hot')::int AS hot_leads,
                    COUNT(*) FILTER (
                        WHERE LOWER(COALESCE(payment_status, '')) IN ('paid','confirmed','completed','pago_confirmado')
                    )::int AS conversions,
                    COUNT(*) FILTER (WHERE last_message_at < NOW() - (:days * INTERVAL '1 day') OR last_message_at IS NULL)::int AS inactive_14d,
                    COALESCE(SUM(unread_count), 0)::int AS unread_count,
                    COALESCE(AVG(EXTRACT(EPOCH FROM (last_agent_message_at - last_customer_message_at)) / 60)
                        FILTER (
                            WHERE last_agent_message_at IS NOT NULL
                              AND last_customer_message_at IS NOT NULL
                              AND last_agent_message_at >= last_customer_message_at
                        ), 0)::numeric(18,6) AS avg_response_time_minutes
                FROM saas_conversations
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND updated_at >= NOW() - (:days * INTERVAL '1 day')
            ),
            campaign AS (
                SELECT
                    COUNT(*)::int AS campaign_events,
                    COUNT(*) FILTER (WHERE outcome IN ('clicked','replied','converted','sent','delivered','read','queued'))::int AS campaign_positive
                FROM saas_campaign_ab_events
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND created_at >= NOW() - (:days * INTERVAL '1 day')
            ),
            remarketing AS (
                SELECT
                    COUNT(*)::int AS remarketing_total,
                    COUNT(*) FILTER (WHERE state = 'active')::int AS remarketing_active
                FROM saas_remarketing_enrollments
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND GREATEST(updated_at, enrolled_at) >= NOW() - (:days * INTERVAL '1 day')
            ),
            webhooks AS (
                SELECT
                    COUNT(*)::int AS webhook_total,
                    COUNT(*) FILTER (WHERE status IN ('error','failed'))::int AS webhook_failed
                FROM saas_webhook_events
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND received_at >= NOW() - (:days * INTERVAL '1 day')
            ),
            outbound AS (
                SELECT
                    COUNT(*)::int AS outbound_total,
                    COUNT(*) FILTER (WHERE status IN ('failed','blocked'))::int AS outbound_failed
                FROM saas_outbound_messages
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND updated_at >= NOW() - (:days * INTERVAL '1 day')
            ),
            ai_runs AS (
                SELECT
                    COUNT(*)::int AS ai_total,
                    COUNT(*) FILTER (WHERE status = 'failed')::int AS ai_failed
                FROM saas_ai_runs
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND created_at >= NOW() - (:days * INTERVAL '1 day')
            ),
            triggers AS (
                SELECT
                    COUNT(*)::int AS trigger_total,
                    COUNT(*) FILTER (WHERE status <> 'ok')::int AS trigger_failed
                FROM saas_trigger_executions
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND executed_at >= NOW() - (:days * INTERVAL '1 day')
            )
            SELECT conv.*, campaign.*, remarketing.*, webhooks.*, outbound.*, ai_runs.*, triggers.*
            FROM conv, campaign, remarketing, webhooks, outbound, ai_runs, triggers
            """
        ),
        {"tenant_id": tenant_id, "days": days},
    ).mappings().first()
    return dict(row or {})


def _rate(numerator: Any, denominator: Any) -> float:
    denom = _num(denominator)
    if denom <= 0:
        return 0.0
    return round((_num(numerator) / denom) * 100.0, 6)


def build_local_update_package(conn: Connection, tenant_id: str, *, task_type: str, model_key: str = "", window_key: str = "90d") -> dict[str, Any]:
    ensure_federated_learning_tables(conn)
    tenant = _tenant_profile(conn, tenant_id)
    policy = federated_policy(conn, tenant_id)
    task = _normalize_task(task_type)
    definition = TASK_DEFINITIONS[task]
    model = _clean(model_key, 160) or str(definition["model_key"])
    raw = _local_raw_metrics(conn, tenant_id, window_key)
    features = _feature_values(conn, tenant_id)
    conversations = int(raw.get("conversations") or 0)
    campaign_events = int(raw.get("campaign_events") or 0)
    operational_events = int(raw.get("webhook_total") or 0) + int(raw.get("outbound_total") or 0) + int(raw.get("ai_total") or 0) + int(raw.get("trigger_total") or 0)
    sample_by_task = {
        "lead_scoring": conversations,
        "churn_prediction": conversations,
        "smart_remarketing": max(campaign_events, int(raw.get("remarketing_total") or 0)),
        "operational_anomaly": operational_events,
    }
    metrics = {
        "avg_lead_score": round(_num(raw.get("avg_lead_score")), 6),
        "hot_lead_rate": _rate(raw.get("hot_leads"), conversations),
        "conversion_rate": _rate(raw.get("conversions"), conversations),
        "avg_response_time_minutes": round(_num(raw.get("avg_response_time_minutes")), 6),
        "inactive_14d_rate": _rate(raw.get("inactive_14d"), conversations),
        "unread_rate": _rate(raw.get("unread_count"), max(conversations, 1)),
        "negative_signal_rate": _rate(int(raw.get("webhook_failed") or 0) + int(raw.get("outbound_failed") or 0), max(operational_events, 1)),
        "campaign_positive_rate": _rate(raw.get("campaign_positive"), campaign_events),
        "campaign_volume": float(campaign_events),
        "remarketing_active_rate": _rate(raw.get("remarketing_active"), raw.get("remarketing_total")),
        "webhook_failure_rate": _rate(raw.get("webhook_failed"), raw.get("webhook_total")),
        "outbound_failure_rate": _rate(raw.get("outbound_failed"), raw.get("outbound_total")),
        "ai_failure_rate": _rate(raw.get("ai_failed"), raw.get("ai_total")),
        "trigger_failure_rate": _rate(raw.get("trigger_failed"), raw.get("trigger_total")),
    }
    allowed_tasks = set(policy.get("allowed_task_types_json") or [])
    sample_count = int(sample_by_task.get(task) or 0)
    min_samples = int(policy.get("min_local_samples") or 25)
    blockers: list[str] = []
    if not bool(policy.get("opt_in_enabled")):
        blockers.append("tenant_not_opted_in")
    if task not in allowed_tasks:
        blockers.append("task_not_allowed_by_policy")
    if sample_count < min_samples:
        blockers.append("insufficient_local_samples")
    selected_metrics = {key: metrics.get(key, 0.0) for key in definition["metrics"]}
    completeness = sum(1 for value in selected_metrics.values() if _num(value) > 0) / max(1, len(selected_metrics))
    quality_score = min(100.0, 35.0 + min(sample_count, 500) / 10.0 + completeness * 25.0)
    if blockers:
        quality_score = min(quality_score, 60.0)
    feature_importance = dict(definition["importance"]) if bool(policy.get("share_feature_importance", True)) else {}
    feature_stats = {
        "window_key": _clean(window_key, 40) or "90d",
        "counts": {
            "conversations": conversations,
            "campaign_events": campaign_events,
            "remarketing_total": int(raw.get("remarketing_total") or 0),
            "operational_events": operational_events,
        },
        "feature_values": {key: round(_num(value), 6) for key, value in list(features.items())[:40]},
        "raw_content_used": False,
    }
    privacy = {
        "privacy_mode": policy.get("privacy_mode") or "aggregate_only",
        "raw_messages_shared": False,
        "raw_conversations_shared": False,
        "raw_media_shared": False,
        "tenant_identity_shared_in_aggregate": False,
        "differential_privacy_enabled": bool(policy.get("differential_privacy_enabled")),
        "noise_multiplier": _num(policy.get("noise_multiplier")),
        "clipping_norm": _num(policy.get("clipping_norm"), 1.0),
        "minimum_cohort_tenants": int(policy.get("min_cohort_tenants") or 3),
    }
    payload = {
        "tenant_id": tenant_id,
        "task_type": task,
        "model_key": model,
        "model_version": "v1",
        "industry_code": tenant["industry_code"],
        "window_key": _clean(window_key, 40) or "90d",
        "sample_count": sample_count,
        "metrics_json": selected_metrics,
        "feature_stats_json": feature_stats,
        "feature_importance_json": feature_importance,
        "privacy_json": privacy,
        "quality_score": round(quality_score, 4),
    }
    return {
        **payload,
        "tenant": tenant,
        "policy": policy,
        "eligible": not blockers,
        "blockers": blockers,
        "update_hash": _hash_update({key: value for key, value in payload.items() if key != "tenant_id"}),
        "task_definition": definition,
    }


def _round_key(industry_code: str, task_type: str, model_key: str, window_key: str) -> str:
    model_fragment = _clean(model_key, 80).lower().replace(" ", "_") or "scentra_global_v1"
    return f"federated:{_clean(industry_code, 80) or 'general'}:{_normalize_task(task_type)}:{model_fragment}:{_clean(window_key, 40) or '90d'}:{_round_period()}"


def _upsert_round(conn: Connection, tenant_id: str, actor_user_id: str, package: dict[str, Any], *, min_participants: int, min_total_samples: int, aggregation_strategy: str) -> dict[str, Any]:
    round_key = _round_key(str(package["industry_code"]), str(package["task_type"]), str(package["model_key"]), str(package["window_key"]))
    policy = package.get("policy") or {}
    row = conn.execute(
        text(
            """
            INSERT INTO saas_federated_learning_rounds (
                round_key, task_type, model_key, model_version, industry_code, cohort_key,
                window_key, status, min_participants, min_total_samples, aggregation_strategy,
                privacy_budget_epsilon, created_by_tenant_id, created_by_user_id, metadata_json, updated_at
            )
            VALUES (
                :round_key, :task_type, :model_key, :model_version, :industry_code, 'industry',
                :window_key, 'open', :min_participants, :min_total_samples, :aggregation_strategy,
                :privacy_budget_epsilon, CAST(:tenant_id AS uuid), CAST(NULLIF(:actor_user_id, '') AS uuid),
                CAST(:metadata_json AS jsonb), NOW()
            )
            ON CONFLICT (round_key)
            DO UPDATE SET
                status = CASE WHEN saas_federated_learning_rounds.status = 'closed' THEN saas_federated_learning_rounds.status ELSE 'open' END,
                min_participants = GREATEST(saas_federated_learning_rounds.min_participants, EXCLUDED.min_participants),
                min_total_samples = GREATEST(saas_federated_learning_rounds.min_total_samples, EXCLUDED.min_total_samples),
                aggregation_strategy = EXCLUDED.aggregation_strategy,
                metadata_json = saas_federated_learning_rounds.metadata_json || EXCLUDED.metadata_json,
                updated_at = NOW()
            RETURNING id::text, round_key, task_type, model_key, model_version, industry_code, cohort_key,
                      window_key, status, min_participants, min_total_samples, aggregation_strategy,
                      privacy_budget_epsilon, COALESCE(created_by_tenant_id::text, '') AS created_by_tenant_id,
                      COALESCE(created_by_user_id::text, '') AS created_by_user_id,
                      metadata_json, opened_at::text, closed_at::text, created_at::text, updated_at::text
            """
        ),
        {
            "round_key": round_key,
            "task_type": package["task_type"],
            "model_key": package["model_key"],
            "model_version": package["model_version"],
            "industry_code": package["industry_code"],
            "window_key": package["window_key"],
            "min_participants": max(3, int(min_participants or policy.get("min_cohort_tenants") or 3)),
            "min_total_samples": max(1, int(min_total_samples or max(int(policy.get("min_local_samples") or 25) * max(3, int(policy.get("min_cohort_tenants") or 3)), 100))),
            "aggregation_strategy": _clean(aggregation_strategy, 80) or "weighted_average",
            "privacy_budget_epsilon": 0 if bool(policy.get("differential_privacy_enabled")) else 0,
            "tenant_id": tenant_id,
            "actor_user_id": actor_user_id,
            "metadata_json": _json({"created_from": "tenant_update_package", "raw_content_used": False}),
        },
    ).mappings().first()
    return dict(row or {})


def _submit_package(conn: Connection, tenant_id: str, actor_user_id: str, round_row: dict[str, Any], package: dict[str, Any]) -> dict[str, Any]:
    if not package.get("eligible"):
        raise HTTPException(status_code=409, detail={"code": "federated_update_not_eligible", "blockers": package.get("blockers") or []})
    update_key = f"federated:update:{round_row['id']}:{tenant_id}"
    row = conn.execute(
        text(
            """
            INSERT INTO saas_federated_learning_updates (
                round_id, tenant_id, update_key, task_type, model_key, model_version,
                industry_code, window_key, sample_count, metrics_json, feature_stats_json,
                feature_importance_json, privacy_json, update_hash, quality_score, status,
                submitted_by_user_id, submitted_at, updated_at
            )
            VALUES (
                CAST(:round_id AS uuid), CAST(:tenant_id AS uuid), :update_key, :task_type, :model_key, :model_version,
                :industry_code, :window_key, :sample_count, CAST(:metrics_json AS jsonb), CAST(:feature_stats_json AS jsonb),
                CAST(:feature_importance_json AS jsonb), CAST(:privacy_json AS jsonb), :update_hash, :quality_score, 'submitted',
                CAST(NULLIF(:actor_user_id, '') AS uuid), NOW(), NOW()
            )
            ON CONFLICT (round_id, tenant_id)
            DO UPDATE SET
                sample_count = EXCLUDED.sample_count,
                metrics_json = EXCLUDED.metrics_json,
                feature_stats_json = EXCLUDED.feature_stats_json,
                feature_importance_json = EXCLUDED.feature_importance_json,
                privacy_json = EXCLUDED.privacy_json,
                update_hash = EXCLUDED.update_hash,
                quality_score = EXCLUDED.quality_score,
                status = 'submitted',
                submitted_by_user_id = EXCLUDED.submitted_by_user_id,
                submitted_at = NOW(),
                updated_at = NOW()
            RETURNING id::text, round_id::text, tenant_id::text, update_key, task_type, model_key,
                      model_version, industry_code, window_key, sample_count, metrics_json,
                      feature_stats_json, feature_importance_json, privacy_json, update_hash,
                      quality_score, status, COALESCE(submitted_by_user_id::text, '') AS submitted_by_user_id,
                      submitted_at::text, created_at::text, updated_at::text
            """
        ),
        {
            "round_id": round_row["id"],
            "tenant_id": tenant_id,
            "update_key": update_key,
            "task_type": package["task_type"],
            "model_key": package["model_key"],
            "model_version": package["model_version"],
            "industry_code": package["industry_code"],
            "window_key": package["window_key"],
            "sample_count": int(package["sample_count"] or 0),
            "metrics_json": _json(package["metrics_json"]),
            "feature_stats_json": _json(package["feature_stats_json"]),
            "feature_importance_json": _json(package["feature_importance_json"]),
            "privacy_json": _json(package["privacy_json"]),
            "update_hash": package["update_hash"],
            "quality_score": _num(package["quality_score"]),
            "actor_user_id": actor_user_id,
        },
    ).mappings().first()
    _record_usage_any(
        conn,
        tenant_id,
        ("federated_model_updates", "federated_learning", "ai_premium"),
        quantity=1,
        usage_metric="federated_update_submitted",
        metadata={"round_id": round_row["id"], "task_type": package["task_type"], "sample_count": package["sample_count"]},
    )
    record_event(
        conn,
        tenant_id,
        {
            "event_type": "federated.update_submitted",
            "source": "federated_learning",
            "entity_type": "federated_update",
            "entity_id": str(row.get("id") if row else ""),
            "payload_json": {
                "round_id": round_row["id"],
                "task_type": package["task_type"],
                "sample_count": package["sample_count"],
                "privacy": package["privacy_json"],
                "raw_content_used": False,
            },
            "replay_key": f"federated:update:{round_row['id']}:{tenant_id}:{package['update_hash']}",
        },
    )
    return dict(row or {})


def prepare_federated_round(
    conn: Connection,
    tenant_id: str,
    *,
    actor_user_id: str = "",
    task_type: str = "lead_scoring",
    model_key: str = "",
    window_key: str = "90d",
    dry_run: bool = True,
    min_participants: int = 3,
    min_total_samples: int = 100,
    aggregation_strategy: str = "weighted_average",
) -> dict[str, Any]:
    ensure_federated_learning_tables(conn)
    _resolve_federated_access(conn, tenant_id, require_full=not dry_run)
    package = build_local_update_package(conn, tenant_id, task_type=task_type, model_key=model_key, window_key=window_key)
    if dry_run:
        return {"dry_run": True, "round": None, "local_update": package, "submitted_update": None}
    round_row = _upsert_round(
        conn,
        tenant_id,
        actor_user_id,
        package,
        min_participants=min_participants,
        min_total_samples=min_total_samples,
        aggregation_strategy=aggregation_strategy,
    )
    update = _submit_package(conn, tenant_id, actor_user_id, round_row, package)
    return {"dry_run": False, "round": round_row, "local_update": package, "submitted_update": update}


def _get_round(conn: Connection, round_id: str) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            SELECT id::text, round_key, task_type, model_key, model_version, industry_code, cohort_key,
                   window_key, status, min_participants, min_total_samples, aggregation_strategy,
                   privacy_budget_epsilon, COALESCE(created_by_tenant_id::text, '') AS created_by_tenant_id,
                   COALESCE(created_by_user_id::text, '') AS created_by_user_id,
                   metadata_json, opened_at::text, closed_at::text, created_at::text, updated_at::text
            FROM saas_federated_learning_rounds
            WHERE id = CAST(:round_id AS uuid)
            LIMIT 1
            """
        ),
        {"round_id": round_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail={"code": "federated_round_not_found"})
    return dict(row)


def submit_federated_update(conn: Connection, tenant_id: str, actor_user_id: str, round_id: str, *, dry_run: bool = False) -> dict[str, Any]:
    ensure_federated_learning_tables(conn)
    _resolve_federated_access(conn, tenant_id, require_full=not dry_run)
    round_row = _get_round(conn, round_id)
    tenant = _tenant_profile(conn, tenant_id)
    if str(round_row.get("industry_code") or "general") not in {tenant["industry_code"], "general"}:
        raise HTTPException(status_code=403, detail={"code": "federated_round_industry_mismatch"})
    if str(round_row.get("status") or "") not in {"open", "aggregating", "insufficient_sample"}:
        raise HTTPException(status_code=409, detail={"code": "federated_round_not_open", "status": round_row.get("status")})
    package = build_local_update_package(
        conn,
        tenant_id,
        task_type=str(round_row["task_type"]),
        model_key=str(round_row["model_key"]),
        window_key=str(round_row["window_key"]),
    )
    if dry_run:
        return {"dry_run": True, "round": round_row, "local_update": package, "submitted_update": None}
    update = _submit_package(conn, tenant_id, actor_user_id, round_row, package)
    return {"dry_run": False, "round": round_row, "local_update": package, "submitted_update": update}


def _round_updates(conn: Connection, round_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT id::text, round_id::text, tenant_id::text, update_key, task_type, model_key,
                   model_version, industry_code, window_key, sample_count, metrics_json,
                   feature_stats_json, feature_importance_json, privacy_json, update_hash,
                   quality_score, status, COALESCE(submitted_by_user_id::text, '') AS submitted_by_user_id,
                   submitted_at::text, created_at::text, updated_at::text
            FROM saas_federated_learning_updates
            WHERE round_id = CAST(:round_id AS uuid)
              AND status = 'submitted'
            ORDER BY submitted_at DESC
            """
        ),
        {"round_id": round_id},
    ).mappings().all()
    return [dict(row) for row in rows]


def _aggregate_updates(updates: list[dict[str, Any]]) -> tuple[dict[str, float], dict[str, float], dict[str, Any]]:
    metric_keys: set[str] = set()
    importance_keys: set[str] = set()
    samples: list[int] = []
    qualities: list[float] = []
    for update in updates:
        metrics = _safe_dict(update.get("metrics_json"))
        importance = _safe_dict(update.get("feature_importance_json"))
        metric_keys.update(metrics.keys())
        importance_keys.update(importance.keys())
        samples.append(int(update.get("sample_count") or 0))
        qualities.append(_num(update.get("quality_score")))
    aggregated_metrics = {
        key: round(_weighted_average([(_safe_dict(update.get("metrics_json")).get(key, 0), int(update.get("sample_count") or 0)) for update in updates]), 6)
        for key in sorted(metric_keys)
    }
    aggregated_importance = {
        key: round(_weighted_average([(_safe_dict(update.get("feature_importance_json")).get(key, 0), int(update.get("sample_count") or 0)) for update in updates]), 6)
        for key in sorted(importance_keys)
    }
    benchmark = {
        "participant_count": len(updates),
        "total_samples": sum(samples),
        "median_sample_count": median(samples) if samples else 0,
        "avg_quality_score": round(sum(qualities) / len(qualities), 4) if qualities else 0,
        "raw_content_used": False,
    }
    return aggregated_metrics, aggregated_importance, benchmark


def _global_signal(task_type: str, industry_code: str, metrics: dict[str, float], benchmark: dict[str, Any]) -> dict[str, Any]:
    definition = TASK_DEFINITIONS.get(task_type) or TASK_DEFINITIONS["lead_scoring"]
    if task_type == "lead_scoring":
        focus = f"conversion {metrics.get('conversion_rate', 0):.1f}% y hot leads {metrics.get('hot_lead_rate', 0):.1f}%"
    elif task_type == "churn_prediction":
        focus = f"inactividad {metrics.get('inactive_14d_rate', 0):.1f}% y unread {metrics.get('unread_rate', 0):.1f}%"
    elif task_type == "smart_remarketing":
        focus = f"respuesta campanas {metrics.get('campaign_positive_rate', 0):.1f}%"
    else:
        focus = f"fallos webhook {metrics.get('webhook_failure_rate', 0):.1f}% y AI {metrics.get('ai_failure_rate', 0):.1f}%"
    return {
        "title": f"{definition['label']} - {industry_code}",
        "summary": f"Agregado federado con {int(benchmark.get('participant_count') or 0)} tenants y {int(benchmark.get('total_samples') or 0)} muestras: {focus}.",
        "confidence": min(0.95, 0.55 + (int(benchmark.get("participant_count") or 0) * 0.06) + (min(int(benchmark.get("total_samples") or 0), 1000) / 10000)),
        "recommended_action": "Usar como senal de benchmark/modelo candidato; no promocionar modelos automaticamente sin evaluacion.",
    }


def aggregate_federated_round(conn: Connection, tenant_id: str, actor_user_id: str, round_id: str, *, dry_run: bool = False) -> dict[str, Any]:
    ensure_federated_learning_tables(conn)
    _resolve_federated_access(conn, tenant_id, require_full=not dry_run)
    tenant = _tenant_profile(conn, tenant_id)
    round_row = _get_round(conn, round_id)
    if str(round_row.get("industry_code") or "general") not in {tenant["industry_code"], "general"}:
        raise HTTPException(status_code=403, detail={"code": "federated_round_industry_mismatch"})
    updates = _round_updates(conn, round_id)
    participants = len(updates)
    total_samples = sum(int(update.get("sample_count") or 0) for update in updates)
    min_participants = max(3, int(round_row.get("min_participants") or 3))
    min_total_samples = max(1, int(round_row.get("min_total_samples") or 100))
    aggregate_metrics, aggregate_importance, benchmark = _aggregate_updates(updates)
    privacy = {
        "raw_messages_shared": False,
        "raw_conversations_shared": False,
        "raw_media_shared": False,
        "tenant_names_shared": False,
        "minimum_participants": min_participants,
        "minimum_total_samples": min_total_samples,
        "aggregation_strategy": round_row.get("aggregation_strategy") or "weighted_average",
        "privacy_mode": "aggregate_only",
    }
    status = "aggregated" if participants >= min_participants and total_samples >= min_total_samples else "insufficient_sample"
    signal = _global_signal(str(round_row["task_type"]), str(round_row["industry_code"]), aggregate_metrics, benchmark)
    if dry_run:
        return {
            "dry_run": True,
            "round": round_row,
            "participant_count": participants,
            "total_samples": total_samples,
            "status": status,
            "aggregate": {
                "aggregate_metrics_json": aggregate_metrics,
                "aggregate_feature_importance_json": aggregate_importance,
                "benchmark_json": benchmark,
                "global_signal_json": signal,
                "privacy_json": privacy,
            },
        }
    row = conn.execute(
        text(
            """
            INSERT INTO saas_federated_learning_aggregates (
                round_id, task_type, model_key, model_version, industry_code, window_key,
                participant_count, total_samples, aggregate_metrics_json,
                aggregate_feature_importance_json, benchmark_json, global_signal_json,
                privacy_json, status, created_by_user_id, computed_at, updated_at
            )
            VALUES (
                CAST(:round_id AS uuid), :task_type, :model_key, :model_version, :industry_code, :window_key,
                :participant_count, :total_samples, CAST(:aggregate_metrics_json AS jsonb),
                CAST(:aggregate_feature_importance_json AS jsonb), CAST(:benchmark_json AS jsonb),
                CAST(:global_signal_json AS jsonb), CAST(:privacy_json AS jsonb),
                :status, CAST(NULLIF(:actor_user_id, '') AS uuid), NOW(), NOW()
            )
            ON CONFLICT (round_id)
            DO UPDATE SET
                participant_count = EXCLUDED.participant_count,
                total_samples = EXCLUDED.total_samples,
                aggregate_metrics_json = EXCLUDED.aggregate_metrics_json,
                aggregate_feature_importance_json = EXCLUDED.aggregate_feature_importance_json,
                benchmark_json = EXCLUDED.benchmark_json,
                global_signal_json = EXCLUDED.global_signal_json,
                privacy_json = EXCLUDED.privacy_json,
                status = EXCLUDED.status,
                created_by_user_id = EXCLUDED.created_by_user_id,
                computed_at = NOW(),
                updated_at = NOW()
            RETURNING id::text, round_id::text, task_type, model_key, model_version, industry_code,
                      window_key, participant_count, total_samples, aggregate_metrics_json,
                      aggregate_feature_importance_json, benchmark_json, global_signal_json,
                      privacy_json, status, COALESCE(created_by_user_id::text, '') AS created_by_user_id,
                      computed_at::text, created_at::text, updated_at::text
            """
        ),
        {
            "round_id": round_id,
            "task_type": round_row["task_type"],
            "model_key": round_row["model_key"],
            "model_version": round_row["model_version"],
            "industry_code": round_row["industry_code"],
            "window_key": round_row["window_key"],
            "participant_count": participants,
            "total_samples": total_samples,
            "aggregate_metrics_json": _json(aggregate_metrics),
            "aggregate_feature_importance_json": _json(aggregate_importance),
            "benchmark_json": _json(benchmark),
            "global_signal_json": _json(signal),
            "privacy_json": _json(privacy),
            "status": status,
            "actor_user_id": actor_user_id,
        },
    ).mappings().first()
    aggregate = dict(row or {})
    conn.execute(
        text(
            """
            UPDATE saas_federated_learning_rounds
            SET status = :status,
                closed_at = CASE WHEN :status = 'aggregated' THEN NOW() ELSE closed_at END,
                updated_at = NOW()
            WHERE id = CAST(:round_id AS uuid)
            """
        ),
        {"round_id": round_id, "status": status},
    )
    signal_key = f"federated:signal:{round_id}"
    conn.execute(
        text(
            """
            INSERT INTO saas_global_intelligence_signals (
                signal_key, signal_type, industry_code, task_type, title, summary,
                confidence, aggregate_id, source_json, privacy_json, status, updated_at
            )
            VALUES (
                :signal_key, 'federated_aggregate', :industry_code, :task_type, :title, :summary,
                :confidence, CAST(:aggregate_id AS uuid), CAST(:source_json AS jsonb),
                CAST(:privacy_json AS jsonb), :status, NOW()
            )
            ON CONFLICT (signal_key)
            DO UPDATE SET
                title = EXCLUDED.title,
                summary = EXCLUDED.summary,
                confidence = EXCLUDED.confidence,
                aggregate_id = EXCLUDED.aggregate_id,
                source_json = EXCLUDED.source_json,
                privacy_json = EXCLUDED.privacy_json,
                status = EXCLUDED.status,
                updated_at = NOW()
            """
        ),
        {
            "signal_key": signal_key,
            "industry_code": round_row["industry_code"],
            "task_type": round_row["task_type"],
            "title": signal["title"],
            "summary": signal["summary"],
            "confidence": signal["confidence"],
            "aggregate_id": aggregate["id"],
            "source_json": _json({"round_id": round_id, "participant_count": participants, "total_samples": total_samples}),
            "privacy_json": _json(privacy),
            "status": "active" if status == "aggregated" else "blocked",
        },
    )
    _record_usage_any(
        conn,
        tenant_id,
        ("privacy_safe_model_aggregation", "federated_learning", "ai_premium"),
        quantity=1,
        usage_metric="federated_round_aggregated",
        metadata={"round_id": round_id, "status": status, "participant_count": participants, "total_samples": total_samples},
    )
    record_event(
        conn,
        tenant_id,
        {
            "event_type": "federated.aggregate_generated",
            "source": "federated_learning",
            "entity_type": "federated_aggregate",
            "entity_id": aggregate["id"],
            "payload_json": {"round_id": round_id, "status": status, "participant_count": participants, "total_samples": total_samples, "raw_content_used": False},
            "replay_key": f"federated:aggregate:{round_id}:{status}:{participants}:{total_samples}",
        },
    )
    return {
        "dry_run": False,
        "round": _get_round(conn, round_id),
        "participant_count": participants,
        "total_samples": total_samples,
        "status": status,
        "aggregate": aggregate,
    }


def _list_rounds(conn: Connection, industry_code: str, *, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT r.id::text, r.round_key, r.task_type, r.model_key, r.model_version, r.industry_code,
                   r.cohort_key, r.window_key, r.status, r.min_participants, r.min_total_samples,
                   r.aggregation_strategy, r.privacy_budget_epsilon, r.metadata_json,
                   r.opened_at::text, r.closed_at::text, r.created_at::text, r.updated_at::text,
                   COALESCE(COUNT(u.id), 0)::int AS submitted_updates,
                   COALESCE(SUM(u.sample_count), 0)::int AS submitted_samples
            FROM saas_federated_learning_rounds r
            LEFT JOIN saas_federated_learning_updates u ON u.round_id = r.id AND u.status = 'submitted'
            WHERE r.industry_code IN (:industry_code, 'general')
            GROUP BY r.id
            ORDER BY r.updated_at DESC
            LIMIT :limit
            """
        ),
        {"industry_code": industry_code, "limit": max(1, min(int(limit or 50), 200))},
    ).mappings().all()
    return [dict(row) for row in rows]


def _list_updates(conn: Connection, tenant_id: str, *, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT u.id::text, u.round_id::text, u.tenant_id::text, u.update_key, u.task_type,
                   u.model_key, u.model_version, u.industry_code, u.window_key, u.sample_count,
                   u.metrics_json, u.feature_stats_json, u.feature_importance_json, u.privacy_json,
                   u.update_hash, u.quality_score, u.status, u.submitted_at::text,
                   r.round_key, r.status AS round_status
            FROM saas_federated_learning_updates u
            JOIN saas_federated_learning_rounds r ON r.id = u.round_id
            WHERE u.tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY u.updated_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "limit": max(1, min(int(limit or 50), 200))},
    ).mappings().all()
    return [dict(row) for row in rows]


def _list_aggregates(conn: Connection, industry_code: str, *, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT id::text, round_id::text, task_type, model_key, model_version, industry_code,
                   window_key, participant_count, total_samples, aggregate_metrics_json,
                   aggregate_feature_importance_json, benchmark_json, global_signal_json,
                   privacy_json, status, computed_at::text, created_at::text, updated_at::text
            FROM saas_federated_learning_aggregates
            WHERE industry_code IN (:industry_code, 'general')
            ORDER BY computed_at DESC
            LIMIT :limit
            """
        ),
        {"industry_code": industry_code, "limit": max(1, min(int(limit or 50), 200))},
    ).mappings().all()
    return [dict(row) for row in rows]


def _list_signals(conn: Connection, industry_code: str, *, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT id::text, signal_key, signal_type, industry_code, task_type, title, summary,
                   confidence, COALESCE(aggregate_id::text, '') AS aggregate_id,
                   source_json, privacy_json, status, created_at::text, updated_at::text
            FROM saas_global_intelligence_signals
            WHERE industry_code IN (:industry_code, 'general')
            ORDER BY updated_at DESC
            LIMIT :limit
            """
        ),
        {"industry_code": industry_code, "limit": max(1, min(int(limit or 50), 200))},
    ).mappings().all()
    return [dict(row) for row in rows]


def federated_learning_center(conn: Connection, tenant_id: str, *, limit: int = 50) -> dict[str, Any]:
    ensure_federated_learning_tables(conn)
    tenant = _tenant_profile(conn, tenant_id)
    access = _resolve_federated_access(conn, tenant_id, require_full=False)
    policy = federated_policy(conn, tenant_id)
    industry = str(tenant["industry_code"])
    max_limit = max(1, min(int(limit or 50), 200))
    task_previews = [
        build_local_update_package(conn, tenant_id, task_type=task, window_key="90d")
        for task in policy.get("allowed_task_types_json", list(VALID_TASKS))
        if task in TASK_DEFINITIONS
    ]
    rounds = _list_rounds(conn, industry, limit=max_limit)
    updates = _list_updates(conn, tenant_id, limit=max_limit)
    aggregates = _list_aggregates(conn, industry, limit=max_limit)
    signals = _list_signals(conn, industry, limit=max_limit)
    features = {
        item["key"]: item
        for item in intelligence_feature_state(conn, tenant_id).get("features", [])
        if item["key"] in FEDERATED_FEATURE_KEYS or item["key"] in {"ai_premium", "cross_tenant_intelligence"}
    }
    return {
        "tenant": tenant,
        "access": access,
        "policy": policy,
        "features": features,
        "tasks": [
            {
                "task_type": key,
                "label": value["label"],
                "model_key": value["model_key"],
                "metrics": list(value["metrics"]),
                "default_feature_importance": value["importance"],
            }
            for key, value in TASK_DEFINITIONS.items()
        ],
        "local_previews": task_previews,
        "rounds": rounds,
        "updates": updates,
        "aggregates": aggregates,
        "global_signals": signals,
        "privacy": {
            "architecture": "federated_control_plane",
            "raw_messages_shared": False,
            "raw_conversations_shared": False,
            "raw_media_shared": False,
            "tenant_names_shared_in_aggregates": False,
            "minimum_cohort_tenants": int(policy.get("min_cohort_tenants") or 3),
            "full_mode_required_to_submit": True,
            "model_promotion_automatic": False,
        },
        "rollout": {
            "default_enabled": False,
            "requires_opt_in": True,
            "supports_demo_preview": True,
            "supports_shadow_model_signals": True,
            "production_promotion": "manual_model_registry_review_required",
        },
    }


def process_federated_learning(conn: Connection, tenant_id: str, *, source: str = "worker", limit: int = 4) -> dict[str, Any]:
    ensure_federated_learning_tables(conn)
    access = _resolve_federated_access(conn, tenant_id, require_full=True)
    policy = federated_policy(conn, tenant_id)
    if not bool(policy.get("opt_in_enabled")) or not bool(policy.get("auto_participation_enabled")):
        return {"skipped": True, "reason": "policy_auto_participation_disabled", "access": access}
    tasks = [task for task in policy.get("allowed_task_types_json", list(VALID_TASKS)) if task in TASK_DEFINITIONS][: max(1, min(int(limit or 4), 10))]
    prepared: list[dict[str, Any]] = []
    aggregates: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for task in tasks:
        try:
            result = prepare_federated_round(
                conn,
                tenant_id,
                actor_user_id="",
                task_type=task,
                window_key="90d",
                dry_run=False,
                min_participants=int(policy.get("min_cohort_tenants") or 3),
                min_total_samples=max(int(policy.get("min_local_samples") or 25) * int(policy.get("min_cohort_tenants") or 3), 100),
                aggregation_strategy="weighted_average",
            )
            prepared.append(result)
            round_id = str((result.get("round") or {}).get("id") or "")
            if round_id:
                try:
                    aggregates.append(aggregate_federated_round(conn, tenant_id, "", round_id, dry_run=False))
                except HTTPException as exc:
                    aggregates.append({"round_id": round_id, "skipped": True, "reason": exc.detail})
        except HTTPException as exc:
            errors.append({"task_type": task, "error": str(exc.detail)[:500]})
        except Exception as exc:
            errors.append({"task_type": task, "error": str(exc)[:500]})
    return {
        "skipped": False,
        "source": source,
        "prepared_updates": len(prepared),
        "aggregates": aggregates,
        "errors": errors[:5],
    }
