from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
from statistics import median
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app_saas.intelligence.service import ensure_intelligence_tables, intelligence_feature_state, record_intelligence_usage, resolve_intelligence_access
from app_saas.verticals.catalog import get_industry_pack, list_industry_packs, normalize_industry_code, pack_summary

NETWORK_FEATURE_KEYS = (
    "enterprise_ai_network",
    "vertical_ai_intelligence",
    "industry_ai_models",
    "benchmark_intelligence",
    "cross_tenant_intelligence",
    "vertical_ai_advisors",
    "ai_playbook_library",
)
NETWORK_FULL_KEYS = ("enterprise_ai_network", "cross_tenant_intelligence", "ai_premium")
MIN_BENCHMARK_SAMPLE = 3


EXTRA_VERTICAL_PROFILES: dict[str, dict[str, Any]] = {
    "retail": {
        "label": "Retail",
        "category": "commerce",
        "advisor": "Retail AI Advisor",
        "kpis": ["conversion_rate", "campaign_positive_rate", "response_time_minutes", "retention_risk_rate"],
        "model_tasks": ["retail_lead_scoring", "store_followup_optimization"],
        "best_practices": ["priorizar recompra", "medir respuesta por canal", "separar leads de soporte y venta"],
    },
    "ecommerce": {
        "label": "Ecommerce",
        "category": "commerce",
        "advisor": "Ecommerce AI Advisor",
        "kpis": ["conversion_rate", "campaign_positive_rate", "hot_lead_rate", "retention_risk_rate"],
        "model_tasks": ["ecommerce_lead_scoring", "cart_recovery_scoring", "repeat_purchase_recommendations"],
        "best_practices": ["recuperar carrito", "segmentar por intencion", "optimizar ventanas de remarketing"],
    },
    "support": {
        "label": "Soporte tecnico",
        "category": "support",
        "advisor": "Support AI Advisor",
        "kpis": ["response_time_minutes", "retention_risk_rate", "automation_coverage"],
        "model_tasks": ["ticket_priority_scoring", "sla_risk_prediction"],
        "best_practices": ["clasificar urgencia", "detectar escalaciones", "auditar SLA por canal"],
    },
    "automotive": {
        "label": "Automotriz",
        "category": "services",
        "advisor": "Automotive AI Advisor",
        "kpis": ["conversion_rate", "hot_lead_rate", "response_time_minutes"],
        "model_tasks": ["vehicle_lead_qualification", "test_drive_recovery"],
        "best_practices": ["calificar presupuesto", "agendar test drive", "separar venta y posventa"],
    },
    "financial_services": {
        "label": "Servicios financieros",
        "category": "regulated",
        "advisor": "Financial Services AI Advisor",
        "kpis": ["conversion_rate", "response_time_minutes", "retention_risk_rate"],
        "model_tasks": ["financial_lead_scoring", "portfolio_retention_risk"],
        "best_practices": ["mantener revision humana", "registrar consentimiento", "priorizar riesgo operativo"],
    },
}


