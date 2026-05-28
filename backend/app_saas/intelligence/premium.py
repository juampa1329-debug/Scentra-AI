from __future__ import annotations

from decimal import Decimal
import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app_saas.intelligence.catalog import INTELLIGENCE_FEATURE_MAP

VALID_SCOPE_TYPES = {"global", "plan", "tenant"}
VALID_PROVIDER_CATEGORIES = {"ai", "search", "tts"}
VALID_MODES = {"disabled", "demo", "full"}
PHASE24_FEATURE_KEYS = (
    "voice_intelligence",
    "voice_transcription",
    "voice_sentiment_intent",
    "vision_intelligence",
    "image_understanding",
    "document_ocr",
    "web_search_intelligence",
    "image_search_intelligence",
    "external_source_assist",
    "agent_multimodal_tools",
    "agent_voice_tools",
    "agent_vision_tools",
    "agent_external_search_tools",
    "multimodal_memory_events",
    "multimodal_training_events",
    "multimodal_rag_materialization",
    "multimodal_agent_memory",
    "multimodal_observability",
    "multimodal_cost_observability",
    "multimodal_quality_monitoring",
    "multimodal_safe_rollout",
    "multimodal_canary",
)


def _clean(value: Any, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def _num(value: Any) -> float:
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _mode(value: Any, *, enabled: bool) -> str:
    if not enabled:
        return "disabled"
    mode = _clean(value, 40).lower().replace("-", "_")
    return mode if mode in VALID_MODES else "demo"


def _table_exists(conn: Connection, table_name: str) -> bool:
    return bool(conn.execute(text("SELECT to_regclass(:table_name)"), {"table_name": table_name}).scalar())


def ensure_premium_gating_tables(conn: Connection) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_intelligence_plan_feature_limits (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                plan_code TEXT NOT NULL REFERENCES saas_plan_limits(plan_code) ON DELETE CASCADE,
                feature_key TEXT NOT NULL,
                enabled BOOLEAN NOT NULL DEFAULT FALSE,
                mode TEXT NOT NULL DEFAULT 'disabled',
                quota_monthly INTEGER NOT NULL DEFAULT 0,
                notes TEXT NOT NULL DEFAULT '',
                updated_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (plan_code, feature_key)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_intelligence_plan_feature_limits_plan ON saas_intelligence_plan_feature_limits (plan_code, feature_key)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_provider_policies (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                scope_type TEXT NOT NULL DEFAULT 'global',
                scope_id TEXT NOT NULL DEFAULT '',
                provider_category TEXT NOT NULL DEFAULT 'ai',
                provider_code TEXT NOT NULL,
                model_id TEXT NOT NULL DEFAULT '',
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                input_cost_cents_per_1k NUMERIC(18,6) NOT NULL DEFAULT 0,
                output_cost_cents_per_1k NUMERIC(18,6) NOT NULL DEFAULT 0,
                request_cost_cents NUMERIC(18,6) NOT NULL DEFAULT 0,
                monthly_request_quota INTEGER NOT NULL DEFAULT 0,
                monthly_cost_limit_cents INTEGER NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'USD',
                notes TEXT NOT NULL DEFAULT '',
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                updated_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (scope_type, scope_id, provider_category, provider_code, model_id)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_provider_policies_lookup ON saas_ai_provider_policies (provider_category, provider_code, model_id, scope_type, scope_id)"))


def plan_feature_limits(conn: Connection, plan_code: str = "") -> dict[str, dict[str, Any]]:
    ensure_premium_gating_tables(conn)
    params = {"plan_code": _clean(plan_code, 80).lower().replace("-", "_")}
    where = "WHERE plan_code = :plan_code" if params["plan_code"] else ""
    rows = conn.execute(
        text(
            f"""
            SELECT id::text, plan_code, feature_key, enabled, mode, quota_monthly,
                   notes, updated_at::text
            FROM saas_intelligence_plan_feature_limits
            {where}
            ORDER BY plan_code ASC, feature_key ASC
            """
        ),
        params,
    ).mappings().all()
    return {f"{row['plan_code']}:{row['feature_key']}": dict(row) for row in rows}


def plan_feature_limits_for_plan(conn: Connection, plan_code: str) -> dict[str, dict[str, Any]]:
    rows = plan_feature_limits(conn, plan_code)
    return {str(row["feature_key"]): row for row in rows.values()}


def upsert_plan_feature_limit(conn: Connection, plan_code: str, payload: Any, *, actor_user_id: str) -> dict[str, Any]:
    ensure_premium_gating_tables(conn)
    clean_plan = _clean(plan_code, 80).lower().replace("-", "_")
    if not clean_plan:
        raise HTTPException(status_code=400, detail="plan_code_required")
    if not conn.execute(text("SELECT 1 FROM saas_plan_limits WHERE plan_code = :plan_code"), {"plan_code": clean_plan}).first():
        raise HTTPException(status_code=404, detail="plan_not_found")
    data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload or {})
    feature_key = _clean(data.get("feature_key"), 120).lower().replace("-", "_")
    if feature_key not in INTELLIGENCE_FEATURE_MAP:
        raise HTTPException(status_code=400, detail={"code": "unknown_intelligence_feature", "feature": feature_key})
    mode = _mode(data.get("mode"), enabled=bool(data.get("enabled", True)))
    row = conn.execute(
        text(
            """
            INSERT INTO saas_intelligence_plan_feature_limits (
                plan_code, feature_key, enabled, mode, quota_monthly,
                notes, updated_by_user_id, updated_at
            )
            VALUES (
                :plan_code, :feature_key, :enabled, :mode, :quota_monthly,
                :notes, CAST(:actor_user_id AS uuid), NOW()
            )
            ON CONFLICT (plan_code, feature_key)
            DO UPDATE SET
                enabled = EXCLUDED.enabled,
                mode = EXCLUDED.mode,
                quota_monthly = EXCLUDED.quota_monthly,
                notes = EXCLUDED.notes,
                updated_by_user_id = EXCLUDED.updated_by_user_id,
                updated_at = NOW()
            RETURNING id::text, plan_code, feature_key, enabled, mode, quota_monthly,
                      notes, updated_at::text
            """
        ),
        {
            "plan_code": clean_plan,
            "feature_key": feature_key,
            "enabled": mode != "disabled",
            "mode": mode,
            "quota_monthly": max(0, int(data.get("quota_monthly") or 0)),
            "notes": _clean(data.get("notes"), 1000),
            "actor_user_id": actor_user_id,
        },
    ).mappings().first()
    return dict(row or {})


def _tenant_plan_code(conn: Connection, tenant_id: str) -> str:
    row = conn.execute(
        text("SELECT plan_code FROM saas_tenants WHERE id = CAST(:tenant_id AS uuid) LIMIT 1"),
        {"tenant_id": tenant_id},
    ).mappings().first()
    return _clean((row or {}).get("plan_code"), 80).lower().replace("-", "_")


def _validate_provider_scope(conn: Connection, scope_type: str, scope_id: str) -> None:
    if scope_type == "global":
        return
    if scope_type == "plan":
        if not scope_id:
            raise HTTPException(status_code=400, detail="provider_policy_plan_scope_required")
        if not conn.execute(text("SELECT 1 FROM saas_plan_limits WHERE plan_code = :plan_code"), {"plan_code": scope_id}).first():
            raise HTTPException(status_code=404, detail="provider_policy_plan_not_found")
        return
    if scope_type == "tenant":
        if not scope_id:
            raise HTTPException(status_code=400, detail="provider_policy_tenant_scope_required")
        if not conn.execute(text("SELECT 1 FROM saas_tenants WHERE id = CAST(:tenant_id AS uuid)"), {"tenant_id": scope_id}).first():
            raise HTTPException(status_code=404, detail="provider_policy_tenant_not_found")
        return
    raise HTTPException(status_code=400, detail={"code": "invalid_provider_policy_scope", "allowed": sorted(VALID_SCOPE_TYPES)})


def upsert_provider_policy(conn: Connection, payload: Any, *, actor_user_id: str) -> dict[str, Any]:
    ensure_premium_gating_tables(conn)
    data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload or {})
    scope_type = _clean(data.get("scope_type") or "global", 40).lower().replace("-", "_")
    scope_id = _clean(data.get("scope_id"), 120)
    provider_category = _clean(data.get("provider_category") or "ai", 40).lower().replace("-", "_")
    provider_code = _clean(data.get("provider_code"), 80).lower().replace("-", "_")
    model_id = _clean(data.get("model_id"), 240)
    if scope_type not in VALID_SCOPE_TYPES:
        raise HTTPException(status_code=400, detail={"code": "invalid_provider_policy_scope", "allowed": sorted(VALID_SCOPE_TYPES)})
    if scope_type == "global":
        scope_id = ""
    if scope_type == "plan":
        scope_id = scope_id.lower().replace("-", "_")
    if provider_category not in VALID_PROVIDER_CATEGORIES:
        raise HTTPException(status_code=400, detail={"code": "invalid_provider_category", "allowed": sorted(VALID_PROVIDER_CATEGORIES)})
    if not provider_code:
        raise HTTPException(status_code=400, detail="provider_code_required")
    _validate_provider_scope(conn, scope_type, scope_id)
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_provider_policies (
                scope_type, scope_id, provider_category, provider_code, model_id,
                enabled, input_cost_cents_per_1k, output_cost_cents_per_1k,
                request_cost_cents, monthly_request_quota, monthly_cost_limit_cents,
                currency, notes, metadata_json, updated_by_user_id, updated_at
            )
            VALUES (
                :scope_type, :scope_id, :provider_category, :provider_code, :model_id,
                :enabled, :input_cost_cents_per_1k, :output_cost_cents_per_1k,
                :request_cost_cents, :monthly_request_quota, :monthly_cost_limit_cents,
                :currency, :notes, CAST(:metadata_json AS jsonb), CAST(:actor_user_id AS uuid), NOW()
            )
            ON CONFLICT (scope_type, scope_id, provider_category, provider_code, model_id)
            DO UPDATE SET
                enabled = EXCLUDED.enabled,
                input_cost_cents_per_1k = EXCLUDED.input_cost_cents_per_1k,
                output_cost_cents_per_1k = EXCLUDED.output_cost_cents_per_1k,
                request_cost_cents = EXCLUDED.request_cost_cents,
                monthly_request_quota = EXCLUDED.monthly_request_quota,
                monthly_cost_limit_cents = EXCLUDED.monthly_cost_limit_cents,
                currency = EXCLUDED.currency,
                notes = EXCLUDED.notes,
                metadata_json = EXCLUDED.metadata_json,
                updated_by_user_id = EXCLUDED.updated_by_user_id,
                updated_at = NOW()
            RETURNING id::text, scope_type, scope_id, provider_category, provider_code,
                      model_id, enabled, input_cost_cents_per_1k, output_cost_cents_per_1k,
                      request_cost_cents, monthly_request_quota, monthly_cost_limit_cents,
                      currency, notes, metadata_json, updated_at::text
            """
        ),
        {
            "scope_type": scope_type,
            "scope_id": scope_id,
            "provider_category": provider_category,
            "provider_code": provider_code,
            "model_id": model_id,
            "enabled": bool(data.get("enabled", True)),
            "input_cost_cents_per_1k": max(0.0, _num(data.get("input_cost_cents_per_1k"))),
            "output_cost_cents_per_1k": max(0.0, _num(data.get("output_cost_cents_per_1k"))),
            "request_cost_cents": max(0.0, _num(data.get("request_cost_cents"))),
            "monthly_request_quota": max(0, int(data.get("monthly_request_quota") or 0)),
            "monthly_cost_limit_cents": max(0, int(data.get("monthly_cost_limit_cents") or 0)),
            "currency": _clean(data.get("currency") or "USD", 12).upper() or "USD",
            "notes": _clean(data.get("notes"), 1000),
            "metadata_json": _json(data.get("metadata_json") if isinstance(data.get("metadata_json"), dict) else {"source": "admin"}),
            "actor_user_id": actor_user_id,
        },
    ).mappings().first()
    return _policy_row(dict(row or {}))


def _policy_row(row: dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    for key in ("input_cost_cents_per_1k", "output_cost_cents_per_1k", "request_cost_cents"):
        data[key] = _num(data.get(key))
    data["monthly_request_quota"] = int(data.get("monthly_request_quota") or 0)
    data["monthly_cost_limit_cents"] = int(data.get("monthly_cost_limit_cents") or 0)
    return data


def provider_policy_for(
    conn: Connection,
    tenant_id: str,
    provider_category: str,
    provider_code: str,
    model_id: str = "",
) -> dict[str, Any]:
    ensure_premium_gating_tables(conn)
    clean_category = _clean(provider_category, 40).lower().replace("-", "_")
    clean_provider = _clean(provider_code, 80).lower().replace("-", "_")
    clean_model = _clean(model_id, 240)
    plan_code = _tenant_plan_code(conn, tenant_id)
    candidates = [
        ("tenant", tenant_id, clean_model),
        ("tenant", tenant_id, ""),
        ("plan", plan_code, clean_model),
        ("plan", plan_code, ""),
        ("global", "", clean_model),
        ("global", "", ""),
    ]
    for scope_type, scope_id, candidate_model in candidates:
        if scope_type == "plan" and not scope_id:
            continue
        row = conn.execute(
            text(
                """
                SELECT id::text, scope_type, scope_id, provider_category, provider_code,
                       model_id, enabled, input_cost_cents_per_1k, output_cost_cents_per_1k,
                       request_cost_cents, monthly_request_quota, monthly_cost_limit_cents,
                       currency, notes, metadata_json, updated_at::text
                FROM saas_ai_provider_policies
                WHERE scope_type = :scope_type
                  AND scope_id = :scope_id
                  AND provider_category = :provider_category
                  AND provider_code = :provider_code
                  AND model_id = :model_id
                LIMIT 1
                """
            ),
            {
                "scope_type": scope_type,
                "scope_id": scope_id,
                "provider_category": clean_category,
                "provider_code": clean_provider,
                "model_id": candidate_model,
            },
        ).mappings().first()
        if row:
            data = _policy_row(dict(row))
            data["resolved_scope"] = f"{scope_type}:{scope_id or '*'}"
            return data
    return {
        "id": "",
        "scope_type": "default",
        "scope_id": "",
        "provider_category": clean_category,
        "provider_code": clean_provider,
        "model_id": clean_model,
        "enabled": True,
        "input_cost_cents_per_1k": 0.0,
        "output_cost_cents_per_1k": 0.0,
        "request_cost_cents": 0.0,
        "monthly_request_quota": 0,
        "monthly_cost_limit_cents": 0,
        "currency": "USD",
        "notes": "Default compatibility allow; no explicit policy configured.",
        "metadata_json": {},
        "updated_at": "",
        "resolved_scope": "default",
    }


def _estimate_policy_cost_cents(policy: dict[str, Any], *, requests: int, input_tokens: int = 0, output_tokens: int = 0) -> float:
    return (
        (_num(input_tokens) / 1000.0) * _num(policy.get("input_cost_cents_per_1k"))
        + (_num(output_tokens) / 1000.0) * _num(policy.get("output_cost_cents_per_1k"))
        + _num(requests) * _num(policy.get("request_cost_cents"))
    )


def _provider_monthly_usage(
    conn: Connection,
    *,
    tenant_id: str,
    provider_category: str,
    provider_code: str,
    model_id: str,
    policy: dict[str, Any],
) -> dict[str, Any]:
    if provider_category == "ai" and _table_exists(conn, "saas_ai_runs"):
        model_filter = "AND r.model = :model_id" if model_id else ""
        row = conn.execute(
            text(
                f"""
                SELECT COUNT(*) FILTER (WHERE r.status <> 'skipped')::int AS requests,
                       COALESCE(SUM(r.input_tokens) FILTER (WHERE r.status <> 'skipped'), 0)::int AS input_tokens,
                       COALESCE(SUM(r.output_tokens) FILTER (WHERE r.status <> 'skipped'), 0)::int AS output_tokens
                FROM saas_ai_runs r
                WHERE r.tenant_id = CAST(:tenant_id AS uuid)
                  AND r.provider_code = :provider_code
                  {model_filter}
                  AND r.created_at >= date_trunc('month', NOW())
                """
            ),
            {
                "tenant_id": tenant_id,
                "provider_code": provider_code,
                "model_id": model_id,
            },
        ).mappings().first() or {}
        requests = int(row.get("requests") or 0)
        input_tokens = int(row.get("input_tokens") or 0)
        output_tokens = int(row.get("output_tokens") or 0)
        return {
            "requests": requests,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost_cents": round(
                _estimate_policy_cost_cents(
                    policy,
                    requests=requests,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                ),
                6,
            ),
        }
    if provider_category == "search" and _table_exists(conn, "saas_web_search_intelligence_runs"):
        row = conn.execute(
            text(
                """
                SELECT COUNT(*)::int AS requests
                FROM saas_web_search_intelligence_runs r
                WHERE r.tenant_id = CAST(:tenant_id AS uuid)
                  AND r.provider_code = :provider_code
                  AND r.created_at >= date_trunc('month', NOW())
                """
            ),
            {"tenant_id": tenant_id, "provider_code": provider_code},
        ).mappings().first() or {}
        requests = int(row.get("requests") or 0)
        return {
            "requests": requests,
            "input_tokens": 0,
            "output_tokens": 0,
            "estimated_cost_cents": round(_estimate_policy_cost_cents(policy, requests=requests), 6),
        }
    return {"requests": 0, "input_tokens": 0, "output_tokens": 0, "estimated_cost_cents": 0.0}


def assert_provider_enabled(conn: Connection, tenant_id: str, provider_category: str, provider_code: str, model_id: str = "") -> dict[str, Any]:
    policy = provider_policy_for(conn, tenant_id, provider_category, provider_code, model_id)
    if not bool(policy.get("enabled", True)):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "ai_provider_disabled_by_admin",
                "provider_category": provider_category,
                "provider_code": provider_code,
                "model_id": model_id,
                "scope": policy.get("resolved_scope") or policy.get("scope_type"),
            },
        )
    usage = _provider_monthly_usage(
        conn,
        tenant_id=tenant_id,
        provider_category=_clean(provider_category, 40).lower().replace("-", "_"),
        provider_code=_clean(provider_code, 80).lower().replace("-", "_"),
        model_id=_clean(model_id, 240),
        policy=policy,
    )
    policy["monthly_usage"] = usage
    quota = int(policy.get("monthly_request_quota") or 0)
    if quota > 0 and int(usage.get("requests") or 0) >= quota:
        raise HTTPException(
            status_code=402,
            detail={
                "code": "ai_provider_request_quota_exceeded",
                "provider_category": provider_category,
                "provider_code": provider_code,
                "model_id": model_id,
                "scope": policy.get("resolved_scope") or policy.get("scope_type"),
                "used": int(usage.get("requests") or 0),
                "limit": quota,
            },
        )
    cost_limit = int(policy.get("monthly_cost_limit_cents") or 0)
    if cost_limit > 0 and _num(usage.get("estimated_cost_cents")) >= cost_limit:
        raise HTTPException(
            status_code=402,
            detail={
                "code": "ai_provider_cost_limit_exceeded",
                "provider_category": provider_category,
                "provider_code": provider_code,
                "model_id": model_id,
                "scope": policy.get("resolved_scope") or policy.get("scope_type"),
                "used_cents": round(_num(usage.get("estimated_cost_cents")), 6),
                "limit_cents": cost_limit,
            },
        )
    return policy


def list_provider_policies(conn: Connection) -> list[dict[str, Any]]:
    ensure_premium_gating_tables(conn)
    rows = conn.execute(
        text(
            """
            SELECT id::text, scope_type, scope_id, provider_category, provider_code,
                   model_id, enabled, input_cost_cents_per_1k, output_cost_cents_per_1k,
                   request_cost_cents, monthly_request_quota, monthly_cost_limit_cents,
                   currency, notes, metadata_json, updated_at::text
            FROM saas_ai_provider_policies
            ORDER BY provider_category ASC, provider_code ASC, scope_type ASC,
                     scope_id ASC, model_id ASC
            """
        )
    ).mappings().all()
    return [_policy_row(dict(row)) for row in rows]


def provider_credential_summary(conn: Connection) -> list[dict[str, Any]]:
    if not _table_exists(conn, "saas_api_credentials"):
        return []
    rows = conn.execute(
        text(
            """
            SELECT c.tenant_id::text, t.name AS tenant_name, t.slug AS tenant_slug,
                   t.plan_code, c.category, c.provider_code,
                   COUNT(*)::int AS credentials,
                   COUNT(*) FILTER (WHERE c.secret_value <> '')::int AS secrets_ready,
                   MAX(c.updated_at)::text AS last_updated_at
            FROM saas_api_credentials c
            JOIN saas_tenants t ON t.id = c.tenant_id
            WHERE c.category IN ('ai', 'search', 'tts')
            GROUP BY c.tenant_id, t.name, t.slug, t.plan_code, c.category, c.provider_code
            ORDER BY MAX(c.updated_at) DESC NULLS LAST, c.category ASC, c.provider_code ASC
            LIMIT 500
            """
        )
    ).mappings().all()
    return [dict(row) for row in rows]


def provider_cost_summary(conn: Connection) -> dict[str, Any]:
    ensure_premium_gating_tables(conn)
    ai_rows = []
    if _table_exists(conn, "saas_ai_runs"):
        rows = conn.execute(
            text(
                """
                SELECT r.tenant_id::text, t.name AS tenant_name, t.slug AS tenant_slug,
                       t.plan_code, r.provider_code, r.model,
                       COUNT(*)::int AS requests,
                       COUNT(*) FILTER (WHERE r.status = 'success')::int AS successful_requests,
                       COALESCE(SUM(r.input_tokens), 0)::int AS input_tokens,
                       COALESCE(SUM(r.output_tokens), 0)::int AS output_tokens,
                       COALESCE(SUM(r.total_tokens), 0)::int AS total_tokens
                FROM saas_ai_runs r
                JOIN saas_tenants t ON t.id = r.tenant_id
                WHERE r.created_at >= date_trunc('month', NOW())
                GROUP BY r.tenant_id, t.name, t.slug, t.plan_code, r.provider_code, r.model
                ORDER BY total_tokens DESC, requests DESC
                LIMIT 500
                """
            )
        ).mappings().all()
        for row in rows:
            item = dict(row)
            policy = provider_policy_for(conn, item["tenant_id"], "ai", item["provider_code"], item.get("model") or "")
            estimated = (
                (_num(item.get("input_tokens")) / 1000.0) * _num(policy.get("input_cost_cents_per_1k"))
                + (_num(item.get("output_tokens")) / 1000.0) * _num(policy.get("output_cost_cents_per_1k"))
                + _num(item.get("requests")) * _num(policy.get("request_cost_cents"))
            )
            item["policy"] = policy
            item["estimated_cost_cents"] = round(estimated, 6)
            item["estimated_cost_usd"] = round(estimated / 100.0, 6)
            ai_rows.append(item)
    search_rows = []
    if _table_exists(conn, "saas_web_search_intelligence_runs"):
        rows = conn.execute(
            text(
                """
                SELECT r.tenant_id::text, t.name AS tenant_name, t.slug AS tenant_slug,
                       t.plan_code, r.provider_code, r.search_type,
                       COUNT(*)::int AS requests
                FROM saas_web_search_intelligence_runs r
                JOIN saas_tenants t ON t.id = r.tenant_id
                WHERE r.created_at >= date_trunc('month', NOW())
                GROUP BY r.tenant_id, t.name, t.slug, t.plan_code, r.provider_code, r.search_type
                ORDER BY requests DESC
                LIMIT 500
                """
            )
        ).mappings().all()
        for row in rows:
            item = dict(row)
            policy = provider_policy_for(conn, item["tenant_id"], "search", item["provider_code"], "")
            estimated = _num(item.get("requests")) * _num(policy.get("request_cost_cents"))
            item["policy"] = policy
            item["estimated_cost_cents"] = round(estimated, 6)
            item["estimated_cost_usd"] = round(estimated / 100.0, 6)
            search_rows.append(item)
    return {
        "ai": ai_rows,
        "search": search_rows,
        "totals": {
            "ai_estimated_cost_usd": round(sum(_num(item.get("estimated_cost_usd")) for item in ai_rows), 6),
            "search_estimated_cost_usd": round(sum(_num(item.get("estimated_cost_usd")) for item in search_rows), 6),
            "ai_requests": sum(int(item.get("requests") or 0) for item in ai_rows),
            "search_requests": sum(int(item.get("requests") or 0) for item in search_rows),
        },
    }
