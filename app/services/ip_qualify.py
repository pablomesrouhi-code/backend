"""Classify analytics IPs (optional IPQualityScore). MaxMind is not used."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def _env_bool(key: str, default: bool) -> bool:
    v = os.getenv(key)
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True, slots=True)
class IpQualifyResult:
    country_iso: str | None
    mm_risk_score: Decimal | None
    mm_is_vpn: bool | None
    mm_is_proxy: bool | None
    mm_is_tor: bool | None
    mm_is_hosting: bool | None
    ipqs_vpn: bool | None
    ipqs_proxy: bool | None
    ipqs_tor: bool | None
    counts_as_trusted: bool
    raw_flags: dict[str, Any]


def _fetch_ipqs(ip: str) -> dict[str, Any] | None:
    key = (os.getenv("IPQUALITYSCORE_API_KEY") or "").strip()
    if not key:
        return None
    url = f"https://www.ipqualityscore.com/api/json/ip/{ip}"
    try:
        with httpx.Client(timeout=12.0) as client:
            r = client.get(url, params={"key": key, "strictness": "1", "fast": "true"})
    except Exception:
        logger.exception("[analytics/ipqs] request_failed ip=%s", ip)
        return None
    if not r.is_success:
        logger.warning(
            "[analytics/ipqs] bad_http status=%s ip=%s body=%s",
            r.status_code,
            ip,
            (r.text or "")[:300],
        )
        return None
    try:
        data = r.json()
    except Exception:
        logger.exception("[analytics/ipqs] invalid_json ip=%s", ip)
        return None
    if isinstance(data, dict) and data.get("success") is False:
        logger.warning("[analytics/ipqs] api_error ip=%s msg=%s", ip, data.get("message"))
        return None
    return data if isinstance(data, dict) else None


def qualify_analytics_ip(*, client_ip: str | None, user_agent: str | None) -> IpQualifyResult:
    del user_agent  # unused after MaxMind removal
    allowed_country = "SA"

    ipqs_block_vpn = _env_bool("ANALYTICS_IPQS_BLOCK_VPN", True)
    ipqs_block_proxy = _env_bool("ANALYTICS_IPQS_BLOCK_PROXY", True)
    ipqs_block_tor = _env_bool("ANALYTICS_IPQS_BLOCK_TOR", True)

    raw_out: dict[str, Any] = {"ipqs": None}
    country_iso: str | None = None
    ipqs_vpn = ipqs_proxy = ipqs_tor = None

    if not client_ip or client_ip in ("127.0.0.1", "::1"):
        raw_out["reason"] = "no_public_ip"
        return IpQualifyResult(
            country_iso=None,
            mm_risk_score=None,
            mm_is_vpn=None,
            mm_is_proxy=None,
            mm_is_tor=None,
            mm_is_hosting=None,
            ipqs_vpn=None,
            ipqs_proxy=None,
            ipqs_tor=None,
            counts_as_trusted=False,
            raw_flags=raw_out,
        )

    ipqs = _fetch_ipqs(client_ip)
    if ipqs:
        raw_out["ipqs"] = {
            "vpn": ipqs.get("vpn"),
            "proxy": ipqs.get("proxy"),
            "tor": ipqs.get("tor"),
            "country_code": ipqs.get("country_code"),
            "fraud_score": ipqs.get("fraud_score"),
        }
        cc = ipqs.get("country_code")
        country_iso = cc.upper() if isinstance(cc, str) else None
        ipqs_vpn = bool(ipqs.get("vpn"))
        ipqs_proxy = bool(ipqs.get("proxy"))
        ipqs_tor = bool(ipqs.get("tor"))

    trusted = True
    reasons: list[str] = []

    if country_iso is not None and country_iso != allowed_country:
        trusted = False
        reasons.append(f"country:{country_iso}")

    if ipqs_vpn is not None:
        if ipqs_block_vpn and ipqs_vpn:
            trusted = False
            reasons.append("ipqs_vpn")
        if ipqs_block_proxy and ipqs_proxy:
            trusted = False
            reasons.append("ipqs_proxy")
        if ipqs_block_tor and ipqs_tor:
            trusted = False
            reasons.append("ipqs_tor")

    raw_out["trusted"] = trusted
    raw_out["reasons"] = reasons

    return IpQualifyResult(
        country_iso=country_iso,
        mm_risk_score=None,
        mm_is_vpn=None,
        mm_is_proxy=None,
        mm_is_tor=None,
        mm_is_hosting=None,
        ipqs_vpn=ipqs_vpn,
        ipqs_proxy=ipqs_proxy,
        ipqs_tor=ipqs_tor,
        counts_as_trusted=trusted,
        raw_flags=raw_out,
    )
