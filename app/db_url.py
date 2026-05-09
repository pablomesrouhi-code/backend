"""Normalize DATABASE_URL for SQLAlchemy + psycopg3.

EasyPanel and others often emit ``postgres://`` or ``postgresql://`` without a driver;
this project uses psycopg v3 (``postgresql+psycopg://``).
"""

from __future__ import annotations


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
