"""Marketing Lead → same Google Sheet as orders (after Meta Lead on thank-you)."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from pydantic import BaseModel, Field

from app.services.phone_sa import normalize_sa_phone
from app.services.sheet_webhook import build_marketing_lead_sheet_row, send_google_sheet_webhook

router = APIRouter()
logger = logging.getLogger(__name__)


class LeadSheetLineIn(BaseModel):
    product_id: str = Field(..., min_length=1, max_length=96)
    offer_qty: int = Field(..., ge=1, le=9999)


class MarketingLeadSheetIn(BaseModel):
    """Same window as thank-you `trackMeta('Lead', …)` — sent via Next.js server route (secret not in browser)."""

    lead_event_id: str = Field(..., min_length=8, max_length=128)
    customer_name: str = Field(..., min_length=1, max_length=220)
    phone: str = Field(..., min_length=8, max_length=32)
    total_sar: float = Field(..., ge=0, le=9_999_999)
    lines: list[LeadSheetLineIn] = Field(..., min_length=1, max_length=50)
    order_number: str | None = Field(None, max_length=64)


def _require_sheet_lead_ingest_secret(x_secret: str | None) -> None:
    expected = os.getenv("SHEET_LEAD_INGEST_SECRET", "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="SHEET_LEAD_INGEST_SECRET غير مهيّأ — لا يمكن تسجيل Lead في الشيت.",
        )
    got = (x_secret or "").strip()
    if not got or got != expected:
        raise HTTPException(status_code=401, detail="Invalid X-Sheet-Lead-Ingest-Secret")


def _deliver_marketing_lead_row(payload: dict[str, str | int]) -> None:
    outcome, err = send_google_sheet_webhook(payload)
    logger.info(
        "[sheet_leads] marketing_lead SEND_DONE order_id=%s outcome=%s detail=%s",
        payload.get("order_id"),
        outcome,
        (err[:200] if err else None),
    )


@router.post("/sheet-leads/marketing")
def post_marketing_lead_sheet_row(
    body: MarketingLeadSheetIn,
    background_tasks: BackgroundTasks,
    x_sheet_lead_ingest_secret: str | None = Header(default=None, alias="X-Sheet-Lead-Ingest-Secret"),
) -> dict[str, object]:
    """Append one row when Meta Lead fires (thank-you). Secured by shared secret (set on API + Next server)."""

    _require_sheet_lead_ingest_secret(x_sheet_lead_ingest_secret)

    try:
        _local, _e164, phone_digits = normalize_sa_phone(body.phone)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    lines = [(ln.product_id.strip().lower(), ln.offer_qty) for ln in body.lines]
    try:
        payload = build_marketing_lead_sheet_row(
            customer_name=body.customer_name,
            phone_digits=phone_digits,
            total_sar=body.total_sar,
            lines=lines,
            lead_event_id=body.lead_event_id.strip(),
            order_number_hint=body.order_number,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    background_tasks.add_task(_deliver_marketing_lead_row, payload)
    logger.info(
        "[sheet_leads] marketing_lead ENQUEUED order_id=%s lead_event_id=%s",
        payload.get("order_id"),
        body.lead_event_id[:32],
    )
    return {"ok": True, "sheet_order_id": payload.get("order_id")}
