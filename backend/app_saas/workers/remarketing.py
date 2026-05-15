from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text

from app_saas.billing.limits import tenant_entitlements
from app_saas.db import db_session, set_tenant_context
from app_saas.workers.triggers import _action_send_template, _clean, _load_context, _safe_dict, _safe_list


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _remarketing_allowed(conn, tenant_id: str) -> tuple[bool, str]:
    entitlements = tenant_entitlements(conn, tenant_id)
    if not entitlements.get("is_operational"):
        return False, f"tenant_not_operational:{entitlements.get('tenant_status') or 'unknown'}"
    if not bool(entitlements.get("features", {}).get("remarketing", False)):
        return False, "feature_not_enabled:remarketing"
    return True, ""


def ensure_remarketing_runtime_tables(conn) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_remarketing_enrollments (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                flow_id UUID NOT NULL REFERENCES saas_remarketing_flows(id) ON DELETE CASCADE,
                conversation_id UUID NOT NULL REFERENCES saas_conversations(id) ON DELETE CASCADE,
                channel TEXT NOT NULL DEFAULT 'whatsapp',
                recipient_external_id TEXT NOT NULL DEFAULT '',
                current_step_order INTEGER NOT NULL DEFAULT 0,
                state TEXT NOT NULL DEFAULT 'active',
                next_run_at TIMESTAMP NULL,
                last_sent_at TIMESTAMP NULL,
                last_sent_step_order INTEGER NULL,
                last_error TEXT NOT NULL DEFAULT '',
                meta_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                enrolled_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, flow_id, conversation_id)
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_rmk_enroll_due
            ON saas_remarketing_enrollments (tenant_id, state, next_run_at)
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_rmk_enroll_conversation
            ON saas_remarketing_enrollments (tenant_id, conversation_id, updated_at DESC)
            """
        )
    )


def _split_tags(value: Any) -> list[str]:
    raw = str(value or "").replace("\n", ",").split(",")
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        tag = item.strip()
        key = tag.lower()
        if tag and key not in seen:
            seen.add(key)
            out.append(tag)
    return out[:50]


def _rules_match(conversation: dict[str, Any], rules: dict[str, Any], *, empty_matches: bool) -> bool:
    rules = _safe_dict(rules)
    condition_keys = {"tag", "crm_stage", "payment_status", "city", "customer_type", "intent", "channel", "takeover"}
    active_rules = {key: value for key, value in rules.items() if key in condition_keys and value not in ("", None, [], {})}
    if not active_rules:
        return empty_matches

    tags = ",".join(_split_tags(conversation.get("tags"))).lower()
    checks: list[bool] = []
    tag = str(rules.get("tag") or "").strip().lower()
    if tag:
        checks.append(tag in tags)

    for field in ("crm_stage", "payment_status", "city", "customer_type", "intent", "channel"):
        expected = str(rules.get(field) or "").strip().lower()
        if expected:
            current = str(conversation.get(field) or "").strip().lower()
            checks.append(expected in current if field in {"city", "intent"} else expected == current)

    takeover = rules.get("takeover")
    if isinstance(takeover, bool):
        checks.append(bool(conversation.get("takeover")) is takeover)
    elif str(takeover or "").strip().lower() in {"on", "true", "human"}:
        checks.append(bool(conversation.get("takeover")) is True)
    elif str(takeover or "").strip().lower() in {"off", "false", "ai"}:
        checks.append(bool(conversation.get("takeover")) is False)

    return all(checks) if checks else empty_matches


def _resume_after_minutes(flow: dict[str, Any]) -> int:
    rules = _safe_dict(flow.get("entry_rules_json"))
    try:
        value = int(rules.get("resume_after_minutes") or rules.get("idle_minutes") or 120)
    except Exception:
        value = 120
    return max(1, min(value, 60 * 24 * 60))


def _retry_minutes(flow: dict[str, Any]) -> int:
    rules = _safe_dict(flow.get("entry_rules_json"))
    try:
        value = int(rules.get("retry_minutes") or 30)
    except Exception:
        value = 30
    return max(1, min(value, 60 * 24))


def _steps(flow: dict[str, Any]) -> list[dict[str, Any]]:
    steps = [step for step in _safe_list(flow.get("steps_json")) if isinstance(step, dict)]
    return sorted(steps, key=lambda item: int(item.get("order") or item.get("step_order") or 0))


def _step_order(step: dict[str, Any]) -> int:
    return int(step.get("order") or step.get("step_order") or 0)


def _step_wait(step: dict[str, Any]) -> int:
    try:
        value = int(step.get("wait_minutes") or 0)
    except Exception:
        value = 0
    return max(0, min(value, 60 * 24 * 365))


def _first_step(flow: dict[str, Any]) -> dict[str, Any] | None:
    rows = _steps(flow)
    return rows[0] if rows else None


def _next_step(flow: dict[str, Any], current_order: int) -> dict[str, Any] | None:
    for step in _steps(flow):
        if _step_order(step) > int(current_order or 0):
            return step
    return None


def _load_flows(conn, tenant_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT id::text, tenant_id::text, name, channel, status,
                   entry_rules_json, exit_rules_json, steps_json
            FROM saas_remarketing_flows
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND status = 'active'
            ORDER BY updated_at ASC
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().all()
    return [dict(row) for row in rows]


def _candidate_conversations(conn, tenant_id: str, flow: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    resume_after = _resume_after_minutes(flow)
    channel = str(flow.get("channel") or "whatsapp").strip().lower()
    rows = conn.execute(
        text(
            """
            SELECT id::text, channel, external_contact_id, phone, display_name,
                   first_name, last_name, city, customer_type, interests,
                   takeover, tags, notes, payment_status, crm_stage, intent,
                   last_message_at::text, updated_at::text
            FROM saas_conversations c
            WHERE c.tenant_id = CAST(:tenant_id AS uuid)
              AND c.channel = :channel
              AND COALESCE(c.last_message_at, c.updated_at, c.created_at) <= NOW() - (:resume_after * INTERVAL '1 minute')
              AND NOT EXISTS (
                SELECT 1
                FROM saas_remarketing_enrollments e
                WHERE e.tenant_id = c.tenant_id
                  AND e.flow_id = CAST(:flow_id AS uuid)
                  AND e.conversation_id = c.id
                  AND e.state IN ('active', 'hold', 'completed')
              )
            ORDER BY COALESCE(c.last_message_at, c.updated_at, c.created_at) ASC
            LIMIT :limit
            """
        ),
        {
            "tenant_id": tenant_id,
            "channel": channel,
            "flow_id": flow["id"],
            "resume_after": resume_after,
            "limit": max(1, min(int(limit or 100), 500)),
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _add_flow_tags(conn, tenant_id: str, conversation_id: str, flow: dict[str, Any], step_order: int, state: str = "active") -> None:
    row = conn.execute(
        text(
            """
            SELECT tags
            FROM saas_conversations
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:conversation_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "conversation_id": conversation_id},
    ).mappings().first()
    tags = _split_tags((row or {}).get("tags"))
    flow_prefix = f"rmk_{str(flow['id'])[:8].lower()}_"
    tags = [tag for tag in tags if not tag.lower().startswith(flow_prefix)]
    if state == "active":
        tags.extend(["remarketing", f"{flow_prefix}s{step_order}"])
    elif state in {"completed", "exited"}:
        tags.append(f"{flow_prefix}{'done' if state == 'completed' else 'exit'}")
    merged = []
    seen: set[str] = set()
    for tag in tags:
        key = tag.lower()
        if tag and key not in seen:
            seen.add(key)
            merged.append(tag)
    conn.execute(
        text(
            """
            UPDATE saas_conversations
            SET tags = :tags, updated_at = NOW()
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:conversation_id AS uuid)
            """
        ),
        {"tenant_id": tenant_id, "conversation_id": conversation_id, "tags": ", ".join(merged[:50])},
    )


