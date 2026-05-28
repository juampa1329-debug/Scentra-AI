from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MarketplaceInstallIn(BaseModel):
    enable: bool = True
    create_resources: bool = False
    config_json: dict[str, Any] = Field(default_factory=dict)


class StatusPatchIn(BaseModel):
    status: str = Field(default="enabled", max_length=40)
    config_json: dict[str, Any] = Field(default_factory=dict)


class PluginCreateIn(BaseModel):
    plugin_key: str = Field(min_length=2, max_length=140)
    name: str = Field(min_length=2, max_length=180)
    description: str = Field(default="", max_length=1000)
    category: str = Field(default="ai", max_length=80)
    status: str = Field(default="draft", max_length=40)
    version: str = Field(default="1.0.0", max_length=80)
    runtime_type: str = Field(default="manifest", max_length=80)
    sandbox_mode: str = Field(default="metadata_only", max_length=80)
    permissions_json: list[Any] = Field(default_factory=list)
    manifest_json: dict[str, Any] = Field(default_factory=dict)
    config_json: dict[str, Any] = Field(default_factory=dict)


class PluginPatchIn(BaseModel):
    name: str | None = Field(default=None, max_length=180)
    description: str | None = Field(default=None, max_length=1000)
    category: str | None = Field(default=None, max_length=80)
    status: str | None = Field(default=None, max_length=40)
    version: str | None = Field(default=None, max_length=80)
    runtime_type: str | None = Field(default=None, max_length=80)
    sandbox_mode: str | None = Field(default=None, max_length=80)
    permissions_json: list[Any] | None = None
    manifest_json: dict[str, Any] | None = None
    config_json: dict[str, Any] | None = None
    approval_status: str | None = Field(default=None, max_length=40)


class ToolCreateIn(BaseModel):
    tool_key: str = Field(min_length=2, max_length=160)
    name: str = Field(min_length=2, max_length=180)
    category: str = Field(default="ai", max_length=80)
    description: str = Field(default="", max_length=1000)
    status: str = Field(default="enabled", max_length=40)
    risk_level: str = Field(default="medium", max_length=40)
    runtime_type: str = Field(default="manifest", max_length=80)
    handler_ref: str = Field(default="", max_length=240)
    input_schema_json: dict[str, Any] = Field(default_factory=dict)
    output_schema_json: dict[str, Any] = Field(default_factory=dict)
    permission_scopes_json: list[Any] = Field(default_factory=list)
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class ToolPatchIn(BaseModel):
    name: str | None = Field(default=None, max_length=180)
    category: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=1000)
    status: str | None = Field(default=None, max_length=40)
    risk_level: str | None = Field(default=None, max_length=40)
    runtime_type: str | None = Field(default=None, max_length=80)
    handler_ref: str | None = Field(default=None, max_length=240)
    input_schema_json: dict[str, Any] | None = None
    output_schema_json: dict[str, Any] | None = None
    permission_scopes_json: list[Any] | None = None
    metadata_json: dict[str, Any] | None = None


class EventSubscriptionCreateIn(BaseModel):
    subscriber_type: str = Field(default="plugin", max_length=80)
    subscriber_id: str = Field(default="", max_length=160)
    event_type: str = Field(min_length=2, max_length=160)
    target_type: str = Field(default="internal", max_length=80)
    target_ref: str = Field(default="", max_length=240)
    status: str = Field(default="enabled", max_length=40)
    priority: int = Field(default=50, ge=0, le=1000)
    filters_json: dict[str, Any] = Field(default_factory=dict)
    retry_policy_json: dict[str, Any] = Field(default_factory=dict)


class EventSubscriptionPatchIn(BaseModel):
    status: str | None = Field(default=None, max_length=40)
    priority: int | None = Field(default=None, ge=0, le=1000)
    filters_json: dict[str, Any] | None = None
    retry_policy_json: dict[str, Any] | None = None


class DeveloperAppCreateIn(BaseModel):
    app_key: str = Field(min_length=2, max_length=140)
    name: str = Field(min_length=2, max_length=180)
    description: str = Field(default="", max_length=1000)
    status: str = Field(default="active", max_length=40)
    scopes_json: list[Any] = Field(default_factory=list)
    webhook_url: str = Field(default="", max_length=1000)


class DeveloperAppPatchIn(BaseModel):
    name: str | None = Field(default=None, max_length=180)
    description: str | None = Field(default=None, max_length=1000)
    status: str | None = Field(default=None, max_length=40)
    scopes_json: list[Any] | None = None
    webhook_url: str | None = Field(default=None, max_length=1000)


class ExternalIntegrationCreateIn(BaseModel):
    integration_key: str = Field(min_length=2, max_length=140)
    provider_type: str = Field(default="crm", max_length=80)
    provider_name: str = Field(min_length=2, max_length=160)
    status: str = Field(default="draft", max_length=40)
    auth_mode: str = Field(default="none", max_length=80)
    scopes_json: list[Any] = Field(default_factory=list)
    config_json: dict[str, Any] = Field(default_factory=dict)


class ExternalIntegrationPatchIn(BaseModel):
    provider_type: str | None = Field(default=None, max_length=80)
    provider_name: str | None = Field(default=None, max_length=160)
    status: str | None = Field(default=None, max_length=40)
    auth_mode: str | None = Field(default=None, max_length=80)
    scopes_json: list[Any] | None = None
    config_json: dict[str, Any] | None = None
    health_json: dict[str, Any] | None = None


class AiAppCreateIn(BaseModel):
    app_key: str = Field(min_length=2, max_length=140)
    name: str = Field(min_length=2, max_length=180)
    app_type: str = Field(default="dashboard", max_length=80)
    description: str = Field(default="", max_length=1000)
    status: str = Field(default="draft", max_length=40)
    manifest_json: dict[str, Any] = Field(default_factory=dict)
    permissions_json: list[Any] = Field(default_factory=list)
    layout_json: dict[str, Any] = Field(default_factory=dict)


class AiAppPatchIn(BaseModel):
    name: str | None = Field(default=None, max_length=180)
    app_type: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=1000)
    status: str | None = Field(default=None, max_length=40)
    manifest_json: dict[str, Any] | None = None
    permissions_json: list[Any] | None = None
    layout_json: dict[str, Any] | None = None
