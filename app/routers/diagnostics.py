"""Optional DB diagnostics — set DATABASE_DIAGNOSTICS_TOKEN in env to enable."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload

from app.database import SessionLocal, get_engine
from app.models.order_models import Order
from app.services.cod_network import (
    rebuild_cod_network_payload_from_persisted_order,
    send_cod_network_lead,
)
from app.services.sheet_webhook import (
    _webhook_url_from_env,
    rebuild_sheet_payload_from_persisted_order,
    send_google_sheet_webhook,
)

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


class DatabaseDiagnostics(BaseModel):
    database_name: str
    db_user: str
    orders_table_exists: bool
    orders_insert_privilege: bool | None = None
    orders_select_privilege: bool | None = None
    orders_total: int
    latest_created_at_iso: str | None


def _require_token(token: str | None) -> None:
    expected = (os.getenv("DATABASE_DIAGNOSTICS_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(status_code=404, detail="Not Found")
    if (token or "").strip() != expected:
        raise HTTPException(status_code=404, detail="Not Found")


class RecentOrderSheetRow(BaseModel):
    order_number: str
    created_at_iso: str | None
    sheet_sent_at_iso: str | None
    sheet_error: str | None


class SheetWebhookDiagnostics(BaseModel):
    webhook_configured: bool
    webhook_url_suffix: str | None = Field(
        default=None, description="Trailing part of GOOGLE_SHEET_WEBHOOK_URL (masked)."
    )
    get_probe_http_status: int | None = None
    get_probe_ok_hint: bool = Field(
        ...,
        description='True if GET webhook returns JSON {"ok":true} (deployment OK). '
        "False often means OAuth HTML or wrong deployment URL.",
    )
    get_probe_preview: str
    recent_orders_sheet: list[RecentOrderSheetRow]


class ResendSheetRequest(BaseModel):
    """Either ``order_id`` (UUID) or ``order_number`` — loads order from Postgres and POSTs row to Sheets."""

    order_number: str | None = None
    order_id: str | None = None


@router.post("/resend-sheet-row")
def resend_sheet_row_manual(
    body: ResendSheetRequest,
    token: str | None = Query(None, alias="token"),
) -> dict[str, Any]:
    """Rebuild sheet JSON from DB and POST again (fixes orders stuck in Postgres only). Requires token."""
    _require_token(token)
    oid_raw = (body.order_id or "").strip()
    on_raw = (body.order_number or "").strip()
    if not oid_raw and not on_raw:
        raise HTTPException(status_code=400, detail="Provide order_id or order_number")

    try:
        get_engine()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    db = SessionLocal()
    try:
        stmt = select(Order).options(selectinload(Order.items))
        if oid_raw:
            try:
                oid = uuid.UUID(oid_raw)
            except ValueError as e:
                raise HTTPException(status_code=400, detail="invalid order_id UUID") from e
            order = db.execute(stmt.where(Order.id == oid)).scalar_one_or_none()
        else:
            order = db.execute(stmt.where(Order.order_number == on_raw)).scalar_one_or_none()

        if order is None:
            raise HTTPException(status_code=404, detail="order not found")

        payload = rebuild_sheet_payload_from_persisted_order(order)
        outcome, sheet_err = send_google_sheet_webhook(payload)

        if outcome == "ok":
            order.sheet_sent_at = datetime.now(UTC)
            order.sheet_error = None
        elif outcome == "failed":
            order.sheet_error = (sheet_err or "unknown")[:4000]
        else:
            order.sheet_error = (sheet_err or "no_webhook_url")[:4000]

        try:
            db.commit()
        except SQLAlchemyError:
            db.rollback()
            raise HTTPException(status_code=503, detail="failed to persist sheet_* after resend")

        return {
            "ok": outcome == "ok",
            "outcome": outcome,
            "detail": sheet_err,
            "order_number": order.order_number,
            "order_id": str(order.id),
        }
    finally:
        db.close()


@router.post("/resend-cod-network-lead")
def resend_cod_network_lead_manual(
    body: ResendSheetRequest,
    token: str | None = Query(None, alias="token"),
) -> dict[str, Any]:
    """Rebuild COD Network lead JSON from DB and POST again. Requires token."""
    _require_token(token)
    oid_raw = (body.order_id or "").strip()
    on_raw = (body.order_number or "").strip()
    if not oid_raw and not on_raw:
        raise HTTPException(status_code=400, detail="Provide order_id or order_number")

    try:
        get_engine()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    db = SessionLocal()
    try:
        stmt = select(Order).options(selectinload(Order.items))
        if oid_raw:
            try:
                oid = uuid.UUID(oid_raw)
            except ValueError as e:
                raise HTTPException(status_code=400, detail="invalid order_id UUID") from e
            order = db.execute(stmt.where(Order.id == oid)).scalar_one_or_none()
        else:
            order = db.execute(stmt.where(Order.order_number == on_raw)).scalar_one_or_none()

        if order is None:
            raise HTTPException(status_code=404, detail="order not found")

        payload = rebuild_cod_network_payload_from_persisted_order(order)
        outcome, err, lead_id = send_cod_network_lead(payload)

        if outcome == "ok":
            order.cod_network_sent_at = datetime.now(UTC)
            order.cod_network_error = None
            if lead_id is not None:
                order.cod_network_lead_id = lead_id
        elif outcome == "failed":
            order.cod_network_error = (err or "unknown")[:4000]
        else:
            order.cod_network_error = (err or "cod_skipped")[:4000]

        try:
            db.commit()
        except SQLAlchemyError:
            db.rollback()
            raise HTTPException(status_code=503, detail="failed to persist cod_network_* after resend")

        return {
            "ok": outcome == "ok",
            "outcome": outcome,
            "detail": err,
            "lead_id": lead_id,
            "order_number": order.order_number,
            "order_id": str(order.id),
        }
    finally:
        db.close()


@router.get("/sheet-webhook", response_model=SheetWebhookDiagnostics)
def sheet_webhook_diagnostic(
    token: str | None = Query(None, alias="token"),
    recent: int = Query(15, alias="recent", ge=1, le=80),
) -> Any:
    """See GOOGLE_SHEET_WEBHOOK_URL reachability plus last orders' sheet_* fields."""
    _require_token(token)

    webhook = _webhook_url_from_env()
    configured = bool(webhook)
    suffix = None
    if webhook:
        suffix = webhook[-56:] if len(webhook) > 56 else webhook

    status: int | None = None
    ok_hint = False
    preview = ""
    if configured:
        try:
            with httpx.Client(timeout=20.0, follow_redirects=True) as c:
                r = c.get(
                    webhook,
                    headers={"User-Agent": "NabtalaboBackend/1.0 (+diagnostics GET)"},
                )
            status = r.status_code
            body = r.text or ""
            preview = body[:500]
            if r.is_success:
                try:
                    j = r.json()
                    ok_hint = isinstance(j, dict) and j.get("ok") is True
                except Exception:
                    ok_hint = False
        except Exception as e:
            preview = f"GET_failed:{type(e).__name__}:{e!s}"[:500]

    eng = get_engine()
    rows_out: list[RecentOrderSheetRow] = []
    with eng.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT order_number, created_at, sheet_sent_at, sheet_error "
                "FROM orders ORDER BY created_at DESC LIMIT :lim"
            ),
            {"lim": recent},
        ).mappings().all()
        for row in rows:
            ca = row.get("created_at")
            ss = row.get("sheet_sent_at")
            rows_out.append(
                RecentOrderSheetRow(
                    order_number=str(row.get("order_number") or ""),
                    created_at_iso=ca.isoformat() if ca else None,
                    sheet_sent_at_iso=ss.isoformat() if ss else None,
                    sheet_error=(
                        str(row["sheet_error"])[:900] if row.get("sheet_error") else None
                    ),
                )
            )

    return SheetWebhookDiagnostics(
        webhook_configured=configured,
        webhook_url_suffix=suffix,
        get_probe_http_status=status,
        get_probe_ok_hint=ok_hint,
        get_probe_preview=preview[:500],
        recent_orders_sheet=rows_out,
    )


