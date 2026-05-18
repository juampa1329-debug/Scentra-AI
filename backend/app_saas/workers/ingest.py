from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from app_saas.ai_agent.service import schedule_conversation_ai
from app_saas.db import db_session, set_tenant_context
from app_saas.workers.triggers import execute_triggers_for_message


@dataclass
class NormalizedMessage:
    channel: str
    external_contact_id: str
    external_message_id: str
    direction: str
    msg_type: str
    text: str
    media_id: str = ""
    mime_type: str = ""
    display_name: str = ""


@dataclass
class NormalizedStatus:
    channel: str
    provider_message_id: str
    status: str
    timestamp: str = ""
    recipient_id: str = ""
    error: str = ""
    payload: dict[str, Any] | None = None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _clean(value: Any, limit: int = 1000) -> str:
    return str(value or "").strip()[:limit]


def _message_text(message: dict[str, Any], msg_type: str) -> str:
    if msg_type == "text":
        return _clean(_as_dict(message.get("text")).get("body"), 4000)
    if msg_type in {"image", "video", "document", "audio"}:
        payload = _as_dict(message.get(msg_type))
        return _clean(payload.get("caption") or f"[{msg_type}]", 4000)
    if message.get("button"):
        return _clean(_as_dict(message.get("button")).get("text"), 4000)
    if message.get("interactive"):
        interactive = _as_dict(message.get("interactive"))
        button_reply = _as_dict(interactive.get("button_reply"))
        list_reply = _as_dict(interactive.get("list_reply"))
        return _clean(button_reply.get("title") or list_reply.get("title") or "[interactive]", 4000)
    return _clean(message.get("body") or message.get("message") or f"[{msg_type}]", 4000)


def _media_fields(message: dict[str, Any], msg_type: str) -> tuple[str, str]:
    if msg_type not in {"image", "video", "document", "audio"}:
        return "", ""
    payload = _as_dict(message.get(msg_type))
    return _clean(payload.get("id"), 240), _clean(payload.get("mime_type"), 240)


def _contact_name(value: dict[str, Any], sender: str) -> str:
    contacts = _as_list(value.get("contacts"))
    for item in contacts:
        contact = _as_dict(item)
        if _clean(contact.get("wa_id")) and _clean(contact.get("wa_id")) != sender:
            continue
        profile = _as_dict(contact.get("profile"))
        name = _clean(profile.get("name"), 180)
        if name:
            return name
    return ""


def _status_timestamp(value: Any) -> str:
    raw = _clean(value, 40)
    if not raw:
        return ""
    if raw.isdigit():
        try:
            return datetime.fromtimestamp(int(raw), tz=timezone.utc).isoformat()
        except Exception:
            return raw
    return raw


def _status_error(status_payload: dict[str, Any]) -> str:
    errors = _as_list(status_payload.get("errors"))
    if not errors:
        return ""
    first = _as_dict(errors[0])
    return _clean(first.get("message") or first.get("title") or first.get("code") or errors[0], 500)


def _normalize_whatsapp_payload(provider: str, payload: dict[str, Any], fallback_event_id: str) -> list[NormalizedMessage]:
    out: list[NormalizedMessage] = []
    for entry in _as_list(payload.get("entry")):
        for change in _as_list(_as_dict(entry).get("changes")):
            value = _as_dict(_as_dict(change).get("value"))
            for message in _as_list(value.get("messages")):
                msg = _as_dict(message)
                sender = _clean(msg.get("from"), 120)
                if not sender:
                    continue
                msg_type = _clean(msg.get("type") or "text", 40).lower()
                media_id, mime_type = _media_fields(msg, msg_type)
                out.append(
                    NormalizedMessage(
                        channel="whatsapp" if provider in {"whatsapp", "meta"} else provider,
                        external_contact_id=sender,
                        external_message_id=_clean(msg.get("id"), 240) or fallback_event_id,
                        direction="in",
                        msg_type=msg_type,
                        text=_message_text(msg, msg_type),
                        media_id=media_id,
                        mime_type=mime_type,
                        display_name=_contact_name(value, sender),
                    )
                )
    return out


