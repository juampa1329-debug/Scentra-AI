from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from app_saas.ai_gateway.models import ProviderCallError

DEFAULT_PROVIDER_HEADERS = {
    "User-Agent": "ScentraAI/1.0 (+https://scentra-ai.online)",
    "Accept": "application/json",
}


def estimate_tokens(*parts: Any) -> int:
    size = sum(len(str(part or "")) for part in parts)
    return max(1, int(size / 4) + 16)


def post_json(url: str, payload: dict[str, Any], *, headers: dict[str, str] | None = None, timeout: int = 45) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={**DEFAULT_PROVIDER_HEADERS, "Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw or "{}")
            return parsed if isinstance(parsed, dict) else {"data": parsed}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        retryable = exc.code in {408, 409, 425, 429, 500, 502, 503, 504}
        raise ProviderCallError(f"http_{exc.code}", raw[:1200], retryable=retryable, http_status=exc.code) from exc
    except Exception as exc:
        raise ProviderCallError("provider_unavailable", str(exc)[:500], retryable=True) from exc


def get_json(url: str, *, headers: dict[str, str] | None = None, timeout: int = 20) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={**DEFAULT_PROVIDER_HEADERS, **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw or "{}")
            return parsed if isinstance(parsed, dict) else {"data": parsed}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        retryable = exc.code in {408, 409, 425, 429, 500, 502, 503, 504}
        raise ProviderCallError(f"http_{exc.code}", raw[:1200], retryable=retryable, http_status=exc.code) from exc
    except Exception as exc:
        raise ProviderCallError("provider_unavailable", str(exc)[:500], retryable=True) from exc
