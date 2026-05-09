from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app_saas.admin.schemas import (
    AdminBootstrapIn,
    AdminLoginIn,
    FeatureFlagPatchIn,
    PlanPatchIn,
    PlanUpsertIn,
    PlatformTokenOut,
    TenantImpersonateIn,
    SubscriptionPatchIn,
    TenantPatchIn,
)
from app_saas.billing.limits import billing_overview
from app_saas.config import settings
from app_saas.db import db_session, set_tenant_context
from app_saas.shared.security import (
    PLATFORM_ROLE_ORDER,
    PlatformAuthContext,
    create_token,
    get_current_platform_admin,
    hash_password,
    normalize_email,
    normalize_slug,
    require_platform_role,
    verify_password,
)
from app_saas.workers.dispatch import process_due_outbound_messages
from app_saas.workers.ingest import process_due_webhook_events
from app_saas.workers.triggers import process_due_scheduled_trigger_messages

router = APIRouter(prefix="/admin", tags=["saas-admin"])

FEATURE_CATALOG = [
    {"key": "inbox", "label": "Inbox"},
    {"key": "ai", "label": "IA comercial"},
    {"key": "broadcast", "label": "Mensajeria masiva"},
    {"key": "triggers", "label": "Triggers CRM"},
    {"key": "remarketing", "label": "Remarketing"},
    {"key": "ads", "label": "Ads Manager"},
    {"key": "whatsapp_cloud", "label": "WhatsApp Cloud real"},
    {"key": "elevenlabs_voice", "label": "Voz ElevenLabs"},
]
TENANT_STATUSES = {"active", "trial", "paused", "past_due", "suspended", "cancelled"}
SUBSCRIPTION_STATUSES = {"trial", "active", "past_due", "cancelled", "suspended"}
IMPERSONATION_ROLES = {"owner", "admin", "supervisor", "agent", "viewer"}


def _clean(value: object, limit: int = 200) -> str:
    return str(value or "").strip()[:limit]


def _period_yyyymm() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m")


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _admin_token(row: dict[str, Any]) -> PlatformTokenOut:
    role = str(row["platform_role"] or row["role"] or "platform_admin").strip().lower()
    token = create_token(user_id=row["user_id"], email=row["email"], token_type="access", platform_role=role)
    return PlatformTokenOut(
        access_token=token,
        user_id=row["user_id"],
        email=row["email"],
        platform_role=role,
    )


def _audit(
    conn,
    *,
    actor: PlatformAuthContext,
    action: str,
    resource_type: str,
    resource_id: str = "",
    tenant_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        text(
            """
            INSERT INTO saas_audit_events (tenant_id, actor_user_id, action, resource_type, resource_id, details_json)
            VALUES (
                CAST(NULLIF(:tenant_id, '') AS uuid),
                CAST(:actor_user_id AS uuid),
                :action,
                :resource_type,
                :resource_id,
                CAST(:details_json AS jsonb)
            )
            """
        ),
        {
            "tenant_id": tenant_id or "",
            "actor_user_id": actor.user_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "details_json": _json(details or {}),
        },
    )


def _platform_admin_count(conn) -> int:
    return int(
        conn.execute(
            text("SELECT COUNT(*) FROM saas_platform_admins WHERE status = 'active'")
        ).scalar_one()
        or 0
    )


def _load_plan(conn, plan_code: str) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            """
            SELECT plan_code, display_name, max_agents, max_monthly_messages, max_integrations, max_storage_gb,
                   max_campaigns, max_broadcasts, max_ai_tokens, feature_flags_json, price_monthly_cents,
                   currency, is_public, is_active, sort_order, created_at::text, updated_at::text
            FROM saas_plan_limits
            WHERE plan_code = :plan_code
            LIMIT 1
            """
        ),
        {"plan_code": plan_code},
    ).mappings().first()
    return dict(row) if row else None


def _tenant_exists(conn, tenant_id: str) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            SELECT id::text, slug, name, status, plan_code, timezone, locale, created_at::text, updated_at::text
            FROM saas_tenants
            WHERE id = CAST(:tenant_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="tenant_not_found")
    return dict(row)


