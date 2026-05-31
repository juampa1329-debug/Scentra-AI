from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app_saas.config import settings
from app_saas.shared.secrets import decrypt_secret, encrypt_secret, is_masked_secret, mask_secret

PAYMENT_PROVIDERS = {
    "wompi": {
        "display_name": "Wompi",
        "title": "Paga con Wompi",
        "webhook_path": "/saas/v1/billing/webhooks/wompi",
        "required_checkout_fields": ("public_key", "integrity_key"),
        "required_webhook_fields": ("event_key",),
    },
    "mercadopago": {
        "display_name": "Mercado Pago",
        "title": "Paga con Mercado Pago",
        "webhook_path": "/saas/v1/billing/webhooks/mercadopago",
        "required_checkout_fields": ("access_token",),
        "required_webhook_fields": ("webhook_secret",),
    },
}
SECRET_COLUMNS = {
    "test_private_key": "test_private_key_enc",
    "test_event_key": "test_event_key_enc",
    "test_integrity_key": "test_integrity_key_enc",
    "live_private_key": "live_private_key_enc",
    "live_event_key": "live_event_key_enc",
    "live_integrity_key": "live_integrity_key_enc",
    "test_access_token": "test_access_token_enc",
    "test_webhook_secret": "test_webhook_secret_enc",
    "live_access_token": "live_access_token_enc",
    "live_webhook_secret": "live_webhook_secret_enc",
}


def _clean(value: object, limit: int = 1000) -> str:
    return str(value or "").strip()[:limit]


def _bool(value: object) -> bool:
    return bool(value)


def _api_public_url() -> str:
    return str(settings.scentra_api_public_url or "https://api.scentra-ai.online").rstrip("/")


def _env_provider_config(provider: str) -> dict[str, Any]:
    if provider == "wompi":
        environment = _clean(settings.wompi_environment, 40).lower() or "production"
        test_mode = environment in {"sandbox", "test", "testing", "dev", "development"}
        return {
            "provider": provider,
            "display_name": "Wompi",
            "title": "Paga con Wompi",
            "source": "environment",
            "has_database_config": False,
            "is_enabled": bool(settings.wompi_public_key or settings.wompi_integrity_key or settings.wompi_private_key or settings.wompi_events_key),
            "is_default": False,
            "test_mode": test_mode,
            "debug_logging": False,
            "environment": "sandbox" if test_mode else "production",
            "public_key": settings.wompi_public_key.strip(),
            "private_key": settings.wompi_private_key.strip(),
            "event_key": settings.wompi_events_key.strip(),
            "integrity_key": settings.wompi_integrity_key.strip(),
            "access_token": "",
            "webhook_secret": "",
        }
    if provider == "mercadopago":
        return {
            "provider": provider,
            "display_name": "Mercado Pago",
            "title": "Paga con Mercado Pago",
            "source": "environment",
            "has_database_config": False,
            "is_enabled": bool(settings.mercadopago_access_token or settings.mercadopago_webhook_secret),
            "is_default": False,
            "test_mode": False,
            "debug_logging": False,
            "environment": "production",
            "public_key": "",
            "private_key": "",
            "event_key": "",
            "integrity_key": "",
            "access_token": settings.mercadopago_access_token.strip(),
            "webhook_secret": settings.mercadopago_webhook_secret.strip(),
        }
    raise HTTPException(status_code=400, detail="unsupported_billing_provider")


