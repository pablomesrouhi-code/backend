"""Dispatch Meta/TikTok/Snap CAPI after orders; persist rows to tracking_events."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.meta_capi import send_meta_web_event
from app.models.order_models import TrackingEvent
from app.phone_hash import hash_sa_phone_for_capi
from app.snap_capi import send_snap_web_event
from app.tiktok_capi import send_tiktok_web_event

logger = logging.getLogger(__name__)

TIKTOK_PURCHASE = "Purchase"
TIKTOK_LEAD = "Lead"
SNAP_PURCHASE = "PURCHASE"
SNAP_LEAD = "SIGN_UP"


def _tracking_enabled() -> bool:
    raw = os.getenv("TRACKING_ENABLED", "true").strip().lower()
    return raw not in ("0", "false", "no")


async def _skipped_coro() -> tuple[int, str]:
    return 503, "skipped: platform not configured"


def _tiktok_pixel_code() -> str:
    return (
        os.getenv("TIKTOK_PIXEL_CODE", "").strip()
        or os.getenv("TIKTOK_PIXEL_ID", "").strip()
        or os.getenv("NEXT_PUBLIC_TIKTOK_PIXEL_ID", "").strip()
    )


def _build_user_match(
    *,
    phone_plain: str,
    client_ip: str | None,
    user_agent: str | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Return (meta_user_data, tiktok_user, snap_user_data)."""
    meta_user: dict[str, Any] = {}
    tiktok_user: dict[str, Any] = {}
    snap_user: dict[str, Any] = {}

    phone_hash = hash_sa_phone_for_capi(phone_plain)
    if phone_hash:
        meta_user["ph"] = [phone_hash]
        tiktok_user["phone"] = phone_hash
        # Snap CAPI v3 user_data field is `ph` (SHA256, normalized digits).
        snap_user["ph"] = phone_hash

    if client_ip:
        meta_user["client_ip_address"] = client_ip
        tiktok_user["ip"] = client_ip
        snap_user["client_ip_address"] = client_ip

    if user_agent:
        meta_user["client_user_agent"] = user_agent
        tiktok_user["user_agent"] = user_agent
        snap_user["client_user_agent"] = user_agent

    return meta_user, tiktok_user, snap_user


def _persist_tracking_event(
    db: Session,
    *,
    platform: str,
    event_name: str,
    event_id: str,
    order_id: uuid.UUID | None,
    payload: dict[str, Any],
    status: int | None,
    body: str | None,
) -> None:
    try:
        row = TrackingEvent(
            event_name=event_name,
            event_id=event_id,
            platform=platform,
            order_id=order_id,
            payload=payload,
            response_status=status,
            response_body=(body or "")[:4000] if body else None,
        )
        db.add(row)
        db.commit()
    except Exception:
        logger.exception(
            "[capi] failed to persist tracking_events row platform=%s event=%s",
            platform,
            event_name,
        )
        db.rollback()


async def _send_platform_event(
    *,
    platform: str,
    event_name: str,
    event_id: str,
    order_id: uuid.UUID | None,
    payload: dict[str, Any],
    coro,
) -> None:
    db = SessionLocal()
    status: int | None = None
    body: str | None = None
    try:
        status, body = await coro
        ok = status is not None and status < 400
        logger.info(
            "[capi] %s %s event_id=%s order_id=%s status=%s ok=%s",
            platform,
            event_name,
            event_id,
            order_id,
            status,
            ok,
        )
        if not ok:
            logger.warning(
                "[capi] %s %s non-success status=%s body=%s",
                platform,
                event_name,
                status,
                (body or "")[:800],
            )
    except Exception:
        logger.exception(
            "[capi] %s %s failed event_id=%s order_id=%s",
            platform,
            event_name,
            event_id,
            order_id,
        )
    finally:
        try:
            _persist_tracking_event(
                db,
                platform=platform,
                event_name=event_name,
                event_id=event_id,
                order_id=order_id,
                payload=payload,
                status=status,
                body=body,
            )
        except Exception:
            logger.exception("[capi] failed to persist tracking_events row")
            db.rollback()
        finally:
            db.close()


