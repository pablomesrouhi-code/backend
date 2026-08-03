"""HTML admin dashboard + JSON APIs (auth via signed cookie)."""

from __future__ import annotations

import os
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import func, inspect, or_, select
from sqlalchemy.orm import Session, selectinload

from app.admin_session import mint_admin_token, verify_admin_token
from app.deps import get_db
from app.models.analytics_models import AnalyticsEvent
from app.models.order_models import Order, OrderItem, TrackingEvent
from app.services.admin_ads_lab import analyze_ad_run, delete_ad_log, list_ad_logs, save_ad_log
from app.services.admin_brand_day import (
    brand_day_bootstrap,
    delete_brand_day,
    list_brand_days,
    period_resume,
    save_brand_day,
)
from app.services.admin_economics import compute_store_economics, sar_per_usd
from app.services.catalog import resolve_sku
from app.services.cod_network import (
    mark_order_cod_delivery,
    resend_persisted_order_to_cod_network,
    resolve_cod_sku,
)
from app.services.store_settings import get_store_config, save_store_config

router = APIRouter()

_TEMPLATES = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)

COOKIE_NAME = "nbt_admin"
STORE_TZ = ZoneInfo("Asia/Riyadh")


def _public_table_exists(db: Session, table: str) -> bool:
    try:
        bind = db.get_bind()
        return bool(inspect(bind).has_table(table, schema="public"))
    except Exception:
        return False


def _admin_enabled() -> bool:
    return os.getenv("ADMIN_ENABLED", "true").strip().lower() in ("1", "true", "yes")


def _cookie_secure(request: Request | None = None) -> bool:
    """Secure cookie flag.

    **Important:** ``ADMIN_COOKIE_SECURE=true`` over plain HTTP prevents browsers from storing
    the admin session cookie — login appears broken (reload shows login again).

    When unset: ``Secure`` is applied only if the request is HTTPS or ``X-Forwarded-Proto: https``.
    """

    raw = os.getenv("ADMIN_COOKIE_SECURE", "").strip().lower()
    if raw in ("1", "true", "yes"):
        return True
    if raw in ("0", "false", "no"):
        return False
    if request is None:
        return False
    xf = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    if xf == "https":
        return True
    scheme = getattr(request.url, "scheme", "") or ""
    return scheme == "https"


def _parse_day_range(start_s: str, end_s: str) -> tuple[datetime, datetime]:
    """Inclusive calendar-day range [start, end] in Asia/Riyadh → UTC for DB filters."""

    try:
        start_d = date.fromisoformat(start_s.strip())
        end_d = date.fromisoformat(end_s.strip())
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid date format — use YYYY-MM-DD") from e
    if end_d < start_d:
        raise HTTPException(status_code=400, detail="end must be >= start")
    start_dt = datetime(start_d.year, start_d.month, start_d.day, tzinfo=STORE_TZ).astimezone(
        timezone.utc
    )
    end_dt = (
        datetime(end_d.year, end_d.month, end_d.day, tzinfo=STORE_TZ)
        + timedelta(days=1)
    ).astimezone(timezone.utc)
    return start_dt, end_dt


def _today_store() -> str:
    return datetime.now(STORE_TZ).date().isoformat()


def _order_list_item(o: Order) -> dict[str, Any]:
    mm = o.maxmind_risk_score
    mm_f = float(mm) if mm is not None else None
    return {
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
        "cod_network_sent_at": o.cod_network_sent_at.isoformat() if o.cod_network_sent_at else None,
        "cod_network_error": o.cod_network_error,
        "cod_network_lead_id": o.cod_network_lead_id,
    }


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


def _frontend_base_url() -> str:
    return (os.getenv("FRONTEND_URL", "https://nabtalabo.store").strip() or "https://nabtalabo.store").rstrip(
        "/"
    )


def _brand_logo_url() -> str:
    path = (os.getenv("ADMIN_BRAND_LOGO_PATH", "/nabta-lab-brand.png") or "/nabta-lab-brand.png").strip()
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{_frontend_base_url()}{path}"


@router.get("/admin")
def admin_ui(request: Request):
    if not _admin_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    authed = bool(verify_admin_token(request.cookies.get(COOKIE_NAME)))
    # Starlette ≥0.29: TemplateResponse(request, name, context=…) — old (name, dict) breaks prod (500).
    return _TEMPLATES.TemplateResponse(
        request=request,
        name="admin_dashboard.html",
        context={
            "authed": authed,
            "brand_logo_url": _brand_logo_url(),
            "brand_site_url": _frontend_base_url(),
        },
    )


