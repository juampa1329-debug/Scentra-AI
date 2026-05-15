from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app_saas.api_credentials.router import router as api_credentials_router
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
app.include_router(media_router, prefix="/saas/v1")
app.include_router(billing_router, prefix="/saas/v1")
app.include_router(webhooks_router, prefix="/saas/v1")
