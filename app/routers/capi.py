"""Authenticated HTTP ingress for server-side pixel events (call after order save)."""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.services.capi_dispatch import (
    send_meta_capi_event,
    send_snap_capi_event,
    send_tiktok_capi_event,
)

logger = logging.getLogger(__name__)

router = APIRouter()

META_EVENTS = {"Purchase", "Lead"}
TIKTOK_EVENTS = {
    "Purchase",
    "Lead",
    "CompletePayment",
    "SubmitForm",
    "ViewContent",
    "AddToCart",
    "InitiateCheckout",
}
SNAP_EVENTS = {"PURCHASE", "SIGN_UP", "VIEW_CONTENT", "ADD_CART", "START_CHECKOUT"}


def _require_capi_secret(x_capi_secret: str | None) -> None:
    expected = os.getenv("CAPI_INGEST_SECRET", "").strip()
    if not expected:
        return
    if not x_capi_secret or x_capi_secret.strip() != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing X-CAPI-Secret")


class TrackingEventIn(BaseModel):
    """Shared shape for Purchase / Lead style events."""

    event_name: str = Field(..., examples=["Purchase"])
    event_id: str = Field(..., min_length=8, max_length=128)
    event_source_url: str | None = None
    phone_plain: str | None = None
    client_ip_address: str | None = None
    client_user_agent: str | None = None
    currency: str = "SAR"
    value: float | None = None
    content_ids: list[str] = Field(default_factory=list)
    order_id: str | None = None
    order_number: str | None = None


def _parse_order_id(raw: str | None) -> uuid.UUID | None:
    if not raw or not raw.strip():
        return None
    try:
        return uuid.UUID(raw.strip())
    except ValueError:
        return None


@router.post("/meta")
async def capi_meta(
    body: TrackingEventIn,
    x_capi_secret: str | None = Header(default=None, alias="X-CAPI-Secret"),
) -> dict[str, Any]:
    _require_capi_secret(x_capi_secret)
    if body.event_name not in META_EVENTS:
        raise HTTPException(status_code=400, detail=f"Unsupported Meta event: {body.event_name}")
    if body.value is None:
        raise HTTPException(status_code=400, detail="value is required")

    await send_meta_capi_event(
        event_name=body.event_name,
        event_id=body.event_id,
        order_id=_parse_order_id(body.order_id),
        phone_plain=body.phone_plain or "",
        client_ip=body.client_ip_address,
        user_agent=body.client_user_agent,
        value=body.value,
        content_ids=body.content_ids,
        source_url=body.event_source_url,
    )
    return {"platform": "meta", "ok": True}


@router.post("/tiktok")
async def capi_tiktok(
    body: TrackingEventIn,
    x_capi_secret: str | None = Header(default=None, alias="X-CAPI-Secret"),
) -> dict[str, Any]:
    _require_capi_secret(x_capi_secret)
    if body.event_name not in TIKTOK_EVENTS:
        raise HTTPException(status_code=400, detail=f"Unsupported TikTok event: {body.event_name}")
    if body.value is None:
        raise HTTPException(status_code=400, detail="value is required")

    await send_tiktok_capi_event(
        event_name=body.event_name,
        event_id=body.event_id,
        order_id=_parse_order_id(body.order_id),
        phone_plain=body.phone_plain or "",
        client_ip=body.client_ip_address,
        user_agent=body.client_user_agent,
        value=body.value,
        content_ids=body.content_ids,
        source_url=body.event_source_url,
    )
    return {"platform": "tiktok", "ok": True}


@router.post("/snap")
async def capi_snap(
    body: TrackingEventIn,
    x_capi_secret: str | None = Header(default=None, alias="X-CAPI-Secret"),
) -> dict[str, Any]:
    _require_capi_secret(x_capi_secret)
    snap_name = body.event_name.upper()
    if snap_name not in SNAP_EVENTS:
        raise HTTPException(status_code=400, detail=f"Unsupported Snap event: {body.event_name}")
    if body.value is None:
        raise HTTPException(status_code=400, detail="value is required")

    await send_snap_capi_event(
        event_name=snap_name,
        event_id=body.event_id,
        order_id=_parse_order_id(body.order_id),
        order_number=body.order_number,
        phone_plain=body.phone_plain or "",
        client_ip=body.client_ip_address,
        user_agent=body.client_user_agent,
        value=body.value,
        content_ids=body.content_ids,
        source_url=body.event_source_url,
    )
    return {"platform": "snap", "ok": True}