def _normalize_whatsapp_statuses(provider: str, payload: dict[str, Any]) -> list[NormalizedStatus]:
    out: list[NormalizedStatus] = []
    for entry in _as_list(payload.get("entry")):
        for change in _as_list(_as_dict(entry).get("changes")):
            value = _as_dict(_as_dict(change).get("value"))
            for status_payload in _as_list(value.get("statuses")):
                item = _as_dict(status_payload)
                provider_message_id = _clean(item.get("id"), 240)
                if not provider_message_id:
                    continue
                out.append(
                    NormalizedStatus(
                        channel="whatsapp" if provider in {"whatsapp", "meta"} else provider,
                        provider_message_id=provider_message_id,
                        status=_clean(item.get("status") or "sent", 40).lower(),
                        timestamp=_status_timestamp(item.get("timestamp")),
                        recipient_id=_clean(item.get("recipient_id"), 120),
                        error=_status_error(item),
                        payload=item,
                    )
                )
    return out


def _normalize_instagram_payload(payload: dict[str, Any], fallback_event_id: str) -> list[NormalizedMessage]:
    out: list[NormalizedMessage] = []
    for entry in _as_list(payload.get("entry")):
        entry_dict = _as_dict(entry)
        for event in _as_list(entry_dict.get("messaging")):
            item = _as_dict(event)
            sender = _clean(_as_dict(item.get("sender")).get("id"), 120)
            if not sender:
                continue
            message = _as_dict(item.get("message"))
            if bool(message.get("is_echo")):
                continue
            postback = _as_dict(item.get("postback"))
            attachments = _as_list(message.get("attachments"))
            msg_type = "text"
            text_value = _clean(message.get("text"), 4000)
            media_id = ""
            mime_type = ""
            if not text_value and postback:
                msg_type = "postback"
                text_value = _clean(postback.get("title") or postback.get("payload") or "[postback]", 4000)
            if attachments:
                first = _as_dict(attachments[0])
                msg_type = _clean(first.get("type") or "attachment", 40).lower()
                payload_value = _as_dict(first.get("payload"))
                media_id = _clean(payload_value.get("url") or payload_value.get("id"), 1000)
                text_value = text_value or f"[{msg_type}]"
            out.append(
                NormalizedMessage(
                    channel="instagram",
                    external_contact_id=sender,
                    external_message_id=_clean(message.get("mid") or item.get("timestamp"), 240) or fallback_event_id,
                    direction="in",
                    msg_type=msg_type,
                    text=text_value or "[instagram]",
                    media_id=media_id,
                    mime_type=mime_type,
                    display_name="",
                )
            )

        for change in _as_list(entry_dict.get("changes")):
            change_dict = _as_dict(change)
            field = _clean(change_dict.get("field"), 60).lower()
            value = _as_dict(change_dict.get("value"))
            if field not in {"comments", "mentions"}:
                continue
            sender_info = _as_dict(value.get("from"))
            sender = _clean(sender_info.get("id") or value.get("sender_id") or value.get("user_id"), 120)
            if not sender:
                continue
            text_value = _clean(value.get("text") or value.get("message") or f"[{field}]", 4000)
            out.append(
                NormalizedMessage(
                    channel="instagram",
                    external_contact_id=sender,
                    external_message_id=_clean(value.get("id") or value.get("comment_id") or value.get("media_id"), 240) or fallback_event_id,
                    direction="in",
                    msg_type=field[:-1] if field.endswith("s") else field,
                    text=text_value,
                    display_name=_clean(sender_info.get("username") or sender_info.get("name"), 180),
                )
            )
    return out


def _normalize_generic_payload(provider: str, payload: dict[str, Any], fallback_event_id: str) -> list[NormalizedMessage]:
    sender = _clean(
        payload.get("from")
        or payload.get("phone")
        or payload.get("sender")
        or payload.get("contact_id")
        or payload.get("customer_id"),
        120,
    )
    if not sender:
        return []
    text_value = _clean(payload.get("text") or payload.get("body") or payload.get("message"), 4000)
    msg_type = _clean(payload.get("type") or "text", 40).lower()
    return [
        NormalizedMessage(
            channel=provider,
            external_contact_id=sender,
            external_message_id=_clean(payload.get("id") or payload.get("message_id"), 240) or fallback_event_id,
            direction="in",
            msg_type=msg_type,
            text=text_value or f"[{msg_type}]",
            display_name=_clean(payload.get("name") or payload.get("display_name"), 180),
        )
    ]


