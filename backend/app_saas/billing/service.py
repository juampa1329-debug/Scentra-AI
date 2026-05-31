from __future__ import annotations

import json
import hashlib
import hmac
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app_saas.config import settings
from app_saas.billing.provider_settings import (
    billing_default_provider,
    billing_provider_runtime_settings,
    ensure_billing_provider_ready,
)
from app_saas.intelligence.capture import record_inline_event
from app_saas.shared.email import send_plain_email


def _clean(value: Any, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _clean_uuid(value: Any) -> str:
    try:
        return str(UUID(str(value or "").strip()))
    except (TypeError, ValueError, AttributeError):
        return ""


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_signature_header(value: str) -> dict[str, str]:
    parts: dict[str, str] = {}
    for item in str(value or "").split(","):
        if "=" not in item:
            continue
        key, raw = item.split("=", 1)
        parts[key.strip().lower()] = raw.strip()
    return parts


def _safe_compare_digest(left: str, right: str) -> bool:
    return bool(left and right and hmac.compare_digest(str(left), str(right)))


def _owner_email(conn: Connection, tenant_id: str) -> str:
    return _clean(_tenant_owner(conn, tenant_id).get("email"), 240)


def _send_billing_notice(conn: Connection, *, tenant_id: str, subject: str, body: str) -> bool:
    email = _owner_email(conn, tenant_id)
    if not email:
        return False
    try:
        return send_plain_email(to_email=email, subject=subject, body=body)
    except Exception:
        return False


def _plan(conn: Connection, plan_code: str) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            SELECT plan_code, display_name, price_monthly_cents, currency, is_public, is_active
            FROM saas_plan_limits
            WHERE plan_code = :plan_code
            LIMIT 1
            """
        ),
        {"plan_code": _clean(plan_code, 40).lower()},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="plan_not_found")
    return dict(row)


def _tenant_owner(conn: Connection, tenant_id: str) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            SELECT u.id::text AS user_id, u.email, u.full_name
            FROM saas_memberships m
            JOIN saas_users u ON u.id = m.user_id
            WHERE m.tenant_id = CAST(:tenant_id AS uuid)
              AND m.is_active = TRUE
              AND m.role = 'owner'
            ORDER BY m.created_at ASC
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()
    return dict(row or {})


def _app_success_url(session_id: str = "") -> str:
    url = settings.billing_success_url or f"{settings.scentra_app_public_url}/?billing=success"
    return url.replace("{CHECKOUT_SESSION_ID}", session_id or "{CHECKOUT_SESSION_ID}")


def _stripe_request(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    key = settings.stripe_secret_key.strip()
    if not key:
        raise HTTPException(status_code=501, detail="stripe_secret_key_missing")
    body = urllib.parse.urlencode(payload, doseq=True).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.stripe.com{path}",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=502, detail=f"stripe_error:{detail[:700]}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"stripe_unavailable:{str(exc)[:300]}") from exc


def _mercadopago_request(conn: Connection, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    provider_config = billing_provider_runtime_settings(conn, "mercadopago")
    ensure_billing_provider_ready(provider_config, action="checkout")
    token = str(provider_config.get("access_token") or "").strip()
    if not token:
        raise HTTPException(status_code=501, detail="mercadopago_access_token_missing")
    request = urllib.request.Request(
        f"https://api.mercadopago.com{path}",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=502, detail=f"mercadopago_error:{detail[:700]}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"mercadopago_unavailable:{str(exc)[:300]}") from exc


def _mercadopago_get(conn: Connection, path: str) -> dict[str, Any]:
    provider_config = billing_provider_runtime_settings(conn, "mercadopago")
    ensure_billing_provider_ready(provider_config, action="checkout")
    token = str(provider_config.get("access_token") or "").strip()
    if not token:
        raise HTTPException(status_code=501, detail="mercadopago_access_token_missing")
    request = urllib.request.Request(
        f"https://api.mercadopago.com{path}",
        method="GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=502, detail=f"mercadopago_error:{detail[:700]}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"mercadopago_unavailable:{str(exc)[:300]}") from exc


def _wompi_checkout_base(provider_config: dict[str, Any] | None = None) -> str:
    return "https://checkout.wompi.co/p/"


def _wompi_transaction_base(provider_config: dict[str, Any] | None = None) -> str:
    env = str((provider_config or {}).get("environment") or settings.wompi_environment).strip().lower()
    if env in {"sandbox", "test", "testing", "dev"}:
        return "https://sandbox.wompi.co"
    return "https://production.wompi.co"


def _wompi_integrity_signature(reference: str, amount_cents: int, currency: str, provider_config: dict[str, Any]) -> str:
    secret = str(provider_config.get("integrity_key") or "").strip()
    if not secret:
        raise HTTPException(status_code=501, detail="wompi_integrity_key_missing")
    raw = f"{reference}{int(amount_cents)}{currency.upper()}{secret}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _wompi_event_value(data: dict[str, Any], dotted_path: str) -> str:
    cursor: Any = data
    for part in str(dotted_path or "").split("."):
        if not isinstance(cursor, dict):
            return ""
        cursor = cursor.get(part)
    return "" if cursor is None else str(cursor)


def verify_wompi_event(conn: Connection, payload: dict[str, Any], header_checksum: str = "") -> bool:
    provider_config = billing_provider_runtime_settings(conn, "wompi")
    secret = str(provider_config.get("event_key") or "").strip()
    if not secret:
        return settings.is_local
    signature = payload.get("signature") if isinstance(payload.get("signature"), dict) else {}
    properties = signature.get("properties") if isinstance(signature.get("properties"), list) else []
    expected = str(header_checksum or signature.get("checksum") or "").strip().lower()
    if not expected or not properties:
        return False
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    raw = "".join(_wompi_event_value(data, item) for item in properties)
    raw = f"{raw}{payload.get('timestamp', '')}{secret}"
    calculated = hashlib.sha256(raw.encode("utf-8")).hexdigest().lower()
    return calculated == expected


def verify_stripe_event(raw_body: bytes, signature_header: str) -> bool:
    secret = settings.stripe_webhook_secret.strip()
    if not secret:
        return settings.is_local
    parts = _parse_signature_header(signature_header)
    timestamp = parts.get("t", "")
    received = parts.get("v1", "")
    if not timestamp or not received:
        return False
    try:
        payload = raw_body.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return False
    signed_payload = f"{timestamp}.{payload}".encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return _safe_compare_digest(expected, received)


def verify_mercadopago_event(conn: Connection, *, data_id: str, x_request_id: str, x_signature: str) -> bool:
    provider_config = billing_provider_runtime_settings(conn, "mercadopago")
    secret = str(provider_config.get("webhook_secret") or "").strip()
    if not secret:
        return settings.is_local
    parts = _parse_signature_header(x_signature)
    timestamp = parts.get("ts", "")
    received = parts.get("v1", "")
    clean_data_id = _clean(data_id, 220)
    if any(ch.isalpha() for ch in clean_data_id):
        clean_data_id = clean_data_id.lower()
    if not clean_data_id or not x_request_id or not timestamp or not received:
        return False
    manifest = f"id:{clean_data_id};request-id:{x_request_id};ts:{timestamp};"
    expected = hmac.new(secret.encode("utf-8"), manifest.encode("utf-8"), hashlib.sha256).hexdigest()
    return _safe_compare_digest(expected, received)


def _wompi_checkout_url(*, reference: str, amount_cents: int, currency: str, redirect_url: str, owner: dict[str, Any], provider_config: dict[str, Any]) -> str:
    ensure_billing_provider_ready(provider_config, action="checkout")
    public_key = str(provider_config.get("public_key") or "").strip()
    if not public_key:
        raise HTTPException(status_code=501, detail="wompi_public_key_missing")
    clean_currency = currency.upper()
    if clean_currency != "COP":
        raise HTTPException(status_code=400, detail="wompi_only_supports_cop")
    query: dict[str, str] = {
        "public-key": public_key,
        "currency": clean_currency,
        "amount-in-cents": str(int(amount_cents)),
        "reference": reference,
        "signature:integrity": _wompi_integrity_signature(reference, amount_cents, clean_currency, provider_config),
        "redirect-url": redirect_url,
    }
    if owner.get("email"):
        query["customer-data:email"] = str(owner["email"])
    if owner.get("full_name"):
        query["customer-data:full-name"] = str(owner["full_name"])
    return f"{_wompi_checkout_base(provider_config)}?{urllib.parse.urlencode(query)}"


def fetch_wompi_transaction(conn: Connection, transaction_id: str) -> dict[str, Any]:
    clean_id = _clean(transaction_id, 220)
    if not clean_id:
        raise HTTPException(status_code=400, detail="wompi_transaction_id_required")
    provider_config = billing_provider_runtime_settings(conn, "wompi")
    private_key = str(provider_config.get("private_key") or "").strip()
    headers = {"Content-Type": "application/json"}
    if private_key:
        headers["Authorization"] = f"Bearer {private_key}"
    request = urllib.request.Request(
        f"{_wompi_transaction_base(provider_config)}/v1/transactions/{urllib.parse.quote(clean_id)}",
        method="GET",
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=502, detail=f"wompi_error:{detail[:700]}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"wompi_unavailable:{str(exc)[:300]}") from exc


def create_checkout_session(
    conn: Connection,
    *,
    tenant_id: str,
    user_id: str,
    plan_code: str,
    provider: str = "auto",
    success_url: str = "",
    cancel_url: str = "",
) -> dict[str, Any]:
    selected_provider = _clean(provider, 40).lower()
    if selected_provider in {"", "auto"}:
        selected_provider = billing_default_provider(conn)
    if selected_provider not in {"manual", "stripe", "mercadopago", "wompi"}:
        raise HTTPException(status_code=400, detail="unsupported_billing_provider")

    plan = _plan(conn, plan_code)
    if not plan.get("is_active") or not plan.get("is_public"):
        raise HTTPException(status_code=404, detail="plan_not_available")

    owner = _tenant_owner(conn, tenant_id)
    amount_cents = int(plan.get("price_monthly_cents") or 0)
    currency = _clean(plan.get("currency") or "USD", 12).upper()
    session_uuid = str(uuid4())
    provider_checkout_id = ""
    checkout_url = ""
    provider_customer_id = ""
    status = "pending"
    error = ""
    success = success_url or _app_success_url()
    cancel = cancel_url or settings.billing_cancel_url or f"{settings.scentra_app_public_url}/?billing=cancelled"
    metadata = {
        "tenant_id": tenant_id,
        "plan_code": plan["plan_code"],
        "owner_email": owner.get("email", ""),
        "created_at": _now_iso(),
    }

    if selected_provider == "stripe":
        response = _stripe_request(
            "/v1/checkout/sessions",
            {
                "mode": "subscription",
                "client_reference_id": tenant_id,
                "customer_email": owner.get("email", ""),
                "success_url": success,
                "cancel_url": cancel,
                "line_items[0][quantity]": 1,
                "line_items[0][price_data][currency]": currency.lower(),
                "line_items[0][price_data][unit_amount]": amount_cents,
                "line_items[0][price_data][recurring][interval]": "month",
                "line_items[0][price_data][product_data][name]": plan.get("display_name") or plan["plan_code"],
                "metadata[tenant_id]": tenant_id,
                "metadata[plan_code]": plan["plan_code"],
            },
        )
        provider_checkout_id = _clean(response.get("id"), 220)
        provider_customer_id = _clean(response.get("customer"), 220)
        checkout_url = _clean(response.get("url"), 1500)
        metadata["provider_response"] = response
    elif selected_provider == "mercadopago":
        external_reference = f"{tenant_id}:{plan['plan_code']}"
        metadata["external_reference"] = external_reference
        provider_config = billing_provider_runtime_settings(conn, "mercadopago")
        response = _mercadopago_request(
            conn,
            "/checkout/preferences",
            {
                "items": [
                    {
                        "title": plan.get("display_name") or plan["plan_code"],
                        "quantity": 1,
                        "currency_id": currency,
                        "unit_price": round(amount_cents / 100, 2),
                    }
                ],
                "external_reference": external_reference,
                "payer": {"email": owner.get("email", "")},
                "back_urls": {"success": success, "failure": cancel, "pending": cancel},
                "metadata": metadata,
            },
        )
        provider_checkout_id = _clean(response.get("id"), 220)
        checkout_url = _clean(
            (response.get("sandbox_init_point") if provider_config.get("test_mode") else response.get("init_point"))
            or response.get("init_point")
            or response.get("sandbox_init_point"),
            1500,
        )
        metadata["provider_response"] = response
    elif selected_provider == "wompi":
        if currency != "COP":
            raise HTTPException(status_code=400, detail="wompi_requires_cop_plan_currency")
        provider_config = billing_provider_runtime_settings(conn, "wompi")
        reference = f"scentra-{tenant_id[:8]}-{session_uuid[:8]}".replace("-", "").upper()[:64]
        checkout_url = _clean(
            _wompi_checkout_url(
                reference=reference,
                amount_cents=amount_cents,
                currency=currency,
                redirect_url=success,
                owner=owner,
                provider_config=provider_config,
            ),
            1500,
        )
        provider_checkout_id = reference
        metadata["wompi"] = {
            "environment": provider_config.get("environment") or settings.wompi_environment,
            "reference": reference,
            "checkout_type": "web_checkout",
        }
    else:
        status = "manual_pending"
        error = "provider_not_configured_manual_checkout"

    row = conn.execute(
        text(
            """
            INSERT INTO saas_billing_checkout_sessions (
                id, tenant_id, provider, provider_checkout_id, provider_customer_id,
                plan_code, status, currency, amount_cents, checkout_url, success_url,
                cancel_url, error, metadata_json, created_by_user_id, updated_at
            )
            VALUES (
                CAST(:id AS uuid), CAST(:tenant_id AS uuid), :provider, :provider_checkout_id,
                :provider_customer_id, :plan_code, :status, :currency, :amount_cents,
                :checkout_url, :success_url, :cancel_url, :error, CAST(:metadata_json AS jsonb),
                CAST(:user_id AS uuid), NOW()
            )
            RETURNING id::text, tenant_id::text, provider, provider_checkout_id, provider_customer_id,
                      plan_code, status, currency, amount_cents, checkout_url, success_url,
                      cancel_url, error, metadata_json, expires_at::text, completed_at::text,
                      created_at::text, updated_at::text
            """
        ),
        {
            "id": session_uuid,
            "tenant_id": tenant_id,
            "provider": selected_provider,
            "provider_checkout_id": provider_checkout_id,
            "provider_customer_id": provider_customer_id,
            "plan_code": plan["plan_code"],
            "status": status,
            "currency": currency,
            "amount_cents": amount_cents,
            "checkout_url": checkout_url,
            "success_url": success,
            "cancel_url": cancel,
            "error": error,
            "metadata_json": _json(metadata),
            "user_id": user_id,
        },
    ).mappings().first()
    return dict(row or {})


def list_checkout_sessions(conn: Connection, tenant_id: str, limit: int = 100) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT id::text, tenant_id::text, provider, provider_checkout_id,
                   provider_customer_id, plan_code, status, currency, amount_cents,
                   checkout_url, success_url, cancel_url, error, metadata_json,
                   expires_at::text, completed_at::text, created_at::text, updated_at::text
            FROM saas_billing_checkout_sessions
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "limit": int(max(1, min(limit, 250)))},
    ).mappings().all()
    return [dict(row) for row in rows]


def list_invoices(conn: Connection, tenant_id: str, limit: int = 100) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT id::text, tenant_id::text, provider, provider_invoice_id, invoice_number,
                   status, plan_code, currency, subtotal_cents, discount_cents, tax_cents,
                   total_cents, amount_paid_cents, amount_due_cents, hosted_invoice_url,
                   pdf_url, period_start::text, period_end::text, due_at::text, paid_at::text,
                   metadata_json, created_at::text, updated_at::text
            FROM saas_billing_invoices
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "limit": int(max(1, min(limit, 250)))},
    ).mappings().all()
    return [dict(row) for row in rows]


def get_invoice(conn: Connection, tenant_id: str, invoice_id: str) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            SELECT i.id::text, i.tenant_id::text, t.name AS tenant_name, t.slug AS tenant_slug,
                   i.provider, i.provider_invoice_id, i.invoice_number, i.status,
                   i.plan_code, i.currency, i.subtotal_cents, i.discount_cents, i.tax_cents,
                   i.total_cents, i.amount_paid_cents, i.amount_due_cents, i.hosted_invoice_url,
                   i.pdf_url, i.period_start::text, i.period_end::text, i.due_at::text,
                   i.paid_at::text, i.metadata_json, i.created_at::text, i.updated_at::text
            FROM saas_billing_invoices i
            JOIN saas_tenants t ON t.id = i.tenant_id
            WHERE i.id = CAST(:invoice_id AS uuid)
              AND (:tenant_id = '' OR i.tenant_id = CAST(NULLIF(:tenant_id, '') AS uuid))
            LIMIT 1
            """
        ),
        {"tenant_id": _clean(tenant_id, 80), "invoice_id": invoice_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="invoice_not_found")
    return dict(row)


