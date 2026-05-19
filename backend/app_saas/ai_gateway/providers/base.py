from __future__ import annotations

from abc import ABC, abstractmethod

from app_saas.ai_gateway.models import GatewayRequest, ProviderDefinition, ProviderResult


class BaseProviderAdapter(ABC):
    def __init__(self, definition: ProviderDefinition):
        self.definition = definition

    @abstractmethod
    def generate(self, request: GatewayRequest, token: str, model: str) -> ProviderResult:
        raise NotImplementedError

    def stream(self, request: GatewayRequest, token: str, model: str):
        raise NotImplementedError("streaming_not_implemented")

    def embeddings(self, text: str, token: str, model: str):
        raise NotImplementedError("embeddings_not_implemented")

    def tool_call(self, request: GatewayRequest, token: str, model: str):
        raise NotImplementedError("tool_call_not_implemented")

    def reasoning(self, request: GatewayRequest, token: str, model: str) -> ProviderResult:
        return self.generate(request, token, model)

    def moderation(self, text: str, token: str) -> dict:
        return {"ok": True, "provider": self.definition.code, "flagged": False, "mode": "not_configured"}

