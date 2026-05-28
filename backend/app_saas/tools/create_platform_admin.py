from __future__ import annotations

import argparse
import os
import sys
import uuid

from sqlalchemy import text

from app_saas.db import db_session
from app_saas.shared.security import PLATFORM_ROLE_ORDER, hash_password, normalize_email


def _clean(value: object, limit: int = 240) -> str:
    return str(value or "").strip()[:limit]


def _ensure_platform_admin_table(conn) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_platform_admins (
                user_id UUID PRIMARY KEY REFERENCES saas_users(id) ON DELETE CASCADE,
                role TEXT NOT NULL DEFAULT 'platform_admin',
                status TEXT NOT NULL DEFAULT 'active',
                notes TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_platform_admins_status_role
            ON saas_platform_admins (status, role)
            """
        )
    )


def create_platform_admin(*, email: str, password: str, full_name: str, role: str, notes: str) -> dict:
    clean_email = normalize_email(email)
    clean_role = _clean(role, 40).lower() or "superadmin"
    if "@" not in clean_email:
        raise ValueError("email invalido")
    if len(str(password or "")) < 12:
        raise ValueError("password debe tener al menos 12 caracteres para admin de plataforma")
    if clean_role not in PLATFORM_ROLE_ORDER:
        raise ValueError(f"rol invalido: {clean_role}")

    with db_session() as conn:
        _ensure_platform_admin_table(conn)
        row = conn.execute(
            text(
                """
                INSERT INTO saas_users (id, email, full_name, password_hash, password_algo, status, updated_at)
                VALUES (CAST(:id AS uuid), :email, :full_name, :password_hash, 'argon2id', 'active', NOW())
                ON CONFLICT (email)
                DO UPDATE SET
                    full_name = COALESCE(NULLIF(EXCLUDED.full_name, ''), saas_users.full_name),
                    password_hash = EXCLUDED.password_hash,
                    password_algo = 'argon2id',
                    status = 'active',
                    updated_at = NOW()
                RETURNING id::text AS user_id, email, full_name
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "email": clean_email,
                "full_name": _clean(full_name, 180) or "Scentra Admin",
                "password_hash": hash_password(password),
            },
        ).mappings().first()
        conn.execute(
            text(
                """
                INSERT INTO saas_platform_admins (user_id, role, status, notes, updated_at)
                VALUES (CAST(:user_id AS uuid), :role, 'active', :notes, NOW())
                ON CONFLICT (user_id)
                DO UPDATE SET role = EXCLUDED.role, status = 'active', notes = EXCLUDED.notes, updated_at = NOW()
                """
            ),
            {"user_id": row["user_id"], "role": clean_role, "notes": _clean(notes, 500) or "created by platform admin seed"},
        )
    return {"user_id": row["user_id"], "email": row["email"], "full_name": row["full_name"], "platform_role": clean_role}


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or update the first Scentra platform admin.")
    parser.add_argument("--email", default=os.getenv("SAAS_ADMIN_EMAIL", ""))
    parser.add_argument("--password", default=os.getenv("SAAS_ADMIN_PASSWORD", ""))
    parser.add_argument("--full-name", default=os.getenv("SAAS_ADMIN_FULL_NAME", "Scentra Admin"))
    parser.add_argument("--role", default=os.getenv("SAAS_ADMIN_ROLE", "superadmin"))
    parser.add_argument("--notes", default=os.getenv("SAAS_ADMIN_NOTES", "production seed"))
    args = parser.parse_args()

    try:
        result = create_platform_admin(
            email=args.email,
            password=args.password,
            full_name=args.full_name,
            role=args.role,
            notes=args.notes,
        )
    except Exception as exc:
        print(f"[platform-admin] error: {exc}", file=sys.stderr)
        raise SystemExit(1)

    print(
        "[platform-admin] ok "
        f"email={result['email']} role={result['platform_role']} user_id={result['user_id']}"
    )


if __name__ == "__main__":
    main()
