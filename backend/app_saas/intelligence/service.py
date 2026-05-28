from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import time
from typing import Any
import urllib.error
import urllib.request

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app_saas.billing.limits import tenant_entitlements
from app_saas.config import settings
from app_saas.intelligence.catalog import INTELLIGENCE_FEATURE_MAP, INTELLIGENCE_FEATURES, PREDICTION_FEATURE_MAP
from app_saas.intelligence.premium import (
    PHASE24_FEATURE_KEYS,
    ensure_premium_gating_tables,
    list_provider_policies,
    plan_feature_limits,
    plan_feature_limits_for_plan,
    provider_cost_summary,
    provider_credential_summary,
)

VALID_MODES = {"disabled", "demo", "full"}
VALID_MODEL_STATUSES = {"active", "paused", "deprecated", "candidate"}
VALID_MODEL_STAGES = {"development", "staging", "shadow", "production", "archived"}
VALID_ROLLOUT_MODES = {"disabled", "shadow", "canary", "production"}
VALID_PROMOTION_STATUSES = {"draft", "pending_review", "approved", "rejected", "blocked"}
VALID_PREDICTION_TASKS = set(PREDICTION_FEATURE_MAP.keys())

EVENT_CONTRACTS: list[dict[str, Any]] = [
    {
        "event_type": "message.received",
        "category": "conversation",
        "source": "saas_messages",
        "description": "Inbound tenant customer message.",
        "required_fields": ["tenant_id", "conversation_id", "channel", "direction"],
        "schema": {"direction": "inbound", "no_raw_content": True},
    },
    {
        "event_type": "message.sent",
        "category": "conversation",
        "source": "saas_messages|saas_outbound_messages",
        "description": "Outbound tenant message or provider send confirmation.",
        "required_fields": ["tenant_id", "conversation_id", "channel", "direction"],
        "schema": {"direction": "outbound", "no_raw_content": True},
    },
    {
        "event_type": "message.failed",
        "category": "operations",
        "source": "saas_outbound_messages",
        "description": "Outbound message failed or was blocked before provider delivery.",
        "required_fields": ["tenant_id", "entity_id", "status"],
        "schema": {"status": "failed|blocked"},
    },
    {
        "event_type": "lead.created",
        "category": "crm",
        "source": "saas_conversations",
        "description": "Conversation/customer lead created.",
        "required_fields": ["tenant_id", "conversation_id", "channel"],
        "schema": {"entity_type": "conversation"},
    },
    {
        "event_type": "lead.converted",
        "category": "crm",
        "source": "auto_labeler_v1",
        "description": "Conversation reached a conversion state derived from CRM/payment fields.",
        "required_fields": ["tenant_id", "conversation_id", "crm_stage"],
        "schema": {"label_source": "crm_payment_stage"},
    },
    {
        "event_type": "customer.inactive",
        "category": "crm",
        "source": "auto_labeler_v1",
        "description": "Customer inactivity window was reached.",
        "required_fields": ["tenant_id", "conversation_id", "inactive_days"],
        "schema": {"label_source": "last_message_at"},
    },
    {
        "event_type": "trigger.executed",
        "category": "automation",
        "source": "saas_trigger_executions",
        "description": "Campaign trigger executed successfully.",
        "required_fields": ["tenant_id", "trigger_id", "status"],
        "schema": {"status": "ok"},
    },
    {
        "event_type": "trigger.failed",
        "category": "automation",
        "source": "saas_trigger_executions",
        "description": "Campaign trigger execution failed.",
        "required_fields": ["tenant_id", "trigger_id", "status"],
        "schema": {"status": "failed|error"},
    },
    {
        "event_type": "workflow.executed",
        "category": "automation",
        "source": "saas_remarketing_enrollments",
        "description": "Workflow or remarketing step execution was derived.",
        "required_fields": ["tenant_id", "flow_id", "state"],
        "schema": {"entity_type": "remarketing_enrollment"},
    },
    {
        "event_type": "campaign.sent",
        "category": "campaign",
        "source": "saas_campaign_ab_events|saas_broadcast_recipients",
        "description": "Campaign/broadcast message was queued or sent.",
        "required_fields": ["tenant_id", "entity_id", "outcome"],
        "schema": {"outcome": "queued|sent|delivered|read|replied"},
    },
    {
        "event_type": "campaign.clicked",
        "category": "campaign",
        "source": "saas_campaign_ab_events",
        "description": "Campaign click/engagement was recorded when provider telemetry is available.",
        "required_fields": ["tenant_id", "entity_id", "outcome"],
        "schema": {"outcome": "clicked"},
    },
    {
        "event_type": "campaign.converted",
        "category": "campaign",
        "source": "auto_labeler_v1",
        "description": "Campaign resulted in reply/purchase/conversion evidence.",
        "required_fields": ["tenant_id", "subject_id", "label_key"],
        "schema": {"label_source": "campaign_broadcast_outcome"},
    },
    {
        "event_type": "campaign.failed",
        "category": "campaign",
        "source": "saas_campaign_ab_events|saas_broadcast_recipients",
        "description": "Campaign/broadcast delivery failed.",
        "required_fields": ["tenant_id", "entity_id", "outcome"],
        "schema": {"outcome": "failed"},
    },
    {
        "event_type": "conversation.closed",
        "category": "conversation",
        "source": "saas_conversations",
        "description": "Conversation closure signal when CRM state supports it.",
        "required_fields": ["tenant_id", "conversation_id"],
        "schema": {"state": "closed_or_terminal"},
    },
    {
        "event_type": "ticket.closed",
        "category": "crm",
        "source": "saas_crm_tasks",
        "description": "CRM task/ticket was completed.",
        "required_fields": ["tenant_id", "task_id", "status"],
        "schema": {"status": "completed|done|closed"},
    },
    {
        "event_type": "webhook.failed",
        "category": "operations",
        "source": "saas_webhook_events",
        "description": "Webhook event failed processing.",
        "required_fields": ["tenant_id", "provider", "status"],
        "schema": {"status": "error|failed"},
    },
    {
        "event_type": "ai.run.failed",
        "category": "ai",
        "source": "saas_ai_runs",
        "description": "AI Gateway/provider run failed.",
        "required_fields": ["tenant_id", "provider_code", "status"],
        "schema": {"status": "failed"},
    },
    {
        "event_type": "ai.prediction.generated",
        "category": "ai",
        "source": "intelligence_engine",
        "description": "Prediction generated by Intelligence Engine or optional ML service.",
        "required_fields": ["tenant_id", "prediction_type", "model_key"],
        "schema": {"premium_gated": True},
    },
    {
        "event_type": "ai.recommendation.generated",
        "category": "ai",
        "source": "intelligence_engine",
        "description": "Predictive recommendation persisted after recommendation gate approval.",
        "required_fields": ["tenant_id", "recommendation_type", "source_prediction_id"],
        "schema": {"premium_gated": True},
    },
    {
        "event_type": "multimodal.voice.analysis_ready",
        "category": "multimodal",
        "source": "saas_voice_intelligence_analyses|multimodal_memory",
        "description": "Sanitized voice analysis is available as tenant-scoped memory/training signal.",
        "required_fields": ["tenant_id", "conversation_id", "message_id"],
        "schema": {"raw_media_used": False, "base64_stored": False, "customer_content": True},
    },
    {
        "event_type": "multimodal.vision.analysis_ready",
        "category": "multimodal",
        "source": "saas_vision_intelligence_analyses|multimodal_memory",
        "description": "Sanitized image/document analysis is available as tenant-scoped memory/training signal.",
        "required_fields": ["tenant_id", "conversation_id", "message_id"],
        "schema": {"raw_media_used": False, "base64_stored": False, "customer_content": True},
    },
    {
        "event_type": "multimodal.external_source.approved",
        "category": "multimodal",
        "source": "saas_web_search_intelligence_results|multimodal_memory",
        "description": "Human-approved external source is available for agent/RAG context.",
        "required_fields": ["tenant_id", "entity_id", "approval_status"],
        "schema": {"approval_status": "approved", "blocked_source": False},
    },
    {
        "event_type": "multimodal.agent_tool.completed",
        "category": "multimodal",
        "source": "saas_ai_agent_tool_runs|multimodal_memory",
        "description": "Agent multimodal tool run completed and was distilled as training/memory signal.",
        "required_fields": ["tenant_id", "agent_id", "tool_code"],
        "schema": {"tool_status": "completed", "no_customer_side_effects": True},
    },
    {
        "event_type": "multimodal.memory.materialized",
        "category": "multimodal",
        "source": "multimodal_memory",
        "description": "A reviewed multimodal memory event was materialized into RAG and/or collective memory.",
        "required_fields": ["tenant_id", "entity_id", "destination"],
        "schema": {"manual_or_explicit_action": True, "auto_customer_send": False},
    },
]

