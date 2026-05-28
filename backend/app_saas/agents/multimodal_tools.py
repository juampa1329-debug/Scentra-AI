from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app_saas.agents.operating_system import ensure_agent_os_tables
from app_saas.agents.service import _audit, get_agent
from app_saas.agents.multimodal_memory import sync_multimodal_memory_events
from app_saas.db import db_session, set_tenant_context
from app_saas.intelligence.service import record_intelligence_usage, resolve_intelligence_access
from app_saas.media.router import (
    WebImageSearchIn,
    analyze_vision_message,
    analyze_voice_message,
    create_web_image_search,
)
from app_saas.shared.security import AuthContext


AGENT_MULTIMODAL_TOOL_CODES = {"media.voice_analyze", "media.vision_analyze", "media.web_image_search"}

AGENT_MULTIMODAL_TOOLS: list[dict[str, Any]] = [
    {
        "code": "media.voice_analyze",
        "label": "Analizar audio",
        "category": "voice",
        "feature_keys": ["agent_voice_tools", "agent_multimodal_tools", "ai_premium"],
        "requires": ["message_id", "voice_intelligence_or_ai_premium"],
        "approval": "not_required_read_only",
        "side_effects": "stores_voice_analysis_and_tool_trace_only",
        "description": "Transcribe y resume un audio existente del Inbox para que el agente lo use como contexto.",
    },
    {
        "code": "media.vision_analyze",
        "label": "Analizar imagen/documento",
        "category": "vision",
        "feature_keys": ["agent_vision_tools", "agent_multimodal_tools", "ai_premium"],
        "requires": ["message_id", "vision_intelligence_or_ai_premium"],
        "approval": "not_required_read_only",
        "side_effects": "stores_vision_analysis_and_tool_trace_only",
        "description": "Describe imagenes o extrae texto de documentos existentes del Inbox para contexto del agente.",
    },
    {
        "code": "media.web_image_search",
        "label": "Buscar web/imagen",
        "category": "external_search",
        "feature_keys": ["agent_external_search_tools", "agent_multimodal_tools", "ai_premium"],
        "requires": ["query", "tenant_search_provider_credential", "web_or_image_search_or_ai_premium"],
        "approval": "human_approval_required_per_result",
        "side_effects": "stores_search_run_results_and_tool_trace_only",
        "description": "Busca fuentes externas y deja cada resultado pendiente de aprobacion humana.",
    },
]


def _clean(value: Any, limit: int = 240) -> str:
    return str(value or "").strip()[:limit]


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _safe_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _safe_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _row(row: Any) -> dict[str, Any]:
    data = dict(row or {})
    for key in ("input_json", "output_json"):
        data[key] = _safe_dict(data.get(key))
    return data


def _scrub_detail(value: Any) -> Any:
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key or "")
            if any(secret_key in key_text.lower() for secret_key in ("token", "secret", "api_key", "authorization")):
                clean[key_text] = "[redacted]"
            else:
                clean[key_text] = _scrub_detail(item)
        return clean
    if isinstance(value, list):
        return [_scrub_detail(item) for item in value[:20]]
    text_value = str(value or "")
    return text_value[:700]


def _multimodal_tool_for(tool_code: str) -> dict[str, Any]:
    clean = _clean(tool_code, 120).lower()
    for item in AGENT_MULTIMODAL_TOOLS:
        if item["code"] == clean:
            return item
    raise HTTPException(status_code=400, detail={"code": "unknown_multimodal_tool", "tool_code": clean})


def _resolve_agent_tool_access(conn: Connection, tenant_id: str, tool_code: str) -> dict[str, Any]:
    tool = _multimodal_tool_for(tool_code)
    last_detail: Any = None
    for feature_key in tool["feature_keys"]:
        try:
            access = dict(resolve_intelligence_access(conn, tenant_id, feature_key, allow_demo=True))
            access["resolved_feature_key"] = feature_key
            return access
        except HTTPException as exc:
            last_detail = exc.detail
    raise HTTPException(
        status_code=403,
        detail={"code": "agent_multimodal_tool_not_enabled", "tool_code": tool_code, "features": tool["feature_keys"], "last_error": last_detail},
    )