def normalize_event(provider: str, payload: dict[str, Any], fallback_event_id: str) -> list[NormalizedMessage]:
    provider_clean = _clean(provider, 50).lower()
    if provider_clean == "instagram":
        messages = _normalize_instagram_payload(payload, fallback_event_id)
        if messages:
            return messages
    messages = _normalize_whatsapp_payload(provider_clean, payload, fallback_event_id)
    if messages:
        return messages
    return _normalize_generic_payload(provider_clean, payload, fallback_event_id)


def normalize_status_events(provider: str, payload: dict[str, Any]) -> list[NormalizedStatus]:
    provider_clean = _clean(provider, 50).lower()
    if provider_clean in {"whatsapp", "meta", "facebook", "instagram"}:
        return _normalize_whatsapp_statuses(provider_clean, payload)
    provider_message_id = _clean(payload.get("message_id") or payload.get("wa_message_id") or payload.get("id"), 240)
    status = _clean(payload.get("status"), 40).lower()
    if provider_message_id and status in {"sent", "delivered", "read", "failed"}:
        return [
            NormalizedStatus(
                channel=provider_clean,
                provider_message_id=provider_message_id,
                status=status,
                timestamp=_status_timestamp(payload.get("timestamp")),
                recipient_id=_clean(payload.get("recipient_id") or payload.get("to"), 120),
                error=_status_error(payload),
                payload=payload,
            )
        ]
    return []


def _period_yyyymm() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m")


def _upsert_message(conn, tenant_id: str, event_id: str, payload: dict[str, Any], message: NormalizedMessage) -> dict[str, Any]:
    conversation = conn.execute(
        text(
            """
            INSERT INTO saas_conversations (
                tenant_id,
                channel,
                external_contact_id,
                phone,
                display_name,
                last_message_text,
                last_message_at,
                unread_count,
                updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid),
                :channel,
                :external_contact_id,
                :phone,
                :display_name,
                :last_message_text,
                NOW(),
                1,
                NOW()
            )
            ON CONFLICT (tenant_id, channel, external_contact_id)
            DO UPDATE SET
                phone = COALESCE(NULLIF(EXCLUDED.phone, ''), saas_conversations.phone),
                display_name = COALESCE(NULLIF(EXCLUDED.display_name, ''), saas_conversations.display_name),
                last_message_text = EXCLUDED.last_message_text,
                last_message_at = NOW(),
                unread_count = saas_conversations.unread_count + 1,
                updated_at = NOW()
            RETURNING id::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "channel": message.channel,
            "external_contact_id": message.external_contact_id,
            "phone": message.external_contact_id if message.channel == "whatsapp" else "",
            "display_name": message.display_name,
            "last_message_text": message.text,
        },
    ).mappings().first()

    result = conn.execute(
        text(
            """
            INSERT INTO saas_messages (
                tenant_id,
                conversation_id,
                channel,
                external_message_id,
                direction,
                msg_type,
                text,
                media_id,
                mime_type,
                payload_json
            )
            VALUES (
                CAST(:tenant_id AS uuid),
                CAST(:conversation_id AS uuid),
                :channel,
                :external_message_id,
                :direction,
                :msg_type,
                :text,
                :media_id,
                :mime_type,
                CAST(:payload_json AS jsonb)
            )
            ON CONFLICT (tenant_id, channel, external_message_id) DO NOTHING
            RETURNING id::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "conversation_id": conversation["id"],
            "channel": message.channel,
            "external_message_id": message.external_message_id or event_id,
            "direction": message.direction,
            "msg_type": message.msg_type,
            "text": message.text,
            "media_id": message.media_id,
            "mime_type": message.mime_type,
            "payload_json": json.dumps(payload),
        },
    ).mappings().first()
    return {
        "inserted": bool(result),
        "conversation_id": conversation["id"],
        "message_id": result["id"] if result else "",
    }


