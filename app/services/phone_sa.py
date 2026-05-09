"""Saudi phone normalization for storage."""

from __future__ import annotations

import re


def normalize_sa_phone(phone: str) -> tuple[str, str, str]:
    """
    Returns (phone_local like 05xxxxxxxx, phone_e164 +966..., phone_digits 9665...).
    """
    digits = re.sub(r"\D", "", phone.strip())
    if len(digits) == 10 and digits.startswith("0"):
        local = digits
        phone_digits = "966" + digits[1:]
    elif len(digits) == 9 and digits.startswith("5"):
        local = "0" + digits
        phone_digits = "966" + digits
    elif digits.startswith("966") and len(digits) >= 12:
        rest = digits[3:]
        if len(rest) == 9 and rest.startswith("5"):
            local = "0" + rest
        else:
            local = "0" + rest[-9:] if len(rest) >= 9 else digits
        phone_digits = digits
    else:
        raise ValueError("Invalid Saudi mobile phone")

    if not phone_digits.startswith("966") or len(phone_digits) < 12:
        raise ValueError("Invalid Saudi mobile phone")

    e164 = "+" + phone_digits
    return local, e164, phone_digits
