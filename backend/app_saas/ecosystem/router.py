from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app_saas.db import db_session, set_tenant_context
from app_saas.ecosystem.schemas import (
    AiAppCreateIn,
    AiAppPatchIn,
    DeveloperAppCreateIn,
    DeveloperAppPatchIn,
    EventSubscriptionCreateIn,
    EventSubscriptionPatchIn,
    ExternalIntegrationCreateIn,
    ExternalIntegrationPatchIn,
    MarketplaceInstallIn,
    PluginCreateIn,
    PluginPatchIn,
    StatusPatchIn,
    ToolCreateIn,
    ToolPatchIn,
)
from app_saas.ecosystem.service import (
    create_ai_app,
    create_developer_app,
    create_event_subscription,
    create_external_integration,
    create_plugin,
    create_tool,
    ecosystem_metrics,
    ecosystem_overview,
    install_marketplace_item,
    list_ai_apps,
    list_developer_apps,
    list_event_subscriptions,
    list_external_integrations,
    list_marketplace_installations,
    list_marketplace_items,
    list_plugins,
    list_tools,
    patch_ai_app,
    patch_developer_app,
    patch_event_subscription,
    patch_external_integration,
    patch_plugin,
    patch_tool,
    rotate_developer_app_key,
    sdk_manifest,
    update_installation,
)
from app_saas.shared.security import AuthContext, get_current_user, require_role

router = APIRouter(prefix="/ecosystem", tags=["saas-ai-ecosystem"])


@router.get("/overview")
def get_ecosystem_overview(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "overview": ecosystem_overview(conn, ctx.tenant_id)}


@router.get("/marketplace")
def get_marketplace(
    item_type: str = Query("", max_length=80),
    category: str = Query("", max_length=80),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "items": list_marketplace_items(conn, ctx.tenant_id, item_type=item_type, category=category)}


@router.get("/installations")
def get_installations(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "installations": list_marketplace_installations(conn, ctx.tenant_id)}


@router.post("/marketplace/{item_id}/install")
def post_marketplace_install(
    item_id: str,
    payload: MarketplaceInstallIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        installation = install_marketplace_item(conn, ctx.tenant_id, ctx.user_id, item_id, payload.model_dump())
        return {"ok": True, "installation": installation}


@router.patch("/installations/{installation_id}")
def patch_installation(
    installation_id: str,
    payload: StatusPatchIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "installation": update_installation(conn, ctx.tenant_id, installation_id, payload.model_dump())}


@router.get("/plugins")
def get_plugins(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "plugins": list_plugins(conn, ctx.tenant_id)}


@router.post("/plugins")
def post_plugin(payload: PluginCreateIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "plugin": create_plugin(conn, ctx.tenant_id, ctx.user_id, payload.model_dump())}


@router.patch("/plugins/{plugin_id}")
def patch_plugin_endpoint(
    plugin_id: str,
    payload: PluginPatchIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "plugin": patch_plugin(conn, ctx.tenant_id, plugin_id, payload.model_dump(), ctx.user_id)}


@router.get("/tools")
def get_tools(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "tools": list_tools(conn, ctx.tenant_id)}


@router.post("/tools")
def post_tool(payload: ToolCreateIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "tool": create_tool(conn, ctx.tenant_id, ctx.user_id, payload.model_dump())}


@router.patch("/tools/{tool_id}")
def patch_tool_endpoint(
    tool_id: str,
    payload: ToolPatchIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "tool": patch_tool(conn, ctx.tenant_id, tool_id, payload.model_dump(), ctx.user_id)}


@router.get("/event-subscriptions")
def get_event_subscriptions(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "subscriptions": list_event_subscriptions(conn, ctx.tenant_id)}


@router.post("/event-subscriptions")
def post_event_subscription(
    payload: EventSubscriptionCreateIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "subscription": create_event_subscription(conn, ctx.tenant_id, ctx.user_id, payload.model_dump())}


@router.patch("/event-subscriptions/{subscription_id}")
def patch_event_subscription_endpoint(
    subscription_id: str,
    payload: EventSubscriptionPatchIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "subscription": patch_event_subscription(conn, ctx.tenant_id, subscription_id, payload.model_dump(), ctx.user_id)}


@router.get("/developer/apps")
def get_developer_apps(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "apps": list_developer_apps(conn, ctx.tenant_id)}


@router.post("/developer/apps")
def post_developer_app(payload: DeveloperAppCreateIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "app": create_developer_app(conn, ctx.tenant_id, ctx.user_id, payload.model_dump())}


@router.patch("/developer/apps/{app_id}")
def patch_developer_app_endpoint(
    app_id: str,
    payload: DeveloperAppPatchIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "app": patch_developer_app(conn, ctx.tenant_id, app_id, payload.model_dump())}


@router.post("/developer/apps/{app_id}/rotate-key")
def post_rotate_developer_app_key(app_id: str, ctx: AuthContext = Depends(require_role("owner", "admin"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "app": rotate_developer_app_key(conn, ctx.tenant_id, app_id)}


@router.get("/sdk/manifest")
def get_sdk_manifest(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "manifest": sdk_manifest(conn, ctx.tenant_id)}


@router.get("/external-integrations")
def get_external_integrations(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "integrations": list_external_integrations(conn, ctx.tenant_id)}


@router.post("/external-integrations")
def post_external_integration(
    payload: ExternalIntegrationCreateIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "integration": create_external_integration(conn, ctx.tenant_id, ctx.user_id, payload.model_dump())}


@router.patch("/external-integrations/{integration_id}")
def patch_external_integration_endpoint(
    integration_id: str,
    payload: ExternalIntegrationPatchIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "integration": patch_external_integration(conn, ctx.tenant_id, integration_id, payload.model_dump(), ctx.user_id)}


@router.get("/ai-apps")
def get_ai_apps(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "apps": list_ai_apps(conn, ctx.tenant_id)}


@router.post("/ai-apps")
def post_ai_app(payload: AiAppCreateIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "app": create_ai_app(conn, ctx.tenant_id, ctx.user_id, payload.model_dump())}


@router.patch("/ai-apps/{app_id}")
def patch_ai_app_endpoint(
    app_id: str,
    payload: AiAppPatchIn,
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "app": patch_ai_app(conn, ctx.tenant_id, app_id, payload.model_dump(), ctx.user_id)}


@router.get("/metrics")
def get_metrics(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        return {"ok": True, "metrics": ecosystem_metrics(conn, ctx.tenant_id)}