@router.get("/admin/setup-status")
def admin_setup_status(request: Request) -> dict[str, Any]:
    """Anonymous diagnostics — booleans only (no secrets)."""

    xf = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    scheme = getattr(request.url, "scheme", "") or ""
    inferred_https = xf == "https" or scheme == "https"
    cookie_secure_applied = _cookie_secure(request)
    raw_cs = os.getenv("ADMIN_COOKIE_SECURE", "").strip()

    hints: list[str] = []
    if cookie_secure_applied and not inferred_https:
        hints.append(
            "كعكة الجلسة مع Secure على اتصال HTTP غالباً لا تُخزَّن — عيّن ADMIN_COOKIE_SECURE=false أو اتركه فارغاً للتلقائي."
        )
    if not (os.getenv("ADMIN_USERNAME") or "").strip():
        hints.append("ADMIN_USERNAME غير معيّن.")
    if os.getenv("ADMIN_PASSWORD") in (None, ""):
        hints.append("ADMIN_PASSWORD غير معيّن.")
    if not (os.getenv("ADMIN_SESSION_SECRET") or "").strip():
        hints.append("ADMIN_SESSION_SECRET غير معيّن.")

    return {
        "admin_enabled": _admin_enabled(),
        "credentials_username_set": bool((os.getenv("ADMIN_USERNAME") or "").strip()),
        "credentials_password_set": os.getenv("ADMIN_PASSWORD") not in (None, ""),
        "session_secret_set": bool((os.getenv("ADMIN_SESSION_SECRET") or "").strip()),
        "cookie_secure_env_raw": raw_cs or None,
        "cookie_secure_applied": cookie_secure_applied,
        "request_scheme": scheme or None,
        "forwarded_proto": xf or None,
        "hints": hints,
    }


@router.post("/admin/login")
def admin_login(request: Request, body: LoginBody, response: Response):
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
        secure=_cookie_secure(request),
        samesite="lax",
        max_age=43200,
        path="/",
    )
    return {"ok": True}


@router.post("/admin/logout")
def admin_logout(request: Request, response: Response, _: str = Depends(require_admin_user)):
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        secure=_cookie_secure(request),
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
    today = _today_store()
    start_s = start.strip() or today
    end_s = end.strip() or today
    start_dt, end_dt = _parse_day_range(start_s, end_s)

    analytics_ready = _public_table_exists(db, "analytics_events")
    warning: str | None = None
    if not analytics_ready:
        warning = (
            "جدول analytics_events غير موجود — شغّل alembic upgrade head "
            "أو نفّذ backend/scripts/0002_analytics_events.sql على نفس قاعدة DATABASE_URL."
        )
        trusted_views = 0
        total_views = 0
        trusted_unique_ips = 0
    else:
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

    economics = compute_store_economics(db, start_dt=start_dt, end_dt=end_dt)

    out: dict[str, Any] = {
        "range": {"start": start_s, "end": end_s, "timezone": "Asia/Riyadh"},
        "trusted_clicks": int(trusted_views),
        "trusted_unique_ips": int(trusted_unique_ips),
        "total_page_views_recorded": int(total_views),
        "orders": int(orders_count),
        "revenue_sar": rev_int,
        "subtotal_sar": economics["subtotal_sar"],
        "upsell_revenue_sar": economics["upsell_revenue_sar"],
        "aov_sar": economics["aov_sar"],
        "aov_usd": economics["aov_usd"],
        "subtotal_aov_sar": economics["subtotal_aov_sar"],
        "upsell_per_order_sar": economics["upsell_per_order_sar"],
        "selling_price_per_piece_sar": economics["selling_price_per_piece_sar"],
        "selling_price_per_piece_usd": economics["selling_price_per_piece_usd"],
        "realized_avg_per_piece_sar": economics.get("realized_avg_per_piece_sar"),
        "avg_main_pieces_per_order": economics["avg_main_pieces_per_order"],
        "computed_aov_sar": economics["computed_aov_sar"],
        "conversion_rate_percent": conv,
        "upsell_orders": int(upsell_orders),
        "upsell_attach_rate_percent": upsell_rate,
        "sar_per_usd": economics["sar_per_usd"],
        "catalog_selling_prices_sar": economics["catalog_selling_prices_sar"],
        "fixed_costs_usd": economics["fixed_costs_usd"],
        "fixed_costs_sar": economics["fixed_costs_sar"],
        "notes": economics["notes"]
        + " conversion_rate_percent = orders / trusted_clicks (page_view events); "
        "trusted = SA + MaxMind/IPQS analytics rules.",
    }
    if warning is not None:
        out["warning"] = warning
    return out


