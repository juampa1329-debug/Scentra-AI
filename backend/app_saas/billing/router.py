from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import text

from app_saas.billing.limits import billing_overview, tenant_entitlements
from app_saas.billing.service import (
    create_checkout_session,
    get_invoice,
    invoice_pdf_bytes,
    list_checkout_sessions,
    list_credits,
    list_invoices,
    process_provider_event,
)
from app_saas.config import settings
from app_saas.db import db_session, set_tenant_context
from app_saas.shared.security import AuthContext, get_current_user, require_role

router = APIRouter(prefix="/billing", tags=["saas-billing"])


class ChangePlanIn(BaseModel):
    plan_code: str = Field(min_length=2, max_length=40)


class CheckoutIn(BaseModel):
    plan_code: str = Field(min_length=2, max_length=40)
    provider: str = Field(default="auto", max_length=40)
    success_url: str = Field(default="", max_length=1500)
    cancel_url: str = Field(default="", max_length=1500)


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


@router.get("/checkout-sessions")
def checkout_sessions(
    limit: int = 100,
    ctx: AuthContext = Depends(require_role("owner", "admin")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        rows = list_checkout_sessions(conn, ctx.tenant_id, limit)
    return {"tenant_id": ctx.tenant_id, "checkout_sessions": rows}


@router.post("/checkout")
def checkout(
    payload: CheckoutIn,
    ctx: AuthContext = Depends(require_role("owner", "admin")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        session = create_checkout_session(
            conn,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            plan_code=payload.plan_code,
            provider=payload.provider,
            success_url=payload.success_url,
            cancel_url=payload.cancel_url,
        )
    return {"tenant_id": ctx.tenant_id, "checkout": session}


@router.get("/invoices")
def invoices(
    limit: int = 100,
    ctx: AuthContext = Depends(require_role("owner", "admin")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        rows = list_invoices(conn, ctx.tenant_id, limit)
    return {"tenant_id": ctx.tenant_id, "invoices": rows}


@router.get("/invoices/{invoice_id}/pdf")
def invoice_pdf(
    invoice_id: str,
    ctx: AuthContext = Depends(require_role("owner", "admin")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        invoice = get_invoice(conn, ctx.tenant_id, invoice_id)
        conn.execute(
            text("UPDATE saas_billing_invoices SET pdf_generated_at = NOW(), updated_at = NOW() WHERE id = CAST(:invoice_id AS uuid)"),
            {"invoice_id": invoice_id},
        )
    filename = f"scentra-invoice-{invoice.get('invoice_number') or invoice_id}.pdf".replace(" ", "-")
    return Response(
        content=invoice_pdf_bytes(invoice),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/credits")
def credits(
    limit: int = 100,
    ctx: AuthContext = Depends(require_role("owner", "admin")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        rows = list_credits(conn, ctx.tenant_id, limit)
    return {"tenant_id": ctx.tenant_id, "credits": rows}


@router.post("/webhooks/{provider}")
async def provider_webhook(provider: str, request: Request):
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid_json_payload") from exc
    header_checksum = request.headers.get("x-event-checksum", "")
    headers = {key.lower(): value for key, value in request.headers.items()}
    query_params = {key.lower(): value for key, value in request.query_params.items()}
    with db_session() as conn:
        result = process_provider_event(
            conn,
            provider=provider,
            payload=payload,
            raw_body=raw_body,
            headers=headers,
            query_params=query_params,
            header_checksum=header_checksum,
        )
    return {"ok": True, **result}


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
