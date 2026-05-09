from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AdminLoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=240)
    password: str = Field(min_length=8, max_length=200)


class AdminBootstrapIn(AdminLoginIn):
    full_name: str = Field(default="Scentra Admin", max_length=180)
    platform_role: str = Field(default="superadmin", max_length=40)


class PlatformTokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    email: str
    platform_role: str


class TenantPatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    status: str | None = Field(default=None, max_length=40)
    plan_code: str | None = Field(default=None, max_length=40)
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


class TenantImpersonateIn(BaseModel):
    role: str = Field(default="admin", max_length=40)
    reason: str = Field(default="support", max_length=500)
