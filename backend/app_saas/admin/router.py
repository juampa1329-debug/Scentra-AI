from __future__ import annotations

import contextlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app_saas.admin.schemas import (
    AdminBootstrapIn,
    AdminLoginIn,
    AdminMfaChallengeOut,
    AdminMfaVerifyIn,
    AdminPasswordChangeIn,
    AdminProfilePatchIn,
    AdminTwoFactorPatchIn,
    AdminTenantMembershipPatchIn,
    AdminTenantUserCreateIn,
    BillingCreditCreateIn,
    BillingInvoiceCreateIn,
    FeatureFlagPatchIn,
    PlanPatchIn,
    PlanUpsertIn,
    PlatformAdminCreateIn,
    PlatformAdminPatchIn,
    PlatformTokenOut,
    ReliabilityBackpressurePatchIn,
    ReliabilityRetentionPatchIn,
    TenantImpersonateIn,
    SubscriptionPatchIn,
    TenantPatchIn,
)
from app_saas.billing.limits import billing_overview
from app_saas.billing.service import apply_manual_credit, create_manual_invoice, get_invoice, invoice_pdf_bytes, sync_billing_lifecycle
from app_saas.config import settings
from app_saas.db import db_session, set_tenant_context
from app_saas.intelligence.catalog import INTELLIGENCE_FEATURES
from app_saas.intelligence.schemas import (
    AdminAiProviderPolicyPatchIn,
    AdminIntelligenceFeaturePatchIn,
    AdminIntelligencePlanFeaturePatchIn,
    AutoLabelGenerationRequestIn,
    AutoLabelTrainingRequestIn,
    DatasetBuildRequestIn,
    FeaturePipelineRequestIn,
    ModelMetricsRecomputeIn,
    ModelRegistryCreateIn,
    ModelRegistryPatchIn,
    SyntheticTrainingRequestIn,
)
from app_saas.intelligence.service import (
    admin_multimodal_premium_gating,
    admin_intelligence_tenants,
    assess_model_rollout,
    generate_auto_labels,
    intelligence_catalog,
    intelligence_feature_state,
    list_model_metrics,
    list_model_registry,
    mlops_overview,
    recompute_model_metrics,
    recompute_training_feature_pipelines,
    register_model_registry_entry,
    request_ml_autolabel_training,
    request_ml_dataset_build,
    request_ml_synthetic_training,
    training_dataset_readiness,
    update_model_registry_control,
    upsert_feature_grant,
)
from app_saas.intelligence.premium import upsert_plan_feature_limit, upsert_provider_policy
from app_saas.intelligence.realtime import admin_refresh_realtime_metrics, admin_realtime_overview
from app_saas.observability.service import (
    channel_diagnostics,
    dead_letter_events,
    global_health,
    meta_error_history,
    queue_snapshot,
    resolve_dead_letter,
    retry_dead_letter,
    sync_dead_letters,
)
from app_saas.reliability.service import (
    backpressure_status,
    index_audit,
    record_reliability_snapshot,
    reliability_overview,
    run_reliability_drill,
    run_retention,
    update_retention_policy,
)
from app_saas.shared.captcha import verify_captcha_or_raise
from app_saas.shared.email import send_alert_email, send_welcome_email, smtp_is_configured
from app_saas.shared.mfa import create_mfa_challenge, role_requires_mfa, send_security_notice, verify_mfa_code
from app_saas.shared.security import (
    PLATFORM_ROLE_ORDER,
    PlatformAuthContext,
    clear_login_lock,
    create_token,
    get_current_platform_admin,
    hash_password,
    increment_failed_login,
    normalize_email,
    normalize_slug,
    require_platform_role,
    verify_password,
)
from app_saas.shared.security_events import enforce_auth_rate_limits, rate_limit_key, record_security_event
from app_saas.verticals.catalog import normalize_industry_code
from app_saas.verticals.service import apply_industry_pack
from app_saas.agents.orchestrator import process_due_agent_orchestration
from app_saas.ai_agent.service import process_due_ai_replies
from app_saas.workers.dispatch import process_due_outbound_messages
from app_saas.workers.ingest import process_due_webhook_events
from app_saas.workers.intelligence import process_due_intelligence
from app_saas.workers.meta_tokens import process_due_meta_token_refreshes
from app_saas.workers.remarketing import process_due_remarketing_flows
from app_saas.workers.reliability import process_due_reliability
from app_saas.workers.triggers import process_due_scheduled_trigger_messages

router = APIRouter(prefix="/admin", tags=["saas-admin"])

FEATURE_CATALOG = [
    {"key": "inbox", "label": "Inbox"},
    {"key": "ai", "label": "IA comercial"},
    {"key": "ai_agents", "label": "AI Agents"},
    {"key": "advisor", "label": "Advisor AI"},
    {"key": "broadcast", "label": "Mensajeria masiva"},
    {"key": "triggers", "label": "Triggers CRM"},
    {"key": "remarketing", "label": "Remarketing"},
    {"key": "ads", "label": "Ads Manager"},
    {"key": "whatsapp_cloud", "label": "WhatsApp Cloud real"},
    {"key": "instagram_business", "label": "Instagram Business"},
    {"key": "facebook_messenger", "label": "Facebook Messenger"},
    {"key": "social_comments", "label": "Comentarios sociales"},
    {"key": "knowledge_base", "label": "Knowledge Base"},
    {"key": "woocommerce", "label": "WooCommerce"},
    {"key": "shopify", "label": "Shopify"},
    {"key": "elevenlabs_voice", "label": "Voz ElevenLabs"},
] + [{"key": item["key"], "label": item["label"]} for item in INTELLIGENCE_FEATURES]
TENANT_STATUSES = {"active", "trial", "paused", "past_due", "suspended", "cancelled"}
SUBSCRIPTION_STATUSES = {"trial", "active", "past_due", "cancelled", "suspended"}
IMPERSONATION_ROLES = {"owner", "admin", "supervisor", "agent", "viewer"}
PLATFORM_ADMIN_STATUSES = {"active", "paused", "disabled"}
TENANT_ROLE_LABELS = {
    "owner": "Propietario",
    "admin": "Administrador",
    "supervisor": "Supervisor",
    "agent": "Agente",
    "viewer": "Lector",
}
PLATFORM_ROLE_LABELS = {
    "superadmin": "Superadministrador",
    "platform_admin": "Administrador de plataforma",
    "billing_admin": "Administrador de facturacion",
    "support": "Soporte",
    "viewer": "Lector",
}
STATUS_LABELS = {
    "active": "Activo",
    "paused": "Pausado",
    "disabled": "Deshabilitado",
}


def _role_label(role: object, *, platform: bool = False) -> str:
    value = str(role or "").strip().lower()
    labels = PLATFORM_ROLE_LABELS if platform else TENANT_ROLE_LABELS
    return labels.get(value, value.replace("_", " ").title() if value else "Usuario")


def _status_label(status: object) -> str:
    value = str(status or "").strip().lower()
    return STATUS_LABELS.get(value, value.replace("_", " ").title() if value else "Sin estado")


def _clean(value: object, limit: int = 200) -> str:
    return str(value or "").strip()[:limit]


def _period_yyyymm() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m")


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def _admin_token(row: dict[str, Any], *, mfa_verified: bool = False) -> PlatformTokenOut:
    role = str(row["platform_role"] or row["role"] or "platform_admin").strip().lower()
    token = create_token(user_id=row["user_id"], email=row["email"], token_type="access", platform_role=role, mfa_verified=mfa_verified)
    return PlatformTokenOut(
        access_token=token,
        user_id=row["user_id"],
        email=row["email"],
        platform_role=role,
    )


def _admin_mfa_required(row: dict[str, Any]) -> bool:
    method = str(row.get("two_factor_method") or "none").strip().lower()
    enabled = bool(row.get("two_factor_enabled")) and method == "email_otp"
    role = str(row.get("platform_role") or row.get("role") or "").strip().lower()
    return enabled or role_requires_mfa(role, settings.saas_admin_mfa_required_roles)


def _audit(
    conn,
    *,
    actor: PlatformAuthContext,
    action: str,
    resource_type: str,
    resource_id: str = "",
    tenant_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        text(
            """
            INSERT INTO saas_audit_events (tenant_id, actor_user_id, action, resource_type, resource_id, details_json)
            VALUES (
                CAST(NULLIF(:tenant_id, '') AS uuid),
                CAST(:actor_user_id AS uuid),
                :action,
                :resource_type,
                :resource_id,
                CAST(:details_json AS jsonb)
            )
            """
        ),
        {
            "tenant_id": tenant_id or "",
            "actor_user_id": actor.user_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "details_json": _json(details or {}),
        },
    )


def _platform_admin_count(conn) -> int:
    return int(
        conn.execute(
            text("SELECT COUNT(*) FROM saas_platform_admins WHERE status = 'active'")
        ).scalar_one()
        or 0
    )


def _admin_app_url() -> str:
    public_url = str(settings.scentra_app_public_url or "").rstrip("/")
    if public_url.startswith("https://app."):
        return public_url.replace("https://app.", "https://admin.", 1)
    return "https://admin.scentra-ai.online"


def _tenant_admin_contacts(conn, tenant_id: str, *, exclude_user_id: str = "") -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT DISTINCT u.id::text AS user_id, u.email, u.full_name, m.role
            FROM saas_memberships m
            JOIN saas_users u ON u.id = m.user_id
            WHERE m.tenant_id = CAST(:tenant_id AS uuid)
              AND m.is_active = TRUE
              AND m.role IN ('owner', 'admin')
              AND u.status = 'active'
              AND (:exclude_user_id = '' OR u.id <> CAST(NULLIF(:exclude_user_id, '') AS uuid))
            ORDER BY m.role ASC, u.email ASC
            LIMIT 20
            """
        ),
        {"tenant_id": tenant_id, "exclude_user_id": exclude_user_id or ""},
    ).mappings().all()
    return [dict(row) for row in rows]


def _ensure_ai_agent_plan_limit_table(conn) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_agent_plan_limits (
                plan_code TEXT PRIMARY KEY,
                max_ai_agents INTEGER NOT NULL DEFAULT 1,
                max_active_ai_agents INTEGER NOT NULL DEFAULT 1,
                max_memory_archives INTEGER NOT NULL DEFAULT 1,
                allowed_agent_types_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                builder_enabled BOOLEAN NOT NULL DEFAULT TRUE,
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
            ALTER TABLE saas_ai_agent_plan_limits
              ADD COLUMN IF NOT EXISTS max_ai_agents INTEGER NOT NULL DEFAULT 1,
              ADD COLUMN IF NOT EXISTS max_active_ai_agents INTEGER NOT NULL DEFAULT 1,
              ADD COLUMN IF NOT EXISTS max_memory_archives INTEGER NOT NULL DEFAULT 1,
              ADD COLUMN IF NOT EXISTS allowed_agent_types_json JSONB NOT NULL DEFAULT '[]'::jsonb,
              ADD COLUMN IF NOT EXISTS builder_enabled BOOLEAN NOT NULL DEFAULT TRUE,
              ADD COLUMN IF NOT EXISTS notes TEXT NOT NULL DEFAULT '',
              ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT NOW(),
              ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            """
        )
    )