@router.post("/auth/bootstrap", response_model=PlatformTokenOut)
def bootstrap_platform_admin(payload: AdminBootstrapIn):
    if not settings.is_local:
        raise HTTPException(status_code=403, detail="bootstrap_only_available_locally")
    email = normalize_email(payload.email)
    role = _clean(payload.platform_role, 40).lower() or "superadmin"
    if role not in PLATFORM_ROLE_ORDER:
        raise HTTPException(status_code=400, detail="invalid_platform_role")
    with db_session() as conn:
        user = conn.execute(
            text(
                """
                INSERT INTO saas_users (email, full_name, password_hash, password_algo, status, updated_at)
                VALUES (:email, :full_name, :password_hash, 'argon2id', 'active', NOW())
                ON CONFLICT (email)
                DO UPDATE SET
                    full_name = COALESCE(NULLIF(EXCLUDED.full_name, ''), saas_users.full_name),
                    password_hash = EXCLUDED.password_hash,
                    status = 'active',
                    updated_at = NOW()
                RETURNING id::text AS user_id, email
                """
            ),
            {
                "email": email,
                "full_name": _clean(payload.full_name, 180),
                "password_hash": hash_password(payload.password),
            },
        ).mappings().first()
        conn.execute(
            text(
                """
                INSERT INTO saas_platform_admins (user_id, role, status, notes, updated_at)
                VALUES (CAST(:user_id AS uuid), :role, 'active', 'local bootstrap', NOW())
                ON CONFLICT (user_id)
                DO UPDATE SET role = EXCLUDED.role, status = 'active', updated_at = NOW()
                """
            ),
            {"user_id": user["user_id"], "role": role},
        )
    return _admin_token({"user_id": user["user_id"], "email": user["email"], "platform_role": role, "role": role})


@router.post("/auth/login", response_model=PlatformTokenOut)
def admin_login(payload: AdminLoginIn):
    email = normalize_email(payload.email)
    with db_session() as conn:
        row = conn.execute(
            text(
                """
                SELECT u.id::text AS user_id, u.email, u.password_hash, u.status AS user_status,
                       pa.role AS platform_role, pa.status AS admin_status
                FROM saas_users u
                JOIN saas_platform_admins pa ON pa.user_id = u.id
                WHERE LOWER(u.email) = :email
                LIMIT 1
                """
            ),
            {"email": email},
        ).mappings().first()
        if (
            not row
            or row["user_status"] != "active"
            or row["admin_status"] != "active"
            or str(row["platform_role"] or "").lower() not in PLATFORM_ROLE_ORDER
            or not verify_password(payload.password, row["password_hash"])
        ):
            raise HTTPException(status_code=401, detail="invalid_admin_credentials")
        conn.execute(
            text("UPDATE saas_users SET last_login_at = NOW(), updated_at = NOW() WHERE id = CAST(:id AS uuid)"),
            {"id": row["user_id"]},
        )
    return _admin_token(dict(row))


@router.get("/auth/me")
def admin_me(ctx: PlatformAuthContext = Depends(get_current_platform_admin)):
    return {"user_id": ctx.user_id, "email": ctx.email, "platform_role": ctx.platform_role}


@router.get("/feature-flags/catalog")
def feature_flags_catalog(ctx: PlatformAuthContext = Depends(get_current_platform_admin)):
    return {"features": FEATURE_CATALOG}


@router.get("/overview")
def platform_overview(ctx: PlatformAuthContext = Depends(get_current_platform_admin)):
    period = _period_yyyymm()
    with db_session() as conn:
        tenant_counts = conn.execute(
            text(
                """
                SELECT
                    COUNT(*)::int AS total,
                    COUNT(*) FILTER (WHERE status = 'active')::int AS active,
                    COUNT(*) FILTER (WHERE status = 'trial')::int AS trial,
                    COUNT(*) FILTER (WHERE status = 'paused')::int AS paused,
                    COUNT(*) FILTER (WHERE status = 'past_due')::int AS past_due,
                    COUNT(*) FILTER (WHERE status = 'suspended')::int AS suspended,
                    COUNT(*) FILTER (WHERE status = 'cancelled')::int AS cancelled
                FROM saas_tenants
                """
            )
        ).mappings().first()
        plans = conn.execute(
            text("SELECT plan_code, COUNT(*)::int AS tenants FROM saas_tenants GROUP BY plan_code ORDER BY plan_code ASC")
        ).mappings().all()
        subscriptions = conn.execute(
            text("SELECT status, COUNT(*)::int AS total FROM saas_billing_subscriptions GROUP BY status ORDER BY status ASC")
        ).mappings().all()
        usage = conn.execute(
            text(
                """
                SELECT metric_code, SUM(metric_value)::bigint AS total
                FROM saas_usage_counters
                WHERE period_yyyymm = :period
                GROUP BY metric_code
                ORDER BY metric_code ASC
                """
            ),
            {"period": period},
        ).mappings().all()
        queues = _queue_counts(conn)
    return {
        "period_yyyymm": period,
        "tenants": dict(tenant_counts or {}),
        "plans": [dict(row) for row in plans],
        "subscriptions": [dict(row) for row in subscriptions],
        "usage": [dict(row) for row in usage],
        "queues": queues,
    }


