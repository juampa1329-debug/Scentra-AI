from __future__ import annotations

import os
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app_saas.agents.service import (
    _agent_row_to_dict,
    _clean,
    _ensure_governance_tables,
    _json,
    _json_value,
    _uuid,
    assign_conversation_ai_agent,
)
from app_saas.db import db_session, set_tenant_context


ORCHESTRATOR_VERSION = "phase_7_multiagent_orchestrator"


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _safe_int(value: Any, default: int, *, minimum: int = 1, maximum: int = 10_000) -> int:
    try:
        parsed = int(value or default)
    except Exception:
        parsed = default
    return max(minimum, min(parsed, maximum))


def _lock_ttl_minutes() -> int:
    return _safe_int(os.getenv("SAAS_AGENT_ORCHESTRATOR_LOCK_TTL_MINUTES"), 15, minimum=1, maximum=1440)


def _retry_minutes() -> int:
    return _safe_int(os.getenv("SAAS_AGENT_ORCHESTRATOR_RETRY_MINUTES"), 5, minimum=1, maximum=240)


def _is_enabled() -> bool:
    return str(os.getenv("SAAS_AGENT_ORCHESTRATOR_ENABLED", "true")).strip().lower() not in {"0", "false", "no", "off"}


def ensure_orchestrator_tables(conn: Connection) -> None:
    _ensure_governance_tables(conn)
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_agent_orchestration_jobs (
                id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                source TEXT NOT NULL DEFAULT 'system',
                event_type TEXT NOT NULL DEFAULT 'agent.event',
                entity_type TEXT NOT NULL DEFAULT '',
                entity_id TEXT NOT NULL DEFAULT '',
                channel TEXT NOT NULL DEFAULT '',
                lock_key TEXT NOT NULL DEFAULT '',
                source_agent_id UUID NULL REFERENCES saas_ai_agents(id) ON DELETE SET NULL,
                selected_agent_id UUID NULL REFERENCES saas_ai_agents(id) ON DELETE SET NULL,
                priority INTEGER NOT NULL DEFAULT 50,
                status TEXT NOT NULL DEFAULT 'queued',
                attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 3,
                scheduled_at TIMESTAMP NOT NULL DEFAULT NOW(),
                locked_by TEXT NOT NULL DEFAULT '',
                locked_at TIMESTAMP NULL,
                payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                error TEXT NOT NULL DEFAULT '',
                created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                completed_at TIMESTAMP NULL
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_ai_agent_orchestration_jobs_due
            ON saas_ai_agent_orchestration_jobs (tenant_id, status, scheduled_at, priority DESC, created_at)
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_ai_agent_orchestration_jobs_lock
            ON saas_ai_agent_orchestration_jobs (tenant_id, lock_key, status, updated_at DESC)
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_agent_locks (
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                lock_key TEXT NOT NULL,
                owner_agent_id UUID NULL REFERENCES saas_ai_agents(id) ON DELETE SET NULL,
                owner_job_id UUID NULL REFERENCES saas_ai_agent_orchestration_jobs(id) ON DELETE SET NULL,
                entity_type TEXT NOT NULL DEFAULT '',
                entity_id TEXT NOT NULL DEFAULT '',
                lock_scope TEXT NOT NULL DEFAULT 'orchestrator',
                payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                expires_at TIMESTAMP NOT NULL DEFAULT NOW(),
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                PRIMARY KEY (tenant_id, lock_key)
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_ai_agent_locks_expires
            ON saas_ai_agent_locks (tenant_id, expires_at)
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_agent_handoffs (
                id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                source_agent_id UUID NULL REFERENCES saas_ai_agents(id) ON DELETE SET NULL,
                target_agent_id UUID NULL REFERENCES saas_ai_agents(id) ON DELETE SET NULL,
                job_id UUID NULL REFERENCES saas_ai_agent_orchestration_jobs(id) ON DELETE SET NULL,
                entity_type TEXT NOT NULL DEFAULT '',
                entity_id TEXT NOT NULL DEFAULT '',
                reason TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'proposed',
                payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                accepted_at TIMESTAMP NULL
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_ai_agent_handoffs_tenant_status
            ON saas_ai_agent_handoffs (tenant_id, status, created_at DESC)
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_agent_conflicts (
                id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                lock_key TEXT NOT NULL DEFAULT '',
                entity_type TEXT NOT NULL DEFAULT '',
                entity_id TEXT NOT NULL DEFAULT '',
                source_job_id UUID NULL REFERENCES saas_ai_agent_orchestration_jobs(id) ON DELETE SET NULL,
                existing_owner_agent_id UUID NULL REFERENCES saas_ai_agents(id) ON DELETE SET NULL,
                requested_agent_id UUID NULL REFERENCES saas_ai_agents(id) ON DELETE SET NULL,
                conflict_type TEXT NOT NULL DEFAULT 'lock_conflict',
                resolution_status TEXT NOT NULL DEFAULT 'open',
                details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                resolved_at TIMESTAMP NULL
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_ai_agent_conflicts_tenant_status
            ON saas_ai_agent_conflicts (tenant_id, resolution_status, created_at DESC)
            """
        )
    )


def _row_job(row: dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    for key in ("payload_json", "result_json"):
        data[key] = _json_value(data.get(key), {})
    return {key: _jsonable(value) for key, value in data.items()}


def _row_generic(row: dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    for key in ("payload_json", "details_json"):
        if key in data:
            data[key] = _json_value(data.get(key), {})
    return {key: _jsonable(value) for key, value in data.items()}


def _lock_key(payload: dict[str, Any], entity_type: str, entity_id: str, channel: str) -> str:
    conversation_id = _clean(payload.get("conversation_id"), 80)
    comment_id = _clean(payload.get("comment_id") or payload.get("social_comment_id"), 120)
    post_id = _clean(payload.get("post_id") or payload.get("external_post_id"), 160)
    customer_id = _clean(payload.get("customer_id") or payload.get("external_contact_id"), 160)
    if conversation_id:
        return f"conversation:{conversation_id}"
    if comment_id:
        return f"comment:{comment_id}"
    if post_id:
        return f"post:{channel}:{post_id}"
    if customer_id:
        return f"customer:{channel}:{customer_id}"
    return f"{_clean(entity_type, 80) or 'entity'}:{_clean(entity_id, 160) or _uuid()}"


def enqueue_orchestration_event(
    conn: Connection,
    tenant_id: str,
    *,
    source: str,
    event_type: str,
    entity_type: str,
    entity_id: str,
    channel: str = "",
    payload: dict[str, Any] | None = None,
    source_agent_id: str = "",
    priority: int = 50,
    created_by_user_id: str = "",
) -> dict[str, Any]:
    ensure_orchestrator_tables(conn)
    clean_payload = _as_dict(payload or {})
    lock_key = _lock_key(clean_payload, entity_type, entity_id, channel)

    existing = conn.execute(
        text(
            """
            SELECT id::text, tenant_id::text, source, event_type, entity_type, entity_id,
                   channel, lock_key, source_agent_id::text, selected_agent_id::text,
                   priority, status, attempts, max_attempts, scheduled_at::text,
                   locked_by, locked_at::text, payload_json, result_json, error,
                   created_by_user_id::text, created_at::text, updated_at::text,
                   completed_at::text
            FROM saas_ai_agent_orchestration_jobs
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND lock_key = :lock_key
              AND status IN ('queued', 'processing')
            ORDER BY created_at ASC
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "lock_key": lock_key},
    ).mappings().first()
    if existing:
        merged_payload = {
            **_json_value(existing.get("payload_json"), {}),
            "coalesced_events": int(_as_dict(_json_value(existing.get("payload_json"), {})).get("coalesced_events") or 1) + 1,
            "latest_event": clean_payload,
            "latest_event_type": event_type,
        }
        row = conn.execute(
            text(
                """
                UPDATE saas_ai_agent_orchestration_jobs
                SET priority = GREATEST(priority, :priority),
                    payload_json = CAST(:payload_json AS jsonb),
                    updated_at = NOW()
                WHERE id = CAST(:id AS uuid)
                RETURNING id::text, tenant_id::text, source, event_type, entity_type, entity_id,
                          channel, lock_key, source_agent_id::text, selected_agent_id::text,
                          priority, status, attempts, max_attempts, scheduled_at::text,
                          locked_by, locked_at::text, payload_json, result_json, error,
                          created_by_user_id::text, created_at::text, updated_at::text,
                          completed_at::text
                """
            ),
            {"id": existing["id"], "priority": int(priority or 50), "payload_json": _json(merged_payload)},
        ).mappings().first()
        return {"created": False, "job": _row_job(dict(row))}

    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_agent_orchestration_jobs (
                id, tenant_id, source, event_type, entity_type, entity_id, channel, lock_key,
                source_agent_id, priority, payload_json, created_by_user_id
            )
            VALUES (
                CAST(:id AS uuid),
                CAST(:tenant_id AS uuid),
                :source,
                :event_type,
                :entity_type,
                :entity_id,
                :channel,
                :lock_key,
                CAST(NULLIF(:source_agent_id, '') AS uuid),
                :priority,
                CAST(:payload_json AS jsonb),
                CAST(NULLIF(:created_by_user_id, '') AS uuid)
            )
            RETURNING id::text, tenant_id::text, source, event_type, entity_type, entity_id,
                      channel, lock_key, source_agent_id::text, selected_agent_id::text,
                      priority, status, attempts, max_attempts, scheduled_at::text,
                      locked_by, locked_at::text, payload_json, result_json, error,
                      created_by_user_id::text, created_at::text, updated_at::text,
                      completed_at::text
            """
        ),
        {
            "id": _uuid(),
            "tenant_id": tenant_id,
            "source": _clean(source, 80) or "system",
            "event_type": _clean(event_type, 120) or "agent.event",
            "entity_type": _clean(entity_type, 80),
            "entity_id": _clean(entity_id, 180),
            "channel": _clean(channel, 40).lower(),
            "lock_key": lock_key,
            "source_agent_id": source_agent_id or "",
            "priority": max(1, min(int(priority or 50), 100)),
            "payload_json": _json(clean_payload),
            "created_by_user_id": created_by_user_id or "",
        },
    ).mappings().first()
    return {"created": True, "job": _row_job(dict(row))}


def _load_active_agents(conn: Connection, tenant_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT id::text, tenant_id::text, agent_type, name, description, status,
                   provider_policy_json, personality_json, goals_json, rules_json, channels_json,
                   tools_json, memory_policy_json, approval_policy_json, metrics_json,
                   created_by_user_id::text, created_at::text, updated_at::text
            FROM saas_ai_agents
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND status = 'active'
            ORDER BY updated_at DESC
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().all()
    return [_agent_row_to_dict(dict(row)) for row in rows]


def _score_agent(agent: dict[str, Any], job: dict[str, Any]) -> int:
    channel = _clean(job.get("channel"), 40).lower()
    event_type = _clean(job.get("event_type"), 120).lower()
    entity_type = _clean(job.get("entity_type"), 80).lower()
    payload = _as_dict(job.get("payload_json"))
    text_value = _clean(payload.get("text") or payload.get("message") or payload.get("summary"), 1000).lower()
    agent_type = _clean(agent.get("agent_type"), 80).lower()
    channels = {str(item or "").lower() for item in _as_list(agent.get("channels_json"))}
    tools = {str(item or "").lower() for item in _as_list(agent.get("tools_json"))}
    score = 0
    if channel and channel in channels:
        score += 30
    if "global" in channels:
        score += 8
    if entity_type == "conversation" or event_type.startswith("conversation."):
        score += {
            "sales": 42,
            "support": 38,
            "retention": 24,
            "crm_intelligence": 20,
            "advisor": 14,
        }.get(agent_type, 0)
        if any(word in text_value for word in ("precio", "comprar", "cotizar", "disponible", "pago")):
            score += 14 if agent_type in {"sales", "retention"} else 0
        if any(word in text_value for word in ("problema", "no funciona", "ayuda", "error", "queja")):
            score += 16 if agent_type in {"support", "operations"} else 0
    if entity_type == "social_comment" or "comment" in event_type:
        score += {
            "reputation_manager": 44,
            "support": 34,
            "sales": 24,
            "campaign_strategist": 18,
            "advisor": 12,
        }.get(agent_type, 0)
        if "reviews.manage" in tools:
            score += 15
    if entity_type in {"webhook", "integration", "diagnostic"} or any(word in event_type for word in ("webhook", "diagnostic", "error")):
        score += {"operations": 45, "advisor": 16, "workflow_architect": 12}.get(agent_type, 0)
        if "meta.checks" in tools or "diagnostics.read" in tools:
            score += 12
    if entity_type in {"workflow", "trigger", "campaign"}:
        score += {"workflow_architect": 42, "campaign_strategist": 36, "advisor": 18}.get(agent_type, 0)
    if entity_type in {"student", "course", "education"}:
        score += {"teacher": 48, "education_admissions": 30, "knowledge": 20}.get(agent_type, 0)
    if agent_type == "advisor":
        score += 4
    return score


def select_agent_for_job(conn: Connection, tenant_id: str, job: dict[str, Any]) -> dict[str, Any] | None:
    agents = _load_active_agents(conn, tenant_id)
    if not agents:
        return None
    scored = sorted(((agent, _score_agent(agent, job)) for agent in agents), key=lambda item: item[1], reverse=True)
    if scored and scored[0][1] > 0:
        return scored[0][0]
    for agent in agents:
        if agent.get("agent_type") == "advisor":
            return agent
    return agents[0]


def _record_conflict(
    conn: Connection,
    tenant_id: str,
    *,
    job: dict[str, Any],
    requested_agent_id: str,
    existing_lock: dict[str, Any],
) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_agent_conflicts (
                id, tenant_id, lock_key, entity_type, entity_id, source_job_id,
                existing_owner_agent_id, requested_agent_id, conflict_type, details_json
            )
            VALUES (
                CAST(:id AS uuid),
                CAST(:tenant_id AS uuid),
                :lock_key,
                :entity_type,
                :entity_id,
                CAST(:source_job_id AS uuid),
                CAST(NULLIF(:existing_owner_agent_id, '') AS uuid),
                CAST(NULLIF(:requested_agent_id, '') AS uuid),
                'lock_conflict',
                CAST(:details_json AS jsonb)
            )
            RETURNING id::text, tenant_id::text, lock_key, entity_type, entity_id,
                      source_job_id::text, existing_owner_agent_id::text, requested_agent_id::text,
                      conflict_type, resolution_status, details_json, created_at::text, resolved_at::text
            """
        ),
        {
            "id": _uuid(),
            "tenant_id": tenant_id,
            "lock_key": job.get("lock_key") or "",
            "entity_type": job.get("entity_type") or "",
            "entity_id": job.get("entity_id") or "",
            "source_job_id": job["id"],
            "existing_owner_agent_id": existing_lock.get("owner_agent_id") or "",
            "requested_agent_id": requested_agent_id or "",
            "details_json": _json({"existing_lock": existing_lock, "job": job}),
        },
    ).mappings().first()
    return _row_generic(dict(row))


