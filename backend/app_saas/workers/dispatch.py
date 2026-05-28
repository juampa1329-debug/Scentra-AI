from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from app_saas.billing.limits import tenant_entitlements
from app_saas.db import db_session, set_tenant_context
from app_saas.shared.secrets import decrypt_secret

try:
    import imageio_ffmpeg
except Exception:  # pragma: no cover - optional runtime fallback
    imageio_ffmpeg = None


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
    row = conn.execute(
        text(
            """
            UPDATE saas_messages
            SET payload_json = payload_json || CAST(:dispatch_payload AS jsonb)
            WHERE id = CAST(:message_id AS uuid)
            RETURNING tenant_id::text, conversation_id::text, id::text
            """
        ),
        {"message_id": message_id, "dispatch_payload": json.dumps(dispatch_payload)},
    ).mappings().first()
    if row:
        conn.execute(
            text(
                """
                INSERT INTO saas_message_status_events (
                    tenant_id,
                    conversation_id,
                    message_id,
                    provider_message_id,
                    status,
                    error,
                    payload_json
                )
                VALUES (
                    CAST(:tenant_id AS uuid),
                    CAST(:conversation_id AS uuid),
                    CAST(:message_id AS uuid),
                    :provider_message_id,
                    :status,
                    :error,
                    CAST(:payload_json AS jsonb)
                )
                """
            ),
            {
                "tenant_id": row["tenant_id"],
                "conversation_id": row["conversation_id"],
                "message_id": row["id"],
                "provider_message_id": provider_message_id,
                "status": status,
                "error": error[:500],
                "payload_json": json.dumps({"source": "dispatch_worker"}),
            },
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
    inline_token = decrypt_secret(str(config.get("access_token") or config.get("token") or "").strip())
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


def _normalize_social_recipient(value: str) -> str:
    recipient = str(value or "").strip()
    if not recipient:
        raise DispatchPermanentError("recipient_external_id_required")
    return recipient[:180]


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


def _post_multipart(
    url: str,
    *,
    fields: dict[str, Any],
    file_name: str,
    file_content_type: str,
    file_bytes: bytes,
    access_token: str,
    timeout_sec: int,
) -> dict[str, Any]:
    boundary = f"----scentra{uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        chunks.append(str(value).encode("utf-8"))
        chunks.append(b"\r\n")
    safe_name = (file_name or f"media-{uuid4().hex}").replace("\\", "_").replace('"', "_").replace("\r", "_").replace("\n", "_")[:240]
    chunks.append(f"--{boundary}\r\n".encode("utf-8"))
    chunks.append(
        (
            f'Content-Disposition: form-data; name="file"; filename="{safe_name}"\r\n'
            f"Content-Type: {file_content_type or 'application/octet-stream'}\r\n\r\n"
        ).encode("utf-8")
    )
    chunks.append(file_bytes)
    chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(chunks)
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
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
            raise DispatchTransientError(f"meta_upload_http_{exc.code}:{message}") from exc
        raise DispatchPermanentError(f"meta_upload_http_{exc.code}:{message}") from exc
    except urllib.error.URLError as exc:
        raise DispatchTransientError(f"meta_upload_network_error:{exc.reason}") from exc


def _load_local_media_asset(conn, tenant_id: str, media_id: str) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            SELECT id::text, kind, filename, content_type, byte_size, data
            FROM saas_media_assets
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id::text = :media_id
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "media_id": str(media_id or "").strip()},
    ).mappings().first()
    if not row:
        raise DispatchPermanentError("media_asset_not_found")
    return dict(row)


def _media_message_type(kind: str, content_type: str) -> str:
    clean_kind = str(kind or "").strip().lower()
    if clean_kind in {"image", "video", "audio", "document"}:
        return clean_kind
    mime = str(content_type or "").strip().lower()
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("audio/"):
        return "audio"
    return "document"


def _meta_upload_mime(content_type: str) -> str:
    return str(content_type or "application/octet-stream").split(";", 1)[0].strip().lower() or "application/octet-stream"


def _ffmpeg_executable() -> str:
    configured = str(os.getenv("FFMPEG_BINARY") or "").strip()
    if configured:
        return configured
    system_binary = shutil.which("ffmpeg")
    if system_binary:
        return system_binary
    if imageio_ffmpeg is not None:
        try:
            bundled = str(imageio_ffmpeg.get_ffmpeg_exe() or "").strip()
            if bundled:
                return bundled
        except Exception:
            return ""
    return ""


