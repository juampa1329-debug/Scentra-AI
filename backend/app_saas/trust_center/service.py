from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app_saas.billing.limits import ensure_tenant_operational
from app_saas.intelligence.service import (
    ensure_intelligence_tables,
    intelligence_feature_state,
    record_intelligence_usage,
    resolve_intelligence_access,
)


TRUST_CENTER_FEATURE_KEY = "ai_trust_center"
POLICY_FEATURE_KEY = "ai_governance_policies"
RISK_FEATURE_KEY = "ai_risk_assessments"
MODEL_CARD_FEATURE_KEY = "ai_model_cards"
REPORT_FEATURE_KEY = "ai_compliance_reports"
AUDIT_FEATURE_KEY = "ai_audit_exports"
DEMO_FEATURE_KEY = "intelligence_demo"

TRUST_FEATURE_KEYS = (
    TRUST_CENTER_FEATURE_KEY,
    POLICY_FEATURE_KEY,
    RISK_FEATURE_KEY,
    MODEL_CARD_FEATURE_KEY,
    REPORT_FEATURE_KEY,
    AUDIT_FEATURE_KEY,
    "ai_premium",
)

STATUS_VALUES = {"enabled", "draft", "disabled", "open", "accepted", "mitigated", "rejected", "closed", "monitoring", "completed"}
RISK_LEVELS = {"low", "medium", "high", "critical"}

HIGH_RISK_ACTIONS = {
    "send_whatsapp",
    "send_instagram",
    "launch_campaign",
    "execute_trigger",
    "update_pipeline",
    "assign_agent",
    "billing.update",
    "meta.subscription",
    "plugin.execute",
}

DEFAULT_POLICIES: list[dict[str, Any]] = [
    {
        "policy_key": "ai.customer_facing_actions.require_approval",
        "name": "Human approval for customer-facing AI actions",
        "description": "Requires approval before AI sends customer-facing messages or launches outbound actions.",
        "risk_tier": "high",
        "enforcement_mode": "approval_required",
        "applies_to_json": ["agents", "workflow_composer", "campaigns", "advisor_actions"],
        "rules_json": {"requires_approval": True, "action_scope": "customer_facing", "blocks_autonomous_send": True},
    },
    {
        "policy_key": "ai.high_risk_tools.require_approval",
        "name": "Approval required for high-risk tools",
        "description": "High-risk AI tools must create approval records instead of executing directly.",
        "risk_tier": "high",
        "enforcement_mode": "approval_required",
        "applies_to_json": ["agents", "ecosystem_tools", "plugins"],
        "rules_json": {"high_risk_tools": sorted(HIGH_RISK_ACTIONS), "metadata_only_plugins": True},
    },
    {
        "policy_key": "ai.data_privacy.no_raw_cross_tenant",
        "name": "No raw cross-tenant data sharing",
        "description": "Cross-tenant intelligence may use aggregate anonymized metrics only.",
        "risk_tier": "critical",
        "enforcement_mode": "block",
        "applies_to_json": ["enterprise_ai_network", "analytics", "ml_training"],
        "rules_json": {"no_raw_messages": True, "min_benchmark_sample_size": 3, "aggregate_only": True},
    },
    {
        "policy_key": "ai.model_rollout.shadow_canary_required",
        "name": "Shadow and canary required before production ML",
        "description": "Trained ML artifacts must pass model-card review, shadow inference and canary rollout before production.",
        "risk_tier": "high",
        "enforcement_mode": "approval_required",
        "applies_to_json": ["mlflow", "bentoml", "model_registry", "predictions"],
        "rules_json": {"requires_model_card": True, "requires_shadow": True, "requires_canary": True},
    },
    {
        "policy_key": "ai.workflow_composer.preflight_required",
        "name": "Workflow Composer preflight required",
        "description": "AI workflows must pass preflight and approval before activation.",
        "risk_tier": "medium",
        "enforcement_mode": "approval_required",
        "applies_to_json": ["workflow_composer"],
        "rules_json": {"requires_preflight": True, "requires_approval": True, "composer_only_activation": True},
    },
    {
        "policy_key": "ai.autonomous_operations.supervised_execution",
        "name": "Supervised autonomous operations",
        "description": "Autonomous operations can recommend and record controlled execution but cannot mutate Meta, CRM or billing directly.",
        "risk_tier": "high",
        "enforcement_mode": "approval_required",
        "applies_to_json": ["autonomous_operations", "self_healing", "ai_control_center"],
        "rules_json": {"direct_provider_mutation": False, "rollback_metadata_required": True},
    },
    {
        "policy_key": "ai.plugins.metadata_only_until_sandbox",
        "name": "Plugins remain metadata-only until sandbox review",
        "description": "Plugin manifests and developer apps are records only until a sandbox runtime is explicitly approved.",
        "risk_tier": "high",
        "enforcement_mode": "block",
        "applies_to_json": ["ecosystem", "plugins", "developer_apps"],
        "rules_json": {"execute_untrusted_code": False, "sandbox_required": True},
    },
]


