from __future__ import annotations

import base64
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app_saas.api_credentials.router import _ensure_api_credentials_table, _load_credential
from app_saas.db import db_session, set_tenant_context
from app_saas.shared.security import AuthContext, get_current_user
from app_saas.shared.secrets import decrypt_secret

router = APIRouter(prefix="/commerce", tags=["saas-commerce"])


def _normalize_store_url(value: str) -> str:
    clean = str(value or "").strip().rstrip("/")
    if not clean:
        return ""
    if not clean.startswith(("http://", "https://")):
        clean = f"https://{clean}"
    return clean


def _credential_value(conn, tenant_id: str, provider_code: str, credential_key: str) -> str:
    credential = _load_credential(conn, tenant_id, provider_code, credential_key)
    return decrypt_secret(str((credential or {}).get("secret_value") or ""))


def _woocommerce_request(base_url: str, consumer_key: str, consumer_secret: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode(params)
    url = f"{base_url}/wp-json/wc/v3/products?{query}"
    token = base64.b64encode(f"{consumer_key}:{consumer_secret}".encode("utf-8")).decode("ascii")
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Basic {token}",
            "User-Agent": "ScentraAI/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw or "[]")
            return parsed if isinstance(parsed, list) else []
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=502, detail={"code": "woocommerce_catalog_error", "message": raw[:500]})
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"code": "woocommerce_catalog_unavailable", "message": str(exc)[:300]})


def _safe_product(item: dict[str, Any]) -> dict[str, Any]:
    images = item.get("images") if isinstance(item.get("images"), list) else []
    first_image = next((image for image in images if isinstance(image, dict) and image.get("src")), {})
    categories = item.get("categories") if isinstance(item.get("categories"), list) else []
    attributes = item.get("attributes") if isinstance(item.get("attributes"), list) else []
    clean_attributes: list[dict[str, str]] = []
    for attribute in attributes:
        if not isinstance(attribute, dict):
            continue
        name = str(attribute.get("name") or "").strip()
        options = attribute.get("options")
        value = ", ".join(str(option).strip() for option in options if str(option).strip()) if isinstance(options, list) else str(attribute.get("option") or "").strip()
        if name and value:
            clean_attributes.append({"name": name[:80], "value": value[:220]})
    short_description = html.unescape(re.sub(r"<[^>]+>", " ", str(item.get("short_description") or "")))
    short_description = re.sub(r"\s+", " ", short_description).strip()
    return {
        "id": str(item.get("id") or ""),
        "name": str(item.get("name") or "Producto"),
        "sku": str(item.get("sku") or ""),
        "price": str(item.get("price") or ""),
        "regular_price": str(item.get("regular_price") or ""),
        "sale_price": str(item.get("sale_price") or ""),
        "currency": str(item.get("currency") or ""),
        "permalink": str(item.get("permalink") or ""),
        "image_url": str(first_image.get("src") or ""),
        "stock_status": str(item.get("stock_status") or ""),
        "categories": [str(category.get("name") or "") for category in categories if isinstance(category, dict) and category.get("name")],
        "attributes": clean_attributes[:8],
        "short_description": short_description[:300],
    }


@router.get("/products")
def list_commerce_products(
    search: str = Query("", max_length=120),
    limit: int = Query(24, ge=1, le=50),
    ctx: AuthContext = Depends(get_current_user),
):
    with db_session() as conn:
        _ensure_api_credentials_table(conn)
        set_tenant_context(conn, ctx.tenant_id)
        base_url = _normalize_store_url(_credential_value(conn, ctx.tenant_id, "woocommerce", "WC_BASE_URL"))
        consumer_key = _credential_value(conn, ctx.tenant_id, "woocommerce", "WC_CONSUMER_KEY")
        consumer_secret = _credential_value(conn, ctx.tenant_id, "woocommerce", "WC_CONSUMER_SECRET")

    if not base_url or not consumer_key or not consumer_secret:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "commerce_credentials_missing",
                "message": "Conecta WC_BASE_URL, WC_CONSUMER_KEY y WC_CONSUMER_SECRET en Ajustes > APIs.",
            },
        )

    params: dict[str, Any] = {
        "per_page": limit,
        "status": "publish",
        "orderby": "date",
        "order": "desc",
    }
    if search.strip():
        params["search"] = search.strip()
    products = _woocommerce_request(base_url, consumer_key, consumer_secret, params)
    return {
        "ok": True,
        "source": "woocommerce",
        "products": [_safe_product(item) for item in products if isinstance(item, dict)],
    }