def _upsert_ai_agent_plan_limits(conn, plan_code: str, raw_limits: dict[str, Any] | None) -> dict[str, Any] | None:
    if raw_limits is None:
        return None
    _ensure_ai_agent_plan_limit_table(conn)
    allowed = raw_limits.get("allowed_agent_types_json")
    if not isinstance(allowed, list):
        allowed = []
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_agent_plan_limits (
                plan_code, max_ai_agents, max_active_ai_agents, max_memory_archives,
                allowed_agent_types_json, builder_enabled, notes, updated_at
            )
            VALUES (
                :plan_code, :max_ai_agents, :max_active_ai_agents, :max_memory_archives,
                CAST(:allowed_agent_types_json AS jsonb), :builder_enabled, :notes, NOW()
            )
            ON CONFLICT (plan_code)
            DO UPDATE SET
                max_ai_agents = EXCLUDED.max_ai_agents,
                max_active_ai_agents = EXCLUDED.max_active_ai_agents,
                max_memory_archives = EXCLUDED.max_memory_archives,
                allowed_agent_types_json = EXCLUDED.allowed_agent_types_json,
                builder_enabled = EXCLUDED.builder_enabled,
                notes = EXCLUDED.notes,
                updated_at = NOW()
            RETURNING plan_code, max_ai_agents, max_active_ai_agents, max_memory_archives,
                      allowed_agent_types_json, builder_enabled, notes, updated_at::text
            """
        ),
        {
            "plan_code": plan_code,
            "max_ai_agents": int(raw_limits.get("max_ai_agents") or 0),
            "max_active_ai_agents": int(raw_limits.get("max_active_ai_agents") or 0),
            "max_memory_archives": int(raw_limits.get("max_memory_archives") or 0),
            "allowed_agent_types_json": _json([str(item).strip() for item in allowed if str(item).strip()]),
            "builder_enabled": bool(raw_limits.get("builder_enabled", True)),
            "notes": _clean(raw_limits.get("notes"), 1000),
        },
    ).mappings().first()
    return dict(row or {})


def _load_plan(conn, plan_code: str) -> dict[str, Any] | None:
    _ensure_ai_agent_plan_limit_table(conn)
    row = conn.execute(
        text(
            """
            SELECT plan_code, display_name, max_agents, max_monthly_messages, max_integrations, max_storage_gb,
                   max_campaigns, max_broadcasts, max_ai_tokens, feature_flags_json, price_monthly_cents,
                   currency, is_public, is_active, sort_order, created_at::text, updated_at::text,
                   COALESCE((
                       SELECT jsonb_build_object(
                           'plan_code', apl.plan_code,
                           'max_ai_agents', apl.max_ai_agents,
                           'max_active_ai_agents', apl.max_active_ai_agents,
                           'max_memory_archives', apl.max_memory_archives,
                           'allowed_agent_types_json', apl.allowed_agent_types_json,
                           'builder_enabled', apl.builder_enabled,
                           'notes', apl.notes,
                           'updated_at', apl.updated_at::text
                       )
                       FROM saas_ai_agent_plan_limits apl
                       WHERE apl.plan_code = saas_plan_limits.plan_code
                       LIMIT 1
                   ), '{}'::jsonb) AS ai_agent_limits
            FROM saas_plan_limits
            WHERE plan_code = :plan_code
            LIMIT 1
            """
        ),
        {"plan_code": plan_code},
    ).mappings().first()
    return dict(row) if row else None


def _tenant_exists(conn, tenant_id: str) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            SELECT
                id::text,
                slug,
                name,
                status,
                plan_code,
                timezone,
                locale,
                industry_code,
                vertical_pack_version,
                vertical_pack_json,
                vertical_pack_applied_at::text,
                created_at::text,
                updated_at::text
            FROM saas_tenants
            WHERE id = CAST(:tenant_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="tenant_not_found")
    return dict(row)


@router.post("/auth/bootstrap", response_model=PlatformTokenOut)
def bootstrap_platform_admin(payload: AdminBootstrapIn, request: Request):
    if not settings.is_local:
        raise HTTPException(status_code=403, detail="bootstrap_only_available_locally")
    email = normalize_email(payload.email)
    role = _clean(payload.platform_role, 40).lower() or "superadmin"
    if role not in PLATFORM_ROLE_ORDER:
        raise HTTPException(status_code=400, detail="invalid_platform_role")
    auth_error: HTTPException | None = None
    token_payload: PlatformTokenOut | None = None
    rate_key = rate_limit_key(action="admin.bootstrap", principal=email, request=request)
    with db_session() as conn:
        enforce_auth_rate_limits(
            conn,
            event_type="admin.bootstrap",
            rate_key=rate_key,
            combined_limit=3,
            principal_limit=3,
            ip_limit=10,
            window_seconds=3600,
            request=request,
            principal=email,
            count_statuses=("attempt", "failed", "blocked"),
        )
        try:
            verify_captcha_or_raise(token=payload.captcha_token, provider=payload.captcha_provider, request=request)
        except HTTPException as exc:
            auth_error = exc
            record_security_event(
                conn,
                event_type="admin.bootstrap",
                status="blocked",
                request=request,
                principal=email,
                rate_key=rate_key,
                reason="captcha_rejected",
                details={"detail": exc.detail},
            )
        if not auth_error:
            record_security_event(conn, event_type="admin.bootstrap", status="attempt", request=request, principal=email, rate_key=rate_key)
            user = conn.execute(
                text(
                    """
                    INSERT INTO saas_users (
                        email, full_name, password_hash, password_algo, status,
                        failed_login_count, locked_until, password_changed_at, updated_at
                    )
                    VALUES (:email, :full_name, :password_hash, 'argon2id', 'active', 0, NULL, NOW(), NOW())
                    ON CONFLICT (email)
                    DO UPDATE SET
                        full_name = COALESCE(NULLIF(EXCLUDED.full_name, ''), saas_users.full_name),
                        password_hash = EXCLUDED.password_hash,
                        status = 'active',
                        failed_login_count = 0,
                        locked_until = NULL,
                        password_changed_at = NOW(),
                        updated_at = NOW()
                    RETURNING id::text AS user_id, email
                    """
                ),
                {
                    "email": email,
                    "full_name": _clean(payload.full_name, 180),
                    "password_hash": hash_password(payload.password),
                },
            ).mappings().first()
            conn.execute(
                text(
                    """
                    INSERT INTO saas_platform_admins (user_id, role, status, notes, updated_at)
                    VALUES (CAST(:user_id AS uuid), :role, 'active', 'local bootstrap', NOW())
                    ON CONFLICT (user_id)
                    DO UPDATE SET role = EXCLUDED.role, status = 'active', updated_at = NOW()
                    """
                ),
                {"user_id": user["user_id"], "role": role},
            )
            record_security_event(conn, event_type="admin.bootstrap", status="success", request=request, principal=email, rate_key=rate_key, user_id=user["user_id"])
            token_payload = _admin_token({"user_id": user["user_id"], "email": user["email"], "platform_role": role, "role": role})
    if auth_error:
        raise auth_error
    if token_payload is None:
        raise HTTPException(status_code=500, detail="admin_bootstrap_response_unavailable")
    return token_payload


@router.post("/auth/login", response_model=PlatformTokenOut | AdminMfaChallengeOut)
def admin_login(payload: AdminLoginIn, request: Request):
    email = normalize_email(payload.email)
    auth_error: HTTPException | None = None
    token_payload: PlatformTokenOut | AdminMfaChallengeOut | None = None
    rate_key = rate_limit_key(action="admin.login", principal=email, request=request)
    with db_session() as conn:
        enforce_auth_rate_limits(
            conn,
            event_type="admin.login",
            rate_key=rate_key,
            combined_limit=6,
            principal_limit=8,
            ip_limit=30,
            window_seconds=900,
            request=request,
            principal=email,
            count_statuses=("failed", "blocked"),
        )
        try:
            verify_captcha_or_raise(token=payload.captcha_token, provider=payload.captcha_provider, request=request)
        except HTTPException as exc:
            auth_error = exc
            record_security_event(
                conn,
                event_type="admin.login",
                status="blocked",
                request=request,
                principal=email,
                rate_key=rate_key,
                reason="captcha_rejected",
                details={"detail": exc.detail},
            )
        if not auth_error:
            row = conn.execute(
                text(
                    """
                    SELECT u.id::text AS user_id, u.email, u.password_hash, u.status AS user_status,
                           u.locked_until::text, u.two_factor_enabled, u.two_factor_method,
                           pa.role AS platform_role, pa.status AS admin_status
                    FROM saas_users u
                    JOIN saas_platform_admins pa ON pa.user_id = u.id
                    WHERE LOWER(u.email) = :email
                    LIMIT 1
                    """
                ),
                {"email": email},
            ).mappings().first()
            if row and row["locked_until"]:
                locked = conn.execute(
                    text(
                        """
                        SELECT locked_until > NOW() AS is_locked,
                               locked_until::text AS locked_until
                        FROM saas_users
                        WHERE id = CAST(:user_id AS uuid)
                        LIMIT 1
                        """
                    ),
                    {"user_id": row["user_id"]},
                ).mappings().first()
                if locked and locked["is_locked"]:
                    record_security_event(
                        conn,
                        event_type="admin.login",
                        status="blocked",
                        request=request,
                        principal=email,
                        rate_key=rate_key,
                        user_id=row["user_id"],
                        reason="account_temporarily_locked",
                        details={"locked_until": locked["locked_until"]},
                    )
                    auth_error = HTTPException(
                        status_code=423,
                        detail={"code": "account_temporarily_locked", "locked_until": locked["locked_until"]},
                    )
            if not auth_error and (
                not row
                or row["user_status"] != "active"
                or row["admin_status"] != "active"
                or str(row["platform_role"] or "").lower() not in PLATFORM_ROLE_ORDER
                or not verify_password(payload.password, row["password_hash"])
            ):
                lock_info = increment_failed_login(conn, row["user_id"]) if row and row["user_status"] == "active" else {}
                record_security_event(
                    conn,
                    event_type="admin.login",
                    status="failed",
                    request=request,
                    principal=email,
                    rate_key=rate_key,
                    user_id=row["user_id"] if row else None,
                    reason="invalid_admin_credentials",
                    details={"failed_login_count": lock_info.get("failed_login_count"), "locked_until": lock_info.get("locked_until")},
                )
                auth_error = HTTPException(status_code=401, detail="invalid_admin_credentials")
            elif not auth_error:
                if _admin_mfa_required(dict(row)):
                    token_payload = AdminMfaChallengeOut(
                        **create_mfa_challenge(
                            conn,
                            request=request,
                            user_id=row["user_id"],
                            email=row["email"],
                            context="platform_admin",
                            platform_role=row["platform_role"],
                            event_type="admin.login.mfa",
                            rate_key=rate_key,
                        )
                    )
                else:
                    clear_login_lock(conn, row["user_id"])
                    conn.execute(
                        text("UPDATE saas_users SET last_login_at = NOW(), updated_at = NOW() WHERE id = CAST(:id AS uuid)"),
                        {"id": row["user_id"]},
                    )
                    record_security_event(conn, event_type="admin.login", status="success", request=request, principal=email, rate_key=rate_key, user_id=row["user_id"])
                    token_payload = _admin_token(dict(row))
    if auth_error:
        raise auth_error
    if token_payload is None:
        raise HTTPException(status_code=500, detail="admin_auth_response_unavailable")
    return token_payload


@router.post("/auth/login/verify-otp", response_model=PlatformTokenOut)
def admin_verify_login_otp(payload: AdminMfaVerifyIn, request: Request):
    rate_key = rate_limit_key(action="admin.login.mfa_verify", principal=payload.challenge_token[:24], request=request)
    with db_session() as conn:
        enforce_auth_rate_limits(
            conn,
            event_type="admin.login.mfa_verify",
            rate_key=rate_key,
            combined_limit=10,
            principal_limit=10,
            ip_limit=40,
            window_seconds=900,
            request=request,
            principal=payload.challenge_token[:24],
            count_statuses=("failed", "blocked"),
        )
        challenge = verify_mfa_code(
            conn,
            request=request,
            challenge_token=payload.challenge_token,
            code=payload.code,
            context="platform_admin",
            event_type="admin.login.mfa_verify",
            rate_key=rate_key,
        )
        row = conn.execute(
            text(
                """
                SELECT u.id::text AS user_id, u.email, pa.role AS platform_role, pa.status AS admin_status, u.status AS user_status
                FROM saas_users u
                JOIN saas_platform_admins pa ON pa.user_id = u.id
                WHERE u.id = CAST(:user_id AS uuid)
                LIMIT 1
                """
            ),
            {"user_id": challenge["user_id"]},
        ).mappings().first()
        if not row or row["user_status"] != "active" or row["admin_status"] != "active":
            raise HTTPException(status_code=403, detail="platform_admin_inactive")
        clear_login_lock(conn, row["user_id"])
        conn.execute(
            text("UPDATE saas_users SET last_login_at = NOW(), updated_at = NOW() WHERE id = CAST(:id AS uuid)"),
            {"id": row["user_id"]},
        )
        record_security_event(
            conn,
            event_type="admin.login",
            status="success",
            request=request,
            principal=row["email"],
            rate_key=rate_key,
            user_id=row["user_id"],
            reason="mfa_verified",
        )
        send_security_notice(
            row["email"],
            "Nuevo ingreso protegido al Admin Scentra",
            "Se completo un ingreso al panel Admin con segundo factor. Si no fuiste tu, cambia tu clave de inmediato.",
        )
    return _admin_token(dict(row), mfa_verified=True)


@router.get("/auth/me")
def admin_me(ctx: PlatformAuthContext = Depends(get_current_platform_admin)):
    with db_session() as conn:
        row = conn.execute(
            text(
                """
                SELECT email, full_name, profile_json
                FROM saas_users
                WHERE id = CAST(:user_id AS uuid)
                LIMIT 1
                """
            ),
            {"user_id": ctx.user_id},
        ).mappings().first()
    return {
        "user_id": ctx.user_id,
        "email": normalize_email(str((row or {}).get("email") or ctx.email)),
        "full_name": str((row or {}).get("full_name") or "").strip(),
        "profile_json": dict((row or {}).get("profile_json") or {}),
        "platform_role": ctx.platform_role,
    }


@router.patch("/auth/profile")
def admin_update_profile(payload: AdminProfilePatchIn, request: Request, ctx: PlatformAuthContext = Depends(get_current_platform_admin)):
    next_email = normalize_email(payload.email or ctx.email)
    full_name = _clean(payload.full_name, 180)
    profile_patch = {
        "phone": _clean(payload.phone, 60),
        "role_label": _clean(payload.role_label, 120),
        "avatar_url": _clean(payload.avatar_url, 1000),
    }
    if next_email and "@" not in next_email:
        raise HTTPException(status_code=400, detail="valid_email_required")
    with db_session() as conn:
        current = conn.execute(
            text(
                """
                SELECT id::text, email, password_hash, status, full_name
                FROM saas_users
                WHERE id = CAST(:user_id AS uuid)
                LIMIT 1
                """
            ),
            {"user_id": ctx.user_id},
        ).mappings().first()
        if not current or current["status"] != "active":
            raise HTTPException(status_code=404, detail="user_not_found")
        email_changed = next_email and next_email != normalize_email(current["email"])
        if email_changed:
            if not payload.current_password or not verify_password(payload.current_password, current["password_hash"]):
                raise HTTPException(status_code=401, detail="invalid_current_password")
            duplicate = conn.execute(
                text("SELECT id::text FROM saas_users WHERE email = :email AND id <> CAST(:user_id AS uuid) LIMIT 1"),
                {"email": next_email, "user_id": ctx.user_id},
            ).mappings().first()
            if duplicate:
                raise HTTPException(status_code=409, detail="email_already_registered")
        row = conn.execute(
            text(
                """
                UPDATE saas_users
                SET email = :email,
                    full_name = :full_name,
                    profile_json = COALESCE(profile_json, '{}'::jsonb) || CAST(:profile_json AS jsonb),
                    updated_at = NOW()
                WHERE id = CAST(:user_id AS uuid)
                RETURNING id::text, email, full_name, profile_json
                """
            ),
            {
                "user_id": ctx.user_id,
                "email": next_email or current["email"],
                "full_name": full_name or current["full_name"] or "",
                "profile_json": _json(profile_patch),
            },
        ).mappings().first()
        record_security_event(
            conn,
            event_type="admin.profile_update",
            status="success",
            request=request,
            principal=ctx.email,
            user_id=ctx.user_id,
            reason="email_changed" if email_changed else "profile_updated",
        )
    return {"ok": True, "user": dict(row or {})}


@router.post("/auth/password/change")
def admin_change_password(payload: AdminPasswordChangeIn, request: Request, ctx: PlatformAuthContext = Depends(get_current_platform_admin)):
    rate_key = rate_limit_key(action="admin.password_change", principal=ctx.email, request=request)
    auth_error: HTTPException | None = None
    with db_session() as conn:
        enforce_auth_rate_limits(
            conn,
            event_type="admin.password_change",
            rate_key=rate_key,
            combined_limit=6,
            principal_limit=10,
            ip_limit=30,
            window_seconds=3600,
            request=request,
            principal=ctx.email,
            count_statuses=("failed", "blocked"),
        )
        row = conn.execute(
            text(
                """
                SELECT id::text, password_hash, status
                FROM saas_users
                WHERE id = CAST(:user_id AS uuid)
                LIMIT 1
                """
            ),
            {"user_id": ctx.user_id},
        ).mappings().first()
        if not row or row["status"] != "active" or not verify_password(payload.current_password, row["password_hash"]):
            record_security_event(
                conn,
                event_type="admin.password_change",
                status="failed",
                request=request,
                principal=ctx.email,
                rate_key=rate_key,
                user_id=ctx.user_id,
                reason="invalid_current_password",
            )
            auth_error = HTTPException(status_code=401, detail="invalid_current_password")
        if not auth_error:
            conn.execute(
                text(
                    """
                    UPDATE saas_users
                    SET password_hash = :password_hash,
                        password_algo = 'argon2id',
                        password_changed_at = NOW(),
                        failed_login_count = 0,
                        locked_until = NULL,
                        updated_at = NOW()
                    WHERE id = CAST(:user_id AS uuid)
                    """
                ),
                {"user_id": ctx.user_id, "password_hash": hash_password(payload.new_password)},
            )
            record_security_event(
                conn,
                event_type="admin.password_change",
                status="success",
                request=request,
                principal=ctx.email,
                rate_key=rate_key,
                user_id=ctx.user_id,
            )
            send_security_notice(
                ctx.email,
                "Clave actualizada en Scentra Admin",
                "Tu clave del panel Admin fue actualizada. Si no fuiste tu, contacta al superadmin.",
            )
    if auth_error:
        raise auth_error
    return {"ok": True}


@router.get("/auth/security")
def admin_security_status(ctx: PlatformAuthContext = Depends(get_current_platform_admin)):
    with db_session() as conn:
        row = conn.execute(
            text(
                """
                SELECT two_factor_enabled, two_factor_method, locked_until::text, password_changed_at::text
                FROM saas_users
                WHERE id = CAST(:user_id AS uuid)
                LIMIT 1
                """
            ),
            {"user_id": ctx.user_id},
        ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="user_not_found")
    method = str(row["two_factor_method"] or "none").strip().lower()
    return {
        "two_factor_enabled": bool(row["two_factor_enabled"]),
        "two_factor_method": method if method == "email_otp" else "none",
        "locked_until": row["locked_until"],
        "password_changed_at": row["password_changed_at"],
        "smtp_configured": smtp_is_configured(),
    }


@router.patch("/auth/security/2fa")
def admin_update_two_factor(payload: AdminTwoFactorPatchIn, request: Request, ctx: PlatformAuthContext = Depends(get_current_platform_admin)):
    method = str(payload.method or "email_otp").strip().lower()
    if payload.enabled and method != "email_otp":
        raise HTTPException(status_code=400, detail="invalid_two_factor_method")
    if payload.enabled and not smtp_is_configured() and not settings.is_local:
        raise HTTPException(status_code=409, detail="smtp_required_for_email_otp")
    if not payload.enabled:
        method = "none"
    with db_session() as conn:
        row = conn.execute(
            text(
                """
                UPDATE saas_users
                SET two_factor_enabled = :enabled,
                    two_factor_method = :method,
                    updated_at = NOW()
                WHERE id = CAST(:user_id AS uuid)
                RETURNING two_factor_enabled, two_factor_method, locked_until::text, password_changed_at::text
                """
            ),
            {"user_id": ctx.user_id, "enabled": bool(payload.enabled), "method": method},
        ).mappings().first()
        record_security_event(
            conn,
            event_type="admin.two_factor_policy",
            status="success",
            request=request,
            principal=ctx.email,
            user_id=ctx.user_id,
            reason="two_factor_enabled" if payload.enabled else "two_factor_disabled",
            details={"method": method},
        )
        send_security_notice(
            ctx.email,
            "Cambio de seguridad en Scentra Admin",
            f"El segundo factor fue {'activado' if payload.enabled else 'desactivado'} para tu cuenta Admin.",
        )
    return {
        "two_factor_enabled": bool(row["two_factor_enabled"]) if row else False,
        "two_factor_method": str((row or {}).get("two_factor_method") or "none"),
        "locked_until": (row or {}).get("locked_until"),
        "password_changed_at": (row or {}).get("password_changed_at"),
        "smtp_configured": smtp_is_configured(),
    }


@router.get("/users/platform")
def list_platform_admins(ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support"))):
    with db_session() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    u.id::text AS user_id,
                    u.email,
                    u.full_name,
                    u.status AS user_status,
                    u.last_login_at::text,
                    u.password_changed_at::text,
                    u.two_factor_enabled,
                    pa.role AS platform_role,
                    pa.status AS platform_status,
                    pa.notes,
                    pa.created_at::text,
                    pa.updated_at::text
                FROM saas_platform_admins pa
                JOIN saas_users u ON u.id = pa.user_id
                ORDER BY pa.updated_at DESC
                LIMIT 300
                """
            )
        ).mappings().all()
    return {"ok": True, "admins": [dict(row) for row in rows], "roles": sorted(PLATFORM_ROLE_ORDER.keys())}


