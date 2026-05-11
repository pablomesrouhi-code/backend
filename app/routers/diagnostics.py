"""Optional DB diagnostics — set DATABASE_DIAGNOSTICS_TOKEN in env to enable."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text

from app.database import get_engine

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
