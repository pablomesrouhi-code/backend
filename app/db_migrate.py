"""Run Alembic migrations programmatically on API startup."""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def run_upgrade_head() -> None:
    flag = os.getenv("SKIP_AUTO_MIGRATE", "").strip().lower()
    if flag in ("1", "true", "yes"):
        logger.info("SKIP_AUTO_MIGRATE is set — skipping database migrations.")
        return

    if not os.getenv("DATABASE_URL", "").strip():
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
    logger.info("Applying database migrations (alembic upgrade head)...")
    try:
        command.upgrade(cfg, "head")
    except Exception as e:
        logger.exception("Database migration failed — refusing to start API with an out-of-date schema.")
        raise RuntimeError(
            "Alembic upgrade head failed. Check DATABASE_URL connectivity, permissions, and migration files."
        ) from e

    logger.info("Database migrations applied successfully (alembic at head).")
