from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app_saas.db import db_session, set_tenant_context
from app_saas.intelligence.operations import (
    approve_autonomous_action,
    autonomous_operations_center,
    dismiss_autonomous_action,
    execute_autonomous_action,
    list_autonomous_actions,
    run_operational_intelligence_analysis,
    update_autonomy_policy,
)
from app_saas.intelligence.network import (
    enterprise_ai_network_center,
    list_vertical_playbooks,
    refresh_enterprise_ai_network,
)
from app_saas.intelligence.federated import (
    aggregate_federated_round,
    federated_learning_center,
    prepare_federated_round,
    submit_federated_update,
    update_federated_policy,
)
from app_saas.intelligence.memory_network import (
    delete_memory_node,
    export_memory_network,
    import_memory_network,
    memory_network_center,
    review_memory_node,
    sync_enterprise_memory_network,
    update_memory_policy,
)
from app_saas.intelligence.multimodal_observability import (
    multimodal_observability_center,
    multimodal_rollout_center,
    refresh_multimodal_observability,
    update_multimodal_rollout_policy,
)
from app_saas.intelligence.revenue import (
    analyze_revenue_engine,
    approve_revenue_opportunity,
    dismiss_revenue_opportunity,
    execute_revenue_opportunity,
    revenue_engine_center,
    update_revenue_policy,
)
from app_saas.intelligence.schemas import (
    AutonomousActionExecuteIn,
    AutonomyPolicyPatchIn,
    EnterpriseNetworkRefreshIn,
    FederatedAggregateIn,
    FederatedPolicyPatchIn,
    FederatedRoundPrepareIn,
    FederatedUpdateSubmitIn,
    FeatureRecomputeIn,
    IntelligenceEventIn,
    MemoryNetworkNodeReviewIn,
    MemoryNetworkImportIn,
    MemoryNetworkPolicyPatchIn,
    MemoryNetworkSyncIn,
    MultimodalObservabilityRefreshIn,
    MultimodalRolloutPolicyPatchIn,
    OperationalAnalysisIn,
    PredictionFeedbackIn,
    PredictionRequestIn,
    RealtimeCursorPatchIn,
    RealtimeSessionIn,
    RevenueAnalysisIn,
    RevenueOpportunityActionIn,
    RevenuePolicyPatchIn,
)
from app_saas.intelligence.realtime import (
    close_realtime_session,
    list_realtime_events,
    realtime_intelligence_center,
    register_realtime_session,
    STREAM_FEATURE,
    update_realtime_cursor,
)
from app_saas.intelligence.service import (
    dismiss_recommendation,
    generate_prediction,
    intelligence_catalog,
    intelligence_feature_state,
    list_feature_values,
    list_model_metrics,
    list_prediction_feedback,
    list_predictions,
    list_recommendations,
    predictive_business_overview,
    record_event,
    resolve_intelligence_access,
    record_prediction_feedback,
    recompute_feature_snapshot,
)
from app_saas.shared.security import AuthContext, get_current_user, require_role

router = APIRouter(prefix="/intelligence", tags=["saas-intelligence"])


@router.get("/catalog")
def get_intelligence_catalog(ctx: AuthContext = Depends(get_current_user)):
    return {"ok": True, "features": intelligence_catalog()}


@router.get("/state")
def get_intelligence_state(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "state": intelligence_feature_state(conn, ctx.tenant_id)}


@router.get("/overview")
def get_intelligence_overview(
    limit: int = Query(40, ge=5, le=120),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "overview": predictive_business_overview(conn, ctx.tenant_id, limit=limit)}


