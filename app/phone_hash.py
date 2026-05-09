"""Normalize Saudi mobile numbers and SHA-256 hash for CAPI user_data fields."""

from __future__ import annotations

import hashlib
import re


def digits_only_sa_phone(phone: str) -> str | None:
    """Return digits with Saudi country code (966…) when possible."""
    if not phone or not str(phone).strip():
        return None
    digits = re.sub(r"\D", "", str(phone).strip())
    if len(digits) == 10 and digits.startswith("0"):
        return "966" + digits[1:]
    if len(digits) == 9 and digits.startswith("5"):
        return "966" + digits
    if digits.startswith("966"):
        return digits
    return digits or None


def sha256_lower_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_sa_phone_for_capi(phone: str) -> str | None:
    d = digits_only_sa_phone(phone)
    if not d:
        return None
    return sha256_lower_hex(d)