def _enroll_candidates(conn, tenant_id: str, flow: dict[str, Any], limit: int) -> int:
    first = _first_step(flow)
    if not first:
        return 0
    inserted = 0
    for conversation in _candidate_conversations(conn, tenant_id, flow, limit):
        if not _rules_match(conversation, _safe_dict(flow.get("entry_rules_json")), empty_matches=True):
            continue
        if _rules_match(conversation, _safe_dict(flow.get("exit_rules_json")), empty_matches=False):
            continue
        if bool(conversation.get("takeover")) and "takeover" not in _safe_dict(flow.get("entry_rules_json")):
            continue
        order = _step_order(first) or 1
        wait = _step_wait(first)
        conn.execute(
            text(
                """
                INSERT INTO saas_remarketing_enrollments (
                    tenant_id, flow_id, conversation_id, channel, recipient_external_id,
                    current_step_order, state, next_run_at, meta_json, updated_at
                )
                VALUES (
                    CAST(:tenant_id AS uuid), CAST(:flow_id AS uuid), CAST(:conversation_id AS uuid),
                    :channel, :recipient_external_id, :current_step_order, 'active',
                    NOW() + (:wait_minutes * INTERVAL '1 minute'),
                    CAST(:meta_json AS jsonb), NOW()
                )
                ON CONFLICT (tenant_id, flow_id, conversation_id) DO NOTHING
                """
            ),
            {
                "tenant_id": tenant_id,
                "flow_id": flow["id"],
                "conversation_id": conversation["id"],
                "channel": conversation.get("channel") or flow.get("channel") or "whatsapp",
                "recipient_external_id": conversation.get("external_contact_id") or conversation.get("phone") or "",
                "current_step_order": order,
                "wait_minutes": wait,
                "meta_json": _json({"source": "remarketing_auto_enroll", "flow_name": flow.get("name") or ""}),
            },
        )
        _add_flow_tags(conn, tenant_id, conversation["id"], flow, order, "active")
        inserted += 1
    return inserted


