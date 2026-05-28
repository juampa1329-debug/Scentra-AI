from __future__ import annotations

import os
import time
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app_saas.config import settings
from app_saas.db import db_session
from app_saas.agents.operating_system import sync_event_driven_agent_jobs
from app_saas.intelligence.catalog import PREDICTION_FEATURE_MAP
from app_saas.intelligence.federated import process_federated_learning
from app_saas.intelligence.network import refresh_enterprise_ai_network
from app_saas.intelligence.memory_network import sync_enterprise_memory_network
from app_saas.intelligence.operations import run_operational_intelligence_analysis
from app_saas.intelligence.revenue import analyze_revenue_engine
from app_saas.intelligence.service import (
    ensure_intelligence_tables,
    generate_prediction,
    intelligence_feature_state,
    recompute_model_metrics,
    recompute_feature_snapshot,
    run_training_data_preparation,
)

_last_run_monotonic = 0.0


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _count_inserted(conn: Connection, sql: str, params: dict[str, Any]) -> int:
    value = conn.execute(text(sql), params).scalar()
    return int(value or 0)


def _derive_message_events(conn: Connection, tenant_id: str, *, limit: int, lookback_hours: int) -> int:
    return _count_inserted(
        conn,
        """
        WITH source_rows AS (
            SELECT
                m.id, m.tenant_id, m.conversation_id, m.channel, m.external_message_id,
                m.direction, m.msg_type, m.text AS body_text, m.media_id, m.mime_type,
                m.payload_json, m.created_at, c.external_contact_id
            FROM saas_messages m
            LEFT JOIN saas_conversations c
              ON c.id = m.conversation_id AND c.tenant_id = m.tenant_id
            WHERE m.tenant_id = CAST(:tenant_id AS uuid)
              AND m.created_at >= NOW() - (:lookback_hours * INTERVAL '1 hour')
            ORDER BY m.created_at DESC
            LIMIT :limit
        ),
        inserted AS (
            INSERT INTO saas_intelligence_events (
                tenant_id, event_type, source, channel, entity_type, entity_id,
                conversation_id, customer_key, occurred_at, payload_json, correlation_id, replay_key
            )
            SELECT
                tenant_id,
                CASE WHEN LOWER(direction) = 'inbound' THEN 'message.received' ELSE 'message.sent' END,
                'saas_messages',
                channel,
                'message',
                id::text,
                conversation_id,
                COALESCE(external_contact_id, ''),
                created_at,
                jsonb_build_object(
                    'direction', direction,
                    'msg_type', msg_type,
                    'external_message_id', external_message_id,
                    'has_media', COALESCE(media_id, '') <> '',
                    'mime_type', mime_type,
                    'text_preview', LEFT(COALESCE(body_text, ''), 280)
                ),
                '',
                'message:' || id::text
            FROM source_rows
            ON CONFLICT (tenant_id, replay_key) WHERE replay_key <> ''
            DO NOTHING
            RETURNING 1
        )
        SELECT COUNT(*)::int FROM inserted
        """,
        {"tenant_id": tenant_id, "limit": limit, "lookback_hours": lookback_hours},
    )


def _derive_conversation_events(conn: Connection, tenant_id: str, *, limit: int, lookback_hours: int) -> int:
    return _count_inserted(
        conn,
        """
        WITH source_rows AS (
            SELECT
                id, tenant_id, channel, external_contact_id, phone, display_name,
                crm_stage, payment_status, lead_score, lead_temperature, created_at
            FROM saas_conversations
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND created_at >= NOW() - (:lookback_hours * INTERVAL '1 hour')
            ORDER BY created_at DESC
            LIMIT :limit
        ),
        inserted AS (
            INSERT INTO saas_intelligence_events (
                tenant_id, event_type, source, channel, entity_type, entity_id,
                conversation_id, customer_key, occurred_at, payload_json, correlation_id, replay_key
            )
            SELECT
                tenant_id,
                'lead.created',
                'saas_conversations',
                channel,
                'conversation',
                id::text,
                id,
                external_contact_id,
                created_at,
                jsonb_build_object(
                    'display_name', display_name,
                    'phone_present', COALESCE(phone, '') <> '',
                    'crm_stage', crm_stage,
                    'payment_status', payment_status,
                    'lead_score', lead_score,
                    'lead_temperature', lead_temperature
                ),
                '',
                'conversation:' || id::text || ':' || 'created'
            FROM source_rows
            ON CONFLICT (tenant_id, replay_key) WHERE replay_key <> ''
            DO NOTHING
            RETURNING 1
        )
        SELECT COUNT(*)::int FROM inserted
        """,
        {"tenant_id": tenant_id, "limit": limit, "lookback_hours": lookback_hours},
    )