@router.post("/users/platform")
def create_platform_admin_user(
    payload: PlatformAdminCreateIn,
    request: Request,
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin")),
):
    email = normalize_email(payload.email)
    role = _clean(payload.platform_role, 40).lower() or "support"
    status = _clean(payload.status, 40).lower() or "active"
    if role not in PLATFORM_ROLE_ORDER:
        raise HTTPException(status_code=400, detail="invalid_platform_role")
    if status not in PLATFORM_ADMIN_STATUSES:
        raise HTTPException(status_code=400, detail="invalid_platform_status")
    if role == "superadmin" and ctx.platform_role != "superadmin":
        raise HTTPException(status_code=403, detail="superadmin_role_requires_superadmin")
    with db_session() as conn:
        user = conn.execute(
            text(
                """
                INSERT INTO saas_users (email, full_name, password_hash, password_algo, password_changed_at)
                VALUES (:email, :full_name, :password_hash, 'argon2id', NOW())
                ON CONFLICT (email)
                DO UPDATE SET full_name = COALESCE(NULLIF(EXCLUDED.full_name, ''), saas_users.full_name), updated_at = NOW()
                RETURNING id::text, email
                """
            ),
            {"email": email, "full_name": _clean(payload.full_name, 180), "password_hash": hash_password(payload.password)},
        ).mappings().first()
        row = conn.execute(
            text(
                """
                INSERT INTO saas_platform_admins (user_id, role, status, notes, updated_at)
                VALUES (CAST(:user_id AS uuid), :role, :status, :notes, NOW())
                ON CONFLICT (user_id)
                DO UPDATE SET role = EXCLUDED.role, status = EXCLUDED.status, notes = EXCLUDED.notes, updated_at = NOW()
                RETURNING user_id::text, role, status, notes, updated_at::text
                """
            ),
            {"user_id": user["id"], "role": role, "status": status, "notes": _clean(payload.notes, 1000)},
        ).mappings().first()
        _audit(conn, actor=ctx, action="admin.platform_user.upsert", resource_type="platform_admin", resource_id=user["id"], details=dict(row or {}))
        email_sent = False
        if payload.send_email and smtp_is_configured():
            with contextlib.suppress(Exception):
                email_sent = send_welcome_email(
                    to_email=email,
                    full_name=_clean(payload.full_name, 180),
                    tenant_name="Scentra Admin",
                    role_label=_role_label(role, platform=True),
                    login_url=_admin_app_url(),
                    temporary_password=payload.password,
                )
    return {"ok": True, "admin": dict(row or {}), "user_id": user["id"], "email_sent": email_sent}


@router.patch("/users/platform/{user_id}")
def update_platform_admin_user(
    user_id: str,
    payload: PlatformAdminPatchIn,
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin")),
):
    role = _clean(payload.platform_role, 40).lower()
    status = _clean(payload.status, 40).lower()
    if role and role not in PLATFORM_ROLE_ORDER:
        raise HTTPException(status_code=400, detail="invalid_platform_role")
    if status and status not in PLATFORM_ADMIN_STATUSES:
        raise HTTPException(status_code=400, detail="invalid_platform_status")
    if role == "superadmin" and ctx.platform_role != "superadmin":
        raise HTTPException(status_code=403, detail="superadmin_role_requires_superadmin")
    if user_id == ctx.user_id and status and status != "active":
        raise HTTPException(status_code=400, detail="cannot_disable_self")
    with db_session() as conn:
        current = conn.execute(
            text(
                """
                SELECT u.email, u.full_name, pa.role, pa.status
                FROM saas_platform_admins pa
                JOIN saas_users u ON u.id = pa.user_id
                WHERE pa.user_id = CAST(:user_id AS uuid)
                LIMIT 1
                """
            ),
            {"user_id": user_id},
        ).mappings().first()
        row = conn.execute(
            text(
                """
                UPDATE saas_platform_admins
                SET role = COALESCE(NULLIF(:role, ''), role),
                    status = COALESCE(NULLIF(:status, ''), status),
                    notes = COALESCE(:notes, notes),
                    updated_at = NOW()
                WHERE user_id = CAST(:user_id AS uuid)
                RETURNING user_id::text, role, status, notes, updated_at::text
                """
            ),
            {"user_id": user_id, "role": role, "status": status, "notes": payload.notes},
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="platform_admin_not_found")
        _audit(conn, actor=ctx, action="admin.platform_user.update", resource_type="platform_admin", resource_id=user_id, details=dict(row))
        if current and smtp_is_configured():
            changed = role or status
            if changed:
                body = (
                    "Tu acceso al panel Scentra Admin fue actualizado.\n\n"
                    f"Rol actual: {_role_label(row['role'], platform=True)}.\n"
                    f"Estado actual: {_status_label(row['status'])}.\n"
                    f"Acción realizada por: {ctx.email}."
                )
                with contextlib.suppress(Exception):
                    send_alert_email(
                        to_email=current["email"],
                        subject="Cambio en tu acceso Scentra Admin",
                        body=body,
                        severity="warning",
                        cta_url=_admin_app_url(),
                    )
    return {"ok": True, "admin": dict(row)}


@router.get("/users/tenants")
def list_tenant_users(
    tenant_id: str = Query("", max_length=80),
    search: str = Query("", max_length=160),
    limit: int = Query(300, ge=1, le=500),
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support")),
):
    where = ["1=1"]
    params: dict[str, Any] = {"limit": limit, "tenant_id": tenant_id, "search": f"%{search.lower()}%"}
    if tenant_id:
        where.append("m.tenant_id = CAST(:tenant_id AS uuid)")
    if search:
        where.append("(LOWER(u.email) LIKE :search OR LOWER(u.full_name) LIKE :search OR LOWER(t.name) LIKE :search)")
    with db_session() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT
                    m.id::text,
                    m.tenant_id::text,
                    t.name AS tenant_name,
                    m.user_id::text,
                    u.email,
                    u.full_name,
                    u.status AS user_status,
                    u.last_login_at::text,
                    m.role,
                    m.is_active,
                    m.created_at::text,
                    m.updated_at::text
                FROM saas_memberships m
                JOIN saas_users u ON u.id = m.user_id
                JOIN saas_tenants t ON t.id = m.tenant_id
                WHERE {' AND '.join(where)}
                ORDER BY t.name ASC, u.email ASC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
    return {"ok": True, "members": [dict(row) for row in rows], "roles": sorted(IMPERSONATION_ROLES)}


