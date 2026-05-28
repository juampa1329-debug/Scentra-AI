from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app_saas.intelligence.service import ensure_intelligence_tables, intelligence_feature_state, record_event, record_intelligence_usage


REVENUE_FEATURE_KEYS = (
    "autonomous_revenue_engine",
    "revenue_opportunity_detection",
    "revenue_forecasting",
    "revenue_playbooks",
    "revenue_experiments",
)
REVENUE_FULL_KEYS = ("autonomous_revenue_engine", "ai_premium")


REVENUE_PLAYBOOKS: list[dict[str, Any]] = [
    {
        "playbook_key": "hot_lead_followup",
        "category": "conversion",
        "title": "Follow-up a leads calientes",
        "description": "Prioriza conversaciones con alta intencion y propone seguimiento humano o plantilla revisada.",
        "risk_level": "low",
        "action_type": "crm_followup_draft",
    },
    {
        "playbook_key": "payment_recovery",
        "category": "recovery",
        "title": "Recuperar pagos pendientes",
        "description": "Detecta leads con pago pendiente y sugiere recuperacion sin enviar mensajes automaticamente.",
        "risk_level": "medium",
        "action_type": "payment_recovery_plan",
    },
    {
        "playbook_key": "inactive_warm_lead_winback",
        "category": "winback",
        "title": "Reactivar leads tibios inactivos",
        "description": "Agrupa oportunidades con engagement previo e inactividad para campanas futuras aprobadas.",
        "risk_level": "medium",
        "action_type": "winback_campaign_draft",
    },
    {
        "playbook_key": "proposal_close_assist",
        "category": "closing",
        "title": "Asistencia de cierre",
        "description": "Detecta oportunidades en cotizacion/propuesta y recomienda siguiente accion comercial.",
        "risk_level": "low",
        "action_type": "close_assist_report",
    },
]


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
        "allowed_action_types_json",
        "settings_json",
        "recommended_action_json",
        "evidence_json",
        "approval_json",
        "execution_result_json",
        "scenario_json",
        "source_json",
        "variants_json",
        "guardrails_json",
        "result_json",
        "findings_json",
        "recommendations_json",
        "metrics_json",
    ):
        if key in data:
            data[key] = _json_value(data.get(key), [] if key.endswith("_json") and key in {"findings_json", "recommendations_json", "variants_json", "allowed_action_types_json"} else {})
    return {key: _jsonable(value) for key, value in data.items()}


def _period_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m")


def _feature_map(conn: Connection, tenant_id: str) -> dict[str, dict[str, Any]]:
    state = intelligence_feature_state(conn, tenant_id)
    return {str(item.get("key") or ""): item for item in state.get("features", [])}


def revenue_access(conn: Connection, tenant_id: str) -> dict[str, Any]:
    features = _feature_map(conn, tenant_id)
    items = {key: features.get(key, {"key": key, "enabled": False, "mode": "disabled"}) for key in REVENUE_FEATURE_KEYS}
    full = any(bool((features.get(key) or {}).get("enabled")) and str((features.get(key) or {}).get("mode") or "") == "full" for key in REVENUE_FULL_KEYS)
    enabled = full or any(bool(item.get("enabled")) for item in items.values())
    mode = "full" if full else "demo" if enabled else "disabled"
    return {"enabled": enabled, "full": full, "mode": mode, "features": items}


def _require_revenue_access(conn: Connection, tenant_id: str, *, allow_demo: bool) -> dict[str, Any]:
    access = revenue_access(conn, tenant_id)
    if not access.get("enabled"):
        raise HTTPException(status_code=403, detail={"code": "intelligence_feature_not_enabled", "feature": "autonomous_revenue_engine"})
    if not allow_demo and not access.get("full"):
        raise HTTPException(status_code=403, detail={"code": "intelligence_feature_requires_full", "feature": "autonomous_revenue_engine"})
    return access


