"""SQLAlchemy declarative base and engine (optional until DATABASE_URL is set)."""

from __future__ import annotations

import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.db_url import database_url_raw_from_env, normalize_database_url
from app.log_safe import summarize_database_url

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


_engine = None
SessionLocal = sessionmaker(autoflush=False, autocommit=False, expire_on_commit=False)


def configure_database() -> None:
    """Bind engine when DATABASE_URL is present (no-op otherwise).

    Never raises: a bad URL must not prevent the process from starting (EasyPanel /health probes).
    """

    global _engine
    raw = database_url_raw_from_env()
    if not raw:
        logger.warning(
            "[db] DATABASE_URL empty — Postgres routes will 503 (e.g. POST /api/orders)."
        )
        return
    url = normalize_database_url(raw)
    try:
        _engine = create_engine(url, pool_pre_ping=True)
        SessionLocal.configure(bind=_engine)
        logger.info("[db] SQLAlchemy engine ready — %s", summarize_database_url(raw))
    except Exception:
        logger.exception(
            "[db] create_engine failed — fix DATABASE_URL; Postgres routes will 503 until then."
        )
        _engine = None


configure_database()


def get_engine():
    if _engine is None:
        raise RuntimeError("DATABASE_URL is not set or database is not configured")
    return _engine