def _derive_webhook_events(conn: Connection, tenant_id: str, *, limit: int, lookback_hours: int) -> int:
    return _count_inserted(
        conn,
        """
        WITH source_rows AS (
            SELECT id, tenant_id, provider, event_id, status, received_at, processed_at, error, raw_sha256
            FROM saas_webhook_events
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND received_at >= NOW() - (:lookback_hours * INTERVAL '1 hour')
            ORDER BY received_at DESC
            LIMIT :limit
        ),
        inserted AS (
            INSERT INTO saas_intelligence_events (
                tenant_id, event_type, source, channel, entity_type, entity_id,
                conversation_id, customer_key, occurred_at, payload_json, correlation_id, replay_key
            )
            SELECT
                tenant_id,
                CASE WHEN status IN ('error', 'failed') THEN 'webhook.failed' ELSE 'webhook.received' END,
                'saas_webhook_events',
                provider,
                'webhook_event',
                id::text,
                NULL,
                '',
                received_at,
                jsonb_build_object(
                    'provider', provider,
                    'event_id', event_id,
                    'status', status,
                    'processed_at', processed_at,
                    'error', LEFT(COALESCE(error, ''), 500)
                ),
                COALESCE(raw_sha256, ''),
                'webhook:' || id::text || ':' || status
            FROM source_rows
            ON CONFLICT (tenant_id, replay_key) WHERE replay_key <> ''
            DO NOTHING
            RETURNING 1
        )
        SELECT COUNT(*)::int FROM inserted
        """,
        {"tenant_id": tenant_id, "limit": limit, "lookback_hours": lookback_hours},
    )


def _derive_outbound_events(conn: Connection, tenant_id: str, *, limit: int, lookback_hours: int) -> int:
    return _count_inserted(
        conn,
        """
        WITH source_rows AS (
            SELECT
                id, tenant_id, conversation_id, message_id, channel, provider,
                recipient_external_id, status, attempts, sent_at, error, updated_at, created_at
            FROM saas_outbound_messages
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND updated_at >= NOW() - (:lookback_hours * INTERVAL '1 hour')
              AND status IN ('sent', 'failed', 'blocked')
            ORDER BY updated_at DESC
            LIMIT :limit
        ),
        inserted AS (
            INSERT INTO saas_intelligence_events (
                tenant_id, event_type, source, channel, entity_type, entity_id,
                conversation_id, customer_key, occurred_at, payload_json, correlation_id, replay_key
            )
            SELECT
                tenant_id,
                CASE WHEN status = 'sent' THEN 'message.sent' ELSE 'message.failed' END,
                'saas_outbound_messages',
                channel,
                'outbound_message',
                id::text,
                conversation_id,
                recipient_external_id,
                COALESCE(sent_at, updated_at, created_at),
                jsonb_build_object(
                    'provider', provider,
                    'status', status,
                    'attempts', attempts,
                    'message_id', COALESCE(message_id::text, ''),
                    'error', LEFT(COALESCE(error, ''), 500)
                ),
                '',
                'outbound:' || id::text || ':' || status
            FROM source_rows
            ON CONFLICT (tenant_id, replay_key) WHERE replay_key <> ''
            DO NOTHING
            RETURNING 1
        )
        SELECT COUNT(*)::int FROM inserted
        """,
        {"tenant_id": tenant_id, "limit": limit, "lookback_hours": lookback_hours},
    )


