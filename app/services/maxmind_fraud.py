"""MaxMind minFraud Score for Saudi-only, low-risk IPs (see docs/12-fraud-maxmind-saudi-only.md)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx

from app.log_safe import mask_phone_sa

logger = logging.getLogger(__name__)

SCORE_URL = "https://minfraud.maxmind.com/minfraud/v2.0/score"

# Generic UX copy — do not mention VPN/fraud (docs/12).
PUBLIC_BLOCK_DETAIL = (
    "عذراً، لا يمكن إكمال الطلب حالياً. تأكّدي من رقم الجوال أو حاولي لاحقاً."
)


@dataclass(frozen=True, slots=True)
class MaxMindOrderFields:
    country_iso: str | None
    risk_score: Decimal | None
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
    source: str  # e.g. "whitelist", "minfraud", "skipped_no_creds", "skipped_error"


def _env_bool(key: str, default: bool) -> bool:
    v = os.getenv(key)
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


# Match `TEST_PHONES` in `frontend/components/checkout/CheckoutPopup.tsx` — always bypass MinFraud
# for this number so staging/prod works even if `ORDER_TEST_PHONE_WHITELIST` was not set in the panel.
_DEFAULT_TEST_LOCAL_PHONES = frozenset({"055000000"})


def _parse_whitelist() -> set[str]:
    raw = os.getenv("ORDER_TEST_PHONE_WHITELIST", "")
    return {p.strip() for p in raw.split(",") if p.strip()}


def is_test_phone_whitelisted(phone_local: str) -> bool:
    pl = phone_local.strip()
    if pl in _DEFAULT_TEST_LOCAL_PHONES:
        return True
    return pl in _parse_whitelist()


def _dig(obj: Any, *keys: str) -> Any:
    cur = obj
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _traits(data: dict[str, Any]) -> dict[str, Any]:
    t = _dig(data, "ip_address", "traits")
    return t if isinstance(t, dict) else {}


def evaluate_order_fraud(
    *,
    client_ip: str | None,
    user_agent: str | None,
    phone_e164: str,
    phone_local: str,
    order_total_sar: int,
) -> FraudEvalResult:
    """
    Returns allowed=False with Arabic PUBLIC_BLOCK_DETAIL message when blocked.
    Test whitelist bypasses all risk rules (production QA).
    Set MAXMIND_ENABLED=false to disable all checks (troubleshooting only).
    """
    if not _env_bool("MAXMIND_ENABLED", True):
        logger.warning(
            "[maxmind] MAXMIND_ENABLED=false — fraud checks skipped (disable in production after debugging)"
        )
        return FraudEvalResult(
            allowed=True,
            detail=None,
            fields=None,
            raw_response=None,
            source="disabled",
        )

    if is_test_phone_whitelisted(phone_local):
        logger.info("[maxmind] bypass test whitelist phone=%s", mask_phone_sa(phone_local))
        return FraudEvalResult(
            allowed=True,
            detail=None,
            fields=None,
            raw_response=None,
            source="whitelist",
        )

    if not phone_e164.startswith("+9665"):
        logger.info("[maxmind] block non-SA mobile e164=%s", mask_phone_sa(phone_local))
        return FraudEvalResult(
            allowed=False,
            detail=PUBLIC_BLOCK_DETAIL,
            fields=None,
            raw_response=None,
            source="phone_country",
        )

    account_id = (os.getenv("MAXMIND_ACCOUNT_ID") or "").strip()
    license_key = (os.getenv("MAXMIND_LICENSE_KEY") or "").strip()
    fail_closed = _env_bool("MAXMIND_FAIL_CLOSED", False)

    if not account_id or not license_key:
        logger.warning("[maxmind] missing MAXMIND_ACCOUNT_ID or MAXMIND_LICENSE_KEY")
        if fail_closed:
            return FraudEvalResult(
                allowed=False,
                detail=PUBLIC_BLOCK_DETAIL,
                fields=None,
                raw_response=None,
                source="skipped_no_creds",
            )
        return FraudEvalResult(
            allowed=True,
            detail=None,
            fields=None,
            raw_response=None,
            source="skipped_no_creds",
        )

    allowed_country = (os.getenv("MAXMIND_ALLOWED_COUNTRY") or "SA").strip().upper()
    try:
        risk_ceiling = float(os.getenv("MAXMIND_MIN_RISK_SCORE_BLOCK", "30"))
    except ValueError:
        risk_ceiling = 30.0
    block_vpn = _env_bool("MAXMIND_BLOCK_VPN", True)
    block_proxy = _env_bool("MAXMIND_BLOCK_PROXY", True)
    block_tor = _env_bool("MAXMIND_BLOCK_TOR", True)
    block_hosting = _env_bool("MAXMIND_BLOCK_HOSTING", True)

    if not client_ip or client_ip in ("127.0.0.1", "::1"):
        logger.warning(
            "[maxmind] no_public_client_ip — configure reverse proxy X-Forwarded-For (phone=%s)",
            mask_phone_sa(phone_local),
        )
        if fail_closed:
            return FraudEvalResult(
                allowed=False,
                detail=PUBLIC_BLOCK_DETAIL,
                fields=None,
                raw_response=None,
                source="skipped_no_ip",
            )
        return FraudEvalResult(
            allowed=True,
            detail=None,
            fields=None,
            raw_response=None,
            source="skipped_no_ip",
        )

    payload: dict[str, Any] = {
        "device": {"ip_address": client_ip},
        "billing": {"country": "SA", "phone_number": phone_e164},
        "order": {"amount": float(order_total_sar), "currency": "SAR"},
    }
    if user_agent:
        payload["device"]["user_agent"] = user_agent

    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.post(
                SCORE_URL,
                json=payload,
                auth=(account_id, license_key),
            )
    except Exception:
        logger.exception("[maxmind] request_failed phone=%s", mask_phone_sa(phone_local))
        if fail_closed:
            return FraudEvalResult(
                allowed=False,
                detail=PUBLIC_BLOCK_DETAIL,
                fields=None,
                raw_response=None,
                source="error",
            )
        return FraudEvalResult(
            allowed=True,
            detail=None,
            fields=None,
            raw_response=None,
            source="skipped_error",
        )

    if not r.is_success:
        logger.warning(
            "[maxmind] bad_http status=%s body=%s",
            r.status_code,
            (r.text or "")[:400],
        )
        if fail_closed:
            return FraudEvalResult(
                allowed=False,
                detail=PUBLIC_BLOCK_DETAIL,
                fields=None,
                raw_response=None,
                source="error",
            )
        return FraudEvalResult(
            allowed=True,
            detail=None,
            fields=None,
            raw_response=None,
            source="skipped_error",
        )

    try:
        data = r.json()
    except Exception:
        logger.exception("[maxmind] invalid JSON body")
        if fail_closed:
            return FraudEvalResult(
                allowed=False,
                detail=PUBLIC_BLOCK_DETAIL,
                fields=None,
                raw_response=None,
                source="error",
            )
        return FraudEvalResult(
            allowed=True,
            detail=None,
            fields=None,
            raw_response=None,
            source="skipped_error",
        )

    traits = _traits(data)
    country = _dig(data, "ip_address", "country", "iso_code")
    if isinstance(country, str):
        country_iso = country.upper()
    else:
        country_iso = None

    rs = data.get("risk_score")
    risk_score = Decimal(str(rs)) if rs is not None else None

    is_vpn = bool(traits.get("is_anonymous_vpn"))
    is_proxy = bool(traits.get("is_public_proxy"))
    is_tor = bool(traits.get("is_tor_exit_node"))
    is_hosting = bool(traits.get("is_hosting_provider"))

    fields = MaxMindOrderFields(
        country_iso=country_iso,
        risk_score=risk_score,
        is_vpn=is_vpn,
        is_proxy=is_proxy,
        is_tor=is_tor,
        is_hosting=is_hosting,
    )

    raw_trim: dict[str, Any] = data if len(str(data)) < 120_000 else {"truncated": True}

    if country_iso is None:
        logger.warning("[maxmind] missing country_iso in minFraud response")
        if fail_closed:
            return FraudEvalResult(
                allowed=False,
                detail=PUBLIC_BLOCK_DETAIL,
                fields=fields,
                raw_response=raw_trim,
                source="minfraud",
            )
    elif country_iso != allowed_country:
        logger.info(
            "[maxmind] block country=%s wanted=%s score=%s phone=%s",
            country_iso,
            allowed_country,
            risk_score,
            mask_phone_sa(phone_local),
        )
        return FraudEvalResult(
            allowed=False,
            detail=PUBLIC_BLOCK_DETAIL,
            fields=fields,
            raw_response=raw_trim,
            source="minfraud",
        )

    if risk_score is not None and float(risk_score) >= risk_ceiling:
        logger.info("[maxmind] block risk_score=%s ceiling=%s", risk_score, risk_ceiling)
        return FraudEvalResult(
            allowed=False,
            detail=PUBLIC_BLOCK_DETAIL,
            fields=fields,
            raw_response=raw_trim,
            source="minfraud",
        )

    if block_vpn and is_vpn:
        logger.info("[maxmind] block vpn")
        return FraudEvalResult(
            False,
            PUBLIC_BLOCK_DETAIL,
            fields,
            raw_trim,
            "minfraud",
        )
    if block_proxy and is_proxy:
        logger.info("[maxmind] block proxy")
        return FraudEvalResult(False, PUBLIC_BLOCK_DETAIL, fields, raw_trim, "minfraud")
    if block_tor and is_tor:
        logger.info("[maxmind] block tor")
        return FraudEvalResult(False, PUBLIC_BLOCK_DETAIL, fields, raw_trim, "minfraud")
    if block_hosting and is_hosting:
        logger.info("[maxmind] block hosting")
        return FraudEvalResult(False, PUBLIC_BLOCK_DETAIL, fields, raw_trim, "minfraud")

    return FraudEvalResult(
        True,
        None,
        fields,
        raw_trim,
        "minfraud",
    )
