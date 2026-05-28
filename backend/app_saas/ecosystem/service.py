from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
import secrets
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app_saas.agents.service import create_from_template
from app_saas.ecosystem.catalog import (
    DEFAULT_MARKETPLACE_ITEMS,
    DEFAULT_TOOL_REGISTRY,
    ECOSYSTEM_EVENT_TYPES,
    ECOSYSTEM_FEATURE_KEYS,
    ECOSYSTEM_SCOPES,
)
from app_saas.intelligence.service import (
    intelligence_feature_state,
    record_intelligence_usage,
    resolve_intelligence_access,
)


ECOSYSTEM_VERSION = "phase_11_ai_platform_ecosystem"


def _clean(value: Any, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def _json_value(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return fallback


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _row(row: dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    json_fields = {
        "manifest_json",
        "permissions_json",
        "install_schema_json",
        "tags_json",
        "config_json",
        "installation_result_json",
        "input_schema_json",
        "output_schema_json",
        "permission_scopes_json",
        "metadata_json",
        "filters_json",
        "retry_policy_json",
        "scopes_json",
        "health_json",
        "layout_json",
        "input_json",
        "output_json",
        "dimensions_json",
    }
    list_fields = {"permissions_json", "tags_json", "permission_scopes_json", "scopes_json"}
    for key in json_fields:
        if key in data:
            data[key] = _json_value(data.get(key), [] if key in list_fields else {})
    return {key: _jsonable(value) for key, value in data.items()}


def _normalize_key(value: Any, limit: int = 140) -> str:
    clean = _clean(value, limit).lower().replace(" ", "_").replace("-", "_")
    return "".join(ch for ch in clean if ch.isalnum() or ch in {"_", ".", ":"})[:limit]


def ensure_ecosystem_tables(conn: Connection) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_marketplace_items (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                item_key TEXT NOT NULL UNIQUE,
                item_type TEXT NOT NULL DEFAULT 'agent_template',
                category TEXT NOT NULL DEFAULT 'general',
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                publisher TEXT NOT NULL DEFAULT 'Scentra',
                version TEXT NOT NULL DEFAULT '1.0.0',
                status TEXT NOT NULL DEFAULT 'published',
                premium_required BOOLEAN NOT NULL DEFAULT TRUE,
                required_feature_key TEXT NOT NULL DEFAULT 'ai_marketplace',
                manifest_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                permissions_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                install_schema_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                tags_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                created_by_tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE SET NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_marketplace_items_type_status ON saas_ai_marketplace_items (item_type, status, category)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_marketplace_items_feature ON saas_ai_marketplace_items (required_feature_key, premium_required, status)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_marketplace_installations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                item_id UUID NOT NULL REFERENCES saas_ai_marketplace_items(id) ON DELETE CASCADE,
                installed_version TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'installed',
                config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                installation_result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                installed_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                enabled_at TIMESTAMP NULL,
                installed_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, item_id)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_marketplace_installations_tenant ON saas_ai_marketplace_installations (tenant_id, status, updated_at DESC)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_plugins (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                plugin_key TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT 'ai',
                status TEXT NOT NULL DEFAULT 'draft',
                version TEXT NOT NULL DEFAULT '1.0.0',
                runtime_type TEXT NOT NULL DEFAULT 'manifest',
                sandbox_mode TEXT NOT NULL DEFAULT 'metadata_only',
                permissions_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                manifest_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                approval_status TEXT NOT NULL DEFAULT 'pending',
                created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, plugin_key)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_plugins_tenant_status ON saas_ai_plugins (tenant_id, status, category, updated_at DESC)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_tool_registry (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                tool_key TEXT NOT NULL,
                name TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'ai',
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'enabled',
                risk_level TEXT NOT NULL DEFAULT 'medium',
                runtime_type TEXT NOT NULL DEFAULT 'internal',
                handler_ref TEXT NOT NULL DEFAULT '',
                input_schema_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                output_schema_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                permission_scopes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_saas_ai_tool_registry_system_key ON saas_ai_tool_registry (tool_key) WHERE tenant_id IS NULL"))
    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_saas_ai_tool_registry_tenant_key ON saas_ai_tool_registry (tenant_id, tool_key) WHERE tenant_id IS NOT NULL"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_tool_registry_tenant_status ON saas_ai_tool_registry (tenant_id, status, category, risk_level)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_ecosystem_event_subscriptions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                subscriber_type TEXT NOT NULL DEFAULT 'plugin',
                subscriber_id TEXT NOT NULL DEFAULT '',
                event_type TEXT NOT NULL,
                target_type TEXT NOT NULL DEFAULT 'internal',
                target_ref TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'enabled',
                priority INTEGER NOT NULL DEFAULT 50,
                filters_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                retry_policy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, subscriber_type, subscriber_id, event_type, target_ref)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_ecosystem_subscriptions_enabled ON saas_ai_ecosystem_event_subscriptions (tenant_id, status, event_type, priority DESC)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_developer_apps (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                app_key TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                scopes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                webhook_url TEXT NOT NULL DEFAULT '',
                api_key_hash TEXT NOT NULL DEFAULT '',
                api_key_hint TEXT NOT NULL DEFAULT '',
                created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                last_used_at TIMESTAMP NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, app_key)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_developer_apps_tenant_status ON saas_ai_developer_apps (tenant_id, status, updated_at DESC)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_external_integrations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                integration_key TEXT NOT NULL,
                provider_type TEXT NOT NULL DEFAULT 'crm',
                provider_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                auth_mode TEXT NOT NULL DEFAULT 'none',
                scopes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                health_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, integration_key)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_external_integrations_tenant_status ON saas_ai_external_integrations (tenant_id, status, provider_type)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_apps (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                app_key TEXT NOT NULL,
                name TEXT NOT NULL,
                app_type TEXT NOT NULL DEFAULT 'dashboard',
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft',
                manifest_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                permissions_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                layout_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, app_key)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_apps_tenant_status ON saas_ai_apps (tenant_id, status, app_type)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_ecosystem_traces (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL DEFAULT '',
                event_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ok',
                duration_ms INTEGER NOT NULL DEFAULT 0,
                input_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                output_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                error_text TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_ecosystem_traces_tenant_time ON saas_ai_ecosystem_traces (tenant_id, entity_type, event_type, created_at DESC)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_ecosystem_metrics (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                metric_key TEXT NOT NULL,
                metric_value NUMERIC(18,4) NOT NULL DEFAULT 0,
                dimensions_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                period_key TEXT NOT NULL DEFAULT 'latest',
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_ecosystem_metrics_tenant ON saas_ai_ecosystem_metrics (tenant_id, metric_key, period_key, created_at DESC)"))


def seed_ecosystem_defaults(conn: Connection) -> None:
    ensure_ecosystem_tables(conn)
    for item in DEFAULT_MARKETPLACE_ITEMS:
        conn.execute(
            text(
                """
                INSERT INTO saas_ai_marketplace_items (
                    item_key, item_type, category, name, description, publisher, version,
                    status, premium_required, required_feature_key, manifest_json,
                    permissions_json, install_schema_json, tags_json, updated_at
                )
                VALUES (
                    :item_key, :item_type, :category, :name, :description, 'Scentra',
                    COALESCE(:version, '1.0.0'), 'published', TRUE, :required_feature_key,
                    CAST(:manifest_json AS jsonb), CAST(:permissions_json AS jsonb),
                    CAST(:install_schema_json AS jsonb), CAST(:tags_json AS jsonb), NOW()
                )
                ON CONFLICT (item_key) DO UPDATE SET
                    item_type = EXCLUDED.item_type,
                    category = EXCLUDED.category,
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    version = EXCLUDED.version,
                    status = EXCLUDED.status,
                    required_feature_key = EXCLUDED.required_feature_key,
                    manifest_json = EXCLUDED.manifest_json,
                    permissions_json = EXCLUDED.permissions_json,
                    install_schema_json = EXCLUDED.install_schema_json,
                    tags_json = EXCLUDED.tags_json,
                    updated_at = NOW()
                """
            ),
            {
                "item_key": item["item_key"],
                "item_type": item["item_type"],
                "category": item["category"],
                "name": item["name"],
                "description": item.get("description") or "",
                "version": item.get("version") or "1.0.0",
                "required_feature_key": item.get("required_feature_key") or "ai_marketplace",
                "manifest_json": _json(item.get("manifest_json") or {}),
                "permissions_json": _json(item.get("permissions_json") or []),
                "install_schema_json": _json(item.get("install_schema_json") or {}),
                "tags_json": _json(item.get("tags_json") or []),
            },
        )
    for tool in DEFAULT_TOOL_REGISTRY:
        conn.execute(
            text(
                """
                INSERT INTO saas_ai_tool_registry (
                    tenant_id, tool_key, name, category, description, status, risk_level,
                    runtime_type, handler_ref, input_schema_json, output_schema_json,
                    permission_scopes_json, metadata_json, updated_at
                )
                VALUES (
                    NULL, :tool_key, :name, :category, :description, 'enabled', :risk_level,
                    'internal', :handler_ref, CAST(:input_schema_json AS jsonb),
                    CAST(:output_schema_json AS jsonb), CAST(:permission_scopes_json AS jsonb),
                    CAST(:metadata_json AS jsonb), NOW()
                )
                ON CONFLICT (tool_key) WHERE tenant_id IS NULL DO UPDATE SET
                    name = EXCLUDED.name,
                    category = EXCLUDED.category,
                    description = EXCLUDED.description,
                    status = EXCLUDED.status,
                    risk_level = EXCLUDED.risk_level,
                    runtime_type = EXCLUDED.runtime_type,
                    handler_ref = EXCLUDED.handler_ref,
                    input_schema_json = EXCLUDED.input_schema_json,
                    output_schema_json = EXCLUDED.output_schema_json,
                    permission_scopes_json = EXCLUDED.permission_scopes_json,
                    metadata_json = EXCLUDED.metadata_json,
                    updated_at = NOW()
                """
            ),
            {
                "tool_key": tool["tool_key"],
                "name": tool["name"],
                "category": tool.get("category") or "ai",
                "description": tool.get("description") or "",
                "risk_level": tool.get("risk_level") or "medium",
                "handler_ref": tool.get("handler_ref") or "",
                "input_schema_json": _json(tool.get("input_schema_json") or {}),
                "output_schema_json": _json(tool.get("output_schema_json") or {}),
                "permission_scopes_json": _json(tool.get("permission_scopes_json") or []),
                "metadata_json": _json({"seed": "system", "ecosystem_version": ECOSYSTEM_VERSION}),
            },
        )


def ecosystem_access(conn: Connection, tenant_id: str) -> dict[str, Any]:
    seed_ecosystem_defaults(conn)
    state = intelligence_feature_state(conn, tenant_id)
    features = {str(item.get("key")): item for item in state.get("features", [])}
    modes = {key: str(features.get(key, {}).get("mode") or "disabled") for key in ECOSYSTEM_FEATURE_KEYS}
    enabled = {key: bool(features.get(key, {}).get("enabled")) for key in ECOSYSTEM_FEATURE_KEYS}
    full_enabled = {key: modes.get(key) == "full" for key in ECOSYSTEM_FEATURE_KEYS}
    return {
        "state": state,
        "features": features,
        "modes": modes,
        "enabled": enabled,
        "full_enabled": full_enabled,
        "demo_available": any(modes.get(key) == "demo" for key in ECOSYSTEM_FEATURE_KEYS),
        "full_available": any(full_enabled.values()),
    }


def _require_feature(conn: Connection, tenant_id: str, feature_key: str, *, allow_demo: bool = False) -> dict[str, Any]:
    access = resolve_intelligence_access(conn, tenant_id, feature_key, allow_demo=allow_demo)
    record_intelligence_usage(
        conn,
        tenant_id,
        feature_key,
        metadata={"source": "ai_platform_ecosystem", "mode": access.get("mode")},
    )
    return access


def _trace(
    conn: Connection,
    tenant_id: str,
    *,
    entity_type: str,
    entity_id: str = "",
    event_type: str,
    status: str = "ok",
    input_json: dict[str, Any] | None = None,
    output_json: dict[str, Any] | None = None,
    error_text: str = "",
) -> None:
    conn.execute(
        text(
            """
            INSERT INTO saas_ai_ecosystem_traces (
                tenant_id, entity_type, entity_id, event_type, status, input_json, output_json, error_text
            )
            VALUES (
                CAST(:tenant_id AS uuid), :entity_type, :entity_id, :event_type, :status,
                CAST(:input_json AS jsonb), CAST(:output_json AS jsonb), :error_text
            )
            """
        ),
        {
            "tenant_id": tenant_id,
            "entity_type": _clean(entity_type, 80),
            "entity_id": _clean(entity_id, 160),
            "event_type": _clean(event_type, 160),
            "status": _clean(status, 40),
            "input_json": _json(input_json or {}),
            "output_json": _json(output_json or {}),
            "error_text": _clean(error_text, 1200),
        },
    )


def _get_marketplace_item(conn: Connection, item_id: str) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            SELECT id::text, item_key, item_type, category, name, description, publisher, version,
                   status, premium_required, required_feature_key, manifest_json,
                   permissions_json, install_schema_json, tags_json, created_at::text, updated_at::text
            FROM saas_ai_marketplace_items
            WHERE id = CAST(:item_id AS uuid)
            LIMIT 1
            """
        ),
        {"item_id": item_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="marketplace_item_not_found")
    return _row(dict(row))


def list_marketplace_items(conn: Connection, tenant_id: str, *, item_type: str = "", category: str = "") -> list[dict[str, Any]]:
    seed_ecosystem_defaults(conn)
    access = ecosystem_access(conn, tenant_id)
    params = {"tenant_id": tenant_id, "item_type": _clean(item_type, 80), "category": _clean(category, 80)}
    rows = conn.execute(
        text(
            """
            SELECT i.id::text, i.item_key, i.item_type, i.category, i.name, i.description,
                   i.publisher, i.version, i.status, i.premium_required, i.required_feature_key,
                   i.manifest_json, i.permissions_json, i.install_schema_json, i.tags_json,
                   ins.id::text AS installation_id, COALESCE(ins.status, '') AS installation_status,
                   ins.updated_at::text AS installation_updated_at,
                   i.created_at::text, i.updated_at::text
            FROM saas_ai_marketplace_items i
            LEFT JOIN saas_ai_marketplace_installations ins
              ON ins.item_id = i.id AND ins.tenant_id = CAST(:tenant_id AS uuid)
            WHERE i.status = 'published'
              AND (:item_type = '' OR i.item_type = :item_type)
              AND (:category = '' OR i.category = :category)
            ORDER BY i.category, i.item_type, i.name
            """
        ),
        params,
    ).mappings().all()
    items = []
    for row in rows:
        item = _row(dict(row))
        feature_key = str(item.get("required_feature_key") or "")
        item["access"] = {
            "feature_key": feature_key,
            "enabled": bool(access["enabled"].get(feature_key)),
            "mode": access["modes"].get(feature_key, "disabled"),
            "install_requires_full": bool(item.get("premium_required", True)),
        }
        items.append(item)
    return items


def list_marketplace_installations(conn: Connection, tenant_id: str) -> list[dict[str, Any]]:
    seed_ecosystem_defaults(conn)
    rows = conn.execute(
        text(
            """
            SELECT ins.id::text, ins.tenant_id::text, ins.item_id::text, i.item_key, i.item_type,
                   i.category, i.name, i.description, i.required_feature_key, ins.installed_version,
                   ins.status, ins.config_json, ins.installation_result_json,
                   ins.installed_by_user_id::text, ins.enabled_at::text, ins.installed_at::text,
                   ins.updated_at::text
            FROM saas_ai_marketplace_installations ins
            JOIN saas_ai_marketplace_items i ON i.id = ins.item_id
            WHERE ins.tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY ins.updated_at DESC
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().all()
    return [_row(dict(row)) for row in rows]


def install_marketplace_item(conn: Connection, tenant_id: str, user_id: str, item_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    seed_ecosystem_defaults(conn)
    item = _get_marketplace_item(conn, item_id)
    feature_key = str(item.get("required_feature_key") or "ai_marketplace")
    _require_feature(conn, tenant_id, feature_key, allow_demo=not bool(item.get("premium_required", True)))
    manifest = item.get("manifest_json") if isinstance(item.get("manifest_json"), dict) else {}
    result: dict[str, Any] = {
        "item_key": item.get("item_key"),
        "item_type": item.get("item_type"),
        "created_resources": [],
        "execution_mode": "control_plane",
    }
    if payload.get("create_resources") and item.get("item_type") == "agent_template":
        agent_type = _clean(manifest.get("agent_type"), 80)
        if agent_type:
            agent = create_from_template(conn, tenant_id, user_id, agent_type)
            result["created_resources"].append({"type": "agent", "id": agent.get("id"), "agent_type": agent.get("agent_type")})
    status = "enabled" if payload.get("enable", True) else "installed"
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_marketplace_installations (
                tenant_id, item_id, installed_version, status, config_json, installation_result_json,
                installed_by_user_id, enabled_at, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), CAST(:item_id AS uuid), :installed_version, :status,
                CAST(:config_json AS jsonb), CAST(:installation_result_json AS jsonb),
                CAST(:user_id AS uuid), CASE WHEN :status = 'enabled' THEN NOW() ELSE NULL END, NOW()
            )
            ON CONFLICT (tenant_id, item_id) DO UPDATE SET
                installed_version = EXCLUDED.installed_version,
                status = EXCLUDED.status,
                config_json = EXCLUDED.config_json,
                installation_result_json = EXCLUDED.installation_result_json,
                installed_by_user_id = EXCLUDED.installed_by_user_id,
                enabled_at = CASE
                    WHEN EXCLUDED.status = 'enabled' THEN COALESCE(saas_ai_marketplace_installations.enabled_at, NOW())
                    ELSE saas_ai_marketplace_installations.enabled_at
                END,
                updated_at = NOW()
            RETURNING id::text, tenant_id::text, item_id::text, installed_version, status,
                      config_json, installation_result_json, installed_by_user_id::text,
                      enabled_at::text, installed_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "item_id": item_id,
            "installed_version": item.get("version") or "",
            "status": status,
            "config_json": _json(payload.get("config_json") or {}),
            "installation_result_json": _json(result),
            "user_id": user_id,
        },
    ).mappings().first()
    installation = _row(dict(row or {}))
    _trace(conn, tenant_id, entity_type="marketplace_installation", entity_id=installation.get("id", ""), event_type="marketplace.install", input_json={"item_id": item_id}, output_json=result)
    return installation


def update_installation(conn: Connection, tenant_id: str, installation_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    _require_feature(conn, tenant_id, "ai_marketplace", allow_demo=False)
    status = _clean(payload.get("status"), 40).lower() or "enabled"
    row = conn.execute(
        text(
            """
            UPDATE saas_ai_marketplace_installations
            SET status = :status,
                config_json = CASE WHEN :config_json = '{}' THEN config_json ELSE CAST(:config_json AS jsonb) END,
                enabled_at = CASE WHEN :status = 'enabled' THEN COALESCE(enabled_at, NOW()) ELSE enabled_at END,
                updated_at = NOW()
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:installation_id AS uuid)
            RETURNING id::text, tenant_id::text, item_id::text, installed_version, status,
                      config_json, installation_result_json, installed_by_user_id::text,
                      enabled_at::text, installed_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "installation_id": installation_id,
            "status": status,
            "config_json": _json(payload.get("config_json") or {}),
        },
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="marketplace_installation_not_found")
    item = _row(dict(row))
    _trace(conn, tenant_id, entity_type="marketplace_installation", entity_id=installation_id, event_type="marketplace.update", output_json={"status": status})
    return item


def _list_table(conn: Connection, tenant_id: str, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    rows = conn.execute(text(sql), {"tenant_id": tenant_id, **(params or {})}).mappings().all()
    return [_row(dict(row)) for row in rows]


def list_plugins(conn: Connection, tenant_id: str) -> list[dict[str, Any]]:
    seed_ecosystem_defaults(conn)
    return _list_table(
        conn,
        tenant_id,
        """
        SELECT id::text, tenant_id::text, plugin_key, name, description, category, status,
               version, runtime_type, sandbox_mode, permissions_json, manifest_json, config_json,
               approval_status, created_by_user_id::text, created_at::text, updated_at::text
        FROM saas_ai_plugins
        WHERE tenant_id = CAST(:tenant_id AS uuid)
        ORDER BY updated_at DESC
        """,
    )


def create_plugin(conn: Connection, tenant_id: str, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    _require_feature(conn, tenant_id, "ai_plugin_center", allow_demo=False)
    plugin_key = _normalize_key(payload.get("plugin_key"))
    if not plugin_key:
        raise HTTPException(status_code=400, detail="plugin_key_required")
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_plugins (
                tenant_id, plugin_key, name, description, category, status, version, runtime_type,
                sandbox_mode, permissions_json, manifest_json, config_json, created_by_user_id, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), :plugin_key, :name, :description, :category, :status,
                :version, :runtime_type, :sandbox_mode, CAST(:permissions_json AS jsonb),
                CAST(:manifest_json AS jsonb), CAST(:config_json AS jsonb), CAST(:user_id AS uuid), NOW()
            )
            ON CONFLICT (tenant_id, plugin_key) DO UPDATE SET
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                category = EXCLUDED.category,
                status = EXCLUDED.status,
                version = EXCLUDED.version,
                runtime_type = EXCLUDED.runtime_type,
                sandbox_mode = EXCLUDED.sandbox_mode,
                permissions_json = EXCLUDED.permissions_json,
                manifest_json = EXCLUDED.manifest_json,
                config_json = EXCLUDED.config_json,
                updated_at = NOW()
            RETURNING id::text, tenant_id::text, plugin_key, name, description, category, status,
                      version, runtime_type, sandbox_mode, permissions_json, manifest_json, config_json,
                      approval_status, created_by_user_id::text, created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "plugin_key": plugin_key,
            "name": _clean(payload.get("name"), 180),
            "description": _clean(payload.get("description"), 1000),
            "category": _normalize_key(payload.get("category"), 80) or "ai",
            "status": _clean(payload.get("status"), 40).lower() or "draft",
            "version": _clean(payload.get("version"), 80) or "1.0.0",
            "runtime_type": _clean(payload.get("runtime_type"), 80).lower() or "manifest",
            "sandbox_mode": _clean(payload.get("sandbox_mode"), 80).lower() or "metadata_only",
            "permissions_json": _json(payload.get("permissions_json") or []),
            "manifest_json": _json(payload.get("manifest_json") or {}),
            "config_json": _json(payload.get("config_json") or {}),
            "user_id": user_id,
        },
    ).mappings().first()
    item = _row(dict(row or {}))
    _trace(conn, tenant_id, entity_type="plugin", entity_id=item.get("id", ""), event_type="plugin.upsert", output_json={"plugin_key": plugin_key})
    return item


def patch_plugin(conn: Connection, tenant_id: str, plugin_id: str, payload: dict[str, Any], user_id: str) -> dict[str, Any]:
    _require_feature(conn, tenant_id, "ai_plugin_center", allow_demo=False)
    existing = _get_tenant_row(conn, tenant_id, "saas_ai_plugins", plugin_id, "plugin")
    merged = {**existing, **{key: value for key, value in payload.items() if value is not None}}
    merged["plugin_key"] = existing.get("plugin_key")
    return create_plugin(conn, tenant_id, user_id, merged)


def list_tools(conn: Connection, tenant_id: str) -> list[dict[str, Any]]:
    seed_ecosystem_defaults(conn)
    return _list_table(
        conn,
        tenant_id,
        """
        SELECT id::text, tenant_id::text, tool_key, name, category, description, status, risk_level,
               runtime_type, handler_ref, input_schema_json, output_schema_json, permission_scopes_json,
               metadata_json, created_by_user_id::text, created_at::text, updated_at::text
        FROM saas_ai_tool_registry
        WHERE tenant_id IS NULL OR tenant_id = CAST(:tenant_id AS uuid)
        ORDER BY CASE WHEN tenant_id IS NULL THEN 0 ELSE 1 END, category, tool_key
        """,
    )


def create_tool(conn: Connection, tenant_id: str, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    _require_feature(conn, tenant_id, "ai_tool_registry", allow_demo=False)
    tool_key = _normalize_key(payload.get("tool_key"), 160)
    if not tool_key:
        raise HTTPException(status_code=400, detail="tool_key_required")
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_tool_registry (
                tenant_id, tool_key, name, category, description, status, risk_level, runtime_type,
                handler_ref, input_schema_json, output_schema_json, permission_scopes_json,
                metadata_json, created_by_user_id, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), :tool_key, :name, :category, :description, :status,
                :risk_level, :runtime_type, :handler_ref, CAST(:input_schema_json AS jsonb),
                CAST(:output_schema_json AS jsonb), CAST(:permission_scopes_json AS jsonb),
                CAST(:metadata_json AS jsonb), CAST(:user_id AS uuid), NOW()
            )
            ON CONFLICT (tenant_id, tool_key) WHERE tenant_id IS NOT NULL DO UPDATE SET
                name = EXCLUDED.name,
                category = EXCLUDED.category,
                description = EXCLUDED.description,
                status = EXCLUDED.status,
                risk_level = EXCLUDED.risk_level,
                runtime_type = EXCLUDED.runtime_type,
                handler_ref = EXCLUDED.handler_ref,
                input_schema_json = EXCLUDED.input_schema_json,
                output_schema_json = EXCLUDED.output_schema_json,
                permission_scopes_json = EXCLUDED.permission_scopes_json,
                metadata_json = EXCLUDED.metadata_json,
                updated_at = NOW()
            RETURNING id::text, tenant_id::text, tool_key, name, category, description, status,
                      risk_level, runtime_type, handler_ref, input_schema_json, output_schema_json,
                      permission_scopes_json, metadata_json, created_by_user_id::text,
                      created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "tool_key": tool_key,
            "name": _clean(payload.get("name"), 180),
            "category": _normalize_key(payload.get("category"), 80) or "ai",
            "description": _clean(payload.get("description"), 1000),
            "status": _clean(payload.get("status"), 40).lower() or "enabled",
            "risk_level": _clean(payload.get("risk_level"), 40).lower() or "medium",
            "runtime_type": _clean(payload.get("runtime_type"), 80).lower() or "manifest",
            "handler_ref": _clean(payload.get("handler_ref"), 240),
            "input_schema_json": _json(payload.get("input_schema_json") or {}),
            "output_schema_json": _json(payload.get("output_schema_json") or {}),
            "permission_scopes_json": _json(payload.get("permission_scopes_json") or []),
            "metadata_json": _json(payload.get("metadata_json") or {}),
            "user_id": user_id,
        },
    ).mappings().first()
    item = _row(dict(row or {}))
    _trace(conn, tenant_id, entity_type="tool", entity_id=item.get("id", ""), event_type="tool.upsert", output_json={"tool_key": tool_key})
    return item


def _get_tenant_row(conn: Connection, tenant_id: str, table: str, row_id: str, entity_name: str) -> dict[str, Any]:
    row = conn.execute(
        text(f"SELECT * FROM {table} WHERE tenant_id = CAST(:tenant_id AS uuid) AND id = CAST(:row_id AS uuid) LIMIT 1"),
        {"tenant_id": tenant_id, "row_id": row_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail=f"{entity_name}_not_found")
    return _row(dict(row))


def patch_tool(conn: Connection, tenant_id: str, tool_id: str, payload: dict[str, Any], user_id: str) -> dict[str, Any]:
    existing = _get_tenant_row(conn, tenant_id, "saas_ai_tool_registry", tool_id, "tool")
    merged = {**existing, **{key: value for key, value in payload.items() if value is not None}}
    merged["tool_key"] = existing.get("tool_key")
    return create_tool(conn, tenant_id, user_id, merged)


def list_event_subscriptions(conn: Connection, tenant_id: str) -> list[dict[str, Any]]:
    seed_ecosystem_defaults(conn)
    return _list_table(
        conn,
        tenant_id,
        """
        SELECT id::text, tenant_id::text, subscriber_type, subscriber_id, event_type, target_type,
               target_ref, status, priority, filters_json, retry_policy_json,
               created_by_user_id::text, created_at::text, updated_at::text
        FROM saas_ai_ecosystem_event_subscriptions
        WHERE tenant_id = CAST(:tenant_id AS uuid)
        ORDER BY status, priority DESC, event_type
        """,
    )


def create_event_subscription(conn: Connection, tenant_id: str, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    _require_feature(conn, tenant_id, "ai_plugin_center", allow_demo=False)
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_ecosystem_event_subscriptions (
                tenant_id, subscriber_type, subscriber_id, event_type, target_type, target_ref,
                status, priority, filters_json, retry_policy_json, created_by_user_id, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), :subscriber_type, :subscriber_id, :event_type,
                :target_type, :target_ref, :status, :priority, CAST(:filters_json AS jsonb),
                CAST(:retry_policy_json AS jsonb), CAST(:user_id AS uuid), NOW()
            )
            ON CONFLICT (tenant_id, subscriber_type, subscriber_id, event_type, target_ref)
            DO UPDATE SET
                target_type = EXCLUDED.target_type,
                status = EXCLUDED.status,
                priority = EXCLUDED.priority,
                filters_json = EXCLUDED.filters_json,
                retry_policy_json = EXCLUDED.retry_policy_json,
                updated_at = NOW()
            RETURNING id::text, tenant_id::text, subscriber_type, subscriber_id, event_type,
                      target_type, target_ref, status, priority, filters_json, retry_policy_json,
                      created_by_user_id::text, created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "subscriber_type": _normalize_key(payload.get("subscriber_type"), 80) or "plugin",
            "subscriber_id": _clean(payload.get("subscriber_id"), 160),
            "event_type": _clean(payload.get("event_type"), 160),
            "target_type": _normalize_key(payload.get("target_type"), 80) or "internal",
            "target_ref": _clean(payload.get("target_ref"), 240),
            "status": _clean(payload.get("status"), 40).lower() or "enabled",
            "priority": int(payload.get("priority") or 50),
            "filters_json": _json(payload.get("filters_json") or {}),
            "retry_policy_json": _json(payload.get("retry_policy_json") or {}),
            "user_id": user_id,
        },
    ).mappings().first()
    item = _row(dict(row or {}))
    _trace(conn, tenant_id, entity_type="event_subscription", entity_id=item.get("id", ""), event_type="subscription.upsert", output_json={"event_type": item.get("event_type")})
    return item


def patch_event_subscription(conn: Connection, tenant_id: str, subscription_id: str, payload: dict[str, Any], user_id: str) -> dict[str, Any]:
    existing = _get_tenant_row(conn, tenant_id, "saas_ai_ecosystem_event_subscriptions", subscription_id, "event_subscription")
    merged = {**existing, **{key: value for key, value in payload.items() if value is not None}}
    return create_event_subscription(conn, tenant_id, user_id, merged)


def _api_key() -> tuple[str, str, str]:
    raw = f"scentra_{secrets.token_urlsafe(32)}"
    hashed = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    hint = f"...{raw[-6:]}"
    return raw, hashed, hint


def list_developer_apps(conn: Connection, tenant_id: str) -> list[dict[str, Any]]:
    seed_ecosystem_defaults(conn)
    return _list_table(
        conn,
        tenant_id,
        """
        SELECT id::text, tenant_id::text, app_key, name, description, status, scopes_json,
               webhook_url, api_key_hint, created_by_user_id::text, last_used_at::text,
               created_at::text, updated_at::text
        FROM saas_ai_developer_apps
        WHERE tenant_id = CAST(:tenant_id AS uuid)
        ORDER BY updated_at DESC
        """,
    )


def create_developer_app(conn: Connection, tenant_id: str, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    _require_feature(conn, tenant_id, "ai_developer_console", allow_demo=False)
    app_key = _normalize_key(payload.get("app_key"))
    raw, hashed, hint = _api_key()
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_developer_apps (
                tenant_id, app_key, name, description, status, scopes_json, webhook_url,
                api_key_hash, api_key_hint, created_by_user_id, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), :app_key, :name, :description, :status,
                CAST(:scopes_json AS jsonb), :webhook_url, :api_key_hash, :api_key_hint,
                CAST(:user_id AS uuid), NOW()
            )
            ON CONFLICT (tenant_id, app_key) DO UPDATE SET
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                status = EXCLUDED.status,
                scopes_json = EXCLUDED.scopes_json,
                webhook_url = EXCLUDED.webhook_url,
                api_key_hash = EXCLUDED.api_key_hash,
                api_key_hint = EXCLUDED.api_key_hint,
                updated_at = NOW()
            RETURNING id::text, tenant_id::text, app_key, name, description, status, scopes_json,
                      webhook_url, api_key_hint, created_by_user_id::text, last_used_at::text,
                      created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "app_key": app_key,
            "name": _clean(payload.get("name"), 180),
            "description": _clean(payload.get("description"), 1000),
            "status": _clean(payload.get("status"), 40).lower() or "active",
            "scopes_json": _json(payload.get("scopes_json") or []),
            "webhook_url": _clean(payload.get("webhook_url"), 1000),
            "api_key_hash": hashed,
            "api_key_hint": hint,
            "user_id": user_id,
        },
    ).mappings().first()
    item = _row(dict(row or {}))
    item["api_key_once"] = raw
    _trace(conn, tenant_id, entity_type="developer_app", entity_id=item.get("id", ""), event_type="developer_app.create", output_json={"app_key": app_key})
    return item


def rotate_developer_app_key(conn: Connection, tenant_id: str, app_id: str) -> dict[str, Any]:
    _require_feature(conn, tenant_id, "ai_developer_console", allow_demo=False)
    raw, hashed, hint = _api_key()
    row = conn.execute(
        text(
            """
            UPDATE saas_ai_developer_apps
            SET api_key_hash = :api_key_hash,
                api_key_hint = :api_key_hint,
                updated_at = NOW()
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:app_id AS uuid)
            RETURNING id::text, tenant_id::text, app_key, name, description, status, scopes_json,
                      webhook_url, api_key_hint, created_by_user_id::text, last_used_at::text,
                      created_at::text, updated_at::text
            """
        ),
        {"tenant_id": tenant_id, "app_id": app_id, "api_key_hash": hashed, "api_key_hint": hint},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="developer_app_not_found")
    item = _row(dict(row))
    item["api_key_once"] = raw
    _trace(conn, tenant_id, entity_type="developer_app", entity_id=app_id, event_type="developer_app.rotate_key")
    return item


def patch_developer_app(conn: Connection, tenant_id: str, app_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    _require_feature(conn, tenant_id, "ai_developer_console", allow_demo=False)
    existing = _get_tenant_row(conn, tenant_id, "saas_ai_developer_apps", app_id, "developer_app")
    merged = {**existing, **{key: value for key, value in payload.items() if value is not None}}
    row = conn.execute(
        text(
            """
            UPDATE saas_ai_developer_apps
            SET name = :name,
                description = :description,
                status = :status,
                scopes_json = CAST(:scopes_json AS jsonb),
                webhook_url = :webhook_url,
                updated_at = NOW()
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:app_id AS uuid)
            RETURNING id::text, tenant_id::text, app_key, name, description, status, scopes_json,
                      webhook_url, api_key_hint, created_by_user_id::text, last_used_at::text,
                      created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "app_id": app_id,
            "name": _clean(merged.get("name"), 180),
            "description": _clean(merged.get("description"), 1000),
            "status": _clean(merged.get("status"), 40).lower() or "active",
            "scopes_json": _json(merged.get("scopes_json") or []),
            "webhook_url": _clean(merged.get("webhook_url"), 1000),
        },
    ).mappings().first()
    return _row(dict(row or {}))


def list_external_integrations(conn: Connection, tenant_id: str) -> list[dict[str, Any]]:
    seed_ecosystem_defaults(conn)
    return _list_table(
        conn,
        tenant_id,
        """
        SELECT id::text, tenant_id::text, integration_key, provider_type, provider_name, status,
               auth_mode, scopes_json, config_json, health_json, created_by_user_id::text,
               created_at::text, updated_at::text
        FROM saas_ai_external_integrations
        WHERE tenant_id = CAST(:tenant_id AS uuid)
        ORDER BY updated_at DESC
        """,
    )


def create_external_integration(conn: Connection, tenant_id: str, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    _require_feature(conn, tenant_id, "ai_developer_console", allow_demo=False)
    integration_key = _normalize_key(payload.get("integration_key"))
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_external_integrations (
                tenant_id, integration_key, provider_type, provider_name, status, auth_mode,
                scopes_json, config_json, created_by_user_id, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), :integration_key, :provider_type, :provider_name,
                :status, :auth_mode, CAST(:scopes_json AS jsonb), CAST(:config_json AS jsonb),
                CAST(:user_id AS uuid), NOW()
            )
            ON CONFLICT (tenant_id, integration_key) DO UPDATE SET
                provider_type = EXCLUDED.provider_type,
                provider_name = EXCLUDED.provider_name,
                status = EXCLUDED.status,
                auth_mode = EXCLUDED.auth_mode,
                scopes_json = EXCLUDED.scopes_json,
                config_json = EXCLUDED.config_json,
                updated_at = NOW()
            RETURNING id::text, tenant_id::text, integration_key, provider_type, provider_name,
                      status, auth_mode, scopes_json, config_json, health_json,
                      created_by_user_id::text, created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "integration_key": integration_key,
            "provider_type": _normalize_key(payload.get("provider_type"), 80) or "crm",
            "provider_name": _clean(payload.get("provider_name"), 160),
            "status": _clean(payload.get("status"), 40).lower() or "draft",
            "auth_mode": _normalize_key(payload.get("auth_mode"), 80) or "none",
            "scopes_json": _json(payload.get("scopes_json") or []),
            "config_json": _json(payload.get("config_json") or {}),
            "user_id": user_id,
        },
    ).mappings().first()
    item = _row(dict(row or {}))
    _trace(conn, tenant_id, entity_type="external_integration", entity_id=item.get("id", ""), event_type="external_integration.upsert")
    return item