async def send_meta_capi_event(
    *,
    event_name: str,
    event_id: str,
    order_id: uuid.UUID | None,
    order_number: str | None = None,
    phone_plain: str,
    client_ip: str | None,
    user_agent: str | None,
    value: float,
    content_ids: list[str],
    source_url: str | None,
) -> None:
    pixel_id = os.getenv("META_PIXEL_ID", "").strip()
    token = os.getenv("META_CAPI_ACCESS_TOKEN", "").strip()
    if not pixel_id or not token:
        logger.warning("[capi] meta skipped — META_PIXEL_ID or META_CAPI_ACCESS_TOKEN missing")
        await _send_platform_event(
            platform="meta",
            event_name=event_name,
            event_id=event_id,
            order_id=order_id,
            payload={"skipped": True, "reason": "missing META_PIXEL_ID or META_CAPI_ACCESS_TOKEN"},
            coro=_skipped_coro(),
        )
        return

    meta_user, _, _ = _build_user_match(
        phone_plain=phone_plain,
        client_ip=client_ip,
        user_agent=user_agent,
    )
    value_out = round(max(0.0, float(value)), 2)
    custom_data: dict[str, Any] = {
        "currency": "SAR",
        "value": value_out,
        "content_type": "product",
        "content_ids": content_ids,
        "contents": [{"id": cid, "quantity": 1} for cid in content_ids],
    }
    if event_name == "Purchase" and order_number:
        custom_data["order_id"] = order_number
    payload = {
        "event_name": event_name,
        "event_id": event_id,
        "user_data": meta_user,
        "custom_data": custom_data,
        "event_source_url": source_url,
    }

    await _send_platform_event(
        platform="meta",
        event_name=event_name,
        event_id=event_id,
        order_id=order_id,
        payload=payload,
        coro=send_meta_web_event(
            pixel_id=pixel_id,
            access_token=token,
            event_name=event_name,
            event_id=event_id,
            user_data=meta_user,
            custom_data=custom_data,
            event_source_url=source_url,
        ),
    )


async def send_tiktok_capi_event(
    *,
    event_name: str,
    event_id: str,
    order_id: uuid.UUID | None,
    order_number: str | None = None,
    phone_plain: str,
    client_ip: str | None,
    user_agent: str | None,
    value: float,
    content_ids: list[str],
    source_url: str | None,
) -> None:
    pixel_code = _tiktok_pixel_code()
    token = os.getenv("TIKTOK_ACCESS_TOKEN", "").strip()
    if not pixel_code or not token:
        logger.warning("[capi] tiktok skipped — TIKTOK_PIXEL_CODE or TIKTOK_ACCESS_TOKEN missing")
        await _send_platform_event(
            platform="tiktok",
            event_name=event_name,
            event_id=event_id,
            order_id=order_id,
            payload={"skipped": True, "reason": "missing TIKTOK_PIXEL_CODE or TIKTOK_ACCESS_TOKEN"},
            coro=_skipped_coro(),
        )
        return

    _, tiktok_user, _ = _build_user_match(
        phone_plain=phone_plain,
        client_ip=client_ip,
        user_agent=user_agent,
    )
    properties: dict[str, Any] = {
        "currency": "SAR",
        "value": value,
        "content_type": "product",
        "content_ids": content_ids,
        "contents": [
            {"content_id": cid, "content_type": "product"} for cid in content_ids
        ],
        "quantity": len(content_ids),
    }
    if content_ids:
        properties["content_id"] = content_ids[0]
    if event_name == TIKTOK_PURCHASE and order_number:
        properties["order_id"] = order_number
    page = {"url": source_url} if source_url else None
    payload = {
        "event": event_name,
        "event_id": event_id,
        "properties": properties,
        "user": tiktok_user,
        "page": page,
    }

    await _send_platform_event(
        platform="tiktok",
        event_name=event_name,
        event_id=event_id,
        order_id=order_id,
        payload=payload,
        coro=send_tiktok_web_event(
            pixel_code=pixel_code,
            access_token=token,
            event_name=event_name,
            event_id=event_id,
            properties=properties,
            user=tiktok_user,
            page=page,
        ),
    )


