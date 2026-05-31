from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AiAgentPlanLimitsIn(BaseModel):
    max_ai_agents: int = Field(default=1, ge=0, le=1000000)
    max_active_ai_agents: int = Field(default=1, ge=0, le=1000000)
    max_memory_archives: int = Field(default=1, ge=0, le=1000000)
    allowed_agent_types_json: list[str] = Field(default_factory=list)
    builder_enabled: bool = True
    notes: str = Field(default="", max_length=1000)


class AdminLoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=240)
    password: str = Field(min_length=8, max_length=200)
    captcha_token: str = Field(default="", max_length=5000)
    captcha_provider: str = Field(default="turnstile", max_length=40)


class AdminBootstrapIn(AdminLoginIn):
    full_name: str = Field(default="Scentra Admin", max_length=180)
    platform_role: str = Field(default="superadmin", max_length=40)


class PlatformTokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    email: str
    platform_role: str


class AdminMfaVerifyIn(BaseModel):
    challenge_token: str = Field(min_length=20, max_length=500)
    code: str = Field(min_length=4, max_length=20)


class AdminMfaChallengeOut(BaseModel):
    ok: bool = False
    mfa_required: bool = True
    challenge_token: str
    method: str = "email_otp"
    email_hint: str = ""
    expires_at: str | None = None
    email_sent: bool = False
    dev_otp: str | None = None


class AdminTwoFactorPatchIn(BaseModel):
    enabled: bool = False
    method: str = Field(default="email_otp", max_length=40)


class AdminProfilePatchIn(BaseModel):
    full_name: str | None = Field(default=None, max_length=180)
    email: str | None = Field(default=None, max_length=240)
    current_password: str = Field(default="", max_length=200)
    phone: str | None = Field(default=None, max_length=60)
    role_label: str | None = Field(default=None, max_length=120)
    avatar_url: str | None = Field(default=None, max_length=1000)
    timezone: str | None = Field(default=None, max_length=80)


class AdminPasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


class PlatformAdminCreateIn(BaseModel):
    email: str = Field(min_length=3, max_length=240)
    full_name: str = Field(default="", max_length=180)
    password: str = Field(min_length=8, max_length=200)
    platform_role: str = Field(default="support", max_length=40)
    status: str = Field(default="active", max_length=40)
    notes: str = Field(default="", max_length=1000)
    send_email: bool = True


class PlatformAdminPatchIn(BaseModel):
    platform_role: str | None = Field(default=None, max_length=40)
    status: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=1000)


class AdminTenantUserCreateIn(BaseModel):
    tenant_id: str = Field(min_length=20, max_length=80)
    email: str = Field(min_length=3, max_length=240)
    full_name: str = Field(default="", max_length=180)
    password: str = Field(default="", max_length=200)
    role: str = Field(default="agent", max_length=40)
    send_email: bool = True


class AdminTenantMembershipPatchIn(BaseModel):
    role: str | None = Field(default=None, max_length=40)
    is_active: bool | None = None


class TenantPatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    status: str | None = Field(default=None, max_length=40)
    plan_code: str | None = Field(default=None, max_length=40)
    industry_code: str | None = Field(default=None, max_length=80)
    subscription_status: str | None = Field(default=None, max_length=40)
    timezone: str | None = Field(default=None, max_length=80)
    locale: str | None = Field(default=None, max_length=20)


class PlanUpsertIn(BaseModel):
    plan_code: str = Field(min_length=2, max_length=40)
    display_name: str = Field(default="", max_length=120)
    max_agents: int = Field(default=3, ge=0, le=1000000)
    max_monthly_messages: int = Field(default=5000, ge=0, le=1000000000)
    max_integrations: int = Field(default=3, ge=0, le=100000)
    max_storage_gb: int = Field(default=5, ge=0, le=1000000)
    max_campaigns: int = Field(default=10, ge=0, le=1000000)
    max_broadcasts: int = Field(default=10, ge=0, le=1000000)
    max_ai_tokens: int = Field(default=1000000, ge=0, le=1000000000000)
    price_monthly_cents: int = Field(default=0, ge=0, le=100000000)
    currency: str = Field(default="USD", max_length=12)
    is_public: bool = True
    is_active: bool = True
    sort_order: int = Field(default=100, ge=0, le=1000000)
    feature_flags_json: dict[str, Any] = Field(default_factory=dict)
    ai_agent_limits: AiAgentPlanLimitsIn | None = None


class PlanPatchIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    max_agents: int | None = Field(default=None, ge=0, le=1000000)
    max_monthly_messages: int | None = Field(default=None, ge=0, le=1000000000)
    max_integrations: int | None = Field(default=None, ge=0, le=100000)
    max_storage_gb: int | None = Field(default=None, ge=0, le=1000000)
    max_campaigns: int | None = Field(default=None, ge=0, le=1000000)
    max_broadcasts: int | None = Field(default=None, ge=0, le=1000000)
    max_ai_tokens: int | None = Field(default=None, ge=0, le=1000000000000)
    price_monthly_cents: int | None = Field(default=None, ge=0, le=100000000)
    currency: str | None = Field(default=None, max_length=12)
    is_public: bool | None = None
    is_active: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=1000000)
    feature_flags_json: dict[str, Any] | None = None
    ai_agent_limits: AiAgentPlanLimitsIn | None = None


class FeatureFlagPatchIn(BaseModel):
    feature_key: str = Field(min_length=2, max_length=80)
    is_enabled: bool = True
    source: str = Field(default="admin", max_length=40)
    notes: str = Field(default="", max_length=500)


class SubscriptionPatchIn(BaseModel):
    status: str = Field(default="active", max_length=40)
    plan_code: str | None = Field(default=None, max_length=40)
    current_period_end: str | None = Field(default=None, max_length=80)
    cancel_at_period_end: bool = False


class BillingCreditCreateIn(BaseModel):
    tenant_id: str = Field(min_length=20, max_length=80)
    metric_code: str = Field(default="monthly_messages", max_length=80)
    amount: int = Field(default=0, ge=1, le=1000000000)
    reason: str = Field(default="", max_length=700)
    expires_at: str = Field(default="", max_length=80)


class BillingInvoiceCreateIn(BaseModel):
    tenant_id: str = Field(min_length=20, max_length=80)
    plan_code: str = Field(min_length=2, max_length=40)
    status: str = Field(default="open", max_length=40)
    total_cents: int | None = Field(default=None, ge=0, le=1000000000)
    due_at: str = Field(default="", max_length=80)


class BillingProviderSettingsPatchIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    title: str | None = Field(default=None, max_length=140)
    is_enabled: bool | None = None
    is_default: bool | None = None
    test_mode: bool | None = None
    debug_logging: bool | None = None
    test_public_key: str | None = Field(default=None, max_length=1000)
    test_private_key: str | None = Field(default=None, max_length=5000)
    test_event_key: str | None = Field(default=None, max_length=5000)
    test_integrity_key: str | None = Field(default=None, max_length=5000)
    live_public_key: str | None = Field(default=None, max_length=1000)
    live_private_key: str | None = Field(default=None, max_length=5000)
    live_event_key: str | None = Field(default=None, max_length=5000)
    live_integrity_key: str | None = Field(default=None, max_length=5000)
    test_access_token: str | None = Field(default=None, max_length=5000)
    test_webhook_secret: str | None = Field(default=None, max_length=5000)
    live_access_token: str | None = Field(default=None, max_length=5000)
    live_webhook_secret: str | None = Field(default=None, max_length=5000)


class TenantImpersonateIn(BaseModel):
    role: str = Field(default="admin", max_length=40)
    reason: str = Field(default="support", max_length=500)


class ReliabilityRetentionPatchIn(BaseModel):
    retention_days: int | None = Field(default=None, ge=1, le=3650)
    batch_limit: int | None = Field(default=None, ge=1, le=10000)
    enabled: bool | None = None
    dry_run_default: bool | None = None
    notes: str | None = Field(default=None, max_length=1000)


class ReliabilityBackpressurePatchIn(BaseModel):
    warn_backlog: int | None = Field(default=None, ge=0, le=10000000)
    critical_backlog: int | None = Field(default=None, ge=1, le=10000000)
    max_batch_size: int | None = Field(default=None, ge=1, le=10000)
    is_active: bool | None = None
    notes: str | None = Field(default=None, max_length=1000)
