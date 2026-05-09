from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from app_saas.config import settings
from app_saas.db import db_session

router = APIRouter(tags=["saas-health"])


@router.get("/health")
def health():
    return {"ok": True, "service": "scentra-ai-api", "env": settings.saas_env}


@router.get("/ready")
def ready():
    try:
        with db_session() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"database_unavailable: {str(exc)[:180]}")
    return {"ok": True}
