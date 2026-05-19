from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app_saas.billing.limits import ensure_feature_enabled, ensure_tenant_operational

ALL_AGENT_TYPES = [
    "advisor",
    "sales",
    "support",
    "crm_intelligence",
    "campaign_strategist",
    "retention",
    "operations",
    "executive_summary",
    "knowledge",
    "workflow_architect",
]

EDITABLE_STATUSES = {"draft", "active", "paused", "archived"}

AGENT_TEMPLATES: dict[str, dict[str, Any]] = {
    "advisor": {
        "agent_type": "advisor",
        "name": "Advisor Agent",
        "category": "strategy",
        "headline": "Copiloto empresarial y estratega operativo.",
        "description": "Analiza CRM, conversaciones, campanas, triggers y operacion para sugerir acciones.",
        "channels": ["global"],
        "tools": ["crm.read", "analytics.read", "advisor.actions", "campaigns.suggest", "diagnostics.read"],
        "goals": [
            "Detectar oportunidades comerciales",
            "Priorizar clientes y cuellos de botella",
            "Sugerir campanas, triggers y automatizaciones",
        ],
        "personality": {"tone": "estrategico, claro y accionable", "risk_posture": "conservador"},
        "provider_policy": {"route": "advisor", "preferred": "kimi", "fallback": "openrouter"},
        "memory_policy": {"short_term": True, "semantic": True, "business_summary": True},
        "approval_policy": {"requires_human_approval": True, "can_execute_safe_actions": True},
        "risk_level": "medium",
    },
    "sales": {
        "agent_type": "sales",
        "name": "Sales Agent",
        "category": "revenue",
        "headline": "Calificacion, seguimiento y cierre de leads.",
        "description": "Acompana conversaciones comerciales, detecta intencion y propone proximos pasos.",
        "channels": ["whatsapp", "instagram"],
        "tools": ["crm.update", "conversation.reply", "catalog.search", "campaigns.suggest"],
        "goals": ["Calificar leads", "Recuperar conversaciones abiertas", "Aumentar conversion"],
        "personality": {"tone": "humano, vendedor consultivo y breve", "risk_posture": "moderado"},
        "provider_policy": {"route": "sales", "preferred": "gemini", "fallback": "openrouter"},
        "memory_policy": {"short_term": True, "semantic": True, "customer_profile": True},
        "approval_policy": {"requires_human_approval": True, "can_execute_safe_actions": False},
        "risk_level": "high",
    },
    "support": {
        "agent_type": "support",
        "name": "Support Agent",
        "category": "service",
        "headline": "FAQs, soporte y escalacion humana.",
        "description": "Responde preguntas frecuentes usando knowledge base y escala casos sensibles.",
        "channels": ["whatsapp", "instagram"],
        "tools": ["knowledge.search", "conversation.reply", "crm.update", "tickets.create"],
        "goals": ["Resolver dudas repetidas", "Reducir tiempos de respuesta", "Escalar casos criticos"],
        "personality": {"tone": "calido, preciso y resolutivo", "risk_posture": "conservador"},
        "provider_policy": {"route": "support", "preferred": "gemini", "fallback": "mistral"},
        "memory_policy": {"short_term": True, "semantic": True, "knowledge_grounded": True},
        "approval_policy": {"requires_human_approval": True, "can_execute_safe_actions": False},
        "risk_level": "medium",
    },
    "crm_intelligence": {
        "agent_type": "crm_intelligence",
        "name": "CRM Intelligence Agent",
        "category": "crm",
        "headline": "Scoring, segmentacion y salud del pipeline.",
        "description": "Analiza clientes, etapas, tags, pagos e intereses para priorizar oportunidades.",
        "channels": ["global"],
        "tools": ["crm.read", "crm.update", "analytics.read", "segments.create"],
        "goals": ["Puntuar leads", "Segmentar clientes", "Detectar etapas estancadas"],
        "personality": {"tone": "analitico, concreto y orientado a pipeline"},
        "provider_policy": {"route": "classification", "preferred": "mistral", "fallback": "openrouter"},
        "memory_policy": {"short_term": False, "semantic": True, "pipeline_snapshots": True},
        "approval_policy": {"requires_human_approval": True, "can_execute_safe_actions": True},
        "risk_level": "medium",
    },
    "campaign_strategist": {
        "agent_type": "campaign_strategist",
        "name": "Campaign Strategist Agent",
        "category": "marketing",
        "headline": "Ideas de campanas, triggers y remarketing.",
        "description": "Propone campanas, secuencias y reglas basadas en comportamiento real.",
        "channels": ["whatsapp", "instagram"],
        "tools": ["campaigns.create_draft", "triggers.suggest", "remarketing.suggest", "templates.read"],
        "goals": ["Crear campanas accionables", "Optimizar remarketing", "Mejorar plantillas"],
        "personality": {"tone": "creativo, comercial y medible"},
        "provider_policy": {"route": "campaigns", "preferred": "kimi", "fallback": "openrouter"},
        "memory_policy": {"short_term": False, "semantic": True, "campaign_history": True},
        "approval_policy": {"requires_human_approval": True, "can_execute_safe_actions": True},
        "risk_level": "medium",
    },
    "retention": {
        "agent_type": "retention",
        "name": "Retention Agent",
        "category": "growth",
        "headline": "Churn, clientes dormidos y recuperacion.",
        "description": "Detecta riesgo de abandono y sugiere acciones de recuperacion.",
        "channels": ["whatsapp", "instagram"],
        "tools": ["crm.read", "analytics.read", "remarketing.suggest", "segments.create"],
        "goals": ["Reducir abandono", "Reactivar clientes dormidos", "Priorizar retencion"],
        "personality": {"tone": "preventivo, empatico y orientado a retencion"},
        "provider_policy": {"route": "analysis", "preferred": "mistral", "fallback": "openrouter"},
        "memory_policy": {"short_term": False, "semantic": True, "behavioral_memory": True},
        "approval_policy": {"requires_human_approval": True, "can_execute_safe_actions": True},
        "risk_level": "medium",
    },
    "operations": {
        "agent_type": "operations",
        "name": "Operations Agent",
        "category": "ops",
        "headline": "Monitoreo tecnico, Meta health y auto-reparacion.",
        "description": "Observa webhooks, errores, workers, tokens, Meta y recomienda reparaciones.",
        "channels": ["global"],
        "tools": ["diagnostics.read", "meta.checks", "webhooks.repair", "logs.read"],
        "goals": ["Detectar fallas operativas", "Sugerir reparaciones", "Priorizar incidentes"],
        "personality": {"tone": "tecnico, claro y preventivo", "risk_posture": "conservador"},
        "provider_policy": {"route": "ops", "preferred": "kimi", "fallback": "openrouter"},
        "memory_policy": {"short_term": True, "semantic": True, "incident_history": True},
        "approval_policy": {"requires_human_approval": True, "can_execute_safe_actions": False},
        "risk_level": "high",
    },
    "executive_summary": {
        "agent_type": "executive_summary",
        "name": "Executive Summary Agent",
        "category": "executive",
        "headline": "Balances, reportes y resumenes ejecutivos.",
        "description": "Convierte operacion, ventas y soporte en informes ejecutivos faciles de leer.",
        "channels": ["global"],
        "tools": ["analytics.read", "crm.read", "advisor.summarize", "reports.create"],
        "goals": ["Crear balances ejecutivos", "Explicar KPIs", "Resumir prioridades"],
        "personality": {"tone": "ejecutivo, sobrio y accionable"},
        "provider_policy": {"route": "summaries", "preferred": "gemini", "fallback": "openrouter"},
        "memory_policy": {"short_term": False, "semantic": True, "report_history": True},
        "approval_policy": {"requires_human_approval": False, "can_execute_safe_actions": True},
        "risk_level": "low",
    },
    "knowledge": {
        "agent_type": "knowledge",
        "name": "Knowledge Agent",
        "category": "knowledge",
        "headline": "RAG, politicas, documentos y FAQs.",
        "description": "Administra fuentes de conocimiento y valida respuestas contra documentos.",
        "channels": ["global"],
        "tools": ["knowledge.search", "knowledge.audit", "rag.evaluate"],
        "goals": ["Mejorar base de conocimiento", "Reducir alucinaciones", "Detectar huecos de informacion"],
        "personality": {"tone": "preciso, verificable y didactico"},
        "provider_policy": {"route": "rag", "preferred": "gemini", "fallback": "mistral"},
        "memory_policy": {"short_term": False, "semantic": True, "rag": True},
        "approval_policy": {"requires_human_approval": False, "can_execute_safe_actions": True},
        "risk_level": "low",
    },
    "workflow_architect": {
        "agent_type": "workflow_architect",
        "name": "Workflow Architect Agent",
        "category": "automation",
        "headline": "Diseno de automatizaciones y optimizacion de triggers.",
        "description": "Encuentra patrones operativos y propone flujos automatizados con aprobacion humana.",
        "channels": ["global"],
        "tools": ["workflows.create_draft", "triggers.suggest", "remarketing.suggest", "analytics.read"],
        "goals": ["Disenar workflows", "Optimizar triggers", "Reducir trabajo manual"],
        "personality": {"tone": "arquitecto, practico y medible"},
        "provider_policy": {"route": "workflow_reasoning", "preferred": "kimi", "fallback": "openrouter"},
        "memory_policy": {"short_term": True, "semantic": True, "workflow_history": True},
        "approval_policy": {"requires_human_approval": True, "can_execute_safe_actions": True},
        "risk_level": "medium",
    },
}


