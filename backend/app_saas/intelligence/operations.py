from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app_saas.billing.limits import tenant_entitlements
from app_saas.intelligence.service import (
    ensure_intelligence_tables,
    intelligence_feature_state,
    list_recommendations,
    predictive_business_overview,
    record_event,
    record_intelligence_usage,
)


AUTONOMY_LEVELS: list[dict[str, Any]] = [
    {"level": 0, "label": "Insights only", "description": "Detecta y reporta sin sugerir acciones ejecutables."},
    {"level": 1, "label": "Recommendations", "description": "Genera recomendaciones y playbooks sugeridos."},
    {"level": 2, "label": "Suggested actions", "description": "Crea acciones propuestas que requieren aprobacion humana."},
    {"level": 3, "label": "Semi-autonomous", "description": "Prepara acciones listas para aprobacion y rollback documentado."},
    {"level": 4, "label": "Low-risk autonomous", "description": "Permite ejecucion controlada solo para acciones de bajo riesgo habilitadas."},
]

DEFAULT_PLAYBOOKS: list[dict[str, Any]] = [
    {
        "playbook_key": "retry_webhook_events",
        "category": "self_healing",
        "title": "Reintentar eventos webhook fallidos",
        "description": "Revisar y reencolar eventos webhook fallidos desde observabilidad/admin cuando aplique.",
        "risk_level": "low",
        "required_autonomy_level": 2,
        "approval_required": True,
        "auto_executable": False,
        "action_type": "webhook_retry_plan",
        "action_json": {"target": "webhooks", "recommended_endpoint": "/admin/observability/dead-letter/{id}/retry"},
        "rollback_json": {"strategy": "detener nuevos reintentos y volver a estado open en dead-letter si falla"},
    },
    {
        "playbook_key": "retry_outbound_queue",
        "category": "self_healing",
        "title": "Revisar cola outbound degradada",
        "description": "Preparar remediacion de cola outbound con retries controlados y revision de errores Meta.",
        "risk_level": "low",
        "required_autonomy_level": 2,
        "approval_required": True,
        "auto_executable": False,
        "action_type": "outbound_retry_plan",
        "action_json": {"target": "outbound", "recommended_endpoint": "/admin/operations/outbound/process"},
        "rollback_json": {"strategy": "pausar dispatch y revisar mensajes fallidos antes de nuevo intento"},
    },
    {
        "playbook_key": "resubscribe_meta_webhooks",
        "category": "meta_ops",
        "title": "Revisar subscribed_apps Meta",
        "description": "Diagnosticar drift de suscripcion Meta y preparar resuscripcion bajo aprobacion.",
        "risk_level": "high",
        "required_autonomy_level": 3,
        "approval_required": True,
        "auto_executable": False,
        "action_type": "meta_subscription_review",
        "action_json": {"target": "meta", "requires_credentials": True},
        "rollback_json": {"strategy": "revertir cambios de subscription desde Meta app dashboard si la verificacion falla"},
    },
    {
        "playbook_key": "refresh_meta_tokens",
        "category": "meta_ops",
        "title": "Revisar salud de tokens Meta",
        "description": "Detectar tokens vencidos o proximos a vencer y preparar renovacion segura.",
        "risk_level": "medium",
        "required_autonomy_level": 2,
        "approval_required": True,
        "auto_executable": False,
        "action_type": "meta_token_health_review",
        "action_json": {"target": "integrations", "recommended_endpoint": "/admin/operations/meta-tokens/process"},
        "rollback_json": {"strategy": "mantener token anterior hasta confirmar refresh valido"},
    },
    {
        "playbook_key": "optimize_trigger_timing",
        "category": "optimization",
        "title": "Optimizar timing de triggers",
        "description": "Proponer ajustes de horario, cooldown y condiciones cuando la ejecucion baja el rendimiento.",
        "risk_level": "medium",
        "required_autonomy_level": 2,
        "approval_required": True,
        "auto_executable": False,
        "action_type": "trigger_optimization_draft",
        "action_json": {"target": "campaigns", "tool": "triggers.suggest"},
        "rollback_json": {"strategy": "mantener version previa del trigger y usar rollback de Phase 7"},
    },
    {
        "playbook_key": "optimize_campaign_send_time",
        "category": "optimization",
        "title": "Optimizar horario de campana",
        "description": "Recomendar ventanas de envio y segmentos cuando baja la respuesta de campana.",
        "risk_level": "medium",
        "required_autonomy_level": 2,
        "approval_required": True,
        "auto_executable": False,
        "action_type": "campaign_optimization_draft",
        "action_json": {"target": "campaigns", "tool": "campaigns.create_draft"},
        "rollback_json": {"strategy": "no activar campana sin preflight y aprobacion humana"},
    },
    {
        "playbook_key": "churn_recovery",
        "category": "crm",
        "title": "Recuperar clientes inactivos",
        "description": "Priorizar clientes inactivos y sugerir recuperacion comercial con remarketing.",
        "risk_level": "medium",
        "required_autonomy_level": 2,
        "approval_required": True,
        "auto_executable": False,
        "action_type": "retention_campaign_draft",
        "action_json": {"target": "crm", "tool": "remarketing.suggest"},
        "rollback_json": {"strategy": "mantener campana en draft hasta preflight y quiet-hours validos"},
    },
    {
        "playbook_key": "lead_prioritization",
        "category": "crm",
        "title": "Priorizar leads calientes",
        "description": "Ordenar oportunidades por prioridad comercial y recomendar follow-up humano.",
        "risk_level": "low",
        "required_autonomy_level": 1,
        "approval_required": False,
        "auto_executable": True,
        "action_type": "crm_priority_report",
        "action_json": {"target": "crm", "side_effect": "report_only"},
        "rollback_json": {"strategy": "descartar reporte; no cambia datos CRM"},
    },
    {
        "playbook_key": "queue_degradation_triage",
        "category": "operations",
        "title": "Triage de degradacion de colas",
        "description": "Agrupar senales de backlog, dead-letter y errores recientes para priorizar operaciones.",
        "risk_level": "low",
        "required_autonomy_level": 1,
        "approval_required": False,
        "auto_executable": True,
        "action_type": "ops_triage_report",
        "action_json": {"target": "operations", "side_effect": "report_only"},
        "rollback_json": {"strategy": "descartar reporte; no modifica colas"},
    },
]

