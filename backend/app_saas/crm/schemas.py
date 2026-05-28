from typing import Any

from pydantic import BaseModel, Field


class SendMessageIn(BaseModel):
    text: str = Field(default="", max_length=4096)
    channel: str = ""
    msg_type: str = Field(default="text", max_length=40)
    media_id: str = Field(default="", max_length=240)
    mime_type: str = Field(default="", max_length=160)
    filename: str = Field(default="", max_length=240)
    payload_json: dict[str, Any] | None = None


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
    assigned_user_id: str | None = Field(default=None, max_length=80)
    assigned_ai_agent_id: str | None = Field(default=None, max_length=80)
    ai_owner_mode: str | None = Field(default=None, max_length=40)
    priority: str | None = Field(default=None, max_length=40)
    sla_due_at: str | None = Field(default=None, max_length=80)
    first_response_due_at: str | None = Field(default=None, max_length=80)
    lead_score: int | None = Field(default=None, ge=0, le=100)
    lead_temperature: str | None = Field(default=None, max_length=40)
    profile_json: dict[str, Any] | None = None
    custom_fields: dict[str, Any] | None = None


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


class CrmTaskCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    description: str = Field(default="", max_length=1200)
    assigned_user_id: str | None = Field(default=None, max_length=80)
    priority: str = Field(default="normal", max_length=40)
    due_at: str | None = Field(default=None, max_length=80)


class CrmTaskPatchIn(BaseModel):
    title: str | None = Field(default=None, max_length=180)
    description: str | None = Field(default=None, max_length=1200)
    assigned_user_id: str | None = Field(default=None, max_length=80)
    priority: str | None = Field(default=None, max_length=40)
    due_at: str | None = Field(default=None, max_length=80)
    status: str | None = Field(default=None, max_length=40)


class CrmCustomFieldCreateIn(BaseModel):
    field_key: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=120)
    field_type: str = Field(default="text", max_length=40)
    options_json: Any | None = None
    is_required: bool = False
    display_order: int = Field(default=100, ge=0, le=10000)


class CrmCustomFieldPatchIn(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=120)
    field_type: str | None = Field(default=None, max_length=40)
    options_json: Any | None = None
    is_required: bool | None = None
    is_active: bool | None = None
    display_order: int | None = Field(default=None, ge=0, le=10000)


class CrmPipelineStageCreateIn(BaseModel):
    stage_key: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=120)
    probability: int = Field(default=0, ge=0, le=100)
    display_order: int = Field(default=100, ge=0, le=10000)
    is_won: bool = False
    is_lost: bool = False


class CrmPipelineStagePatchIn(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=120)
    probability: int | None = Field(default=None, ge=0, le=100)
    display_order: int | None = Field(default=None, ge=0, le=10000)
    is_won: bool | None = None
    is_lost: bool | None = None
    is_active: bool | None = None


class CustomerMergeIn(BaseModel):
    source_conversation_id: str = Field(min_length=1, max_length=80)
    reason: str = Field(default="", max_length=500)
