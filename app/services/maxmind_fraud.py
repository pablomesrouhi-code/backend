"""Test-phone whitelist (used by checkout). MaxMind minFraud is removed."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class MaxMindOrderFields:
    country_iso: str | None
    risk_score: Any
    is_vpn: bool | None
    is_proxy: bool | None
    is_tor: bool | None
    is_hosting: bool | None


@dataclass(frozen=True, slots=True)
class FraudEvalResult:
    allowed: bool
    detail: str | None
    fields: MaxMindOrderFields | None
    raw_response: dict[str, Any] | None
    source: str


_DEFAULT_TEST_LOCAL_PHONES = frozenset({"055000000"})


def _parse_whitelist() -> set[str]:
    raw = os.getenv("ORDER_TEST_PHONE_WHITELIST", "")
    return {p.strip() for p in raw.split(",") if p.strip()}


def is_test_phone_whitelisted(phone_local: str) -> bool:
    pl = phone_local.strip()
    if pl in _DEFAULT_TEST_LOCAL_PHONES:
        return True
    return pl in _parse_whitelist()


def evaluate_order_fraud(
    *,
    client_ip: str | None = None,
    user_agent: str | None = None,
    phone_e164: str = "",
    phone_local: str = "",
    order_total_sar: int = 0,
) -> FraudEvalResult:
    """MaxMind removed — orders are not blocked by IP/fraud scoring."""
    return FraudEvalResult(
        allowed=True,
        detail=None,
        fields=None,
        raw_response=None,
        source="disabled",
    )