def _validate_agent_tool(conn: Connection, tenant_id: str, agent_id: str, tool_code: str) -> dict[str, Any]:
    tool = _multimodal_tool_for(tool_code)
    agent = get_agent(conn, tenant_id, agent_id)
    allowed_tools = {str(item or "").strip().lower() for item in _safe_list(agent.get("tools_json"))}
    if allowed_tools and tool["code"] not in allowed_tools:
        raise HTTPException(status_code=403, detail={"code": "agent_tool_not_allowed", "tool_code": tool["code"], "agent_id": agent_id})
    return agent


def _tool_input(payload: dict[str, Any], tool_code: str) -> dict[str, Any]:
    return {
        "tool_code": tool_code,
        "conversation_id": _clean(payload.get("conversation_id"), 80),
        "message_id": _clean(payload.get("message_id"), 80),
        "query": _clean(payload.get("query"), 280),
        "search_type": _clean(payload.get("search_type") or "mixed", 20).lower(),
        "provider_code": _clean(payload.get("provider_code"), 80).lower(),
        "force": bool(payload.get("force")),
        "limit": max(1, min(int(payload.get("limit") or 6), 12)),
        "metadata_json": _safe_dict(payload.get("metadata_json")),
    }


def _insert_tool_run(
    conn: Connection,
    *,
    tenant_id: str,
    user_id: str,
    agent_id: str,
    tool_code: str,
    input_json: dict[str, Any],
    access: dict[str, Any],
) -> dict[str, Any]:
    approval_status = "result_approval_required" if tool_code == "media.web_image_search" else "not_required"
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ai_agent_tool_runs (
                tenant_id, agent_id, tool_code, status, approval_status, risk_level,
                input_json, output_json, created_by_user_id, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), CAST(:agent_id AS uuid), :tool_code,
                'running', :approval_status, :risk_level,
                CAST(:input_json AS jsonb), CAST(:output_json AS jsonb),
                CAST(NULLIF(:created_by_user_id, '') AS uuid), NOW()
            )
            RETURNING id::text, agent_id::text, COALESCE(action_draft_id::text, '') AS action_draft_id,
                      tool_code, status, approval_status, risk_level, input_json, output_json,
                      error_text, COALESCE(created_by_user_id::text, '') AS created_by_user_id,
                      created_at::text, updated_at::text, COALESCE(completed_at::text, '') AS completed_at
            """
        ),
        {
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "tool_code": tool_code,
            "approval_status": approval_status,
            "risk_level": "medium" if tool_code == "media.web_image_search" else "low",
            "input_json": _json(input_json),
            "output_json": _json(
                {
                    "state": "running",
                    "access_mode": access.get("mode") or "demo",
                    "feature_key": access.get("resolved_feature_key") or "",
                    "safety": "read_only_no_customer_send_no_crm_mutation",
                }
            ),
            "created_by_user_id": user_id or "",
        },
    ).mappings().first()
    return _row(row)


def _update_tool_run(
    conn: Connection,
    *,
    tenant_id: str,
    run_id: str,
    status: str,
    output_json: dict[str, Any],
    error_text: str = "",
) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            UPDATE saas_ai_agent_tool_runs
            SET status = :status,
                output_json = CAST(:output_json AS jsonb),
                error_text = :error_text,
                updated_at = NOW(),
                completed_at = CASE WHEN :status IN ('completed', 'failed') THEN NOW() ELSE completed_at END
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id = CAST(:run_id AS uuid)
            RETURNING id::text, agent_id::text, COALESCE(action_draft_id::text, '') AS action_draft_id,
                      tool_code, status, approval_status, risk_level, input_json, output_json,
                      error_text, COALESCE(created_by_user_id::text, '') AS created_by_user_id,
                      created_at::text, updated_at::text, COALESCE(completed_at::text, '') AS completed_at
            """
        ),
        {"tenant_id": tenant_id, "run_id": run_id, "status": status, "output_json": _json(output_json), "error_text": _clean(error_text, 1000)},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="agent_multimodal_tool_run_not_found")
    return _row(row)


