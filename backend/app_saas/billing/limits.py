from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import Connection

MESSAGE_USAGE_METRICS = ("messages_in", "outbound_messages_queued")
ACTIVE_TENANT_STATUSES = {"active", "trial"}
PAYMENT_BLOCKED_STATUSES = {"past_due"}
DISABLED_TENANT_STATUSES = {"paused", "suspended", "cancelled"}
DEFAULT_FEATURE_FLAGS: dict[str, bool] = {
    "inbox": True,
    "ai": True,
    "broadcast": True,
    "triggers": False,
    "remarketing": False,
    "ads": False,
    "whatsapp_cloud": True,
    "elevenlabs_voice": False,
}


def current_period_yyyymm() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m")


def _limit_reached_detail(metric: str, limit: int, used: int, requested: int = 1) -> dict[str, Any]:
    return {
        "code": "plan_limit_reached",
        "metric": metric,
        "limit": limit,
        "used": used,
        "requested": requested,
    }


def _feature_disabled_detail(feature_key: str) -> dict[str, Any]:
    return {
        "code": "feature_not_enabled",
        "feature": feature_key,
        "message": f"Modulo no incluido o desactivado: {feature_key}",
    }


def _tenant_blocked_detail(status: str) -> dict[str, Any]:
    return {
        "code": "tenant_not_operational",
        "status": status,
        "message": "La empresa no esta habilitada para operar.",
    }


def _as_feature_map(raw: Any) -> dict[str, bool]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {}
    if not isinstance(raw, dict):
        return {}
    return {str(key).strip().lower().replace("-", "_"): bool(value) for key, value in raw.items() if str(key).strip()}


def _load_plan_limits(conn: Connection, tenant_id: str) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            SELECT
                t.plan_code,
                t.status AS tenant_status,
                l.display_name,
                l.max_agents,
                l.max_monthly_messages,
                l.max_integrations,
                l.max_storage_gb,
                l.max_campaigns,
                l.max_broadcasts,
                l.max_ai_tokens,
                l.feature_flags_json,
                l.is_active AS plan_is_active
            FROM saas_tenants t
            JOIN saas_plan_limits l ON l.plan_code = t.plan_code
            WHERE t.id = CAST(:tenant_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="tenant_plan_not_found")
    return dict(row)


def _tenant_feature_overrides(conn: Connection, tenant_id: str) -> dict[str, dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT feature_key, is_enabled, source, notes, updated_at::text
            FROM saas_tenant_feature_flags
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().all()
    return {
        str(row["feature_key"] or "").strip().lower().replace("-", "_"): dict(row)
        for row in rows
        if str(row["feature_key"] or "").strip()
    }


def _current_usage(conn: Connection, tenant_id: str, period: str) -> dict[str, int]:
    rows = conn.execute(
        text(
            """
            SELECT metric_code, metric_value
            FROM saas_usage_counters
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND period_yyyymm = :period
            """
        ),
        {"tenant_id": tenant_id, "period": period},
    ).mappings().all()
    return {str(row["metric_code"]): int(row["metric_value"] or 0) for row in rows}


def _membership_count(conn: Connection, tenant_id: str) -> int:
    return int(
        conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM saas_memberships
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND is_active = TRUE
                """
            ),
            {"tenant_id": tenant_id},
        ).scalar()
        or 0
    )


def _active_integration_count(conn: Connection, tenant_id: str) -> int:
    return int(
        conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM saas_integrations
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND status <> 'disconnected'
                """
            ),
            {"tenant_id": tenant_id},
        ).scalar()
        or 0
    )


def _campaign_count(conn: Connection, tenant_id: str) -> int:
    return int(
        conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM saas_campaigns
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND COALESCE(status, '') <> 'archived'
                """
            ),
            {"tenant_id": tenant_id},
        ).scalar()
        or 0
    )


def _broadcast_count(conn: Connection, tenant_id: str) -> int:
    return int(
        conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM saas_broadcasts
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND COALESCE(status, '') <> 'archived'
                """
            ),
            {"tenant_id": tenant_id},
        ).scalar()
        or 0
    )


