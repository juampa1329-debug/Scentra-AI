from __future__ import annotations

import time

from sqlalchemy import text

from app_saas.billing.service import sync_billing_lifecycle
from app_saas.config import settings
from app_saas.db import db_session

_last_run_monotonic = 0.0


def process_billing_lifecycle(*, force: bool = False) -> dict:
    global _last_run_monotonic
    interval_minutes = max(1, int(getattr(settings, "saas_billing_lifecycle_interval_minutes", 30) or 30))
    now = time.monotonic()
    if not force and _last_run_monotonic and now - _last_run_monotonic < interval_minutes * 60:
        return {"skipped": True, "reason": "interval", "interval_minutes": interval_minutes}
    with db_session() as conn:
        locked = bool(conn.execute(text("SELECT pg_try_advisory_xact_lock(hashtext('scentra:billing:lifecycle'))")).scalar())
        if not locked:
            return {"skipped": True, "reason": "locked"}
        result = sync_billing_lifecycle(conn)
        _last_run_monotonic = time.monotonic()
        return {"skipped": False, **result}
