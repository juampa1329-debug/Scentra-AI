from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app_saas.ai_gateway.models import GatewayRequest, ProviderCallError, ProviderResult
from app_saas.ai_gateway.providers.http import estimate_tokens
from app_saas.ai_gateway.registry import PROVIDER_DEFINITIONS, provider_adapter, provider_definition
from app_saas.api_credentials.router import _ensure_api_credentials_table
from app_saas.shared.secrets import decrypt_secret


def _clean(value: Any, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def ensure_ai_gateway_tables(conn: Connection) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_providers (
                provider_code TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                credential_key TEXT NOT NULL DEFAULT '',
                default_model TEXT NOT NULL DEFAULT '',
                capabilities_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_models (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                provider_code TEXT NOT NULL REFERENCES saas_ai_providers(provider_code) ON DELETE CASCADE,
                model_id TEXT NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                capabilities_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                context_window INTEGER NOT NULL DEFAULT 0,
                cost_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (provider_code, model_id)
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_routes (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                route_code TEXT NOT NULL,
                task_type TEXT NOT NULL,
                primary_provider TEXT NOT NULL DEFAULT '',
                primary_model TEXT NOT NULL DEFAULT '',
                fallback_provider TEXT NOT NULL DEFAULT '',
                fallback_model TEXT NOT NULL DEFAULT '',
                policy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, route_code)
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_runs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                conversation_id UUID NULL,
                agent_type TEXT NOT NULL DEFAULT '',
                task_type TEXT NOT NULL DEFAULT '',
                route_code TEXT NOT NULL DEFAULT '',
                provider_code TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                credential_key TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'started',
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                latency_ms INTEGER NOT NULL DEFAULT 0,
                fallback_used BOOLEAN NOT NULL DEFAULT FALSE,
                error_code TEXT NOT NULL DEFAULT '',
                error_message TEXT NOT NULL DEFAULT '',
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_saas_ai_runs_tenant_created
            ON saas_ai_runs (tenant_id, created_at DESC)
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_tool_calls (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                ai_run_id UUID NULL REFERENCES saas_ai_runs(id) ON DELETE SET NULL,
                tool_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                input_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                output_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                requires_approval BOOLEAN NOT NULL DEFAULT FALSE,
                approved_by UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                error TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_recommendations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                ai_run_id UUID NULL REFERENCES saas_ai_runs(id) ON DELETE SET NULL,
                recommendation_type TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'info',
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                action_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                confidence NUMERIC(5,2) NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    _seed_provider_catalog(conn)


def _seed_provider_catalog(conn: Connection) -> None:
    for definition in PROVIDER_DEFINITIONS.values():
        conn.execute(
            text(
                """
                INSERT INTO saas_ai_providers (
                    provider_code, display_name, credential_key, default_model,
                    capabilities_json, metadata_json, is_active, updated_at
                )
                VALUES (
                    :provider_code, :display_name, :credential_key, :default_model,
                    CAST(:capabilities_json AS jsonb), CAST(:metadata_json AS jsonb), TRUE, NOW()
                )
                ON CONFLICT (provider_code)
                DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    credential_key = EXCLUDED.credential_key,
                    default_model = EXCLUDED.default_model,
                    capabilities_json = EXCLUDED.capabilities_json,
                    metadata_json = saas_ai_providers.metadata_json || EXCLUDED.metadata_json,
                    updated_at = NOW()
                """
            ),
            {
                "provider_code": definition.code,
                "display_name": definition.display_name,
                "credential_key": definition.credential_key,
                "default_model": definition.default_model,
                "capabilities_json": _json(list(definition.capabilities)),
                "metadata_json": _json(definition.metadata),
            },
        )
        for model_id in definition.static_models:
            conn.execute(
                text(
                    """
                    INSERT INTO saas_ai_models (
                        provider_code, model_id, display_name, capabilities_json, metadata_json, updated_at
                    )
                    VALUES (
                        :provider_code, :model_id, :display_name,
                        CAST(:capabilities_json AS jsonb), CAST(:metadata_json AS jsonb), NOW()
                    )
                    ON CONFLICT (provider_code, model_id)
                    DO UPDATE SET
                        display_name = EXCLUDED.display_name,
                        capabilities_json = EXCLUDED.capabilities_json,
                        metadata_json = saas_ai_models.metadata_json || EXCLUDED.metadata_json,
                        updated_at = NOW()
                    """
                ),
                {
                    "provider_code": definition.code,
                    "model_id": model_id,
                    "display_name": model_id,
                    "capabilities_json": _json(list(definition.capabilities)),
                    "metadata_json": _json({"static": True}),
                },
            )


def _metadata(row_value: Any) -> dict[str, Any]:
    if isinstance(row_value, dict):
        return row_value
    if isinstance(row_value, str) and row_value.strip():
        try:
            parsed = json.loads(row_value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _load_gateway_credential(conn: Connection, tenant_id: str, provider_code: str) -> tuple[str, str, str]:
    definition = provider_definition(provider_code)
    if not definition:
        return "", "", ""
    _ensure_api_credentials_table(conn)
    row = conn.execute(
        text(
            """
            SELECT credential_key, secret_value, metadata_json
            FROM saas_api_credentials
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND provider_code = :provider_code
              AND category = 'ai'
            ORDER BY
              CASE WHEN credential_key = :credential_key THEN 0 ELSE 1 END,
              updated_at DESC
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "provider_code": definition.code, "credential_key": definition.credential_key},
    ).mappings().first()
    if not row:
        return "", definition.default_model, definition.credential_key
    metadata = _metadata(row.get("metadata_json"))
    selected_model = _clean(metadata.get("selected_model") or definition.default_model, 240)
    return decrypt_secret(str(row.get("secret_value") or "")), selected_model, str(row.get("credential_key") or definition.credential_key)


def _record_run(
    conn: Connection,
    request: GatewayRequest,
    provider_code: str,
    model: str,
    credential_key: str,
    status: str,
    *,
    fallback_used: bool,
    result: ProviderResult | None = None,
    error_code: str = "",
    error_message: str = "",
    metadata: dict[str, Any] | None = None,
) -> str:
    input_tokens = int((result.input_tokens if result else 0) or estimate_tokens(request.system_prompt, request.user_prompt))
    output_tokens = int((result.output_tokens if result else 0) or 0)
    request_metadata = _metadata((request.settings or {}).get("metadata_json"))
    run_metadata = {**request_metadata, **(result.metadata if result else {}), **(metadata or {})}
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_runs (
                tenant_id, conversation_id, agent_type, task_type, route_code,
                provider_code, model, credential_key, status, input_tokens,
                output_tokens, total_tokens, latency_ms, fallback_used,
                error_code, error_message, metadata_json
            )
            VALUES (
                CAST(:tenant_id AS uuid), CAST(NULLIF(:conversation_id, '') AS uuid),
                :agent_type, :task_type, :route_code, :provider_code, :model,
                :credential_key, :status, :input_tokens, :output_tokens,
                :total_tokens, :latency_ms, :fallback_used, :error_code,
                :error_message, CAST(:metadata_json AS jsonb)
            )
            RETURNING id::text
            """
        ),
        {
            "tenant_id": request.tenant_id,
            "conversation_id": request.conversation_id,
            "agent_type": request.agent_type,
            "task_type": request.task_type,
            "route_code": request.route_code,
            "provider_code": provider_code,
            "model": model,
            "credential_key": credential_key,
            "status": status,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "latency_ms": int((result.latency_ms if result else 0) or 0),
            "fallback_used": bool(fallback_used),
            "error_code": _clean(error_code, 120),
            "error_message": _clean(error_message, 1200),
            "metadata_json": _json(run_metadata),
        },
    ).mappings().first()
    return str(row["id"] if row else "")


def generate_with_gateway(
    conn: Connection,
    *,
    tenant_id: str,
    task_type: str,
    system_prompt: str,
    user_prompt: str,
    provider_chain: list[str],
    settings: dict[str, Any],
    agent_type: str = "sales_agent",
    route_code: str = "conversation.sales",
    conversation_id: str = "",
) -> dict[str, Any]:
    ensure_ai_gateway_tables(conn)
    request = GatewayRequest(
        tenant_id=tenant_id,
        task_type=task_type,
        agent_type=agent_type,
        route_code=route_code,
        conversation_id=conversation_id,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        settings=settings,
    )
    seen: set[str] = set()
    providers = []
    for provider in provider_chain:
        clean_provider = _clean(provider, 80).lower()
        if clean_provider and clean_provider not in seen:
            seen.add(clean_provider)
            providers.append(clean_provider)

    last_error = ""
    for index, provider_code in enumerate(providers):
        definition = provider_definition(provider_code)
        if not definition:
            last_error = f"unsupported_ai_provider:{provider_code}"
            continue
        token, model, credential_key = _load_gateway_credential(conn, tenant_id, provider_code)
        fallback_used = index > 0
        if not token:
            last_error = f"missing_ai_credential:{provider_code}:{credential_key}"
            _record_run(
                conn,
                request,
                provider_code,
                model,
                credential_key,
                "skipped",
                fallback_used=fallback_used,
                error_code="missing_credential",
                error_message=last_error,
            )
            continue
        try:
            result = provider_adapter(provider_code).generate(request, token, model)
            run_id = _record_run(
                conn,
                request,
                provider_code,
                result.model,
                credential_key,
                "success",
                fallback_used=fallback_used,
                result=result,
            )
            return {
                "ok": True,
                "raw": result.raw,
                "provider_code": result.provider_code,
                "model": result.model,
                "run_id": run_id,
                "fallback_used": fallback_used,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "estimated_tokens": result.input_tokens + result.output_tokens,
                "latency_ms": result.latency_ms,
            }
        except ProviderCallError as exc:
            last_error = f"{provider_code}:{exc.code}:{str(exc)[:500]}"
            _record_run(
                conn,
                request,
                provider_code,
                model,
                credential_key,
                "failed",
                fallback_used=fallback_used,
                error_code=exc.code,
                error_message=str(exc),
                metadata={"retryable": exc.retryable, "http_status": exc.http_status},
            )
        except Exception as exc:
            last_error = f"{provider_code}:gateway_error:{str(exc)[:500]}"
            _record_run(
                conn,
                request,
                provider_code,
                model,
                credential_key,
                "failed",
                fallback_used=fallback_used,
                error_code="gateway_error",
                error_message=str(exc),
            )
    return {"ok": False, "skipped": last_error or "ai_gateway_unavailable"}


def provider_catalog(conn: Connection) -> list[dict[str, Any]]:
    ensure_ai_gateway_tables(conn)
    rows = conn.execute(
        text(
            """
            SELECT provider_code, display_name, credential_key, default_model,
                   capabilities_json, metadata_json, is_active, updated_at::text
            FROM saas_ai_providers
            ORDER BY provider_code ASC
            """
        )
    ).mappings().all()
    return [dict(row) for row in rows]


def recent_runs(conn: Connection, tenant_id: str, limit: int = 50) -> list[dict[str, Any]]:
    ensure_ai_gateway_tables(conn)
    rows = conn.execute(
        text(
            """
            SELECT id::text, COALESCE(conversation_id::text, '') AS conversation_id,
                   agent_type, task_type, route_code, provider_code, model, status,
                   input_tokens, output_tokens, total_tokens, latency_ms, fallback_used,
                   error_code, error_message, metadata_json, created_at::text
            FROM saas_ai_runs
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "limit": max(1, min(int(limit or 50), 200))},
    ).mappings().all()
    return [dict(row) for row in rows]


def route_catalog(conn: Connection, tenant_id: str) -> list[dict[str, Any]]:
    ensure_ai_gateway_tables(conn)
    rows = conn.execute(
        text(
            """
            SELECT id::text, COALESCE(tenant_id::text, '') AS tenant_id, route_code, task_type,
                   primary_provider, primary_model, fallback_provider, fallback_model,
                   policy_json, is_active, updated_at::text
            FROM saas_ai_routes
            WHERE tenant_id IS NULL OR tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY tenant_id NULLS FIRST, route_code ASC
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().all()
    return [dict(row) for row in rows]
