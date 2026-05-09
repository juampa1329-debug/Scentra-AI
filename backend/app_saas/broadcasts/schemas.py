from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MetaTemplateButtonIn(BaseModel):
    type: str = Field(default="QUICK_REPLY", max_length=40)
    text: str = Field(default="", max_length=25)
    url: str = Field(default="", max_length=2000)
    phone_number: str = Field(default="", max_length=80)


class MetaTemplateCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    language: str = Field(default="es", max_length=20)
    category: str = Field(default="MARKETING", max_length=40)
    body_text: str = Field(default="", min_length=1, max_length=1024)
    header_type: str = Field(default="", max_length=40)
    header_text: str = Field(default="", max_length=60)
    header_media_handle: str = Field(default="", max_length=500)
    footer_text: str = Field(default="", max_length=60)
    buttons: list[MetaTemplateButtonIn] = Field(default_factory=list)
    allow_category_change: bool = True


class MetaTemplatePatchIn(BaseModel):
    status: str | None = Field(default=None, max_length=40)
    quality_score: str | None = Field(default=None, max_length=80)
    rejection_reason: str | None = Field(default=None, max_length=1000)


class BroadcastPreviewIn(BaseModel):
    channel: str = Field(default="whatsapp", max_length=40)
    template_id: str | None = None
    meta_template_id: str | None = None
    segment_id: str | None = None
    filters_json: dict[str, Any] | None = None
    body: str = Field(default="", max_length=8000)
    limit: int = Field(default=500, ge=1, le=5000)


class BroadcastCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    channel: str = Field(default="whatsapp", max_length=40)
    template_id: str | None = None
    meta_template_id: str | None = None
    meta_template_name: str = Field(default="", max_length=200)
    meta_template_language: str = Field(default="", max_length=20)
    meta_template_category: str = Field(default="", max_length=40)
    meta_template_body: str = Field(default="", max_length=1024)
    segment_id: str | None = None
    body: str = Field(default="", max_length=8000)
    status: str = Field(default="draft", max_length=40)
    scheduled_at: str | None = None


class BroadcastPatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    channel: str | None = Field(default=None, max_length=40)
    template_id: str | None = None
    meta_template_id: str | None = None
    meta_template_name: str | None = Field(default=None, max_length=200)
    meta_template_language: str | None = Field(default=None, max_length=20)
    meta_template_category: str | None = Field(default=None, max_length=40)
    meta_template_body: str | None = Field(default=None, max_length=1024)
    segment_id: str | None = None
    body: str | None = Field(default=None, max_length=8000)
    status: str | None = Field(default=None, max_length=40)
    scheduled_at: str | None = None


class BroadcastEnqueueIn(BaseModel):
    limit: int = Field(default=500, ge=1, le=5000)
    process_now: bool = False
