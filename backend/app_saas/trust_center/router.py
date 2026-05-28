from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app_saas.db import db_session, set_tenant_context
from app_saas.shared.security import (
    AuthContext,
    PlatformAuthContext,
    get_current_platform_admin,
    get_current_user,
    require_platform_role,
    require_role,
)
from app_saas.trust_center.schemas import (
    GovernanceIncidentIn,
    GovernanceIncidentPatchIn,
    GovernanceReportGenerateIn,
    ModelCardIn,
    ModelCardPatchIn,
    RiskAssessmentPatchIn,
    RiskAssessmentRunIn,
    TrustPolicyAttestationIn,
    TrustPolicyIn,
    TrustPolicyPatchIn,
)
from app_saas.trust_center.service import (
    admin_overview,
    attest_policy,
    create_incident,
    generate_report,
    get_overview,
    list_audits,
    list_incidents,
    list_model_cards,
    list_policies,
    list_reports,
    list_risk_assessments,
    patch_incident,
    patch_model_card,
    patch_policy,
    patch_risk_assessment,
    run_risk_assessment,
    upsert_model_card,
    upsert_policy,
)


router = APIRouter(prefix="/trust-center", tags=["ai-trust-center"])
admin_router = APIRouter(prefix="/admin/trust-center", tags=["admin-ai-trust-center"])


@router.get("/overview")
def trust_overview(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return get_overview(conn, ctx.tenant_id)


@router.get("/policies")
def trust_policies(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return list_policies(conn, ctx.tenant_id)


@router.post("/policies")
def post_trust_policy(payload: TrustPolicyIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return upsert_policy(conn, ctx.tenant_id, ctx, payload)


@router.patch("/policies/{policy_id}")
def patch_trust_policy(policy_id: str, payload: TrustPolicyPatchIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return patch_policy(conn, ctx.tenant_id, ctx, policy_id, payload)


@router.post("/policies/{policy_id}/attest")
def post_policy_attestation(policy_id: str, payload: TrustPolicyAttestationIn, ctx: AuthContext = Depends(require_role("owner", "admin"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return attest_policy(conn, ctx.tenant_id, ctx, policy_id, payload)


@router.get("/risk-assessments")
def trust_risk_assessments(status: str | None = Query(default=None), ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return list_risk_assessments(conn, ctx.tenant_id, status=status)


@router.post("/risk-assessments/run")
def post_risk_assessment_run(payload: RiskAssessmentRunIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return run_risk_assessment(conn, ctx.tenant_id, ctx, payload)


@router.patch("/risk-assessments/{assessment_id}")
def patch_trust_assessment(assessment_id: str, payload: RiskAssessmentPatchIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return patch_risk_assessment(conn, ctx.tenant_id, ctx, assessment_id, payload)


@router.get("/model-cards")
def trust_model_cards(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return list_model_cards(conn, ctx.tenant_id)


@router.post("/model-cards")
def post_model_card(payload: ModelCardIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return upsert_model_card(conn, ctx.tenant_id, ctx, payload)


@router.patch("/model-cards/{card_id}")
def patch_trust_model_card(card_id: str, payload: ModelCardPatchIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return patch_model_card(conn, ctx.tenant_id, ctx, card_id, payload)


@router.get("/incidents")
def trust_incidents(status: str | None = Query(default=None), ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return list_incidents(conn, ctx.tenant_id, status=status)


@router.post("/incidents")
def post_trust_incident(payload: GovernanceIncidentIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return create_incident(conn, ctx.tenant_id, ctx, payload)


@router.patch("/incidents/{incident_id}")
def patch_trust_incident(incident_id: str, payload: GovernanceIncidentPatchIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return patch_incident(conn, ctx.tenant_id, ctx, incident_id, payload)


@router.get("/audits")
def trust_audits(limit: int = Query(100, ge=1, le=500), ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return list_audits(conn, ctx.tenant_id, limit=limit)


@router.get("/reports")
def trust_reports(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return list_reports(conn, ctx.tenant_id)


@router.post("/reports/generate")
def post_trust_report(payload: GovernanceReportGenerateIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return generate_report(conn, ctx.tenant_id, ctx, payload)


@admin_router.get("/overview")
def admin_trust_overview(ctx: PlatformAuthContext = Depends(get_current_platform_admin)):
    with db_session() as conn:
        return admin_overview(conn)


@admin_router.get("/tenants")
def admin_trust_tenants(ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support"))):
    with db_session() as conn:
        data = admin_overview(conn)
        return {"ok": True, "tenants": data.get("tenants", []), "aggregate": data.get("aggregate", {})}