@router.post("/users/tenants")
def create_tenant_user(
    payload: AdminTenantUserCreateIn,
    request: Request,
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support")),
):
    role = _clean(payload.role, 40).lower() or "agent"
    if role not in IMPERSONATION_ROLES:
        raise HTTPException(status_code=400, detail="invalid_tenant_role")
    email = normalize_email(payload.email)
    if "@" not in email:
        raise HTTPException(status_code=400, detail="valid_email_required")
    with db_session() as conn:
        tenant = _tenant_exists(conn, payload.tenant_id)
        user = conn.execute(text("SELECT id::text, email FROM saas_users WHERE email = :email LIMIT 1"), {"email": email}).mappings().first()
        created = False
        if not user:
            if not payload.password or len(payload.password) < 8:
                raise HTTPException(status_code=400, detail="password_required_for_new_user")
            user = conn.execute(
                text(
                    """
                    INSERT INTO saas_users (email, full_name, password_hash, password_algo, password_changed_at)
                    VALUES (:email, :full_name, :password_hash, 'argon2id', NOW())
                    RETURNING id::text, email
                    """
                ),
                {"email": email, "full_name": _clean(payload.full_name, 180), "password_hash": hash_password(payload.password)},
            ).mappings().first()
            created = True
        elif payload.full_name:
            conn.execute(
                text("UPDATE saas_users SET full_name = :full_name, updated_at = NOW() WHERE id = CAST(:user_id AS uuid)"),
                {"user_id": user["id"], "full_name": _clean(payload.full_name, 180)},
            )
        member = conn.execute(
            text(
                """
                INSERT INTO saas_memberships (tenant_id, user_id, role, is_active)
                VALUES (CAST(:tenant_id AS uuid), CAST(:user_id AS uuid), :role, TRUE)
                ON CONFLICT (tenant_id, user_id)
                DO UPDATE SET role = EXCLUDED.role, is_active = TRUE, updated_at = NOW()
                RETURNING id::text, tenant_id::text, user_id::text, role, is_active, updated_at::text
                """
            ),
            {"tenant_id": payload.tenant_id, "user_id": user["id"], "role": role},
        ).mappings().first()
        _audit(conn, actor=ctx, action="admin.tenant_user.upsert", resource_type="tenant_user", resource_id=member["id"], tenant_id=payload.tenant_id, details=dict(member))
        record_security_event(
            conn,
            event_type="admin.tenant_user_upsert",
            status="success",
            request=request,
            principal=email,
            tenant_id=payload.tenant_id,
            user_id=user["id"],
            details={"role": role, "created": created, "actor_user_id": ctx.user_id},
        )
        email_sent = False
        if payload.send_email and smtp_is_configured():
            with contextlib.suppress(Exception):
                email_sent = send_welcome_email(
                    to_email=email,
                    full_name=_clean(payload.full_name, 180),
                    tenant_name=str(tenant.get("name") or ""),
                    role_label=_role_label(role),
                    login_url=str(settings.scentra_app_public_url or "").rstrip("/"),
                    temporary_password=payload.password if created else "",
                )
            alert_body = (
                f"Se {'creó' if created else 'actualizó'} el acceso de {email} en {tenant.get('name') or 'Scentra'}.\n\n"
                f"Rol asignado: {_role_label(role)}.\n"
                f"Acción realizada por: {ctx.email}."
            )
            for admin in _tenant_admin_contacts(conn, payload.tenant_id):
                if str(admin.get("email") or "").strip().lower() == email:
                    continue
                with contextlib.suppress(Exception):
                    send_alert_email(to_email=admin["email"], subject="Alerta de usuarios Scentra", body=alert_body, severity="info")
    return {"ok": True, "created": created, "member": dict(member or {}), "user_id": user["id"], "email_sent": email_sent}


@router.patch("/users/tenants/{membership_id}")
def update_tenant_user(
    membership_id: str,
    payload: AdminTenantMembershipPatchIn,
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support")),
):
    role = _clean(payload.role, 40).lower()
    if role and role not in IMPERSONATION_ROLES:
        raise HTTPException(status_code=400, detail="invalid_tenant_role")
    with db_session() as conn:
        current = conn.execute(
            text(
                """
                SELECT
                    m.id::text,
                    m.tenant_id::text,
                    m.user_id::text,
                    m.role,
                    m.is_active,
                    u.email,
                    u.full_name,
                    t.name AS tenant_name
                FROM saas_memberships m
                JOIN saas_users u ON u.id = m.user_id
                JOIN saas_tenants t ON t.id = m.tenant_id
                WHERE m.id = CAST(:membership_id AS uuid)
                LIMIT 1
                """
            ),
            {"membership_id": membership_id},
        ).mappings().first()
        row = conn.execute(
            text(
                """
                UPDATE saas_memberships
                SET role = COALESCE(NULLIF(:role, ''), role),
                    is_active = COALESCE(:is_active, is_active),
                    updated_at = NOW()
                WHERE id = CAST(:membership_id AS uuid)
                RETURNING id::text, tenant_id::text, user_id::text, role, is_active, updated_at::text
                """
            ),
            {"membership_id": membership_id, "role": role, "is_active": payload.is_active},
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="membership_not_found")
        _audit(conn, actor=ctx, action="admin.tenant_user.update", resource_type="tenant_user", resource_id=membership_id, tenant_id=row["tenant_id"], details=dict(row))
        if current and smtp_is_configured():
            changed = role or payload.is_active is not None
            if changed:
                affected_body = (
                    f"Tu acceso en {current['tenant_name'] or 'Scentra'} fue actualizado.\n\n"
                    f"Rol actual: {_role_label(row['role'])}.\n"
                    f"Estado: {'activo' if row['is_active'] else 'inactivo'}."
                )
                with contextlib.suppress(Exception):
                    send_alert_email(to_email=current["email"], subject="Cambio en tu acceso Scentra", body=affected_body, severity="warning")
                admin_body = (
                    f"Se actualizó el usuario {current['email']} en {current['tenant_name'] or 'Scentra'}.\n\n"
                    f"Rol actual: {_role_label(row['role'])}.\n"
                    f"Estado: {'activo' if row['is_active'] else 'inactivo'}.\n"
                    f"Acción realizada por: {ctx.email}."
                )
                for admin in _tenant_admin_contacts(conn, row["tenant_id"], exclude_user_id=row["user_id"]):
                    with contextlib.suppress(Exception):
                        send_alert_email(to_email=admin["email"], subject="Alerta de roles Scentra", body=admin_body, severity="warning")
    return {"ok": True, "member": dict(row)}


@router.get("/feature-flags/catalog")
def feature_flags_catalog(ctx: PlatformAuthContext = Depends(get_current_platform_admin)):
    return {"features": FEATURE_CATALOG}


@router.get("/intelligence/catalog")
def admin_intelligence_catalog(ctx: PlatformAuthContext = Depends(get_current_platform_admin)):
    return {"ok": True, "features": intelligence_catalog()}


@router.get("/intelligence/tenants")
def admin_list_intelligence_tenants(
    limit: int = Query(120, ge=1, le=300),
    ctx: PlatformAuthContext = Depends(get_current_platform_admin),
):
    with db_session() as conn:
        return {"ok": True, "tenants": admin_intelligence_tenants(conn, limit=limit)}


@router.get("/intelligence/tenants/{tenant_id}")
def admin_intelligence_tenant_detail(tenant_id: str, ctx: PlatformAuthContext = Depends(get_current_platform_admin)):
    with db_session() as conn:
        _tenant_exists(conn, tenant_id)
        set_tenant_context(conn, tenant_id)
        return {"ok": True, "state": intelligence_feature_state(conn, tenant_id)}


@router.get("/intelligence/premium-gating")
def admin_intelligence_premium_gating(
    limit: int = Query(120, ge=1, le=300),
    ctx: PlatformAuthContext = Depends(get_current_platform_admin),
):
    with db_session() as conn:
        return {"ok": True, "gating": admin_multimodal_premium_gating(conn, limit=limit)}


@router.patch("/intelligence/plans/{plan_code}/features")
def admin_set_intelligence_plan_feature(
    plan_code: str,
    payload: AdminIntelligencePlanFeaturePatchIn,
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "billing_admin")),
):
    with db_session() as conn:
        limit = upsert_plan_feature_limit(conn, plan_code, payload, actor_user_id=ctx.user_id)
        _audit(
            conn,
            actor=ctx,
            action="admin.intelligence_plan_feature.set",
            resource_type="intelligence_plan_feature_limit",
            resource_id=f"{limit.get('plan_code', plan_code)}:{limit.get('feature_key', payload.feature_key)}",
            details=limit,
        )
        gating = admin_multimodal_premium_gating(conn, limit=120)
    return {"ok": True, "limit": limit, "gating": gating}


@router.patch("/intelligence/provider-policies")
def admin_set_ai_provider_policy(
    payload: AdminAiProviderPolicyPatchIn,
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "billing_admin")),
):
    with db_session() as conn:
        policy = upsert_provider_policy(conn, payload, actor_user_id=ctx.user_id)
        _audit(
            conn,
            actor=ctx,
            action="admin.ai_provider_policy.set",
            resource_type="ai_provider_policy",
            resource_id=f"{policy.get('scope_type')}:{policy.get('scope_id')}:{policy.get('provider_category')}:{policy.get('provider_code')}:{policy.get('model_id') or '*'}",
            details=policy,
        )
        gating = admin_multimodal_premium_gating(conn, limit=120)
    return {"ok": True, "policy": policy, "gating": gating}


@router.get("/intelligence/realtime")
def admin_intelligence_realtime(
    tenant_id: str = Query("", max_length=80),
    limit: int = Query(80, ge=1, le=200),
    ctx: PlatformAuthContext = Depends(get_current_platform_admin),
):
    with db_session() as conn:
        if tenant_id:
            _tenant_exists(conn, tenant_id)
        return {"ok": True, "realtime": admin_realtime_overview(conn, tenant_id=tenant_id, limit=limit)}


@router.post("/intelligence/realtime/metrics/refresh")
def admin_intelligence_realtime_metrics_refresh(
    tenant_id: str = Query("", max_length=80),
    limit: int = Query(80, ge=1, le=200),
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support")),
):
    with db_session() as conn:
        if tenant_id:
            _tenant_exists(conn, tenant_id)
        result = admin_refresh_realtime_metrics(conn, tenant_id=tenant_id, limit=limit)
        _audit(
            conn,
            actor=ctx,
            action="admin.intelligence_realtime.metrics_refresh",
            resource_type="realtime_intelligence_metrics",
            resource_id=tenant_id or "all",
            tenant_id=tenant_id or None,
            details={"snapshots_written": result.get("snapshots_written", 0)},
        )
    return {"ok": True, **result}


@router.patch("/intelligence/tenants/{tenant_id}/features")
def admin_set_intelligence_feature(
    tenant_id: str,
    payload: AdminIntelligenceFeaturePatchIn,
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "billing_admin")),
):
    with db_session() as conn:
        _tenant_exists(conn, tenant_id)
        grant = upsert_feature_grant(conn, tenant_id, payload, actor_user_id=ctx.user_id)
        _audit(
            conn,
            actor=ctx,
            action="admin.intelligence_feature.set",
            resource_type="intelligence_feature_grant",
            resource_id=grant.get("feature_key", ""),
            tenant_id=tenant_id,
            details=grant,
        )
        state = intelligence_feature_state(conn, tenant_id)
    return {"ok": True, "grant": grant, "state": state}


@router.get("/intelligence/model-metrics")
def admin_list_intelligence_model_metrics(
    tenant_id: str = Query("", max_length=80),
    model_key: str = Query("", max_length=160),
    prediction_type: str = Query("", max_length=120),
    limit: int = Query(120, ge=1, le=500),
    ctx: PlatformAuthContext = Depends(get_current_platform_admin),
):
    with db_session() as conn:
        if tenant_id:
            _tenant_exists(conn, tenant_id)
        return {
            "ok": True,
            "metrics": list_model_metrics(conn, tenant_id=tenant_id, model_key=model_key, prediction_type=prediction_type, limit=limit),
        }


@router.post("/intelligence/model-metrics/recompute")
def admin_recompute_intelligence_model_metrics(
    payload: ModelMetricsRecomputeIn,
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support")),
):
    with db_session() as conn:
        if payload.tenant_id:
            _tenant_exists(conn, payload.tenant_id)
        metrics = recompute_model_metrics(
            conn,
            tenant_id=payload.tenant_id,
            model_key=payload.model_key,
            prediction_type=payload.prediction_type,
            window_key=payload.window_key,
        )
        _audit(
            conn,
            actor=ctx,
            action="admin.intelligence_model_metrics.recompute",
            resource_type="intelligence_model_metrics",
            resource_id=payload.model_key or payload.prediction_type or "all",
            tenant_id=payload.tenant_id or None,
            details={"count": len(metrics), "window_key": payload.window_key},
        )
    return {"ok": True, "metrics": metrics}


@router.get("/intelligence/training-dataset")
def admin_intelligence_training_dataset(
    tenant_id: str = Query("", max_length=80),
    model_key: str = Query("", max_length=160),
    prediction_type: str = Query("", max_length=120),
    window_key: str = Query("90d", max_length=80),
    only_labeled: bool = Query(True),
    limit: int = Query(80, ge=1, le=500),
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin")),
):
    with db_session() as conn:
        if tenant_id:
            _tenant_exists(conn, tenant_id)
        dataset = training_dataset_readiness(
            conn,
            tenant_id=tenant_id,
            model_key=model_key,
            prediction_type=prediction_type,
            window_key=window_key,
            only_labeled=only_labeled,
            limit=limit,
        )
    return {"ok": True, **dataset}