def _apply_delivery_status(conn, tenant_id: str, status_event: NormalizedStatus) -> int:
    status = status_event.status if status_event.status in {"sent", "delivered", "read", "failed"} else "sent"
    patch = {
        "delivery_status": status,
        "delivery_timestamp": status_event.timestamp,
        "delivery_error": status_event.error,
        "delivery_provider_payload": status_event.payload or {},
    }
    rows = conn.execute(
        text(
            """
            WITH outbound_matches AS (
                SELECT message_id
                FROM saas_outbound_messages
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND message_id IS NOT NULL
                  AND (
                    payload_json->'provider_response'->>'provider_message_id' = :provider_message_id
                    OR payload_json->'provider_response'->>'id' = :provider_message_id
                    OR payload_json->'provider_response'->'messages'->0->>'id' = :provider_message_id
                  )
            ),
            updated AS (
                UPDATE saas_messages
                SET payload_json = payload_json || CAST(:patch_json AS jsonb)
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND direction = 'out'
                  AND (
                    payload_json->>'provider_message_id' = :provider_message_id
                    OR external_message_id = :provider_message_id
                    OR id IN (SELECT message_id FROM outbound_matches)
                  )
                RETURNING id
            )
            SELECT id::text FROM updated
            """
        ),
        {
            "tenant_id": tenant_id,
            "provider_message_id": status_event.provider_message_id,
            "patch_json": json.dumps(patch),
        },
    ).mappings().all()
    message_ids = [str(row["id"]) for row in rows]

    conn.execute(
        text(
            """
            UPDATE saas_outbound_messages
            SET status = :status,
                error = CASE WHEN :status = 'failed' THEN :error ELSE error END,
                payload_json = payload_json || CAST(:patch_json AS jsonb),
                updated_at = NOW()
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND (
                message_id = ANY(CAST(:message_ids AS uuid[]))
                OR payload_json->'provider_response'->>'provider_message_id' = :provider_message_id
                OR payload_json->'provider_response'->>'id' = :provider_message_id
                OR payload_json->'provider_response'->'messages'->0->>'id' = :provider_message_id
              )
            """
        ),
        {
            "tenant_id": tenant_id,
            "status": status,
            "error": status_event.error[:500],
            "provider_message_id": status_event.provider_message_id,
            "message_ids": message_ids,
            "patch_json": json.dumps(patch),
        },
    )
    conn.execute(
        text(
            """
            UPDATE saas_broadcast_recipients
            SET status = :status,
                error = CASE WHEN :status = 'failed' THEN :error ELSE error END,
                updated_at = NOW()
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND (
                provider_message_id = :provider_message_id
                OR outbound_id IN (
                    SELECT id
                    FROM saas_outbound_messages
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND (
                        message_id = ANY(CAST(:message_ids AS uuid[]))
                        OR payload_json->'provider_response'->>'provider_message_id' = :provider_message_id
                        OR payload_json->'provider_response'->>'id' = :provider_message_id
                        OR payload_json->'provider_response'->'messages'->0->>'id' = :provider_message_id
                      )
                )
              )
            """
        ),
        {
            "tenant_id": tenant_id,
            "status": status,
            "error": status_event.error[:500],
            "provider_message_id": status_event.provider_message_id,
            "message_ids": message_ids,
        },
    )
    return len(message_ids)


