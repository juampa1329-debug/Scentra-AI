from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app_saas.agents.service import create_from_template
from app_saas.verticals.catalog import get_industry_pack, list_industry_packs, normalize_industry_code, pack_summary


def _clean(value: Any, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _json(value: Any, fallback: Any) -> str:
    if value is None:
        value = fallback
    return json.dumps(value, ensure_ascii=False, default=str)


def public_pack_summaries() -> list[dict[str, Any]]:
    return [pack_summary(pack) for pack in list_industry_packs()]


def tenant_vertical_state(conn: Connection, tenant_id: str) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            SELECT
                id::text AS tenant_id,
                slug,
                name,
                status,
                plan_code,
                industry_code,
                vertical_pack_version,
                vertical_pack_json,
                vertical_pack_applied_at::text
            FROM saas_tenants
            WHERE id = CAST(:tenant_id AS uuid)
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="tenant_not_found")
    tenant = dict(row)
    code = normalize_industry_code(tenant.get("industry_code"))
    pack = get_industry_pack(code)
    return {
        "tenant": tenant,
        "current_pack": pack_summary(pack),
        "kpis": vertical_kpis(conn, tenant_id),
        "last_applications": last_applications(conn, tenant_id),
    }


def last_applications(conn: Connection, tenant_id: str, limit: int = 8) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT
                id::text,
                industry_code,
                pack_version,
                created_agents,
                result_json,
                created_at::text
            FROM saas_vertical_pack_applications
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "limit": max(1, min(int(limit), 50))},
    ).mappings().all()
    return [dict(row) for row in rows]


def vertical_kpis(conn: Connection, tenant_id: str) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            SELECT
                (SELECT COUNT(*)::int FROM saas_crm_pipeline_stages s WHERE s.tenant_id = CAST(:tenant_id AS uuid) AND s.is_active = TRUE) AS pipeline_stages,
                (SELECT COUNT(*)::int FROM saas_crm_custom_fields f WHERE f.tenant_id = CAST(:tenant_id AS uuid) AND f.is_active = TRUE) AS custom_fields,
                (SELECT COUNT(*)::int FROM saas_message_templates mt WHERE mt.tenant_id = CAST(:tenant_id AS uuid) AND mt.template_scope = 'crm') AS templates,
                (SELECT COUNT(*)::int FROM saas_segments sg WHERE sg.tenant_id = CAST(:tenant_id AS uuid)) AS segments,
                (SELECT COUNT(*)::int FROM saas_crm_triggers tr WHERE tr.tenant_id = CAST(:tenant_id AS uuid)) AS triggers,
                (SELECT COUNT(*)::int FROM saas_crm_triggers tr WHERE tr.tenant_id = CAST(:tenant_id AS uuid) AND tr.is_active = TRUE) AS active_triggers,
                (SELECT COUNT(*)::int FROM saas_remarketing_flows fl WHERE fl.tenant_id = CAST(:tenant_id AS uuid)) AS flows,
                (SELECT COUNT(*)::int FROM saas_remarketing_flows fl WHERE fl.tenant_id = CAST(:tenant_id AS uuid) AND fl.status = 'active') AS active_flows,
                (SELECT COUNT(*)::int FROM saas_ai_agents aa WHERE aa.tenant_id = CAST(:tenant_id AS uuid) AND aa.status <> 'archived') AS agents,
                (SELECT COUNT(*)::int FROM saas_ai_agents aa WHERE aa.tenant_id = CAST(:tenant_id AS uuid) AND aa.status = 'active') AS active_agents
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    return dict(row or {})


