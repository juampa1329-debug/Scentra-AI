from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy import text

from app_saas.config import settings
from app_saas.shared.email import send_plain_email, smtp_is_configured
from app_saas.shared.security import hash_secret
from app_saas.shared.security_events import record_security_event


def _csv_set(value: str) -> set[str]:
    return {item.strip().lower() for item in str(value or "").split(",") if item.strip()}


def role_requires_mfa(role: str, configured_roles: str) -> bool:
    return str(role or "").strip().lower() in _csv_set(configured_roles)


def email_hint(email: str) -> str:
    clean = str(email or "").strip()
    if "@" not in clean:
        return clean[:2] + "***"
    local, domain = clean.split("@", 1)
    visible = local[:2] if len(local) > 2 else local[:1]
    return f"{visible}***@{domain}"


def ensure_mfa_tables(conn) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_mfa_challenges (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES saas_users(id) ON DELETE CASCADE,
                tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                context TEXT NOT NULL DEFAULT 'tenant',
                role TEXT NOT NULL DEFAULT '',
                platform_role TEXT NOT NULL DEFAULT '',
                method TEXT NOT NULL DEFAULT 'email_otp',
                challenge_token_hash TEXT NOT NULL UNIQUE,
                code_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 5,
                email_sent BOOLEAN NOT NULL DEFAULT FALSE,
                requested_ip TEXT NOT NULL DEFAULT '',
                user_agent TEXT NOT NULL DEFAULT '',
                expires_at TIMESTAMP NOT NULL,
                verified_at TIMESTAMP NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_mfa_challenges_user_created ON saas_mfa_challenges (user_id, created_at DESC)"))
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_mfa_challenges_pending
            ON saas_mfa_challenges (context, status, expires_at)
            WHERE status = 'pending'
            """
        )
    )


def _request_ip(request: Request | None) -> str:
    if not request:
        return ""
    forwarded = str(request.headers.get("x-forwarded-for") or "").split(",", 1)[0].strip()
    return forwarded or (request.client.host if request.client else "")


def _request_agent(request: Request | None) -> str:
    if not request:
        return ""
    return str(request.headers.get("user-agent") or "").strip()[:500]


def generate_otp() -> str:
    length = max(6, min(int(settings.saas_mfa_otp_length or 6), 10))
    return str(secrets.randbelow(10**length)).zfill(length)


def send_security_notice(email: str, subject: str, body: str) -> bool:
    if not settings.saas_security_notify_enabled or not smtp_is_configured():
        return False
    return send_plain_email(email, subject, body)


def create_mfa_challenge(
    conn,
    *,
    request: Request,
    user_id: str,
    email: str,
    context: str,
    tenant_id: str | None = None,
    role: str = "",
    platform_role: str = "",
    event_type: str = "auth.mfa",
    rate_key: str = "",
) -> dict[str, Any]:
    ensure_mfa_tables(conn)
    code = generate_otp()
    raw_token = secrets.token_urlsafe(32)
    minutes = max(1, min(int(settings.saas_mfa_otp_minutes or 10), 60))
    max_attempts = max(1, min(int(settings.saas_mfa_max_attempts or 5), 10))
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    subject = "Codigo de seguridad Scentra"
    body = (
        "Usa este codigo para completar el ingreso a Scentra.\n\n"
        f"Codigo: {code}\n"
        f"Vence en {minutes} minutos.\n\n"
        "Si no intentaste ingresar, cambia tu clave y revisa la seguridad de tu cuenta."
    )
    sent = send_plain_email(email, subject, body) if smtp_is_configured() else False
    row = conn.execute(
        text(
            """
            INSERT INTO saas_mfa_challenges (
                user_id, tenant_id, context, role, platform_role, method,
                challenge_token_hash, code_hash, max_attempts, email_sent,
                requested_ip, user_agent, expires_at
            )
            VALUES (
                CAST(:user_id AS uuid), CAST(NULLIF(:tenant_id, '') AS uuid), :context, :role, :platform_role, 'email_otp',
                :challenge_token_hash, :code_hash, :max_attempts, :email_sent,
                :requested_ip, :user_agent, :expires_at
            )
            RETURNING id::text, expires_at::text
            """
        ),
        {
            "user_id": user_id,
            "tenant_id": tenant_id or "",
            "context": context,
            "role": role,
            "platform_role": platform_role,
            "challenge_token_hash": hash_secret(raw_token),
            "code_hash": hash_secret(f"{raw_token}:{code}"),
            "max_attempts": max_attempts,
            "email_sent": sent,
            "requested_ip": _request_ip(request),
            "user_agent": _request_agent(request),
            "expires_at": expires_at.replace(tzinfo=None),
        },
    ).mappings().first()
    record_security_event(
        conn,
        event_type=event_type,
        status="challenge",
        request=request,
        principal=email,
        rate_key=rate_key,
        tenant_id=tenant_id,
        user_id=user_id,
        reason="mfa_required",
        details={"context": context, "method": "email_otp", "email_sent": sent},
    )
    response = {
        "ok": False,
        "mfa_required": True,
        "challenge_token": raw_token,
        "method": "email_otp",
        "email_hint": email_hint(email),
        "expires_at": row["expires_at"] if row else expires_at.isoformat(),
        "email_sent": sent,
    }
    if settings.is_local:
        response["dev_otp"] = code
    return response


def verify_mfa_code(
    conn,
    *,
    request: Request,
    challenge_token: str,
    code: str,
    context: str,
    event_type: str = "auth.mfa",
    rate_key: str = "",
) -> dict[str, Any]:
    ensure_mfa_tables(conn)
    raw_token = str(challenge_token or "").strip()
    clean_code = str(code or "").strip().replace(" ", "")
    if len(raw_token) < 20 or len(clean_code) < 4:
        raise HTTPException(status_code=400, detail="invalid_mfa_challenge")
    row = conn.execute(
        text(
            """
            SELECT c.id::text, c.user_id::text, c.tenant_id::text, c.context, c.role, c.platform_role,
                   c.code_hash, c.status, c.attempts, c.max_attempts, c.expires_at,
                   u.email
            FROM saas_mfa_challenges c
            JOIN saas_users u ON u.id = c.user_id
            WHERE c.challenge_token_hash = :challenge_token_hash
              AND c.context = :context
            LIMIT 1
            """
        ),
        {"challenge_token_hash": hash_secret(raw_token), "context": context},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=400, detail="invalid_mfa_challenge")
    if row["status"] != "pending":
        raise HTTPException(status_code=400, detail="mfa_challenge_not_pending")
    if row["expires_at"] and row["expires_at"] < datetime.now():
        conn.execute(text("UPDATE saas_mfa_challenges SET status = 'expired', updated_at = NOW() WHERE id = CAST(:id AS uuid)"), {"id": row["id"]})
        record_security_event(conn, event_type=event_type, status="failed", request=request, principal=row["email"], rate_key=rate_key, user_id=row["user_id"], reason="mfa_expired")
        raise HTTPException(status_code=400, detail="mfa_challenge_expired")
    if not secrets.compare_digest(str(row["code_hash"]), hash_secret(f"{raw_token}:{clean_code}")):
        attempts = int(row["attempts"] or 0) + 1
        status = "blocked" if attempts >= int(row["max_attempts"] or 5) else "pending"
        conn.execute(
            text("UPDATE saas_mfa_challenges SET attempts = :attempts, status = :status, updated_at = NOW() WHERE id = CAST(:id AS uuid)"),
            {"attempts": attempts, "status": status, "id": row["id"]},
        )
        record_security_event(conn, event_type=event_type, status="failed", request=request, principal=row["email"], rate_key=rate_key, user_id=row["user_id"], reason="invalid_mfa_code", details={"attempts": attempts})
        raise HTTPException(status_code=401, detail="invalid_mfa_code")
    conn.execute(
        text("UPDATE saas_mfa_challenges SET status = 'verified', verified_at = NOW(), updated_at = NOW() WHERE id = CAST(:id AS uuid)"),
        {"id": row["id"]},
    )
    return dict(row)