def _pdf_escape(value: Any) -> str:
    text_value = str(value or "")
    text_value = text_value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return text_value.encode("latin-1", errors="replace").decode("latin-1")


def invoice_pdf_bytes(invoice: dict[str, Any]) -> bytes:
    amount = (int(invoice.get("total_cents") or 0) / 100)
    due = (int(invoice.get("amount_due_cents") or 0) / 100)
    paid = (int(invoice.get("amount_paid_cents") or 0) / 100)
    lines = [
        "Scentra +AI",
        "Factura / comprobante interno",
        f"Numero: {invoice.get('invoice_number') or invoice.get('id')}",
        f"Empresa: {invoice.get('tenant_name') or invoice.get('tenant_id')}",
        f"Plan: {invoice.get('plan_code')}",
        f"Estado: {invoice.get('status')}",
        f"Proveedor: {invoice.get('provider')}",
        f"Periodo: {invoice.get('period_start') or '-'} a {invoice.get('period_end') or '-'}",
        f"Vence: {invoice.get('due_at') or '-'}",
        f"Moneda: {invoice.get('currency') or 'USD'}",
        f"Total: {amount:.2f}",
        f"Pagado: {paid:.2f}",
        f"Saldo: {due:.2f}",
        "",
        "Documento generado por Scentra +AI para seguimiento operativo.",
    ]
    stream_lines = ["BT", "/F1 12 Tf", "50 790 Td"]
    first = True
    for line in lines:
        if not first:
            stream_lines.append("0 -22 Td")
        first = False
        stream_lines.append(f"({_pdf_escape(line)}) Tj")
    stream_lines.append("ET")
    stream = "\n".join(stream_lines).encode("latin-1", errors="replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    content = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for idx, obj in enumerate(objects, start=1):
        offsets.append(len(content))
        content.extend(f"{idx} 0 obj\n".encode("ascii"))
        content.extend(obj)
        content.extend(b"\nendobj\n")
    xref_at = len(content)
    content.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    content.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        content.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    content.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode("ascii")
    )
    return bytes(content)