def _row_to_runtime(row: dict[str, Any], provider: str) -> dict[str, Any]:
    mode = "test" if _bool(row.get("test_mode")) else "live"
    env = _env_provider_config(provider)
    public_key = _clean(row.get(f"{mode}_public_key")) or env.get("public_key", "")
    runtime = {
        "provider": provider,
        "display_name": _clean(row.get("display_name"), 120) or PAYMENT_PROVIDERS[provider]["display_name"],
        "title": _clean(row.get("title"), 140) or PAYMENT_PROVIDERS[provider]["title"],
        "source": "database",
        "has_database_config": True,
        "is_enabled": _bool(row.get("is_enabled")),
        "is_default": _bool(row.get("is_default")),
        "test_mode": _bool(row.get("test_mode")),
        "debug_logging": _bool(row.get("debug_logging")),
        "environment": "sandbox" if _bool(row.get("test_mode")) else "production",
        "public_key": public_key,
        "private_key": decrypt_secret(row.get(f"{mode}_private_key_enc")) or env.get("private_key", ""),
        "event_key": decrypt_secret(row.get(f"{mode}_event_key_enc")) or env.get("event_key", ""),
        "integrity_key": decrypt_secret(row.get(f"{mode}_integrity_key_enc")) or env.get("integrity_key", ""),
        "access_token": decrypt_secret(row.get(f"{mode}_access_token_enc")) or env.get("access_token", ""),
        "webhook_secret": decrypt_secret(row.get(f"{mode}_webhook_secret_enc")) or env.get("webhook_secret", ""),
    }
    return runtime


def _with_readiness(config: dict[str, Any]) -> dict[str, Any]:
    required_checkout = PAYMENT_PROVIDERS[config["provider"]]["required_checkout_fields"]
    required_webhook = PAYMENT_PROVIDERS[config["provider"]]["required_webhook_fields"]
    config["checkout_ready"] = config["is_enabled"] and all(_clean(config.get(field)) for field in required_checkout)
    config["webhook_ready"] = config["is_enabled"] and all(_clean(config.get(field)) for field in required_webhook)
    config["webhook_url"] = f"{_api_public_url()}{PAYMENT_PROVIDERS[config['provider']]['webhook_path']}"
    return config


def billing_provider_runtime_settings(conn: Connection, provider: str) -> dict[str, Any]:
    clean_provider = _clean(provider, 40).lower()
    if clean_provider not in PAYMENT_PROVIDERS:
        raise HTTPException(status_code=400, detail="unsupported_billing_provider")
    row = conn.execute(
        text(
            """
            SELECT *
            FROM saas_billing_provider_settings
            WHERE provider = :provider
            LIMIT 1
            """
        ),
        {"provider": clean_provider},
    ).mappings().first()
    if row:
        return _with_readiness(_row_to_runtime(dict(row), clean_provider))
    return _with_readiness(_env_provider_config(clean_provider))


def billing_default_provider(conn: Connection) -> str:
    row = conn.execute(
        text(
            """
            SELECT provider
            FROM saas_billing_provider_settings
            WHERE is_default = TRUE
              AND is_enabled = TRUE
            ORDER BY updated_at DESC
            LIMIT 1
            """
        )
    ).mappings().first()
    if row and row.get("provider"):
        return _clean(row["provider"], 40).lower()
    return _clean(settings.billing_default_provider, 40).lower() or "manual"


def ensure_billing_provider_ready(config: dict[str, Any], *, action: str = "checkout") -> None:
    provider = config.get("provider") or "provider"
    if not config.get("is_enabled"):
        raise HTTPException(status_code=501, detail=f"{provider}_disabled")
    ready_key = "webhook_ready" if action == "webhook" else "checkout_ready"
    if not config.get(ready_key):
        raise HTTPException(status_code=501, detail=f"{provider}_{action}_not_configured")


def _secret_for_public(config: dict[str, Any], key: str) -> str:
    return mask_secret(config.get(key))