def ensure_revenue_tables(conn: Connection) -> None:
    ensure_intelligence_tables(conn)
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_revenue_policies (
                tenant_id UUID PRIMARY KEY REFERENCES saas_tenants(id) ON DELETE CASCADE,
                autonomy_level INTEGER NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'USD',
                revenue_goal_cents BIGINT NOT NULL DEFAULT 0,
                approval_required_min_value_cents BIGINT NOT NULL DEFAULT 0,
                max_monthly_revenue_actions INTEGER NOT NULL DEFAULT 0,
                auto_execute_low_risk BOOLEAN NOT NULL DEFAULT FALSE,
                allowed_action_types_json JSONB NOT NULL DEFAULT '[]'::jsonb,
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
            CREATE TABLE IF NOT EXISTS saas_ai_revenue_opportunities (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                opportunity_key TEXT NOT NULL,
                source_type TEXT NOT NULL DEFAULT '',
                source_id TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT 'conversion',
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                estimated_value_cents BIGINT NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'USD',
                confidence NUMERIC(8,4) NOT NULL DEFAULT 0,
                priority_score NUMERIC(8,4) NOT NULL DEFAULT 0,
                stage TEXT NOT NULL DEFAULT 'detected',
                status TEXT NOT NULL DEFAULT 'suggested',
                recommended_action_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                approval_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                execution_result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                approved_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                executed_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                approved_at TIMESTAMP NULL,
                executed_at TIMESTAMP NULL,
                expires_at TIMESTAMP NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, opportunity_key)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_revenue_opportunities_tenant_status ON saas_ai_revenue_opportunities (tenant_id, status, priority_score DESC, updated_at DESC)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_revenue_opportunities_source ON saas_ai_revenue_opportunities (tenant_id, source_type, source_id, category)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_revenue_forecasts (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                period_key TEXT NOT NULL DEFAULT 'latest',
                forecast_type TEXT NOT NULL DEFAULT 'pipeline',
                forecast_value_cents BIGINT NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'USD',
                confidence NUMERIC(8,4) NOT NULL DEFAULT 0,
                scenario_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                source_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, period_key, forecast_type)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_revenue_forecasts_tenant ON saas_ai_revenue_forecasts (tenant_id, period_key, forecast_type)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_revenue_experiments (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                experiment_key TEXT NOT NULL,
                title TEXT NOT NULL,
                hypothesis TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft',
                target_metric TEXT NOT NULL DEFAULT 'conversion_rate',
                variants_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                guardrails_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, experiment_key)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_revenue_experiments_tenant_status ON saas_ai_revenue_experiments (tenant_id, status, updated_at DESC)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_revenue_reports (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                report_key TEXT NOT NULL,
                report_type TEXT NOT NULL DEFAULT 'analysis',
                title TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                score NUMERIC(8,4) NOT NULL DEFAULT 0,
                findings_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                recommendations_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, report_key)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_revenue_reports_tenant ON saas_ai_revenue_reports (tenant_id, report_type, updated_at DESC)"))


def revenue_policy(conn: Connection, tenant_id: str) -> dict[str, Any]:
    ensure_revenue_tables(conn)
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_revenue_policies (tenant_id)
            VALUES (CAST(:tenant_id AS uuid))
            ON CONFLICT (tenant_id) DO NOTHING
            RETURNING tenant_id::text
            """
        ),
        {"tenant_id": tenant_id},
    ).first()
    data = conn.execute(
        text(
            """
            SELECT tenant_id::text, autonomy_level, currency, revenue_goal_cents,
                   approval_required_min_value_cents, max_monthly_revenue_actions,
                   auto_execute_low_risk, allowed_action_types_json, settings_json,
                   COALESCE(updated_by_user_id::text, '') AS updated_by_user_id,
                   created_at::text, updated_at::text
            FROM saas_ai_revenue_policies
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    return _row(dict(data or {}))


def update_revenue_policy(conn: Connection, tenant_id: str, actor_user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    ensure_revenue_tables(conn)
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_revenue_policies (
                tenant_id, autonomy_level, currency, revenue_goal_cents,
                approval_required_min_value_cents, max_monthly_revenue_actions,
                auto_execute_low_risk, allowed_action_types_json, settings_json,
                updated_by_user_id, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), :autonomy_level, :currency, :revenue_goal_cents,
                :approval_required_min_value_cents, :max_monthly_revenue_actions,
                :auto_execute_low_risk, CAST(:allowed_action_types_json AS jsonb), CAST(:settings_json AS jsonb),
                CAST(NULLIF(:actor_user_id, '') AS uuid), NOW()
            )
            ON CONFLICT (tenant_id)
            DO UPDATE SET
                autonomy_level = EXCLUDED.autonomy_level,
                currency = EXCLUDED.currency,
                revenue_goal_cents = EXCLUDED.revenue_goal_cents,
                approval_required_min_value_cents = EXCLUDED.approval_required_min_value_cents,
                max_monthly_revenue_actions = EXCLUDED.max_monthly_revenue_actions,
                auto_execute_low_risk = EXCLUDED.auto_execute_low_risk,
                allowed_action_types_json = EXCLUDED.allowed_action_types_json,
                settings_json = EXCLUDED.settings_json,
                updated_by_user_id = EXCLUDED.updated_by_user_id,
                updated_at = NOW()
            RETURNING tenant_id::text, autonomy_level, currency, revenue_goal_cents,
                      approval_required_min_value_cents, max_monthly_revenue_actions,
                      auto_execute_low_risk, allowed_action_types_json, settings_json,
                      COALESCE(updated_by_user_id::text, '') AS updated_by_user_id,
                      created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "actor_user_id": actor_user_id,
            "autonomy_level": max(0, min(int(payload.get("autonomy_level") or 0), 4)),
            "currency": _clean(payload.get("currency") or "USD", 12).upper() or "USD",
            "revenue_goal_cents": max(0, int(payload.get("revenue_goal_cents") or 0)),
            "approval_required_min_value_cents": max(0, int(payload.get("approval_required_min_value_cents") or 0)),
            "max_monthly_revenue_actions": max(0, int(payload.get("max_monthly_revenue_actions") or 0)),
            "auto_execute_low_risk": bool(payload.get("auto_execute_low_risk")),
            "allowed_action_types_json": _json(payload.get("allowed_action_types_json") or []),
            "settings_json": _json(payload.get("settings_json") or {}),
        },
    ).mappings().first()
    return _row(dict(row or {}))


