"""HTML admin dashboard + JSON APIs (auth via signed cookie)."""

from __future__ import annotations

import os
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.admin_session import mint_admin_token, verify_admin_token
from app.deps import get_db
from app.models.analytics_models import AnalyticsEvent
from app.models.order_models import Order, OrderItem

router = APIRouter()

_TEMPLATES = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)

COOKIE_NAME = "nbt_admin"


def _admin_enabled() -> bool:
    return os.getenv("ADMIN_ENABLED", "true").strip().lower() in ("1", "true", "yes")


def _cookie_secure() -> bool:
    return os.getenv("ADMIN_COOKIE_SECURE", "").strip().lower() in ("1", "true", "yes")


def _parse_day_range(start_s: str, end_s: str) -> tuple[datetime, datetime]:
    """Inclusive calendar-day range [start, end] interpreted as UTC boundaries."""

    try:
        start_d = date.fromisoformat(start_s.strip())
        end_d = date.fromisoformat(end_s.strip())
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid date format — use YYYY-MM-DD") from e
    if end_d < start_d:
        raise HTTPException(status_code=400, detail="end must be >= start")
    start_dt = datetime(start_d.year, start_d.month, start_d.day, tzinfo=timezone.utc)
    end_dt = datetime(end_d.year, end_d.month, end_d.day, tzinfo=timezone.utc) + timedelta(days=1)
    return start_dt, end_dt


def require_admin_user(request: Request) -> str:
    if not _admin_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    user = verify_admin_token(request.cookies.get(COOKIE_NAME))
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


@router.get("/admin")
def admin_ui(request: Request):
    if not _admin_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    authed = bool(verify_admin_token(request.cookies.get(COOKIE_NAME)))
    return _TEMPLATES.TemplateResponse(
        "admin_dashboard.html",
        {"request": request, "authed": authed},
    )


@router.post("/admin/login")
def admin_login(body: LoginBody, response: Response):
    if not _admin_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    exp_user = (os.getenv("ADMIN_USERNAME") or "").strip()
    exp_pass = os.getenv("ADMIN_PASSWORD") or ""
    if not exp_user or exp_pass == "":
        raise HTTPException(status_code=503, detail="Admin credentials not configured")
    ok_u = secrets.compare_digest(body.username.strip(), exp_user)
    ok_p = secrets.compare_digest(body.password, exp_pass)
    if not (ok_u and ok_p):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    try:
        token = mint_admin_token(username=exp_user)
    except RuntimeError:
        raise HTTPException(
            status_code=503,
            detail="ADMIN_SESSION_SECRET missing — cannot mint session",
        ) from None
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        max_age=43200,
        path="/",
    )
    return {"ok": True}


@router.post("/admin/logout")
def admin_logout(response: Response, _: str = Depends(require_admin_user)):
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        secure=_cookie_secure(),
        httponly=True,
        samesite="lax",
    )
    return {"ok": True}


@router.get("/admin/data/metrics")
def admin_metrics(
    db: Session = Depends(get_db),
    _: str = Depends(require_admin_user),
    start: str = "",
    end: str = "",
) -> dict[str, Any]:
    today = datetime.now(timezone.utc).date().isoformat()
    start_s = start.strip() or today
    end_s = end.strip() or today
    start_dt, end_dt = _parse_day_range(start_s, end_s)

    trusted_views = db.scalar(
        select(func.count())
        .select_from(AnalyticsEvent)
        .where(
            AnalyticsEvent.created_at >= start_dt,
            AnalyticsEvent.created_at < end_dt,
            AnalyticsEvent.event_type == "page_view",
            AnalyticsEvent.counts_as_trusted.is_(True),
        )
    ) or 0

    total_views = db.scalar(
        select(func.count())
        .select_from(AnalyticsEvent)
        .where(
            AnalyticsEvent.created_at >= start_dt,
            AnalyticsEvent.created_at < end_dt,
            AnalyticsEvent.event_type == "page_view",
        )
    ) or 0

    trusted_unique_ips = db.scalar(
        select(func.count(func.distinct(AnalyticsEvent.ip_address)))
        .select_from(AnalyticsEvent)
        .where(
            AnalyticsEvent.created_at >= start_dt,
            AnalyticsEvent.created_at < end_dt,
            AnalyticsEvent.event_type == "page_view",
            AnalyticsEvent.counts_as_trusted.is_(True),
            AnalyticsEvent.ip_address.is_not(None),
        )
    ) or 0

    orders_count = db.scalar(
        select(func.count())
        .select_from(Order)
        .where(Order.created_at >= start_dt, Order.created_at < end_dt)
    ) or 0

    revenue = db.scalar(
        select(func.coalesce(func.sum(Order.total_sar), 0)).where(
            Order.created_at >= start_dt, Order.created_at < end_dt
        )
    )
    rev_int = int(revenue or 0)
    aov = round(rev_int / orders_count, 2) if orders_count else 0.0

    conv = None
    if trusted_views > 0:
        conv = round(100.0 * float(orders_count) / float(trusted_views), 3)

    upsell_orders = db.scalar(
        select(func.count())
        .select_from(Order)
        .where(
            Order.created_at >= start_dt,
            Order.created_at < end_dt,
            Order.accepted_upsell.is_(True),
        )
    ) or 0

    upsell_rate = None
    if orders_count > 0:
        upsell_rate = round(100.0 * float(upsell_orders) / float(orders_count), 3)

    return {
        "range": {"start": start_s, "end": end_s, "timezone": "UTC"},
        "trusted_clicks": int(trusted_views),
        "trusted_unique_ips": int(trusted_unique_ips),
        "total_page_views_recorded": int(total_views),
        "orders": int(orders_count),
        "revenue_sar": rev_int,
        "aov_sar": aov,
        "conversion_rate_percent": conv,
        "upsell_orders": int(upsell_orders),
        "upsell_attach_rate_percent": upsell_rate,
        "notes": (
            "conversion_rate_percent = orders / trusted_clicks (page_view events); "
            "trusted = SA + MaxMind/IPQS analytics rules."
        ),
    }


