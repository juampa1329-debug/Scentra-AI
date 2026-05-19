from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProviderDefinition:
    code: str
    display_name: str
    credential_key: str
    default_model: str
    static_models: tuple[str, ...]
    adapter: str
    base_url: str = ""
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GatewayRequest:
    tenant_id: str
    task_type: str
    system_prompt: str
    user_prompt: str
    settings: dict[str, Any]
    agent_type: str = "sales_agent"
    route_code: str = "conversation.sales"
    conversation_id: str = ""
    response_format: str = "json_object"


@dataclass
class ProviderResult:
    raw: str
    provider_code: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    metadata: dict[str, Any] = field(default_factory=dict)


class ProviderCallError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False, http_status: int | None = None):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.http_status = http_status