@router.get("/admin/data/orders/latest")
def admin_orders_latest(
    db: Session = Depends(get_db),
    _: str = Depends(require_admin_user),
    limit: int = 20,
) -> dict[str, Any]:
    """Most recent orders — no date filter (for live dashboard feed)."""
    lim = max(1, min(limit, 100))
    rows = db.scalars(select(Order).order_by(Order.created_at.desc()).limit(lim)).all()
    return {"orders": [_order_list_item(o) for o in rows], "limit": lim}


@router.get("/admin/data/orders")
def admin_orders(
    db: Session = Depends(get_db),
    _: str = Depends(require_admin_user),
    start: str = "",
    end: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    today = _today_store()
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

    return {
        "total": int(total),
        "limit": lim,
        "offset": off,
        "start": start_s,
        "end": end_s,
        "orders": [_order_list_item(o) for o in rows],
    }


def _dec(v: Decimal | None) -> float | None:
    if v is None:
        return None
    return float(v)


def _sar_per_usd() -> float:
    return sar_per_usd()


@router.get("/admin/data/profit-baseline")
def admin_profit_baseline(
    db: Session = Depends(get_db),
    _: str = Depends(require_admin_user),
    start: str = "",
    end: str = "",
) -> dict[str, Any]:
    """Store stats for COD profit calculator — optional date range (Asia/Riyadh)."""

    if start.strip() or end.strip():
        today = _today_store()
        start_s = start.strip() or today
        end_s = end.strip() or today
        start_dt, end_dt = _parse_day_range(start_s, end_s)
        economics = compute_store_economics(db, start_dt=start_dt, end_dt=end_dt)
        economics["range"] = {"start": start_s, "end": end_s, "timezone": "Asia/Riyadh"}
    else:
        economics = compute_store_economics(db)
        economics["range"] = None

    economics["profit_defaults"] = get_store_config(db).get("profit_defaults") or {}

    # Back-compat field names for profit calculator JS
    economics["avg_pieces_per_order"] = economics["avg_main_pieces_per_order"]
    return economics


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
            "cod_network_sent_at": o.cod_network_sent_at.isoformat() if o.cod_network_sent_at else None,
            "cod_network_error": o.cod_network_error,
            "cod_network_lead_id": o.cod_network_lead_id,
        },
        "items": lines,
        "tracking_events": _order_tracking_events(db, oid),
    }


