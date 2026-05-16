from typing import Any, Optional

from pydantic import BaseModel, Field


class IntegrationUpsertIn(BaseModel):
    provider: str = Field(min_length=2)
    channel: str = Field(min_length=2)
    status: str = "connected"
    secret_ref: Optional[str] = None
    config_json: dict[str, Any] = Field(default_factory=dict)
    current_password: Optional[str] = None


class IntegrationOut(BaseModel):
    id: str
    provider: str
    channel: str
    status: str
    secret_ref: str
    config_json: dict[str, Any]
    last_sync_at: Optional[str] = None


class WhatsappPhoneRegisterIn(BaseModel):
    phone_number_id: str = Field(min_length=4, max_length=80)
    pin: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
