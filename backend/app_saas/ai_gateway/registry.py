from __future__ import annotations

from app_saas.ai_gateway.models import ProviderDefinition
from app_saas.ai_gateway.providers.base import BaseProviderAdapter
from app_saas.ai_gateway.providers.gemini_adapter import GeminiAdapter
from app_saas.ai_gateway.providers.openai_compatible import OpenAICompatibleAdapter


PROVIDER_DEFINITIONS: dict[str, ProviderDefinition] = {
    "google": ProviderDefinition(
        code="google",
        display_name="Google / Gemini",
        credential_key="GOOGLE_AI_API_KEY",
        default_model="gemini-2.5-flash",
        static_models=("gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-flash", "gemini-1.5-pro"),
        adapter="gemini",
        capabilities=("generate", "stream", "structured_outputs", "long_context", "multimodal"),
    ),
    "groq": ProviderDefinition(
        code="groq",
        display_name="Groq",
        credential_key="GROQ_API_KEY",
        default_model="llama-3.1-8b-instant",
        static_models=("llama-3.1-8b-instant", "llama-3.1-70b-versatile", "llama-3.3-70b-versatile"),
        adapter="openai_compatible",
        base_url="https://api.groq.com/openai/v1",
        capabilities=("generate", "structured_outputs", "low_latency"),
    ),
    "mistral": ProviderDefinition(
        code="mistral",
        display_name="Mistral",
        credential_key="MISTRAL_API_KEY",
        default_model="mistral-small-latest",
        static_models=("mistral-small-latest", "mistral-medium-latest", "mistral-large-latest"),
        adapter="openai_compatible",
        base_url="https://api.mistral.ai/v1",
        capabilities=("generate", "structured_outputs", "classification"),
    ),
    "openrouter": ProviderDefinition(
        code="openrouter",
        display_name="OpenRouter",
        credential_key="OPENROUTER_API_KEY",
        default_model="google/gemini-2.5-flash",
        static_models=("google/gemini-2.5-flash", "openai/gpt-4o-mini", "meta-llama/llama-3.1-8b-instruct"),
        adapter="openai_compatible",
        base_url="https://openrouter.ai/api/v1",
        capabilities=("generate", "structured_outputs", "fallback_gateway", "multi_model"),
    ),
    "kimi": ProviderDefinition(
        code="kimi",
        display_name="Kimi / Moonshot AI",
        credential_key="KIMI_API_KEY",
        default_model="kimi-k2.6",
        static_models=("kimi-k2.6", "kimi-k2", "moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"),
        adapter="openai_compatible",
        base_url="https://api.moonshot.ai/v1",
        capabilities=("generate", "stream", "structured_outputs", "reasoning", "long_context", "tool_calling"),
        metadata={"aliases": ["MOONSHOT_API_KEY"], "official": True},
    ),
}


def provider_definition(provider_code: str) -> ProviderDefinition | None:
    return PROVIDER_DEFINITIONS.get(str(provider_code or "").strip().lower())


def provider_adapter(provider_code: str) -> BaseProviderAdapter:
    definition = provider_definition(provider_code)
    if not definition:
        raise KeyError(f"unsupported_provider:{provider_code}")
    if definition.adapter == "gemini":
        return GeminiAdapter(definition)
    return OpenAICompatibleAdapter(definition)

