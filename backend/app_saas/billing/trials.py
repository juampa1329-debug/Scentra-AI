from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app_saas.config import settings


def configured_trial_days() -> int:
    try:
        days = int(settings.saas_trial_days)
    except (TypeError, ValueError):
        days = 30
    return max(1, min(days, 365))


def configured_trial_plan_code(conn: Connection) -> str:
    desired = str(settings.saas_trial_plan_code or "starter").strip().lower() or "starter"
    row = conn.execute(
        text(
            """
            SELECT plan_code
            FROM saas_plan_limits
            WHERE plan_code = :plan_code
            LIMIT 1
            """
        ),
        {"plan_code": desired},
    ).mappings().first()
    if row:
        return str(row["plan_code"])

    fallback = conn.execute(
        text(
            """
            SELECT plan_code
            FROM saas_plan_limits
            WHERE plan_code = 'starter'
            LIMIT 1
            """
        )
    ).mappings().first()
    return str(fallback["plan_code"]) if fallback else desired


def create_trial_subscription(conn: Connection, tenant_id: str, plan_code: str | None = None) -> dict:
    effective_plan = (plan_code or configured_trial_plan_code(conn)).strip().lower()
    trial_days = configured_trial_days()
    conn.execute(
        text(
            """
            UPDATE saas_tenants
            SET status = 'trial',
                plan_code = :plan_code,
                updated_at = NOW()
            WHERE id = CAST(:tenant_id AS uuid)
            """
        ),
        {"tenant_id": tenant_id, "plan_code": effective_plan},
    )
    row = conn.execute(
        text(
            """
            INSERT INTO saas_billing_subscriptions (
                tenant_id,
                provider,
                provider_subscription_id,
                status,
                plan_code,
                current_period_start,
                current_period_end,
                cancel_at_period_end,
                updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid),
                'trial',
                :provider_subscription_id,
                'trial',
                :plan_code,
                NOW(),
                NOW() + make_interval(days => :trial_days),
                FALSE,
                NOW()
            )
            ON CONFLICT (provider_subscription_id)
            DO UPDATE SET
                status = 'trial',
                plan_code = EXCLUDED.plan_code,
                current_period_start = EXCLUDED.current_period_start,
                current_period_end = EXCLUDED.current_period_end,
                cancel_at_period_end = FALSE,
                updated_at = NOW()
            RETURNING
                provider,
                provider_subscription_id,
                status,
                plan_code,
                current_period_start::text,
                current_period_end::text,
                cancel_at_period_end
            """
        ),
        {
            "tenant_id": tenant_id,
            "plan_code": effective_plan,
            "trial_days": trial_days,
            "provider_subscription_id": f"trial:{tenant_id}",
        },
    ).mappings().first()
    return dict(row or {})
