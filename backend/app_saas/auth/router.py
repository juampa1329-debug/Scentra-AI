from __future__ import annotations

import contextlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app_saas.auth.schemas import (
    LoginIn,
    MeOut,
    MfaChallengeOut,
    MfaVerifyIn,
    PasswordChangeIn,
    PasswordForgotIn,
    PasswordForgotOut,
    ProfilePatchIn,
    PasswordResetIn,
    RefreshIn,
    RegisterIn,
    SecurityStatusOut,
    SwitchTenantIn,
    TeamMembershipPatchIn,
    TeamUserCreateIn,
    TenantMembershipOut,
    TwoFactorPatchIn,
    TokenOut,
)
from app_saas.billing.trials import configured_trial_plan_code, create_trial_subscription
from app_saas.config import settings
from app_saas.db import db_session, set_tenant_context
from app_saas.shared.captcha import verify_captcha_or_raise
from app_saas.shared.email import send_alert_email, send_password_reset_email, send_welcome_email, smtp_is_configured
from app_saas.shared.mfa import create_mfa_challenge, role_requires_mfa, send_security_notice, verify_mfa_code
from app_saas.shared.request_meta import client_ip, user_agent
from app_saas.shared.security import (
    AuthContext,
    clear_login_lock,
    create_token,
    decode_token,
    get_current_user,
    hash_secret,
    hash_password,
    increment_failed_login,
    normalize_email,
    normalize_slug,
    verify_password,
)
from app_saas.shared.security_events import enforce_auth_rate_limits, rate_limit_key, record_security_event
from app_saas.verticals.catalog import normalize_industry_code
from app_saas.verticals.service import apply_industry_pack

router = APIRouter(prefix="/auth", tags=["saas-auth"])

TWO_FACTOR_METHODS = {"none", "email_otp"}
TEAM_ROLES = {"owner", "admin", "supervisor", "agent", "viewer"}
TEAM_ADMIN_ROLES = {"owner", "admin"}
TEAM_ROLE_LABELS = {
    "owner": "Propietario",
    "admin": "Administrador",
    "supervisor": "Supervisor",
    "agent": "Agente",
    "viewer": "Lector",
}


def _role_label(role: object) -> str:
    value = str(role or "").strip().lower()
    return TEAM_ROLE_LABELS.get(value, value.replace("_", " ").title() if value else "Usuario")


def _json(value) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def _reset_url(raw_token: str) -> str:
    base = str(settings.scentra_app_public_url or "").rstrip("/") or "http://localhost:5174"
    path = str(settings.saas_password_reset_path or "/?reset_token=")
    if path.startswith("http://") or path.startswith("https://"):
        return f"{path}{quote(raw_token)}"
    return f"{base}{path}{quote(raw_token)}"


def _expiry_label(expires_at: datetime) -> str:
    bogota = timezone(timedelta(hours=-5), name="America/Bogota")
    local = expires_at.astimezone(bogota)
    return local.strftime("%d/%m/%Y %I:%M %p hora Colombia")