def _tenant_revenue_metrics(conn: Connection, tenant_id: str) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            WITH conv AS (
                SELECT
                    COUNT(*)::int AS conversations,
                    COUNT(*) FILTER (WHERE lead_score >= 75 OR LOWER(lead_temperature) = 'hot')::int AS hot_leads,
                    COUNT(*) FILTER (WHERE LOWER(payment_status) = 'pending')::int AS pending_payments,
                    COUNT(*) FILTER (WHERE LOWER(payment_status) IN ('paid', 'converted', 'won'))::int AS converted,
                    COUNT(*) FILTER (WHERE COALESCE(last_message_at, updated_at, created_at) < NOW() - INTERVAL '14 days')::int AS inactive_14d
                FROM saas_conversations
                WHERE tenant_id = CAST(:tenant_id AS uuid)
            ),
            messages AS (
                SELECT COUNT(*)::int AS messages_30d
                FROM saas_messages
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND created_at >= NOW() - INTERVAL '30 days'
            ),
            invoices AS (
                SELECT
                    COALESCE(SUM(total_cents) FILTER (WHERE status IN ('paid', 'succeeded')), 0)::bigint AS paid_invoice_cents_90d,
                    COALESCE(SUM(amount_due_cents) FILTER (WHERE status IN ('open', 'past_due', 'uncollectible')), 0)::bigint AS open_invoice_cents
                FROM saas_billing_invoices
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND created_at >= NOW() - INTERVAL '90 days'
            )
            SELECT conv.*, messages.messages_30d, invoices.paid_invoice_cents_90d, invoices.open_invoice_cents
            FROM conv, messages, invoices
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    return _row(dict(row or {}))