def _queue_counts(conn) -> dict[str, Any]:
    outbound = conn.execute(
        text("SELECT status, COUNT(*)::int AS total FROM saas_outbound_messages GROUP BY status ORDER BY status ASC")
    ).mappings().all()
    webhooks = conn.execute(
        text("SELECT status, COUNT(*)::int AS total FROM saas_webhook_events GROUP BY status ORDER BY status ASC")
    ).mappings().all()
    scheduled = conn.execute(
        text(
            """
            SELECT status, COUNT(*)::int AS total
            FROM saas_trigger_scheduled_messages
            GROUP BY status
            ORDER BY status ASC
            """
        )
    ).mappings().all()
    return {
        "outbound": [dict(row) for row in outbound],
        "webhooks": [dict(row) for row in webhooks],
        "scheduled_triggers": [dict(row) for row in scheduled],
    }


@router.get("/tenants")
def list_tenants(
    search: str = Query("", max_length=160),
    status: str = Query("all", max_length=40),
    plan_code: str = Query("all", max_length=40),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ctx: PlatformAuthContext = Depends(get_current_platform_admin),
):
    where = ["1=1"]
    params: dict[str, Any] = {"limit": limit, "offset": offset, "period": _period_yyyymm()}
    clean_search = _clean(search, 160).lower()
    if clean_search:
        params["search"] = f"%{clean_search}%"
        where.append("(LOWER(t.name) LIKE :search OR LOWER(t.slug) LIKE :search)")
    if status and status != "all":
        params["status"] = _clean(status, 40).lower()
        where.append("t.status = :status")
    if plan_code and plan_code != "all":
        params["plan_code"] = _clean(plan_code, 40).lower()
        where.append("t.plan_code = :plan_code")
    where_sql = " AND ".join(where)
    with db_session() as conn:
        total = int(conn.execute(text(f"SELECT COUNT(*) FROM saas_tenants t WHERE {where_sql}"), params).scalar_one() or 0)
        rows = conn.execute(
            text(
                f"""
                SELECT
                    t.id::text,
                    t.slug,
                    t.name,
                    t.status,
                    t.plan_code,
                    t.timezone,
                    t.locale,
                    t.created_at::text,
                    t.updated_at::text,
                    COALESCE((SELECT COUNT(*)::int FROM saas_memberships m WHERE m.tenant_id = t.id AND m.is_active = TRUE), 0) AS users_count,
                    COALESCE((SELECT COUNT(*)::int FROM saas_integrations i WHERE i.tenant_id = t.id AND i.status <> 'disconnected'), 0) AS integrations_count,
                    COALESCE((SELECT SUM(metric_value)::bigint FROM saas_usage_counters u WHERE u.tenant_id = t.id AND u.period_yyyymm = :period AND u.metric_code IN ('messages_in', 'outbound_messages_queued')), 0) AS used_monthly_messages,
                    COALESCE((SELECT status FROM saas_billing_subscriptions s WHERE s.tenant_id = t.id ORDER BY s.updated_at DESC LIMIT 1), 'none') AS subscription_status,
                    COALESCE((
                        SELECT NULLIF(u.full_name, '')
                        FROM saas_memberships m
                        JOIN saas_users u ON u.id = m.user_id
                        WHERE m.tenant_id = t.id AND m.role = 'owner' AND m.is_active = TRUE
                        ORDER BY m.created_at ASC
                        LIMIT 1
                    ), '') AS owner_name,
                    COALESCE((
                        SELECT u.email
                        FROM saas_memberships m
                        JOIN saas_users u ON u.id = m.user_id
                        WHERE m.tenant_id = t.id AND m.role = 'owner' AND m.is_active = TRUE
                        ORDER BY m.created_at ASC
                        LIMIT 1
                    ), '') AS owner_email
                FROM saas_tenants t
                WHERE {where_sql}
                ORDER BY t.updated_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).mappings().all()
    return {"total": total, "limit": limit, "offset": offset, "tenants": [dict(row) for row in rows]}


@router.get("/tenants/{tenant_id}")
def tenant_detail(tenant_id: str, ctx: PlatformAuthContext = Depends(get_current_platform_admin)):
    with db_session() as conn:
        tenant = _tenant_exists(conn, tenant_id)
        set_tenant_context(conn, tenant_id)
        owner = conn.execute(
            text(
                """
                SELECT u.id::text AS user_id, u.email, u.full_name
                FROM saas_memberships m
                JOIN saas_users u ON u.id = m.user_id
                WHERE m.tenant_id = CAST(:tenant_id AS uuid)
                  AND m.role = 'owner'
                  AND m.is_active = TRUE
                ORDER BY m.created_at ASC
                LIMIT 1
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().first()
        overview = billing_overview(conn, tenant_id)
        members = conn.execute(
            text(
                """
                SELECT m.id::text, m.role, m.is_active, m.created_at::text, m.updated_at::text,
                       u.id::text AS user_id, u.email, u.full_name, u.status AS user_status, u.last_login_at::text
                FROM saas_memberships m
                JOIN saas_users u ON u.id = m.user_id
                WHERE m.tenant_id = CAST(:tenant_id AS uuid)
                ORDER BY m.created_at ASC
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().all()
        integrations = conn.execute(
            text(
                """
                SELECT id::text, provider, channel, status, secret_ref, config_json, last_sync_at::text, updated_at::text
                FROM saas_integrations
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                ORDER BY provider ASC, channel ASC
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().all()
        features = conn.execute(
            text(
                """
                SELECT feature_key, is_enabled, source, notes, updated_at::text
                FROM saas_tenant_feature_flags
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                ORDER BY feature_key ASC
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().all()
        audit = conn.execute(
            text(
                """
                SELECT id, action, resource_type, resource_id, details_json, created_at::text
                FROM saas_audit_events
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                ORDER BY created_at DESC
                LIMIT 30
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().all()
    return {
        "tenant": tenant,
        "owner": dict(owner) if owner else None,
        "billing": overview,
        "members": [dict(row) for row in members],
        "integrations": [dict(row) for row in integrations],
        "feature_flags": [dict(row) for row in features],
        "audit": [dict(row) for row in audit],
    }


@router.patch("/tenants/{tenant_id}")
def update_tenant(
    tenant_id: str,
    payload: TenantPatchIn,
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "billing_admin")),
):
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="tenant_patch_required")
    assignments: list[str] = []
    params: dict[str, Any] = {"tenant_id": tenant_id}
    with db_session() as conn:
        _tenant_exists(conn, tenant_id)
        if "plan_code" in data and data["plan_code"]:
            plan_code = _clean(data["plan_code"], 40).lower()
            if not _load_plan(conn, plan_code):
                raise HTTPException(status_code=404, detail="plan_not_found")
            params["plan_code"] = plan_code
            assignments.append("plan_code = :plan_code")
        if "status" in data and data["status"]:
            tenant_status = _clean(data["status"], 40).lower()
            if tenant_status not in TENANT_STATUSES:
                raise HTTPException(status_code=400, detail="invalid_tenant_status")
            params["status"] = tenant_status
            assignments.append("status = :status")
        for key in ("name", "timezone", "locale"):
            if key in data and data[key] is not None:
                params[key] = _clean(data[key], 160 if key == "name" else 80)
                assignments.append(f"{key} = :{key}")
        if assignments:
            conn.execute(
                text(
                    f"""
                    UPDATE saas_tenants
                    SET {", ".join(assignments)}, updated_at = NOW()
                    WHERE id = CAST(:tenant_id AS uuid)
                    """
                ),
                params,
            )
        sub_status = _clean(data.get("subscription_status"), 40).lower()
        if sub_status:
            if sub_status not in SUBSCRIPTION_STATUSES:
                raise HTTPException(status_code=400, detail="invalid_subscription_status")
            conn.execute(
                text(
                    """
                    INSERT INTO saas_billing_subscriptions (
                        tenant_id, provider, provider_subscription_id, status, plan_code,
                        current_period_start, current_period_end, updated_at
                    )
                    VALUES (
                        CAST(:tenant_id AS uuid), 'admin', :provider_subscription_id, :status,
                        COALESCE(:plan_code, (SELECT plan_code FROM saas_tenants WHERE id = CAST(:tenant_id AS uuid))),
                        date_trunc('month', NOW()), date_trunc('month', NOW()) + INTERVAL '1 month', NOW()
                    )
                    ON CONFLICT (provider_subscription_id)
                    DO UPDATE SET status = EXCLUDED.status, plan_code = EXCLUDED.plan_code, updated_at = NOW()
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "provider_subscription_id": f"admin:{tenant_id}",
                    "status": sub_status,
                    "plan_code": params.get("plan_code"),
                },
            )
        _audit(conn, actor=ctx, action="admin.tenant.update", resource_type="tenant", resource_id=tenant_id, tenant_id=tenant_id, details=data)
    with db_session() as conn:
        tenant = _tenant_exists(conn, tenant_id)
    return {"ok": True, "tenant": tenant}


@router.post("/tenants/{tenant_id}/feature-flags")
def set_tenant_feature(
    tenant_id: str,
    payload: FeatureFlagPatchIn,
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support")),
):
    feature_key = normalize_slug(payload.feature_key).replace("-", "_")
    if not feature_key:
        raise HTTPException(status_code=400, detail="valid_feature_key_required")
    with db_session() as conn:
        _tenant_exists(conn, tenant_id)
        row = conn.execute(
            text(
                """
                INSERT INTO saas_tenant_feature_flags (
                    tenant_id, feature_key, is_enabled, source, notes, updated_by_user_id, updated_at
                )
                VALUES (
                    CAST(:tenant_id AS uuid), :feature_key, :is_enabled, :source, :notes, CAST(:user_id AS uuid), NOW()
                )
                ON CONFLICT (tenant_id, feature_key)
                DO UPDATE SET
                    is_enabled = EXCLUDED.is_enabled,
                    source = EXCLUDED.source,
                    notes = EXCLUDED.notes,
                    updated_by_user_id = EXCLUDED.updated_by_user_id,
                    updated_at = NOW()
                RETURNING feature_key, is_enabled, source, notes, updated_at::text
                """
            ),
            {
                "tenant_id": tenant_id,
                "feature_key": feature_key,
                "is_enabled": payload.is_enabled,
                "source": _clean(payload.source, 40) or "admin",
                "notes": _clean(payload.notes, 500),
                "user_id": ctx.user_id,
            },
        ).mappings().first()
        _audit(
            conn,
            actor=ctx,
            action="admin.feature_flag.set",
            resource_type="tenant_feature_flag",
            resource_id=feature_key,
            tenant_id=tenant_id,
            details=dict(row or {}),
        )
    return {"ok": True, "feature": dict(row)}


@router.post("/tenants/{tenant_id}/impersonate")
def impersonate_tenant(
    tenant_id: str,
    payload: TenantImpersonateIn,
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support")),
):
    role = _clean(payload.role, 40).lower() or "admin"
    if role not in IMPERSONATION_ROLES:
        raise HTTPException(status_code=400, detail="invalid_impersonation_role")
    with db_session() as conn:
        tenant = _tenant_exists(conn, tenant_id)
        if tenant["status"] in {"cancelled"}:
            raise HTTPException(status_code=409, detail="tenant_cancelled")
        _audit(
            conn,
            actor=ctx,
            action="admin.tenant.impersonate",
            resource_type="tenant",
            resource_id=tenant_id,
            tenant_id=tenant_id,
            details={"role": role, "reason": _clean(payload.reason, 500)},
        )
    access_token = create_token(
        user_id=ctx.user_id,
        email=ctx.email,
        token_type="access",
        tenant_id=tenant_id,
        role=role,
        expires_delta=timedelta(minutes=20),
    )
    return {
        "ok": True,
        "tenant_id": tenant_id,
        "tenant_name": tenant["name"],
        "role": role,
        "expires_in_minutes": 20,
        "access_token": access_token,
    }


@router.get("/plans")
def list_plans(ctx: PlatformAuthContext = Depends(get_current_platform_admin)):
    with db_session() as conn:
        rows = conn.execute(
            text(
                """
                SELECT plan_code, display_name, max_agents, max_monthly_messages, max_integrations, max_storage_gb,
                       max_campaigns, max_broadcasts, max_ai_tokens, feature_flags_json, price_monthly_cents,
                       currency, is_public, is_active, sort_order, created_at::text, updated_at::text,
                       (SELECT COUNT(*)::int FROM saas_tenants t WHERE t.plan_code = saas_plan_limits.plan_code) AS tenants_count
                FROM saas_plan_limits
                ORDER BY sort_order ASC, plan_code ASC
                """
            )
        ).mappings().all()
    return {"plans": [dict(row) for row in rows]}


@router.post("/plans")
def upsert_plan(
    payload: PlanUpsertIn,
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "billing_admin")),
):
    plan_code = normalize_slug(payload.plan_code).replace("-", "_")
    if not plan_code:
        raise HTTPException(status_code=400, detail="valid_plan_code_required")
    with db_session() as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO saas_plan_limits (
                    plan_code, display_name, max_agents, max_monthly_messages, max_integrations, max_storage_gb,
                    max_campaigns, max_broadcasts, max_ai_tokens, feature_flags_json, price_monthly_cents,
                    currency, is_public, is_active, sort_order, updated_at
                )
                VALUES (
                    :plan_code, :display_name, :max_agents, :max_monthly_messages, :max_integrations, :max_storage_gb,
                    :max_campaigns, :max_broadcasts, :max_ai_tokens, CAST(:feature_flags_json AS jsonb), :price_monthly_cents,
                    :currency, :is_public, :is_active, :sort_order, NOW()
                )
                ON CONFLICT (plan_code)
                DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    max_agents = EXCLUDED.max_agents,
                    max_monthly_messages = EXCLUDED.max_monthly_messages,
                    max_integrations = EXCLUDED.max_integrations,
                    max_storage_gb = EXCLUDED.max_storage_gb,
                    max_campaigns = EXCLUDED.max_campaigns,
                    max_broadcasts = EXCLUDED.max_broadcasts,
                    max_ai_tokens = EXCLUDED.max_ai_tokens,
                    feature_flags_json = EXCLUDED.feature_flags_json,
                    price_monthly_cents = EXCLUDED.price_monthly_cents,
                    currency = EXCLUDED.currency,
                    is_public = EXCLUDED.is_public,
                    is_active = EXCLUDED.is_active,
                    sort_order = EXCLUDED.sort_order,
                    updated_at = NOW()
                RETURNING plan_code, display_name, max_agents, max_monthly_messages, max_integrations, max_storage_gb,
                          max_campaigns, max_broadcasts, max_ai_tokens, feature_flags_json, price_monthly_cents,
                          currency, is_public, is_active, sort_order, created_at::text, updated_at::text
                """
            ),
            {
                **payload.model_dump(),
                "plan_code": plan_code,
                "display_name": _clean(payload.display_name, 120) or plan_code.title(),
                "currency": _clean(payload.currency, 12).upper() or "USD",
                "feature_flags_json": _json(payload.feature_flags_json),
            },
        ).mappings().first()
        _audit(conn, actor=ctx, action="admin.plan.upsert", resource_type="plan", resource_id=plan_code, details=dict(row or {}))
    return {"ok": True, "plan": dict(row)}


@router.patch("/plans/{plan_code}")
def patch_plan(
    plan_code: str,
    payload: PlanPatchIn,
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "billing_admin")),
):
    clean_plan = normalize_slug(plan_code).replace("-", "_")
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="plan_patch_required")
    assignments: list[str] = []
    params: dict[str, Any] = {"plan_code": clean_plan}
    for key, value in data.items():
        if key == "feature_flags_json":
            params[key] = _json(value or {})
            assignments.append("feature_flags_json = CAST(:feature_flags_json AS jsonb)")
        elif key in {"display_name", "currency"}:
            params[key] = _clean(value, 120 if key == "display_name" else 12)
            assignments.append(f"{key} = :{key}")
        else:
            params[key] = value
            assignments.append(f"{key} = :{key}")
    with db_session() as conn:
        if not _load_plan(conn, clean_plan):
            raise HTTPException(status_code=404, detail="plan_not_found")
        row = conn.execute(
            text(
                f"""
                UPDATE saas_plan_limits
                SET {", ".join(assignments)}, updated_at = NOW()
                WHERE plan_code = :plan_code
                RETURNING plan_code, display_name, max_agents, max_monthly_messages, max_integrations, max_storage_gb,
                          max_campaigns, max_broadcasts, max_ai_tokens, feature_flags_json, price_monthly_cents,
                          currency, is_public, is_active, sort_order, created_at::text, updated_at::text
                """
            ),
            params,
        ).mappings().first()
        _audit(conn, actor=ctx, action="admin.plan.patch", resource_type="plan", resource_id=clean_plan, details=data)
    return {"ok": True, "plan": dict(row)}


