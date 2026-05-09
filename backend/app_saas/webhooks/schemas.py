from typing import Optional

from pydantic import BaseModel, Field


class WebhookEndpointCreateIn(BaseModel):
    provider: str = Field(min_length=2)
    endpoint_key: Optional[str] = None
    is_active: bool = True
    signature_required: bool = False


class WebhookEndpointPatchIn(BaseModel):
    is_active: Optional[bool] = None
    signature_required: Optional[bool] = None


class WebhookEndpointOut(BaseModel):
    id: str
    tenant_id: str
    provider: str
    endpoint_key: str
    url_path: str
    is_active: bool
    signature_required: bool = False
    last_seen_at: Optional[str] = None
    verify_token_once: Optional[str] = None
    signature_secret_once: Optional[str] = None


class WebhookEventOut(BaseModel):
    id: str
    provider: str
    event_id: str
    status: str
    received_at: str
    error: str = ""