SENSITIVITY_THRESHOLDS: dict[str, dict[str, float]] = {
    "low": {"webhook_errors": 8, "outbound_failed": 12, "dead_letters": 3, "failure_rate": 35, "inactive": 12, "queue_backlog": 60},
    "medium": {"webhook_errors": 4, "outbound_failed": 6, "dead_letters": 1, "failure_rate": 25, "inactive": 6, "queue_backlog": 30},
    "high": {"webhook_errors": 1, "outbound_failed": 2, "dead_letters": 1, "failure_rate": 15, "inactive": 2, "queue_backlog": 10},
}


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
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _row(row: dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    for key in ("settings_json", "action_json", "rollback_json", "evidence_json", "input_json", "result_json", "findings_json", "recommendations_json"):
        if key in data:
            data[key] = _json_value(data.get(key), [] if key.endswith("json") and key in {"findings_json", "recommendations_json"} else {})
    return {key: _jsonable(value) for key, value in data.items()}


def _table_exists(conn: Connection, table_name: str) -> bool:
    return bool(conn.execute(text("SELECT to_regclass(:table_name) IS NOT NULL"), {"table_name": table_name}).scalar())


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _period_day() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def ensure_autonomous_operations_tables(conn: Connection) -> None:
    ensure_intelligence_tables(conn)
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_operation_policies (
                tenant_id UUID PRIMARY KEY REFERENCES saas_tenants(id) ON DELETE CASCADE,
                autonomy_level INTEGER NOT NULL DEFAULT 0,
                auto_remediation_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                low_risk_auto_execute BOOLEAN NOT NULL DEFAULT FALSE,
                sensitivity TEXT NOT NULL DEFAULT 'medium',
                max_daily_actions INTEGER NOT NULL DEFAULT 0,
                approval_required_from_level INTEGER NOT NULL DEFAULT 2,
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
            CREATE TABLE IF NOT EXISTS saas_ai_operation_playbooks (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                playbook_key TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'operations',
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                risk_level TEXT NOT NULL DEFAULT 'medium',
                required_autonomy_level INTEGER NOT NULL DEFAULT 1,
                approval_required BOOLEAN NOT NULL DEFAULT TRUE,
                auto_executable BOOLEAN NOT NULL DEFAULT FALSE,
                action_type TEXT NOT NULL DEFAULT '',
                action_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                rollback_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, playbook_key)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_operation_playbooks_tenant ON saas_ai_operation_playbooks (tenant_id, enabled, category, risk_level)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_operation_anomalies (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                anomaly_type TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'autonomous_operations',
                entity_type TEXT NOT NULL DEFAULT 'tenant',
                entity_id TEXT NOT NULL DEFAULT '',
                severity TEXT NOT NULL DEFAULT 'info',
                confidence NUMERIC(8,4) NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'open',
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                recommended_playbook_key TEXT NOT NULL DEFAULT '',
                first_seen_at TIMESTAMP NOT NULL DEFAULT NOW(),
                last_seen_at TIMESTAMP NOT NULL DEFAULT NOW(),
                occurrence_count INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_saas_ai_operation_anomalies_open
            ON saas_ai_operation_anomalies (tenant_id, anomaly_type, entity_type, entity_id)
            WHERE status = 'open'
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_operation_anomalies_tenant_status ON saas_ai_operation_anomalies (tenant_id, status, severity, last_seen_at DESC)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_operation_actions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                anomaly_id UUID NULL REFERENCES saas_ai_operation_anomalies(id) ON DELETE SET NULL,
                recommendation_id UUID NULL REFERENCES saas_intelligence_recommendations(id) ON DELETE SET NULL,
                playbook_key TEXT NOT NULL DEFAULT '',
                action_type TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                risk_level TEXT NOT NULL DEFAULT 'medium',
                status TEXT NOT NULL DEFAULT 'suggested',
                approval_required BOOLEAN NOT NULL DEFAULT TRUE,
                autonomy_level INTEGER NOT NULL DEFAULT 0,
                confidence NUMERIC(8,4) NOT NULL DEFAULT 0,
                input_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                rollback_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                approved_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                approved_at TIMESTAMP NULL,
                executed_at TIMESTAMP NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_operation_actions_tenant_status ON saas_ai_operation_actions (tenant_id, status, risk_level, created_at DESC)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_operation_actions_anomaly ON saas_ai_operation_actions (tenant_id, anomaly_id, created_at DESC)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_operation_reports (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                report_type TEXT NOT NULL,
                period_key TEXT NOT NULL DEFAULT 'latest',
                title TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                score NUMERIC(8,4) NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'open',
                findings_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                recommendations_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, report_type, period_key)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_operation_reports_tenant ON saas_ai_operation_reports (tenant_id, report_type, updated_at DESC)"))


def seed_autonomous_operations_defaults(conn: Connection, tenant_id: str) -> None:
    ensure_autonomous_operations_tables(conn)
    conn.execute(
        text(
            """
            INSERT INTO saas_ai_operation_policies (tenant_id)
            VALUES (CAST(:tenant_id AS uuid))
            ON CONFLICT (tenant_id) DO NOTHING
            """
        ),
        {"tenant_id": tenant_id},
    )
    for playbook in DEFAULT_PLAYBOOKS:
        conn.execute(
            text(
                """
                INSERT INTO saas_ai_operation_playbooks (
                    tenant_id, playbook_key, category, title, description, risk_level,
                    required_autonomy_level, approval_required, auto_executable,
                    action_type, action_json, rollback_json, enabled, updated_at
                )
                VALUES (
                    CAST(:tenant_id AS uuid), :playbook_key, :category, :title, :description, :risk_level,
                    :required_autonomy_level, :approval_required, :auto_executable,
                    :action_type, CAST(:action_json AS jsonb), CAST(:rollback_json AS jsonb), TRUE, NOW()
                )
                ON CONFLICT (tenant_id, playbook_key)
                DO UPDATE SET
                    category = EXCLUDED.category,
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    risk_level = EXCLUDED.risk_level,
                    required_autonomy_level = EXCLUDED.required_autonomy_level,
                    approval_required = EXCLUDED.approval_required,
                    auto_executable = EXCLUDED.auto_executable,
                    action_type = EXCLUDED.action_type,
                    action_json = EXCLUDED.action_json,
                    rollback_json = EXCLUDED.rollback_json,
                    updated_at = NOW()
                """
            ),
            {"tenant_id": tenant_id, **playbook, "action_json": _json(playbook.get("action_json") or {}), "rollback_json": _json(playbook.get("rollback_json") or {})},
        )


def _operation_access(conn: Connection, tenant_id: str) -> dict[str, Any]:
    entitlements = tenant_entitlements(conn, tenant_id)
    features = entitlements.get("features") if isinstance(entitlements.get("features"), dict) else {}
    state = intelligence_feature_state(conn, tenant_id)
    feature_rows = {str(item.get("key") or ""): dict(item) for item in state.get("features", []) if item.get("key")}
    full = any(
        bool((feature_rows.get(key) or {}).get("enabled")) and str((feature_rows.get(key) or {}).get("mode") or "") == "full"
        for key in ("autonomous_operations", "ai_self_healing", "ai_control_center", "ai_premium")
    ) or bool(features.get("autonomous_operations") or features.get("ai_self_healing") or features.get("ai_premium"))
    demo = any(
        bool((feature_rows.get(key) or {}).get("enabled")) and str((feature_rows.get(key) or {}).get("mode") or "") == "demo"
        for key in ("autonomous_operations", "ai_self_healing", "ai_control_center", "ai_operational_intelligence", "intelligence_demo")
    ) or bool(features.get("intelligence_demo") or entitlements.get("tenant_status") == "trial")
    mode = "full" if full else "demo" if demo else "disabled"
    return {
        "enabled": mode != "disabled",
        "mode": mode,
        "demo_mode": mode == "demo",
        "is_operational": bool(entitlements.get("is_operational")),
        "tenant_status": entitlements.get("tenant_status"),
        "feature_flags": {
            "autonomous_operations": bool(features.get("autonomous_operations")),
            "ai_self_healing": bool(features.get("ai_self_healing")),
            "ai_control_center": bool(features.get("ai_control_center")),
            "ai_operational_intelligence": bool(features.get("ai_operational_intelligence")),
            "ai_premium": bool(features.get("ai_premium")),
            "intelligence_demo": bool(features.get("intelligence_demo")),
        },
        "features": {
            key: {
                "enabled": bool((feature_rows.get(key) or {}).get("enabled")),
                "mode": (feature_rows.get(key) or {}).get("mode") or "disabled",
                "quota_used": int((feature_rows.get(key) or {}).get("quota_used") or 0),
                "quota_monthly": int((feature_rows.get(key) or {}).get("quota_monthly") or 0),
            }
            for key in ("autonomous_operations", "ai_self_healing", "ai_control_center", "ai_operational_intelligence")
        },
    }


def _policy(conn: Connection, tenant_id: str) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            SELECT tenant_id::text, autonomy_level, auto_remediation_enabled,
                   low_risk_auto_execute, sensitivity, max_daily_actions,
                   approval_required_from_level, settings_json,
                   updated_by_user_id::text, created_at::text, updated_at::text
            FROM saas_ai_operation_policies
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    if not row:
        seed_autonomous_operations_defaults(conn, tenant_id)
        return _policy(conn, tenant_id)
    data = _row(dict(row))
    sensitivity = str(data.get("sensitivity") or "medium").lower()
    if sensitivity not in SENSITIVITY_THRESHOLDS:
        data["sensitivity"] = "medium"
    return data


def update_autonomy_policy(conn: Connection, tenant_id: str, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    seed_autonomous_operations_defaults(conn, tenant_id)
    access = _operation_access(conn, tenant_id)
    if not access.get("enabled"):
        raise HTTPException(status_code=403, detail={"code": "autonomous_operations_not_enabled"})
    level = max(0, min(int(payload.get("autonomy_level", 0) or 0), 4))
    sensitivity = _clean(payload.get("sensitivity"), 20).lower() or "medium"
    if sensitivity not in SENSITIVITY_THRESHOLDS:
        sensitivity = "medium"
    max_daily_actions = max(0, min(int(payload.get("max_daily_actions", 0) or 0), 1000))
    approval_level = max(0, min(int(payload.get("approval_required_from_level", 2) or 2), 4))
    auto_remediation = bool(payload.get("auto_remediation_enabled")) and access.get("mode") == "full"
    low_risk_auto = bool(payload.get("low_risk_auto_execute")) and access.get("mode") == "full" and level >= 4
    settings = payload.get("settings_json") if isinstance(payload.get("settings_json"), dict) else {}
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_operation_policies (
                tenant_id, autonomy_level, auto_remediation_enabled, low_risk_auto_execute,
                sensitivity, max_daily_actions, approval_required_from_level,
                settings_json, updated_by_user_id, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), :autonomy_level, :auto_remediation_enabled, :low_risk_auto_execute,
                :sensitivity, :max_daily_actions, :approval_required_from_level,
                CAST(:settings_json AS jsonb), CAST(NULLIF(:updated_by_user_id, '') AS uuid), NOW()
            )
            ON CONFLICT (tenant_id)
            DO UPDATE SET
                autonomy_level = EXCLUDED.autonomy_level,
                auto_remediation_enabled = EXCLUDED.auto_remediation_enabled,
                low_risk_auto_execute = EXCLUDED.low_risk_auto_execute,
                sensitivity = EXCLUDED.sensitivity,
                max_daily_actions = EXCLUDED.max_daily_actions,
                approval_required_from_level = EXCLUDED.approval_required_from_level,
                settings_json = EXCLUDED.settings_json,
                updated_by_user_id = EXCLUDED.updated_by_user_id,
                updated_at = NOW()
            RETURNING tenant_id::text, autonomy_level, auto_remediation_enabled,
                      low_risk_auto_execute, sensitivity, max_daily_actions,
                      approval_required_from_level, settings_json,
                      updated_by_user_id::text, created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "autonomy_level": level,
            "auto_remediation_enabled": auto_remediation,
            "low_risk_auto_execute": low_risk_auto,
            "sensitivity": sensitivity,
            "max_daily_actions": max_daily_actions,
            "approval_required_from_level": approval_level,
            "settings_json": _json(settings),
            "updated_by_user_id": user_id or "",
        },
    ).mappings().first()
    result = _row(dict(row or {}))
    record_event(
        conn,
        tenant_id,
        {
            "event_type": "ai.autonomy_policy.updated",
            "source": "autonomous_operations",
            "entity_type": "policy",
            "entity_id": tenant_id,
            "payload_json": {"policy": result, "mode": access.get("mode")},
            "replay_key": f"autonomy_policy:{tenant_id}:{datetime.now(timezone.utc).isoformat()}",
        },
    )
    return result


def _count(conn: Connection, sql: str, params: dict[str, Any]) -> int:
    try:
        return int(conn.execute(text(sql), params).scalar() or 0)
    except Exception:
        return 0


def _operational_snapshot(conn: Connection, tenant_id: str) -> dict[str, Any]:
    params = {"tenant_id": tenant_id}
    snapshot: dict[str, Any] = {
        "webhook_errors_24h": 0,
        "webhook_backlog": 0,
        "outbound_failed_24h": 0,
        "outbound_retry_backlog": 0,
        "dead_letters_open": 0,
        "campaign_events_7d": 0,
        "campaign_failed_7d": 0,
        "trigger_executions_7d": 0,
        "trigger_failed_7d": 0,
        "inactive_14d": 0,
        "hot_leads": 0,
        "meta_subscription_drift": 0,
        "worker_stale": 0,
    }
    if _table_exists(conn, "saas_webhook_events"):
        snapshot["webhook_errors_24h"] = _count(conn, "SELECT COUNT(*) FROM saas_webhook_events WHERE tenant_id = CAST(:tenant_id AS uuid) AND status IN ('error','failed') AND received_at >= NOW() - INTERVAL '24 hours'", params)
        snapshot["webhook_backlog"] = _count(conn, "SELECT COUNT(*) FROM saas_webhook_events WHERE tenant_id = CAST(:tenant_id AS uuid) AND status IN ('received','pending','processing') AND received_at < NOW() - INTERVAL '15 minutes'", params)
    if _table_exists(conn, "saas_outbound_messages"):
        snapshot["outbound_failed_24h"] = _count(conn, "SELECT COUNT(*) FROM saas_outbound_messages WHERE tenant_id = CAST(:tenant_id AS uuid) AND status IN ('failed','blocked') AND updated_at >= NOW() - INTERVAL '24 hours'", params)
        snapshot["outbound_retry_backlog"] = _count(conn, "SELECT COUNT(*) FROM saas_outbound_messages WHERE tenant_id = CAST(:tenant_id AS uuid) AND status IN ('queued','retry') AND attempts > 0 AND next_attempt_at < NOW()", params)
    if _table_exists(conn, "saas_dead_letter_events"):
        snapshot["dead_letters_open"] = _count(conn, "SELECT COUNT(*) FROM saas_dead_letter_events WHERE tenant_id = CAST(:tenant_id AS uuid) AND status = 'open'", params)
    if _table_exists(conn, "saas_campaign_ab_events"):
        row = conn.execute(
            text(
                """
                SELECT COUNT(*)::int AS total,
                       COUNT(*) FILTER (WHERE outcome IN ('failed','blocked','error'))::int AS failed
                FROM saas_campaign_ab_events
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND created_at >= NOW() - INTERVAL '7 days'
                """
            ),
            params,
        ).mappings().first() or {}
        snapshot["campaign_events_7d"] = int(row.get("total") or 0)
        snapshot["campaign_failed_7d"] = int(row.get("failed") or 0)
    if _table_exists(conn, "saas_trigger_executions"):
        row = conn.execute(
            text(
                """
                SELECT COUNT(*)::int AS total,
                       COUNT(*) FILTER (WHERE status IN ('failed','error','blocked'))::int AS failed
                FROM saas_trigger_executions
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND executed_at >= NOW() - INTERVAL '7 days'
                """
            ),
            params,
        ).mappings().first() or {}
        snapshot["trigger_executions_7d"] = int(row.get("total") or 0)
        snapshot["trigger_failed_7d"] = int(row.get("failed") or 0)
    if _table_exists(conn, "saas_conversations"):
        row = conn.execute(
            text(
                """
                SELECT
                    COUNT(*) FILTER (WHERE last_message_at < NOW() - INTERVAL '14 days')::int AS inactive_14d,
                    COUNT(*) FILTER (WHERE lead_score >= 75 OR LOWER(lead_temperature) = 'hot')::int AS hot_leads
                FROM saas_conversations
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                """
            ),
            params,
        ).mappings().first() or {}
        snapshot["inactive_14d"] = int(row.get("inactive_14d") or 0)
        snapshot["hot_leads"] = int(row.get("hot_leads") or 0)
    if _table_exists(conn, "saas_whatsapp_subscription_checks"):
        snapshot["meta_subscription_drift"] += _count(
            conn,
            """
            SELECT COUNT(*) FROM (
                SELECT DISTINCT ON (COALESCE(integration_id::text, waba_id)) final_subscribed, status, created_at
                FROM saas_whatsapp_subscription_checks
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                ORDER BY COALESCE(integration_id::text, waba_id), created_at DESC
            ) latest
            WHERE final_subscribed = FALSE OR status IN ('error','failed','not_subscribed','subscription_not_confirmed')
            """,
            params,
        )
    if _table_exists(conn, "saas_instagram_subscription_checks"):
        snapshot["meta_subscription_drift"] += _count(
            conn,
            """
            SELECT COUNT(*) FROM (
                SELECT DISTINCT ON (COALESCE(integration_id::text, page_id)) final_subscribed, status, created_at
                FROM saas_instagram_subscription_checks
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                ORDER BY COALESCE(integration_id::text, page_id), created_at DESC
            ) latest
            WHERE final_subscribed = FALSE OR status IN ('error','failed','not_subscribed','subscription_not_confirmed')
            """,
            params,
        )
    if _table_exists(conn, "saas_worker_heartbeats"):
        snapshot["worker_stale"] = _count(
            conn,
            """
            SELECT COUNT(*) FROM saas_worker_heartbeats
            WHERE last_seen_at < NOW() - INTERVAL '30 minutes'
               OR status IN ('error','failed','degraded')
            """,
            {},
        )
    campaign_total = max(0, int(snapshot["campaign_events_7d"]))
    trigger_total = max(0, int(snapshot["trigger_executions_7d"]))
    snapshot["campaign_failure_rate"] = round((int(snapshot["campaign_failed_7d"]) / campaign_total) * 100, 2) if campaign_total else 0
    snapshot["trigger_failure_rate"] = round((int(snapshot["trigger_failed_7d"]) / trigger_total) * 100, 2) if trigger_total else 0
    return snapshot


def _candidate_anomalies(snapshot: dict[str, Any], policy: dict[str, Any]) -> list[dict[str, Any]]:
    sensitivity = str(policy.get("sensitivity") or "medium").lower()
    thresholds = SENSITIVITY_THRESHOLDS.get(sensitivity) or SENSITIVITY_THRESHOLDS["medium"]
    anomalies: list[dict[str, Any]] = []

    def add(key: str, title: str, description: str, severity: str, confidence: float, playbook: str, evidence: dict[str, Any], entity_type: str = "tenant", entity_id: str = "") -> None:
        anomalies.append(
            {
                "anomaly_type": key,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "severity": severity,
                "confidence": max(0.0, min(float(confidence), 100.0)),
                "title": title,
                "description": description,
                "recommended_playbook_key": playbook,
                "evidence_json": {**evidence, "sensitivity": sensitivity},
            }
        )

    if snapshot["webhook_errors_24h"] >= thresholds["webhook_errors"]:
        add("webhook_failures", "Webhooks con fallos recientes", "Se detectaron errores de procesamiento webhook en las ultimas 24 horas.", "high", min(100, 55 + snapshot["webhook_errors_24h"] * 5), "retry_webhook_events", snapshot)
    if snapshot["webhook_backlog"] >= thresholds["queue_backlog"]:
        add("webhook_backlog", "Backlog webhook envejecido", "Hay eventos webhook pendientes con mas de 15 minutos sin procesar.", "warning", min(100, 50 + snapshot["webhook_backlog"]), "queue_degradation_triage", snapshot)
    if snapshot["outbound_failed_24h"] >= thresholds["outbound_failed"] or snapshot["outbound_retry_backlog"] >= thresholds["queue_backlog"]:
        add("outbound_retry_storm", "Cola outbound degradada", "La cola saliente muestra fallos, bloqueos o retries acumulados.", "high", min(100, 55 + snapshot["outbound_failed_24h"] * 4 + snapshot["outbound_retry_backlog"]), "retry_outbound_queue", snapshot)
    if snapshot["dead_letters_open"] >= thresholds["dead_letters"]:
        add("dead_letter_open", "Dead-letter abierto", "Existen errores operativos abiertos que requieren diagnostico o reintento controlado.", "critical" if snapshot["dead_letters_open"] >= 5 else "high", min(100, 65 + snapshot["dead_letters_open"] * 6), "queue_degradation_triage", snapshot)
    if snapshot["meta_subscription_drift"] > 0:
        add("meta_subscription_drift", "Drift en subscribed_apps Meta", "La ultima verificacion indica suscripciones Meta incompletas o fallidas.", "critical", 88, "resubscribe_meta_webhooks", snapshot, entity_type="integration", entity_id="meta")
    if snapshot["campaign_events_7d"] >= 10 and snapshot["campaign_failure_rate"] >= thresholds["failure_rate"]:
        add("campaign_low_performance", "Campana con bajo rendimiento operativo", "La telemetria de campanas muestra tasa alta de fallos o bloqueos.", "warning", min(100, 50 + snapshot["campaign_failure_rate"]), "optimize_campaign_send_time", snapshot, entity_type="campaign", entity_id="all")
    if snapshot["trigger_executions_7d"] >= 5 and snapshot["trigger_failure_rate"] >= thresholds["failure_rate"]:
        add("trigger_degradation", "Triggers con degradacion", "Los triggers recientes muestran una tasa de fallos superior al umbral de sensibilidad.", "warning", min(100, 50 + snapshot["trigger_failure_rate"]), "optimize_trigger_timing", snapshot, entity_type="trigger", entity_id="all")
    if snapshot["inactive_14d"] >= thresholds["inactive"]:
        add("customer_inactivity_risk", "Clientes inactivos acumulados", "Hay clientes sin actividad suficiente para activar recuperacion o remarketing.", "medium", min(100, 45 + snapshot["inactive_14d"] * 3), "churn_recovery", snapshot, entity_type="crm", entity_id="inactive_14d")
    if snapshot["hot_leads"] >= 3:
        add("sales_opportunity_detected", "Leads calientes pendientes", "Hay oportunidades comerciales que conviene priorizar con follow-up humano o agente de ventas.", "info", min(100, 50 + snapshot["hot_leads"] * 4), "lead_prioritization", snapshot, entity_type="crm", entity_id="hot_leads")
    if snapshot["worker_stale"] > 0:
        add("worker_degradation", "Worker potencialmente degradado", "Uno o mas workers tienen heartbeat viejo o estado degradado.", "critical", 90, "queue_degradation_triage", snapshot, entity_type="worker", entity_id="global")
    return anomalies


def _upsert_anomaly(conn: Connection, tenant_id: str, item: dict[str, Any]) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_operation_anomalies (
                tenant_id, anomaly_type, source, entity_type, entity_id, severity, confidence,
                status, title, description, evidence_json, recommended_playbook_key,
                first_seen_at, last_seen_at, occurrence_count, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), :anomaly_type, 'autonomous_operations', :entity_type, :entity_id,
                :severity, :confidence, 'open', :title, :description, CAST(:evidence_json AS jsonb),
                :recommended_playbook_key, NOW(), NOW(), 1, NOW()
            )
            ON CONFLICT (tenant_id, anomaly_type, entity_type, entity_id) WHERE status = 'open'
            DO UPDATE SET
                severity = EXCLUDED.severity,
                confidence = GREATEST(saas_ai_operation_anomalies.confidence, EXCLUDED.confidence),
                title = EXCLUDED.title,
                description = EXCLUDED.description,
                evidence_json = saas_ai_operation_anomalies.evidence_json || EXCLUDED.evidence_json,
                recommended_playbook_key = EXCLUDED.recommended_playbook_key,
                last_seen_at = NOW(),
                occurrence_count = saas_ai_operation_anomalies.occurrence_count + 1,
                updated_at = NOW()
            RETURNING id::text, tenant_id::text, anomaly_type, source, entity_type, entity_id,
                      severity, confidence, status, title, description, evidence_json,
                      recommended_playbook_key, first_seen_at::text, last_seen_at::text,
                      occurrence_count, created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "anomaly_type": _clean(item.get("anomaly_type"), 120),
            "entity_type": _clean(item.get("entity_type"), 80) or "tenant",
            "entity_id": _clean(item.get("entity_id"), 160),
            "severity": _clean(item.get("severity"), 40) or "info",
            "confidence": float(item.get("confidence") or 0),
            "title": _clean(item.get("title"), 220),
            "description": _clean(item.get("description"), 1200),
            "evidence_json": _json(item.get("evidence_json") or {}),
            "recommended_playbook_key": _clean(item.get("recommended_playbook_key"), 120),
        },
    ).mappings().first()
    return _row(dict(row or {}))