def _tenant_rows(conn, user_id: str) -> list[dict]:
    rows = conn.execute(
        text(
            """
            SELECT
                t.id::text AS tenant_id,
                t.slug AS tenant_slug,
                t.name AS tenant_name,
                t.status AS tenant_status,
                COALESCE(NULLIF(t.plan_code, ''), 'starter') AS plan_code,
                COALESCE(NULLIF(t.industry_code, ''), 'general') AS industry_code,
                t.vertical_pack_applied_at::text,
                COALESCE(s.status, 'none') AS subscription_status,
                CASE WHEN COALESCE(s.status, '') = 'trial' THEN s.current_period_end::text ELSE NULL END AS trial_ends_at,
                m.role
            FROM saas_memberships m
            JOIN saas_tenants t ON t.id = m.tenant_id
            LEFT JOIN LATERAL (
                SELECT status, current_period_end
                FROM saas_billing_subscriptions
                WHERE tenant_id = t.id
                ORDER BY updated_at DESC
                LIMIT 1
            ) s ON TRUE
            WHERE m.user_id = CAST(:user_id AS uuid)
              AND m.is_active = TRUE
              AND t.status IN ('active', 'trial')
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


def _tenant_admin_contacts(conn, tenant_id: str, *, exclude_user_id: str = "") -> list[dict]:
    rows = conn.execute(
        text(
            """
            SELECT DISTINCT u.id::text AS user_id, u.email, u.full_name, m.role
            FROM saas_memberships m
            JOIN saas_users u ON u.id = m.user_id
            WHERE m.tenant_id = CAST(:tenant_id AS uuid)
              AND m.is_active = TRUE
              AND m.role IN ('owner', 'admin')
              AND u.status = 'active'
              AND (:exclude_user_id = '' OR u.id <> CAST(NULLIF(:exclude_user_id, '') AS uuid))
            ORDER BY m.role ASC, u.email ASC
            LIMIT 20
            """
        ),
        {"tenant_id": tenant_id, "exclude_user_id": exclude_user_id or ""},
    ).mappings().all()
    return [dict(row) for row in rows]


def _tenant_name(conn, tenant_id: str) -> str:
    return str(
        conn.execute(
            text("SELECT name FROM saas_tenants WHERE id = CAST(:tenant_id AS uuid) LIMIT 1"),
            {"tenant_id": tenant_id},
        ).scalar()
        or ""
    )


def _mfa_required_for_user(user: dict, membership: dict) -> bool:
    method = str(user.get("two_factor_method") or "none").strip().lower()
    enabled = bool(user.get("two_factor_enabled")) and method == "email_otp"
    required_by_role = role_requires_mfa(str(membership.get("role") or ""), settings.saas_mfa_required_roles)
    return enabled or required_by_role


def _token_response(*, user_id: str, email: str, membership: dict, tenants: list[dict], include_refresh: bool, mfa_verified: bool = False) -> TokenOut:
    access_token = create_token(
        user_id=user_id,
        email=email,
        token_type="access",
        tenant_id=membership["tenant_id"],
        role=membership["role"],
        mfa_verified=mfa_verified,
    )
    refresh_token = None
    if include_refresh:
        refresh_token = create_token(user_id=user_id, email=email, token_type="refresh", mfa_verified=mfa_verified)

    return TokenOut(
        access_token=access_token,
        refresh_token=refresh_token,
        tenant_id=membership["tenant_id"],
        role=membership["role"],
        tenants=[TenantMembershipOut(**row) for row in tenants],
    )


@router.post("/register", response_model=TokenOut)
def register(payload: RegisterIn, request: Request):
    email = normalize_email(payload.email)
    tenant_slug = normalize_slug(payload.tenant_slug or payload.tenant_name)
    industry_code = normalize_industry_code(payload.industry_code)
    if "@" not in email:
        raise HTTPException(status_code=400, detail="valid_email_required")
    if not tenant_slug:
        raise HTTPException(status_code=400, detail="valid_tenant_slug_required")

    rate_key = rate_limit_key(action="auth.register", principal=email or tenant_slug, request=request)
    with db_session() as conn:
        enforce_auth_rate_limits(
            conn,
            event_type="auth.register",
            rate_key=rate_key,
            combined_limit=5,
            principal_limit=5,
            ip_limit=20,
            window_seconds=3600,
            request=request,
            principal=email,
            count_statuses=("attempt", "failed", "blocked"),
        )

    try:
        verify_captcha_or_raise(token=payload.captcha_token, provider=payload.captcha_provider, request=request)
    except HTTPException as exc:
        with contextlib.suppress(Exception):
            with db_session() as conn:
                record_security_event(
                    conn,
                    event_type="auth.register",
                    status="blocked",
                    request=request,
                    principal=email,
                    rate_key=rate_key,
                    reason="captcha_rejected",
                    details={"detail": exc.detail},
                )
        raise exc

    password_hash = hash_password(payload.password)
    try:
        with db_session() as conn:
            record_security_event(
                conn,
                event_type="auth.register",
                status="attempt",
                request=request,
                principal=email,
                rate_key=rate_key,
                details={"tenant_slug": tenant_slug},
            )
            user = conn.execute(
                text(
                    """
                    INSERT INTO saas_users (email, full_name, password_hash, password_algo, password_changed_at)
                    VALUES (:email, :full_name, :password_hash, 'argon2id', NOW())
                    RETURNING id::text, email
                    """
                ),
                {
                    "email": email,
                    "full_name": str(payload.full_name or "").strip(),
                    "password_hash": password_hash,
                },
            ).mappings().first()
            trial_plan_code = configured_trial_plan_code(conn)
            tenant = conn.execute(
                text(
                    """
                    INSERT INTO saas_tenants (slug, name, status, plan_code, industry_code)
                    VALUES (:slug, :name, 'trial', :plan_code, :industry_code)
                    RETURNING id::text, slug, name
                    """
                ),
                {"slug": tenant_slug, "name": str(payload.tenant_name).strip(), "plan_code": trial_plan_code, "industry_code": industry_code},
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
            create_trial_subscription(conn, tenant["id"], trial_plan_code)
            try:
                with conn.begin_nested():
                    apply_industry_pack(conn, tenant["id"], user["id"], industry_code, create_agents=False)
            except Exception as exc:
                record_security_event(
                    conn,
                    event_type="auth.register",
                    status="warning",
                    request=request,
                    principal=email,
                    rate_key=rate_key,
                    tenant_id=tenant["id"],
                    user_id=user["id"],
                    reason="vertical_pack_apply_failed",
                    details={"industry_code": industry_code, "error": f"{type(exc).__name__}: {str(exc)[:300]}"},
                )
            tenants = _tenant_rows(conn, user["id"])
            record_security_event(
                conn,
                event_type="auth.register",
                status="success",
                request=request,
                principal=email,
                rate_key=rate_key,
                tenant_id=tenant["id"],
                user_id=user["id"],
            )
    except IntegrityError:
        with db_session() as conn:
            record_security_event(
                conn,
                event_type="auth.register",
                status="failed",
                request=request,
                principal=email,
                rate_key=rate_key,
                reason="email_or_tenant_already_exists",
                details={"tenant_slug": tenant_slug},
            )
        raise HTTPException(status_code=409, detail="email_or_tenant_already_exists")

    membership = _select_membership(tenants, str(tenant["id"]))
    return _token_response(
        user_id=user["id"],
        email=user["email"],
        membership=membership,
        tenants=tenants,
        include_refresh=True,
    )


@router.post("/login", response_model=TokenOut | MfaChallengeOut)
def login(payload: LoginIn, request: Request):
    email = normalize_email(payload.email)
    auth_error: HTTPException | None = None
    token_payload: TokenOut | MfaChallengeOut | None = None
    rate_key = rate_limit_key(action="auth.login", principal=email, request=request)
    with db_session() as conn:
        enforce_auth_rate_limits(
            conn,
            event_type="auth.login",
            rate_key=rate_key,
            combined_limit=8,
            principal_limit=10,
            ip_limit=40,
            window_seconds=900,
            request=request,
            principal=email,
            count_statuses=("failed", "blocked"),
        )
        try:
            verify_captcha_or_raise(token=payload.captcha_token, provider=payload.captcha_provider, request=request)
        except HTTPException as exc:
            auth_error = exc
            record_security_event(
                conn,
                event_type="auth.login",
                status="blocked",
                request=request,
                principal=email,
                rate_key=rate_key,
                reason="captcha_rejected",
                details={"detail": exc.detail},
            )

        if not auth_error:
            user = conn.execute(
                text(
                    """
                    SELECT id::text, email, password_hash, status, locked_until::text,
                           two_factor_enabled, two_factor_method
                    FROM saas_users
                    WHERE LOWER(email) = :email
                    LIMIT 1
                    """
                ),
                {"email": email},
            ).mappings().first()

            if user and user.get("locked_until"):
                locked = conn.execute(
                    text(
                        """
                        SELECT locked_until > NOW() AS is_locked,
                               locked_until::text AS locked_until
                        FROM saas_users
                        WHERE id = CAST(:user_id AS uuid)
                        LIMIT 1
                        """
                    ),
                    {"user_id": user["id"]},
                ).mappings().first()
                if locked and locked["is_locked"]:
                    record_security_event(
                        conn,
                        event_type="auth.login",
                        status="blocked",
                        request=request,
                        principal=email,
                        rate_key=rate_key,
                        user_id=user["id"],
                        reason="account_temporarily_locked",
                        details={"locked_until": locked["locked_until"]},
                    )
                    auth_error = HTTPException(
                        status_code=423,
                        detail={"code": "account_temporarily_locked", "locked_until": locked["locked_until"]},
                    )

            if not auth_error and (not user or user["status"] != "active" or not verify_password(payload.password, user["password_hash"])):
                lock_info = increment_failed_login(conn, user["id"]) if user and user["status"] == "active" else {}
                record_security_event(
                    conn,
                    event_type="auth.login",
                    status="failed",
                    request=request,
                    principal=email,
                    rate_key=rate_key,
                    user_id=user["id"] if user else None,
                    reason="invalid_credentials",
                    details={"failed_login_count": lock_info.get("failed_login_count"), "locked_until": lock_info.get("locked_until")},
                )
                auth_error = HTTPException(status_code=401, detail="invalid_credentials")
            elif not auth_error:
                tenants = _tenant_rows(conn, user["id"])
                membership = _select_membership(tenants, payload.tenant_id)
                if _mfa_required_for_user(dict(user), membership):
                    token_payload = MfaChallengeOut(
                        **create_mfa_challenge(
                            conn,
                            request=request,
                            user_id=user["id"],
                            email=user["email"],
                            tenant_id=membership["tenant_id"],
                            role=membership["role"],
                            context="tenant",
                            event_type="auth.login.mfa",
                            rate_key=rate_key,
                        )
                    )
                else:
                    clear_login_lock(conn, user["id"])
                    conn.execute(
                        text("UPDATE saas_users SET last_login_at = NOW(), updated_at = NOW() WHERE id = CAST(:id AS uuid)"),
                        {"id": user["id"]},
                    )
                    record_security_event(
                        conn,
                        event_type="auth.login",
                        status="success",
                        request=request,
                        principal=email,
                        rate_key=rate_key,
                        tenant_id=membership["tenant_id"],
                        user_id=user["id"],
                    )
                    token_payload = _token_response(
                        user_id=user["id"],
                        email=user["email"],
                        membership=membership,
                        tenants=tenants,
                        include_refresh=True,
                    )

    if auth_error:
        raise auth_error
    if token_payload is None:
        raise HTTPException(status_code=500, detail="auth_response_unavailable")
    return token_payload


@router.post("/login/verify-otp", response_model=TokenOut)
def verify_login_otp(payload: MfaVerifyIn, request: Request):
    rate_key = rate_limit_key(action="auth.login.mfa_verify", principal=payload.challenge_token[:24], request=request)
    with db_session() as conn:
        enforce_auth_rate_limits(
            conn,
            event_type="auth.login.mfa_verify",
            rate_key=rate_key,
            combined_limit=10,
            principal_limit=10,
            ip_limit=40,
            window_seconds=900,
            request=request,
            principal=payload.challenge_token[:24],
            count_statuses=("failed", "blocked"),
        )
        challenge = verify_mfa_code(
            conn,
            request=request,
            challenge_token=payload.challenge_token,
            code=payload.code,
            context="tenant",
            event_type="auth.login.mfa_verify",
            rate_key=rate_key,
        )
        tenants = _tenant_rows(conn, challenge["user_id"])
        membership = _select_membership(tenants, challenge.get("tenant_id"))
        clear_login_lock(conn, challenge["user_id"])
        conn.execute(
            text("UPDATE saas_users SET last_login_at = NOW(), updated_at = NOW() WHERE id = CAST(:id AS uuid)"),
            {"id": challenge["user_id"]},
        )
        record_security_event(
            conn,
            event_type="auth.login",
            status="success",
            request=request,
            principal=challenge["email"],
            rate_key=rate_key,
            tenant_id=membership["tenant_id"],
            user_id=challenge["user_id"],
            reason="mfa_verified",
        )
        send_security_notice(
            challenge["email"],
            "Nuevo ingreso protegido en Scentra",
            "Se completo un ingreso con segundo factor en tu cuenta de Scentra. Si no fuiste tu, cambia tu clave de inmediato.",
        )
    return _token_response(
        user_id=challenge["user_id"],
        email=challenge["email"],
        membership=membership,
        tenants=tenants,
        include_refresh=True,
        mfa_verified=True,
    )


@router.post("/password/forgot", response_model=PasswordForgotOut)
def forgot_password(payload: PasswordForgotIn, request: Request):
    email = normalize_email(payload.email)
    rate_key = rate_limit_key(action="auth.password_forgot", principal=email, request=request)
    response = PasswordForgotOut(email_sent=False)
    auth_error: HTTPException | None = None
    with db_session() as conn:
        enforce_auth_rate_limits(
            conn,
            event_type="auth.password_forgot",
            rate_key=rate_key,
            combined_limit=5,
            principal_limit=5,
            ip_limit=20,
            window_seconds=3600,
            request=request,
            principal=email,
            count_statuses=("attempt", "failed", "blocked"),
        )
        try:
            verify_captcha_or_raise(token=payload.captcha_token, provider=payload.captcha_provider, request=request)
        except HTTPException as exc:
            auth_error = exc
            record_security_event(
                conn,
                event_type="auth.password_forgot",
                status="blocked",
                request=request,
                principal=email,
                rate_key=rate_key,
                reason="captcha_rejected",
                details={"detail": exc.detail},
            )
        if not auth_error:
            record_security_event(conn, event_type="auth.password_forgot", status="attempt", request=request, principal=email, rate_key=rate_key)
            user = conn.execute(
                text(
                    """
                    SELECT id::text, email, status
                    FROM saas_users
                    WHERE LOWER(email) = :email
                    LIMIT 1
                    """
                ),
                {"email": email},
            ).mappings().first()
            if user and user["status"] == "active":
                raw_token = secrets.token_urlsafe(36)
                token_hash = hash_secret(raw_token)
                reset_url = _reset_url(raw_token)
                expires_minutes = max(5, int(settings.saas_password_reset_minutes or 30))
                expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
                conn.execute(
                    text(
                        """
                        UPDATE saas_password_reset_tokens
                        SET status = 'superseded', updated_at = NOW()
                        WHERE user_id = CAST(:user_id AS uuid)
                          AND status = 'pending'
                        """
                    ),
                    {"user_id": user["id"]},
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO saas_password_reset_tokens (
                            user_id, email, token_hash, requested_ip, user_agent, expires_at
                        )
                        VALUES (CAST(:user_id AS uuid), :email, :token_hash, :requested_ip, :user_agent, :expires_at)
                        """
                    ),
                    {
                        "user_id": user["id"],
                        "email": email,
                        "token_hash": token_hash,
                        "requested_ip": client_ip(request)[:120],
                        "user_agent": user_agent(request),
                        "expires_at": expires_at.replace(tzinfo=None),
                    },
                )
                email_sent = False
                email_error = ""
                if smtp_is_configured():
                    try:
                        email_sent = send_password_reset_email(to_email=email, reset_url=reset_url, expires_label=_expiry_label(expires_at))
                    except Exception as exc:
                        email_error = str(exc)[:240]
                response.email_sent = email_sent
                if settings.is_local:
                    response.dev_reset_token = raw_token
                    response.dev_reset_url = reset_url
                record_security_event(
                    conn,
                    event_type="auth.password_forgot",
                    status="success",
                    request=request,
                    principal=email,
                    rate_key=rate_key,
                    user_id=user["id"],
                    reason="reset_token_created",
                    details={"email_sent": email_sent, "smtp_configured": smtp_is_configured(), "email_error": email_error},
                )
            else:
                record_security_event(
                    conn,
                    event_type="auth.password_forgot",
                    status="success",
                    request=request,
                    principal=email,
                    rate_key=rate_key,
                    reason="account_not_revealed",
                )
    if auth_error:
        raise auth_error
    return response