def _public_provider_payload(config: dict[str, Any], row: dict[str, Any] | None = None) -> dict[str, Any]:
    provider = config["provider"]
    row = row or {}
    return {
        "provider": provider,
        "display_name": config.get("display_name") or PAYMENT_PROVIDERS[provider]["display_name"],
        "title": config.get("title") or PAYMENT_PROVIDERS[provider]["title"],
        "is_enabled": bool(config.get("is_enabled")),
        "is_default": bool(config.get("is_default")),
        "test_mode": bool(config.get("test_mode")),
        "debug_logging": bool(config.get("debug_logging")),
        "source": config.get("source", "database"),
        "has_database_config": bool(config.get("has_database_config")),
        "checkout_ready": bool(config.get("checkout_ready")),
        "webhook_ready": bool(config.get("webhook_ready")),
        "webhook_url": config.get("webhook_url"),
        "test": {
            "public_key": _clean(row.get("test_public_key")) if row else (config.get("public_key") if config.get("test_mode") else ""),
            "private_key": mask_secret(row.get("test_private_key_enc")) if row else (_secret_for_public(config, "private_key") if config.get("test_mode") else ""),
            "event_key": mask_secret(row.get("test_event_key_enc")) if row else (_secret_for_public(config, "event_key") if config.get("test_mode") else ""),
            "integrity_key": mask_secret(row.get("test_integrity_key_enc")) if row else (_secret_for_public(config, "integrity_key") if config.get("test_mode") else ""),
            "access_token": mask_secret(row.get("test_access_token_enc")) if row else (_secret_for_public(config, "access_token") if config.get("test_mode") else ""),
            "webhook_secret": mask_secret(row.get("test_webhook_secret_enc")) if row else (_secret_for_public(config, "webhook_secret") if config.get("test_mode") else ""),
        },
        "live": {
            "public_key": _clean(row.get("live_public_key")) if row else (config.get("public_key") if not config.get("test_mode") else ""),
            "private_key": mask_secret(row.get("live_private_key_enc")) if row else (_secret_for_public(config, "private_key") if not config.get("test_mode") else ""),
            "event_key": mask_secret(row.get("live_event_key_enc")) if row else (_secret_for_public(config, "event_key") if not config.get("test_mode") else ""),
            "integrity_key": mask_secret(row.get("live_integrity_key_enc")) if row else (_secret_for_public(config, "integrity_key") if not config.get("test_mode") else ""),
            "access_token": mask_secret(row.get("live_access_token_enc")) if row else (_secret_for_public(config, "access_token") if not config.get("test_mode") else ""),
            "webhook_secret": mask_secret(row.get("live_webhook_secret_enc")) if row else (_secret_for_public(config, "webhook_secret") if not config.get("test_mode") else ""),
        },
    }


def list_billing_provider_settings(conn: Connection) -> list[dict[str, Any]]:
    rows = {
        row["provider"]: dict(row)
        for row in conn.execute(
            text(
                """
                SELECT *
                FROM saas_billing_provider_settings
                WHERE provider IN ('wompi', 'mercadopago')
                ORDER BY provider ASC
                """
            )
        ).mappings().all()
    }
    payload: list[dict[str, Any]] = []
    for provider in ("wompi", "mercadopago"):
        runtime = billing_provider_runtime_settings(conn, provider)
        payload.append(_public_provider_payload(runtime, rows.get(provider)))
    return payload


