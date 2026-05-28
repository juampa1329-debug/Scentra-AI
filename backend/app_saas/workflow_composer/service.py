from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app_saas.billing.limits import ensure_tenant_operational
from app_saas.intelligence.service import record_intelligence_usage, resolve_intelligence_access


COMPOSER_FEATURE_KEY = "ai_workflow_composer"
TEMPLATE_FEATURE_KEY = "workflow_composer_templates"
DEMO_FEATURE_KEY = "intelligence_demo"

ALLOWED_NODE_TYPES = {
    "event",
    "condition",
    "ai_decision",
    "approval",
    "action",
    "delay",
    "handoff",
    "end",
}
HIGH_RISK_ACTIONS = {
    "send_whatsapp",
    "send_instagram",
    "launch_campaign",
    "execute_trigger",
    "update_pipeline",
    "assign_agent",
}


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


def _clean(value: Any, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    json_fields = {
        "graph_json",
        "config_json",
        "preflight_json",
        "simulation_json",
        "safety_json",
        "tags_json",
        "snapshot_json",
        "input_json",
        "result_json",
        "approval_json",
    }
    list_fields = {"tags_json"}
    for key in json_fields:
        if key in data:
            data[key] = _json_value(data.get(key), [] if key in list_fields else {})
    return {key: _jsonable(value) for key, value in data.items()}


def _user_id(user: Any) -> str | None:
    value = getattr(user, "user_id", None) or getattr(user, "id", None)
    return str(value) if value else None


def default_graph() -> dict[str, Any]:
    return {
        "nodes": [
            {
                "id": "event_1",
                "type": "event",
                "label": "Lead or customer event",
                "config": {"event_type": "lead.created", "channel": "omnichannel"},
            },
            {
                "id": "decision_1",
                "type": "ai_decision",
                "label": "AI evaluates context and risk",
                "config": {"uses_predictions": True, "uses_memory": True},
            },
            {
                "id": "approval_1",
                "type": "approval",
                "label": "Human approval for customer-facing action",
                "config": {"required": True, "roles": ["owner", "admin"]},
            },
            {
                "id": "action_1",
                "type": "action",
                "label": "Create recommended follow-up",
                "config": {"action_type": "create_task", "priority": "normal"},
            },
            {"id": "end_1", "type": "end", "label": "End workflow", "config": {}},
        ],
        "edges": [
            {"from": "event_1", "to": "decision_1"},
            {"from": "decision_1", "to": "approval_1"},
            {"from": "approval_1", "to": "action_1"},
            {"from": "action_1", "to": "end_1"},
        ],
        "settings": {
            "requires_preflight": True,
            "requires_approval": True,
            "side_effects": "blocked_until_materialized",
        },
    }


DEFAULT_WORKFLOW_TEMPLATES: list[dict[str, Any]] = [
    {
        "template_key": "scentra.lead_qualification.v1",
        "name": "AI Lead Qualification",
        "category": "sales",
        "industry_code": "general",
        "description": "Qualifies new leads, routes hot opportunities, and creates an approved follow-up plan.",
        "tags_json": ["lead_scoring", "crm", "sales"],
        "graph_json": {
            "nodes": [
                {"id": "lead_created", "type": "event", "label": "Lead created", "config": {"event_type": "lead.created"}},
                {"id": "score", "type": "ai_decision", "label": "Predict conversion probability", "config": {"prediction": "lead_scoring"}},
                {"id": "hot_check", "type": "condition", "label": "Score is hot", "config": {"field": "lead_score", "operator": ">=", "value": 75}},
                {"id": "approval", "type": "approval", "label": "Approve outreach", "config": {"required": True}},
                {"id": "task", "type": "action", "label": "Create sales follow-up task", "config": {"action_type": "create_task"}},
                {"id": "end", "type": "end", "label": "End", "config": {}},
            ],
            "edges": [
                {"from": "lead_created", "to": "score"},
                {"from": "score", "to": "hot_check"},
                {"from": "hot_check", "to": "approval"},
                {"from": "approval", "to": "task"},
                {"from": "task", "to": "end"},
            ],
            "settings": {"requires_preflight": True, "requires_approval": True},
        },
        "safety_json": {"risk_level": "medium", "requires_human_approval": True, "side_effects": "draft_only"},
    },
    {
        "template_key": "scentra.churn_recovery.v1",
        "name": "Churn Recovery Workflow",
        "category": "retention",
        "industry_code": "general",
        "description": "Detects inactive customers and proposes a recovery playbook before outbound action.",
        "tags_json": ["churn", "retention", "remarketing"],
        "graph_json": {
            "nodes": [
                {"id": "inactive", "type": "event", "label": "Customer inactive", "config": {"event_type": "customer.inactive"}},
                {"id": "risk", "type": "ai_decision", "label": "Evaluate churn risk", "config": {"prediction": "churn_prediction"}},
                {"id": "approval", "type": "approval", "label": "Approve recovery action", "config": {"required": True}},
                {"id": "recovery", "type": "action", "label": "Create recovery follow-up", "config": {"action_type": "create_task"}},
                {"id": "end", "type": "end", "label": "End", "config": {}},
            ],
            "edges": [
                {"from": "inactive", "to": "risk"},
                {"from": "risk", "to": "approval"},
                {"from": "approval", "to": "recovery"},
                {"from": "recovery", "to": "end"},
            ],
            "settings": {"requires_preflight": True, "requires_approval": True},
        },
        "safety_json": {"risk_level": "medium", "requires_human_approval": True, "side_effects": "draft_only"},
    },
    {
        "template_key": "scentra.campaign_optimization.v1",
        "name": "Campaign Optimization Review",
        "category": "campaigns",
        "industry_code": "general",
        "description": "Reviews low performance campaigns and recommends timing, segment and template changes.",
        "tags_json": ["campaigns", "analytics", "optimization"],
        "graph_json": {
            "nodes": [
                {"id": "low_performance", "type": "event", "label": "Campaign low performance", "config": {"event_type": "campaign.low_performance"}},
                {"id": "analysis", "type": "ai_decision", "label": "Analyze channel, segment and timing", "config": {"uses_recommendations": True}},
                {"id": "approval", "type": "approval", "label": "Approve optimization draft", "config": {"required": True}},
                {"id": "draft", "type": "action", "label": "Draft optimization recommendation", "config": {"action_type": "generate_summary"}},
                {"id": "end", "type": "end", "label": "End", "config": {}},
            ],
            "edges": [
                {"from": "low_performance", "to": "analysis"},
                {"from": "analysis", "to": "approval"},
                {"from": "approval", "to": "draft"},
                {"from": "draft", "to": "end"},
            ],
            "settings": {"requires_preflight": True, "requires_approval": True},
        },
        "safety_json": {"risk_level": "low", "requires_human_approval": True, "side_effects": "recommendation_only"},
    },
    {
        "template_key": "scentra.ops_incident_response.v1",
        "name": "AI Operations Incident Response",
        "category": "operations",
        "industry_code": "general",
        "description": "Turns webhook or queue incidents into diagnosis, approval and controlled remediation plans.",
        "tags_json": ["operations", "self_healing", "observability"],
        "graph_json": {
            "nodes": [
                {"id": "incident", "type": "event", "label": "Operational incident detected", "config": {"event_type": "webhook.failed"}},
                {"id": "diagnose", "type": "ai_decision", "label": "Diagnose root cause", "config": {"uses_observability": True}},
                {"id": "approval", "type": "approval", "label": "Approve remediation", "config": {"required": True}},
                {"id": "playbook", "type": "action", "label": "Create remediation playbook", "config": {"action_type": "create_task"}},
                {"id": "end", "type": "end", "label": "End", "config": {}},
            ],
            "edges": [
                {"from": "incident", "to": "diagnose"},
                {"from": "diagnose", "to": "approval"},
                {"from": "approval", "to": "playbook"},
                {"from": "playbook", "to": "end"},
            ],
            "settings": {"requires_preflight": True, "requires_approval": True},
        },
        "safety_json": {"risk_level": "high", "requires_human_approval": True, "side_effects": "approval_required"},
    },
    {
        "template_key": "nexus.agent_discovery_strategy.v1",
        "name": "Agentic Discovery to Strategy",
        "category": "agents",
        "industry_code": "general",
        "description": "Converts discovery context into a strategy handoff for specialized Scentra agents.",
        "tags_json": ["agents", "nexus", "strategy"],
        "graph_json": {
            "nodes": [
                {"id": "discovery", "type": "event", "label": "Discovery input received", "config": {"event_type": "advisor.requested"}},
                {"id": "router", "type": "ai_decision", "label": "Route to specialist agent", "config": {"uses_agent_orchestrator": True}},
                {"id": "approval", "type": "approval", "label": "Approve specialist handoff", "config": {"required": True}},
                {"id": "handoff", "type": "handoff", "label": "Create agent handoff plan", "config": {"action_type": "assign_agent"}},
                {"id": "end", "type": "end", "label": "End", "config": {}},
            ],
            "edges": [
                {"from": "discovery", "to": "router"},
                {"from": "router", "to": "approval"},
                {"from": "approval", "to": "handoff"},
                {"from": "handoff", "to": "end"},
            ],
            "settings": {"requires_preflight": True, "requires_approval": True, "one_ai_owner": True},
        },
        "safety_json": {"risk_level": "high", "requires_human_approval": True, "one_ai_owner_required": True},
    },
]


def ensure_workflow_composer_tables(conn: Connection) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_workflow_templates (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                template_key TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'general',
                industry_code TEXT NOT NULL DEFAULT 'general',
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'published',
                source TEXT NOT NULL DEFAULT 'scentra',
                required_feature_key TEXT NOT NULL DEFAULT 'workflow_composer_templates',
                graph_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                safety_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                tags_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_workflow_templates_status ON saas_ai_workflow_templates(status)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_workflow_templates_category ON saas_ai_workflow_templates(category)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_workflow_templates_industry ON saas_ai_workflow_templates(industry_code)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_workflows (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft',
                category TEXT NOT NULL DEFAULT 'general',
                channel TEXT NOT NULL DEFAULT 'omnichannel',
                source_template_key TEXT,
                graph_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                preflight_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                simulation_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                version_number INTEGER NOT NULL DEFAULT 1,
                activation_mode TEXT NOT NULL DEFAULT 'composer_only',
                linked_trigger_id UUID REFERENCES saas_crm_triggers(id) ON DELETE SET NULL,
                linked_flow_id UUID REFERENCES saas_remarketing_flows(id) ON DELETE SET NULL,
                approval_status TEXT NOT NULL DEFAULT 'draft',
                approved_by_user_id UUID REFERENCES saas_users(id) ON DELETE SET NULL,
                approved_at TIMESTAMP,
                activated_at TIMESTAMP,
                created_by_user_id UUID REFERENCES saas_users(id) ON DELETE SET NULL,
                updated_by_user_id UUID REFERENCES saas_users(id) ON DELETE SET NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_saas_ai_workflows_tenant_lower_name ON saas_ai_workflows(tenant_id, LOWER(name))"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_workflows_tenant_status ON saas_ai_workflows(tenant_id, status)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_workflows_tenant_category ON saas_ai_workflows(tenant_id, category)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_workflow_versions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                workflow_id UUID NOT NULL REFERENCES saas_ai_workflows(id) ON DELETE CASCADE,
                version_number INTEGER NOT NULL,
                snapshot_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                change_reason TEXT NOT NULL DEFAULT '',
                created_by_user_id UUID REFERENCES saas_users(id) ON DELETE SET NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (tenant_id, workflow_id, version_number)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_workflow_versions_workflow ON saas_ai_workflow_versions(workflow_id, version_number DESC)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_workflow_simulations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                workflow_id UUID REFERENCES saas_ai_workflows(id) ON DELETE CASCADE,
                scenario_key TEXT NOT NULL DEFAULT 'manual',
                status TEXT NOT NULL DEFAULT 'completed',
                input_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_by_user_id UUID REFERENCES saas_users(id) ON DELETE SET NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_workflow_simulations_workflow ON saas_ai_workflow_simulations(workflow_id, created_at DESC)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_workflow_simulations_tenant ON saas_ai_workflow_simulations(tenant_id, created_at DESC)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_workflow_approvals (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                workflow_id UUID NOT NULL REFERENCES saas_ai_workflows(id) ON DELETE CASCADE,
                requested_by_user_id UUID REFERENCES saas_users(id) ON DELETE SET NULL,
                reviewed_by_user_id UUID REFERENCES saas_users(id) ON DELETE SET NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                risk_level TEXT NOT NULL DEFAULT 'medium',
                request_note TEXT NOT NULL DEFAULT '',
                review_note TEXT NOT NULL DEFAULT '',
                approval_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                reviewed_at TIMESTAMP
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_workflow_approvals_workflow ON saas_ai_workflow_approvals(workflow_id, created_at DESC)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_workflow_approvals_tenant_status ON saas_ai_workflow_approvals(tenant_id, status)"))
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS saas_ai_workflow_materializations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
                workflow_id UUID NOT NULL REFERENCES saas_ai_workflows(id) ON DELETE CASCADE,
                target_type TEXT NOT NULL DEFAULT 'composer_only',
                target_id TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_by_user_id UUID REFERENCES saas_users(id) ON DELETE SET NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_workflow_materializations_workflow ON saas_ai_workflow_materializations(workflow_id, created_at DESC)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_saas_ai_workflow_materializations_tenant ON saas_ai_workflow_materializations(tenant_id, target_type)"))


def seed_default_templates(conn: Connection) -> None:
    ensure_workflow_composer_tables(conn)
    for item in DEFAULT_WORKFLOW_TEMPLATES:
        conn.execute(
            text(
                """
                INSERT INTO saas_ai_workflow_templates (
                    template_key, name, category, industry_code, description, status, source,
                    required_feature_key, graph_json, safety_json, tags_json, updated_at
                )
                VALUES (
                    :template_key, :name, :category, :industry_code, :description, 'published', 'scentra',
                    :required_feature_key, CAST(:graph_json AS JSONB), CAST(:safety_json AS JSONB),
                    CAST(:tags_json AS JSONB), NOW()
                )
                ON CONFLICT (template_key) DO UPDATE SET
                    name = EXCLUDED.name,
                    category = EXCLUDED.category,
                    industry_code = EXCLUDED.industry_code,
                    description = EXCLUDED.description,
                    status = EXCLUDED.status,
                    required_feature_key = EXCLUDED.required_feature_key,
                    graph_json = EXCLUDED.graph_json,
                    safety_json = EXCLUDED.safety_json,
                    tags_json = EXCLUDED.tags_json,
                    updated_at = NOW()
                """
            ),
            {
                "template_key": item["template_key"],
                "name": item["name"],
                "category": item["category"],
                "industry_code": item["industry_code"],
                "description": item["description"],
                "required_feature_key": TEMPLATE_FEATURE_KEY,
                "graph_json": _json(item["graph_json"]),
                "safety_json": _json(item.get("safety_json", {})),
                "tags_json": _json(item.get("tags_json", [])),
            },
        )


def _access(conn: Connection, tenant_id: str, feature_key: str = COMPOSER_FEATURE_KEY, *, require_full: bool = False) -> dict[str, Any]:
    try:
        access = resolve_intelligence_access(conn, tenant_id, feature_key, allow_demo=not require_full)
    except HTTPException as exc:
        if require_full:
            raise
        try:
            demo_access = resolve_intelligence_access(conn, tenant_id, DEMO_FEATURE_KEY, allow_demo=True)
            demo_access = dict(demo_access)
            demo_access["feature_key"] = DEMO_FEATURE_KEY
            demo_access["fallback_for"] = feature_key
            demo_access["mode"] = "demo"
            return demo_access
        except HTTPException:
            raise exc
    if require_full and access.get("mode") != "full":
        raise HTTPException(status_code=402, detail=f"{feature_key} requires premium access")
    return access


def _require_full(conn: Connection, tenant_id: str) -> dict[str, Any]:
    ensure_tenant_operational(conn, tenant_id)
    return _access(conn, tenant_id, COMPOSER_FEATURE_KEY, require_full=True)


def _validate_graph(graph: dict[str, Any] | None) -> dict[str, Any]:
    candidate = graph if isinstance(graph, dict) and graph else default_graph()
    nodes = candidate.get("nodes")
    edges = candidate.get("edges")
    if not isinstance(nodes, list):
        nodes = []
    if not isinstance(edges, list):
        edges = []
    normalized_nodes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        node_id = _clean(node.get("id") or f"node_{index + 1}", 80)
        if not node_id or node_id in seen:
            node_id = f"node_{index + 1}"
        seen.add(node_id)
        node_type = _clean(node.get("type") or "action", 40)
        normalized_nodes.append(
            {
                "id": node_id,
                "type": node_type,
                "label": _clean(node.get("label") or node_type.replace("_", " ").title(), 160),
                "config": node.get("config") if isinstance(node.get("config"), dict) else {},
            }
        )
    node_ids = {node["id"] for node in normalized_nodes}
    normalized_edges: list[dict[str, str]] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        source = _clean(edge.get("from"), 80)
        target = _clean(edge.get("to"), 80)
        if source in node_ids and target in node_ids and source != target:
            normalized_edges.append({"from": source, "to": target})
    return {
        "nodes": normalized_nodes,
        "edges": normalized_edges,
        "settings": candidate.get("settings") if isinstance(candidate.get("settings"), dict) else {},
    }


def evaluate_preflight(graph: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = _validate_graph(graph)
    nodes = normalized["nodes"]
    edges = normalized["edges"]
    config = config if isinstance(config, dict) else {}
    checks: list[dict[str, Any]] = []

    def add_check(key: str, ok: bool, severity: str, message: str) -> None:
        checks.append({"key": key, "ok": ok, "severity": severity, "message": message})

    node_ids = {node["id"] for node in nodes}
    unknown_nodes = [node for node in nodes if node.get("type") not in ALLOWED_NODE_TYPES]
    has_event = any(node.get("type") == "event" for node in nodes)
    has_action = any(node.get("type") in {"action", "handoff"} for node in nodes)
    has_approval = any(node.get("type") == "approval" for node in nodes)
    action_types = {
        _clean((node.get("config") or {}).get("action_type"), 80)
        for node in nodes
        if node.get("type") in {"action", "handoff"}
    }
    high_risk_actions = sorted(action_types.intersection(HIGH_RISK_ACTIONS))
    disconnected = sorted(node_ids - {edge["from"] for edge in edges} - {edge["to"] for edge in edges})

    add_check("graph_has_nodes", len(nodes) >= 2, "error", "Workflow needs at least two nodes.")
    add_check("graph_has_edges", len(edges) >= 1, "error", "Workflow needs at least one edge.")
    add_check("has_event", has_event, "error", "Workflow needs a starting event node.")
    add_check("has_action", has_action, "error", "Workflow needs an action or handoff node.")
    add_check("supported_node_types", not unknown_nodes, "error", "Workflow contains unsupported node types.")
    add_check("approval_for_high_risk", not high_risk_actions or has_approval, "error", "High-risk actions require an approval node.")
    add_check("no_direct_secret_usage", not config.get("provider_secret") and not config.get("raw_token"), "error", "Workflow cannot carry provider secrets.")
    add_check("side_effects_are_controlled", has_approval or not high_risk_actions, "warning", "Customer-facing side effects should remain approval-gated.")
    add_check("connected_graph", not disconnected, "warning", "Some nodes are disconnected from the main path.")

    error_count = sum(1 for check in checks if check["severity"] == "error" and not check["ok"])
    warning_count = sum(1 for check in checks if check["severity"] == "warning" and not check["ok"])
    score = max(0, 100 - (error_count * 25) - (warning_count * 8))
    risk_level = "high" if high_risk_actions else ("medium" if warning_count else "low")
    ready = error_count == 0 and score >= 70
    return {
        "status": "ready" if ready else "blocked",
        "ready": ready,
        "score": score,
        "risk_level": risk_level,
        "checks": checks,
        "high_risk_actions": high_risk_actions,
        "generated_at": datetime.utcnow().isoformat(),
    }


def simulate_graph(graph: dict[str, Any], input_json: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = _validate_graph(graph)
    input_json = input_json if isinstance(input_json, dict) else {}
    nodes = normalized["nodes"]
    edges = normalized["edges"]
    outgoing: dict[str, list[str]] = {}
    incoming: dict[str, int] = {node["id"]: 0 for node in nodes}
    for edge in edges:
        outgoing.setdefault(edge["from"], []).append(edge["to"])
        incoming[edge["to"]] = incoming.get(edge["to"], 0) + 1
    queue = [node["id"] for node in nodes if incoming.get(node["id"], 0) == 0] or ([nodes[0]["id"]] if nodes else [])
    visited: list[str] = []
    while queue and len(visited) < len(nodes):
        current = queue.pop(0)
        if current in visited:
            continue
        visited.append(current)
        for target in outgoing.get(current, []):
            queue.append(target)
    node_map = {node["id"]: node for node in nodes}
    actions = []
    blockers = []
    for node_id in visited:
        node = node_map.get(node_id) or {}
        if node.get("type") in {"action", "handoff"}:
            config = node.get("config") or {}
            actions.append(
                {
                    "node_id": node_id,
                    "label": node.get("label"),
                    "action_type": config.get("action_type") or node.get("type"),
                    "side_effect": "blocked_in_simulation",
                }
            )
        if node.get("type") == "approval":
            blockers.append({"node_id": node_id, "reason": "human_approval_required"})
    return {
        "status": "completed",
        "scenario": input_json or {"event_type": "lead.created", "lead_score": 82, "channel": "whatsapp"},
        "visited_nodes": visited,
        "actions_planned": actions,
        "blockers": blockers,
        "side_effects_executed": False,
        "generated_at": datetime.utcnow().isoformat(),
    }


def _fetch_workflow(conn: Connection, tenant_id: str, workflow_id: str) -> dict[str, Any]:
    row = conn.execute(
        text("SELECT * FROM saas_ai_workflows WHERE tenant_id = :tenant_id AND id = :workflow_id"),
        {"tenant_id": tenant_id, "workflow_id": workflow_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="workflow_not_found")
    return _row(row) or {}


def _assert_name_available(conn: Connection, tenant_id: str, name: str, *, exclude_workflow_id: str | None = None) -> None:
    row = conn.execute(
        text(
            """
            SELECT id
            FROM saas_ai_workflows
            WHERE tenant_id = :tenant_id
              AND LOWER(name) = LOWER(:name)
              AND (:exclude_workflow_id IS NULL OR id <> CAST(:exclude_workflow_id AS UUID))
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "name": name, "exclude_workflow_id": exclude_workflow_id},
    ).mappings().first()
    if row:
        raise HTTPException(status_code=409, detail="workflow_name_already_exists")


def _unique_workflow_name(conn: Connection, tenant_id: str, preferred_name: str) -> str:
    base = _clean(preferred_name, 145) or "AI Workflow"
    for index in range(1, 50):
        candidate = base if index == 1 else f"{base} {index}"
        row = conn.execute(
            text(
                """
                SELECT id
                FROM saas_ai_workflows
                WHERE tenant_id = :tenant_id AND LOWER(name) = LOWER(:name)
                LIMIT 1
                """
            ),
            {"tenant_id": tenant_id, "name": candidate},
        ).mappings().first()
        if not row:
            return candidate
    raise HTTPException(status_code=409, detail="workflow_name_already_exists")


def _record_version(
    conn: Connection,
    tenant_id: str,
    workflow: dict[str, Any],
    *,
    user_id: str | None,
    reason: str,
    version_number: int | None = None,
) -> None:
    snapshot = {
        "name": workflow.get("name"),
        "description": workflow.get("description"),
        "status": workflow.get("status"),
        "category": workflow.get("category"),
        "channel": workflow.get("channel"),
        "source_template_key": workflow.get("source_template_key"),
        "graph_json": workflow.get("graph_json") or {},
        "config_json": workflow.get("config_json") or {},
        "preflight_json": workflow.get("preflight_json") or {},
        "approval_status": workflow.get("approval_status"),
    }
    conn.execute(
        text(
            """
            INSERT INTO saas_ai_workflow_versions (
                tenant_id, workflow_id, version_number, snapshot_json, change_reason, created_by_user_id
            )
            VALUES (
                :tenant_id, :workflow_id, :version_number, CAST(:snapshot_json AS JSONB),
                :change_reason, CAST(:created_by_user_id AS UUID)
            )
            ON CONFLICT (tenant_id, workflow_id, version_number) DO NOTHING
            """
        ),
        {
            "tenant_id": tenant_id,
            "workflow_id": workflow["id"],
            "version_number": version_number or int(workflow.get("version_number") or 1),
            "snapshot_json": _json(snapshot),
            "change_reason": reason,
            "created_by_user_id": user_id,
        },
    )


def get_overview(conn: Connection, tenant_id: str) -> dict[str, Any]:
    seed_default_templates(conn)
    access = _access(conn, tenant_id, COMPOSER_FEATURE_KEY)
    template_access = _access(conn, tenant_id, TEMPLATE_FEATURE_KEY)
    counts = conn.execute(
        text(
            """
            SELECT
                COUNT(*)::int AS total_workflows,
                COUNT(*) FILTER (WHERE status = 'active')::int AS active_workflows,
                COUNT(*) FILTER (WHERE approval_status = 'pending')::int AS pending_approvals,
                COUNT(*) FILTER (WHERE preflight_json ->> 'status' = 'blocked')::int AS blocked_preflights
            FROM saas_ai_workflows
            WHERE tenant_id = :tenant_id
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    recent = conn.execute(
        text(
            """
            SELECT id, name, status, approval_status, version_number, updated_at
            FROM saas_ai_workflows
            WHERE tenant_id = :tenant_id
            ORDER BY updated_at DESC
            LIMIT 6
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().all()
    template_count = conn.execute(text("SELECT COUNT(*)::int AS total FROM saas_ai_workflow_templates WHERE status = 'published'")).mappings().first()
    return {
        "phase": "phase_18_ai_workflow_composer",
        "access": access,
        "template_access": template_access,
        "counts": _jsonable(dict(counts or {})),
        "template_count": int((template_count or {}).get("total") or 0),
        "recent_workflows": [_row(item) for item in recent],
        "safety": {
            "side_effect_free_simulation": True,
            "requires_preflight": True,
            "requires_approval_for_activation": True,
            "runtime_materialization": "composer_control_plane",
        },
    }


def list_templates(conn: Connection, tenant_id: str, category: str | None = None, industry_code: str | None = None) -> dict[str, Any]:
    seed_default_templates(conn)
    access = _access(conn, tenant_id, TEMPLATE_FEATURE_KEY)
    params: dict[str, Any] = {"status": "published"}
    clauses = ["status = :status"]
    if category:
        clauses.append("category = :category")
        params["category"] = category
    if industry_code:
        clauses.append("(industry_code = :industry_code OR industry_code = 'general')")
        params["industry_code"] = industry_code
    rows = conn.execute(
        text(
            f"""
            SELECT *
            FROM saas_ai_workflow_templates
            WHERE {' AND '.join(clauses)}
            ORDER BY category, name
            """
        ),
        params,
    ).mappings().all()
    return {"access": access, "templates": [_row(item) for item in rows]}


def list_workflows(conn: Connection, tenant_id: str, status: str | None = None) -> dict[str, Any]:
    ensure_workflow_composer_tables(conn)
    access = _access(conn, tenant_id, COMPOSER_FEATURE_KEY)
    params: dict[str, Any] = {"tenant_id": tenant_id}
    clauses = ["tenant_id = :tenant_id"]
    if status:
        clauses.append("status = :status")
        params["status"] = status
    rows = conn.execute(
        text(
            f"""
            SELECT *
            FROM saas_ai_workflows
            WHERE {' AND '.join(clauses)}
            ORDER BY updated_at DESC
            """
        ),
        params,
    ).mappings().all()
    return {"access": access, "workflows": [_row(item) for item in rows]}


def get_workflow_detail(conn: Connection, tenant_id: str, workflow_id: str) -> dict[str, Any]:
    ensure_workflow_composer_tables(conn)
    access = _access(conn, tenant_id, COMPOSER_FEATURE_KEY)
    workflow = _fetch_workflow(conn, tenant_id, workflow_id)
    approvals = conn.execute(
        text(
            """
            SELECT *
            FROM saas_ai_workflow_approvals
            WHERE tenant_id = :tenant_id AND workflow_id = :workflow_id
            ORDER BY created_at DESC
            LIMIT 10
            """
        ),
        {"tenant_id": tenant_id, "workflow_id": workflow_id},
    ).mappings().all()
    materializations = conn.execute(
        text(
            """
            SELECT *
            FROM saas_ai_workflow_materializations
            WHERE tenant_id = :tenant_id AND workflow_id = :workflow_id
            ORDER BY created_at DESC
            LIMIT 10
            """
        ),
        {"tenant_id": tenant_id, "workflow_id": workflow_id},
    ).mappings().all()
    return {
        "access": access,
        "workflow": workflow,
        "approvals": [_row(item) for item in approvals],
        "materializations": [_row(item) for item in materializations],
    }


def create_workflow(conn: Connection, tenant_id: str, user: Any, payload: Any) -> dict[str, Any]:
    _require_full(conn, tenant_id)
    ensure_workflow_composer_tables(conn)
    workflow_name = _clean(payload.name, 160)
    _assert_name_available(conn, tenant_id, workflow_name)
    graph = _validate_graph(getattr(payload, "graph_json", None))
    config = getattr(payload, "config_json", None) or {}
    preflight = evaluate_preflight(graph, config)
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_workflows (
                tenant_id, name, description, status, category, channel, source_template_key,
                graph_json, config_json, preflight_json, created_by_user_id, updated_by_user_id
            )
            VALUES (
                :tenant_id, :name, :description, 'draft', :category, :channel, :source_template_key,
                CAST(:graph_json AS JSONB), CAST(:config_json AS JSONB), CAST(:preflight_json AS JSONB),
                CAST(:user_id AS UUID), CAST(:user_id AS UUID)
            )
            RETURNING *
            """
        ),
        {
            "tenant_id": tenant_id,
            "name": workflow_name,
            "description": _clean(getattr(payload, "description", ""), 1200),
            "category": _clean(getattr(payload, "category", "") or "general", 80),
            "channel": _clean(getattr(payload, "channel", "") or "omnichannel", 80),
            "source_template_key": _clean(getattr(payload, "source_template_key", ""), 180) or None,
            "graph_json": _json(graph),
            "config_json": _json(config),
            "preflight_json": _json(preflight),
            "user_id": _user_id(user),
        },
    ).mappings().first()
    workflow = _row(row) or {}
    _record_version(conn, tenant_id, workflow, user_id=_user_id(user), reason="created", version_number=1)
    record_intelligence_usage(conn, tenant_id, COMPOSER_FEATURE_KEY, metadata={"operation": "workflow.create"})
    return {"workflow": workflow}


def instantiate_template(conn: Connection, tenant_id: str, user: Any, template_key: str, payload: Any) -> dict[str, Any]:
    _require_full(conn, tenant_id)
    seed_default_templates(conn)
    template = conn.execute(
        text("SELECT * FROM saas_ai_workflow_templates WHERE template_key = :template_key AND status = 'published'"),
        {"template_key": template_key},
    ).mappings().first()
    if not template:
        raise HTTPException(status_code=404, detail="template_not_found")
    template_row = _row(template) or {}
    graph = _validate_graph(template_row.get("graph_json") or {})
    config = payload.config_json if getattr(payload, "config_json", None) else {}
    preflight = evaluate_preflight(graph, config)
    workflow_name = _unique_workflow_name(conn, tenant_id, getattr(payload, "name", None) or template_row["name"])
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_workflows (
                tenant_id, name, description, status, category, channel, source_template_key,
                graph_json, config_json, preflight_json, created_by_user_id, updated_by_user_id
            )
            VALUES (
                :tenant_id, :name, :description, 'draft', :category, 'omnichannel', :source_template_key,
                CAST(:graph_json AS JSONB), CAST(:config_json AS JSONB), CAST(:preflight_json AS JSONB),
                CAST(:user_id AS UUID), CAST(:user_id AS UUID)
            )
            RETURNING *
            """
        ),
        {
            "tenant_id": tenant_id,
            "name": workflow_name,
            "description": _clean(getattr(payload, "description", None) or template_row["description"], 1200),
            "category": template_row.get("category") or "general",
            "source_template_key": template_row["template_key"],
            "graph_json": _json(graph),
            "config_json": _json(config),
            "preflight_json": _json(preflight),
            "user_id": _user_id(user),
        },
    ).mappings().first()
    workflow = _row(row) or {}
    _record_version(conn, tenant_id, workflow, user_id=_user_id(user), reason=f"instantiated:{template_key}", version_number=1)
    record_intelligence_usage(conn, tenant_id, COMPOSER_FEATURE_KEY, metadata={"operation": "template.instantiate", "template_key": template_key})
    return {"template": template_row, "workflow": workflow}


def update_workflow(conn: Connection, tenant_id: str, user: Any, workflow_id: str, payload: Any) -> dict[str, Any]:
    _require_full(conn, tenant_id)
    current = _fetch_workflow(conn, tenant_id, workflow_id)
    before_version = int(current.get("version_number") or 1)
    _record_version(conn, tenant_id, current, user_id=_user_id(user), reason="before_update", version_number=before_version)
    graph_changed = getattr(payload, "graph_json", None) is not None
    config_changed = getattr(payload, "config_json", None) is not None
    graph = _validate_graph(payload.graph_json if graph_changed else current.get("graph_json"))
    config = payload.config_json if config_changed else (current.get("config_json") or {})
    preflight = evaluate_preflight(graph, config)
    workflow_name = _clean(getattr(payload, "name", None) or current.get("name"), 160)
    _assert_name_available(conn, tenant_id, workflow_name, exclude_workflow_id=workflow_id)
    status = _clean(getattr(payload, "status", None) or current.get("status") or "draft", 40)
    if graph_changed or config_changed:
        status = "draft"
    if status not in {"draft", "paused", "archived", "active"}:
        raise HTTPException(status_code=400, detail="invalid_workflow_status")
    approval_status = "draft" if graph_changed or config_changed else current.get("approval_status", "draft")
    if status == "active" and (approval_status != "approved" or not preflight.get("ready")):
        raise HTTPException(status_code=400, detail="workflow_requires_ready_preflight_and_approval")
    row = conn.execute(
        text(
            """
            UPDATE saas_ai_workflows
            SET name = :name,
                description = :description,
                status = :status,
                category = :category,
                channel = :channel,
                graph_json = CAST(:graph_json AS JSONB),
                config_json = CAST(:config_json AS JSONB),
                preflight_json = CAST(:preflight_json AS JSONB),
                approval_status = :approval_status,
                version_number = version_number + 1,
                updated_by_user_id = CAST(:user_id AS UUID),
                updated_at = NOW()
            WHERE tenant_id = :tenant_id AND id = :workflow_id
            RETURNING *
            """
        ),
        {
            "tenant_id": tenant_id,
            "workflow_id": workflow_id,
            "name": workflow_name,
            "description": _clean(getattr(payload, "description", None) if getattr(payload, "description", None) is not None else current.get("description"), 1200),
            "status": status,
            "category": _clean(getattr(payload, "category", None) or current.get("category") or "general", 80),
            "channel": _clean(getattr(payload, "channel", None) or current.get("channel") or "omnichannel", 80),
            "graph_json": _json(graph),
            "config_json": _json(config),
            "preflight_json": _json(preflight),
            "approval_status": approval_status,
            "user_id": _user_id(user),
        },
    ).mappings().first()
    workflow = _row(row) or {}
    _record_version(conn, tenant_id, workflow, user_id=_user_id(user), reason="updated", version_number=int(workflow.get("version_number") or before_version + 1))
    record_intelligence_usage(conn, tenant_id, COMPOSER_FEATURE_KEY, metadata={"operation": "workflow.update"})
    return {"workflow": workflow}


def run_preflight(conn: Connection, tenant_id: str, workflow_id: str) -> dict[str, Any]:
    _require_full(conn, tenant_id)
    workflow = _fetch_workflow(conn, tenant_id, workflow_id)
    preflight = evaluate_preflight(workflow.get("graph_json") or {}, workflow.get("config_json") or {})
    conn.execute(
        text(
            """
            UPDATE saas_ai_workflows
            SET preflight_json = CAST(:preflight_json AS JSONB), updated_at = NOW()
            WHERE tenant_id = :tenant_id AND id = :workflow_id
            """
        ),
        {"tenant_id": tenant_id, "workflow_id": workflow_id, "preflight_json": _json(preflight)},
    )
    record_intelligence_usage(conn, tenant_id, COMPOSER_FEATURE_KEY, metadata={"operation": "workflow.preflight"})
    return {"preflight": preflight}


def run_simulation(conn: Connection, tenant_id: str, user: Any, workflow_id: str, payload: Any) -> dict[str, Any]:
    _require_full(conn, tenant_id)
    workflow = _fetch_workflow(conn, tenant_id, workflow_id)
    result = simulate_graph(workflow.get("graph_json") or {}, getattr(payload, "input_json", {}) or {})
    scenario_key = _clean(getattr(payload, "scenario_key", None) or "manual", 80)
    if getattr(payload, "persist", True):
        conn.execute(
            text(
                """
                INSERT INTO saas_ai_workflow_simulations (
                    tenant_id, workflow_id, scenario_key, status, input_json, result_json, created_by_user_id
                )
                VALUES (
                    :tenant_id, :workflow_id, :scenario_key, :status,
                    CAST(:input_json AS JSONB), CAST(:result_json AS JSONB), CAST(:user_id AS UUID)
                )
                """
            ),
            {
                "tenant_id": tenant_id,
                "workflow_id": workflow_id,
                "scenario_key": scenario_key,
                "status": result["status"],
                "input_json": _json(getattr(payload, "input_json", {}) or {}),
                "result_json": _json(result),
                "user_id": _user_id(user),
            },
        )
    conn.execute(
        text(
            """
            UPDATE saas_ai_workflows
            SET simulation_json = CAST(:simulation_json AS JSONB), updated_at = NOW()
            WHERE tenant_id = :tenant_id AND id = :workflow_id
            """
        ),
        {"tenant_id": tenant_id, "workflow_id": workflow_id, "simulation_json": _json(result)},
    )
    record_intelligence_usage(conn, tenant_id, COMPOSER_FEATURE_KEY, metadata={"operation": "workflow.simulate"})
    return {"simulation": result}


def request_approval(conn: Connection, tenant_id: str, user: Any, workflow_id: str, payload: Any) -> dict[str, Any]:
    _require_full(conn, tenant_id)
    workflow = _fetch_workflow(conn, tenant_id, workflow_id)
    preflight = workflow.get("preflight_json") or evaluate_preflight(workflow.get("graph_json") or {}, workflow.get("config_json") or {})
    if not preflight.get("ready"):
        raise HTTPException(status_code=400, detail="workflow_preflight_not_ready")
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_workflow_approvals (
                tenant_id, workflow_id, requested_by_user_id, status, risk_level, request_note, approval_json
            )
            VALUES (
                :tenant_id, :workflow_id, CAST(:user_id AS UUID), 'pending', :risk_level,
                :request_note, CAST(:approval_json AS JSONB)
            )
            RETURNING *
            """
        ),
        {
            "tenant_id": tenant_id,
            "workflow_id": workflow_id,
            "user_id": _user_id(user),
            "risk_level": preflight.get("risk_level") or "medium",
            "request_note": _clean(getattr(payload, "note", "") or "", 1200),
            "approval_json": _json({"preflight": preflight}),
        },
    ).mappings().first()
    conn.execute(
        text(
            """
            UPDATE saas_ai_workflows
            SET approval_status = 'pending', updated_at = NOW()
            WHERE tenant_id = :tenant_id AND id = :workflow_id
            """
        ),
        {"tenant_id": tenant_id, "workflow_id": workflow_id},
    )
    record_intelligence_usage(conn, tenant_id, COMPOSER_FEATURE_KEY, metadata={"operation": "workflow.approval.request"})
    return {"approval": _row(row)}


def review_approval(conn: Connection, tenant_id: str, user: Any, workflow_id: str, payload: Any) -> dict[str, Any]:
    _require_full(conn, tenant_id)
    status = _clean(getattr(payload, "status", ""), 30).lower()
    if status not in {"approved", "rejected"}:
        raise HTTPException(status_code=400, detail="invalid_approval_status")
    workflow = _fetch_workflow(conn, tenant_id, workflow_id)
    preflight = workflow.get("preflight_json") or {}
    if status == "approved" and not preflight.get("ready"):
        raise HTTPException(status_code=400, detail="workflow_preflight_not_ready")
    approval = conn.execute(
        text(
            """
            SELECT *
            FROM saas_ai_workflow_approvals
            WHERE tenant_id = :tenant_id AND workflow_id = :workflow_id AND status = 'pending'
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "workflow_id": workflow_id},
    ).mappings().first()
    if not approval:
        raise HTTPException(status_code=404, detail="pending_approval_not_found")
    row = conn.execute(
        text(
            """
            UPDATE saas_ai_workflow_approvals
            SET status = :status,
                reviewed_by_user_id = CAST(:user_id AS UUID),
                review_note = :review_note,
                reviewed_at = NOW()
            WHERE id = :approval_id
            RETURNING *
            """
        ),
        {
            "approval_id": approval["id"],
            "status": status,
            "user_id": _user_id(user),
            "review_note": _clean(getattr(payload, "note", "") or "", 1200),
        },
    ).mappings().first()
    conn.execute(
        text(
            """
            UPDATE saas_ai_workflows
            SET approval_status = :approval_status,
                approved_by_user_id = CASE WHEN :approval_status = 'approved' THEN CAST(:user_id AS UUID) ELSE approved_by_user_id END,
                approved_at = CASE WHEN :approval_status = 'approved' THEN NOW() ELSE approved_at END,
                updated_at = NOW()
            WHERE tenant_id = :tenant_id AND id = :workflow_id
            """
        ),
        {"tenant_id": tenant_id, "workflow_id": workflow_id, "approval_status": status, "user_id": _user_id(user)},
    )
    record_intelligence_usage(conn, tenant_id, COMPOSER_FEATURE_KEY, metadata={"operation": "workflow.approval.review", "status": status})
    return {"approval": _row(row), "workflow": _fetch_workflow(conn, tenant_id, workflow_id)}


def materialize_workflow(conn: Connection, tenant_id: str, user: Any, workflow_id: str, payload: Any) -> dict[str, Any]:
    _require_full(conn, tenant_id)
    workflow = _fetch_workflow(conn, tenant_id, workflow_id)
    target_type = _clean(getattr(payload, "target_type", None) or "composer_only", 80)
    if target_type != "composer_only":
        raise HTTPException(status_code=400, detail="only_composer_control_plane_materialization_is_supported")
    preflight = workflow.get("preflight_json") or {}
    if not preflight.get("ready"):
        raise HTTPException(status_code=400, detail="workflow_preflight_not_ready")
    if workflow.get("approval_status") != "approved":
        raise HTTPException(status_code=400, detail="workflow_requires_approval")
    result = {
        "target_type": target_type,
        "target_id": str(workflow_id),
        "side_effects": "none",
        "note": "Workflow activated in Composer control-plane. Runtime deployment remains approval-gated.",
    }
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_workflow_materializations (
                tenant_id, workflow_id, target_type, target_id, status, result_json, created_by_user_id
            )
            VALUES (
                :tenant_id, :workflow_id, :target_type, :target_id, 'active',
                CAST(:result_json AS JSONB), CAST(:user_id AS UUID)
            )
            RETURNING *
            """
        ),
        {
            "tenant_id": tenant_id,
            "workflow_id": workflow_id,
            "target_type": target_type,
            "target_id": str(workflow_id),
            "result_json": _json(result),
            "user_id": _user_id(user),
        },
    ).mappings().first()
    record_intelligence_usage(conn, tenant_id, COMPOSER_FEATURE_KEY, metadata={"operation": "workflow.materialize", "target_type": target_type})
    return {"materialization": _row(row), "result": result}


def activate_workflow(conn: Connection, tenant_id: str, user: Any, workflow_id: str) -> dict[str, Any]:
    materialization = materialize_workflow(conn, tenant_id, user, workflow_id, type("Payload", (), {"target_type": "composer_only"})())
    row = conn.execute(
        text(
            """
            UPDATE saas_ai_workflows
            SET status = 'active', activated_at = NOW(), updated_at = NOW(), updated_by_user_id = CAST(:user_id AS UUID)
            WHERE tenant_id = :tenant_id AND id = :workflow_id
            RETURNING *
            """
        ),
        {"tenant_id": tenant_id, "workflow_id": workflow_id, "user_id": _user_id(user)},
    ).mappings().first()
    return {"workflow": _row(row), **materialization}


def list_versions(conn: Connection, tenant_id: str, workflow_id: str) -> dict[str, Any]:
    ensure_workflow_composer_tables(conn)
    _fetch_workflow(conn, tenant_id, workflow_id)
    rows = conn.execute(
        text(
            """
            SELECT *
            FROM saas_ai_workflow_versions
            WHERE tenant_id = :tenant_id AND workflow_id = :workflow_id
            ORDER BY version_number DESC, created_at DESC
            """
        ),
        {"tenant_id": tenant_id, "workflow_id": workflow_id},
    ).mappings().all()
    return {"versions": [_row(item) for item in rows]}


def restore_version(conn: Connection, tenant_id: str, user: Any, workflow_id: str, version_id: str, payload: Any) -> dict[str, Any]:
    _require_full(conn, tenant_id)
    current = _fetch_workflow(conn, tenant_id, workflow_id)
    version = conn.execute(
        text(
            """
            SELECT *
            FROM saas_ai_workflow_versions
            WHERE tenant_id = :tenant_id AND workflow_id = :workflow_id AND id = :version_id
            """
        ),
        {"tenant_id": tenant_id, "workflow_id": workflow_id, "version_id": version_id},
    ).mappings().first()
    if not version:
        raise HTTPException(status_code=404, detail="version_not_found")
    next_version = int(current.get("version_number") or 1) + 1
    _record_version(conn, tenant_id, current, user_id=_user_id(user), reason="before_restore", version_number=int(current.get("version_number") or 1))
    snapshot = _json_value(version["snapshot_json"], {})
    graph = _validate_graph(snapshot.get("graph_json") or {})
    config = snapshot.get("config_json") if isinstance(snapshot.get("config_json"), dict) else {}
    preflight = evaluate_preflight(graph, config)
    row = conn.execute(
        text(
            """
            UPDATE saas_ai_workflows
            SET name = :name,
                description = :description,
                status = 'draft',
                category = :category,
                channel = :channel,
                source_template_key = :source_template_key,
                graph_json = CAST(:graph_json AS JSONB),
                config_json = CAST(:config_json AS JSONB),
                preflight_json = CAST(:preflight_json AS JSONB),
                approval_status = 'draft',
                version_number = :version_number,
                updated_by_user_id = CAST(:user_id AS UUID),
                updated_at = NOW()
            WHERE tenant_id = :tenant_id AND id = :workflow_id
            RETURNING *
            """
        ),
        {
            "tenant_id": tenant_id,
            "workflow_id": workflow_id,
            "name": snapshot.get("name") or current.get("name"),
            "description": snapshot.get("description") or current.get("description") or "",
            "category": snapshot.get("category") or current.get("category") or "general",
            "channel": snapshot.get("channel") or current.get("channel") or "omnichannel",
            "source_template_key": snapshot.get("source_template_key") or current.get("source_template_key"),
            "graph_json": _json(graph),
            "config_json": _json(config),
            "preflight_json": _json(preflight),
            "version_number": next_version,
            "user_id": _user_id(user),
        },
    ).mappings().first()
    workflow = _row(row) or {}
    _record_version(
        conn,
        tenant_id,
        workflow,
        user_id=_user_id(user),
        reason=_clean(getattr(payload, "note", "") or "restored", 1200),
        version_number=next_version,
    )
    record_intelligence_usage(conn, tenant_id, COMPOSER_FEATURE_KEY, metadata={"operation": "workflow.version.restore"})
    return {"workflow": workflow}
