from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app_saas.billing.limits import ensure_integration_quota
from app_saas.db import db_session, set_tenant_context
from app_saas.integrations.schemas import IntegrationOut, IntegrationUpsertIn
from app_saas.shared.security import AuthContext, get_current_user, require_role
from app_saas.shared.secrets import encrypt_secret, is_masked_secret, mask_secret

router = APIRouter(prefix="/integrations", tags=["saas-integrations"])

SENSITIVE_CONFIG_KEYS = {"access_token", "token", "permanent_token", "app_secret"}


def _safe_config_for_output(raw: dict | None) -> dict:
    config = dict(raw or {})
    for key in SENSITIVE_CONFIG_KEYS:
        value = str(config.get(key) or "").strip()
        if value:
            config[key] = mask_secret(value)
            config[f"has_{key}"] = True
    return config


def _merge_secret_config(incoming: dict, existing: dict | None) -> dict:
    next_config = dict(incoming or {})
    existing_config = dict(existing or {})
    for key in SENSITIVE_CONFIG_KEYS:
        incoming_value = str(next_config.get(key) or "").strip()
        if incoming_value and not is_masked_secret(incoming_value):
            next_config[key] = encrypt_secret(incoming_value)
            continue
        if existing_config.get(key):
            next_config[key] = existing_config[key]
        elif key in next_config:
            next_config.pop(key, None)
    return next_config


@router.get("", response_model=list[IntegrationOut])
def list_integrations(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        rows = conn.execute(
            text(
                """
                SELECT
                    id::text,
                    provider,
                    channel,
                    status,
                    secret_ref,
                    config_json,
                    last_sync_at::text
                FROM saas_integrations
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                ORDER BY provider ASC, channel ASC
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().all()
    return [
        IntegrationOut(
            **{
                **dict(row),
                "config_json": _safe_config_for_output(dict(row).get("config_json")),
            }
        )
        for row in rows
    ]


@router.post("", response_model=IntegrationOut)
def upsert_integration(
    payload: IntegrationUpsertIn,
    ctx: AuthContext = Depends(require_role("owner", "admin")),
):
    provider = payload.provider.strip().lower()
    channel = payload.channel.strip().lower()
    status = payload.status.strip().lower()
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        if status != "disconnected":
            ensure_integration_quota(conn, ctx.tenant_id, provider, channel)
        existing = conn.execute(
            text(
                """
                SELECT config_json
                FROM saas_integrations
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND provider = :provider
                  AND channel = :channel
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id, "provider": provider, "channel": channel},
        ).mappings().first()
        config_json = _merge_secret_config(payload.config_json or {}, dict(existing["config_json"] or {}) if existing else {})
        row = conn.execute(
            text(
                """
                INSERT INTO saas_integrations (
                    tenant_id, provider, channel, status, secret_ref, config_json, updated_at
                )
                VALUES (
                    CAST(:tenant_id AS uuid), :provider, :channel, :status, :secret_ref,
                    CAST(:config_json AS jsonb), NOW()
                )
                ON CONFLICT (tenant_id, provider, channel)
                DO UPDATE SET
                    status = EXCLUDED.status,
                    secret_ref = COALESCE(NULLIF(EXCLUDED.secret_ref, ''), saas_integrations.secret_ref),
                    config_json = EXCLUDED.config_json,
                    updated_at = NOW()
                RETURNING
                    id::text,
                    provider,
                    channel,
                    status,
                    secret_ref,
                    config_json,
                    last_sync_at::text
                """
            ),
            {
                "tenant_id": ctx.tenant_id,
                "provider": provider,
                "channel": channel,
                "status": status,
                "secret_ref": str(payload.secret_ref or "").strip(),
                "config_json": json.dumps(config_json),
            },
        ).mappings().first()
    return IntegrationOut(**{**dict(row), "config_json": _safe_config_for_output(dict(row).get("config_json"))})