def tenant_entitlements(conn: Connection, tenant_id: str) -> dict[str, Any]:
    limits = _load_plan_limits(conn, tenant_id)
    overrides = _tenant_feature_overrides(conn, tenant_id)
    plan_features = _as_feature_map(limits.get("feature_flags_json"))
    features = {**DEFAULT_FEATURE_FLAGS, **plan_features}
    feature_sources = {key: "default" for key in DEFAULT_FEATURE_FLAGS}
    feature_sources.update({key: "plan" for key in plan_features})

    for key, row in overrides.items():
        features[key] = bool(row.get("is_enabled"))
        feature_sources[key] = str(row.get("source") or "admin")

    tenant_status = str(limits.get("tenant_status") or "").lower()
    return {
        "tenant_id": tenant_id,
        "tenant_status": tenant_status,
        "is_operational": tenant_status in ACTIVE_TENANT_STATUSES,
        "features": features,
        "feature_sources": feature_sources,
        "feature_overrides": list(overrides.values()),
        "plan": {
            "plan_code": limits["plan_code"],
            "display_name": limits.get("display_name") or str(limits["plan_code"]).title(),
            "is_active": bool(limits.get("plan_is_active", True)),
            "tenant_status": tenant_status,
            "limits": {
                "max_agents": int(limits["max_agents"] or 0),
                "max_monthly_messages": int(limits["max_monthly_messages"] or 0),
                "max_integrations": int(limits["max_integrations"] or 0),
                "max_storage_gb": int(limits["max_storage_gb"] or 0),
                "max_campaigns": int(limits["max_campaigns"] or 0),
                "max_broadcasts": int(limits["max_broadcasts"] or 0),
                "max_ai_tokens": int(limits["max_ai_tokens"] or 0),
            },
        },
    }


def ensure_tenant_operational(conn: Connection, tenant_id: str) -> None:
    entitlements = tenant_entitlements(conn, tenant_id)
    status = str(entitlements.get("tenant_status") or "").lower()
    if status in ACTIVE_TENANT_STATUSES:
        return
    status_code = 402 if status in PAYMENT_BLOCKED_STATUSES else 403
    raise HTTPException(status_code=status_code, detail=_tenant_blocked_detail(status or "unknown"))


def ensure_feature_enabled(conn: Connection, tenant_id: str, feature_key: str) -> None:
    key = str(feature_key or "").strip().lower().replace("-", "_")
    if not key:
        raise HTTPException(status_code=400, detail="feature_key_required")
    entitlements = tenant_entitlements(conn, tenant_id)
    if not entitlements.get("is_operational"):
        status = str(entitlements.get("tenant_status") or "").lower()
        status_code = 402 if status in PAYMENT_BLOCKED_STATUSES else 403
        raise HTTPException(status_code=status_code, detail=_tenant_blocked_detail(status or "unknown"))
    if bool(entitlements.get("features", {}).get(key, False)):
        return
    raise HTTPException(status_code=403, detail=_feature_disabled_detail(key))