def _clean(value: Any, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def _json_value(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, type(fallback)) else fallback
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


def _row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    list_fields = {"applies_to_json", "findings_json", "mitigations_json"}
    json_fields = {
        "applies_to_json",
        "rules_json",
        "evidence_json",
        "findings_json",
        "mitigations_json",
        "training_data_json",
        "evaluation_json",
        "rollout_json",
        "compliance_json",
        "metadata_json",
        "remediation_json",
        "metrics_json",
    }
    for key in json_fields:
        if key in data:
            data[key] = _json_value(data.get(key), [] if key in list_fields else {})
    return {key: _jsonable(value) for key, value in data.items()}


def _user_id(user: Any) -> str | None:
    value = getattr(user, "user_id", None) or getattr(user, "id", None)
    return str(value) if value else None


def _norm_key(value: Any, limit: int = 180) -> str:
    clean = _clean(value, limit).lower().replace(" ", "_").replace("-", "_")
    return "".join(ch for ch in clean if ch.isalnum() or ch in {"_", ".", ":"})[:limit]


def _status(value: Any, fallback: str = "enabled") -> str:
    clean = _clean(value, 40).lower().replace("-", "_")
    return clean if clean in STATUS_VALUES else fallback


def _risk_level(value: Any, fallback: str = "medium") -> str:
    clean = _clean(value, 40).lower().replace("-", "_")
    return clean if clean in RISK_LEVELS else fallback


def _table_exists(conn: Connection, table_name: str) -> bool:
    return bool(conn.execute(text("SELECT to_regclass(:table_name) IS NOT NULL"), {"table_name": table_name}).scalar())


def _safe_count(conn: Connection, table_name: str, where_sql: str = "", params: dict[str, Any] | None = None) -> int:
    if not _table_exists(conn, table_name):
        return 0
    sql = f"SELECT COUNT(*)::int FROM {table_name}"
    if where_sql:
        sql += f" WHERE {where_sql}"
    return int(conn.execute(text(sql), params or {}).scalar() or 0)


def ensure_trust_tables(conn: Connection) -> None:
    ensure_intelligence_tables(conn)
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_governance_policies (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                policy_key TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'enabled',
                risk_tier TEXT NOT NULL DEFAULT 'standard',
                enforcement_mode TEXT NOT NULL DEFAULT 'monitor',
                applies_to_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                rules_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                updated_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, policy_key)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_governance_policies_tenant_status ON saas_ai_governance_policies (tenant_id, status, risk_tier, updated_at DESC)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_governance_policy_attestations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                policy_id UUID NOT NULL REFERENCES saas_ai_governance_policies(id) ON DELETE CASCADE,
                attestation_type TEXT NOT NULL DEFAULT 'human_review',
                status TEXT NOT NULL DEFAULT 'attested',
                signed_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                signed_at TIMESTAMP NULL,
                evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                notes TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_policy_attestations_tenant_policy ON saas_ai_governance_policy_attestations (tenant_id, policy_id, created_at DESC)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_risk_assessments (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL,
                risk_level TEXT NOT NULL DEFAULT 'medium',
                status TEXT NOT NULL DEFAULT 'open',
                score NUMERIC(8,4) NOT NULL DEFAULT 0,
                findings_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                mitigations_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                reviewed_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                reviewed_at TIMESTAMP NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_risk_assessments_tenant_status ON saas_ai_risk_assessments (tenant_id, status, risk_level, updated_at DESC)"))
    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_saas_ai_risk_assessments_open_entity ON saas_ai_risk_assessments (tenant_id, entity_type, entity_id) WHERE status = 'open'"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_model_cards (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                model_key TEXT NOT NULL,
                provider_key TEXT NOT NULL DEFAULT '',
                task_type TEXT NOT NULL DEFAULT '',
                version TEXT NOT NULL DEFAULT 'v1',
                status TEXT NOT NULL DEFAULT 'draft',
                intended_use TEXT NOT NULL DEFAULT '',
                limitations TEXT NOT NULL DEFAULT '',
                training_data_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                evaluation_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                rollout_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                compliance_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                owner_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, model_key)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_model_cards_tenant_status ON saas_ai_model_cards (tenant_id, status, task_type, updated_at DESC)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_governance_incidents (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                incident_type TEXT NOT NULL DEFAULT 'ai_governance',
                severity TEXT NOT NULL DEFAULT 'medium',
                status TEXT NOT NULL DEFAULT 'open',
                entity_type TEXT NOT NULL DEFAULT '',
                entity_id TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                remediation_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                opened_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                closed_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                closed_at TIMESTAMP NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_governance_incidents_tenant_status ON saas_ai_governance_incidents (tenant_id, status, severity, updated_at DESC)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_governance_reports (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                report_type TEXT NOT NULL DEFAULT 'trust_summary',
                period_key TEXT NOT NULL DEFAULT 'latest',
                status TEXT NOT NULL DEFAULT 'completed',
                summary TEXT NOT NULL DEFAULT '',
                findings_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, report_type, period_key)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_governance_reports_tenant_type ON saas_ai_governance_reports (tenant_id, report_type, updated_at DESC)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_governance_audits (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                event_type TEXT NOT NULL,
                entity_type TEXT NOT NULL DEFAULT '',
                entity_id TEXT NOT NULL DEFAULT '',
                severity TEXT NOT NULL DEFAULT 'info',
                actor_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
                summary TEXT NOT NULL DEFAULT '',
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_governance_audits_tenant_time ON saas_ai_governance_audits (tenant_id, created_at DESC)"))


def seed_default_policies(conn: Connection, tenant_id: str) -> None:
    ensure_trust_tables(conn)
    for policy in DEFAULT_POLICIES:
        conn.execute(
            text(
                """
                INSERT INTO saas_ai_governance_policies (
                    tenant_id, policy_key, name, description, status, risk_tier,
                    enforcement_mode, applies_to_json, rules_json
                )
                VALUES (
                    CAST(:tenant_id AS uuid), :policy_key, :name, :description, 'enabled',
                    :risk_tier, :enforcement_mode, CAST(:applies_to_json AS jsonb), CAST(:rules_json AS jsonb)
                )
                ON CONFLICT (tenant_id, policy_key)
                DO UPDATE SET
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    applies_to_json = EXCLUDED.applies_to_json,
                    rules_json = saas_ai_governance_policies.rules_json || EXCLUDED.rules_json,
                    updated_at = NOW()
                """
            ),
            {
                "tenant_id": tenant_id,
                "policy_key": policy["policy_key"],
                "name": policy["name"],
                "description": policy["description"],
                "risk_tier": policy["risk_tier"],
                "enforcement_mode": policy["enforcement_mode"],
                "applies_to_json": _json(policy["applies_to_json"]),
                "rules_json": _json(policy["rules_json"]),
            },
        )


def _access(conn: Connection, tenant_id: str, feature_key: str = TRUST_CENTER_FEATURE_KEY, *, require_full: bool = False) -> dict[str, Any]:
    try:
        access = resolve_intelligence_access(conn, tenant_id, feature_key, allow_demo=not require_full)
    except HTTPException as exc:
        if require_full:
            raise
        try:
            demo = resolve_intelligence_access(conn, tenant_id, DEMO_FEATURE_KEY, allow_demo=True)
            demo = dict(demo)
            demo["feature_key"] = DEMO_FEATURE_KEY
            demo["fallback_for"] = feature_key
            demo["mode"] = "demo"
            return demo
        except HTTPException:
            raise exc
    if require_full and access.get("mode") != "full":
        raise HTTPException(status_code=403, detail={"code": "ai_trust_feature_requires_full", "feature": feature_key})
    return access


def _require_full(conn: Connection, tenant_id: str, feature_key: str = TRUST_CENTER_FEATURE_KEY) -> dict[str, Any]:
    ensure_trust_tables(conn)
    ensure_tenant_operational(conn, tenant_id)
    return _access(conn, tenant_id, feature_key, require_full=True)


def _feature_map(conn: Connection, tenant_id: str) -> dict[str, Any]:
    state = intelligence_feature_state(conn, tenant_id)
    return {item["key"]: item for item in state.get("features", []) if item.get("key") in TRUST_FEATURE_KEYS}


def _audit(
    conn: Connection,
    tenant_id: str,
    event_type: str,
    *,
    actor_user_id: str | None = None,
    entity_type: str = "",
    entity_id: str = "",
    severity: str = "info",
    summary: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ensure_trust_tables(conn)
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_governance_audits (
                tenant_id, event_type, entity_type, entity_id, severity, actor_user_id, summary, metadata_json
            )
            VALUES (
                CAST(:tenant_id AS uuid), :event_type, :entity_type, :entity_id, :severity,
                CAST(NULLIF(:actor_user_id, '') AS uuid), :summary, CAST(:metadata_json AS jsonb)
            )
            RETURNING id::text, tenant_id::text, event_type, entity_type, entity_id, severity,
                      actor_user_id::text, summary, metadata_json, created_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "event_type": _clean(event_type, 120),
            "entity_type": _clean(entity_type, 80),
            "entity_id": _clean(entity_id, 180),
            "severity": _risk_level(severity, "low") if severity in RISK_LEVELS else _clean(severity or "info", 40),
            "actor_user_id": actor_user_id or "",
            "summary": _clean(summary, 1000),
            "metadata_json": _json(metadata or {}),
        },
    ).mappings().first()
    conn.execute(
        text(
            """
            INSERT INTO saas_audit_events (tenant_id, actor_user_id, action, resource_type, resource_id, details_json)
            VALUES (
                CAST(:tenant_id AS uuid), CAST(NULLIF(:actor_user_id, '') AS uuid),
                :action, :resource_type, :resource_id, CAST(:details_json AS jsonb)
            )
            """
        ),
        {
            "tenant_id": tenant_id,
            "actor_user_id": actor_user_id or "",
            "action": f"trust_center.{_clean(event_type, 100)}",
            "resource_type": _clean(entity_type or "ai_governance", 80),
            "resource_id": _clean(entity_id, 180),
            "details_json": _json({"summary": summary, "severity": severity, **(metadata or {})}),
        },
    )
    return _row(row) or {}


def _counts(conn: Connection, tenant_id: str) -> dict[str, int]:
    params = {"tenant_id": tenant_id}
    return {
        "policies": _safe_count(conn, "saas_ai_governance_policies", "tenant_id = CAST(:tenant_id AS uuid)", params),
        "enabled_policies": _safe_count(conn, "saas_ai_governance_policies", "tenant_id = CAST(:tenant_id AS uuid) AND status = 'enabled'", params),
        "open_risks": _safe_count(conn, "saas_ai_risk_assessments", "tenant_id = CAST(:tenant_id AS uuid) AND status = 'open'", params),
        "high_risks": _safe_count(conn, "saas_ai_risk_assessments", "tenant_id = CAST(:tenant_id AS uuid) AND status = 'open' AND risk_level IN ('high', 'critical')", params),
        "model_cards": _safe_count(conn, "saas_ai_model_cards", "tenant_id = CAST(:tenant_id AS uuid)", params),
        "open_incidents": _safe_count(conn, "saas_ai_governance_incidents", "tenant_id = CAST(:tenant_id AS uuid) AND status NOT IN ('closed', 'resolved')", params),
        "reports": _safe_count(conn, "saas_ai_governance_reports", "tenant_id = CAST(:tenant_id AS uuid)", params),
        "audit_events": _safe_count(conn, "saas_ai_governance_audits", "tenant_id = CAST(:tenant_id AS uuid)", params),
    }


def _source_signals(conn: Connection, tenant_id: str) -> dict[str, int]:
    params = {"tenant_id": tenant_id}
    return {
        "active_agents": _safe_count(conn, "saas_ai_agents", "tenant_id = CAST(:tenant_id AS uuid) AND status = 'active'", params),
        "pending_agent_tool_approvals": _safe_count(conn, "saas_ai_agent_tool_approvals", "tenant_id = CAST(:tenant_id AS uuid) AND status = 'pending'", params),
        "pending_advisor_actions": _safe_count(conn, "saas_advisor_actions", "tenant_id = CAST(:tenant_id AS uuid) AND status IN ('pending', 'suggested')", params),
        "pending_operation_actions": _safe_count(conn, "saas_ai_operation_actions", "tenant_id = CAST(:tenant_id AS uuid) AND status IN ('suggested', 'approved')", params),
        "active_workflows": _safe_count(conn, "saas_ai_workflows", "tenant_id = CAST(:tenant_id AS uuid) AND status = 'active'", params),
        "unapproved_workflows": _safe_count(conn, "saas_ai_workflows", "tenant_id = CAST(:tenant_id AS uuid) AND approval_status <> 'approved'", params),
        "tenant_plugins": _safe_count(conn, "saas_ai_plugins", "tenant_id = CAST(:tenant_id AS uuid) AND status <> 'archived'", params),
        "high_risk_tools": _safe_count(conn, "saas_ai_tool_registry", "(tenant_id = CAST(:tenant_id AS uuid) OR tenant_id IS NULL) AND risk_level IN ('high', 'critical') AND status = 'enabled'", params),
        "pending_privacy_requests": _safe_count(conn, "saas_privacy_requests", "tenant_id = CAST(:tenant_id AS uuid) AND status = 'pending'", params),
        "registry_models": _safe_count(conn, "saas_intelligence_model_registry", "status IN ('active', 'candidate')", {}),
    }


def get_overview(conn: Connection, tenant_id: str) -> dict[str, Any]:
    seed_default_policies(conn, tenant_id)
    access = _access(conn, tenant_id, TRUST_CENTER_FEATURE_KEY)
    controls = [
        {"key": "approval_first", "label": "Approval-first AI", "status": "enabled"},
        {"key": "privacy_safe_network", "label": "Cross-tenant aggregate only", "status": "enabled"},
        {"key": "model_rollout_governance", "label": "Shadow/canary rollout", "status": "monitoring"},
        {"key": "plugin_sandbox", "label": "Plugin execution blocked until sandbox", "status": "enabled"},
        {"key": "audit_trail", "label": "AI governance audit trail", "status": "enabled"},
    ]
    recent_audits = conn.execute(
        text(
            """
            SELECT id::text, tenant_id::text, event_type, entity_type, entity_id, severity,
                   actor_user_id::text, summary, metadata_json, created_at::text
            FROM saas_ai_governance_audits
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY created_at DESC
            LIMIT 10
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().all()
    return {
        "phase": "phase_22_ai_trust_compliance_governance",
        "access": access,
        "features": _feature_map(conn, tenant_id),
        "counts": _counts(conn, tenant_id),
        "source_signals": _source_signals(conn, tenant_id),
        "controls": controls,
        "recent_audits": [_row(row) for row in recent_audits],
        "safety": {
            "control_plane_only": True,
            "demo_mode_mutations_blocked": True,
            "human_approval_required_for_critical_actions": True,
            "raw_cross_tenant_data_shared": False,
            "model_cards_do_not_change_rollout": True,
        },
    }


def list_policies(conn: Connection, tenant_id: str) -> dict[str, Any]:
    seed_default_policies(conn, tenant_id)
    access = _access(conn, tenant_id, POLICY_FEATURE_KEY)
    rows = conn.execute(
        text(
            """
            SELECT id::text, tenant_id::text, policy_key, name, description, status, risk_tier,
                   enforcement_mode, applies_to_json, rules_json, created_by_user_id::text,
                   updated_by_user_id::text, created_at::text, updated_at::text
            FROM saas_ai_governance_policies
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY
                CASE risk_tier WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                policy_key
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().all()
    return {"access": access, "policies": [_row(row) for row in rows]}


def upsert_policy(conn: Connection, tenant_id: str, user: Any, payload: Any) -> dict[str, Any]:
    _require_full(conn, tenant_id, POLICY_FEATURE_KEY)
    data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload or {})
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_governance_policies (
                tenant_id, policy_key, name, description, status, risk_tier, enforcement_mode,
                applies_to_json, rules_json, created_by_user_id, updated_by_user_id, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), :policy_key, :name, :description, :status, :risk_tier,
                :enforcement_mode, CAST(:applies_to_json AS jsonb), CAST(:rules_json AS jsonb),
                CAST(NULLIF(:user_id, '') AS uuid), CAST(NULLIF(:user_id, '') AS uuid), NOW()
            )
            ON CONFLICT (tenant_id, policy_key)
            DO UPDATE SET
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                status = EXCLUDED.status,
                risk_tier = EXCLUDED.risk_tier,
                enforcement_mode = EXCLUDED.enforcement_mode,
                applies_to_json = EXCLUDED.applies_to_json,
                rules_json = EXCLUDED.rules_json,
                updated_by_user_id = EXCLUDED.updated_by_user_id,
                updated_at = NOW()
            RETURNING id::text, tenant_id::text, policy_key, name, description, status, risk_tier,
                      enforcement_mode, applies_to_json, rules_json, created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "policy_key": _norm_key(data.get("policy_key")),
            "name": _clean(data.get("name"), 180),
            "description": _clean(data.get("description"), 1500),
            "status": _status(data.get("status"), "enabled"),
            "risk_tier": _risk_level(data.get("risk_tier"), "medium"),
            "enforcement_mode": _clean(data.get("enforcement_mode") or "monitor", 60),
            "applies_to_json": _json(data.get("applies_to_json") if isinstance(data.get("applies_to_json"), list) else []),
            "rules_json": _json(data.get("rules_json") if isinstance(data.get("rules_json"), dict) else {}),
            "user_id": _user_id(user) or "",
        },
    ).mappings().first()
    _audit(conn, tenant_id, "policy.upsert", actor_user_id=_user_id(user), entity_type="governance_policy", entity_id=str(row["id"]), summary=f"Policy upserted: {row['policy_key']}")
    return {"ok": True, "policy": _row(row)}


