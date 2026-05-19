from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app_saas.ai_gateway.service import provider_catalog, recent_runs, route_catalog
from app_saas.db import db_session, set_tenant_context
from app_saas.shared.security import AuthContext, get_current_user, require_role

router = APIRouter(prefix="/ai-gateway", tags=["saas-ai-gateway"])


@router.get("/providers")
def list_ai_gateway_providers(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "providers": provider_catalog(conn)}


@router.get("/routes")
def list_ai_gateway_routes(ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "routes": route_catalog(conn, ctx.tenant_id)}


@router.get("/runs")
def list_ai_gateway_runs(
    limit: int = Query(default=50, ge=1, le=200),
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "runs": recent_runs(conn, ctx.tenant_id, limit=limit)}