def _playbook(conn: Connection, tenant_id: str, playbook_key: str) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            SELECT id::text, tenant_id::text, playbook_key, category, title, description,
                   risk_level, required_autonomy_level, approval_required, auto_executable,
                   action_type, action_json, rollback_json, enabled,
                   created_at::text, updated_at::text
            FROM saas_ai_operation_playbooks
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND playbook_key = :playbook_key
              AND enabled = TRUE
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "playbook_key": playbook_key},
    ).mappings().first()
    return _row(dict(row or {})) if row else {}


def _daily_action_count(conn: Connection, tenant_id: str) -> int:
    return _count(
        conn,
        """
        SELECT COUNT(*) FROM saas_ai_operation_actions
        WHERE tenant_id = CAST(:tenant_id AS uuid)
          AND created_at >= date_trunc('day', NOW())
        """,
        {"tenant_id": tenant_id},
    )


def _action_exists(conn: Connection, tenant_id: str, anomaly_id: str, playbook_key: str) -> bool:
    return bool(
        conn.execute(
            text(
                """
                SELECT 1
                FROM saas_ai_operation_actions
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND anomaly_id = CAST(:anomaly_id AS uuid)
                  AND playbook_key = :playbook_key
                  AND status IN ('suggested','pending_approval','approved','executing')
                LIMIT 1
                """
            ),
            {"tenant_id": tenant_id, "anomaly_id": anomaly_id, "playbook_key": playbook_key},
        ).first()
    )