@router.post("/password/reset")
def reset_password(payload: PasswordResetIn, request: Request):
    token_hash = hash_secret(payload.token)
    rate_key = rate_limit_key(action="auth.password_reset", principal=token_hash[:40], request=request)
    auth_error: HTTPException | None = None
    with db_session() as conn:
        enforce_auth_rate_limits(
            conn,
            event_type="auth.password_reset",
            rate_key=rate_key,
            combined_limit=6,
            principal_limit=6,
            ip_limit=30,
            window_seconds=3600,
            request=request,
            principal=token_hash[:80],
            count_statuses=("failed", "blocked"),
        )
        try:
            verify_captcha_or_raise(token=payload.captcha_token, provider=payload.captcha_provider, request=request)
        except HTTPException as exc:
            auth_error = exc
            record_security_event(
                conn,
                event_type="auth.password_reset",
                status="blocked",
                request=request,
                principal=token_hash[:80],
                rate_key=rate_key,
                reason="captcha_rejected",
                details={"detail": exc.detail},
            )
        if not auth_error:
            row = conn.execute(
                text(
                    """
                    SELECT t.id::text AS token_id, t.user_id::text, u.email, u.status AS user_status
                    FROM saas_password_reset_tokens t
                    JOIN saas_users u ON u.id = t.user_id
                    WHERE t.token_hash = :token_hash
                      AND t.status = 'pending'
                      AND t.expires_at > NOW()
                    LIMIT 1
                    """
                ),
                {"token_hash": token_hash},
            ).mappings().first()
            if not row or row["user_status"] != "active":
                record_security_event(
                    conn,
                    event_type="auth.password_reset",
                    status="failed",
                    request=request,
                    principal=token_hash[:80],
                    rate_key=rate_key,
                    reason="invalid_or_expired_reset_token",
                )
                auth_error = HTTPException(status_code=400, detail="invalid_or_expired_reset_token")
            else:
                conn.execute(
                    text(
                        """
                        UPDATE saas_users
                        SET password_hash = :password_hash,
                            password_algo = 'argon2id',
                            failed_login_count = 0,
                            locked_until = NULL,
                            password_changed_at = NOW(),
                            updated_at = NOW()
                        WHERE id = CAST(:user_id AS uuid)
                        """
                    ),
                    {"user_id": row["user_id"], "password_hash": hash_password(payload.new_password)},
                )
                conn.execute(
                    text(
                        """
                        UPDATE saas_password_reset_tokens
                        SET status = 'used', used_at = NOW(), updated_at = NOW()
                        WHERE id = CAST(:token_id AS uuid)
                        """
                    ),
                    {"token_id": row["token_id"]},
                )
                record_security_event(
                    conn,
                    event_type="auth.password_reset",
                    status="success",
                    request=request,
                    principal=row["email"],
                    rate_key=rate_key,
                    user_id=row["user_id"],
                    reason="password_reset_completed",
                )
                send_security_notice(
                    row["email"],
                    "Clave actualizada en Scentra",
                    "Tu clave fue actualizada mediante recuperacion de cuenta. Si no fuiste tu, contacta al administrador de Scentra.",
                )
    if auth_error:
        raise auth_error
    return {"ok": True}