@router.get("/intelligence/mlops")
def admin_intelligence_mlops(
    tenant_id: str = Query("", max_length=80),
    limit: int = Query(80, ge=1, le=300),
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support")),
):
    with db_session() as conn:
        if tenant_id:
            _tenant_exists(conn, tenant_id)
        overview = mlops_overview(conn, tenant_id=tenant_id, limit=limit)
    return {"ok": True, **overview}


@router.post("/intelligence/auto-labels/generate")
def admin_generate_intelligence_auto_labels(
    payload: AutoLabelGenerationRequestIn,
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin")),
):
    with db_session() as conn:
        if payload.tenant_id:
            _tenant_exists(conn, payload.tenant_id)
        result = generate_auto_labels(
            conn,
            tenant_id=payload.tenant_id,
            prediction_type=payload.prediction_type,
            window_key=payload.window_key,
            limit=payload.limit,
        )
        _audit(
            conn,
            actor=ctx,
            action="admin.intelligence_auto_labels.generate",
            resource_type="ml_auto_labels",
            resource_id=payload.prediction_type or "all",
            tenant_id=payload.tenant_id or None,
            details=result,
        )
    return {"ok": True, **result}


@router.post("/intelligence/feature-pipelines/recompute")
def admin_recompute_intelligence_feature_pipelines(
    payload: FeaturePipelineRequestIn,
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin")),
):
    with db_session() as conn:
        if payload.tenant_id:
            _tenant_exists(conn, payload.tenant_id)
        result = recompute_training_feature_pipelines(
            conn,
            tenant_id=payload.tenant_id,
            prediction_type=payload.prediction_type,
            window_key=payload.window_key,
            limit=payload.limit,
        )
        _audit(
            conn,
            actor=ctx,
            action="admin.intelligence_feature_pipelines.recompute",
            resource_type="ml_feature_pipeline",
            resource_id=payload.prediction_type or "all",
            tenant_id=payload.tenant_id or None,
            details=result,
        )
    return {"ok": True, **result}


@router.post("/intelligence/ml-datasets/build")
def admin_build_intelligence_ml_dataset(
    payload: DatasetBuildRequestIn,
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin")),
):
    with db_session() as conn:
        if payload.tenant_id:
            _tenant_exists(conn, payload.tenant_id)
    dataset_result = request_ml_dataset_build(payload)
    with db_session() as conn:
        _audit(
            conn,
            actor=ctx,
            action="admin.intelligence_ml_dataset.build",
            resource_type="ml_training_dataset",
            resource_id=((dataset_result.get("dataset") or {}).get("dataset_key") or payload.dataset_key or payload.task_type),
            tenant_id=payload.tenant_id or None,
            details=dataset_result,
        )
    return {"ok": True, **dataset_result}


@router.post("/intelligence/ml-training/synthetic")
def admin_run_synthetic_ml_training(
    payload: SyntheticTrainingRequestIn,
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin")),
):
    with db_session() as conn:
        if payload.tenant_id:
            _tenant_exists(conn, payload.tenant_id)
    training_result = request_ml_synthetic_training(payload)
    registry_model = None
    registry_error = None
    artifact = training_result.get("artifact") or {}
    if payload.register_model_registry and artifact.get("model_key"):
        try:
            with db_session() as conn:
                registry_model = register_model_registry_entry(
                    conn,
                    ModelRegistryCreateIn(
                        model_key=artifact.get("model_key") or payload.model_key,
                        model_type="trained_ml",
                        task_type=artifact.get("task_type") or payload.task_type,
                        framework=artifact.get("framework") or payload.framework,
                        version=artifact.get("version") or payload.version or "v1",
                        status="candidate",
                        stage="shadow",
                        artifact_uri=artifact.get("artifact_uri") or "",
                        shadow_mode=True,
                        rollout_mode="shadow",
                        traffic_percent=0,
                        promotion_status="pending_review",
                        metadata_json={
                            "training_job_id": training_result.get("job_id") or "",
                            "mlflow_run_id": artifact.get("mlflow_run_id") or "",
                            "bentoml_tag": artifact.get("bentoml_tag") or "",
                            "training_source": "synthetic_autolabel",
                        },
                        reason="Synthetic ML training registered from Scentra Admin",
                    ),
                    actor_user_id=ctx.user_id,
                )
                _audit(
                    conn,
                    actor=ctx,
                    action="admin.intelligence_ml_training.synthetic",
                    resource_type="intelligence_model",
                    resource_id=registry_model.get("model_key", ""),
                    tenant_id=payload.tenant_id or None,
                    details={"training_result": training_result, "registry_model": registry_model},
                )
        except HTTPException as exc:
            registry_error = exc.detail
    return {"ok": True, "training": training_result, "registry_model": registry_model, "registry_error": registry_error}


@router.post("/intelligence/ml-training/autolabel")
def admin_run_autolabel_ml_training(
    payload: AutoLabelTrainingRequestIn,
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin")),
):
    with db_session() as conn:
        if payload.tenant_id:
            _tenant_exists(conn, payload.tenant_id)
    training_result = request_ml_autolabel_training(payload)
    registry_model = None
    registry_error = None
    artifact = training_result.get("artifact") or {}
    if payload.register_model_registry and artifact.get("model_key"):
        try:
            with db_session() as conn:
                registry_model = register_model_registry_entry(
                    conn,
                    ModelRegistryCreateIn(
                        model_key=artifact.get("model_key") or payload.model_key,
                        model_type="trained_ml",
                        task_type=artifact.get("task_type") or payload.task_type,
                        framework=artifact.get("framework") or payload.framework,
                        version=artifact.get("version") or payload.version or "v1",
                        status="candidate",
                        stage="shadow",
                        artifact_uri=artifact.get("artifact_uri") or "",
                        shadow_mode=True,
                        rollout_mode="shadow",
                        traffic_percent=0,
                        promotion_status="pending_review",
                        metadata_json={
                            "training_job_id": training_result.get("job_id") or "",
                            "mlflow_run_id": artifact.get("mlflow_run_id") or "",
                            "bentoml_tag": artifact.get("bentoml_tag") or "",
                            "dataset": artifact.get("dataset") or {},
                            "training_source": "postgres_auto_labels",
                            "raw_content_used": False,
                        },
                        reason="Autolabel ML training registered from Scentra Admin",
                    ),
                    actor_user_id=ctx.user_id,
                )
                _audit(
                    conn,
                    actor=ctx,
                    action="admin.intelligence_ml_training.autolabel",
                    resource_type="intelligence_model",
                    resource_id=registry_model.get("model_key", ""),
                    tenant_id=payload.tenant_id or None,
                    details={"training_result": training_result, "registry_model": registry_model},
                )
        except HTTPException as exc:
            registry_error = exc.detail
    return {"ok": True, "training": training_result, "registry_model": registry_model, "registry_error": registry_error}


@router.get("/intelligence/models")
def admin_list_intelligence_models(
    model_key: str = Query("", max_length=160),
    limit: int = Query(120, ge=1, le=300),
    ctx: PlatformAuthContext = Depends(get_current_platform_admin),
):
    with db_session() as conn:
        return {"ok": True, "models": list_model_registry(conn, model_key=model_key, limit=limit)}


@router.post("/intelligence/models")
def admin_register_intelligence_model(
    payload: ModelRegistryCreateIn,
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin")),
):
    with db_session() as conn:
        model = register_model_registry_entry(conn, payload, actor_user_id=ctx.user_id)
        _audit(
            conn,
            actor=ctx,
            action="admin.intelligence_model_registry.create",
            resource_type="intelligence_model",
            resource_id=model.get("model_key", ""),
            details=model,
        )
    return {"ok": True, "model": model}


@router.get("/intelligence/models/{model_key}/assessment")
def admin_assess_intelligence_model(model_key: str, ctx: PlatformAuthContext = Depends(get_current_platform_admin)):
    with db_session() as conn:
        return {"ok": True, "assessment": assess_model_rollout(conn, model_key)}


@router.patch("/intelligence/models/{model_key}")
def admin_update_intelligence_model(
    model_key: str,
    payload: ModelRegistryPatchIn,
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support")),
):
    with db_session() as conn:
        model = update_model_registry_control(conn, model_key, payload, actor_user_id=ctx.user_id)
        _audit(
            conn,
            actor=ctx,
            action="admin.intelligence_model_registry.update",
            resource_type="intelligence_model",
            resource_id=model_key,
            details=model,
        )
    return {"ok": True, "model": model}


@router.get("/overview")
def platform_overview(ctx: PlatformAuthContext = Depends(get_current_platform_admin)):
    period = _period_yyyymm()
    with db_session() as conn:
        tenant_counts = conn.execute(
            text(
                """
                SELECT
                    COUNT(*)::int AS total,
                    COUNT(*) FILTER (WHERE status = 'active')::int AS active,
                    COUNT(*) FILTER (WHERE status = 'trial')::int AS trial,
                    COUNT(*) FILTER (WHERE status = 'paused')::int AS paused,
                    COUNT(*) FILTER (WHERE status = 'past_due')::int AS past_due,
                    COUNT(*) FILTER (WHERE status = 'suspended')::int AS suspended,
                    COUNT(*) FILTER (WHERE status = 'cancelled')::int AS cancelled
                FROM saas_tenants
                """
            )
        ).mappings().first()
        plans = conn.execute(
            text("SELECT plan_code, COUNT(*)::int AS tenants FROM saas_tenants GROUP BY plan_code ORDER BY plan_code ASC")
        ).mappings().all()
        subscriptions = conn.execute(
            text("SELECT status, COUNT(*)::int AS total FROM saas_billing_subscriptions GROUP BY status ORDER BY status ASC")
        ).mappings().all()
        usage = conn.execute(
            text(
                """
                SELECT metric_code, SUM(metric_value)::bigint AS total
                FROM saas_usage_counters
                WHERE period_yyyymm = :period
                GROUP BY metric_code
                ORDER BY metric_code ASC
                """
            ),
            {"period": period},
        ).mappings().all()
        queues = _queue_counts(conn)
    return {
        "period_yyyymm": period,
        "tenants": dict(tenant_counts or {}),
        "plans": [dict(row) for row in plans],
        "subscriptions": [dict(row) for row in subscriptions],
        "usage": [dict(row) for row in usage],
        "queues": queues,
    }


def _queue_counts(conn) -> dict[str, Any]:
    return queue_snapshot(conn)