def _create_action_from_anomaly(conn: Connection, tenant_id: str, anomaly: dict[str, Any], policy: dict[str, Any], access: dict[str, Any]) -> dict[str, Any] | None:
    level = int(policy.get("autonomy_level") or 0)
    if level < 2:
        return None
    playbook_key = _clean(anomaly.get("recommended_playbook_key"), 120)
    playbook = _playbook(conn, tenant_id, playbook_key)
    if not playbook or level < int(playbook.get("required_autonomy_level") or 1):
        return None
    if _action_exists(conn, tenant_id, str(anomaly.get("id") or ""), playbook_key):
        return None
    max_daily = int(policy.get("max_daily_actions") or 0)
    if max_daily > 0 and _daily_action_count(conn, tenant_id) >= max_daily:
        return None
    risk = _clean(playbook.get("risk_level"), 40) or "medium"
    approval_required = bool(playbook.get("approval_required")) or level >= int(policy.get("approval_required_from_level") or 2) or risk in {"medium", "high", "critical"}
    can_auto_execute = (
        access.get("mode") == "full"
        and level >= 4
        and bool(policy.get("auto_remediation_enabled"))
        and bool(policy.get("low_risk_auto_execute"))
        and bool(playbook.get("auto_executable"))
        and risk == "low"
        and not approval_required
    )
    status = "executed" if can_auto_execute else "pending_approval" if level >= 3 else "suggested"
    result_json = {
        "execution_mode": "controlled_record",
        "side_effects": "none",
        "auto_executed": bool(can_auto_execute),
        "note": "Autonomous Operations records/coordinates this action; provider or queue mutations require explicit approved processors.",
    }
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_operation_actions (
                tenant_id, anomaly_id, playbook_key, action_type, title, description,
                risk_level, status, approval_required, autonomy_level, confidence,
                input_json, result_json, rollback_json, executed_at, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), CAST(:anomaly_id AS uuid), :playbook_key, :action_type,
                :title, :description, :risk_level, :status, :approval_required, :autonomy_level,
                :confidence, CAST(:input_json AS jsonb), CAST(:result_json AS jsonb),
                CAST(:rollback_json AS jsonb), CASE WHEN :executed THEN NOW() ELSE NULL END, NOW()
            )
            RETURNING id::text, tenant_id::text, anomaly_id::text, recommendation_id::text,
                      playbook_key, action_type, title, description, risk_level, status,
                      approval_required, autonomy_level, confidence, input_json, result_json,
                      rollback_json, approved_by_user_id::text, created_by_user_id::text,
                      approved_at::text, executed_at::text, created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "anomaly_id": anomaly.get("id"),
            "playbook_key": playbook_key,
            "action_type": _clean(playbook.get("action_type"), 120),
            "title": f"{playbook.get('title')}: {anomaly.get('title')}",
            "description": _clean(playbook.get("description"), 1200),
            "risk_level": risk,
            "status": status,
            "approval_required": approval_required,
            "autonomy_level": level,
            "confidence": float(anomaly.get("confidence") or 0),
            "input_json": _json({"anomaly": anomaly, "playbook": playbook, "policy": policy}),
            "result_json": _json(result_json),
            "rollback_json": _json(playbook.get("rollback_json") or {}),
            "executed": can_auto_execute,
        },
    ).mappings().first()
    action = _row(dict(row or {}))
    record_event(
        conn,
        tenant_id,
        {
            "event_type": "ai.autonomous_action.generated" if not can_auto_execute else "ai.autonomous_action.executed",
            "source": "autonomous_operations",
            "entity_type": "operation_action",
            "entity_id": action.get("id", ""),
            "payload_json": {"action": action, "anomaly_id": anomaly.get("id"), "playbook_key": playbook_key},
            "replay_key": f"autonomous_action:{action.get('id', '')}",
        },
    )
    return action