def _acquire_lock(conn: Connection, tenant_id: str, job: dict[str, Any], agent_id: str) -> tuple[bool, dict[str, Any]]:
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_agent_locks (
                tenant_id, lock_key, owner_agent_id, owner_job_id, entity_type, entity_id,
                lock_scope, payload_json, expires_at, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid),
                :lock_key,
                CAST(:owner_agent_id AS uuid),
                CAST(:owner_job_id AS uuid),
                :entity_type,
                :entity_id,
                'orchestrator',
                CAST(:payload_json AS jsonb),
                NOW() + (:ttl_minutes * INTERVAL '1 minute'),
                NOW()
            )
            ON CONFLICT (tenant_id, lock_key)
            DO UPDATE SET
                owner_agent_id = EXCLUDED.owner_agent_id,
                owner_job_id = EXCLUDED.owner_job_id,
                entity_type = EXCLUDED.entity_type,
                entity_id = EXCLUDED.entity_id,
                payload_json = EXCLUDED.payload_json,
                expires_at = EXCLUDED.expires_at,
                updated_at = NOW()
            WHERE saas_ai_agent_locks.expires_at <= NOW()
               OR saas_ai_agent_locks.owner_job_id = EXCLUDED.owner_job_id
            RETURNING tenant_id::text, lock_key, owner_agent_id::text, owner_job_id::text,
                      entity_type, entity_id, lock_scope, payload_json, expires_at::text,
                      created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "lock_key": job.get("lock_key") or "",
            "owner_agent_id": agent_id,
            "owner_job_id": job["id"],
            "entity_type": job.get("entity_type") or "",
            "entity_id": job.get("entity_id") or "",
            "payload_json": _json({"job_id": job["id"], "event_type": job.get("event_type"), "source": job.get("source")}),
            "ttl_minutes": _lock_ttl_minutes(),
        },
    ).mappings().first()
    if row:
        return True, _row_generic(dict(row))
    existing = conn.execute(
        text(
            """
            SELECT tenant_id::text, lock_key, owner_agent_id::text, owner_job_id::text,
                   entity_type, entity_id, lock_scope, payload_json, expires_at::text,
                   created_at::text, updated_at::text
            FROM saas_ai_agent_locks
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND lock_key = :lock_key
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "lock_key": job.get("lock_key") or ""},
    ).mappings().first()
    return False, _row_generic(dict(existing or {}))


def _write_coordination_event(
    conn: Connection,
    tenant_id: str,
    *,
    job: dict[str, Any],
    selected_agent: dict[str, Any],
    result: dict[str, Any],
) -> None:
    conn.execute(
        text(
            """
            INSERT INTO saas_ai_agent_coordination_events (
                id, tenant_id, source_agent_id, target_agent_id, event_type,
                summary, payload_json, status
            )
            VALUES (
                CAST(:id AS uuid),
                CAST(:tenant_id AS uuid),
                CAST(NULLIF(:source_agent_id, '') AS uuid),
                CAST(:target_agent_id AS uuid),
                :event_type,
                :summary,
                CAST(:payload_json AS jsonb),
                :status
            )
            """
        ),
        {
            "id": _uuid(),
            "tenant_id": tenant_id,
            "source_agent_id": job.get("source_agent_id") or "",
            "target_agent_id": selected_agent["id"],
            "event_type": "orchestrator.assignment",
            "summary": f"{selected_agent['name']} asumio {job.get('entity_type') or 'evento'} desde {job.get('source') or 'system'}.",
            "payload_json": _json({"job": job, "result": result, "version": ORCHESTRATOR_VERSION}),
            "status": "completed",
        },
    )


def _maybe_create_handoff(conn: Connection, tenant_id: str, job: dict[str, Any], selected_agent: dict[str, Any]) -> dict[str, Any] | None:
    source_agent_id = _clean(job.get("source_agent_id"), 80)
    if not source_agent_id or source_agent_id == selected_agent["id"]:
        return None
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_agent_handoffs (
                id, tenant_id, source_agent_id, target_agent_id, job_id,
                entity_type, entity_id, reason, status, payload_json
            )
            VALUES (
                CAST(:id AS uuid),
                CAST(:tenant_id AS uuid),
                CAST(:source_agent_id AS uuid),
                CAST(:target_agent_id AS uuid),
                CAST(:job_id AS uuid),
                :entity_type,
                :entity_id,
                :reason,
                'proposed',
                CAST(:payload_json AS jsonb)
            )
            RETURNING id::text, tenant_id::text, source_agent_id::text, target_agent_id::text,
                      job_id::text, entity_type, entity_id, reason, status, payload_json,
                      created_at::text, updated_at::text, accepted_at::text
            """
        ),
        {
            "id": _uuid(),
            "tenant_id": tenant_id,
            "source_agent_id": source_agent_id,
            "target_agent_id": selected_agent["id"],
            "job_id": job["id"],
            "entity_type": job.get("entity_type") or "",
            "entity_id": job.get("entity_id") or "",
            "reason": "El orquestador detecto un agente mas adecuado para este evento.",
            "payload_json": _json({"event_type": job.get("event_type"), "selected_agent_type": selected_agent.get("agent_type")}),
        },
    ).mappings().first()
    return _row_generic(dict(row))


