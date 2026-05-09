from typing import Any, Optional

from pydantic import BaseModel, Field


class IntegrationUpsertIn(BaseModel):
    provider: str = Field(min_length=2)
    channel: str = Field(min_length=2)
    status: str = "connected"
    secret_ref: Optional[str] = None
    config_json: dict[str, Any] = Field(default_factory=dict)


class IntegrationOut(BaseModel):
    id: str
    provider: str
    channel: str
    status: str
    secret_ref: str
    config_json: dict[str, Any]
    last_sync_at: Optional[str] = None
