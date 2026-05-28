from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class WorkflowCreateIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=160)
    description: str | None = Field(default="", max_length=1200)
    category: str | None = Field(default="general", max_length=80)
    channel: str | None = Field(default="omnichannel", max_length=80)
    source_template_key: str | None = Field(default=None, max_length=180)
    graph_json: dict[str, Any] = Field(default_factory=dict)
    config_json: dict[str, Any] = Field(default_factory=dict)


class WorkflowPatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=1200)
    status: str | None = Field(default=None, max_length=40)
    category: str | None = Field(default=None, max_length=80)
    channel: str | None = Field(default=None, max_length=80)
    graph_json: dict[str, Any] | None = None
    config_json: dict[str, Any] | None = None


class WorkflowTemplateInstantiateIn(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    description: str | None = Field(default=None, max_length=1200)
    config_json: dict[str, Any] = Field(default_factory=dict)


class WorkflowSimulationIn(BaseModel):
    scenario_key: str | None = Field(default="manual", max_length=80)
    input_json: dict[str, Any] = Field(default_factory=dict)
    persist: bool = True


class WorkflowApprovalRequestIn(BaseModel):
    note: str | None = Field(default="", max_length=1200)


class WorkflowApprovalReviewIn(BaseModel):
    status: str = Field(..., max_length=30)
    note: str | None = Field(default="", max_length=1200)


class WorkflowMaterializeIn(BaseModel):
    target_type: str | None = Field(default="composer_only", max_length=80)
    config_json: dict[str, Any] = Field(default_factory=dict)


class WorkflowVersionRestoreIn(BaseModel):
    note: str | None = Field(default="", max_length=1200)
