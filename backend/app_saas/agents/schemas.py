from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AiAgentCreateIn(BaseModel):
    agent_type: str = Field(min_length=2, max_length=80)
    name: str = Field(default="", max_length=160)
    description: str = Field(default="", max_length=1200)
    channels_json: list[str] = Field(default_factory=list)
    tools_json: list[str] = Field(default_factory=list)
    goals_json: list[str] = Field(default_factory=list)
    personality_json: dict[str, Any] = Field(default_factory=dict)
    rules_json: list[str] = Field(default_factory=list)
    provider_policy_json: dict[str, Any] = Field(default_factory=dict)
    memory_policy_json: dict[str, Any] = Field(default_factory=dict)
    approval_policy_json: dict[str, Any] = Field(default_factory=dict)


class AiAgentPatchIn(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    description: str | None = Field(default=None, max_length=1200)
    status: str | None = Field(default=None, max_length=40)
    channels_json: list[str] | None = None
    tools_json: list[str] | None = None
    goals_json: list[str] | None = None
    personality_json: dict[str, Any] | None = None
    rules_json: list[str] | None = None
    provider_policy_json: dict[str, Any] | None = None
    memory_policy_json: dict[str, Any] | None = None
    approval_policy_json: dict[str, Any] | None = None


class AgentEventIn(BaseModel):
    event_type: str = Field(default="manual_note", max_length=80)
    summary: str = Field(default="", max_length=500)
    details_json: dict[str, Any] = Field(default_factory=dict)


class AgentActionDraftIn(BaseModel):
    title: str = Field(default="", max_length=180)
    description: str = Field(default="", max_length=1200)
    action_type: str = Field(default="", max_length=120)
    tool_code: str = Field(default="advisor.actions", max_length=120)
    target_module: str = Field(default="", max_length=120)
    impact: str = Field(default="medium", max_length=40)
    risk_level: str = Field(default="medium", max_length=40)
    payload_json: dict[str, Any] = Field(default_factory=dict)


class AgentArchiveIn(BaseModel):
    preserve_memory: bool = False
    memory_title: str = Field(default="", max_length=180)
    notes: str = Field(default="", max_length=1200)


class AgentMemoryRestoreIn(BaseModel):
    name: str = Field(default="", max_length=160)
    status: str = Field(default="draft", max_length=40)


class AgentMemoryImportIn(BaseModel):
    title: str = Field(default="", max_length=180)
    notes: str = Field(default="", max_length=1200)
    payload_json: dict[str, Any] = Field(default_factory=dict)