async def send_snap_capi_event(
    *,
    event_name: str,
    event_id: str,
    order_id: uuid.UUID | None,
    order_number: str | None,
    phone_plain: str,
    client_ip: str | None,
    user_agent: str | None,
    value: float,
    content_ids: list[str],
    source_url: str | None,
) -> None:
    pixel_id = os.getenv("SNAP_PIXEL_ID", "").strip()
    token = os.getenv("SNAP_ACCESS_TOKEN", "").strip()
    if not pixel_id or not token:
        logger.warning("[capi] snap skipped — SNAP_PIXEL_ID or SNAP_ACCESS_TOKEN missing")
        await _send_platform_event(
            platform="snap",
            event_name=event_name,
            event_id=event_id,
            order_id=order_id,
            payload={"skipped": True, "reason": "missing SNAP_PIXEL_ID or SNAP_ACCESS_TOKEN"},
            coro=_skipped_coro(),
        )
        return

    _, _, snap_user = _build_user_match(
        phone_plain=phone_plain,
        client_ip=client_ip,
        user_agent=user_agent,
    )
    custom_data: dict[str, Any] = {
        "currency": "SAR",
        "value": str(value),
        "content_ids": content_ids,
        "number_items": str(len(content_ids)),
    }
    if event_name == SNAP_PURCHASE and order_number:
        custom_data["order_id"] = order_number

    payload = {
        "event_name": event_name,
        "event_id": event_id,
        "user_data": snap_user,
        "custom_data": custom_data,
        "event_source_url": source_url,
    }

    await _send_platform_event(
        platform="snap",
        event_name=event_name,
        event_id=event_id,
        order_id=order_id,
        payload=payload,
        coro=send_snap_web_event(
            pixel_id=pixel_id,
            access_token=token,
            event_name=event_name,
            event_id=event_id,
            user_data=snap_user,
            custom_data=custom_data,
            event_source_url=source_url,
        ),
    )


async def dispatch_order_purchase_capi_events(
    *,
    order_id: uuid.UUID,
    order_number: str,
    phone_plain: str,
    client_ip: str | None,
    user_agent: str | None,
    value: float,
    content_ids: list[str],
    source_url: str | None,
    purchase_event_id: str | None,
) -> None:
    """TikTok/Snap Purchase after order save. Meta Purchase waits for thank-you."""

    if not _tracking_enabled():
        logger.info("[capi] skipped — TRACKING_ENABLED=false")
        return

    purchase_eid = (purchase_event_id or "").strip() or str(uuid.uuid4())
    thank_you_url = source_url or "https://nabtalabo.store/thank-you"

    logger.info(
        "[capi] purchase_dispatch_no_meta order_id=%s order_number=%s purchase_event_id=%s content_ids=%s value=%s",
        order_id,
        order_number,
        purchase_eid,
        content_ids,
        value,
    )

    results = await asyncio.gather(
        send_tiktok_capi_event(
            event_name=TIKTOK_PURCHASE,
            event_id=purchase_eid,
            order_id=order_id,
            order_number=order_number,
            phone_plain=phone_plain,
            client_ip=client_ip,
            user_agent=user_agent,
            value=value,
            content_ids=content_ids,
            source_url=thank_you_url,
        ),
        send_snap_capi_event(
            event_name=SNAP_PURCHASE,
            event_id=purchase_eid,
            order_id=order_id,
            order_number=order_number,
            phone_plain=phone_plain,
            client_ip=client_ip,
            user_agent=user_agent,
            value=value,
            content_ids=content_ids,
            source_url=thank_you_url,
        ),
        return_exceptions=True,
    )
    for result in results:
        if isinstance(result, Exception):
            logger.error("[capi] purchase dispatch task failed: %s", result)