@router.post("/password/change")
def change_password(payload: PasswordChangeIn, request: Request, ctx: AuthContext = Depends(get_current_user)):
    rate_key = rate_limit_key(action="auth.password_change", principal=ctx.email, request=request)
    auth_error: HTTPException | None = None
    with db_session() as conn:
        enforce_auth_rate_limits(
            conn,
            event_type="auth.password_change",
            rate_key=rate_key,
            combined_limit=6,
            principal_limit=10,
            ip_limit=30,
            window_seconds=3600,
            request=request,
            principal=ctx.email,
            count_statuses=("failed", "blocked"),
        )
        user = conn.execute(
            text(
                """
                SELECT id::text, password_hash, status
                FROM saas_users
                WHERE id = CAST(:user_id AS uuid)
                LIMIT 1
                """
            ),
            {"user_id": ctx.user_id},
        ).mappings().first()
        if not user or user["status"] != "active" or not verify_password(payload.current_password, user["password_hash"]):
            record_security_event(
                conn,
                event_type="auth.password_change",
                status="failed",
                request=request,
                principal=ctx.email,
                rate_key=rate_key,
                user_id=ctx.user_id,
                reason="invalid_current_password",
            )
            auth_error = HTTPException(status_code=401, detail="invalid_current_password")
        if not auth_error:
            conn.execute(
                text(
                    """
                    UPDATE saas_users
                    SET password_hash = :password_hash,
                        password_algo = 'argon2id',
                        password_changed_at = NOW(),
                        failed_login_count = 0,
                        locked_until = NULL,
                        updated_at = NOW()
                    WHERE id = CAST(:user_id AS uuid)
                    """
                ),
                {"user_id": ctx.user_id, "password_hash": hash_password(payload.new_password)},
            )
            record_security_event(
                conn,
                event_type="auth.password_change",
                status="success",
                request=request,
                principal=ctx.email,
                rate_key=rate_key,
                tenant_id=ctx.tenant_id,
                user_id=ctx.user_id,
            )
            send_security_notice(
                ctx.email,
                "Clave actualizada en Scentra",
                "Tu clave fue actualizada desde la configuracion de seguridad de Scentra.",
            )
    if auth_error:
        raise auth_error
    return {"ok": True}


