from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text

from app_saas.db import db_session, set_tenant_context
from app_saas.notifications.schemas import AdminNotificationCreateIn, AdminNotificationDraftIn, NotificationReadOut
from app_saas.shared.email import send_scentra_notification_email, smtp_is_configured
from app_saas.shared.security import AuthContext, PlatformAuthContext, get_current_user, require_platform_role

router = APIRouter(tags=["saas-notifications"])

TENANT_ROLES = {"owner", "admin", "supervisor", "agent", "viewer"}
SEVERITIES = {"info", "success", "warning", "critical"}
SEVERITY_LABELS = {
    "info": "Información",
    "success": "Confirmación",
    "warning": "Alerta",
    "critical": "Alerta crítica",
}


def _clean(value: object, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def _audit(conn, *, actor: PlatformAuthContext, action: str, resource_type: str, resource_id: str = "", details: dict[str, Any] | None = None) -> None:
    conn.execute(
        text(
            """
            INSERT INTO saas_audit_events (actor_user_id, action, resource_type, resource_id, details_json)
            VALUES (CAST(:actor_user_id AS uuid), :action, :resource_type, :resource_id, CAST(:details_json AS jsonb))
            """
        ),
        {
            "actor_user_id": actor.user_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "details_json": _json(details or {}),
        },
    )


def _recipient_rows(conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT DISTINCT
                u.id::text AS user_id,
                u.email,
                u.full_name,
                u.status AS user_status,
                t.id::text AS tenant_id,
                t.name AS tenant_name,
                t.status AS tenant_status,
                m.role AS membership_role
            FROM saas_memberships m
            JOIN saas_users u ON u.id = m.user_id
            JOIN saas_tenants t ON t.id = m.tenant_id
            WHERE m.is_active = TRUE
              AND u.status = 'active'
              AND t.status IN ('active', 'trial', 'past_due')
            ORDER BY t.name ASC, u.email ASC
            LIMIT 5000
            """
        )
    ).mappings().all()
    return [dict(row) for row in rows]


def _resolve_recipients(conn, payload: AdminNotificationCreateIn) -> list[dict[str, Any]]:
    tenant_ids = {str(item).strip() for item in payload.tenant_ids if str(item).strip()}
    user_ids = {str(item).strip() for item in payload.user_ids if str(item).strip()}
    roles = {str(item).strip().lower() for item in payload.roles if str(item).strip()}
    rows = _recipient_rows(conn)
    selected: list[dict[str, Any]] = []
    for row in rows:
        role = str(row.get("membership_role") or "").strip().lower()
        if payload.audience_type != "all":
            matches_user = bool(user_ids and str(row["user_id"]) in user_ids)
            matches_tenant = bool(tenant_ids and str(row["tenant_id"]) in tenant_ids)
            matches_role = bool(roles and role in roles)
            if not (matches_user or matches_tenant or matches_role):
                continue
        selected.append(row)
    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in selected:
        deduped[(str(row["tenant_id"]), str(row["user_id"]))] = row
    return list(deduped.values())[:1000]


@router.get("/notifications")
def list_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=100),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        rows = conn.execute(
            text(
                """
                SELECT
                    r.id::text AS recipient_id,
                    n.id::text AS notification_id,
                    n.title,
                    n.body,
                    n.severity,
                    n.category,
                    n.audience_type,
                    n.ai_assisted,
                    n.email_copy,
                    n.created_at::text,
                    n.sent_at::text,
                    r.read_at::text,
                    r.dismissed_at::text,
                    r.popup_until_read,
                    r.pinned_until_read,
                    r.email_sent,
                    r.email_error,
                    r.membership_role
                FROM saas_system_notification_recipients r
                JOIN saas_system_notifications n ON n.id = r.notification_id
                WHERE r.tenant_id = CAST(:tenant_id AS uuid)
                  AND r.user_id = CAST(:user_id AS uuid)
                  AND (:unread_only = FALSE OR r.read_at IS NULL)
                ORDER BY
                  CASE WHEN r.read_at IS NULL AND r.pinned_until_read = TRUE THEN 0 ELSE 1 END,
                  n.created_at DESC
                LIMIT :limit
                """
            ),
            {"tenant_id": ctx.tenant_id, "user_id": ctx.user_id, "unread_only": unread_only, "limit": limit},
        ).mappings().all()
        unread_count = int(
            conn.execute(
                text(
                    """
                    SELECT COUNT(*)::int
                    FROM saas_system_notification_recipients
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND user_id = CAST(:user_id AS uuid)
                      AND read_at IS NULL
                    """
                ),
                {"tenant_id": ctx.tenant_id, "user_id": ctx.user_id},
            ).scalar_one()
            or 0
        )
    return {"ok": True, "unread_count": unread_count, "notifications": [dict(row) for row in rows]}


@router.post("/notifications/{recipient_id}/read", response_model=NotificationReadOut)
def mark_notification_read(recipient_id: str, ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        row = conn.execute(
            text(
                """
                UPDATE saas_system_notification_recipients
                SET read_at = COALESCE(read_at, NOW()),
                    popup_until_read = FALSE,
                    pinned_until_read = FALSE,
                    updated_at = NOW()
                WHERE id = CAST(:recipient_id AS uuid)
                  AND tenant_id = CAST(:tenant_id AS uuid)
                  AND user_id = CAST(:user_id AS uuid)
                RETURNING id::text
                """
            ),
            {"recipient_id": recipient_id, "tenant_id": ctx.tenant_id, "user_id": ctx.user_id},
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="notification_not_found")
        unread_count = int(
            conn.execute(
                text(
                    """
                    SELECT COUNT(*)::int
                    FROM saas_system_notification_recipients
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND user_id = CAST(:user_id AS uuid)
                      AND read_at IS NULL
                    """
                ),
                {"tenant_id": ctx.tenant_id, "user_id": ctx.user_id},
            ).scalar_one()
            or 0
        )
    return NotificationReadOut(unread_count=unread_count)


@router.post("/notifications/read-all", response_model=NotificationReadOut)
def mark_all_notifications_read(ctx: AuthContext = Depends(get_current_user)):
    with db_session() as conn:
        set_tenant_context(conn, ctx.tenant_id)
        conn.execute(
            text(
                """
                UPDATE saas_system_notification_recipients
                SET read_at = COALESCE(read_at, NOW()),
                    popup_until_read = FALSE,
                    pinned_until_read = FALSE,
                    updated_at = NOW()
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND user_id = CAST(:user_id AS uuid)
                  AND read_at IS NULL
                """
            ),
            {"tenant_id": ctx.tenant_id, "user_id": ctx.user_id},
        )
    return NotificationReadOut(unread_count=0)


@router.get("/admin/notifications/targets")
def admin_notification_targets(ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support"))):
    with db_session() as conn:
        tenants = conn.execute(
            text(
                """
                SELECT id::text, name, status, plan_code
                FROM saas_tenants
                ORDER BY updated_at DESC
                LIMIT 500
                """
            )
        ).mappings().all()
        users = _recipient_rows(conn)
    return {
        "ok": True,
        "smtp_configured": smtp_is_configured(),
        "roles": sorted(TENANT_ROLES),
        "tenants": [dict(row) for row in tenants],
        "users": users,
    }


@router.get("/admin/notifications")
def admin_list_notifications(
    limit: int = Query(80, ge=1, le=200),
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support")),
):
    with db_session() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    n.id::text,
                    n.title,
                    n.severity,
                    n.category,
                    n.audience_type,
                    n.ai_assisted,
                    n.email_copy,
                    n.status,
                    n.created_at::text,
                    n.sent_at::text,
                    COALESCE(COUNT(r.id), 0)::int AS recipients,
                    COALESCE(SUM(CASE WHEN r.read_at IS NOT NULL THEN 1 ELSE 0 END), 0)::int AS read_count,
                    COALESCE(SUM(CASE WHEN r.email_sent = TRUE THEN 1 ELSE 0 END), 0)::int AS email_sent_count
                FROM saas_system_notifications n
                LEFT JOIN saas_system_notification_recipients r ON r.notification_id = n.id
                GROUP BY n.id
                ORDER BY n.created_at DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        ).mappings().all()
    return {"ok": True, "notifications": [dict(row) for row in rows]}


@router.post("/admin/notifications/draft-ai")
def admin_notification_draft(payload: AdminNotificationDraftIn, ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin", "support"))):
    topic = _clean(payload.topic, 160) or "Actualización importante de Scentra"
    audience = _clean(payload.audience, 140) or "usuarios de Scentra"
    tone = _clean(payload.tone, 60).lower() or "claro"
    urgency = _clean(payload.urgency, 60).lower() or "normal"
    prefix = "Importante" if urgency in {"alta", "urgente", "critical", "critica", "crítica"} else "Actualización"
    title = f"{prefix}: {topic}"[:180]
    body_hint = _clean(payload.body_hint, 1000)
    body = (
        "Hola,\n\n"
        f"Tenemos una comunicación para {audience}: {topic}.\n\n"
        f"{body_hint + chr(10) + chr(10) if body_hint else ''}"
        "Revisa esta información antes de continuar con tus operaciones. "
        "Si necesitas apoyo, contacta al equipo administrador de Scentra."
    )
    return {"ok": True, "title": title, "body": body, "ai_assisted": False, "draft_source": "template_assist", "tone": tone}


@router.post("/admin/notifications")
def admin_send_notification(
    payload: AdminNotificationCreateIn,
    request: Request,
    ctx: PlatformAuthContext = Depends(require_platform_role("superadmin", "platform_admin")),
):
    severity = _clean(payload.severity, 40).lower() or "info"
    if severity not in SEVERITIES:
        raise HTTPException(status_code=400, detail="invalid_notification_severity")

    recipients_count = 0
    email_sent = 0
    email_errors = 0
    notification_id = ""
    recipients: list[dict[str, Any]] = []

    with db_session() as conn:
        recipients = _resolve_recipients(conn, payload)
        if not recipients:
            raise HTTPException(status_code=400, detail="notification_recipients_required")
        notification_id = conn.execute(
            text(
                """
                INSERT INTO saas_system_notifications (
                    sender_user_id, sender_platform_role, title, body, severity, category,
                    audience_type, target_roles_json, metadata_json, ai_assisted, email_copy, status, sent_at
                )
                VALUES (
                    CAST(:sender_user_id AS uuid), :sender_platform_role, :title, :body, :severity, :category,
                    :audience_type, CAST(:target_roles_json AS jsonb), CAST(:metadata_json AS jsonb),
                    :ai_assisted, :email_copy, 'sent', NOW()
                )
                RETURNING id::text
                """
            ),
            {
                "sender_user_id": ctx.user_id,
                "sender_platform_role": ctx.platform_role,
                "title": _clean(payload.title, 180),
                "body": str(payload.body or "").strip()[:4000],
                "severity": severity,
                "category": _clean(payload.category, 80) or "system",
                "audience_type": _clean(payload.audience_type, 40) or "selected",
                "target_roles_json": _json(payload.roles or []),
                "metadata_json": _json(
                    {
                        "ip": request.client.host if request.client else "",
                        "tenant_ids": payload.tenant_ids,
                        "user_ids": payload.user_ids,
                    }
                ),
                "ai_assisted": bool(payload.ai_assisted),
                "email_copy": bool(payload.email_copy),
            },
        ).scalar_one()
        for item in recipients:
            conn.execute(
                text(
                    """
                    INSERT INTO saas_system_notification_recipients (
                        notification_id, tenant_id, user_id, membership_role, delivery_channel,
                        popup_until_read, pinned_until_read
                    )
                    VALUES (
                        CAST(:notification_id AS uuid), CAST(:tenant_id AS uuid), CAST(:user_id AS uuid),
                        :membership_role, 'in_app', TRUE, TRUE
                    )
                    ON CONFLICT (notification_id, tenant_id, user_id) DO NOTHING
                    """
                ),
                {
                    "notification_id": notification_id,
                    "tenant_id": item["tenant_id"],
                    "user_id": item["user_id"],
                    "membership_role": item.get("membership_role") or "",
                },
            )
            recipients_count += 1

    email_updates: list[dict[str, Any]] = []
    if payload.email_copy and smtp_is_configured():
        for item in recipients:
            error = ""
            sent = False
            try:
                sent = send_scentra_notification_email(
                    to_email=item["email"],
                    subject=_clean(payload.title, 180),
                    title=_clean(payload.title, 180),
                    body=str(payload.body or "").strip(),
                    cta_label="Abrir Scentra",
                    cta_url="https://app.scentra-ai.online",
                    preheader=f"{SEVERITY_LABELS.get(severity, 'Notificación')} de Scentra +AI.",
                    footer_note="Recibes este correo porque un administrador de Scentra envió una comunicación interna a tu cuenta.",
                    severity=severity,
                )
            except Exception as exc:  # noqa: BLE001 - email failure is stored per recipient.
                error = str(exc)[:500]
            if sent:
                email_sent += 1
            elif error:
                email_errors += 1
            email_updates.append(
                {
                    "notification_id": notification_id,
                    "tenant_id": item["tenant_id"],
                    "user_id": item["user_id"],
                    "email_sent": sent,
                    "email_error": error,
                }
            )

    with db_session() as conn:
        for update in email_updates:
            conn.execute(
                text(
                    """
                    UPDATE saas_system_notification_recipients
                    SET email_sent = :email_sent,
                        email_error = :email_error,
                        updated_at = NOW()
                    WHERE notification_id = CAST(:notification_id AS uuid)
                      AND tenant_id = CAST(:tenant_id AS uuid)
                      AND user_id = CAST(:user_id AS uuid)
                    """
                ),
                update,
            )
        _audit(
            conn,
            actor=ctx,
            action="admin.notification.send",
            resource_type="system_notification",
            resource_id=notification_id,
            details={"recipients": recipients_count, "email_sent": email_sent, "email_errors": email_errors},
        )

    return {
        "ok": True,
        "notification_id": notification_id,
        "recipients": recipients_count,
        "email_sent": email_sent,
        "email_errors": email_errors,
    }