def _apply_pipeline(conn: Connection, tenant_id: str, user_id: str, pack: dict[str, Any]) -> dict[str, Any]:
    pipeline = conn.execute(
        text(
            """
            SELECT id::text, name, industry_code, is_default
            FROM saas_crm_pipelines
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND is_default = TRUE
            ORDER BY created_at ASC
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    if pipeline:
        pipeline = conn.execute(
            text(
                """
                UPDATE saas_crm_pipelines
                SET industry_code = :industry_code,
                    updated_at = NOW()
                WHERE id = CAST(:pipeline_id AS uuid)
                  AND tenant_id = CAST(:tenant_id AS uuid)
                RETURNING id::text, name, industry_code, is_default
                """
            ),
            {"tenant_id": tenant_id, "pipeline_id": pipeline["id"], "industry_code": pack["code"]},
        ).mappings().first()
    else:
        pipeline = conn.execute(
            text(
                """
                INSERT INTO saas_crm_pipelines (tenant_id, name, industry_code, is_default, created_by_user_id)
                VALUES (
                    CAST(:tenant_id AS uuid),
                    'Pipeline comercial',
                    :industry_code,
                    TRUE,
                    CAST(NULLIF(:user_id, '') AS uuid)
                )
                RETURNING id::text, name, industry_code, is_default
                """
            ),
            {"tenant_id": tenant_id, "industry_code": pack["code"], "user_id": user_id or ""},
        ).mappings().first()
    if not pipeline:
        raise HTTPException(status_code=500, detail="vertical_pipeline_unavailable")
    conn.execute(
        text(
            """
            UPDATE saas_crm_pipeline_stages
            SET is_active = FALSE,
                updated_at = NOW()
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND pipeline_id = CAST(:pipeline_id AS uuid)
            """
        ),
        {"tenant_id": tenant_id, "pipeline_id": pipeline["id"]},
    )
    for stage in pack.get("pipeline") or []:
        conn.execute(
            text(
                """
                INSERT INTO saas_crm_pipeline_stages (
                    tenant_id, pipeline_id, stage_key, label, probability,
                    display_order, is_won, is_lost, is_active
                )
                VALUES (
                    CAST(:tenant_id AS uuid), CAST(:pipeline_id AS uuid), :stage_key, :label,
                    :probability, :display_order, :is_won, :is_lost, TRUE
                )
                ON CONFLICT (tenant_id, pipeline_id, stage_key)
                DO UPDATE SET
                    label = EXCLUDED.label,
                    probability = EXCLUDED.probability,
                    display_order = EXCLUDED.display_order,
                    is_won = EXCLUDED.is_won,
                    is_lost = EXCLUDED.is_lost,
                    is_active = TRUE,
                    updated_at = NOW()
                """
            ),
            {
                "tenant_id": tenant_id,
                "pipeline_id": pipeline["id"],
                "stage_key": _clean(stage.get("stage_key"), 80),
                "label": _clean(stage.get("label"), 120),
                "probability": int(stage.get("probability") or 0),
                "display_order": int(stage.get("display_order") or 100),
                "is_won": bool(stage.get("is_won")),
                "is_lost": bool(stage.get("is_lost")),
            },
        )
    return {"id": pipeline["id"], "stages": len(pack.get("pipeline") or [])}


def _upsert_custom_fields(conn: Connection, tenant_id: str, user_id: str, pack: dict[str, Any]) -> int:
    count = 0
    for field in pack.get("custom_fields") or []:
        conn.execute(
            text(
                """
                INSERT INTO saas_crm_custom_fields (
                    tenant_id, field_key, label, field_type, options_json,
                    is_required, is_active, display_order, created_by_user_id
                )
                VALUES (
                    CAST(:tenant_id AS uuid), :field_key, :label, :field_type,
                    CAST(:options_json AS jsonb), :is_required, TRUE, :display_order,
                    CAST(NULLIF(:user_id, '') AS uuid)
                )
                ON CONFLICT (tenant_id, field_key)
                DO UPDATE SET
                    label = EXCLUDED.label,
                    field_type = EXCLUDED.field_type,
                    options_json = EXCLUDED.options_json,
                    is_required = EXCLUDED.is_required,
                    is_active = TRUE,
                    display_order = EXCLUDED.display_order,
                    updated_at = NOW()
                """
            ),
            {
                "tenant_id": tenant_id,
                "field_key": _clean(field.get("field_key"), 80).lower(),
                "label": _clean(field.get("label"), 120),
                "field_type": _clean(field.get("field_type"), 40).lower() or "text",
                "options_json": _json(field.get("options_json"), []),
                "is_required": bool(field.get("is_required")),
                "display_order": int(field.get("display_order") or 100),
                "user_id": user_id or "",
            },
        )
        count += 1
    return count


def _upsert_labels(conn: Connection, tenant_id: str, pack: dict[str, Any]) -> int:
    count = 0
    for label in pack.get("labels") or []:
        conn.execute(
            text(
                """
                INSERT INTO saas_labels (tenant_id, name, color, description, category, is_active)
                VALUES (CAST(:tenant_id AS uuid), :name, :color, :description, :category, TRUE)
                ON CONFLICT (tenant_id, lower(name))
                DO UPDATE SET
                    color = EXCLUDED.color,
                    description = EXCLUDED.description,
                    category = EXCLUDED.category,
                    is_active = TRUE,
                    updated_at = NOW()
                """
            ),
            {
                "tenant_id": tenant_id,
                "name": _clean(label.get("name"), 120),
                "color": _clean(label.get("color"), 20) or "#5eead4",
                "description": _clean(label.get("description"), 500),
                "category": _clean(label.get("category"), 80) or "vertical",
            },
        )
        count += 1
    return count


def _upsert_templates(conn: Connection, tenant_id: str, user_id: str, pack: dict[str, Any]) -> int:
    count = 0
    for template in pack.get("templates") or []:
        conn.execute(
            text(
                """
                INSERT INTO saas_message_templates (
                    tenant_id, name, channel, category, status, body,
                    variables_json, blocks_json, params_json, render_mode,
                    template_scope, source, created_by_user_id
                )
                VALUES (
                    CAST(:tenant_id AS uuid), :name, :channel, :category, :status, :body,
                    CAST(:variables_json AS jsonb), CAST(:blocks_json AS jsonb),
                    CAST(:params_json AS jsonb), :render_mode, :template_scope, :source,
                    CAST(NULLIF(:user_id, '') AS uuid)
                )
                ON CONFLICT (tenant_id, channel, lower(name))
                DO UPDATE SET
                    category = EXCLUDED.category,
                    params_json = saas_message_templates.params_json || EXCLUDED.params_json,
                    updated_at = NOW()
                """
            ),
            {
                "tenant_id": tenant_id,
                "name": _clean(template.get("name"), 140),
                "channel": _clean(template.get("channel"), 40).lower() or "whatsapp",
                "category": _clean(template.get("category"), 80) or "vertical_pack",
                "status": _clean(template.get("status"), 40).lower() or "draft",
                "body": _clean(template.get("body"), 8000),
                "variables_json": _json(template.get("variables_json"), []),
                "blocks_json": _json(template.get("blocks_json"), []),
                "params_json": _json(template.get("params_json"), {}),
                "render_mode": _clean(template.get("render_mode"), 40) or "chat",
                "template_scope": _clean(template.get("template_scope"), 40) or "crm",
                "source": _clean(template.get("source"), 80) or "vertical_pack",
                "user_id": user_id or "",
            },
        )
        count += 1
    return count


def _upsert_segments(conn: Connection, tenant_id: str, user_id: str, pack: dict[str, Any]) -> int:
    count = 0
    for segment in pack.get("segments") or []:
        conn.execute(
            text(
                """
                INSERT INTO saas_segments (tenant_id, name, description, filters_json, created_by_user_id)
                VALUES (
                    CAST(:tenant_id AS uuid), :name, :description,
                    CAST(:filters_json AS jsonb), CAST(NULLIF(:user_id, '') AS uuid)
                )
                ON CONFLICT (tenant_id, lower(name))
                DO UPDATE SET
                    description = EXCLUDED.description,
                    filters_json = EXCLUDED.filters_json,
                    updated_at = NOW()
                """
            ),
            {
                "tenant_id": tenant_id,
                "name": _clean(segment.get("name"), 140),
                "description": _clean(segment.get("description"), 800),
                "filters_json": _json(segment.get("filters_json"), {}),
                "user_id": user_id or "",
            },
        )
        count += 1
    return count


def _upsert_triggers(conn: Connection, tenant_id: str, user_id: str, pack: dict[str, Any]) -> int:
    count = 0
    for trigger in pack.get("triggers") or []:
        conn.execute(
            text(
                """
                INSERT INTO saas_crm_triggers (
                    tenant_id, name, channel, event_type, trigger_type, flow_event,
                    conditions_json, actions_json, priority, cooldown_minutes, is_active,
                    assistant_enabled, assistant_message_type, block_ai, stop_on_match,
                    only_when_no_takeover, quiet_hours_json, ab_test_json, preflight_json,
                    last_preflight_at, revision_note, created_by_user_id
                )
                VALUES (
                    CAST(:tenant_id AS uuid), :name, :channel, :event_type, :trigger_type, :flow_event,
                    CAST(:conditions_json AS jsonb), CAST(:actions_json AS jsonb), :priority,
                    :cooldown_minutes, :is_active, :assistant_enabled, :assistant_message_type,
                    :block_ai, :stop_on_match, :only_when_no_takeover, CAST(:quiet_hours_json AS jsonb),
                    CAST(:ab_test_json AS jsonb), CAST(:preflight_json AS jsonb), NOW(), :revision_note,
                    CAST(NULLIF(:user_id, '') AS uuid)
                )
                ON CONFLICT (tenant_id, channel, lower(name))
                DO UPDATE SET
                    conditions_json = EXCLUDED.conditions_json,
                    actions_json = EXCLUDED.actions_json,
                    priority = EXCLUDED.priority,
                    cooldown_minutes = EXCLUDED.cooldown_minutes,
                    assistant_enabled = EXCLUDED.assistant_enabled,
                    assistant_message_type = EXCLUDED.assistant_message_type,
                    block_ai = EXCLUDED.block_ai,
                    stop_on_match = EXCLUDED.stop_on_match,
                    only_when_no_takeover = EXCLUDED.only_when_no_takeover,
                    quiet_hours_json = EXCLUDED.quiet_hours_json,
                    ab_test_json = EXCLUDED.ab_test_json,
                    preflight_json = EXCLUDED.preflight_json,
                    last_preflight_at = NOW(),
                    revision_note = EXCLUDED.revision_note,
                    updated_at = NOW()
                """
            ),
            {
                "tenant_id": tenant_id,
                "name": _clean(trigger.get("name"), 160),
                "channel": _clean(trigger.get("channel"), 40).lower() or "whatsapp",
                "event_type": _clean(trigger.get("event_type"), 80).lower() or "message_in",
                "trigger_type": _clean(trigger.get("trigger_type"), 80).lower() or "message_flow",
                "flow_event": _clean(trigger.get("flow_event"), 40).lower() or "received",
                "conditions_json": _json(trigger.get("conditions_json"), {"conditions": []}),
                "actions_json": _json(trigger.get("actions_json"), {"actions": []}),
                "priority": int(trigger.get("priority") or 100),
                "cooldown_minutes": int(trigger.get("cooldown_minutes") or 60),
                "is_active": bool(trigger.get("is_active")),
                "assistant_enabled": bool(trigger.get("assistant_enabled")),
                "assistant_message_type": _clean(trigger.get("assistant_message_type"), 40) or "auto",
                "block_ai": bool(trigger.get("block_ai")),
                "stop_on_match": bool(trigger.get("stop_on_match")),
                "only_when_no_takeover": bool(trigger.get("only_when_no_takeover")),
                "quiet_hours_json": _json(trigger.get("quiet_hours_json"), {}),
                "ab_test_json": _json(trigger.get("ab_test_json"), {}),
                "preflight_json": _json({"status": "draft", "ready": False, "source": "vertical_pack"}, {}),
                "revision_note": _clean(trigger.get("revision_note"), 500) or "vertical_pack_phase10",
                "user_id": user_id or "",
            },
        )
        count += 1
    return count


def _upsert_flows(conn: Connection, tenant_id: str, user_id: str, pack: dict[str, Any]) -> int:
    count = 0
    for flow in pack.get("flows") or []:
        conn.execute(
            text(
                """
                INSERT INTO saas_remarketing_flows (
                    tenant_id, name, description, channel, status,
                    entry_rules_json, exit_rules_json, steps_json,
                    quiet_hours_json, ab_test_json, preflight_json,
                    last_preflight_at, created_by_user_id
                )
                VALUES (
                    CAST(:tenant_id AS uuid), :name, :description, :channel, :status,
                    CAST(:entry_rules_json AS jsonb), CAST(:exit_rules_json AS jsonb),
                    CAST(:steps_json AS jsonb), CAST(:quiet_hours_json AS jsonb),
                    CAST(:ab_test_json AS jsonb), CAST(:preflight_json AS jsonb),
                    NOW(), CAST(NULLIF(:user_id, '') AS uuid)
                )
                ON CONFLICT (tenant_id, channel, lower(name))
                DO UPDATE SET
                    description = EXCLUDED.description,
                    entry_rules_json = EXCLUDED.entry_rules_json,
                    exit_rules_json = EXCLUDED.exit_rules_json,
                    steps_json = EXCLUDED.steps_json,
                    quiet_hours_json = EXCLUDED.quiet_hours_json,
                    ab_test_json = EXCLUDED.ab_test_json,
                    preflight_json = EXCLUDED.preflight_json,
                    last_preflight_at = NOW(),
                    updated_at = NOW()
                """
            ),
            {
                "tenant_id": tenant_id,
                "name": _clean(flow.get("name"), 160),
                "description": _clean(flow.get("description"), 1000),
                "channel": _clean(flow.get("channel"), 40).lower() or "whatsapp",
                "status": _clean(flow.get("status"), 40).lower() or "draft",
                "entry_rules_json": _json(flow.get("entry_rules_json"), {}),
                "exit_rules_json": _json(flow.get("exit_rules_json"), {}),
                "steps_json": _json(flow.get("steps_json"), []),
                "quiet_hours_json": _json(flow.get("quiet_hours_json"), {}),
                "ab_test_json": _json(flow.get("ab_test_json"), {}),
                "preflight_json": _json({"status": "draft", "ready": False, "source": "vertical_pack"}, {}),
                "user_id": user_id or "",
            },
        )
        count += 1
    return count


def _upsert_quiet_hours(conn: Connection, tenant_id: str, user_id: str, pack: dict[str, Any]) -> int:
    quiet = pack.get("quiet_hours") or {}
    conn.execute(
        text(
            """
            INSERT INTO saas_campaign_quiet_hours (
                tenant_id, channel, entity_type, enabled, timezone,
                start_time, end_time, days_json, created_by_user_id
            )
            VALUES (
                CAST(:tenant_id AS uuid), :channel, :entity_type, :enabled, :timezone,
                :start_time, :end_time, CAST(:days_json AS jsonb), CAST(NULLIF(:user_id, '') AS uuid)
            )
            ON CONFLICT (tenant_id, channel, entity_type)
            DO UPDATE SET
                timezone = EXCLUDED.timezone,
                start_time = EXCLUDED.start_time,
                end_time = EXCLUDED.end_time,
                days_json = EXCLUDED.days_json,
                updated_at = NOW()
            """
        ),
        {
            "tenant_id": tenant_id,
            "channel": _clean(quiet.get("channel"), 40).lower() or "all",
            "entity_type": _clean(quiet.get("entity_type"), 40).lower() or "all",
            "enabled": bool(quiet.get("enabled")),
            "timezone": _clean(quiet.get("timezone"), 80) or "America/Bogota",
            "start_time": _clean(quiet.get("start_time"), 10) or "21:00",
            "end_time": _clean(quiet.get("end_time"), 10) or "08:00",
            "days_json": _json(quiet.get("days_json"), ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]),
            "user_id": user_id or "",
        },
    )
    return 1


def _existing_agent(conn: Connection, tenant_id: str, agent_type: str) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            """
            SELECT id::text, agent_type, name, status
            FROM saas_ai_agents
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND agent_type = :agent_type
              AND status <> 'archived'
            ORDER BY created_at ASC
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "agent_type": agent_type},
    ).mappings().first()
    return dict(row) if row else None


