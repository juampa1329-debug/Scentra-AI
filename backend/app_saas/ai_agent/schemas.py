from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AiSettingsIn(BaseModel):
    enabled: bool = True
    provider_code: str = Field(default="google", max_length=80)
    fallback_provider_code: str = Field(default="", max_length=80)
    system_prompt: str = Field(default="", max_length=20000)
    max_tokens: int = Field(default=700, ge=200, le=8000)
    temperature: float = Field(default=0.5, ge=0, le=2)
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class AiSettingsOut(AiSettingsIn):
    tenant_id: str
    active_model: str = ""
    fallback_model: str = ""
    updated_at: str = ""


class AiTestIn(BaseModel):
    phone: str = Field(default="", max_length=120)
    message: str = Field(min_length=1, max_length=4000)


class AiMemoryOut(BaseModel):
    tenant_id: str
    conversation_id: str
    summary: str = ""
    facts_json: dict[str, Any] = Field(default_factory=dict)
    last_message_id: str = ""
    updated_at: str = ""