def _candidate_opportunities(conn: Connection, tenant_id: str, *, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT
                c.id::text AS conversation_id,
                c.display_name,
                c.phone,
                c.channel,
                c.crm_stage,
                c.payment_status,
                c.lead_score,
                c.lead_temperature,
                c.last_message_text,
                c.updated_at::text AS updated_at,
                COALESCE(EXTRACT(EPOCH FROM (NOW() - COALESCE(c.last_message_at, c.updated_at, c.created_at))) / 86400, 999)::numeric(10,2) AS inactivity_days,
                COALESCE(pred.score, 0)::numeric(8,4) AS predictive_score,
                COALESCE(pred.label, '') AS predictive_label
            FROM saas_conversations c
            LEFT JOIN LATERAL (
                SELECT score, label
                FROM saas_intelligence_predictions p
                WHERE p.tenant_id = c.tenant_id
                  AND p.subject_type = 'conversation'
                  AND p.subject_id = c.id::text
                  AND p.prediction_type = 'lead_scoring'
                ORDER BY p.created_at DESC
                LIMIT 1
            ) pred ON TRUE
            WHERE c.tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY GREATEST(COALESCE(c.lead_score, 0), COALESCE(pred.score, 0)) DESC, c.updated_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "limit": max(1, min(int(limit or 50), 200))},
    ).mappings().all()
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows:
        row = _row(dict(raw))
        score = max(float(row.get("lead_score") or 0), float(row.get("predictive_score") or 0))
        temperature = str(row.get("lead_temperature") or "").lower()
        stage = str(row.get("crm_stage") or "").lower()
        payment = str(row.get("payment_status") or "").lower()
        inactivity = float(row.get("inactivity_days") or 999)
        name = row.get("display_name") or row.get("phone") or "Contacto"
        base = {
            "source_type": "conversation",
            "source_id": row["conversation_id"],
            "currency": "USD",
            "estimated_value_cents": 0,
            "evidence_json": {
                "crm_stage": stage,
                "payment_status": payment,
                "lead_score": score,
                "lead_temperature": temperature,
                "inactivity_days": inactivity,
                "channel": row.get("channel") or "",
                "value_note": "estimated_value_unknown_without_tenant_order_data",
            },
        }
        options: list[dict[str, Any]] = []
        if score >= 75 or temperature == "hot":
            options.append({
                **base,
                "category": "conversion",
                "opportunity_key": f"revenue:hot_lead:{row['conversation_id']}",
                "title": f"Lead caliente: {name}",
                "description": "Alta intencion detectada; conviene priorizar seguimiento humano antes de perder momentum.",
                "confidence": min(100, max(score, 72)),
                "priority_score": min(100, score + 12),
                "stage": "detected",
                "recommended_action_json": {"playbook_key": "hot_lead_followup", "action_type": "crm_followup_draft", "requires_human_approval": True},
            })
        if payment == "pending":
            options.append({
                **base,
                "category": "recovery",
                "opportunity_key": f"revenue:payment_recovery:{row['conversation_id']}",
                "title": f"Pago pendiente: {name}",
                "description": "El CRM marca pago pendiente; preparar recuperacion con revision humana.",
                "confidence": min(100, max(score, 68)),
                "priority_score": min(100, score + 18),
                "stage": "payment_pending",
                "recommended_action_json": {"playbook_key": "payment_recovery", "action_type": "payment_recovery_plan", "requires_human_approval": True},
            })
        if inactivity >= 14 and (score >= 50 or temperature in {"warm", "hot"}):
            options.append({
                **base,
                "category": "winback",
                "opportunity_key": f"revenue:winback:{row['conversation_id']}",
                "title": f"Reactivacion: {name}",
                "description": "Contacto con senales comerciales previas e inactividad; candidato a recuperacion o remarketing.",
                "confidence": min(100, max(score, 55)),
                "priority_score": min(100, score + min(inactivity, 30) / 2),
                "stage": "inactive",
                "recommended_action_json": {"playbook_key": "inactive_warm_lead_winback", "action_type": "winback_campaign_draft", "requires_human_approval": True},
            })
        if stage in {"cotizacion", "propuesta", "proposal", "quote", "negociacion"}:
            options.append({
                **base,
                "category": "closing",
                "opportunity_key": f"revenue:closing:{row['conversation_id']}",
                "title": f"Cierre asistido: {name}",
                "description": "La oportunidad parece estar en etapa de propuesta/cotizacion; sugerir siguiente accion de cierre.",
                "confidence": min(100, max(score, 62)),
                "priority_score": min(100, score + 10),
                "stage": "proposal",
                "recommended_action_json": {"playbook_key": "proposal_close_assist", "action_type": "close_assist_report", "requires_human_approval": True},
            })
        for item in options:
            if item["opportunity_key"] in seen:
                continue
            seen.add(item["opportunity_key"])
            candidates.append(item)
            if len(candidates) >= limit:
                return candidates
    return candidates


