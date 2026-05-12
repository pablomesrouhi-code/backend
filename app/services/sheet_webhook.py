"""Push one confirmed order row to Google Sheets via Apps Script URL."""

from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy.exc import SQLAlchemyError

from app.database import SessionLocal, get_engine
from app.models.order_models import Order
from app.services.catalog import resolve_product, resolve_sku, sheet_product_labels

logger = logging.getLogger(__name__)

Ryadh = ZoneInfo("Asia/Riyadh")


def sheet_order_public_id(internal_order_number: str) -> str:
    """Public ORDERID for Sheets (``SHEET_ORDER_ID_PREFIX``). Default converts ``nabta-…`` → ``nama-…``."""

    inn = internal_order_number.strip()
    pref = (os.getenv("SHEET_ORDER_ID_PREFIX") or "nama").strip().lower()
    if not pref:
        return inn
    if inn.startswith("nabta-"):
        return pref + inn[5:]
    if inn.startswith("nabta"):
        return pref + inn[len("nabta") :]
    return f"{pref}-{inn}"


def build_sheet_row(
    *,
    customer_name: str,
    phone_digits: str,
    order_number: str,
    total_sar: float,
    lines: list[tuple[str, int]],
) -> dict[str, str | int]:
    """JSON body matching Sheets row order (see ``google-apps-script-webhook.js``). ``status`` sent empty."""

    order_date = datetime.now(Ryadh).strftime("%d/%m/%Y")

    arabic_short: list[str] = []
    skus: list[str] = []
    qtys: list[str] = []
    for product_id, qty in lines:
        resolve_product(product_id)  # validate id
        arabic_short.append(sheet_product_labels(product_id))
        skus.append(resolve_sku(product_id))
        qtys.append(str(qty))

    total_int = int(round(total_sar))

    return {
        "date": order_date,
        "order_id": sheet_order_public_id(order_number),
        "country": "KSA",
        "name": customer_name.strip(),
        "phone": phone_digits,
        "product": "/".join(arabic_short),
        "sku": "/".join(skus),
        "quantity": "/".join(qtys),
        "total_price": total_int,
        "currency": "SAR",
        "status": "",
    }


def rebuild_sheet_payload_from_persisted_order(order: Order) -> dict[str, str | int]:
    """Rebuild POST JSON from DB (manual resend / diagnostics). Lines follow saved ``order_items`` order."""

    lines = [(it.product_id.strip().lower(), it.offer_qty) for it in order.items]
    return build_sheet_row(
        customer_name=order.customer_name,
        phone_digits=order.phone_digits,
        order_number=order.order_number,
        total_sar=float(order.total_sar),
        lines=lines,
    )


def _sheet_retries() -> int:
    raw = os.getenv("GOOGLE_SHEET_WEBHOOK_RETRIES", "5").strip()
    try:
        n = int(raw)
        return max(1, min(n, 10))
    except ValueError:
        return 5


def _strip_panel_wrapped_url(raw: str) -> str:
    s = (raw or "").strip()
    if s.startswith("\ufeff"):
        s = s.lstrip("\ufeff").strip()
    while len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        s = s[1:-1].strip()
    return s.rstrip("/")


def _webhook_url_from_env() -> str:
    """``GOOGLE_SHEET_WEBHOOK_URL`` or shorter alias ``SHEET_WEBHOOK_URL`` (some panels truncate long keys)."""

    for key in ("GOOGLE_SHEET_WEBHOOK_URL", "SHEET_WEBHOOK_URL"):
        url = _strip_panel_wrapped_url(os.getenv(key) or "")
        if url:
            return url
    return ""


def send_google_sheet_webhook(
    payload: dict[str, str | int],
) -> tuple[Literal["ok", "skipped", "failed"], str | None]:
    """POST JSON to Apps Script; retries on transient errors so orders reach the Sheet."""

    url = _webhook_url_from_env()
    if not url:
        return "skipped", "no_webhook_url"

    headers = {
        "User-Agent": "NabtalaboBackend/1.0 (+sheet webhook; contact store tech)",
        "Accept": "application/json, text/plain;q=0.9, */*;q=0.8",
    }

    retries = _sheet_retries()
    last_err: str | None = None

    for attempt in range(retries):
        try:
            # Google Apps Script often returns redirects; POST must follow them or we never reach doPost().
            with httpx.Client(timeout=25.0, follow_redirects=True) as client:
                resp = client.post(url, json=payload, headers=headers)
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
            # Web apps often return HTTP 200 even when the script returns JSON { ok: false }.
            try:
                j = resp.json()
            except Exception:
                logger.warning(
                    "[sheet_webhook] attempt %s/%s http_ok_non_json body=%s",
                    attempt + 1,
                    retries,
                    (resp.text or "")[:400],
                )
                last_err = "non_json_response"
                if attempt < retries - 1:
                    time.sleep(min(8.0, 2**attempt))
                    continue
                return "failed", last_err

            if isinstance(j, dict) and j.get("ok") is True:
                if attempt > 0:
                    logger.info("[sheet_webhook] ok after_retries=%s", attempt + 1)
                return "ok", None

            if isinstance(j, dict):
                script_err = str(j.get("error") or j.get("detail") or "script_ok_false")[:400]
                hint = j.get("hint")
                if isinstance(hint, str) and hint.strip():
                    script_err = f"{script_err} — {hint.strip()[:280]}"
                last_err = f"sheet_script:{script_err}"
            else:
                last_err = "unexpected_json"

            logger.warning(
                "[sheet_webhook] attempt %s/%s script_rejected json=%s",
                attempt + 1,
                retries,
                str(j)[:500],
            )
            if attempt < retries - 1:
                time.sleep(min(8.0, 2**attempt))
                continue
            return "failed", last_err

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


def apply_sheet_delivery_to_order(
    order_id: uuid.UUID, payload: dict[str, str | int]
) -> None:
    """POST to Apps Script **after** the API response returns (avoid blocking checkout).

    Persists webhook outcome onto ``Order.sheet_*`` using a fresh session.
    """

    logger.info(
        "[sheet_webhook] SEND_START order_uuid=%s order_number=%s",
        order_id,
        payload.get("order_id"),
    )

    try:
        outcome, sheet_err = send_google_sheet_webhook(payload)
    except Exception:
        logger.exception(
            "[sheet_webhook] background send failed order_id=%s", order_id
        )
        outcome, sheet_err = "failed", "sheet_payload_error"

    try:
        get_engine()
    except RuntimeError:
        logger.warning("[sheet_webhook] skip_sheet_meta_save no engine order_id=%s", order_id)
        return

    db = SessionLocal()
    try:
        persisted = db.get(Order, order_id)
        if persisted is None:
            logger.warning("[sheet_webhook] order_missing_for_sheet_meta order_id=%s", order_id)
            return
        if outcome == "ok":
            persisted.sheet_sent_at = datetime.now(UTC)
            persisted.sheet_error = None
        elif outcome == "failed":
            persisted.sheet_error = (sheet_err or "unknown")[:4000]
        elif outcome == "skipped":
            persisted.sheet_error = (sheet_err or "sheet_skipped")[:4000]
        try:
            db.commit()
        except SQLAlchemyError:
            logger.exception("[sheet_webhook] sheet_meta_commit_failed order_id=%s", order_id)
            db.rollback()
        else:
            logger.info(
                "[sheet_webhook] SEND_DONE order_uuid=%s order_number=%s outcome=%s detail=%s",
                order_id,
                payload.get("order_id"),
                outcome,
                (sheet_err[:200] if sheet_err else None),
            )
    finally:
        db.close()