@router.get("/subscriptions")
def list_subscriptions(
    status: str = Query("all", max_length=40),
    limit: int = Query(100, ge=1, le=500),
    ctx: PlatformAuthContext = Depends(get_current_platform_admin),
):
    where = ["1=1"]
    params: dict[str, Any] = {"limit": limit}
    if status and status != "all":
        params["status"] = _clean(status, 40).lower()
        where.append("s.status = :status")
    with db_session() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT DISTINCT ON (s.tenant_id)
                    s.id::text,
                    s.tenant_id::text,
                    t.name AS tenant_name,
                    t.slug AS tenant_slug,
                    s.provider,
                    s.provider_subscription_id,
                    s.status,
                    s.plan_code,
                    s.current_period_start::text,
                    s.current_period_end::text,
                    s.cancel_at_period_end,
                    s.updated_at::text,
                    COALESCE((
                        SELECT NULLIF(u.full_name, '')
                        FROM saas_memberships m
                        JOIN saas_users u ON u.id = m.user_id
                        WHERE m.tenant_id = t.id AND m.role = 'owner' AND m.is_active = TRUE
                        ORDER BY m.created_at ASC
                        LIMIT 1
                    ), '') AS owner_name,
                    COALESCE((
                        SELECT u.email
                        FROM saas_memberships m
                        JOIN saas_users u ON u.id = m.user_id
                        WHERE m.tenant_id = t.id AND m.role = 'owner' AND m.is_active = TRUE
                        ORDER BY m.created_at ASC
                        LIMIT 1
                    ), '') AS owner_email
                FROM saas_billing_subscriptions s
                JOIN saas_tenants t ON t.id = s.tenant_id
                WHERE {" AND ".join(where)}
                ORDER BY s.tenant_id, s.updated_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
    return {"subscriptions": [dict(row) for row in rows]}


