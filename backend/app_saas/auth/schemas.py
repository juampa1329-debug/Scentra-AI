from typing import Optional

from pydantic import BaseModel, Field


class RegisterIn(BaseModel):
    email: str
    password: str = Field(min_length=8)
    full_name: str = ""
    tenant_name: str = Field(min_length=2)
    tenant_slug: Optional[str] = None


class LoginIn(BaseModel):
    email: str
    password: str
    tenant_id: Optional[str] = None


class RefreshIn(BaseModel):
    refresh_token: str
    tenant_id: Optional[str] = None


class SwitchTenantIn(BaseModel):
    tenant_id: str


class TenantMembershipOut(BaseModel):
    tenant_id: str
    tenant_slug: str
    tenant_name: str
    role: str
    tenant_status: str = "active"
    plan_code: str = "starter"
    subscription_status: str = "none"
    trial_ends_at: Optional[str] = None


class TokenOut(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    tenant_id: str
    role: str
    tenants: list[TenantMembershipOut] = []


class MeOut(BaseModel):
    user_id: str
    email: str
    tenant_id: str
    role: str
    tenants: list[TenantMembershipOut] = []