FEATURE_SET_DEFINITIONS: dict[str, dict[str, Any]] = {
    "lead_scoring_v1": {
        "prediction_type": "lead_scoring",
        "version": "v1",
        "feature_keys": [
            "response_time",
            "message_count",
            "asked_for_price",
            "engagement_score",
            "avg_reply_speed",
            "channel_source_score",
            "followup_count",
            "multimodal_event_count",
            "multimodal_avg_confidence",
            "multimodal_sentiment_score",
            "multimodal_urgency_score",
            "approved_external_sources_count",
        ],
        "definitions": {
            "response_time": "Minutes from latest customer message to latest agent response; lower is better.",
            "message_count": "Conversation message volume in the training window.",
            "asked_for_price": "Keyword proxy for price/payment/product purchase intent.",
            "engagement_score": "Bounded 0-100 engagement proxy from volume, recency and CRM state.",
            "avg_reply_speed": "Average inter-message delay proxy in minutes.",
            "channel_source_score": "Stable channel prior for WhatsApp/Instagram/Facebook/web channels.",
            "followup_count": "Open/completed CRM tasks associated with the conversation.",
            "multimodal_event_count": "Number of distilled voice/vision/search memory signals for the conversation.",
            "multimodal_avg_confidence": "Average confidence across multimodal analysis signals.",
            "multimodal_sentiment_score": "Average sentiment from voice/vision analysis signals.",
            "multimodal_urgency_score": "Max urgency from multimodal analysis signals.",
            "approved_external_sources_count": "Human-approved external sources available for this conversation.",
        },
    },
    "churn_prediction_v1": {
        "prediction_type": "churn_prediction",
        "version": "v1",
        "feature_keys": [
            "inactivity_days",
            "negative_sentiment_ratio",
            "response_drop",
            "ticket_frequency",
            "engagement_decline",
            "message_count",
            "engagement_score",
            "multimodal_event_count",
            "multimodal_sentiment_score",
            "multimodal_urgency_score",
        ],
        "definitions": {
            "inactivity_days": "Days since last conversation message.",
            "negative_sentiment_ratio": "Keyword proxy ratio for complaints/frustration/escalation.",
            "response_drop": "Recent engagement drop proxy.",
            "ticket_frequency": "CRM task/ticket frequency for the conversation.",
            "engagement_decline": "Decline proxy from inactivity and recent message volume.",
            "message_count": "Conversation message volume in the training window.",
            "engagement_score": "Bounded 0-100 engagement proxy.",
            "multimodal_event_count": "Number of distilled voice/vision/search memory signals for the conversation.",
            "multimodal_sentiment_score": "Average sentiment from voice/vision analysis signals.",
            "multimodal_urgency_score": "Max urgency from multimodal analysis signals.",
        },
    },
    "smart_remarketing_v1": {
        "prediction_type": "smart_remarketing",
        "version": "v1",
        "feature_keys": [
            "open_rate",
            "click_rate",
            "best_hour",
            "best_channel_score",
            "campaign_engagement",
            "engagement_score",
            "inactivity_days",
            "approved_external_sources_count",
            "multimodal_event_count",
        ],
        "definitions": {
            "open_rate": "Broadcast read/open proxy from recipient status history.",
            "click_rate": "Campaign click/reply/convert proxy from A/B outcomes.",
            "best_hour": "Most active local hour derived from tenant messages.",
            "best_channel_score": "Stable channel prior for remarketing.",
            "campaign_engagement": "Campaign/broadcast positive outcome rate.",
            "engagement_score": "Bounded 0-100 engagement proxy.",
            "inactivity_days": "Days since last conversation message.",
            "approved_external_sources_count": "Human-approved external references that can support a follow-up.",
            "multimodal_event_count": "Number of distilled voice/vision/search memory signals for the conversation.",
        },
    },
    "operational_anomaly_v1": {
        "prediction_type": "operational_anomaly",
        "version": "v1",
        "feature_keys": [
            "webhook_errors_24h",
            "ai_failed_24h",
            "outbound_failed_24h",
            "dead_letters_open",
            "event_failure_rate",
        ],
        "definitions": {
            "webhook_errors_24h": "Webhook errors in the last 24 hours.",
            "ai_failed_24h": "AI run failures in the last 24 hours.",
            "outbound_failed_24h": "Outbound message failures in the last 24 hours.",
            "dead_letters_open": "Open dead-letter records.",
            "event_failure_rate": "Failure ratio over recent Intelligence events.",
        },
    },
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


def _period_yyyymm() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m")


def normalize_feature_key(value: str) -> str:
    return _clean(value, 120).lower().replace("-", "_")


def normalize_mode(value: str, *, enabled: bool = True) -> str:
    mode = _clean(value, 40).lower().replace("-", "_")
    if not enabled:
        return "disabled"
    if mode not in VALID_MODES:
        return "demo"
    return mode


def ensure_intelligence_tables(conn: Connection) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_intelligence_events (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                event_type TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT '',
                channel TEXT NOT NULL DEFAULT '',
                entity_type TEXT NOT NULL DEFAULT '',
                entity_id TEXT NOT NULL DEFAULT '',
                conversation_id UUID NULL REFERENCES saas_conversations(id) ON DELETE SET NULL,
                customer_key TEXT NOT NULL DEFAULT '',
                occurred_at TIMESTAMP NOT NULL DEFAULT NOW(),
                payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                correlation_id TEXT NOT NULL DEFAULT '',
                replay_key TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_intelligence_events_tenant_type_time ON saas_intelligence_events (tenant_id, event_type, occurred_at DESC)"))
    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_saas_intelligence_events_replay_key ON saas_intelligence_events (tenant_id, replay_key) WHERE replay_key <> ''"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_intelligence_feature_values (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                subject_type TEXT NOT NULL DEFAULT 'tenant',
                subject_id TEXT NOT NULL DEFAULT '',
                feature_key TEXT NOT NULL,
                window_key TEXT NOT NULL DEFAULT 'latest',
                value_numeric NUMERIC(18,6) NULL,
                value_text TEXT NOT NULL DEFAULT '',
                value_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                source TEXT NOT NULL DEFAULT 'snapshot',
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                computed_at TIMESTAMP NOT NULL DEFAULT NOW(),
                expires_at TIMESTAMP NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, subject_type, subject_id, feature_key, window_key)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_intelligence_features_tenant_subject ON saas_intelligence_feature_values (tenant_id, subject_type, subject_id, computed_at DESC)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_intelligence_predictions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                subject_type TEXT NOT NULL DEFAULT 'tenant',
                subject_id TEXT NOT NULL DEFAULT '',
                prediction_type TEXT NOT NULL,
                model_key TEXT NOT NULL DEFAULT 'baseline_rules',
                model_version TEXT NOT NULL DEFAULT 'v1',
                mode TEXT NOT NULL DEFAULT 'demo',
                score NUMERIC(8,4) NOT NULL DEFAULT 0,
                label TEXT NOT NULL DEFAULT '',
                confidence NUMERIC(8,4) NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'ready',
                explanation_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                features_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                output_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                expires_at TIMESTAMP NULL
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_intelligence_predictions_tenant_type ON saas_intelligence_predictions (tenant_id, prediction_type, created_at DESC)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_intelligence_recommendations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                recommendation_type TEXT NOT NULL,
                source_prediction_id UUID NULL REFERENCES saas_intelligence_predictions(id) ON DELETE SET NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                severity TEXT NOT NULL DEFAULT 'info',
                confidence NUMERIC(8,4) NOT NULL DEFAULT 0,
                action_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_intelligence_recommendations_tenant_status ON saas_intelligence_recommendations (tenant_id, status, updated_at DESC)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_intelligence_feature_grants (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                feature_key TEXT NOT NULL,
                enabled BOOLEAN NOT NULL DEFAULT FALSE,
                mode TEXT NOT NULL DEFAULT 'disabled',
                quota_monthly INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'admin',
                valid_until TIMESTAMP NULL,
                notes TEXT NOT NULL DEFAULT '',
                updated_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, feature_key)
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_intelligence_model_registry (
                model_key TEXT PRIMARY KEY,
                model_type TEXT NOT NULL DEFAULT 'rules',
                task_type TEXT NOT NULL DEFAULT '',
                framework TEXT NOT NULL DEFAULT '',
                version TEXT NOT NULL DEFAULT 'v1',
                status TEXT NOT NULL DEFAULT 'active',
                stage TEXT NOT NULL DEFAULT 'production',
                artifact_uri TEXT NOT NULL DEFAULT '',
                shadow_mode BOOLEAN NOT NULL DEFAULT FALSE,
                metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
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
            ALTER TABLE saas_intelligence_model_registry
                ADD COLUMN IF NOT EXISTS rollout_mode TEXT NOT NULL DEFAULT 'production',
                ADD COLUMN IF NOT EXISTS traffic_percent INTEGER NOT NULL DEFAULT 100,
                ADD COLUMN IF NOT EXISTS min_labeled_count INTEGER NOT NULL DEFAULT 10,
                ADD COLUMN IF NOT EXISTS min_accuracy NUMERIC(8,4) NOT NULL DEFAULT 70,
                ADD COLUMN IF NOT EXISTS max_drift_score NUMERIC(8,4) NOT NULL DEFAULT 25,
                ADD COLUMN IF NOT EXISTS promotion_status TEXT NOT NULL DEFAULT 'approved',
                ADD COLUMN IF NOT EXISTS approved_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP NULL
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_intelligence_model_rollout_events (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                model_key TEXT NOT NULL REFERENCES saas_intelligence_model_registry(model_key) ON DELETE CASCADE,
                tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                action TEXT NOT NULL DEFAULT '',
                previous_state_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                next_state_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                reason TEXT NOT NULL DEFAULT '',
                created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_intelligence_rollout_events_model_time ON saas_intelligence_model_rollout_events (model_key, created_at DESC)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_intelligence_rollout_events_tenant_time ON saas_intelligence_model_rollout_events (tenant_id, created_at DESC) WHERE tenant_id IS NOT NULL"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_intelligence_usage (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                feature_key TEXT NOT NULL,
                usage_metric TEXT NOT NULL DEFAULT 'prediction_requests',
                quantity INTEGER NOT NULL DEFAULT 1,
                period_yyyymm TEXT NOT NULL,
                source_event_id UUID NULL REFERENCES saas_intelligence_events(id) ON DELETE SET NULL,
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_intelligence_usage_tenant_period ON saas_intelligence_usage (tenant_id, period_yyyymm, feature_key)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_intelligence_prediction_feedback (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                prediction_id UUID NOT NULL REFERENCES saas_intelligence_predictions(id) ON DELETE CASCADE,
                feedback_type TEXT NOT NULL DEFAULT 'outcome',
                actual_label TEXT NOT NULL DEFAULT '',
                actual_score NUMERIC(8,4) NULL,
                is_correct BOOLEAN NULL,
                outcome_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                notes TEXT NOT NULL DEFAULT '',
                created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, prediction_id, feedback_type)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_intelligence_feedback_tenant_time ON saas_intelligence_prediction_feedback (tenant_id, created_at DESC)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_intelligence_feedback_prediction ON saas_intelligence_prediction_feedback (tenant_id, prediction_id)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_intelligence_model_metrics (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                model_key TEXT NOT NULL,
                prediction_type TEXT NOT NULL DEFAULT '',
                window_key TEXT NOT NULL DEFAULT '90d',
                sample_size INTEGER NOT NULL DEFAULT 0,
                labeled_count INTEGER NOT NULL DEFAULT 0,
                accuracy NUMERIC(8,4) NULL,
                precision_score NUMERIC(8,4) NULL,
                recall_score NUMERIC(8,4) NULL,
                avg_confidence NUMERIC(8,4) NULL,
                avg_score NUMERIC(8,4) NULL,
                avg_error NUMERIC(8,4) NULL,
                drift_score NUMERIC(8,4) NULL,
                status TEXT NOT NULL DEFAULT 'insufficient_data',
                metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                computed_at TIMESTAMP NOT NULL DEFAULT NOW(),
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, model_key, prediction_type, window_key)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_intelligence_model_metrics_tenant_status ON saas_intelligence_model_metrics (tenant_id, status, computed_at DESC)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_intelligence_model_metrics_model ON saas_intelligence_model_metrics (model_key, prediction_type, computed_at DESC)"))
    ensure_ml_training_tables(conn)


def ensure_ml_training_tables(conn: Connection) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_intelligence_event_contracts (
                event_type TEXT PRIMARY KEY,
                version TEXT NOT NULL DEFAULT 'v1',
                category TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                required_fields_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                schema_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                pii_policy TEXT NOT NULL DEFAULT 'no_raw_content',
                retention_days INTEGER NOT NULL DEFAULT 365,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_intelligence_event_contracts_category ON saas_intelligence_event_contracts (category, enabled)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_intelligence_event_replay_cursors (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                source_name TEXT NOT NULL,
                cursor_key TEXT NOT NULL DEFAULT '',
                last_event_at TIMESTAMP NULL,
                last_replay_key TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                stats_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, source_name, cursor_key)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_intelligence_event_replay_cursors_source ON saas_intelligence_event_replay_cursors (source_name, status, updated_at DESC)"))
    conn.execute(
        text(
            """
            ALTER TABLE saas_intelligence_feature_values
                ADD COLUMN IF NOT EXISTS feature_set_key TEXT NOT NULL DEFAULT 'default',
                ADD COLUMN IF NOT EXISTS feature_version TEXT NOT NULL DEFAULT 'v1',
                ADD COLUMN IF NOT EXISTS quality_json JSONB NOT NULL DEFAULT '{}'::jsonb
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_intelligence_features_set ON saas_intelligence_feature_values (tenant_id, feature_set_key, feature_version, computed_at DESC)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ml_auto_labels (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                prediction_type TEXT NOT NULL,
                subject_type TEXT NOT NULL DEFAULT 'tenant',
                subject_id TEXT NOT NULL DEFAULT '',
                label_key TEXT NOT NULL,
                label_value BOOLEAN NOT NULL,
                label_text TEXT NOT NULL DEFAULT '',
                label_confidence NUMERIC(8,4) NOT NULL DEFAULT 0,
                source_event_id UUID NULL REFERENCES saas_intelligence_events(id) ON DELETE SET NULL,
                evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                window_key TEXT NOT NULL DEFAULT '90d',
                generated_by TEXT NOT NULL DEFAULT 'auto_labeler_v1',
                generated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                expires_at TIMESTAMP NULL,
                replay_key TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, prediction_type, subject_type, subject_id, label_key, window_key)
            )
            """
        )
    )
    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_saas_ml_auto_labels_replay_key ON saas_ml_auto_labels (tenant_id, replay_key) WHERE replay_key <> ''"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ml_auto_labels_training ON saas_ml_auto_labels (tenant_id, prediction_type, window_key, generated_at DESC)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ml_feature_sets (
                feature_set_key TEXT PRIMARY KEY,
                prediction_type TEXT NOT NULL DEFAULT '',
                version TEXT NOT NULL DEFAULT 'v1',
                status TEXT NOT NULL DEFAULT 'active',
                feature_keys_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                definitions_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ml_feature_sets_prediction ON saas_ml_feature_sets (prediction_type, status)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ml_feature_pipeline_runs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                pipeline_key TEXT NOT NULL,
                prediction_type TEXT NOT NULL DEFAULT '',
                feature_set_key TEXT NOT NULL DEFAULT '',
                window_key TEXT NOT NULL DEFAULT '90d',
                status TEXT NOT NULL DEFAULT 'running',
                subjects_processed INTEGER NOT NULL DEFAULT 0,
                features_written INTEGER NOT NULL DEFAULT 0,
                labels_generated INTEGER NOT NULL DEFAULT 0,
                stats_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                error_text TEXT NOT NULL DEFAULT '',
                started_at TIMESTAMP NULL,
                completed_at TIMESTAMP NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ml_feature_pipeline_runs_tenant ON saas_ml_feature_pipeline_runs (tenant_id, prediction_type, status, created_at DESC)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ml_training_datasets (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                dataset_key TEXT NOT NULL,
                prediction_type TEXT NOT NULL,
                feature_set_key TEXT NOT NULL DEFAULT '',
                version TEXT NOT NULL DEFAULT 'v1',
                window_key TEXT NOT NULL DEFAULT '90d',
                label_policy TEXT NOT NULL DEFAULT 'auto_label_v1',
                source TEXT NOT NULL DEFAULT 'postgres_feature_store',
                sample_count INTEGER NOT NULL DEFAULT 0,
                positive_count INTEGER NOT NULL DEFAULT 0,
                negative_count INTEGER NOT NULL DEFAULT 0,
                label_distribution_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                feature_summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                dataset_uri TEXT NOT NULL DEFAULT '',
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (dataset_key, version)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ml_training_datasets_task ON saas_ml_training_datasets (prediction_type, created_at DESC)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ml_training_datasets_tenant ON saas_ml_training_datasets (tenant_id, prediction_type, created_at DESC) WHERE tenant_id IS NOT NULL"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ml_model_evaluations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                model_key TEXT NOT NULL,
                model_version TEXT NOT NULL DEFAULT '',
                prediction_type TEXT NOT NULL DEFAULT '',
                evaluation_type TEXT NOT NULL DEFAULT 'offline',
                dataset_id UUID NULL REFERENCES saas_ml_training_datasets(id) ON DELETE SET NULL,
                status TEXT NOT NULL DEFAULT 'completed',
                metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                slices_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                notes TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ml_model_evaluations_model ON saas_ml_model_evaluations (model_key, model_version, evaluation_type, created_at DESC)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ml_model_evaluations_tenant ON saas_ml_model_evaluations (tenant_id, prediction_type, created_at DESC) WHERE tenant_id IS NOT NULL"))
    _seed_event_contracts(conn)
    _seed_feature_sets(conn)


def _seed_event_contracts(conn: Connection) -> None:
    for item in EVENT_CONTRACTS:
        conn.execute(
            text(
                """
                INSERT INTO saas_intelligence_event_contracts (
                    event_type, version, category, source, description,
                    required_fields_json, schema_json, pii_policy,
                    retention_days, enabled, metadata_json, updated_at
                )
                VALUES (
                    :event_type, 'v1', :category, :source, :description,
                    CAST(:required_fields AS jsonb), CAST(:schema_json AS jsonb),
                    'no_raw_content', 365, TRUE, CAST(:metadata_json AS jsonb), NOW()
                )
                ON CONFLICT (event_type)
                DO UPDATE SET
                    version = EXCLUDED.version,
                    category = EXCLUDED.category,
                    source = EXCLUDED.source,
                    description = EXCLUDED.description,
                    required_fields_json = EXCLUDED.required_fields_json,
                    schema_json = EXCLUDED.schema_json,
                    pii_policy = EXCLUDED.pii_policy,
                    retention_days = EXCLUDED.retention_days,
                    enabled = EXCLUDED.enabled,
                    metadata_json = saas_intelligence_event_contracts.metadata_json || EXCLUDED.metadata_json,
                    updated_at = NOW()
                """
            ),
            {
                "event_type": item["event_type"],
                "category": item["category"],
                "source": item["source"],
                "description": item["description"],
                "required_fields": _json(item.get("required_fields") or []),
                "schema_json": _json(item.get("schema") or {}),
                "metadata_json": _json({"phase": "11", "contract_source": "code_seed"}),
            },
        )


def _seed_feature_sets(conn: Connection) -> None:
    for feature_set_key, item in FEATURE_SET_DEFINITIONS.items():
        conn.execute(
            text(
                """
                INSERT INTO saas_ml_feature_sets (
                    feature_set_key, prediction_type, version, status,
                    feature_keys_json, definitions_json, metadata_json, updated_at
                )
                VALUES (
                    :feature_set_key, :prediction_type, :version, 'active',
                    CAST(:feature_keys AS jsonb), CAST(:definitions AS jsonb),
                    CAST(:metadata_json AS jsonb), NOW()
                )
                ON CONFLICT (feature_set_key)
                DO UPDATE SET
                    prediction_type = EXCLUDED.prediction_type,
                    version = EXCLUDED.version,
                    status = EXCLUDED.status,
                    feature_keys_json = EXCLUDED.feature_keys_json,
                    definitions_json = EXCLUDED.definitions_json,
                    metadata_json = saas_ml_feature_sets.metadata_json || EXCLUDED.metadata_json,
                    updated_at = NOW()
                """
            ),
            {
                "feature_set_key": feature_set_key,
                "prediction_type": item["prediction_type"],
                "version": item.get("version") or "v1",
                "feature_keys": _json(item.get("feature_keys") or []),
                "definitions": _json(item.get("definitions") or {}),
                "metadata_json": _json({"phase": "11", "store": "postgres_primary", "cache_ready": True, "clickhouse_ready": True}),
            },
        )


def intelligence_catalog() -> list[dict[str, Any]]:
    return [dict(item) for item in INTELLIGENCE_FEATURES]


def _grant_rows(conn: Connection, tenant_id: str) -> dict[str, dict[str, Any]]:
    ensure_intelligence_tables(conn)
    rows = conn.execute(
        text(
            """
            SELECT feature_key, enabled, mode, quota_monthly, source, valid_until::text, notes, updated_at::text
            FROM saas_intelligence_feature_grants
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().all()
    return {normalize_feature_key(row["feature_key"]): dict(row) for row in rows}


def _usage_rows(conn: Connection, tenant_id: str, period: str) -> dict[str, int]:
    rows = conn.execute(
        text(
            """
            SELECT feature_key, COALESCE(SUM(quantity), 0)::int AS used
            FROM saas_intelligence_usage
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND period_yyyymm = :period
            GROUP BY feature_key
            """
        ),
        {"tenant_id": tenant_id, "period": period},
    ).mappings().all()
    return {normalize_feature_key(row["feature_key"]): int(row["used"] or 0) for row in rows}


def intelligence_feature_state(conn: Connection, tenant_id: str) -> dict[str, Any]:
    ensure_intelligence_tables(conn)
    ensure_premium_gating_tables(conn)
    entitlements = tenant_entitlements(conn, tenant_id)
    features = entitlements.get("features", {}) or {}
    sources = entitlements.get("feature_sources", {}) or {}
    grants = _grant_rows(conn, tenant_id)
    plan_code = _clean((entitlements.get("plan") or {}).get("plan_code"), 80).lower().replace("-", "_")
    plan_limits = plan_feature_limits_for_plan(conn, plan_code) if plan_code else {}
    period = _period_yyyymm()
    usage = _usage_rows(conn, tenant_id, period)
    demo_enabled = bool(features.get("intelligence_demo", False))
    ai_premium = bool(features.get("ai_premium", False))
    items: list[dict[str, Any]] = []

    for catalog_item in INTELLIGENCE_FEATURES:
        key = catalog_item["key"]
        grant = grants.get(key)
        flag_full = bool(features.get(key, False)) or (ai_premium and key not in {"intelligence_demo"})
        mode = "disabled"
        enabled = False
        source = str(sources.get(key) or "default")
        quota = int(catalog_item.get("default_quota_monthly") or 0)
        valid_until = ""
        notes = ""
        plan_limit = plan_limits.get(key)
        if grant:
            mode = normalize_mode(str(grant.get("mode") or ""), enabled=bool(grant.get("enabled")))
            enabled = mode != "disabled"
            source = str(grant.get("source") or "admin")
            quota = int(grant.get("quota_monthly") or quota)
            valid_until = str(grant.get("valid_until") or "")
            notes = str(grant.get("notes") or "")
        elif plan_limit:
            mode = normalize_mode(str(plan_limit.get("mode") or ""), enabled=bool(plan_limit.get("enabled")))
            enabled = mode != "disabled"
            source = "plan_quota"
            quota = int(plan_limit.get("quota_monthly") or quota)
            notes = str(plan_limit.get("notes") or "")
        elif flag_full:
            mode = "demo" if key == "intelligence_demo" else "full"
            enabled = True
        elif demo_enabled and bool(catalog_item.get("demo_allowed")):
            mode = "demo"
            enabled = True
            source = "demo"
        items.append(
            {
                **catalog_item,
                "enabled": enabled,
                "mode": mode,
                "source": source,
                "quota_monthly": quota,
                "quota_used": int(usage.get(key, 0) or 0),
                "valid_until": valid_until,
                "notes": notes,
                "plan_limit": dict(plan_limit) if plan_limit else None,
            }
        )
    return {
        "tenant_id": tenant_id,
        "period_yyyymm": period,
        "plan": entitlements.get("plan", {}),
        "tenant_status": entitlements.get("tenant_status"),
        "is_operational": entitlements.get("is_operational"),
        "features": items,
    }


def resolve_intelligence_access(conn: Connection, tenant_id: str, feature_key: str, *, allow_demo: bool = True) -> dict[str, Any]:
    key = normalize_feature_key(feature_key)
    if key not in INTELLIGENCE_FEATURE_MAP:
        raise HTTPException(status_code=400, detail={"code": "unknown_intelligence_feature", "feature": key})
    state = intelligence_feature_state(conn, tenant_id)
    if not state.get("is_operational"):
        raise HTTPException(status_code=403, detail={"code": "tenant_not_operational"})
    item = next((feature for feature in state["features"] if feature["key"] == key), None)
    if not item or not item.get("enabled"):
        raise HTTPException(status_code=403, detail={"code": "intelligence_feature_not_enabled", "feature": key})
    if item["mode"] == "demo" and not allow_demo:
        raise HTTPException(status_code=403, detail={"code": "intelligence_feature_requires_full", "feature": key})
    return item


def record_intelligence_usage(
    conn: Connection,
    tenant_id: str,
    feature_key: str,
    *,
    quantity: int = 1,
    usage_metric: str = "prediction_requests",
    metadata: dict[str, Any] | None = None,
) -> None:
    access = resolve_intelligence_access(conn, tenant_id, feature_key, allow_demo=True)
    quota = int(access.get("quota_monthly") or 0)
    used = int(access.get("quota_used") or 0)
    amount = max(1, int(quantity or 1))
    if quota > 0 and used + amount > quota:
        raise HTTPException(
            status_code=402,
            detail={"code": "intelligence_quota_exceeded", "feature": feature_key, "quota": quota, "used": used, "requested": amount},
        )
    conn.execute(
        text(
            """
            INSERT INTO saas_intelligence_usage (tenant_id, feature_key, usage_metric, quantity, period_yyyymm, metadata_json)
            VALUES (CAST(:tenant_id AS uuid), :feature_key, :usage_metric, :quantity, :period, CAST(:metadata_json AS jsonb))
            """
        ),
        {
            "tenant_id": tenant_id,
            "feature_key": normalize_feature_key(feature_key),
            "usage_metric": _clean(usage_metric, 80) or "prediction_requests",
            "quantity": amount,
            "period": _period_yyyymm(),
            "metadata_json": _json(metadata or {}),
        },
    )


def record_event(conn: Connection, tenant_id: str, payload: Any) -> dict[str, Any]:
    ensure_intelligence_tables(conn)
    data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload or {})
    row = conn.execute(
        text(
            """
            INSERT INTO saas_intelligence_events (
                tenant_id, event_type, source, channel, entity_type, entity_id,
                conversation_id, customer_key, occurred_at, payload_json, correlation_id, replay_key
            )
            VALUES (
                CAST(:tenant_id AS uuid), :event_type, :source, :channel, :entity_type, :entity_id,
                CAST(NULLIF(:conversation_id, '') AS uuid), :customer_key,
                COALESCE(CAST(NULLIF(:occurred_at, '') AS timestamp), NOW()),
                CAST(:payload_json AS jsonb), :correlation_id, :replay_key
            )
            ON CONFLICT (tenant_id, replay_key) WHERE replay_key <> ''
            DO UPDATE SET payload_json = saas_intelligence_events.payload_json || EXCLUDED.payload_json
            RETURNING id::text, event_type, source, channel, entity_type, entity_id,
                      COALESCE(conversation_id::text, '') AS conversation_id,
                      customer_key, occurred_at::text, correlation_id, replay_key, created_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "event_type": _clean(data.get("event_type"), 160),
            "source": _clean(data.get("source"), 120),
            "channel": _clean(data.get("channel"), 80),
            "entity_type": _clean(data.get("entity_type"), 120),
            "entity_id": _clean(data.get("entity_id"), 160),
            "conversation_id": _clean(data.get("conversation_id"), 80),
            "customer_key": _clean(data.get("customer_key"), 180),
            "occurred_at": _clean(data.get("occurred_at"), 80),
            "payload_json": _json(data.get("payload_json") or {}),
            "correlation_id": _clean(data.get("correlation_id"), 160),
            "replay_key": _clean(data.get("replay_key"), 240),
        },
    ).mappings().first()
    return dict(row or {})


def _upsert_feature(
    conn: Connection,
    tenant_id: str,
    *,
    subject_type: str,
    subject_id: str,
    window_key: str,
    feature_key: str,
    value_numeric: float | int | None = None,
    value_text: str = "",
    value_json: dict[str, Any] | None = None,
    source: str = "snapshot",
    feature_set_key: str = "default",
    feature_version: str = "v1",
    quality_json: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        text(
            """
            INSERT INTO saas_intelligence_feature_values (
                tenant_id, subject_type, subject_id, feature_key, window_key,
                value_numeric, value_text, value_json, source, feature_set_key,
                feature_version, quality_json, updated_at, computed_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), :subject_type, :subject_id, :feature_key, :window_key,
                :value_numeric, :value_text, CAST(:value_json AS jsonb), :source,
                :feature_set_key, :feature_version, CAST(:quality_json AS jsonb), NOW(), NOW()
            )
            ON CONFLICT (tenant_id, subject_type, subject_id, feature_key, window_key)
            DO UPDATE SET
                value_numeric = EXCLUDED.value_numeric,
                value_text = EXCLUDED.value_text,
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
            "subject_type": subject_type,
            "subject_id": subject_id,
            "feature_key": feature_key,
            "window_key": window_key,
            "value_numeric": value_numeric,
            "value_text": _clean(value_text, 2000),
            "value_json": _json(value_json or {}),
            "source": _clean(source, 80),
            "feature_set_key": _clean(feature_set_key, 160) or "default",
            "feature_version": _clean(feature_version, 80) or "v1",
            "quality_json": _json(quality_json or {}),
        },
    )


def _channel_source_score(channel: str) -> float:
    clean = _clean(channel, 80).lower()
    if clean == "whatsapp":
        return 1.0
    if clean in {"instagram", "instagram_dm"}:
        return 0.9
    if clean in {"facebook", "messenger"}:
        return 0.85
    if clean in {"web", "website"}:
        return 0.75
    return 0.65


def _conversation_feature_snapshot(conn: Connection, tenant_id: str, conversation_id: str, *, window_key: str) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            SELECT c.id::text AS conversation_id,
                   c.channel,
                   c.crm_stage,
                   c.payment_status,
                   c.intent,
                   c.customer_type,
                   c.lead_score,
                   c.lead_temperature,
                   c.created_at,
                   c.last_message_at,
                   c.last_customer_message_at,
                   c.last_agent_message_at,
                   COALESCE(EXTRACT(EPOCH FROM (NOW() - COALESCE(c.last_message_at, c.created_at))) / 86400, 999)::numeric(10,2) AS inactivity_days,
                   COALESCE(EXTRACT(EPOCH FROM (c.last_agent_message_at - c.last_customer_message_at)) / 60, 0)::numeric(10,2) AS response_time,
                   COALESCE((
                       SELECT COUNT(*)::int
                       FROM saas_messages m
                       WHERE m.tenant_id = c.tenant_id
                         AND m.conversation_id = c.id
                         AND m.created_at >= NOW() - (:window_days * INTERVAL '1 day')
                   ), 0) AS message_count,
                   COALESCE((
                       SELECT COUNT(*)::int
                       FROM saas_messages m
                       WHERE m.tenant_id = c.tenant_id
                         AND m.conversation_id = c.id
                         AND m.direction = 'inbound'
                         AND m.created_at >= NOW() - (:window_days * INTERVAL '1 day')
                   ), 0) AS inbound_count,
                   COALESCE((
                       SELECT COUNT(*)::int
                       FROM saas_messages m
                       WHERE m.tenant_id = c.tenant_id
                         AND m.conversation_id = c.id
                         AND m.direction = 'outbound'
                         AND m.created_at >= NOW() - (:window_days * INTERVAL '1 day')
                   ), 0) AS outbound_count,
                   COALESCE((
                       SELECT COUNT(*)::int
                       FROM saas_messages m
                       WHERE m.tenant_id = c.tenant_id
                         AND m.conversation_id = c.id
                         AND m.created_at >= NOW() - (:window_days * INTERVAL '1 day')
                         AND LOWER(COALESCE(m.text, '')) ~ '(precio|price|costo|cost|pago|compr|cotiz|reserv|disponible|catalogo|catálogo)'
                   ), 0) AS asked_for_price,
                   COALESCE((
                       SELECT COUNT(*)::int
                       FROM saas_messages m
                       WHERE m.tenant_id = c.tenant_id
                         AND m.conversation_id = c.id
                         AND m.created_at >= NOW() - (:window_days * INTERVAL '1 day')
                         AND LOWER(COALESCE(m.text, '')) ~ '(queja|molest|malo|terrible|cancel|devolu|reclamo|demora|problema|error|no sirve)'
                   ), 0) AS negative_message_count,
                   COALESCE((
                       SELECT COUNT(*)::int
                       FROM saas_crm_tasks t
                       WHERE t.tenant_id = c.tenant_id
                         AND t.conversation_id = c.id
                         AND t.created_at >= NOW() - (:window_days * INTERVAL '1 day')
                   ), 0) AS followup_count,
                   COALESCE((
                       SELECT COUNT(*)::int
                       FROM saas_broadcast_recipients br
                       WHERE br.tenant_id = c.tenant_id
                         AND br.conversation_id = c.id
                         AND br.status IN ('read', 'replied', 'delivered', 'sent')
                         AND br.created_at >= NOW() - (:window_days * INTERVAL '1 day')
                   ), 0) AS broadcast_positive,
                   COALESCE((
                       SELECT COUNT(*)::int
                       FROM saas_broadcast_recipients br
                       WHERE br.tenant_id = c.tenant_id
                         AND br.conversation_id = c.id
                         AND br.created_at >= NOW() - (:window_days * INTERVAL '1 day')
                   ), 0) AS broadcast_total,
                   COALESCE((
                       SELECT COUNT(*)::int
                       FROM saas_campaign_ab_events e
                       WHERE e.tenant_id = c.tenant_id
                         AND e.conversation_id = c.id
                         AND e.outcome IN ('clicked', 'replied', 'converted', 'purchased', 'success')
                         AND e.created_at >= NOW() - (:window_days * INTERVAL '1 day')
                   ), 0) AS campaign_positive,
                   COALESCE((
                       SELECT COUNT(*)::int
                       FROM saas_campaign_ab_events e
                       WHERE e.tenant_id = c.tenant_id
                         AND e.conversation_id = c.id
                         AND e.created_at >= NOW() - (:window_days * INTERVAL '1 day')
                   ), 0) AS campaign_total,
                   COALESCE((
                       SELECT EXTRACT(HOUR FROM MAX(m.created_at))::int
                       FROM saas_messages m
                       WHERE m.tenant_id = c.tenant_id
                         AND m.conversation_id = c.id
                   ), 10) AS best_hour
            FROM saas_conversations c
            WHERE c.tenant_id = CAST(:tenant_id AS uuid)
              AND c.id = CAST(:conversation_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "conversation_id": conversation_id, "window_days": _window_days(window_key)},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail={"code": "conversation_not_found"})
    item = dict(row)
    message_count = float(item.get("message_count") or 0)
    inbound_count = float(item.get("inbound_count") or 0)
    outbound_count = float(item.get("outbound_count") or 0)
    inactivity_days = float(item.get("inactivity_days") or 0)
    response_time = max(0.0, float(item.get("response_time") or 0))
    lead_score = float(item.get("lead_score") or 0)
    negative_count = float(item.get("negative_message_count") or 0)
    broadcast_total = float(item.get("broadcast_total") or 0)
    campaign_total = float(item.get("campaign_total") or 0)
    campaign_positive = float(item.get("campaign_positive") or 0)
    broadcast_positive = float(item.get("broadcast_positive") or 0)
    open_rate = (broadcast_positive / broadcast_total * 100.0) if broadcast_total else 0.0
    click_rate = (campaign_positive / campaign_total * 100.0) if campaign_total else 0.0
    negative_ratio = (negative_count / message_count * 100.0) if message_count else 0.0
    channel_score = _channel_source_score(str(item.get("channel") or ""))
    engagement_score = max(
        0.0,
        min(
            100.0,
            lead_score * 0.35
            + min(message_count * 4.0, 30.0)
            + min(inbound_count * 3.0, 20.0)
            + (10.0 if float(item.get("asked_for_price") or 0) > 0 else 0.0)
            + channel_score * 10.0
            - min(inactivity_days * 1.4, 35.0)
            - min(response_time / 60.0, 10.0),
        ),
    )
    response_drop = max(0.0, min(100.0, inactivity_days * 1.8 - inbound_count * 2.0))
    engagement_decline = max(0.0, min(100.0, 100.0 - engagement_score + min(inactivity_days, 45.0)))
    avg_reply_speed = response_time or max(0.0, min(720.0, inactivity_days * 24.0))
    campaign_engagement = max(open_rate, click_rate, (campaign_positive + broadcast_positive) / max(1.0, campaign_total + broadcast_total) * 100.0)
    features = {
        "response_time": response_time,
        "message_count": message_count,
        "asked_for_price": float(item.get("asked_for_price") or 0),
        "engagement_score": engagement_score,
        "avg_reply_speed": avg_reply_speed,
        "channel_source_score": channel_score,
        "followup_count": float(item.get("followup_count") or 0),
        "inactivity_days": inactivity_days,
        "negative_sentiment_ratio": negative_ratio,
        "response_drop": response_drop,
        "ticket_frequency": float(item.get("followup_count") or 0),
        "engagement_decline": engagement_decline,
        "open_rate": open_rate,
        "click_rate": click_rate,
        "best_hour": float(item.get("best_hour") or 10),
        "best_channel_score": channel_score,
        "campaign_engagement": campaign_engagement,
        "lead_score": lead_score,
    }
    if _pg_table_exists(conn, "saas_multimodal_memory_events"):
        multimodal = conn.execute(
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
                  AND updated_at >= NOW() - (:window_days * INTERVAL '1 day')
                """
            ),
            {"tenant_id": tenant_id, "conversation_id": conversation_id, "window_days": _window_days(window_key)},
        ).mappings().first() or {}
        features.update(
            {
                "multimodal_event_count": float(multimodal.get("event_count") or 0),
                "approved_external_sources_count": float(multimodal.get("approved_external_sources") or 0),
                "multimodal_avg_confidence": float(multimodal.get("avg_confidence") or 0),
                "multimodal_sentiment_score": float(multimodal.get("avg_sentiment_score") or 0),
                "multimodal_urgency_score": float(multimodal.get("max_urgency_score") or 0),
                "multimodal_text_chars": float(multimodal.get("text_chars") or 0),
            }
        )
    for key, value in features.items():
        _upsert_feature(
            conn,
            tenant_id,
            subject_type="conversation",
            subject_id=conversation_id,
            window_key=window_key,
            feature_key=key,
            value_numeric=float(value or 0),
            value_json={"value": float(value or 0)},
            source="conversation_feature_snapshot",
            feature_set_key="conversation_features_v1",
            feature_version="v1",
            quality_json={"window_key": window_key, "raw_content_used": False},
        )
    return {"tenant_id": tenant_id, "subject_type": "conversation", "subject_id": conversation_id, "window_key": window_key, "features": features}


def recompute_feature_snapshot(conn: Connection, tenant_id: str, *, subject_type: str = "tenant", subject_id: str = "", window_key: str = "latest") -> dict[str, Any]:
    ensure_intelligence_tables(conn)
    clean_subject_type = _clean(subject_type, 80) or "tenant"
    clean_subject_id = _clean(subject_id, 160) or tenant_id
    clean_window = _clean(window_key, 80) or "latest"
    if clean_subject_type in {"conversation", "customer"} and clean_subject_id and clean_subject_id != tenant_id:
        return _conversation_feature_snapshot(conn, tenant_id, clean_subject_id, window_key=clean_window)
    crm = conn.execute(
        text(
            """
            SELECT
                COUNT(*)::int AS conversations,
                COUNT(*) FILTER (WHERE lead_score >= 75 OR LOWER(lead_temperature) = 'hot')::int AS hot_leads,
                COALESCE(AVG(NULLIF(lead_score, 0)), 0)::numeric(10,2) AS avg_lead_score,
                COUNT(*) FILTER (WHERE last_message_at >= NOW() - INTERVAL '7 days')::int AS active_7d,
                COUNT(*) FILTER (WHERE last_message_at < NOW() - INTERVAL '14 days' OR last_message_at IS NULL)::int AS inactive_14d,
                COALESCE(EXTRACT(EPOCH FROM (NOW() - MAX(last_message_at))) / 86400, 999)::numeric(10,2) AS inactivity_days,
                COALESCE(AVG(EXTRACT(EPOCH FROM (last_agent_message_at - last_customer_message_at)) / 60)
                    FILTER (WHERE last_customer_message_at IS NOT NULL AND last_agent_message_at IS NOT NULL AND last_agent_message_at >= last_customer_message_at), 0)::numeric(10,2) AS avg_response_time_minutes
            FROM saas_conversations
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first() or {}
    messages = conn.execute(
        text(
            """
            SELECT
                COUNT(*) FILTER (WHERE direction = 'inbound')::int AS inbound_30d,
                COUNT(*) FILTER (WHERE direction = 'outbound')::int AS outbound_30d,
                COUNT(DISTINCT conversation_id)::int AS engaged_conversations_30d
            FROM saas_messages
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND created_at >= NOW() - INTERVAL '30 days'
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first() or {}
    ops = conn.execute(
        text(
            """
            SELECT
                COALESCE((SELECT COUNT(*)::int FROM saas_ai_runs WHERE tenant_id = CAST(:tenant_id AS uuid) AND status = 'failed' AND created_at >= NOW() - INTERVAL '24 hours'), 0) AS ai_failed_24h,
                COALESCE((SELECT COUNT(*)::int FROM saas_webhook_events WHERE tenant_id = CAST(:tenant_id AS uuid) AND status IN ('error','failed') AND received_at >= NOW() - INTERVAL '24 hours'), 0) AS webhook_errors_24h,
                COALESCE((SELECT COUNT(*)::int FROM saas_dead_letter_events WHERE tenant_id = CAST(:tenant_id AS uuid) AND status = 'open'), 0) AS dead_letters_open,
                COALESCE((SELECT COUNT(*)::int FROM saas_outbound_messages WHERE tenant_id = CAST(:tenant_id AS uuid) AND status = 'failed' AND updated_at >= NOW() - INTERVAL '24 hours'), 0) AS outbound_failed_24h
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first() or {}
    campaigns = conn.execute(
        text(
            """
            SELECT
                COALESCE((SELECT COUNT(*)::int FROM saas_campaigns WHERE tenant_id = CAST(:tenant_id AS uuid) AND COALESCE(status, '') <> 'archived'), 0) AS campaigns,
                COALESCE((SELECT COUNT(*)::int FROM saas_crm_triggers WHERE tenant_id = CAST(:tenant_id AS uuid) AND is_active = TRUE), 0) AS active_triggers,
                COALESCE((SELECT COUNT(*)::int FROM saas_remarketing_enrollments WHERE tenant_id = CAST(:tenant_id AS uuid) AND state = 'active'), 0) AS active_remarketing
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first() or {}
    features = {**dict(crm), **dict(messages), **dict(ops), **dict(campaigns)}
    numeric_keys = (
        "conversations",
        "hot_leads",
        "avg_lead_score",
        "active_7d",
        "inactive_14d",
        "inactivity_days",
        "avg_response_time_minutes",
        "inbound_30d",
        "outbound_30d",
        "engaged_conversations_30d",
        "ai_failed_24h",
        "webhook_errors_24h",
        "dead_letters_open",
        "outbound_failed_24h",
        "campaigns",
        "active_triggers",
        "active_remarketing",
    )
    for key in numeric_keys:
        try:
            value = float(features.get(key) or 0)
        except (TypeError, ValueError):
            value = 0.0
        _upsert_feature(
            conn,
            tenant_id,
            subject_type=clean_subject_type,
            subject_id=clean_subject_id,
            window_key=clean_window,
            feature_key=key,
            value_numeric=value,
            value_json={"value": value},
        )
    return {
        "tenant_id": tenant_id,
        "subject_type": clean_subject_type,
        "subject_id": clean_subject_id,
        "window_key": clean_window,
        "features": features,
    }


def list_feature_values(conn: Connection, tenant_id: str, *, subject_type: str = "tenant", subject_id: str = "", limit: int = 120) -> list[dict[str, Any]]:
    ensure_intelligence_tables(conn)
    clean_subject_id = _clean(subject_id, 160) or tenant_id
    rows = conn.execute(
        text(
            """
            SELECT id::text, subject_type, subject_id, feature_key, window_key,
                   value_numeric, value_text, value_json, source, feature_set_key,
                   feature_version, quality_json, computed_at::text, updated_at::text
            FROM saas_intelligence_feature_values
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND subject_type = :subject_type
              AND subject_id = :subject_id
            ORDER BY computed_at DESC, feature_key ASC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "subject_type": _clean(subject_type, 80) or "tenant", "subject_id": clean_subject_id, "limit": max(1, min(int(limit or 120), 500))},
    ).mappings().all()
    return [dict(row) for row in rows]


def _label(score: float, *, high: str = "high", medium: str = "medium", low: str = "low") -> str:
    if score >= 70:
        return high
    if score >= 40:
        return medium
    return low


def _prediction_payload(prediction_type: str, features: dict[str, Any]) -> dict[str, Any]:
    conversations = max(1.0, float(features.get("conversations") or 0))
    hot_leads = float(features.get("hot_leads") or 0)
    avg_lead_score = float(features.get("avg_lead_score") or 0)
    inactive_14d = float(features.get("inactive_14d") or 0)
    inactivity_days = float(features.get("inactivity_days") or 0)
    avg_response = float(features.get("avg_response_time_minutes") or 0)
    failures = float(features.get("ai_failed_24h") or 0) + float(features.get("webhook_errors_24h") or 0) + float(features.get("dead_letters_open") or 0) + float(features.get("outbound_failed_24h") or 0)
    is_subject_snapshot = "message_count" in features or "engagement_score" in features
    if prediction_type == "lead_scoring":
        if is_subject_snapshot:
            engagement = float(features.get("engagement_score") or 0)
            asked_for_price = float(features.get("asked_for_price") or 0)
            followups = float(features.get("followup_count") or 0)
            response = float(features.get("response_time") or features.get("avg_reply_speed") or 0)
            score = min(100.0, max(float(features.get("lead_score") or 0), engagement + min(asked_for_price * 8.0, 16.0) + min(followups * 2.5, 8.0) - min(response / 90.0, 12.0)))
            return {
                "model_key": "baseline_lead_scoring_v1",
                "score": round(score, 2),
                "label": _label(score, high="hot", medium="warm", low="cold"),
                "confidence": 0.6 if float(features.get("message_count") or 0) >= 3 else 0.4,
                "explanation": {"engagement_score": engagement, "asked_for_price": asked_for_price, "followup_count": followups},
                "output": {"suggested_action": "prioritize_human_followup", "scope": "conversation"},
            }
        score = min(100.0, max(avg_lead_score, (hot_leads / conversations) * 100.0))
        return {
            "model_key": "baseline_lead_scoring_v1",
            "score": round(score, 2),
            "label": _label(score, high="hot", medium="warm", low="cold"),
            "confidence": 0.62 if conversations >= 10 else 0.42,
            "explanation": {"hot_leads": hot_leads, "avg_lead_score": avg_lead_score, "sample_size": conversations},
            "output": {"hot_leads_detected": int(hot_leads), "suggested_action": "prioritize_human_followup"},
        }
    if prediction_type == "churn_prediction":
        if is_subject_snapshot:
            negative_ratio = float(features.get("negative_sentiment_ratio") or 0)
            response_drop = float(features.get("response_drop") or 0)
            engagement_decline = float(features.get("engagement_decline") or 0)
            ticket_frequency = float(features.get("ticket_frequency") or 0)
            score = min(100.0, inactivity_days * 1.4 + negative_ratio * 0.45 + response_drop * 0.25 + engagement_decline * 0.25 + min(ticket_frequency * 4.0, 12.0))
            return {
                "model_key": "baseline_churn_prediction_v1",
                "score": round(score, 2),
                "label": _label(score, high="high_risk", medium="medium_risk", low="low_risk"),
                "confidence": 0.58 if float(features.get("message_count") or 0) >= 3 else 0.38,
                "explanation": {"inactivity_days": inactivity_days, "negative_sentiment_ratio": negative_ratio, "engagement_decline": engagement_decline},
                "output": {"suggested_action": "launch_reactivation_segment", "scope": "conversation"},
            }
        score = min(100.0, (inactive_14d / conversations) * 75.0 + min(25.0, inactivity_days))
        return {
            "model_key": "baseline_churn_prediction_v1",
            "score": round(score, 2),
            "label": _label(score, high="high_risk", medium="medium_risk", low="low_risk"),
            "confidence": 0.58 if conversations >= 10 else 0.38,
            "explanation": {"inactive_14d": inactive_14d, "inactivity_days": inactivity_days, "sample_size": conversations},
            "output": {"at_risk_conversations": int(inactive_14d), "suggested_action": "launch_reactivation_segment"},
        }
    if prediction_type == "smart_remarketing":
        if is_subject_snapshot:
            engagement = float(features.get("engagement_score") or 0)
            campaign_engagement = float(features.get("campaign_engagement") or 0)
            open_rate = float(features.get("open_rate") or 0)
            click_rate = float(features.get("click_rate") or 0)
            best_hour = int(float(features.get("best_hour") or 10))
            score = min(100.0, engagement * 0.35 + campaign_engagement * 0.35 + open_rate * 0.15 + click_rate * 0.25 + min(inactivity_days, 20.0))
            return {
                "model_key": "baseline_smart_remarketing_v1",
                "score": round(score, 2),
                "label": _label(score, high="high_opportunity", medium="watchlist", low="low_opportunity"),
                "confidence": 0.56 if campaign_engagement > 0 or open_rate > 0 else 0.36,
                "explanation": {"campaign_engagement": campaign_engagement, "open_rate": open_rate, "click_rate": click_rate},
                "output": {
                    "best_channel": "whatsapp" if float(features.get("best_channel_score") or 0) >= 0.9 else "current_channel",
                    "best_window": f"{best_hour:02d}:00-{(best_hour + 2) % 24:02d}:00 local",
                    "frequency": "1 touch cada 48-72 horas",
                    "segment_hint": "conversaciones con engagement o inactividad recuperable",
                    "scope": "conversation",
                },
            }
        score = min(100.0, ((inactive_14d + hot_leads) / conversations) * 70.0 + min(30.0, avg_response / 10.0))
        return {
            "model_key": "baseline_smart_remarketing_v1",
            "score": round(score, 2),
            "label": _label(score, high="high_opportunity", medium="watchlist", low="low_opportunity"),
            "confidence": 0.55 if conversations >= 10 else 0.35,
            "explanation": {"inactive_14d": inactive_14d, "hot_leads": hot_leads, "avg_response_time_minutes": avg_response},
            "output": {
                "best_channel": "whatsapp",
                "best_window": "09:00-11:00 local",
                "frequency": "1 touch cada 48-72 horas",
                "segment_hint": "leads calientes inactivos o pagos pendientes",
            },
        }
    score = min(100.0, failures * 20.0)
    return {
        "model_key": "baseline_operational_anomaly_v1",
        "score": round(score, 2),
        "label": _label(score, high="degraded", medium="watch", low="normal"),
        "confidence": 0.65,
        "explanation": {"failures_24h_plus_open": failures},
        "output": {"suggested_action": "review_dead_letters_and_provider_health", "failure_signal": failures},
    }


def _rollout_bucket(*parts: Any) -> int:
    raw = "|".join(_clean(part, 240) for part in parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 100


def _model_registry_row(conn: Connection, model_key: str) -> dict[str, Any]:
    ensure_intelligence_tables(conn)
    row = conn.execute(
        text(
            """
            SELECT model_key, model_type, task_type, framework, version, status, stage,
                   artifact_uri, shadow_mode, rollout_mode, traffic_percent,
                   min_labeled_count, min_accuracy, max_drift_score, promotion_status,
                   COALESCE(approved_by_user_id::text, '') AS approved_by_user_id,
                   approved_at::text, metrics_json, metadata_json, created_at::text, updated_at::text
            FROM saas_intelligence_model_registry
            WHERE model_key = :model_key
            LIMIT 1
            """
        ),
        {"model_key": _clean(model_key, 160)},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail={"code": "intelligence_model_not_found", "model_key": model_key})
    return dict(row)


def _model_registry_rows_for_task(conn: Connection, task_type: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT model_key, model_type, task_type, framework, version, status, stage,
                   artifact_uri, shadow_mode, rollout_mode, traffic_percent,
                   min_labeled_count, min_accuracy, max_drift_score, promotion_status,
                   COALESCE(approved_by_user_id::text, '') AS approved_by_user_id,
                   approved_at::text, metrics_json, metadata_json, created_at::text, updated_at::text
            FROM saas_intelligence_model_registry
            WHERE task_type = :task_type
            ORDER BY
                CASE rollout_mode
                    WHEN 'production' THEN 0
                    WHEN 'canary' THEN 1
                    WHEN 'shadow' THEN 2
                    ELSE 3
                END,
                updated_at DESC,
                model_key ASC
            """
        ),
        {"task_type": _clean(task_type, 120).lower().replace("-", "_")},
    ).mappings().all()
    return [dict(row) for row in rows]


def _shadow_model_candidate(conn: Connection, task_type: str, *, excluded_model_key: str = "") -> dict[str, Any] | None:
    for model in _model_registry_rows_for_task(conn, task_type):
        if str(model.get("model_key") or "") == excluded_model_key:
            continue
        if str(model.get("rollout_mode") or "") != "shadow":
            continue
        if str(model.get("model_type") or "") == "rules":
            continue
        if str(model.get("status") or "") not in {"active", "candidate"}:
            continue
        if not model.get("artifact_uri"):
            continue
        return model
    return None


def _baseline_model_allowed(model: dict[str, Any]) -> bool:
    metadata = _json_object(model.get("metadata_json"))
    return str(model.get("model_type") or "") == "rules" and metadata.get("purpose") == "safe_baseline"


def _model_can_serve(model: dict[str, Any]) -> bool:
    return str(model.get("status") or "") == "active" and str(model.get("rollout_mode") or "production") != "disabled"


def _model_can_create_ready_predictions(model: dict[str, Any]) -> bool:
    return _baseline_model_allowed(model) or str(model.get("promotion_status") or "") == "approved"


def _call_ml_service_prediction(
    *,
    tenant_id: str,
    prediction_id: str = "",
    prediction_type: str,
    model_key: str,
    model_version: str,
    subject_type: str,
    subject_id: str,
    mode: str,
    features: dict[str, Any],
) -> dict[str, Any]:
    started = time.perf_counter()
    url = f"{settings.saas_ml_service_url.rstrip('/')}/predict"
    payload = {
        "tenant_id": tenant_id,
        "prediction_id": prediction_id,
        "task_type": prediction_type,
        "model_key": model_key,
        "version": model_version,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "mode": mode,
        "features": _json_safe(features),
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json", "Accept": "application/json"})
    timeout = max(1, min(int(settings.saas_ml_inference_timeout_sec or 3), 30))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8") or "{}")
        prediction = body.get("prediction") if isinstance(body, dict) else {}
        if not isinstance(prediction, dict):
            prediction = {}
        return {
            "attempted": True,
            "ok": True,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "prediction": prediction,
        }
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        return {
            "attempted": True,
            "ok": False,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "error": str(exc)[:500],
        }


def request_ml_synthetic_training(payload: Any) -> dict[str, Any]:
    if not settings.saas_ml_enabled:
        raise HTTPException(status_code=409, detail={"code": "ml_infrastructure_disabled", "message": "SAAS_ML_ENABLED must be true to run training."})
    data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload or {})
    url = f"{settings.saas_ml_service_url.rstrip('/')}/train/synthetic"
    body = json.dumps(
        {
            "tenant_id": _clean(data.get("tenant_id"), 80),
            "task_type": _clean(data.get("task_type"), 120).lower().replace("-", "_") or "lead_scoring",
            "model_key": _clean(data.get("model_key"), 160),
            "framework": _clean(data.get("framework"), 80) or "lightgbm",
            "version": _clean(data.get("version"), 80),
            "sample_size": max(50, min(int(data.get("sample_size") or 1000), 100000)),
            "seed": max(1, min(int(data.get("seed") or 42), 1000000000)),
            "register_artifact": True,
            "notes": _clean(data.get("notes"), 1000),
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json", "Accept": "application/json"})
    timeout = max(5, min(int(settings.saas_ml_inference_timeout_sec or 3) * 20, 600))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8") or "{}")
        if not isinstance(result, dict):
            result = {}
        if not result.get("ok"):
            raise HTTPException(status_code=502, detail={"code": "ml_training_service_failed", "response": result})
        return result
    except HTTPException:
        raise
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail={"code": "ml_training_service_unavailable", "message": str(exc)[:500]}) from exc


def request_ml_dataset_build(payload: Any) -> dict[str, Any]:
    if not settings.saas_ml_enabled:
        raise HTTPException(status_code=409, detail={"code": "ml_infrastructure_disabled", "message": "SAAS_ML_ENABLED must be true to build ML datasets."})
    data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload or {})
    task_type = _clean(data.get("task_type"), 120).lower().replace("-", "_") or "lead_scoring"
    url = f"{settings.saas_ml_service_url.rstrip('/')}/datasets/build"
    body = json.dumps(
        {
            "tenant_id": _clean(data.get("tenant_id"), 80),
            "task_type": task_type,
            "dataset_key": _clean(data.get("dataset_key"), 180),
            "version": _clean(data.get("version"), 80),
            "window_key": _clean(data.get("window_key"), 80) or "90d",
            "min_samples": max(5, min(int(data.get("min_samples") or 50), 1000000)),
            "include_global": bool(data.get("include_global", False)),
            "notes": _clean(data.get("notes"), 1000),
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json", "Accept": "application/json"})
    timeout = max(5, min(int(settings.saas_ml_inference_timeout_sec or 3) * 10, 300))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8") or "{}")
        if not isinstance(result, dict):
            result = {}
        if not result.get("ok"):
            raise HTTPException(status_code=502, detail={"code": "ml_dataset_service_failed", "response": result})
        return result
    except HTTPException:
        raise
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail={"code": "ml_dataset_service_unavailable", "message": str(exc)[:500]}) from exc


def request_ml_autolabel_training(payload: Any) -> dict[str, Any]:
    if not settings.saas_ml_enabled:
        raise HTTPException(status_code=409, detail={"code": "ml_infrastructure_disabled", "message": "SAAS_ML_ENABLED must be true to run autolabel training."})
    data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload or {})
    url = f"{settings.saas_ml_service_url.rstrip('/')}/train/autolabel"
    body = json.dumps(
        {
            "tenant_id": _clean(data.get("tenant_id"), 80),
            "task_type": _clean(data.get("task_type"), 120).lower().replace("-", "_") or "lead_scoring",
            "model_key": _clean(data.get("model_key"), 160),
            "framework": _clean(data.get("framework"), 80) or "lightgbm",
            "version": _clean(data.get("version"), 80),
            "dataset_key": _clean(data.get("dataset_key"), 180),
            "window_key": _clean(data.get("window_key"), 80) or "90d",
            "min_samples": max(5, min(int(data.get("min_samples") or 50), 1000000)),
            "include_global": bool(data.get("include_global", False)),
            "seed": max(1, min(int(data.get("seed") or 42), 1000000000)),
            "register_artifact": True,
            "notes": _clean(data.get("notes"), 1000),
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json", "Accept": "application/json"})
    timeout = max(5, min(int(settings.saas_ml_inference_timeout_sec or 3) * 30, 900))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8") or "{}")
        if not isinstance(result, dict):
            result = {}
        if not result.get("ok"):
            raise HTTPException(status_code=502, detail={"code": "ml_autolabel_training_failed", "response": result})
        return result
    except HTTPException:
        raise
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail={"code": "ml_training_service_unavailable", "message": str(exc)[:500]}) from exc


def _select_prediction_model(
    conn: Connection,
    *,
    prediction_type: str,
    default_model_key: str,
    tenant_id: str,
    subject_type: str,
    subject_id: str,
    window_key: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    default_model = _model_registry_row(conn, default_model_key)
    task_models = _model_registry_rows_for_task(conn, prediction_type)
    active_models = [model for model in task_models if _model_can_serve(model)]
    if not active_models:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "intelligence_model_disabled",
                "model_key": default_model_key,
                "status": default_model.get("status") or "unknown",
                "rollout_mode": default_model.get("rollout_mode") or "disabled",
            },
        )

    production_models = [model for model in active_models if str(model.get("rollout_mode") or "") == "production"]
    fallback_model = next((model for model in production_models if model.get("model_key") == default_model_key), None)
    fallback_model = fallback_model or (production_models[0] if production_models else default_model)
    selected_model = fallback_model if _model_can_serve(fallback_model) else active_models[0]
    bucket = _rollout_bucket(tenant_id, prediction_type, subject_type, subject_id or tenant_id, window_key)
    decision = "production"

    canary_models = [model for model in active_models if str(model.get("rollout_mode") or "") == "canary" and int(model.get("traffic_percent") or 0) > 0]
    for candidate in canary_models:
        traffic_percent = max(0, min(int(candidate.get("traffic_percent") or 0), 100))
        if bucket < traffic_percent:
            selected_model = candidate
            decision = "canary_selected"
            break
        decision = "canary_not_selected"

    rollout_mode = str(selected_model.get("rollout_mode") or "production")
    prediction_status = "ready"
    status_reason = ""
    if rollout_mode == "shadow":
        prediction_status = "shadow"
        status_reason = "shadow_rollout"
    elif rollout_mode == "canary":
        if decision == "canary_selected" and _model_can_create_ready_predictions(selected_model):
            prediction_status = "ready"
            status_reason = "canary_traffic_selected"
        else:
            prediction_status = "shadow"
            status_reason = "canary_not_selected" if decision != "canary_selected" else "canary_not_approved"
    elif bool(selected_model.get("shadow_mode")) and rollout_mode != "production":
        prediction_status = "shadow"
        status_reason = "shadow_mode"

    return selected_model, {
        "decision": decision,
        "prediction_status": prediction_status,
        "status_reason": status_reason,
        "bucket": bucket,
        "selected_model_key": selected_model.get("model_key") or default_model_key,
        "default_model_key": default_model_key,
        "fallback_model_key": fallback_model.get("model_key") or default_model_key,
        "rollout_mode": rollout_mode,
        "traffic_percent": int(selected_model.get("traffic_percent") or 100),
        "shadow_mode": bool(selected_model.get("shadow_mode")),
        "promotion_status": selected_model.get("promotion_status") or "approved",
    }


def _model_metric_summary(conn: Connection, model_key: str) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            SELECT COALESCE(SUM(sample_size), 0)::int AS sample_size,
                   COALESCE(SUM(labeled_count), 0)::int AS labeled_count,
                   AVG(accuracy) FILTER (WHERE accuracy IS NOT NULL) AS avg_accuracy,
                   MAX(drift_score) FILTER (WHERE drift_score IS NOT NULL) AS max_drift_score,
                   MAX(computed_at)::text AS last_metric_at,
                   COUNT(*) FILTER (WHERE status = 'healthy')::int AS healthy_metrics,
                   COUNT(*) FILTER (WHERE status IN ('watch','degraded'))::int AS risk_metrics
            FROM saas_intelligence_model_metrics
            WHERE model_key = :model_key
            """
        ),
        {"model_key": _clean(model_key, 160)},
    ).mappings().first() or {}
    summary = dict(row)
    summary["avg_accuracy"] = float(summary["avg_accuracy"]) if summary.get("avg_accuracy") is not None else None
    summary["max_drift_score"] = float(summary["max_drift_score"]) if summary.get("max_drift_score") is not None else None
    return summary


def assess_model_rollout(conn: Connection, model_key: str) -> dict[str, Any]:
    model = _model_registry_row(conn, model_key)
    metrics = _model_metric_summary(conn, model_key)
    reasons: list[str] = []
    ready = True
    if _baseline_model_allowed(model):
        reasons.append("baseline_rules_allowed")
    else:
        labeled_count = int(metrics.get("labeled_count") or 0)
        min_labeled = int(model.get("min_labeled_count") or 10)
        avg_accuracy = metrics.get("avg_accuracy")
        min_accuracy = float(model.get("min_accuracy") or 70)
        max_drift = metrics.get("max_drift_score")
        drift_limit = float(model.get("max_drift_score") or 25)
        if labeled_count < min_labeled:
            ready = False
            reasons.append("insufficient_labeled_feedback")
        if avg_accuracy is None:
            ready = False
            reasons.append("accuracy_unavailable")
        elif float(avg_accuracy) < min_accuracy:
            ready = False
            reasons.append("accuracy_below_threshold")
        if max_drift is not None and float(max_drift) > drift_limit:
            ready = False
            reasons.append("drift_above_threshold")
    if str(model.get("status") or "") != "active":
        ready = False
        reasons.append("model_not_active")
    return {
        "model_key": model["model_key"],
        "ready_for_production": ready,
        "reasons": reasons or ["thresholds_passed"],
        "metrics_summary": metrics,
        "thresholds": {
            "min_labeled_count": int(model.get("min_labeled_count") or 10),
            "min_accuracy": float(model.get("min_accuracy") or 70),
            "max_drift_score": float(model.get("max_drift_score") or 25),
        },
    }


def list_model_registry(conn: Connection, *, model_key: str = "", limit: int = 120) -> list[dict[str, Any]]:
    ensure_intelligence_tables(conn)
    clean_model = _clean(model_key, 160)
    where_sql = "WHERE model_key = :model_key" if clean_model else ""
    rows = conn.execute(
        text(
            f"""
            SELECT model_key, model_type, task_type, framework, version, status, stage,
                   artifact_uri, shadow_mode, rollout_mode, traffic_percent,
                   min_labeled_count, min_accuracy, max_drift_score, promotion_status,
                   COALESCE(approved_by_user_id::text, '') AS approved_by_user_id,
                   approved_at::text, metrics_json, metadata_json, created_at::text, updated_at::text
            FROM saas_intelligence_model_registry
            {where_sql}
            ORDER BY task_type ASC, model_key ASC
            LIMIT :limit
            """
        ),
        {"model_key": clean_model, "limit": max(1, min(int(limit or 120), 300))},
    ).mappings().all()
    items: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["metrics_summary"] = _model_metric_summary(conn, item["model_key"])
        item["assessment"] = assess_model_rollout(conn, item["model_key"])
        items.append(item)
    return items


def _normalize_registry_value(value: str, valid_values: set[str], fallback: str) -> str:
    clean = _clean(value, 40).lower().replace("-", "_")
    return clean if clean in valid_values else fallback


def register_model_registry_entry(conn: Connection, payload: Any, *, actor_user_id: str) -> dict[str, Any]:
    ensure_intelligence_tables(conn)
    data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload or {})
    model_key = _clean(data.get("model_key"), 160).lower().replace("-", "_").replace(" ", "_")
    if not model_key:
        raise HTTPException(status_code=400, detail={"code": "intelligence_model_key_required"})
    task_type = _clean(data.get("task_type"), 120).lower().replace("-", "_")
    if task_type not in VALID_PREDICTION_TASKS:
        raise HTTPException(status_code=400, detail={"code": "unsupported_prediction_task", "task_type": task_type})
    existing = conn.execute(
        text("SELECT model_key FROM saas_intelligence_model_registry WHERE model_key = :model_key LIMIT 1"),
        {"model_key": model_key},
    ).mappings().first()
    if existing:
        raise HTTPException(status_code=409, detail={"code": "intelligence_model_already_exists", "model_key": model_key})

    rollout_mode = _normalize_registry_value(data.get("rollout_mode") or "shadow", VALID_ROLLOUT_MODES, "shadow")
    status = _normalize_registry_value(data.get("status") or "active", VALID_MODEL_STATUSES, "active")
    stage = _normalize_registry_value(data.get("stage") or "shadow", VALID_MODEL_STAGES, "shadow")
    promotion_status = _normalize_registry_value(data.get("promotion_status") or "pending_review", VALID_PROMOTION_STATUSES, "pending_review")
    traffic_percent = max(0, min(int(data.get("traffic_percent", 0) or 0), 100))
    shadow_mode = bool(data.get("shadow_mode", rollout_mode == "shadow"))
    if rollout_mode == "disabled":
        traffic_percent = 0
        shadow_mode = False
        promotion_status = "blocked"
    elif rollout_mode == "shadow":
        traffic_percent = 0
        shadow_mode = True
        stage = "shadow"
        if promotion_status == "approved":
            promotion_status = "pending_review"
    elif rollout_mode == "canary":
        shadow_mode = False
        stage = "staging" if traffic_percent > 0 else "shadow"
        if promotion_status == "draft":
            promotion_status = "pending_review"
    elif rollout_mode == "production":
        traffic_percent = 100
        shadow_mode = False
        stage = "production"

    metadata = _json_object(data.get("metadata_json"))
    metadata = {
        **metadata,
        "registered_from": "scentra_admin",
        "phase": "11",
        "training_state": metadata.get("training_state") or "external_or_pending",
    }
    row = conn.execute(
        text(
            """
            INSERT INTO saas_intelligence_model_registry (
                model_key, model_type, task_type, framework, version, status, stage,
                artifact_uri, shadow_mode, metrics_json, metadata_json, rollout_mode,
                traffic_percent, min_labeled_count, min_accuracy, max_drift_score,
                promotion_status, approved_by_user_id, approved_at, updated_at
            )
            VALUES (
                :model_key, :model_type, :task_type, :framework, :version, :status, :stage,
                :artifact_uri, :shadow_mode, '{}'::jsonb, CAST(:metadata_json AS jsonb),
                :rollout_mode, :traffic_percent, :min_labeled_count, :min_accuracy,
                :max_drift_score, :promotion_status,
                CASE WHEN :promotion_status = 'approved' THEN CAST(NULLIF(:actor_user_id, '') AS uuid) ELSE NULL END,
                CASE WHEN :promotion_status = 'approved' THEN NOW() ELSE NULL END,
                NOW()
            )
            RETURNING model_key, model_type, task_type, framework, version, status, stage,
                      artifact_uri, shadow_mode, rollout_mode, traffic_percent,
                      min_labeled_count, min_accuracy, max_drift_score, promotion_status,
                      COALESCE(approved_by_user_id::text, '') AS approved_by_user_id,
                      approved_at::text, metrics_json, metadata_json, created_at::text, updated_at::text
            """
        ),
        {
            "model_key": model_key,
            "model_type": _clean(data.get("model_type"), 80) or "external",
            "task_type": task_type,
            "framework": _clean(data.get("framework"), 120) or "pending",
            "version": _clean(data.get("version"), 80) or "v1",
            "status": status,
            "stage": stage,
            "artifact_uri": _clean(data.get("artifact_uri"), 1000),
            "shadow_mode": shadow_mode,
            "metadata_json": _json(metadata),
            "rollout_mode": rollout_mode,
            "traffic_percent": traffic_percent,
            "min_labeled_count": max(0, min(int(data.get("min_labeled_count", 10) or 0), 1000000)),
            "min_accuracy": max(0.0, min(float(data.get("min_accuracy", 70) or 0), 100.0)),
            "max_drift_score": max(0.0, min(float(data.get("max_drift_score", 25) or 0), 100.0)),
            "promotion_status": promotion_status,
            "actor_user_id": _clean(actor_user_id, 80),
        },
    ).mappings().first()
    model = dict(row or {})
    conn.execute(
        text(
            """
            INSERT INTO saas_intelligence_model_rollout_events (
                model_key, action, previous_state_json, next_state_json, reason, created_by_user_id
            )
            VALUES (
                :model_key, 'model_registry.create', '{}'::jsonb,
                CAST(:next_state_json AS jsonb), :reason, CAST(NULLIF(:actor_user_id, '') AS uuid)
            )
            """
        ),
        {
            "model_key": model["model_key"],
            "next_state_json": _json(model),
            "reason": _clean(data.get("reason"), 1000) or "Modelo registrado desde Scentra Admin",
            "actor_user_id": _clean(actor_user_id, 80),
        },
    )
    model["metrics_summary"] = _model_metric_summary(conn, model["model_key"])
    model["assessment"] = assess_model_rollout(conn, model["model_key"])
    return model


def update_model_registry_control(conn: Connection, model_key: str, payload: Any, *, actor_user_id: str) -> dict[str, Any]:
    ensure_intelligence_tables(conn)
    data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload or {})
    previous = _model_registry_row(conn, model_key)
    status = _normalize_registry_value(data.get("status") or previous.get("status"), VALID_MODEL_STATUSES, previous.get("status") or "active")
    stage = _normalize_registry_value(data.get("stage") or previous.get("stage"), VALID_MODEL_STAGES, previous.get("stage") or "production")
    rollout_mode = _normalize_registry_value(data.get("rollout_mode") or previous.get("rollout_mode"), VALID_ROLLOUT_MODES, previous.get("rollout_mode") or "production")
    promotion_status = _normalize_registry_value(data.get("promotion_status") or previous.get("promotion_status"), VALID_PROMOTION_STATUSES, previous.get("promotion_status") or "approved")
    traffic_percent = max(0, min(int(data.get("traffic_percent", previous.get("traffic_percent") or 100) or 0), 100))
    min_labeled_count = max(0, min(int(data.get("min_labeled_count", previous.get("min_labeled_count") or 10) or 0), 1000000))
    min_accuracy = max(0.0, min(float(data.get("min_accuracy", previous.get("min_accuracy") or 70) or 0), 100.0))
    max_drift_score = max(0.0, min(float(data.get("max_drift_score", previous.get("max_drift_score") or 25) or 0), 100.0))
    shadow_mode = bool(data.get("shadow_mode", previous.get("shadow_mode") or False))

    if rollout_mode == "disabled":
        traffic_percent = 0
        shadow_mode = False
        promotion_status = "blocked"
    elif rollout_mode == "shadow":
        traffic_percent = 0
        shadow_mode = True
        stage = "shadow"
        if promotion_status == "approved":
            promotion_status = "pending_review"
    elif rollout_mode == "canary":
        shadow_mode = False
        stage = "shadow" if traffic_percent == 0 else "staging"
        if promotion_status == "draft":
            promotion_status = "pending_review"
    elif rollout_mode == "production":
        traffic_percent = 100
        shadow_mode = False
        stage = "production"

    candidate = {
        **previous,
        "status": status,
        "stage": stage,
        "shadow_mode": shadow_mode,
        "rollout_mode": rollout_mode,
        "traffic_percent": traffic_percent,
        "min_labeled_count": min_labeled_count,
        "min_accuracy": min_accuracy,
        "max_drift_score": max_drift_score,
        "promotion_status": promotion_status,
    }
    metrics = _model_metric_summary(conn, model_key)
    if rollout_mode == "production" and not _baseline_model_allowed(previous):
        ready = True
        reasons: list[str] = []
        if int(metrics.get("labeled_count") or 0) < min_labeled_count:
            ready = False
            reasons.append("insufficient_labeled_feedback")
        if metrics.get("avg_accuracy") is None:
            ready = False
            reasons.append("accuracy_unavailable")
        elif float(metrics["avg_accuracy"]) < min_accuracy:
            ready = False
            reasons.append("accuracy_below_threshold")
        if metrics.get("max_drift_score") is not None and float(metrics["max_drift_score"]) > max_drift_score:
            ready = False
            reasons.append("drift_above_threshold")
        if not ready:
            candidate["rollout_mode"] = "shadow"
            candidate["traffic_percent"] = 0
            candidate["shadow_mode"] = True
            candidate["stage"] = "shadow"
            candidate["promotion_status"] = "blocked"
            candidate["metadata_json"] = {**_json_object(previous.get("metadata_json")), "last_rollout_block_reason": reasons}

    next_row = conn.execute(
        text(
            """
            UPDATE saas_intelligence_model_registry
            SET status = :status,
                stage = :stage,
                shadow_mode = :shadow_mode,
                rollout_mode = :rollout_mode,
                traffic_percent = :traffic_percent,
                min_labeled_count = :min_labeled_count,
                min_accuracy = :min_accuracy,
                max_drift_score = :max_drift_score,
                promotion_status = :promotion_status,
                approved_by_user_id = CASE WHEN :promotion_status = 'approved' THEN CAST(NULLIF(:actor_user_id, '') AS uuid) ELSE approved_by_user_id END,
                approved_at = CASE WHEN :promotion_status = 'approved' THEN NOW() ELSE approved_at END,
                metadata_json = CASE
                    WHEN :metadata_json = '' THEN metadata_json
                    ELSE CAST(:metadata_json AS jsonb)
                END,
                updated_at = NOW()
            WHERE model_key = :model_key
            RETURNING model_key, model_type, task_type, framework, version, status, stage,
                      artifact_uri, shadow_mode, rollout_mode, traffic_percent,
                      min_labeled_count, min_accuracy, max_drift_score, promotion_status,
                      COALESCE(approved_by_user_id::text, '') AS approved_by_user_id,
                      approved_at::text, metrics_json, metadata_json, created_at::text, updated_at::text
            """
        ),
        {
            "model_key": previous["model_key"],
            "status": candidate["status"],
            "stage": candidate["stage"],
            "shadow_mode": candidate["shadow_mode"],
            "rollout_mode": candidate["rollout_mode"],
            "traffic_percent": candidate["traffic_percent"],
            "min_labeled_count": candidate["min_labeled_count"],
            "min_accuracy": candidate["min_accuracy"],
            "max_drift_score": candidate["max_drift_score"],
            "promotion_status": candidate["promotion_status"],
            "actor_user_id": _clean(actor_user_id, 80),
            "metadata_json": _json(candidate["metadata_json"]) if "metadata_json" in candidate else "",
        },
    ).mappings().first()
    if not next_row:
        raise HTTPException(status_code=404, detail={"code": "intelligence_model_not_found", "model_key": model_key})
    updated = dict(next_row)
    conn.execute(
        text(
            """
            INSERT INTO saas_intelligence_model_rollout_events (
                model_key, action, previous_state_json, next_state_json, reason, created_by_user_id
            )
            VALUES (
                :model_key, 'model_rollout.update', CAST(:previous_state_json AS jsonb),
                CAST(:next_state_json AS jsonb), :reason, CAST(NULLIF(:actor_user_id, '') AS uuid)
            )
            """
        ),
        {
            "model_key": updated["model_key"],
            "previous_state_json": _json(previous),
            "next_state_json": _json(updated),
            "reason": _clean(data.get("reason"), 1000),
            "actor_user_id": _clean(actor_user_id, 80),
        },
    )
    updated["metrics_summary"] = _model_metric_summary(conn, updated["model_key"])
    updated["assessment"] = assess_model_rollout(conn, updated["model_key"])
    return updated


def _prediction_model_state(conn: Connection, model_key: str) -> dict[str, Any]:
    model = _model_registry_row(conn, model_key)
    status = str(model.get("status") or "active")
    rollout_mode = str(model.get("rollout_mode") or "production")
    if status != "active" or rollout_mode == "disabled":
        raise HTTPException(
            status_code=403,
            detail={"code": "intelligence_model_disabled", "model_key": model_key, "status": status, "rollout_mode": rollout_mode},
        )
    return model


def generate_prediction(
    conn: Connection,
    tenant_id: str,
    *,
    prediction_type: str,
    subject_type: str = "tenant",
    subject_id: str = "",
    window_key: str = "latest",
    persist_recommendations: bool = True,
) -> dict[str, Any]:
    clean_prediction = _clean(prediction_type, 120).lower().replace("-", "_")
    if clean_prediction not in PREDICTION_FEATURE_MAP:
        raise HTTPException(status_code=400, detail={"code": "unsupported_prediction_type", "prediction_type": clean_prediction})
    feature_key = PREDICTION_FEATURE_MAP[clean_prediction]
    access = resolve_intelligence_access(conn, tenant_id, feature_key, allow_demo=True)
    record_intelligence_usage(conn, tenant_id, feature_key, metadata={"prediction_type": clean_prediction})
    snapshot = recompute_feature_snapshot(conn, tenant_id, subject_type=subject_type, subject_id=subject_id, window_key=window_key)
    payload = _prediction_payload(clean_prediction, snapshot["features"])
    model_state, rollout_decision = _select_prediction_model(
        conn,
        prediction_type=clean_prediction,
        default_model_key=payload["model_key"],
        tenant_id=tenant_id,
        subject_type=subject_type,
        subject_id=subject_id or tenant_id,
        window_key=window_key,
    )
    _prediction_model_state(conn, str(model_state.get("model_key") or payload["model_key"]))
    payload["model_key"] = str(model_state.get("model_key") or payload["model_key"])
    rollout_mode = str(model_state.get("rollout_mode") or "production")
    prediction_status = str(rollout_decision.get("prediction_status") or "ready")
    scoring_engine = "baseline_rules"
    ml_inference: dict[str, Any] = {
        "enabled": bool(settings.saas_ml_enabled),
        "attempted": False,
        "ok": False,
        "fallback_used": False,
    }
    model_type = str(model_state.get("model_type") or "rules")
    can_attempt_ml = (
        bool(settings.saas_ml_enabled)
        and model_type != "rules"
        and bool(model_state.get("artifact_uri"))
        and (prediction_status == "ready" or bool(settings.saas_ml_shadow_inference_enabled))
    )
    if can_attempt_ml:
        ml_result = _call_ml_service_prediction(
            tenant_id=tenant_id,
            prediction_type=clean_prediction,
            model_key=payload["model_key"],
            model_version=_clean(model_state.get("version"), 80) or "v1",
            subject_type=_clean(subject_type, 80) or "tenant",
            subject_id=_clean(subject_id, 160) or tenant_id,
            mode=prediction_status,
            features=snapshot["features"],
        )
        ml_prediction = ml_result.get("prediction") or {}
        ml_inference = {
            "enabled": True,
            "attempted": True,
            "ok": bool(ml_result.get("ok")),
            "latency_ms": int(ml_result.get("latency_ms") or 0),
            "fallback_used": not bool(ml_result.get("ok")) or prediction_status != "ready",
            "error": ml_result.get("error") or "",
            "shadow_prediction": ml_prediction if prediction_status != "ready" else {},
        }
        if ml_result.get("ok") and prediction_status == "ready":
            payload["score"] = float(ml_prediction.get("score") or payload["score"])
            payload["label"] = _clean(ml_prediction.get("label"), 80) or payload["label"]
            payload["confidence"] = float(ml_prediction.get("confidence") or payload["confidence"])
            payload["explanation"] = {
                **payload["explanation"],
                "ml_model_key": ml_prediction.get("model_key") or payload["model_key"],
                "ml_version": ml_prediction.get("version") or model_state.get("version") or "v1",
                "ml_metadata": ml_prediction.get("metadata") or {},
            }
            payload["output"] = {**payload["output"], "ml_prediction": ml_prediction}
            scoring_engine = "ml_service"
        elif ml_result.get("ok"):
            scoring_engine = "baseline_rules+ml_shadow"
        else:
            scoring_engine = "baseline_rules_fallback"
    if not ml_inference.get("attempted") and bool(settings.saas_ml_enabled) and bool(settings.saas_ml_shadow_inference_enabled):
        shadow_model = _shadow_model_candidate(conn, clean_prediction, excluded_model_key=payload["model_key"])
        if shadow_model:
            ml_result = _call_ml_service_prediction(
                tenant_id=tenant_id,
                prediction_type=clean_prediction,
                model_key=str(shadow_model.get("model_key") or ""),
                model_version=_clean(shadow_model.get("version"), 80) or "v1",
                subject_type=_clean(subject_type, 80) or "tenant",
                subject_id=_clean(subject_id, 160) or tenant_id,
                mode="shadow",
                features=snapshot["features"],
            )
            shadow_prediction = ml_result.get("prediction") or {}
            ml_inference = {
                "enabled": True,
                "attempted": True,
                "ok": bool(ml_result.get("ok")),
                "latency_ms": int(ml_result.get("latency_ms") or 0),
                "fallback_used": False,
                "error": ml_result.get("error") or "",
                "shadow_model_key": shadow_model.get("model_key") or "",
                "shadow_model_version": shadow_model.get("version") or "v1",
                "shadow_prediction": shadow_prediction,
            }
            if ml_result.get("ok"):
                scoring_engine = "baseline_rules+ml_shadow"
    recommendation_gate: dict[str, Any] = {
        "requested": bool(persist_recommendations),
        "enabled": False,
        "created": False,
    }
    if persist_recommendations and prediction_status == "ready":
        try:
            recommendation_access = resolve_intelligence_access(conn, tenant_id, "predictive_recommendations", allow_demo=True)
            recommendation_gate.update(
                {
                    "enabled": True,
                    "mode": recommendation_access.get("mode") or "demo",
                    "quota_monthly": int(recommendation_access.get("quota_monthly") or 0),
                    "quota_used": int(recommendation_access.get("quota_used") or 0),
                }
            )
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {"code": str(exc.detail or "recommendation_feature_blocked")}
            recommendation_gate.update({"reason": detail.get("code") or "recommendation_feature_blocked"})
    elif persist_recommendations and prediction_status != "ready":
        recommendation_gate.update({"reason": "prediction_not_ready_for_recommendation"})
    if access.get("mode") == "demo":
        payload["output"] = {**payload["output"], "demo_limited": True, "limit_note": "Activa modo full para predicciones completas, automatizacion y historico profundo."}
    payload["output"] = {
        **payload["output"],
        "model_rollout": {
            "scoring_engine": scoring_engine,
            "selected_model_type": model_type,
            "selected_model_version": model_state.get("version") or "v1",
            "rollout_mode": rollout_mode,
            "traffic_percent": int(model_state.get("traffic_percent") or 100),
            "shadow_mode": bool(model_state.get("shadow_mode")),
            "promotion_status": model_state.get("promotion_status") or "approved",
            "decision": rollout_decision,
        },
        "ml_inference": ml_inference,
        "recommendation_gate": recommendation_gate,
    }
    row = conn.execute(
        text(
            """
            INSERT INTO saas_intelligence_predictions (
                tenant_id, subject_type, subject_id, prediction_type, model_key, model_version,
                mode, score, label, confidence, status, explanation_json, features_json, output_json
            )
            VALUES (
                CAST(:tenant_id AS uuid), :subject_type, :subject_id, :prediction_type, :model_key, :model_version,
                :mode, :score, :label, :confidence, :status, CAST(:explanation_json AS jsonb),
                CAST(:features_json AS jsonb), CAST(:output_json AS jsonb)
            )
            RETURNING id::text, tenant_id::text, subject_type, subject_id, prediction_type, model_key,
                      model_version, mode, score, label, confidence, explanation_json, features_json,
                      output_json, status, created_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "subject_type": _clean(subject_type, 80) or "tenant",
            "subject_id": _clean(subject_id, 160) or tenant_id,
            "prediction_type": clean_prediction,
            "model_key": payload["model_key"],
            "model_version": _clean(model_state.get("version"), 80) or "v1",
            "mode": access.get("mode") or "demo",
            "score": float(payload["score"]),
            "label": payload["label"],
            "confidence": float(payload["confidence"]),
            "status": prediction_status,
            "explanation_json": _json(payload["explanation"]),
            "features_json": _json(snapshot["features"]),
            "output_json": _json(payload["output"]),
        },
    ).mappings().first()
    prediction = dict(row or {})
    if persist_recommendations and prediction_status == "ready" and recommendation_gate.get("enabled"):
        try:
            record_intelligence_usage(
                conn,
                tenant_id,
                "predictive_recommendations",
                metadata={"prediction_id": prediction.get("id", ""), "prediction_type": clean_prediction},
            )
            recommendation = upsert_recommendation_from_prediction(conn, tenant_id, prediction)
            recommendation_gate.update({"created": True, "recommendation_id": recommendation.get("id", "")})
            prediction["output_json"] = {**_json_object(prediction.get("output_json")), "recommendation_gate": recommendation_gate}
            conn.execute(
                text(
                    """
                    UPDATE saas_intelligence_predictions
                    SET output_json = CAST(:output_json AS jsonb)
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND id = CAST(:prediction_id AS uuid)
                    """
                ),
                {"tenant_id": tenant_id, "prediction_id": prediction.get("id", ""), "output_json": _json(prediction["output_json"])},
            )
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {"code": str(exc.detail or "recommendation_feature_blocked")}
            recommendation_gate.update({"created": False, "reason": detail.get("code") or "recommendation_feature_blocked"})
            prediction["output_json"] = {**_json_object(prediction.get("output_json")), "recommendation_gate": recommendation_gate}
            conn.execute(
                text(
                    """
                    UPDATE saas_intelligence_predictions
                    SET output_json = CAST(:output_json AS jsonb)
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND id = CAST(:prediction_id AS uuid)
                    """
                ),
                {"tenant_id": tenant_id, "prediction_id": prediction.get("id", ""), "output_json": _json(prediction["output_json"])},
            )
    record_event(
        conn,
        tenant_id,
        {
            "event_type": "ai.prediction.generated",
            "source": "intelligence_engine",
            "entity_type": "prediction",
            "entity_id": prediction.get("id", ""),
            "payload_json": {
                "prediction_type": clean_prediction,
                "mode": access.get("mode"),
                "status": prediction_status,
                "rollout_mode": rollout_mode,
                "model_key": payload["model_key"],
                "scoring_engine": scoring_engine,
                "ml_inference": ml_inference,
                "rollout_decision": rollout_decision,
                "score": float(payload["score"]),
            },
            "replay_key": f"prediction:{prediction.get('id', '')}",
        },
    )
    return prediction


def upsert_recommendation_from_prediction(conn: Connection, tenant_id: str, prediction: dict[str, Any]) -> dict[str, Any]:
    prediction_type = _clean(prediction.get("prediction_type"), 120)
    score = float(prediction.get("score") or 0)
    output = _json_object(prediction.get("output_json"))
    label = _clean(prediction.get("label"), 80)
    templates = {
        "lead_scoring": ("Priorizar leads calientes", "Hay leads con alta probabilidad comercial. Revisa conversaciones hot y asigna seguimiento humano.", "high" if score >= 70 else "info"),
        "churn_prediction": ("Reactivar clientes en riesgo", "El modelo detecto inactividad relevante. Crea segmento de reactivacion antes de perder oportunidad.", "high" if score >= 70 else "warn"),
        "smart_remarketing": ("Optimizar remarketing", "Ajusta canal, horario y frecuencia segun la oportunidad detectada.", "warn" if score >= 40 else "info"),
        "operational_anomaly": ("Revisar salud operativa", "Hay senales de fallos en colas, webhooks, AI Gateway o outbound.", "high" if score >= 70 else "warn"),
    }
    title, description, severity = templates.get(prediction_type, ("Recomendacion predictiva", "Revisa la prediccion generada por Intelligence Engine.", "info"))
    existing = conn.execute(
        text(
            """
            SELECT id::text
            FROM saas_intelligence_recommendations
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND recommendation_type = :recommendation_type
              AND status = 'open'
            ORDER BY updated_at DESC
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "recommendation_type": prediction_type},
    ).mappings().first()
    params = {
        "tenant_id": tenant_id,
        "recommendation_type": prediction_type,
        "source_prediction_id": prediction.get("id") or "",
        "title": title,
        "description": description,
        "severity": severity,
        "confidence": float(prediction.get("confidence") or 0),
        "action_json": _json({"label": label, **output}),
        "evidence_json": _json({"score": score, "prediction": prediction}),
    }
    if existing:
        row = conn.execute(
            text(
                """
                UPDATE saas_intelligence_recommendations
                SET source_prediction_id = CAST(NULLIF(:source_prediction_id, '') AS uuid),
                    title = :title,
                    description = :description,
                    severity = :severity,
                    confidence = :confidence,
                    action_json = CAST(:action_json AS jsonb),
                    evidence_json = CAST(:evidence_json AS jsonb),
                    updated_at = NOW()
                WHERE id = CAST(:id AS uuid)
                RETURNING id::text, recommendation_type, title, description, severity, confidence,
                          action_json, evidence_json, status, updated_at::text
                """
            ),
            {**params, "id": existing["id"]},
        ).mappings().first()
    else:
        row = conn.execute(
            text(
                """
                INSERT INTO saas_intelligence_recommendations (
                    tenant_id, recommendation_type, source_prediction_id, title, description,
                    severity, confidence, action_json, evidence_json
                )
                VALUES (
                    CAST(:tenant_id AS uuid), :recommendation_type,
                    CAST(NULLIF(:source_prediction_id, '') AS uuid), :title, :description,
                    :severity, :confidence, CAST(:action_json AS jsonb), CAST(:evidence_json AS jsonb)
                )
                RETURNING id::text, recommendation_type, title, description, severity, confidence,
                          action_json, evidence_json, status, updated_at::text
                """
            ),
            params,
        ).mappings().first()
    recommendation = dict(row or {})
    record_event(
        conn,
        tenant_id,
        {
            "event_type": "ai.recommendation.generated",
            "source": "intelligence_engine",
            "entity_type": "recommendation",
            "entity_id": recommendation.get("id", ""),
            "payload_json": {"recommendation_type": prediction_type, "severity": severity, "score": score},
            "replay_key": f"recommendation:{recommendation.get('id', '')}",
        },
    )
    return recommendation


def list_predictions(conn: Connection, tenant_id: str, *, prediction_type: str = "", limit: int = 50) -> list[dict[str, Any]]:
    ensure_intelligence_tables(conn)
    where = ["tenant_id = CAST(:tenant_id AS uuid)"]
    params: dict[str, Any] = {"tenant_id": tenant_id, "limit": max(1, min(int(limit or 50), 200))}
    if prediction_type:
        where.append("prediction_type = :prediction_type")
        params["prediction_type"] = _clean(prediction_type, 120).lower().replace("-", "_")
    rows = conn.execute(
        text(
            f"""
            SELECT id::text, subject_type, subject_id, prediction_type, model_key, model_version,
                   mode, score, label, confidence, status, explanation_json, features_json,
                   output_json, created_at::text
            FROM saas_intelligence_predictions
            WHERE {" AND ".join(where)}
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()
    return [dict(row) for row in rows]


def _window_days(window_key: str) -> int:
    clean = _clean(window_key, 40).lower()
    if clean.endswith("d"):
        clean = clean[:-1]
    try:
        return max(1, min(int(clean or 90), 365))
    except ValueError:
        return 90


def _metric_status(labeled_count: int, accuracy: float | None, drift_score: float | None) -> str:
    if labeled_count <= 0:
        return "needs_feedback"
    if labeled_count < 10:
        return "insufficient_data"
    if accuracy is None:
        return "needs_feedback"
    if accuracy >= 70 and float(drift_score or 0) <= 25:
        return "healthy"
    if accuracy >= 50:
        return "watch"
    return "degraded"


def record_prediction_feedback(conn: Connection, tenant_id: str, prediction_id: str, payload: Any, *, actor_user_id: str) -> dict[str, Any]:
    ensure_intelligence_tables(conn)
    data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload or {})
    prediction = conn.execute(
        text(
            """
            SELECT id::text, prediction_type, model_key
            FROM saas_intelligence_predictions
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:prediction_id AS uuid)
            """
        ),
        {"tenant_id": tenant_id, "prediction_id": prediction_id},
    ).mappings().first()
    if not prediction:
        raise HTTPException(status_code=404, detail="prediction_not_found")
    feedback_type = _clean(data.get("feedback_type"), 80).lower().replace("-", "_") or "outcome"
    row = conn.execute(
        text(
            """
            INSERT INTO saas_intelligence_prediction_feedback (
                tenant_id, prediction_id, feedback_type, actual_label, actual_score,
                is_correct, outcome_json, notes, created_by_user_id, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), CAST(:prediction_id AS uuid), :feedback_type,
                :actual_label, :actual_score, :is_correct, CAST(:outcome_json AS jsonb),
                :notes, CAST(NULLIF(:actor_user_id, '') AS uuid), NOW()
            )
            ON CONFLICT (tenant_id, prediction_id, feedback_type)
            DO UPDATE SET
                actual_label = EXCLUDED.actual_label,
                actual_score = EXCLUDED.actual_score,
                is_correct = EXCLUDED.is_correct,
                outcome_json = EXCLUDED.outcome_json,
                notes = EXCLUDED.notes,
                created_by_user_id = EXCLUDED.created_by_user_id,
                updated_at = NOW()
            RETURNING id::text, prediction_id::text, feedback_type, actual_label,
                      actual_score, is_correct, outcome_json, notes,
                      COALESCE(created_by_user_id::text, '') AS created_by_user_id,
                      created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "prediction_id": prediction_id,
            "feedback_type": feedback_type,
            "actual_label": _clean(data.get("actual_label"), 120),
            "actual_score": data.get("actual_score"),
            "is_correct": data.get("is_correct"),
            "outcome_json": _json(data.get("outcome_json") or {}),
            "notes": _clean(data.get("notes"), 1000),
            "actor_user_id": _clean(actor_user_id, 80),
        },
    ).mappings().first()
    record_event(
        conn,
        tenant_id,
        {
            "event_type": "ai.prediction.feedback_recorded",
            "source": "intelligence_engine",
            "entity_type": "prediction",
            "entity_id": prediction_id,
            "payload_json": {
                "prediction_type": prediction["prediction_type"],
                "model_key": prediction["model_key"],
                "feedback_type": feedback_type,
                "is_correct": data.get("is_correct"),
            },
            "replay_key": f"prediction_feedback:{prediction_id}:{feedback_type}",
        },
    )
    metrics = recompute_model_metrics(
        conn,
        tenant_id=tenant_id,
        model_key=str(prediction["model_key"] or ""),
        prediction_type=str(prediction["prediction_type"] or ""),
    )
    return {"feedback": dict(row or {}), "metrics": metrics}


def list_prediction_feedback(conn: Connection, tenant_id: str, *, prediction_id: str = "", limit: int = 100) -> list[dict[str, Any]]:
    ensure_intelligence_tables(conn)
    where = ["f.tenant_id = CAST(:tenant_id AS uuid)"]
    params: dict[str, Any] = {"tenant_id": tenant_id, "limit": max(1, min(int(limit or 100), 300))}
    if prediction_id:
        where.append("f.prediction_id = CAST(:prediction_id AS uuid)")
        params["prediction_id"] = prediction_id
    rows = conn.execute(
        text(
            f"""
            SELECT f.id::text, f.prediction_id::text, f.feedback_type, f.actual_label,
                   f.actual_score, f.is_correct, f.outcome_json, f.notes,
                   COALESCE(f.created_by_user_id::text, '') AS created_by_user_id,
                   f.created_at::text, f.updated_at::text,
                   p.prediction_type, p.model_key, p.score, p.label
            FROM saas_intelligence_prediction_feedback f
            JOIN saas_intelligence_predictions p ON p.id = f.prediction_id AND p.tenant_id = f.tenant_id
            WHERE {" AND ".join(where)}
            ORDER BY f.updated_at DESC
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()
    return [dict(row) for row in rows]


def _pg_table_exists(conn: Connection, table_name: str) -> bool:
    return bool(conn.execute(text("SELECT to_regclass(:table_name)"), {"table_name": table_name}).scalar())


def _task_list(prediction_type: str = "") -> list[str]:
    clean = _clean(prediction_type, 120).lower().replace("-", "_")
    valid_tasks = {str(item.get("prediction_type") or "") for item in FEATURE_SET_DEFINITIONS.values()}
    if clean:
        if clean not in valid_tasks:
            raise HTTPException(status_code=400, detail={"code": "unsupported_prediction_task", "prediction_type": clean})
        return [clean]
    return ["lead_scoring", "churn_prediction", "smart_remarketing", "operational_anomaly"]


def _upsert_auto_label(
    conn: Connection,
    *,
    tenant_id: str,
    prediction_type: str,
    subject_type: str,
    subject_id: str,
    label_key: str,
    label_value: bool,
    label_text: str,
    label_confidence: float,
    evidence: dict[str, Any],
    window_key: str,
    replay_key: str,
) -> None:
    conn.execute(
        text(
            """
            INSERT INTO saas_ml_auto_labels (
                tenant_id, prediction_type, subject_type, subject_id, label_key,
                label_value, label_text, label_confidence, evidence_json,
                window_key, generated_by, generated_at, replay_key, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), :prediction_type, :subject_type, :subject_id,
                :label_key, :label_value, :label_text, :label_confidence,
                CAST(:evidence_json AS jsonb), :window_key, 'auto_labeler_v1',
                NOW(), :replay_key, NOW()
            )
            ON CONFLICT (tenant_id, prediction_type, subject_type, subject_id, label_key, window_key)
            DO UPDATE SET
                label_value = EXCLUDED.label_value,
                label_text = EXCLUDED.label_text,
                label_confidence = EXCLUDED.label_confidence,
                evidence_json = EXCLUDED.evidence_json,
                generated_at = NOW(),
                replay_key = EXCLUDED.replay_key,
                updated_at = NOW()
            """
        ),
        {
            "tenant_id": tenant_id,
            "prediction_type": prediction_type,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "label_key": label_key,
            "label_value": bool(label_value),
            "label_text": _clean(label_text, 160),
            "label_confidence": max(0.0, min(float(label_confidence or 0), 1.0)),
            "evidence_json": _json(evidence),
            "window_key": _clean(window_key, 80) or "90d",
            "replay_key": _clean(replay_key, 240),
        },
    )


def _conversion_condition_sql() -> str:
    return """
    (
        LOWER(COALESCE(payment_status, '')) IN ('paid', 'pagado', 'approved', 'aprobado', 'completed', 'success', 'succeeded')
        OR LOWER(COALESCE(crm_stage, '')) IN ('won', 'closed_won', 'converted', 'conversion', 'customer', 'cliente', 'comprado', 'venta', 'ganado')
    )
    """


def _generate_lead_labels(conn: Connection, tenant_id: str, *, window_key: str, limit: int) -> int:
    rows = conn.execute(
        text(
            f"""
            SELECT id::text AS subject_id, crm_stage, payment_status, lead_score,
                   lead_temperature, created_at::text, last_message_at::text,
                   CASE WHEN {_conversion_condition_sql()} THEN TRUE ELSE FALSE END AS label_value,
                   CASE WHEN {_conversion_condition_sql()} THEN 0.92 ELSE 0.66 END AS confidence
            FROM saas_conversations
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND (
                    {_conversion_condition_sql()}
                    OR (
                        created_at < NOW() - INTERVAL '30 days'
                        AND COALESCE(last_message_at, created_at) < NOW() - INTERVAL '30 days'
                    )
              )
            ORDER BY updated_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "limit": limit},
    ).mappings().all()
    count = 0
    for row in rows:
        label_value = bool(row.get("label_value"))
        subject_id = str(row.get("subject_id") or "")
        _upsert_auto_label(
            conn,
            tenant_id=tenant_id,
            prediction_type="lead_scoring",
            subject_type="conversation",
            subject_id=subject_id,
            label_key="conversion_30d",
            label_value=label_value,
            label_text="converted" if label_value else "not_converted_inactive_30d",
            label_confidence=float(row.get("confidence") or 0.66),
            evidence={
                "crm_stage": row.get("crm_stage") or "",
                "payment_status": row.get("payment_status") or "",
                "lead_score": row.get("lead_score") or 0,
                "lead_temperature": row.get("lead_temperature") or "",
                "policy": "crm_stage_or_payment_status_positive_else_inactive_30d_negative",
            },
            window_key=window_key,
            replay_key=f"auto_label:lead_scoring:{subject_id}:{window_key}",
        )
        count += 1
    return count


def _generate_churn_labels(conn: Connection, tenant_id: str, *, window_key: str, limit: int) -> int:
    rows = conn.execute(
        text(
            """
            SELECT id::text AS subject_id,
                   created_at::text,
                   last_message_at::text,
                   COALESCE(EXTRACT(EPOCH FROM (NOW() - COALESCE(last_message_at, created_at))) / 86400, 999)::numeric(10,2) AS inactivity_days,
                   CASE
                       WHEN created_at < NOW() - INTERVAL '45 days'
                        AND COALESCE(last_message_at, created_at) < NOW() - INTERVAL '45 days'
                       THEN TRUE
                       WHEN COALESCE(last_message_at, created_at) >= NOW() - INTERVAL '7 days'
                       THEN FALSE
                       ELSE NULL
                   END AS label_value
            FROM saas_conversations
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND (
                  (created_at < NOW() - INTERVAL '45 days' AND COALESCE(last_message_at, created_at) < NOW() - INTERVAL '45 days')
                  OR COALESCE(last_message_at, created_at) >= NOW() - INTERVAL '7 days'
              )
            ORDER BY updated_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "limit": limit},
    ).mappings().all()
    count = 0
    for row in rows:
        if row.get("label_value") is None:
            continue
        label_value = bool(row.get("label_value"))
        subject_id = str(row.get("subject_id") or "")
        _upsert_auto_label(
            conn,
            tenant_id=tenant_id,
            prediction_type="churn_prediction",
            subject_type="conversation",
            subject_id=subject_id,
            label_key="inactive_45_days",
            label_value=label_value,
            label_text="high_churn_risk" if label_value else "recently_active",
            label_confidence=0.86 if label_value else 0.72,
            evidence={"inactivity_days": float(row.get("inactivity_days") or 0), "policy": "inactive_45_days_positive_recent_7_days_negative"},
            window_key=window_key,
            replay_key=f"auto_label:churn_prediction:{subject_id}:{window_key}",
        )
        count += 1
    return count


def _generate_remarketing_labels(conn: Connection, tenant_id: str, *, window_key: str, limit: int) -> int:
    rows = conn.execute(
        text(
            """
            WITH signals AS (
                SELECT tenant_id, conversation_id::text AS subject_id,
                       COUNT(*) FILTER (WHERE status IN ('read', 'replied', 'delivered'))::int AS positive_count,
                       COUNT(*) FILTER (WHERE status = 'failed')::int AS negative_count,
                       COUNT(*)::int AS total_count
                FROM saas_broadcast_recipients
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND created_at >= NOW() - (:window_days * INTERVAL '1 day')
                GROUP BY tenant_id, conversation_id
                UNION ALL
                SELECT tenant_id, conversation_id::text AS subject_id,
                       COUNT(*) FILTER (WHERE outcome IN ('clicked', 'replied', 'converted', 'purchased', 'success'))::int AS positive_count,
                       COUNT(*) FILTER (WHERE outcome = 'failed')::int AS negative_count,
                       COUNT(*)::int AS total_count
                FROM saas_campaign_ab_events
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND conversation_id IS NOT NULL
                  AND created_at >= NOW() - (:window_days * INTERVAL '1 day')
                GROUP BY tenant_id, conversation_id
            ),
            grouped AS (
                SELECT subject_id,
                       SUM(positive_count)::int AS positive_count,
                       SUM(negative_count)::int AS negative_count,
                       SUM(total_count)::int AS total_count
                FROM signals
                WHERE COALESCE(subject_id, '') <> ''
                GROUP BY subject_id
            )
            SELECT subject_id, positive_count, negative_count, total_count,
                   CASE WHEN positive_count > 0 THEN TRUE ELSE FALSE END AS label_value
            FROM grouped
            WHERE positive_count > 0 OR negative_count > 0
            ORDER BY positive_count DESC, total_count DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "window_days": _window_days(window_key), "limit": limit},
    ).mappings().all()
    count = 0
    for row in rows:
        label_value = bool(row.get("label_value"))
        subject_id = str(row.get("subject_id") or "")
        _upsert_auto_label(
            conn,
            tenant_id=tenant_id,
            prediction_type="smart_remarketing",
            subject_type="conversation",
            subject_id=subject_id,
            label_key="campaign_success",
            label_value=label_value,
            label_text="campaign_engaged" if label_value else "campaign_failed_or_no_engagement",
            label_confidence=0.8 if label_value else 0.68,
            evidence={
                "positive_count": int(row.get("positive_count") or 0),
                "negative_count": int(row.get("negative_count") or 0),
                "total_count": int(row.get("total_count") or 0),
                "policy": "broadcast_or_campaign_engagement",
            },
            window_key=window_key,
            replay_key=f"auto_label:smart_remarketing:{subject_id}:{window_key}",
        )
        count += 1
    return count


def _generate_operational_labels(conn: Connection, tenant_id: str, *, window_key: str) -> int:
    row = conn.execute(
        text(
            """
            SELECT COUNT(*) FILTER (
                       WHERE event_type IN ('webhook.failed', 'message.failed', 'ai.run.failed', 'trigger.failed', 'campaign.failed')
                   )::int AS failures,
                   COUNT(*)::int AS total_events
            FROM saas_intelligence_events
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND occurred_at >= NOW() - INTERVAL '24 hours'
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first() or {}
    total = int(row.get("total_events") or 0)
    if total <= 0:
        return 0
    failures = int(row.get("failures") or 0)
    label_value = failures >= 3 or (failures / max(1, total)) >= 0.2
    _upsert_auto_label(
        conn,
        tenant_id=tenant_id,
        prediction_type="operational_anomaly",
        subject_type="tenant",
        subject_id=tenant_id,
        label_key="degraded_24h",
        label_value=label_value,
        label_text="degraded" if label_value else "normal",
        label_confidence=0.82 if label_value else 0.7,
        evidence={"failures_24h": failures, "total_events_24h": total, "policy": "failure_count_or_ratio"},
        window_key=window_key,
        replay_key=f"auto_label:operational_anomaly:{tenant_id}:{window_key}",
    )
    return 1


def generate_auto_labels(
    conn: Connection,
    *,
    tenant_id: str = "",
    prediction_type: str = "",
    window_key: str = "90d",
    limit: int = 1000,
) -> dict[str, Any]:
    ensure_intelligence_tables(conn)
    clean_tenant_id = _clean(tenant_id, 80)
    clean_window = _clean(window_key, 80) or "90d"
    capped_limit = max(1, min(int(limit or 1000), 25000))
    tenant_rows = conn.execute(
        text(
            """
            SELECT id::text
            FROM saas_tenants
            WHERE status IN ('active', 'trial')
              AND (CAST(NULLIF(:tenant_id, '') AS uuid) IS NULL OR id = CAST(NULLIF(:tenant_id, '') AS uuid))
            ORDER BY updated_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": clean_tenant_id, "limit": 500 if not clean_tenant_id else 1},
    ).mappings().all()
    tasks = _task_list(prediction_type)
    totals = {task: 0 for task in tasks}
    for tenant in tenant_rows:
        tid = str(tenant.get("id") or "")
        if not tid:
            continue
        if "lead_scoring" in tasks:
            totals["lead_scoring"] += _generate_lead_labels(conn, tid, window_key=clean_window, limit=capped_limit)
        if "churn_prediction" in tasks:
            totals["churn_prediction"] += _generate_churn_labels(conn, tid, window_key=clean_window, limit=capped_limit)
        if "smart_remarketing" in tasks:
            totals["smart_remarketing"] += _generate_remarketing_labels(conn, tid, window_key=clean_window, limit=capped_limit)
        if "operational_anomaly" in tasks:
            totals["operational_anomaly"] += _generate_operational_labels(conn, tid, window_key=clean_window)
    return {
        "tenant_id": clean_tenant_id,
        "window_key": clean_window,
        "tasks": tasks,
        "tenants": len(tenant_rows),
        "labels_generated": totals,
        "total": sum(totals.values()),
        "label_policy": "auto_label_v1",
        "raw_content_used": False,
    }


def _conversation_subjects(conn: Connection, tenant_id: str, *, window_key: str, limit: int) -> list[str]:
    rows = conn.execute(
        text(
            """
            SELECT id::text
            FROM saas_conversations
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND (
                  updated_at >= NOW() - (:window_days * INTERVAL '1 day')
                  OR COALESCE(last_message_at, created_at) >= NOW() - (:window_days * INTERVAL '1 day')
                  OR created_at >= NOW() - (:window_days * INTERVAL '1 day')
              )
            ORDER BY updated_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "window_days": _window_days(window_key), "limit": limit},
    ).mappings().all()
    return [str(row.get("id") or "") for row in rows if row.get("id")]


def _run_feature_pipeline_for_tenant(
    conn: Connection,
    tenant_id: str,
    *,
    prediction_type: str,
    window_key: str,
    limit: int,
) -> dict[str, Any]:
    feature_set_key = f"{prediction_type}_v1"
    feature_set = FEATURE_SET_DEFINITIONS.get(feature_set_key) or {}
    feature_keys = list(feature_set.get("feature_keys") or [])
    subjects_processed = 0
    features_written = 0
    if prediction_type == "operational_anomaly":
        snapshot = recompute_feature_snapshot(conn, tenant_id, subject_type="tenant", subject_id=tenant_id, window_key=window_key)
        event_row = conn.execute(
            text(
                """
                SELECT COUNT(*) FILTER (
                           WHERE event_type IN ('webhook.failed', 'message.failed', 'ai.run.failed', 'trigger.failed', 'campaign.failed')
                       )::int AS failures,
                       COUNT(*)::int AS total_events
                FROM saas_intelligence_events
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND occurred_at >= NOW() - INTERVAL '24 hours'
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().first() or {}
        features = dict(snapshot.get("features") or {})
        total_events = max(1, int(event_row.get("total_events") or 0))
        features["event_failure_rate"] = float(event_row.get("failures") or 0) / total_events * 100.0
        for key in feature_keys:
            value = float(features.get(key) or 0)
            _upsert_feature(
                conn,
                tenant_id,
                subject_type="tenant",
                subject_id=tenant_id,
                window_key=window_key,
                feature_key=key,
                value_numeric=value,
                value_json={"value": value},
                source="ml_feature_pipeline",
                feature_set_key=feature_set_key,
                feature_version=str(feature_set.get("version") or "v1"),
                quality_json={"window_key": window_key, "raw_content_used": False},
            )
            features_written += 1
        return {"subjects_processed": 1, "features_written": features_written}

    for subject_id in _conversation_subjects(conn, tenant_id, window_key=window_key, limit=limit):
        snapshot = _conversation_feature_snapshot(conn, tenant_id, subject_id, window_key=window_key)
        features = dict(snapshot.get("features") or {})
        for key in feature_keys:
            value = float(features.get(key) or 0)
            _upsert_feature(
                conn,
                tenant_id,
                subject_type="conversation",
                subject_id=subject_id,
                window_key=window_key,
                feature_key=key,
                value_numeric=value,
                value_json={"value": value},
                source="ml_feature_pipeline",
                feature_set_key=feature_set_key,
                feature_version=str(feature_set.get("version") or "v1"),
                quality_json={"window_key": window_key, "raw_content_used": False},
            )
            features_written += 1
        subjects_processed += 1
    return {"subjects_processed": subjects_processed, "features_written": features_written}


def recompute_training_feature_pipelines(
    conn: Connection,
    *,
    tenant_id: str = "",
    prediction_type: str = "",
    window_key: str = "90d",
    limit: int = 1000,
) -> dict[str, Any]:
    ensure_intelligence_tables(conn)
    clean_tenant_id = _clean(tenant_id, 80)
    clean_window = _clean(window_key, 80) or "90d"
    capped_limit = max(1, min(int(limit or 1000), 25000))
    tasks = _task_list(prediction_type)
    tenants = conn.execute(
        text(
            """
            SELECT id::text
            FROM saas_tenants
            WHERE status IN ('active', 'trial')
              AND (CAST(NULLIF(:tenant_id, '') AS uuid) IS NULL OR id = CAST(NULLIF(:tenant_id, '') AS uuid))
            ORDER BY updated_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": clean_tenant_id, "limit": 500 if not clean_tenant_id else 1},
    ).mappings().all()
    runs: list[dict[str, Any]] = []
    totals = {"subjects_processed": 0, "features_written": 0}
    for tenant in tenants:
        tid = str(tenant.get("id") or "")
        if not tid:
            continue
        for task in tasks:
            run_row = conn.execute(
                text(
                    """
                    INSERT INTO saas_ml_feature_pipeline_runs (
                        tenant_id, pipeline_key, prediction_type, feature_set_key,
                        window_key, status, started_at, updated_at
                    )
                    VALUES (
                        CAST(:tenant_id AS uuid), :pipeline_key, :prediction_type,
                        :feature_set_key, :window_key, 'running', NOW(), NOW()
                    )
                    RETURNING id::text
                    """
                ),
                {"tenant_id": tid, "pipeline_key": f"{task}_feature_pipeline_v1", "prediction_type": task, "feature_set_key": f"{task}_v1", "window_key": clean_window},
            ).mappings().first()
            run_id = str((run_row or {}).get("id") or "")
            try:
                result = _run_feature_pipeline_for_tenant(conn, tid, prediction_type=task, window_key=clean_window, limit=capped_limit)
                labels = generate_auto_labels(conn, tenant_id=tid, prediction_type=task, window_key=clean_window, limit=capped_limit)
                conn.execute(
                    text(
                        """
                        UPDATE saas_ml_feature_pipeline_runs
                        SET status = 'succeeded',
                            subjects_processed = :subjects_processed,
                            features_written = :features_written,
                            labels_generated = :labels_generated,
                            stats_json = CAST(:stats_json AS jsonb),
                            completed_at = NOW(),
                            updated_at = NOW()
                        WHERE id = CAST(:run_id AS uuid)
                        """
                    ),
                    {
                        "run_id": run_id,
                        "subjects_processed": int(result.get("subjects_processed") or 0),
                        "features_written": int(result.get("features_written") or 0),
                        "labels_generated": int(labels.get("total") or 0),
                        "stats_json": _json({"features": result, "labels": labels}),
                    },
                )
                item = {"id": run_id, "tenant_id": tid, "prediction_type": task, "status": "succeeded", **result, "labels_generated": int(labels.get("total") or 0)}
            except Exception as exc:
                conn.execute(
                    text(
                        """
                        UPDATE saas_ml_feature_pipeline_runs
                        SET status = 'failed', error_text = :error_text, completed_at = NOW(), updated_at = NOW()
                        WHERE id = CAST(:run_id AS uuid)
                        """
                    ),
                    {"run_id": run_id, "error_text": str(exc)[:2000]},
                )
                item = {"id": run_id, "tenant_id": tid, "prediction_type": task, "status": "failed", "error": str(exc)[:500], "subjects_processed": 0, "features_written": 0, "labels_generated": 0}
            totals["subjects_processed"] += int(item.get("subjects_processed") or 0)
            totals["features_written"] += int(item.get("features_written") or 0)
            runs.append(item)
    return {"tenant_id": clean_tenant_id, "window_key": clean_window, "tasks": tasks, "tenants": len(tenants), "totals": totals, "runs": runs[:100]}


def run_training_data_preparation(
    conn: Connection,
    *,
    tenant_id: str = "",
    prediction_type: str = "",
    window_key: str = "90d",
    limit: int = 1000,
) -> dict[str, Any]:
    features = recompute_training_feature_pipelines(conn, tenant_id=tenant_id, prediction_type=prediction_type, window_key=window_key, limit=limit)
    labels_total = sum(int((run or {}).get("labels_generated") or 0) for run in features.get("runs", []))
    return {
        "labels": {"total": labels_total, "source": "feature_pipeline_runs"},
        "feature_pipelines": features,
    }


def mlops_overview(conn: Connection, *, tenant_id: str = "", limit: int = 80) -> dict[str, Any]:
    ensure_intelligence_tables(conn)
    clean_tenant_id = _clean(tenant_id, 80)
    capped_limit = max(1, min(int(limit or 80), 300))
    tenant_clause = "(CAST(NULLIF(:tenant_id, '') AS uuid) IS NULL OR tenant_id = CAST(NULLIF(:tenant_id, '') AS uuid))"
    params = {"tenant_id": clean_tenant_id, "limit": capped_limit}
    jobs: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    inference_runs: list[dict[str, Any]] = []
    drift_snapshots: list[dict[str, Any]] = []
    auto_labels: list[dict[str, Any]] = []
    feature_pipeline_runs: list[dict[str, Any]] = []
    training_datasets: list[dict[str, Any]] = []
    model_evaluations: list[dict[str, Any]] = []
    event_contract_count = 0
    feature_set_count = 0

    if _pg_table_exists(conn, "saas_ml_training_jobs"):
        rows = conn.execute(
            text(
                f"""
                SELECT id::text, COALESCE(tenant_id::text, '') AS tenant_id, job_type,
                       prediction_type, model_key, framework, status, source,
                       dataset_summary_json, params_json, result_json, error_text,
                       mlflow_run_id, bentoml_tag, artifact_uri,
                       started_at::text, completed_at::text, created_at::text, updated_at::text
                FROM saas_ml_training_jobs
                WHERE {tenant_clause}
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
        jobs = [dict(row) for row in rows]

    if _pg_table_exists(conn, "saas_ml_model_artifacts"):
        rows = conn.execute(
            text(
                f"""
                SELECT id::text, COALESCE(tenant_id::text, '') AS tenant_id, model_key,
                       prediction_type, framework, version, artifact_uri, local_path,
                       mlflow_run_id, bentoml_tag, status, metrics_json, metadata_json,
                       created_at::text, updated_at::text
                FROM saas_ml_model_artifacts
                WHERE {tenant_clause}
                ORDER BY updated_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
        artifacts = [dict(row) for row in rows]

    if _pg_table_exists(conn, "saas_ml_inference_runs"):
        rows = conn.execute(
            text(
                f"""
                SELECT id::text, tenant_id::text, COALESCE(prediction_id::text, '') AS prediction_id,
                       model_key, model_version, prediction_type, subject_type, subject_id,
                       mode, status, score, label, confidence, latency_ms, fallback_used,
                       input_json, output_json, error_text, created_at::text
                FROM saas_ml_inference_runs
                WHERE {tenant_clause}
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
        for row in rows:
            item = dict(row)
            item["score"] = float(item["score"]) if item.get("score") is not None else None
            item["confidence"] = float(item["confidence"]) if item.get("confidence") is not None else None
            inference_runs.append(item)

    if _pg_table_exists(conn, "saas_ml_drift_snapshots"):
        rows = conn.execute(
            text(
                f"""
                SELECT id::text, COALESCE(tenant_id::text, '') AS tenant_id, model_key,
                       prediction_type, window_key, baseline_json, current_json,
                       drift_score, status, signals_json, computed_at::text, created_at::text
                FROM saas_ml_drift_snapshots
                WHERE {tenant_clause}
                ORDER BY computed_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
        for row in rows:
            item = dict(row)
            item["drift_score"] = float(item["drift_score"]) if item.get("drift_score") is not None else None
            drift_snapshots.append(item)

    if _pg_table_exists(conn, "saas_intelligence_event_contracts"):
        event_contract_count = int(conn.execute(text("SELECT COUNT(*)::int FROM saas_intelligence_event_contracts WHERE enabled = TRUE")).scalar() or 0)

    if _pg_table_exists(conn, "saas_ml_feature_sets"):
        feature_set_count = int(conn.execute(text("SELECT COUNT(*)::int FROM saas_ml_feature_sets WHERE status = 'active'")).scalar() or 0)

    if _pg_table_exists(conn, "saas_ml_auto_labels"):
        rows = conn.execute(
            text(
                f"""
                SELECT id::text, tenant_id::text, prediction_type, subject_type,
                       subject_id, label_key, label_value, label_text,
                       label_confidence, evidence_json, window_key,
                       generated_by, generated_at::text, updated_at::text
                FROM saas_ml_auto_labels
                WHERE {tenant_clause}
                ORDER BY generated_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
        for row in rows:
            item = dict(row)
            item["label_confidence"] = float(item["label_confidence"]) if item.get("label_confidence") is not None else None
            auto_labels.append(item)

    if _pg_table_exists(conn, "saas_ml_feature_pipeline_runs"):
        rows = conn.execute(
            text(
                f"""
                SELECT id::text, COALESCE(tenant_id::text, '') AS tenant_id,
                       pipeline_key, prediction_type, feature_set_key, window_key,
                       status, subjects_processed, features_written, labels_generated,
                       stats_json, error_text, started_at::text, completed_at::text,
                       created_at::text, updated_at::text
                FROM saas_ml_feature_pipeline_runs
                WHERE {tenant_clause}
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
        feature_pipeline_runs = [dict(row) for row in rows]

    if _pg_table_exists(conn, "saas_ml_training_datasets"):
        rows = conn.execute(
            text(
                f"""
                SELECT id::text, COALESCE(tenant_id::text, '') AS tenant_id,
                       dataset_key, prediction_type, feature_set_key, version,
                       window_key, label_policy, source, sample_count,
                       positive_count, negative_count, label_distribution_json,
                       feature_summary_json, dataset_uri, metadata_json,
                       created_at::text, updated_at::text
                FROM saas_ml_training_datasets
                WHERE {tenant_clause}
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
        training_datasets = [dict(row) for row in rows]

    if _pg_table_exists(conn, "saas_ml_model_evaluations"):
        rows = conn.execute(
            text(
                f"""
                SELECT id::text, COALESCE(tenant_id::text, '') AS tenant_id,
                       model_key, model_version, prediction_type, evaluation_type,
                       COALESCE(dataset_id::text, '') AS dataset_id, status,
                       metrics_json, slices_json, notes, created_at::text
                FROM saas_ml_model_evaluations
                WHERE {tenant_clause}
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
        model_evaluations = [dict(row) for row in rows]

    return {
        "config": {
            "enabled": bool(settings.saas_ml_enabled),
            "shadow_inference_enabled": bool(settings.saas_ml_shadow_inference_enabled),
            "auto_train_enabled": bool(settings.saas_ml_auto_train_enabled),
            "service_url": settings.saas_ml_service_url,
            "inference_timeout_sec": int(settings.saas_ml_inference_timeout_sec or 3),
            "mlflow_tracking_uri": settings.saas_mlflow_tracking_uri,
            "model_dir": settings.saas_ml_model_dir,
            "qdrant_url": settings.saas_qdrant_url,
            "default_rollout": "disabled",
        },
        "jobs": jobs,
        "artifacts": artifacts,
        "inference_runs": inference_runs,
        "drift_snapshots": drift_snapshots,
        "auto_labels": auto_labels,
        "feature_pipeline_runs": feature_pipeline_runs,
        "training_datasets": training_datasets,
        "model_evaluations": model_evaluations,
        "counts": {
            "jobs": len(jobs),
            "artifacts": len(artifacts),
            "inference_runs": len(inference_runs),
            "drift_snapshots": len(drift_snapshots),
            "auto_labels": len(auto_labels),
            "feature_pipeline_runs": len(feature_pipeline_runs),
            "training_datasets": len(training_datasets),
            "model_evaluations": len(model_evaluations),
            "event_contracts": event_contract_count,
            "feature_sets": feature_set_count,
        },
    }


def training_dataset_readiness(
    conn: Connection,
    *,
    tenant_id: str = "",
    model_key: str = "",
    prediction_type: str = "",
    window_key: str = "90d",
    limit: int = 80,
    only_labeled: bool = True,
) -> dict[str, Any]:
    ensure_intelligence_tables(conn)
    clean_tenant_id = _clean(tenant_id, 80)
    clean_model = _clean(model_key, 160)
    clean_prediction = _clean(prediction_type, 120).lower().replace("-", "_")
    clean_window = _clean(window_key, 80) or "90d"
    days = _window_days(clean_window)
    capped_limit = max(1, min(int(limit or 80), 500))
    params = {
        "tenant_id": clean_tenant_id,
        "model_key": clean_model,
        "prediction_type": clean_prediction,
        "window_days": days,
        "window_key": clean_window,
        "limit": capped_limit,
        "only_labeled": bool(only_labeled),
    }
    summary_rows = conn.execute(
        text(
            """
            SELECT p.tenant_id::text AS tenant_id,
                   t.name AS tenant_name,
                   t.slug AS tenant_slug,
                   p.model_key,
                   p.prediction_type,
                   COUNT(*)::int AS sample_size,
                   COUNT(f.id) FILTER (WHERE f.feedback_type = 'outcome')::int AS labeled_count,
                   COUNT(*) FILTER (WHERE f.id IS NULL)::int AS unlabeled_count,
                   COUNT(*) FILTER (WHERE f.is_correct = TRUE)::int AS correct_count,
                   COUNT(*) FILTER (WHERE f.is_correct = FALSE)::int AS incorrect_count,
                   COUNT(DISTINCT COALESCE(NULLIF(f.actual_label, ''), f.is_correct::text)) FILTER (WHERE f.id IS NOT NULL)::int AS label_diversity,
                   AVG(p.score)::numeric(8,4) AS avg_score,
                   AVG(f.actual_score) FILTER (WHERE f.actual_score IS NOT NULL)::numeric(8,4) AS avg_actual_score,
                   MAX(p.created_at)::text AS last_prediction_at,
                   MAX(f.updated_at)::text AS last_feedback_at,
                   COALESCE(r.min_labeled_count, 50)::int AS min_labeled_count
            FROM saas_intelligence_predictions p
            JOIN saas_tenants t ON t.id = p.tenant_id
            LEFT JOIN saas_intelligence_prediction_feedback f
              ON f.prediction_id = p.id
             AND f.tenant_id = p.tenant_id
             AND f.feedback_type = 'outcome'
            LEFT JOIN saas_intelligence_model_registry r ON r.model_key = p.model_key
            WHERE (CAST(NULLIF(:tenant_id, '') AS uuid) IS NULL OR p.tenant_id = CAST(NULLIF(:tenant_id, '') AS uuid))
              AND (:model_key = '' OR p.model_key = :model_key)
              AND (:prediction_type = '' OR p.prediction_type = :prediction_type)
              AND p.created_at >= NOW() - (:window_days * INTERVAL '1 day')
            GROUP BY p.tenant_id, t.name, t.slug, p.model_key, p.prediction_type, r.min_labeled_count
            ORDER BY labeled_count DESC, sample_size DESC, last_prediction_at DESC
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()
    summaries: list[dict[str, Any]] = []
    total_sample_size = 0
    total_labeled = 0
    ready_groups = 0
    for row in summary_rows:
        item = dict(row)
        sample_size = int(item.get("sample_size") or 0)
        labeled_count = int(item.get("labeled_count") or 0)
        label_diversity = int(item.get("label_diversity") or 0)
        min_labeled = int(item.get("min_labeled_count") or 50)
        reasons: list[str] = []
        if labeled_count < min_labeled:
            reasons.append("insufficient_labeled_feedback")
        if label_diversity < 2:
            reasons.append("single_label_or_unlabeled")
        ready = not reasons
        if ready:
            ready_groups += 1
        total_sample_size += sample_size
        total_labeled += labeled_count
        item.update(
            {
                "sample_size": sample_size,
                "labeled_count": labeled_count,
                "unlabeled_count": int(item.get("unlabeled_count") or 0),
                "correct_count": int(item.get("correct_count") or 0),
                "incorrect_count": int(item.get("incorrect_count") or 0),
                "label_diversity": label_diversity,
                "avg_score": float(item["avg_score"]) if item.get("avg_score") is not None else None,
                "avg_actual_score": float(item["avg_actual_score"]) if item.get("avg_actual_score") is not None else None,
                "min_labeled_count": min_labeled,
                "ready_for_training": ready,
                "readiness_reasons": reasons or ["ready"],
            }
        )
        summaries.append(item)

    sample_rows = conn.execute(
        text(
            """
            SELECT p.id::text AS prediction_id,
                   p.tenant_id::text AS tenant_id,
                   t.name AS tenant_name,
                   t.slug AS tenant_slug,
                   p.subject_type,
                   p.subject_id,
                   p.prediction_type,
                   p.model_key,
                   p.model_version,
                   p.mode,
                   p.score,
                   p.label,
                   p.confidence,
                   p.status,
                   p.features_json,
                   p.explanation_json,
                   p.output_json,
                   p.created_at::text AS prediction_created_at,
                   COALESCE(f.id::text, '') AS feedback_id,
                   COALESCE(f.actual_label, '') AS actual_label,
                   f.actual_score,
                   f.is_correct,
                   f.outcome_json,
                   COALESCE(f.notes, '') AS feedback_notes,
                   f.updated_at::text AS feedback_updated_at
            FROM saas_intelligence_predictions p
            JOIN saas_tenants t ON t.id = p.tenant_id
            LEFT JOIN saas_intelligence_prediction_feedback f
              ON f.prediction_id = p.id
             AND f.tenant_id = p.tenant_id
             AND f.feedback_type = 'outcome'
            WHERE (CAST(NULLIF(:tenant_id, '') AS uuid) IS NULL OR p.tenant_id = CAST(NULLIF(:tenant_id, '') AS uuid))
              AND (:model_key = '' OR p.model_key = :model_key)
              AND (:prediction_type = '' OR p.prediction_type = :prediction_type)
              AND p.created_at >= NOW() - (:window_days * INTERVAL '1 day')
              AND (:only_labeled = FALSE OR f.id IS NOT NULL)
            ORDER BY f.updated_at DESC NULLS LAST, p.created_at DESC
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()
    samples = []
    for row in sample_rows:
        item = dict(row)
        item["score"] = float(item["score"]) if item.get("score") is not None else None
        item["confidence"] = float(item["confidence"]) if item.get("confidence") is not None else None
        item["actual_score"] = float(item["actual_score"]) if item.get("actual_score") is not None else None
        item["training_label"] = item.get("actual_label") or ("correct" if item.get("is_correct") is True else "incorrect" if item.get("is_correct") is False else "")
        samples.append(item)
    auto_label_rows = conn.execute(
        text(
            """
            SELECT l.tenant_id::text AS tenant_id,
                   t.name AS tenant_name,
                   t.slug AS tenant_slug,
                   l.prediction_type,
                   l.window_key,
                   COUNT(*)::int AS labeled_count,
                   COUNT(*) FILTER (WHERE l.label_value = TRUE)::int AS positive_count,
                   COUNT(*) FILTER (WHERE l.label_value = FALSE)::int AS negative_count,
                   COUNT(DISTINCT l.subject_id)::int AS subjects,
                   MAX(l.generated_at)::text AS last_generated_at
            FROM saas_ml_auto_labels l
            JOIN saas_tenants t ON t.id = l.tenant_id
            WHERE (CAST(NULLIF(:tenant_id, '') AS uuid) IS NULL OR l.tenant_id = CAST(NULLIF(:tenant_id, '') AS uuid))
              AND (:prediction_type = '' OR l.prediction_type = :prediction_type)
              AND l.window_key = :window_key
            GROUP BY l.tenant_id, t.name, t.slug, l.prediction_type, l.window_key
            ORDER BY labeled_count DESC, last_generated_at DESC
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()
    auto_label_summaries = []
    auto_label_count = 0
    auto_label_ready = 0
    for row in auto_label_rows:
        item = dict(row)
        item["labeled_count"] = int(item.get("labeled_count") or 0)
        item["positive_count"] = int(item.get("positive_count") or 0)
        item["negative_count"] = int(item.get("negative_count") or 0)
        item["subjects"] = int(item.get("subjects") or 0)
        item["ready_for_training"] = item["labeled_count"] >= 50 and item["positive_count"] > 0 and item["negative_count"] > 0
        auto_label_count += item["labeled_count"]
        if item["ready_for_training"]:
            auto_label_ready += 1
        auto_label_summaries.append(item)
    return {
        "filters": {
            "tenant_id": clean_tenant_id,
            "model_key": clean_model,
            "prediction_type": clean_prediction,
            "window_key": clean_window,
            "only_labeled": bool(only_labeled),
            "limit": capped_limit,
        },
        "readiness": {
            "groups": len(summaries),
            "ready_groups": ready_groups,
            "sample_size": total_sample_size,
            "labeled_count": total_labeled,
            "auto_label_groups": len(auto_label_summaries),
            "auto_label_ready_groups": auto_label_ready,
            "auto_label_count": auto_label_count,
            "ready_for_training": bool(summaries) and ready_groups == len(summaries),
            "ready_for_autolabel_training": bool(auto_label_summaries) and auto_label_ready > 0,
        },
        "summaries": summaries,
        "auto_label_summaries": auto_label_summaries,
        "samples": samples,
    }


def recompute_model_metrics(
    conn: Connection,
    *,
    tenant_id: str = "",
    model_key: str = "",
    prediction_type: str = "",
    window_key: str = "90d",
) -> list[dict[str, Any]]:
    ensure_intelligence_tables(conn)
    clean_tenant_id = _clean(tenant_id, 80)
    clean_model = _clean(model_key, 160)
    clean_prediction = _clean(prediction_type, 120).lower().replace("-", "_")
    clean_window = _clean(window_key, 80) or "90d"
    days = _window_days(clean_window)
    rows = conn.execute(
        text(
            """
            SELECT p.tenant_id::text AS tenant_id,
                   p.model_key,
                   p.prediction_type,
                   COUNT(*)::int AS sample_size,
                   COUNT(f.id) FILTER (WHERE f.is_correct IS NOT NULL)::int AS labeled_count,
                   AVG(CASE
                       WHEN f.is_correct = TRUE THEN 100.0
                       WHEN f.is_correct = FALSE THEN 0.0
                       ELSE NULL
                   END)::numeric(8,4) AS accuracy,
                   AVG(p.confidence)::numeric(8,4) AS avg_confidence,
                   AVG(p.score)::numeric(8,4) AS avg_score,
                   AVG(ABS(p.score - f.actual_score)) FILTER (WHERE f.actual_score IS NOT NULL)::numeric(8,4) AS avg_error,
                   AVG(p.score) FILTER (WHERE p.created_at >= NOW() - INTERVAL '30 days')::numeric(8,4) AS recent_avg_score,
                   AVG(p.score) FILTER (
                       WHERE p.created_at < NOW() - INTERVAL '30 days'
                         AND p.created_at >= NOW() - INTERVAL '60 days'
                   )::numeric(8,4) AS previous_avg_score
            FROM saas_intelligence_predictions p
            LEFT JOIN saas_intelligence_prediction_feedback f
              ON f.prediction_id = p.id
             AND f.tenant_id = p.tenant_id
             AND f.feedback_type = 'outcome'
            WHERE (CAST(NULLIF(:tenant_id, '') AS uuid) IS NULL OR p.tenant_id = CAST(NULLIF(:tenant_id, '') AS uuid))
              AND (:model_key = '' OR p.model_key = :model_key)
              AND (:prediction_type = '' OR p.prediction_type = :prediction_type)
              AND p.created_at >= NOW() - (:window_days * INTERVAL '1 day')
            GROUP BY p.tenant_id, p.model_key, p.prediction_type
            """
        ),
        {
            "tenant_id": clean_tenant_id,
            "model_key": clean_model,
            "prediction_type": clean_prediction,
            "window_days": days,
        },
    ).mappings().all()
    metrics: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        previous = item.get("previous_avg_score")
        recent = item.get("recent_avg_score")
        drift = abs(float(recent) - float(previous)) if previous is not None and recent is not None else 0.0
        accuracy = float(item["accuracy"]) if item.get("accuracy") is not None else None
        status = _metric_status(int(item.get("labeled_count") or 0), accuracy, drift)
        params = {
            "tenant_id": item["tenant_id"],
            "model_key": item["model_key"],
            "prediction_type": item["prediction_type"],
            "window_key": clean_window,
            "sample_size": int(item.get("sample_size") or 0),
            "labeled_count": int(item.get("labeled_count") or 0),
            "accuracy": accuracy,
            "precision_score": None,
            "recall_score": None,
            "avg_confidence": item.get("avg_confidence"),
            "avg_score": item.get("avg_score"),
            "avg_error": item.get("avg_error"),
            "drift_score": drift,
            "status": status,
            "metrics_json": _json(
                {
                    "recent_avg_score": item.get("recent_avg_score"),
                    "previous_avg_score": item.get("previous_avg_score"),
                    "window_days": days,
                    "precision_recall_note": "No confusion matrix is computed until per-task labels are standardized.",
                }
            ),
        }
        saved = conn.execute(
            text(
                """
                INSERT INTO saas_intelligence_model_metrics (
                    tenant_id, model_key, prediction_type, window_key, sample_size,
                    labeled_count, accuracy, precision_score, recall_score,
                    avg_confidence, avg_score, avg_error, drift_score, status,
                    metrics_json, computed_at, updated_at
                )
                VALUES (
                    CAST(:tenant_id AS uuid), :model_key, :prediction_type, :window_key,
                    :sample_size, :labeled_count, :accuracy, :precision_score, :recall_score,
                    :avg_confidence, :avg_score, :avg_error, :drift_score, :status,
                    CAST(:metrics_json AS jsonb), NOW(), NOW()
                )
                ON CONFLICT (tenant_id, model_key, prediction_type, window_key)
                DO UPDATE SET
                    sample_size = EXCLUDED.sample_size,
                    labeled_count = EXCLUDED.labeled_count,
                    accuracy = EXCLUDED.accuracy,
                    precision_score = EXCLUDED.precision_score,
                    recall_score = EXCLUDED.recall_score,
                    avg_confidence = EXCLUDED.avg_confidence,
                    avg_score = EXCLUDED.avg_score,
                    avg_error = EXCLUDED.avg_error,
                    drift_score = EXCLUDED.drift_score,
                    status = EXCLUDED.status,
                    metrics_json = EXCLUDED.metrics_json,
                    computed_at = NOW(),
                    updated_at = NOW()
                RETURNING id::text, tenant_id::text, model_key, prediction_type, window_key,
                          sample_size, labeled_count, accuracy, precision_score, recall_score,
                          avg_confidence, avg_score, avg_error, drift_score, status,
                          metrics_json, computed_at::text, updated_at::text
                """
            ),
            params,
        ).mappings().first()
        metrics.append(dict(saved or {}))
    return metrics


def list_model_metrics(
    conn: Connection,
    *,
    tenant_id: str = "",
    model_key: str = "",
    prediction_type: str = "",
    limit: int = 120,
) -> list[dict[str, Any]]:
    ensure_intelligence_tables(conn)
    where: list[str] = []
    params: dict[str, Any] = {
        "tenant_id": _clean(tenant_id, 80),
        "model_key": _clean(model_key, 160),
        "prediction_type": _clean(prediction_type, 120).lower().replace("-", "_"),
        "limit": max(1, min(int(limit or 120), 500)),
    }
    if params["tenant_id"]:
        where.append("m.tenant_id = CAST(:tenant_id AS uuid)")
    if params["model_key"]:
        where.append("m.model_key = :model_key")
    if params["prediction_type"]:
        where.append("m.prediction_type = :prediction_type")
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    rows = conn.execute(
        text(
            f"""
            SELECT m.id::text, m.tenant_id::text, t.name AS tenant_name, t.slug AS tenant_slug,
                   m.model_key, m.prediction_type, m.window_key, m.sample_size,
                   m.labeled_count, m.accuracy, m.precision_score, m.recall_score,
                   m.avg_confidence, m.avg_score, m.avg_error, m.drift_score,
                   m.status, m.metrics_json, m.computed_at::text, m.updated_at::text
            FROM saas_intelligence_model_metrics m
            JOIN saas_tenants t ON t.id = m.tenant_id
            {where_sql}
            ORDER BY m.computed_at DESC, m.status DESC, m.sample_size DESC
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()
    return [dict(row) for row in rows]


def list_recommendations(conn: Connection, tenant_id: str, *, status: str = "open", limit: int = 50) -> list[dict[str, Any]]:
    ensure_intelligence_tables(conn)
    where = ["tenant_id = CAST(:tenant_id AS uuid)"]
    params: dict[str, Any] = {"tenant_id": tenant_id, "limit": max(1, min(int(limit or 50), 200))}
    clean_status = _clean(status, 40).lower()
    if clean_status and clean_status != "all":
        where.append("status = :status")
        params["status"] = clean_status
    rows = conn.execute(
        text(
            f"""
            SELECT id::text, recommendation_type, COALESCE(source_prediction_id::text, '') AS source_prediction_id,
                   title, description, severity, confidence, action_json, evidence_json,
                   status, created_at::text, updated_at::text
            FROM saas_intelligence_recommendations
            WHERE {" AND ".join(where)}
            ORDER BY updated_at DESC
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()
    return [dict(row) for row in rows]


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _latest_predictions_by_type(predictions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for prediction in predictions:
        prediction_type = _clean(prediction.get("prediction_type"), 120)
        if prediction_type and prediction_type not in latest:
            latest[prediction_type] = prediction
    return latest


def _prediction_action(prediction: dict[str, Any], fallback: str) -> str:
    output = _json_object(prediction.get("output_json"))
    action = _clean(output.get("suggested_action"), 180)
    if action:
        return action.replace("_", " ")
    rollout = _json_object(output.get("model_rollout"))
    decision = _json_object(rollout.get("decision"))
    if decision.get("prediction_status") == "shadow":
        return "revisar en modo shadow antes de automatizar"
    return fallback


def _feature_state_map(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("key") or ""): dict(item) for item in state.get("features", []) if item.get("key")}


def _feature_rows_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item.get("feature_key") or ""): dict(item) for item in rows if item.get("feature_key")}


def _metric_observability(predictions: list[dict[str, Any]], metrics: list[dict[str, Any]]) -> dict[str, Any]:
    latencies: list[float] = []
    fallback_count = 0
    shadow_count = 0
    for prediction in predictions:
        output = _json_object(prediction.get("output_json"))
        inference = _json_object(output.get("ml_inference"))
        latency = _num(inference.get("latency_ms"), -1)
        if latency >= 0:
            latencies.append(latency)
        if inference.get("fallback_used"):
            fallback_count += 1
        rollout = _json_object(output.get("model_rollout"))
        decision = _json_object(rollout.get("decision"))
        if prediction.get("status") == "shadow" or decision.get("prediction_status") == "shadow":
            shadow_count += 1
    drift_values = [_num(item.get("drift_score"), -1) for item in metrics if item.get("drift_score") is not None]
    return {
        "prediction_count": len(predictions),
        "metric_count": len(metrics),
        "avg_inference_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0,
        "fallback_count": fallback_count,
        "shadow_count": shadow_count,
        "max_drift_score": round(max(drift_values), 2) if drift_values else 0,
        "model_statuses": {
            status: sum(1 for item in metrics if str(item.get("status") or "") == status)
            for status in sorted({str(item.get("status") or "") for item in metrics if item.get("status")})
        },
    }


def predictive_business_overview(conn: Connection, tenant_id: str, *, limit: int = 40) -> dict[str, Any]:
    """Compact tenant-facing predictive intelligence overview for dashboards and Advisor."""
    ensure_intelligence_tables(conn)
    max_limit = max(5, min(int(limit or 40), 120))
    state = intelligence_feature_state(conn, tenant_id)
    feature_state = _feature_state_map(state)
    feature_rows = list_feature_values(conn, tenant_id, subject_type="tenant", subject_id=tenant_id, limit=120)
    feature_values = _feature_rows_map(feature_rows)
    predictions = list_predictions(conn, tenant_id, limit=max_limit)
    recommendations = list_recommendations(conn, tenant_id, status="open", limit=max_limit)
    metrics = list_model_metrics(conn, tenant_id=tenant_id, limit=80)
    latest = _latest_predictions_by_type(predictions)
    crm_row = conn.execute(
        text(
            """
            SELECT
                COUNT(*)::int AS conversations,
                COALESCE(SUM(unread_count), 0)::int AS unread,
                COUNT(*) FILTER (WHERE lead_score >= 75 OR LOWER(lead_temperature) = 'hot')::int AS hot_leads,
                COUNT(*) FILTER (WHERE payment_status = 'pending')::int AS pending_payments,
                COUNT(*) FILTER (WHERE last_message_at < NOW() - INTERVAL '14 days')::int AS inactive_14d,
                COUNT(*) FILTER (WHERE sla_due_at IS NOT NULL AND sla_due_at < NOW())::int AS sla_overdue,
                COALESCE(AVG(NULLIF(lead_score, 0)), 0)::numeric(8,2) AS avg_lead_score
            FROM saas_conversations
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first() or {}
    channel_rows = conn.execute(
        text(
            """
            SELECT channel, COUNT(*)::int AS total,
                   COUNT(*) FILTER (WHERE lead_score >= 75 OR LOWER(lead_temperature) = 'hot')::int AS hot_leads
            FROM saas_conversations
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            GROUP BY channel
            ORDER BY hot_leads DESC, total DESC, channel ASC
            LIMIT 5
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().all()

    lead_prediction = latest.get("lead_scoring") or {}
    churn_prediction = latest.get("churn_prediction") or {}
    remarketing_prediction = latest.get("smart_remarketing") or {}
    operational_prediction = latest.get("operational_anomaly") or {}
    remarketing_output = _json_object(remarketing_prediction.get("output_json"))
    cards = [
        {
            "key": "lead_scoring",
            "title": "Lead scoring",
            "value": round(_num(lead_prediction.get("score"), _num(crm_row.get("avg_lead_score"))), 2),
            "label": lead_prediction.get("label") or ("hot" if int(crm_row.get("hot_leads") or 0) else "baseline"),
            "detail": f"{int(crm_row.get('hot_leads') or 0)} leads calientes detectados",
            "recommended_action": _prediction_action(lead_prediction, "priorizar seguimiento humano"),
            "feature": feature_state.get("lead_scoring_ml", {}),
        },
        {
            "key": "churn_prediction",
            "title": "Churn prediction",
            "value": round(_num(churn_prediction.get("score"), min(100, int(crm_row.get("inactive_14d") or 0) * 10)), 2),
            "label": churn_prediction.get("label") or ("high_risk" if int(crm_row.get("inactive_14d") or 0) >= 5 else "low_risk"),
            "detail": f"{int(crm_row.get('inactive_14d') or 0)} conversaciones inactivas 14d",
            "recommended_action": _prediction_action(churn_prediction, "crear recuperacion de clientes inactivos"),
            "feature": feature_state.get("churn_prediction", {}),
        },
        {
            "key": "smart_remarketing",
            "title": "Smart remarketing",
            "value": round(_num(remarketing_prediction.get("score"), _num(feature_values.get("campaign_response_rate", {}).get("value_numeric"))), 2),
            "label": remarketing_prediction.get("label") or "watchlist",
            "detail": f"{remarketing_output.get('best_channel') or 'whatsapp'} / {remarketing_output.get('best_window') or '09:00-11:00 local'}",
            "recommended_action": _prediction_action(remarketing_prediction, "simular campana antes de activar"),
            "feature": feature_state.get("smart_remarketing", {}),
        },
        {
            "key": "operational_anomaly",
            "title": "Operational intelligence",
            "value": round(_num(operational_prediction.get("score")), 2),
            "label": operational_prediction.get("label") or ("degraded" if int(crm_row.get("sla_overdue") or 0) else "normal"),
            "detail": f"{int(crm_row.get('sla_overdue') or 0)} SLA vencidos / {int(crm_row.get('unread') or 0)} sin leer",
            "recommended_action": _prediction_action(operational_prediction, "revisar diagnostico y colas"),
            "feature": feature_state.get("ai_operational_intelligence", {}),
        },
    ]
    top_channel = dict(channel_rows[0]) if channel_rows else {}
    daily_summary = (
        f"Hoy Intelligence ve {int(crm_row.get('hot_leads') or 0)} leads calientes, "
        f"{int(crm_row.get('inactive_14d') or 0)} clientes en riesgo por inactividad "
        f"y {len(recommendations)} recomendaciones abiertas."
    )
    weekly_summary = (
        f"El canal con mayor senal comercial es {top_channel.get('channel') or 'sin datos'} "
        f"con {int(top_channel.get('hot_leads') or 0)} leads calientes. "
        f"Usa las predicciones recientes para priorizar follow-up, recuperacion y remarketing."
    )
    operations_summary = (
        f"ModelOps registra {len(metrics)} metricas, "
        f"{_metric_observability(predictions, metrics)['fallback_count']} inferencias con fallback "
        f"y {int(crm_row.get('sla_overdue') or 0)} conversaciones con SLA vencido."
    )
    return {
        "tenant_id": tenant_id,
        "state": state,
        "crm": {key: _num(value) if key == "avg_lead_score" else int(value or 0) for key, value in dict(crm_row).items()},
        "channels": [dict(row) for row in channel_rows],
        "cards": cards,
        "predictions": predictions,
        "latest_predictions": latest,
        "recommendations": recommendations,
        "features": feature_rows,
        "metrics": metrics,
        "observability": _metric_observability(predictions, metrics),
        "executive_summaries": {
            "daily": daily_summary,
            "weekly": weekly_summary,
            "operations": operations_summary,
        },
        "premium": {
            "enabled": bool((feature_state.get("ai_premium") or {}).get("enabled")),
            "demo": any(str(item.get("mode") or "") == "demo" and item.get("enabled") for item in feature_state.values()),
            "features": {
                key: {
                    "enabled": bool((feature_state.get(key) or {}).get("enabled")),
                    "mode": (feature_state.get(key) or {}).get("mode") or "disabled",
                    "quota_used": int((feature_state.get(key) or {}).get("quota_used") or 0),
                    "quota_monthly": int((feature_state.get(key) or {}).get("quota_monthly") or 0),
                }
                for key in [str(item.get("key") or "") for item in INTELLIGENCE_FEATURES] if key in feature_state
            },
        },
    }


def dismiss_recommendation(conn: Connection, tenant_id: str, recommendation_id: str) -> dict[str, Any]:
    ensure_intelligence_tables(conn)
    row = conn.execute(
        text(
            """
            UPDATE saas_intelligence_recommendations
            SET status = 'dismissed', updated_at = NOW()
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:id AS uuid)
            RETURNING id::text, status, updated_at::text
            """
        ),
        {"tenant_id": tenant_id, "id": recommendation_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="recommendation_not_found")
    return dict(row)


def admin_intelligence_tenants(conn: Connection, *, limit: int = 120) -> list[dict[str, Any]]:
    ensure_intelligence_tables(conn)
    rows = conn.execute(
        text(
            """
            SELECT
                t.id::text,
                t.name,
                t.slug,
                t.status,
                t.plan_code,
                COALESCE((SELECT SUM(quantity)::int FROM saas_intelligence_usage u WHERE u.tenant_id = t.id AND u.period_yyyymm = :period), 0) AS intelligence_usage_month,
                COALESCE((SELECT COUNT(*)::int FROM saas_intelligence_predictions p WHERE p.tenant_id = t.id AND p.created_at >= NOW() - INTERVAL '30 days'), 0) AS predictions_30d,
                COALESCE((SELECT COUNT(*)::int FROM saas_intelligence_recommendations r WHERE r.tenant_id = t.id AND r.status = 'open'), 0) AS open_recommendations
            FROM saas_tenants t
            ORDER BY t.updated_at DESC
            LIMIT :limit
            """
        ),
        {"period": _period_yyyymm(), "limit": max(1, min(int(limit or 120), 300))},
    ).mappings().all()
    output = []
    for row in rows:
        item = dict(row)
        item["intelligence"] = intelligence_feature_state(conn, item["id"])
        output.append(item)
    return output


def upsert_feature_grant(conn: Connection, tenant_id: str, payload: Any, *, actor_user_id: str) -> dict[str, Any]:
    ensure_intelligence_tables(conn)
    data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload or {})
    feature_key = normalize_feature_key(str(data.get("feature_key") or ""))
    if feature_key not in INTELLIGENCE_FEATURE_MAP:
        raise HTTPException(status_code=400, detail={"code": "unknown_intelligence_feature", "feature": feature_key})
    mode = normalize_mode(str(data.get("mode") or ""), enabled=bool(data.get("enabled", True)))
    row = conn.execute(
        text(
            """
            INSERT INTO saas_intelligence_feature_grants (
                tenant_id, feature_key, enabled, mode, quota_monthly, source,
                valid_until, notes, updated_by_user_id, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), :feature_key, :enabled, :mode, :quota_monthly, :source,
                CAST(NULLIF(:valid_until, '') AS timestamp), :notes, CAST(:actor_user_id AS uuid), NOW()
            )
            ON CONFLICT (tenant_id, feature_key)
            DO UPDATE SET
                enabled = EXCLUDED.enabled,
                mode = EXCLUDED.mode,
                quota_monthly = EXCLUDED.quota_monthly,
                source = EXCLUDED.source,
                valid_until = EXCLUDED.valid_until,
                notes = EXCLUDED.notes,
                updated_by_user_id = EXCLUDED.updated_by_user_id,
                updated_at = NOW()
            RETURNING id::text, feature_key, enabled, mode, quota_monthly, source,
                      valid_until::text, notes, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "feature_key": feature_key,
            "enabled": mode != "disabled",
            "mode": mode,
            "quota_monthly": int(data.get("quota_monthly") or 0),
            "source": _clean(data.get("source"), 80) or "admin",
            "valid_until": _clean(data.get("valid_until"), 80),
            "notes": _clean(data.get("notes"), 1000),
            "actor_user_id": actor_user_id,
        },
    ).mappings().first()
    return dict(row or {})


def admin_multimodal_premium_gating(conn: Connection, *, limit: int = 120) -> dict[str, Any]:
    ensure_intelligence_tables(conn)
    ensure_premium_gating_tables(conn)
    phase_features = [
        dict(item)
        for item in INTELLIGENCE_FEATURES
        if str(item.get("key") or "") in PHASE24_FEATURE_KEYS
    ]
    tenants = admin_intelligence_tenants(conn, limit=limit)
    tenant_rows: list[dict[str, Any]] = []
    for tenant in tenants:
        features = {
            str(feature.get("key") or ""): feature
            for feature in ((tenant.get("intelligence") or {}).get("features") or [])
            if feature.get("key")
        }
        phase_state = [features.get(item["key"], {"key": item["key"], "enabled": False, "mode": "disabled"}) for item in phase_features]
        tenant_rows.append(
            {
                "id": tenant.get("id"),
                "name": tenant.get("name"),
                "slug": tenant.get("slug"),
                "status": tenant.get("status"),
                "plan_code": tenant.get("plan_code"),
                "intelligence_usage_month": tenant.get("intelligence_usage_month"),
                "phase24_features": phase_state,
                "phase24_summary": {
                    "enabled": sum(1 for item in phase_state if bool(item.get("enabled"))),
                    "full": sum(1 for item in phase_state if str(item.get("mode") or "") == "full"),
                    "demo": sum(1 for item in phase_state if str(item.get("mode") or "") == "demo"),
                    "quota_used": sum(int(item.get("quota_used") or 0) for item in phase_state),
                    "quota_monthly": sum(int(item.get("quota_monthly") or 0) for item in phase_state),
                },
            }
        )
    plan_rows = conn.execute(
        text(
            """
            SELECT plan_code, display_name, is_active, price_monthly_cents,
                   currency, sort_order
            FROM saas_plan_limits
            ORDER BY sort_order ASC, plan_code ASC
            """
        )
    ).mappings().all()
    return {
        "phase": "24.8-24.10",
        "features": phase_features,
        "tenants": tenant_rows,
        "plans": [dict(row) for row in plan_rows],
        "plan_feature_limits": list(plan_feature_limits(conn).values()),
        "provider_policies": list_provider_policies(conn),
        "provider_credentials": provider_credential_summary(conn),
        "provider_costs": provider_cost_summary(conn),
        "safety": {
            "default_provider_policy": "allow_when_no_explicit_policy",
            "cost_policy": "admin_configured_zero_by_default",
            "tenant_grants_override_plan_limits": True,
            "provider_disable_is_enforced": True,
            "multimodal_rollout_defaults_off": True,
            "multimodal_runtime_enforcement_requires_explicit_policy": True,
        },
    }