def list_credits(conn: Connection, tenant_id: str, limit: int = 100) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT id::text, tenant_id::text, metric_code, amount, remaining_amount,
                   reason, expires_at::text, created_by_user_id::text, created_at::text, updated_at::text
            FROM saas_billing_credits
            WHERE tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "limit": int(max(1, min(limit, 250)))},
    ).mappings().all()
    return [dict(row) for row in rows]


def apply_manual_credit(
    conn: Connection,
    *,
    tenant_id: str,
    actor_user_id: str,
    metric_code: str,
    amount: int,
    reason: str = "",
    expires_at: str = "",
) -> dict[str, Any]:
    clean_metric = _clean(metric_code, 80).lower().replace("-", "_") or "monthly_messages"
    clean_amount = int(amount or 0)
    if clean_amount <= 0:
        raise HTTPException(status_code=400, detail="credit_amount_required")
    row = conn.execute(
        text(
            """
            INSERT INTO saas_billing_credits (
                tenant_id, metric_code, amount, remaining_amount, reason, expires_at, created_by_user_id
            )
            VALUES (
                CAST(:tenant_id AS uuid), :metric_code, :amount, :amount, :reason,
                CAST(NULLIF(:expires_at, '') AS timestamp), CAST(:actor_user_id AS uuid)
            )
            RETURNING id::text, tenant_id::text, metric_code, amount, remaining_amount,
                      reason, expires_at::text, created_by_user_id::text, created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "metric_code": clean_metric,
            "amount": clean_amount,
            "reason": _clean(reason, 700),
            "expires_at": _clean(expires_at, 80),
            "actor_user_id": actor_user_id,
        },
    ).mappings().first()
    return dict(row or {})


def create_manual_invoice(
    conn: Connection,
    *,
    tenant_id: str,
    plan_code: str,
    status: str = "open",
    total_cents: int | None = None,
    due_at: str = "",
) -> dict[str, Any]:
    plan = _plan(conn, plan_code)
    amount = int(total_cents if total_cents is not None else plan.get("price_monthly_cents") or 0)
    invoice_number = f"SC-{datetime.now(timezone.utc).strftime('%Y%m')}-{str(uuid4())[:8].upper()}"
    row = conn.execute(
        text(
            """
            INSERT INTO saas_billing_invoices (
                tenant_id, provider, invoice_number, status, plan_code, currency,
                subtotal_cents, total_cents, amount_due_cents, period_start, period_end, due_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), 'manual', :invoice_number, :status, :plan_code, :currency,
                :amount, :amount, CASE WHEN :status = 'paid' THEN 0 ELSE :amount END,
                date_trunc('month', NOW()), date_trunc('month', NOW()) + INTERVAL '1 month',
                CAST(NULLIF(:due_at, '') AS timestamp)
            )
            RETURNING id::text, tenant_id::text, provider, provider_invoice_id, invoice_number,
                      status, plan_code, currency, subtotal_cents, discount_cents, tax_cents,
                      total_cents, amount_paid_cents, amount_due_cents, hosted_invoice_url,
                      pdf_url, period_start::text, period_end::text, due_at::text, paid_at::text,
                      metadata_json, created_at::text, updated_at::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "invoice_number": invoice_number,
            "status": _clean(status, 40).lower() or "open",
            "plan_code": plan["plan_code"],
            "currency": _clean(plan.get("currency") or "USD", 12).upper(),
            "amount": max(0, amount),
            "due_at": _clean(due_at, 80),
        },
    ).mappings().first()
    return dict(row or {})