def _clean(value: Any, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _json_value(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value


def _normalize_agent_type(value: str) -> str:
    clean = _clean(value, 80).lower().replace("-", "_").replace(" ", "_")
    if clean not in AGENT_TEMPLATES:
        raise HTTPException(status_code=400, detail={"code": "unknown_agent_type", "agent_type": clean})
    return clean


def _normalize_status(value: str) -> str:
    clean = _clean(value, 40).lower()
    if clean not in EDITABLE_STATUSES:
        raise HTTPException(status_code=400, detail={"code": "invalid_agent_status", "status": clean})
    return clean


def _ensure_tables(conn: Connection) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_agent_plan_limits (
                plan_code TEXT PRIMARY KEY,
                max_ai_agents INTEGER NOT NULL DEFAULT 1,
                max_active_ai_agents INTEGER NOT NULL DEFAULT 1,
                allowed_agent_types_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                builder_enabled BOOLEAN NOT NULL DEFAULT TRUE,
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
            CREATE TABLE IF NOT EXISTS saas_ai_agents (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                agent_type TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft',
                provider_policy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                personality_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                goals_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                rules_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                channels_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                tools_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                memory_policy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                approval_policy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_saas_ai_agents_tenant_type_lower_name
            ON saas_ai_agents (tenant_id, agent_type, lower(name))
            WHERE status <> 'archived'
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_ai_agents_tenant_status
            ON saas_ai_agents (tenant_id, status, updated_at DESC)
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_agent_events (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                agent_id UUID NULL REFERENCES saas_ai_agents(id) ON DELETE CASCADE,
                actor_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                event_type TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_ai_agent_events_tenant_created
            ON saas_ai_agent_events (tenant_id, created_at DESC)
            """
        )
    )
    _seed_plan_limits(conn)


def _seed_plan_limits(conn: Connection) -> None:
    all_types = ALL_AGENT_TYPES
    rows = [
        ("demo", 2, 1, all_types, True, "Demo de 30 dias: explora AI Agents con ejecucion controlada."),
        ("starter", 1, 1, all_types, True, "Plan starter: un agente AI activo."),
        ("basic", 1, 1, all_types, True, "Plan basico: un agente AI activo."),
        ("growth", 3, 3, all_types, True, "Growth: equipo pequeno con varios agentes AI."),
        ("pro", 6, 6, all_types, True, "Pro: suite de agentes AI para operacion comercial."),
        ("enterprise", 50, 50, all_types, True, "Enterprise: limites negociables y gobierno avanzado."),
    ]
    for plan_code, max_agents, max_active, allowed, builder_enabled, notes in rows:
        conn.execute(
            text(
                """
                INSERT INTO saas_ai_agent_plan_limits (
                    plan_code, max_ai_agents, max_active_ai_agents, allowed_agent_types_json,
                    builder_enabled, notes, updated_at
                )
                VALUES (
                    :plan_code, :max_agents, :max_active, CAST(:allowed AS jsonb),
                    :builder_enabled, :notes, NOW()
                )
                ON CONFLICT (plan_code) DO NOTHING
                """
            ),
            {
                "plan_code": plan_code,
                "max_agents": max_agents,
                "max_active": max_active,
                "allowed": _json(allowed),
                "builder_enabled": builder_enabled,
                "notes": notes,
            },
        )


def _tenant_plan_code(conn: Connection, tenant_id: str) -> tuple[str, str]:
    row = conn.execute(
        text(
            """
            SELECT plan_code, status
            FROM saas_tenants
            WHERE id = CAST(:tenant_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="tenant_not_found")
    plan_code = _clean(row.get("plan_code"), 40).lower() or "starter"
    tenant_status = _clean(row.get("status"), 40).lower()
    if tenant_status == "trial":
        return "demo", tenant_status
    return plan_code, tenant_status


def plan_limits(conn: Connection, tenant_id: str) -> dict[str, Any]:
    _ensure_tables(conn)
    effective_plan_code, tenant_status = _tenant_plan_code(conn, tenant_id)
    row = conn.execute(
        text(
            """
            SELECT plan_code, max_ai_agents, max_active_ai_agents, allowed_agent_types_json,
                   builder_enabled, notes, updated_at::text
            FROM saas_ai_agent_plan_limits
            WHERE plan_code = :plan_code
            LIMIT 1
            """
        ),
        {"plan_code": effective_plan_code},
    ).mappings().first()
    if not row:
        row = conn.execute(
            text(
                """
                SELECT plan_code, max_ai_agents, max_active_ai_agents, allowed_agent_types_json,
                       builder_enabled, notes, updated_at::text
                FROM saas_ai_agent_plan_limits
                WHERE plan_code = 'starter'
                LIMIT 1
                """
            )
        ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="ai_agent_plan_limits_not_found")
    data = dict(row)
    allowed = _json_value(data.get("allowed_agent_types_json"), ALL_AGENT_TYPES)
    counts = agent_counts(conn, tenant_id)
    return {
        "tenant_id": tenant_id,
        "tenant_status": tenant_status,
        "plan_code": data.get("plan_code") or effective_plan_code,
        "max_ai_agents": int(data.get("max_ai_agents") or 0),
        "max_active_ai_agents": int(data.get("max_active_ai_agents") or 0),
        "allowed_agent_types": [str(item) for item in allowed if str(item) in AGENT_TEMPLATES],
        "builder_enabled": bool(data.get("builder_enabled")),
        "notes": data.get("notes") or "",
        "usage": counts,
        "remaining": {
            "total": max(0, int(data.get("max_ai_agents") or 0) - counts["total"]),
            "active": max(0, int(data.get("max_active_ai_agents") or 0) - counts["active"]),
        },
        "updated_at": str(data.get("updated_at") or ""),
    }


def agent_counts(conn: Connection, tenant_id: str) -> dict[str, int]:
    _ensure_tables(conn)
    row = conn.execute(
        text(
            """
            SELECT
                COUNT(*) FILTER (WHERE status <> 'archived')::int AS total,
                COUNT(*) FILTER (WHERE status = 'active')::int AS active,
                COUNT(*) FILTER (WHERE status = 'paused')::int AS paused,
                COUNT(*) FILTER (WHERE status = 'draft')::int AS draft
            FROM saas_ai_agents
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    data = dict(row or {})
    return {key: int(data.get(key) or 0) for key in ("total", "active", "paused", "draft")}


def list_templates() -> list[dict[str, Any]]:
    return [dict(template) for template in AGENT_TEMPLATES.values()]


def _template_payload(agent_type: str) -> dict[str, Any]:
    template = dict(AGENT_TEMPLATES[_normalize_agent_type(agent_type)])
    return {
        "agent_type": template["agent_type"],
        "name": template["name"],
        "description": template["description"],
        "status": "draft",
        "provider_policy_json": template.get("provider_policy", {}),
        "personality_json": template.get("personality", {}),
        "goals_json": template.get("goals", []),
        "rules_json": [],
        "channels_json": template.get("channels", []),
        "tools_json": template.get("tools", []),
        "memory_policy_json": template.get("memory_policy", {}),
        "approval_policy_json": template.get("approval_policy", {}),
        "metrics_json": {"risk_level": template.get("risk_level", "medium"), "category": template.get("category", "")},
    }


def _agent_row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    template = AGENT_TEMPLATES.get(str(row.get("agent_type") or ""), {})
    return {
        "id": str(row.get("id") or ""),
        "tenant_id": str(row.get("tenant_id") or ""),
        "agent_type": str(row.get("agent_type") or ""),
        "name": str(row.get("name") or ""),
        "description": str(row.get("description") or ""),
        "status": str(row.get("status") or "draft"),
        "category": str(template.get("category") or _json_value(row.get("metrics_json"), {}).get("category") or ""),
        "headline": str(template.get("headline") or ""),
        "provider_policy_json": _json_value(row.get("provider_policy_json"), {}),
        "personality_json": _json_value(row.get("personality_json"), {}),
        "goals_json": _json_value(row.get("goals_json"), []),
        "rules_json": _json_value(row.get("rules_json"), []),
        "channels_json": _json_value(row.get("channels_json"), []),
        "tools_json": _json_value(row.get("tools_json"), []),
        "memory_policy_json": _json_value(row.get("memory_policy_json"), {}),
        "approval_policy_json": _json_value(row.get("approval_policy_json"), {}),
        "metrics_json": _json_value(row.get("metrics_json"), {}),
        "created_by_user_id": str(row.get("created_by_user_id") or ""),
        "created_at": str(row.get("created_at") or ""),
        "updated_at": str(row.get("updated_at") or ""),
    }


def _audit(
    conn: Connection,
    *,
    tenant_id: str,
    agent_id: str | None,
    actor_user_id: str | None,
    event_type: str,
    summary: str,
    details: dict[str, Any] | None = None,
) -> None:
    _ensure_tables(conn)
    conn.execute(
        text(
            """
            INSERT INTO saas_ai_agent_events (
                tenant_id, agent_id, actor_user_id, event_type, summary, details_json
            )
            VALUES (
                CAST(:tenant_id AS uuid),
                CASE WHEN :agent_id = '' THEN NULL ELSE CAST(:agent_id AS uuid) END,
                CASE WHEN :actor_user_id = '' THEN NULL ELSE CAST(:actor_user_id AS uuid) END,
                :event_type,
                :summary,
                CAST(:details AS jsonb)
            )
            """
        ),
        {
            "tenant_id": tenant_id,
            "agent_id": agent_id or "",
            "actor_user_id": actor_user_id or "",
            "event_type": _clean(event_type, 80) or "agent.event",
            "summary": _clean(summary, 500),
            "details": _json(details or {}),
        },
    )


def ensure_default_advisor_agent(conn: Connection, tenant_id: str, user_id: str | None = None) -> dict[str, Any] | None:
    _ensure_tables(conn)
    row = conn.execute(
        text(
            """
            SELECT id::text, tenant_id::text, agent_type, name, description, status,
                   provider_policy_json, personality_json, goals_json, rules_json, channels_json,
                   tools_json, memory_policy_json, approval_policy_json, metrics_json,
                   created_by_user_id::text, created_at::text, updated_at::text
            FROM saas_ai_agents
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND agent_type = 'advisor'
              AND status <> 'archived'
            ORDER BY created_at ASC
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    if row:
        return _agent_row_to_dict(dict(row))

    limits = plan_limits(conn, tenant_id)
    if limits["usage"]["total"] >= int(limits["max_ai_agents"] or 0):
        return None
    payload = _template_payload("advisor")
    payload["status"] = "active" if limits["usage"]["active"] < int(limits["max_active_ai_agents"] or 0) else "draft"
    item = _insert_agent(conn, tenant_id=tenant_id, user_id=user_id or "", payload=payload, skip_quota=True)
    _audit(
        conn,
        tenant_id=tenant_id,
        agent_id=item["id"],
        actor_user_id=user_id,
        event_type="agent.seeded",
        summary="Advisor Agent creado automaticamente como agente base del tenant.",
        details={"agent_type": "advisor", "status": item["status"]},
    )
    return item


def _assert_create_allowed(conn: Connection, tenant_id: str, agent_type: str) -> dict[str, Any]:
    ensure_tenant_operational(conn, tenant_id)
    ensure_feature_enabled(conn, tenant_id, "ai")
    limits = plan_limits(conn, tenant_id)
    if not bool(limits.get("builder_enabled")):
        raise HTTPException(status_code=403, detail={"code": "ai_agent_builder_disabled"})
    if agent_type not in set(limits.get("allowed_agent_types") or []):
        raise HTTPException(status_code=403, detail={"code": "agent_type_not_allowed", "agent_type": agent_type})
    if limits["usage"]["total"] >= int(limits["max_ai_agents"] or 0):
        raise HTTPException(
            status_code=402,
            detail={
                "code": "ai_agent_limit_reached",
                "metric": "ai_agents",
                "limit": limits["max_ai_agents"],
                "used": limits["usage"]["total"],
            },
        )
    return limits


def _insert_agent(
    conn: Connection,
    *,
    tenant_id: str,
    user_id: str,
    payload: dict[str, Any],
    skip_quota: bool = False,
) -> dict[str, Any]:
    _ensure_tables(conn)
    agent_type = _normalize_agent_type(str(payload.get("agent_type") or ""))
    if not skip_quota:
        _assert_create_allowed(conn, tenant_id, agent_type)
    template = _template_payload(agent_type)
    merged = {**template, **payload}
    name = _clean(merged.get("name"), 160) or template["name"]
    description = _clean(merged.get("description"), 1200) or template["description"]
    status = _normalize_status(str(merged.get("status") or "draft"))
    if status == "active":
        _assert_activation_allowed(conn, tenant_id, "")
    try:
        row = conn.execute(
            text(
                """
                INSERT INTO saas_ai_agents (
                    tenant_id, agent_type, name, description, status, provider_policy_json,
                    personality_json, goals_json, rules_json, channels_json, tools_json,
                    memory_policy_json, approval_policy_json, metrics_json, created_by_user_id, updated_at
                )
                VALUES (
                    CAST(:tenant_id AS uuid), :agent_type, :name, :description, :status,
                    CAST(:provider_policy_json AS jsonb),
                    CAST(:personality_json AS jsonb),
                    CAST(:goals_json AS jsonb),
                    CAST(:rules_json AS jsonb),
                    CAST(:channels_json AS jsonb),
                    CAST(:tools_json AS jsonb),
                    CAST(:memory_policy_json AS jsonb),
                    CAST(:approval_policy_json AS jsonb),
                    CAST(:metrics_json AS jsonb),
                    CASE WHEN :user_id = '' THEN NULL ELSE CAST(:user_id AS uuid) END,
                    NOW()
                )
                RETURNING id::text, tenant_id::text, agent_type, name, description, status,
                          provider_policy_json, personality_json, goals_json, rules_json, channels_json,
                          tools_json, memory_policy_json, approval_policy_json, metrics_json,
                          created_by_user_id::text, created_at::text, updated_at::text
                """
            ),
            {
                "tenant_id": tenant_id,
                "agent_type": agent_type,
                "name": name,
                "description": description,
                "status": status,
                "provider_policy_json": _json(merged.get("provider_policy_json") or merged.get("provider_policy") or {}),
                "personality_json": _json(merged.get("personality_json") or merged.get("personality") or {}),
                "goals_json": _json(merged.get("goals_json") or merged.get("goals") or []),
                "rules_json": _json(merged.get("rules_json") or []),
                "channels_json": _json(merged.get("channels_json") or merged.get("channels") or []),
                "tools_json": _json(merged.get("tools_json") or merged.get("tools") or []),
                "memory_policy_json": _json(merged.get("memory_policy_json") or merged.get("memory_policy") or {}),
                "approval_policy_json": _json(merged.get("approval_policy_json") or merged.get("approval_policy") or {}),
                "metrics_json": _json(merged.get("metrics_json") or {}),
                "user_id": user_id or "",
            },
        ).mappings().first()
    except Exception as exc:
        if "ux_saas_ai_agents_tenant_type_lower_name" in str(exc) or "duplicate key" in str(exc).lower():
            raise HTTPException(status_code=409, detail={"code": "agent_already_exists", "agent_type": agent_type, "name": name})
        raise
    item = _agent_row_to_dict(dict(row))
    _audit(
        conn,
        tenant_id=tenant_id,
        agent_id=item["id"],
        actor_user_id=user_id,
        event_type="agent.created",
        summary=f"{item['name']} creado desde el registry AI Agents.",
        details={"agent_type": agent_type, "status": status},
    )
    return item


def create_agent(conn: Connection, tenant_id: str, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _insert_agent(conn, tenant_id=tenant_id, user_id=user_id, payload=payload)


def create_from_template(conn: Connection, tenant_id: str, user_id: str, agent_type: str) -> dict[str, Any]:
    clean_type = _normalize_agent_type(agent_type)
    payload = _template_payload(clean_type)
    return _insert_agent(conn, tenant_id=tenant_id, user_id=user_id, payload=payload)


def list_agents(conn: Connection, tenant_id: str, *, include_archived: bool = False, seed_advisor: bool = True) -> list[dict[str, Any]]:
    _ensure_tables(conn)
    if seed_advisor:
        ensure_default_advisor_agent(conn, tenant_id)
    where_archived = "" if include_archived else "AND status <> 'archived'"
    rows = conn.execute(
        text(
            f"""
            SELECT id::text, tenant_id::text, agent_type, name, description, status,
                   provider_policy_json, personality_json, goals_json, rules_json, channels_json,
                   tools_json, memory_policy_json, approval_policy_json, metrics_json,
                   created_by_user_id::text, created_at::text, updated_at::text
            FROM saas_ai_agents
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              {where_archived}
            ORDER BY
              CASE status WHEN 'active' THEN 1 WHEN 'paused' THEN 2 WHEN 'draft' THEN 3 ELSE 4 END,
              updated_at DESC
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().all()
    return [_hydrate_metrics(conn, _agent_row_to_dict(dict(row))) for row in rows]


def get_agent(conn: Connection, tenant_id: str, agent_id: str) -> dict[str, Any]:
    _ensure_tables(conn)
    row = conn.execute(
        text(
            """
            SELECT id::text, tenant_id::text, agent_type, name, description, status,
                   provider_policy_json, personality_json, goals_json, rules_json, channels_json,
                   tools_json, memory_policy_json, approval_policy_json, metrics_json,
                   created_by_user_id::text, created_at::text, updated_at::text
            FROM saas_ai_agents
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:agent_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "agent_id": agent_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="agent_not_found")
    return _hydrate_metrics(conn, _agent_row_to_dict(dict(row)))


def _hydrate_metrics(conn: Connection, item: dict[str, Any]) -> dict[str, Any]:
    metrics = dict(item.get("metrics_json") or {})
    if item.get("agent_type") == "advisor":
        row = conn.execute(
            text(
                """
                SELECT
                    (SELECT COUNT(*)::int FROM saas_advisor_actions WHERE tenant_id = CAST(:tenant_id AS uuid) AND status IN ('draft','pending_approval','approved')) AS pending_actions,
                    (SELECT COUNT(*)::int FROM saas_advisor_messages WHERE tenant_id = CAST(:tenant_id AS uuid) AND role = 'assistant' AND created_at >= NOW() - INTERVAL '7 days') AS assistant_messages_7d,
                    (SELECT COUNT(*)::int FROM saas_ai_insights WHERE tenant_id = CAST(:tenant_id AS uuid) AND status = 'open') AS open_insights
                """
            ),
            {"tenant_id": item["tenant_id"]},
        ).mappings().first()
        if row:
            metrics.update({key: int(row[key] or 0) for key in row.keys()})
    item["metrics_json"] = metrics
    return item


def _assert_activation_allowed(conn: Connection, tenant_id: str, agent_id: str) -> dict[str, Any]:
    limits = plan_limits(conn, tenant_id)
    exclude_clause = "AND id <> CAST(:agent_id AS uuid)" if agent_id else ""
    active_count = int(
        conn.execute(
            text(
                f"""
                SELECT COUNT(*)::int
                FROM saas_ai_agents
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND status = 'active'
                  {exclude_clause}
                """
            ),
            {"tenant_id": tenant_id, "agent_id": agent_id or ""},
        ).scalar()
        or 0
    )
    if active_count >= int(limits["max_active_ai_agents"] or 0):
        raise HTTPException(
            status_code=402,
            detail={
                "code": "active_ai_agent_limit_reached",
                "metric": "active_ai_agents",
                "limit": limits["max_active_ai_agents"],
                "used": active_count,
            },
        )
    return limits


def update_agent(conn: Connection, tenant_id: str, user_id: str, agent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    _ensure_tables(conn)
    current = get_agent(conn, tenant_id, agent_id)
    assignments: list[str] = []
    params: dict[str, Any] = {"tenant_id": tenant_id, "agent_id": agent_id}
    scalar_fields = {"name": 160, "description": 1200}
    for field, limit in scalar_fields.items():
        if field in payload and payload[field] is not None:
            params[field] = _clean(payload[field], limit)
            assignments.append(f"{field} = :{field}")
    if "status" in payload and payload["status"] is not None:
        status = _normalize_status(str(payload["status"]))
        if status == "active" and current["status"] != "active":
            _assert_activation_allowed(conn, tenant_id, agent_id)
        params["status"] = status
        assignments.append("status = :status")
    json_fields = [
        "provider_policy_json",
        "personality_json",
        "goals_json",
        "rules_json",
        "channels_json",
        "tools_json",
        "memory_policy_json",
        "approval_policy_json",
    ]
    for field in json_fields:
        if field in payload and payload[field] is not None:
            params[field] = _json(payload[field])
            assignments.append(f"{field} = CAST(:{field} AS jsonb)")
    if not assignments:
        return current
    sql = f"""
        UPDATE saas_ai_agents
        SET {", ".join(assignments)}, updated_at = NOW()
        WHERE tenant_id = CAST(:tenant_id AS uuid)
          AND id = CAST(:agent_id AS uuid)
        RETURNING id::text, tenant_id::text, agent_type, name, description, status,
                  provider_policy_json, personality_json, goals_json, rules_json, channels_json,
                  tools_json, memory_policy_json, approval_policy_json, metrics_json,
                  created_by_user_id::text, created_at::text, updated_at::text
    """
    row = conn.execute(text(sql), params).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="agent_not_found")
    item = _hydrate_metrics(conn, _agent_row_to_dict(dict(row)))
    _audit(
        conn,
        tenant_id=tenant_id,
        agent_id=agent_id,
        actor_user_id=user_id,
        event_type="agent.updated",
        summary=f"{item['name']} actualizado.",
        details={"fields": list(payload.keys())},
    )
    return item


def set_agent_status(conn: Connection, tenant_id: str, user_id: str, agent_id: str, status: str) -> dict[str, Any]:
    clean_status = _normalize_status(status)
    if clean_status == "active":
        _assert_activation_allowed(conn, tenant_id, agent_id)
    return update_agent(conn, tenant_id, user_id, agent_id, {"status": clean_status})


def list_agent_events(conn: Connection, tenant_id: str, agent_id: str | None = None, limit: int = 60) -> list[dict[str, Any]]:
    _ensure_tables(conn)
    where_agent = "AND agent_id = CAST(:agent_id AS uuid)" if agent_id else ""
    rows = conn.execute(
        text(
            f"""
            SELECT id::text, tenant_id::text, agent_id::text, actor_user_id::text,
                   event_type, summary, details_json, created_at::text
            FROM saas_ai_agent_events
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              {where_agent}
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "agent_id": agent_id or "", "limit": max(1, min(int(limit or 60), 200))},
    ).mappings().all()
    return [
        {
            **dict(row),
            "details_json": _json_value(row.get("details_json"), {}),
        }
        for row in rows
    ]


def add_agent_event(
    conn: Connection,
    tenant_id: str,
    user_id: str,
    agent_id: str,
    *,
    event_type: str,
    summary: str,
    details: dict[str, Any] | None = None,
) -> None:
    get_agent(conn, tenant_id, agent_id)
    _audit(
        conn,
        tenant_id=tenant_id,
        agent_id=agent_id,
        actor_user_id=user_id,
        event_type=event_type,
        summary=summary,
        details=details or {},
    )
