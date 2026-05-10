"""Browser origins allowed for checkout / CAPI — never rely on forgetting env in EasyPanel."""

from __future__ import annotations

import os

# When CORS_ORIGINS is unset, these cover the public storefront + local dev.
DEFAULT_STORE_ORIGINS: tuple[str, ...] = (
    "https://Nabtalabo.store",
    "https://www.Nabtalabo.store",
    "https://NabtaLabo.store",
    "https://www.NabtaLabo.store",
    "https://nabtalabo.store",
    "https://www.nabtalabo.store",
)

LOCAL_DEV_ORIGINS: tuple[str, ...] = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
)


def cors_allowed_origins() -> list[str]:
    """
    If CORS_ORIGINS is set, use only that list (strict).
    Otherwise merge FRONTEND_URL (if any), known store domains, and localhost.
    """
    raw = os.getenv("CORS_ORIGINS", "").strip()
    if raw:
        return _dedupe([o.strip() for o in raw.split(",") if o.strip()])

    parts: list[str] = []
    fu = os.getenv("FRONTEND_URL", "").strip()
    if fu:
        parts.append(fu)
    parts.extend(DEFAULT_STORE_ORIGINS)
    parts.extend(LOCAL_DEV_ORIGINS)
    return _dedupe(parts)


def _dedupe(seq: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for o in seq:
        if o not in seen:
            seen.add(o)
            out.append(o)
    return out