def process_due_webhook_events(limit: int = 25, tenant_id: str | None = None) -> dict[str, int]:
    processed = 0
    ignored = 0
    errors = 0
    messages_inserted = 0
    statuses_updated = 0
    triggers_matched = 0
    trigger_errors = 0
    ai_replies_queued = 0
    ai_skipped = 0

    with db_session() as conn:
        filters = ["status = 'received'"]
        params: dict[str, Any] = {"limit": int(max(1, min(limit, 200)))}
        if tenant_id:
            filters.append("tenant_id = CAST(:tenant_id AS uuid)")
            params["tenant_id"] = tenant_id

        rows = conn.execute(
            text(
                f"""
                SELECT id::text, tenant_id::text, provider, event_id, payload_json
                FROM saas_webhook_events
                WHERE {" AND ".join(filters)}
                ORDER BY received_at ASC
                LIMIT :limit
                FOR UPDATE SKIP LOCKED
                """
            ),
            params,
        ).mappings().all()

        for row in rows:
            event_id = row["id"]
            tenant_id = row["tenant_id"]
            provider = row["provider"]
            source_event_id = row["event_id"]
            payload = _as_dict(row["payload_json"])
            set_tenant_context(conn, tenant_id)

            try:
                messages = normalize_event(provider, payload, source_event_id)
                statuses = normalize_status_events(provider, payload)
                if not messages and not statuses:
                    conn.execute(
                        text(
                            """
                            UPDATE saas_webhook_events
                            SET status = 'ignored', processed_at = NOW(), error = 'no_messages_found'
                            WHERE id = CAST(:id AS uuid)
                            """
                        ),
                        {"id": event_id},
                    )
                    ignored += 1
                    continue

                inserted_for_event = 0
                updated_statuses_for_event = 0
                for message in messages:
                    saved = _upsert_message(conn, tenant_id, source_event_id, payload, message)
                    if saved["inserted"]:
                        inserted_for_event += 1
                        trigger_result = execute_triggers_for_message(
                            conn,
                            tenant_id=tenant_id,
                            conversation_id=saved["conversation_id"],
                            message_id=saved["message_id"],
                            event_kind="received",
                        )
                        if trigger_result.get("matched"):
                            triggers_matched += 1
                        if trigger_result.get("ok") is not True:
                            trigger_errors += 1
                        block_ai = any(bool(item.get("block_ai")) for item in trigger_result.get("details", []) if isinstance(item, dict))
                        if block_ai:
                            ai_skipped += 1
                        else:
                            ai_result = schedule_conversation_ai(
                                conn,
                                tenant_id=tenant_id,
                                conversation_id=saved["conversation_id"],
                                message_id=saved["message_id"],
                            )
                            if ai_result.get("ok"):
                                ai_replies_queued += 1
                            else:
                                ai_skipped += 1
                for status_event in statuses:
                    updated_statuses_for_event += _apply_delivery_status(conn, tenant_id, status_event)

                conn.execute(
                    text(
                        """
                        UPDATE saas_webhook_events
                        SET status = 'processed', processed_at = NOW(), error = ''
                        WHERE id = CAST(:id AS uuid)
                        """
                    ),
                    {"id": event_id},
                )

                if inserted_for_event:
                    conn.execute(
                        text(
                            """
                            INSERT INTO saas_usage_counters (tenant_id, metric_code, period_yyyymm, metric_value)
                            VALUES (CAST(:tenant_id AS uuid), 'messages_in', :period, :count)
                            ON CONFLICT (tenant_id, metric_code, period_yyyymm)
                            DO UPDATE SET
                                metric_value = saas_usage_counters.metric_value + EXCLUDED.metric_value,
                                updated_at = NOW()
                            """
                        ),
                        {"tenant_id": tenant_id, "period": _period_yyyymm(), "count": inserted_for_event},
                    )

                processed += 1
                messages_inserted += inserted_for_event
                statuses_updated += updated_statuses_for_event
            except Exception as exc:
                conn.execute(
                    text(
                        """
                        UPDATE saas_webhook_events
                        SET status = 'error', processed_at = NOW(), error = :error
                        WHERE id = CAST(:id AS uuid)
                        """
                    ),
                    {"id": event_id, "error": str(exc)[:900]},
                )
                errors += 1

    return {
        "processed": processed,
        "ignored": ignored,
        "errors": errors,
        "messages_inserted": messages_inserted,
        "statuses_updated": statuses_updated,
        "triggers_matched": triggers_matched,
        "trigger_errors": trigger_errors,
        "ai_replies_queued": ai_replies_queued,
        "ai_skipped": ai_skipped,
    }
