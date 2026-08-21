"""Saudi mobile + plausible customer name."""

from __future__ import annotations

import re

from app.services.maxmind_fraud import is_test_phone_whitelisted

NAME_INVALID_DETAIL = "يرجى إدخال اسمك الحقيقي (حرفين على الأقل، بدون أرقام فقط)."
PHONE_INVALID_DETAIL = "يرجى إدخال جوال سعودي صحيح (05XXXXXXXX)."

# Saudi mobile: 050 + 053–059 (STC/Mobily/Zain ranges).
_SA_LOCAL_RE = re.compile(r"^05(?:0|[3-9])\d{7}$")

_GARBAGE_NAMES = frozenset(
    {
        "test",
        "testing",
        "asdf",
        "qwerty",
        "aaa",
        "bbb",
        "abc",
        "name",
        "user",
        "guest",
        "none",
        "null",
        "undefined",
        "اسم",
        "اختبار",
        "تجربة",
    }
)


def validate_customer_name(raw: str) -> str:
    name = " ".join(raw.strip().split())
    if len(name) < 2:
        raise ValueError(NAME_INVALID_DETAIL)

    compact = name.replace(" ", "")
    if not re.search(r"[\u0600-\u06FFa-zA-Z]", name):
        raise ValueError(NAME_INVALID_DETAIL)
    if re.fullmatch(r"[\d\s\-+().]+", name):
        raise ValueError(NAME_INVALID_DETAIL)
    if len(set(compact)) == 1:
        raise ValueError(NAME_INVALID_DETAIL)
    if re.search(r"(.)\1{2,}", compact):
        raise ValueError(NAME_INVALID_DETAIL)

    key = compact.lower()
    if key in _GARBAGE_NAMES:
        raise ValueError(NAME_INVALID_DETAIL)

    return name


def validate_sa_mobile_local(phone_local: str) -> None:
    pl = phone_local.strip()
    if is_test_phone_whitelisted(pl):
        return
    if not _SA_LOCAL_RE.fullmatch(pl):
        raise ValueError(PHONE_INVALID_DETAIL)
