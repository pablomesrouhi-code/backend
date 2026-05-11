"""Normalize DATABASE_URL for SQLAlchemy + psycopg3.

EasyPanel and others often emit ``postgres://`` or ``postgresql://`` without a driver;
this project uses psycopg v3 (``postgresql+psycopg://``).
"""

from __future__ import annotations

import os


def database_url_raw_from_env() -> str:
    """Read ``DATABASE_URL``; strip whitespace and outer ``"`` / ``'`` when panels YAML-wrap the value."""

    raw = (os.getenv("DATABASE_URL") or "").strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        raw = raw[1:-1].strip()
    return raw


def normalize_database_url(raw: str) -> str:
    url = raw.strip()
    if not url:
        return url
    if url.startswith("postgresql+psycopg://"):
        return url
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url