def patch_policy(conn: Connection, tenant_id: str, user: Any, policy_id: str, payload: Any) -> dict[str, Any]:
    _require_full(conn, tenant_id, POLICY_FEATURE_KEY)
    data = payload.model_dump(exclude_unset=True) if hasattr(payload, "model_dump") else dict(payload or {})
    current = conn.execute(
        text("SELECT * FROM saas_ai_governance_policies WHERE id = CAST(:policy_id AS uuid) AND tenant_id = CAST(:tenant_id AS uuid)"),
        {"policy_id": policy_id, "tenant_id": tenant_id},
    ).mappings().first()
    if not current:
        raise HTTPException(status_code=404, detail="policy_not_found")
    next_data = {**dict(current), **data}
    row = conn.execute(
        text(
            """
            UPDATE saas_ai_governance_policies
            SET name = :name,
                description = :description,
                status = :status,
                risk_tier = :risk_tier,
                enforcement_mode = :enforcement_mode,
                applies_to_json = CAST(:applies_to_json AS jsonb),
                rules_json = CAST(:rules_json AS jsonb),
                updated_by_user_id = CAST(NULLIF(:user_id, '') AS uuid),
                updated_at = NOW()
            WHERE id = CAST(:policy_id AS uuid)
              AND tenant_id = CAST(:tenant_id AS uuid)
            RETURNING id::text, tenant_id::text, policy_key, name, description, status, risk_tier,
                      enforcement_mode, applies_to_json, rules_json, created_at::text, updated_at::text
            """
        ),
        {
            "policy_id": policy_id,
            "tenant_id": tenant_id,
            "name": _clean(next_data.get("name"), 180),
            "description": _clean(next_data.get("description"), 1500),
            "status": _status(next_data.get("status"), "enabled"),
            "risk_tier": _risk_level(next_data.get("risk_tier"), "medium"),
            "enforcement_mode": _clean(next_data.get("enforcement_mode") or "monitor", 60),
            "applies_to_json": _json(next_data.get("applies_to_json") if isinstance(next_data.get("applies_to_json"), list) else _json_value(next_data.get("applies_to_json"), [])),
            "rules_json": _json(next_data.get("rules_json") if isinstance(next_data.get("rules_json"), dict) else _json_value(next_data.get("rules_json"), {})),
            "user_id": _user_id(user) or "",
        },
    ).mappings().first()
    _audit(conn, tenant_id, "policy.patch", actor_user_id=_user_id(user), entity_type="governance_policy", entity_id=policy_id, summary=f"Policy updated: {row['policy_key']}")
    return {"ok": True, "policy": _row(row)}


