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
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_advisor_audit_events (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                thread_id UUID NULL REFERENCES saas_advisor_threads(id) ON DELETE SET NULL,
                message_id UUID NULL REFERENCES saas_advisor_messages(id) ON DELETE SET NULL,
                action_id UUID NULL REFERENCES saas_advisor_actions(id) ON DELETE SET NULL,
                event_type TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'info',
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
            CREATE INDEX IF NOT EXISTS idx_saas_advisor_audit_tenant_created
            ON saas_advisor_audit_events (tenant_id, created_at DESC)
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_advisor_feedback (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                message_id UUID NOT NULL REFERENCES saas_advisor_messages(id) ON DELETE CASCADE,
                rating TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, user_id, message_id)
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_advisor_feedback_tenant_rating
            ON saas_advisor_feedback (tenant_id, rating, updated_at DESC)
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


def _event_out(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("id") or ""),
        "event_type": str(row.get("event_type") or ""),
        "severity": str(row.get("severity") or "info"),
        "summary": str(row.get("summary") or ""),
        "details_json": _safe_json(row.get("details_json")),
        "thread_id": str(row.get("thread_id") or ""),
        "message_id": str(row.get("message_id") or ""),
        "action_id": str(row.get("action_id") or ""),
        "user_id": str(row.get("user_id") or ""),
        "created_at": str(row.get("created_at") or ""),
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


def record_advisor_event(
    conn: Connection,
    tenant_id: str,
    *,
    event_type: str,
    summary: str,
    user_id: str = "",
    severity: str = "info",
    details: dict[str, Any] | None = None,
    thread_id: str = "",
    message_id: str = "",
    action_id: str = "",
) -> dict[str, Any]:
    ensure_advisor_tables(conn)
    row = conn.execute(
        text(
            """
            INSERT INTO saas_advisor_audit_events (
                tenant_id, user_id, thread_id, message_id, action_id, event_type, severity, summary, details_json
            )
            VALUES (
                CAST(:tenant_id AS uuid),
                CAST(NULLIF(:user_id, '') AS uuid),
                CAST(NULLIF(:thread_id, '') AS uuid),
                CAST(NULLIF(:message_id, '') AS uuid),
                CAST(NULLIF(:action_id, '') AS uuid),
                :event_type, :severity, :summary, CAST(:details_json AS jsonb)
            )
            RETURNING id::text, event_type, severity, summary, details_json,
                      thread_id::text, message_id::text, action_id::text, user_id::text, created_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "user_id": _clean(user_id, 80),
            "thread_id": _clean(thread_id, 80),
            "message_id": _clean(message_id, 80),
            "action_id": _clean(action_id, 80),
            "event_type": _clean(event_type, 100) or "advisor_event",
            "severity": _clean(severity, 40) or "info",
            "summary": _clean(summary, 500),
            "details_json": _json(details or {}),
        },
    ).mappings().first()
    return _event_out(_row_dict(row))


def list_advisor_events(conn: Connection, tenant_id: str, limit: int = 30) -> list[dict[str, Any]]:
    ensure_advisor_tables(conn)
    rows = conn.execute(
        text(
            """
            SELECT id::text, event_type, severity, summary, details_json,
                   thread_id::text, message_id::text, action_id::text, user_id::text, created_at::text
            FROM saas_advisor_audit_events
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "limit": max(1, min(int(limit or 30), 100))},
    ).mappings().all()
    return [_event_out(_row_dict(row)) for row in rows]


def advisor_metrics(conn: Connection, tenant_id: str) -> dict[str, Any]:
    ensure_advisor_tables(conn)
    action_rows = conn.execute(
        text(
            """
            SELECT status, COUNT(*)::int AS total
            FROM saas_advisor_actions
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            GROUP BY status
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().all()
    feedback_rows = conn.execute(
        text(
            """
            SELECT rating, COUNT(*)::int AS total
            FROM saas_advisor_feedback
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND updated_at >= NOW() - INTERVAL '30 days'
            GROUP BY rating
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().all()
    open_counts = conn.execute(
        text(
            """
            SELECT
                (SELECT COUNT(*)::int FROM saas_ai_insights WHERE tenant_id = CAST(:tenant_id AS uuid) AND status = 'open') AS open_insights,
                (SELECT COUNT(*)::int FROM saas_ai_recommendations WHERE tenant_id = CAST(:tenant_id AS uuid) AND status = 'open') AS open_recommendations,
                (SELECT COUNT(*)::int FROM saas_advisor_audit_events WHERE tenant_id = CAST(:tenant_id AS uuid) AND created_at >= NOW() - INTERVAL '24 hours') AS events_24h,
                (SELECT COUNT(*)::int FROM saas_advisor_messages WHERE tenant_id = CAST(:tenant_id AS uuid) AND role = 'assistant' AND created_at >= NOW() - INTERVAL '7 days') AS assistant_messages_7d
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    actions_by_status = {str(row["status"]): int(row["total"] or 0) for row in action_rows}
    feedback_by_rating = {str(row["rating"]): int(row["total"] or 0) for row in feedback_rows}
    return {
        **_row_dict(open_counts),
        "actions": actions_by_status,
        "feedback": feedback_by_rating,
        "pending_actions": int(actions_by_status.get("draft", 0)) + int(actions_by_status.get("pending_approval", 0)),
        "approved_actions": int(actions_by_status.get("approved", 0)),
        "executed_actions": int(actions_by_status.get("executed", 0)),
        "negative_feedback": int(feedback_by_rating.get("not_helpful", 0)) + int(feedback_by_rating.get("unsafe", 0)),
    }


def submit_advisor_feedback(
    conn: Connection,
    tenant_id: str,
    user_id: str,
    message_id: str,
    *,
    rating: str,
    note: str = "",
) -> dict[str, Any]:
    ensure_advisor_tables(conn)
    allowed = {"helpful", "not_helpful", "unsafe", "irrelevant"}
    rating_value = _clean(rating, 40).lower()
    if rating_value not in allowed:
        rating_value = "not_helpful"
    target = conn.execute(
        text(
            """
            SELECT id::text, thread_id::text, role
            FROM saas_advisor_messages
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:message_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "message_id": message_id},
    ).mappings().first()
    target_row = _row_dict(target)
    if not target_row:
        return {}
    row = conn.execute(
        text(
            """
            INSERT INTO saas_advisor_feedback (
                tenant_id, user_id, message_id, rating, note, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), CAST(:user_id AS uuid), CAST(:message_id AS uuid), :rating, :note, NOW()
            )
            ON CONFLICT (tenant_id, user_id, message_id)
            DO UPDATE SET rating = EXCLUDED.rating, note = EXCLUDED.note, updated_at = NOW()
            RETURNING id::text, message_id::text, rating, note, created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "message_id": message_id,
            "rating": rating_value,
            "note": _clean(note, 1000),
        },
    ).mappings().first()
    feedback = _row_dict(row)
    record_advisor_event(
        conn,
        tenant_id,
        user_id=user_id,
        thread_id=str(target_row.get("thread_id") or ""),
        message_id=message_id,
        event_type="feedback_recorded",
        severity="warning" if rating_value in {"unsafe", "not_helpful"} else "info",
        summary=f"Feedback Advisor: {rating_value}",
        details={"rating": rating_value, "note": _clean(note, 1000), "message_role": target_row.get("role")},
    )
    return feedback


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
        item = _action_out(_row_dict(result))
        record_advisor_event(
            conn,
            tenant_id,
            user_id=user_id,
            action_id=item["id"],
            event_type="action_prepared",
            summary=f"Accion preparada desde recomendacion: {item['title']}",
            details={"source": "recommendation", "recommendation_id": recommendation_id, "action_type": item["action_type"]},
        )
        return item
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
    item = _action_out(_row_dict(existing))
    if item:
        record_advisor_event(
            conn,
            tenant_id,
            user_id=user_id,
            action_id=item["id"],
            event_type="action_reused",
            summary=f"Accion existente reutilizada: {item['title']}",
            details={"source": "recommendation", "recommendation_id": recommendation_id},
        )
    return item


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
        item = _action_out(_row_dict(result))
        record_advisor_event(
            conn,
            tenant_id,
            user_id=user_id,
            action_id=item["id"],
            event_type="action_prepared",
            summary=f"Accion preparada desde insight: {item['title']}",
            details={"source": "insight", "insight_id": insight_id, "action_type": item["action_type"]},
        )
        return item
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
    item = _action_out(_row_dict(existing))
    if item:
        record_advisor_event(
            conn,
            tenant_id,
            user_id=user_id,
            action_id=item["id"],
            event_type="action_reused",
            summary=f"Accion existente reutilizada: {item['title']}",
            details={"source": "insight", "insight_id": insight_id},
        )
    return item


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
    item = _action_out(_row_dict(row))
    if item:
        record_advisor_event(
            conn,
            tenant_id,
            user_id=user_id,
            action_id=item["id"],
            event_type="action_prepared",
            summary=f"Accion manual preparada: {item['title']}",
            details={"source": "custom", "action_type": item["action_type"], "risk_level": item["risk_level"]},
        )
    return item


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
    item = _action_out(_row_dict(row))
    if item:
        record_advisor_event(
            conn,
            tenant_id,
            user_id=user_id,
            action_id=item["id"],
            event_type="action_approved",
            summary=f"Accion aprobada: {item['title']}",
            details={"action_type": item["action_type"], "risk_level": item["risk_level"]},
        )
    return item


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
    item = _row_dict(row)
    if item:
        record_advisor_event(
            conn,
            tenant_id,
            action_id=action_id,
            event_type="action_dismissed",
            summary="Accion del Advisor descartada",
            details={"action_id": action_id},
        )
    return item


def _load_action(conn: Connection, tenant_id: str, action_id: str) -> dict[str, Any]:
    ensure_advisor_tables(conn)
    row = conn.execute(
        text(
            """
            SELECT id::text, action_type, title, description, payload_json, impact, risk_level,
                   approval_required, status, recommendation_id::text, insight_id::text,
                   approved_by::text, approved_at::text, executed_at::text,
                   execution_result_json, created_at::text, updated_at::text
            FROM saas_advisor_actions
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:action_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "action_id": action_id},
    ).mappings().first()
    return _action_out(_row_dict(row))


def _complete_action_execution(
    conn: Connection,
    tenant_id: str,
    action_id: str,
    *,
    status: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            UPDATE saas_advisor_actions
            SET status = :status,
                executed_at = CASE WHEN :status = 'executed' THEN NOW() ELSE executed_at END,
                execution_result_json = CAST(:execution_result_json AS jsonb),
                updated_at = NOW()
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:action_id AS uuid)
            RETURNING id::text, action_type, title, description, payload_json, impact, risk_level,
                      approval_required, status, recommendation_id::text, insight_id::text,
                      approved_by::text, approved_at::text, executed_at::text,
                      execution_result_json, created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "action_id": action_id,
            "status": status,
            "execution_result_json": _json(result),
        },
    ).mappings().first()
    return _action_out(_row_dict(row))


def _action_payload(action_row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], str]:
    payload = action_row.get("payload_json") if isinstance(action_row.get("payload_json"), dict) else {}
    nested = payload.get("action") if isinstance(payload.get("action"), dict) else {}
    action = nested or payload
    action_type = _clean(action.get("type") or action_row.get("action_type"), 100).lower()
    return payload, action, action_type


