from __future__ import annotations

import sys
import os
from pathlib import Path

from sqlalchemy import text

from app_saas.db import get_engine


def _ensure_migration_table(conn) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_schema_migrations (
                version TEXT PRIMARY KEY,
                file_name TEXT NOT NULL,
                applied_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )


def _applied_versions(conn) -> set[str]:
    rows = conn.execute(text("SELECT version FROM saas_schema_migrations")).mappings().all()
    return {str(row["version"]) for row in rows}


def _version_from_file(path: Path) -> str:
    return path.name.split("_", 1)[0]


def _should_apply(path: Path, profile: str) -> bool:
    legacy_versions = {"002", "003", "004"}
    version = _version_from_file(path)
    if profile == "all":
        return True
    if profile == "legacy":
        return True
    return version not in legacy_versions


def run_migrations(migrations_dir: Path) -> None:
    profile = os.getenv("SAAS_MIGRATION_PROFILE", "core").strip().lower() or "core"
    files = sorted(path for path in migrations_dir.glob("*.sql") if path.is_file())
    if not files:
        raise RuntimeError(f"no migration files found in {migrations_dir}")

    engine = get_engine()
    with engine.begin() as conn:
        _ensure_migration_table(conn)
        applied = _applied_versions(conn)

    for path in files:
        version = _version_from_file(path)
        if not _should_apply(path, profile):
            print(f"[migrate] skip {path.name} profile={profile}")
            continue
        if version in applied:
            print(f"[migrate] skip {path.name}")
            continue

        sql = path.read_text(encoding="utf-8")
        print(f"[migrate] apply {path.name}")
        raw_conn = engine.raw_connection()
        try:
            try:
                with raw_conn.cursor() as cur:
                    cur.execute(sql)
                    cur.execute(
                        """
                        INSERT INTO saas_schema_migrations (version, file_name)
                        VALUES (%s, %s)
                        """,
                        (version, path.name),
                    )
                raw_conn.commit()
            except Exception:
                raw_conn.rollback()
                raise
        finally:
            raw_conn.close()

    print("[migrate] done")


def main() -> None:
    raw_dir = sys.argv[1] if len(sys.argv) > 1 else "/migrations"
    run_migrations(Path(raw_dir))


if __name__ == "__main__":
    main()