def _complete_job(conn: Connection, job_id: str, selected_agent_id: str, result: dict[str, Any]) -> None:
    conn.execute(
        text(
            """
            UPDATE saas_ai_agent_orchestration_jobs
            SET selected_agent_id = CAST(NULLIF(:selected_agent_id, '') AS uuid),
                status = :status,
                result_json = CAST(:result_json AS jsonb),
                error = '',
                locked_by = '',
                locked_at = NULL,
                updated_at = NOW(),
                completed_at = NOW()
            WHERE id = CAST(:id AS uuid)
            """
        ),
        {
            "id": job_id,
            "selected_agent_id": selected_agent_id or "",
            "status": str(result.get("status") or "completed"),
            "result_json": _json(result),
        },
    )


def _fail_or_retry_job(conn: Connection, job: dict[str, Any], error: str) -> None:
    attempts = int(job.get("attempts") or 0)
    max_attempts = int(job.get("max_attempts") or 3)
    retry = attempts < max_attempts
    conn.execute(
        text(
            """
            UPDATE saas_ai_agent_orchestration_jobs
            SET status = :status,
                scheduled_at = CASE WHEN :retry THEN NOW() + (:retry_minutes * INTERVAL '1 minute') ELSE scheduled_at END,
                error = :error,
                locked_by = '',
                locked_at = NULL,
                updated_at = NOW(),
                completed_at = CASE WHEN :retry THEN NULL ELSE NOW() END
            WHERE id = CAST(:id AS uuid)
            """
        ),
        {
            "id": job["id"],
            "status": "queued" if retry else "failed",
            "retry": retry,
            "retry_minutes": _retry_minutes(),
            "error": _clean(error, 900),
        },
    )