def _upsert_report(conn: Connection, tenant_id: str, snapshot: dict[str, Any], anomalies: list[dict[str, Any]], actions: list[dict[str, Any]], access: dict[str, Any]) -> dict[str, Any]:
    risk_score = min(
        100.0,
        snapshot["webhook_errors_24h"] * 5
        + snapshot["outbound_failed_24h"] * 4
        + snapshot["dead_letters_open"] * 8
        + snapshot["meta_subscription_drift"] * 20
        + snapshot["campaign_failure_rate"]
        + snapshot["trigger_failure_rate"],
    )
    findings = [
        {"key": key, "value": value}
        for key, value in snapshot.items()
        if isinstance(value, (int, float)) and float(value) > 0
    ]
    recommendations = [
        {"anomaly_type": item.get("anomaly_type"), "playbook": item.get("recommended_playbook_key"), "severity": item.get("severity")}
        for item in anomalies[:12]
    ]
    title = "Operacion estable" if risk_score < 25 else "Operacion en observacion" if risk_score < 60 else "Riesgo operativo alto"
    summary = (
        f"{len(anomalies)} anomalias abiertas o actualizadas, {len(actions)} acciones generadas, "
        f"score operativo {round(risk_score, 2)} en modo {access.get('mode')}."
    )
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_operation_reports (
                tenant_id, report_type, period_key, title, summary, score, status,
                findings_json, recommendations_json, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), 'daily_operations', :period_key, :title, :summary,
                :score, 'open', CAST(:findings_json AS jsonb), CAST(:recommendations_json AS jsonb), NOW()
            )
            ON CONFLICT (tenant_id, report_type, period_key)
            DO UPDATE SET
                title = EXCLUDED.title,
                summary = EXCLUDED.summary,
                score = EXCLUDED.score,
                findings_json = EXCLUDED.findings_json,
                recommendations_json = EXCLUDED.recommendations_json,
                updated_at = NOW()
            RETURNING id::text, tenant_id::text, report_type, period_key, title, summary,
                      score, status, findings_json, recommendations_json,
                      created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "period_key": _period_day(),
            "title": title,
            "summary": summary,
            "score": risk_score,
            "findings_json": _json(findings),
            "recommendations_json": _json(recommendations),
        },
    ).mappings().first()
    return _row(dict(row or {}))