METRIC_DEFINITIONS: dict[str, dict[str, Any]] = {
    "response_time_minutes": {
        "label": "Tiempo respuesta",
        "unit": "min",
        "direction": "lower_better",
        "kpi": "response_time",
        "low_sample_message": "Aun no hay muestra anonima suficiente para comparar tiempos de respuesta por industria.",
    },
    "conversion_rate": {
        "label": "Conversion",
        "unit": "%",
        "direction": "higher_better",
        "kpi": "conversion",
        "low_sample_message": "Aun no hay muestra anonima suficiente para comparar conversion por industria.",
    },
    "hot_lead_rate": {
        "label": "Leads calientes",
        "unit": "%",
        "direction": "higher_better",
        "kpi": "lead_quality",
        "low_sample_message": "Aun no hay muestra anonima suficiente para comparar leads calientes.",
    },
    "campaign_positive_rate": {
        "label": "Campanas positivas",
        "unit": "%",
        "direction": "higher_better",
        "kpi": "campaign_performance",
        "low_sample_message": "Aun no hay muestra anonima suficiente para comparar campanas.",
    },
    "retention_risk_rate": {
        "label": "Riesgo retencion",
        "unit": "%",
        "direction": "lower_better",
        "kpi": "retention",
        "low_sample_message": "Aun no hay muestra anonima suficiente para comparar riesgo de abandono.",
    },
    "automation_coverage": {
        "label": "Cobertura automatizacion",
        "unit": "%",
        "direction": "higher_better",
        "kpi": "workflow_efficiency",
        "low_sample_message": "Aun no hay muestra anonima suficiente para comparar automatizacion.",
    },
    "agent_coverage": {
        "label": "Cobertura agentes",
        "unit": "%",
        "direction": "higher_better",
        "kpi": "ai_agents",
        "low_sample_message": "Aun no hay muestra anonima suficiente para comparar uso de agentes.",
    },
}


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def _num(value: Any, default: float = 0.0) -> float:
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clean(value: Any, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _period_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m")


def _percentile(sorted_values: list[float], percentile: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (len(sorted_values) - 1) * percentile
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    weight = rank - low
    return sorted_values[low] * (1 - weight) + sorted_values[high] * weight


def _industry_profile(industry_code: str) -> dict[str, Any]:
    code = _clean(industry_code, 80).lower().replace("-", "_") or "general"
    if code in EXTRA_VERTICAL_PROFILES:
        return {"code": code, **EXTRA_VERTICAL_PROFILES[code]}
    pack = get_industry_pack(code)
    summary = pack_summary(pack)
    return {
        "code": summary["code"],
        "label": summary["label"],
        "category": summary["category"],
        "advisor": f"{summary['label']} AI Advisor",
        "kpis": summary.get("kpis") or [],
        "model_tasks": [
            f"{summary['code']}_lead_scoring",
            f"{summary['code']}_churn_prediction",
            f"{summary['code']}_smart_remarketing",
        ],
        "best_practices": [
            "priorizar oportunidades con alta intencion",
            "optimizar seguimiento segun etapa CRM",
            "medir conversion y tiempo de respuesta por canal",
        ],
    }


def _all_profiles() -> list[dict[str, Any]]:
    existing = [_industry_profile((pack.get("code") or "general")) for pack in list_industry_packs()]
    extras = [_industry_profile(code) for code in EXTRA_VERTICAL_PROFILES]
    seen: set[str] = set()
    profiles: list[dict[str, Any]] = []
    for profile in [*existing, *extras]:
        code = str(profile.get("code") or "general")
        if code in seen:
            continue
        seen.add(code)
        profiles.append(profile)
    return profiles


def ensure_enterprise_network_tables(conn: Connection) -> None:
    ensure_intelligence_tables(conn)
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_vertical_industry_models (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                industry_code TEXT NOT NULL DEFAULT 'general',
                prediction_type TEXT NOT NULL DEFAULT 'lead_scoring',
                model_key TEXT NOT NULL,
                model_version TEXT NOT NULL DEFAULT 'v1',
                routing_mode TEXT NOT NULL DEFAULT 'metadata_only',
                status TEXT NOT NULL DEFAULT 'active',
                feature_set_key TEXT NOT NULL DEFAULT '',
                required_feature_key TEXT NOT NULL DEFAULT 'industry_ai_models',
                model_metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (industry_code, prediction_type, model_key, model_version)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_vertical_models_industry ON saas_ai_vertical_industry_models (industry_code, prediction_type, status)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_vertical_benchmarks (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                industry_code TEXT NOT NULL DEFAULT 'general',
                cohort_key TEXT NOT NULL DEFAULT 'all',
                metric_key TEXT NOT NULL,
                period_key TEXT NOT NULL DEFAULT 'latest',
                sample_count INTEGER NOT NULL DEFAULT 0,
                average_value NUMERIC(18,6) NULL,
                p50_value NUMERIC(18,6) NULL,
                p75_value NUMERIC(18,6) NULL,
                p90_value NUMERIC(18,6) NULL,
                direction TEXT NOT NULL DEFAULT 'higher_better',
                privacy_level TEXT NOT NULL DEFAULT 'aggregated',
                source_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                computed_at TIMESTAMP NOT NULL DEFAULT NOW(),
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (industry_code, cohort_key, metric_key, period_key)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_vertical_benchmarks_lookup ON saas_ai_vertical_benchmarks (industry_code, period_key, metric_key)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_vertical_tenant_benchmarks (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                industry_code TEXT NOT NULL DEFAULT 'general',
                metric_key TEXT NOT NULL,
                period_key TEXT NOT NULL DEFAULT 'latest',
                tenant_value NUMERIC(18,6) NULL,
                benchmark_value NUMERIC(18,6) NULL,
                delta_percent NUMERIC(18,6) NULL,
                percentile NUMERIC(8,4) NULL,
                sample_count INTEGER NOT NULL DEFAULT 0,
                comparison_label TEXT NOT NULL DEFAULT 'insufficient_sample',
                recommendation_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                computed_at TIMESTAMP NOT NULL DEFAULT NOW(),
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, industry_code, metric_key, period_key)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_vertical_tenant_benchmarks_tenant ON saas_ai_vertical_tenant_benchmarks (tenant_id, industry_code, period_key, metric_key)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_vertical_insights (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                industry_code TEXT NOT NULL DEFAULT 'general',
                insight_key TEXT NOT NULL,
                insight_type TEXT NOT NULL DEFAULT 'benchmark',
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                severity TEXT NOT NULL DEFAULT 'info',
                confidence NUMERIC(8,4) NOT NULL DEFAULT 0,
                kpi_key TEXT NOT NULL DEFAULT '',
                recommendation_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                source_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, insight_key)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_vertical_insights_tenant ON saas_ai_vertical_insights (tenant_id, status, severity, updated_at DESC)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_vertical_playbooks (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                industry_code TEXT NOT NULL DEFAULT 'general',
                playbook_key TEXT NOT NULL,
                playbook_type TEXT NOT NULL DEFAULT 'workflow',
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                kpi_key TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'published',
                premium_required BOOLEAN NOT NULL DEFAULT TRUE,
                required_feature_key TEXT NOT NULL DEFAULT 'ai_playbook_library',
                trigger_template_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                workflow_template_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                recommendation_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                safety_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (industry_code, playbook_key)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_vertical_playbooks_industry ON saas_ai_vertical_playbooks (industry_code, status, playbook_type)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_knowledge_network (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                industry_code TEXT NOT NULL DEFAULT 'general',
                node_key TEXT NOT NULL,
                node_type TEXT NOT NULL DEFAULT 'best_practice',
                title TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                tags_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                privacy_class TEXT NOT NULL DEFAULT 'aggregate_only',
                status TEXT NOT NULL DEFAULT 'published',
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (industry_code, node_key)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_knowledge_network_industry ON saas_ai_knowledge_network (industry_code, node_type, status)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_network_metrics (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                industry_code TEXT NOT NULL DEFAULT 'general',
                metric_key TEXT NOT NULL,
                metric_value NUMERIC(18,6) NOT NULL DEFAULT 0,
                dimensions_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                period_key TEXT NOT NULL DEFAULT 'latest',
                privacy_level TEXT NOT NULL DEFAULT 'aggregate_only',
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_network_metrics_lookup ON saas_ai_network_metrics (tenant_id, industry_code, metric_key, period_key, created_at DESC)"))


def _resolve_network_access(conn: Connection, tenant_id: str, *, require_full: bool = False) -> dict[str, Any]:
    candidates = NETWORK_FULL_KEYS if require_full else ("enterprise_ai_network", "vertical_ai_intelligence", "benchmark_intelligence", "intelligence_demo", "ai_premium")
    last_detail: Any = None
    for key in candidates:
        try:
            access = resolve_intelligence_access(conn, tenant_id, key, allow_demo=not require_full)
            access = dict(access)
            access["access_feature"] = key
            access["network_enabled"] = True
            return access
        except HTTPException as exc:
            last_detail = exc.detail
    if require_full:
        raise HTTPException(status_code=403, detail={"code": "enterprise_ai_network_requires_full", "features": list(candidates), "last_error": last_detail})
    return {
        "network_enabled": False,
        "enabled": False,
        "mode": "disabled",
        "access_feature": "",
        "reason": "enterprise_ai_network_not_enabled",
        "last_error": last_detail,
    }


def _tenant_industry(conn: Connection, tenant_id: str) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            SELECT id::text AS tenant_id, name, slug, status, plan_code, COALESCE(NULLIF(industry_code, ''), 'general') AS industry_code
            FROM saas_tenants
            WHERE id = CAST(:tenant_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="tenant_not_found")
    data = dict(row)
    data["industry_code"] = _clean(data.get("industry_code"), 80) or "general"
    return data


def _tenant_metric_rows(conn: Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            WITH conv AS (
                SELECT
                    t.id AS tenant_id,
                    COALESCE(NULLIF(t.industry_code, ''), 'general') AS industry_code,
                    COUNT(DISTINCT c.id)::int AS conversations,
                    COALESCE(AVG(EXTRACT(EPOCH FROM (c.last_agent_message_at - c.last_customer_message_at)) / 60)
                        FILTER (
                            WHERE c.last_agent_message_at IS NOT NULL
                              AND c.last_customer_message_at IS NOT NULL
                              AND c.last_agent_message_at >= c.last_customer_message_at
                        ), 0)::numeric(18,6) AS response_time_minutes,
                    COUNT(DISTINCT c.id) FILTER (WHERE c.lead_score >= 75 OR LOWER(COALESCE(c.lead_temperature, '')) = 'hot')::int AS hot_leads,
                    COUNT(DISTINCT c.id) FILTER (
                        WHERE COALESCE(ps.is_won, FALSE) = TRUE
                           OR LOWER(COALESCE(c.payment_status, '')) IN ('paid', 'confirmed', 'completed', 'pago_confirmado')
                    )::int AS conversions,
                    COUNT(DISTINCT c.id) FILTER (WHERE c.last_message_at < NOW() - INTERVAL '14 days' OR c.last_message_at IS NULL)::int AS inactive_14d
                FROM saas_tenants t
                LEFT JOIN saas_conversations c
                  ON c.tenant_id = t.id
                LEFT JOIN saas_crm_pipeline_stages ps
                  ON ps.tenant_id = t.id
                 AND ps.stage_key = c.crm_stage
                 AND ps.is_active = TRUE
                WHERE t.status IN ('active', 'trial')
                GROUP BY t.id, COALESCE(NULLIF(t.industry_code, ''), 'general')
            ),
            campaign AS (
                SELECT
                    tenant_id,
                    COUNT(*)::int AS campaign_events,
                    COUNT(*) FILTER (WHERE outcome IN ('clicked', 'replied', 'converted', 'sent', 'delivered', 'read', 'queued'))::int AS campaign_positive
                FROM saas_campaign_ab_events
                WHERE created_at >= NOW() - INTERVAL '90 days'
                GROUP BY tenant_id
            ),
            automation AS (
                SELECT
                    t.id AS tenant_id,
                    COALESCE((SELECT COUNT(*)::int FROM saas_crm_triggers tr WHERE tr.tenant_id = t.id AND tr.is_active = TRUE), 0) AS active_triggers,
                    COALESCE((SELECT COUNT(*)::int FROM saas_remarketing_flows fl WHERE fl.tenant_id = t.id AND fl.status = 'active'), 0) AS active_flows
                FROM saas_tenants t
                WHERE t.status IN ('active', 'trial')
            ),
            agents AS (
                SELECT
                    tenant_id,
                    COUNT(*) FILTER (WHERE status = 'active')::int AS active_agents
                FROM saas_ai_agents
                GROUP BY tenant_id
            )
            SELECT
                conv.tenant_id::text,
                conv.industry_code,
                conv.conversations,
                conv.response_time_minutes,
                conv.hot_leads,
                conv.conversions,
                conv.inactive_14d,
                COALESCE(campaign.campaign_events, 0)::int AS campaign_events,
                COALESCE(campaign.campaign_positive, 0)::int AS campaign_positive,
                COALESCE(automation.active_triggers, 0)::int AS active_triggers,
                COALESCE(automation.active_flows, 0)::int AS active_flows,
                COALESCE(agents.active_agents, 0)::int AS active_agents
            FROM conv
            LEFT JOIN campaign ON campaign.tenant_id = conv.tenant_id
            LEFT JOIN automation ON automation.tenant_id = conv.tenant_id
            LEFT JOIN agents ON agents.tenant_id = conv.tenant_id
            """
        )
    ).mappings().all()
    return [dict(row) for row in rows]


def _metric_values(row: dict[str, Any]) -> dict[str, float]:
    conversations = max(1.0, _num(row.get("conversations")))
    campaign_events = max(1.0, _num(row.get("campaign_events")))
    automation_total = _num(row.get("active_triggers")) + _num(row.get("active_flows"))
    return {
        "response_time_minutes": round(_num(row.get("response_time_minutes")), 4),
        "conversion_rate": round((_num(row.get("conversions")) / conversations) * 100, 4),
        "hot_lead_rate": round((_num(row.get("hot_leads")) / conversations) * 100, 4),
        "campaign_positive_rate": round((_num(row.get("campaign_positive")) / campaign_events) * 100, 4),
        "retention_risk_rate": round((_num(row.get("inactive_14d")) / conversations) * 100, 4),
        "automation_coverage": round((automation_total / conversations) * 100, 4),
        "agent_coverage": round((_num(row.get("active_agents")) / conversations) * 100, 4),
    }


def _benchmark_stats(values: list[float]) -> dict[str, Any]:
    sorted_values = sorted(values)
    return {
        "sample_count": len(sorted_values),
        "average_value": round(sum(sorted_values) / len(sorted_values), 6) if sorted_values else None,
        "p50_value": round(median(sorted_values), 6) if sorted_values else None,
        "p75_value": round(_percentile(sorted_values, 0.75) or 0, 6) if sorted_values else None,
        "p90_value": round(_percentile(sorted_values, 0.9) or 0, 6) if sorted_values else None,
    }


def _comparison(metric_key: str, tenant_value: float, peer_values: list[float]) -> dict[str, Any]:
    definition = METRIC_DEFINITIONS[metric_key]
    direction = definition["direction"]
    sample_count = len(peer_values)
    if sample_count < MIN_BENCHMARK_SAMPLE:
        return {
            "metric_key": metric_key,
            "label": "insufficient_sample",
            "tenant_value": tenant_value,
            "benchmark_value": None,
            "delta_percent": None,
            "percentile": None,
            "sample_count": sample_count,
            "recommendation": definition["low_sample_message"],
            "direction": direction,
        }
    benchmark = sum(peer_values) / sample_count
    if benchmark == 0:
        delta = 0.0 if tenant_value == 0 else 100.0
    elif direction == "lower_better":
        delta = ((benchmark - tenant_value) / abs(benchmark)) * 100
    else:
        delta = ((tenant_value - benchmark) / abs(benchmark)) * 100
    if delta >= 15:
        label = "above_industry"
    elif delta <= -15:
        label = "below_industry"
    else:
        label = "on_track"
    if direction == "lower_better":
        better_or_equal = sum(1 for value in peer_values if value >= tenant_value)
    else:
        better_or_equal = sum(1 for value in peer_values if value <= tenant_value)
    percentile = (better_or_equal / sample_count) * 100
    return {
        "metric_key": metric_key,
        "label": label,
        "tenant_value": round(tenant_value, 6),
        "benchmark_value": round(benchmark, 6),
        "delta_percent": round(delta, 4),
        "percentile": round(percentile, 2),
        "sample_count": sample_count,
        "recommendation": _recommendation_for_comparison(metric_key, label, delta),
        "direction": direction,
    }


def _recommendation_for_comparison(metric_key: str, label: str, delta: float) -> str:
    if label == "above_industry":
        return {
            "response_time_minutes": "Mantener el SLA actual y convertirlo en playbook para el equipo.",
            "conversion_rate": "Usar este flujo como referencia para nuevos segmentos y campanas.",
            "hot_lead_rate": "Asignar leads calientes a agentes especializados antes de que se enfrien.",
            "campaign_positive_rate": "Replicar la combinacion de canal, horario y plantilla en audiencias similares.",
            "retention_risk_rate": "Documentar el flujo de retencion actual como mejor practica interna.",
            "automation_coverage": "Medir conversion antes de agregar mas automatizaciones.",
            "agent_coverage": "Auditar calidad de respuestas y costos por agente para escalar con control.",
        }.get(metric_key, "Mantener la practica y medir su impacto por cohorte.")
    if label == "below_industry":
        return {
            "response_time_minutes": "Reducir tiempo de primera respuesta con asignacion, SLA y playbook de triage.",
            "conversion_rate": "Revisar pipeline, objeciones frecuentes y follow-ups por etapa.",
            "hot_lead_rate": "Afinar scoring y captura de intencion en triggers y CRM.",
            "campaign_positive_rate": "Simular campanas, ajustar segmento y validar plantillas antes de activar.",
            "retention_risk_rate": "Activar recuperacion de inactivos y priorizar clientes con alto riesgo.",
            "automation_coverage": "Agregar workflows draft para etapas repetitivas y medir antes de activar.",
            "agent_coverage": "Probar copilotos verticales en modo supervisado para reducir carga humana.",
        }.get(metric_key, "Priorizar una mejora controlada y medir contra el benchmark.")
    return "El KPI esta cerca del promedio sectorial; buscar mejoras incrementales con A/B o playbooks."


def _seed_vertical_assets(conn: Connection) -> dict[str, int]:
    profiles = _all_profiles()
    model_rows = 0
    playbook_rows = 0
    knowledge_rows = 0
    for profile in profiles:
        code = str(profile["code"])
        kpis = list(profile.get("kpis") or [])
        for task in ("lead_scoring", "churn_prediction", "smart_remarketing", "operational_anomaly"):
            model_key = f"vertical_{code}_{task}_v1"
            conn.execute(
                text(
                    """
                    INSERT INTO saas_ai_vertical_industry_models (
                        industry_code, prediction_type, model_key, model_version, routing_mode,
                        status, feature_set_key, required_feature_key, model_metadata_json, metrics_json
                    )
                    VALUES (
                        :industry_code, :prediction_type, :model_key, 'v1', 'metadata_only',
                        'active', :feature_set_key, 'industry_ai_models', CAST(:metadata_json AS jsonb), '{}'::jsonb
                    )
                    ON CONFLICT (industry_code, prediction_type, model_key, model_version)
                    DO UPDATE SET updated_at = NOW(), model_metadata_json = EXCLUDED.model_metadata_json
                    """
                ),
                {
                    "industry_code": code,
                    "prediction_type": task,
                    "model_key": model_key,
                    "feature_set_key": f"{code}_{task}_features_v1",
                    "metadata_json": _json(
                        {
                            "industry_label": profile.get("label"),
                            "model_strategy": "shared_global_baseline_plus_tenant_personalization",
                            "raw_content_used": False,
                            "training_mode": "lightweight_ml_or_baseline_shadow",
                            "recommended_features": kpis,
                        }
                    ),
                },
            )
            model_rows += 1
        playbooks = [
            {
                "suffix": "lead_recovery",
                "type": "workflow",
                "title": f"{profile['label']}: recuperacion de oportunidades",
                "description": "Playbook sectorial para leads con intencion que no avanzan.",
                "kpi": "conversion_rate",
                "trigger": {"conditions": [{"type": "crm_stage_stalled"}, {"type": "hot_lead"}], "block_ai": True},
                "workflow": {"steps": ["validar intencion", "asignar responsable", "enviar seguimiento aprobado"]},
            },
            {
                "suffix": "retention_watch",
                "type": "remarketing",
                "title": f"{profile['label']}: retencion inteligente",
                "description": "Playbook sectorial para clientes inactivos o con caida de engagement.",
                "kpi": "retention_risk_rate",
                "trigger": {"conditions": [{"type": "inactivity_days", "gte": 14}], "block_ai": False},
                "workflow": {"steps": ["segmentar inactivos", "proponer incentivo", "medir respuesta"]},
            },
        ]
        for item in playbooks:
            key = f"{code}_{item['suffix']}"
            conn.execute(
                text(
                    """
                    INSERT INTO saas_ai_vertical_playbooks (
                        industry_code, playbook_key, playbook_type, title, description, kpi_key,
                        trigger_template_json, workflow_template_json, recommendation_json, safety_json
                    )
                    VALUES (
                        :industry_code, :playbook_key, :playbook_type, :title, :description, :kpi_key,
                        CAST(:trigger_json AS jsonb), CAST(:workflow_json AS jsonb), CAST(:recommendation_json AS jsonb), CAST(:safety_json AS jsonb)
                    )
                    ON CONFLICT (industry_code, playbook_key)
                    DO UPDATE SET title = EXCLUDED.title, description = EXCLUDED.description, updated_at = NOW()
                    """
                ),
                {
                    "industry_code": code,
                    "playbook_key": key,
                    "playbook_type": item["type"],
                    "title": item["title"],
                    "description": item["description"],
                    "kpi_key": item["kpi"],
                    "trigger_json": _json(item["trigger"]),
                    "workflow_json": _json(item["workflow"]),
                    "recommendation_json": _json({"advisor": profile.get("advisor"), "industry_code": code}),
                    "safety_json": _json({"auto_activate": False, "requires_preflight": True, "human_review": True}),
                },
            )
            playbook_rows += 1
        for index, practice in enumerate(profile.get("best_practices") or []):
            key = f"{code}_best_practice_{index + 1}"
            conn.execute(
                text(
                    """
                    INSERT INTO saas_ai_knowledge_network (
                        industry_code, node_key, node_type, title, summary, tags_json, evidence_json, privacy_class
                    )
                    VALUES (
                        :industry_code, :node_key, 'best_practice', :title, :summary,
                        CAST(:tags_json AS jsonb), CAST(:evidence_json AS jsonb), 'aggregate_only'
                    )
                    ON CONFLICT (industry_code, node_key)
                    DO UPDATE SET title = EXCLUDED.title, summary = EXCLUDED.summary, updated_at = NOW()
                    """
                ),
                {
                    "industry_code": code,
                    "node_key": key,
                    "title": f"{profile['label']}: {practice}",
                    "summary": f"Practica sectorial recomendada para {profile['label']}. No usa mensajes crudos ni datos privados.",
                    "tags_json": _json([code, "vertical_intelligence", "best_practice"]),
                    "evidence_json": _json({"source": "scentra_vertical_profile", "raw_content_used": False}),
                },
            )
            knowledge_rows += 1
    return {"profiles": len(profiles), "models": model_rows, "playbooks": playbook_rows, "knowledge_nodes": knowledge_rows}


def _industry_benchmark_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, list[float]]]:
    grouped: dict[str, dict[str, list[float]]] = {}
    for row in rows:
        industry = _clean(row.get("industry_code"), 80) or "general"
        metrics = _metric_values(row)
        bucket = grouped.setdefault(industry, {key: [] for key in METRIC_DEFINITIONS})
        for key, value in metrics.items():
            bucket[key].append(value)
    return grouped


def _upsert_benchmark(conn: Connection, industry: str, metric_key: str, values: list[float], *, period_key: str) -> dict[str, Any]:
    definition = METRIC_DEFINITIONS[metric_key]
    stats = _benchmark_stats(values)
    if stats["sample_count"] < MIN_BENCHMARK_SAMPLE:
        return {"industry_code": industry, "metric_key": metric_key, **stats, "privacy_level": "insufficient_sample", "direction": definition["direction"]}
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_vertical_benchmarks (
                industry_code, cohort_key, metric_key, period_key, sample_count,
                average_value, p50_value, p75_value, p90_value, direction, privacy_level, source_json, computed_at, updated_at
            )
            VALUES (
                :industry_code, 'all', :metric_key, :period_key, :sample_count,
                :average_value, :p50_value, :p75_value, :p90_value, :direction, 'aggregated',
                CAST(:source_json AS jsonb), NOW(), NOW()
            )
            ON CONFLICT (industry_code, cohort_key, metric_key, period_key)
            DO UPDATE SET
                sample_count = EXCLUDED.sample_count,
                average_value = EXCLUDED.average_value,
                p50_value = EXCLUDED.p50_value,
                p75_value = EXCLUDED.p75_value,
                p90_value = EXCLUDED.p90_value,
                direction = EXCLUDED.direction,
                privacy_level = EXCLUDED.privacy_level,
                source_json = EXCLUDED.source_json,
                computed_at = NOW(),
                updated_at = NOW()
            RETURNING industry_code, metric_key, period_key, sample_count, average_value, p50_value, p75_value, p90_value, direction, privacy_level, computed_at::text
            """
        ),
        {
            "industry_code": industry,
            "metric_key": metric_key,
            "period_key": period_key,
            "sample_count": int(stats["sample_count"]),
            "average_value": stats["average_value"],
            "p50_value": stats["p50_value"],
            "p75_value": stats["p75_value"],
            "p90_value": stats["p90_value"],
            "direction": definition["direction"],
            "source_json": _json({"raw_content_used": False, "min_sample": MIN_BENCHMARK_SAMPLE, "aggregation": "tenant_metric_average"}),
        },
    ).mappings().first()
    return dict(row or {})


def _upsert_tenant_benchmark(conn: Connection, tenant_id: str, industry: str, comparison: dict[str, Any], *, period_key: str) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_vertical_tenant_benchmarks (
                tenant_id, industry_code, metric_key, period_key, tenant_value, benchmark_value,
                delta_percent, percentile, sample_count, comparison_label, recommendation_json, computed_at, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), :industry_code, :metric_key, :period_key, :tenant_value, :benchmark_value,
                :delta_percent, :percentile, :sample_count, :comparison_label, CAST(:recommendation_json AS jsonb), NOW(), NOW()
            )
            ON CONFLICT (tenant_id, industry_code, metric_key, period_key)
            DO UPDATE SET
                tenant_value = EXCLUDED.tenant_value,
                benchmark_value = EXCLUDED.benchmark_value,
                delta_percent = EXCLUDED.delta_percent,
                percentile = EXCLUDED.percentile,
                sample_count = EXCLUDED.sample_count,
                comparison_label = EXCLUDED.comparison_label,
                recommendation_json = EXCLUDED.recommendation_json,
                computed_at = NOW(),
                updated_at = NOW()
            RETURNING id::text, industry_code, metric_key, period_key, tenant_value, benchmark_value, delta_percent,
                      percentile, sample_count, comparison_label, recommendation_json, computed_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "industry_code": industry,
            "metric_key": comparison["metric_key"],
            "period_key": period_key,
            "tenant_value": comparison.get("tenant_value"),
            "benchmark_value": comparison.get("benchmark_value"),
            "delta_percent": comparison.get("delta_percent"),
            "percentile": comparison.get("percentile"),
            "sample_count": int(comparison.get("sample_count") or 0),
            "comparison_label": comparison.get("label") or "insufficient_sample",
            "recommendation_json": _json({"message": comparison.get("recommendation"), "direction": comparison.get("direction")}),
        },
    ).mappings().first()
    return dict(row or {})


def _insights_from_comparisons(industry: str, profile: dict[str, Any], comparisons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    insights: list[dict[str, Any]] = [
        {
            "insight_key": f"advisor:{industry}",
            "insight_type": "vertical_advisor",
            "title": profile.get("advisor") or f"{profile.get('label')} AI Advisor",
            "description": f"Copiloto sectorial listo para analizar KPIs de {profile.get('label')} y sugerir playbooks sin compartir datos privados.",
            "severity": "info",
            "confidence": 0.86,
            "kpi_key": "vertical_strategy",
            "recommendation_json": {
                "advisor": profile.get("advisor"),
                "kpis": profile.get("kpis"),
                "next_action": "Revisar benchmarks y elegir un playbook sectorial en modo supervisado.",
            },
            "source_json": {"raw_content_used": False, "source": "vertical_profile"},
        }
    ]
    for item in comparisons:
        metric = item["metric_key"]
        definition = METRIC_DEFINITIONS[metric]
        label = item.get("label")
        if label == "insufficient_sample":
            insights.append(
                {
                    "insight_key": f"benchmark:{metric}:insufficient",
                    "insight_type": "privacy",
                    "title": f"{definition['label']}: benchmark protegido",
                    "description": item.get("recommendation") or definition["low_sample_message"],
                    "severity": "info",
                    "confidence": 0.72,
                    "kpi_key": definition["kpi"],
                    "recommendation_json": {"next_action": "Esperar mayor muestra anonima o usar benchmark interno."},
                    "source_json": {"privacy": "sample_threshold", "sample_count": item.get("sample_count"), "raw_content_used": False},
                }
            )
            continue
        delta = _num(item.get("delta_percent"))
        if label == "below_industry":
            severity = "warn" if delta > -30 else "critical"
            title = f"{definition['label']} por debajo del sector"
            description = f"El KPI esta {abs(delta):.0f}% por debajo del promedio anonimo de la industria."
        elif label == "above_industry":
            severity = "success"
            title = f"{definition['label']} por encima del sector"
            description = f"El KPI esta {delta:.0f}% arriba del promedio anonimo de la industria."
        else:
            severity = "info"
            title = f"{definition['label']} alineado con el sector"
            description = "El KPI esta cerca del benchmark anonimo de la industria."
        insights.append(
            {
                "insight_key": f"benchmark:{metric}",
                "insight_type": "benchmark",
                "title": title,
                "description": description,
                "severity": severity,
                "confidence": min(0.95, 0.65 + (int(item.get("sample_count") or 0) * 0.03)),
                "kpi_key": definition["kpi"],
                "recommendation_json": {"next_action": item.get("recommendation"), "metric_key": metric},
                "source_json": {"sample_count": item.get("sample_count"), "raw_content_used": False, "privacy": "aggregated"},
            }
        )
    return insights


def _upsert_insight(conn: Connection, tenant_id: str, industry: str, insight: dict[str, Any]) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_vertical_insights (
                tenant_id, industry_code, insight_key, insight_type, title, description,
                severity, confidence, kpi_key, recommendation_json, source_json, status, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), :industry_code, :insight_key, :insight_type, :title, :description,
                :severity, :confidence, :kpi_key, CAST(:recommendation_json AS jsonb), CAST(:source_json AS jsonb), 'open', NOW()
            )
            ON CONFLICT (tenant_id, insight_key)
            DO UPDATE SET
                industry_code = EXCLUDED.industry_code,
                insight_type = EXCLUDED.insight_type,
                title = EXCLUDED.title,
                description = EXCLUDED.description,
                severity = EXCLUDED.severity,
                confidence = EXCLUDED.confidence,
                kpi_key = EXCLUDED.kpi_key,
                recommendation_json = EXCLUDED.recommendation_json,
                source_json = EXCLUDED.source_json,
                status = 'open',
                updated_at = NOW()
            RETURNING id::text, industry_code, insight_key, insight_type, title, description, severity,
                      confidence, kpi_key, recommendation_json, source_json, status, created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "industry_code": industry,
            "insight_key": insight["insight_key"],
            "insight_type": insight["insight_type"],
            "title": insight["title"],
            "description": insight["description"],
            "severity": insight["severity"],
            "confidence": insight["confidence"],
            "kpi_key": insight["kpi_key"],
            "recommendation_json": _json(insight.get("recommendation_json") or {}),
            "source_json": _json(insight.get("source_json") or {}),
        },
    ).mappings().first()
    return dict(row or {})


def _list_table(conn: Connection, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    rows = conn.execute(text(sql), params).mappings().all()
    return [dict(row) for row in rows]


def list_vertical_playbooks(conn: Connection, industry_code: str, *, limit: int = 40) -> list[dict[str, Any]]:
    ensure_enterprise_network_tables(conn)
    _seed_vertical_assets(conn)
    industry = _industry_profile(industry_code)["code"]
    return _list_table(
        conn,
        """
        SELECT id::text, industry_code, playbook_key, playbook_type, title, description, kpi_key,
               status, premium_required, required_feature_key, trigger_template_json, workflow_template_json,
               recommendation_json, safety_json, updated_at::text
        FROM saas_ai_vertical_playbooks
        WHERE status = 'published'
          AND industry_code IN (:industry_code, 'general')
        ORDER BY CASE WHEN industry_code = :industry_code THEN 0 ELSE 1 END, playbook_type, title
        LIMIT :limit
        """,
        {"industry_code": industry, "limit": max(1, min(int(limit or 40), 200))},
    )


def _list_models(conn: Connection, industry_code: str, *, limit: int = 40) -> list[dict[str, Any]]:
    return _list_table(
        conn,
        """
        SELECT id::text, industry_code, prediction_type, model_key, model_version, routing_mode,
               status, feature_set_key, required_feature_key, model_metadata_json, metrics_json, updated_at::text
        FROM saas_ai_vertical_industry_models
        WHERE status = 'active'
          AND industry_code IN (:industry_code, 'general')
        ORDER BY CASE WHEN industry_code = :industry_code THEN 0 ELSE 1 END, prediction_type, model_key
        LIMIT :limit
        """,
        {"industry_code": industry_code, "limit": max(1, min(int(limit or 40), 200))},
    )


def _list_knowledge(conn: Connection, industry_code: str, *, limit: int = 20) -> list[dict[str, Any]]:
    return _list_table(
        conn,
        """
        SELECT id::text, industry_code, node_key, node_type, title, summary, tags_json, evidence_json,
               privacy_class, status, updated_at::text
        FROM saas_ai_knowledge_network
        WHERE status = 'published'
          AND industry_code IN (:industry_code, 'general')
        ORDER BY CASE WHEN industry_code = :industry_code THEN 0 ELSE 1 END, node_type, title
        LIMIT :limit
        """,
        {"industry_code": industry_code, "limit": max(1, min(int(limit or 20), 100))},
    )


def _persist_network_metric(conn: Connection, tenant_id: str, industry: str, metric_key: str, value: float, *, period_key: str, dimensions: dict[str, Any]) -> None:
    conn.execute(
        text(
            """
            INSERT INTO saas_ai_network_metrics (
                tenant_id, industry_code, metric_key, metric_value, dimensions_json, period_key, privacy_level
            )
            VALUES (
                CAST(:tenant_id AS uuid), :industry_code, :metric_key, :metric_value,
                CAST(:dimensions_json AS jsonb), :period_key, 'tenant_private'
            )
            """
        ),
        {
            "tenant_id": tenant_id,
            "industry_code": industry,
            "metric_key": metric_key,
            "metric_value": value,
            "dimensions_json": _json(dimensions),
            "period_key": period_key,
        },
    )


def refresh_enterprise_ai_network(
    conn: Connection,
    tenant_id: str,
    *,
    actor_user_id: str = "",
    dry_run: bool = False,
    limit: int = 50,
) -> dict[str, Any]:
    ensure_enterprise_network_tables(conn)
    seeded = _seed_vertical_assets(conn)
    access = _resolve_network_access(conn, tenant_id, require_full=not dry_run)
    tenant = _tenant_industry(conn, tenant_id)
    profile = _industry_profile(str(tenant.get("industry_code") or "general"))
    industry = str(profile["code"])
    period_key = _period_key()
    rows = _tenant_metric_rows(conn)
    tenant_row = next((row for row in rows if str(row.get("tenant_id")) == tenant_id), None)
    if not tenant_row:
        tenant_row = {"tenant_id": tenant_id, "industry_code": industry, "conversations": 0}
    tenant_metrics = _metric_values(tenant_row)
    grouped = _industry_benchmark_map(rows)
    industry_values = grouped.get(industry) or {}
    comparisons: list[dict[str, Any]] = []
    aggregate_rows: list[dict[str, Any]] = []
    tenant_benchmark_rows: list[dict[str, Any]] = []

    for metric_key, tenant_value in tenant_metrics.items():
        peer_values = list(industry_values.get(metric_key) or [])
        comparison = _comparison(metric_key, tenant_value, peer_values)
        comparisons.append(comparison)
        if dry_run:
            aggregate_rows.append({"industry_code": industry, "metric_key": metric_key, **_benchmark_stats(peer_values), "privacy_level": "preview"})
            tenant_benchmark_rows.append({"metric_key": metric_key, **comparison})
            continue
        aggregate_rows.append(_upsert_benchmark(conn, industry, metric_key, peer_values, period_key=period_key))
        tenant_benchmark_rows.append(_upsert_tenant_benchmark(conn, tenant_id, industry, comparison, period_key=period_key))
        _persist_network_metric(conn, tenant_id, industry, metric_key, tenant_value, period_key=period_key, dimensions={"source": "enterprise_ai_network", "raw_content_used": False})

    insights = _insights_from_comparisons(industry, profile, comparisons)[: max(1, min(int(limit or 50), 200))]
    insight_rows = insights if dry_run else [_upsert_insight(conn, tenant_id, industry, item) for item in insights]
    if not dry_run:
        record_intelligence_usage(
            conn,
            tenant_id,
            str(access.get("access_feature") or "enterprise_ai_network"),
            quantity=1,
            metadata={"source": "enterprise_ai_network_refresh", "dry_run": False, "industry_code": industry, "actor_user_id": actor_user_id},
        )
    return {
        "tenant": tenant,
        "industry": profile,
        "access": access,
        "privacy": {
            "raw_messages_shared": False,
            "raw_conversations_shared": False,
            "sensitive_content_shared": False,
            "minimum_benchmark_sample": MIN_BENCHMARK_SAMPLE,
            "aggregation": "industry_metric_average",
        },
        "seeded": seeded,
        "tenant_metrics": tenant_metrics,
        "benchmarks": aggregate_rows,
        "tenant_benchmarks": tenant_benchmark_rows,
        "insights": insight_rows,
        "dry_run": bool(dry_run),
    }


def enterprise_ai_network_center(conn: Connection, tenant_id: str, *, limit: int = 50) -> dict[str, Any]:
    ensure_enterprise_network_tables(conn)
    seeded = _seed_vertical_assets(conn)
    access = _resolve_network_access(conn, tenant_id, require_full=False)
    tenant = _tenant_industry(conn, tenant_id)
    profile = _industry_profile(str(tenant.get("industry_code") or "general"))
    industry = str(profile["code"])
    max_limit = max(1, min(int(limit or 50), 200))
    rows = _tenant_metric_rows(conn)
    tenant_row = next((row for row in rows if str(row.get("tenant_id")) == tenant_id), None) or {"tenant_id": tenant_id, "industry_code": industry}
    tenant_metrics = _metric_values(tenant_row)
    grouped = _industry_benchmark_map(rows)
    comparisons = [
        _comparison(metric_key, value, list((grouped.get(industry) or {}).get(metric_key) or []))
        for metric_key, value in tenant_metrics.items()
    ]
    insights = _list_table(
        conn,
        """
        SELECT id::text, industry_code, insight_key, insight_type, title, description, severity,
               confidence, kpi_key, recommendation_json, source_json, status, created_at::text, updated_at::text
        FROM saas_ai_vertical_insights
        WHERE tenant_id = CAST(:tenant_id AS uuid)
          AND status = 'open'
        ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'warn' THEN 1 WHEN 'success' THEN 2 ELSE 3 END, updated_at DESC
        LIMIT :limit
        """,
        {"tenant_id": tenant_id, "limit": max_limit},
    )
    if not insights:
        insights = _insights_from_comparisons(industry, profile, comparisons)[:max_limit]
    tenant_benchmarks = _list_table(
        conn,
        """
        SELECT id::text, industry_code, metric_key, period_key, tenant_value, benchmark_value,
               delta_percent, percentile, sample_count, comparison_label, recommendation_json, computed_at::text
        FROM saas_ai_vertical_tenant_benchmarks
        WHERE tenant_id = CAST(:tenant_id AS uuid)
          AND industry_code = :industry_code
        ORDER BY computed_at DESC, metric_key
        LIMIT :limit
        """,
        {"tenant_id": tenant_id, "industry_code": industry, "limit": max_limit},
    )
    if not tenant_benchmarks:
        tenant_benchmarks = comparisons
    benchmarks = _list_table(
        conn,
        """
        SELECT id::text, industry_code, cohort_key, metric_key, period_key, sample_count,
               average_value, p50_value, p75_value, p90_value, direction, privacy_level, source_json, computed_at::text
        FROM saas_ai_vertical_benchmarks
        WHERE industry_code = :industry_code
        ORDER BY computed_at DESC, metric_key
        LIMIT :limit
        """,
        {"industry_code": industry, "limit": max_limit},
    )
    if not benchmarks:
        industry_values = grouped.get(industry) or {}
        benchmarks = [{"industry_code": industry, "metric_key": key, **_benchmark_stats(list(values)), "privacy_level": "preview"} for key, values in industry_values.items()]
    playbooks = list_vertical_playbooks(conn, industry, limit=max_limit)
    models = _list_models(conn, industry, limit=max_limit)
    knowledge = _list_knowledge(conn, industry, limit=max_limit)
    advisors = [
        {
            "advisor_key": f"{industry}_advisor",
            "name": profile.get("advisor"),
            "industry_code": industry,
            "industry_label": profile.get("label"),
            "kpis": profile.get("kpis") or [],
            "capabilities": [
                "benchmark_analysis",
                "vertical_playbook_recommendations",
                "workflow_optimization",
                "privacy_safe_business_insights",
            ],
            "routing": {"provider_preference": "kimi_for_deep_reasoning", "fallback": "gemini_or_openrouter"},
        }
    ]
    return {
        "tenant": tenant,
        "industry": profile,
        "access": access,
        "features": {item["key"]: item for item in intelligence_feature_state(conn, tenant_id).get("features", []) if item["key"] in NETWORK_FEATURE_KEYS or item["key"] == "ai_premium"},
        "privacy": {
            "raw_messages_shared": False,
            "raw_conversations_shared": False,
            "sensitive_content_shared": False,
            "tenant_names_shared": False,
            "minimum_benchmark_sample": MIN_BENCHMARK_SAMPLE,
            "cohort_policy": "return only aggregate metrics when sample_count >= minimum",
        },
        "seeded": seeded,
        "tenant_metrics": tenant_metrics,
        "benchmarks": benchmarks,
        "tenant_benchmarks": tenant_benchmarks,
        "insights": insights,
        "playbooks": playbooks,
        "industry_models": models,
        "knowledge_network": knowledge,
        "vertical_advisors": advisors,
        "recommendation_network": {
            "strategy": "industry + tenant behavior + anonymized benchmark deltas",
            "raw_content_used": False,
            "similar_company_recommendations": [
                {
                    "title": "Comparar KPI contra cohorte anonima",
                    "description": "Usar delta porcentual y sample_count para priorizar mejoras sin exponer datos privados.",
                },
                {
                    "title": "Aplicar playbook en modo draft",
                    "description": "Los playbooks se muestran como recomendacion; no activan triggers ni flows automaticamente.",
                },
            ],
        },
    }
