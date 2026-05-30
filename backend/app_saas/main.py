import asyncio
import contextlib
import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from app_saas.api_credentials.router import router as api_credentials_router
from app_saas.advisor.router import router as advisor_router
from app_saas.ai_gateway.router import router as ai_gateway_router
from app_saas.ai_agent.service import process_due_ai_replies
from app_saas.ai_agent.router import router as ai_agent_router
from app_saas.agents.orchestrator import process_due_agent_orchestration
from app_saas.agents.router import router as agents_router
from app_saas.admin.router import router as admin_router
from app_saas.ads.router import router as ads_router
from app_saas.auth.router import router as auth_router
from app_saas.billing.router import router as billing_router
from app_saas.broadcasts.router import router as broadcasts_router
from app_saas.campaigns.router import router as campaigns_router
from app_saas.commerce.router import router as commerce_router
from app_saas.compliance.router import router as compliance_router
from app_saas.config import settings
from app_saas.crm.router import router as crm_router
from app_saas.db import db_session
from app_saas.diagnostics.router import router as diagnostics_router
from app_saas.ecosystem.router import router as ecosystem_router
from app_saas.health.router import router as health_router
from app_saas.integrations.instagram_router import router as instagram_router
from app_saas.integrations.router import router as integrations_router
from app_saas.internal.router import router as internal_router
from app_saas.intelligence.router import router as intelligence_router
from app_saas.knowledge.router import router as knowledge_router
from app_saas.media.router import router as media_router
from app_saas.notifications.router import router as notifications_router
from app_saas.social.router import router as social_router
from app_saas.tenants.router import router as tenants_router
from app_saas.trust_center.router import admin_router as trust_center_admin_router
from app_saas.trust_center.router import router as trust_center_router
from app_saas.verticals.router import router as verticals_router
from app_saas.workflow_composer.router import router as workflow_composer_router
from app_saas.observability.service import record_worker_heartbeat
from app_saas.shared.security import decode_token
from app_saas.workers.dispatch import process_due_outbound_messages
from app_saas.workers.billing import process_billing_lifecycle
from app_saas.workers.ingest import process_due_webhook_events
from app_saas.workers.intelligence import process_due_intelligence
from app_saas.workers.meta_tokens import process_due_meta_token_refreshes
from app_saas.workers.remarketing import process_due_remarketing_flows
from app_saas.workers.reliability import process_due_reliability
from app_saas.workers.triggers import process_due_scheduled_trigger_messages
from app_saas.webhooks.router import router as webhooks_router

app = FastAPI(title="Scentra +AI API", version="0.1.0")
logger = logging.getLogger("scentra.saas")

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
BILLING_WRITE_EXEMPT_PREFIXES = (
    "/saas/v1/auth",
    "/saas/v1/billing",
    "/saas/v1/admin",
    "/saas/v1/health",
    "/saas/v1/ready",
    "/docs",
    "/openapi.json",
)


