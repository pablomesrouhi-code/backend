"""`/api/sheet-webhook-status` plus optional `/sheet-webhook-status` alias."""

from __future__ import annotations

import os

from fastapi import APIRouter
from pydantic import BaseModel

from app.services.sheet_webhook import _webhook_url_from_env

router = APIRouter()


class SheetWebhookStatus(BaseModel):
    configured: bool
    app_env: str
    hint: str


def _sheet_status_response() -> SheetWebhookStatus:
    ae = (os.getenv("APP_ENV") or "").strip() or "(unset)"
    return SheetWebhookStatus(
        configured=bool(_webhook_url_from_env()),
        app_env=ae,
        hint="If configured is false: add GOOGLE_SHEET_WEBHOOK_URL or SHEET_WEBHOOK_URL to THIS API service in EasyPanel and restart. If true: open orders.sheet_error in Postgres after a test order, and check API logs for SHEET_ENQUEUED → SEND_DONE.",
    )


@router.get("/sheet-webhook-status", response_model=SheetWebhookStatus)
def sheet_webhook_status() -> SheetWebhookStatus:
    """Mounted under ``/api`` in ``main`` → `/api/sheet-webhook-status`."""

    return _sheet_status_response()


def sheet_webhook_status_root() -> SheetWebhookStatus:
    """Mounted at `/sheet-webhook-status` on app (outside `/api`)."""

    return _sheet_status_response()