def _invoice_pdf_path(invoice_id: str) -> str:
    base = str(settings.scentra_api_public_url or "").strip().rstrip("/")
    return f"{base}/saas/v1/billing/invoices/{invoice_id}/pdf" if base else ""


def _ensure_period_invoice(
    conn: Connection,
    *,
    tenant_id: str,
    subscription_id: str,
    plan_code: str,
    provider: str,
    status: str,
    period_start: str | None = None,
    period_end: str | None = None,
    due_at: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    plan = _plan(conn, plan_code)
    amount = int(plan.get("price_monthly_cents") or 0)
    provider_invoice_id = f"lifecycle:{subscription_id}:{period_end or current_period_key()}"
    invoice_number = f"SC-{datetime.now(timezone.utc).strftime('%Y%m')}-{str(uuid4())[:8].upper()}"
    row = conn.execute(
        text(
            """
            INSERT INTO saas_billing_invoices (
                tenant_id, subscription_id, provider, provider_invoice_id, invoice_number,
                status, plan_code, currency, subtotal_cents, total_cents, amount_paid_cents,
                amount_due_cents, period_start, period_end, due_at, metadata_json
            )
            VALUES (
                CAST(:tenant_id AS uuid), CAST(:subscription_id AS uuid), :provider, :provider_invoice_id,
                :invoice_number, :status, :plan_code, :currency, :amount, :amount,
                CASE WHEN :status = 'paid' THEN :amount ELSE 0 END,
                CASE WHEN :status = 'paid' THEN 0 ELSE :amount END,
                COALESCE(CAST(NULLIF(:period_start, '') AS timestamp), date_trunc('month', NOW())),
                COALESCE(CAST(NULLIF(:period_end, '') AS timestamp), date_trunc('month', NOW()) + INTERVAL '1 month'),
                COALESCE(CAST(NULLIF(:due_at, '') AS timestamp), NOW() + INTERVAL '7 days'),
                CAST(:metadata_json AS jsonb)
            )
            ON CONFLICT (provider, provider_invoice_id)
            WHERE provider_invoice_id <> ''
            DO UPDATE SET
                status = EXCLUDED.status,
                amount_due_cents = EXCLUDED.amount_due_cents,
                metadata_json = saas_billing_invoices.metadata_json || EXCLUDED.metadata_json,
                updated_at = NOW()
            RETURNING id::text, tenant_id::text, provider, provider_invoice_id, invoice_number,
                      status, plan_code, currency, total_cents, amount_due_cents,
                      period_start::text, period_end::text, due_at::text, pdf_url
            """
        ),
        {
            "tenant_id": tenant_id,
            "subscription_id": subscription_id,
            "provider": provider,
            "provider_invoice_id": provider_invoice_id,
            "invoice_number": invoice_number,
            "status": status,
            "plan_code": plan["plan_code"],
            "currency": _clean(plan.get("currency") or "USD", 12).upper(),
            "amount": max(0, amount),
            "period_start": _clean(period_start, 80),
            "period_end": _clean(period_end, 80),
            "due_at": _clean(due_at, 80),
            "metadata_json": _json(metadata or {}),
        },
    ).mappings().first()
    if row and not row.get("pdf_url"):
        pdf_url = _invoice_pdf_path(str(row["id"]))
        if pdf_url:
            conn.execute(
                text("UPDATE saas_billing_invoices SET pdf_url = :pdf_url, updated_at = NOW() WHERE id = CAST(:id AS uuid)"),
                {"id": row["id"], "pdf_url": pdf_url},
            )
            row = {**dict(row), "pdf_url": pdf_url}
    return dict(row or {})


def current_period_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m")


def sync_billing_lifecycle(conn: Connection) -> dict[str, int]:
    grace_days = max(0, int(getattr(settings, "billing_past_due_grace_days", 7) or 7))
    expired_rows = conn.execute(
        text(
            """
            WITH expired AS (
                UPDATE saas_billing_subscriptions s
                SET status = CASE WHEN s.cancel_at_period_end = TRUE THEN 'cancelled' ELSE 'past_due' END,
                    past_due_at = CASE WHEN s.cancel_at_period_end = TRUE THEN s.past_due_at ELSE COALESCE(s.past_due_at, NOW()) END,
                    lifecycle_last_checked_at = NOW(),
                    updated_at = NOW()
                WHERE s.status IN ('trial', 'active')
                  AND s.current_period_end IS NOT NULL
                  AND s.current_period_end < NOW()
                RETURNING s.id::text, s.tenant_id::text, s.provider, s.status, s.plan_code,
                          s.current_period_start::text, s.current_period_end::text,
                          s.payment_failed_notice_sent_at::text,
                          s.trial_expired_notice_sent_at::text
            )
            UPDATE saas_tenants t
            SET status = expired.status,
                plan_code = expired.plan_code,
                updated_at = NOW()
            FROM expired
            WHERE t.id = CAST(expired.tenant_id AS uuid)
            RETURNING expired.*
            """
        )
    ).mappings().all()

    trials_past_due = 0
    active_past_due = 0
    cancelled = 0
    invoices_created = 0
    notices_sent = 0
    for row in expired_rows:
        status = str(row["status"] or "")
        if status == "cancelled":
            cancelled += 1
            continue
        if row.get("provider") == "trial":
            trials_past_due += 1
        else:
            active_past_due += 1
        invoice = _ensure_period_invoice(
            conn,
            tenant_id=str(row["tenant_id"]),
            subscription_id=str(row["id"]),
            plan_code=str(row["plan_code"]),
            provider=str(row["provider"] or "lifecycle"),
            status="open",
            period_start=row.get("current_period_start"),
            period_end=row.get("current_period_end"),
            due_at="",
            metadata={"source": "billing_lifecycle", "subscription_status": status},
        )
        if invoice:
            invoices_created += 1
        notice_column = "trial_expired_notice_sent_at" if row.get("provider") == "trial" else "payment_failed_notice_sent_at"
        if not row.get(notice_column):
            sent = _send_billing_notice(
                conn,
                tenant_id=str(row["tenant_id"]),
                subject="Scentra +AI: pago requerido para continuar",
                body=(
                    "Hola. Tu periodo de Scentra +AI vencio y la empresa quedo en estado pago pendiente.\n\n"
                    "Para recuperar la operacion completa, entra a Plan y consumo y completa el checkout."
                ),
            )
            if sent:
                notices_sent += 1
                conn.execute(
                    text(f"UPDATE saas_billing_subscriptions SET {notice_column} = NOW() WHERE id = CAST(:id AS uuid)"),
                    {"id": row["id"]},
                )

    suspended_rows = conn.execute(
        text(
            """
            WITH suspended AS (
                UPDATE saas_billing_subscriptions s
                SET status = 'suspended',
                    lifecycle_last_checked_at = NOW(),
                    updated_at = NOW()
                WHERE s.status = 'past_due'
                  AND s.past_due_at IS NOT NULL
                  AND s.past_due_at < NOW() - make_interval(days => :grace_days)
                RETURNING s.id::text, s.tenant_id::text, s.suspension_notice_sent_at::text
            )
            UPDATE saas_tenants t
            SET status = 'suspended', updated_at = NOW()
            FROM suspended
            WHERE t.id = CAST(suspended.tenant_id AS uuid)
            RETURNING suspended.*
            """
        ),
        {"grace_days": grace_days},
    ).mappings().all()
    for row in suspended_rows:
        if not row.get("suspension_notice_sent_at"):
            if _send_billing_notice(
                conn,
                tenant_id=str(row["tenant_id"]),
                subject="Scentra +AI: empresa suspendida por pago pendiente",
                body=(
                    "Hola. La empresa fue suspendida por mantener pago pendiente despues del periodo de gracia.\n\n"
                    "Puedes recuperar acceso operativo completando el pago o contactando soporte."
                ),
            ):
                notices_sent += 1
                conn.execute(
                    text("UPDATE saas_billing_subscriptions SET suspension_notice_sent_at = NOW() WHERE id = CAST(:id AS uuid)"),
                    {"id": row["id"]},
                )

    open_due_rows = conn.execute(
        text(
            """
            UPDATE saas_billing_invoices i
            SET status = 'uncollectible',
                updated_at = NOW()
            WHERE i.status IN ('open', 'past_due')
              AND i.due_at IS NOT NULL
              AND i.due_at < NOW() - make_interval(days => :grace_days)
            RETURNING i.id::text
            """
        ),
        {"grace_days": grace_days},
    ).mappings().all()
    return {
        "trials_past_due": trials_past_due,
        "subscriptions_past_due": active_past_due,
        "subscriptions_cancelled": cancelled,
        "subscriptions_suspended": len(suspended_rows),
        "invoices_created": invoices_created,
        "invoices_uncollectible": len(open_due_rows),
        "notices_sent": notices_sent,
    }


def _activate_paid_checkout(
    conn: Connection,
    *,
    provider: str,
    provider_checkout_id: str,
    provider_payment_id: str,
    payload: dict[str, Any],
    fallback_tenant_id: str = "",
    fallback_plan_code: str = "",
    provider_customer_id: str = "",
    provider_subscription_id: str = "",
) -> dict[str, Any]:
    fallback_tenant_id = _clean_uuid(fallback_tenant_id)
    session = conn.execute(
        text(
            """
            SELECT id::text, tenant_id::text, plan_code, currency, amount_cents
            FROM saas_billing_checkout_sessions
            WHERE provider = :provider
              AND provider_checkout_id = :provider_checkout_id
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"provider": provider, "provider_checkout_id": provider_checkout_id},
    ).mappings().first()
    if not session and fallback_tenant_id and fallback_plan_code:
        session = conn.execute(
            text(
                """
                SELECT id::text, tenant_id::text, plan_code, currency, amount_cents
                FROM saas_billing_checkout_sessions
                WHERE provider = :provider
                  AND tenant_id = CAST(:tenant_id AS uuid)
                  AND plan_code = :plan_code
                  AND status IN ('pending', 'manual_pending')
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"provider": provider, "tenant_id": fallback_tenant_id, "plan_code": fallback_plan_code},
        ).mappings().first()
    if not session:
        return {"ok": False, "reason": "checkout_session_not_found"}

    plan_code = str(session["plan_code"])
    tenant_id = str(session["tenant_id"])
    amount = int(session.get("amount_cents") or 0)
    currency = str(session.get("currency") or "COP").upper()
    subscription_id = conn.execute(
        text(
            """
            INSERT INTO saas_billing_subscriptions (
                tenant_id, provider, provider_subscription_id, status, plan_code,
                provider_customer_id, current_period_start, current_period_end, last_payment_at,
                past_due_at, payment_failed_notice_sent_at, metadata_json, updated_at
            )
            VALUES (
                CAST(:tenant_id AS uuid), :provider, :provider_subscription_id, 'active', :plan_code,
                :provider_customer_id, NOW(), NOW() + INTERVAL '1 month', NOW(),
                NULL, NULL, CAST(:metadata_json AS jsonb), NOW()
            )
            ON CONFLICT (provider_subscription_id)
            DO UPDATE SET
                status = 'active',
                plan_code = EXCLUDED.plan_code,
                provider_customer_id = COALESCE(NULLIF(EXCLUDED.provider_customer_id, ''), saas_billing_subscriptions.provider_customer_id),
                current_period_start = EXCLUDED.current_period_start,
                current_period_end = EXCLUDED.current_period_end,
                last_payment_at = NOW(),
                past_due_at = NULL,
                payment_failed_notice_sent_at = NULL,
                metadata_json = EXCLUDED.metadata_json,
                updated_at = NOW()
            RETURNING id::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "provider": provider,
            "provider_subscription_id": provider_subscription_id or f"{provider}:{provider_checkout_id or provider_payment_id}",
            "provider_customer_id": provider_customer_id,
            "plan_code": plan_code,
            "metadata_json": _json({"source": "checkout", "payload": payload}),
        },
    ).scalar()
    conn.execute(
        text("UPDATE saas_tenants SET status = 'active', plan_code = :plan_code, updated_at = NOW() WHERE id = CAST(:tenant_id AS uuid)"),
        {"tenant_id": tenant_id, "plan_code": plan_code},
    )
    conn.execute(
        text(
            """
            UPDATE saas_billing_checkout_sessions
            SET status = 'paid', completed_at = COALESCE(completed_at, NOW()),
                last_provider_event_at = NOW(),
                error = '', metadata_json = metadata_json || CAST(:metadata_json AS jsonb), updated_at = NOW()
            WHERE id = CAST(:session_id AS uuid)
            """
        ),
        {"session_id": session["id"], "metadata_json": _json({"paid_event": payload})},
    )
    invoice = conn.execute(
        text(
            """
            INSERT INTO saas_billing_invoices (
                tenant_id, subscription_id, provider, provider_invoice_id, invoice_number,
                status, plan_code, currency, subtotal_cents, total_cents, amount_paid_cents,
                amount_due_cents, period_start, period_end, paid_at, metadata_json
            )
            VALUES (
                CAST(:tenant_id AS uuid), CAST(:subscription_id AS uuid), :provider,
                :provider_invoice_id, :invoice_number, 'paid', :plan_code, :currency,
                :amount, :amount, :amount, 0, NOW(), NOW() + INTERVAL '1 month', NOW(),
                CAST(:metadata_json AS jsonb)
            )
            ON CONFLICT (provider, provider_invoice_id)
            WHERE provider_invoice_id <> ''
            DO UPDATE SET
                status = 'paid',
                amount_paid_cents = EXCLUDED.amount_paid_cents,
                amount_due_cents = 0,
                paid_at = COALESCE(saas_billing_invoices.paid_at, NOW()),
                metadata_json = EXCLUDED.metadata_json,
                updated_at = NOW()
            RETURNING id::text
            """
        ),
        {
            "tenant_id": tenant_id,
            "subscription_id": subscription_id,
            "provider": provider,
            "provider_invoice_id": provider_payment_id or provider_checkout_id,
            "invoice_number": f"{provider.upper()}-{provider_checkout_id[:22]}",
            "plan_code": plan_code,
            "currency": currency,
            "amount": amount,
            "metadata_json": _json({"checkout_session_id": session["id"], "payload": payload}),
        },
    ).mappings().first()
    conn.execute(
        text(
            """
            INSERT INTO saas_billing_payments (
                tenant_id, invoice_id, provider, provider_payment_id, status, currency,
                amount_cents, paid_at, metadata_json
            )
            VALUES (
                CAST(:tenant_id AS uuid), CAST(:invoice_id AS uuid), :provider,
                :provider_payment_id, 'paid', :currency, :amount, NOW(), CAST(:metadata_json AS jsonb)
            )
            ON CONFLICT (provider, provider_payment_id)
            WHERE provider_payment_id <> ''
            DO UPDATE SET
                status = 'paid',
                paid_at = COALESCE(saas_billing_payments.paid_at, NOW()),
                metadata_json = EXCLUDED.metadata_json,
                updated_at = NOW()
            """
        ),
        {
            "tenant_id": tenant_id,
            "invoice_id": invoice["id"] if invoice else None,
            "provider": provider,
            "provider_payment_id": provider_payment_id or provider_checkout_id,
            "currency": currency,
            "amount": amount,
            "metadata_json": _json(payload),
        },
    )
    record_inline_event(
        conn,
        tenant_id,
        event_type="billing.subscription.changed",
        source="saas_billing_subscriptions",
        channel=provider,
        entity_type="billing_subscription",
        entity_id=subscription_id,
        payload_json={
            "status": "active",
            "plan_code": plan_code,
            "provider": provider,
            "checkout_session_id": session["id"],
            "provider_checkout_id": provider_checkout_id,
            "provider_payment_id": provider_payment_id,
            "amount_cents": amount,
            "currency": currency,
        },
        replay_key=f"billing_subscription:{subscription_id}:active:{plan_code}",
    )
    return {"ok": True, "tenant_id": tenant_id, "plan_code": plan_code, "subscription_id": subscription_id}


def _tenant_plan_from_reference(reference: str) -> tuple[str, str]:
    clean = _clean(reference, 220)
    if ":" not in clean:
        return "", ""
    tenant_id, plan_code = clean.split(":", 1)
    return _clean_uuid(tenant_id), _clean(plan_code, 40).lower()


def _find_subscription_tenant(conn: Connection, *, provider: str, provider_subscription_id: str = "", tenant_id: str = "") -> dict[str, Any]:
    if tenant_id:
        row = conn.execute(
            text(
                """
                SELECT s.id::text, s.tenant_id::text, s.plan_code, s.status, t.name AS tenant_name
                FROM saas_billing_subscriptions s
                JOIN saas_tenants t ON t.id = s.tenant_id
                WHERE s.tenant_id = CAST(:tenant_id AS uuid)
                ORDER BY s.updated_at DESC
                LIMIT 1
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().first()
        return dict(row or {})
    if provider_subscription_id:
        row = conn.execute(
            text(
                """
                SELECT s.id::text, s.tenant_id::text, s.plan_code, s.status, t.name AS tenant_name
                FROM saas_billing_subscriptions s
                JOIN saas_tenants t ON t.id = s.tenant_id
                WHERE s.provider = :provider
                  AND s.provider_subscription_id = :provider_subscription_id
                LIMIT 1
                """
            ),
            {"provider": provider, "provider_subscription_id": provider_subscription_id},
        ).mappings().first()
        return dict(row or {})
    return {}


def _mark_subscription_state(
    conn: Connection,
    *,
    provider: str,
    status: str,
    provider_subscription_id: str = "",
    tenant_id: str = "",
    payload: dict[str, Any] | None = None,
    notify: bool = False,
    reason: str = "",
) -> dict[str, Any]:
    tenant_id = _clean_uuid(tenant_id)
    sub = _find_subscription_tenant(conn, provider=provider, provider_subscription_id=provider_subscription_id, tenant_id=tenant_id)
    if not sub:
        return {"ok": False, "reason": "subscription_not_found"}
    clean_status = _clean(status, 40).lower()
    tenant_status = "active" if clean_status == "active" else clean_status
    if clean_status == "past_due":
        tenant_status = "past_due"
    elif clean_status == "cancelled":
        tenant_status = "cancelled"
    elif clean_status == "suspended":
        tenant_status = "suspended"
    conn.execute(
        text(
            """
            UPDATE saas_billing_subscriptions
            SET status = :status,
                past_due_at = CASE WHEN :status = 'past_due' THEN COALESCE(past_due_at, NOW()) ELSE past_due_at END,
                payment_failed_notice_sent_at = CASE WHEN :status = 'active' THEN NULL ELSE payment_failed_notice_sent_at END,
                metadata_json = metadata_json || CAST(:metadata_json AS jsonb),
                updated_at = NOW()
            WHERE id = CAST(:subscription_id AS uuid)
            """
        ),
        {
            "subscription_id": sub["id"],
            "status": clean_status,
            "metadata_json": _json({"last_provider_event": payload or {}, "reason": reason}),
        },
    )
    conn.execute(
        text("UPDATE saas_tenants SET status = :status, updated_at = NOW() WHERE id = CAST(:tenant_id AS uuid)"),
        {"tenant_id": sub["tenant_id"], "status": tenant_status},
    )
    sent = False
    if notify and clean_status in {"past_due", "suspended", "cancelled"}:
        sent = _send_billing_notice(
            conn,
            tenant_id=str(sub["tenant_id"]),
            subject="Scentra +AI: accion requerida en tu suscripcion",
            body=(
                f"Hola. La suscripcion de {sub.get('tenant_name') or 'tu empresa'} quedo en estado {clean_status}.\n\n"
                "Para recuperar la operacion, entra a Scentra +AI y actualiza el pago desde Plan y consumo.\n"
                f"Detalle: {reason or 'evento de proveedor'}"
            ),
        )
        if sent:
            conn.execute(
                text(
                    """
                    UPDATE saas_billing_subscriptions
                    SET payment_failed_notice_sent_at = COALESCE(payment_failed_notice_sent_at, NOW())
                    WHERE id = CAST(:subscription_id AS uuid)
                    """
                ),
                {"subscription_id": sub["id"]},
            )
    record_inline_event(
        conn,
        str(sub["tenant_id"]),
        event_type="billing.subscription.changed",
        source="saas_billing_subscriptions",
        channel=provider,
        entity_type="billing_subscription",
        entity_id=str(sub["id"]),
        payload_json={
            "status": clean_status,
            "plan_code": sub.get("plan_code") or "",
            "provider": provider,
            "provider_subscription_id": provider_subscription_id,
            "reason": reason,
            "notice_sent": sent,
        },
        replay_key=f"billing_subscription:{sub['id']}:{clean_status}:{sub.get('plan_code') or ''}",
    )
    return {"ok": True, "tenant_id": sub["tenant_id"], "subscription_id": sub["id"], "status": clean_status, "notice_sent": sent}


def record_provider_event(
    conn: Connection,
    *,
    provider: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    clean_provider = _clean(provider, 40).lower()
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    wompi_transaction = data.get("transaction") if isinstance(data.get("transaction"), dict) else {}
    event_id = _clean(
        payload.get("id")
        or payload.get("event_id")
        or data.get("id")
        or wompi_transaction.get("id"),
        220,
    )
    event_type = _clean(payload.get("type") or payload.get("event") or payload.get("action") or payload.get("topic"), 160)
    tenant_id = ""
    metadata = payload.get("data", {}).get("object", {}).get("metadata") if isinstance(payload.get("data"), dict) else {}
    if isinstance(metadata, dict):
        tenant_id = _clean_uuid(metadata.get("tenant_id"))
    if not tenant_id:
        external_reference = _clean(payload.get("external_reference") or payload.get("data", {}).get("external_reference"), 220)
        if ":" in external_reference:
            tenant_id = external_reference.split(":", 1)[0]
    row = conn.execute(
        text(
            """
            INSERT INTO saas_billing_provider_events (
                provider, provider_event_id, event_type, status, tenant_id, payload_json
            )
            VALUES (
                :provider, :provider_event_id, :event_type, 'received',
                CAST(NULLIF(:tenant_id, '') AS uuid), CAST(:payload_json AS jsonb)
            )
            ON CONFLICT (provider, provider_event_id)
            WHERE provider_event_id <> ''
            DO UPDATE SET payload_json = EXCLUDED.payload_json, received_at = NOW()
            RETURNING id::text, provider, provider_event_id, event_type, status,
                      tenant_id::text, received_at::text, processed_at::text
            """
        ),
        {
            "provider": clean_provider,
            "provider_event_id": event_id,
            "event_type": event_type,
            "tenant_id": tenant_id,
            "payload_json": _json(payload),
        },
    ).mappings().first()
    return dict(row or {})


def process_provider_event(
    conn: Connection,
    *,
    provider: str,
    payload: dict[str, Any],
    raw_body: bytes = b"",
    headers: dict[str, str] | None = None,
    query_params: dict[str, str] | None = None,
    header_checksum: str = "",
) -> dict[str, Any]:
    clean_provider = _clean(provider, 40).lower()
    clean_headers = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    clean_query = {str(k).lower(): str(v) for k, v in (query_params or {}).items()}
    if clean_provider == "stripe" and not verify_stripe_event(raw_body, clean_headers.get("stripe-signature", "")):
        raise HTTPException(status_code=401, detail="invalid_stripe_signature")
    if clean_provider == "mercadopago":
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        data_id = clean_query.get("data.id") or clean_query.get("id") or _clean(data.get("id"), 220)
        if not verify_mercadopago_event(
            conn,
            data_id=data_id,
            x_request_id=clean_headers.get("x-request-id", ""),
            x_signature=clean_headers.get("x-signature", ""),
        ):
            raise HTTPException(status_code=401, detail="invalid_mercadopago_signature")
    if clean_provider == "wompi" and not verify_wompi_event(conn, payload, header_checksum):
        raise HTTPException(status_code=401, detail="invalid_wompi_signature")

    event = record_provider_event(conn, provider=clean_provider, payload=payload)
    processed: dict[str, Any] = {"ok": False, "reason": "recorded_only"}
    if clean_provider == "stripe":
        event_type = _clean(payload.get("type"), 120)
        obj = payload.get("data", {}).get("object") if isinstance(payload.get("data"), dict) else {}
        if not isinstance(obj, dict):
            obj = {}
        if event_type == "checkout.session.completed":
            metadata = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
            paid = _clean(obj.get("payment_status"), 40).lower() in {"paid", "no_payment_required"} or _clean(obj.get("status"), 40).lower() == "complete"
            if paid:
                processed = _activate_paid_checkout(
                    conn,
                    provider="stripe",
                    provider_checkout_id=_clean(obj.get("id"), 220),
                    provider_payment_id=_clean(obj.get("payment_intent") or obj.get("subscription") or obj.get("id"), 220),
                    provider_customer_id=_clean(obj.get("customer"), 220),
                    provider_subscription_id=_clean(obj.get("subscription"), 220) or f"stripe:{_clean(obj.get('id'), 220)}",
                    fallback_tenant_id=_clean_uuid(metadata.get("tenant_id")),
                    fallback_plan_code=_clean(metadata.get("plan_code"), 40).lower(),
                    payload=payload,
                )
        elif event_type in {"invoice.payment_succeeded", "invoice.paid"}:
            subscription_id = _clean(obj.get("subscription"), 220)
            metadata = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
            tenant_id = _clean_uuid(metadata.get("tenant_id"))
            sub = _find_subscription_tenant(conn, provider="stripe", provider_subscription_id=subscription_id, tenant_id=tenant_id)
            if sub:
                amount_paid = int(obj.get("amount_paid") or 0)
                currency = _clean(obj.get("currency") or "USD", 12).upper()
                conn.execute(
                    text(
                        """
                        INSERT INTO saas_billing_invoices (
                            tenant_id, subscription_id, provider, provider_invoice_id, invoice_number,
                            status, plan_code, currency, total_cents, amount_paid_cents,
                            amount_due_cents, hosted_invoice_url, pdf_url, paid_at, metadata_json
                        )
                        VALUES (
                            CAST(:tenant_id AS uuid), CAST(:subscription_id AS uuid), 'stripe', :provider_invoice_id,
                            :invoice_number, 'paid', :plan_code, :currency, :amount, :amount, 0,
                            :hosted_invoice_url, :pdf_url, NOW(), CAST(:metadata_json AS jsonb)
                        )
                        ON CONFLICT (provider, provider_invoice_id)
                        WHERE provider_invoice_id <> ''
                        DO UPDATE SET status = 'paid', amount_paid_cents = EXCLUDED.amount_paid_cents,
                            amount_due_cents = 0, paid_at = COALESCE(saas_billing_invoices.paid_at, NOW()),
                            hosted_invoice_url = EXCLUDED.hosted_invoice_url,
                            pdf_url = EXCLUDED.pdf_url,
                            metadata_json = EXCLUDED.metadata_json,
                            updated_at = NOW()
                        """
                    ),
                    {
                        "tenant_id": sub["tenant_id"],
                        "subscription_id": sub["id"],
                        "provider_invoice_id": _clean(obj.get("id"), 220),
                        "invoice_number": _clean(obj.get("number") or obj.get("id"), 120),
                        "plan_code": sub["plan_code"],
                        "currency": currency,
                        "amount": amount_paid,
                        "hosted_invoice_url": _clean(obj.get("hosted_invoice_url"), 1500),
                        "pdf_url": _clean(obj.get("invoice_pdf"), 1500),
                        "metadata_json": _json(payload),
                    },
                )
                processed = _mark_subscription_state(
                    conn,
                    provider="stripe",
                    provider_subscription_id=subscription_id,
                    tenant_id=str(sub["tenant_id"]),
                    status="active",
                    payload=payload,
                    reason="invoice paid",
                )
        elif event_type in {"invoice.payment_failed", "customer.subscription.paused"}:
            obj_subscription = _clean(obj.get("subscription") or obj.get("id"), 220)
            processed = _mark_subscription_state(
                conn,
                provider="stripe",
                provider_subscription_id=obj_subscription,
                status="past_due",
                payload=payload,
                notify=True,
                reason=event_type,
            )
        elif event_type in {"customer.subscription.deleted", "customer.subscription.canceled"}:
            processed = _mark_subscription_state(
                conn,
                provider="stripe",
                provider_subscription_id=_clean(obj.get("id"), 220),
                status="cancelled",
                payload=payload,
                notify=True,
                reason=event_type,
            )
    elif clean_provider == "mercadopago":
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        payment_id = _clean(data.get("id") or clean_query.get("data.id") or clean_query.get("id"), 220)
        topic = _clean(payload.get("type") or payload.get("topic") or payload.get("action"), 120)
        if payment_id and ("payment" in topic or not topic):
            payment = _mercadopago_get(conn, f"/v1/payments/{urllib.parse.quote(payment_id)}")
            status = _clean(payment.get("status"), 40).lower()
            tenant_id, plan_code = _tenant_plan_from_reference(_clean(payment.get("external_reference"), 220))
            metadata = payment.get("metadata") if isinstance(payment.get("metadata"), dict) else {}
            tenant_id = tenant_id or _clean_uuid(metadata.get("tenant_id"))
            plan_code = plan_code or _clean(metadata.get("plan_code"), 40).lower()
            if status == "approved":
                processed = _activate_paid_checkout(
                    conn,
                    provider="mercadopago",
                    provider_checkout_id=_clean(payment.get("order", {}).get("id") if isinstance(payment.get("order"), dict) else "", 220),
                    provider_payment_id=payment_id,
                    fallback_tenant_id=tenant_id,
                    fallback_plan_code=plan_code,
                    payload={"webhook": payload, "payment": payment},
                )
            elif status in {"rejected", "cancelled", "refunded", "charged_back"} and tenant_id:
                processed = _mark_subscription_state(
                    conn,
                    provider="mercadopago",
                    tenant_id=tenant_id,
                    status="past_due",
                    payload={"webhook": payload, "payment": payment},
                    notify=True,
                    reason=f"payment {status}",
                )
    elif clean_provider == "wompi":
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        tx = data.get("transaction") if isinstance(data.get("transaction"), dict) else {}
        reference = _clean(tx.get("reference"), 220)
        tx_status = _clean(tx.get("status"), 40).upper()
        tx_id = _clean(tx.get("id"), 220)
        if reference and tx_status == "APPROVED":
            processed = _activate_paid_checkout(
                conn,
                provider="wompi",
                provider_checkout_id=reference,
                provider_payment_id=tx_id,
                payload=payload,
            )
        elif reference and tx_status in {"DECLINED", "ERROR", "VOIDED"}:
            session = conn.execute(
                text(
                    """
                    UPDATE saas_billing_checkout_sessions
                    SET status = 'failed',
                        error = :error,
                        last_provider_event_at = NOW(),
                        metadata_json = metadata_json || CAST(:metadata_json AS jsonb),
                        updated_at = NOW()
                    WHERE provider = 'wompi'
                      AND provider_checkout_id = :reference
                    RETURNING tenant_id::text, plan_code
                    """
                ),
                {"reference": reference, "error": tx_status.lower(), "metadata_json": _json({"failed_event": payload})},
            ).mappings().first()
            if session:
                _send_billing_notice(
                    conn,
                    tenant_id=str(session["tenant_id"]),
                    subject="Scentra +AI: pago no aprobado",
                    body=(
                        "Hola. El ultimo intento de pago en Wompi no fue aprobado.\n\n"
                        "Puedes reintentar el checkout desde Plan y consumo en Scentra +AI."
                    ),
                )
                processed = {"ok": True, "tenant_id": session["tenant_id"], "plan_code": session["plan_code"], "status": "payment_failed"}
    conn.execute(
        text(
            """
            UPDATE saas_billing_provider_events
            SET status = :status, processed_at = NOW(), error = :error
            WHERE id = CAST(:event_id AS uuid)
            """
        ),
        {
            "event_id": event.get("id"),
            "status": "processed" if processed.get("ok") else "received",
            "error": "" if processed.get("ok") else _clean(processed.get("reason"), 500),
        },
    )
    return {"event": event, "processed": processed}
