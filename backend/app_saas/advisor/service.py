from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app_saas.ai_agent.service import get_settings
from app_saas.ai_gateway.service import generate_with_gateway


ADVISOR_SYSTEM_PROMPT = """Eres Scentra Advisor, el AI Business Advisor persistente de Scentra.
Tu trabajo es ayudar al usuario a tomar mejores decisiones comerciales y operativas usando CRM, inbox, canales Meta, triggers, remarketing, knowledge base y diagnosticos.
Responde en espanol claro, accionable y con criterio ejecutivo. No inventes datos: si una cifra no esta en contexto, dilo.
Cuando puedas, prioriza acciones por impacto y urgencia. Si una accion puede afectar clientes, campanas, tokens, webhooks o envios masivos, proponla como borrador y pide aprobacion humana.
Devuelve respuestas concretas, con bullets cortos y siguientes pasos."""


def _clean(value: Any, limit: int = 5000) -> str:
    return str(value or "").strip()[:limit]


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def ensure_advisor_tables(conn: Connection) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_advisor_threads (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                user_id UUID NOT NULL REFERENCES saas_users(id) ON DELETE CASCADE,
                title TEXT NOT NULL DEFAULT '',
                context_type TEXT NOT NULL DEFAULT 'global',
                context_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
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
            CREATE INDEX IF NOT EXISTS idx_saas_advisor_threads_tenant_user
            ON saas_advisor_threads (tenant_id, user_id, updated_at DESC)
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_advisor_messages (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                thread_id UUID NOT NULL REFERENCES saas_advisor_threads(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                ai_run_id UUID NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_advisor_messages_thread_created
            ON saas_advisor_messages (thread_id, created_at ASC)
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_advisor_memory (
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                user_id UUID NOT NULL REFERENCES saas_users(id) ON DELETE CASCADE,
                memory_key TEXT NOT NULL DEFAULT 'default',
                summary TEXT NOT NULL DEFAULT '',
                facts_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                last_thread_id UUID NULL REFERENCES saas_advisor_threads(id) ON DELETE SET NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                PRIMARY KEY (tenant_id, user_id, memory_key)
            )
            """
        )
    )
    _ensure_insight_tables(conn)
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_advisor_actions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                created_by UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                recommendation_id UUID NULL REFERENCES saas_ai_recommendations(id) ON DELETE SET NULL,
                insight_id UUID NULL REFERENCES saas_ai_insights(id) ON DELETE SET NULL,
                action_type TEXT NOT NULL DEFAULT 'advisor_action',
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                impact TEXT NOT NULL DEFAULT 'medium',
                risk_level TEXT NOT NULL DEFAULT 'medium',
                approval_required BOOLEAN NOT NULL DEFAULT TRUE,
                status TEXT NOT NULL DEFAULT 'draft',
                approved_by UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                approved_at TIMESTAMP NULL,
                executed_at TIMESTAMP NULL,
                execution_result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_advisor_actions_tenant_status
            ON saas_advisor_actions (tenant_id, status, updated_at DESC)
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_saas_advisor_actions_open_recommendation
            ON saas_advisor_actions (tenant_id, recommendation_id)
            WHERE recommendation_id IS NOT NULL AND status IN ('draft', 'pending_approval', 'approved')
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_saas_advisor_actions_open_insight
            ON saas_advisor_actions (tenant_id, insight_id)
            WHERE insight_id IS NOT NULL AND status IN ('draft', 'pending_approval', 'approved')
            """
        )
    )


def _ensure_insight_tables(conn: Connection) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_recommendations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                ai_run_id UUID NULL,
                recommendation_type TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'info',
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                action_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                confidence NUMERIC(5,2) NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_insights (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                insight_type TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'info',
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                recommended_action_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                status TEXT NOT NULL DEFAULT 'open',
                expires_at TIMESTAMP NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_ai_insights_tenant_status
            ON saas_ai_insights (tenant_id, status, created_at DESC)
            """
        )
    )


def _row_dict(row: Any) -> dict[str, Any]:
    return dict(row or {})


def _safe_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _thread_out(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("id") or ""),
        "title": str(row.get("title") or "Scentra Advisor"),
        "context_type": str(row.get("context_type") or ""),
        "context_id": str(row.get("context_id") or ""),
        "status": str(row.get("status") or "active"),
        "updated_at": str(row.get("updated_at") or ""),
    }


def _message_out(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("id") or ""),
        "role": str(row.get("role") or ""),
        "content": str(row.get("content") or ""),
        "metadata_json": _safe_json(row.get("metadata_json")),
        "ai_run_id": str(row.get("ai_run_id") or ""),
        "created_at": str(row.get("created_at") or ""),
    }


def _action_out(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("id") or ""),
        "action_type": str(row.get("action_type") or "advisor_action"),
        "title": str(row.get("title") or ""),
        "description": str(row.get("description") or ""),
        "payload_json": _safe_json(row.get("payload_json")),
        "impact": str(row.get("impact") or "medium"),
        "risk_level": str(row.get("risk_level") or "medium"),
        "approval_required": bool(row.get("approval_required", True)),
        "status": str(row.get("status") or "draft"),
        "recommendation_id": str(row.get("recommendation_id") or ""),
        "insight_id": str(row.get("insight_id") or ""),
        "approved_by": str(row.get("approved_by") or ""),
        "approved_at": str(row.get("approved_at") or ""),
        "executed_at": str(row.get("executed_at") or ""),
        "execution_result_json": _safe_json(row.get("execution_result_json")),
        "created_at": str(row.get("created_at") or ""),
        "updated_at": str(row.get("updated_at") or ""),
    }


def get_or_create_thread(
    conn: Connection,
    *,
    tenant_id: str,
    user_id: str,
    thread_id: str = "",
    context_type: str = "global",
    context_id: str = "",
    module: str = "dashboard",
    title_seed: str = "",
) -> dict[str, Any]:
    ensure_advisor_tables(conn)
    if thread_id:
        row = conn.execute(
            text(
                """
                SELECT id::text, title, context_type, context_id, status, updated_at::text
                FROM saas_advisor_threads
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND user_id = CAST(:user_id AS uuid)
                  AND id = CAST(:thread_id AS uuid)
                LIMIT 1
                """
            ),
            {"tenant_id": tenant_id, "user_id": user_id, "thread_id": thread_id},
        ).mappings().first()
        if row:
            return _row_dict(row)
    title = _clean(title_seed, 80) or f"Advisor / {module or context_type or 'Scentra'}"
    row = conn.execute(
        text(
            """
            INSERT INTO saas_advisor_threads (
                tenant_id, user_id, title, context_type, context_id, metadata_json
            )
            VALUES (
                CAST(:tenant_id AS uuid), CAST(:user_id AS uuid), :title, :context_type,
                :context_id, CAST(:metadata_json AS jsonb)
            )
            RETURNING id::text, title, context_type, context_id, status, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "title": title,
            "context_type": _clean(context_type, 80) or "global",
            "context_id": _clean(context_id, 120),
            "metadata_json": _json({"module": module}),
        },
    ).mappings().first()
    return _row_dict(row)