def patch_external_integration(conn: Connection, tenant_id: str, integration_id: str, payload: dict[str, Any], user_id: str) -> dict[str, Any]:
    existing = _get_tenant_row(conn, tenant_id, "saas_ai_external_integrations", integration_id, "external_integration")
    merged = {**existing, **{key: value for key, value in payload.items() if value is not None}}
    merged["integration_key"] = existing.get("integration_key")
    return create_external_integration(conn, tenant_id, user_id, merged)


def list_ai_apps(conn: Connection, tenant_id: str) -> list[dict[str, Any]]:
    seed_ecosystem_defaults(conn)
    return _list_table(
        conn,
        tenant_id,
        """
        SELECT id::text, tenant_id::text, app_key, name, app_type, description, status,
               manifest_json, permissions_json, layout_json, created_by_user_id::text,
               created_at::text, updated_at::text
        FROM saas_ai_apps
        WHERE tenant_id = CAST(:tenant_id AS uuid)
        ORDER BY updated_at DESC
        """,
    )


def create_ai_app(conn: Connection, tenant_id: str, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    _require_feature(conn, tenant_id, "ai_app_framework", allow_demo=False)
    app_key = _normalize_key(payload.get("app_key"))
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_apps (
                tenant_id, app_key, name, app_type, description, status,
                manifest_json, permissions_json, layout_json, created_by_user_id, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), :app_key, :name, :app_type, :description,
                :status, CAST(:manifest_json AS jsonb), CAST(:permissions_json AS jsonb),
                CAST(:layout_json AS jsonb), CAST(:user_id AS uuid), NOW()
            )
            ON CONFLICT (tenant_id, app_key) DO UPDATE SET
                name = EXCLUDED.name,
                app_type = EXCLUDED.app_type,
                description = EXCLUDED.description,
                status = EXCLUDED.status,
                manifest_json = EXCLUDED.manifest_json,
                permissions_json = EXCLUDED.permissions_json,
                layout_json = EXCLUDED.layout_json,
                updated_at = NOW()
            RETURNING id::text, tenant_id::text, app_key, name, app_type, description, status,
                      manifest_json, permissions_json, layout_json, created_by_user_id::text,
                      created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "app_key": app_key,
            "name": _clean(payload.get("name"), 180),
            "app_type": _normalize_key(payload.get("app_type"), 80) or "dashboard",
            "description": _clean(payload.get("description"), 1000),
            "status": _clean(payload.get("status"), 40).lower() or "draft",
            "manifest_json": _json(payload.get("manifest_json") or {}),
            "permissions_json": _json(payload.get("permissions_json") or []),
            "layout_json": _json(payload.get("layout_json") or {}),
            "user_id": user_id,
        },
    ).mappings().first()
    item = _row(dict(row or {}))
    _trace(conn, tenant_id, entity_type="ai_app", entity_id=item.get("id", ""), event_type="ai_app.upsert")
    return item


