from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app_saas.api_credentials.router import router as api_credentials_router
from app_saas.ai_agent.router import router as ai_agent_router
from app_saas.admin.router import router as admin_router
from app_saas.ads.router import router as ads_router
from app_saas.auth.router import router as auth_router
from app_saas.billing.router import router as billing_router
from app_saas.broadcasts.router import router as broadcasts_router
from app_saas.campaigns.router import router as campaigns_router
from app_saas.config import settings
from app_saas.crm.router import router as crm_router
from app_saas.health.router import router as health_router
from app_saas.integrations.router import router as integrations_router
from app_saas.media.router import router as media_router
from app_saas.tenants.router import router as tenants_router
from app_saas.webhooks.router import router as webhooks_router

app = FastAPI(title="Scentra +AI API", version="0.1.0")


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
    origin = request.headers.get("origin")
    cors_headers = _cors_headers_for_origin(origin)
    if request.method.upper() == "OPTIONS" and cors_headers:
        headers = {
            **cors_headers,
            "Access-Control-Allow-Methods": "DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT",
            "Access-Control-Allow-Headers": request.headers.get("access-control-request-headers", "*"),
            "Access-Control-Max-Age": "600",
        }
        return Response("OK", status_code=200, headers=headers)
    try:
        response = await call_next(request)
    except Exception as exc:
        content = {"ok": False, "error": str(exc) if settings.is_local else "internal_server_error"}
        return JSONResponse(status_code=500, content=content, headers=cors_headers)
    for key, value in cors_headers.items():
        if key not in response.headers:
            response.headers[key] = value
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
    if settings.is_local:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})
    return JSONResponse(status_code=500, content={"ok": False, "error": "internal_server_error"})


app.include_router(health_router, prefix="/saas/v1")
app.include_router(admin_router, prefix="/saas/v1")
app.include_router(auth_router, prefix="/saas/v1")
app.include_router(tenants_router, prefix="/saas/v1")
app.include_router(crm_router, prefix="/saas/v1")
app.include_router(campaigns_router, prefix="/saas/v1")
app.include_router(broadcasts_router, prefix="/saas/v1")
app.include_router(ads_router, prefix="/saas/v1")
app.include_router(integrations_router, prefix="/saas/v1")
app.include_router(api_credentials_router, prefix="/saas/v1")
app.include_router(ai_agent_router, prefix="/saas/v1")
app.include_router(media_router, prefix="/saas/v1")
app.include_router(billing_router, prefix="/saas/v1")
app.include_router(webhooks_router, prefix="/saas/v1")