def _order_tracking_events(db: Session, order_id: uuid.UUID) -> list[dict[str, Any]]:
    if not _public_table_exists(db, "tracking_events"):
        return []
    rows = db.scalars(
        select(TrackingEvent)
        .where(TrackingEvent.order_id == order_id)
        .order_by(TrackingEvent.created_at.asc())
    ).all()
    return [
        {
            "id": str(row.id),
            "platform": row.platform,
            "event_name": row.event_name,
            "event_id": row.event_id,
            "response_status": row.response_status,
            "response_body": row.response_body,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


@router.get("/admin/data/capi-events")
def admin_capi_events(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin_user),
) -> dict[str, Any]:
    if not _public_table_exists(db, "tracking_events"):
        return {"events": [], "total": 0}

    lim = max(1, min(limit, 200))
    off = max(0, offset)
    total = int(db.scalar(select(func.count()).select_from(TrackingEvent)) or 0)
    rows = db.scalars(
        select(TrackingEvent)
        .order_by(TrackingEvent.created_at.desc())
        .limit(lim)
        .offset(off)
    ).all()
    events = [
        {
            "id": str(row.id),
            "platform": row.platform,
            "event_name": row.event_name,
            "event_id": row.event_id,
            "order_id": str(row.order_id) if row.order_id else None,
            "response_status": row.response_status,
            "response_body": (row.response_body or "")[:500],
            "payload": row.payload,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]
    return {"events": events, "total": total, "limit": lim, "offset": off}


def _admin_load_order(db: Session, order_id: str) -> Order:
    try:
        oid = uuid.UUID(order_id.strip())
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid order id") from e
    order = db.scalar(
        select(Order).where(Order.id == oid).options(selectinload(Order.items))
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.post("/admin/data/orders/{order_id}/resend-sheet")
def admin_resend_order_sheet(
    order_id: str,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin_user),
) -> dict[str, Any]:
    """Replay one Postgres order row to Google Sheet (admin UI)."""

    order = _admin_load_order(db, order_id)
    try:
        outcome, sheet_err = resend_persisted_order_to_sheet(order)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    mark_order_sheet_delivery(order, outcome, sheet_err)
    try:
        db.commit()
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=503, detail="Failed to persist sheet status") from e
    return {
        "ok": outcome == "ok",
        "outcome": outcome,
        "detail": sheet_err,
        "order_number": order.order_number,
        "order_id": str(order.id),
    }


@router.post("/admin/data/orders/{order_id}/resend-cod")
def admin_resend_order_cod(
    order_id: str,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin_user),
) -> dict[str, Any]:
    """Replay one order to COD Network leads API."""

    order = _admin_load_order(db, order_id)
    try:
        outcome, err, lead_id = resend_persisted_order_to_cod_network(order)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    mark_order_cod_delivery(order, outcome, err, lead_id)
    try:
        db.commit()
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=503, detail="Failed to persist COD status") from e
    return {
        "ok": outcome == "ok",
        "outcome": outcome,
        "detail": err,
        "lead_id": lead_id,
        "order_number": order.order_number,
        "order_id": str(order.id),
        "skus": [resolve_cod_sku(it.product_id) for it in order.items],
    }


@router.get("/admin/data/cod-network/recent")
def admin_cod_network_recent(
    db: Session = Depends(get_db),
    _: str = Depends(require_admin_user),
) -> dict[str, Any]:
    """Last orders with COD Network send status — for debugging failed leads."""

    rows = db.scalars(
        select(Order)
        .options(selectinload(Order.items))
        .order_by(Order.created_at.desc())
        .limit(25)
    ).all()
    out = []
    for o in rows:
        skus = []
        for it in o.items:
            try:
                skus.append(resolve_cod_sku(it.product_id))
            except Exception:
                try:
                    skus.append(resolve_sku(it.product_id))
                except Exception:
                    skus.append(it.product_id)
        out.append(
            {
                "order_number": o.order_number,
                "order_id": str(o.id),
                "created_at": o.created_at.isoformat() if o.created_at else None,
                "cod_network_sent_at": o.cod_network_sent_at.isoformat()
                if o.cod_network_sent_at
                else None,
                "cod_network_lead_id": o.cod_network_lead_id,
                "cod_network_error": o.cod_network_error,
                "skus": skus,
                "ok": bool(o.cod_network_sent_at and not o.cod_network_error),
            }
        )
    return {"ok": True, "orders": out}


class BulkResendBody(BaseModel):
    resend_cod: bool = False


@router.post("/admin/data/orders/resend-failed-sheets")
def admin_resend_failed_sheets(
    body: BulkResendBody,
    start: str = "",
    end: str = "",
    db: Session = Depends(get_db),
    _: str = Depends(require_admin_user),
) -> dict[str, Any]:
    """Resend Sheet rows for orders not successfully delivered in the date range."""

    today = _today_store()
    start_s = start.strip() or today
    end_s = end.strip() or today
    start_dt, end_dt = _parse_day_range(start_s, end_s)

    orders = db.scalars(
        select(Order)
        .where(
            Order.created_at >= start_dt,
            Order.created_at < end_dt,
            or_(Order.sheet_sent_at.is_(None), Order.sheet_error.isnot(None)),
        )
        .options(selectinload(Order.items))
        .order_by(Order.created_at.asc())
    ).all()

    sheet_ok = 0
    sheet_failed = 0
    cod_ok = 0
    cod_failed = 0
    results: list[dict[str, Any]] = []

    for order in orders:
        row: dict[str, Any] = {"order_number": order.order_number, "order_id": str(order.id)}
        try:
            outcome, sheet_err = resend_persisted_order_to_sheet(order)
            mark_order_sheet_delivery(order, outcome, sheet_err)
            row["sheet_outcome"] = outcome
            row["sheet_detail"] = sheet_err
            if outcome == "ok":
                sheet_ok += 1
            else:
                sheet_failed += 1
        except ValueError as e:
            row["sheet_outcome"] = "failed"
            row["sheet_detail"] = str(e)
            sheet_failed += 1

        if body.resend_cod:
            try:
                cod_out, cod_err, lead_id = resend_persisted_order_to_cod_network(order)
                mark_order_cod_delivery(order, cod_out, cod_err, lead_id)
                row["cod_outcome"] = cod_out
                row["cod_detail"] = cod_err
                row["cod_lead_id"] = lead_id
                if cod_out == "ok":
                    cod_ok += 1
                else:
                    cod_failed += 1
            except ValueError as e:
                row["cod_outcome"] = "failed"
                row["cod_detail"] = str(e)
                cod_failed += 1

        results.append(row)

    try:
        db.commit()
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=503, detail="Failed to persist bulk resend results") from e

    return {
        "ok": sheet_failed == 0 and (not body.resend_cod or cod_failed == 0),
        "start": start_s,
        "end": end_s,
        "total": len(orders),
        "sheet_ok": sheet_ok,
        "sheet_failed": sheet_failed,
        "cod_ok": cod_ok if body.resend_cod else None,
        "cod_failed": cod_failed if body.resend_cod else None,
        "results": results,
    }


