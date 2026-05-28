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
    is_custom: bool = False
    base_template_type: str = Field(default="", max_length=80)
    system_prompt_template: str = Field(default="", max_length=12000)
    system_prompt_variables_json: dict[str, Any] = Field(default_factory=dict)
    system_prompt_rendered: str = Field(default="", max_length=20000)


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
    is_custom: bool | None = None
    base_template_type: str | None = Field(default=None, max_length=80)
    system_prompt_template: str | None = Field(default=None, max_length=12000)
    system_prompt_variables_json: dict[str, Any] | None = None
    system_prompt_rendered: str | None = Field(default=None, max_length=20000)


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
    preserve_memory: bool = True
    memory_title: str = Field(default="", max_length=180)
    notes: str = Field(default="", max_length=1200)


class AgentMemoryRestoreIn(BaseModel):
    name: str = Field(default="", max_length=160)
    status: str = Field(default="draft", max_length=40)


class AgentMemoryImportIn(BaseModel):
    title: str = Field(default="", max_length=180)
    notes: str = Field(default="", max_length=1200)
    payload_json: dict[str, Any] = Field(default_factory=dict)


class AgentCollectiveMemoryIn(BaseModel):
    source_agent_id: str = Field(default="", max_length=80)
    source_agent_type: str = Field(default="", max_length=80)
    memory_scope: str = Field(default="tenant", max_length=40)
    memory_type: str = Field(default="fact", max_length=40)
    title: str = Field(min_length=2, max_length=180)
    content: str = Field(min_length=2, max_length=4000)
    confidence_score: int = Field(default=80, ge=0, le=100)
    visibility: str = Field(default="agents", max_length=40)
    tags_json: list[str] = Field(default_factory=list)


class AgentPromptVersionIn(BaseModel):
    version_label: str = Field(default="Draft prompt", max_length=120)
    prompt_text: str = Field(min_length=2, max_length=12000)
    variables_json: dict[str, Any] = Field(default_factory=dict)


class AgentOrchestrationEventIn(BaseModel):
    event_type: str = Field(default="manual.test", max_length=120)
    entity_type: str = Field(default="manual", max_length=80)
    entity_id: str = Field(default="", max_length=180)
    channel: str = Field(default="global", max_length=40)
    source_agent_id: str = Field(default="", max_length=80)
    priority: int = Field(default=50, ge=1, le=100)
    payload_json: dict[str, Any] = Field(default_factory=dict)


class AgentOsMessageIn(BaseModel):
    source_agent_id: str = Field(default="", max_length=80)
    target_agent_id: str = Field(default="", max_length=80)
    message_type: str = Field(default="context", max_length=80)
    subject: str = Field(default="", max_length=180)
    body: str = Field(default="", max_length=4000)
    priority: int = Field(default=50, ge=1, le=100)
    payload_json: dict[str, Any] = Field(default_factory=dict)


class AgentToolRunIn(BaseModel):
    tool_code: str = Field(min_length=2, max_length=120)
    title: str = Field(default="", max_length=180)
    description: str = Field(default="", max_length=1200)
    impact: str = Field(default="medium", max_length=40)
    risk_level: str = Field(default="medium", max_length=40)
    input_json: dict[str, Any] = Field(default_factory=dict)
    create_action_draft: bool = True


class AgentMultimodalToolRunIn(BaseModel):
    tool_code: str = Field(default="media.voice_analyze", min_length=2, max_length=120)
    conversation_id: str = Field(default="", max_length=80)
    message_id: str = Field(default="", max_length=80)
    query: str = Field(default="", max_length=280)
    search_type: str = Field(default="mixed", max_length=20)
    provider_code: str = Field(default="", max_length=80)
    force: bool = False
    limit: int = Field(default=6, ge=1, le=12)
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class AgentMultimodalMemorySyncIn(BaseModel):
    conversation_id: str = Field(default="", max_length=80)
    message_id: str = Field(default="", max_length=80)
    agent_id: str = Field(default="", max_length=80)
    lookback_days: int = Field(default=30, ge=1, le=365)
    limit: int = Field(default=60, ge=1, le=200)
    include_voice: bool = True
    include_vision: bool = True
    include_search: bool = True
    include_agent_runs: bool = True


class AgentMultimodalMemoryMaterializeIn(BaseModel):
    destination: str = Field(default="knowledge", max_length=40)
    title: str = Field(default="", max_length=240)
    content_override: str = Field(default="", max_length=20000)
    allow_customer_content: bool = False
    confidence_score: int = Field(default=82, ge=0, le=100)


class AgentOsEventSyncIn(BaseModel):
    dry_run: bool = False
    limit: int = Field(default=50, ge=1, le=250)
    lookback_days: int = Field(default=7, ge=1, le=90)