def _due_enrollments(conn, tenant_id: str | None, limit: int) -> list[dict[str, Any]]:
    filters = ["e.state = 'active'", "e.next_run_at IS NOT NULL", "e.next_run_at <= NOW()"]
    params: dict[str, Any] = {"limit": max(1, min(int(limit or 100), 500))}
    if tenant_id:
        filters.append("e.tenant_id = CAST(:tenant_id AS uuid)")
        params["tenant_id"] = tenant_id
    rows = conn.execute(
        text(
            f"""
            WITH due AS (
                SELECT e.id
                FROM saas_remarketing_enrollments e
                WHERE {" AND ".join(filters)}
                ORDER BY e.next_run_at ASC, e.updated_at ASC
                LIMIT :limit
                FOR UPDATE SKIP LOCKED
            )
            UPDATE saas_remarketing_enrollments e
            SET state = 'processing',
                updated_at = NOW()
            FROM due
            WHERE e.id = due.id
            RETURNING e.id::text, e.tenant_id::text, e.flow_id::text, e.conversation_id::text,
                      e.channel, e.recipient_external_id, e.current_step_order, e.meta_json
            """
        ),
        params,
    ).mappings().all()
    return [dict(row) for row in rows]


def _load_flow(conn, tenant_id: str, flow_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            """
            SELECT id::text, tenant_id::text, name, channel, status,
                   entry_rules_json, exit_rules_json, steps_json
            FROM saas_remarketing_flows
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:flow_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "flow_id": flow_id},
    ).mappings().first()
    return dict(row) if row else None


def _current_step(flow: dict[str, Any], order: int) -> dict[str, Any] | None:
    for step in _steps(flow):
        if _step_order(step) == int(order or 0):
            return step
    return _first_step(flow)


def _mark_enrollment(conn, enrollment_id: str, *, state: str, error: str = "", next_run_minutes: int | None = None, meta: dict[str, Any] | None = None) -> None:
    next_expr = "NULL" if next_run_minutes is None else "NOW() + (:next_run_minutes * INTERVAL '1 minute')"
    conn.execute(
        text(
            f"""
            UPDATE saas_remarketing_enrollments
            SET state = :state,
                next_run_at = {next_expr},
                last_error = :error,
                meta_json = meta_json || CAST(:meta_json AS jsonb),
                updated_at = NOW()
            WHERE id = CAST(:id AS uuid)
            """
        ),
        {
            "id": enrollment_id,
            "state": state,
            "error": _clean(error, 900),
            "next_run_minutes": int(next_run_minutes or 0),
            "meta_json": _json(meta or {}),
        },
    )


def _process_due_one(conn, enrollment: dict[str, Any]) -> tuple[str, int]:
    tenant_id = str(enrollment["tenant_id"])
    flow = _load_flow(conn, tenant_id, str(enrollment["flow_id"]))
    conversation = _load_context(conn, tenant_id, str(enrollment["conversation_id"]))
    if not flow or flow.get("status") != "active":
        _mark_enrollment(conn, enrollment["id"], state="hold", error="flow_not_active", next_run_minutes=60)
        return "hold", 0
    if not conversation:
        _mark_enrollment(conn, enrollment["id"], state="failed", error="conversation_not_found")
        return "failed", 0
    if _rules_match(conversation, _safe_dict(flow.get("exit_rules_json")), empty_matches=False):
        _mark_enrollment(conn, enrollment["id"], state="exited", meta={"exit_reason": "exit_rules_matched"})
        _add_flow_tags(conn, tenant_id, str(enrollment["conversation_id"]), flow, int(enrollment.get("current_step_order") or 0), "exited")
        return "exited", 0
    if bool(conversation.get("takeover")) and "takeover" not in _safe_dict(flow.get("entry_rules_json")):
        _mark_enrollment(conn, enrollment["id"], state="active", error="takeover_on", next_run_minutes=_retry_minutes(flow), meta={"last_skip": "takeover_on"})
        return "skipped", 0

    step = _current_step(flow, int(enrollment.get("current_step_order") or 0))
    if not step:
        _mark_enrollment(conn, enrollment["id"], state="completed", meta={"completed_reason": "no_steps"})
        return "completed", 0
    template_id = _clean(step.get("template_id"), 120)
    if not template_id:
        _mark_enrollment(conn, enrollment["id"], state="failed", error="step_template_required")
        return "failed", 0

    trigger = {"id": flow["id"], "name": flow.get("name") or "remarketing", "channel": flow.get("channel") or conversation.get("channel") or "whatsapp"}
    result = _action_send_template(
        conn,
        tenant_id,
        conversation,
        trigger,
        {"template_id": template_id, "remarketing_flow_id": flow["id"], "remarketing_step_order": _step_order(step)},
        "remarketing",
    )
    if not result.get("ok"):
        _mark_enrollment(conn, enrollment["id"], state="active", error=result.get("error") or "send_failed", next_run_minutes=_retry_minutes(flow))
        return "failed", 0

    current_order = _step_order(step)
    next_step = _next_step(flow, current_order)
    if next_step:
        next_order = _step_order(next_step)
        conn.execute(
            text(
                """
                UPDATE saas_remarketing_enrollments
                SET state = 'active',
                    current_step_order = :next_order,
                    next_run_at = NOW() + (:wait_minutes * INTERVAL '1 minute'),
                    last_sent_at = NOW(),
                    last_sent_step_order = :current_order,
                    last_error = '',
                    meta_json = meta_json || CAST(:meta_json AS jsonb),
                    updated_at = NOW()
                WHERE id = CAST(:id AS uuid)
                """
            ),
            {
                "id": enrollment["id"],
                "next_order": next_order,
                "wait_minutes": _step_wait(next_step),
                "current_order": current_order,
                "meta_json": _json({"last_sent_template_id": template_id, "last_sent_at": datetime.utcnow().isoformat()}),
            },
        )
        _add_flow_tags(conn, tenant_id, str(enrollment["conversation_id"]), flow, next_order, "active")
        return "queued", int(result.get("queued") or 0)

    conn.execute(
        text(
            """
            UPDATE saas_remarketing_enrollments
            SET state = 'completed',
                next_run_at = NULL,
                last_sent_at = NOW(),
                last_sent_step_order = :current_order,
                last_error = '',
                meta_json = meta_json || CAST(:meta_json AS jsonb),
                updated_at = NOW()
            WHERE id = CAST(:id AS uuid)
            """
        ),
        {
            "id": enrollment["id"],
            "current_order": current_order,
            "meta_json": _json({"last_sent_template_id": template_id, "completed_at": datetime.utcnow().isoformat()}),
        },
    )
    _add_flow_tags(conn, tenant_id, str(enrollment["conversation_id"]), flow, current_order, "completed")
    return "queued", int(result.get("queued") or 0)


def process_due_remarketing_flows(limit: int = 100, tenant_id: str | None = None, enroll_limit: int | None = None) -> dict[str, int]:
    stats = {"flows": 0, "enrolled": 0, "picked": 0, "queued": 0, "completed": 0, "exited": 0, "skipped": 0, "failed": 0}
    with db_session() as conn:
        ensure_remarketing_runtime_tables(conn)
        if tenant_id:
            set_tenant_context(conn, tenant_id)
            tenant_ids = [tenant_id]
        else:
            rows = conn.execute(
                text(
                    """
                    SELECT DISTINCT tenant_id::text
                    FROM saas_remarketing_flows
                    WHERE status = 'active'
                    ORDER BY tenant_id::text ASC
                    LIMIT 100
                    """
                )
            ).mappings().all()
            tenant_ids = [str(row["tenant_id"]) for row in rows]

        for current_tenant in tenant_ids:
            set_tenant_context(conn, current_tenant)
            allowed, reason = _remarketing_allowed(conn, current_tenant)
            if not allowed:
                continue
            flows = _load_flows(conn, current_tenant)
            stats["flows"] += len(flows)
            for flow in flows:
                stats["enrolled"] += _enroll_candidates(conn, current_tenant, flow, enroll_limit or limit)

        due_rows = _due_enrollments(conn, tenant_id, limit)
        stats["picked"] = len(due_rows)
        for row in due_rows:
            set_tenant_context(conn, str(row["tenant_id"]))
            allowed, reason = _remarketing_allowed(conn, str(row["tenant_id"]))
            if not allowed:
                _mark_enrollment(conn, row["id"], state="active", error=reason, next_run_minutes=60)
                stats["skipped"] += 1
                continue
            state, queued = _process_due_one(conn, row)
            stats["queued"] += queued
            if state == "completed":
                stats["completed"] += 1
            elif state == "exited":
                stats["exited"] += 1
            elif state == "skipped":
                stats["skipped"] += 1
            elif state == "failed":
                stats["failed"] += 1
    return stats