def _derive_trigger_events(conn: Connection, tenant_id: str, *, limit: int, lookback_hours: int) -> int:
    return _count_inserted(
        conn,
        """
        WITH source_rows AS (
            SELECT
                id, tenant_id, trigger_id, conversation_id, message_id, channel,
                event_kind, recipient_external_id, status, error, details_json, executed_at
            FROM saas_trigger_executions
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND executed_at >= NOW() - (:lookback_hours * INTERVAL '1 hour')
            ORDER BY executed_at DESC
            LIMIT :limit
        ),
        inserted AS (
            INSERT INTO saas_intelligence_events (
                tenant_id, event_type, source, channel, entity_type, entity_id,
                conversation_id, customer_key, occurred_at, payload_json, correlation_id, replay_key
            )
            SELECT
                tenant_id,
                CASE WHEN status = 'ok' THEN 'trigger.executed' ELSE 'trigger.failed' END,
                'saas_trigger_executions',
                channel,
                'trigger_execution',
                id::text,
                conversation_id,
                recipient_external_id,
                executed_at,
                jsonb_build_object(
                    'trigger_id', trigger_id,
                    'message_id', COALESCE(message_id::text, ''),
                    'event_kind', event_kind,
                    'status', status,
                    'error', LEFT(COALESCE(error, ''), 500),
                    'details', details_json
                ),
                '',
                'trigger_execution:' || id::text || ':' || status
            FROM source_rows
            ON CONFLICT (tenant_id, replay_key) WHERE replay_key <> ''
            DO NOTHING
            RETURNING 1
        )
        SELECT COUNT(*)::int FROM inserted
        """,
        {"tenant_id": tenant_id, "limit": limit, "lookback_hours": lookback_hours},
    )


def _derive_campaign_events(conn: Connection, tenant_id: str, *, limit: int, lookback_hours: int) -> int:
    return _count_inserted(
        conn,
        """
        WITH source_rows AS (
            SELECT
                id, tenant_id, entity_type, entity_id, conversation_id, message_id,
                outbound_id, channel, recipient_external_id, variant_key, template_id,
                source, outcome, metadata_json, created_at
            FROM saas_campaign_ab_events
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND created_at >= NOW() - (:lookback_hours * INTERVAL '1 hour')
            ORDER BY created_at DESC
            LIMIT :limit
        ),
        inserted AS (
            INSERT INTO saas_intelligence_events (
                tenant_id, event_type, source, channel, entity_type, entity_id,
                conversation_id, customer_key, occurred_at, payload_json, correlation_id, replay_key
            )
            SELECT
                tenant_id,
                CASE WHEN outcome = 'failed' THEN 'campaign.failed' ELSE 'campaign.sent' END,
                'saas_campaign_ab_events',
                channel,
                entity_type,
                COALESCE(entity_id::text, id::text),
                conversation_id,
                recipient_external_id,
                created_at,
                jsonb_build_object(
                    'ab_event_id', id,
                    'outcome', outcome,
                    'variant_key', variant_key,
                    'template_id', COALESCE(template_id::text, ''),
                    'message_id', COALESCE(message_id::text, ''),
                    'outbound_id', COALESCE(outbound_id::text, ''),
                    'source', source,
                    'metadata', metadata_json
                ),
                '',
                'campaign_ab:' || id::text || ':' || outcome
            FROM source_rows
            ON CONFLICT (tenant_id, replay_key) WHERE replay_key <> ''
            DO NOTHING
            RETURNING 1
        )
        SELECT COUNT(*)::int FROM inserted
        """,
        {"tenant_id": tenant_id, "limit": limit, "lookback_hours": lookback_hours},
    )


def _derive_remarketing_events(conn: Connection, tenant_id: str, *, limit: int, lookback_hours: int) -> int:
    return _count_inserted(
        conn,
        """
        WITH source_rows AS (
            SELECT
                id, tenant_id, flow_id, conversation_id, channel, recipient_external_id,
                current_step_order, state, next_run_at, last_sent_at, last_error, updated_at, enrolled_at
            FROM saas_remarketing_enrollments
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND GREATEST(updated_at, enrolled_at) >= NOW() - (:lookback_hours * INTERVAL '1 hour')
            ORDER BY GREATEST(updated_at, enrolled_at) DESC
            LIMIT :limit
        ),
        inserted AS (
            INSERT INTO saas_intelligence_events (
                tenant_id, event_type, source, channel, entity_type, entity_id,
                conversation_id, customer_key, occurred_at, payload_json, correlation_id, replay_key
            )
            SELECT
                tenant_id,
                CASE WHEN last_sent_at IS NOT NULL THEN 'remarketing.step.sent' ELSE 'remarketing.enrolled' END,
                'saas_remarketing_enrollments',
                channel,
                'remarketing_enrollment',
                id::text,
                conversation_id,
                recipient_external_id,
                COALESCE(last_sent_at, enrolled_at, updated_at),
                jsonb_build_object(
                    'flow_id', flow_id,
                    'current_step_order', current_step_order,
                    'state', state,
                    'next_run_at', next_run_at,
                    'last_error', LEFT(COALESCE(last_error, ''), 500)
                ),
                '',
                CASE
                    WHEN last_sent_at IS NOT NULL THEN 'remarketing:' || id::text || ':' || 'sent:' || current_step_order::text
                    ELSE 'remarketing:' || id::text || ':' || 'enrolled'
                END
            FROM source_rows
            ON CONFLICT (tenant_id, replay_key) WHERE replay_key <> ''
            DO NOTHING
            RETURNING 1
        )
        SELECT COUNT(*)::int FROM inserted
        """,
        {"tenant_id": tenant_id, "limit": limit, "lookback_hours": lookback_hours},
    )


