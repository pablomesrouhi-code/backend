"""Run Alembic migrations programmatically on API startup."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from urllib.parse import urlsplit

from app.db_url import database_url_raw_from_env, normalize_database_url

logger = logging.getLogger(__name__)


def _migration_log_target() -> None:
    """Log where Alembic will connect (no password) — helps diagnose hang vs wrong host."""
    raw = database_url_raw_from_env()
    if not raw:
        return
    try:
        url = normalize_database_url(raw)
        u = urlsplit(url)
        host = u.hostname or "(missing)"
        port = u.port or 5432
        dbname = (u.path or "/").lstrip("/") or "?"
        q = (u.query or "").lower()
        has_ct = "connect_timeout" in q
        logger.info(
            "Alembic will connect: host=%s port=%s database=%s connect_timeout_in_url=%s",
            host,
            port,
            dbname,
            "yes" if has_ct else "no",
        )
    except Exception:
        logger.info("Alembic: could not parse DATABASE_URL for startup log")


def run_upgrade_head() -> None:
    flag = os.getenv("SKIP_AUTO_MIGRATE", "").strip().lower()
    if flag in ("1", "true", "yes"):
        logger.info("SKIP_AUTO_MIGRATE is set — skipping database migrations.")
        return

    if not database_url_raw_from_env():
        logger.warning("DATABASE_URL is not set — skipping database migrations.")
        return

    from alembic import command
    from alembic.config import Config

    backend_root = Path(__file__).resolve().parent.parent
    ini_path = backend_root / "alembic.ini"
    if not ini_path.is_file():
        logger.warning("alembic.ini not found at %s — skipping migrations.", ini_path)
        return

    cfg = Config(str(ini_path))
    _migration_log_target()
    logger.info("Applying database migrations (alembic upgrade head)...")
    try:
        command.upgrade(cfg, "head")
    except Exception as e:
        logger.exception("Database migration failed — refusing to start API with an out-of-date schema.")
        raise RuntimeError(
            "Alembic upgrade head failed. Check DATABASE_URL connectivity, permissions, and migration files."
        ) from e

    logger.info("Database migrations applied successfully (alembic at head).")