def patch_ai_app(conn: Connection, tenant_id: str, app_id: str, payload: dict[str, Any], user_id: str) -> dict[str, Any]:
    existing = _get_tenant_row(conn, tenant_id, "saas_ai_apps", app_id, "ai_app")
    merged = {**existing, **{key: value for key, value in payload.items() if value is not None}}
    merged["app_key"] = existing.get("app_key")
    return create_ai_app(conn, tenant_id, user_id, merged)


def ecosystem_metrics(conn: Connection, tenant_id: str) -> dict[str, Any]:
    seed_ecosystem_defaults(conn)
    counts = conn.execute(
        text(
            """
            SELECT
              (SELECT COUNT(*)::int FROM saas_ai_marketplace_items WHERE status = 'published') AS marketplace_items,
              (SELECT COUNT(*)::int FROM saas_ai_marketplace_installations WHERE tenant_id = CAST(:tenant_id AS uuid)) AS installations,
              (SELECT COUNT(*)::int FROM saas_ai_plugins WHERE tenant_id = CAST(:tenant_id AS uuid)) AS plugins,
              (SELECT COUNT(*)::int FROM saas_ai_tool_registry WHERE tenant_id IS NULL OR tenant_id = CAST(:tenant_id AS uuid)) AS tools,
              (SELECT COUNT(*)::int FROM saas_ai_ecosystem_event_subscriptions WHERE tenant_id = CAST(:tenant_id AS uuid) AND status = 'enabled') AS active_subscriptions,
              (SELECT COUNT(*)::int FROM saas_ai_developer_apps WHERE tenant_id = CAST(:tenant_id AS uuid)) AS developer_apps,
              (SELECT COUNT(*)::int FROM saas_ai_external_integrations WHERE tenant_id = CAST(:tenant_id AS uuid)) AS external_integrations,
              (SELECT COUNT(*)::int FROM saas_ai_apps WHERE tenant_id = CAST(:tenant_id AS uuid)) AS ai_apps,
              (SELECT COUNT(*)::int FROM saas_ai_ecosystem_traces WHERE tenant_id = CAST(:tenant_id AS uuid) AND created_at >= NOW() - INTERVAL '7 days') AS traces_7d
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    latest_traces = _list_table(
        conn,
        tenant_id,
        """
        SELECT id::text, tenant_id::text, entity_type, entity_id, event_type, status,
               duration_ms, input_json, output_json, error_text, created_at::text
        FROM saas_ai_ecosystem_traces
        WHERE tenant_id = CAST(:tenant_id AS uuid)
        ORDER BY created_at DESC
        LIMIT 20
        """,
    )
    return {"counts": dict(counts or {}), "latest_traces": latest_traces}


def sdk_manifest(conn: Connection, tenant_id: str) -> dict[str, Any]:
    access = ecosystem_access(conn, tenant_id)
    return {
        "version": ECOSYSTEM_VERSION,
        "mode": "full" if access["full_available"] else "demo" if access["demo_available"] else "disabled",
        "features": {
            key: {"enabled": access["enabled"].get(key, False), "mode": access["modes"].get(key, "disabled")}
            for key in ECOSYSTEM_FEATURE_KEYS
        },
        "scopes": ECOSYSTEM_SCOPES,
        "event_types": ECOSYSTEM_EVENT_TYPES,
        "endpoints": {
            "marketplace": "/saas/v1/ecosystem/marketplace",
            "plugins": "/saas/v1/ecosystem/plugins",
            "tools": "/saas/v1/ecosystem/tools",
            "event_subscriptions": "/saas/v1/ecosystem/event-subscriptions",
            "developer_apps": "/saas/v1/ecosystem/developer/apps",
            "external_integrations": "/saas/v1/ecosystem/external-integrations",
            "ai_apps": "/saas/v1/ecosystem/ai-apps",
        },
        "sdk_contract": {
            "plugin_runtime": "metadata_only",
            "sandbox": "no_untrusted_code_execution_in_api",
            "secret_policy": "store_external_secrets_in_existing_encrypted_credentials_or_future_vault",
            "side_effect_policy": "approval_required_for_medium_high_risk_tools",
        },
    }


def ecosystem_overview(conn: Connection, tenant_id: str) -> dict[str, Any]:
    access = ecosystem_access(conn, tenant_id)
    metrics = ecosystem_metrics(conn, tenant_id)
    return {
        "version": ECOSYSTEM_VERSION,
        "access": {
            "demo_available": access["demo_available"],
            "full_available": access["full_available"],
            "features": {
                key: {"enabled": access["enabled"].get(key, False), "mode": access["modes"].get(key, "disabled")}
                for key in ECOSYSTEM_FEATURE_KEYS
            },
        },
        "metrics": metrics.get("counts", {}),
        "latest_traces": metrics.get("latest_traces", []),
        "governance": {
            "plugin_sandbox_mode": "metadata_only",
            "execution_policy": "control_plane_only",
            "approval_required_for": ["messaging", "crm_write", "campaign_launch", "external_webhooks"],
            "tenant_isolation": "tenant_id_filters_and_fk_cascade",
        },
        "sdk": sdk_manifest(conn, tenant_id),
        "installations": list_marketplace_installations(conn, tenant_id),
    }
