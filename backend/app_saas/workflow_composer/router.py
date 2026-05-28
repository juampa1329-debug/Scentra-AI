from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app_saas.db import db_session, set_tenant_context
from app_saas.shared.security import AuthContext, get_current_user, require_role
from app_saas.workflow_composer.schemas import (
    WorkflowApprovalRequestIn,
    WorkflowApprovalReviewIn,
    WorkflowCreateIn,
    WorkflowMaterializeIn,
    WorkflowPatchIn,
    WorkflowSimulationIn,
    WorkflowTemplateInstantiateIn,
    WorkflowVersionRestoreIn,
)
from app_saas.workflow_composer.service import (
    activate_workflow,
    create_workflow,
    get_overview,
    get_workflow_detail,
    instantiate_template,
    list_templates,
    list_versions,
    list_workflows,
    materialize_workflow,
    request_approval,
    restore_version,
    review_approval,
    run_preflight,
    run_simulation,
    update_workflow,
)


router = APIRouter(prefix="/workflow-composer", tags=["workflow-composer"])


@router.get("/overview")
def composer_overview(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return get_overview(conn, ctx.tenant_id)


@router.get("/templates")
def composer_templates(
    category: str | None = Query(default=None),
    industry_code: str | None = Query(default=None),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return list_templates(conn, ctx.tenant_id, category=category, industry_code=industry_code)


@router.post("/templates/{template_key}/instantiate")
def instantiate_composer_template(
    template_key: str,
    payload: WorkflowTemplateInstantiateIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return instantiate_template(conn, ctx.tenant_id, ctx, template_key, payload)


@router.get("/workflows")
def workflows(status: str | None = Query(default=None), ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return list_workflows(conn, ctx.tenant_id, status=status)


@router.post("/workflows")
def post_workflow(payload: WorkflowCreateIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return create_workflow(conn, ctx.tenant_id, ctx, payload)


@router.get("/workflows/{workflow_id}")
def workflow_detail(workflow_id: str, ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return get_workflow_detail(conn, ctx.tenant_id, workflow_id)


@router.patch("/workflows/{workflow_id}")
def patch_workflow(
    workflow_id: str,
    payload: WorkflowPatchIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return update_workflow(conn, ctx.tenant_id, ctx, workflow_id, payload)


@router.post("/workflows/{workflow_id}/preflight")
def post_preflight(workflow_id: str, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return run_preflight(conn, ctx.tenant_id, workflow_id)


@router.post("/workflows/{workflow_id}/simulate")
def post_simulation(
    workflow_id: str,
    payload: WorkflowSimulationIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return run_simulation(conn, ctx.tenant_id, ctx, workflow_id, payload)


@router.post("/workflows/{workflow_id}/approval/request")
def post_approval_request(
    workflow_id: str,
    payload: WorkflowApprovalRequestIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return request_approval(conn, ctx.tenant_id, ctx, workflow_id, payload)


@router.post("/workflows/{workflow_id}/approval/review")
def post_approval_review(
    workflow_id: str,
    payload: WorkflowApprovalReviewIn,
    ctx: AuthContext = Depends(require_role("owner", "admin")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return review_approval(conn, ctx.tenant_id, ctx, workflow_id, payload)


@router.post("/workflows/{workflow_id}/materialize")
def post_materialize(
    workflow_id: str,
    payload: WorkflowMaterializeIn,
    ctx: AuthContext = Depends(require_role("owner", "admin")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return materialize_workflow(conn, ctx.tenant_id, ctx, workflow_id, payload)


@router.post("/workflows/{workflow_id}/activate")
def post_activate(workflow_id: str, ctx: AuthContext = Depends(require_role("owner", "admin"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return activate_workflow(conn, ctx.tenant_id, ctx, workflow_id)


@router.get("/workflows/{workflow_id}/versions")
def workflow_versions(workflow_id: str, ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return list_versions(conn, ctx.tenant_id, workflow_id)


@router.post("/workflows/{workflow_id}/versions/{version_id}/restore")
def post_restore_version(
    workflow_id: str,
    version_id: str,
    payload: WorkflowVersionRestoreIn,
    ctx: AuthContext = Depends(require_role("owner", "admin")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return restore_version(conn, ctx.tenant_id, ctx, workflow_id, version_id, payload)
