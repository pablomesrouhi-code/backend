"""Optional DB diagnostics — set DATABASE_DIAGNOSTICS_TOKEN in env to enable."""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.database import get_engine
from app.services.sheet_webhook import _webhook_url_from_env

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