@router.patch("/subscriptions/{tenant_id}")
def patch_subscription(
    tenant_id: str,
    payload: SubscriptionPatchIn,
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "billing_admin")),
):
    status = _clean(payload.status, 40).lower()
    if status not in SUBSCRIPTION_STATUSES:
        raise HTTPException(status_code=400, detail="invalid_subscription_status")
    plan_code = _clean(payload.plan_code, 40).lower()
    with db_session() as conn:
        tenant = _tenant_exists(conn, tenant_id)
        if plan_code and not _load_plan(conn, plan_code):
            raise HTTPException(status_code=404, detail="plan_not_found")
        effective_plan = plan_code or tenant["plan_code"]
        conn.execute(
            text("UPDATE saas_tenants SET plan_code = :plan_code, status = :tenant_status, updated_at = NOW() WHERE id = CAST(:tenant_id AS uuid)"),
            {
                "tenant_id": tenant_id,
                "plan_code": effective_plan,
                "tenant_status": "past_due" if status == "past_due" else "suspended" if status == "suspended" else "cancelled" if status == "cancelled" else "active",
            },
        )
        row = conn.execute(
            text(
                """
                INSERT INTO saas_billing_subscriptions (
                    tenant_id, provider, provider_subscription_id, status, plan_code,
                    current_period_start, current_period_end, cancel_at_period_end, updated_at
                )
                VALUES (
                    CAST(:tenant_id AS uuid), 'admin', :provider_subscription_id, :status, :plan_code,
                    date_trunc('month', NOW()), COALESCE(CAST(NULLIF(:current_period_end, '') AS timestamp), date_trunc('month', NOW()) + INTERVAL '1 month'),
                    :cancel_at_period_end, NOW()
                )
                ON CONFLICT (provider_subscription_id)
                DO UPDATE SET
                    status = EXCLUDED.status,
                    plan_code = EXCLUDED.plan_code,
                    current_period_end = EXCLUDED.current_period_end,
                    cancel_at_period_end = EXCLUDED.cancel_at_period_end,
                    updated_at = NOW()
                RETURNING id::text, tenant_id::text, provider, provider_subscription_id, status, plan_code,
                          current_period_start::text, current_period_end::text, cancel_at_period_end, updated_at::text
                """
            ),
            {
                "tenant_id": tenant_id,
                "provider_subscription_id": f"admin:{tenant_id}",
                "status": status,
                "plan_code": effective_plan,
                "current_period_end": _clean(payload.current_period_end, 80),
                "cancel_at_period_end": payload.cancel_at_period_end,
            },
        ).mappings().first()
        _audit(conn, actor=ctx, action="admin.subscription.patch", resource_type="subscription", resource_id=tenant_id, tenant_id=tenant_id, details=dict(row or {}))
    return {"ok": True, "subscription": dict(row)}