def create_message(
    conn: Connection,
    *,
    tenant_id: str,
    thread_id: str,
    role: str,
    content: str,
    metadata: dict[str, Any] | None = None,
    ai_run_id: str = "",
) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            INSERT INTO saas_advisor_messages (
                tenant_id, thread_id, role, content, metadata_json, ai_run_id
            )
            VALUES (
                CAST(:tenant_id AS uuid), CAST(:thread_id AS uuid), :role, :content,
                CAST(:metadata_json AS jsonb), CAST(NULLIF(:ai_run_id, '') AS uuid)
            )
            RETURNING id::text, role, content, metadata_json, COALESCE(ai_run_id::text, '') AS ai_run_id, created_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "thread_id": thread_id,
            "role": _clean(role, 40),
            "content": _clean(content, 20000),
            "metadata_json": _json(metadata or {}),
            "ai_run_id": _clean(ai_run_id, 80),
        },
    ).mappings().first()
    conn.execute(text("UPDATE saas_advisor_threads SET updated_at = NOW() WHERE id = CAST(:id AS uuid)"), {"id": thread_id})
    return _row_dict(row)


def recent_thread_messages(conn: Connection, tenant_id: str, thread_id: str, limit: int = 12) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT id::text, role, content, metadata_json, COALESCE(ai_run_id::text, '') AS ai_run_id, created_at::text
            FROM saas_advisor_messages
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND thread_id = CAST(:thread_id AS uuid)
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "thread_id": thread_id, "limit": max(1, min(int(limit or 12), 40))},
    ).mappings().all()
    items = [_row_dict(row) for row in rows]
    items.reverse()
    return items