@router.get("/realtime/center")
def get_realtime_intelligence_center(
    limit: int = Query(60, ge=5, le=120),
    since_event_id: str = Query("", max_length=80),
    cursor_key: str = Query("default", max_length=80),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {
            "ok": True,
            "center": realtime_intelligence_center(
                conn,
                ctx.tenant_id,
                ctx.user_id,
                limit=limit,
                since_event_id=since_event_id,
                cursor_key=cursor_key,
            ),
        }


@router.get("/realtime/events")
def get_realtime_intelligence_events(
    limit: int = Query(60, ge=1, le=200),
    since_event_id: str = Query("", max_length=80),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        resolve_intelligence_access(conn, ctx.tenant_id, "realtime_intelligence_layer", allow_demo=True)
        return {"ok": True, "events": list_realtime_events(conn, ctx.tenant_id, limit=limit, since_event_id=since_event_id)}


@router.post("/realtime/sessions")
def post_realtime_session(payload: RealtimeSessionIn, ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "session": register_realtime_session(conn, ctx.tenant_id, ctx.user_id, payload)}


@router.patch("/realtime/cursor")
def patch_realtime_cursor(payload: RealtimeCursorPatchIn, ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "cursor": update_realtime_cursor(conn, ctx.tenant_id, ctx.user_id, payload)}


@router.post("/realtime/sessions/{session_id}/close")
def post_realtime_session_close(session_id: str, ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "session": close_realtime_session(conn, ctx.tenant_id, ctx.user_id, session_id)}


@router.get("/realtime/stream")
async def get_realtime_intelligence_stream(
    limit: int = Query(40, ge=5, le=100),
    since_event_id: str = Query("", max_length=80),
    poll_seconds: int = Query(8, ge=3, le=30),
    max_seconds: int = Query(60, ge=15, le=180),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        resolve_intelligence_access(conn, ctx.tenant_id, STREAM_FEATURE, allow_demo=True)

    async def event_stream():
        elapsed = 0
        current_since = since_event_id
        while elapsed <= max_seconds:
            with db_session() as stream_conn:
                set_tenant_context(stream_conn, ctx.tenant_id)
                center = realtime_intelligence_center(
                    stream_conn,
                    ctx.tenant_id,
                    ctx.user_id,
                    limit=limit,
                    since_event_id=current_since,
                )
                latest_id = str((center.get("stream") or {}).get("latest_event_id") or "")
                if latest_id:
                    current_since = latest_id
                data = json.dumps(center, ensure_ascii=False, default=str)
                yield f"event: snapshot\nid: {latest_id or 'snapshot'}\ndata: {data}\n\n"
            await asyncio.sleep(poll_seconds)
            elapsed += poll_seconds
        yield "event: close\ndata: {\"reason\":\"max_seconds\"}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/events")
def post_intelligence_event(payload: IntelligenceEventIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor", "agent"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "event": record_event(conn, ctx.tenant_id, payload)}


@router.get("/features")
def get_feature_values(
    subject_type: str = Query("tenant", max_length=80),
    subject_id: str = Query("", max_length=160),
    limit: int = Query(120, ge=1, le=500),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        if not subject_id:
            subject_id = ctx.tenant_id
        return {"ok": True, "features": list_feature_values(conn, ctx.tenant_id, subject_type=subject_type, subject_id=subject_id, limit=limit)}


@router.post("/features/recompute")
def post_feature_recompute(payload: FeatureRecomputeIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {
            "ok": True,
            "snapshot": recompute_feature_snapshot(
                conn,
                ctx.tenant_id,
                subject_type=payload.subject_type,
                subject_id=payload.subject_id or ctx.tenant_id,
                window_key=payload.window_key,
            ),
        }


@router.post("/predict")
def post_prediction(payload: PredictionRequestIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        prediction = generate_prediction(
            conn,
            ctx.tenant_id,
            prediction_type=payload.prediction_type,
            subject_type=payload.subject_type,
            subject_id=payload.subject_id or ctx.tenant_id,
            window_key=payload.window_key,
            persist_recommendations=payload.persist_recommendations,
        )
        return {"ok": True, "prediction": prediction}


@router.get("/predictions")
def get_predictions(
    prediction_type: str = Query("", max_length=120),
    limit: int = Query(50, ge=1, le=200),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "predictions": list_predictions(conn, ctx.tenant_id, prediction_type=prediction_type, limit=limit)}


@router.get("/feedback")
def get_prediction_feedback(
    prediction_id: str = Query("", max_length=80),
    limit: int = Query(100, ge=1, le=300),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "feedback": list_prediction_feedback(conn, ctx.tenant_id, prediction_id=prediction_id, limit=limit)}


@router.post("/predictions/{prediction_id}/feedback")
def post_prediction_feedback(
    prediction_id: str,
    payload: PredictionFeedbackIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        result = record_prediction_feedback(conn, ctx.tenant_id, prediction_id, payload, actor_user_id=ctx.user_id)
        return {"ok": True, **result}


@router.get("/model-metrics")
def get_model_metrics(
    model_key: str = Query("", max_length=160),
    prediction_type: str = Query("", max_length=120),
    limit: int = Query(120, ge=1, le=500),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "metrics": list_model_metrics(conn, tenant_id=ctx.tenant_id, model_key=model_key, prediction_type=prediction_type, limit=limit)}


@router.get("/multimodal/observability/center")
def get_multimodal_observability_center(
    window_key: str = Query("30d", max_length=20),
    limit: int = Query(20, ge=1, le=100),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {
            "ok": True,
            "center": multimodal_observability_center(conn, ctx.tenant_id, window_key=window_key, limit=limit),
        }


@router.post("/multimodal/observability/refresh")
def post_multimodal_observability_refresh(
    payload: MultimodalObservabilityRefreshIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        result = refresh_multimodal_observability(
            conn,
            ctx.tenant_id,
            actor_user_id=ctx.user_id,
            window_key=payload.window_key,
            dry_run=payload.dry_run,
            limit=payload.limit,
        )
        return {
            "ok": True,
            "result": result,
            "center": multimodal_observability_center(conn, ctx.tenant_id, window_key=payload.window_key, limit=payload.limit),
        }


@router.get("/multimodal/rollout/center")
def get_multimodal_rollout_center(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "rollout": multimodal_rollout_center(conn, ctx.tenant_id)}


@router.patch("/multimodal/rollout/policy")
def patch_multimodal_rollout_policy(
    payload: MultimodalRolloutPolicyPatchIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        policy = update_multimodal_rollout_policy(conn, ctx.tenant_id, ctx.user_id, payload)
        return {"ok": True, "policy": policy, "rollout": multimodal_rollout_center(conn, ctx.tenant_id)}


@router.get("/recommendations")
def get_recommendations(
    status: str = Query("open", max_length=40),
    limit: int = Query(50, ge=1, le=200),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "recommendations": list_recommendations(conn, ctx.tenant_id, status=status, limit=limit)}


@router.get("/operations/center")
def get_operations_center(
    limit: int = Query(50, ge=1, le=200),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "center": autonomous_operations_center(conn, ctx.tenant_id, limit=limit)}


@router.patch("/operations/control")
def patch_operations_control(
    payload: AutonomyPolicyPatchIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "policy": update_autonomy_policy(conn, ctx.tenant_id, ctx.user_id, payload.model_dump())}


@router.post("/operations/analyze")
def post_operations_analyze(
    payload: OperationalAnalysisIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        result = run_operational_intelligence_analysis(
            conn,
            ctx.tenant_id,
            actor_user_id=ctx.user_id,
            dry_run=payload.dry_run,
            limit=payload.limit,
        )
        return {"ok": True, "result": result, "center": autonomous_operations_center(conn, ctx.tenant_id, limit=payload.limit)}


@router.get("/operations/actions")
def get_operations_actions(
    status: str = Query("all", max_length=40),
    limit: int = Query(50, ge=1, le=200),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "actions": list_autonomous_actions(conn, ctx.tenant_id, status=status, limit=limit)}


@router.get("/network/center")
def get_enterprise_ai_network_center(
    limit: int = Query(50, ge=1, le=200),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "network": enterprise_ai_network_center(conn, ctx.tenant_id, limit=limit)}


@router.post("/network/refresh")
def post_enterprise_ai_network_refresh(
    payload: EnterpriseNetworkRefreshIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        result = refresh_enterprise_ai_network(
            conn,
            ctx.tenant_id,
            actor_user_id=ctx.user_id,
            dry_run=payload.dry_run,
            limit=payload.limit,
        )
        return {
            "ok": True,
            "result": result,
            "network": enterprise_ai_network_center(conn, ctx.tenant_id, limit=payload.limit),
        }


@router.get("/network/playbooks")
def get_enterprise_ai_network_playbooks(
    limit: int = Query(50, ge=1, le=200),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        center = enterprise_ai_network_center(conn, ctx.tenant_id, limit=limit)
        industry_code = str((center.get("industry") or {}).get("code") or "general")
        return {
            "ok": True,
            "industry": center.get("industry"),
            "access": center.get("access"),
            "playbooks": list_vertical_playbooks(conn, industry_code, limit=limit),
        }


@router.get("/federated/center")
def get_federated_learning_center(
    limit: int = Query(60, ge=1, le=200),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "federated": federated_learning_center(conn, ctx.tenant_id, limit=limit)}


@router.patch("/federated/policy")
def patch_federated_learning_policy(
    payload: FederatedPolicyPatchIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        policy = update_federated_policy(conn, ctx.tenant_id, ctx.user_id, payload.model_dump())
        return {"ok": True, "policy": policy, "federated": federated_learning_center(conn, ctx.tenant_id, limit=60)}


@router.post("/federated/rounds/prepare")
def post_federated_round_prepare(
    payload: FederatedRoundPrepareIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        result = prepare_federated_round(
            conn,
            ctx.tenant_id,
            actor_user_id=ctx.user_id,
            task_type=payload.task_type,
            model_key=payload.model_key,
            window_key=payload.window_key,
            dry_run=payload.dry_run,
            min_participants=payload.min_participants,
            min_total_samples=payload.min_total_samples,
            aggregation_strategy=payload.aggregation_strategy,
        )
        return {"ok": True, "result": result, "federated": federated_learning_center(conn, ctx.tenant_id, limit=60)}


@router.post("/federated/rounds/{round_id}/submit-update")
def post_federated_round_submit_update(
    round_id: str,
    payload: FederatedUpdateSubmitIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        result = submit_federated_update(conn, ctx.tenant_id, ctx.user_id, round_id, dry_run=payload.dry_run)
        return {"ok": True, "result": result, "federated": federated_learning_center(conn, ctx.tenant_id, limit=60)}


@router.post("/federated/rounds/{round_id}/aggregate")
def post_federated_round_aggregate(
    round_id: str,
    payload: FederatedAggregateIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        result = aggregate_federated_round(conn, ctx.tenant_id, ctx.user_id, round_id, dry_run=payload.dry_run)
        return {"ok": True, "result": result, "federated": federated_learning_center(conn, ctx.tenant_id, limit=60)}


@router.get("/revenue/center")
def get_revenue_engine_center(
    limit: int = Query(50, ge=1, le=200),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "revenue": revenue_engine_center(conn, ctx.tenant_id, limit=limit)}


@router.patch("/revenue/policy")
def patch_revenue_policy(
    payload: RevenuePolicyPatchIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "policy": update_revenue_policy(conn, ctx.tenant_id, ctx.user_id, payload.model_dump())}


@router.post("/revenue/analyze")
def post_revenue_analysis(
    payload: RevenueAnalysisIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        result = analyze_revenue_engine(
            conn,
            ctx.tenant_id,
            actor_user_id=ctx.user_id,
            dry_run=payload.dry_run,
            limit=payload.limit,
        )
        return {"ok": True, "result": result, "revenue": revenue_engine_center(conn, ctx.tenant_id, limit=payload.limit)}


@router.post("/revenue/opportunities/{opportunity_id}/approve")
def post_revenue_opportunity_approve(
    opportunity_id: str,
    payload: RevenueOpportunityActionIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {
            "ok": True,
            "opportunity": approve_revenue_opportunity(
                conn,
                ctx.tenant_id,
                ctx.user_id,
                opportunity_id,
                notes=payload.notes,
                dry_run=payload.dry_run,
            ),
        }


@router.post("/revenue/opportunities/{opportunity_id}/execute")
def post_revenue_opportunity_execute(
    opportunity_id: str,
    payload: RevenueOpportunityActionIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {
            "ok": True,
            "opportunity": execute_revenue_opportunity(
                conn,
                ctx.tenant_id,
                ctx.user_id,
                opportunity_id,
                notes=payload.notes,
                dry_run=payload.dry_run,
            ),
        }


@router.post("/revenue/opportunities/{opportunity_id}/dismiss")
def post_revenue_opportunity_dismiss(
    opportunity_id: str,
    payload: RevenueOpportunityActionIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {
            "ok": True,
            "opportunity": dismiss_revenue_opportunity(
                conn,
                ctx.tenant_id,
                ctx.user_id,
                opportunity_id,
                notes=payload.notes,
                dry_run=payload.dry_run,
            ),
        }


@router.get("/memory-network/center")
def get_memory_network_center(
    limit: int = Query(80, ge=1, le=300),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "memory_network": memory_network_center(conn, ctx.tenant_id, limit=limit)}


@router.patch("/memory-network/policy")
def patch_memory_network_policy(
    payload: MemoryNetworkPolicyPatchIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "policy": update_memory_policy(conn, ctx.tenant_id, ctx.user_id, payload.model_dump())}


@router.post("/memory-network/sync")
def post_memory_network_sync(
    payload: MemoryNetworkSyncIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        result = sync_enterprise_memory_network(
            conn,
            ctx.tenant_id,
            actor_user_id=ctx.user_id,
            dry_run=payload.dry_run,
            limit=payload.limit,
            source_types=payload.source_types,
        )
        return {"ok": True, "result": result, "memory_network": memory_network_center(conn, ctx.tenant_id, limit=payload.limit)}


@router.get("/memory-network/export")
def get_memory_network_export(
    include_archived: bool = Query(False),
    limit: int = Query(300, ge=1, le=1000),
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {
            "ok": True,
            "export": export_memory_network(
                conn,
                ctx.tenant_id,
                ctx.user_id,
                include_archived=include_archived,
                limit=limit,
            ),
        }


@router.post("/memory-network/import")
def post_memory_network_import(
    payload: MemoryNetworkImportIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        result = import_memory_network(conn, ctx.tenant_id, ctx.user_id, payload.model_dump())
        return {"ok": True, "result": result, "memory_network": memory_network_center(conn, ctx.tenant_id, limit=80)}


@router.post("/memory-network/nodes/{node_id}/review")
def post_memory_network_node_review(
    node_id: str,
    payload: MemoryNetworkNodeReviewIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "node": review_memory_node(conn, ctx.tenant_id, ctx.user_id, node_id, status=payload.status, notes=payload.notes)}


@router.delete("/memory-network/nodes/{node_id}")
def delete_memory_network_node(
    node_id: str,
    reason: str = Query("", max_length=1000),
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "node": delete_memory_node(conn, ctx.tenant_id, ctx.user_id, node_id, reason=reason)}


@router.post("/operations/actions/{action_id}/approve")
def post_operations_action_approve(
    action_id: str,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "action": approve_autonomous_action(conn, ctx.tenant_id, ctx.user_id, action_id)}


@router.post("/operations/actions/{action_id}/execute")
def post_operations_action_execute(
    action_id: str,
    payload: AutonomousActionExecuteIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "action": execute_autonomous_action(conn, ctx.tenant_id, ctx.user_id, action_id, dry_run=payload.dry_run)}


@router.post("/operations/actions/{action_id}/dismiss")
def post_operations_action_dismiss(
    action_id: str,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "action": dismiss_autonomous_action(conn, ctx.tenant_id, ctx.user_id, action_id)}


@router.post("/recommendations/{recommendation_id}/dismiss")
def post_dismiss_recommendation(recommendation_id: str, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "recommendation": dismiss_recommendation(conn, ctx.tenant_id, recommendation_id)}
