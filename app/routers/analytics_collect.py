"""Browser analytics ingest — classified server-side."""

from __future__ import annotations

import logging
import os
import uuid

from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.analytics_models import AnalyticsEvent
from app.request_ip import client_ip
from app.services.ip_qualify import qualify_analytics_ip

router = APIRouter()
logger = logging.getLogger(__name__)


class CollectBody(BaseModel):
    event: str = Field(default="page_view", max_length=64)
    path: str | None = Field(default=None, max_length=4096)
    referrer: str | None = Field(default=None, max_length=4096)


def _ingest_secret_ok(request: Request) -> bool:
    expected = (os.getenv("ANALYTICS_INGEST_SECRET") or "").strip()
    if not expected:
        return True
    got = (request.headers.get("x-analytics-secret") or "").strip()
    return got == expected


def _persist_event(
    *,
    event_type: str,
    path: str | None,
    referrer: str | None,
    ip: str | None,
    ua: str | None,
) -> None:
    q = qualify_analytics_ip(client_ip=ip, user_agent=ua)
    db: Session = SessionLocal()
    try:
        db.add(
            AnalyticsEvent(
                id=uuid.uuid4(),
                event_type=event_type[:64],
                path=path,
                referrer=referrer,
                ip_address=ip,
                user_agent=ua,
                country_iso=q.country_iso,
                mm_risk_score=q.mm_risk_score,
                mm_is_vpn=q.mm_is_vpn,
                mm_is_proxy=q.mm_is_proxy,
                mm_is_tor=q.mm_is_tor,
                mm_is_hosting=q.mm_is_hosting,
                ipqs_vpn=q.ipqs_vpn,
                ipqs_proxy=q.ipqs_proxy,
                ipqs_tor=q.ipqs_tor,
                counts_as_trusted=q.counts_as_trusted,
                raw_flags=q.raw_flags,
            )
        )
        db.commit()
    except Exception:
        logger.exception("[analytics] persist_failed path=%s", path)
        db.rollback()
    finally:
        db.close()


@router.post("/analytics/collect", status_code=204)
def collect(
    body: CollectBody,
    request: Request,
    background_tasks: BackgroundTasks,
) -> None:
    if not _ingest_secret_ok(request):
        return None
    ip = client_ip(request)
    ua = request.headers.get("user-agent")
    background_tasks.add_task(
        _persist_event,
        event_type=body.event.strip() or "page_view",
        path=body.path,
        referrer=body.referrer,
        ip=ip,
        ua=ua,
    )
    return None
