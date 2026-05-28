from typing import Optional

from pydantic import BaseModel, Field


class TenantCreateIn(BaseModel):
    name: str = Field(min_length=2)
    slug: Optional[str] = None
    timezone: str = "America/Bogota"
    locale: str = "es-CO"
    industry_code: str = Field(default="general", max_length=80)


class TenantOut(BaseModel):
    tenant_id: str
    slug: str
    name: str
    plan_code: str
    status: str
    role: str
    industry_code: str = "general"
    vertical_pack_applied_at: Optional[str] = None


class TenantPatchIn(BaseModel):
    name: Optional[str] = None
    timezone: Optional[str] = None
    locale: Optional[str] = None