@router.patch("/profile")
def update_profile(payload: ProfilePatchIn, request: Request, ctx: AuthContext = Depends(get_current_user)):
    full_name = str(payload.full_name or "").strip()
    next_email = normalize_email(payload.email or ctx.email)
    profile_patch = {
        "phone": str(payload.phone or "").strip(),
        "role_label": str(payload.role_label or "").strip(),
        "avatar_url": str(payload.avatar_url or "").strip(),
    }
    if next_email and "@" not in next_email:
        raise HTTPException(status_code=400, detail="valid_email_required")
    with db_session() as conn:
        row = conn.execute(
            text(
                """
                SELECT id::text, email, password_hash, status, full_name, profile_json
                FROM saas_users
                WHERE id = CAST(:user_id AS uuid)
                LIMIT 1
                """
            ),
            {"user_id": ctx.user_id},
        ).mappings().first()
        if not row or row["status"] != "active":
            raise HTTPException(status_code=404, detail="user_not_found")
        email_changed = next_email and next_email != normalize_email(row["email"])
        if email_changed:
            if not payload.current_password or not verify_password(payload.current_password, row["password_hash"]):
                raise HTTPException(status_code=401, detail="invalid_current_password")
            duplicate = conn.execute(
                text("SELECT id::text FROM saas_users WHERE email = :email AND id <> CAST(:user_id AS uuid) LIMIT 1"),
                {"email": next_email, "user_id": ctx.user_id},
            ).mappings().first()
            if duplicate:
                raise HTTPException(status_code=409, detail="email_already_registered")
        updated = conn.execute(
            text(
                """
                UPDATE saas_users
                SET email = :email,
                    full_name = :full_name,
                    profile_json = COALESCE(profile_json, '{}'::jsonb) || CAST(:profile_json AS jsonb),
                    updated_at = NOW()
                WHERE id = CAST(:user_id AS uuid)
                RETURNING id::text, email, full_name, profile_json
                """
            ),
            {
                "user_id": ctx.user_id,
                "email": next_email or row["email"],
                "full_name": full_name or row["full_name"] or "",
                "profile_json": _json(profile_patch),
            },
        ).mappings().first()
        record_security_event(
            conn,
            event_type="auth.profile_update",
            status="success",
            request=request,
            principal=ctx.email,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            reason="email_changed" if email_changed else "profile_updated",
        )
    return {"ok": True, "user": dict(updated or {})}


