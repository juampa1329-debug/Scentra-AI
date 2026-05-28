from typing import Optional

from pydantic import BaseModel, Field


class RegisterIn(BaseModel):
    email: str
    password: str = Field(min_length=8)
    full_name: str = ""
    tenant_name: str = Field(min_length=2)
    tenant_slug: Optional[str] = None
    industry_code: str = Field(default="general", max_length=80)
    captcha_token: str = ""
    captcha_provider: str = "turnstile"


class LoginIn(BaseModel):
    email: str
    password: str
    tenant_id: Optional[str] = None
    captcha_token: str = ""
    captcha_provider: str = "turnstile"


class MfaVerifyIn(BaseModel):
    challenge_token: str = Field(min_length=20, max_length=500)
    code: str = Field(min_length=4, max_length=20)


class MfaChallengeOut(BaseModel):
    ok: bool = False
    mfa_required: bool = True
    challenge_token: str
    method: str = "email_otp"
    email_hint: str = ""
    expires_at: Optional[str] = None
    email_sent: bool = False
    dev_otp: Optional[str] = None


class PasswordForgotIn(BaseModel):
    email: str = Field(min_length=3, max_length=240)
    captcha_token: str = Field(default="", max_length=5000)
    captcha_provider: str = Field(default="turnstile", max_length=40)


class PasswordForgotOut(BaseModel):
    ok: bool = True
    message: str = "password_reset_if_account_exists"
    email_sent: bool = False
    dev_reset_token: Optional[str] = None
    dev_reset_url: Optional[str] = None


class PasswordResetIn(BaseModel):
    token: str = Field(min_length=20, max_length=500)
    new_password: str = Field(min_length=8, max_length=200)
    captcha_token: str = Field(default="", max_length=5000)
    captcha_provider: str = Field(default="turnstile", max_length=40)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


class TwoFactorPatchIn(BaseModel):
    enabled: bool = False
    method: str = Field(default="email_otp", max_length=40)


class SecurityStatusOut(BaseModel):
    two_factor_enabled: bool = False
    two_factor_method: str = "none"
    locked_until: Optional[str] = None
    password_changed_at: Optional[str] = None


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
    industry_code: str = "general"
    vertical_pack_applied_at: Optional[str] = None
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
    full_name: str = ""
    tenant_id: str
    role: str
    tenants: list[TenantMembershipOut] = []
