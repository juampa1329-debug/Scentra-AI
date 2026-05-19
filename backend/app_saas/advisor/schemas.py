from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AdvisorChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=6000)
    thread_id: str = Field(default="", max_length=80)
    context_type: str = Field(default="global", max_length=80)
    context_id: str = Field(default="", max_length=120)
    module: str = Field(default="dashboard", max_length=80)


class AdvisorThreadOut(BaseModel):
    id: str
    title: str
    context_type: str = ""
    context_id: str = ""
    status: str = "active"
    updated_at: str = ""


class AdvisorMessageOut(BaseModel):
    id: str
    role: str
    content: str
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    ai_run_id: str = ""
    created_at: str = ""


class AdvisorChatOut(BaseModel):
    ok: bool = True
    thread: AdvisorThreadOut
    user_message: AdvisorMessageOut
    assistant_message: AdvisorMessageOut
    insights: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: list[dict[str, Any]] = Field(default_factory=list)

