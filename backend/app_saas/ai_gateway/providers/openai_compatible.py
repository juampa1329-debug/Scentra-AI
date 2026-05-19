from __future__ import annotations

import time

from app_saas.ai_gateway.models import GatewayRequest, ProviderCallError, ProviderResult
from app_saas.ai_gateway.providers.base import BaseProviderAdapter
from app_saas.ai_gateway.providers.http import estimate_tokens, post_json
from app_saas.config import settings as app_settings


class OpenAICompatibleAdapter(BaseProviderAdapter):
    def generate(self, request: GatewayRequest, token: str, model: str) -> ProviderResult:
        provider = self.definition.code
        selected_model = model or self.definition.default_model
        base_url = self.definition.base_url.rstrip("/")
        url = f"{base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {token}"}
        if provider == "openrouter":
            headers.update(
                {
                    "HTTP-Referer": app_settings.scentra_app_public_url,
                    "X-Title": "Scentra +AI",
                }
            )
        payload = {
            "model": selected_model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "temperature": float(request.settings.get("temperature") or 0.5),
            "max_tokens": int(request.settings.get("max_tokens") or 1800),
        }
        if request.response_format == "json_object":
            payload["response_format"] = {"type": "json_object"}

        started = time.perf_counter()
        data = post_json(url, payload, headers=headers, timeout=int(request.settings.get("timeout_sec") or 45))
        latency_ms = int((time.perf_counter() - started) * 1000)
        choices = data.get("choices") if isinstance(data.get("choices"), list) else []
        if not choices:
            raise ProviderCallError("empty_choices", "provider returned no choices", retryable=True)
        message = (choices[0] or {}).get("message") or {}
        raw = str(message.get("content") or "").strip()
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        input_tokens = int(usage.get("prompt_tokens") or estimate_tokens(request.system_prompt, request.user_prompt))
        output_tokens = int(usage.get("completion_tokens") or estimate_tokens(raw))
        return ProviderResult(
            raw=raw,
            provider_code=provider,
            model=selected_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            metadata={"usage": usage, "id": data.get("id") or ""},
        )