def _derive_ai_events(conn: Connection, tenant_id: str, *, limit: int, lookback_hours: int) -> int:
    return _count_inserted(
        conn,
        """
        WITH source_rows AS (
            SELECT
                id, tenant_id, conversation_id, agent_type, task_type, route_code,
                provider_code, model, status, total_tokens, latency_ms,
                fallback_used, error_code, error_message, created_at
            FROM saas_ai_runs
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND created_at >= NOW() - (:lookback_hours * INTERVAL '1 hour')
            ORDER BY created_at DESC
            LIMIT :limit
        ),
        inserted AS (
            INSERT INTO saas_intelligence_events (
                tenant_id, event_type, source, channel, entity_type, entity_id,
                conversation_id, customer_key, occurred_at, payload_json, correlation_id, replay_key
            )
            SELECT
                tenant_id,
                CASE WHEN status = 'failed' THEN 'ai.run.failed' ELSE 'ai.run.completed' END,
                'saas_ai_runs',
                '',
                'ai_run',
                id::text,
                conversation_id,
                '',
                created_at,
                jsonb_build_object(
                    'agent_type', agent_type,
                    'task_type', task_type,
                    'route_code', route_code,
                    'provider_code', provider_code,
                    'model', model,
                    'status', status,
                    'total_tokens', total_tokens,
                    'latency_ms', latency_ms,
                    'fallback_used', fallback_used,
                    'error_code', error_code,
                    'error_message', LEFT(COALESCE(error_message, ''), 500)
                ),
                '',
                'ai_run:' || id::text || ':' || status
            FROM source_rows
            ON CONFLICT (tenant_id, replay_key) WHERE replay_key <> ''
            DO NOTHING
            RETURNING 1
        )
        SELECT COUNT(*)::int FROM inserted
        """,
        {"tenant_id": tenant_id, "limit": limit, "lookback_hours": lookback_hours},
    )


def _derive_billing_events(conn: Connection, tenant_id: str, *, limit: int, lookback_hours: int) -> int:
    return _count_inserted(
        conn,
        """
        WITH source_rows AS (
            SELECT id, tenant_id, provider, status, plan_code, current_period_end, cancel_at_period_end, updated_at
            FROM saas_billing_subscriptions
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND updated_at >= NOW() - (:lookback_hours * INTERVAL '1 hour')
            ORDER BY updated_at DESC
            LIMIT :limit
        ),
        inserted AS (
            INSERT INTO saas_intelligence_events (
                tenant_id, event_type, source, channel, entity_type, entity_id,
                conversation_id, customer_key, occurred_at, payload_json, correlation_id, replay_key
            )
            SELECT
                tenant_id,
                'billing.subscription.changed',
                'saas_billing_subscriptions',
                provider,
                'billing_subscription',
                id::text,
                NULL,
                '',
                updated_at,
                jsonb_build_object(
                    'status', status,
                    'plan_code', plan_code,
                    'current_period_end', current_period_end,
                    'cancel_at_period_end', cancel_at_period_end
                ),
                '',
                'billing_subscription:' || id::text || ':' || status || ':' || plan_code
            FROM source_rows
            ON CONFLICT (tenant_id, replay_key) WHERE replay_key <> ''
            DO NOTHING
            RETURNING 1
        )
        SELECT COUNT(*)::int FROM inserted
        """,
        {"tenant_id": tenant_id, "limit": limit, "lookback_hours": lookback_hours},
    )


