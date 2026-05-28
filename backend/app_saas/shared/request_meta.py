from __future__ import annotations

from fastapi import Request


def client_ip(request: Request | None) -> str:
    if request is None:
        return ""
    for header in ("cf-connecting-ip", "x-real-ip", "x-forwarded-for"):
        value = str(request.headers.get(header) or "").strip()
        if value:
            return value.split(",", 1)[0].strip()
    return str(getattr(request.client, "host", "") or "")


def user_agent(request: Request | None) -> str:
    if request is None:
        return ""
    return str(request.headers.get("user-agent") or "")[:500]