def _analysis_output(result: dict[str, Any], *, tool_code: str, access: dict[str, Any]) -> dict[str, Any]:
    analysis = _safe_dict(result.get("analysis"))
    compact = _safe_dict(analysis.get("voice_intelligence") if tool_code == "media.voice_analyze" else analysis.get("vision_intelligence"))
    if not compact:
        compact = analysis
    if tool_code == "media.voice_analyze":
        return {
            "state": "completed",
            "tool_code": tool_code,
            "cached": bool(result.get("cached")),
            "access_mode": access.get("mode") or "demo",
            "analysis_id": _clean(analysis.get("id"), 80),
            "conversation_id": _clean(analysis.get("conversation_id"), 80),
            "message_id": _clean(analysis.get("message_id"), 80),
            "provider_code": _clean(analysis.get("provider_code"), 80),
            "model": _clean(analysis.get("model"), 240),
            "summary": _clean(compact.get("summary") or analysis.get("summary"), 1500),
            "transcript_preview": _clean(compact.get("transcript") or analysis.get("transcript"), 1200),
            "sentiment": _clean(compact.get("sentiment") or analysis.get("sentiment"), 40),
            "intent": _clean(compact.get("intent") or analysis.get("intent"), 80),
            "urgency": _clean(compact.get("urgency") or analysis.get("urgency"), 40),
            "confidence": compact.get("confidence") if compact.get("confidence") is not None else analysis.get("confidence"),
            "recommended_action": _clean(compact.get("recommended_action") or analysis.get("recommended_action"), 700),
            "safety": "read_only_context_no_customer_send",
        }
    return {
        "state": "completed",
        "tool_code": tool_code,
        "cached": bool(result.get("cached")),
        "access_mode": access.get("mode") or "demo",
        "analysis_id": _clean(analysis.get("id"), 80),
        "conversation_id": _clean(analysis.get("conversation_id"), 80),
        "message_id": _clean(analysis.get("message_id"), 80),
        "provider_code": _clean(analysis.get("provider_code"), 80),
        "model": _clean(analysis.get("model"), 240),
        "summary": _clean(compact.get("summary") or analysis.get("summary"), 1500),
        "visual_description": _clean(compact.get("visual_description") or analysis.get("visual_description"), 1500),
        "extracted_text_preview": _clean(compact.get("extracted_text") or analysis.get("extracted_text"), 1200),
        "document_type": _clean(compact.get("document_type") or analysis.get("document_type"), 80),
        "sentiment": _clean(compact.get("sentiment") or analysis.get("sentiment"), 40),
        "intent": _clean(compact.get("intent") or analysis.get("intent"), 80),
        "urgency": _clean(compact.get("urgency") or analysis.get("urgency"), 40),
        "confidence": compact.get("confidence") if compact.get("confidence") is not None else analysis.get("confidence"),
        "recommended_action": _clean(compact.get("recommended_action") or analysis.get("recommended_action"), 700),
        "safety": "read_only_context_no_customer_send",
    }


def _search_output(result: dict[str, Any], *, access: dict[str, Any]) -> dict[str, Any]:
    run = _safe_dict(result.get("run"))
    results = _safe_list(run.get("results"))
    compact_results: list[dict[str, Any]] = []
    for item in results[:12]:
        if not isinstance(item, dict):
            continue
        compact_results.append(
            {
                "id": _clean(item.get("id"), 80),
                "result_type": _clean(item.get("result_type"), 20),
                "title": _clean(item.get("title"), 240),
                "url": _clean(item.get("url"), 1000),
                "image_url": _clean(item.get("image_url"), 1000),
                "thumbnail_url": _clean(item.get("thumbnail_url"), 1000),
                "snippet": _clean(item.get("snippet"), 600),
                "source_name": _clean(item.get("source_name"), 160),
                "rank": item.get("rank"),
                "safety_status": _clean(item.get("safety_status"), 40),
                "approval_status": _clean(item.get("approval_status"), 40),
            }
        )
    return {
        "state": "completed",
        "tool_code": "media.web_image_search",
        "access_mode": access.get("mode") or "demo",
        "search_run_id": _clean(run.get("id"), 80),
        "conversation_id": _clean(run.get("conversation_id"), 80),
        "message_id": _clean(run.get("message_id"), 80),
        "query": _clean(run.get("query"), 280),
        "search_type": _clean(run.get("search_type"), 20),
        "provider_code": _clean(run.get("provider_code"), 80),
        "result_count": int(run.get("result_count") or len(compact_results)),
        "approved_count": int(run.get("approved_count") or 0),
        "blocked_count": int(run.get("blocked_count") or 0),
        "approval_required": True,
        "results": compact_results,
        "safety": "external_sources_pending_human_approval_no_customer_send",
    }


