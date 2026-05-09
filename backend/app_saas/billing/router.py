from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from app_saas.billing.limits import billing_overview, tenant_entitlements
from app_saas.config import settings
from app_saas.db import db_session, set_tenant_context
from app_saas.shared.security import AuthContext, get_current_user, require_role

router = APIRouter(prefix="/billing", tags=["saas-billing"])


class ChangePlanIn(BaseModel):
    plan_code: str = Field(min_length=2, max_length=40)


@router.get("/subscription")
def subscription(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        row = conn.execute(
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
            {"tenant_id": ctx.tenant_id},
        ).mappings().first()
    return {"tenant_id": ctx.tenant_id, "subscription": dict(row) if row else None}


@router.get("/overview")
def overview(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return billing_overview(conn, ctx.tenant_id)


@router.get("/entitlements")
def entitlements(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return tenant_entitlements(conn, ctx.tenant_id)


@router.get("/limits")
def limits(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        row = conn.execute(
            text(
                """
                SELECT l.*
                FROM saas_tenants t
                JOIN saas_plan_limits l ON l.plan_code = t.plan_code
                WHERE t.id = CAST(:tenant_id AS uuid)
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().first()
    return {"tenant_id": ctx.tenant_id, "limits": dict(row) if row else None}


@router.get("/usage")
def usage(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        rows = conn.execute(
            text(
                """
                SELECT metric_code, period_yyyymm, metric_value
                FROM saas_usage_counters
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                ORDER BY period_yyyymm DESC, metric_code ASC
                LIMIT 200
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().all()
    return {"tenant_id": ctx.tenant_id, "usage": [dict(row) for row in rows]}


@router.get("/plans")
def plans(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        rows = conn.execute(
            text(
                """
                SELECT
                    plan_code,
                    display_name,
                    max_agents,
                    max_monthly_messages,
                    max_integrations,
                    max_storage_gb,
                    max_campaigns,
                    max_broadcasts,
                    max_ai_tokens,
                    feature_flags_json,
                    price_monthly_cents,
                    currency,
                    is_public,
                    is_active,
                    sort_order
                FROM saas_plan_limits
                WHERE is_public = TRUE
                ORDER BY
                    sort_order ASC,
                    plan_code ASC
                """
            )
        ).mappings().all()
    return {"tenant_id": ctx.tenant_id, "plans": [dict(row) for row in rows]}


@router.post("/dev/change-plan")
def change_plan_dev(
    payload: ChangePlanIn,
    ctx: AuthContext = Depends(require_role("owner", "admin")),
):
    if not settings.is_local:
        raise HTTPException(status_code=403, detail="billing_provider_required")

    plan_code = payload.plan_code.strip().lower()
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        plan = conn.execute(
            text(
                """
                SELECT plan_code
                FROM saas_plan_limits
                WHERE plan_code = :plan_code
                LIMIT 1
                """
            ),
            {"plan_code": plan_code},
        ).mappings().first()
        if not plan:
            raise HTTPException(status_code=404, detail="plan_not_found")

        conn.execute(
            text(
                """
                UPDATE saas_tenants
                SET plan_code = :plan_code, updated_at = NOW()
                WHERE id = CAST(:tenant_id AS uuid)
                """
            ),
            {"tenant_id": ctx.tenant_id, "plan_code": plan_code},
        )
        conn.execute(
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
                    updated_at
                )
                VALUES (
                    CAST(:tenant_id AS uuid),
                    'dev',
                    :provider_subscription_id,
                    'active',
                    :plan_code,
                    date_trunc('month', NOW()),
                    date_trunc('month', NOW()) + INTERVAL '1 month',
                    NOW()
                )
                ON CONFLICT (provider_subscription_id)
                DO UPDATE SET
                    status = 'active',
                    plan_code = EXCLUDED.plan_code,
                    current_period_start = EXCLUDED.current_period_start,
                    current_period_end = EXCLUDED.current_period_end,
                    cancel_at_period_end = FALSE,
                    updated_at = NOW()
                """
            ),
            {
                "tenant_id": ctx.tenant_id,
                "plan_code": plan_code,
                "provider_subscription_id": f"dev:{ctx.tenant_id}",
            },
        )
        return billing_overview(conn, ctx.tenant_id)