def _upsert_opportunity(conn: Connection, tenant_id: str, item: dict[str, Any], *, actor_user_id: str) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_revenue_opportunities (
                tenant_id, opportunity_key, source_type, source_id, category, title, description,
                estimated_value_cents, currency, confidence, priority_score, stage, status,
                recommended_action_json, evidence_json, created_by_user_id, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), :opportunity_key, :source_type, :source_id, :category,
                :title, :description, :estimated_value_cents, :currency, :confidence, :priority_score,
                :stage, 'suggested', CAST(:recommended_action_json AS jsonb), CAST(:evidence_json AS jsonb),
                CAST(NULLIF(:actor_user_id, '') AS uuid), NOW()
            )
            ON CONFLICT (tenant_id, opportunity_key)
            DO UPDATE SET
                title = EXCLUDED.title,
                description = EXCLUDED.description,
                estimated_value_cents = EXCLUDED.estimated_value_cents,
                currency = EXCLUDED.currency,
                confidence = EXCLUDED.confidence,
                priority_score = EXCLUDED.priority_score,
                stage = EXCLUDED.stage,
                recommended_action_json = EXCLUDED.recommended_action_json,
                evidence_json = EXCLUDED.evidence_json,
                updated_at = NOW()
            RETURNING id::text, tenant_id::text, opportunity_key, source_type, source_id, category,
                      title, description, estimated_value_cents, currency, confidence, priority_score,
                      stage, status, recommended_action_json, evidence_json, approval_json,
                      execution_result_json, COALESCE(created_by_user_id::text, '') AS created_by_user_id,
                      COALESCE(approved_by_user_id::text, '') AS approved_by_user_id,
                      COALESCE(executed_by_user_id::text, '') AS executed_by_user_id,
                      approved_at::text, executed_at::text, expires_at::text,
                      created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "actor_user_id": actor_user_id,
            "opportunity_key": _clean(item.get("opportunity_key"), 240),
            "source_type": _clean(item.get("source_type"), 80),
            "source_id": _clean(item.get("source_id"), 160),
            "category": _clean(item.get("category"), 80),
            "title": _clean(item.get("title"), 240),
            "description": _clean(item.get("description"), 1200),
            "estimated_value_cents": max(0, int(item.get("estimated_value_cents") or 0)),
            "currency": _clean(item.get("currency") or "USD", 12).upper() or "USD",
            "confidence": float(item.get("confidence") or 0),
            "priority_score": float(item.get("priority_score") or 0),
            "stage": _clean(item.get("stage"), 80),
            "recommended_action_json": _json(item.get("recommended_action_json") or {}),
            "evidence_json": _json(item.get("evidence_json") or {}),
        },
    ).mappings().first()
    return _row(dict(row or {}))


def _upsert_forecast(conn: Connection, tenant_id: str, candidates: list[dict[str, Any]], metrics: dict[str, Any]) -> dict[str, Any]:
    forecast_value = sum(int(item.get("estimated_value_cents") or 0) for item in candidates)
    confidence = min(100, 35 + len(candidates) * 5)
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_revenue_forecasts (
                tenant_id, period_key, forecast_type, forecast_value_cents, currency,
                confidence, scenario_json, source_json, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), :period_key, 'opportunity_pipeline',
                :forecast_value_cents, 'USD', :confidence,
                CAST(:scenario_json AS jsonb), CAST(:source_json AS jsonb), NOW()
            )
            ON CONFLICT (tenant_id, period_key, forecast_type)
            DO UPDATE SET
                forecast_value_cents = EXCLUDED.forecast_value_cents,
                confidence = EXCLUDED.confidence,
                scenario_json = EXCLUDED.scenario_json,
                source_json = EXCLUDED.source_json,
                updated_at = NOW()
            RETURNING id::text, tenant_id::text, period_key, forecast_type, forecast_value_cents,
                      currency, confidence, scenario_json, source_json, created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "period_key": _period_key(),
            "forecast_value_cents": forecast_value,
            "confidence": confidence,
            "scenario_json": _json({"method": "detected_opportunities", "value_note": "zero_when_no_order_value_available"}),
            "source_json": _json({"candidate_count": len(candidates), "metrics": metrics}),
        },
    ).mappings().first()
    return _row(dict(row or {}))


