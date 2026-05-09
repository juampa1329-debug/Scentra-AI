from typing import Optional

from pydantic import BaseModel, Field


class TenantCreateIn(BaseModel):
    name: str = Field(min_length=2)
    slug: Optional[str] = None
    timezone: str = "America/Bogota"
    locale: str = "es-CO"


class TenantOut(BaseModel):
    tenant_id: str
    slug: str
    name: str
    plan_code: str
    status: str
    role: str


class TenantPatchIn(BaseModel):
    name: Optional[str] = None
    timezone: Optional[str] = None
    locale: Optional[str] = None
