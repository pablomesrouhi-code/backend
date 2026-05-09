"""TikTok Events API (server-side). Payload shape follows Business API v1.3 batch track."""

from __future__ import annotations

import time
from typing import Any

import httpx

TIKTOK_TRACK_URL = "https://business-api.tiktok.com/open_api/v1.3/event/track/"


async def send_tiktok_web_event(
    *,
    pixel_code: str,
    access_token: str,
    event_name: str,
    event_id: str,
    properties: dict[str, Any],
    user: dict[str, Any],
    event_time: int | None = None,
) -> tuple[int, str]:
    payload = {
        "event_source": "web",
        "event_source_id": pixel_code,
        "data": [
            {
                "event": event_name,
                "event_time": int(event_time or time.time()),
                "event_id": event_id,
                "properties": properties,
                "user": user,
            }
        ],
    }
    headers = {"Access-Token": access_token, "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(TIKTOK_TRACK_URL, headers=headers, json=payload)
        return response.status_code, response.text
