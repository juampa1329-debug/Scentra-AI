from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app_saas.billing.limits import ensure_monthly_message_quota, tenant_entitlements
from app_saas.db import db_session, set_tenant_context


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _json(value: Any, fallback: Any | None = None) -> str:
    if value is None:
        value = {} if fallback is None else fallback
    return json.dumps(value, ensure_ascii=False)


def _triggers_allowed(conn, tenant_id: str) -> tuple[bool, str]:
    entitlements = tenant_entitlements(conn, tenant_id)
    if not entitlements.get("is_operational"):
        return False, f"tenant_not_operational:{entitlements.get('tenant_status') or 'unknown'}"
    if not bool(entitlements.get("features", {}).get("triggers", False)):
        return False, "feature_not_enabled:triggers"
    return True, ""


def _clean(value: Any, limit: int = 4000) -> str:
    return str(value or "").strip()[:limit]


def _norm(value: Any) -> str:
    raw = str(value or "").strip().lower()
    normalized = unicodedata.normalize("NFKD", raw)
    asciiish = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", asciiish).strip()


def _compare(left: float, op: str, right: float) -> bool:
    token = str(op or "gte").strip().lower()
    if token in {"=", "eq"}:
        return left == right
    if token in {"!=", "ne"}:
        return left != right
    if token in {"<", "lt"}:
        return left < right
    if token in {"<=", "lte"}:
        return left <= right
    if token in {">", "gt"}:
        return left > right
    return left >= right


def _split_tags(value: Any) -> list[str]:
    items = value if isinstance(value, list) else str(value or "").replace("\n", ",").split(",")
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        tag = _clean(item, 80)
        key = _norm(tag)
        if tag and key not in seen:
            seen.add(key)
            out.append(tag)
    return out[:50]


def _join_tags(tags: list[str]) -> str:
    out: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        label = _clean(tag, 80)
        key = _norm(label)
        if label and key not in seen:
            seen.add(key)
            out.append(label)
    return ", ".join(out)


def _render(text_value: Any, variables: dict[str, Any]) -> str:
    out = str(text_value or "")
    for key, value in variables.items():
        token = str(key or "").strip()
        if not token:
            continue
        out = out.replace(f"{{{{{token}}}}}", str(value if value is not None else ""))
    return out.strip()


def _event_matches(trigger: dict[str, Any], event_kind: str) -> bool:
    trigger_type = _norm(trigger.get("trigger_type") or "message_flow")
    flow_event = _norm(trigger.get("flow_event") or "received")
    event_type = _norm(trigger.get("event_type") or "message_in")
    event = _norm(event_kind or "received")

    if trigger_type in {"none", "tag_changed"}:
        return False
    if trigger_type == "comment_flow" and event != "comment":
        return False
    if trigger_type == "message_flow" and event == "comment":
        return False

    if event == "comment":
        return event_type in {"comment", "comment_in", "comment_received", "incoming_comment", "all", "*"} or "comment" in event_type
    if event == "sent":
        if trigger_type == "message_flow" and flow_event not in {"sent", "both", "all"}:
            return False
        return event_type in {"message_out", "outbound", "outgoing", "sent", "message", "all", "*"} or ("message" in event_type and "out" in event_type)

    if trigger_type == "message_flow" and flow_event not in {"received", "both", "all"}:
        return False
    return event_type in {"message_in", "inbound", "incoming", "received", "message", "all", "*"} or ("message" in event_type and "in" in event_type)


def _conditions_payload(value: Any) -> tuple[str, list[dict[str, Any]]]:
    root = _safe_dict(value)
    mode = _norm(root.get("match") or root.get("mode") or "all")
    if mode not in {"all", "any"}:
        mode = "all"
    rows = _safe_list(root.get("conditions"))
    if not rows and isinstance(root.get("all"), list):
        rows = root["all"]
    if not rows and root.get("contains"):
        rows = [{"type": "check_words", "words": [str(root.get("contains") or "")]}]
    return mode, [row for row in rows if isinstance(row, dict)]


def _actions_payload(value: Any) -> list[dict[str, Any]]:
    root = _safe_dict(value)
    rows = _safe_list(root.get("actions"))
    if not rows and isinstance(root.get("list"), list):
        rows = root["list"]
    if not rows and root.get("type"):
        rows = [root]
    return [row for row in rows if isinstance(row, dict)]


