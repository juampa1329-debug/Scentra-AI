from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from fastapi import HTTPException, Request

from app_saas.config import settings
from app_saas.shared.request_meta import client_ip

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def captcha_is_enabled() -> bool:
    return bool(settings.saas_captcha_enabled)


def captcha_public_status() -> dict[str, Any]:
    return {
        "enabled": captcha_is_enabled(),
        "provider": settings.saas_captcha_provider.strip().lower() or "turnstile",
    }


def verify_captcha_or_raise(*, token: str = "", provider: str = "", request: Request | None = None) -> None:
    if not captcha_is_enabled():
        return

    captcha_provider = (provider or settings.saas_captcha_provider or "turnstile").strip().lower()
    if captcha_provider != "turnstile":
        raise HTTPException(status_code=500, detail={"code": "captcha_provider_not_supported", "provider": captcha_provider})

    if not settings.turnstile_secret_key:
        raise HTTPException(status_code=503, detail={"code": "captcha_not_configured"})

    clean_token = str(token or "").strip()
    if not clean_token:
        raise HTTPException(status_code=400, detail={"code": "captcha_required"})

    payload = urllib.parse.urlencode(
        {
            "secret": settings.turnstile_secret_key,
            "response": clean_token,
            "remoteip": client_ip(request),
        }
    ).encode("utf-8")

    try:
        req = urllib.request.Request(
            TURNSTILE_VERIFY_URL,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as response:
            raw = response.read().decode("utf-8")
        data = json.loads(raw or "{}")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail={"code": "captcha_verify_unavailable", "message": str(exc)[:240]})

    if not data.get("success"):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "captcha_failed",
                "error_codes": data.get("error-codes") or data.get("error_codes") or [],
            },
        )