def attest_policy(conn: Connection, tenant_id: str, user: Any, policy_id: str, payload: Any) -> dict[str, Any]:
    _require_full(conn, tenant_id, POLICY_FEATURE_KEY)
    data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload or {})
    policy = conn.execute(
        text("SELECT id::text, policy_key FROM saas_ai_governance_policies WHERE id = CAST(:policy_id AS uuid) AND tenant_id = CAST(:tenant_id AS uuid)"),
        {"policy_id": policy_id, "tenant_id": tenant_id},
    ).mappings().first()
    if not policy:
        raise HTTPException(status_code=404, detail="policy_not_found")
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_governance_policy_attestations (
                tenant_id, policy_id, attestation_type, status, signed_by_user_id,
                signed_at, evidence_json, notes, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), CAST(:policy_id AS uuid), :attestation_type, :status,
                CAST(NULLIF(:user_id, '') AS uuid), NOW(), CAST(:evidence_json AS jsonb), :notes, NOW()
            )
            RETURNING id::text, tenant_id::text, policy_id::text, attestation_type, status,
                      signed_by_user_id::text, signed_at::text, evidence_json, notes, created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "policy_id": policy_id,
            "attestation_type": _clean(data.get("attestation_type") or "human_review", 80),
            "status": _status(data.get("status"), "completed"),
            "user_id": _user_id(user) or "",
            "evidence_json": _json(data.get("evidence_json") if isinstance(data.get("evidence_json"), dict) else {}),
            "notes": _clean(data.get("notes"), 1500),
        },
    ).mappings().first()
    _audit(conn, tenant_id, "policy.attested", actor_user_id=_user_id(user), entity_type="governance_policy", entity_id=policy_id, summary=f"Policy attested: {policy['policy_key']}")
    return {"ok": True, "attestation": _row(row)}


def list_risk_assessments(conn: Connection, tenant_id: str, status: str | None = None) -> dict[str, Any]:
    ensure_trust_tables(conn)
    access = _access(conn, tenant_id, RISK_FEATURE_KEY)
    params: dict[str, Any] = {"tenant_id": tenant_id}
    clauses = ["tenant_id = CAST(:tenant_id AS uuid)"]
    if status:
        clauses.append("status = :status")
        params["status"] = _status(status, "open")
    rows = conn.execute(
        text(
            f"""
            SELECT id::text, tenant_id::text, entity_type, entity_id, title, risk_level, status,
                   score, findings_json, mitigations_json, evidence_json, reviewed_by_user_id::text,
                   reviewed_at::text, created_at::text, updated_at::text
            FROM saas_ai_risk_assessments
            WHERE {' AND '.join(clauses)}
            ORDER BY
                CASE risk_level WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                updated_at DESC
            LIMIT 300
            """
        ),
        params,
    ).mappings().all()
    return {"access": access, "assessments": [_row(row) for row in rows]}


def _assessment(entity_type: str, entity_id: str, title: str, risk_level: str, score: float, findings: list[dict[str, Any]], mitigations: list[dict[str, Any]], evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "title": title,
        "risk_level": _risk_level(risk_level),
        "score": max(0.0, min(float(score or 0), 100.0)),
        "findings_json": findings,
        "mitigations_json": mitigations,
        "evidence_json": evidence,
        "status": "open",
    }


