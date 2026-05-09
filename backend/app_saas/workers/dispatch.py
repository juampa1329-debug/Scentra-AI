from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from app_saas.billing.limits import tenant_entitlements
from app_saas.db import db_session, set_tenant_context


class DispatchPermanentError(Exception):
    pass


class DispatchTransientError(Exception):
    pass


def _period_yyyymm() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m")


def _load_connected_integration(conn, tenant_id: str, channel: str) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            """
            SELECT provider, channel, status, secret_ref, config_json
            FROM saas_integrations
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND channel = :channel
              AND status = 'connected'
            ORDER BY updated_at DESC
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "channel": channel},
    ).mappings().first()
    return dict(row) if row else None


def _mark_message_dispatch(conn, message_id: str | None, status: str, provider_message_id: str = "", error: str = "") -> None:
    if not message_id:
        return
    dispatch_payload = {
        "dispatch_status": status,
        "provider_message_id": provider_message_id,
        "error": error,
    }
    conn.execute(
        text(
            """
            UPDATE saas_messages
            SET payload_json = payload_json || CAST(:dispatch_payload AS jsonb)
            WHERE id = CAST(:message_id AS uuid)
            """
        ),
        {"message_id": message_id, "dispatch_payload": json.dumps(dispatch_payload)},
    )


def _integration_config(integration: dict[str, Any]) -> dict[str, Any]:
    raw = integration.get("config_json") or {}
    return raw if isinstance(raw, dict) else {}


def _job_payload(job: dict[str, Any]) -> dict[str, Any]:
    raw = job.get("payload_json") or {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _mark_outbound(
    conn,
    job_id: str,
    *,
    status: str,
    provider: str = "",
    error: str = "",
    provider_response: dict[str, Any] | None = None,
    ) -> None:
    provider_message_id = str((provider_response or {}).get("id") or (provider_response or {}).get("provider_message_id") or "")
    response_json = json.dumps({"provider_response": provider_response or {}})
    conn.execute(
        text(
            """
            UPDATE saas_outbound_messages
            SET status = :status,
                provider = COALESCE(NULLIF(:provider, ''), provider),
                sent_at = CASE WHEN :status = 'sent' THEN NOW() ELSE sent_at END,
                locked_at = NULL,
                error = :error,
                payload_json = payload_json || CAST(:response_json AS jsonb),
                updated_at = NOW()
            WHERE id = CAST(:id AS uuid)
            """
        ),
        {
            "id": job_id,
            "status": status,
            "provider": provider,
            "error": error[:500],
            "response_json": response_json,
        },
    )
    recipient_status = "sent" if status == "sent" else "failed" if status in {"failed", "blocked"} else status
    conn.execute(
        text(
            """
            UPDATE saas_broadcast_recipients
            SET status = :recipient_status,
                sent_at = CASE WHEN :recipient_status = 'sent' THEN COALESCE(sent_at, NOW()) ELSE sent_at END,
                failed_at = CASE WHEN :recipient_status = 'failed' THEN COALESCE(failed_at, NOW()) ELSE failed_at END,
                provider_message_id = COALESCE(NULLIF(:provider_message_id, ''), provider_message_id),
                error = :error,
                updated_at = NOW()
            WHERE outbound_id = CAST(:id AS uuid)
            """
        ),
        {
            "id": job_id,
            "recipient_status": recipient_status,
            "provider_message_id": provider_message_id,
            "error": error[:500],
        },
    )
    conn.execute(
        text(
            """
            UPDATE saas_broadcasts b
            SET sent_count = counts.sent_count,
                failed_count = counts.failed_count,
                status = CASE
                    WHEN counts.total_count > 0 AND counts.sent_count + counts.failed_count >= counts.total_count THEN 'completed'
                    WHEN b.status = 'queued' AND counts.sent_count > 0 THEN 'running'
                    ELSE b.status
                END,
                metrics_json = jsonb_build_object(
                    'total', counts.total_count,
                    'queued', counts.queued_count,
                    'sent', counts.sent_count,
                    'delivered', counts.delivered_count,
                    'read', counts.read_count,
                    'replied', counts.replied_count,
                    'failed', counts.failed_count
                ),
                updated_at = NOW()
            FROM (
                SELECT
                    r.broadcast_id,
                    COUNT(*)::int AS total_count,
                    COUNT(*) FILTER (WHERE status IN ('queued', 'processing'))::int AS queued_count,
                    COUNT(*) FILTER (WHERE status = 'sent')::int AS sent_count,
                    COUNT(*) FILTER (WHERE status = 'delivered')::int AS delivered_count,
                    COUNT(*) FILTER (WHERE status = 'read')::int AS read_count,
                    COUNT(*) FILTER (WHERE status = 'replied')::int AS replied_count,
                    COUNT(*) FILTER (WHERE status = 'failed')::int AS failed_count
                FROM saas_broadcast_recipients r
                WHERE r.broadcast_id IN (
                    SELECT broadcast_id
                    FROM saas_broadcast_recipients
                    WHERE outbound_id = CAST(:id AS uuid)
                )
                GROUP BY r.broadcast_id
            ) counts
            WHERE b.id = counts.broadcast_id
            """
        ),
        {"id": job_id},
    )


def _secret_from_env(config: dict[str, Any], integration: dict[str, Any]) -> str:
    inline_token = str(config.get("access_token") or config.get("token") or "").strip()
    if inline_token:
        return inline_token
    env_name = str(config.get("access_token_env") or "").strip()
    secret_ref = str(integration.get("secret_ref") or "").strip()
    if not env_name and secret_ref.lower().startswith("env:"):
        env_name = secret_ref.split(":", 1)[1].strip()
    if not env_name:
        env_name = "SCENTRA_META_ACCESS_TOKEN"
    return str(os.getenv(env_name) or "").strip()


def _meta_graph_version(config: dict[str, Any]) -> str:
    version = str(
        config.get("graph_api_version")
        or os.getenv("SCENTRA_META_GRAPH_VERSION")
        or "v22.0"
    ).strip()
    return version if version.startswith("v") else f"v{version}"


def _normalize_recipient(value: str) -> str:
    recipient = "".join(ch for ch in str(value or "") if ch.isdigit())
    if not recipient:
        raise DispatchPermanentError("recipient_external_id_required")
    return recipient


def _post_json(url: str, payload: dict[str, Any], access_token: str, timeout_sec: int) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return json.loads(raw or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw or "{}")
        except Exception:
            parsed = {"error": raw}
        message = json.dumps(parsed, ensure_ascii=True)[:500]
        if exc.code == 429 or exc.code >= 500:
            raise DispatchTransientError(f"meta_http_{exc.code}:{message}") from exc
        raise DispatchPermanentError(f"meta_http_{exc.code}:{message}") from exc
    except urllib.error.URLError as exc:
        raise DispatchTransientError(f"meta_network_error:{exc.reason}") from exc


def _send_meta_cloud_text(integration: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    config = _integration_config(integration)
    phone_number_id = str(config.get("phone_number_id") or "").strip()
    if not phone_number_id:
        raise DispatchPermanentError("meta_phone_number_id_required")

    access_token = _secret_from_env(config, integration)
    if not access_token:
        raise DispatchPermanentError("meta_access_token_env_missing")

    recipient = _normalize_recipient(str(job.get("recipient_external_id") or ""))
    body_text = str(job.get("body_text") or "").strip()
    if not body_text:
        raise DispatchPermanentError("message_body_required")

    base_url = str(config.get("graph_base_url") or "https://graph.facebook.com").rstrip("/")
    version = _meta_graph_version(config)
    timeout_sec = int(config.get("timeout_sec") or os.getenv("SCENTRA_META_TIMEOUT_SEC") or "15")
    url = f"{base_url}/{version}/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient,
        "type": "text",
        "text": {
            "preview_url": bool(config.get("preview_url", False)),
            "body": body_text,
        },
    }
    response = _post_json(url, payload, access_token, timeout_sec)
    messages = response.get("messages") if isinstance(response, dict) else None
    provider_message_id = ""
    if isinstance(messages, list) and messages:
        provider_message_id = str((messages[0] or {}).get("id") or "")
    return {
        "provider_message_id": provider_message_id,
        "provider_response": response,
    }


def _template_text_parameter(value: Any) -> dict[str, str]:
    return {"type": "text", "text": str(value or "")[:1024]}


def _template_parameters(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    params: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            ptype = str(item.get("type") or "text").strip().lower() or "text"
            if ptype == "text":
                params.append(_template_text_parameter(item.get("text") or item.get("value") or ""))
            elif ptype in {"image", "video", "document"}:
                media = item.get(ptype) if isinstance(item.get(ptype), dict) else {}
                if media:
                    params.append({"type": ptype, ptype: media})
            else:
                params.append(_template_text_parameter(item.get("text") or item.get("value") or ""))
        else:
            params.append(_template_text_parameter(item))
    return params


def _send_meta_cloud_template(integration: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    config = _integration_config(integration)
    payload_json = _job_payload(job)
    phone_number_id = str(config.get("phone_number_id") or "").strip()
    if not phone_number_id:
        raise DispatchPermanentError("meta_phone_number_id_required")

    access_token = _secret_from_env(config, integration)
    if not access_token:
        raise DispatchPermanentError("meta_access_token_missing")

    recipient = _normalize_recipient(str(job.get("recipient_external_id") or ""))
    template_name = str(payload_json.get("meta_template_name") or payload_json.get("template_name") or "").strip()
    if not template_name:
        raise DispatchPermanentError("meta_template_name_required")
    language = str(payload_json.get("meta_template_language") or payload_json.get("template_language") or "es").strip() or "es"

    components: list[dict[str, Any]] = []
    header_parameters = _template_parameters(payload_json.get("template_header_parameters"))
    body_parameters = _template_parameters(payload_json.get("template_body_parameters"))
    button_parameters = payload_json.get("template_button_parameters")
    if header_parameters:
        components.append({"type": "header", "parameters": header_parameters})
    if body_parameters:
        components.append({"type": "body", "parameters": body_parameters})
    if isinstance(button_parameters, list):
        for button in button_parameters:
            if isinstance(button, dict):
                components.append(button)

    base_url = str(config.get("graph_base_url") or "https://graph.facebook.com").rstrip("/")
    version = _meta_graph_version(config)
    timeout_sec = int(config.get("timeout_sec") or os.getenv("SCENTRA_META_TIMEOUT_SEC") or "15")
    url = f"{base_url}/{version}/{phone_number_id}/messages"
    template_payload: dict[str, Any] = {
        "name": template_name,
        "language": {"code": language},
    }
    if components:
        template_payload["components"] = components
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient,
        "type": "template",
        "template": template_payload,
    }
    response = _post_json(url, payload, access_token, timeout_sec)
    messages = response.get("messages") if isinstance(response, dict) else None
    provider_message_id = ""
    if isinstance(messages, list) and messages:
        provider_message_id = str((messages[0] or {}).get("id") or "")
    return {
        "provider_message_id": provider_message_id,
        "provider_response": response,
        "request_type": "template",
    }


def _dispatch_stub(conn, integration: dict[str, Any], job: dict[str, Any]) -> str:
    provider_message_id = f"stub:{integration['provider']}:{uuid4().hex}"
    payload_json = _job_payload(job)
    _mark_outbound(
        conn,
        str(job["id"]),
        status="sent",
        provider=str(integration["provider"]),
        provider_response={
            "id": provider_message_id,
            "mode": "stub",
            "message_type": payload_json.get("message_type") or "text",
            "template_name": payload_json.get("meta_template_name") or payload_json.get("template_name") or "",
        },
    )
    _mark_message_dispatch(conn, str(job.get("message_id") or ""), "sent", provider_message_id=provider_message_id)
    return "sent"


def _job_feature_key(job: dict[str, Any]) -> str:
    payload = _job_payload(job)
    source = str(payload.get("source") or "").strip().lower()
    if source == "saas_broadcast" or payload.get("broadcast_id"):
        return "broadcast"
    if source.startswith("trigger") or payload.get("trigger_id"):
        return "triggers"
    return "inbox"


def _block_dispatch(conn, job: dict[str, Any], error: str) -> str:
    _mark_outbound(conn, str(job["id"]), status="blocked", error=error)
    _mark_message_dispatch(conn, str(job.get("message_id") or ""), "blocked", error=error)
    return "blocked"


def _dispatch_one(conn, job: dict[str, Any]) -> str:
    tenant_id = str(job["tenant_id"])
    entitlements = tenant_entitlements(conn, tenant_id)
    if not entitlements.get("is_operational"):
        return _block_dispatch(conn, job, f"tenant_not_operational:{entitlements.get('tenant_status') or 'unknown'}")
    feature_key = _job_feature_key(job)
    if not bool(entitlements.get("features", {}).get(feature_key, False)):
        return _block_dispatch(conn, job, f"feature_not_enabled:{feature_key}")

    integration = _load_connected_integration(conn, str(job["tenant_id"]), str(job["channel"]))
    if not integration:
        error = "integration_not_connected"
        _mark_outbound(conn, str(job["id"]), status="blocked", error=error)
        _mark_message_dispatch(conn, str(job.get("message_id") or ""), "blocked", error=error)
        return "blocked"

    config = _integration_config(integration)
    mode = str(config.get("dispatch_mode") or "stub").strip().lower()
    if mode in {"meta_cloud", "whatsapp_cloud"}:
        try:
            payload_json = _job_payload(job)
            message_type = str(payload_json.get("message_type") or payload_json.get("type") or "").strip().lower()
            if message_type == "template" or payload_json.get("meta_template_name") or payload_json.get("template_name"):
                result = _send_meta_cloud_template(integration, job)
            else:
                result = _send_meta_cloud_text(integration, job)
        except DispatchPermanentError as exc:
            error = str(exc)
            _mark_outbound(conn, str(job["id"]), status="failed", provider=str(integration["provider"]), error=error)
            _mark_message_dispatch(conn, str(job.get("message_id") or ""), "failed", error=error)
            return "failed"
        provider_message_id = str(result.get("provider_message_id") or "")
        _mark_outbound(
            conn,
            str(job["id"]),
            status="sent",
            provider=str(integration["provider"]),
            provider_response={
                "provider_message_id": provider_message_id,
                **(result.get("provider_response") or {}),
            },
        )
        _mark_message_dispatch(conn, str(job.get("message_id") or ""), "sent", provider_message_id=provider_message_id)
    else:
        _dispatch_stub(conn, integration, job)

    conn.execute(
        text(
            """
            INSERT INTO saas_usage_counters (tenant_id, metric_code, period_yyyymm, metric_value)
            VALUES (CAST(:tenant_id AS uuid), 'outbound_messages_sent', :period, 1)
            ON CONFLICT (tenant_id, metric_code, period_yyyymm)
            DO UPDATE SET
                metric_value = saas_usage_counters.metric_value + 1,
                updated_at = NOW()
            """
        ),
        {"tenant_id": job["tenant_id"], "period": _period_yyyymm()},
    )
    return "sent"


def process_due_outbound_messages(limit: int = 25, tenant_id: str | None = None) -> dict[str, int]:
    filters = ["status IN ('queued', 'retry')", "next_attempt_at <= NOW()"]
    params: dict[str, Any] = {"limit": int(limit)}
    if tenant_id:
        filters.append("tenant_id = CAST(:tenant_id AS uuid)")
        params["tenant_id"] = tenant_id

    stats = {"picked": 0, "sent": 0, "blocked": 0, "failed": 0}
    with db_session() as conn:
        if tenant_id:
            set_tenant_context(conn, tenant_id)
        jobs = conn.execute(
            text(
                f"""
                SELECT
                    id::text,
                    tenant_id::text,
                    conversation_id::text,
                    message_id::text,
                    channel,
                    recipient_external_id,
                    body_text,
                    payload_json,
                    attempts,
                    max_attempts
                FROM saas_outbound_messages
                WHERE {" AND ".join(filters)}
                ORDER BY next_attempt_at ASC, created_at ASC
                LIMIT :limit
                FOR UPDATE SKIP LOCKED
                """
            ),
            params,
        ).mappings().all()
        stats["picked"] = len(jobs)

        for row in jobs:
            job = dict(row)
            conn.execute(
                text(
                    """
                    UPDATE saas_outbound_messages
                    SET attempts = attempts + 1,
                        locked_at = NOW(),
                        updated_at = NOW()
                    WHERE id = CAST(:id AS uuid)
                    """
                ),
                {"id": job["id"]},
            )
            try:
                status = _dispatch_one(conn, job)
                stats[status] = stats.get(status, 0) + 1
            except Exception as exc:
                attempts = int(job.get("attempts") or 0) + 1
                max_attempts = int(job.get("max_attempts") or 5)
                next_status = "failed" if attempts >= max_attempts else "retry"
                conn.execute(
                    text(
                        """
                        UPDATE saas_outbound_messages
                        SET status = :status,
                            error = :error,
                            locked_at = NULL,
                            next_attempt_at = NOW() + INTERVAL '5 minutes',
                            updated_at = NOW()
                        WHERE id = CAST(:id AS uuid)
                        """
                    ),
                    {
                        "id": job["id"],
                        "status": next_status,
                        "error": str(exc)[:500],
                    },
                )
                _mark_message_dispatch(conn, str(job.get("message_id") or ""), next_status, error=str(exc)[:500])
                stats["failed"] += 1
    return stats
