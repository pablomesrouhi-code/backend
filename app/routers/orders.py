"""Create orders persisted to Postgres."""

from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.deps import get_db
from app.log_safe import mask_phone_sa
from app.models.order_models import Order, OrderItem
from app.schemas.order_create import CreateOrderRequest, CreateOrderResponse
from app.services.catalog import resolve_product
from app.services.order_number import next_order_number
from app.services.phone_sa import normalize_sa_phone
from app.services.sheet_webhook import apply_sheet_delivery_to_order, build_sheet_row
from app.services.maxmind_fraud import evaluate_order_fraud
from app.services.pricing import (
    UPSELL_PRICE_SAR,
    allocate_line_totals,
    bundle_total_sar,
    line_unit_prices,
)

router = APIRouter()
logger = logging.getLogger(__name__)


async def _run_sheet_delivery_async(order_id: uuid.UUID, payload: dict[str, str | int]) -> None:
    """Run sync sheet POST in a worker thread so it always runs after the HTTP response (reliable with ASGI)."""

    await asyncio.to_thread(apply_sheet_delivery_to_order, order_id, payload)


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


@router.post("/orders", response_model=CreateOrderResponse)
def create_order(
    body: CreateOrderRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> CreateOrderResponse:
    log_skus = [(line.product_id, line.offer_qty) for line in body.items]
    logger.info(
        "[orders] POST /api/orders attempt items=%s total_offer_qty_sum=%s accepted_upsell=%s phone=%s payment_method=%s",
        log_skus,
        sum(line.offer_qty for line in body.items),
        body.accepted_upsell,
        mask_phone_sa(body.phone),
        body.payment_method,
    )

    quantities: list[int] = []
    product_keys: list[str] = []
    for line in body.items:
        try:
            resolve_product(line.product_id)
        except ValueError as e:
            logger.warning("[orders] bad_product_id %s: %s", line.product_id, e)
            raise HTTPException(status_code=400, detail=str(e)) from e
        quantities.append(line.offer_qty)
        product_keys.append(line.product_id.strip().lower())

    total_qty = sum(quantities)
    try:
        subtotal = bundle_total_sar(total_qty)
    except ValueError as e:
        logger.warning("[orders] bundle_pricing_failed total_qty=%s: %s", total_qty, e)
        raise HTTPException(status_code=400, detail=str(e)) from e

    upsell_total = 0
    if body.accepted_upsell:
        if not body.upsell_product_id:
            logger.warning("[orders] accepted_upsell true but upsell_product_id missing")
            raise HTTPException(
                status_code=400,
                detail="upsell_product_id required when accepted_upsell is true",
            )
        try:
            resolve_product(body.upsell_product_id)
        except ValueError as e:
            logger.warning("[orders] bad_upsell_id %s: %s", body.upsell_product_id, e)
            raise HTTPException(status_code=400, detail=str(e)) from e
        upsell_total = UPSELL_PRICE_SAR

    try:
        phone_local, phone_e164, phone_digits = normalize_sa_phone(body.phone)
    except ValueError as e:
        logger.warning("[orders] phone_invalid masked=%s: %s", mask_phone_sa(body.phone), e)
        raise HTTPException(status_code=400, detail=str(e)) from e

    fraud = evaluate_order_fraud(
        client_ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        phone_e164=phone_e164,
        phone_local=phone_local,
        order_total_sar=subtotal + upsell_total,
    )
    if not fraud.allowed:
        logger.info(
            "[orders] fraud_block source=%s phone=%s",
            fraud.source,
            mask_phone_sa(body.phone),
        )
        raise HTTPException(
            status_code=403,
            detail=fraud.detail or "عذراً، لا يمكن إكمال الطلب حالياً.",
        )

    line_totals = allocate_line_totals(subtotal, quantities)
    unit_prices = line_unit_prices(line_totals, quantities)

    order_id = uuid.uuid4()
    order_number = next_order_number(db)

    mm_fields = fraud.fields
    order = Order(
        id=order_id,
        order_number=order_number,
        customer_name=body.customer_name.strip(),
        phone_local=phone_local,
        phone_e164=phone_e164,
        phone_digits=phone_digits,
        status="confirmed",
        subtotal_sar=subtotal,
        upsell_total_sar=upsell_total,
        total_sar=subtotal + upsell_total,
        accepted_upsell=body.accepted_upsell,
        upsell_product_id=(
            body.upsell_product_id.strip().lower() if body.upsell_product_id else None
        ),
        source_page=body.source_page,
        client_event_id=body.client_event_id,
        purchase_event_id=body.purchase_event_id,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        maxmind_country_iso=mm_fields.country_iso if mm_fields else None,
        maxmind_risk_score=mm_fields.risk_score if mm_fields else None,
        maxmind_is_vpn=mm_fields.is_vpn if mm_fields else None,
        maxmind_is_proxy=mm_fields.is_proxy if mm_fields else None,
        maxmind_is_tor=mm_fields.is_tor if mm_fields else None,
        maxmind_is_hosting=mm_fields.is_hosting if mm_fields else None,
    )
    db.add(order)

    for pid, qty, lt, up in zip(product_keys, quantities, line_totals, unit_prices, strict=True):
        ar, en = resolve_product(pid)
        db.add(
            OrderItem(
                order_id=order_id,
                product_id=pid,
                product_name_ar=ar,
                product_name_en=en,
                item_type="original",
                offer_qty=qty,
                unit_price_sar=up,
                line_total_sar=lt,
            )
        )

    if body.accepted_upsell and body.upsell_product_id:
        upid = body.upsell_product_id.strip().lower()
        ar, en = resolve_product(upid)
        db.add(
            OrderItem(
                order_id=order_id,
                product_id=upid,
                product_name_ar=ar,
                product_name_en=en,
                item_type="post_validation_upsell",
                offer_qty=1,
                unit_price_sar=UPSELL_PRICE_SAR,
                line_total_sar=UPSELL_PRICE_SAR,
            )
        )

    try:
        db.commit()
    except SQLAlchemyError:
        logger.exception(
            "[orders] POSTGRES_COMMIT_FAILED order_number=%s order_id=%s — DB down, migration missing, "
            "or permissions. Check DATABASE_URL matches PgWeb + run alembic.",
            order_number,
            order_id,
        )
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="تعذر حفظ الطلب في قاعدة البيانات. راجعوا سجلات الـ API وأحوال PostgreSQL.",
        ) from None

    sheet_lines: list[tuple[str, int]] = list(zip(product_keys, quantities, strict=True))
    if body.accepted_upsell and body.upsell_product_id:
        sheet_lines.append((body.upsell_product_id.strip().lower(), 1))

    try:
        sheet_payload = build_sheet_row(
            customer_name=body.customer_name,
            phone_digits=phone_digits,
            order_number=order_number,
            total_sar=subtotal + upsell_total,
            lines=sheet_lines,
        )
        background_tasks.add_task(_run_sheet_delivery_async, order_id, sheet_payload)
        logger.info("[orders] SHEET_ENQUEUED order_number=%s order_id=%s", order_number, order_id)
    except Exception:
        logger.exception("[orders] sheet_row_build_failed order_number=%s", order_number)
        try:
            o_row = db.get(Order, order_id)
            if o_row is not None:
                o_row.sheet_error = "sheet_row_build_failed_see_api_logs"
                db.commit()
        except SQLAlchemyError:
            logger.exception("[orders] persist_sheet_build_error_failed order_id=%s", order_id)
            db.rollback()

    logger.info(
        "[orders] SAVED_OK order_number=%s order_id=%s total_sar=%s line_items=%s accepted_upsell=%s",
        order_number,
        order_id,
        subtotal + upsell_total,
        len(product_keys) + (1 if body.accepted_upsell and body.upsell_product_id else 0),
        body.accepted_upsell,
    )

    return CreateOrderResponse(
        order_id=str(order_id),
        order_number=order_number,
        subtotal_sar=subtotal,
        upsell_total_sar=upsell_total,
        total_sar=subtotal + upsell_total,
    )
