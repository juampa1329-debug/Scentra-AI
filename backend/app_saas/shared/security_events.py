from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app_saas.config import settings
from app_saas.shared.request_meta import client_ip, user_agent


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def ensure_security_event_table(conn: Connection) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_security_events (
                id uuid PRIMARY KEY,
                tenant_id uuid NULL,
                user_id uuid NULL,
                event_type text NOT NULL,
                rate_limit_key text NOT NULL DEFAULT '',
                principal text NOT NULL DEFAULT '',
                ip_address text NOT NULL DEFAULT '',
                user_agent text NOT NULL DEFAULT '',
                status text NOT NULL DEFAULT 'attempt',
                reason text NOT NULL DEFAULT '',
                details_json jsonb NOT NULL DEFAULT '{}'::jsonb,
                created_at timestamptz NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_security_events_rate
            ON saas_security_events (event_type, rate_limit_key, created_at DESC)
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_security_events_created
            ON saas_security_events (created_at DESC)
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_security_events_principal_created
            ON saas_security_events (event_type, principal, created_at DESC)
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_security_events_ip_created
            ON saas_security_events (event_type, ip_address, created_at DESC)
            """
        )
    )


def rate_limit_key(*, action: str, principal: str = "", request: Request | None = None) -> str:
    clean_action = str(action or "security").strip().lower()
    clean_principal = str(principal or "anonymous").strip().lower()[:240]
    return f"{clean_action}:{client_ip(request)}:{clean_principal}"


def record_security_event(
    conn: Connection,
    *,
    event_type: str,
    status: str,
    request: Request | None = None,
    principal: str = "",
    rate_key: str = "",
    tenant_id: str | None = None,
    user_id: str | None = None,
    reason: str = "",
    details: dict[str, Any] | None = None,
) -> None:
    ensure_security_event_table(conn)
    conn.execute(
        text(
            """
            INSERT INTO saas_security_events (
                id, tenant_id, user_id, event_type, rate_limit_key, principal,
                ip_address, user_agent, status, reason, details_json
            )
            VALUES (
                CAST(:id AS uuid),
                CAST(NULLIF(:tenant_id, '') AS uuid),
                CAST(NULLIF(:user_id, '') AS uuid),
                :event_type,
                :rate_limit_key,
                :principal,
                :ip_address,
                :user_agent,
                :status,
                :reason,
                CAST(:details_json AS jsonb)
            )
            """
        ),
        {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id or "",
            "user_id": user_id or "",
            "event_type": str(event_type or "security.event")[:120],
            "rate_limit_key": str(rate_key or "")[:320],
            "principal": str(principal or "")[:240],
            "ip_address": client_ip(request)[:120],
            "user_agent": user_agent(request),
            "status": str(status or "attempt")[:40],
            "reason": str(reason or "")[:240],
            "details_json": _json(details or {}),
        },
    )


def _record_security_event_isolated(
    *,
    event_type: str,
    status: str,
    request: Request | None = None,
    principal: str = "",
    rate_key: str = "",
    tenant_id: str | None = None,
    user_id: str | None = None,
    reason: str = "",
    details: dict[str, Any] | None = None,
) -> None:
    from app_saas.db import get_engine

    try:
        with get_engine().begin() as event_conn:
            record_security_event(
                event_conn,
                event_type=event_type,
                status=status,
                request=request,
                principal=principal,
                rate_key=rate_key,
                tenant_id=tenant_id,
                user_id=user_id,
                reason=reason,
                details=details,
            )
    except Exception:
        return


def enforce_rate_limit(
    conn: Connection,
    *,
    event_type: str,
    rate_key: str,
    limit: int,
    window_seconds: int,
    request: Request | None = None,
    principal: str = "",
    count_statuses: tuple[str, ...] = ("attempt", "failed", "blocked"),
) -> None:
    if not settings.saas_rate_limit_enabled:
        return
    ensure_security_event_table(conn)
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(1, int(window_seconds)))
    statuses = [str(status or "").strip().lower()[:40] for status in count_statuses if str(status or "").strip()]
    if not statuses:
        statuses = ["failed", "blocked"]
    status_params = {f"status_{index}": status for index, status in enumerate(statuses)}
    status_sql = ", ".join(f":status_{index}" for index in range(len(statuses)))
    count = int(
        conn.execute(
            text(
                f"""
                SELECT COUNT(*)::int
                FROM saas_security_events
                WHERE event_type = :event_type
                  AND rate_limit_key = :rate_limit_key
                  AND created_at >= :cutoff
                  AND status IN ({status_sql})
                """
            ),
            {
                "event_type": event_type,
                "rate_limit_key": rate_key,
                "cutoff": cutoff,
                **status_params,
            },
        ).scalar_one()
        or 0
    )
    if count >= int(limit):
        _record_security_event_isolated(
            event_type=event_type,
            status="blocked",
            request=request,
            principal=principal,
            rate_key=rate_key,
            reason="rate_limit_exceeded",
            details={"limit": limit, "window_seconds": window_seconds, "count": count},
        )
        raise HTTPException(status_code=429, detail={"code": "rate_limit_exceeded", "retry_after_seconds": window_seconds})


def enforce_event_window_limit(
    conn: Connection,
    *,
    event_type: str,
    scope: str,
    limit: int,
    window_seconds: int,
    request: Request | None = None,
    principal: str = "",
    rate_key: str = "",
    count_statuses: tuple[str, ...] = ("attempt", "failed", "blocked"),
) -> None:
    if not settings.saas_rate_limit_enabled:
        return
    ensure_security_event_table(conn)
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(1, int(window_seconds)))
    clean_scope = str(scope or "combined").strip().lower()
    statuses = [str(status or "").strip().lower()[:40] for status in count_statuses if str(status or "").strip()]
    if not statuses:
        statuses = ["failed", "blocked"]
    status_params = {f"status_{index}": status for index, status in enumerate(statuses)}
    status_sql = ", ".join(f":status_{index}" for index in range(len(statuses)))
    params: dict[str, Any] = {
        "event_type": event_type,
        "cutoff": cutoff,
        **status_params,
    }
    where = [
        "event_type = :event_type",
        "created_at >= :cutoff",
        f"status IN ({status_sql})",
    ]
    if clean_scope == "ip":
        params["ip_address"] = client_ip(request)[:120]
        where.append("ip_address = :ip_address")
    elif clean_scope == "principal":
        params["principal"] = str(principal or "")[:240]
        where.append("principal = :principal")
    elif clean_scope == "combined":
        params["rate_limit_key"] = str(rate_key or "")[:320]
        where.append("rate_limit_key = :rate_limit_key")
    else:
        raise ValueError(f"unsupported_rate_limit_scope:{clean_scope}")

    count = int(
        conn.execute(
            text(
                f"""
                SELECT COUNT(*)::int
                FROM saas_security_events
                WHERE {" AND ".join(where)}
                """
            ),
            params,
        ).scalar_one()
        or 0
    )
    if count >= int(limit):
        _record_security_event_isolated(
            event_type=event_type,
            status="blocked",
            request=request,
            principal=principal,
            rate_key=rate_key,
            reason=f"rate_limit_exceeded:{clean_scope}",
            details={"limit": limit, "window_seconds": window_seconds, "count": count, "scope": clean_scope},
        )
        raise HTTPException(
            status_code=429,
            detail={"code": "rate_limit_exceeded", "scope": clean_scope, "retry_after_seconds": window_seconds},
        )


def enforce_auth_rate_limits(
    conn: Connection,
    *,
    event_type: str,
    rate_key: str,
    request: Request | None = None,
    principal: str = "",
    combined_limit: int,
    principal_limit: int,
    ip_limit: int,
    window_seconds: int,
    count_statuses: tuple[str, ...] = ("failed", "blocked"),
) -> None:
    enforce_event_window_limit(
        conn,
        event_type=event_type,
        scope="combined",
        limit=combined_limit,
        window_seconds=window_seconds,
        request=request,
        principal=principal,
        rate_key=rate_key,
        count_statuses=count_statuses,
    )
    enforce_event_window_limit(
        conn,
        event_type=event_type,
        scope="principal",
        limit=principal_limit,
        window_seconds=window_seconds,
        request=request,
        principal=principal,
        rate_key=rate_key,
        count_statuses=count_statuses,
    )
    enforce_event_window_limit(
        conn,
        event_type=event_type,
        scope="ip",
        limit=ip_limit,
        window_seconds=window_seconds,
        request=request,
        principal=principal,
        rate_key=rate_key,
        count_statuses=count_statuses,
    )
