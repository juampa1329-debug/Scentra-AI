from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=140)
    channel: str = Field(default="whatsapp", max_length=40)
    category: str = Field(default="general", max_length=80)
    status: str = Field(default="draft", max_length=40)
    body: str = Field(default="", max_length=8000)
    variables_json: list[str] | None = None
    blocks_json: list[dict[str, Any]] | None = None
    params_json: dict[str, Any] | None = None
    render_mode: str = Field(default="chat", max_length=40)
    template_scope: str = Field(default="crm", max_length=40)


class TemplatePatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=140)
    channel: str | None = Field(default=None, max_length=40)
    category: str | None = Field(default=None, max_length=80)
    status: str | None = Field(default=None, max_length=40)
    body: str | None = Field(default=None, max_length=8000)
    variables_json: list[str] | None = None
    blocks_json: list[dict[str, Any]] | None = None
    params_json: dict[str, Any] | None = None
    render_mode: str | None = Field(default=None, max_length=40)
    template_scope: str | None = Field(default=None, max_length=40)


class SegmentIn(BaseModel):
    name: str = Field(min_length=1, max_length=140)
    description: str = Field(default="", max_length=800)
    filters_json: dict[str, Any] = Field(default_factory=dict)


class SegmentPatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=140)
    description: str | None = Field(default=None, max_length=800)
    filters_json: dict[str, Any] | None = None


class SegmentPreviewIn(BaseModel):
    filters_json: dict[str, Any] = Field(default_factory=dict)


class CampaignIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    channel: str = Field(default="whatsapp", max_length=40)
    objective: str = Field(default="", max_length=1000)
    template_id: str | None = None
    segment_id: str | None = None
    status: str = Field(default="draft", max_length=40)
    scheduled_at: str | None = None


class CampaignPatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    channel: str | None = Field(default=None, max_length=40)
    objective: str | None = Field(default=None, max_length=1000)
    template_id: str | None = None
    segment_id: str | None = None
    status: str | None = Field(default=None, max_length=40)
    scheduled_at: str | None = None


class TriggerIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    channel: str = Field(default="whatsapp", max_length=40)
    event_type: str = Field(default="message_in", max_length=80)
    trigger_type: str = Field(default="message_flow", max_length=80)
    flow_event: str = Field(default="received", max_length=40)
    conditions_json: dict[str, Any] = Field(default_factory=lambda: {"conditions": []})
    actions_json: dict[str, Any] = Field(default_factory=lambda: {"actions": []})
    priority: int = Field(default=100, ge=1, le=10000)
    cooldown_minutes: int = Field(default=60, ge=0, le=60 * 24 * 30)
    is_active: bool = True
    assistant_enabled: bool = False
    assistant_message_type: str = Field(default="auto", max_length=40)
    block_ai: bool = True
    stop_on_match: bool = True
    only_when_no_takeover: bool = True


class TriggerPatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    channel: str | None = Field(default=None, max_length=40)
    event_type: str | None = Field(default=None, max_length=80)
    trigger_type: str | None = Field(default=None, max_length=80)
    flow_event: str | None = Field(default=None, max_length=40)
    conditions_json: dict[str, Any] | None = None
    actions_json: dict[str, Any] | None = None
    priority: int | None = Field(default=None, ge=1, le=10000)
    cooldown_minutes: int | None = Field(default=None, ge=0, le=60 * 24 * 30)
    is_active: bool | None = None
    assistant_enabled: bool | None = None
    assistant_message_type: str | None = Field(default=None, max_length=40)
    block_ai: bool | None = None
    stop_on_match: bool | None = None
    only_when_no_takeover: bool | None = None


class TriggerCopyIn(BaseModel):
    channel: str = Field(default="whatsapp", max_length=40)
    name: str | None = Field(default=None, max_length=160)


class FlowIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=1000)
    channel: str = Field(default="whatsapp", max_length=40)
    status: str = Field(default="draft", max_length=40)
    entry_rules_json: dict[str, Any] = Field(default_factory=dict)
    exit_rules_json: dict[str, Any] = Field(default_factory=dict)
    steps_json: list[dict[str, Any]] = Field(default_factory=list)


class FlowPatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=1000)
    channel: str | None = Field(default=None, max_length=40)
    status: str | None = Field(default=None, max_length=40)
    entry_rules_json: dict[str, Any] | None = None
    exit_rules_json: dict[str, Any] | None = None
    steps_json: list[dict[str, Any]] | None = None