@router.get("/admin/data/orders")
def admin_orders(
    db: Session = Depends(get_db),
    _: str = Depends(require_admin_user),
    start: str = "",
    end: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    today = datetime.now(timezone.utc).date().isoformat()
    start_s = start.strip() or today
    end_s = end.strip() or today
    start_dt, end_dt = _parse_day_range(start_s, end_s)
    lim = max(1, min(limit, 200))
    off = max(0, offset)

    q = (
        select(Order)
        .where(Order.created_at >= start_dt, Order.created_at < end_dt)
        .order_by(Order.created_at.desc())
        .offset(off)
        .limit(lim)
    )
    rows = db.scalars(q).all()
    total = db.scalar(
        select(func.count())
        .select_from(Order)
        .where(Order.created_at >= start_dt, Order.created_at < end_dt)
    ) or 0

    out: list[dict[str, Any]] = []
    for o in rows:
        mm = o.maxmind_risk_score
        mm_f = float(mm) if mm is not None else None
        out.append(
            {
                "id": str(o.id),
                "order_number": o.order_number,
                "created_at": o.created_at.isoformat() if o.created_at else None,
                "customer_name": o.customer_name,
                "phone_local": o.phone_local,
                "total_sar": o.total_sar,
                "status": o.status,
                "accepted_upsell": o.accepted_upsell,
                "source_page": o.source_page,
                "maxmind_country_iso": o.maxmind_country_iso,
                "maxmind_risk_score": mm_f,
                "sheet_sent_at": o.sheet_sent_at.isoformat() if o.sheet_sent_at else None,
                "sheet_error": o.sheet_error,
            }
        )
    return {"total": int(total), "limit": lim, "offset": off, "orders": out}


def _dec(v: Decimal | None) -> float | None:
    if v is None:
        return None
    return float(v)


@router.get("/admin/data/orders/{order_id}")
def admin_order_detail(
    order_id: str,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin_user),
) -> dict[str, Any]:
    try:
        oid = uuid.UUID(order_id.strip())
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid order id") from e
    o = db.get(Order, oid)
    if o is None:
        raise HTTPException(status_code=404, detail="Order not found")
    items = db.scalars(
        select(OrderItem).where(OrderItem.order_id == oid).order_by(OrderItem.created_at.asc())
    ).all()
    lines = [
        {
            "product_id": it.product_id,
            "product_name_ar": it.product_name_ar,
            "product_name_en": it.product_name_en,
            "item_type": it.item_type,
            "offer_qty": it.offer_qty,
            "unit_price_sar": it.unit_price_sar,
            "line_total_sar": it.line_total_sar,
        }
        for it in items
    ]
    return {
        "order": {
            "id": str(o.id),
            "order_number": o.order_number,
            "created_at": o.created_at.isoformat() if o.created_at else None,
            "updated_at": o.updated_at.isoformat() if o.updated_at else None,
            "customer_name": o.customer_name,
            "phone_local": o.phone_local,
            "phone_e164": o.phone_e164,
            "phone_digits": o.phone_digits,
            "status": o.status,
            "subtotal_sar": o.subtotal_sar,
            "upsell_total_sar": o.upsell_total_sar,
            "total_sar": o.total_sar,
            "currency": o.currency,
            "accepted_upsell": o.accepted_upsell,
            "upsell_product_id": o.upsell_product_id,
            "source_page": o.source_page,
            "client_event_id": o.client_event_id,
            "purchase_event_id": o.purchase_event_id,
            "ip_address": o.ip_address,
            "user_agent": o.user_agent,
            "maxmind_country_iso": o.maxmind_country_iso,
            "maxmind_risk_score": _dec(o.maxmind_risk_score),
            "maxmind_is_vpn": o.maxmind_is_vpn,
            "maxmind_is_proxy": o.maxmind_is_proxy,
            "maxmind_is_tor": o.maxmind_is_tor,
            "maxmind_is_hosting": o.maxmind_is_hosting,
            "sheet_sent_at": o.sheet_sent_at.isoformat() if o.sheet_sent_at else None,
            "sheet_error": o.sheet_error,
        },
        "items": lines,
    }
