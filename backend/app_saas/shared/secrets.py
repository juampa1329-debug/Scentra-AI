from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app_saas.config import settings

SECRET_PREFIX = "enc:v1:"
MASKED_SECRET = "********"


def _fernet() -> Fernet:
    raw_key = str(settings.saas_secret_key or settings.saas_jwt_secret or "dev-only-change-me").encode("utf-8")
    key = base64.urlsafe_b64encode(hashlib.sha256(raw_key).digest())
    return Fernet(key)


def is_masked_secret(value: str | None) -> bool:
    return str(value or "").strip() in {MASKED_SECRET, "************"}


def encrypt_secret(value: str | None) -> str:
    clean = str(value or "").strip()
    if not clean or clean.startswith(SECRET_PREFIX) or is_masked_secret(clean):
        return clean
    token = _fernet().encrypt(clean.encode("utf-8")).decode("utf-8")
    return f"{SECRET_PREFIX}{token}"


def decrypt_secret(value: str | None) -> str:
    clean = str(value or "").strip()
    if not clean:
        return ""
    if not clean.startswith(SECRET_PREFIX):
        return clean
    token = clean[len(SECRET_PREFIX) :].encode("utf-8")
    try:
        return _fernet().decrypt(token).decode("utf-8")
    except InvalidToken:
        return ""


def mask_secret(value: str | None) -> str:
    return MASKED_SECRET if str(value or "").strip() else ""
