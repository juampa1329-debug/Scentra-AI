from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app_saas.config import settings
from app_saas.db import db_session, set_tenant_context
from app_saas.integrations.router import _refresh_meta_social_page_token


def _safe_positive_int(value: Any, default: int, *, minimum: int = 1, maximum: int = 10_000) -> int:
    try:
        parsed = int(value or default)
    except Exception:
        parsed = default
    return max(minimum, min(parsed, maximum))


def process_due_meta_token_refreshes(limit: int | None = None) -> dict[str, Any]:
    """Refresh Facebook/Instagram page tokens on a throttled schedule.

    The worker stores the last attempt in saas_integrations.config_json->last_token_refresh,
    so the embedded API worker can run every few seconds without hammering Meta.
    """
    if not bool(settings.saas_meta_token_refresh_enabled):
        return {"picked": 0, "refreshed": 0, "skipped": "disabled"}

    batch_size = _safe_positive_int(
        limit or settings.saas_meta_token_refresh_batch_size,
        int(settings.saas_meta_token_refresh_batch_size or 10),
        minimum=1,
        maximum=100,
    )
    interval_hours = _safe_positive_int(
        settings.saas_meta_token_refresh_interval_hours,
        12,
        minimum=1,
        maximum=720,
    )
    with db_session() as conn:
        rows = conn.execute(
            text(
                """
                SELECT tenant_id::text, id::text, channel, config_json
                FROM saas_integrations
                WHERE provider = 'meta'
                  AND channel IN ('instagram', 'facebook')
                  AND status = 'connected'
                  AND LOWER(COALESCE(config_json->>'dispatch_mode', '')) NOT IN ('stub', 'local', 'disabled')
                  AND (
                    config_json->'last_token_refresh' IS NULL
                    OR COALESCE(config_json->'last_token_refresh'->>'checked_at', '') = ''
                    OR NULLIF(config_json->'last_token_refresh'->>'checked_at', '')::timestamptz <= NOW() - (:interval_hours * INTERVAL '1 hour')
                    OR (
                      COALESCE(config_json->'last_token_refresh'->>'ok', 'false') = 'false'
                      AND NULLIF(config_json->'last_token_refresh'->>'checked_at', '')::timestamptz <= NOW() - INTERVAL '1 hour'
                    )
                  )
                ORDER BY
                  COALESCE(NULLIF(config_json->'last_token_refresh'->>'checked_at', '')::timestamptz, '1970-01-01'::timestamptz) ASC,
                  updated_at ASC
                LIMIT :limit
                """
            ),
            {"interval_hours": interval_hours, "limit": batch_size},
        ).mappings().all()

        refreshed = 0
        failed = 0
        manual = 0
        errors: list[dict[str, str]] = []
        for row in rows:
            tenant_id = str(row["tenant_id"])
            channel = str(row["channel"] or "").lower()
            try:
                set_tenant_context(conn, tenant_id)
                result = _refresh_meta_social_page_token(conn, tenant_id=tenant_id, channel=channel)
                if result.get("ok"):
                    refreshed += 1
                elif result.get("status") in {"manual_page_token_only", "missing_app_credentials"}:
                    manual += 1
                else:
                    failed += 1
                    errors.append({"tenant_id": tenant_id, "channel": channel, "status": str(result.get("status") or "failed")[:120]})
            except Exception as exc:
                failed += 1
                errors.append({"tenant_id": tenant_id, "channel": channel, "error": str(exc)[:300]})

        return {
            "picked": len(rows),
            "refreshed": refreshed,
            "manual_or_unrefreshable": manual,
            "failed": failed,
            "interval_hours": interval_hours,
            "errors": errors[:5],
        }
