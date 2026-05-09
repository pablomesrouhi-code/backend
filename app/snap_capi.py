"""Snapchat Conversions API v3 (server-side)."""

from __future__ import annotations

import time
from typing import Any

import httpx


async def send_snap_web_event(
    *,
    pixel_id: str,
    access_token: str,
    event_name: str,
    event_id: str,
    user_data: dict[str, Any],
    custom_data: dict[str, Any],
    event_source_url: str | None = None,
    action_source: str = "WEB",
    event_time_ms: int | None = None,
) -> tuple[int, str]:
    evt: dict[str, Any] = {
        "event_name": event_name,
        "event_time": int(event_time_ms or time.time() * 1000),
        "event_id": event_id,
        "action_source": action_source,
        "user_data": user_data,
        "custom_data": custom_data,
    }
    if event_source_url:
        evt["event_source_url"] = event_source_url

    payload = {"data": [evt]}
    url = f"https://tr.snapchat.com/v3/{pixel_id}/events"

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(url, params={"access_token": access_token}, json=payload)
        return response.status_code, response.text