def _conversation_vars(conversation: dict[str, Any]) -> dict[str, Any]:
    first_name = _clean(conversation.get("first_name") or "").strip()
    display = _clean(conversation.get("display_name") or "").strip()
    if not first_name and display:
        first_name = display.split(" ", 1)[0]
    customer_name = display or "cliente"
    return {
        "customer_name": customer_name,
        "customer_first_name": first_name or customer_name,
        "customer_phone": _clean(conversation.get("phone") or conversation.get("external_contact_id")),
        "customer_city": _clean(conversation.get("city")),
        "crm_stage": _clean(conversation.get("crm_stage")),
        "payment_status": _clean(conversation.get("payment_status")),
        "interests": _clean(conversation.get("interests")),
        "tags": _clean(conversation.get("tags")),
        "business_name": "Scentra +AI",
        "assistant_name": "Asesor IA",
    }


def _load_context(conn, tenant_id: str, conversation_id: str, message_id: str | None = None) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            """
            SELECT
                c.id::text,
                c.tenant_id::text,
                c.channel,
                c.external_contact_id,
                c.phone,
                c.display_name,
                c.first_name,
                c.last_name,
                c.city,
                c.customer_type,
                c.interests,
                c.takeover,
                c.tags,
                c.notes,
                c.payment_status,
                c.crm_stage,
                c.intent,
                c.profile_json,
                m.id::text AS message_id,
                m.text AS message_text,
                m.msg_type,
                m.direction,
                m.created_at::text AS message_created_at
            FROM saas_conversations c
            LEFT JOIN saas_messages m
              ON m.tenant_id = c.tenant_id
             AND m.conversation_id = c.id
             AND (:message_id = '' OR m.id = CAST(NULLIF(:message_id, '') AS uuid))
            WHERE c.tenant_id = CAST(:tenant_id AS uuid)
              AND c.id = CAST(:conversation_id AS uuid)
            ORDER BY m.created_at DESC NULLS LAST
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "conversation_id": conversation_id, "message_id": message_id or ""},
    ).mappings().first()
    return dict(row) if row else None


def _is_in_cooldown(conn, tenant_id: str, trigger_id: str, recipient: str, minutes: int) -> bool:
    cooldown = max(0, int(minutes or 0))
    if cooldown <= 0:
        return False
    since = datetime.utcnow() - timedelta(minutes=cooldown)
    row = conn.execute(
        text(
            """
            SELECT 1
            FROM saas_trigger_executions
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND trigger_id = CAST(:trigger_id AS uuid)
              AND recipient_external_id = :recipient
              AND executed_at >= :since
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "trigger_id": trigger_id, "recipient": recipient, "since": since},
    ).first()
    return bool(row)


def _condition_check_words(user_text: str, condition: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    text_norm = _norm(user_text)
    raw_words = condition.get("words")
    if isinstance(raw_words, str):
        words = [item.strip() for item in raw_words.split(",") if item.strip()]
    else:
        words = [str(item or "").strip() for item in _safe_list(raw_words) if str(item or "").strip()]
    tokens = [_norm(word) for word in words if _norm(word)]
    if not tokens:
        return False, {"reason": "empty_words"}
    mode = "all" if _norm(condition.get("mode")) == "all" else "any"
    matched = [word for word in tokens if word in text_norm]
    ok = len(matched) == len(tokens) if mode == "all" else bool(matched)
    return ok, {"mode": mode, "words": tokens, "matched": matched}


def _condition_template_sent_status(conn, tenant_id: str, conversation_id: str, condition: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    template_id = _clean(condition.get("template_id"), 120)
    state = "sent" if _norm(condition.get("state")) == "sent" else "not_sent"
    if not template_id:
        return state == "not_sent", {"reason": "template_id_empty", "state": state}
    count = conn.execute(
        text(
            """
            SELECT COUNT(*)
            FROM saas_messages
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND conversation_id = CAST(:conversation_id AS uuid)
              AND direction = 'out'
              AND payload_json->>'template_id' = :template_id
            """
        ),
        {"tenant_id": tenant_id, "conversation_id": conversation_id, "template_id": template_id},
    ).scalar_one()
    sent = int(count or 0) > 0
    return (sent if state == "sent" else not sent), {"state": state, "sent": sent, "count": int(count or 0), "template_id": template_id}


def _condition_current_tag(conversation: dict[str, Any], condition: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    expected = _norm(condition.get("tag"))
    state = "not_has" if _norm(condition.get("state")) == "not_has" else "has"
    tags = [_norm(tag) for tag in _split_tags(conversation.get("tags"))]
    has = expected in tags if expected else False
    return (not has if state == "not_has" else has), {"state": state, "tag": expected, "tags": tags}


def _condition_last_message_sent(conn, tenant_id: str, conversation_id: str, condition: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    row = conn.execute(
        text(
            """
            SELECT created_at
            FROM saas_messages
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND conversation_id = CAST(:conversation_id AS uuid)
              AND direction = 'out'
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "conversation_id": conversation_id},
    ).mappings().first()
    last_out = row["created_at"] if row else None
    minutes_since = 999999.0
    if isinstance(last_out, datetime):
        minutes_since = max(0.0, (datetime.utcnow() - last_out).total_seconds() / 60.0)
    value = float(condition.get("minutes") or condition.get("value") or 0)
    op = _norm(condition.get("op") or "gte")
    return _compare(minutes_since, op, value), {"minutes_since": minutes_since, "op": op, "value": value}


def _condition_sent_count(conn, tenant_id: str, conversation_id: str, condition: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    value = float(condition.get("value") or condition.get("count") or 0)
    op = _norm(condition.get("op") or "gte")
    window_hours = max(1, min(int(condition.get("window_hours") or 24), 24 * 180))
    since = datetime.utcnow() - timedelta(hours=window_hours)
    count = conn.execute(
        text(
            """
            SELECT COUNT(*)
            FROM saas_messages
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND conversation_id = CAST(:conversation_id AS uuid)
              AND direction = 'out'
              AND created_at >= :since
            """
        ),
        {"tenant_id": tenant_id, "conversation_id": conversation_id, "since": since},
    ).scalar_one()
    current = float(count or 0)
    return _compare(current, op, value), {"count": current, "op": op, "value": value, "window_hours": window_hours}


def _parse_hhmm(raw: Any, fallback: int) -> int:
    text_value = str(raw or "").strip()
    match = re.match(r"^(\d{1,2}):(\d{2})$", text_value)
    if not match:
        return fallback
    hour = max(0, min(int(match.group(1)), 23))
    minute = max(0, min(int(match.group(2)), 59))
    return hour * 60 + minute


def _condition_schedule(condition: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    tz_name = str(condition.get("timezone") or "America/Bogota").strip()
    try:
        zone = ZoneInfo(tz_name)
    except Exception:
        zone = ZoneInfo("America/Bogota")
        tz_name = "America/Bogota"
    now = datetime.now(zone)
    days = [str(day or "").strip().lower()[:3] for day in _safe_list(condition.get("days")) if str(day or "").strip()]
    week_days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    current_day = week_days[now.weekday()]
    if days and current_day not in days:
        return False, {"reason": "day_not_allowed", "current_day": current_day, "days": days, "timezone": tz_name}
    start = _parse_hhmm(condition.get("start_time"), 0)
    end = _parse_hhmm(condition.get("end_time"), 23 * 60 + 59)
    current = now.hour * 60 + now.minute
    in_window = start <= current <= end if start <= end else current >= start or current <= end
    return in_window, {"timezone": tz_name, "current_day": current_day, "days": days, "start_minutes": start, "end_minutes": end, "now_minutes": current}


def _evaluate_conditions(conn, tenant_id: str, conversation: dict[str, Any], user_text: str, conditions_json: Any) -> tuple[bool, list[dict[str, Any]]]:
    mode, conditions = _conditions_payload(conditions_json)
    if not conditions:
        return True, []
    evals: list[dict[str, Any]] = []
    for condition in conditions:
        ctype = _norm(condition.get("type"))
        ok = False
        info: dict[str, Any] = {}
        if ctype in {"check_words", "comment_keywords"}:
            ok, info = _condition_check_words(user_text, condition)
        elif ctype == "template_sent_status":
            ok, info = _condition_template_sent_status(conn, tenant_id, conversation["id"], condition)
        elif ctype == "current_tag":
            ok, info = _condition_current_tag(conversation, condition)
        elif ctype == "last_message_sent":
            ok, info = _condition_last_message_sent(conn, tenant_id, conversation["id"], condition)
        elif ctype == "sent_count":
            ok, info = _condition_sent_count(conn, tenant_id, conversation["id"], condition)
        elif ctype == "schedule":
            ok, info = _condition_schedule(condition)
        else:
            info = {"reason": "unknown_condition_type"}
        evals.append({"type": ctype or "unknown", "ok": bool(ok), "info": info})
    matched = any(item["ok"] for item in evals) if mode == "any" else all(item["ok"] for item in evals)
    return bool(matched), evals


def _load_template(conn, tenant_id: str, template_id: str) -> dict[str, Any] | None:
    if not template_id:
        return None
    row = conn.execute(
        text(
            """
            SELECT id::text, name, channel, status, body, blocks_json, params_json
            FROM saas_message_templates
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:template_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "template_id": template_id},
    ).mappings().first()
    return dict(row) if row else None


def _text_blocks(template: dict[str, Any], variables: dict[str, Any]) -> list[str]:
    blocks = _safe_list(template.get("blocks_json"))
    out: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        kind = _norm(block.get("kind") or block.get("type") or "text")
        if kind == "text":
            rendered = _render(block.get("text") or block.get("body") or block.get("content"), variables)
        elif kind in {"image", "video"}:
            rendered = _render(block.get("caption") or "", variables)
        else:
            rendered = ""
        if rendered:
            out.append(rendered)
    if out:
        return out
    fallback = _render(template.get("body") or "", variables)
    return [fallback] if fallback else []


def _queue_outbound_text(
    conn,
    *,
    tenant_id: str,
    conversation: dict[str, Any],
    body_text: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    body = _clean(body_text, 4000)
    if not body:
        return {"ok": False, "error": "empty_body"}
    ensure_monthly_message_quota(conn, tenant_id, requested=1)
    channel = _clean(conversation.get("channel"), 40) or "whatsapp"
    conversation_id = str(conversation["id"])
    external_id = f"local:trigger:{uuid4().hex}"
    message = conn.execute(
        text(
            """
            INSERT INTO saas_messages (
                tenant_id, conversation_id, channel, external_message_id, direction, msg_type, text, payload_json
            )
            VALUES (
                CAST(:tenant_id AS uuid), CAST(:conversation_id AS uuid), :channel, :external_message_id,
                'out', 'text', :body_text, CAST(:payload_json AS jsonb)
            )
            RETURNING id::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "conversation_id": conversation_id,
            "channel": channel,
            "external_message_id": external_id,
            "body_text": body,
            "payload_json": _json(payload),
        },
    ).mappings().first()
    outbound = conn.execute(
        text(
            """
            INSERT INTO saas_outbound_messages (
                tenant_id, conversation_id, message_id, channel, recipient_external_id, body_text, payload_json
            )
            VALUES (
                CAST(:tenant_id AS uuid), CAST(:conversation_id AS uuid), CAST(:message_id AS uuid),
                :channel, :recipient_external_id, :body_text, CAST(:payload_json AS jsonb)
            )
            RETURNING id::text, status
            """
        ),
        {
            "tenant_id": tenant_id,
            "conversation_id": conversation_id,
            "message_id": message["id"],
            "channel": channel,
            "recipient_external_id": _clean(conversation.get("external_contact_id") or conversation.get("phone"), 180),
            "body_text": body,
            "payload_json": _json({"local_external_message_id": external_id, **payload}),
        },
    ).mappings().first()
    conn.execute(
        text(
            """
            INSERT INTO saas_usage_counters (
                tenant_id, metric_code, period_yyyymm, metric_value
            )
            VALUES (
                CAST(:tenant_id AS uuid),
                'outbound_messages_queued',
                TO_CHAR(NOW(), 'YYYYMM'),
                1
            )
            ON CONFLICT (tenant_id, metric_code, period_yyyymm)
            DO UPDATE SET
                metric_value = saas_usage_counters.metric_value + 1,
                updated_at = NOW()
            """
        ),
        {"tenant_id": tenant_id},
    )
    conn.execute(
        text(
            """
            UPDATE saas_conversations
            SET last_message_text = :body_text,
                last_message_at = NOW(),
                updated_at = NOW()
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:conversation_id AS uuid)
            """
        ),
        {"tenant_id": tenant_id, "conversation_id": conversation_id, "body_text": body},
    )
    return {"ok": True, "message_id": message["id"], "outbound_id": outbound["id"], "status": outbound["status"]}


def _action_send_template(conn, tenant_id: str, conversation: dict[str, Any], trigger: dict[str, Any], action: dict[str, Any], source: str) -> dict[str, Any]:
    template_id = _clean(action.get("template_id"), 120)
    template = _load_template(conn, tenant_id, template_id)
    if not template:
        return {"ok": False, "error": "template_not_found", "template_id": template_id}
    variables = {**_safe_dict(template.get("params_json")), **_conversation_vars(conversation), **_safe_dict(action.get("overrides"))}
    bodies = _text_blocks(template, variables)
    if not bodies:
        return {"ok": False, "error": "template_without_text_blocks", "template_id": template_id}
    queued = []
    for idx, body in enumerate(bodies):
        queued.append(
            _queue_outbound_text(
                conn,
                tenant_id=tenant_id,
                conversation=conversation,
                body_text=body,
                payload={
                    "source": source,
                    "trigger_id": trigger["id"],
                    "template_id": template_id,
                    "template_name": template.get("name") or "",
                    "block_index": idx,
                },
            )
        )
    ok_count = sum(1 for item in queued if item.get("ok"))
    return {"ok": ok_count == len(queued), "queued": ok_count, "template_id": template_id, "messages": queued}


def _action_change_tag(conn, tenant_id: str, conversation: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    mode = _norm(action.get("mode") or "add")
    raw_tags = action.get("tags")
    tags_to_apply = _split_tags(raw_tags)
    single = _clean(action.get("tag"), 80)
    if single:
        tags_to_apply.append(single)
    current = _split_tags(conversation.get("tags"))
    apply_keys = {_norm(tag) for tag in tags_to_apply}
    if mode == "remove":
        next_tags = [tag for tag in current if _norm(tag) not in apply_keys]
    elif mode == "set":
        next_tags = tags_to_apply
    else:
        next_tags = current + tags_to_apply
    tags_csv = _join_tags(next_tags)
    conn.execute(
        text(
            """
            UPDATE saas_conversations
            SET tags = :tags, updated_at = NOW()
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:conversation_id AS uuid)
            """
        ),
        {"tenant_id": tenant_id, "conversation_id": conversation["id"], "tags": tags_csv},
    )
    conversation["tags"] = tags_csv
    return {"ok": True, "mode": mode, "tags": _split_tags(tags_csv)}


def _action_configure_conversation(conn, tenant_id: str, conversation: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    takeover_raw = action.get("takeover")
    profile_patch: dict[str, Any] = {}
    sets = ["updated_at = NOW()"]
    params: dict[str, Any] = {"tenant_id": tenant_id, "conversation_id": conversation["id"]}
    if isinstance(takeover_raw, bool):
        sets.append("takeover = :takeover")
        params["takeover"] = takeover_raw
    elif isinstance(takeover_raw, str):
        token = _norm(takeover_raw)
        if token in {"on", "true", "1", "yes"}:
            sets.append("takeover = TRUE")
            params["takeover"] = True
        elif token in {"off", "false", "0", "no"}:
            sets.append("takeover = FALSE")
            params["takeover"] = False
    if bool(action.get("clear_ai_state")):
        sets.append("profile_json = profile_json - 'ai_state'")
    elif _clean(action.get("ai_state"), 120):
        profile_patch["ai_state"] = _clean(action.get("ai_state"), 120)
        params["profile_patch"] = _json(profile_patch)
        sets.append("profile_json = profile_json || CAST(:profile_patch AS jsonb)")
    conn.execute(
        text(
            f"""
            UPDATE saas_conversations
            SET {", ".join(sets)}
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:conversation_id AS uuid)
            """
        ),
        params,
    )
    return {"ok": True, "takeover": params.get("takeover", takeover_raw), "profile_patch": profile_patch}


def _action_change_contact_status(conn, tenant_id: str, conversation: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    field = _norm(action.get("field") or "customer_type")
    if field not in {"customer_type", "payment_status", "crm_stage", "intent"}:
        field = "customer_type"
    status = _clean(action.get("status"), 140)
    if not status:
        return {"ok": False, "error": "status_required"}
    conn.execute(
        text(
            f"""
            UPDATE saas_conversations
            SET {field} = :status, updated_at = NOW()
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:conversation_id AS uuid)
            """
        ),
        {"tenant_id": tenant_id, "conversation_id": conversation["id"], "status": status},
    )
    conversation[field] = status
    return {"ok": True, "field": field, "status": status}


def _action_notify_admins(conn, tenant_id: str, conversation: dict[str, Any], trigger: dict[str, Any], action: dict[str, Any], user_text: str) -> dict[str, Any]:
    variables = _conversation_vars(conversation)
    variables["incoming_text"] = user_text
    variables["trigger_name"] = trigger.get("name") or ""
    body = _render(action.get("message") or "Alerta trigger {{trigger_name}} para {{customer_name}}: {{incoming_text}}", variables)
    conn.execute(
        text(
            """
            INSERT INTO saas_audit_events (tenant_id, action, resource_type, resource_id, details_json)
            VALUES (
                CAST(:tenant_id AS uuid), 'trigger.notify_admins', 'trigger', :trigger_id, CAST(:details_json AS jsonb)
            )
            """
        ),
        {"tenant_id": tenant_id, "trigger_id": trigger["id"], "details_json": _json({"message": body, "conversation_id": conversation["id"]})},
    )
    return {"ok": True, "recorded": True}


def _action_extract_conversation_info(conn, tenant_id: str, conversation: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    limit = max(3, min(int(action.get("last_messages") or 10), 30))
    rows = conn.execute(
        text(
            """
            SELECT direction, text
            FROM saas_messages
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND conversation_id = CAST(:conversation_id AS uuid)
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "conversation_id": conversation["id"], "limit": limit},
    ).mappings().all()
    lines = []
    for row in reversed(rows):
        prefix = "Cliente" if row["direction"] == "in" else "Scentra"
        text_value = _clean(row["text"], 600)
        if text_value:
            lines.append(f"{prefix}: {text_value}")
    payload = {"trigger_extract": {"summary": " | ".join(lines)[:1600], "messages_considered": len(rows), "updated_at": datetime.utcnow().isoformat()}}
    conn.execute(
        text(
            """
            UPDATE saas_conversations
            SET profile_json = profile_json || CAST(:payload AS jsonb),
                last_profiled_at = NOW(),
                updated_at = NOW()
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:conversation_id AS uuid)
            """
        ),
        {"tenant_id": tenant_id, "conversation_id": conversation["id"], "payload": _json(payload)},
    )
    return {"ok": True, **payload["trigger_extract"]}


def _action_schedule_message(conn, tenant_id: str, conversation: dict[str, Any], trigger: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    template_id = _clean(action.get("template_id"), 120)
    delay_minutes = max(0, min(int(action.get("delay_minutes") or 0), 60 * 24 * 90))
    if not template_id:
        return {"ok": False, "error": "template_id_required"}
    run_at = datetime.utcnow() + timedelta(minutes=delay_minutes)
    row = conn.execute(
        text(
            """
            INSERT INTO saas_trigger_scheduled_messages (
                tenant_id, trigger_id, conversation_id, template_id, channel, recipient_external_id, payload_json, run_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), CAST(:trigger_id AS uuid), CAST(:conversation_id AS uuid),
                CAST(:template_id AS uuid), :channel, :recipient_external_id, CAST(:payload_json AS jsonb), :run_at
            )
            RETURNING id::text, run_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "trigger_id": trigger["id"],
            "conversation_id": conversation["id"],
            "template_id": template_id,
            "channel": conversation.get("channel") or "whatsapp",
            "recipient_external_id": _clean(conversation.get("external_contact_id") or conversation.get("phone"), 180),
            "payload_json": _json({"source": "trigger_scheduled", "trigger_id": trigger["id"], "template_id": template_id}),
            "run_at": run_at,
        },
    ).mappings().first()
    return {"ok": True, "scheduled_id": row["id"], "run_at": row["run_at"]}


def _execute_actions(conn, tenant_id: str, conversation: dict[str, Any], trigger: dict[str, Any], user_text: str, event_kind: str) -> dict[str, Any]:
    actions = _actions_payload(trigger.get("actions_json") or trigger.get("action_json"))
    results = []
    failed = 0
    queued_total = 0
    for idx, action in enumerate(actions):
        atype = _norm(action.get("type"))
        try:
            if atype == "send_template":
                result = _action_send_template(conn, tenant_id, conversation, trigger, action, "trigger")
                queued_total += int(result.get("queued") or 0)
            elif atype == "reply_comment":
                mode = _norm(action.get("mode") or ("ai" if action.get("use_ai") else "text"))
                if mode == "template":
                    result = _action_send_template(conn, tenant_id, conversation, trigger, action, "trigger_comment")
                    queued_total += int(result.get("queued") or 0)
                else:
                    body = action.get("reply_text") or action.get("text") or action.get("ai_prompt") or "Gracias por escribirnos. Te contactamos por interno."
                    result = _queue_outbound_text(conn, tenant_id=tenant_id, conversation=conversation, body_text=_render(body, _conversation_vars(conversation)), payload={"source": "trigger_comment", "trigger_id": trigger["id"]})
                    queued_total += 1 if result.get("ok") else 0
            elif atype == "change_tag":
                result = _action_change_tag(conn, tenant_id, conversation, action)
            elif atype == "configure_conversation":
                result = _action_configure_conversation(conn, tenant_id, conversation, action)
            elif atype == "change_contact_status":
                result = _action_change_contact_status(conn, tenant_id, conversation, action)
            elif atype == "notify_admins":
                result = _action_notify_admins(conn, tenant_id, conversation, trigger, action, user_text)
            elif atype == "extract_conversation_info":
                result = _action_extract_conversation_info(conn, tenant_id, conversation, action)
            elif atype == "schedule_message":
                result = _action_schedule_message(conn, tenant_id, conversation, trigger, action)
            else:
                result = {"ok": False, "error": "unknown_action_type"}
        except Exception as exc:
            result = {"ok": False, "error": str(exc)[:900]}
        if result.get("ok") is not True:
            failed += 1
        results.append({"index": idx, "type": atype or "unknown", "ok": result.get("ok") is True, "result": result})
    return {"ok": failed == 0, "actions_total": len(actions), "failed_actions": failed, "queued_messages": queued_total, "actions": results, "event_kind": event_kind}


def _insert_execution(
    conn,
    *,
    tenant_id: str,
    trigger: dict[str, Any],
    conversation: dict[str, Any],
    message_id: str | None,
    event_kind: str,
    status: str,
    error: str,
    details: dict[str, Any],
) -> None:
    conn.execute(
        text(
            """
            INSERT INTO saas_trigger_executions (
                tenant_id, trigger_id, conversation_id, message_id, channel, event_kind,
                recipient_external_id, status, error, details_json
            )
            VALUES (
                CAST(:tenant_id AS uuid), CAST(:trigger_id AS uuid), CAST(:conversation_id AS uuid),
                CAST(NULLIF(:message_id, '') AS uuid), :channel, :event_kind, :recipient_external_id,
                :status, :error, CAST(:details_json AS jsonb)
            )
            """
        ),
        {
            "tenant_id": tenant_id,
            "trigger_id": trigger["id"],
            "conversation_id": conversation["id"],
            "message_id": message_id or "",
            "channel": conversation.get("channel") or trigger.get("channel") or "whatsapp",
            "event_kind": event_kind,
            "recipient_external_id": _clean(conversation.get("external_contact_id") or conversation.get("phone"), 180),
            "status": status[:40],
            "error": error[:900],
            "details_json": _json(details),
        },
    )
    conn.execute(
        text(
            """
            UPDATE saas_crm_triggers
            SET last_run_at = NOW(), updated_at = NOW()
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:trigger_id AS uuid)
            """
        ),
        {"tenant_id": tenant_id, "trigger_id": trigger["id"]},
    )


def execute_triggers_for_message(
    conn,
    *,
    tenant_id: str,
    conversation_id: str,
    message_id: str,
    event_kind: str = "received",
) -> dict[str, Any]:
    set_tenant_context(conn, tenant_id)
    allowed, reason = _triggers_allowed(conn, tenant_id)
    if not allowed:
        return {"ok": False, "matched": False, "reason": reason}
    conversation = _load_context(conn, tenant_id, conversation_id, message_id)
    if not conversation:
        return {"ok": False, "matched": False, "reason": "conversation_not_found"}
    channel = _clean(conversation.get("channel"), 40).lower() or "whatsapp"
    message_text = _clean(conversation.get("message_text"), 4000)
    if _norm(conversation.get("msg_type")) == "comment":
        event_kind = "comment"
    triggers = conn.execute(
        text(
            """
            SELECT id::text, name, channel, event_type, trigger_type, flow_event, conditions_json, actions_json,
                   priority, cooldown_minutes, is_active, assistant_enabled, assistant_message_type,
                   block_ai, stop_on_match, only_when_no_takeover
            FROM saas_crm_triggers
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND is_active = TRUE
              AND channel = :channel
            ORDER BY priority ASC, updated_at ASC
            """
        ),
        {"tenant_id": tenant_id, "channel": channel},
    ).mappings().all()

    matched = False
    sent = False
    details = []
    recipient = _clean(conversation.get("external_contact_id") or conversation.get("phone"), 180)
    takeover = bool(conversation.get("takeover"))

    for row in triggers:
        trigger = dict(row)
        if not _event_matches(trigger, event_kind):
            continue
        if bool(trigger.get("only_when_no_takeover")) and takeover:
            details.append({"trigger_id": trigger["id"], "name": trigger.get("name"), "skipped": "takeover_on"})
            continue
        if _is_in_cooldown(conn, tenant_id, trigger["id"], recipient, int(trigger.get("cooldown_minutes") or 0)):
            details.append({"trigger_id": trigger["id"], "name": trigger.get("name"), "skipped": "cooldown"})
            continue
        conditions_ok, condition_evals = _evaluate_conditions(conn, tenant_id, conversation, message_text, trigger.get("conditions_json"))
        if not conditions_ok:
            details.append({"trigger_id": trigger["id"], "name": trigger.get("name"), "matched": False, "conditions": condition_evals})
            continue

        matched = True
        action_result = _execute_actions(conn, tenant_id, conversation, trigger, message_text, event_kind)
        status = "ok" if action_result.get("ok") else "error"
        error = "" if status == "ok" else "actions_failed"
        sent = sent or int(action_result.get("queued_messages") or 0) > 0
        execution_details = {"conditions": condition_evals, "result": action_result, "block_ai": bool(trigger.get("block_ai")) and status == "ok"}
        _insert_execution(
            conn,
            tenant_id=tenant_id,
            trigger=trigger,
            conversation=conversation,
            message_id=message_id,
            event_kind=event_kind,
            status=status,
            error=error,
            details=execution_details,
        )
        details.append({"trigger_id": trigger["id"], "name": trigger.get("name"), "matched": True, "status": status, "sent": sent, "conditions": condition_evals, "actions": action_result.get("actions") or []})
        if bool(trigger.get("stop_on_match")):
            break

    return {"ok": True, "matched": matched, "sent": sent, "details": details}


def process_due_scheduled_trigger_messages(limit: int = 50, tenant_id: str | None = None) -> dict[str, int]:
    stats = {"picked": 0, "queued": 0, "failed": 0}
    with db_session() as conn:
        filters = ["status = 'pending'", "run_at <= NOW()"]
        params: dict[str, Any] = {"limit": max(1, min(int(limit or 50), 500))}
        if tenant_id:
            filters.append("tenant_id = CAST(:tenant_id AS uuid)")
            params["tenant_id"] = tenant_id
            set_tenant_context(conn, tenant_id)
        rows = conn.execute(
            text(
                f"""
                WITH due AS (
                    SELECT id, tenant_id::text, trigger_id::text, conversation_id::text, template_id::text, payload_json
                    FROM saas_trigger_scheduled_messages
                    WHERE {" AND ".join(filters)}
                    ORDER BY run_at ASC, created_at ASC
                    LIMIT :limit
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE saas_trigger_scheduled_messages sm
                SET status = 'processing',
                    attempts = sm.attempts + 1,
                    updated_at = NOW()
                FROM due
                WHERE sm.id = due.id
                RETURNING due.id::text, due.tenant_id, due.trigger_id, due.conversation_id, due.template_id, due.payload_json
                """
            ),
            params,
        ).mappings().all()
        stats["picked"] = len(rows)
        for row in rows:
            tenant = row["tenant_id"]
            set_tenant_context(conn, tenant)
            allowed, reason = _triggers_allowed(conn, tenant)
            if not allowed:
                conn.execute(
                    text("UPDATE saas_trigger_scheduled_messages SET status = 'failed', last_error = :error, updated_at = NOW() WHERE id = CAST(:id AS uuid)"),
                    {"id": row["id"], "error": reason},
                )
                stats["failed"] += 1
                continue
            conversation = _load_context(conn, tenant, row["conversation_id"])
            trigger = {"id": row["trigger_id"] or "", "name": "scheduled_trigger", "channel": conversation.get("channel") if conversation else "whatsapp"}
            if not conversation or not row["template_id"]:
                conn.execute(
                    text("UPDATE saas_trigger_scheduled_messages SET status = 'failed', last_error = :error, updated_at = NOW() WHERE id = CAST(:id AS uuid)"),
                    {"id": row["id"], "error": "invalid_scheduled_message"},
                )
                stats["failed"] += 1
                continue
            result = _action_send_template(conn, tenant, conversation, trigger, {"template_id": row["template_id"], **_safe_dict(row["payload_json"])}, "trigger_scheduled")
            if result.get("ok"):
                conn.execute(
                    text("UPDATE saas_trigger_scheduled_messages SET status = 'sent', sent_at = NOW(), last_error = '', updated_at = NOW() WHERE id = CAST(:id AS uuid)"),
                    {"id": row["id"]},
                )
                stats["queued"] += int(result.get("queued") or 0)
            else:
                conn.execute(
                    text("UPDATE saas_trigger_scheduled_messages SET status = 'failed', last_error = :error, updated_at = NOW() WHERE id = CAST(:id AS uuid)"),
                    {"id": row["id"], "error": _clean(result.get("error") or "send_failed", 900)},
                )
                stats["failed"] += 1
    return stats
