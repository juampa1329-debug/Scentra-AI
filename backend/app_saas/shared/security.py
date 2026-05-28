from __future__ import annotations

import re
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text

from app_saas.config import settings

ROLE_ORDER = {
    "owner": 100,
    "admin": 80,
    "supervisor": 60,
    "agent": 40,
    "viewer": 20,
}

PLATFORM_ROLE_ORDER = {
    "superadmin": 100,
    "platform_admin": 80,
    "billing_admin": 60,
    "support": 40,
    "viewer": 20,
}

_password_hasher = PasswordHasher()


class AuthContext(BaseModel):
    user_id: str
    email: str
    tenant_id: str
    role: str


class PlatformAuthContext(BaseModel):
    user_id: str
    email: str
    platform_role: str


def normalize_email(value: str) -> str:
    return str(value or "").strip().lower()


def normalize_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", str(value or "").strip().lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:80]


def hash_password(password: str) -> str:
    return _password_hasher.hash(str(password or ""))


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bool(_password_hasher.verify(str(password_hash or ""), str(password or "")))
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def login_lock_minutes() -> int:
    return max(1, int(settings.saas_login_lock_minutes or 15))


def login_lock_failed_attempts() -> int:
    return max(1, int(settings.saas_login_lock_failed_attempts or 6))


def increment_failed_login(conn, user_id: str) -> dict:
    row = conn.execute(
        text(
            """
            UPDATE saas_users
            SET failed_login_count = COALESCE(failed_login_count, 0) + 1,
                locked_until = CASE
                    WHEN COALESCE(failed_login_count, 0) + 1 >= :max_attempts
                    THEN NOW() + make_interval(mins => :lock_minutes)
                    ELSE locked_until
                END,
                updated_at = NOW()
            WHERE id = CAST(:user_id AS uuid)
            RETURNING failed_login_count, locked_until::text
            """
        ),
        {
            "user_id": user_id,
            "max_attempts": login_lock_failed_attempts(),
            "lock_minutes": login_lock_minutes(),
        },
    ).mappings().first()
    return dict(row or {})


def clear_login_lock(conn, user_id: str) -> None:
    conn.execute(
        text(
            """
            UPDATE saas_users
            SET failed_login_count = 0,
                locked_until = NULL,
                updated_at = NOW()
            WHERE id = CAST(:user_id AS uuid)
            """
        ),
        {"user_id": user_id},
    )


def new_secret(prefix: str = "whsec") -> str:
    clean_prefix = re.sub(r"[^a-zA-Z0-9_]+", "", str(prefix or "secret"))[:18] or "secret"
    return f"{clean_prefix}_{secrets.token_urlsafe(32)}"


def hash_secret(secret_value: str) -> str:
    material = f"{settings.saas_jwt_secret}:{str(secret_value or '')}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def verify_secret(secret_value: str, expected_hash: str) -> bool:
    if not secret_value or not expected_hash:
        return False
    return secrets.compare_digest(hash_secret(secret_value), str(expected_hash or ""))


def derive_webhook_signature_secret(*, tenant_id: str, provider: str, endpoint_key: str, salt: str) -> str:
    material = f"webhook-signature:{tenant_id}:{provider}:{endpoint_key}:{salt}".encode("utf-8")
    digest = hmac.new(settings.saas_jwt_secret.encode("utf-8"), material, hashlib.sha256).hexdigest()
    return f"whsig_{digest}"


def verify_hmac_sha256_signature(*, secret_value: str, raw_body: bytes, signature_header: str) -> bool:
    signature = str(signature_header or "").strip()
    if not secret_value or not signature:
        return False
    if signature.lower().startswith("sha256="):
        signature = signature.split("=", 1)[1].strip()
    expected = hmac.new(secret_value.encode("utf-8"), raw_body or b"", hashlib.sha256).hexdigest()
    return secrets.compare_digest(expected, signature)