def _process_one_job(job_id: str, worker_name: str) -> dict[str, Any]:
    with db_session() as conn:
        row = conn.execute(
            text(
                """
                SELECT id::text, tenant_id::text, source, event_type, entity_type, entity_id,
                       channel, lock_key, source_agent_id::text, selected_agent_id::text,
                       priority, status, attempts, max_attempts, scheduled_at::text,
                       locked_by, locked_at::text, payload_json, result_json, error,
                       created_by_user_id::text, created_at::text, updated_at::text,
                       completed_at::text
                FROM saas_ai_agent_orchestration_jobs
                WHERE id = CAST(:id AS uuid)
                  AND status = 'queued'
                  AND scheduled_at <= NOW()
                FOR UPDATE SKIP LOCKED
                """
            ),
            {"id": job_id},
        ).mappings().first()
        if not row:
            return {"picked": 0, "completed": 0, "skipped": "not_available"}
        job = _row_job(dict(row))
        tenant_id = job["tenant_id"]
        set_tenant_context(conn, tenant_id)
        conn.execute(
            text(
                """
                UPDATE saas_ai_agent_orchestration_jobs
                SET status = 'processing',
                    attempts = attempts + 1,
                    locked_by = :worker_name,
                    locked_at = NOW(),
                    updated_at = NOW()
                WHERE id = CAST(:id AS uuid)
                RETURNING attempts
                """
            ),
            {"id": job_id, "worker_name": worker_name},
        )
        job["attempts"] = int(job.get("attempts") or 0) + 1

        try:
            selected_agent = select_agent_for_job(conn, tenant_id, job)
            if not selected_agent:
                result = {
                    "status": "ignored",
                    "reason": "no_active_agent_available",
                    "recommendation": "Activa al menos un agente para este canal o usa Advisor como fallback.",
                }
                _complete_job(conn, job_id, "", result)
                return {"picked": 1, "completed": 0, "ignored": 1}

            acquired, lock = _acquire_lock(conn, tenant_id, job, selected_agent["id"])
            if not acquired:
                conflict = _record_conflict(conn, tenant_id, job=job, requested_agent_id=selected_agent["id"], existing_lock=lock)
                result = {
                    "status": "conflict",
                    "reason": "active_lock_exists",
                    "selected_agent_id": selected_agent["id"],
                    "selected_agent_name": selected_agent["name"],
                    "conflict": conflict,
                }
                _complete_job(conn, job_id, selected_agent["id"], result)
                return {"picked": 1, "completed": 0, "conflicts": 1}

            handoff = _maybe_create_handoff(conn, tenant_id, job, selected_agent)
            conversation_assignment = None
            if job.get("entity_type") == "conversation" and _clean(job.get("entity_id"), 80):
                try:
                    conversation_assignment = assign_conversation_ai_agent(
                        conn,
                        tenant_id,
                        _clean(job.get("entity_id"), 80),
                        selected_agent["id"],
                        source="orchestrator",
                    )
                except Exception as exc:
                    conversation_assignment = {"ok": False, "error": str(exc)[:300]}
            result = {
                "status": "completed",
                "selected_agent_id": selected_agent["id"],
                "selected_agent_type": selected_agent["agent_type"],
                "selected_agent_name": selected_agent["name"],
                "lock": lock,
                "handoff": handoff,
                "conversation_assignment": conversation_assignment,
                "next_step": "agent_runtime_or_human_approval",
                "version": ORCHESTRATOR_VERSION,
            }
            _write_coordination_event(conn, tenant_id, job=job, selected_agent=selected_agent, result=result)
            _complete_job(conn, job_id, selected_agent["id"], result)
            return {"picked": 1, "completed": 1, "handoffs": 1 if handoff else 0}
        except Exception as exc:
            _fail_or_retry_job(conn, job, str(exc))
            return {"picked": 1, "completed": 0, "errors": 1, "error": str(exc)[:300]}