@router.get("/database", response_model=DatabaseDiagnostics)
def database_diagnostic(token: str | None = Query(None, alias="token")) -> Any:
    """Return counts / schema hints when DATABASE_DIAGNOSTICS_TOKEN matches ?token=."""
    _require_token(token)

    eng = None
    try:
        eng = get_engine()
    except RuntimeError as e:
        raise HTTPException(
            status_code=503,
            detail=f"DATABASE_URL not configured: {e}",
        ) from e

    with eng.connect() as conn:
        name = conn.execute(text("SELECT current_database()")).scalar_one()
        db_user = str(conn.execute(text("SELECT CURRENT_USER")).scalar_one())
        exists = conn.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = :schema AND table_name = :tname)"
            ),
            {"schema": "public", "tname": "orders"},
        ).scalar()
        orders_total = 0
        latest: str | None = None
        insert_ok: bool | None = None
        select_ok: bool | None = None
        if exists:
            insert_ok = bool(
                conn.execute(
                    text(
                        "SELECT has_table_privilege(CURRENT_USER, CAST(:tbl AS regclass), 'INSERT')"
                    ),
                    {"tbl": "public.orders"},
                ).scalar_one()
            )
            select_ok = bool(
                conn.execute(
                    text(
                        "SELECT has_table_privilege(CURRENT_USER, CAST(:tbl AS regclass), 'SELECT')"
                    ),
                    {"tbl": "public.orders"},
                ).scalar_one()
            )
            orders_total = int(
                conn.execute(text("SELECT COUNT(*)::bigint FROM orders")).scalar_one()
            )
            last_at = conn.execute(text("SELECT MAX(created_at) FROM orders")).scalar()
            latest = (
                last_at.isoformat()
                if last_at is not None and hasattr(last_at, "isoformat")
                else (str(last_at) if last_at is not None else None)
            )

        return DatabaseDiagnostics(
            database_name=str(name),
            db_user=db_user,
            orders_table_exists=bool(exists),
            orders_insert_privilege=insert_ok,
            orders_select_privilege=select_ok,
            orders_total=orders_total,
            latest_created_at_iso=latest,
        )
