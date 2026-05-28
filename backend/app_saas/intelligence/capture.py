from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.engine import Connection

from app_saas.intelligence.service import record_event

logger = logging.getLogger(__name__)


def record_inline_event(
    conn: Connection,
    tenant_id: str,
    *,
    event_type: str,
    source: str,
    channel: str = "",
    entity_type: str = "",
    entity_id: str = "",
    conversation_id: str = "",
    customer_key: str = "",
    occurred_at: str = "",
    payload_json: dict[str, Any] | None = None,
    correlation_id: str = "",
    replay_key: str = "",
) -> dict[str, Any] | None:
    try:
        with conn.begin_nested():
            return record_event(
                conn,
                tenant_id,
                {
                    "event_type": event_type,
                    "source": source,
                    "channel": channel,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "conversation_id": conversation_id,
                    "customer_key": customer_key,
                    "occurred_at": occurred_at,
                    "payload_json": payload_json or {},
                    "correlation_id": correlation_id,
                    "replay_key": replay_key,
                },
            )
    except Exception as exc:  # pragma: no cover - defensive telemetry path
        logger.warning(
            "intelligence_inline_event_failed tenant_id=%s event_type=%s replay_key=%s error=%s",
            str(tenant_id)[:80],
            str(event_type)[:160],
            str(replay_key)[:240],
            str(exc)[:300],
        )
        return None
