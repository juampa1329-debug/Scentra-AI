from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app_saas.ai_agent.service import ensure_ai_tables, get_settings, process_due_ai_replies
from app_saas.api_credentials.router import _ensure_api_credentials_table
from app_saas.config import settings
from app_saas.db import db_session, set_tenant_context
from app_saas.integrations.router import _integration_token, _safe_config_for_output
from app_saas.knowledge.router import ensure_knowledge_tables
from app_saas.shared.security import AuthContext, get_current_user, require_role
from app_saas.workers.dispatch import process_due_outbound_messages
from app_saas.workers.ingest import process_due_webhook_events

router = APIRouter(prefix="/diagnostics", tags=["saas-diagnostics"])


def _table_exists(conn: Connection, table_name: str) -> bool:
    return bool(conn.execute(text("SELECT to_regclass(:table_name) IS NOT NULL"), {"table_name": table_name}).scalar())


def _status_counts(conn: Connection, table_name: str, tenant_id: str) -> list[dict[str, Any]]:
    if not _table_exists(conn, table_name):
        return []
    rows = conn.execute(
        text(
            f"""
            SELECT status, COUNT(*)::int AS total
            FROM {table_name}
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            GROUP BY status
            ORDER BY status ASC
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().all()
    return [dict(row) for row in rows]


def _recent_rows(conn: Connection, sql: str, tenant_id: str, limit: int = 5) -> list[dict[str, Any]]:
    rows = conn.execute(text(sql), {"tenant_id": tenant_id, "limit": limit}).mappings().all()
    return [dict(row) for row in rows]


@router.get("/overview")
def diagnostics_overview(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_api_credentials_table(conn)
        ensure_ai_tables(conn)
        ensure_knowledge_tables(conn)
        tenant = conn.execute(
            text(
                """
                SELECT id::text, name, slug, status, plan_code
                FROM saas_tenants
                WHERE id = CAST(:tenant_id AS uuid)
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().first()
        ai_settings = get_settings(conn, ctx.tenant_id)
        credentials = conn.execute(
            text(
                """
                SELECT category, provider_code, credential_key, secret_hint, metadata_json, updated_at::text
                FROM saas_api_credentials
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                ORDER BY category, provider_code, credential_key
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().all()
        integrations = conn.execute(
            text(
                """
                SELECT provider, channel, status, config_json, last_sync_at::text
                FROM saas_integrations
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                ORDER BY provider, channel
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().all()
        integration_rows = []
        for row in integrations:
            data = dict(row)
            config = data.get("config_json") if isinstance(data.get("config_json"), dict) else {}
            safe_config = _safe_config_for_output(config)
            integration_rows.append(
                {
                    "provider": data.get("provider"),
                    "channel": data.get("channel"),
                    "status": data.get("status"),
                    "dispatch_mode": safe_config.get("dispatch_mode", ""),
                    "phone_number_id": safe_config.get("phone_number_id", ""),
                    "business_account_id": safe_config.get("business_account_id", ""),
                    "has_token": bool(_integration_token(config)),
                    "last_sync_at": data.get("last_sync_at") or "",
                }
            )
        webhooks = _recent_rows(
            conn,
            """
            SELECT provider, endpoint_key, is_active, signature_required, last_seen_at::text
            FROM saas_webhook_endpoints
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY updated_at DESC
            LIMIT :limit
            """,
            ctx.tenant_id,
        ) if _table_exists(conn, "saas_webhook_endpoints") else []
        last_events = _recent_rows(
            conn,
            """
            SELECT provider, status, received_at::text, processed_at::text, error
            FROM saas_webhook_events
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY received_at DESC
            LIMIT :limit
            """,
            ctx.tenant_id,
        ) if _table_exists(conn, "saas_webhook_events") else []
        outbound_errors = _recent_rows(
            conn,
            """
            SELECT status, channel, recipient_external_id, attempts, error, updated_at::text
            FROM saas_outbound_messages
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND COALESCE(error, '') <> ''
            ORDER BY updated_at DESC
            LIMIT :limit
            """,
            ctx.tenant_id,
        ) if _table_exists(conn, "saas_outbound_messages") else []
        totals = conn.execute(
            text(
                """
                SELECT
                  (SELECT COUNT(*) FROM saas_conversations WHERE tenant_id = CAST(:tenant_id AS uuid))::int AS conversations,
                  (SELECT COUNT(*) FROM saas_messages WHERE tenant_id = CAST(:tenant_id AS uuid))::int AS messages,
                  (SELECT COUNT(*) FROM saas_knowledge_sources WHERE tenant_id = CAST(:tenant_id AS uuid) AND status = 'active')::int AS knowledge_sources
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().first()
        webhook_counts = _status_counts(conn, "saas_webhook_events", ctx.tenant_id)
        outbound_counts = _status_counts(conn, "saas_outbound_messages", ctx.tenant_id)
        ai_pending_counts = _status_counts(conn, "saas_ai_pending_replies", ctx.tenant_id)
    return {
        "tenant": dict(tenant or {}),
        "runtime": {
            "api_ok": True,
            "embedded_worker_enabled": settings.saas_embedded_worker_enabled,
            "worker_idle_sec": settings.saas_worker_idle_sec,
            "cors_origins": settings.cors_origins,
        },
        "ai": {
            "enabled": bool(ai_settings.get("enabled")),
            "provider": ai_settings.get("provider_code"),
            "active_model": ai_settings.get("active_model"),
            "fallback_provider": ai_settings.get("fallback_provider_code"),
            "fallback_model": ai_settings.get("fallback_model"),
        },
        "credentials": [
            {
                "category": row["category"],
                "provider_code": row["provider_code"],
                "credential_key": row["credential_key"],
                "has_secret": bool(str(row.get("secret_hint") or "").strip()),
                "selected_model": (row.get("metadata_json") or {}).get("selected_model", "") if isinstance(row.get("metadata_json"), dict) else "",
                "updated_at": row["updated_at"],
            }
            for row in credentials
        ],
        "integrations": integration_rows,
        "webhooks": {"endpoints": webhooks, "events": webhook_counts, "last_events": last_events},
        "queues": {
            "outbound": outbound_counts,
            "ai_pending": ai_pending_counts,
            "outbound_errors": outbound_errors,
        },
        "totals": dict(totals or {}),
    }


@router.post("/run")
def run_diagnostics_processors(
    limit: int = Query(25, ge=1, le=200),
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    return {
        "webhooks": process_due_webhook_events(limit=limit, tenant_id=ctx.tenant_id),
        "ai": process_due_ai_replies(limit=limit, tenant_id=ctx.tenant_id),
        "outbound": process_due_outbound_messages(limit=limit, tenant_id=ctx.tenant_id),
    }
