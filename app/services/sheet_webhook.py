"""Push one confirmed order row to Google Sheets via Apps Script URL."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

import httpx

from app.services.catalog import resolve_product, resolve_sku

logger = logging.getLogger(__name__)

Ryadh = ZoneInfo("Asia/Riyadh")


def build_sheet_row(
    *,
    customer_name: str,
    phone_digits: str,
    order_number: str,
    total_sar: float,
    lines: list[tuple[str, int]],
) -> dict[str, str | int]:
    """JSON body matching spreadsheet columns (DATE … STATUS); status stays empty."""

    order_date = datetime.now(Ryadh).strftime("%d/%m/%Y")

    arabic_names: list[str] = []
    skus: list[str] = []
    qtys: list[str] = []
    for product_id, qty in lines:
        ar, _en = resolve_product(product_id)
        arabic_names.append(ar)
        skus.append(resolve_sku(product_id))
        qtys.append(str(qty))

    total_int = int(round(total_sar))

    return {
        "date": order_date,
        "order_id": order_number,
        "country": "KSA",
        "name": customer_name.strip(),
        "phone": phone_digits,
        "product": "/".join(arabic_names),
        "sku": "/".join(skus),
        "quantity": "/".join(qtys),
        "total_price": total_int,
        "currency": "SAR",
        "status": "",
    }


def _sheet_retries() -> int:
    raw = os.getenv("GOOGLE_SHEET_WEBHOOK_RETRIES", "5").strip()
    try:
        n = int(raw)
        return max(1, min(n, 10))
    except ValueError:
        return 5


def send_google_sheet_webhook(
    payload: dict[str, str | int],
) -> tuple[Literal["ok", "skipped", "failed"], str | None]:
    """POST JSON to Apps Script; retries on transient errors so orders reach the Sheet."""

    url = (os.getenv("GOOGLE_SHEET_WEBHOOK_URL") or "").strip()
    if not url:
        return "skipped", "no_webhook_url"

    retries = _sheet_retries()
    last_err: str | None = None

    for attempt in range(retries):
        try:
            resp = httpx.post(url, json=payload, timeout=25.0)
        except Exception:
            last_err = "request_error"
            logger.warning(
                "[sheet_webhook] attempt %s/%s connection_error url_host=%s",
                attempt + 1,
                retries,
                url.split("//", 1)[-1][:80],
            )
            if attempt < retries - 1:
                time.sleep(min(8.0, 2**attempt))
                continue
            logger.exception("[sheet_webhook] all retries exhausted (connection)")
            return "failed", last_err

        if resp.is_success:
            if attempt > 0:
                logger.info("[sheet_webhook] ok after_retries=%s", attempt + 1)
            return "ok", None

        code = resp.status_code
        last_err = f"http_{code}"
        body_preview = (resp.text or "")[:500]
        logger.warning(
            "[sheet_webhook] attempt %s/%s status=%s body=%s",
            attempt + 1,
            retries,
            code,
            body_preview,
        )
        retryable = code in (408, 429, 500, 502, 503, 504)
        if retryable and attempt < retries - 1:
            time.sleep(min(8.0, 2**attempt))
            continue
        break

    return "failed", last_err or "unknown"