def derive_intelligence_events(conn: Connection, tenant_id: str, *, limit: int = 250, lookback_hours: int = 48) -> dict[str, int]:
    ensure_intelligence_tables(conn)
    per_source_limit = max(1, min(int(limit or 250), 1000))
    lookback = max(1, min(int(lookback_hours or 48), 24 * 30))
    result = {
        "conversations": _derive_conversation_events(conn, tenant_id, limit=per_source_limit, lookback_hours=lookback),
        "messages": _derive_message_events(conn, tenant_id, limit=per_source_limit, lookback_hours=lookback),
        "webhooks": _derive_webhook_events(conn, tenant_id, limit=per_source_limit, lookback_hours=lookback),
        "outbound": _derive_outbound_events(conn, tenant_id, limit=per_source_limit, lookback_hours=lookback),
        "triggers": _derive_trigger_events(conn, tenant_id, limit=per_source_limit, lookback_hours=lookback),
        "campaigns": _derive_campaign_events(conn, tenant_id, limit=per_source_limit, lookback_hours=lookback),
        "remarketing": _derive_remarketing_events(conn, tenant_id, limit=per_source_limit, lookback_hours=lookback),
        "ai_runs": _derive_ai_events(conn, tenant_id, limit=per_source_limit, lookback_hours=lookback),
        "billing": _derive_billing_events(conn, tenant_id, limit=per_source_limit, lookback_hours=lookback),
    }
    result["total"] = sum(result.values())
    return result


def _tenant_rows(conn: Connection, *, tenant_id: str | None, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT id::text, name, status, plan_code
            FROM saas_tenants
            WHERE status IN ('active', 'trial')
              AND (CAST(NULLIF(:tenant_id, '') AS uuid) IS NULL OR id = CAST(NULLIF(:tenant_id, '') AS uuid))
            ORDER BY updated_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": str(tenant_id or "").strip(), "limit": max(1, min(int(limit or 25), 250))},
    ).mappings().all()
    return [dict(row) for row in rows]


def _recent_prediction_exists(conn: Connection, tenant_id: str, prediction_type: str, *, cooldown_minutes: int) -> bool:
    return bool(
        conn.execute(
            text(
                """
                SELECT 1
                FROM saas_intelligence_predictions
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND prediction_type = :prediction_type
                  AND created_at >= NOW() - (:cooldown_minutes * INTERVAL '1 minute')
                LIMIT 1
                """
            ),
            {"tenant_id": tenant_id, "prediction_type": prediction_type, "cooldown_minutes": max(1, int(cooldown_minutes or 60))},
        ).first()
    )


