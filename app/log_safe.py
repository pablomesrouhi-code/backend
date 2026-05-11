"""Privacy-safe strings for logs (phones, database URLs)."""

from __future__ import annotations


def mask_phone_sa(phone: str) -> str:
    """Redact most digits; keep enough to correlate support without full PII."""

    raw = (phone or "").strip()
    digits = "".join(c for c in raw if c.isdigit())
    if len(digits) >= 10:
        return f"{digits[:2]}****{digits[-4:]}"
    if len(digits) >= 6:
        return f"{digits[:2]}****{digits[-2:]}"
    return "****"


def summarize_database_url(raw: str) -> str:
    """One-line DATABASE_URL for stdout logs; password never logged."""

    s = (raw or "").strip()
    if not s:
        return "(empty)"
    if "://" not in s or "@" not in s:
        return s[:96] + ("…" if len(s) > 96 else "")
    try:
        proto, rest = s.split("://", 1)
        creds, tail = rest.split("@", 1)
        if ":" in creds:
            user, _pw = creds.split(":", 1)
            return f"{proto}://{user}:***@{tail[:80]}{'…' if len(tail) > 80 else ''}"
        return f"{proto}://***@{tail[:80]}{'…' if len(tail) > 80 else ''}"
    except ValueError:
        return "(unparseable)"