def process_due_agent_orchestration(limit: int | None = None, tenant_id: str | None = None) -> dict[str, Any]:
    if not _is_enabled():
        return {"picked": 0, "completed": 0, "skipped": "disabled"}
    batch_size = _safe_int(limit or os.getenv("SAAS_AGENT_ORCHESTRATOR_BATCH_SIZE"), 20, minimum=1, maximum=200)
    worker_name = os.getenv("SAAS_WORKER_NAME", "api-embedded-worker")
    with db_session() as conn:
        ensure_orchestrator_tables(conn)
        tenant_clause = "AND tenant_id = CAST(:tenant_id AS uuid)" if tenant_id else ""
        rows = conn.execute(
            text(
                f"""
                SELECT id::text
                FROM saas_ai_agent_orchestration_jobs
                WHERE status = 'queued'
                  AND scheduled_at <= NOW()
                  {tenant_clause}
                ORDER BY priority DESC, created_at ASC
                LIMIT :limit
                """
            ),
            {"limit": batch_size, "tenant_id": tenant_id or ""},
        ).mappings().all()
    totals: dict[str, Any] = {"picked": 0, "completed": 0, "ignored": 0, "conflicts": 0, "handoffs": 0, "errors": 0}
    for row in rows:
        result = _process_one_job(str(row["id"]), worker_name)
        for key, value in result.items():
            if isinstance(value, int):
                totals[key] = int(totals.get(key) or 0) + value
    return totals