def _prepare_audio_asset_for_meta(asset: dict[str, Any]) -> dict[str, Any]:
    content_type = _meta_upload_mime(str(asset.get("content_type") or ""))
    if not content_type.startswith("audio/"):
        return asset
    if content_type in {"audio/ogg", "audio/mpeg", "audio/mp4", "audio/aac", "audio/amr"}:
        next_asset = dict(asset)
        next_asset["content_type"] = content_type
        return next_asset

    raw = bytes(asset.get("data") or b"")
    if not raw:
        raise DispatchPermanentError("audio_file_empty")

    suffix = ".webm" if "webm" in content_type else ".audio"
    ffmpeg_binary = _ffmpeg_executable()
    if not ffmpeg_binary:
        raise DispatchPermanentError("audio_transcode_unavailable_ffmpeg_required")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / f"input{suffix}"
            target = Path(tmp) / "voice-note.ogg"
            source.write_bytes(raw)
            subprocess.run(
                [
                    ffmpeg_binary,
                    "-y",
                    "-i",
                    str(source),
                    "-vn",
                    "-c:a",
                    "libopus",
                    "-b:a",
                    "32k",
                    "-vbr",
                    "on",
                    str(target),
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=45,
            )
            converted = target.read_bytes()
    except FileNotFoundError as exc:
        raise DispatchPermanentError("audio_transcode_unavailable_ffmpeg_required") from exc
    except subprocess.TimeoutExpired as exc:
        raise DispatchTransientError("audio_transcode_timeout") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or b"").decode("utf-8", errors="replace")[-300:]
        raise DispatchPermanentError(f"audio_transcode_failed:{stderr}") from exc

    next_asset = dict(asset)
    original_name = str(asset.get("filename") or "nota-voz").rsplit(".", 1)[0]
    next_asset["filename"] = f"{original_name}.ogg"
    next_asset["content_type"] = "audio/ogg"
    next_asset["data"] = converted
    next_asset["byte_size"] = len(converted)
    return next_asset


def _prepare_asset_for_meta(asset: dict[str, Any], message_type: str) -> dict[str, Any]:
    if message_type == "audio":
        return _prepare_audio_asset_for_meta(asset)
    next_asset = dict(asset)
    next_asset["content_type"] = _meta_upload_mime(str(asset.get("content_type") or "application/octet-stream"))
    return next_asset


def _upload_meta_media(config: dict[str, Any], access_token: str, asset: dict[str, Any]) -> dict[str, Any]:
    phone_number_id = str(config.get("phone_number_id") or "").strip()
    if not phone_number_id:
        raise DispatchPermanentError("meta_phone_number_id_required")
    base_url = str(config.get("graph_base_url") or "https://graph.facebook.com").rstrip("/")
    version = _meta_graph_version(config)
    timeout_sec = int(config.get("timeout_sec") or os.getenv("SCENTRA_META_TIMEOUT_SEC") or "30")
    content_type = _meta_upload_mime(str(asset.get("content_type") or "application/octet-stream").strip())
    url = f"{base_url}/{version}/{phone_number_id}/media"
    response = _post_multipart(
        url,
        fields={"messaging_product": "whatsapp", "type": content_type},
        file_name=str(asset.get("filename") or ""),
        file_content_type=content_type,
        file_bytes=bytes(asset.get("data") or b""),
        access_token=access_token,
        timeout_sec=timeout_sec,
    )
    provider_media_id = str(response.get("id") or "")
    if not provider_media_id:
        raise DispatchPermanentError("meta_media_upload_missing_id")
    return {"provider_media_id": provider_media_id, "upload_response": response}