def run_operational_intelligence_analysis(
    conn: Connection,
    tenant_id: str,
    *,
    actor_user_id: str = "",
    dry_run: bool = False,
    limit: int = 50,
) -> dict[str, Any]:
    seed_autonomous_operations_defaults(conn, tenant_id)
    access = _operation_access(conn, tenant_id)
    policy = _policy(conn, tenant_id)
    if not access.get("is_operational"):
        return {"skipped": True, "reason": "tenant_not_operational", "access": access, "policy": policy}
    if not access.get("enabled"):
        return {"skipped": True, "reason": "autonomous_operations_not_enabled", "access": access, "policy": policy}
    try:
        record_intelligence_usage(conn, tenant_id, "autonomous_operations", metadata={"source": "operations_analysis", "dry_run": dry_run})
    except HTTPException as exc:
        return {"skipped": True, "reason": "quota_or_access", "detail": exc.detail, "access": access, "policy": policy}
    snapshot = _operational_snapshot(conn, tenant_id)
    candidates = _candidate_anomalies(snapshot, policy)[: max(1, min(int(limit or 50), 200))]
    if dry_run:
        return {
            "skipped": False,
            "dry_run": True,
            "access": access,
            "policy": policy,
            "snapshot": snapshot,
            "candidate_anomalies": candidates,
            "created_anomalies": [],
            "created_actions": [],
            "report": {},
        }
    created_anomalies: list[dict[str, Any]] = []
    created_actions: list[dict[str, Any]] = []
    for candidate in candidates:
        anomaly = _upsert_anomaly(conn, tenant_id, candidate)
        created_anomalies.append(anomaly)
        action = _create_action_from_anomaly(conn, tenant_id, anomaly, policy, access)
        if action:
            created_actions.append(action)
    report = _upsert_report(conn, tenant_id, snapshot, created_anomalies, created_actions, access)
    if created_anomalies or created_actions:
        record_event(
            conn,
            tenant_id,
            {
                "event_type": "ai.operations.analysis_completed",
                "source": "autonomous_operations",
                "entity_type": "tenant",
                "entity_id": tenant_id,
                "payload_json": {
                    "snapshot": snapshot,
                    "anomalies": len(created_anomalies),
                    "actions": len(created_actions),
                    "report_id": report.get("id", ""),
                    "actor_user_id": actor_user_id,
                },
                "replay_key": f"ops_analysis:{tenant_id}:{_period_day()}",
            },
        )
    return {
        "skipped": False,
        "dry_run": False,
        "access": access,
        "policy": policy,
        "snapshot": snapshot,
        "candidate_anomalies": candidates,
        "created_anomalies": created_anomalies,
        "created_actions": created_actions,
        "report": report,
    }


