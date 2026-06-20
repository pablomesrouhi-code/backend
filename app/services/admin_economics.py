"""Store economics for admin dashboard — AOV, selling price, COD Network ops fees."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.order_models import Order, OrderItem
from app.services.pricing import BUNDLE_PRICES_SAR, UPSELL_PRICE_SAR

_DEFAULT_COD_FEES_USD: dict[str, float] = {
    # COD Network KSA seller ops (USD) — override via env to match your agreement.
    "per_confirmed_lead": 1.7,
    "per_delivered_order": 4.0,
    "per_return_order": 1.3,
    "per_fulfilled_shipment": 0.8,
}


def _env_float(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        v = float(raw)
        return v if v >= 0 else default
    except ValueError:
        return default


def sar_per_usd() -> float:
    raw = (os.getenv("SAR_PER_USD") or "3.75").strip()
    try:
        v = float(raw)
        return v if v > 0 else 3.75
    except ValueError:
        return 3.75


def cod_ops_fees_usd() -> dict[str, float]:
    return {
        "per_confirmed_lead": _env_float(
            "COD_FEE_CONFIRMATION_USD", _DEFAULT_COD_FEES_USD["per_confirmed_lead"]
        ),
        "per_delivered_order": _env_float(
            "COD_FEE_DELIVERY_USD", _DEFAULT_COD_FEES_USD["per_delivered_order"]
        ),
        "per_return_order": _env_float(
            "COD_FEE_RETURN_USD", _DEFAULT_COD_FEES_USD["per_return_order"]
        ),
        "per_fulfilled_shipment": _env_float(
            "COD_FEE_WAREHOUSE_USD", _DEFAULT_COD_FEES_USD["per_fulfilled_shipment"]
        ),
    }


def cod_ops_fees_sar(rate: float | None = None) -> dict[str, float]:
    fx = rate if rate and rate > 0 else sar_per_usd()
    usd = cod_ops_fees_usd()
    return {k: round(v * fx, 2) for k, v in usd.items()}


def catalog_selling_prices_sar() -> dict[int, float]:
    """List selling price per piece for each bundle tier (199 / 279 / 349)."""

    return {qty: round(BUNDLE_PRICES_SAR[qty] / qty, 2) for qty in sorted(BUNDLE_PRICES_SAR)}


def _order_filters(start_dt: datetime | None, end_dt: datetime | None) -> list[Any]:
    clauses: list[Any] = []
    if start_dt is not None:
        clauses.append(Order.created_at >= start_dt)
    if end_dt is not None:
        clauses.append(Order.created_at < end_dt)
    return clauses


def compute_store_economics(
    db: Session,
    *,
    start_dt: datetime | None = None,
    end_dt: datetime | None = None,
) -> dict[str, Any]:
    """Aggregate order economics for admin KPIs and profit calculator."""

    rate = sar_per_usd()
    filters = _order_filters(start_dt, end_dt)

    def _where(base):
        return base.where(*filters) if filters else base

    orders_count = int(db.scalar(_where(select(func.count()).select_from(Order))) or 0)
    revenue_sar = int(
        db.scalar(_where(select(func.coalesce(func.sum(Order.total_sar), 0)))) or 0
    )
    subtotal_sar = int(
        db.scalar(_where(select(func.coalesce(func.sum(Order.subtotal_sar), 0)))) or 0
    )
    upsell_revenue_sar = int(
        db.scalar(_where(select(func.coalesce(func.sum(Order.upsell_total_sar), 0)))) or 0
    )

    upsell_orders = int(
        db.scalar(
            _where(
                select(func.count())
                .select_from(Order)
                .where(Order.accepted_upsell.is_(True))
            )
        )
        or 0
    )

    main_pieces_subq = (
        select(
            OrderItem.order_id.label("order_id"),
            func.sum(OrderItem.offer_qty).label("main_pieces"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .where(OrderItem.item_type == "original")
    )
    if filters:
        main_pieces_subq = main_pieces_subq.where(*filters)
    main_pieces_subq = main_pieces_subq.group_by(OrderItem.order_id).subquery()

    avg_main_pieces_raw = db.scalar(select(func.avg(main_pieces_subq.c.main_pieces)))
    avg_main_pieces = round(float(avg_main_pieces_raw or 0), 3) if orders_count else 0.0
    total_main_pieces = int(
        db.scalar(select(func.coalesce(func.sum(main_pieces_subq.c.main_pieces), 0))) or 0
    )

    aov_sar = round(revenue_sar / orders_count, 2) if orders_count else 0.0
    subtotal_aov_sar = round(subtotal_sar / orders_count, 2) if orders_count else 0.0
    upsell_per_order_sar = round(upsell_revenue_sar / orders_count, 2) if orders_count else 0.0
    upsell_attach_rate = round(upsell_orders / orders_count, 4) if orders_count else 0.0

    selling_price_sar = (
        round(subtotal_sar / total_main_pieces, 2) if total_main_pieces > 0 else 0.0
    )
    selling_price_usd = round(selling_price_sar / rate, 2) if selling_price_sar > 0 and rate > 0 else 0.0
    upsell_price_usd = round(UPSELL_PRICE_SAR / rate, 2) if rate > 0 else 0.0

    computed_aov_sar = round(
        avg_main_pieces * selling_price_sar + upsell_attach_rate * UPSELL_PRICE_SAR,
        2,
    )
    aov_usd = round(aov_sar / rate, 2) if orders_count and rate > 0 else 0.0
    computed_aov_usd = round(
        avg_main_pieces * selling_price_usd + upsell_attach_rate * upsell_price_usd,
        2,
    )

    fees_usd = cod_ops_fees_usd()
    fees_sar = cod_ops_fees_sar(rate)

    return {
        "orders_count": orders_count,
        "revenue_sar": revenue_sar,
        "subtotal_sar": subtotal_sar,
        "upsell_revenue_sar": upsell_revenue_sar,
        "upsell_orders": upsell_orders,
        "aov_sar": aov_sar,
        "aov_usd": aov_usd,
        "subtotal_aov_sar": subtotal_aov_sar,
        "upsell_per_order_sar": upsell_per_order_sar,
        "upsell_attach_rate": upsell_attach_rate,
        "upsell_attach_rate_percent": round(upsell_attach_rate * 100, 2),
        "avg_main_pieces_per_order": avg_main_pieces,
        "total_main_pieces": total_main_pieces,
        "selling_price_per_piece_sar": selling_price_sar,
        "selling_price_per_piece_usd": selling_price_usd,
        "upsell_price_sar": UPSELL_PRICE_SAR,
        "upsell_price_usd": upsell_price_usd,
        "computed_aov_sar": computed_aov_sar,
        "computed_aov_usd": computed_aov_usd,
        "sar_per_usd": rate,
        "catalog_selling_prices_sar": catalog_selling_prices_sar(),
        "fixed_costs_usd": fees_usd,
        "fixed_costs_sar": fees_sar,
        "notes": (
            "AOV = sum(total_sar) / orders. Selling price/piece = sum(subtotal_sar) / main pieces "
            "(original lines only, excludes upsell). "
            "Computed AOV ≈ avg_main_pieces × sell_price + upsell_attach × 99 SAR. "
            "COD fees = confirmation + delivery + return + warehouse (USD, env COD_FEE_*)."
        ),
    }