def orchestration_overview(conn: Connection, tenant_id: str, *, limit: int = 20) -> dict[str, Any]:
    ensure_orchestrator_tables(conn)
    safe_limit = max(1, min(int(limit or 20), 100))
    counts = conn.execute(
        text(
            """
            SELECT
              (SELECT COUNT(*)::int FROM saas_ai_agent_orchestration_jobs WHERE tenant_id = CAST(:tenant_id AS uuid) AND status = 'queued') AS queued_jobs,
              (SELECT COUNT(*)::int FROM saas_ai_agent_orchestration_jobs WHERE tenant_id = CAST(:tenant_id AS uuid) AND status = 'processing') AS processing_jobs,
              (SELECT COUNT(*)::int FROM saas_ai_agent_orchestration_jobs WHERE tenant_id = CAST(:tenant_id AS uuid) AND status = 'completed' AND created_at >= NOW() - INTERVAL '7 days') AS completed_7d,
              (SELECT COUNT(*)::int FROM saas_ai_agent_handoffs WHERE tenant_id = CAST(:tenant_id AS uuid) AND created_at >= NOW() - INTERVAL '7 days') AS handoffs_7d,
              (SELECT COUNT(*)::int FROM saas_ai_agent_conflicts WHERE tenant_id = CAST(:tenant_id AS uuid) AND resolution_status = 'open') AS open_conflicts,
              (SELECT COUNT(*)::int FROM saas_ai_agent_locks WHERE tenant_id = CAST(:tenant_id AS uuid) AND expires_at > NOW()) AS active_locks
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    jobs = conn.execute(
        text(
            """
            SELECT id::text, tenant_id::text, source, event_type, entity_type, entity_id,
                   channel, lock_key, source_agent_id::text, selected_agent_id::text,
                   priority, status, attempts, max_attempts, scheduled_at::text,
                   locked_by, locked_at::text, payload_json, result_json, error,
                   created_by_user_id::text, created_at::text, updated_at::text,
                   completed_at::text
            FROM saas_ai_agent_orchestration_jobs
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "limit": safe_limit},
    ).mappings().all()
    locks = conn.execute(
        text(
            """
            SELECT tenant_id::text, lock_key, owner_agent_id::text, owner_job_id::text,
                   entity_type, entity_id, lock_scope, payload_json, expires_at::text,
                   created_at::text, updated_at::text
            FROM saas_ai_agent_locks
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND expires_at > NOW()
            ORDER BY expires_at ASC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "limit": safe_limit},
    ).mappings().all()
    handoffs = conn.execute(
        text(
            """
            SELECT id::text, tenant_id::text, source_agent_id::text, target_agent_id::text,
                   job_id::text, entity_type, entity_id, reason, status, payload_json,
                   created_at::text, updated_at::text, accepted_at::text
            FROM saas_ai_agent_handoffs
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "limit": safe_limit},
    ).mappings().all()
    conflicts = conn.execute(
        text(
            """
            SELECT id::text, tenant_id::text, lock_key, entity_type, entity_id,
                   source_job_id::text, existing_owner_agent_id::text, requested_agent_id::text,
                   conflict_type, resolution_status, details_json, created_at::text, resolved_at::text
            FROM saas_ai_agent_conflicts
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "limit": safe_limit},
    ).mappings().all()
    return {
        "version": ORCHESTRATOR_VERSION,
        "enabled": _is_enabled(),
        "counts": {key: int(value or 0) for key, value in dict(counts or {}).items()},
        "jobs": [_row_job(dict(row)) for row in jobs],
        "locks": [_row_generic(dict(row)) for row in locks],
        "handoffs": [_row_generic(dict(row)) for row in handoffs],
        "conflicts": [_row_generic(dict(row)) for row in conflicts],
        "policies": {
            "lock_ttl_minutes": _lock_ttl_minutes(),
            "retry_minutes": _retry_minutes(),
            "human_approval_required": True,
            "sensitive_actions": "draft_only_until_approved",
        },
    }


def create_manual_orchestration_event(conn: Connection, tenant_id: str, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    event_payload = _as_dict(payload.get("payload_json"))
    event_payload.setdefault("manual", True)
    return enqueue_orchestration_event(
        conn,
        tenant_id,
        source="manual",
        event_type=_clean(payload.get("event_type"), 120) or "manual.test",
        entity_type=_clean(payload.get("entity_type"), 80) or "manual",
        entity_id=_clean(payload.get("entity_id"), 180) or _uuid(),
        channel=_clean(payload.get("channel"), 40).lower(),
        payload=event_payload,
        source_agent_id=_clean(payload.get("source_agent_id"), 80),
        priority=max(1, min(int(payload.get("priority") or 50), 100)),
        created_by_user_id=user_id,
    )


def enqueue_conversation_orchestration(
    conn: Connection,
    *,
    tenant_id: str,
    conversation_id: str,
    message_id: str,
    channel: str,
    text_value: str = "",
    external_contact_id: str = "",
    msg_type: str = "text",
) -> None:
    conn.execute(text("SAVEPOINT agent_orchestration_enqueue"))
    try:
        enqueue_orchestration_event(
            conn,
            tenant_id,
            source="inbox",
            event_type="conversation.message_received",
            entity_type="conversation",
            entity_id=conversation_id,
            channel=channel,
            priority=70,
            payload={
                "conversation_id": conversation_id,
                "message_id": message_id,
                "channel": channel,
                "text": text_value,
                "external_contact_id": external_contact_id,
                "msg_type": msg_type,
            },
        )
        conn.execute(text("RELEASE SAVEPOINT agent_orchestration_enqueue"))
    except Exception:
        conn.execute(text("ROLLBACK TO SAVEPOINT agent_orchestration_enqueue"))
        conn.execute(text("RELEASE SAVEPOINT agent_orchestration_enqueue"))
        # Orchestration must never block ingestion or webhooks.
        return


def enqueue_social_comment_orchestration(
    conn: Connection,
    *,
    tenant_id: str,
    comment_id: str,
    post_id: str = "",
    channel: str = "instagram",
    message: str = "",
    author_external_id: str = "",
) -> None:
    conn.execute(text("SAVEPOINT agent_orchestration_enqueue"))
    try:
        enqueue_orchestration_event(
            conn,
            tenant_id,
            source="social",
            event_type="social.comment_received",
            entity_type="social_comment",
            entity_id=comment_id,
            channel=channel,
            priority=60,
            payload={
                "comment_id": comment_id,
                "post_id": post_id,
                "channel": channel,
                "message": message,
                "author_external_id": author_external_id,
            },
        )
        conn.execute(text("RELEASE SAVEPOINT agent_orchestration_enqueue"))
    except Exception:
        conn.execute(text("ROLLBACK TO SAVEPOINT agent_orchestration_enqueue"))
        conn.execute(text("RELEASE SAVEPOINT agent_orchestration_enqueue"))
        return