def _create_recommended_agents(conn: Connection, tenant_id: str, user_id: str, pack: dict[str, Any], create_agents: bool) -> dict[str, Any]:
    result: dict[str, Any] = {"requested": bool(create_agents), "created": [], "existing": [], "skipped": [], "errors": []}
    for agent_type in pack.get("agent_types") or []:
        agent_type = _clean(agent_type, 80)
        if not agent_type or agent_type == "custom":
            result["skipped"].append({"agent_type": agent_type or "unknown", "reason": "custom_agent_created_manually"})
            continue
        existing = _existing_agent(conn, tenant_id, agent_type)
        if existing:
            result["existing"].append(existing)
            continue
        if not create_agents:
            result["skipped"].append({"agent_type": agent_type, "reason": "create_agents_false"})
            continue
        try:
            with conn.begin_nested():
                result["created"].append(create_from_template(conn, tenant_id, user_id, agent_type))
        except HTTPException as exc:
            result["errors"].append({"agent_type": agent_type, "detail": exc.detail})
        except Exception as exc:
            result["errors"].append({"agent_type": agent_type, "detail": str(exc)[:300]})
    return result


def apply_industry_pack(conn: Connection, tenant_id: str, user_id: str, industry_code: str, create_agents: bool = False) -> dict[str, Any]:
    pack = get_industry_pack(industry_code)
    result: dict[str, Any] = {
        "pipeline": _apply_pipeline(conn, tenant_id, user_id, pack),
        "custom_fields": _upsert_custom_fields(conn, tenant_id, user_id, pack),
        "labels": _upsert_labels(conn, tenant_id, pack),
        "templates": _upsert_templates(conn, tenant_id, user_id, pack),
        "segments": _upsert_segments(conn, tenant_id, user_id, pack),
        "triggers": _upsert_triggers(conn, tenant_id, user_id, pack),
        "flows": _upsert_flows(conn, tenant_id, user_id, pack),
        "quiet_hours": _upsert_quiet_hours(conn, tenant_id, user_id, pack),
    }
    result["agents"] = _create_recommended_agents(conn, tenant_id, user_id, pack, create_agents)
    snapshot = {
        **pack_summary(pack),
        "applied_resources": {key: value for key, value in result.items() if key != "agents"},
        "agent_recommendations": result["agents"],
    }
    conn.execute(
        text(
            """
            UPDATE saas_tenants
            SET industry_code = :industry_code,
                vertical_pack_version = :pack_version,
                vertical_pack_json = CAST(:vertical_pack_json AS jsonb),
                vertical_pack_applied_at = NOW(),
                updated_at = NOW()
            WHERE id = CAST(:tenant_id AS uuid)
            """
        ),
        {
            "tenant_id": tenant_id,
            "industry_code": pack["code"],
            "pack_version": int(pack.get("pack_version") or 1),
            "vertical_pack_json": _json(snapshot, {}),
        },
    )
    conn.execute(
        text(
            """
            INSERT INTO saas_vertical_pack_applications (
                tenant_id, industry_code, pack_version, applied_by_user_id,
                created_agents, result_json
            )
            VALUES (
                CAST(:tenant_id AS uuid), :industry_code, :pack_version,
                CAST(NULLIF(:user_id, '') AS uuid), :created_agents,
                CAST(:result_json AS jsonb)
            )
            """
        ),
        {
            "tenant_id": tenant_id,
            "industry_code": pack["code"],
            "pack_version": int(pack.get("pack_version") or 1),
            "user_id": user_id or "",
            "created_agents": bool(create_agents),
            "result_json": _json(result, {}),
        },
    )
    conn.execute(
        text(
            """
            INSERT INTO saas_audit_events (tenant_id, actor_user_id, action, resource_type, resource_id, details_json)
            VALUES (
                CAST(:tenant_id AS uuid),
                CAST(NULLIF(:user_id, '') AS uuid),
                'vertical_pack.apply',
                'tenant',
                :tenant_id,
                CAST(:details_json AS jsonb)
            )
            """
        ),
        {"tenant_id": tenant_id, "user_id": user_id or "", "details_json": _json({"pack": pack_summary(pack), "result": result}, {})},
    )
    return {"ok": True, "tenant_id": tenant_id, "pack": pack_summary(pack), "applied": result, **tenant_vertical_state(conn, tenant_id)}
