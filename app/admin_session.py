"""Signed cookie session for HTML admin dashboard."""

from __future__ import annotations

import os

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer


def _serializer() -> URLSafeTimedSerializer:
    secret = (os.getenv("ADMIN_SESSION_SECRET") or "").strip()
    if not secret:
        raise RuntimeError("ADMIN_SESSION_SECRET is not set")
    return URLSafeTimedSerializer(secret, salt="nabtalabo-admin-v1")


def mint_admin_token(*, username: str) -> str:
    """Issue URL-safe timed token (store in HttpOnly cookie)."""

    ser = _serializer()
    return ser.dumps({"u": username})


def verify_admin_token(token: str | None, max_age_seconds: int = 43200) -> str | None:
    """Return username if token valid; otherwise None."""

    if not token:
        return None
    try:
        ser = _serializer()
        data = ser.loads(token, max_age=max_age_seconds)
    except (BadSignature, SignatureExpired, RuntimeError):
        return None
    if not isinstance(data, dict):
        return None
    u = data.get("u")
    return u if isinstance(u, str) and u.strip() else None
