from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from app_saas.config import settings

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        if not settings.database_url:
            raise RuntimeError("DATABASE_URL is required for SaaS backend")
        _engine = create_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=max(1, int(settings.saas_db_pool_size or 10)),
            max_overflow=max(0, int(settings.saas_db_max_overflow or 20)),
            pool_timeout=max(5, int(settings.saas_db_pool_timeout_sec or 20)),
            pool_recycle=max(60, int(settings.saas_db_pool_recycle_sec or 1800)),
        )
    return _engine


@contextmanager
def db_session() -> Iterator[Connection]:
    with get_engine().begin() as conn:
        yield conn


def set_tenant_context(conn: Connection, tenant_id: str) -> None:
    conn.execute(
        text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )
