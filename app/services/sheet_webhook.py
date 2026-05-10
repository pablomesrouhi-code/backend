"""POST order summaries to Google Apps Script sheet webhook."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from zoneinfo import ZoneInfo

from app.services.catalog import resolve_sku, sheet_product_labels

logger = logging.getLogger(__name__)

_RIYADH = ZoneInfo("Asia/Riyadh")


def _normalized_webhook_url(url: str) -> str | None:
    u = url.strip()
    if not u:
        return None
    parts = urlsplit(u)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    return u


def build_sheet_row(
    *,
    customer_name: str,
    phone_digits: str,
    order_number: str,
    total_sar: int,
    lines: list[tuple[str, int]],
) -> dict[str, Any]:
    """
    One row aligned with spreadsheet columns:
    DATE, ORDERID, COUNTRY, NAME, PHONE, PRODUCT, SKU, quantité,
    TOTAL PRICE, CURRENCY, STATUS (STATUS left empty — sheet column exists).
    """
    if not lines:
        raise ValueError("sheet webhook needs at least one line item")

    short_names = [sheet_product_labels(pid) for pid, _ in lines]
    skus = [resolve_sku(pid) for pid, _ in lines]
    qty_parts = [str(qty) for _, qty in lines]

    dt = datetime.now(_RIYADH).strftime("%d/%m/%Y")

    return {
        "date": dt,
        "order_id": order_number,
        "country": "KSA",
        "name": customer_name.strip(),
        "phone": phone_digits.strip(),
        "product": "/".join(short_names),
        "sku": "/".join(skus),
        "quantity": "/".join(qty_parts),
        "total_price": total_sar,
        "currency": "SAR",
        "status": "",
    }


def send_google_sheet_webhook(payload: dict[str, Any]) -> tuple[str, str | None]:
    """
    Posts JSON row to Apps Script web app URL.

    Returns (outcome, error_message_or_none) where outcome is
    skipped | ok | failed.
    """
    raw = os.getenv("GOOGLE_SHEET_WEBHOOK_URL") or ""
    url = _normalized_webhook_url(raw)
    if not url:
        logger.info("[sheet_webhook] GOOGLE_SHEET_WEBHOOK_URL not set — skip")
        return "skipped", None

    try:
        with httpx.Client(timeout=20.0) as client:
            r = client.post(url, json=payload, headers={"Content-Type": "application/json"})
        if r.status_code >= 400:
            err = f"HTTP {r.status_code}: {r.text[:500]}"
            logger.warning("[sheet_webhook] failed %s", err)
            return "failed", err
        logger.info("[sheet_webhook] ok status=%s", r.status_code)
        return "ok", None
    except httpx.TimeoutException:
        logger.warning("[sheet_webhook] timeout")
        return "failed", "timeout"
    except Exception as exc:
        msg = str(exc)[:500]
        logger.warning("[sheet_webhook] error %s", msg)
        return "failed", msg
