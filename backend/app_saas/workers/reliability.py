from __future__ import annotations

from app_saas.db import db_session
from app_saas.reliability.service import process_due_reliability as process_reliability_with_conn


def process_due_reliability() -> dict:
    try:
        with db_session() as conn:
            return process_reliability_with_conn(conn)
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:500]}