def _send_meta_cloud_media(conn, integration: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    config = _integration_config(integration)
    phone_number_id = str(config.get("phone_number_id") or "").strip()
    if not phone_number_id:
        raise DispatchPermanentError("meta_phone_number_id_required")

    access_token = _secret_from_env(config, integration)
    if not access_token:
        raise DispatchPermanentError("meta_access_token_missing")

    payload_json = _job_payload(job)
    local_media_id = str(payload_json.get("media_id") or "").strip()
    provider_media_id = str(payload_json.get("provider_media_id") or "").strip()
    if not local_media_id and not provider_media_id:
        raise DispatchPermanentError("media_id_required")

    asset: dict[str, Any] | None = None
    if local_media_id:
        asset = _load_local_media_asset(conn, str(job["tenant_id"]), local_media_id)
    recipient = _normalize_recipient(str(job.get("recipient_external_id") or ""))
    body_text = str(job.get("body_text") or "").strip()
    content_type = str((asset or {}).get("content_type") or payload_json.get("mime_type") or "").strip()
    message_type = str(payload_json.get("message_type") or payload_json.get("type") or "").strip().lower()
    if message_type == "file":
        message_type = "document"
    if message_type not in {"image", "video", "audio", "document"}:
        message_type = _media_message_type(str((asset or {}).get("kind") or ""), content_type)
    if asset:
        asset = _prepare_asset_for_meta(asset, message_type)
        content_type = str(asset.get("content_type") or content_type)
    if not provider_media_id:
        upload = _upload_meta_media(config, access_token, asset or {})
        provider_media_id = upload["provider_media_id"]
    else:
        upload = {"provider_media_id": provider_media_id, "upload_response": {}}

    media_payload: dict[str, Any] = {"id": provider_media_id}
    if message_type in {"image", "video", "document"} and body_text:
        media_payload["caption"] = body_text[:1024]
    filename = str(payload_json.get("filename") or (asset or {}).get("filename") or "").strip()
    if message_type == "document" and filename:
        media_payload["filename"] = filename[:240]

    base_url = str(config.get("graph_base_url") or "https://graph.facebook.com").rstrip("/")
    version = _meta_graph_version(config)
    timeout_sec = int(config.get("timeout_sec") or os.getenv("SCENTRA_META_TIMEOUT_SEC") or "15")
    url = f"{base_url}/{version}/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient,
        "type": message_type,
        message_type: media_payload,
    }
    response = _post_json(url, payload, access_token, timeout_sec)
    messages = response.get("messages") if isinstance(response, dict) else None
    provider_message_id = ""
    if isinstance(messages, list) and messages:
        provider_message_id = str((messages[0] or {}).get("id") or "")
    return {
        "provider_message_id": provider_message_id,
        "provider_response": response,
        "request_type": message_type,
        "provider_media_id": provider_media_id,
        "upload_response": upload.get("upload_response") or {},
    }