def _upsert_report(conn: Connection, tenant_id: str, candidates: list[dict[str, Any]], metrics: dict[str, Any]) -> dict[str, Any]:
    findings = [
        {"key": "hot_leads", "value": metrics.get("hot_leads", 0), "label": "Leads calientes detectados"},
        {"key": "pending_payments", "value": metrics.get("pending_payments", 0), "label": "Pagos pendientes en CRM"},
        {"key": "inactive_14d", "value": metrics.get("inactive_14d", 0), "label": "Conversaciones inactivas 14d"},
    ]
    recommendations = [
        {"playbook_key": item.get("recommended_action_json", {}).get("playbook_key"), "title": item.get("title"), "category": item.get("category")}
        for item in candidates[:10]
    ]
    score = min(100, len(candidates) * 8 + int(metrics.get("hot_leads") or 0) * 3)
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_revenue_reports (
                tenant_id, report_key, report_type, title, summary, score,
                findings_json, recommendations_json, metrics_json, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), :report_key, 'revenue_analysis',
                'Autonomous Revenue Engine',
                :summary, :score, CAST(:findings_json AS jsonb),
                CAST(:recommendations_json AS jsonb), CAST(:metrics_json AS jsonb), NOW()
            )
            ON CONFLICT (tenant_id, report_key)
            DO UPDATE SET
                summary = EXCLUDED.summary,
                score = EXCLUDED.score,
                findings_json = EXCLUDED.findings_json,
                recommendations_json = EXCLUDED.recommendations_json,
                metrics_json = EXCLUDED.metrics_json,
                updated_at = NOW()
            RETURNING id::text, tenant_id::text, report_key, report_type, title, summary, score,
                      findings_json, recommendations_json, metrics_json, created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "report_key": f"revenue:{_period_key()}",
            "summary": f"{len(candidates)} oportunidades comerciales detectadas; todas requieren revision humana antes de acciones externas.",
            "score": score,
            "findings_json": _json(findings),
            "recommendations_json": _json(recommendations),
            "metrics_json": _json(metrics),
        },
    ).mappings().first()
    return _row(dict(row or {}))


def analyze_revenue_engine(
    conn: Connection,
    tenant_id: str,
    *,
    actor_user_id: str = "",
    dry_run: bool = False,
    limit: int = 50,
    source: str = "manual",
) -> dict[str, Any]:
    ensure_revenue_tables(conn)
    access = _require_revenue_access(conn, tenant_id, allow_demo=dry_run)
    metrics = _tenant_revenue_metrics(conn, tenant_id)
    candidates = _candidate_opportunities(conn, tenant_id, limit=max(1, min(int(limit or 50), 200)))
    if dry_run:
        return {"dry_run": True, "access": access, "metrics": metrics, "candidate_opportunities": candidates, "created_opportunities": [], "forecast": None, "report": None}
    record_intelligence_usage(conn, tenant_id, "autonomous_revenue_engine", usage_metric="revenue_analysis", metadata={"source": source})
    created = [_upsert_opportunity(conn, tenant_id, item, actor_user_id=actor_user_id) for item in candidates]
    forecast = _upsert_forecast(conn, tenant_id, candidates, metrics)
    report = _upsert_report(conn, tenant_id, candidates, metrics)
    event = record_event(
        conn,
        tenant_id,
        {
            "event_type": "revenue.opportunities_detected",
            "source": "autonomous_revenue_engine",
            "entity_type": "tenant",
            "entity_id": tenant_id,
            "payload_json": {"opportunities": len(created), "metrics": metrics},
            "replay_key": f"revenue:analysis:{tenant_id}:{_period_key()}",
        },
    )
    return {"dry_run": False, "access": access, "metrics": metrics, "candidate_opportunities": candidates, "created_opportunities": created, "forecast": forecast, "report": report, "event": event}


def list_revenue_opportunities(conn: Connection, tenant_id: str, *, status: str = "all", limit: int = 50) -> list[dict[str, Any]]:
    ensure_revenue_tables(conn)
    status_filter = _clean(status, 40).lower()
    rows = conn.execute(
        text(
            """
            SELECT id::text, tenant_id::text, opportunity_key, source_type, source_id, category,
                   title, description, estimated_value_cents, currency, confidence, priority_score,
                   stage, status, recommended_action_json, evidence_json, approval_json,
                   execution_result_json, COALESCE(created_by_user_id::text, '') AS created_by_user_id,
                   COALESCE(approved_by_user_id::text, '') AS approved_by_user_id,
                   COALESCE(executed_by_user_id::text, '') AS executed_by_user_id,
                   approved_at::text, executed_at::text, expires_at::text, created_at::text, updated_at::text
            FROM saas_ai_revenue_opportunities
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND (:status = 'all' OR status = :status)
            ORDER BY priority_score DESC, updated_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "status": status_filter or "all", "limit": max(1, min(int(limit or 50), 200))},
    ).mappings().all()
    return [_row(dict(row)) for row in rows]


def _list_table(conn: Connection, tenant_id: str, table: str, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            f"""
            SELECT *
            FROM {table}
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY updated_at DESC NULLS LAST, created_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "limit": max(1, min(int(limit or 20), 100))},
    ).mappings().all()
    return [_row(dict(row)) for row in rows]