async def dispatch_thank_you_meta_purchase_capi(
    *,
    order_id: uuid.UUID,
    order_number: str,
    phone_plain: str,
    client_ip: str | None,
    user_agent: str | None,
    value: float,
    content_ids: list[str],
    purchase_event_id: str,
) -> None:
    """Meta Purchase CAPI — thank-you only after the order exists in DB."""

    if not _tracking_enabled():
        return

    purchase_eid = purchase_event_id.strip()
    if not purchase_eid:
        return

    await send_meta_capi_event(
        event_name="Purchase",
        event_id=purchase_eid,
        order_id=order_id,
        order_number=order_number,
        phone_plain=phone_plain,
        client_ip=client_ip,
        user_agent=user_agent,
        value=value,
        content_ids=content_ids,
        source_url="https://nabtalabo.store/thank-you",
    )


async def dispatch_thank_you_lead_capi_events(
    *,
    order_id: uuid.UUID,
    order_number: str,
    phone_plain: str,
    client_ip: str | None,
    user_agent: str | None,
    value: float,
    content_ids: list[str],
    lead_event_id: str,
) -> None:
    """Lead CAPI — only after thank-you page (matches browser `trackLead`)."""

    if not _tracking_enabled():
        logger.info("[capi] lead skipped — TRACKING_ENABLED=false")
        return

    lead_eid = lead_event_id.strip()
    if not lead_eid:
        logger.warning("[capi] lead skipped — empty lead_event_id order_id=%s", order_id)
        return

    thank_you_url = "https://nabtalabo.store/thank-you"

    logger.info(
        "[capi] lead_dispatch order_id=%s order_number=%s lead_event_id=%s content_ids=%s value=%s",
        order_id,
        order_number,
        lead_eid,
        content_ids,
        value,
    )

    results = await asyncio.gather(
        send_meta_capi_event(
            event_name="Lead",
            event_id=lead_eid,
            order_id=order_id,
            phone_plain=phone_plain,
            client_ip=client_ip,
            user_agent=user_agent,
            value=value,
            content_ids=content_ids,
            source_url=thank_you_url,
        ),
        send_tiktok_capi_event(
            event_name=TIKTOK_LEAD,
            event_id=lead_eid,
            order_id=order_id,
            phone_plain=phone_plain,
            client_ip=client_ip,
            user_agent=user_agent,
            value=value,
            content_ids=content_ids,
            source_url=thank_you_url,
        ),
        send_snap_capi_event(
            event_name=SNAP_LEAD,
            event_id=lead_eid,
            order_id=order_id,
            order_number=order_number,
            phone_plain=phone_plain,
            client_ip=client_ip,
            user_agent=user_agent,
            value=value,
            content_ids=content_ids,
            source_url=thank_you_url,
        ),
        return_exceptions=True,
    )
    for result in results:
        if isinstance(result, Exception):
            logger.error("[capi] lead dispatch task failed: %s", result)


# Back-compat alias (order router import).
async def dispatch_order_capi_events(
    *,
    order_id: uuid.UUID,
    order_number: str,
    phone_plain: str,
    client_ip: str | None,
    user_agent: str | None,
    value: float,
    content_ids: list[str],
    source_url: str | None,
    purchase_event_id: str | None,
    lead_event_id: str | None = None,
) -> None:
    del lead_event_id
    await dispatch_order_purchase_capi_events(
        order_id=order_id,
        order_number=order_number,
        phone_plain=phone_plain,
        client_ip=client_ip,
        user_agent=user_agent,
        value=value,
        content_ids=content_ids,
        source_url=source_url,
        purchase_event_id=purchase_event_id,
    )
