from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AdAccountIn(BaseModel):
    provider: str = Field(default="meta", max_length=40)
    external_account_id: str = Field(min_length=1, max_length=160)
    name: str = Field(default="", max_length=180)
    status: str = Field(default="connected", max_length=40)
    currency: str = Field(default="", max_length=20)
    timezone: str = Field(default="", max_length=80)
    config_json: dict[str, Any] | None = None


class AdAccountPatchIn(BaseModel):
    name: str | None = Field(default=None, max_length=180)
    status: str | None = Field(default=None, max_length=40)
    currency: str | None = Field(default=None, max_length=20)
    timezone: str | None = Field(default=None, max_length=80)
    config_json: dict[str, Any] | None = None


class AdCampaignIn(BaseModel):
    account_id: str | None = None
    provider: str = Field(default="meta", max_length=40)
    channel: str = Field(default="facebook", max_length=40)
    external_campaign_id: str = Field(min_length=1, max_length=160)
    name: str = Field(default="", max_length=180)
    objective: str = Field(default="", max_length=120)
    status: str = Field(default="unknown", max_length=40)
    daily_budget_cents: int = Field(default=0, ge=0)
    lifetime_budget_cents: int = Field(default=0, ge=0)
    currency: str = Field(default="", max_length=20)
    metrics_json: dict[str, Any] | None = None


class AdCampaignPatchIn(BaseModel):
    account_id: str | None = None
    channel: str | None = Field(default=None, max_length=40)
    name: str | None = Field(default=None, max_length=180)
    objective: str | None = Field(default=None, max_length=120)
    status: str | None = Field(default=None, max_length=40)
    daily_budget_cents: int | None = Field(default=None, ge=0)
    lifetime_budget_cents: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=20)
    metrics_json: dict[str, Any] | None = None


class LeadImportIn(BaseModel):
    provider: str = Field(default="meta", max_length=40)
    channel: str = Field(default="facebook", max_length=40)
    external_lead_id: str = Field(min_length=1, max_length=180)
    external_form_id: str = Field(default="", max_length=180)
    external_ad_id: str = Field(default="", max_length=180)
    external_campaign_id: str = Field(default="", max_length=180)
    contact_name: str = Field(default="", max_length=180)
    email: str = Field(default="", max_length=180)
    phone: str = Field(default="", max_length=80)
    status: str = Field(default="new", max_length=40)
    payload_json: dict[str, Any] | None = None
    create_conversation: bool = False


class LeadPatchIn(BaseModel):
    contact_name: str | None = Field(default=None, max_length=180)
    email: str | None = Field(default=None, max_length=180)
    phone: str | None = Field(default=None, max_length=80)
    status: str | None = Field(default=None, max_length=40)


class CommentImportIn(BaseModel):
    provider: str = Field(default="meta", max_length=40)
    channel: str = Field(default="facebook", max_length=40)
    external_comment_id: str = Field(min_length=1, max_length=180)
    external_parent_id: str = Field(default="", max_length=180)
    external_post_id: str = Field(default="", max_length=180)
    external_ad_id: str = Field(default="", max_length=180)
    external_campaign_id: str = Field(default="", max_length=180)
    author_id: str = Field(default="", max_length=180)
    author_name: str = Field(default="", max_length=180)
    message: str = Field(default="", max_length=4000)
    permalink_url: str = Field(default="", max_length=1000)
    status: str = Field(default="new", max_length=40)
    payload_json: dict[str, Any] | None = None
    create_conversation: bool = False


class CommentPatchIn(BaseModel):
    status: str | None = Field(default=None, max_length=40)
    author_name: str | None = Field(default=None, max_length=180)
    message: str | None = Field(default=None, max_length=4000)
    permalink_url: str | None = Field(default=None, max_length=1000)