def create_token(
    *,
    user_id: str,
    email: str,
    token_type: str,
    tenant_id: Optional[str] = None,
    role: Optional[str] = None,
    platform_role: Optional[str] = None,
    expires_delta: Optional[timedelta] = None,
    mfa_verified: bool = False,
) -> str:
    now = datetime.now(timezone.utc)
    if expires_delta is None:
        if token_type == "refresh":
            expires_delta = timedelta(days=settings.saas_refresh_token_days)
        else:
            expires_delta = timedelta(minutes=settings.saas_access_token_minutes)

    payload = {
        "iss": settings.saas_jwt_issuer,
        "sub": str(user_id),
        "email": str(email),
        "type": str(token_type),
        "iat": now,
        "exp": now + expires_delta,
    }
    if tenant_id:
        payload["tenant_id"] = str(tenant_id)
    if role:
        payload["role"] = str(role)
    if platform_role:
        payload["platform_role"] = str(platform_role)
    if mfa_verified:
        payload["mfa"] = True
    return jwt.encode(payload, settings.saas_jwt_secret, algorithm="HS256")


def decode_token(raw_token: str, expected_type: str) -> dict:
    try:
        payload = jwt.decode(
            str(raw_token or ""),
            settings.saas_jwt_secret,
            algorithms=["HS256"],
            issuer=settings.saas_jwt_issuer,
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="token_expired")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="invalid_token")

    if payload.get("type") != expected_type:
        raise HTTPException(status_code=401, detail="invalid_token_type")
    return payload


def _bearer_token(request: Request) -> str:
    auth = str(request.headers.get("Authorization") or "").strip()
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="bearer_token_required")
    token = auth.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="bearer_token_required")
    return token


async def get_current_user(request: Request) -> AuthContext:
    payload = decode_token(_bearer_token(request), "access")
    tenant_id = str(payload.get("tenant_id") or "").strip()
    role = str(payload.get("role") or "").strip().lower()
    if not tenant_id or role not in ROLE_ORDER:
        raise HTTPException(status_code=401, detail="tenant_context_required")
    return AuthContext(
        user_id=str(payload.get("sub") or ""),
        email=str(payload.get("email") or ""),
        tenant_id=tenant_id,
        role=role,
    )


async def get_current_platform_admin(request: Request) -> PlatformAuthContext:
    payload = decode_token(_bearer_token(request), "access")
    user_id = str(payload.get("sub") or "").strip()
    email = normalize_email(str(payload.get("email") or ""))
    platform_role = str(payload.get("platform_role") or "").strip().lower()
    if not user_id or platform_role not in PLATFORM_ROLE_ORDER:
        raise HTTPException(status_code=401, detail="platform_admin_context_required")

    from sqlalchemy import text

    from app_saas.db import db_session

    with db_session() as conn:
        row = conn.execute(
            text(
                """
            SELECT pa.role, pa.status, u.email, u.status AS user_status
            FROM saas_platform_admins pa
            JOIN saas_users u ON u.id = pa.user_id
            WHERE pa.user_id = CAST(:user_id AS uuid)
            LIMIT 1
            """,
            ),
            {"user_id": user_id},
        ).mappings().first()
    if not row or row["status"] != "active" or row["user_status"] != "active":
        raise HTTPException(status_code=403, detail="platform_admin_not_active")
    db_role = str(row["role"] or "").strip().lower()
    if db_role not in PLATFORM_ROLE_ORDER:
        raise HTTPException(status_code=403, detail="invalid_platform_role")
    return PlatformAuthContext(user_id=user_id, email=normalize_email(row["email"] or email), platform_role=db_role)


def require_role(*allowed_roles: str) -> Callable[[AuthContext], AuthContext]:
    allowed = {role.strip().lower() for role in allowed_roles}

    def dependency(ctx: AuthContext = Depends(get_current_user)) -> AuthContext:
        if ctx.role not in allowed:
            raise HTTPException(status_code=403, detail="insufficient_role")
        return ctx

    return dependency


def require_platform_role(*allowed_roles: str) -> Callable[[PlatformAuthContext], PlatformAuthContext]:
    allowed = {role.strip().lower() for role in allowed_roles}

    def dependency(ctx: PlatformAuthContext = Depends(get_current_platform_admin)) -> PlatformAuthContext:
        if ctx.platform_role not in allowed:
            raise HTTPException(status_code=403, detail="insufficient_platform_role")
        return ctx

    return dependency
