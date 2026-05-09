from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app_saas.db import db_session
from app_saas.shared.security import AuthContext, get_current_user, normalize_slug, require_role
from app_saas.tenants.schemas import TenantCreateIn, TenantOut, TenantPatchIn

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
                    t.plan_code,
                    t.status,
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
    if not slug:
        raise HTTPException(status_code=400, detail="valid_tenant_slug_required")
    try:
        with db_session() as conn:
            tenant = conn.execute(
                text(
                    """
                    INSERT INTO saas_tenants (slug, name, timezone, locale)
                    VALUES (:slug, :name, :timezone, :locale)
                    RETURNING id::text AS tenant_id, slug, name, plan_code, status
                    """
                ),
                {
                    "slug": slug,
                    "name": payload.name.strip(),
                    "timezone": payload.timezone.strip(),
                    "locale": payload.locale.strip(),
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
                RETURNING id::text AS tenant_id, slug, name, plan_code, status
                """
            ),
            params,
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="tenant_not_found")

    return TenantOut(**dict(row), role=ctx.role)