@router.get("/tenants")
def list_tenants(
    search: str = Query("", max_length=160),
    status: str = Query("all", max_length=40),
    plan_code: str = Query("all", max_length=40),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ctx: PlatformAuthContext = Depends(get_current_platform_admin),
):
    where = ["1=1"]
    params: dict[str, Any] = {"limit": limit, "offset": offset, "period": _period_yyyymm()}
    clean_search = _clean(search, 160).lower()
    if clean_search:
        params["search"] = f"%{clean_search}%"
        where.append("(LOWER(t.name) LIKE :search OR LOWER(t.slug) LIKE :search)")
    if status and status != "all":
        params["status"] = _clean(status, 40).lower()
        where.append("t.status = :status")
    if plan_code and plan_code != "all":
        params["plan_code"] = _clean(plan_code, 40).lower()
        where.append("t.plan_code = :plan_code")
    where_sql = " AND ".join(where)
    with db_session() as conn:
        total = int(conn.execute(text(f"SELECT COUNT(*) FROM saas_tenants t WHERE {where_sql}"), params).scalar_one() or 0)
        rows = conn.execute(
            text(
                f"""
                SELECT
                    t.id::text,
                    t.slug,
                    t.name,
                    t.status,
                    t.plan_code,
                    t.timezone,
                    t.locale,
                    t.industry_code,
                    t.vertical_pack_version,
                    t.vertical_pack_applied_at::text,
                    t.created_at::text,
                    t.updated_at::text,
                    COALESCE((SELECT COUNT(*)::int FROM saas_memberships m WHERE m.tenant_id = t.id AND m.is_active = TRUE), 0) AS users_count,
                    COALESCE((SELECT COUNT(*)::int FROM saas_integrations i WHERE i.tenant_id = t.id AND i.status <> 'disconnected'), 0) AS integrations_count,
                    COALESCE((SELECT SUM(metric_value)::bigint FROM saas_usage_counters u WHERE u.tenant_id = t.id AND u.period_yyyymm = :period AND u.metric_code IN ('messages_in', 'outbound_messages_queued')), 0) AS used_monthly_messages,
                    COALESCE((SELECT status FROM saas_billing_subscriptions s WHERE s.tenant_id = t.id ORDER BY s.updated_at DESC LIMIT 1), 'none') AS subscription_status,
                    COALESCE((
                        SELECT NULLIF(u.full_name, '')
                        FROM saas_memberships m
                        JOIN saas_users u ON u.id = m.user_id
                        WHERE m.tenant_id = t.id AND m.role = 'owner' AND m.is_active = TRUE
                        ORDER BY m.created_at ASC
                        LIMIT 1
                    ), '') AS owner_name,
                    COALESCE((
                        SELECT u.email
                        FROM saas_memberships m
                        JOIN saas_users u ON u.id = m.user_id
                        WHERE m.tenant_id = t.id AND m.role = 'owner' AND m.is_active = TRUE
                        ORDER BY m.created_at ASC
                        LIMIT 1
                    ), '') AS owner_email
                FROM saas_tenants t
                WHERE {where_sql}
                ORDER BY t.updated_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).mappings().all()
    return {"total": total, "limit": limit, "offset": offset, "tenants": [dict(row) for row in rows]}


@router.get("/tenants/{tenant_id}")
def tenant_detail(tenant_id: str, ctx: PlatformAuthContext = Depends(get_current_platform_admin)):
    with db_session() as conn:
        tenant = _tenant_exists(conn, tenant_id)
        set_tenant_context(conn, tenant_id)
        owner = conn.execute(
            text(
                """
                SELECT u.id::text AS user_id, u.email, u.full_name
                FROM saas_memberships m
                JOIN saas_users u ON u.id = m.user_id
                WHERE m.tenant_id = CAST(:tenant_id AS uuid)
                  AND m.role = 'owner'
                  AND m.is_active = TRUE
                ORDER BY m.created_at ASC
                LIMIT 1
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().first()
        overview = billing_overview(conn, tenant_id)
        members = conn.execute(
            text(
                """
                SELECT m.id::text, m.role, m.is_active, m.created_at::text, m.updated_at::text,
                       u.id::text AS user_id, u.email, u.full_name, u.status AS user_status, u.last_login_at::text
                FROM saas_memberships m
                JOIN saas_users u ON u.id = m.user_id
                WHERE m.tenant_id = CAST(:tenant_id AS uuid)
                ORDER BY m.created_at ASC
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().all()
        integrations = conn.execute(
            text(
                """
                SELECT id::text, provider, channel, status, secret_ref, config_json, last_sync_at::text, updated_at::text
                FROM saas_integrations
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                ORDER BY provider ASC, channel ASC
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().all()
        features = conn.execute(
            text(
                """
                SELECT feature_key, is_enabled, source, notes, updated_at::text
                FROM saas_tenant_feature_flags
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                ORDER BY feature_key ASC
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().all()
        audit = conn.execute(
            text(
                """
                SELECT id, action, resource_type, resource_id, details_json, created_at::text
                FROM saas_audit_events
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                ORDER BY created_at DESC
                LIMIT 30
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().all()
    return {
        "tenant": tenant,
        "owner": dict(owner) if owner else None,
        "billing": overview,
        "members": [dict(row) for row in members],
        "integrations": [dict(row) for row in integrations],
        "feature_flags": [dict(row) for row in features],
        "audit": [dict(row) for row in audit],
    }


@router.patch("/tenants/{tenant_id}")
def update_tenant(
    tenant_id: str,
    payload: TenantPatchIn,
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "billing_admin")),
):
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="tenant_patch_required")
    assignments: list[str] = []
    params: dict[str, Any] = {"tenant_id": tenant_id}
    industry_to_apply = ""
    with db_session() as conn:
        _tenant_exists(conn, tenant_id)
        if "plan_code" in data and data["plan_code"]:
            plan_code = _clean(data["plan_code"], 40).lower()
            if not _load_plan(conn, plan_code):
                raise HTTPException(status_code=404, detail="plan_not_found")
            params["plan_code"] = plan_code
            assignments.append("plan_code = :plan_code")
        if "status" in data and data["status"]:
            tenant_status = _clean(data["status"], 40).lower()
            if tenant_status not in TENANT_STATUSES:
                raise HTTPException(status_code=400, detail="invalid_tenant_status")
            params["status"] = tenant_status
            assignments.append("status = :status")
        if "industry_code" in data and data["industry_code"]:
            industry_to_apply = normalize_industry_code(data["industry_code"])
            params["industry_code"] = industry_to_apply
            assignments.append("industry_code = :industry_code")
        for key in ("name", "timezone", "locale"):
            if key in data and data[key] is not None:
                params[key] = _clean(data[key], 160 if key == "name" else 80)
                assignments.append(f"{key} = :{key}")
        if assignments:
            conn.execute(
                text(
                    f"""
                    UPDATE saas_tenants
                    SET {", ".join(assignments)}, updated_at = NOW()
                    WHERE id = CAST(:tenant_id AS uuid)
                    """
                ),
                params,
            )
        if industry_to_apply:
            set_tenant_context(conn, tenant_id)
            apply_industry_pack(conn, tenant_id, ctx.user_id, industry_to_apply, create_agents=False)
        sub_status = _clean(data.get("subscription_status"), 40).lower()
        if sub_status:
            if sub_status not in SUBSCRIPTION_STATUSES:
                raise HTTPException(status_code=400, detail="invalid_subscription_status")
            conn.execute(
                text(
                    """
                    INSERT INTO saas_billing_subscriptions (
                        tenant_id, provider, provider_subscription_id, status, plan_code,
                        current_period_start, current_period_end, updated_at
                    )
                    VALUES (
                        CAST(:tenant_id AS uuid), 'admin', :provider_subscription_id, :status,
                        COALESCE(:plan_code, (SELECT plan_code FROM saas_tenants WHERE id = CAST(:tenant_id AS uuid))),
                        date_trunc('month', NOW()), date_trunc('month', NOW()) + INTERVAL '1 month', NOW()
                    )
                    ON CONFLICT (provider_subscription_id)
                    DO UPDATE SET status = EXCLUDED.status, plan_code = EXCLUDED.plan_code, updated_at = NOW()
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "provider_subscription_id": f"admin:{tenant_id}",
                    "status": sub_status,
                    "plan_code": params.get("plan_code"),
                },
            )
        _audit(conn, actor=ctx, action="admin.tenant.update", resource_type="tenant", resource_id=tenant_id, tenant_id=tenant_id, details=data)
    with db_session() as conn:
        tenant = _tenant_exists(conn, tenant_id)
    return {"ok": True, "tenant": tenant}


@router.post("/tenants/{tenant_id}/feature-flags")
def set_tenant_feature(
    tenant_id: str,
    payload: FeatureFlagPatchIn,
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support")),
):
    feature_key = normalize_slug(payload.feature_key).replace("-", "_")
    if not feature_key:
        raise HTTPException(status_code=400, detail="valid_feature_key_required")
    with db_session() as conn:
        _tenant_exists(conn, tenant_id)
        row = conn.execute(
            text(
                """
                INSERT INTO saas_tenant_feature_flags (
                    tenant_id, feature_key, is_enabled, source, notes, updated_by_user_id, updated_at
                )
                VALUES (
                    CAST(:tenant_id AS uuid), :feature_key, :is_enabled, :source, :notes, CAST(:user_id AS uuid), NOW()
                )
                ON CONFLICT (tenant_id, feature_key)
                DO UPDATE SET
                    is_enabled = EXCLUDED.is_enabled,
                    source = EXCLUDED.source,
                    notes = EXCLUDED.notes,
                    updated_by_user_id = EXCLUDED.updated_by_user_id,
                    updated_at = NOW()
                RETURNING feature_key, is_enabled, source, notes, updated_at::text
                """
            ),
            {
                "tenant_id": tenant_id,
                "feature_key": feature_key,
                "is_enabled": payload.is_enabled,
                "source": _clean(payload.source, 40) or "admin",
                "notes": _clean(payload.notes, 500),
                "user_id": ctx.user_id,
            },
        ).mappings().first()
        _audit(
            conn,
            actor=ctx,
            action="admin.feature_flag.set",
            resource_type="tenant_feature_flag",
            resource_id=feature_key,
            tenant_id=tenant_id,
            details=dict(row or {}),
        )
    return {"ok": True, "feature": dict(row)}


@router.post("/tenants/{tenant_id}/impersonate")
def impersonate_tenant(
    tenant_id: str,
    payload: TenantImpersonateIn,
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support")),
):
    role = _clean(payload.role, 40).lower() or "admin"
    if role not in IMPERSONATION_ROLES:
        raise HTTPException(status_code=400, detail="invalid_impersonation_role")
    with db_session() as conn:
        tenant = _tenant_exists(conn, tenant_id)
        if tenant["status"] in {"cancelled"}:
            raise HTTPException(status_code=409, detail="tenant_cancelled")
        _audit(
            conn,
            actor=ctx,
            action="admin.tenant.impersonate",
            resource_type="tenant",
            resource_id=tenant_id,
            tenant_id=tenant_id,
            details={"role": role, "reason": _clean(payload.reason, 500)},
        )
    access_token = create_token(
        user_id=ctx.user_id,
        email=ctx.email,
        token_type="access",
        tenant_id=tenant_id,
        role=role,
        expires_delta=timedelta(minutes=20),
    )
    return {
        "ok": True,
        "tenant_id": tenant_id,
        "tenant_name": tenant["name"],
        "role": role,
        "expires_in_minutes": 20,
        "access_token": access_token,
    }


@router.get("/plans")
def list_plans(ctx: PlatformAuthContext = Depends(get_current_platform_admin)):
    with db_session() as conn:
        _ensure_ai_agent_plan_limit_table(conn)
        rows = conn.execute(
            text(
                """
                SELECT plan_code, display_name, max_agents, max_monthly_messages, max_integrations, max_storage_gb,
                       max_campaigns, max_broadcasts, max_ai_tokens, feature_flags_json, price_monthly_cents,
                       currency, is_public, is_active, sort_order, created_at::text, updated_at::text,
                       COALESCE((
                           SELECT jsonb_build_object(
                               'plan_code', apl.plan_code,
                               'max_ai_agents', apl.max_ai_agents,
                               'max_active_ai_agents', apl.max_active_ai_agents,
                               'max_memory_archives', apl.max_memory_archives,
                               'allowed_agent_types_json', apl.allowed_agent_types_json,
                               'builder_enabled', apl.builder_enabled,
                               'notes', apl.notes,
                               'updated_at', apl.updated_at::text
                           )
                           FROM saas_ai_agent_plan_limits apl
                           WHERE apl.plan_code = saas_plan_limits.plan_code
                           LIMIT 1
                       ), '{}'::jsonb) AS ai_agent_limits,
                       (SELECT COUNT(*)::int FROM saas_tenants t WHERE t.plan_code = saas_plan_limits.plan_code) AS tenants_count
                FROM saas_plan_limits
                ORDER BY sort_order ASC, plan_code ASC
                """
            )
        ).mappings().all()
    return {"plans": [dict(row) for row in rows]}


@router.post("/plans")
def upsert_plan(
    payload: PlanUpsertIn,
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "billing_admin")),
):
    plan_code = normalize_slug(payload.plan_code).replace("-", "_")
    if not plan_code:
        raise HTTPException(status_code=400, detail="valid_plan_code_required")
    payload_data = payload.model_dump()
    ai_agent_limits = payload_data.pop("ai_agent_limits", None)
    with db_session() as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO saas_plan_limits (
                    plan_code, display_name, max_agents, max_monthly_messages, max_integrations, max_storage_gb,
                    max_campaigns, max_broadcasts, max_ai_tokens, feature_flags_json, price_monthly_cents,
                    currency, is_public, is_active, sort_order, updated_at
                )
                VALUES (
                    :plan_code, :display_name, :max_agents, :max_monthly_messages, :max_integrations, :max_storage_gb,
                    :max_campaigns, :max_broadcasts, :max_ai_tokens, CAST(:feature_flags_json AS jsonb), :price_monthly_cents,
                    :currency, :is_public, :is_active, :sort_order, NOW()
                )
                ON CONFLICT (plan_code)
                DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    max_agents = EXCLUDED.max_agents,
                    max_monthly_messages = EXCLUDED.max_monthly_messages,
                    max_integrations = EXCLUDED.max_integrations,
                    max_storage_gb = EXCLUDED.max_storage_gb,
                    max_campaigns = EXCLUDED.max_campaigns,
                    max_broadcasts = EXCLUDED.max_broadcasts,
                    max_ai_tokens = EXCLUDED.max_ai_tokens,
                    feature_flags_json = EXCLUDED.feature_flags_json,
                    price_monthly_cents = EXCLUDED.price_monthly_cents,
                    currency = EXCLUDED.currency,
                    is_public = EXCLUDED.is_public,
                    is_active = EXCLUDED.is_active,
                    sort_order = EXCLUDED.sort_order,
                    updated_at = NOW()
                RETURNING plan_code, display_name, max_agents, max_monthly_messages, max_integrations, max_storage_gb,
                          max_campaigns, max_broadcasts, max_ai_tokens, feature_flags_json, price_monthly_cents,
                          currency, is_public, is_active, sort_order, created_at::text, updated_at::text
                """
            ),
            {
                **payload_data,
                "plan_code": plan_code,
                "display_name": _clean(payload.display_name, 120) or plan_code.title(),
                "currency": _clean(payload.currency, 12).upper() or "USD",
                "feature_flags_json": _json(payload.feature_flags_json),
            },
        ).mappings().first()
        updated_ai_limits = _upsert_ai_agent_plan_limits(conn, plan_code, ai_agent_limits)
        plan = _load_plan(conn, plan_code) or dict(row or {})
        _audit(conn, actor=ctx, action="admin.plan.upsert", resource_type="plan", resource_id=plan_code, details={"plan": plan, "ai_agent_limits": updated_ai_limits})
    return {"ok": True, "plan": plan}


@router.patch("/plans/{plan_code}")
def patch_plan(
    plan_code: str,
    payload: PlanPatchIn,
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "billing_admin")),
):
    clean_plan = normalize_slug(plan_code).replace("-", "_")
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="plan_patch_required")
    ai_agent_limits = data.pop("ai_agent_limits", None)
    assignments: list[str] = []
    params: dict[str, Any] = {"plan_code": clean_plan}
    for key, value in data.items():
        if key == "feature_flags_json":
            params[key] = _json(value or {})
            assignments.append("feature_flags_json = CAST(:feature_flags_json AS jsonb)")
        elif key in {"display_name", "currency"}:
            params[key] = _clean(value, 120 if key == "display_name" else 12)
            assignments.append(f"{key} = :{key}")
        else:
            params[key] = value
            assignments.append(f"{key} = :{key}")
    with db_session() as conn:
        if not _load_plan(conn, clean_plan):
            raise HTTPException(status_code=404, detail="plan_not_found")
        if assignments:
            conn.execute(
                text(
                    f"""
                    UPDATE saas_plan_limits
                    SET {", ".join(assignments)}, updated_at = NOW()
                    WHERE plan_code = :plan_code
                    """
                ),
                params,
            )
        updated_ai_limits = _upsert_ai_agent_plan_limits(conn, clean_plan, ai_agent_limits)
        row = _load_plan(conn, clean_plan)
        _audit(conn, actor=ctx, action="admin.plan.patch", resource_type="plan", resource_id=clean_plan, details={"patch": data, "ai_agent_limits": updated_ai_limits})
    return {"ok": True, "plan": dict(row)}