def _list_anomalies(conn: Connection, tenant_id: str, *, status: str = "open", limit: int = 50) -> list[dict[str, Any]]:
    where = ["tenant_id = CAST(:tenant_id AS uuid)"]
    params: dict[str, Any] = {"tenant_id": tenant_id, "limit": max(1, min(int(limit or 50), 200))}
    clean_status = _clean(status, 40).lower()
    if clean_status and clean_status != "all":
        where.append("status = :status")
        params["status"] = clean_status
    rows = conn.execute(
        text(
            f"""
            SELECT id::text, tenant_id::text, anomaly_type, source, entity_type, entity_id,
                   severity, confidence, status, title, description, evidence_json,
                   recommended_playbook_key, first_seen_at::text, last_seen_at::text,
                   occurrence_count, created_at::text, updated_at::text
            FROM saas_ai_operation_anomalies
            WHERE {" AND ".join(where)}
            ORDER BY
                CASE severity WHEN 'critical' THEN 4 WHEN 'high' THEN 3 WHEN 'warning' THEN 2 WHEN 'medium' THEN 1 ELSE 0 END DESC,
                last_seen_at DESC
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()
    return [_row(dict(row)) for row in rows]


def list_autonomous_actions(conn: Connection, tenant_id: str, *, status: str = "all", limit: int = 50) -> list[dict[str, Any]]:
    ensure_autonomous_operations_tables(conn)
    where = ["a.tenant_id = CAST(:tenant_id AS uuid)"]
    params: dict[str, Any] = {"tenant_id": tenant_id, "limit": max(1, min(int(limit or 50), 200))}
    clean_status = _clean(status, 40).lower()
    if clean_status and clean_status != "all":
        where.append("a.status = :status")
        params["status"] = clean_status
    rows = conn.execute(
        text(
            f"""
            SELECT a.id::text, a.tenant_id::text, a.anomaly_id::text, an.anomaly_type,
                   a.recommendation_id::text, a.playbook_key, a.action_type, a.title,
                   a.description, a.risk_level, a.status, a.approval_required,
                   a.autonomy_level, a.confidence, a.input_json, a.result_json,
                   a.rollback_json, a.approved_by_user_id::text, a.created_by_user_id::text,
                   a.approved_at::text, a.executed_at::text, a.created_at::text, a.updated_at::text
            FROM saas_ai_operation_actions a
            LEFT JOIN saas_ai_operation_anomalies an ON an.id = a.anomaly_id AND an.tenant_id = a.tenant_id
            WHERE {" AND ".join(where)}
            ORDER BY a.created_at DESC
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()
    return [_row(dict(row)) for row in rows]


def _list_reports(conn: Connection, tenant_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT id::text, tenant_id::text, report_type, period_key, title, summary,
                   score, status, findings_json, recommendations_json,
                   created_at::text, updated_at::text
            FROM saas_ai_operation_reports
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY updated_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "limit": max(1, min(int(limit or 20), 100))},
    ).mappings().all()
    return [_row(dict(row)) for row in rows]


def _list_playbooks(conn: Connection, tenant_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT id::text, tenant_id::text, playbook_key, category, title, description,
                   risk_level, required_autonomy_level, approval_required, auto_executable,
                   action_type, action_json, rollback_json, enabled, created_at::text, updated_at::text
            FROM saas_ai_operation_playbooks
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY category ASC, risk_level DESC, playbook_key ASC
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().all()
    return [_row(dict(row)) for row in rows]


def autonomous_operations_center(conn: Connection, tenant_id: str, *, limit: int = 50) -> dict[str, Any]:
    seed_autonomous_operations_defaults(conn, tenant_id)
    access = _operation_access(conn, tenant_id)
    policy = _policy(conn, tenant_id)
    snapshot = _operational_snapshot(conn, tenant_id)
    anomalies = _list_anomalies(conn, tenant_id, status="open", limit=limit)
    actions = list_autonomous_actions(conn, tenant_id, limit=limit)
    reports = _list_reports(conn, tenant_id, limit=20)
    predictive = predictive_business_overview(conn, tenant_id, limit=20)
    recommendations = list_recommendations(conn, tenant_id, status="open", limit=20)
    counts = {
        "open_anomalies": len(anomalies),
        "pending_actions": sum(1 for item in actions if item.get("status") in {"suggested", "pending_approval", "approved"}),
        "executed_actions": sum(1 for item in actions if item.get("status") == "executed"),
        "critical_anomalies": sum(1 for item in anomalies if item.get("severity") == "critical"),
        "open_recommendations": len(recommendations),
    }
    return {
        "version": "phase_11_autonomous_operational_intelligence",
        "tenant_id": tenant_id,
        "access": access,
        "policy": policy,
        "autonomy_levels": AUTONOMY_LEVELS,
        "snapshot": snapshot,
        "counts": counts,
        "anomalies": anomalies,
        "actions": actions,
        "reports": reports,
        "playbooks": _list_playbooks(conn, tenant_id),
        "predictive": {
            "cards": predictive.get("cards", []),
            "executive_summaries": predictive.get("executive_summaries", {}),
            "observability": predictive.get("observability", {}),
        },
        "recommendations": recommendations,
        "governance": {
            "critical_actions": "approval_required",
            "low_risk_level_4": "controlled_record_only_unless_domain_processor_is_explicitly_called",
            "rollback": "rollback_json_required_per_playbook",
            "audit": "saas_intelligence_events_and_operation_actions",
            "tenant_isolation": "tenant_id_required_on_all_operation_tables",
        },
    }


def approve_autonomous_action(conn: Connection, tenant_id: str, user_id: str, action_id: str) -> dict[str, Any]:
    ensure_autonomous_operations_tables(conn)
    row = conn.execute(
        text(
            """
            UPDATE saas_ai_operation_actions
            SET status = 'approved',
                approved_by_user_id = CAST(:user_id AS uuid),
                approved_at = NOW(),
                updated_at = NOW()
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:action_id AS uuid)
              AND status IN ('suggested','pending_approval')
            RETURNING id::text, tenant_id::text, anomaly_id::text, recommendation_id::text,
                      playbook_key, action_type, title, description, risk_level, status,
                      approval_required, autonomy_level, confidence, input_json, result_json,
                      rollback_json, approved_by_user_id::text, created_by_user_id::text,
                      approved_at::text, executed_at::text, created_at::text, updated_at::text
            """
        ),
        {"tenant_id": tenant_id, "action_id": action_id, "user_id": user_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail={"code": "autonomous_action_not_found_or_not_approvable"})
    action = _row(dict(row))
    record_event(
        conn,
        tenant_id,
        {
            "event_type": "ai.autonomous_action.approved",
            "source": "autonomous_operations",
            "entity_type": "operation_action",
            "entity_id": action_id,
            "payload_json": {"action_id": action_id, "approved_by_user_id": user_id},
            "replay_key": f"autonomous_action_approved:{action_id}:{datetime.now(timezone.utc).isoformat()}",
        },
    )
    return action


def execute_autonomous_action(conn: Connection, tenant_id: str, user_id: str, action_id: str, *, dry_run: bool = False) -> dict[str, Any]:
    ensure_autonomous_operations_tables(conn)
    action_row = conn.execute(
        text(
            """
            SELECT id::text, tenant_id::text, playbook_key, action_type, title, description,
                   risk_level, status, approval_required, autonomy_level, input_json,
                   result_json, rollback_json
            FROM saas_ai_operation_actions
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:action_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "action_id": action_id},
    ).mappings().first()
    if not action_row:
        raise HTTPException(status_code=404, detail={"code": "autonomous_action_not_found"})
    action = _row(dict(action_row))
    access = _operation_access(conn, tenant_id)
    if access.get("mode") != "full":
        raise HTTPException(status_code=403, detail={"code": "autonomous_execution_requires_full_mode"})
    if action.get("approval_required") and action.get("status") != "approved":
        raise HTTPException(status_code=403, detail={"code": "autonomous_action_requires_approval"})
    if action.get("risk_level") not in {"low", "medium"} and action.get("status") != "approved":
        raise HTTPException(status_code=403, detail={"code": "high_risk_action_requires_explicit_approval"})
    result_json = {
        **(_json_value(action.get("result_json"), {}) if isinstance(action.get("result_json"), (str, dict)) else {}),
        "dry_run": bool(dry_run),
        "executed_by_user_id": user_id,
        "execution_mode": "controlled_record",
        "side_effects": "none",
        "message": "Execution recorded. Domain-specific provider/queue mutations remain behind existing approved processors.",
    }
    status = "approved" if dry_run else "executed"
    row = conn.execute(
        text(
            """
            UPDATE saas_ai_operation_actions
            SET status = :status,
                result_json = CAST(:result_json AS jsonb),
                executed_at = CASE WHEN :dry_run THEN executed_at ELSE NOW() END,
                updated_at = NOW()
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:action_id AS uuid)
            RETURNING id::text, tenant_id::text, anomaly_id::text, recommendation_id::text,
                      playbook_key, action_type, title, description, risk_level, status,
                      approval_required, autonomy_level, confidence, input_json, result_json,
                      rollback_json, approved_by_user_id::text, created_by_user_id::text,
                      approved_at::text, executed_at::text, created_at::text, updated_at::text
            """
        ),
        {"tenant_id": tenant_id, "action_id": action_id, "status": status, "result_json": _json(result_json), "dry_run": bool(dry_run)},
    ).mappings().first()
    updated = _row(dict(row or {}))
    record_event(
        conn,
        tenant_id,
        {
            "event_type": "ai.autonomous_action.dry_run" if dry_run else "ai.autonomous_action.executed",
            "source": "autonomous_operations",
            "entity_type": "operation_action",
            "entity_id": action_id,
            "payload_json": {"action": updated, "dry_run": dry_run},
            "replay_key": f"autonomous_action_execute:{action_id}:{'dry' if dry_run else 'run'}:{datetime.now(timezone.utc).isoformat()}",
        },
    )
    return updated


def dismiss_autonomous_action(conn: Connection, tenant_id: str, user_id: str, action_id: str) -> dict[str, Any]:
    ensure_autonomous_operations_tables(conn)
    row = conn.execute(
        text(
            """
            UPDATE saas_ai_operation_actions
            SET status = 'dismissed',
                result_json = result_json || CAST(:result_json AS jsonb),
                updated_at = NOW()
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:action_id AS uuid)
              AND status <> 'executed'
            RETURNING id::text, tenant_id::text, anomaly_id::text, recommendation_id::text,
                      playbook_key, action_type, title, description, risk_level, status,
                      approval_required, autonomy_level, confidence, input_json, result_json,
                      rollback_json, approved_by_user_id::text, created_by_user_id::text,
                      approved_at::text, executed_at::text, created_at::text, updated_at::text
            """
        ),
        {"tenant_id": tenant_id, "action_id": action_id, "result_json": _json({"dismissed_by_user_id": user_id})},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail={"code": "autonomous_action_not_found_or_not_dismissible"})
    return _row(dict(row))
