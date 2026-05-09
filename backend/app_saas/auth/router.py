from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app_saas.auth.schemas import (
    LoginIn,
    MeOut,
    RefreshIn,
    RegisterIn,
    SwitchTenantIn,
    TenantMembershipOut,
    TokenOut,
)
from app_saas.db import db_session
from app_saas.shared.security import (
    AuthContext,
    create_token,
    decode_token,
    get_current_user,
    hash_password,
    normalize_email,
    normalize_slug,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["saas-auth"])


def _tenant_rows(conn, user_id: str) -> list[dict]:
    rows = conn.execute(
        text(
            """
            SELECT
                t.id::text AS tenant_id,
                t.slug AS tenant_slug,
                t.name AS tenant_name,
                m.role
            FROM saas_memberships m
            JOIN saas_tenants t ON t.id = m.tenant_id
            WHERE m.user_id = CAST(:user_id AS uuid)
              AND m.is_active = TRUE
              AND t.status = 'active'
            ORDER BY
                CASE m.role
                    WHEN 'owner' THEN 1
                    WHEN 'admin' THEN 2
                    WHEN 'supervisor' THEN 3
                    WHEN 'agent' THEN 4
                    ELSE 5
                END,
                t.created_at ASC
            """
        ),
        {"user_id": user_id},
    ).mappings().all()
    return [dict(row) for row in rows]


def _select_membership(rows: list[dict], tenant_id: str | None = None) -> dict:
    if not rows:
        raise HTTPException(status_code=403, detail="no_active_tenant_membership")
    if tenant_id:
        for row in rows:
            if str(row["tenant_id"]) == str(tenant_id):
                return row
        raise HTTPException(status_code=403, detail="tenant_membership_required")
    return rows[0]


def _token_response(*, user_id: str, email: str, membership: dict, tenants: list[dict], include_refresh: bool) -> TokenOut:
    access_token = create_token(
        user_id=user_id,
        email=email,
        token_type="access",
        tenant_id=membership["tenant_id"],
        role=membership["role"],
    )
    refresh_token = None
    if include_refresh:
        refresh_token = create_token(user_id=user_id, email=email, token_type="refresh")

    return TokenOut(
        access_token=access_token,
        refresh_token=refresh_token,
        tenant_id=membership["tenant_id"],
        role=membership["role"],
        tenants=[TenantMembershipOut(**row) for row in tenants],
    )


@router.post("/register", response_model=TokenOut)
def register(payload: RegisterIn):
    email = normalize_email(payload.email)
    tenant_slug = normalize_slug(payload.tenant_slug or payload.tenant_name)
    if "@" not in email:
        raise HTTPException(status_code=400, detail="valid_email_required")
    if not tenant_slug:
        raise HTTPException(status_code=400, detail="valid_tenant_slug_required")

    try:
        with db_session() as conn:
            user = conn.execute(
                text(
                    """
                    INSERT INTO saas_users (email, full_name, password_hash, password_algo)
                    VALUES (:email, :full_name, :password_hash, 'argon2id')
                    RETURNING id::text, email
                    """
                ),
                {
                    "email": email,
                    "full_name": str(payload.full_name or "").strip(),
                    "password_hash": hash_password(payload.password),
                },
            ).mappings().first()
            tenant = conn.execute(
                text(
                    """
                    INSERT INTO saas_tenants (slug, name)
                    VALUES (:slug, :name)
                    RETURNING id::text, slug, name
                    """
                ),
                {"slug": tenant_slug, "name": str(payload.tenant_name).strip()},
            ).mappings().first()
            conn.execute(
                text(
                    """
                    INSERT INTO saas_memberships (tenant_id, user_id, role)
                    VALUES (CAST(:tenant_id AS uuid), CAST(:user_id AS uuid), 'owner')
                    """
                ),
                {"tenant_id": tenant["id"], "user_id": user["id"]},
            )
            tenants = _tenant_rows(conn, user["id"])
    except IntegrityError:
        raise HTTPException(status_code=409, detail="email_or_tenant_already_exists")

    membership = _select_membership(tenants, str(tenant["id"]))
    return _token_response(
        user_id=user["id"],
        email=user["email"],
        membership=membership,
        tenants=tenants,
        include_refresh=True,
    )


@router.post("/login", response_model=TokenOut)
def login(payload: LoginIn):
    email = normalize_email(payload.email)
    with db_session() as conn:
        user = conn.execute(
            text(
                """
                SELECT id::text, email, password_hash, status
                FROM saas_users
                WHERE LOWER(email) = :email
                LIMIT 1
                """
            ),
            {"email": email},
        ).mappings().first()

        if not user or user["status"] != "active" or not verify_password(payload.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="invalid_credentials")

        tenants = _tenant_rows(conn, user["id"])
        membership = _select_membership(tenants, payload.tenant_id)
        conn.execute(
            text("UPDATE saas_users SET last_login_at = NOW(), updated_at = NOW() WHERE id = CAST(:id AS uuid)"),
            {"id": user["id"]},
        )

    return _token_response(
        user_id=user["id"],
        email=user["email"],
        membership=membership,
        tenants=tenants,
        include_refresh=True,
    )


@router.post("/refresh", response_model=TokenOut)
def refresh(payload: RefreshIn):
    decoded = decode_token(payload.refresh_token, "refresh")
    user_id = str(decoded.get("sub") or "")
    email = normalize_email(str(decoded.get("email") or ""))
    with db_session() as conn:
        tenants = _tenant_rows(conn, user_id)
    membership = _select_membership(tenants, payload.tenant_id)
    return _token_response(
        user_id=user_id,
        email=email,
        membership=membership,
        tenants=tenants,
        include_refresh=False,
    )


@router.post("/switch-tenant", response_model=TokenOut)
def switch_tenant(payload: SwitchTenantIn, ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        tenants = _tenant_rows(conn, ctx.user_id)
    membership = _select_membership(tenants, payload.tenant_id)
    return _token_response(
        user_id=ctx.user_id,
        email=ctx.email,
        membership=membership,
        tenants=tenants,
        include_refresh=False,
    )


@router.get("/me", response_model=MeOut)
def me(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        tenants = _tenant_rows(conn, ctx.user_id)
    return MeOut(
        user_id=ctx.user_id,
        email=ctx.email,
        tenant_id=ctx.tenant_id,
        role=ctx.role,
        tenants=[TenantMembershipOut(**row) for row in tenants],
    )