class StoreSettingsPatch(BaseModel):
    bundle_prices_sar: dict[str, int] | None = None
    upsell_price_sar: int | None = Field(default=None, ge=0, le=9999)
    sar_per_usd: float | None = Field(default=None, gt=0, le=20)
    cod_fees_usd: dict[str, float] | None = None
    profit_defaults: dict[str, float] | None = None


@router.get("/admin/data/store-settings")
def admin_get_store_settings(
    db: Session = Depends(get_db),
    _: str = Depends(require_admin_user),
) -> dict[str, Any]:
    cfg = get_store_config(db)
    bundles = cfg.get("bundle_prices_sar") or {}
    computed_aov = 0.0
    try:
        b1 = float(bundles.get("1", 199))
        upsell = float(cfg.get("upsell_price_sar", 99))
        pd = cfg.get("profit_defaults") or {}
        avg_p = float(pd.get("avg_main_pieces", 1))
        attach = float(pd.get("upsell_attach_pct", 0)) / 100.0
        sell = b1
        computed_aov = avg_p * sell + attach * upsell
    except (TypeError, ValueError):
        computed_aov = float(bundles.get("1", 199))
    return {
        **cfg,
        "computed_aov_sar_hint": round(computed_aov, 2),
        "notes": (
            "Changes apply to checkout immediately. Storefront labels update via /api/pricing. "
            "Env SAR_PER_USD and COD_FEE_* override DB when set in EasyPanel."
        ),
    }


@router.put("/admin/data/store-settings")
def admin_put_store_settings(
    body: StoreSettingsPatch,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin_user),
) -> dict[str, Any]:
    patch = body.model_dump(exclude_none=True)
    if not patch:
        raise HTTPException(status_code=400, detail="No settings provided")
    saved = save_store_config(db, patch)
    return {"ok": True, "config": saved}


class AdsLabAnalyzeBody(BaseModel):
    name: str = Field(default="", max_length=120)
    platform: str = Field(default="meta", max_length=40)
    spend_usd: float | None = Field(default=None, ge=0, le=10_000_000)
    leads: int | None = Field(default=None, ge=0, le=10_000_000)
    days: int | None = Field(default=None, ge=1, le=366)
    clicks: int | None = Field(default=None, ge=0, le=100_000_000)
    impressions: int | None = Field(default=None, ge=0, le=1_000_000_000)
    cpc_usd: float | None = Field(default=None, ge=0, le=1000)
    cpm_usd: float | None = Field(default=None, ge=0, le=10000)
    ctr_pct: float | None = Field(default=None, ge=0, le=100)
    hook_rate_pct: float | None = Field(default=None, ge=0, le=100)
    hold_rate_pct: float | None = Field(default=None, ge=0, le=100)
    frequency: float | None = Field(default=None, ge=0, le=100)
    day_start: str | None = Field(default=None, max_length=32)
    day_end: str | None = Field(default=None, max_length=32)
    notes: str | None = Field(default=None, max_length=500)
    save: bool = False