@router.get("/subscriptions")
def list_subscriptions(
    status: str = Query("all", max_length=40),
    limit: int = Query(100, ge=1, le=500),
    ctx: PlatformAuthContext = Depends(get_current_platform_admin),
):
    where = ["1=1"]
    params: dict[str, Any] = {"limit": limit}
    if status and status != "all":
        params["status"] = _clean(status, 40).lower()
        where.append("s.status = :status")
    with db_session() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT DISTINCT ON (s.tenant_id)
                    s.id::text,
                    s.tenant_id::text,
                    t.name AS tenant_name,
                    t.slug AS tenant_slug,
                    s.provider,
                    s.provider_subscription_id,
                    s.status,
                    s.plan_code,
                    s.current_period_start::text,
                    s.current_period_end::text,
                    s.cancel_at_period_end,
                    s.updated_at::text,
                    COALESCE((
                        SELECT NULLIF(u.full_name, '')
                        FROM saas_memberships m
                        JOIN saas_users u ON u.id = m.user_id
                        WHERE m.tenant_id = t.id AND m.role = 'owner' AND m.is_active = TRUE
                        ORDER BY m.created_at ASC
                        LIMIT 1
                    ), '') AS owner_name,
                    COALESCE((
                        SELECT u.email
                        FROM saas_memberships m
                        JOIN saas_users u ON u.id = m.user_id
                        WHERE m.tenant_id = t.id AND m.role = 'owner' AND m.is_active = TRUE
                        ORDER BY m.created_at ASC
                        LIMIT 1
                    ), '') AS owner_email
                FROM saas_billing_subscriptions s
                JOIN saas_tenants t ON t.id = s.tenant_id
                WHERE {" AND ".join(where)}
                ORDER BY s.tenant_id, s.updated_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
    return {"subscriptions": [dict(row) for row in rows]}


@router.patch("/subscriptions/{tenant_id}")
def patch_subscription(
    tenant_id: str,
    payload: SubscriptionPatchIn,
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "billing_admin")),
):
    status = _clean(payload.status, 40).lower()
    if status not in SUBSCRIPTION_STATUSES:
        raise HTTPException(status_code=400, detail="invalid_subscription_status")
    plan_code = _clean(payload.plan_code, 40).lower()
    with db_session() as conn:
        tenant = _tenant_exists(conn, tenant_id)
        if plan_code and not _load_plan(conn, plan_code):
            raise HTTPException(status_code=404, detail="plan_not_found")
        effective_plan = plan_code or tenant["plan_code"]
        conn.execute(
            text("UPDATE saas_tenants SET plan_code = :plan_code, status = :tenant_status, updated_at = NOW() WHERE id = CAST(:tenant_id AS uuid)"),
            {
                "tenant_id": tenant_id,
                "plan_code": effective_plan,
                "tenant_status": "trial" if status == "trial" else "past_due" if status == "past_due" else "suspended" if status == "suspended" else "cancelled" if status == "cancelled" else "active",
            },
        )
        row = conn.execute(
            text(
                """
                INSERT INTO saas_billing_subscriptions (
                    tenant_id, provider, provider_subscription_id, status, plan_code,
                    current_period_start, current_period_end, cancel_at_period_end, updated_at
                )
                VALUES (
                    CAST(:tenant_id AS uuid), 'admin', :provider_subscription_id, :status, :plan_code,
                    date_trunc('month', NOW()), COALESCE(CAST(NULLIF(:current_period_end, '') AS timestamp), date_trunc('month', NOW()) + INTERVAL '1 month'),
                    :cancel_at_period_end, NOW()
                )
                ON CONFLICT (provider_subscription_id)
                DO UPDATE SET
                    status = EXCLUDED.status,
                    plan_code = EXCLUDED.plan_code,
                    current_period_end = EXCLUDED.current_period_end,
                    cancel_at_period_end = EXCLUDED.cancel_at_period_end,
                    updated_at = NOW()
                RETURNING id::text, tenant_id::text, provider, provider_subscription_id, status, plan_code,
                          current_period_start::text, current_period_end::text, cancel_at_period_end, updated_at::text
                """
            ),
            {
                "tenant_id": tenant_id,
                "provider_subscription_id": f"admin:{tenant_id}",
                "status": status,
                "plan_code": effective_plan,
                "current_period_end": _clean(payload.current_period_end, 80),
                "cancel_at_period_end": payload.cancel_at_period_end,
            },
        ).mappings().first()
        _audit(conn, actor=ctx, action="admin.subscription.patch", resource_type="subscription", resource_id=tenant_id, tenant_id=tenant_id, details=dict(row or {}))
    return {"ok": True, "subscription": dict(row)}


@router.get("/billing/invoices")
def admin_billing_invoices(
    tenant_id: str = Query("", max_length=80),
    limit: int = Query(100, ge=1, le=500),
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "billing_admin")),
):
    where = ["1=1"]
    params: dict[str, Any] = {"limit": limit}
    if tenant_id:
        params["tenant_id"] = tenant_id
        where.append("i.tenant_id = CAST(:tenant_id AS uuid)")
    with db_session() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT i.id::text, i.tenant_id::text, t.name AS tenant_name, t.slug AS tenant_slug,
                       i.provider, i.provider_invoice_id, i.invoice_number, i.status,
                       i.plan_code, i.currency, i.total_cents, i.amount_paid_cents,
                       i.amount_due_cents, i.hosted_invoice_url, i.pdf_url,
                       i.period_start::text, i.period_end::text, i.due_at::text,
                       i.paid_at::text, i.created_at::text, i.updated_at::text
                FROM saas_billing_invoices i
                JOIN saas_tenants t ON t.id = i.tenant_id
                WHERE {" AND ".join(where)}
                ORDER BY i.created_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
    return {"invoices": [dict(row) for row in rows]}


@router.post("/billing/invoices")
def admin_create_invoice(
    payload: BillingInvoiceCreateIn,
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "billing_admin")),
):
    with db_session() as conn:
        _tenant_exists(conn, payload.tenant_id)
        invoice = create_manual_invoice(
            conn,
            tenant_id=payload.tenant_id,
            plan_code=payload.plan_code,
            status=payload.status,
            total_cents=payload.total_cents,
            due_at=payload.due_at,
        )
        _audit(conn, actor=ctx, action="admin.billing.invoice.create", resource_type="billing_invoice", resource_id=invoice.get("id", ""), tenant_id=payload.tenant_id, details=invoice)
    return {"ok": True, "invoice": invoice}


@router.get("/billing/invoices/{invoice_id}/pdf")
def admin_invoice_pdf(
    invoice_id: str,
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "billing_admin")),
):
    with db_session() as conn:
        invoice = get_invoice(conn, "", invoice_id)
        conn.execute(
            text("UPDATE saas_billing_invoices SET pdf_generated_at = NOW(), updated_at = NOW() WHERE id = CAST(:invoice_id AS uuid)"),
            {"invoice_id": invoice_id},
        )
        _audit(conn, actor=ctx, action="admin.billing.invoice.pdf", resource_type="billing_invoice", resource_id=invoice_id, tenant_id=invoice.get("tenant_id"), details={"invoice_number": invoice.get("invoice_number")})
    filename = f"scentra-invoice-{invoice.get('invoice_number') or invoice_id}.pdf".replace(" ", "-")
    return Response(
        content=invoice_pdf_bytes(invoice),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/billing/credits")
def admin_billing_credits(
    tenant_id: str = Query("", max_length=80),
    limit: int = Query(100, ge=1, le=500),
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "billing_admin")),
):
    where = ["1=1"]
    params: dict[str, Any] = {"limit": limit}
    if tenant_id:
        params["tenant_id"] = tenant_id
        where.append("c.tenant_id = CAST(:tenant_id AS uuid)")
    with db_session() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT c.id::text, c.tenant_id::text, t.name AS tenant_name, t.slug AS tenant_slug,
                       c.metric_code, c.amount, c.remaining_amount, c.reason,
                       c.expires_at::text, c.created_by_user_id::text,
                       c.created_at::text, c.updated_at::text
                FROM saas_billing_credits c
                JOIN saas_tenants t ON t.id = c.tenant_id
                WHERE {" AND ".join(where)}
                ORDER BY c.created_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
    return {"credits": [dict(row) for row in rows]}


@router.post("/billing/credits")
def admin_create_credit(
    payload: BillingCreditCreateIn,
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "billing_admin")),
):
    with db_session() as conn:
        _tenant_exists(conn, payload.tenant_id)
        credit = apply_manual_credit(
            conn,
            tenant_id=payload.tenant_id,
            actor_user_id=ctx.user_id,
            metric_code=payload.metric_code,
            amount=payload.amount,
            reason=payload.reason,
            expires_at=payload.expires_at,
        )
        _audit(conn, actor=ctx, action="admin.billing.credit.create", resource_type="billing_credit", resource_id=credit.get("id", ""), tenant_id=payload.tenant_id, details=credit)
    return {"ok": True, "credit": credit}


@router.post("/billing/lifecycle/sync")
def admin_sync_billing_lifecycle(
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "billing_admin")),
):
    with db_session() as conn:
        result = sync_billing_lifecycle(conn)
        _audit(conn, actor=ctx, action="admin.billing.lifecycle.sync", resource_type="billing", resource_id="lifecycle", details=result)
    return {"ok": True, "result": result}


@router.get("/audit")
def audit_events(
    tenant_id: str = Query("", max_length=80),
    limit: int = Query(100, ge=1, le=500),
    ctx: PlatformAuthContext = Depends(get_current_platform_admin),
):
    where = ["1=1"]
    params: dict[str, Any] = {"limit": limit}
    if tenant_id:
        params["tenant_id"] = tenant_id
        where.append("a.tenant_id = CAST(:tenant_id AS uuid)")
    with db_session() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT a.id, a.tenant_id::text, t.name AS tenant_name, a.actor_user_id::text, u.email AS actor_email,
                       a.action, a.resource_type, a.resource_id, a.details_json, a.created_at::text
                FROM saas_audit_events a
                LEFT JOIN saas_tenants t ON t.id = a.tenant_id
                LEFT JOIN saas_users u ON u.id = a.actor_user_id
                WHERE {" AND ".join(where)}
                ORDER BY a.created_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
    return {"audit": [dict(row) for row in rows]}


