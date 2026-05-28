from __future__ import annotations

from fastapi import APIRouter, Depends

from app_saas.db import db_session, set_tenant_context
from app_saas.shared.security import AuthContext, get_current_user, require_role
from app_saas.verticals.schemas import VerticalApplyIn
from app_saas.verticals.service import apply_industry_pack, public_pack_summaries, tenant_vertical_state

router = APIRouter(prefix="/verticals", tags=["saas-verticals"])


@router.get("/public-packs")
def get_public_vertical_packs():
    return {"ok": True, "packs": public_pack_summaries()}


@router.get("/packs")
def get_vertical_packs(ctx: AuthContext = Depends(get_current_user)):
    return {"ok": True, "tenant_id": ctx.tenant_id, "packs": public_pack_summaries()}


@router.get("/state")
def get_vertical_state(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "tenant_id": ctx.tenant_id, **tenant_vertical_state(conn, ctx.tenant_id)}


@router.post("/apply")
def post_apply_vertical_pack(
    payload: VerticalApplyIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return apply_industry_pack(
            conn,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            industry_code=payload.industry_code,
            create_agents=payload.create_agents,
        )

