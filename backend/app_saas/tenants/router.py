from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app_saas.billing.trials import configured_trial_plan_code, create_trial_subscription
from app_saas.db import db_session
from app_saas.shared.security import AuthContext, get_current_user, normalize_slug, require_role
from app_saas.tenants.schemas import TenantCreateIn, TenantOut, TenantPatchIn
from app_saas.verticals.catalog import normalize_industry_code
from app_saas.verticals.service import apply_industry_pack

router = APIRouter(prefix="/tenants", tags=["saas-tenants"])


@router.get("", response_model=list[TenantOut])
def list_tenants(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    t.id::text AS tenant_id,
                    t.slug,
                    t.name,
                    COALESCE(NULLIF(t.plan_code, ''), 'starter') AS plan_code,
                    t.status,
                    COALESCE(NULLIF(t.industry_code, ''), 'general') AS industry_code,
                    t.vertical_pack_applied_at::text,
                    m.role
                FROM saas_memberships m
                JOIN saas_tenants t ON t.id = m.tenant_id
                WHERE m.user_id = CAST(:user_id AS uuid)
                  AND m.is_active = TRUE
                ORDER BY t.name ASC
                """
            ),
            {"user_id": ctx.user_id},
        ).mappings().all()
    return [TenantOut(**dict(row)) for row in rows]


@router.post("", response_model=TenantOut)
def create_tenant(payload: TenantCreateIn, ctx: AuthContext = Depends(get_current_user)):
    slug = normalize_slug(payload.slug or payload.name)
    industry_code = normalize_industry_code(payload.industry_code)
    if not slug:
        raise HTTPException(status_code=400, detail="valid_tenant_slug_required")
    try:
        with db_session() as conn:
            trial_plan_code = configured_trial_plan_code(conn)
            tenant = conn.execute(
                text(
                    """
                    INSERT INTO saas_tenants (slug, name, timezone, locale, status, plan_code, industry_code)
                    VALUES (:slug, :name, :timezone, :locale, 'trial', :plan_code, :industry_code)
                    RETURNING id::text AS tenant_id, slug, name, plan_code, status, industry_code, vertical_pack_applied_at::text
                    """
                ),
                {
                    "slug": slug,
                    "name": payload.name.strip(),
                    "timezone": payload.timezone.strip(),
                    "locale": payload.locale.strip(),
                    "plan_code": trial_plan_code,
                    "industry_code": industry_code,
                },
            ).mappings().first()
            conn.execute(
                text(
                    """
                    INSERT INTO saas_memberships (tenant_id, user_id, role)
                    VALUES (CAST(:tenant_id AS uuid), CAST(:user_id AS uuid), 'owner')
                    """
                ),
                {"tenant_id": tenant["tenant_id"], "user_id": ctx.user_id},
            )
            create_trial_subscription(conn, tenant["tenant_id"], trial_plan_code)
            vertical = apply_industry_pack(conn, tenant["tenant_id"], ctx.user_id, industry_code, create_agents=False)
            tenant = {**dict(tenant), **(vertical.get("tenant") or {})}
    except IntegrityError:
        raise HTTPException(status_code=409, detail="tenant_slug_already_exists")

    return TenantOut(**dict(tenant), role="owner")


@router.patch("/{tenant_id}", response_model=TenantOut)
def patch_tenant(
    tenant_id: str,
    payload: TenantPatchIn,
    ctx: AuthContext = Depends(require_role("owner", "admin")),
):
    if str(tenant_id) != ctx.tenant_id:
        raise HTTPException(status_code=403, detail="switch_to_tenant_before_editing")
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="no_fields_to_update")

    updates = ["updated_at = NOW()"]
    params = {"tenant_id": tenant_id}
    for key in ("name", "timezone", "locale"):
        if key in data and data[key] is not None:
            updates.append(f"{key} = :{key}")
            params[key] = str(data[key]).strip()

    with db_session() as conn:
        row = conn.execute(
            text(
                f"""
                UPDATE saas_tenants
                SET {", ".join(updates)}
                WHERE id = CAST(:tenant_id AS uuid)
                RETURNING id::text AS tenant_id, slug, name, plan_code, status, industry_code, vertical_pack_applied_at::text
                """
            ),
            params,
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="tenant_not_found")

    return TenantOut(**dict(row), role=ctx.role)
