"""Meta Graph Conversions API (server-side)."""

from __future__ import annotations

import time
from typing import Any

import httpx

GRAPH_API_VERSION = "v21.0"


async def send_meta_web_event(
    *,
    pixel_id: str,
    access_token: str,
    event_name: str,
    event_id: str,
    user_data: dict[str, Any],
    custom_data: dict[str, Any],
    event_source_url: str | None = None,
    action_source: str = "website",
    event_time: int | None = None,
) -> tuple[int, str]:
    row: dict[str, Any] = {
        "event_name": event_name,
        "event_time": int(event_time or time.time()),
        "event_id": event_id,
        "action_source": action_source,
        "user_data": user_data,
        "custom_data": custom_data,
    }
    if event_source_url:
        row["event_source_url"] = event_source_url

    payload = {"data": [row]}
    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{pixel_id}/events"

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(url, params={"access_token": access_token}, json=payload)
        return response.status_code, response.text