def update_billing_provider_settings(
    conn: Connection,
    provider: str,
    patch: dict[str, Any],
    *,
    actor_user_id: str = "",
) -> dict[str, Any]:
    clean_provider = _clean(provider, 40).lower()
    if clean_provider not in PAYMENT_PROVIDERS:
        raise HTTPException(status_code=400, detail="unsupported_billing_provider")
    existing = conn.execute(
        text("SELECT * FROM saas_billing_provider_settings WHERE provider = :provider LIMIT 1"),
        {"provider": clean_provider},
    ).mappings().first()
    existing_dict = dict(existing or {})

    def secret_value(field: str) -> str:
        column = SECRET_COLUMNS[field]
        value = patch.get(field)
        if value is None or is_masked_secret(value) or str(value).strip() == "":
            return existing_dict.get(column, "")
        return encrypt_secret(_clean(value, 5000))

    values: dict[str, Any] = {
        "provider": clean_provider,
        "display_name": _clean(patch.get("display_name") or existing_dict.get("display_name") or PAYMENT_PROVIDERS[clean_provider]["display_name"], 120),
        "title": _clean(patch.get("title") or existing_dict.get("title") or PAYMENT_PROVIDERS[clean_provider]["title"], 140),
        "is_enabled": bool(patch.get("is_enabled")) if "is_enabled" in patch else bool(existing_dict.get("is_enabled")),
        "is_default": bool(patch.get("is_default")) if "is_default" in patch else bool(existing_dict.get("is_default")),
        "test_mode": bool(patch.get("test_mode")) if "test_mode" in patch else bool(existing_dict.get("test_mode", True)),
        "debug_logging": bool(patch.get("debug_logging")) if "debug_logging" in patch else bool(existing_dict.get("debug_logging")),
        "test_public_key": _clean(patch.get("test_public_key"), 1000) if "test_public_key" in patch else existing_dict.get("test_public_key", ""),
        "live_public_key": _clean(patch.get("live_public_key"), 1000) if "live_public_key" in patch else existing_dict.get("live_public_key", ""),
        "updated_by_user_id": actor_user_id or None,
    }
    for field, column in SECRET_COLUMNS.items():
        values[column] = secret_value(field)

    if values["is_default"]:
        conn.execute(
            text("UPDATE saas_billing_provider_settings SET is_default = FALSE WHERE provider <> :provider"),
            {"provider": clean_provider},
        )

    row = conn.execute(
        text(
            """
            INSERT INTO saas_billing_provider_settings (
                provider, display_name, title, is_enabled, is_default, test_mode, debug_logging,
                test_public_key, test_private_key_enc, test_event_key_enc, test_integrity_key_enc,
                live_public_key, live_private_key_enc, live_event_key_enc, live_integrity_key_enc,
                test_access_token_enc, test_webhook_secret_enc,
                live_access_token_enc, live_webhook_secret_enc,
                updated_by_user_id, updated_at
            )
            VALUES (
                :provider, :display_name, :title, :is_enabled, :is_default, :test_mode, :debug_logging,
                :test_public_key, :test_private_key_enc, :test_event_key_enc, :test_integrity_key_enc,
                :live_public_key, :live_private_key_enc, :live_event_key_enc, :live_integrity_key_enc,
                :test_access_token_enc, :test_webhook_secret_enc,
                :live_access_token_enc, :live_webhook_secret_enc,
                CAST(:updated_by_user_id AS uuid), NOW()
            )
            ON CONFLICT (provider)
            DO UPDATE SET
                display_name = EXCLUDED.display_name,
                title = EXCLUDED.title,
                is_enabled = EXCLUDED.is_enabled,
                is_default = EXCLUDED.is_default,
                test_mode = EXCLUDED.test_mode,
                debug_logging = EXCLUDED.debug_logging,
                test_public_key = EXCLUDED.test_public_key,
                test_private_key_enc = EXCLUDED.test_private_key_enc,
                test_event_key_enc = EXCLUDED.test_event_key_enc,
                test_integrity_key_enc = EXCLUDED.test_integrity_key_enc,
                live_public_key = EXCLUDED.live_public_key,
                live_private_key_enc = EXCLUDED.live_private_key_enc,
                live_event_key_enc = EXCLUDED.live_event_key_enc,
                live_integrity_key_enc = EXCLUDED.live_integrity_key_enc,
                test_access_token_enc = EXCLUDED.test_access_token_enc,
                test_webhook_secret_enc = EXCLUDED.test_webhook_secret_enc,
                live_access_token_enc = EXCLUDED.live_access_token_enc,
                live_webhook_secret_enc = EXCLUDED.live_webhook_secret_enc,
                updated_by_user_id = EXCLUDED.updated_by_user_id,
                updated_at = NOW()
            RETURNING *
            """
        ),
        values,
    ).mappings().first()
    runtime = billing_provider_runtime_settings(conn, clean_provider)
    return _public_provider_payload(runtime, dict(row or {}))
