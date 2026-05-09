from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

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
    messages = _normalize_whatsapp_payload(provider_clean, payload, fallback_event_id)
    if messages:
        return messages
    return _normalize_generic_payload(provider_clean, payload, fallback_event_id)


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


def process_due_webhook_events(limit: int = 25, tenant_id: str | None = None) -> dict[str, int]:
    processed = 0
    ignored = 0
    errors = 0
    messages_inserted = 0
    triggers_matched = 0
    trigger_errors = 0

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
                if not messages:
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
        "triggers_matched": triggers_matched,
        "trigger_errors": trigger_errors,
    }
