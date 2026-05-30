from __future__ import annotations

from pydantic import BaseModel, Field


class AdminNotificationDraftIn(BaseModel):
    topic: str = Field(default="", max_length=240)
    audience: str = Field(default="", max_length=240)
    tone: str = Field(default="claro", max_length=80)
    urgency: str = Field(default="normal", max_length=80)
    body_hint: str = Field(default="", max_length=1200)


class AdminNotificationCreateIn(BaseModel):
    title: str = Field(min_length=2, max_length=180)
    body: str = Field(min_length=2, max_length=4000)
    severity: str = Field(default="info", max_length=40)
    category: str = Field(default="system", max_length=80)
    audience_type: str = Field(default="selected", max_length=40)
    tenant_ids: list[str] = Field(default_factory=list)
    user_ids: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    email_copy: bool = False
    ai_assisted: bool = False


class NotificationReadOut(BaseModel):
    ok: bool = True
    unread_count: int = 0