def revenue_engine_center(conn: Connection, tenant_id: str, *, limit: int = 50) -> dict[str, Any]:
    ensure_revenue_tables(conn)
    metrics = _tenant_revenue_metrics(conn, tenant_id)
    opportunities = list_revenue_opportunities(conn, tenant_id, status="all", limit=limit)
    counts = {
        "open_opportunities": sum(1 for item in opportunities if item.get("status") in {"suggested", "approved"}),
        "approved_opportunities": sum(1 for item in opportunities if item.get("status") == "approved"),
        "executed_opportunities": sum(1 for item in opportunities if item.get("status") == "executed"),
        "estimated_open_value_cents": sum(int(item.get("estimated_value_cents") or 0) for item in opportunities if item.get("status") in {"suggested", "approved"}),
    }
    return {
        "phase": "19",
        "access": revenue_access(conn, tenant_id),
        "policy": revenue_policy(conn, tenant_id),
        "metrics": metrics,
        "counts": counts,
        "opportunities": opportunities,
        "forecasts": _list_table(conn, tenant_id, "saas_ai_revenue_forecasts", limit=12),
        "experiments": _list_table(conn, tenant_id, "saas_ai_revenue_experiments", limit=12),
        "reports": _list_table(conn, tenant_id, "saas_ai_revenue_reports", limit=12),
        "playbooks": REVENUE_PLAYBOOKS,
        "safety": {
            "requires_human_approval": True,
            "auto_sends_messages": False,
            "auto_charges": False,
            "auto_campaign_activation": False,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _opportunity_action(conn: Connection, tenant_id: str, actor_user_id: str, opportunity_id: str, *, action: str, notes: str = "", dry_run: bool = False) -> dict[str, Any]:
    ensure_revenue_tables(conn)
    _require_revenue_access(conn, tenant_id, allow_demo=dry_run)
    clean_action = _clean(action, 40).lower()
    if clean_action not in {"approve", "execute", "dismiss"}:
        raise HTTPException(status_code=400, detail={"code": "invalid_revenue_action"})
    policy = revenue_policy(conn, tenant_id)
    existing = conn.execute(
        text(
            """
            SELECT id::text, status, title, recommended_action_json
            FROM saas_ai_revenue_opportunities
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:id AS uuid)
            """
        ),
        {"tenant_id": tenant_id, "id": opportunity_id},
    ).mappings().first()
    if not existing:
        raise HTTPException(status_code=404, detail={"code": "revenue_opportunity_not_found"})
    if dry_run:
        return {"dry_run": True, "action": clean_action, "opportunity": _row(dict(existing)), "would_mutate": False}

    if clean_action in {"approve", "execute"}:
        allowed_actions = {
            _clean(item, 120)
            for item in (policy.get("allowed_action_types_json") or [])
            if _clean(item, 120)
        }
        recommended_action = _json_value(existing.get("recommended_action_json"), {})
        recommended_action_type = _clean(recommended_action.get("action_type"), 120)
        if allowed_actions and recommended_action_type not in allowed_actions:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "revenue_action_type_not_allowed",
                    "action_type": recommended_action_type,
                    "allowed_action_types": sorted(allowed_actions),
                },
            )

    if clean_action == "execute" and str(existing.get("status") or "") != "executed":
        max_monthly = int(policy.get("max_monthly_revenue_actions") or 0)
        if max_monthly > 0:
            executed_count = int(
                conn.execute(
                    text(
                        """
                        SELECT COUNT(*)::int
                        FROM saas_ai_revenue_opportunities
                        WHERE tenant_id = CAST(:tenant_id AS uuid)
                          AND status = 'executed'
                          AND executed_at >= date_trunc('month', NOW())
                        """
                    ),
                    {"tenant_id": tenant_id},
                ).scalar()
                or 0
            )
            if executed_count >= max_monthly:
                raise HTTPException(
                    status_code=429,
                    detail={
                        "code": "revenue_monthly_action_limit_reached",
                        "max_monthly_revenue_actions": max_monthly,
                    },
                )

    if clean_action == "approve":
        sql = """
            UPDATE saas_ai_revenue_opportunities
            SET status = 'approved',
                approved_by_user_id = CAST(NULLIF(:actor_user_id, '') AS uuid),
                approved_at = NOW(),
                approval_json = approval_json || CAST(:payload AS jsonb),
                updated_at = NOW()
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:id AS uuid)
              AND status IN ('suggested', 'approved')
        """
        payload = {"notes": _clean(notes, 1000), "approved_at": datetime.now(timezone.utc).isoformat()}
    elif clean_action == "execute":
        sql = """
            UPDATE saas_ai_revenue_opportunities
            SET status = 'executed',
                executed_by_user_id = CAST(NULLIF(:actor_user_id, '') AS uuid),
                executed_at = NOW(),
                execution_result_json = execution_result_json || CAST(:payload AS jsonb),
                updated_at = NOW()
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:id AS uuid)
              AND status IN ('approved', 'executed')
        """
        payload = {"notes": _clean(notes, 1000), "execution_mode": "controlled_record_only", "external_side_effects": False}
    else:
        sql = """
            UPDATE saas_ai_revenue_opportunities
            SET status = 'dismissed',
                approval_json = approval_json || CAST(:payload AS jsonb),
                updated_at = NOW()
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:id AS uuid)
              AND status <> 'executed'
        """
        payload = {"notes": _clean(notes, 1000), "dismissed_at": datetime.now(timezone.utc).isoformat()}

    row = conn.execute(
        text(
            sql
            + """
            RETURNING id::text, tenant_id::text, opportunity_key, source_type, source_id, category,
                      title, description, estimated_value_cents, currency, confidence, priority_score,
                      stage, status, recommended_action_json, evidence_json, approval_json,
                      execution_result_json, COALESCE(created_by_user_id::text, '') AS created_by_user_id,
                      COALESCE(approved_by_user_id::text, '') AS approved_by_user_id,
                      COALESCE(executed_by_user_id::text, '') AS executed_by_user_id,
                      approved_at::text, executed_at::text, expires_at::text, created_at::text, updated_at::text
            """
        ),
        {"tenant_id": tenant_id, "id": opportunity_id, "actor_user_id": actor_user_id, "payload": _json(payload)},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail={"code": "revenue_opportunity_not_found_or_invalid_status"})
    opportunity = _row(dict(row))
    event_suffix = {"approve": "approved", "execute": "executed", "dismiss": "dismissed"}[clean_action]
    record_event(
        conn,
        tenant_id,
        {
            "event_type": f"revenue.opportunity_{event_suffix}",
            "source": "autonomous_revenue_engine",
            "entity_type": "revenue_opportunity",
            "entity_id": opportunity.get("id", ""),
            "payload_json": {"category": opportunity.get("category"), "status": opportunity.get("status")},
            "replay_key": f"revenue:opportunity:{opportunity.get('id')}:{clean_action}:{opportunity.get('updated_at')}",
        },
    )
    return opportunity


def approve_revenue_opportunity(conn: Connection, tenant_id: str, actor_user_id: str, opportunity_id: str, *, notes: str = "", dry_run: bool = False) -> dict[str, Any]:
    return _opportunity_action(conn, tenant_id, actor_user_id, opportunity_id, action="approve", notes=notes, dry_run=dry_run)


def execute_revenue_opportunity(conn: Connection, tenant_id: str, actor_user_id: str, opportunity_id: str, *, notes: str = "", dry_run: bool = False) -> dict[str, Any]:
    return _opportunity_action(conn, tenant_id, actor_user_id, opportunity_id, action="execute", notes=notes, dry_run=dry_run)


def dismiss_revenue_opportunity(conn: Connection, tenant_id: str, actor_user_id: str, opportunity_id: str, *, notes: str = "", dry_run: bool = False) -> dict[str, Any]:
    return _opportunity_action(conn, tenant_id, actor_user_id, opportunity_id, action="dismiss", notes=notes, dry_run=dry_run)
