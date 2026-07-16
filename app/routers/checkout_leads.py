"""Capture checkout attempts that fail before order save (MaxMind, API errors)."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.schemas.checkout_lead import CheckoutCaptureIn
from app.services.catalog import ensure_product_sellable
from app.services.order_guard import validate_customer_name, validate_sa_mobile_local
from app.services.phone_sa import normalize_sa_phone
from app.services.pricing import bundle_total_sar
from app.services.sheet_webhook import build_sheet_row, send_google_sheet_webhook
from app.services.telegram_notify import notify_checkout_capture

router = APIRouter()
logger = logging.getLogger(__name__)

Ryadh = ZoneInfo("Asia/Riyadh")


def _capture_order_id() -> str:
    day = datetime.now(Ryadh).strftime("%Y%m%d")
    return f"lead-{day}-{secrets.token_hex(3)}"


def _deliver_checkout_capture(
    payload: dict[str, str | float],
    *,
    customer_name: str,
    phone_local: str,
    total_sar: float,
    lines: list[tuple[str, int]],
    failure_status: int | None,
) -> None:
    outcome, err = send_google_sheet_webhook(payload)
    logger.info(
        "[checkout_capture] SEND_DONE order_id=%s outcome=%s detail=%s",
        payload.get("order_id"),
        outcome,
        (err[:200] if err else None),
    )
    notify_checkout_capture(
        sheet_order_id=str(payload.get("order_id") or ""),
        customer_name=customer_name,
        phone_local=phone_local,
        total_sar=total_sar,
        lines=lines,
        failure_status=failure_status,
        sheet_outcome=outcome,
    )


@router.post("/leads/checkout-capture")
def post_checkout_capture(
    body: CheckoutCaptureIn,
    background_tasks: BackgroundTasks,
) -> dict[str, object]:
    """Append Sheet row when checkout fails after the customer entered name+phone."""

    try:
        customer_name = validate_customer_name(body.customer_name)
        phone_local, _e164, phone_digits = normalize_sa_phone(body.phone)
        validate_sa_mobile_local(phone_local)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    lines: list[tuple[str, int]] = []
    quantities: list[int] = []
    for line in body.items:
        pid = line.product_id.strip().lower()
        try:
            ensure_product_sellable(pid)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        lines.append((pid, line.offer_qty))
        quantities.append(line.offer_qty)

    try:
        total_sar = float(bundle_total_sar(sum(quantities)))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    capture_id = _capture_order_id()
    try:
        payload = build_sheet_row(
            customer_name=customer_name,
            phone_digits=phone_digits,
            order_number=capture_id,
            total_sar=total_sar,
            lines=lines,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # STATUS column: flag failed checkout for call center (Apps Script passes through).
    payload["status"] = "CHECKOUT_FAILED"

    background_tasks.add_task(
        _deliver_checkout_capture,
        payload,
        customer_name=customer_name,
        phone_local=phone_local,
        total_sar=total_sar,
        lines=lines,
        failure_status=body.failure_status,
    )
    logger.info(
        "[checkout_capture] ENQUEUED order_id=%s phone=%s status=%s",
        capture_id,
        phone_local[:4] + "…",
        body.failure_status,
    )
    return {"ok": True, "capture_id": capture_id}