@router.get("/audit/export.csv")
def audit_events_export(
    tenant_id: str = Query("", max_length=80),
    limit: int = Query(1000, ge=1, le=5000),
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support")),
):
    data = audit_events(tenant_id=tenant_id, limit=limit, ctx=ctx).get("audit", [])
    headers = ["created_at", "action", "actor_email", "tenant_name", "resource_type", "resource_id"]
    lines = [",".join(headers)]
    for row in data:
        values = []
        for key in headers:
            value = str(row.get(key) or "").replace('"', '""')
            values.append(f'"{value}"')
        lines.append(",".join(values))
    return Response("\n".join(lines), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=scentra-audit.csv"})


@router.get("/security/compliance")
def admin_security_compliance(ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support"))):
    with db_session() as conn:
        users = conn.execute(
            text(
                """
                SELECT COUNT(*)::int AS total,
                       COUNT(*) FILTER (WHERE two_factor_enabled IS TRUE)::int AS two_factor_enabled,
                       COUNT(*) FILTER (WHERE locked_until > NOW())::int AS locked
                FROM saas_users
                """
            )
        ).mappings().first() or {}
        admins = conn.execute(
            text(
                """
                SELECT COUNT(*)::int AS total,
                       COUNT(*) FILTER (WHERE COALESCE(u.two_factor_enabled, FALSE) IS TRUE)::int AS two_factor_enabled,
                       COUNT(*) FILTER (WHERE COALESCE(u.two_factor_enabled, FALSE) IS FALSE)::int AS without_two_factor
                FROM saas_platform_admins pa
                JOIN saas_users u ON u.id = pa.user_id
                WHERE pa.status = 'active'
                """
            )
        ).mappings().first() or {}
        webhooks = conn.execute(
            text(
                """
                SELECT COUNT(*)::int AS total,
                       COUNT(*) FILTER (WHERE signature_required IS TRUE)::int AS signature_required,
                       COUNT(*) FILTER (WHERE is_active IS TRUE)::int AS active
                FROM saas_webhook_endpoints
                """
            )
        ).mappings().first() or {}
        security_24h = conn.execute(
            text(
                """
                SELECT status, COUNT(*)::int AS total
                FROM saas_security_events
                WHERE created_at >= NOW() - INTERVAL '24 hours'
                GROUP BY status
                """
            )
        ).mappings().all()
        privacy = conn.execute(
            text(
                """
                SELECT status, COUNT(*)::int AS total
                FROM saas_privacy_requests
                GROUP BY status
                """
            )
        ).mappings().all()
    return {
        "ok": True,
        "users": dict(users),
        "platform_admins": dict(admins),
        "webhooks": dict(webhooks),
        "security_events_24h": [dict(row) for row in security_24h],
        "privacy_requests": [dict(row) for row in privacy],
        "environment": {
            "captcha_enabled": settings.saas_captcha_enabled,
            "rate_limit_enabled": settings.saas_rate_limit_enabled,
            "smtp_configured": smtp_is_configured(),
            "jwt_secret_default": settings.saas_jwt_secret == "dev-only-change-me",
            "tenant_mfa_required_roles": settings.saas_mfa_required_roles,
            "admin_mfa_required_roles": settings.saas_admin_mfa_required_roles,
        },
    }


@router.get("/operations/queues")
def operation_queues(ctx: PlatformAuthContext = Depends(get_current_platform_admin)):
    with db_session() as conn:
        return {"queues": _queue_counts(conn)}


@router.get("/reliability/overview")
def admin_reliability_overview(
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support")),
):
    with db_session() as conn:
        return reliability_overview(conn)


@router.get("/reliability/index-audit")
def admin_reliability_index_audit(
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support")),
):
    with db_session() as conn:
        return {"index_audit": index_audit(conn)}


@router.get("/reliability/backpressure")
def admin_reliability_backpressure(
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support")),
):
    with db_session() as conn:
        return {"backpressure": backpressure_status(conn)}


@router.patch("/reliability/backpressure/{queue_key}")
def admin_reliability_update_backpressure(
    queue_key: str,
    payload: ReliabilityBackpressurePatchIn,
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin")),
):
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="empty_patch")
    if "critical_backlog" in data and "warn_backlog" in data and int(data["critical_backlog"]) < int(data["warn_backlog"]):
        raise HTTPException(status_code=400, detail="critical_backlog_must_be_gte_warn_backlog")
    assignments = ", ".join(f"{key} = :{key}" for key in data)
    with db_session() as conn:
        row = conn.execute(
            text(
                f"""
                UPDATE saas_reliability_backpressure_policies
                SET {assignments}, updated_at = NOW()
                WHERE queue_key = :queue_key
                RETURNING queue_key, warn_backlog, critical_backlog, max_batch_size, is_active, notes, updated_at::text
                """
            ),
            {"queue_key": queue_key, **data},
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="backpressure_policy_not_found")
        _audit(conn, actor=ctx, action="admin.reliability.backpressure.update", resource_type="reliability_backpressure", resource_id=queue_key, details=dict(row))
        return {"ok": True, "policy": dict(row)}


@router.post("/reliability/snapshot")
def admin_reliability_snapshot(
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support")),
):
    with db_session() as conn:
        result = record_reliability_snapshot(conn, snapshot_key="admin")
        _audit(conn, actor=ctx, action="admin.reliability.snapshot", resource_type="reliability", resource_id=result.get("id", ""), details=result)
        return {"ok": True, "snapshot": result}


@router.post("/reliability/drills/{drill_type}")
def admin_reliability_drill(
    drill_type: str,
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support")),
):
    with db_session() as conn:
        result = run_reliability_drill(conn, drill_type, initiated_by=ctx.email)
        _audit(conn, actor=ctx, action="admin.reliability.drill", resource_type="reliability_drill", resource_id=result.get("id", ""), details=result)
        return {"ok": True, "drill": result}


@router.patch("/reliability/retention/{policy_key}")
def admin_reliability_update_retention(
    policy_key: str,
    payload: ReliabilityRetentionPatchIn,
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin")),
):
    try:
        with db_session() as conn:
            result = update_retention_policy(conn, policy_key, payload.model_dump(exclude_unset=True))
            _audit(conn, actor=ctx, action="admin.reliability.retention.update", resource_type="reliability_retention", resource_id=policy_key, details=result)
            return {"ok": True, **result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/reliability/retention/run")
def admin_reliability_run_retention(
    dry_run: bool = Query(True),
    policy_key: str = Query("", max_length=120),
    include_disabled: bool = Query(True),
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support")),
):
    if not dry_run and ctx.platform_role not in {"superadmin", "platform_admin"}:
        raise HTTPException(status_code=403, detail="destructive_retention_requires_platform_admin")
    with db_session() as conn:
        result = run_retention(conn, dry_run=dry_run, policy_key=policy_key, include_disabled=include_disabled)
        _audit(conn, actor=ctx, action="admin.reliability.retention.run", resource_type="reliability_retention", resource_id=policy_key or "all", details=result)
        return {"ok": True, "result": result}


@router.get("/observability/health")
def admin_observability_health(
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support")),
):
    with db_session() as conn:
        synced = sync_dead_letters(conn, limit=200)
        return {
            "health": global_health(conn),
            "channels": channel_diagnostics(conn),
            "dead_letters": dead_letter_events(conn, limit=25),
            "meta_error_history": meta_error_history(conn, limit=25),
            "dead_letter_sync": synced,
        }


@router.get("/observability/dead-letter")
def admin_dead_letter_events(
    status: str = Query("open", max_length=40),
    source_type: str = Query("all", max_length=80),
    limit: int = Query(100, ge=1, le=300),
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support")),
):
    with db_session() as conn:
        sync_dead_letters(conn, limit=limit)
        return {"dead_letters": dead_letter_events(conn, limit=limit, status=status, source_type=source_type)}


@router.post("/observability/dead-letter/sync")
def admin_sync_dead_letters(
    limit: int = Query(200, ge=1, le=500),
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support")),
):
    with db_session() as conn:
        result = sync_dead_letters(conn, limit=limit)
        _audit(conn, actor=ctx, action="admin.observability.dead_letter_sync", resource_type="dead_letter", details=result)
        return {"ok": True, "result": result}


@router.get("/observability/meta-errors")
def admin_meta_error_history(
    tenant_id: str = Query("", max_length=80),
    limit: int = Query(100, ge=1, le=200),
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support")),
):
    with db_session() as conn:
        return {"meta_errors": meta_error_history(conn, tenant_id=tenant_id, limit=limit)}


@router.post("/observability/dead-letter/{event_id}/resolve")
def admin_resolve_dead_letter(
    event_id: str,
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support")),
):
    with db_session() as conn:
        ok = resolve_dead_letter(conn, event_id)
        if not ok:
            raise HTTPException(status_code=404, detail="dead_letter_not_found")
        _audit(conn, actor=ctx, action="admin.observability.dead_letter_resolve", resource_type="dead_letter", resource_id=event_id)
        return {"ok": True}


def _process_retry_queue(queue_kind: str, tenant_id: str, limit: int = 10) -> dict[str, Any]:
    if queue_kind == "webhooks":
        return process_due_webhook_events(limit=limit, tenant_id=tenant_id or None)
    if queue_kind == "outbound":
        return process_due_outbound_messages(limit=limit, tenant_id=tenant_id or None)
    if queue_kind == "triggers":
        return process_due_scheduled_trigger_messages(limit=limit, tenant_id=tenant_id or None)
    if queue_kind == "ai":
        return process_due_ai_replies(limit=limit, tenant_id=tenant_id or None)
    if queue_kind == "remarketing":
        return process_due_remarketing_flows(limit=limit, tenant_id=tenant_id or None)
    if queue_kind == "agents":
        return process_due_agent_orchestration(limit=limit, tenant_id=tenant_id or None)
    if queue_kind == "intelligence":
        return process_due_intelligence(limit=limit, tenant_id=tenant_id or None, force=True)
    if queue_kind == "reliability":
        return process_due_reliability()
    return {}


@router.post("/observability/dead-letter/{event_id}/retry")
def admin_retry_dead_letter(
    event_id: str,
    process_now: bool = Query(True),
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support")),
):
    with db_session() as conn:
        result = retry_dead_letter(conn, event_id)
        if not result.get("ok"):
            status_code = 404 if result.get("error") == "dead_letter_not_found" else 400
            raise HTTPException(status_code=status_code, detail=result.get("error") or "dead_letter_retry_failed")
        _audit(conn, actor=ctx, action="admin.observability.dead_letter_retry", resource_type="dead_letter", resource_id=event_id, tenant_id=result.get("tenant_id") or None, details=result)
    process_result = _process_retry_queue(str(result.get("queue_kind") or ""), str(result.get("tenant_id") or ""), limit=10) if process_now else {}
    return {"ok": True, "result": result, "process_result": process_result}


@router.post("/operations/webhooks/process")
def admin_process_webhooks(
    tenant_id: str = Query("", max_length=80),
    limit: int = Query(50, ge=1, le=200),
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support")),
):
    result = process_due_webhook_events(limit=limit, tenant_id=tenant_id or None)
    with db_session() as conn:
        _audit(conn, actor=ctx, action="admin.operations.webhooks_process", resource_type="queue", details={"tenant_id": tenant_id, "limit": limit, "result": result})
    return {"ok": True, "result": result}


@router.post("/operations/outbound/process")
def admin_process_outbound(
    tenant_id: str = Query("", max_length=80),
    limit: int = Query(50, ge=1, le=200),
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support")),
):
    result = process_due_outbound_messages(limit=limit, tenant_id=tenant_id or None)
    with db_session() as conn:
        _audit(conn, actor=ctx, action="admin.operations.outbound_process", resource_type="queue", details={"tenant_id": tenant_id, "limit": limit, "result": result})
    return {"ok": True, "result": result}


@router.post("/operations/triggers/process")
def admin_process_triggers(
    tenant_id: str = Query("", max_length=80),
    limit: int = Query(50, ge=1, le=200),
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support")),
):
    result = process_due_scheduled_trigger_messages(limit=limit, tenant_id=tenant_id or None)
    with db_session() as conn:
        _audit(conn, actor=ctx, action="admin.operations.triggers_process", resource_type="queue", details={"tenant_id": tenant_id, "limit": limit, "result": result})
    return {"ok": True, "result": result}


@router.post("/operations/ai/process")
def admin_process_ai(
    tenant_id: str = Query("", max_length=80),
    limit: int = Query(50, ge=1, le=200),
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support")),
):
    result = process_due_ai_replies(limit=limit, tenant_id=tenant_id or None)
    with db_session() as conn:
        _audit(conn, actor=ctx, action="admin.operations.ai_process", resource_type="queue", details={"tenant_id": tenant_id, "limit": limit, "result": result})
    return {"ok": True, "result": result}


@router.post("/operations/remarketing/process")
def admin_process_remarketing(
    tenant_id: str = Query("", max_length=80),
    limit: int = Query(50, ge=1, le=200),
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support")),
):
    result = process_due_remarketing_flows(limit=limit, tenant_id=tenant_id or None)
    with db_session() as conn:
        _audit(conn, actor=ctx, action="admin.operations.remarketing_process", resource_type="queue", details={"tenant_id": tenant_id, "limit": limit, "result": result})
    return {"ok": True, "result": result}


@router.post("/operations/agents/process")
def admin_process_agent_orchestration(
    tenant_id: str = Query("", max_length=80),
    limit: int = Query(50, ge=1, le=200),
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support")),
):
    result = process_due_agent_orchestration(limit=limit, tenant_id=tenant_id or None)
    with db_session() as conn:
        _audit(conn, actor=ctx, action="admin.operations.agent_orchestrator_process", resource_type="queue", details={"tenant_id": tenant_id, "limit": limit, "result": result})
    return {"ok": True, "result": result}


@router.post("/operations/intelligence/process")
def admin_process_intelligence(
    tenant_id: str = Query("", max_length=80),
    limit: int = Query(25, ge=1, le=200),
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support")),
):
    result = process_due_intelligence(limit=limit, tenant_id=tenant_id or None, force=True)
    with db_session() as conn:
        _audit(conn, actor=ctx, action="admin.operations.intelligence_process", resource_type="queue", details={"tenant_id": tenant_id, "limit": limit, "result": result})
    return {"ok": True, "result": result}


@router.post("/operations/reliability/process")
def admin_process_reliability(
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support")),
):
    result = process_due_reliability()
    with db_session() as conn:
        _audit(conn, actor=ctx, action="admin.operations.reliability_process", resource_type="queue", details={"result": result})
    return {"ok": True, "result": result}


@router.post("/operations/meta-tokens/process")
def admin_process_meta_tokens(
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support")),
):
    result = process_due_meta_token_refreshes()
    with db_session() as conn:
        _audit(conn, actor=ctx, action="admin.operations.meta_tokens_process", resource_type="queue", details={"result": result})
    return {"ok": True, "result": result}