def _run_tenant_pipeline(conn: Connection, tenant_id: str, *, event_limit: int, lookback_hours: int, prediction_cooldown_minutes: int) -> dict[str, Any]:
    events = derive_intelligence_events(conn, tenant_id, limit=event_limit, lookback_hours=lookback_hours)
    snapshot = recompute_feature_snapshot(conn, tenant_id, subject_type="tenant", subject_id=tenant_id, window_key="latest")
    training_data: dict[str, Any] = {}
    if settings.saas_ml_auto_train_enabled:
        try:
            training_data = run_training_data_preparation(
                conn,
                tenant_id=tenant_id,
                window_key=os.getenv("SAAS_ML_TRAINING_WINDOW_KEY", "90d"),
                limit=_env_int("SAAS_ML_TRAINING_PIPELINE_LIMIT", 500, minimum=25, maximum=10000),
            )
        except Exception as exc:
            training_data = {"error": str(exc)[:500]}
    state = intelligence_feature_state(conn, tenant_id)
    features_by_key = {item["key"]: item for item in state.get("features", [])}
    predictions: list[dict[str, Any]] = []
    skipped = {"disabled": 0, "recent": 0, "quota_or_access": 0}
    errors: list[dict[str, str]] = []

    for prediction_type, feature_key in PREDICTION_FEATURE_MAP.items():
        feature_state = features_by_key.get(feature_key) or {}
        if not feature_state.get("enabled"):
            skipped["disabled"] += 1
            continue
        if _recent_prediction_exists(conn, tenant_id, prediction_type, cooldown_minutes=prediction_cooldown_minutes):
            skipped["recent"] += 1
            continue
        try:
            with conn.begin_nested():
                predictions.append(
                    generate_prediction(
                        conn,
                        tenant_id,
                        prediction_type=prediction_type,
                        subject_type="tenant",
                        subject_id=tenant_id,
                        window_key="latest",
                        persist_recommendations=True,
                    )
                )
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {"code": str(exc.detail or "")}
            code = str(detail.get("code") or "")
            if code in {"intelligence_model_disabled", "intelligence_feature_not_enabled", "intelligence_quota_exceeded"}:
                skipped["quota_or_access"] += 1
            else:
                skipped["quota_or_access"] += 1
                errors.append({"prediction_type": prediction_type, "error": str(exc.detail)[:500]})
        except Exception as exc:
            errors.append({"prediction_type": prediction_type, "error": str(exc)[:500]})

    metrics: list[dict[str, Any]] = []
    try:
        metrics = recompute_model_metrics(conn, tenant_id=tenant_id)
    except Exception as exc:
        errors.append({"metric_recompute": str(exc)[:500]})

    agent_os: dict[str, Any] = {}
    try:
        with conn.begin_nested():
            agent_os = sync_event_driven_agent_jobs(
                conn,
                tenant_id,
                limit=_env_int("SAAS_AGENT_OS_EVENT_SYNC_LIMIT", 50, minimum=1, maximum=250),
                lookback_days=_env_int("SAAS_AGENT_OS_EVENT_SYNC_LOOKBACK_DAYS", 7, minimum=1, maximum=90),
                dry_run=False,
                source="worker",
            )
    except Exception as exc:
        errors.append({"agent_os_event_sync": str(exc)[:500]})

    autonomous_ops: dict[str, Any] = {}
    try:
        with conn.begin_nested():
            autonomous_ops = run_operational_intelligence_analysis(
                conn,
                tenant_id,
                actor_user_id="",
                dry_run=False,
                limit=_env_int("SAAS_AUTONOMOUS_OPS_ANALYSIS_LIMIT", 50, minimum=1, maximum=200),
            )
    except Exception as exc:
        errors.append({"autonomous_operations": str(exc)[:500]})

    enterprise_ai_network: dict[str, Any] = {}
    try:
        with conn.begin_nested():
            enterprise_ai_network = refresh_enterprise_ai_network(
                conn,
                tenant_id,
                actor_user_id="",
                dry_run=False,
                limit=_env_int("SAAS_ENTERPRISE_AI_NETWORK_LIMIT", 50, minimum=1, maximum=200),
            )
    except HTTPException as exc:
        enterprise_ai_network = {"skipped": True, "reason": str(exc.detail)[:500]}
    except Exception as exc:
        errors.append({"enterprise_ai_network": str(exc)[:500]})

    revenue_engine: dict[str, Any] = {}
    try:
        with conn.begin_nested():
            revenue_engine = analyze_revenue_engine(
                conn,
                tenant_id,
                actor_user_id="",
                dry_run=False,
                limit=_env_int("SAAS_REVENUE_ENGINE_LIMIT", 50, minimum=1, maximum=200),
                source="worker",
            )
    except HTTPException as exc:
        revenue_engine = {"skipped": True, "reason": str(exc.detail)[:500]}
    except Exception as exc:
        errors.append({"revenue_engine": str(exc)[:500]})

    memory_network: dict[str, Any] = {}
    try:
        with conn.begin_nested():
            memory_network = sync_enterprise_memory_network(
                conn,
                tenant_id,
                actor_user_id="",
                dry_run=False,
                limit=_env_int("SAAS_MEMORY_NETWORK_SYNC_LIMIT", 80, minimum=1, maximum=300),
                source="worker",
            )
    except HTTPException as exc:
        memory_network = {"skipped": True, "reason": str(exc.detail)[:500]}
    except Exception as exc:
        errors.append({"memory_network": str(exc)[:500]})

    federated_learning: dict[str, Any] = {}
    try:
        with conn.begin_nested():
            federated_learning = process_federated_learning(
                conn,
                tenant_id,
                source="worker",
                limit=_env_int("SAAS_FEDERATED_LEARNING_TASK_LIMIT", 4, minimum=1, maximum=10),
            )
    except HTTPException as exc:
        federated_learning = {"skipped": True, "reason": str(exc.detail)[:500]}
    except Exception as exc:
        errors.append({"federated_learning": str(exc)[:500]})

    return {
        "tenant_id": tenant_id,
        "events": events,
        "features": len(snapshot.get("features", {}) or {}),
        "training_data": training_data,
        "predictions": len(predictions),
        "metrics": len(metrics),
        "agent_os": agent_os,
        "autonomous_ops": autonomous_ops,
        "enterprise_ai_network": enterprise_ai_network,
        "revenue_engine": revenue_engine,
        "memory_network": memory_network,
        "federated_learning": federated_learning,
        "skipped": skipped,
        "errors": errors[:5],
    }


