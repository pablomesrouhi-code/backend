"""Authenticated HTTP ingress for server-side pixel events (call after order save)."""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.meta_capi import send_meta_web_event
from app.phone_hash import hash_sa_phone_for_capi
from app.snap_capi import send_snap_web_event
from app.tiktok_capi import send_tiktok_web_event

logger = logging.getLogger(__name__)

router = APIRouter()


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


def _meta_user_custom(body: TrackingEventIn) -> tuple[dict[str, Any], dict[str, Any]]:
    user_data: dict[str, Any] = {}
    if body.phone_plain:
        h = hash_sa_phone_for_capi(body.phone_plain)
        if h:
            user_data["ph"] = [h]
    if body.client_ip_address:
        user_data["client_ip_address"] = body.client_ip_address
    if body.client_user_agent:
        user_data["client_user_agent"] = body.client_user_agent

    custom_data: dict[str, Any] = {"currency": body.currency, "content_type": "product"}
    if body.value is not None:
        custom_data["value"] = body.value
    if body.content_ids:
        custom_data["content_ids"] = body.content_ids

    return user_data, custom_data


@router.post("/meta")
async def capi_meta(
    body: TrackingEventIn,
    x_capi_secret: str | None = Header(default=None, alias="X-CAPI-Secret"),
) -> dict[str, Any]:
    _require_capi_secret(x_capi_secret)
    pixel_id = os.getenv("META_PIXEL_ID", "").strip()
    token = os.getenv("META_CAPI_ACCESS_TOKEN", "").strip()
    if not pixel_id or not token:
        raise HTTPException(status_code=503, detail="META_PIXEL_ID or META_CAPI_ACCESS_TOKEN not configured")

    user_data, custom_data = _meta_user_custom(body)
    try:
        status, text = await send_meta_web_event(
            pixel_id=pixel_id,
            access_token=token,
            event_name=body.event_name,
            event_id=body.event_id,
            user_data=user_data,
            custom_data=custom_data,
            event_source_url=body.event_source_url,
        )
        if status >= 400:
            logger.warning("Meta CAPI non-success: %s %s", status, text[:500])
        return {"platform": "meta", "upstream_status": status, "ok": status < 400}
    except Exception:
        logger.exception("Meta CAPI request failed")
        return {"platform": "meta", "upstream_status": None, "ok": False}


@router.post("/tiktok")
async def capi_tiktok(
    body: TrackingEventIn,
    x_capi_secret: str | None = Header(default=None, alias="X-CAPI-Secret"),
) -> dict[str, Any]:
    _require_capi_secret(x_capi_secret)
    pixel_code = os.getenv("TIKTOK_PIXEL_CODE", "").strip()
    token = os.getenv("TIKTOK_ACCESS_TOKEN", "").strip()
    if not pixel_code or not token:
        raise HTTPException(
            status_code=503,
            detail="TIKTOK_PIXEL_CODE or TIKTOK_ACCESS_TOKEN not configured",
        )

    user: dict[str, Any] = {}
    if body.phone_plain:
        h = hash_sa_phone_for_capi(body.phone_plain)
        if h:
            user["phone"] = h
    if body.client_ip_address:
        user["ip"] = body.client_ip_address
    if body.client_user_agent:
        user["user_agent"] = body.client_user_agent

    properties: dict[str, Any] = {"currency": body.currency}
    if body.value is not None:
        properties["value"] = body.value
    if body.content_ids:
        properties["content_id"] = ",".join(body.content_ids)

    try:
        status, text = await send_tiktok_web_event(
            pixel_code=pixel_code,
            access_token=token,
            event_name=body.event_name,
            event_id=body.event_id,
            properties=properties,
            user=user,
        )
        if status >= 400:
            logger.warning("TikTok Events API non-success: %s %s", status, text[:500])
        return {"platform": "tiktok", "upstream_status": status, "ok": status < 400}
    except Exception:
        logger.exception("TikTok Events API request failed")
        return {"platform": "tiktok", "upstream_status": None, "ok": False}


@router.post("/snap")
async def capi_snap(
    body: TrackingEventIn,
    x_capi_secret: str | None = Header(default=None, alias="X-CAPI-Secret"),
) -> dict[str, Any]:
    _require_capi_secret(x_capi_secret)
    pixel_id = os.getenv("SNAP_PIXEL_ID", "").strip()
    token = os.getenv("SNAP_ACCESS_TOKEN", "").strip()
    if not pixel_id or not token:
        raise HTTPException(status_code=503, detail="SNAP_PIXEL_ID or SNAP_ACCESS_TOKEN not configured")

    user_data: dict[str, Any] = {}
    if body.phone_plain:
        h = hash_sa_phone_for_capi(body.phone_plain)
        if h:
            user_data["sha256_phone_number"] = h
    if body.client_ip_address:
        user_data["client_ip_address"] = body.client_ip_address
    if body.client_user_agent:
        user_data["client_user_agent"] = body.client_user_agent

    custom_data: dict[str, Any] = {"currency": body.currency}
    if body.value is not None:
        custom_data["value"] = str(body.value)

    try:
        status, text = await send_snap_web_event(
            pixel_id=pixel_id,
            access_token=token,
            event_name=body.event_name.upper(),
            event_id=body.event_id,
            user_data=user_data,
            custom_data=custom_data,
            event_source_url=body.event_source_url,
        )
        if status >= 400:
            logger.warning("Snapchat CAPI non-success: %s %s", status, text[:500])
        return {"platform": "snap", "upstream_status": status, "ok": status < 400}
    except Exception:
        logger.exception("Snapchat CAPI request failed")
        return {"platform": "snap", "upstream_status": None, "ok": False}
