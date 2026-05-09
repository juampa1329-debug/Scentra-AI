from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app_saas.billing.limits import ensure_feature_enabled
from app_saas.ads.schemas import (
    AdAccountIn,
    AdAccountPatchIn,
    AdCampaignIn,
    AdCampaignPatchIn,
    CommentImportIn,
    CommentPatchIn,
    LeadImportIn,
    LeadPatchIn,
)
from app_saas.db import db_session, set_tenant_context
from app_saas.shared.security import AuthContext, get_current_user, require_role

router = APIRouter(prefix="/ads", tags=["saas-ads"])


def _clean(value: object, limit: int = 1000) -> str:
    return str(value or "").strip()[:limit]


def _norm(value: object, default: str = "") -> str:
    return (_clean(value, 80).lower() or default)[:80]


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _period_yyyymm() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m")


def _row(row) -> dict:
    return dict(row) if row else {}


def _ensure_ads(conn, tenant_id: str) -> None:
    ensure_feature_enabled(conn, tenant_id, "ads")


def _conversation_for_social(
    conn,
    *,
    tenant_id: str,
    channel: str,
    external_contact_id: str,
    display_name: str,
    text_value: str,
    msg_type: str,
    external_message_id: str,
    payload: dict[str, Any],
) -> str:
    contact_id = _clean(external_contact_id, 180)
    if not contact_id:
        raise HTTPException(status_code=400, detail="external_contact_id_required")
    body = _clean(text_value, 4000) or f"[{msg_type}]"
    conversation = conn.execute(
        text(
            """
            INSERT INTO saas_conversations (
                tenant_id, channel, external_contact_id, phone, display_name, last_message_text, last_message_at, unread_count, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), :channel, :external_contact_id, '', :display_name, :last_message_text, NOW(), 1, NOW()
            )
            ON CONFLICT (tenant_id, channel, external_contact_id)
            DO UPDATE SET
                display_name = COALESCE(NULLIF(EXCLUDED.display_name, ''), saas_conversations.display_name),
                last_message_text = EXCLUDED.last_message_text,
                last_message_at = NOW(),
                unread_count = saas_conversations.unread_count + 1,
                updated_at = NOW()
            RETURNING id::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "channel": _norm(channel, "facebook"),
            "external_contact_id": contact_id,
            "display_name": _clean(display_name, 180),
            "last_message_text": body,
        },
    ).mappings().first()
    conn.execute(
        text(
            """
            INSERT INTO saas_messages (
                tenant_id, conversation_id, channel, external_message_id, direction, msg_type, text, payload_json
            )
            VALUES (
                CAST(:tenant_id AS uuid), CAST(:conversation_id AS uuid), :channel, :external_message_id,
                'in', :msg_type, :text, CAST(:payload_json AS jsonb)
            )
            ON CONFLICT (tenant_id, channel, external_message_id) DO NOTHING
            """
        ),
        {
            "tenant_id": tenant_id,
            "conversation_id": conversation["id"],
            "channel": _norm(channel, "facebook"),
            "external_message_id": _clean(external_message_id, 240),
            "msg_type": _clean(msg_type, 40),
            "text": body,
            "payload_json": _json(payload),
        },
    )
    return str(conversation["id"])


def _lead_to_conversation(conn, tenant_id: str, lead: dict[str, Any]) -> str:
    contact_id = _clean(lead.get("phone")) or _clean(lead.get("email")) or _clean(lead.get("external_lead_id"))
    display = _clean(lead.get("contact_name")) or _clean(lead.get("email")) or _clean(lead.get("phone")) or "Lead Meta"
    text_value = f"Lead capturado: {display}"
    if lead.get("email"):
        text_value += f" / {lead['email']}"
    if lead.get("phone"):
        text_value += f" / {lead['phone']}"
    return _conversation_for_social(
        conn,
        tenant_id=tenant_id,
        channel=_clean(lead.get("channel")) or "facebook",
        external_contact_id=contact_id,
        display_name=display,
        text_value=text_value,
        msg_type="lead",
        external_message_id=f"lead:{_clean(lead.get('external_lead_id'), 180)}",
        payload=_as_dict(lead.get("payload_json")),
    )


def _comment_to_conversation(conn, tenant_id: str, comment: dict[str, Any]) -> str:
    contact_id = _clean(comment.get("author_id")) or _clean(comment.get("external_comment_id"))
    display = _clean(comment.get("author_name")) or "Comentario social"
    return _conversation_for_social(
        conn,
        tenant_id=tenant_id,
        channel=_clean(comment.get("channel")) or "facebook",
        external_contact_id=contact_id,
        display_name=display,
        text_value=_clean(comment.get("message"), 4000) or "Comentario recibido",
        msg_type="comment",
        external_message_id=f"comment:{_clean(comment.get('external_comment_id'), 180)}",
        payload=_as_dict(comment.get("payload_json")),
    )


def _extract_lead_from_change(provider: str, channel: str, value: dict[str, Any]) -> dict[str, Any] | None:
    lead_id = _clean(value.get("leadgen_id") or value.get("lead_id") or value.get("id"), 180)
    if not lead_id:
        return None
    field_data = value.get("field_data")
    data: dict[str, str] = {}
    if isinstance(field_data, list):
        for item in field_data:
            item_dict = _as_dict(item)
            name = _clean(item_dict.get("name"), 80).lower()
            values = _as_list(item_dict.get("values"))
            if name and values:
                data[name] = _clean(values[0], 500)
    return {
        "provider": provider,
        "channel": channel,
        "external_lead_id": lead_id,
        "external_form_id": _clean(value.get("form_id"), 180),
        "external_ad_id": _clean(value.get("ad_id"), 180),
        "external_campaign_id": _clean(value.get("campaign_id"), 180),
        "contact_name": _clean(value.get("full_name") or value.get("name") or data.get("full_name") or data.get("name"), 180),
        "email": _clean(value.get("email") or data.get("email"), 180),
        "phone": _clean(value.get("phone_number") or value.get("phone") or data.get("phone_number") or data.get("phone"), 80),
        "payload_json": value,
    }


def _extract_comment_from_change(provider: str, channel: str, value: dict[str, Any]) -> dict[str, Any] | None:
    comment_id = _clean(value.get("comment_id") or value.get("id"), 180)
    message = _clean(value.get("message") or value.get("text") or value.get("comment"), 4000)
    if not comment_id and not message:
        return None
    author = _as_dict(value.get("from") or value.get("sender") or value.get("user"))
    fallback_digest = hashlib.sha256(message.encode("utf-8")).hexdigest()[:16] if message else "no-message"
    return {
        "provider": provider,
        "channel": channel,
        "external_comment_id": comment_id or f"{_clean(value.get('post_id'), 120)}:{fallback_digest}",
        "external_parent_id": _clean(value.get("parent_id"), 180),
        "external_post_id": _clean(value.get("post_id") or value.get("media_id"), 180),
        "external_ad_id": _clean(value.get("ad_id"), 180),
        "external_campaign_id": _clean(value.get("campaign_id"), 180),
        "author_id": _clean(author.get("id") or value.get("author_id") or value.get("sender_id"), 180),
        "author_name": _clean(author.get("name") or value.get("author_name") or value.get("username"), 180),
        "message": message or "[comment]",
        "permalink_url": _clean(value.get("permalink_url"), 1000),
        "payload_json": value,
    }


def _extract_social_items(provider: str, payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    provider_clean = _norm(provider, "meta")
    leads: list[dict[str, Any]] = []
    comments: list[dict[str, Any]] = []
    for entry in _as_list(payload.get("entry")):
        entry_dict = _as_dict(entry)
        for change in _as_list(entry_dict.get("changes")):
            change_dict = _as_dict(change)
            field = _norm(change_dict.get("field"))
            value = _as_dict(change_dict.get("value"))
            channel = "instagram" if "instagram" in field or value.get("media_id") else "facebook"
            if field in {"leadgen", "leadgen_id"} or value.get("leadgen_id"):
                lead = _extract_lead_from_change(provider_clean, channel, value)
                if lead:
                    leads.append(lead)
            if field in {"feed", "comments", "comment"} or value.get("comment_id") or value.get("message"):
                if _norm(value.get("item")) not in {"", "comment"}:
                    continue
                comment = _extract_comment_from_change(provider_clean, channel, value)
                if comment:
                    comments.append(comment)

    direct_lead = _extract_lead_from_change(provider_clean, _norm(payload.get("channel"), "facebook"), payload)
    if direct_lead:
        leads.append(direct_lead)
    direct_comment = _extract_comment_from_change(provider_clean, _norm(payload.get("channel"), "facebook"), payload)
    if direct_comment and (payload.get("comment_id") or payload.get("message")):
        comments.append(direct_comment)
    return leads, comments


@router.get("/summary")
def ads_summary(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_ads(conn, ctx.tenant_id)
        row = conn.execute(
            text(
                """
                SELECT
                    (SELECT COUNT(*) FROM saas_ad_accounts WHERE tenant_id = CAST(:tenant_id AS uuid))::int AS accounts,
                    (SELECT COUNT(*) FROM saas_ad_campaigns WHERE tenant_id = CAST(:tenant_id AS uuid))::int AS campaigns,
                    (SELECT COUNT(*) FROM saas_ad_leads WHERE tenant_id = CAST(:tenant_id AS uuid) AND status IN ('new', 'review'))::int AS open_leads,
                    (SELECT COUNT(*) FROM saas_social_comments WHERE tenant_id = CAST(:tenant_id AS uuid) AND status IN ('new', 'review'))::int AS open_comments,
                    (SELECT COUNT(*) FROM saas_webhook_events WHERE tenant_id = CAST(:tenant_id AS uuid) AND provider IN ('meta', 'facebook', 'instagram'))::int AS webhook_events,
                    (SELECT COUNT(*) FROM saas_conversations WHERE tenant_id = CAST(:tenant_id AS uuid) AND channel IN ('facebook', 'instagram'))::int AS social_conversations
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().first()
    return {"tenant_id": ctx.tenant_id, "summary": dict(row or {})}


@router.get("/accounts")
def list_accounts(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_ads(conn, ctx.tenant_id)
        rows = conn.execute(
            text(
                """
                SELECT id::text, provider, external_account_id, name, status, currency, timezone, config_json, last_sync_at::text, created_at::text, updated_at::text
                FROM saas_ad_accounts
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                ORDER BY updated_at DESC
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().all()
    return {"tenant_id": ctx.tenant_id, "accounts": [dict(row) for row in rows]}


@router.post("/accounts")
def upsert_account(payload: AdAccountIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_ads(conn, ctx.tenant_id)
        row = conn.execute(
            text(
                """
                INSERT INTO saas_ad_accounts (tenant_id, provider, external_account_id, name, status, currency, timezone, config_json, last_sync_at)
                VALUES (CAST(:tenant_id AS uuid), :provider, :external_account_id, :name, :status, :currency, :timezone, CAST(:config_json AS jsonb), NOW())
                ON CONFLICT (tenant_id, provider, external_account_id)
                DO UPDATE SET
                    name = EXCLUDED.name,
                    status = EXCLUDED.status,
                    currency = EXCLUDED.currency,
                    timezone = EXCLUDED.timezone,
                    config_json = EXCLUDED.config_json,
                    last_sync_at = NOW(),
                    updated_at = NOW()
                RETURNING id::text, provider, external_account_id, name, status, currency, timezone, config_json, last_sync_at::text, created_at::text, updated_at::text
                """
            ),
            {
                "tenant_id": ctx.tenant_id,
                "provider": _norm(payload.provider, "meta"),
                "external_account_id": _clean(payload.external_account_id, 160),
                "name": _clean(payload.name, 180),
                "status": _norm(payload.status, "connected"),
                "currency": _clean(payload.currency, 20).upper(),
                "timezone": _clean(payload.timezone, 80),
                "config_json": _json(payload.config_json),
            },
        ).mappings().first()
    return {"ok": True, "tenant_id": ctx.tenant_id, "account": dict(row)}


@router.patch("/accounts/{account_id}")
def patch_account(account_id: str, payload: AdAccountPatchIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="account_patch_required")
    assignments: list[str] = []
    params: dict[str, Any] = {"tenant_id": ctx.tenant_id, "account_id": account_id}
    for key, value in data.items():
        if key == "config_json":
            params[key] = _json(value)
            assignments.append("config_json = CAST(:config_json AS jsonb)")
        else:
            params[key] = _clean(value, 180)
            assignments.append(f"{key} = :{key}")
    assignments.append("updated_at = NOW()")
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_ads(conn, ctx.tenant_id)
        row = conn.execute(
            text(
                f"""
                UPDATE saas_ad_accounts
                SET {", ".join(assignments)}
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:account_id AS uuid)
                RETURNING id::text, provider, external_account_id, name, status, currency, timezone, config_json, last_sync_at::text, created_at::text, updated_at::text
                """
            ),
            params,
        ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="account_not_found")
    return {"ok": True, "tenant_id": ctx.tenant_id, "account": dict(row)}


@router.get("/campaigns")
def list_campaigns(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_ads(conn, ctx.tenant_id)
        rows = conn.execute(
            text(
                """
                SELECT c.id::text, c.account_id::text, c.provider, c.channel, c.external_campaign_id, c.name, c.objective, c.status,
                       c.daily_budget_cents, c.lifetime_budget_cents, c.currency, c.metrics_json, c.last_sync_at::text,
                       c.created_at::text, c.updated_at::text, a.name AS account_name
                FROM saas_ad_campaigns c
                LEFT JOIN saas_ad_accounts a ON a.id = c.account_id
                WHERE c.tenant_id = CAST(:tenant_id AS uuid)
                ORDER BY c.updated_at DESC
                """
            ),
            {"tenant_id": ctx.tenant_id},
        ).mappings().all()
    return {"tenant_id": ctx.tenant_id, "campaigns": [dict(row) for row in rows]}


@router.post("/campaigns")
def upsert_campaign(payload: AdCampaignIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_ads(conn, ctx.tenant_id)
        row = conn.execute(
            text(
                """
                INSERT INTO saas_ad_campaigns (
                    tenant_id, account_id, provider, channel, external_campaign_id, name, objective, status,
                    daily_budget_cents, lifetime_budget_cents, currency, metrics_json, last_sync_at
                )
                VALUES (
                    CAST(:tenant_id AS uuid), CAST(NULLIF(:account_id, '') AS uuid), :provider, :channel,
                    :external_campaign_id, :name, :objective, :status, :daily_budget_cents, :lifetime_budget_cents,
                    :currency, CAST(:metrics_json AS jsonb), NOW()
                )
                ON CONFLICT (tenant_id, provider, external_campaign_id)
                DO UPDATE SET
                    account_id = EXCLUDED.account_id,
                    channel = EXCLUDED.channel,
                    name = EXCLUDED.name,
                    objective = EXCLUDED.objective,
                    status = EXCLUDED.status,
                    daily_budget_cents = EXCLUDED.daily_budget_cents,
                    lifetime_budget_cents = EXCLUDED.lifetime_budget_cents,
                    currency = EXCLUDED.currency,
                    metrics_json = EXCLUDED.metrics_json,
                    last_sync_at = NOW(),
                    updated_at = NOW()
                RETURNING id::text, account_id::text, provider, channel, external_campaign_id, name, objective, status, daily_budget_cents, lifetime_budget_cents, currency, metrics_json, last_sync_at::text, created_at::text, updated_at::text
                """
            ),
            {
                "tenant_id": ctx.tenant_id,
                "account_id": _clean(payload.account_id, 80),
                "provider": _norm(payload.provider, "meta"),
                "channel": _norm(payload.channel, "facebook"),
                "external_campaign_id": _clean(payload.external_campaign_id, 160),
                "name": _clean(payload.name, 180),
                "objective": _clean(payload.objective, 120),
                "status": _norm(payload.status, "unknown"),
                "daily_budget_cents": int(payload.daily_budget_cents or 0),
                "lifetime_budget_cents": int(payload.lifetime_budget_cents or 0),
                "currency": _clean(payload.currency, 20).upper(),
                "metrics_json": _json(payload.metrics_json),
            },
        ).mappings().first()
    return {"ok": True, "tenant_id": ctx.tenant_id, "campaign": dict(row)}


@router.patch("/campaigns/{campaign_id}")
def patch_campaign(campaign_id: str, payload: AdCampaignPatchIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor"))):
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="campaign_patch_required")
    assignments: list[str] = []
    params: dict[str, Any] = {"tenant_id": ctx.tenant_id, "campaign_id": campaign_id}
    for key, value in data.items():
        if key == "metrics_json":
            params[key] = _json(value)
            assignments.append("metrics_json = CAST(:metrics_json AS jsonb)")
        elif key == "account_id":
            params[key] = _clean(value, 80)
            assignments.append("account_id = CAST(NULLIF(:account_id, '') AS uuid)")
        elif key in {"daily_budget_cents", "lifetime_budget_cents"}:
            params[key] = int(value or 0)
            assignments.append(f"{key} = :{key}")
        else:
            params[key] = _clean(value, 180)
            assignments.append(f"{key} = :{key}")
    assignments.append("updated_at = NOW()")
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_ads(conn, ctx.tenant_id)
        row = conn.execute(
            text(
                f"""
                UPDATE saas_ad_campaigns
                SET {", ".join(assignments)}
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:campaign_id AS uuid)
                RETURNING id::text, account_id::text, provider, channel, external_campaign_id, name, objective, status, daily_budget_cents, lifetime_budget_cents, currency, metrics_json, last_sync_at::text, created_at::text, updated_at::text
                """
            ),
            params,
        ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="campaign_not_found")
    return {"ok": True, "tenant_id": ctx.tenant_id, "campaign": dict(row)}


def _upsert_lead(conn, tenant_id: str, data: dict[str, Any], *, create_conversation: bool = False) -> dict:
    row = conn.execute(
        text(
            """
            INSERT INTO saas_ad_leads (
                tenant_id, provider, channel, external_lead_id, external_form_id, external_ad_id, external_campaign_id,
                contact_name, email, phone, status, payload_json
            )
            VALUES (
                CAST(:tenant_id AS uuid), :provider, :channel, :external_lead_id, :external_form_id, :external_ad_id,
                :external_campaign_id, :contact_name, :email, :phone, :status, CAST(:payload_json AS jsonb)
            )
            ON CONFLICT (tenant_id, provider, external_lead_id)
            DO UPDATE SET
                channel = EXCLUDED.channel,
                external_form_id = EXCLUDED.external_form_id,
                external_ad_id = EXCLUDED.external_ad_id,
                external_campaign_id = EXCLUDED.external_campaign_id,
                contact_name = COALESCE(NULLIF(EXCLUDED.contact_name, ''), saas_ad_leads.contact_name),
                email = COALESCE(NULLIF(EXCLUDED.email, ''), saas_ad_leads.email),
                phone = COALESCE(NULLIF(EXCLUDED.phone, ''), saas_ad_leads.phone),
                payload_json = saas_ad_leads.payload_json || EXCLUDED.payload_json,
                updated_at = NOW()
            RETURNING id::text, provider, channel, external_lead_id, external_form_id, external_ad_id, external_campaign_id,
                      contact_name, email, phone, status, conversation_id::text, payload_json, received_at::text, converted_at::text, created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "provider": _norm(data.get("provider"), "meta"),
            "channel": _norm(data.get("channel"), "facebook"),
            "external_lead_id": _clean(data.get("external_lead_id"), 180),
            "external_form_id": _clean(data.get("external_form_id"), 180),
            "external_ad_id": _clean(data.get("external_ad_id"), 180),
            "external_campaign_id": _clean(data.get("external_campaign_id"), 180),
            "contact_name": _clean(data.get("contact_name"), 180),
            "email": _clean(data.get("email"), 180),
            "phone": _clean(data.get("phone"), 80),
            "status": _norm(data.get("status"), "new"),
            "payload_json": _json(data.get("payload_json")),
        },
    ).mappings().first()
    lead = dict(row)
    if create_conversation:
        conversation_id = _lead_to_conversation(conn, tenant_id, lead)
        row = conn.execute(
            text(
                """
                UPDATE saas_ad_leads
                SET conversation_id = CAST(:conversation_id AS uuid),
                    status = 'converted',
                    converted_at = COALESCE(converted_at, NOW()),
                    updated_at = NOW()
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:lead_id AS uuid)
                RETURNING id::text, provider, channel, external_lead_id, external_form_id, external_ad_id, external_campaign_id,
                          contact_name, email, phone, status, conversation_id::text, payload_json, received_at::text, converted_at::text, created_at::text, updated_at::text
                """
            ),
            {"tenant_id": tenant_id, "lead_id": lead["id"], "conversation_id": conversation_id},
        ).mappings().first()
        lead = dict(row)
    return lead


@router.get("/leads")
def list_leads(status: str = Query("all", max_length=40), ctx: AuthContext = Depends(get_current_user)):
    where = ["tenant_id = CAST(:tenant_id AS uuid)"]
    params = {"tenant_id": ctx.tenant_id}
    if status and status != "all":
        where.append("status = :status")
        params["status"] = _norm(status)
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_ads(conn, ctx.tenant_id)
        rows = conn.execute(
            text(
                f"""
                SELECT id::text, provider, channel, external_lead_id, external_form_id, external_ad_id, external_campaign_id,
                       contact_name, email, phone, status, conversation_id::text, payload_json, received_at::text, converted_at::text, created_at::text, updated_at::text
                FROM saas_ad_leads
                WHERE {" AND ".join(where)}
                ORDER BY received_at DESC
                LIMIT 300
                """
            ),
            params,
        ).mappings().all()
    return {"tenant_id": ctx.tenant_id, "leads": [dict(row) for row in rows]}


@router.post("/leads/import")
def import_lead(payload: LeadImportIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor", "agent"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_ads(conn, ctx.tenant_id)
        lead = _upsert_lead(conn, ctx.tenant_id, payload.model_dump(), create_conversation=payload.create_conversation)
    return {"ok": True, "tenant_id": ctx.tenant_id, "lead": lead}


@router.patch("/leads/{lead_id}")
def patch_lead(lead_id: str, payload: LeadPatchIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor", "agent"))):
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="lead_patch_required")
    assignments: list[str] = []
    params: dict[str, Any] = {"tenant_id": ctx.tenant_id, "lead_id": lead_id}
    for key, value in data.items():
        params[key] = _clean(value, 180)
        assignments.append(f"{key} = :{key}")
    assignments.append("updated_at = NOW()")
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_ads(conn, ctx.tenant_id)
        row = conn.execute(
            text(
                f"""
                UPDATE saas_ad_leads
                SET {", ".join(assignments)}
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:lead_id AS uuid)
                RETURNING id::text, provider, channel, external_lead_id, contact_name, email, phone, status, conversation_id::text, payload_json, received_at::text, converted_at::text, created_at::text, updated_at::text
                """
            ),
            params,
        ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="lead_not_found")
    return {"ok": True, "tenant_id": ctx.tenant_id, "lead": dict(row)}


@router.post("/leads/{lead_id}/to-inbox")
def lead_to_inbox(lead_id: str, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor", "agent"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_ads(conn, ctx.tenant_id)
        lead = conn.execute(
            text(
                """
                SELECT id::text, provider, channel, external_lead_id, contact_name, email, phone, payload_json
                FROM saas_ad_leads
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:lead_id AS uuid)
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id, "lead_id": lead_id},
        ).mappings().first()
        if not lead:
            raise HTTPException(status_code=404, detail="lead_not_found")
        conversation_id = _lead_to_conversation(conn, ctx.tenant_id, dict(lead))
        conn.execute(
            text(
                """
                UPDATE saas_ad_leads
                SET conversation_id = CAST(:conversation_id AS uuid), status = 'converted', converted_at = COALESCE(converted_at, NOW()), updated_at = NOW()
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:lead_id AS uuid)
                """
            ),
            {"tenant_id": ctx.tenant_id, "lead_id": lead_id, "conversation_id": conversation_id},
        )
    return {"ok": True, "tenant_id": ctx.tenant_id, "conversation_id": conversation_id}


def _upsert_comment(conn, tenant_id: str, data: dict[str, Any], *, create_conversation: bool = False) -> dict:
    row = conn.execute(
        text(
            """
            INSERT INTO saas_social_comments (
                tenant_id, provider, channel, external_comment_id, external_parent_id, external_post_id, external_ad_id,
                external_campaign_id, author_id, author_name, message, permalink_url, status, payload_json
            )
            VALUES (
                CAST(:tenant_id AS uuid), :provider, :channel, :external_comment_id, :external_parent_id,
                :external_post_id, :external_ad_id, :external_campaign_id, :author_id, :author_name, :message,
                :permalink_url, :status, CAST(:payload_json AS jsonb)
            )
            ON CONFLICT (tenant_id, provider, external_comment_id)
            DO UPDATE SET
                message = COALESCE(NULLIF(EXCLUDED.message, ''), saas_social_comments.message),
                author_name = COALESCE(NULLIF(EXCLUDED.author_name, ''), saas_social_comments.author_name),
                payload_json = saas_social_comments.payload_json || EXCLUDED.payload_json,
                updated_at = NOW()
            RETURNING id::text, provider, channel, external_comment_id, external_parent_id, external_post_id, external_ad_id,
                      external_campaign_id, author_id, author_name, message, permalink_url, status, conversation_id::text,
                      payload_json, received_at::text, replied_at::text, resolved_at::text, created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "provider": _norm(data.get("provider"), "meta"),
            "channel": _norm(data.get("channel"), "facebook"),
            "external_comment_id": _clean(data.get("external_comment_id"), 180),
            "external_parent_id": _clean(data.get("external_parent_id"), 180),
            "external_post_id": _clean(data.get("external_post_id"), 180),
            "external_ad_id": _clean(data.get("external_ad_id"), 180),
            "external_campaign_id": _clean(data.get("external_campaign_id"), 180),
            "author_id": _clean(data.get("author_id"), 180),
            "author_name": _clean(data.get("author_name"), 180),
            "message": _clean(data.get("message"), 4000),
            "permalink_url": _clean(data.get("permalink_url"), 1000),
            "status": _norm(data.get("status"), "new"),
            "payload_json": _json(data.get("payload_json")),
        },
    ).mappings().first()
    comment = dict(row)
    if create_conversation:
        conversation_id = _comment_to_conversation(conn, tenant_id, comment)
        row = conn.execute(
            text(
                """
                UPDATE saas_social_comments
                SET conversation_id = CAST(:conversation_id AS uuid), status = 'review', updated_at = NOW()
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:comment_id AS uuid)
                RETURNING id::text, provider, channel, external_comment_id, external_parent_id, external_post_id, external_ad_id,
                          external_campaign_id, author_id, author_name, message, permalink_url, status, conversation_id::text,
                          payload_json, received_at::text, replied_at::text, resolved_at::text, created_at::text, updated_at::text
                """
            ),
            {"tenant_id": tenant_id, "comment_id": comment["id"], "conversation_id": conversation_id},
        ).mappings().first()
        comment = dict(row)
    return comment


@router.get("/comments")
def list_comments(status: str = Query("all", max_length=40), ctx: AuthContext = Depends(get_current_user)):
    where = ["tenant_id = CAST(:tenant_id AS uuid)"]
    params = {"tenant_id": ctx.tenant_id}
    if status and status != "all":
        where.append("status = :status")
        params["status"] = _norm(status)
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_ads(conn, ctx.tenant_id)
        rows = conn.execute(
            text(
                f"""
                SELECT id::text, provider, channel, external_comment_id, external_parent_id, external_post_id, external_ad_id,
                       external_campaign_id, author_id, author_name, message, permalink_url, status, conversation_id::text,
                       payload_json, received_at::text, replied_at::text, resolved_at::text, created_at::text, updated_at::text
                FROM saas_social_comments
                WHERE {" AND ".join(where)}
                ORDER BY received_at DESC
                LIMIT 300
                """
            ),
            params,
        ).mappings().all()
    return {"tenant_id": ctx.tenant_id, "comments": [dict(row) for row in rows]}


@router.post("/comments/import")
def import_comment(payload: CommentImportIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor", "agent"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_ads(conn, ctx.tenant_id)
        comment = _upsert_comment(conn, ctx.tenant_id, payload.model_dump(), create_conversation=payload.create_conversation)
    return {"ok": True, "tenant_id": ctx.tenant_id, "comment": comment}


@router.patch("/comments/{comment_id}")
def patch_comment(comment_id: str, payload: CommentPatchIn, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor", "agent"))):
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="comment_patch_required")
    assignments: list[str] = []
    params: dict[str, Any] = {"tenant_id": ctx.tenant_id, "comment_id": comment_id}
    for key, value in data.items():
        params[key] = _clean(value, 4000 if key == "message" else 1000)
        assignments.append(f"{key} = :{key}")
    if data.get("status") == "resolved":
        assignments.append("resolved_at = COALESCE(resolved_at, NOW())")
    assignments.append("updated_at = NOW()")
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_ads(conn, ctx.tenant_id)
        row = conn.execute(
            text(
                f"""
                UPDATE saas_social_comments
                SET {", ".join(assignments)}
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:comment_id AS uuid)
                RETURNING id::text, provider, channel, external_comment_id, author_id, author_name, message, permalink_url, status, conversation_id::text, payload_json, received_at::text, replied_at::text, resolved_at::text, created_at::text, updated_at::text
                """
            ),
            params,
        ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="comment_not_found")
    return {"ok": True, "tenant_id": ctx.tenant_id, "comment": dict(row)}


@router.post("/comments/{comment_id}/to-inbox")
def comment_to_inbox(comment_id: str, ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor", "agent"))):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_ads(conn, ctx.tenant_id)
        comment = conn.execute(
            text(
                """
                SELECT id::text, provider, channel, external_comment_id, author_id, author_name, message, payload_json
                FROM saas_social_comments
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:comment_id AS uuid)
                LIMIT 1
                """
            ),
            {"tenant_id": ctx.tenant_id, "comment_id": comment_id},
        ).mappings().first()
        if not comment:
            raise HTTPException(status_code=404, detail="comment_not_found")
        conversation_id = _comment_to_conversation(conn, ctx.tenant_id, dict(comment))
        conn.execute(
            text(
                """
                UPDATE saas_social_comments
                SET conversation_id = CAST(:conversation_id AS uuid), status = 'review', updated_at = NOW()
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:comment_id AS uuid)
                """
            ),
            {"tenant_id": ctx.tenant_id, "comment_id": comment_id, "conversation_id": conversation_id},
        )
    return {"ok": True, "tenant_id": ctx.tenant_id, "conversation_id": conversation_id}


@router.post("/webhook-events/process")
def process_ads_webhook_events(
    limit: int = Query(50, ge=1, le=200),
    ctx: AuthContext = Depends(require_role("owner", "admin", "supervisor")),
):
    stats = {"events": 0, "leads": 0, "comments": 0, "conversations": 0, "ignored": 0}
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        _ensure_ads(conn, ctx.tenant_id)
        rows = conn.execute(
            text(
                """
                SELECT id::text, provider, event_id, payload_json
                FROM saas_webhook_events
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND provider IN ('meta', 'facebook', 'instagram')
                  AND status = 'received'
                ORDER BY received_at DESC
                LIMIT :limit
                """
            ),
            {"tenant_id": ctx.tenant_id, "limit": int(limit)},
        ).mappings().all()
        for row in rows:
            stats["events"] += 1
            payload = _as_dict(row["payload_json"])
            leads, comments = _extract_social_items(str(row["provider"]), payload)
            if not leads and not comments:
                stats["ignored"] += 1
                conn.execute(
                    text(
                        """
                        UPDATE saas_webhook_events
                        SET status = 'ignored', processed_at = COALESCE(processed_at, NOW()), error = 'no_ads_payload'
                        WHERE id = CAST(:id AS uuid)
                        """
                    ),
                    {"id": row["id"]},
                )
                continue
            for lead in leads:
                lead["payload_json"] = {"webhook_event_id": row["id"], **_as_dict(lead.get("payload_json"))}
                saved = _upsert_lead(conn, ctx.tenant_id, lead, create_conversation=True)
                stats["leads"] += 1
                if saved.get("conversation_id"):
                    stats["conversations"] += 1
            for comment in comments:
                comment["payload_json"] = {"webhook_event_id": row["id"], **_as_dict(comment.get("payload_json"))}
                saved = _upsert_comment(conn, ctx.tenant_id, comment, create_conversation=True)
                stats["comments"] += 1
                if saved.get("conversation_id"):
                    stats["conversations"] += 1
            conn.execute(
                text(
                    """
                    UPDATE saas_webhook_events
                    SET status = 'processed', processed_at = COALESCE(processed_at, NOW()), error = ''
                    WHERE id = CAST(:id AS uuid)
                    """
                ),
                {"id": row["id"]},
            )

        if stats["leads"] or stats["comments"]:
            conn.execute(
                text(
                    """
                    INSERT INTO saas_usage_counters (tenant_id, metric_code, period_yyyymm, metric_value)
                    VALUES (CAST(:tenant_id AS uuid), 'webhook_events', :period, :count)
                    ON CONFLICT (tenant_id, metric_code, period_yyyymm)
                    DO UPDATE SET metric_value = saas_usage_counters.metric_value + EXCLUDED.metric_value, updated_at = NOW()
                    """
                ),
                {"tenant_id": ctx.tenant_id, "period": _period_yyyymm(), "count": stats["leads"] + stats["comments"]},
            )
    return {"ok": True, "tenant_id": ctx.tenant_id, "result": stats}