@router.get("/admin/data/ads-lab")
def admin_ads_lab_list(
    db: Session = Depends(get_db),
    _: str = Depends(require_admin_user),
) -> dict[str, Any]:
    return {
        "logs": list_ad_logs(db),
        "defaults": {},
        "notes": (
            "دخل metrics من Ads Manager: CPC · CTR · CPM · Hook rate · Frequency · Spend. "
            "التحليل كيقول ليك: Winner (خلّيه) · Keep testing · ولا Kill."
        ),
    }


@router.post("/admin/data/ads-lab/analyze")
def admin_ads_lab_analyze(
    body: AdsLabAnalyzeBody,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin_user),
) -> dict[str, Any]:
    has_metric = any(
        v is not None
        for v in (
            body.spend_usd,
            body.cpc_usd,
            body.cpm_usd,
            body.ctr_pct,
            body.hook_rate_pct,
            body.hold_rate_pct,
            body.frequency,
            body.clicks,
            body.impressions,
            body.leads,
        )
    )
    if not has_metric:
        raise HTTPException(status_code=400, detail="enter at least one ad metric")
    analysis = analyze_ad_run(
        db,
        spend_usd=body.spend_usd,
        leads=body.leads,
        days=body.days,
        clicks=body.clicks,
        impressions=body.impressions,
        cpc_usd=body.cpc_usd,
        cpm_usd=body.cpm_usd,
        ctr_pct=body.ctr_pct,
        hook_rate_pct=body.hook_rate_pct,
        hold_rate_pct=body.hold_rate_pct,
        frequency=body.frequency,
        name=body.name,
        platform=body.platform,
        day_start=body.day_start,
        day_end=body.day_end,
    )
    saved_row = None
    if body.save:
        saved_row = save_ad_log(
            db,
            {
                "day_start": body.day_start,
                "day_end": body.day_end,
                "notes": body.notes,
            },
            analysis,
        )
    return {"ok": True, "analysis": analysis, "saved": saved_row}


@router.post("/admin/data/ads-lab/delete")
def admin_ads_lab_delete(
    body: dict[str, Any],
    db: Session = Depends(get_db),
    _: str = Depends(require_admin_user),
) -> dict[str, Any]:
    log_id = str(body.get("id") or "").strip()
    if not log_id:
        raise HTTPException(status_code=400, detail="id required")
    ok = delete_ad_log(db, log_id)
    if not ok:
        raise HTTPException(status_code=404, detail="log not found")
    return {"ok": True, "logs": list_ad_logs(db)}


class BrandDaySaveBody(BaseModel):
    day: str = Field(..., min_length=8, max_length=32)
    creatives: int = Field(default=0, ge=0, le=500)
    steps: dict[str, bool] = Field(default_factory=dict)
    notes: str | None = Field(default=None, max_length=800)
    products: str | None = Field(default=None, max_length=200)


@router.get("/admin/data/brand-day")
def admin_brand_day_get(
    day: str | None = None,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin_user),
) -> dict[str, Any]:
    return brand_day_bootstrap(db, day)


@router.post("/admin/data/brand-day/save")
def admin_brand_day_save(
    body: BrandDaySaveBody,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin_user),
) -> dict[str, Any]:
    try:
        row = save_brand_day(
            db,
            day=body.day,
            creatives=body.creatives,
            steps=body.steps,
            notes=body.notes or "",
            products=body.products or "",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    period = period_resume(db)
    return {
        "ok": True,
        "entry": row,
        "month": period,
        "period": period,
        "logs": list_brand_days(db)[:60],
    }


@router.get("/admin/data/brand-day/month")
def admin_brand_day_month(
    db: Session = Depends(get_db),
    _: str = Depends(require_admin_user),
) -> dict[str, Any]:
    period = period_resume(db)
    return {"ok": True, "month": period, "period": period}


@router.post("/admin/data/brand-day/delete")
def admin_brand_day_delete(
    body: dict[str, Any],
    db: Session = Depends(get_db),
    _: str = Depends(require_admin_user),
) -> dict[str, Any]:
    key = str(body.get("id") or body.get("day") or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="id or day required")
    ok = delete_brand_day(db, key)
    if not ok:
        raise HTTPException(status_code=404, detail="day not found")
    period = period_resume(db)
    return {
        "ok": True,
        "logs": list_brand_days(db)[:60],
        "month": period,
        "period": period,
    }