def _safe_name(value: str, fallback: str, suffix: str) -> str:
    base = _clean(value, 120) or fallback
    tail = f" / Advisor {suffix[:8]}"
    return f"{base[:160 - len(tail)]}{tail}"


def _execute_navigation_action(conn: Connection, tenant_id: str, action_id: str, action: dict[str, Any], action_type: str) -> dict[str, Any]:
    module_map = {
        "open_inbox": "inbox",
        "review_crm": "customers",
        "open_debug": "settings",
        "open_campaigns": "campaigns",
        "open_broadcast": "broadcast",
        "open_ads": "ads",
        "open_settings": "settings",
    }
    module = _clean(action.get("module") or module_map.get(action_type), 80)
    tab = _clean(action.get("tab"), 80)
    result = {
        "state": "executed",
        "mode": "navigation",
        "message": "Accion ejecutada como navegacion asistida. No se enviaron mensajes ni se modificaron secretos.",
        "navigation": {"module": module, "tab": tab},
    }
    return _complete_action_execution(conn, tenant_id, action_id, status="executed", result=result)


def _execute_campaign_draft(conn: Connection, tenant_id: str, user_id: str, action_id: str, row: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    draft = action.get("campaign") if isinstance(action.get("campaign"), dict) else action
    campaign = conn.execute(
        text(
            """
            INSERT INTO saas_campaigns (
                tenant_id, name, channel, objective, status, audience_count, created_by_user_id
            )
            VALUES (
                CAST(:tenant_id AS uuid), :name, :channel, :objective, 'draft', 0, CAST(:user_id AS uuid)
            )
            RETURNING id::text, name, channel, objective, status, created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "name": _safe_name(draft.get("name") or row.get("title"), "Campana sugerida", action_id),
            "channel": _clean(draft.get("channel"), 40).lower() or "whatsapp",
            "objective": _clean(draft.get("objective") or row.get("description"), 1000),
        },
    ).mappings().first()
    result = {
        "state": "executed",
        "mode": "draft_created",
        "artifact_type": "campaign",
        "artifact": _row_dict(campaign),
        "navigation": {"module": "campaigns"},
    }
    return _complete_action_execution(conn, tenant_id, action_id, status="executed", result=result)


def _execute_trigger_draft(conn: Connection, tenant_id: str, user_id: str, action_id: str, row: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    draft = action.get("trigger") if isinstance(action.get("trigger"), dict) else action
    trigger = conn.execute(
        text(
            """
            INSERT INTO saas_crm_triggers (
                tenant_id, name, channel, event_type, trigger_type, flow_event, conditions_json, actions_json,
                priority, cooldown_minutes, is_active, assistant_enabled, assistant_message_type,
                block_ai, stop_on_match, only_when_no_takeover, created_by_user_id
            )
            VALUES (
                CAST(:tenant_id AS uuid), :name, :channel, :event_type, :trigger_type, :flow_event,
                CAST(:conditions_json AS jsonb), CAST(:actions_json AS jsonb), :priority, :cooldown_minutes,
                FALSE, :assistant_enabled, :assistant_message_type, TRUE, TRUE, TRUE, CAST(:user_id AS uuid)
            )
            RETURNING id::text, name, channel, event_type, trigger_type, flow_event, conditions_json, actions_json,
                      priority, cooldown_minutes, is_active, assistant_enabled, assistant_message_type,
                      block_ai, stop_on_match, only_when_no_takeover, created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "name": _safe_name(draft.get("name") or row.get("title"), "Trigger sugerido", action_id),
            "channel": _clean(draft.get("channel"), 40).lower() or "whatsapp",
            "event_type": _clean(draft.get("event_type"), 80).lower() or "message_in",
            "trigger_type": _clean(draft.get("trigger_type"), 80).lower() or "message_flow",
            "flow_event": _clean(draft.get("flow_event"), 40).lower() or "received",
            "conditions_json": _json(draft.get("conditions_json") or draft.get("conditions") or {"conditions": []}),
            "actions_json": _json(draft.get("actions_json") or draft.get("actions") or {"actions": []}),
            "priority": int(draft.get("priority") or 100),
            "cooldown_minutes": int(draft.get("cooldown_minutes") or 60),
            "assistant_enabled": bool(draft.get("assistant_enabled", False)),
            "assistant_message_type": _clean(draft.get("assistant_message_type"), 40).lower() or "auto",
        },
    ).mappings().first()
    result = {
        "state": "executed",
        "mode": "draft_created",
        "artifact_type": "trigger",
        "artifact": _row_dict(trigger),
        "safety": "El trigger fue creado desactivado para revision manual.",
        "navigation": {"module": "campaigns"},
    }
    return _complete_action_execution(conn, tenant_id, action_id, status="executed", result=result)


def _execute_remarketing_draft(conn: Connection, tenant_id: str, user_id: str, action_id: str, row: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    draft = action.get("flow") if isinstance(action.get("flow"), dict) else action
    flow = conn.execute(
        text(
            """
            INSERT INTO saas_remarketing_flows (
                tenant_id, name, description, channel, status, entry_rules_json, exit_rules_json, steps_json, created_by_user_id
            )
            VALUES (
                CAST(:tenant_id AS uuid), :name, :description, :channel, 'draft',
                CAST(:entry_rules_json AS jsonb), CAST(:exit_rules_json AS jsonb), CAST(:steps_json AS jsonb), CAST(:user_id AS uuid)
            )
            RETURNING id::text, name, description, channel, status, entry_rules_json, exit_rules_json, steps_json, created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "name": _safe_name(draft.get("name") or row.get("title"), "Flow remarketing sugerido", action_id),
            "description": _clean(draft.get("description") or row.get("description"), 1000),
            "channel": _clean(draft.get("channel"), 40).lower() or "whatsapp",
            "entry_rules_json": _json(draft.get("entry_rules_json") or {}),
            "exit_rules_json": _json(draft.get("exit_rules_json") or {}),
            "steps_json": _json(draft.get("steps_json") or []),
        },
    ).mappings().first()
    result = {
        "state": "executed",
        "mode": "draft_created",
        "artifact_type": "remarketing_flow",
        "artifact": _row_dict(flow),
        "navigation": {"module": "campaigns"},
    }
    return _complete_action_execution(conn, tenant_id, action_id, status="executed", result=result)


def execute_action(conn: Connection, tenant_id: str, user_id: str, action_id: str) -> dict[str, Any]:
    row = _load_action(conn, tenant_id, action_id)
    if not row:
        return {"ok": False, "error": "action_not_found"}
    if row.get("status") != "approved":
        return {"ok": False, "error": "action_must_be_approved", "action": row}
    _payload, action, action_type = _action_payload(row)
    try:
        if action_type in {"open_inbox", "review_crm", "open_debug", "open_campaigns", "open_broadcast", "open_ads", "open_settings"}:
            updated = _execute_navigation_action(conn, tenant_id, action_id, action, action_type)
        elif action_type in {"create_campaign_draft", "campaign_draft", "draft_campaign"}:
            updated = _execute_campaign_draft(conn, tenant_id, user_id, action_id, row, action)
        elif action_type in {"create_trigger_draft", "trigger_draft", "draft_trigger"}:
            updated = _execute_trigger_draft(conn, tenant_id, user_id, action_id, row, action)
        elif action_type in {"create_remarketing_flow_draft", "remarketing_flow_draft", "draft_remarketing_flow"}:
            updated = _execute_remarketing_draft(conn, tenant_id, user_id, action_id, row, action)
        else:
            result = {
                "state": "unsupported_action",
                "message": "Esta accion requiere un executor especifico antes de poder ejecutarse automaticamente.",
                "action_type": action_type,
            }
            updated = _complete_action_execution(conn, tenant_id, action_id, status="approved", result=result)
            record_advisor_event(
                conn,
                tenant_id,
                user_id=user_id,
                action_id=action_id,
                event_type="action_execution_blocked",
                severity="warning",
                summary=f"Executor no disponible para accion: {action_type}",
                details=result,
            )
            return {"ok": False, "error": "unsupported_action_type", "action": updated}
    except Exception as exc:
        result = {"state": "execution_failed", "error": _clean(exc, 1000), "action_type": action_type}
        updated = _complete_action_execution(conn, tenant_id, action_id, status="approved", result=result)
        record_advisor_event(
            conn,
            tenant_id,
            user_id=user_id,
            action_id=action_id,
            event_type="action_execution_failed",
            severity="critical",
            summary=f"Fallo ejecutando accion Advisor: {action_type}",
            details=result,
        )
        return {"ok": False, "error": "execution_failed", "action": updated}
    record_advisor_event(
        conn,
        tenant_id,
        user_id=user_id,
        action_id=action_id,
        event_type="action_executed",
        summary=f"Accion ejecutada: {updated.get('title') or action_type}",
        details=updated.get("execution_result_json") or {},
    )
    return {"ok": True, "action": updated, "result": updated.get("execution_result_json") or {}}


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
        record_advisor_event(
            conn,
            tenant_id,
            user_id=user_id,
            thread_id=str(thread["id"]),
            message_id=str(assistant_msg.get("id") or ""),
            event_type="chat_fallback",
            severity="warning",
            summary="Advisor respondio con fallback por falta de modelo o credencial",
            details={"reason": reason, "module": module, "context_type": context_type, "context_id": context_id},
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
    record_advisor_event(
        conn,
        tenant_id,
        user_id=user_id,
        thread_id=str(thread["id"]),
        message_id=str(assistant_msg.get("id") or ""),
        event_type="chat_response",
        summary="Advisor genero una respuesta",
        details={
            "provider_code": gateway.get("provider_code"),
            "model": gateway.get("model"),
            "fallback_used": gateway.get("fallback_used"),
            "latency_ms": gateway.get("latency_ms"),
            "module": module,
            "context_type": context_type,
            "context_id": context_id,
        },
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

