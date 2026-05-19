from __future__ import annotations

import time
import urllib.parse

from app_saas.ai_gateway.models import GatewayRequest, ProviderCallError, ProviderResult
from app_saas.ai_gateway.providers.base import BaseProviderAdapter
from app_saas.ai_gateway.providers.http import estimate_tokens, post_json


class GeminiAdapter(BaseProviderAdapter):
    def generate(self, request: GatewayRequest, token: str, model: str) -> ProviderResult:
        selected_model = model or self.definition.default_model
        query = urllib.parse.urlencode({"key": token})
        safe_model = urllib.parse.quote(selected_model, safe="")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{safe_model}:generateContent?{query}"
        payload = {
            "contents": [{"role": "user", "parts": [{"text": request.user_prompt}]}],
            "systemInstruction": {"parts": [{"text": request.system_prompt}]},
            "generationConfig": {
                "temperature": float(request.settings.get("temperature") or 0.5),
                "maxOutputTokens": int(request.settings.get("max_tokens") or 1800),
            },
        }
        if request.response_format == "json_object":
            payload["generationConfig"]["responseMimeType"] = "application/json"

        started = time.perf_counter()
        data = post_json(url, payload, timeout=int(request.settings.get("timeout_sec") or 45))
        latency_ms = int((time.perf_counter() - started) * 1000)
        candidates = data.get("candidates") if isinstance(data.get("candidates"), list) else []
        if not candidates:
            raise ProviderCallError("empty_candidates", "gemini returned no candidates", retryable=True)
        parts = (((candidates[0] or {}).get("content") or {}).get("parts") or [])
        raw = "\n".join(str(part.get("text") or "") for part in parts if isinstance(part, dict)).strip()
        usage = data.get("usageMetadata") if isinstance(data.get("usageMetadata"), dict) else {}
        input_tokens = int(usage.get("promptTokenCount") or estimate_tokens(request.system_prompt, request.user_prompt))
        output_tokens = int(usage.get("candidatesTokenCount") or estimate_tokens(raw))
        return ProviderResult(
            raw=raw,
            provider_code=self.definition.code,
            model=selected_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            metadata={"usage": usage},
        )

