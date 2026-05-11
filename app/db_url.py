"""Normalize DATABASE_URL for SQLAlchemy + psycopg3.

EasyPanel and others often emit ``postgres://`` or ``postgresql://`` without a driver;
this project uses psycopg v3 (``postgresql+psycopg://``).
"""

from __future__ import annotations

import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def database_url_raw_from_env() -> str:
    """Read ``DATABASE_URL``; strip whitespace and outer ``"`` / ``'`` when panels YAML-wrap the value."""

    raw = (os.getenv("DATABASE_URL") or "").strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        raw = raw[1:-1].strip()
    return raw


def _connect_timeout_seconds() -> int:
    raw = (os.getenv("DB_CONNECT_TIMEOUT_SEC") or "").strip()
    if not raw:
        return 15
    try:
        n = int(raw)
        return max(3, min(n, 120))
    except ValueError:
        return 15


def with_connect_timeout(url: str) -> str:
    """Append libpq-style ``connect_timeout`` so unreachable Postgres fails fast instead of hanging startup."""

    u = url.strip()
    if not u:
        return u
    sec = _connect_timeout_seconds()
    parts = urlsplit(u)
    q = dict(parse_qsl(parts.query, keep_blank_values=True))
    if "connect_timeout" not in {k.lower() for k in q}:
        q["connect_timeout"] = str(sec)
    new_query = urlencode(sorted(q.items()))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))


def normalize_database_url(raw: str) -> str:
    url = raw.strip()
    if not url:
        return url
    if url.startswith("postgresql+psycopg://"):
        out = url
    elif url.startswith("postgres://"):
        out = "postgresql+psycopg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://"):
        out = "postgresql+psycopg://" + url[len("postgresql://") :]
    else:
        out = url
    return with_connect_timeout(out)