def _search_results_for_run(conn: Connection, tenant_id: str, run_id: str) -> tuple[list[dict[str, Any]], int, int, int]:
    if not run_id:
        return [], 0, 0, 0
    rows = conn.execute(
        text(
            """
            SELECT id::text, result_type, title, url, image_url, thumbnail_url, snippet,
                   source_name, rank, safety_status, approval_status
            FROM saas_web_search_intelligence_results
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND run_id = CAST(:run_id AS uuid)
            ORDER BY rank ASC, created_at ASC
            LIMIT 12
            """
        ),
        {"tenant_id": tenant_id, "run_id": run_id},
    ).mappings().all()
    results: list[dict[str, Any]] = []
    approved = 0
    blocked = 0
    for row in rows:
        item = dict(row)
        if str(item.get("approval_status") or "") == "approved":
            approved += 1
        if str(item.get("safety_status") or "") == "blocked":
            blocked += 1
        results.append(
            {
                "id": _clean(item.get("id"), 80),
                "result_type": _clean(item.get("result_type"), 20),
                "title": _clean(item.get("title"), 240),
                "url": _clean(item.get("url"), 1000),
                "image_url": _clean(item.get("image_url"), 1000),
                "thumbnail_url": _clean(item.get("thumbnail_url"), 1000),
                "snippet": _clean(item.get("snippet"), 600),
                "source_name": _clean(item.get("source_name"), 160),
                "rank": item.get("rank"),
                "safety_status": _clean(item.get("safety_status"), 40),
                "approval_status": _clean(item.get("approval_status"), 40),
            }
        )
    return results, len(results), approved, blocked


def _list_runs(conn: Connection, tenant_id: str, agent_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT id::text, agent_id::text, COALESCE(action_draft_id::text, '') AS action_draft_id,
                   tool_code, status, approval_status, risk_level, input_json, output_json, error_text,
                   COALESCE(created_by_user_id::text, '') AS created_by_user_id,
                   created_at::text, updated_at::text, COALESCE(completed_at::text, '') AS completed_at
            FROM saas_ai_agent_tool_runs
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND agent_id = CAST(:agent_id AS uuid)
              AND tool_code IN ('media.voice_analyze', 'media.vision_analyze', 'media.web_image_search')
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "agent_id": agent_id, "limit": max(1, min(int(limit or 50), 100))},
    ).mappings().all()
    items = [_row(item) for item in rows]
    for item in items:
        output = _safe_dict(item.get("output_json"))
        if item.get("tool_code") == "media.web_image_search" and output.get("search_run_id"):
            results, total, approved, blocked = _search_results_for_run(conn, tenant_id, _clean(output.get("search_run_id"), 80))
            output["results"] = results
            output["result_count"] = total
            output["approved_count"] = approved
            output["blocked_count"] = blocked
            item["output_json"] = output
    return items


def agent_multimodal_tool_catalog() -> list[dict[str, Any]]:
    return [dict(item) for item in AGENT_MULTIMODAL_TOOLS]


