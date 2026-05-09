"""FastAPI dependencies."""

from __future__ import annotations

import logging
from collections.abc import Generator

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_engine

logger = logging.getLogger(__name__)


def get_db() -> Generator[Session, None, None]:
    try:
        get_engine()
    except RuntimeError as e:
        logger.warning("[db] No engine — %s", e)
        raise HTTPException(status_code=503, detail="Database not configured") from e
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