def process_due_intelligence(*, limit: int = 25, tenant_id: str | None = None, force: bool = False) -> dict[str, Any]:
    global _last_run_monotonic
    interval_minutes = _env_int("SAAS_INTELLIGENCE_WORKER_INTERVAL_MINUTES", 15, minimum=1, maximum=24 * 60)
    now = time.monotonic()
    if not force and not tenant_id and _last_run_monotonic and now - _last_run_monotonic < interval_minutes * 60:
        return {"skipped": True, "reason": "interval", "interval_minutes": interval_minutes}

    event_limit = _env_int("SAAS_INTELLIGENCE_EVENT_LIMIT", 250, minimum=25, maximum=2000)
    lookback_hours = _env_int("SAAS_INTELLIGENCE_LOOKBACK_HOURS", 48, minimum=1, maximum=24 * 30)
    prediction_cooldown = _env_int("SAAS_INTELLIGENCE_PREDICTION_COOLDOWN_MINUTES", 60, minimum=5, maximum=24 * 60)

    with db_session() as conn:
        locked = bool(conn.execute(text("SELECT pg_try_advisory_xact_lock(hashtext('scentra:intelligence:pipeline'))")).scalar())
        if not locked:
            return {"skipped": True, "reason": "locked"}
        ensure_intelligence_tables(conn)
        tenants = _tenant_rows(conn, tenant_id=tenant_id, limit=limit)
        tenant_results: list[dict[str, Any]] = []
        for tenant in tenants:
            tid = str(tenant.get("id") or "")
            if not tid:
                continue
            try:
                with conn.begin_nested():
                    tenant_results.append(
                        _run_tenant_pipeline(
                            conn,
                            tid,
                            event_limit=event_limit,
                            lookback_hours=lookback_hours,
                            prediction_cooldown_minutes=prediction_cooldown,
                        )
                    )
            except Exception as exc:
                tenant_results.append({"tenant_id": tid, "events": {"total": 0}, "features": 0, "predictions": 0, "skipped": {}, "errors": [{"error": str(exc)[:500]}]})
        _last_run_monotonic = time.monotonic()

    totals = {
        "events": sum(int((item.get("events") or {}).get("total") or 0) for item in tenant_results),
        "features_snapshots": sum(1 for item in tenant_results if int(item.get("features") or 0) > 0),
        "predictions": sum(int(item.get("predictions") or 0) for item in tenant_results),
        "metrics": sum(int(item.get("metrics") or 0) for item in tenant_results),
        "agent_os_jobs": sum(int(((item.get("agent_os") or {}).get("created")) or 0) for item in tenant_results),
        "autonomous_anomalies": sum(len(((item.get("autonomous_ops") or {}).get("created_anomalies") or [])) for item in tenant_results),
        "autonomous_actions": sum(len(((item.get("autonomous_ops") or {}).get("created_actions") or [])) for item in tenant_results),
        "enterprise_ai_insights": sum(
            len(((item.get("enterprise_ai_network") or {}).get("insights") or []))
            for item in tenant_results
            if not (item.get("enterprise_ai_network") or {}).get("skipped")
        ),
        "revenue_opportunities": sum(
            len(((item.get("revenue_engine") or {}).get("created_opportunities") or []))
            for item in tenant_results
            if not (item.get("revenue_engine") or {}).get("skipped")
        ),
        "memory_nodes": sum(
            len(((item.get("memory_network") or {}).get("created_nodes") or []))
            for item in tenant_results
            if not (item.get("memory_network") or {}).get("skipped")
        ),
        "federated_updates": sum(
            int(((item.get("federated_learning") or {}).get("prepared_updates")) or 0)
            for item in tenant_results
            if not (item.get("federated_learning") or {}).get("skipped")
        ),
        "federated_aggregates": sum(
            len(((item.get("federated_learning") or {}).get("aggregates") or []))
            for item in tenant_results
            if not (item.get("federated_learning") or {}).get("skipped")
        ),
        "training_runs": sum(len(((item.get("training_data") or {}).get("feature_pipelines") or {}).get("runs") or []) for item in tenant_results),
        "errors": sum(len(item.get("errors") or []) for item in tenant_results),
    }
    return {
        "skipped": False,
        "tenants": len(tenant_results),
        "totals": totals,
        "tenant_results": tenant_results[:10],
        "event_limit": event_limit,
        "lookback_hours": lookback_hours,
        "prediction_cooldown_minutes": prediction_cooldown,
    }