def list_threads(conn: Connection, tenant_id: str, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
    ensure_advisor_tables(conn)
    rows = conn.execute(
        text(
            """
            SELECT id::text, title, context_type, context_id, status, updated_at::text
            FROM saas_advisor_threads
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND user_id = CAST(:user_id AS uuid)
            ORDER BY updated_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "user_id": user_id, "limit": max(1, min(int(limit or 20), 100))},
    ).mappings().all()
    return [_thread_out(_row_dict(row)) for row in rows]


def thread_messages(conn: Connection, tenant_id: str, thread_id: str) -> list[dict[str, Any]]:
    ensure_advisor_tables(conn)
    rows = conn.execute(
        text(
            """
            SELECT id::text, role, content, metadata_json, COALESCE(ai_run_id::text, '') AS ai_run_id, created_at::text
            FROM saas_advisor_messages
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND thread_id = CAST(:thread_id AS uuid)
            ORDER BY created_at ASC
            LIMIT 80
            """
        ),
        {"tenant_id": tenant_id, "thread_id": thread_id},
    ).mappings().all()
    return [_message_out(_row_dict(row)) for row in rows]


def advisor_memory(conn: Connection, tenant_id: str, user_id: str) -> dict[str, Any]:
    ensure_advisor_tables(conn)
    row = conn.execute(
        text(
            """
            SELECT summary, facts_json, COALESCE(last_thread_id::text, '') AS last_thread_id, updated_at::text
            FROM saas_advisor_memory
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND user_id = CAST(:user_id AS uuid)
              AND memory_key = 'default'
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "user_id": user_id},
    ).mappings().first()
    data = _row_dict(row)
    data["facts_json"] = _safe_json(data.get("facts_json"))
    return data


def update_advisor_memory(
    conn: Connection,
    *,
    tenant_id: str,
    user_id: str,
    thread_id: str,
    context: dict[str, Any],
    user_message: str,
    assistant_message: str,
) -> dict[str, Any]:
    current = advisor_memory(conn, tenant_id, user_id)
    previous_facts = current.get("facts_json") if isinstance(current.get("facts_json"), dict) else {}
    totals = context.get("totals") if isinstance(context.get("totals"), dict) else {}
    health = context.get("operational_health") if isinstance(context.get("operational_health"), dict) else {}
    now = datetime.now(timezone.utc).isoformat()
    facts = {
        **previous_facts,
        "last_module": _clean(context.get("module"), 80),
        "last_context_type": _clean(context.get("context_type"), 80),
        "last_context_id": _clean(context.get("context_id"), 120),
        "last_question": _clean(user_message, 800),
        "last_answer_preview": _clean(assistant_message, 1000),
        "last_totals": {
            "conversations": int(totals.get("conversations") or 0),
            "unread": int(totals.get("unread") or 0),
            "warm_leads": int(totals.get("warm_leads") or 0),
            "messages_7d": int(totals.get("messages_7d") or 0),
        },
        "last_health": health,
        "last_turn_at": now,
    }
    summary = (
        f"Ultima consulta: {_clean(user_message, 180)}\n"
        f"Ultima orientacion: {_clean(assistant_message, 360)}"
    )
    row = conn.execute(
        text(
            """
            INSERT INTO saas_advisor_memory (
                tenant_id, user_id, memory_key, summary, facts_json, last_thread_id, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), CAST(:user_id AS uuid), 'default',
                :summary, CAST(:facts_json AS jsonb), CAST(:thread_id AS uuid), NOW()
            )
            ON CONFLICT (tenant_id, user_id, memory_key)
            DO UPDATE SET
                summary = EXCLUDED.summary,
                facts_json = saas_advisor_memory.facts_json || EXCLUDED.facts_json,
                last_thread_id = EXCLUDED.last_thread_id,
                updated_at = NOW()
            RETURNING summary, facts_json, COALESCE(last_thread_id::text, '') AS last_thread_id, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "thread_id": thread_id,
            "summary": _clean(summary, 1200),
            "facts_json": _json(facts),
        },
    ).mappings().first()
    data = _row_dict(row)
    data["facts_json"] = _safe_json(data.get("facts_json"))
    return data


def advisor_context(conn: Connection, tenant_id: str, *, module: str, context_type: str, context_id: str) -> dict[str, Any]:
    tenant = conn.execute(
        text(
            """
            SELECT id::text, name, slug, status, plan_code
            FROM saas_tenants
            WHERE id = CAST(:tenant_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    totals = conn.execute(
        text(
            """
            SELECT
                COUNT(*)::int AS conversations,
                COALESCE(SUM(unread_count), 0)::int AS unread,
                COUNT(*) FILTER (WHERE takeover = TRUE)::int AS takeover,
                COUNT(*) FILTER (WHERE crm_stage IN ('interes', 'intencion_compra', 'pago_pendiente'))::int AS warm_leads,
                COUNT(*) FILTER (WHERE payment_status = 'pending')::int AS pending_payments
            FROM saas_conversations
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    message_totals = conn.execute(
        text(
            """
            SELECT
                COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days')::int AS messages_7d,
                COUNT(*) FILTER (WHERE direction = 'in' AND created_at >= NOW() - INTERVAL '7 days')::int AS inbound_7d,
                COUNT(*) FILTER (WHERE direction = 'out' AND created_at >= NOW() - INTERVAL '7 days')::int AS outbound_7d
            FROM saas_messages
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    recent_conversations = conn.execute(
        text(
            """
            SELECT id::text, channel, display_name, phone, external_contact_id, crm_stage,
                   payment_status, intent, unread_count, last_message_text, updated_at::text
            FROM saas_conversations
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY updated_at DESC
            LIMIT 8
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().all()
    selected_conversation: dict[str, Any] = {}
    selected_messages: list[dict[str, Any]] = []
    if context_id and context_type in {"conversation", "inbox", "customer"}:
        selected_conversation = _row_dict(
            conn.execute(
                text(
                    """
                    SELECT id::text, channel, display_name, phone, external_contact_id, first_name,
                           last_name, city, customer_type, interests, tags, notes, payment_status,
                           crm_stage, intent, unread_count, takeover, updated_at::text
                    FROM saas_conversations
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND id = CAST(:conversation_id AS uuid)
                    LIMIT 1
                    """
                ),
                {"tenant_id": tenant_id, "conversation_id": context_id},
            ).mappings().first()
        )
        selected_messages = [
            _row_dict(row)
            for row in conn.execute(
                text(
                    """
                    SELECT direction, msg_type, LEFT(COALESCE(NULLIF(text, ''), '[' || msg_type || ']'), 500) AS text,
                           created_at::text
                    FROM saas_messages
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND conversation_id = CAST(:conversation_id AS uuid)
                    ORDER BY created_at DESC
                    LIMIT 16
                    """
                ),
                {"tenant_id": tenant_id, "conversation_id": context_id},
            ).mappings().all()
        ]
        selected_messages.reverse()
    webhook_health = conn.execute(
        text(
            """
            SELECT
                COUNT(*) FILTER (WHERE status = 'pending')::int AS pending,
                COUNT(*) FILTER (WHERE status = 'failed')::int AS failed,
                COUNT(*) FILTER (WHERE received_at >= NOW() - INTERVAL '24 hours')::int AS last_24h
            FROM saas_webhook_events
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    webhook_signal = conn.execute(
        text(
            """
            SELECT
                COUNT(*) FILTER (
                    WHERE payload_json::text ILIKE '%"statuses"%'
                      AND received_at >= NOW() - INTERVAL '24 hours'
                )::int AS status_events_24h,
                COUNT(*) FILTER (
                    WHERE payload_json::text ILIKE '%"messages"%'
                      AND received_at >= NOW() - INTERVAL '24 hours'
                )::int AS inbound_events_24h,
                COUNT(*) FILTER (
                    WHERE payload_json::text ILIKE '%"statuses"%'
                      AND received_at >= NOW() - INTERVAL '7 days'
                )::int AS status_events_7d,
                COUNT(*) FILTER (
                    WHERE payload_json::text ILIKE '%"messages"%'
                      AND received_at >= NOW() - INTERVAL '7 days'
                )::int AS inbound_events_7d
            FROM saas_webhook_events
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    outbound_health = conn.execute(
        text(
            """
            SELECT
                COUNT(*) FILTER (WHERE status IN ('failed', 'blocked'))::int AS failed_or_blocked,
                COUNT(*) FILTER (WHERE status = 'queued')::int AS queued
            FROM saas_outbound_messages
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    return {
        "module": module,
        "context_type": context_type,
        "context_id": context_id,
        "tenant": _row_dict(tenant),
        "totals": {**_row_dict(totals), **_row_dict(message_totals)},
        "recent_conversations": [_row_dict(row) for row in recent_conversations],
        "selected_conversation": selected_conversation,
        "selected_messages": selected_messages,
        "operational_health": {
            "webhooks": _row_dict(webhook_health),
            "whatsapp_signal": _row_dict(webhook_signal),
            "outbound": _row_dict(outbound_health),
        },
    }


def _advisor_provider_chain(settings: dict[str, Any]) -> list[str]:
    configured = [
        "kimi",
        _clean(settings.get("provider_code"), 80).lower(),
        _clean(settings.get("fallback_provider_code"), 80).lower(),
        "google",
        "openrouter",
    ]
    out: list[str] = []
    for item in configured:
        if item and item not in out:
            out.append(item)
    return out


def _advisor_prompt(context: dict[str, Any], history: list[dict[str, Any]], message: str) -> tuple[str, str]:
    transcript = "\n".join(f"{item.get('role')}: {_clean(item.get('content'), 1200)}" for item in history[-10:])
    user_prompt = f"""
Contexto operativo de Scentra:
{json.dumps(context, ensure_ascii=False)}

Conversacion reciente con el Advisor:
{transcript or "Sin historial previo."}

Pregunta o solicitud del usuario:
{message}

Instrucciones:
1. Responde como Advisor comercial-operativo.
2. Si detectas oportunidad, riesgo o problema, mencionalo con prioridad.
3. Si recomiendas una automatizacion, trigger, remarketing o accion Meta, dilo como propuesta, no como accion ejecutada.
4. Termina con 1 a 3 siguientes pasos claros.
"""
    return ADVISOR_SYSTEM_PROMPT, user_prompt


def generate_seed_insights(conn: Connection, tenant_id: str) -> list[dict[str, Any]]:
    ensure_advisor_tables(conn)
    context = advisor_context(conn, tenant_id, module="dashboard", context_type="global", context_id="")
    totals = context.get("totals") or {}
    health = context.get("operational_health") or {}
    suggestions: list[dict[str, Any]] = []
    unread = int(totals.get("unread") or 0)
    warm = int(totals.get("warm_leads") or 0)
    webhook_failed = int(((health.get("webhooks") or {}).get("failed")) or 0)
    outbound_failed = int(((health.get("outbound") or {}).get("failed_or_blocked")) or 0)
    whatsapp_signal = health.get("whatsapp_signal") or {}
    statuses_7d = int(whatsapp_signal.get("status_events_7d") or 0)
    inbound_7d = int(whatsapp_signal.get("inbound_events_7d") or 0)
    if unread > 0:
        suggestions.append({
            "insight_type": "unread_followup",
            "severity": "high" if unread >= 10 else "medium",
            "title": f"{unread} conversaciones sin leer",
            "description": "Prioriza respuestas pendientes antes de activar nuevas campanas.",
            "recommended_action_json": {"type": "open_inbox", "module": "inbox"},
        })
    if warm > 0:
        suggestions.append({
            "insight_type": "warm_leads",
            "severity": "high" if warm >= 10 else "medium",
            "title": f"{warm} leads en etapas calientes",
            "description": "Hay clientes en interes, intencion de compra o pago pendiente que pueden convertirse con seguimiento.",
            "recommended_action_json": {"type": "review_crm", "module": "customers"},
        })
    if webhook_failed or outbound_failed:
        suggestions.append({
            "insight_type": "operational_health",
            "severity": "high",
            "title": "Hay senales operacionales para revisar",
            "description": f"Webhooks fallidos: {webhook_failed}. Outbound fallidos/bloqueados: {outbound_failed}.",
            "recommended_action_json": {"type": "open_debug", "module": "settings", "tab": "debug"},
        })
    if statuses_7d > 0 and inbound_7d == 0:
        suggestions.append({
            "insight_type": "whatsapp_status_without_inbound",
            "severity": "critical",
            "title": "WhatsApp reporta estados pero no mensajes entrantes",
            "description": "Esto suele indicar que el WABA no esta suscrito a la app o que el webhook no recibe el campo messages.",
            "recommended_action_json": {"type": "open_debug", "module": "settings", "tab": "debug"},
        })
    for item in suggestions:
        conn.execute(
            text(
                """
                INSERT INTO saas_ai_insights (
                    tenant_id, insight_type, severity, title, description, evidence_json, recommended_action_json, status, updated_at
                )
                SELECT CAST(:tenant_id AS uuid), :insight_type, :severity, :title, :description,
                       CAST(:evidence_json AS jsonb), CAST(:recommended_action_json AS jsonb), 'open', NOW()
                WHERE NOT EXISTS (
                    SELECT 1 FROM saas_ai_insights
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND insight_type = :insight_type
                      AND status = 'open'
                      AND created_at >= NOW() - INTERVAL '12 hours'
                )
                """
            ),
            {
                "tenant_id": tenant_id,
                "insight_type": item["insight_type"],
                "severity": item["severity"],
                "title": item["title"],
                "description": item["description"],
                "evidence_json": _json({"totals": totals, "health": health}),
                "recommended_action_json": _json(item["recommended_action_json"]),
            },
        )
    _seed_recommendations(conn, tenant_id, suggestions, {"totals": totals, "health": health})
    return list_insights(conn, tenant_id, limit=20)


def _seed_recommendations(
    conn: Connection,
    tenant_id: str,
    suggestions: list[dict[str, Any]],
    evidence: dict[str, Any],
) -> None:
    for item in suggestions:
        action = item.get("recommended_action_json") if isinstance(item.get("recommended_action_json"), dict) else {}
        conn.execute(
            text(
                """
                INSERT INTO saas_ai_recommendations (
                    tenant_id, recommendation_type, severity, title, description,
                    evidence_json, action_json, confidence, status, updated_at
                )
                SELECT CAST(:tenant_id AS uuid), :recommendation_type, :severity, :title, :description,
                       CAST(:evidence_json AS jsonb), CAST(:action_json AS jsonb), :confidence, 'open', NOW()
                WHERE NOT EXISTS (
                    SELECT 1 FROM saas_ai_recommendations
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND recommendation_type = :recommendation_type
                      AND status = 'open'
                      AND created_at >= NOW() - INTERVAL '12 hours'
                )
                """
            ),
            {
                "tenant_id": tenant_id,
                "recommendation_type": _clean(item.get("insight_type"), 100) or "advisor_recommendation",
                "severity": _clean(item.get("severity"), 40) or "info",
                "title": _clean(item.get("title"), 220),
                "description": _clean(item.get("description"), 1200),
                "evidence_json": _json(evidence),
                "action_json": _json(action),
                "confidence": 0.72,
            },
        )


def list_insights(conn: Connection, tenant_id: str, limit: int = 20) -> list[dict[str, Any]]:
    ensure_advisor_tables(conn)
    rows = conn.execute(
        text(
            """
            SELECT id::text, insight_type, severity, title, description, evidence_json,
                   recommended_action_json, status, created_at::text, updated_at::text
            FROM saas_ai_insights
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND status = 'open'
            ORDER BY
              CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
              created_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "limit": max(1, min(int(limit or 20), 100))},
    ).mappings().all()
    return [_row_dict(row) for row in rows]


def list_recommendations(conn: Connection, tenant_id: str, limit: int = 20) -> list[dict[str, Any]]:
    ensure_advisor_tables(conn)
    rows = conn.execute(
        text(
            """
            SELECT id::text, recommendation_type, severity, title, description, evidence_json,
                   action_json, confidence, status, created_at::text, updated_at::text
            FROM saas_ai_recommendations
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND status = 'open'
            ORDER BY
              CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
              created_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "limit": max(1, min(int(limit or 20), 100))},
    ).mappings().all()
    return [_row_dict(row) for row in rows]


def dismiss_insight(conn: Connection, tenant_id: str, insight_id: str) -> dict[str, Any]:
    ensure_advisor_tables(conn)
    row = conn.execute(
        text(
            """
            UPDATE saas_ai_insights
            SET status = 'dismissed', updated_at = NOW()
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:insight_id AS uuid)
            RETURNING id::text, status
            """
        ),
        {"tenant_id": tenant_id, "insight_id": insight_id},
    ).mappings().first()
    return _row_dict(row)


def dismiss_recommendation(conn: Connection, tenant_id: str, recommendation_id: str) -> dict[str, Any]:
    ensure_advisor_tables(conn)
    row = conn.execute(
        text(
            """
            UPDATE saas_ai_recommendations
            SET status = 'dismissed', updated_at = NOW()
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:recommendation_id AS uuid)
            RETURNING id::text, status
            """
        ),
        {"tenant_id": tenant_id, "recommendation_id": recommendation_id},
    ).mappings().first()
    return _row_dict(row)


def list_actions(conn: Connection, tenant_id: str, *, status: str = "open", limit: int = 20) -> list[dict[str, Any]]:
    ensure_advisor_tables(conn)
    status_value = _clean(status, 40).lower()
    status_filter = "AND status IN ('draft', 'pending_approval', 'approved')" if status_value in {"", "open"} else "AND status = :status"
    rows = conn.execute(
        text(
            f"""
            SELECT id::text, action_type, title, description, payload_json, impact, risk_level,
                   approval_required, status, recommendation_id::text, insight_id::text,
                   approved_by::text, approved_at::text, executed_at::text,
                   execution_result_json, created_at::text, updated_at::text
            FROM saas_advisor_actions
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              {status_filter}
            ORDER BY
              CASE risk_level WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
              updated_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "status": status_value, "limit": max(1, min(int(limit or 20), 100))},
    ).mappings().all()
    return [_action_out(_row_dict(row)) for row in rows]


def _source_action_type(source_type: str, row: dict[str, Any], action: dict[str, Any]) -> str:
    if action.get("type"):
        return _clean(action.get("type"), 100)
    if action.get("module") or action.get("tab"):
        return f"open_{_clean(action.get('module') or action.get('tab'), 80)}"
    return _clean(row.get("recommendation_type") or row.get("insight_type") or source_type, 100) or "advisor_action"


def create_action_from_recommendation(
    conn: Connection,
    tenant_id: str,
    user_id: str,
    recommendation_id: str,
) -> dict[str, Any]:
    ensure_advisor_tables(conn)
    source = conn.execute(
        text(
            """
            SELECT id::text, recommendation_type, severity, title, description, action_json, evidence_json
            FROM saas_ai_recommendations
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:recommendation_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "recommendation_id": recommendation_id},
    ).mappings().first()
    row = _row_dict(source)
    if not row:
        return {}
    action = _safe_json(row.get("action_json"))
    severity = _clean(row.get("severity"), 40).lower()
    result = conn.execute(
        text(
            """
            INSERT INTO saas_advisor_actions (
                tenant_id, created_by, recommendation_id, action_type, title, description,
                payload_json, impact, risk_level, approval_required, status, execution_result_json, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), CAST(:user_id AS uuid), CAST(:recommendation_id AS uuid),
                :action_type, :title, :description, CAST(:payload_json AS jsonb),
                :impact, :risk_level, TRUE, 'pending_approval',
                CAST(:execution_result_json AS jsonb), NOW()
            )
            ON CONFLICT DO NOTHING
            RETURNING id::text, action_type, title, description, payload_json, impact, risk_level,
                      approval_required, status, recommendation_id::text, insight_id::text,
                      approved_by::text, approved_at::text, executed_at::text,
                      execution_result_json, created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "recommendation_id": recommendation_id,
            "action_type": _source_action_type("recommendation", row, action),
            "title": _clean(row.get("title"), 180) or "Accion recomendada por Advisor",
            "description": _clean(row.get("description"), 1200),
            "payload_json": _json({"source": "recommendation", "action": action, "evidence": _safe_json(row.get("evidence_json"))}),
            "impact": "high" if severity in {"critical", "high"} else "medium",
            "risk_level": "high" if severity == "critical" else ("medium" if severity == "high" else "low"),
            "execution_result_json": _json({"state": "awaiting_human_approval"}),
        },
    ).mappings().first()
    if result:
        return _action_out(_row_dict(result))
    existing = conn.execute(
        text(
            """
            SELECT id::text, action_type, title, description, payload_json, impact, risk_level,
                   approval_required, status, recommendation_id::text, insight_id::text,
                   approved_by::text, approved_at::text, executed_at::text,
                   execution_result_json, created_at::text, updated_at::text
            FROM saas_advisor_actions
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND recommendation_id = CAST(:recommendation_id AS uuid)
              AND status IN ('draft', 'pending_approval', 'approved')
            ORDER BY updated_at DESC
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "recommendation_id": recommendation_id},
    ).mappings().first()
    return _action_out(_row_dict(existing))


def create_action_from_insight(conn: Connection, tenant_id: str, user_id: str, insight_id: str) -> dict[str, Any]:
    ensure_advisor_tables(conn)
    source = conn.execute(
        text(
            """
            SELECT id::text, insight_type, severity, title, description, recommended_action_json, evidence_json
            FROM saas_ai_insights
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:insight_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "insight_id": insight_id},
    ).mappings().first()
    row = _row_dict(source)
    if not row:
        return {}
    action = _safe_json(row.get("recommended_action_json"))
    severity = _clean(row.get("severity"), 40).lower()
    result = conn.execute(
        text(
            """
            INSERT INTO saas_advisor_actions (
                tenant_id, created_by, insight_id, action_type, title, description,
                payload_json, impact, risk_level, approval_required, status, execution_result_json, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), CAST(:user_id AS uuid), CAST(:insight_id AS uuid),
                :action_type, :title, :description, CAST(:payload_json AS jsonb),
                :impact, :risk_level, TRUE, 'pending_approval',
                CAST(:execution_result_json AS jsonb), NOW()
            )
            ON CONFLICT DO NOTHING
            RETURNING id::text, action_type, title, description, payload_json, impact, risk_level,
                      approval_required, status, recommendation_id::text, insight_id::text,
                      approved_by::text, approved_at::text, executed_at::text,
                      execution_result_json, created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "insight_id": insight_id,
            "action_type": _source_action_type("insight", row, action),
            "title": _clean(row.get("title"), 180) or "Accion sugerida por Advisor",
            "description": _clean(row.get("description"), 1200),
            "payload_json": _json({"source": "insight", "action": action, "evidence": _safe_json(row.get("evidence_json"))}),
            "impact": "high" if severity in {"critical", "high"} else "medium",
            "risk_level": "high" if severity == "critical" else ("medium" if severity == "high" else "low"),
            "execution_result_json": _json({"state": "awaiting_human_approval"}),
        },
    ).mappings().first()
    if result:
        return _action_out(_row_dict(result))
    existing = conn.execute(
        text(
            """
            SELECT id::text, action_type, title, description, payload_json, impact, risk_level,
                   approval_required, status, recommendation_id::text, insight_id::text,
                   approved_by::text, approved_at::text, executed_at::text,
                   execution_result_json, created_at::text, updated_at::text
            FROM saas_advisor_actions
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND insight_id = CAST(:insight_id AS uuid)
              AND status IN ('draft', 'pending_approval', 'approved')
            ORDER BY updated_at DESC
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "insight_id": insight_id},
    ).mappings().first()
    return _action_out(_row_dict(existing))


def create_custom_action(
    conn: Connection,
    tenant_id: str,
    user_id: str,
    *,
    title: str,
    description: str,
    action_type: str,
    payload_json: dict[str, Any],
    impact: str,
    risk_level: str,
) -> dict[str, Any]:
    ensure_advisor_tables(conn)
    row = conn.execute(
        text(
            """
            INSERT INTO saas_advisor_actions (
                tenant_id, created_by, action_type, title, description,
                payload_json, impact, risk_level, approval_required, status, execution_result_json, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), CAST(:user_id AS uuid), :action_type, :title, :description,
                CAST(:payload_json AS jsonb), :impact, :risk_level, TRUE, 'pending_approval',
                CAST(:execution_result_json AS jsonb), NOW()
            )
            RETURNING id::text, action_type, title, description, payload_json, impact, risk_level,
                      approval_required, status, recommendation_id::text, insight_id::text,
                      approved_by::text, approved_at::text, executed_at::text,
                      execution_result_json, created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "action_type": _clean(action_type, 100) or "advisor_action",
            "title": _clean(title, 180) or "Accion sugerida por Advisor",
            "description": _clean(description, 1200),
            "payload_json": _json(payload_json or {}),
            "impact": _clean(impact, 40) or "medium",
            "risk_level": _clean(risk_level, 40) or "medium",
            "execution_result_json": _json({"state": "awaiting_human_approval"}),
        },
    ).mappings().first()
    return _action_out(_row_dict(row))


def approve_action(conn: Connection, tenant_id: str, user_id: str, action_id: str) -> dict[str, Any]:
    ensure_advisor_tables(conn)
    row = conn.execute(
        text(
            """
            UPDATE saas_advisor_actions
            SET status = 'approved',
                approved_by = CAST(:user_id AS uuid),
                approved_at = NOW(),
                execution_result_json = jsonb_set(
                    COALESCE(execution_result_json, '{}'::jsonb),
                    '{state}',
                    '"approved_waiting_execution"'::jsonb,
                    TRUE
                ),
                updated_at = NOW()
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:action_id AS uuid)
              AND status IN ('draft', 'pending_approval')
            RETURNING id::text, action_type, title, description, payload_json, impact, risk_level,
                      approval_required, status, recommendation_id::text, insight_id::text,
                      approved_by::text, approved_at::text, executed_at::text,
                      execution_result_json, created_at::text, updated_at::text
            """
        ),
        {"tenant_id": tenant_id, "user_id": user_id, "action_id": action_id},
    ).mappings().first()
    return _action_out(_row_dict(row))


def dismiss_action(conn: Connection, tenant_id: str, action_id: str) -> dict[str, Any]:
    ensure_advisor_tables(conn)
    row = conn.execute(
        text(
            """
            UPDATE saas_advisor_actions
            SET status = 'dismissed', updated_at = NOW()
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:action_id AS uuid)
            RETURNING id::text, status, updated_at::text
            """
        ),
        {"tenant_id": tenant_id, "action_id": action_id},
    ).mappings().first()
    return _row_dict(row)


def advisor_chat(
    conn: Connection,
    *,
    tenant_id: str,
    user_id: str,
    message: str,
    thread_id: str,
    context_type: str,
    context_id: str,
    module: str,
) -> dict[str, Any]:
    ensure_advisor_tables(conn)
    thread = get_or_create_thread(
        conn,
        tenant_id=tenant_id,
        user_id=user_id,
        thread_id=thread_id,
        context_type=context_type,
        context_id=context_id,
        module=module,
        title_seed=_clean(message, 72),
    )
    user_msg = create_message(
        conn,
        tenant_id=tenant_id,
        thread_id=str(thread["id"]),
        role="user",
        content=message,
        metadata={"module": module, "context_type": context_type, "context_id": context_id},
    )
    history = recent_thread_messages(conn, tenant_id, str(thread["id"]), limit=14)
    context = advisor_context(conn, tenant_id, module=module, context_type=context_type, context_id=context_id)
    context["advisor_memory"] = advisor_memory(conn, tenant_id, user_id)
    settings = get_settings(conn, tenant_id)
    system_prompt, user_prompt = _advisor_prompt(context, history, message)
    gateway = generate_with_gateway(
        conn,
        tenant_id=tenant_id,
        task_type="advisor_chat",
        agent_type="advisor_agent",
        route_code="advisor.insights",
        conversation_id=context_id if context_type in {"conversation", "inbox", "customer"} else "",
        provider_chain=_advisor_provider_chain(settings),
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        settings={**settings, "max_tokens": min(int(settings.get("max_tokens") or 1800), 2200)},
    )
    if not gateway.get("ok"):
        reason = _clean(gateway.get("skipped") or "advisor_ai_unavailable", 500)
        fallback_answer = (
            "Todavia no puedo generar una respuesta con modelo AI para este tenant.\n\n"
            "Lo mas probable es que falte guardar una API key y seleccionar modelo en Ajustes > APIs, "
            "o que el proveedor configurado no tenga credencial activa.\n\n"
            "Mientras tanto ya revise senales basicas del negocio: abre el panel de insights del Advisor "
            "para ver pendientes de inbox, leads calientes y salud operacional."
        )
        assistant_msg = create_message(
            conn,
            tenant_id=tenant_id,
            thread_id=str(thread["id"]),
            role="assistant",
            content=fallback_answer,
            metadata={"fallback_reason": reason, "context_type": context_type, "context_id": context_id},
        )
        memory = update_advisor_memory(
            conn,
            tenant_id=tenant_id,
            user_id=user_id,
            thread_id=str(thread["id"]),
            context=context,
            user_message=message,
            assistant_message=fallback_answer,
        )
        insights = generate_seed_insights(conn, tenant_id)
        recommendations = list_recommendations(conn, tenant_id, limit=10)
        actions = list_actions(conn, tenant_id, status="open", limit=8)
        return {
            "ok": False,
            "thread": _thread_out(thread),
            "user_message": _message_out(user_msg),
            "assistant_message": _message_out(assistant_msg),
            "insights": insights,
            "recommendations": recommendations,
            "memory": memory,
            "actions": actions,
        }
    assistant_msg = create_message(
        conn,
        tenant_id=tenant_id,
        thread_id=str(thread["id"]),
        role="assistant",
        content=_clean(gateway.get("raw"), 20000),
        metadata={
            "provider_code": gateway.get("provider_code"),
            "model": gateway.get("model"),
            "fallback_used": gateway.get("fallback_used"),
            "latency_ms": gateway.get("latency_ms"),
            "context_type": context_type,
            "context_id": context_id,
        },
        ai_run_id=str(gateway.get("run_id") or ""),
    )
    memory = update_advisor_memory(
        conn,
        tenant_id=tenant_id,
        user_id=user_id,
        thread_id=str(thread["id"]),
        context=context,
        user_message=message,
        assistant_message=_clean(gateway.get("raw"), 20000),
    )
    insights = generate_seed_insights(conn, tenant_id)
    recommendations = list_recommendations(conn, tenant_id, limit=10)
    actions = list_actions(conn, tenant_id, status="open", limit=8)
    return {
        "ok": True,
        "thread": _thread_out(thread),
        "user_message": _message_out(user_msg),
        "assistant_message": _message_out(assistant_msg),
        "insights": insights,
        "recommendations": recommendations,
        "memory": memory,
        "actions": actions,
    }


def chunk_advisor_text(value: str, size: int = 92) -> list[str]:
    text_value = str(value or "")
    if not text_value:
        return []
    chunks: list[str] = []
    current = ""
    for token in text_value.replace("\r\n", "\n").split(" "):
        candidate = f"{current} {token}".strip()
        if len(candidate) >= size and current:
            chunks.append(current)
            current = token
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks

