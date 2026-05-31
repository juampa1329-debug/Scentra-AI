from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timedelta
from hashlib import sha256
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


def _condition_conversation_field(conversation: dict[str, Any], condition: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    ctype = _norm(condition.get("type"))
    field = _norm(condition.get("field") or ctype)
    allowed = {"crm_stage", "payment_status", "customer_type", "intent"}
    if field not in allowed:
        return False, {"reason": "unsupported_field", "field": field}
    expected = _norm(condition.get("value") or condition.get("status") or condition.get("stage"))
    actual = _norm(conversation.get(field))
    if not expected:
        return False, {"reason": "empty_value", "field": field, "actual": actual}
    op = _norm(condition.get("op") or condition.get("state") or "is")
    if op in {"not", "not_is", "neq", "!="}:
        ok = actual != expected
    elif op in {"contains", "has"}:
        ok = expected in actual
    elif op in {"not_contains", "not_has"}:
        ok = expected not in actual
    else:
        ok = actual == expected
    return bool(ok), {"field": field, "op": op or "is", "expected": expected, "actual": actual}


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


def _quiet_hours_blocked(value: Any) -> tuple[bool, dict[str, Any]]:
    settings = _safe_dict(value)
    if not bool(settings.get("enabled")):
        return False, {"enabled": False}
    condition = {
        "timezone": settings.get("timezone") or "America/Bogota",
        "start_time": settings.get("start_time") or "21:00",
        "end_time": settings.get("end_time") or "08:00",
        "days": settings.get("days") or ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
    }
    in_window, info = _condition_schedule(condition)
    return bool(in_window), {"enabled": True, **info}


def _campaign_quiet_hours_rows(conn, tenant_id: str, channel: str, entity_type: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT channel, entity_type, enabled, timezone, start_time, end_time, days_json
            FROM saas_campaign_quiet_hours
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND enabled = TRUE
              AND channel IN ('all', :channel)
              AND entity_type IN ('all', :entity_type)
            ORDER BY
                CASE WHEN channel = :channel THEN 0 ELSE 1 END,
                CASE WHEN entity_type = :entity_type THEN 0 ELSE 1 END,
                updated_at DESC
            """
        ),
        {
            "tenant_id": tenant_id,
            "channel": _clean(channel, 40).lower() or "whatsapp",
            "entity_type": _clean(entity_type, 40).lower() or "all",
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _campaign_quiet_hours_blocked(conn, tenant_id: str, channel: str, entity_type: str) -> tuple[bool, dict[str, Any]]:
    details = []
    for row in _campaign_quiet_hours_rows(conn, tenant_id, channel, entity_type):
        blocked, info = _quiet_hours_blocked(
            {
                "enabled": bool(row.get("enabled")),
                "timezone": row.get("timezone") or "America/Bogota",
                "start_time": row.get("start_time") or "21:00",
                "end_time": row.get("end_time") or "08:00",
                "days": _safe_list(row.get("days_json")) or ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
            }
        )
        info = {**info, "scope": {"channel": row.get("channel") or "all", "entity_type": row.get("entity_type") or "all"}}
        details.append(info)
        if blocked:
            return True, {"enabled": True, "source": "global", "matches": details}
    return False, {"enabled": bool(details), "source": "global", "matches": details}


def _select_ab_variant(config_value: Any, recipient: str) -> dict[str, Any]:
    config = _safe_dict(config_value)
    if not bool(config.get("enabled")):
        return {}
    variants = [row for row in _safe_list(config.get("variants")) if isinstance(row, dict)]
    if not variants:
        return {}
    bucket = int(sha256(str(recipient or "anonymous").encode("utf-8")).hexdigest()[:8], 16) % 100
    cursor = 0
    fallback = variants[-1]
    for idx, variant in enumerate(variants):
        weight = max(1, min(int(variant.get("weight") or variant.get("traffic") or (100 / max(1, len(variants)))), 100))
        cursor += weight
        if bucket < cursor or idx == len(variants) - 1:
            selected = dict(variant)
            selected["bucket"] = bucket
            return selected
    selected = dict(fallback)
    selected["bucket"] = bucket
    return selected


def _apply_action_variant(trigger: dict[str, Any], action: dict[str, Any], recipient: str) -> tuple[dict[str, Any], dict[str, Any]]:
    selected = _select_ab_variant(trigger.get("ab_test_json"), recipient)
    if not selected:
        return action, {}
    patched = dict(action)
    if selected.get("template_id"):
        patched["template_id"] = selected.get("template_id")
    if selected.get("reply_text"):
        patched["reply_text"] = selected.get("reply_text")
    return patched, {
        "key": selected.get("key") or selected.get("name") or "",
        "bucket": selected.get("bucket"),
        "template_id": selected.get("template_id") or "",
    }


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
        elif ctype in {"crm_stage", "payment_status", "customer_type", "intent", "conversation_field"}:
            ok, info = _condition_conversation_field(conversation, condition)
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


def _record_ab_event(
    conn,
    *,
    tenant_id: str,
    entity_type: str,
    entity_id: str,
    conversation: dict[str, Any],
    variant: dict[str, Any],
    action: dict[str, Any],
    result: dict[str, Any],
    source: str,
) -> None:
    if not variant:
        return
    messages = _safe_list(result.get("messages"))
    first_message = next((item for item in messages if isinstance(item, dict)), {})
    conn.execute(
        text(
            """
            INSERT INTO saas_campaign_ab_events (
                tenant_id, entity_type, entity_id, conversation_id, message_id, outbound_id,
                channel, recipient_external_id, variant_key, template_id, source, outcome, metadata_json
            )
            VALUES (
                CAST(:tenant_id AS uuid), :entity_type, CAST(NULLIF(:entity_id, '') AS uuid),
                CAST(NULLIF(:conversation_id, '') AS uuid), CAST(NULLIF(:message_id, '') AS uuid),
                CAST(NULLIF(:outbound_id, '') AS uuid), :channel, :recipient_external_id,
                :variant_key, CAST(NULLIF(:template_id, '') AS uuid), :source, :outcome,
                CAST(:metadata_json AS jsonb)
            )
            """
        ),
        {
            "tenant_id": tenant_id,
            "entity_type": _clean(entity_type, 40).lower() or "trigger",
            "entity_id": _clean(entity_id, 120),
            "conversation_id": _clean(conversation.get("id"), 120),
            "message_id": _clean(first_message.get("message_id"), 120),
            "outbound_id": _clean(first_message.get("outbound_id"), 120),
            "channel": _clean(conversation.get("channel"), 40).lower() or "whatsapp",
            "recipient_external_id": _clean(conversation.get("external_contact_id") or conversation.get("phone"), 180),
            "variant_key": _clean(variant.get("key") or variant.get("template_id") or variant.get("bucket"), 120),
            "template_id": _clean(action.get("template_id") or variant.get("template_id"), 120),
            "source": _clean(source, 80),
            "outcome": "queued" if result.get("ok") else "failed",
            "metadata_json": _json({"variant": variant, "result": result, "action_type": action.get("type")}),
        },
    )


def _template_message_blocks(template: dict[str, Any], variables: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = _safe_list(template.get("blocks_json"))
    out: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        kind = _norm(block.get("kind") or block.get("type") or "text")
        if kind == "file":
            kind = "document"
        if kind == "text":
            rendered = _render(block.get("text") or block.get("body") or block.get("content"), variables)
            if rendered:
                out.append({"kind": "text", "text": rendered})
            continue
        elif kind in {"image", "video"}:
            rendered = _render(block.get("caption") or "", variables)
            media_id = _clean(block.get("media_id"), 120)
            media_url = _clean(block.get(f"{kind}_url") or block.get("media_url") or block.get("media_link"), 1500)
            if media_id or media_url:
                out.append({"kind": kind, "caption": rendered, "media_id": media_id, "media_url": media_url, "mime_type": _clean(block.get("mime_type") or block.get("content_type"), 120)})
            elif rendered:
                out.append({"kind": "text", "text": rendered})
            continue
        elif kind in {"audio", "document"}:
            rendered = _render(block.get("caption") or "", variables)
            media_id = _clean(block.get("media_id"), 120)
            media_url = _clean(
                block.get("document_url")
                or block.get("file_url")
                or block.get("audio_url")
                or block.get("media_url")
                or block.get("media_link"),
                1500,
            )
            if media_id or media_url:
                out.append(
                    {
                        "kind": kind,
                        "caption": rendered if kind == "document" else "",
                        "media_id": media_id,
                        "media_url": media_url,
                        "filename": _clean(block.get("filename") or block.get("name"), 240),
                        "mime_type": _clean(block.get("mime_type") or block.get("content_type"), 120),
                    }
                )
            elif rendered:
                out.append({"kind": "text", "text": rendered})
            continue
        else:
            rendered = _render(block.get("caption") or block.get("text") or "", variables)
            if rendered:
                out.append({"kind": "text", "text": rendered})
    if out:
        return out
    fallback = _render(template.get("body") or "", variables)
    return [{"kind": "text", "text": fallback}] if fallback else []


def _text_blocks(template: dict[str, Any], variables: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for block in _template_message_blocks(template, variables):
        if block.get("kind") == "text":
            text_value = _clean(block.get("text"), 4000)
        else:
            text_value = _clean(block.get("caption") or block.get("filename") or f"[{block.get('kind') or 'media'}]", 4000)
        if text_value:
            out.append(text_value)
    return out


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


def _queue_outbound_media(
    conn,
    *,
    tenant_id: str,
    conversation: dict[str, Any],
    block: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    kind = _norm(block.get("kind") or "document")
    if kind == "file":
        kind = "document"
    if kind not in {"image", "video", "audio", "document"}:
        return _queue_outbound_text(conn, tenant_id=tenant_id, conversation=conversation, body_text=_clean(block.get("text") or block.get("caption"), 4000), payload=payload)

    media_id = _clean(block.get("media_id"), 120)
    media_url = _clean(block.get("media_url") or block.get("media_link"), 1500)
    body = _clean(block.get("caption"), 4000) if kind in {"image", "video", "document"} else ""
    filename = _clean(block.get("filename"), 240)
    mime_type = _clean(block.get("mime_type"), 120)
    if not media_id and not media_url:
        if body:
            return _queue_outbound_text(conn, tenant_id=tenant_id, conversation=conversation, body_text=body, payload=payload)
        return {"ok": False, "error": "media_required", "message_type": kind}

    ensure_monthly_message_quota(conn, tenant_id, requested=1)
    channel = _clean(conversation.get("channel"), 40) or "whatsapp"
    conversation_id = str(conversation["id"])
    external_id = f"local:trigger:{uuid4().hex}"
    display_text = body or (f"[Documento] {filename}" if kind == "document" and filename else f"[{kind}]")
    message_payload = {
        **payload,
        "local_external_message_id": external_id,
        "message_type": kind,
        "media_id": media_id,
        "media_url": media_url,
        "media_link": media_url,
        "filename": filename,
        "mime_type": mime_type,
    }
    message = conn.execute(
        text(
            """
            INSERT INTO saas_messages (
                tenant_id, conversation_id, channel, external_message_id, direction,
                msg_type, text, media_id, mime_type, payload_json
            )
            VALUES (
                CAST(:tenant_id AS uuid), CAST(:conversation_id AS uuid), :channel, :external_message_id,
                'out', :msg_type, :body_text, :media_id, :mime_type, CAST(:payload_json AS jsonb)
            )
            RETURNING id::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "conversation_id": conversation_id,
            "channel": channel,
            "external_message_id": external_id,
            "msg_type": kind,
            "body_text": display_text,
            "media_id": media_id,
            "mime_type": mime_type,
            "payload_json": _json(message_payload),
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
            "payload_json": _json(message_payload),
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
        {"tenant_id": tenant_id, "conversation_id": conversation_id, "body_text": display_text},
    )
    return {"ok": True, "message_id": message["id"], "outbound_id": outbound["id"], "status": outbound["status"], "message_type": kind}


def _action_send_template(conn, tenant_id: str, conversation: dict[str, Any], trigger: dict[str, Any], action: dict[str, Any], source: str) -> dict[str, Any]:
    template_id = _clean(action.get("template_id"), 120)
    template = _load_template(conn, tenant_id, template_id)
    if not template:
        return {"ok": False, "error": "template_not_found", "template_id": template_id}
    if _norm(template.get("status")) not in {"draft", "approved"}:
        return {"ok": False, "error": "template_not_sendable", "template_id": template_id, "status": template.get("status") or ""}
    variables = {**_safe_dict(template.get("params_json")), **_conversation_vars(conversation), **_safe_dict(action.get("overrides"))}
    blocks = _template_message_blocks(template, variables)
    if not blocks:
        return {"ok": False, "error": "template_without_blocks", "template_id": template_id}
    queued = []
    for idx, block in enumerate(blocks):
        block_payload = {
            "source": source,
            "trigger_id": trigger["id"],
            "template_id": template_id,
            "template_name": template.get("name") or "",
            "block_index": idx,
            "template_block_kind": block.get("kind") or "text",
        }
        if block.get("kind") == "text":
            queued.append(
                _queue_outbound_text(
                    conn,
                    tenant_id=tenant_id,
                    conversation=conversation,
                    body_text=_clean(block.get("text"), 4000),
                    payload=block_payload,
                )
            )
        else:
            queued.append(
                _queue_outbound_media(
                    conn,
                    tenant_id=tenant_id,
                    conversation=conversation,
                    block=block,
                    payload=block_payload,
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
    recipient = _clean(conversation.get("external_contact_id") or conversation.get("phone"), 180)
    for idx, action in enumerate(actions):
        action, variant = _apply_action_variant(trigger, action, recipient)
        atype = _norm(action.get("type"))
        action_source = "trigger"
        try:
            if atype == "send_template":
                result = _action_send_template(conn, tenant_id, conversation, trigger, action, "trigger")
                queued_total += int(result.get("queued") or 0)
            elif atype == "reply_comment":
                mode = _norm(action.get("mode") or ("ai" if action.get("use_ai") else "text"))
                action_source = "trigger_comment"
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
                action_source = "trigger_scheduled"
                result = _action_schedule_message(conn, tenant_id, conversation, trigger, action)
            else:
                result = {"ok": False, "error": "unknown_action_type"}
        except Exception as exc:
            result = {"ok": False, "error": str(exc)[:900]}
        if variant:
            _record_ab_event(
                conn,
                tenant_id=tenant_id,
                entity_type="trigger",
                entity_id=trigger.get("id") or "",
                conversation=conversation,
                variant=variant,
                action=action,
                result=result,
                source=action_source,
            )
        if result.get("ok") is not True:
            failed += 1
        results.append({"index": idx, "type": atype or "unknown", "ok": result.get("ok") is True, "variant": variant, "result": result})
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
                   block_ai, stop_on_match, only_when_no_takeover, quiet_hours_json, ab_test_json, version_number
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
    global_quiet_blocked, global_quiet_info = _campaign_quiet_hours_blocked(conn, tenant_id, channel, "trigger")

    for row in triggers:
        trigger = dict(row)
        if not _event_matches(trigger, event_kind):
            continue
        if global_quiet_blocked:
            details.append({"trigger_id": trigger["id"], "name": trigger.get("name"), "skipped": "global_quiet_hours", "quiet_hours": global_quiet_info})
            continue
        if bool(trigger.get("only_when_no_takeover")) and takeover:
            details.append({"trigger_id": trigger["id"], "name": trigger.get("name"), "skipped": "takeover_on"})
            continue
        quiet_blocked, quiet_info = _quiet_hours_blocked(trigger.get("quiet_hours_json"))
        if quiet_blocked:
            details.append({"trigger_id": trigger["id"], "name": trigger.get("name"), "skipped": "quiet_hours", "quiet_hours": quiet_info})
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
        details.append({
            "trigger_id": trigger["id"],
            "name": trigger.get("name"),
            "matched": True,
            "status": status,
            "sent": sent,
            "block_ai": bool(trigger.get("block_ai")) and status == "ok",
            "conditions": condition_evals,
            "actions": action_result.get("actions") or [],
        })
        if bool(trigger.get("stop_on_match")):
            break

    return {"ok": True, "matched": matched, "sent": sent, "details": details}


def simulate_trigger_draft(
    conn,
    *,
    tenant_id: str,
    trigger: dict[str, Any],
    conversation_id: str = "",
    event_kind: str = "received",
    message_text: str = "",
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    set_tenant_context(conn, tenant_id)
    conversation = _load_context(conn, tenant_id, conversation_id) if conversation_id else None
    context = context or {}
    if not conversation:
        conversation = {
            "id": "00000000-0000-0000-0000-000000000000",
            "tenant_id": tenant_id,
            "channel": context.get("channel") or trigger.get("channel") or "whatsapp",
            "external_contact_id": context.get("customer_phone") or "+573001112233",
            "phone": context.get("customer_phone") or "+573001112233",
            "display_name": context.get("customer_name") or "Cliente demo",
            "first_name": str(context.get("customer_name") or "Cliente").split(" ", 1)[0],
            "last_name": "",
            "city": context.get("city") or "",
            "customer_type": context.get("customer_type") or "",
            "interests": context.get("interests") or "",
            "takeover": bool(context.get("takeover")),
            "tags": context.get("tags") or "",
            "notes": "",
            "payment_status": context.get("payment_status") or "",
            "crm_stage": context.get("crm_stage") or "",
            "intent": context.get("intent") or "",
            "profile_json": {},
            "message_id": "",
            "message_text": message_text or context.get("message_text") or "",
            "msg_type": "comment" if _norm(event_kind) == "comment" else "text",
            "direction": "in",
        }
    else:
        conversation["message_text"] = message_text or conversation.get("message_text") or ""

    recipient = _clean(conversation.get("external_contact_id") or conversation.get("phone"), 180)
    checks: list[dict[str, Any]] = []
    event_ok = _event_matches(trigger, event_kind)
    checks.append({"code": "event_match", "ok": bool(event_ok), "label": "Evento compatible", "details": {"event_kind": event_kind}})
    global_quiet_blocked, global_quiet_info = _campaign_quiet_hours_blocked(conn, tenant_id, conversation.get("channel") or trigger.get("channel") or "whatsapp", "trigger")
    checks.append({"code": "global_quiet_hours", "ok": not global_quiet_blocked, "label": "Fuera de quiet hours globales", "details": global_quiet_info})
    quiet_blocked, quiet_info = _quiet_hours_blocked(trigger.get("quiet_hours_json"))
    checks.append({"code": "quiet_hours", "ok": not quiet_blocked, "label": "Fuera de quiet hours", "details": quiet_info})
    takeover_blocked = bool(trigger.get("only_when_no_takeover")) and bool(conversation.get("takeover"))
    checks.append({"code": "takeover", "ok": not takeover_blocked, "label": "Takeover permite automatizar", "details": {"takeover": bool(conversation.get("takeover"))}})
    cooldown_blocked = False
    if conversation_id and trigger.get("id"):
        cooldown_blocked = _is_in_cooldown(conn, tenant_id, trigger["id"], recipient, int(trigger.get("cooldown_minutes") or 0))
    checks.append({"code": "cooldown", "ok": not cooldown_blocked, "label": "Cooldown disponible", "details": {"checked": bool(conversation_id and trigger.get("id"))}})

    conditions_ok, condition_evals = _evaluate_conditions(conn, tenant_id, conversation, conversation.get("message_text") or "", trigger.get("conditions_json"))
    checks.append({"code": "conditions", "ok": bool(conditions_ok), "label": "Condiciones cumplen", "details": {"items": condition_evals}})

    action_previews = []
    for idx, raw_action in enumerate(_actions_payload(trigger.get("actions_json") or trigger.get("action_json"))):
        action, variant = _apply_action_variant(trigger, raw_action, recipient)
        atype = _norm(action.get("type"))
        preview: dict[str, Any] = {"index": idx, "type": atype or "unknown", "variant": variant}
        if atype in {"send_template", "schedule_message"}:
            template_id = _clean(action.get("template_id"), 120)
            template = _load_template(conn, tenant_id, template_id)
            preview.update({
                "template_id": template_id,
                "template_found": bool(template),
                "template_status": (template or {}).get("status") or "",
                "would_queue": len(_template_message_blocks(template, {**_safe_dict((template or {}).get("params_json")), **_conversation_vars(conversation)})) if template else 0,
            })
        elif atype == "reply_comment":
            body = action.get("reply_text") or action.get("text") or action.get("ai_prompt") or ""
            preview.update({"mode": action.get("mode") or ("ai" if action.get("use_ai") else "text"), "sample": _render(body, _conversation_vars(conversation))[:500]})
        else:
            preview.update({"details": {key: value for key, value in action.items() if key != "type"}})
        action_previews.append(preview)

    ready = all(item["ok"] for item in checks)
    return {
        "ok": True,
        "ready": bool(ready),
        "matched": bool(event_ok and not global_quiet_blocked and not quiet_blocked and not takeover_blocked and not cooldown_blocked and conditions_ok),
        "block_ai": bool(trigger.get("block_ai")) and bool(conditions_ok),
        "checks": checks,
        "conditions": condition_evals,
        "actions": action_previews,
        "conversation": {
            "id": conversation.get("id"),
            "channel": conversation.get("channel"),
            "display_name": conversation.get("display_name"),
            "recipient": recipient,
        },
    }


def process_due_scheduled_trigger_messages(limit: int = 50, tenant_id: str | None = None) -> dict[str, int]:
    stats = {"picked": 0, "queued": 0, "failed": 0, "skipped": 0}
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
            quiet_blocked, quiet_info = _campaign_quiet_hours_blocked(conn, tenant, conversation.get("channel") or "whatsapp", "trigger")
            if quiet_blocked:
                conn.execute(
                    text(
                        """
                        UPDATE saas_trigger_scheduled_messages
                        SET status = 'pending',
                            run_at = NOW() + INTERVAL '30 minutes',
                            last_error = :error,
                            updated_at = NOW()
                        WHERE id = CAST(:id AS uuid)
                        """
                    ),
                    {"id": row["id"], "error": _clean(f"global_quiet_hours:{quiet_info}", 900)},
                )
                stats["skipped"] += 1
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