@router.get("/team")
def list_team(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        rows = conn.execute(
            text(
                """
                SELECT m.id::text, m.role, m.is_active, m.created_at::text, m.updated_at::text,
                       u.id::text AS user_id, u.email, u.full_name, u.status AS user_status,
                       u.last_login_at::text, u.profile_json
                FROM saas_memberships m
                JOIN saas_users u ON u.id = m.user_id
                WHERE m.tenant_id = CAST(:tenant_id AS uuid)
                ORDER BY
                  CASE m.role WHEN 'owner' THEN 1 WHEN 'admin' THEN 2 WHEN 'supervisor' THEN 3 WHEN 'agent' THEN 4 ELSE 5 END,
                  u.email ASC
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().all()
    return {"ok": True, "members": [dict(row) for row in rows], "roles": sorted(TEAM_ROLES)}


@router.post("/team/users")
def create_team_user(payload: TeamUserCreateIn, request: Request, ctx: AuthContext = Depends(get_current_user)):
    if ctx.role not in TEAM_ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="insufficient_role")
    role = str(payload.role or "agent").strip().lower()
    if role not in TEAM_ROLES:
        raise HTTPException(status_code=400, detail="invalid_team_role")
    if role == "owner" and ctx.role != "owner":
        raise HTTPException(status_code=403, detail="owner_role_requires_owner")
    email = normalize_email(payload.email)
    if "@" not in email:
        raise HTTPException(status_code=400, detail="valid_email_required")
    created = False
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        user = conn.execute(
            text("SELECT id::text, email FROM saas_users WHERE email = :email LIMIT 1"),
            {"email": email},
        ).mappings().first()
        if not user:
            if not payload.password or len(payload.password) < 8:
                raise HTTPException(status_code=400, detail="password_required_for_new_user")
            user = conn.execute(
                text(
                    """
                    INSERT INTO saas_users (email, full_name, password_hash, password_algo, password_changed_at)
                    VALUES (:email, :full_name, :password_hash, 'argon2id', NOW())
                    RETURNING id::text, email
                    """
                ),
                {
                    "email": email,
                    "full_name": str(payload.full_name or "").strip(),
                    "password_hash": hash_password(payload.password),
                },
            ).mappings().first()
            created = True
        elif payload.full_name:
            conn.execute(
                text("UPDATE saas_users SET full_name = :full_name, updated_at = NOW() WHERE id = CAST(:user_id AS uuid)"),
                {"user_id": user["id"], "full_name": str(payload.full_name or "").strip()},
            )
        membership = conn.execute(
            text(
                """
                INSERT INTO saas_memberships (tenant_id, user_id, role, is_active)
                VALUES (CAST(:tenant_id AS uuid), CAST(:user_id AS uuid), :role, TRUE)
                ON CONFLICT (tenant_id, user_id)
                DO UPDATE SET role = EXCLUDED.role, is_active = TRUE, updated_at = NOW()
                RETURNING id::text, role, is_active, updated_at::text
                """
            ),
            {"tenant_id": ctx.tenant_id, "user_id": user["id"], "role": role},
        ).mappings().first()
        record_security_event(
            conn,
            event_type="auth.team_user_upsert",
            status="success",
            request=request,
            principal=email,
            tenant_id=ctx.tenant_id,
            user_id=user["id"],
            reason="created" if created else "membership_upserted",
            details={"role": role, "actor_user_id": ctx.user_id},
        )
        email_sent = False
        if payload.send_email and smtp_is_configured():
            tenant_name = _tenant_name(conn, ctx.tenant_id)
            with contextlib.suppress(Exception):
                email_sent = send_welcome_email(
                    to_email=email,
                    full_name=str(payload.full_name or "").strip(),
                    tenant_name=tenant_name,
                    role_label=_role_label(role),
                    login_url=str(settings.scentra_app_public_url or "").rstrip("/"),
                    temporary_password=payload.password if created else "",
                )
            alert_body = (
                f"Se {'creó' if created else 'actualizó'} el acceso de {email} en {tenant_name or 'tu empresa'}.\n\n"
                f"Rol asignado: {_role_label(role)}.\n"
                f"Acción realizada por: {ctx.email}."
            )
            for admin in _tenant_admin_contacts(conn, ctx.tenant_id, exclude_user_id=ctx.user_id):
                with contextlib.suppress(Exception):
                    send_alert_email(to_email=admin["email"], subject="Alerta de usuarios Scentra", body=alert_body, severity="info")
    return {"ok": True, "created": created, "email_sent": email_sent, "membership": dict(membership or {}), "user_id": user["id"]}


@router.patch("/team/memberships/{membership_id}")
def update_team_membership(membership_id: str, payload: TeamMembershipPatchIn, request: Request, ctx: AuthContext = Depends(get_current_user)):
    if ctx.role not in TEAM_ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="insufficient_role")
    role = str(payload.role or "").strip().lower()
    if role and role not in TEAM_ROLES:
        raise HTTPException(status_code=400, detail="invalid_team_role")
    if role == "owner" and ctx.role != "owner":
        raise HTTPException(status_code=403, detail="owner_role_requires_owner")
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        current = conn.execute(
            text(
                """
                SELECT m.id::text, m.user_id::text, m.role, m.is_active, u.email, u.full_name
                FROM saas_memberships m
                JOIN saas_users u ON u.id = m.user_id
                WHERE m.id = CAST(:membership_id AS uuid)
                  AND m.tenant_id = CAST(:tenant_id AS uuid)
                LIMIT 1
                """
            ),
            {"membership_id": membership_id, "tenant_id": ctx.tenant_id},
        ).mappings().first()
        if not current:
            raise HTTPException(status_code=404, detail="membership_not_found")
        if str(current["user_id"]) == str(ctx.user_id) and payload.is_active is False:
            raise HTTPException(status_code=400, detail="cannot_deactivate_self")
        row = conn.execute(
            text(
                """
                UPDATE saas_memberships
                SET role = COALESCE(NULLIF(:role, ''), role),
                    is_active = COALESCE(:is_active, is_active),
                    updated_at = NOW()
                WHERE id = CAST(:membership_id AS uuid)
                  AND tenant_id = CAST(:tenant_id AS uuid)
                RETURNING id::text, user_id::text, role, is_active, updated_at::text
                """
            ),
            {"membership_id": membership_id, "tenant_id": ctx.tenant_id, "role": role, "is_active": payload.is_active},
        ).mappings().first()
        record_security_event(
            conn,
            event_type="auth.team_membership_update",
            status="success",
            request=request,
            principal=ctx.email,
            tenant_id=ctx.tenant_id,
            user_id=row["user_id"],
            details={"role": row["role"], "is_active": row["is_active"], "actor_user_id": ctx.user_id},
        )
        if smtp_is_configured():
            tenant_name = _tenant_name(conn, ctx.tenant_id)
            affected_body = (
                f"Tu acceso en {tenant_name or 'Scentra'} fue actualizado.\n\n"
                f"Rol actual: {_role_label(row['role'])}.\n"
                f"Estado: {'activo' if row['is_active'] else 'inactivo'}."
            )
            with contextlib.suppress(Exception):
                send_alert_email(to_email=current["email"], subject="Cambio en tu acceso Scentra", body=affected_body, severity="warning")
            admin_body = (
                f"Se actualizó el usuario {current['email']} en {tenant_name or 'tu empresa'}.\n\n"
                f"Rol actual: {_role_label(row['role'])}.\n"
                f"Estado: {'activo' if row['is_active'] else 'inactivo'}.\n"
                f"Acción realizada por: {ctx.email}."
            )
            for admin in _tenant_admin_contacts(conn, ctx.tenant_id, exclude_user_id=ctx.user_id):
                with contextlib.suppress(Exception):
                    send_alert_email(to_email=admin["email"], subject="Alerta de roles Scentra", body=admin_body, severity="warning")
    return {"ok": True, "membership": dict(row or {})}


@router.get("/security", response_model=SecurityStatusOut)
def security_status(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        row = conn.execute(
            text(
                """
                SELECT two_factor_enabled, two_factor_method, locked_until::text, password_changed_at::text
                FROM saas_users
                WHERE id = CAST(:user_id AS uuid)
                LIMIT 1
                """
            ),
            {"user_id": ctx.user_id},
        ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="user_not_found")
    method = str(row["two_factor_method"] or "none").strip().lower()
    return SecurityStatusOut(
        two_factor_enabled=bool(row["two_factor_enabled"]),
        two_factor_method=method if method in TWO_FACTOR_METHODS else "none",
        locked_until=row["locked_until"],
        password_changed_at=row["password_changed_at"],
    )


@router.patch("/security/2fa", response_model=SecurityStatusOut)
def update_two_factor(payload: TwoFactorPatchIn, request: Request, ctx: AuthContext = Depends(get_current_user)):
    method = str(payload.method or "email_otp").strip().lower()
    if method not in TWO_FACTOR_METHODS - {"none"}:
        raise HTTPException(status_code=400, detail="invalid_two_factor_method")
    if payload.enabled and method == "email_otp" and not smtp_is_configured() and not settings.is_local:
        raise HTTPException(status_code=409, detail="smtp_required_for_email_otp")
    if not payload.enabled:
        method = "none"
    with db_session() as conn:
        row = conn.execute(
            text(
                """
                UPDATE saas_users
                SET two_factor_enabled = :enabled,
                    two_factor_method = :method,
                    updated_at = NOW()
                WHERE id = CAST(:user_id AS uuid)
                RETURNING two_factor_enabled, two_factor_method, locked_until::text, password_changed_at::text
                """
            ),
            {"user_id": ctx.user_id, "enabled": bool(payload.enabled), "method": method},
        ).mappings().first()
        record_security_event(
            conn,
            event_type="auth.two_factor_policy",
            status="success",
            request=request,
            principal=ctx.email,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            reason="two_factor_prepared" if payload.enabled else "two_factor_disabled",
            details={"method": method},
        )
        send_security_notice(
            ctx.email,
            "Cambio de seguridad en Scentra",
            f"El segundo factor fue {'activado' if payload.enabled else 'desactivado'} para tu cuenta de Scentra.",
        )
    if not row:
        raise HTTPException(status_code=404, detail="user_not_found")
    return SecurityStatusOut(
        two_factor_enabled=bool(row["two_factor_enabled"]),
        two_factor_method=str(row["two_factor_method"] or "none"),
        locked_until=row["locked_until"],
        password_changed_at=row["password_changed_at"],
    )


@router.post("/refresh", response_model=TokenOut)
def refresh(payload: RefreshIn):
    decoded = decode_token(payload.refresh_token, "refresh")
    user_id = str(decoded.get("sub") or "")
    email = normalize_email(str(decoded.get("email") or ""))
    with db_session() as conn:
        tenants = _tenant_rows(conn, user_id)
        user = conn.execute(
            text(
                """
                SELECT two_factor_enabled, two_factor_method
                FROM saas_users
                WHERE id = CAST(:user_id AS uuid)
                LIMIT 1
                """
            ),
            {"user_id": user_id},
        ).mappings().first()
    membership = _select_membership(tenants, payload.tenant_id)
    mfa_verified = bool(decoded.get("mfa"))
    if user and _mfa_required_for_user(dict(user), membership) and not mfa_verified:
        raise HTTPException(status_code=401, detail="mfa_required_refresh")
    return _token_response(
        user_id=user_id,
        email=email,
        membership=membership,
        tenants=tenants,
        include_refresh=False,
        mfa_verified=mfa_verified,
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
        user = conn.execute(
            text(
                """
                SELECT email, full_name, profile_json
                FROM saas_users
                WHERE id = CAST(:user_id AS uuid)
                LIMIT 1
                """
            ),
            {"user_id": ctx.user_id},
        ).mappings().first()
    return MeOut(
        user_id=ctx.user_id,
        email=normalize_email(str((user or {}).get("email") or ctx.email)),
        full_name=str((user or {}).get("full_name") or "").strip(),
        profile_json=dict((user or {}).get("profile_json") or {}),
        tenant_id=ctx.tenant_id,
        role=ctx.role,
        tenants=[TenantMembershipOut(**row) for row in tenants],
    )