def billing_overview(conn: Connection, tenant_id: str) -> dict[str, Any]:
    period = current_period_yyyymm()
    entitlements = tenant_entitlements(conn, tenant_id)
    limits = entitlements["plan"]["limits"]
    usage = _current_usage(conn, tenant_id, period)
    subscription = conn.execute(
        text(
            """
            SELECT
                provider,
                provider_subscription_id,
                status,
                plan_code,
                current_period_start::text,
                current_period_end::text,
                cancel_at_period_end
            FROM saas_billing_subscriptions
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY updated_at DESC
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()

    used_monthly_messages = sum(usage.get(metric, 0) for metric in MESSAGE_USAGE_METRICS)
    used_integrations = _active_integration_count(conn, tenant_id)
    used_agents = _membership_count(conn, tenant_id)
    used_campaigns = _campaign_count(conn, tenant_id)
    used_broadcasts = _broadcast_count(conn, tenant_id)
    used_ai_tokens = int(usage.get("ai_tokens", 0) or 0)
    max_monthly_messages = int(limits["max_monthly_messages"] or 0)

    return {
        "tenant_id": tenant_id,
        "period_yyyymm": period,
        "plan": entitlements["plan"],
        "features": entitlements["features"],
        "feature_sources": entitlements["feature_sources"],
        "feature_overrides": entitlements["feature_overrides"],
        "is_operational": entitlements["is_operational"],
        "subscription": dict(subscription) if subscription else None,
        "usage": {
            "messages_in": usage.get("messages_in", 0),
            "outbound_messages_queued": usage.get("outbound_messages_queued", 0),
            "outbound_messages_sent": usage.get("outbound_messages_sent", 0),
            "webhook_events": usage.get("webhook_events", 0),
            "ai_tokens": used_ai_tokens,
            "used_monthly_messages": used_monthly_messages,
            "used_integrations": used_integrations,
            "used_agents": used_agents,
            "used_campaigns": used_campaigns,
            "used_broadcasts": used_broadcasts,
        },
        "remaining": {
            "monthly_messages": max(0, max_monthly_messages - used_monthly_messages),
            "integrations": max(0, int(limits["max_integrations"] or 0) - used_integrations),
            "agents": max(0, int(limits["max_agents"] or 0) - used_agents),
            "campaigns": max(0, int(limits["max_campaigns"] or 0) - used_campaigns),
            "broadcasts": max(0, int(limits["max_broadcasts"] or 0) - used_broadcasts),
            "ai_tokens": max(0, int(limits["max_ai_tokens"] or 0) - used_ai_tokens),
        },
    }


def ensure_monthly_message_quota(conn: Connection, tenant_id: str, requested: int = 1) -> None:
    ensure_tenant_operational(conn, tenant_id)
    overview = billing_overview(conn, tenant_id)
    limit = int(overview["plan"]["limits"]["max_monthly_messages"] or 0)
    used = int(overview["usage"]["used_monthly_messages"] or 0)
    if used + int(requested) > limit:
        raise HTTPException(
            status_code=402,
            detail=_limit_reached_detail("monthly_messages", limit, used, requested),
        )


def ensure_campaign_quota(conn: Connection, tenant_id: str, requested: int = 1) -> None:
    ensure_tenant_operational(conn, tenant_id)
    overview = billing_overview(conn, tenant_id)
    limit = int(overview["plan"]["limits"]["max_campaigns"] or 0)
    used = int(overview["usage"]["used_campaigns"] or 0)
    if used + int(requested) > limit:
        raise HTTPException(
            status_code=402,
            detail=_limit_reached_detail("campaigns", limit, used, requested),
        )


def ensure_broadcast_quota(conn: Connection, tenant_id: str, requested: int = 1) -> None:
    ensure_tenant_operational(conn, tenant_id)
    overview = billing_overview(conn, tenant_id)
    limit = int(overview["plan"]["limits"]["max_broadcasts"] or 0)
    used = int(overview["usage"]["used_broadcasts"] or 0)
    if used + int(requested) > limit:
        raise HTTPException(
            status_code=402,
            detail=_limit_reached_detail("broadcasts", limit, used, requested),
        )


def ensure_ai_token_quota(conn: Connection, tenant_id: str, requested: int = 1) -> None:
    ensure_tenant_operational(conn, tenant_id)
    ensure_feature_enabled(conn, tenant_id, "ai")
    overview = billing_overview(conn, tenant_id)
    limit = int(overview["plan"]["limits"]["max_ai_tokens"] or 0)
    used = int(overview["usage"]["ai_tokens"] or 0)
    if used + int(requested) > limit:
        raise HTTPException(
            status_code=402,
            detail=_limit_reached_detail("ai_tokens", limit, used, requested),
        )


def ensure_integration_quota(conn: Connection, tenant_id: str, provider: str, channel: str) -> None:
    ensure_tenant_operational(conn, tenant_id)
    plan = _load_plan_limits(conn, tenant_id)
    existing = conn.execute(
        text(
            """
            SELECT id::text, status
            FROM saas_integrations
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND provider = :provider
              AND channel = :channel
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "provider": provider, "channel": channel},
    ).mappings().first()
    if existing and str(existing["status"] or "").lower() != "disconnected":
        return

    used = _active_integration_count(conn, tenant_id)
    limit = int(plan["max_integrations"] or 0)
    if used + 1 > limit:
        raise HTTPException(
            status_code=402,
            detail=_limit_reached_detail("integrations", limit, used, 1),
        )
