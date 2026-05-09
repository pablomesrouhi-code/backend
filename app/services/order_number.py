"""Readable order numbers NL-YYYY-NNNNNN."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.order_models import Order


def next_order_number(db: Session) -> str:
    year = datetime.now(UTC).year
    prefix = f"NL-{year}-"
    stmt: Select[tuple[str]] = (
        select(Order.order_number)
        .where(Order.order_number.startswith(prefix))
        .order_by(Order.order_number.desc())
        .limit(1)
    )
    last = db.execute(stmt).scalar_one_or_none()
    if last:
        suffix = int(last.split("-")[-1])
        n = suffix + 1
    else:
        n = 1
    return f"{prefix}{n:06d}"
