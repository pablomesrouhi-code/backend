"""Classify analytics IPs (Saudi + MaxMind + optional IPQualityScore)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx

from app.services.maxmind_fraud import SCORE_URL, _dig, _traits

logger = logging.getLogger(__name__)


def _env_bool(key: str, default: bool) -> bool:
    v = os.getenv(key)
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, "").strip() or default)
    except ValueError:
        return default


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
    allowed_country = (os.getenv("MAXMIND_ALLOWED_COUNTRY") or "SA").strip().upper()
    risk_ceiling = _env_float("ANALYTICS_MM_MAX_RISK_SCORE", 30.0)

    mm_block_vpn = _env_bool("ANALYTICS_MM_BLOCK_VPN", True)
    mm_block_proxy = _env_bool("ANALYTICS_MM_BLOCK_PROXY", True)
    mm_block_tor = _env_bool("ANALYTICS_MM_BLOCK_TOR", True)
    mm_block_hosting = _env_bool("ANALYTICS_MM_BLOCK_HOSTING", True)

    ipqs_block_vpn = _env_bool("ANALYTICS_IPQS_BLOCK_VPN", True)
    ipqs_block_proxy = _env_bool("ANALYTICS_IPQS_BLOCK_PROXY", True)
    ipqs_block_tor = _env_bool("ANALYTICS_IPQS_BLOCK_TOR", True)

    raw_out: dict[str, Any] = {"maxmind": None, "ipqs": None}

    country_iso: str | None = None
    mm_risk: Decimal | None = None
    mm_vpn = mm_proxy = mm_tor = mm_hosting = None

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

    account_id = (os.getenv("MAXMIND_ACCOUNT_ID") or "").strip()
    license_key = (os.getenv("MAXMIND_LICENSE_KEY") or "").strip()

    if account_id and license_key and _env_bool("MAXMIND_ENABLED", True):
        payload: dict[str, Any] = {"device": {"ip_address": client_ip}}
        if user_agent:
            payload["device"]["user_agent"] = user_agent
        try:
            with httpx.Client(timeout=15.0) as client:
                r = client.post(SCORE_URL, json=payload, auth=(account_id, license_key))
        except Exception:
            logger.exception("[analytics/maxmind] request_failed ip=%s", client_ip)
            raw_out["maxmind"] = {"error": "request_failed"}
        else:
            if r.is_success:
                try:
                    data = r.json()
                except Exception:
                    logger.exception("[analytics/maxmind] invalid_json ip=%s", client_ip)
                    raw_out["maxmind"] = {"error": "invalid_json"}
                else:
                    traits = _traits(data)
                    ctry = _dig(data, "ip_address", "country", "iso_code")
                    country_iso = ctry.upper() if isinstance(ctry, str) else None
                    rs = data.get("risk_score")
                    mm_risk = Decimal(str(rs)) if rs is not None else None
                    mm_vpn = bool(traits.get("is_anonymous_vpn"))
                    mm_proxy = bool(traits.get("is_public_proxy"))
                    mm_tor = bool(traits.get("is_tor_exit_node"))
                    mm_hosting = bool(traits.get("is_hosting_provider"))
                    raw_out["maxmind"] = {"risk_score": rs, "traits": traits, "country": country_iso}
            else:
                raw_out["maxmind"] = {"http_status": r.status_code, "body": (r.text or "")[:400]}
                logger.warning(
                    "[analytics/maxmind] bad_http status=%s ip=%s",
                    r.status_code,
                    client_ip,
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
        ipqs_country = cc.upper() if isinstance(cc, str) else None
        if country_iso is None and ipqs_country:
            country_iso = ipqs_country
        ipqs_vpn = bool(ipqs.get("vpn"))
        ipqs_proxy = bool(ipqs.get("proxy"))
        ipqs_tor = bool(ipqs.get("tor"))

    trusted = True
    reasons: list[str] = []

    if country_iso != allowed_country:
        trusted = False
        reasons.append(f"country:{country_iso}")

    if mm_risk is not None and float(mm_risk) >= risk_ceiling:
        trusted = False
        reasons.append(f"mm_risk>={risk_ceiling}")

    if mm_block_vpn and mm_vpn:
        trusted = False
        reasons.append("mm_vpn")
    if mm_block_proxy and mm_proxy:
        trusted = False
        reasons.append("mm_proxy")
    if mm_block_tor and mm_tor:
        trusted = False
        reasons.append("mm_tor")
    if mm_block_hosting and mm_hosting:
        trusted = False
        reasons.append("mm_hosting")

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
        mm_risk_score=mm_risk,
        mm_is_vpn=mm_vpn,
        mm_is_proxy=mm_proxy,
        mm_is_tor=mm_tor,
        mm_is_hosting=mm_hosting,
        ipqs_vpn=ipqs_vpn,
        ipqs_proxy=ipqs_proxy,
        ipqs_tor=ipqs_tor,
        counts_as_trusted=trusted,
        raw_flags=raw_out,
    )