def _generate_assessments(conn: Connection, tenant_id: str, scope: str, max_items: int) -> list[dict[str, Any]]:
    scope = _clean(scope or "all", 80).lower()
    results: list[dict[str, Any]] = []
    params = {"tenant_id": tenant_id, "limit": max_items}

    if scope in {"all", "agents"} and _table_exists(conn, "saas_ai_agents"):
        rows = conn.execute(
            text(
                """
                SELECT id::text, name, status, is_custom, tools_json, approval_policy_json, last_preflight_json
                FROM saas_ai_agents
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND status <> 'archived'
                ORDER BY updated_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
        for row in rows:
            tools = _json_value(row.get("tools_json"), [])
            approval = _json_value(row.get("approval_policy_json"), {})
            preflight = _json_value(row.get("last_preflight_json"), {})
            tool_codes = {str(item) for item in tools} if isinstance(tools, list) else set()
            risky_tools = sorted(tool_codes.intersection(HIGH_RISK_ACTIONS))
            findings: list[dict[str, Any]] = []
            score = 20
            risk = "low"
            if row.get("status") == "active" and preflight.get("status") not in {"ready", "pass", "ok"}:
                findings.append({"key": "preflight_missing", "message": "Active agent has no ready preflight evidence."})
                score += 35
                risk = "high"
            if risky_tools:
                findings.append({"key": "high_risk_tools", "tools": risky_tools})
                score += 25
                risk = "high"
            if not approval:
                findings.append({"key": "approval_policy_empty", "message": "Approval policy is empty or not explicit."})
                score += 15
                risk = "medium" if risk == "low" else risk
            results.append(_assessment("agent", row["id"], f"Agent: {row['name']}", risk, score, findings or [{"key": "baseline", "message": "No blocking issue detected."}], [{"action": "Run preflight, review tools and keep approvals enabled."}], dict(row)))

    if scope in {"all", "workflows"} and _table_exists(conn, "saas_ai_workflows"):
        rows = conn.execute(
            text(
                """
                SELECT id::text, name, status, approval_status, preflight_json, graph_json, config_json
                FROM saas_ai_workflows
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                ORDER BY updated_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
        for row in rows:
            preflight = _json_value(row.get("preflight_json"), {})
            graph = _json_value(row.get("graph_json"), {})
            nodes = graph.get("nodes") if isinstance(graph, dict) else []
            high_actions = []
            for node in nodes if isinstance(nodes, list) else []:
                config = node.get("config") if isinstance(node, dict) else {}
                action_type = str((config or {}).get("action_type") or "")
                if action_type in HIGH_RISK_ACTIONS:
                    high_actions.append(action_type)
            findings = []
            score = 15
            risk = "low"
            if row.get("status") == "active" and row.get("approval_status") != "approved":
                findings.append({"key": "active_without_approval", "message": "Active workflow is not approved."})
                score += 40
                risk = "critical"
            if preflight.get("status") in {"blocked", "failed"}:
                findings.append({"key": "preflight_blocked", "status": preflight.get("status")})
                score += 30
                risk = "high" if risk != "critical" else risk
            if high_actions:
                findings.append({"key": "high_risk_actions", "actions": sorted(set(high_actions))})
                score += 20
                risk = "high" if risk == "low" else risk
            results.append(_assessment("workflow", row["id"], f"Workflow: {row['name']}", risk, score, findings or [{"key": "baseline", "message": "Workflow has no detected critical governance issue."}], [{"action": "Run preflight and keep composer_only activation until materialization is reviewed."}], dict(row)))

    if scope in {"all", "models"} and _table_exists(conn, "saas_intelligence_model_registry"):
        rows = conn.execute(
            text(
                """
                SELECT model_key, model_type, task_type, framework, version, status, stage,
                       artifact_uri, shadow_mode, metrics_json, metadata_json, rollout_mode,
                       traffic_percent, min_labeled_count, min_accuracy, promotion_status
                FROM saas_intelligence_model_registry
                ORDER BY updated_at DESC
                LIMIT :limit
                """
            ),
            {"limit": max_items},
        ).mappings().all()
        for row in rows:
            metrics = _json_value(row.get("metrics_json"), {})
            findings = []
            score = 20
            risk = "medium"
            if row.get("rollout_mode") == "production" and row.get("promotion_status") not in {"approved", "baseline_approved"}:
                findings.append({"key": "production_without_promotion_approval", "promotion_status": row.get("promotion_status")})
                score += 35
                risk = "high"
            if row.get("rollout_mode") == "canary" and int(row.get("traffic_percent") or 0) > 25:
                findings.append({"key": "large_canary", "traffic_percent": row.get("traffic_percent")})
                score += 20
                risk = "high"
            if float(metrics.get("accuracy") or 0) and float(metrics.get("accuracy") or 0) < float(row.get("min_accuracy") or 0):
                findings.append({"key": "accuracy_below_threshold", "accuracy": metrics.get("accuracy")})
                score += 25
                risk = "high"
            results.append(_assessment("model", str(row["model_key"]), f"Model: {row['model_key']}", risk, score, findings or [{"key": "baseline", "message": "Model registry row has no blocking rollout issue detected."}], [{"action": "Attach a model card, keep shadow/canary gates and review metrics before promotion."}], dict(row)))

    if scope in {"all", "tools"} and _table_exists(conn, "saas_ai_tool_registry"):
        rows = conn.execute(
            text(
                """
                SELECT id::text, tool_key, name, status, risk_level, runtime_type, permission_scopes_json, metadata_json
                FROM saas_ai_tool_registry
                WHERE tenant_id IS NULL OR tenant_id = CAST(:tenant_id AS uuid)
                ORDER BY
                    CASE risk_level WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                    updated_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
        for row in rows:
            risk = _risk_level(row.get("risk_level"), "medium")
            score = {"low": 15, "medium": 35, "high": 70, "critical": 90}.get(risk, 35)
            findings = [{"key": "tool_risk_level", "risk_level": risk}]
            if risk in {"high", "critical"} and row.get("status") == "enabled":
                findings.append({"key": "enabled_high_risk_tool", "message": "High-risk enabled tool should require explicit approval."})
            results.append(_assessment("tool", row["id"], f"Tool: {row['tool_key']}", risk, score, findings, [{"action": "Keep permission scopes approval-first and avoid direct execution."}], dict(row)))

    if scope in {"all", "plugins"} and _table_exists(conn, "saas_ai_plugins"):
        rows = conn.execute(
            text(
                """
                SELECT id::text, plugin_key, name, status, runtime_type, sandbox_mode,
                       approval_status, permissions_json, manifest_json
                FROM saas_ai_plugins
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                ORDER BY updated_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
        for row in rows:
            findings = []
            score = 25
            risk = "medium"
            if row.get("sandbox_mode") != "metadata_only":
                findings.append({"key": "sandbox_not_metadata_only", "sandbox_mode": row.get("sandbox_mode")})
                score += 40
                risk = "high"
            if row.get("approval_status") != "approved":
                findings.append({"key": "plugin_not_approved", "approval_status": row.get("approval_status")})
                score += 15
            results.append(_assessment("plugin", row["id"], f"Plugin: {row['plugin_key']}", risk, score, findings or [{"key": "baseline", "message": "Plugin stays metadata-only."}], [{"action": "Keep metadata-only until sandbox, secret and permission review are approved."}], dict(row)))

    if scope in {"all", "operations"} and _table_exists(conn, "saas_ai_operation_actions"):
        rows = conn.execute(
            text(
                """
                SELECT id::text, action_type, title, risk_level, status, approval_required,
                       autonomy_level, confidence, rollback_json, input_json
                FROM saas_ai_operation_actions
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND status IN ('suggested', 'approved', 'executed')
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
        for row in rows:
            risk = _risk_level(row.get("risk_level"), "medium")
            score = {"low": 20, "medium": 45, "high": 75, "critical": 92}.get(risk, 45)
            findings = [{"key": "autonomous_action", "status": row.get("status"), "approval_required": row.get("approval_required")}]
            if row.get("status") == "executed" and risk in {"high", "critical"}:
                findings.append({"key": "executed_high_risk_action", "message": "Executed high-risk action requires audit review."})
            results.append(_assessment("operation_action", row["id"], f"AI operation action: {row['title']}", risk, score, findings, [{"action": "Review audit, approval and rollback metadata."}], dict(row)))

    return results[:max_items]


def _persist_assessment(conn: Connection, tenant_id: str, item: dict[str, Any], user_id: str | None) -> dict[str, Any]:
    existing = conn.execute(
        text(
            """
            SELECT id::text
            FROM saas_ai_risk_assessments
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND entity_type = :entity_type
              AND entity_id = :entity_id
              AND status = 'open'
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "entity_type": item["entity_type"], "entity_id": item["entity_id"]},
    ).mappings().first()
    params = {
        "tenant_id": tenant_id,
        "entity_type": item["entity_type"],
        "entity_id": item["entity_id"],
        "title": item["title"],
        "risk_level": item["risk_level"],
        "score": item["score"],
        "findings_json": _json(item["findings_json"]),
        "mitigations_json": _json(item["mitigations_json"]),
        "evidence_json": _json(item["evidence_json"]),
        "user_id": user_id or "",
    }
    if existing:
        row = conn.execute(
            text(
                """
                UPDATE saas_ai_risk_assessments
                SET title = :title,
                    risk_level = :risk_level,
                    score = :score,
                    findings_json = CAST(:findings_json AS jsonb),
                    mitigations_json = CAST(:mitigations_json AS jsonb),
                    evidence_json = CAST(:evidence_json AS jsonb),
                    updated_at = NOW()
                WHERE id = CAST(:assessment_id AS uuid)
                  AND tenant_id = CAST(:tenant_id AS uuid)
                RETURNING id::text, tenant_id::text, entity_type, entity_id, title, risk_level, status,
                          score, findings_json, mitigations_json, evidence_json, reviewed_by_user_id::text,
                          reviewed_at::text, created_at::text, updated_at::text
                """
            ),
            {**params, "assessment_id": existing["id"]},
        ).mappings().first()
    else:
        row = conn.execute(
            text(
                """
                INSERT INTO saas_ai_risk_assessments (
                    tenant_id, entity_type, entity_id, title, risk_level, status, score,
                    findings_json, mitigations_json, evidence_json
                )
                VALUES (
                    CAST(:tenant_id AS uuid), :entity_type, :entity_id, :title, :risk_level, 'open', :score,
                    CAST(:findings_json AS jsonb), CAST(:mitigations_json AS jsonb), CAST(:evidence_json AS jsonb)
                )
                RETURNING id::text, tenant_id::text, entity_type, entity_id, title, risk_level, status,
                          score, findings_json, mitigations_json, evidence_json, reviewed_by_user_id::text,
                          reviewed_at::text, created_at::text, updated_at::text
                """
            ),
            params,
        ).mappings().first()
    return _row(row) or {}


def run_risk_assessment(conn: Connection, tenant_id: str, user: Any, payload: Any) -> dict[str, Any]:
    ensure_trust_tables(conn)
    data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload or {})
    scope = _clean(data.get("scope") or "all", 80)
    persist = bool(data.get("persist", True))
    max_items = max(1, min(int(data.get("max_items") or 120), 300))
    if persist:
        _require_full(conn, tenant_id, RISK_FEATURE_KEY)
        record_intelligence_usage(conn, tenant_id, RISK_FEATURE_KEY, metadata={"scope": scope, "operation": "risk_assessment"})
    else:
        _access(conn, tenant_id, RISK_FEATURE_KEY)
    generated = _generate_assessments(conn, tenant_id, scope, max_items)
    saved = [_persist_assessment(conn, tenant_id, item, _user_id(user)) for item in generated] if persist else []
    if persist:
        _audit(conn, tenant_id, "risk_assessment.run", actor_user_id=_user_id(user), entity_type="risk_assessment", severity="info", summary=f"Risk assessment generated {len(saved)} records", metadata={"scope": scope})
    return {"ok": True, "scope": scope, "persisted": persist, "generated": generated, "assessments": saved}


def patch_risk_assessment(conn: Connection, tenant_id: str, user: Any, assessment_id: str, payload: Any) -> dict[str, Any]:
    _require_full(conn, tenant_id, RISK_FEATURE_KEY)
    current = conn.execute(
        text("SELECT * FROM saas_ai_risk_assessments WHERE id = CAST(:id AS uuid) AND tenant_id = CAST(:tenant_id AS uuid)"),
        {"id": assessment_id, "tenant_id": tenant_id},
    ).mappings().first()
    if not current:
        raise HTTPException(status_code=404, detail="risk_assessment_not_found")
    data = payload.model_dump(exclude_unset=True) if hasattr(payload, "model_dump") else dict(payload or {})
    status = _status(data.get("status") or current.get("status"), str(current.get("status") or "open"))
    row = conn.execute(
        text(
            """
            UPDATE saas_ai_risk_assessments
            SET status = :status,
                risk_level = :risk_level,
                mitigations_json = CAST(:mitigations_json AS jsonb),
                evidence_json = CAST(:evidence_json AS jsonb),
                reviewed_by_user_id = CASE WHEN :status <> 'open' THEN CAST(NULLIF(:user_id, '') AS uuid) ELSE reviewed_by_user_id END,
                reviewed_at = CASE WHEN :status <> 'open' THEN NOW() ELSE reviewed_at END,
                updated_at = NOW()
            WHERE id = CAST(:id AS uuid)
              AND tenant_id = CAST(:tenant_id AS uuid)
            RETURNING id::text, tenant_id::text, entity_type, entity_id, title, risk_level, status,
                      score, findings_json, mitigations_json, evidence_json, reviewed_by_user_id::text,
                      reviewed_at::text, created_at::text, updated_at::text
            """
        ),
        {
            "id": assessment_id,
            "tenant_id": tenant_id,
            "status": status,
            "risk_level": _risk_level(data.get("risk_level") or current.get("risk_level"), "medium"),
            "mitigations_json": _json(data.get("mitigations_json") if isinstance(data.get("mitigations_json"), list) else _json_value(current.get("mitigations_json"), [])),
            "evidence_json": _json(data.get("evidence_json") if isinstance(data.get("evidence_json"), dict) else _json_value(current.get("evidence_json"), {})),
            "user_id": _user_id(user) or "",
        },
    ).mappings().first()
    _audit(conn, tenant_id, "risk_assessment.patch", actor_user_id=_user_id(user), entity_type="risk_assessment", entity_id=assessment_id, severity=row["risk_level"], summary=f"Risk assessment set to {status}")
    return {"ok": True, "assessment": _row(row)}


def list_model_cards(conn: Connection, tenant_id: str) -> dict[str, Any]:
    ensure_trust_tables(conn)
    access = _access(conn, tenant_id, MODEL_CARD_FEATURE_KEY)
    rows = conn.execute(
        text(
            """
            SELECT id::text, tenant_id::text, model_key, provider_key, task_type, version, status,
                   intended_use, limitations, training_data_json, evaluation_json, rollout_json,
                   compliance_json, owner_user_id::text, created_at::text, updated_at::text
            FROM saas_ai_model_cards
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY updated_at DESC
            LIMIT 200
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().all()
    registry = []
    if _table_exists(conn, "saas_intelligence_model_registry"):
        registry = [
            dict(row)
            for row in conn.execute(
                text(
                    """
                    SELECT model_key, task_type, framework, version, status, stage, rollout_mode, promotion_status
                    FROM saas_intelligence_model_registry
                    ORDER BY updated_at DESC
                    LIMIT 120
                    """
                )
            ).mappings().all()
        ]
    return {"access": access, "model_cards": [_row(row) for row in rows], "registry_models": registry}


def upsert_model_card(conn: Connection, tenant_id: str, user: Any, payload: Any) -> dict[str, Any]:
    _require_full(conn, tenant_id, MODEL_CARD_FEATURE_KEY)
    data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload or {})
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_model_cards (
                tenant_id, model_key, provider_key, task_type, version, status, intended_use,
                limitations, training_data_json, evaluation_json, rollout_json, compliance_json,
                owner_user_id, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), :model_key, :provider_key, :task_type, :version, :status,
                :intended_use, :limitations, CAST(:training_data_json AS jsonb),
                CAST(:evaluation_json AS jsonb), CAST(:rollout_json AS jsonb),
                CAST(:compliance_json AS jsonb), CAST(NULLIF(:user_id, '') AS uuid), NOW()
            )
            ON CONFLICT (tenant_id, model_key)
            DO UPDATE SET
                provider_key = EXCLUDED.provider_key,
                task_type = EXCLUDED.task_type,
                version = EXCLUDED.version,
                status = EXCLUDED.status,
                intended_use = EXCLUDED.intended_use,
                limitations = EXCLUDED.limitations,
                training_data_json = EXCLUDED.training_data_json,
                evaluation_json = EXCLUDED.evaluation_json,
                rollout_json = EXCLUDED.rollout_json,
                compliance_json = EXCLUDED.compliance_json,
                owner_user_id = EXCLUDED.owner_user_id,
                updated_at = NOW()
            RETURNING id::text, tenant_id::text, model_key, provider_key, task_type, version, status,
                      intended_use, limitations, training_data_json, evaluation_json, rollout_json,
                      compliance_json, owner_user_id::text, created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "model_key": _norm_key(data.get("model_key")),
            "provider_key": _clean(data.get("provider_key"), 80),
            "task_type": _clean(data.get("task_type"), 100),
            "version": _clean(data.get("version") or "v1", 80),
            "status": _status(data.get("status"), "draft"),
            "intended_use": _clean(data.get("intended_use"), 2000),
            "limitations": _clean(data.get("limitations"), 2000),
            "training_data_json": _json(data.get("training_data_json") if isinstance(data.get("training_data_json"), dict) else {}),
            "evaluation_json": _json(data.get("evaluation_json") if isinstance(data.get("evaluation_json"), dict) else {}),
            "rollout_json": _json(data.get("rollout_json") if isinstance(data.get("rollout_json"), dict) else {}),
            "compliance_json": _json(data.get("compliance_json") if isinstance(data.get("compliance_json"), dict) else {}),
            "user_id": _user_id(user) or "",
        },
    ).mappings().first()
    _audit(conn, tenant_id, "model_card.upsert", actor_user_id=_user_id(user), entity_type="model_card", entity_id=str(row["id"]), summary=f"Model card upserted: {row['model_key']}")
    return {"ok": True, "model_card": _row(row)}


def patch_model_card(conn: Connection, tenant_id: str, user: Any, card_id: str, payload: Any) -> dict[str, Any]:
    _require_full(conn, tenant_id, MODEL_CARD_FEATURE_KEY)
    current = conn.execute(
        text("SELECT * FROM saas_ai_model_cards WHERE id = CAST(:id AS uuid) AND tenant_id = CAST(:tenant_id AS uuid)"),
        {"id": card_id, "tenant_id": tenant_id},
    ).mappings().first()
    if not current:
        raise HTTPException(status_code=404, detail="model_card_not_found")
    data = payload.model_dump(exclude_unset=True) if hasattr(payload, "model_dump") else dict(payload or {})
    next_data = {**dict(current), **data}
    next_data["model_key"] = current["model_key"]
    return upsert_model_card(conn, tenant_id, user, type("Payload", (), {"model_dump": lambda _self: next_data})())


def list_incidents(conn: Connection, tenant_id: str, status: str | None = None) -> dict[str, Any]:
    ensure_trust_tables(conn)
    access = _access(conn, tenant_id, TRUST_CENTER_FEATURE_KEY)
    params: dict[str, Any] = {"tenant_id": tenant_id}
    clauses = ["tenant_id = CAST(:tenant_id AS uuid)"]
    if status:
        clauses.append("status = :status")
        params["status"] = _status(status, "open")
    rows = conn.execute(
        text(
            f"""
            SELECT id::text, tenant_id::text, incident_type, severity, status, entity_type, entity_id,
                   title, description, remediation_json, opened_by_user_id::text,
                   closed_by_user_id::text, closed_at::text, created_at::text, updated_at::text
            FROM saas_ai_governance_incidents
            WHERE {' AND '.join(clauses)}
            ORDER BY
                CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                updated_at DESC
            LIMIT 200
            """
        ),
        params,
    ).mappings().all()
    return {"access": access, "incidents": [_row(row) for row in rows]}


def create_incident(conn: Connection, tenant_id: str, user: Any, payload: Any) -> dict[str, Any]:
    _require_full(conn, tenant_id, TRUST_CENTER_FEATURE_KEY)
    data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload or {})
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_governance_incidents (
                tenant_id, incident_type, severity, status, entity_type, entity_id, title,
                description, remediation_json, opened_by_user_id, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), :incident_type, :severity, 'open', :entity_type, :entity_id,
                :title, :description, CAST(:remediation_json AS jsonb),
                CAST(NULLIF(:user_id, '') AS uuid), NOW()
            )
            RETURNING id::text, tenant_id::text, incident_type, severity, status, entity_type, entity_id,
                      title, description, remediation_json, opened_by_user_id::text,
                      closed_by_user_id::text, closed_at::text, created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "incident_type": _clean(data.get("incident_type") or "ai_governance", 80),
            "severity": _risk_level(data.get("severity"), "medium"),
            "entity_type": _clean(data.get("entity_type"), 80),
            "entity_id": _clean(data.get("entity_id"), 180),
            "title": _clean(data.get("title"), 220),
            "description": _clean(data.get("description"), 3000),
            "remediation_json": _json(data.get("remediation_json") if isinstance(data.get("remediation_json"), dict) else {}),
            "user_id": _user_id(user) or "",
        },
    ).mappings().first()
    _audit(conn, tenant_id, "incident.create", actor_user_id=_user_id(user), entity_type="governance_incident", entity_id=str(row["id"]), severity=row["severity"], summary=f"Incident created: {row['title']}")
    return {"ok": True, "incident": _row(row)}


def patch_incident(conn: Connection, tenant_id: str, user: Any, incident_id: str, payload: Any) -> dict[str, Any]:
    _require_full(conn, tenant_id, TRUST_CENTER_FEATURE_KEY)
    current = conn.execute(
        text("SELECT * FROM saas_ai_governance_incidents WHERE id = CAST(:id AS uuid) AND tenant_id = CAST(:tenant_id AS uuid)"),
        {"id": incident_id, "tenant_id": tenant_id},
    ).mappings().first()
    if not current:
        raise HTTPException(status_code=404, detail="incident_not_found")
    data = payload.model_dump(exclude_unset=True) if hasattr(payload, "model_dump") else dict(payload or {})
    status = _status(data.get("status") or current.get("status"), str(current.get("status") or "open"))
    row = conn.execute(
        text(
            """
            UPDATE saas_ai_governance_incidents
            SET severity = :severity,
                status = :status,
                description = :description,
                remediation_json = CAST(:remediation_json AS jsonb),
                closed_by_user_id = CASE WHEN :status IN ('closed', 'resolved') THEN CAST(NULLIF(:user_id, '') AS uuid) ELSE closed_by_user_id END,
                closed_at = CASE WHEN :status IN ('closed', 'resolved') THEN NOW() ELSE closed_at END,
                updated_at = NOW()
            WHERE id = CAST(:id AS uuid)
              AND tenant_id = CAST(:tenant_id AS uuid)
            RETURNING id::text, tenant_id::text, incident_type, severity, status, entity_type, entity_id,
                      title, description, remediation_json, opened_by_user_id::text,
                      closed_by_user_id::text, closed_at::text, created_at::text, updated_at::text
            """
        ),
        {
            "id": incident_id,
            "tenant_id": tenant_id,
            "severity": _risk_level(data.get("severity") or current.get("severity"), "medium"),
            "status": status,
            "description": _clean(data.get("description") if data.get("description") is not None else current.get("description"), 3000),
            "remediation_json": _json(data.get("remediation_json") if isinstance(data.get("remediation_json"), dict) else _json_value(current.get("remediation_json"), {})),
            "user_id": _user_id(user) or "",
        },
    ).mappings().first()
    _audit(conn, tenant_id, "incident.patch", actor_user_id=_user_id(user), entity_type="governance_incident", entity_id=incident_id, severity=row["severity"], summary=f"Incident updated to {status}")
    return {"ok": True, "incident": _row(row)}


def list_audits(conn: Connection, tenant_id: str, limit: int = 100) -> dict[str, Any]:
    ensure_trust_tables(conn)
    access = _access(conn, tenant_id, AUDIT_FEATURE_KEY)
    rows = conn.execute(
        text(
            """
            SELECT id::text, tenant_id::text, event_type, entity_type, entity_id, severity,
                   actor_user_id::text, summary, metadata_json, created_at::text
            FROM saas_ai_governance_audits
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "limit": max(1, min(int(limit or 100), 500))},
    ).mappings().all()
    return {"access": access, "audits": [_row(row) for row in rows]}


def list_reports(conn: Connection, tenant_id: str) -> dict[str, Any]:
    ensure_trust_tables(conn)
    access = _access(conn, tenant_id, REPORT_FEATURE_KEY)
    rows = conn.execute(
        text(
            """
            SELECT id::text, tenant_id::text, report_type, period_key, status, summary,
                   findings_json, metrics_json, created_by_user_id::text, created_at::text, updated_at::text
            FROM saas_ai_governance_reports
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY updated_at DESC
            LIMIT 120
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().all()
    return {"access": access, "reports": [_row(row) for row in rows]}


def generate_report(conn: Connection, tenant_id: str, user: Any, payload: Any) -> dict[str, Any]:
    _require_full(conn, tenant_id, REPORT_FEATURE_KEY)
    record_intelligence_usage(conn, tenant_id, REPORT_FEATURE_KEY, metadata={"operation": "generate_report"})
    data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload or {})
    period_key = _clean(data.get("period_key"), 80) or datetime.now(timezone.utc).strftime("%Y%m%d")
    report_type = _norm_key(data.get("report_type") or "trust_summary", 80)
    counts = _counts(conn, tenant_id)
    signals = _source_signals(conn, tenant_id)
    findings = [
        {"key": "open_risks", "value": counts["open_risks"], "severity": "high" if counts["high_risks"] else "medium"},
        {"key": "open_incidents", "value": counts["open_incidents"], "severity": "high" if counts["open_incidents"] else "low"},
        {"key": "approval_backlog", "value": signals["pending_agent_tool_approvals"] + signals["pending_advisor_actions"] + signals["pending_operation_actions"], "severity": "medium"},
        {"key": "model_card_coverage", "value": counts["model_cards"], "severity": "medium" if counts["model_cards"] == 0 and signals["registry_models"] else "low"},
    ]
    summary = (
        f"AI Trust summary: {counts['enabled_policies']} enabled policies, "
        f"{counts['open_risks']} open risk records, {counts['open_incidents']} open incidents, "
        f"{counts['model_cards']} model cards."
    )
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_governance_reports (
                tenant_id, report_type, period_key, status, summary, findings_json,
                metrics_json, created_by_user_id, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), :report_type, :period_key, 'completed', :summary,
                CAST(:findings_json AS jsonb), CAST(:metrics_json AS jsonb),
                CAST(NULLIF(:user_id, '') AS uuid), NOW()
            )
            ON CONFLICT (tenant_id, report_type, period_key)
            DO UPDATE SET
                status = EXCLUDED.status,
                summary = EXCLUDED.summary,
                findings_json = EXCLUDED.findings_json,
                metrics_json = EXCLUDED.metrics_json,
                created_by_user_id = EXCLUDED.created_by_user_id,
                updated_at = NOW()
            RETURNING id::text, tenant_id::text, report_type, period_key, status, summary,
                      findings_json, metrics_json, created_by_user_id::text, created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "report_type": report_type,
            "period_key": period_key,
            "summary": summary,
            "findings_json": _json(findings),
            "metrics_json": _json({"counts": counts, "source_signals": signals}),
            "user_id": _user_id(user) or "",
        },
    ).mappings().first()
    _audit(conn, tenant_id, "report.generate", actor_user_id=_user_id(user), entity_type="governance_report", entity_id=str(row["id"]), summary=f"Governance report generated: {report_type}/{period_key}")
    return {"ok": True, "report": _row(row)}


def admin_overview(conn: Connection) -> dict[str, Any]:
    ensure_trust_tables(conn)
    tenants = conn.execute(
        text(
            """
            SELECT id::text, name, slug, status, plan_code, industry_code
            FROM saas_tenants
            ORDER BY created_at DESC
            LIMIT 120
            """
        )
    ).mappings().all()
    tenant_rows: list[dict[str, Any]] = []
    aggregate = {
        "tenants": 0,
        "open_risks": 0,
        "high_risks": 0,
        "open_incidents": 0,
        "policies": 0,
        "model_cards": 0,
    }
    for tenant in tenants:
        tenant_id = tenant["id"]
        counts = _counts(conn, tenant_id)
        signals = _source_signals(conn, tenant_id)
        tenant_rows.append({"tenant": dict(tenant), "counts": counts, "source_signals": signals})
        aggregate["tenants"] += 1
        for key in ("open_risks", "high_risks", "open_incidents", "policies", "model_cards"):
            aggregate[key] += int(counts.get(key) or 0)
    recent = conn.execute(
        text(
            """
            SELECT a.id::text, a.tenant_id::text, t.name AS tenant_name, a.event_type,
                   a.entity_type, a.entity_id, a.severity, a.summary, a.metadata_json,
                   a.created_at::text
            FROM saas_ai_governance_audits a
            LEFT JOIN saas_tenants t ON t.id = a.tenant_id
            ORDER BY a.created_at DESC
            LIMIT 80
            """
        )
    ).mappings().all()
    return {
        "ok": True,
        "phase": "phase_22_ai_trust_compliance_governance",
        "aggregate": aggregate,
        "tenants": tenant_rows,
        "recent_audits": [_row(row) for row in recent],
    }