@router.get("/audit")
def audit_events(
    tenant_id: str = Query("", max_length=80),
    limit: int = Query(100, ge=1, le=500),
    ctx: PlatformAuthContext = Depends(get_current_platform_admin),
):
    where = ["1=1"]
    params: dict[str, Any] = {"limit": limit}
    if tenant_id:
        params["tenant_id"] = tenant_id
        where.append("a.tenant_id = CAST(:tenant_id AS uuid)")
    with db_session() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT a.id, a.tenant_id::text, t.name AS tenant_name, a.actor_user_id::text, u.email AS actor_email,
                       a.action, a.resource_type, a.resource_id, a.details_json, a.created_at::text
                FROM saas_audit_events a
                LEFT JOIN saas_tenants t ON t.id = a.tenant_id
                LEFT JOIN saas_users u ON u.id = a.actor_user_id
                WHERE {" AND ".join(where)}
                ORDER BY a.created_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
    return {"audit": [dict(row) for row in rows]}


@router.get("/operations/queues")
def operation_queues(ctx: PlatformAuthContext = Depends(get_current_platform_admin)):
    with db_session() as conn:
        return {"queues": _queue_counts(conn)}


@router.post("/operations/webhooks/process")
def admin_process_webhooks(
    tenant_id: str = Query("", max_length=80),
    limit: int = Query(50, ge=1, le=200),
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support")),
):
    result = process_due_webhook_events(limit=limit, tenant_id=tenant_id or None)
    with db_session() as conn:
        _audit(conn, actor=ctx, action="admin.operations.webhooks_process", resource_type="queue", details={"tenant_id": tenant_id, "limit": limit, "result": result})
    return {"ok": True, "result": result}


@router.post("/operations/outbound/process")
def admin_process_outbound(
    tenant_id: str = Query("", max_length=80),
    limit: int = Query(50, ge=1, le=200),
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support")),
):
    result = process_due_outbound_messages(limit=limit, tenant_id=tenant_id or None)
    with db_session() as conn:
        _audit(conn, actor=ctx, action="admin.operations.outbound_process", resource_type="queue", details={"tenant_id": tenant_id, "limit": limit, "result": result})
    return {"ok": True, "result": result}


@router.post("/operations/triggers/process")
def admin_process_triggers(
    tenant_id: str = Query("", max_length=80),
    limit: int = Query(50, ge=1, le=200),
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support")),
):
    result = process_due_scheduled_trigger_messages(limit=limit, tenant_id=tenant_id or None)
    with db_session() as conn:
        _audit(conn, actor=ctx, action="admin.operations.triggers_process", resource_type="queue", details={"tenant_id": tenant_id, "limit": limit, "result": result})
    return {"ok": True, "result": result}