def _send_meta_cloud_text(integration: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    config = _integration_config(integration)
    phone_number_id = str(config.get("phone_number_id") or "").strip()
    if not phone_number_id:
        raise DispatchPermanentError("meta_phone_number_id_required")

    access_token = _secret_from_env(config, integration)
    if not access_token:
        raise DispatchPermanentError("meta_access_token_missing")

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


def _send_instagram_graph_text(integration: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    config = _integration_config(integration)
    page_access_token = decrypt_secret(str(config.get("page_access_token") or "").strip())
    if not page_access_token:
        raise DispatchPermanentError("instagram_page_access_token_missing")
    recipient = _normalize_social_recipient(str(job.get("recipient_external_id") or ""))
    body_text = str(job.get("body_text") or "").strip()
    if not body_text:
        raise DispatchPermanentError("message_body_required")
    base_url = str(config.get("graph_base_url") or "https://graph.facebook.com").rstrip("/")
    version = _meta_graph_version(config)
    timeout_sec = int(config.get("timeout_sec") or os.getenv("SCENTRA_META_TIMEOUT_SEC") or "15")
    page_id = str(config.get("page_id") or config.get("facebook_page_id") or "").strip()
    node_id = urllib.parse.quote(page_id or "me", safe="")
    url = f"{base_url}/{version}/{node_id}/messages"
    payload = {
        "recipient": {"id": recipient},
        "message": {"text": body_text[:1000]},
        "messaging_type": "RESPONSE",
    }
    response = _post_json(url, payload, page_access_token, timeout_sec)
    provider_message_id = str(response.get("message_id") or response.get("id") or "")
    return {
        "provider_message_id": provider_message_id,
        "provider_response": response,
        "request_type": "instagram_text",
    }


def _send_facebook_graph_text(integration: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    config = _integration_config(integration)
    page_access_token = decrypt_secret(str(config.get("page_access_token") or config.get("facebook_page_access_token") or "").strip())
    if not page_access_token:
        raise DispatchPermanentError("facebook_page_access_token_missing")
    recipient = _normalize_social_recipient(str(job.get("recipient_external_id") or ""))
    body_text = str(job.get("body_text") or "").strip()
    if not body_text:
        raise DispatchPermanentError("message_body_required")
    base_url = str(config.get("graph_base_url") or "https://graph.facebook.com").rstrip("/")
    version = _meta_graph_version(config)
    timeout_sec = int(config.get("timeout_sec") or os.getenv("SCENTRA_META_TIMEOUT_SEC") or "15")
    page_id = str(config.get("page_id") or config.get("facebook_page_id") or "").strip()
    node_id = urllib.parse.quote(page_id or "me", safe="")
    url = f"{base_url}/{version}/{node_id}/messages"
    payload = {
        "recipient": {"id": recipient},
        "message": {"text": body_text[:2000]},
        "messaging_type": "RESPONSE",
    }
    response = _post_json(url, payload, page_access_token, timeout_sec)
    provider_message_id = str(response.get("message_id") or response.get("id") or "")
    return {
        "provider_message_id": provider_message_id,
        "provider_response": response,
        "request_type": "facebook_text",
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


def _meta_template_send_allowed(conn, job: dict[str, Any], payload: dict[str, Any]) -> tuple[bool, str]:
    message_type = str(payload.get("message_type") or payload.get("type") or "").strip().lower()
    if message_type != "template" and not (payload.get("meta_template_name") or payload.get("template_name")):
        return True, ""
    template_id = str(payload.get("meta_template_id") or "").strip()
    broadcast_id = str(payload.get("broadcast_id") or "").strip()
    row = None
    if template_id:
        row = conn.execute(
            text(
                """
                SELECT status
                FROM saas_meta_message_templates
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND id = CAST(:template_id AS uuid)
                LIMIT 1
                """
            ),
            {"tenant_id": job["tenant_id"], "template_id": template_id},
        ).mappings().first()
    elif broadcast_id:
        row = conn.execute(
            text(
                """
                SELECT COALESCE(mt.status, '') AS status
                FROM saas_broadcasts b
                LEFT JOIN saas_meta_message_templates mt ON mt.id = b.meta_template_id
                WHERE b.tenant_id = CAST(:tenant_id AS uuid)
                  AND b.id = CAST(:broadcast_id AS uuid)
                LIMIT 1
                """
            ),
            {"tenant_id": job["tenant_id"], "broadcast_id": broadcast_id},
        ).mappings().first()
    if row and str(row.get("status") or "").strip().lower() != "approved":
        return False, "meta_template_must_be_approved_before_dispatch"
    return True, ""


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
    job_channel = str(job["channel"]).strip().lower()
    if job_channel in {"instagram", "facebook"} and mode in {"instagram_graph", "facebook_graph", "messenger_graph", "meta_cloud", "instagram", "facebook"}:
        try:
            payload_json = _job_payload(job)
            message_type = str(payload_json.get("message_type") or payload_json.get("type") or "text").strip().lower()
            if message_type not in {"text", ""}:
                raise DispatchPermanentError(f"{job_channel}_outbound_only_text_enabled")
            result = _send_instagram_graph_text(integration, job) if job_channel == "instagram" else _send_facebook_graph_text(integration, job)
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
                "request_type": result.get("request_type") or f"{job_channel}_text",
                **(result.get("provider_response") or {}),
            },
        )
        _mark_message_dispatch(conn, str(job.get("message_id") or ""), "sent", provider_message_id=provider_message_id)
    elif mode in {"meta_cloud", "whatsapp_cloud"}:
        try:
            payload_json = _job_payload(job)
            message_type = str(payload_json.get("message_type") or payload_json.get("type") or "").strip().lower()
            if message_type in {"image", "video", "audio", "document", "file"} or payload_json.get("media_id"):
                result = _send_meta_cloud_media(conn, integration, job)
            elif message_type == "template" or payload_json.get("meta_template_name") or payload_json.get("template_name"):
                allowed, reason = _meta_template_send_allowed(conn, job, payload_json)
                if not allowed:
                    return _block_dispatch(conn, job, reason)
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
                "request_type": result.get("request_type") or "text",
                "provider_media_id": result.get("provider_media_id") or "",
                "upload_response": result.get("upload_response") or {},
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


def process_due_outbound_messages(limit: int = 25, tenant_id: str | None = None) -> dict[str, Any]:
    filters = ["status IN ('queued', 'retry')", "next_attempt_at <= NOW()"]
    params: dict[str, Any] = {"limit": int(limit)}
    if tenant_id:
        filters.append("tenant_id = CAST(:tenant_id AS uuid)")
        params["tenant_id"] = tenant_id

    stats: dict[str, Any] = {"picked": 0, "sent": 0, "blocked": 0, "failed": 0, "errors": []}
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
                if status in {"blocked", "failed"}:
                    row_error = conn.execute(
                        text("SELECT error FROM saas_outbound_messages WHERE id = CAST(:id AS uuid)"),
                        {"id": job["id"]},
                    ).scalar() or ""
                    if row_error:
                        stats["last_error"] = str(row_error)
                        stats["errors"].append({"id": job["id"], "status": status, "error": str(row_error)})
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
                stats["last_error"] = str(exc)[:500]
                stats["errors"].append({"id": job["id"], "status": next_status, "error": str(exc)[:500]})
    return stats
