"""Create orders persisted to Postgres."""

from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.exc import ProgrammingError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select

from app.deps import get_db
from app.log_safe import mask_phone_sa
from app.models.order_models import Order, OrderItem
from app.schemas.order_create import (
    CreateOrderRequest,
    CreateOrderResponse,
    EnsureSheetDeliveryIn,
)
from app.services.catalog import resolve_product
from app.services.cod_network import (
    apply_cod_network_delivery_to_order,
    build_cod_network_lead_payload,
    cod_network_enabled,
)
from app.services.order_number import next_order_number
from app.services.phone_sa import normalize_sa_phone
from app.services.sheet_webhook import (
    apply_sheet_delivery_to_order,
    build_sheet_row,
    mark_order_sheet_delivery,
    resend_persisted_order_to_sheet,
)
from app.services.telegram_notify import notify_new_order
from app.request_ip import client_ip
from app.services.maxmind_fraud import evaluate_order_fraud
from app.services.order_guard import validate_customer_name, validate_sa_mobile_local
from app.services.pricing import (
    UPSELL_PRICE_SAR,
    allocate_line_totals,
    bundle_total_sar,
    line_unit_prices,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _order_matches_lead_token(order: Order, lead_event_id: str) -> bool:
    token = lead_event_id.strip()
    if not token:
        return False
    for candidate in (order.client_event_id, order.purchase_event_id):
        if candidate and candidate.strip() == token:
            return True
    return False


async def _run_sheet_delivery_async(order_id: uuid.UUID, payload: dict[str, str | int | float]) -> None:
    """Run sync sheet POST in a worker thread so it always runs after the HTTP response (reliable with ASGI)."""

    await asyncio.to_thread(apply_sheet_delivery_to_order, order_id, payload)


async def _run_cod_network_delivery_async(
    order_id: uuid.UUID, payload: dict[str, object]
) -> None:
    await asyncio.to_thread(apply_cod_network_delivery_to_order, order_id, payload)


async def _run_telegram_order_notify_async(
    *,
    order_number: str,
    customer_name: str,
    phone_local: str,
    total_sar: int,
    lines: list[tuple[str, int]],
    accepted_upsell: bool,
) -> None:
    await asyncio.to_thread(
        notify_new_order,
        order_number=order_number,
        customer_name=customer_name,
        phone_local=phone_local,
        total_sar=total_sar,
        lines=lines,
        accepted_upsell=accepted_upsell,
    )


async def _run_order_capi_async(
    *,
    order_id: uuid.UUID,
    order_number: str,
    phone_plain: str,
    client_ip: str | None,
    user_agent: str | None,
    total_sar: int,
    content_ids: list[str],
    source_page: str | None,
    purchase_event_id: str | None,
    lead_event_id: str | None,
) -> None:
    try:
        from app.services.capi_dispatch import dispatch_order_capi_events

        await dispatch_order_capi_events(
            order_id=order_id,
            order_number=order_number,
            phone_plain=phone_plain,
            client_ip=client_ip,
            user_agent=user_agent,
            value=float(total_sar),
            content_ids=content_ids,
            source_url=source_page,
            purchase_event_id=purchase_event_id,
            lead_event_id=lead_event_id,
        )
    except Exception:
        logger.exception("[orders] CAPI background dispatch failed order_id=%s", order_id)


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
        customer_name = validate_customer_name(body.customer_name)
    except ValueError as e:
        logger.warning("[orders] name_invalid: %s", e)
        raise HTTPException(status_code=400, detail=str(e)) from e

    try:
        phone_local, phone_e164, phone_digits = normalize_sa_phone(body.phone)
        validate_sa_mobile_local(phone_local)
    except ValueError as e:
        logger.warning("[orders] phone_invalid masked=%s: %s", mask_phone_sa(body.phone), e)
        raise HTTPException(status_code=400, detail=str(e)) from e

    if not phone_e164.startswith("+9665"):
        logger.warning("[orders] phone_not_sa_mobile masked=%s", mask_phone_sa(body.phone))
        raise HTTPException(status_code=400, detail="يرجى إدخال جوال سعودي صحيح (05XXXXXXXX).")

    fraud = evaluate_order_fraud(
        client_ip=client_ip(request),
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
        customer_name=customer_name,
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
        ip_address=client_ip(request),
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
    except SQLAlchemyError as e:
        logger.exception(
            "[orders] POSTGRES_COMMIT_FAILED order_number=%s order_id=%s — DB down, migration missing, "
            "or permissions. Check DATABASE_URL matches PgWeb + run alembic.",
            order_number,
            order_id,
        )
        db.rollback()
        detail = "تعذر حفظ الطلب في قاعدة البيانات. راجعوا سجلات الـ API وأحوال PostgreSQL."
        if isinstance(e, ProgrammingError):
            raw = str(getattr(e, "orig", e) or e)
            low = raw.lower()
            if "column" in low and "does not exist" in low:
                detail += (
                    " إن ذكر Postgres عموداً ناقصاً: نفِّذ `alembic upgrade head` على نفس قاعدة البيانات "
                    "حتى يتطابق الجدول orders مع المهاجرات الحالية."
                )
        raise HTTPException(status_code=503, detail=detail) from None

    sheet_lines: list[tuple[str, int]] = list(zip(product_keys, quantities, strict=True))
    if body.accepted_upsell and body.upsell_product_id:
        sheet_lines.append((body.upsell_product_id.strip().lower(), 1))

    background_tasks.add_task(
        _run_telegram_order_notify_async,
        order_number=order_number,
        customer_name=customer_name,
        phone_local=phone_local,
        total_sar=subtotal + upsell_total,
        lines=sheet_lines,
        accepted_upsell=body.accepted_upsell,
    )

    capi_content_ids = list(product_keys)
    if body.accepted_upsell and body.upsell_product_id:
        capi_content_ids.append(body.upsell_product_id.strip().lower())

    background_tasks.add_task(
        _run_order_capi_async,
        order_id=order_id,
        order_number=order_number,
        phone_plain=phone_local,
        client_ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
        total_sar=subtotal + upsell_total,
        content_ids=capi_content_ids,
        source_page=body.source_page,
        purchase_event_id=body.purchase_event_id,
        lead_event_id=body.client_event_id,
    )

    try:
        sheet_payload = build_sheet_row(
            customer_name=customer_name,
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

    if cod_network_enabled():
        try:
            cod_payload = build_cod_network_lead_payload(
                customer_name=body.customer_name,
                phone_e164=phone_e164,
                phone_digits=phone_digits,
                order_number=order_number,
                lines=sheet_lines,
                source_page=body.source_page,
                total_sar=float(subtotal + upsell_total),
            )
            cod_skus = "/".join(str(i.get("sku", "")) for i in cod_payload.get("items") or [])
            background_tasks.add_task(_run_cod_network_delivery_async, order_id, cod_payload)
            logger.info(
                "[orders] COD_NETWORK_ENQUEUED order_number=%s order_id=%s sku=%s",
                order_number,
                order_id,
                cod_skus,
            )
        except Exception:
            logger.exception("[orders] cod_network_payload_failed order_number=%s", order_number)
            try:
                o_row = db.get(Order, order_id)
                if o_row is not None:
                    o_row.cod_network_error = "cod_network_payload_failed_see_api_logs"
                    db.commit()
            except SQLAlchemyError:
                logger.exception(
                    "[orders] persist_cod_network_build_error_failed order_id=%s", order_id
                )
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


@router.post("/orders/ensure-sheet")
def ensure_sheet_delivery(
    body: EnsureSheetDeliveryIn,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Thank-you backup when background sheet POST did not complete (Meta Lead already fired)."""

    try:
        oid = uuid.UUID(body.order_id.strip())
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid order_id") from e

    order = db.scalar(
        select(Order).where(Order.id == oid).options(selectinload(Order.items))
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")

    if not _order_matches_lead_token(order, body.lead_event_id):
        logger.warning(
            "[orders] ensure_sheet bad_token order_number=%s phone=%s",
            order.order_number,
            mask_phone_sa(order.phone_local),
        )
        raise HTTPException(status_code=403, detail="Invalid lead_event_id")

    if order.sheet_sent_at and not order.sheet_error:
        return {
            "ok": True,
            "already_sent": True,
            "order_number": order.order_number,
        }

    try:
        outcome, sheet_err = resend_persisted_order_to_sheet(order)
    except ValueError as e:
        logger.warning("[orders] ensure_sheet build_failed order_number=%s: %s", order.order_number, e)
        raise HTTPException(status_code=400, detail=str(e)) from e

    mark_order_sheet_delivery(order, outcome, sheet_err)
    try:
        db.commit()
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=503, detail="Failed to persist sheet status") from e

    logger.info(
        "[orders] ensure_sheet order_number=%s outcome=%s detail=%s",
        order.order_number,
        outcome,
        (sheet_err[:200] if sheet_err else None),
    )
    return {
        "ok": outcome == "ok",
        "already_sent": False,
        "outcome": outcome,
        "detail": sheet_err,
        "order_number": order.order_number,
    }