def _has_worker_activity(value) -> bool:
    if isinstance(value, dict):
        return any(_has_worker_activity(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_worker_activity(item) for item in value)
    return isinstance(value, int) and value > 0


def _run_embedded_worker_tick() -> dict:
    batch_size = max(1, min(int(settings.saas_worker_batch_size or 25), 200))
    result = {
        "ingest": process_due_webhook_events(limit=batch_size),
        "triggers": process_due_scheduled_trigger_messages(limit=batch_size),
        "remarketing": process_due_remarketing_flows(limit=batch_size),
        "ai": process_due_ai_replies(limit=batch_size),
        "agent_orchestrator": process_due_agent_orchestration(limit=batch_size),
        "outbound": process_due_outbound_messages(limit=batch_size),
        "billing": process_billing_lifecycle(),
        "intelligence": process_due_intelligence(limit=batch_size),
        "reliability": process_due_reliability(),
        "meta_tokens": process_due_meta_token_refreshes(),
    }
    with db_session() as conn:
        record_worker_heartbeat(
            conn,
            worker_name="api-embedded-worker",
            worker_type="embedded",
            status="ok",
            result=result,
        )
    return result


def _billing_write_block_response(request: Request) -> JSONResponse | None:
    if request.method.upper() not in UNSAFE_METHODS:
        return None
    path = str(request.url.path or "")
    if not path.startswith("/saas/v1") or any(path.startswith(prefix) for prefix in BILLING_WRITE_EXEMPT_PREFIXES):
        return None
    auth = str(request.headers.get("Authorization") or "").strip()
    if not auth.lower().startswith("bearer "):
        return None
    try:
        payload = decode_token(auth.split(" ", 1)[1].strip(), "access")
    except Exception:
        return None
    tenant_id = str(payload.get("tenant_id") or "").strip()
    if not tenant_id:
        return None
    with db_session() as conn:
        status = str(
            conn.execute(
                text("SELECT status FROM saas_tenants WHERE id = CAST(:tenant_id AS uuid) LIMIT 1"),
                {"tenant_id": tenant_id},
            ).scalar()
            or ""
        ).strip().lower()
    if status in {"active", "trial"}:
        return None
    status_code = 402 if status == "past_due" else 403
    return JSONResponse(
        status_code=status_code,
        content={
            "detail": {
                "code": "tenant_not_operational",
                "status": status or "unknown",
                "message": "La empresa no esta habilitada para operar. Actualiza el pago desde Plan y consumo.",
            }
        },
    )


async def _embedded_worker_loop() -> None:
    interval_sec = max(1, int(settings.saas_worker_idle_sec or 5))
    await asyncio.sleep(2)
    while True:
        try:
            result = await asyncio.to_thread(_run_embedded_worker_tick)
            if _has_worker_activity(result):
                print(f"[api-embedded-worker] tick {result}", flush=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            with contextlib.suppress(Exception):
                with db_session() as conn:
                    record_worker_heartbeat(
                        conn,
                        worker_name="api-embedded-worker",
                        worker_type="embedded",
                        status="error",
                        result={},
                        error=str(exc)[:1200],
                    )
            print(f"[api-embedded-worker] error {str(exc)[:500]}", flush=True)
        await asyncio.sleep(interval_sec)


@app.on_event("startup")
async def start_embedded_worker() -> None:
    if not settings.saas_embedded_worker_enabled:
        return
    with contextlib.suppress(Exception):
        with db_session() as conn:
            record_worker_heartbeat(conn, worker_name="api-embedded-worker", worker_type="embedded", status="ok", started=True)
    app.state.embedded_worker_task = asyncio.create_task(_embedded_worker_loop())
    print("[api-embedded-worker] started", flush=True)


@app.on_event("shutdown")
async def stop_embedded_worker() -> None:
    task = getattr(app.state, "embedded_worker_task", None)
    if not task:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


def _cors_headers_for_origin(origin: str | None) -> dict[str, str]:
    clean_origin = str(origin or "").strip().rstrip("/")
    if not clean_origin or clean_origin not in settings.cors_origins:
        return {}
    return {
        "Access-Control-Allow-Origin": clean_origin,
        "Access-Control-Allow-Credentials": "true",
        "Vary": "Origin",
    }


@app.middleware("http")
async def cors_error_guard(request: Request, call_next):
    started = time.perf_counter()
    correlation_id = (
        request.headers.get("x-correlation-id")
        or request.headers.get("x-request-id")
        or str(uuid.uuid4())
    )
    request.state.correlation_id = correlation_id
    origin = request.headers.get("origin")
    cors_headers = _cors_headers_for_origin(origin)
    trace_headers = {
        "X-Request-ID": correlation_id,
        "X-Correlation-ID": correlation_id,
    }
    if request.method.upper() == "OPTIONS" and cors_headers:
        headers = {
            **cors_headers,
            **trace_headers,
            "Access-Control-Allow-Methods": "DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT",
            "Access-Control-Allow-Headers": request.headers.get("access-control-request-headers", "*"),
            "Access-Control-Max-Age": "600",
        }
        return Response("OK", status_code=200, headers=headers)
    try:
        blocked = _billing_write_block_response(request)
        if blocked is not None:
            for key, value in cors_headers.items():
                if key not in blocked.headers:
                    blocked.headers[key] = value
            for key, value in trace_headers.items():
                if key not in blocked.headers:
                    blocked.headers[key] = value
            return blocked
        response = await call_next(request)
    except SQLAlchemyTimeoutError:
        logger.exception(
            "request_db_pool_timeout correlation_id=%s method=%s path=%s",
            correlation_id,
            request.method,
            request.url.path,
        )
        content = {
            "ok": False,
            "error": "database_busy",
            "correlation_id": correlation_id,
        }
        return JSONResponse(status_code=503, content=content, headers={**cors_headers, **trace_headers})
    except Exception as exc:
        logger.exception(
            "request_failed correlation_id=%s method=%s path=%s",
            correlation_id,
            request.method,
            request.url.path,
        )
        content = {
            "ok": False,
            "error": str(exc) if settings.is_local else "internal_server_error",
            "correlation_id": correlation_id,
        }
        return JSONResponse(status_code=500, content=content, headers={**cors_headers, **trace_headers})
    for key, value in cors_headers.items():
        if key not in response.headers:
            response.headers[key] = value
    for key, value in trace_headers.items():
        response.headers[key] = value
    duration_ms = int((time.perf_counter() - started) * 1000)
    if response.status_code >= 500:
        logger.error(
            "request_error correlation_id=%s method=%s path=%s status=%s duration_ms=%s",
            correlation_id,
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
    elif response.status_code >= 400:
        logger.warning(
            "request_warning correlation_id=%s method=%s path=%s status=%s duration_ms=%s",
            correlation_id,
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    correlation_id = getattr(request.state, "correlation_id", "") or str(uuid.uuid4())
    headers = {"X-Request-ID": correlation_id, "X-Correlation-ID": correlation_id}
    logger.exception("unhandled_exception correlation_id=%s method=%s path=%s", correlation_id, request.method, request.url.path)
    if settings.is_local:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc), "correlation_id": correlation_id}, headers=headers)
    return JSONResponse(status_code=500, content={"ok": False, "error": "internal_server_error", "correlation_id": correlation_id}, headers=headers)


app.include_router(health_router, prefix="/saas/v1")
app.include_router(admin_router, prefix="/saas/v1")
app.include_router(trust_center_admin_router, prefix="/saas/v1")
app.include_router(auth_router, prefix="/saas/v1")
app.include_router(tenants_router, prefix="/saas/v1")
app.include_router(verticals_router, prefix="/saas/v1")
app.include_router(crm_router, prefix="/saas/v1")
app.include_router(campaigns_router, prefix="/saas/v1")
app.include_router(commerce_router, prefix="/saas/v1")
app.include_router(compliance_router, prefix="/saas/v1")
app.include_router(broadcasts_router, prefix="/saas/v1")
app.include_router(ads_router, prefix="/saas/v1")
app.include_router(integrations_router, prefix="/saas/v1")
app.include_router(instagram_router, prefix="/saas/v1")
app.include_router(internal_router, prefix="/saas/v1")
app.include_router(api_credentials_router, prefix="/saas/v1")
app.include_router(advisor_router, prefix="/saas/v1")
app.include_router(agents_router, prefix="/saas/v1")
app.include_router(ai_gateway_router, prefix="/saas/v1")
app.include_router(intelligence_router, prefix="/saas/v1")
app.include_router(ecosystem_router, prefix="/saas/v1")
app.include_router(workflow_composer_router, prefix="/saas/v1")
app.include_router(trust_center_router, prefix="/saas/v1")
app.include_router(knowledge_router, prefix="/saas/v1")
app.include_router(diagnostics_router, prefix="/saas/v1")
app.include_router(ai_agent_router, prefix="/saas/v1")
app.include_router(media_router, prefix="/saas/v1")
app.include_router(notifications_router, prefix="/saas/v1")
app.include_router(social_router, prefix="/saas/v1")
app.include_router(billing_router, prefix="/saas/v1")
app.include_router(webhooks_router, prefix="/saas/v1")