def list_agent_multimodal_tool_runs(conn: Connection, tenant_id: str, agent_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    ensure_agent_os_tables(conn)
    get_agent(conn, tenant_id, agent_id)
    return _list_runs(conn, tenant_id, agent_id, limit=limit)


def execute_agent_multimodal_tool(ctx: AuthContext, agent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    tool_code = _multimodal_tool_for(payload.get("tool_code") or "media.voice_analyze")["code"]
    input_json = _tool_input(payload, tool_code)
    if tool_code in {"media.voice_analyze", "media.vision_analyze"} and not input_json["message_id"]:
        raise HTTPException(status_code=400, detail={"code": "message_id_required", "tool_code": tool_code})
    if tool_code == "media.web_image_search" and not input_json["query"]:
        raise HTTPException(status_code=400, detail={"code": "query_required", "tool_code": tool_code})

    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        ensure_agent_os_tables(conn)
        _validate_agent_tool(conn, ctx.tenant_id, agent_id, tool_code)
        access = _resolve_agent_tool_access(conn, ctx.tenant_id, tool_code)
        record_intelligence_usage(
            conn,
            ctx.tenant_id,
            str(access.get("resolved_feature_key") or "agent_multimodal_tools"),
            usage_metric="agent_multimodal_tool_runs",
            metadata={"agent_id": agent_id, "tool_code": tool_code, "mode": access.get("mode") or "demo"},
        )
        run = _insert_tool_run(
            conn,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            agent_id=agent_id,
            tool_code=tool_code,
            input_json=input_json,
            access=access,
        )
        _audit(
            conn,
            tenant_id=ctx.tenant_id,
            agent_id=agent_id,
            actor_user_id=ctx.user_id,
            event_type="agent.multimodal_tool_started",
            summary=f"Herramienta multimodal iniciada: {tool_code}",
            details={"tool_run_id": run["id"], "tool_code": tool_code, "access_mode": access.get("mode") or "demo"},
        )

    try:
        if tool_code == "media.voice_analyze":
            media_result = analyze_voice_message(
                input_json["message_id"],
                force=bool(input_json.get("force")),
                provider_code=input_json.get("provider_code") or "",
                ctx=ctx,
            )
            output = _analysis_output(media_result, tool_code=tool_code, access=access)
        elif tool_code == "media.vision_analyze":
            media_result = analyze_vision_message(
                input_json["message_id"],
                force=bool(input_json.get("force")),
                provider_code=input_json.get("provider_code") or "",
                ctx=ctx,
            )
            output = _analysis_output(media_result, tool_code=tool_code, access=access)
        else:
            media_result = create_web_image_search(
                WebImageSearchIn(
                    query=input_json["query"],
                    search_type=input_json["search_type"],
                    provider_code=input_json.get("provider_code") or "",
                    conversation_id=input_json.get("conversation_id") or "",
                    message_id=input_json.get("message_id") or "",
                    limit=int(input_json.get("limit") or 6),
                ),
                ctx=ctx,
            )
            output = _search_output(media_result, access=access)
    except HTTPException as exc:
        failure_output = {
            "state": "failed",
            "tool_code": tool_code,
            "access_mode": access.get("mode") or "demo",
            "error": _scrub_detail(exc.detail),
            "safety": "no_customer_side_effects_after_failure",
        }
        with db_session() as conn:
            set_tenant_context(conn, ctx.tenant_id)
            failed = _update_tool_run(
                conn,
                tenant_id=ctx.tenant_id,
                run_id=run["id"],
                status="failed",
                output_json=failure_output,
                error_text=json.dumps(_scrub_detail(exc.detail), ensure_ascii=False)[:1000],
            )
            _audit(
                conn,
                tenant_id=ctx.tenant_id,
                agent_id=agent_id,
                actor_user_id=ctx.user_id,
                event_type="agent.multimodal_tool_failed",
                summary=f"Herramienta multimodal fallo: {tool_code}",
                details={"tool_run_id": failed["id"], "tool_code": tool_code, "error": _scrub_detail(exc.detail)},
            )
        raise

    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        completed = _update_tool_run(conn, tenant_id=ctx.tenant_id, run_id=run["id"], status="completed", output_json=output)
        try:
            sync_multimodal_memory_events(
                conn,
                ctx.tenant_id,
                ctx.user_id,
                {
                    "agent_id": agent_id,
                    "conversation_id": output.get("conversation_id") or input_json.get("conversation_id") or "",
                    "message_id": output.get("message_id") or input_json.get("message_id") or "",
                    "include_voice": tool_code == "media.voice_analyze",
                    "include_vision": tool_code == "media.vision_analyze",
                    "include_search": tool_code == "media.web_image_search",
                    "include_agent_runs": True,
                    "limit": 12,
                },
            )
        except Exception:
            # Memory/training capture is feature-gated and must not convert a
            # successful read-only tool run into a runtime failure.
            pass
        _audit(
            conn,
            tenant_id=ctx.tenant_id,
            agent_id=agent_id,
            actor_user_id=ctx.user_id,
            event_type="agent.multimodal_tool_completed",
            summary=f"Herramienta multimodal completada: {tool_code}",
            details={"tool_run_id": completed["id"], "tool_code": tool_code, "output_state": output.get("state")},
        )
        runs = _list_runs(conn, ctx.tenant_id, agent_id, limit=20)
    return {"tool_run": completed, "tool_runs": runs, "access": access}
