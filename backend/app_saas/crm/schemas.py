from typing import Any

from pydantic import BaseModel, Field


class SendMessageIn(BaseModel):
    text: str = Field(default="", max_length=4096)
    channel: str = ""
    msg_type: str = Field(default="text", max_length=40)
    media_id: str = Field(default="", max_length=240)
    mime_type: str = Field(default="", max_length=160)
    filename: str = Field(default="", max_length=240)


class CustomerUpdateIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=160)
    phone: str | None = Field(default=None, max_length=80)
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=120)
    customer_type: str | None = Field(default=None, max_length=80)
    interests: str | None = Field(default=None, max_length=800)
    tags: str | list[str] | None = None
    notes: str | None = Field(default=None, max_length=4000)
    payment_status: str | None = Field(default=None, max_length=80)
    payment_reference: str | None = Field(default=None, max_length=160)
    crm_stage: str | None = Field(default=None, max_length=80)
    intent: str | None = Field(default=None, max_length=120)
    takeover: bool | None = None
    profile_json: dict[str, Any] | None = None


class CustomerCreateIn(CustomerUpdateIn):
    channel: str = Field(default="whatsapp", max_length=40)
    external_contact_id: str | None = Field(default=None, max_length=180)


class LabelCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    color: str = Field(default="#5eead4", max_length=32)
    description: str = Field(default="", max_length=500)
    category: str = Field(default="general", max_length=80)


class LabelPatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    color: str | None = Field(default=None, max_length=32)
    description: str | None = Field(default=None, max_length=500)
    category: str | None = Field(default=None, max_length=80)
    is_active: bool | None = None
