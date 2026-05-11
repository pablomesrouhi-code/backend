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
    orders_table_exists: bool
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
        exists = conn.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = :schema AND table_name = :tname)"
            ),
            {"schema": "public", "tname": "orders"},
        ).scalar()
        orders_total = 0
        latest: str | None = None
        if exists:
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
            orders_table_exists=bool(exists),
            orders_total=orders_total,
            latest_created_at_iso=latest,
        )
