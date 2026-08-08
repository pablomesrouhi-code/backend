"""Admin-editable store pricing and profit-calculator defaults."""

from __future__ import annotations

import copy
import logging
import os
import time
from typing import Any

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.store_settings_models import StoreSettings

logger = logging.getLogger(__name__)

_DEFAULT_COD_FEES_USD: dict[str, float] = {
    "per_confirmed_lead": 1.7,
    "per_delivered_order": 4.0,
    "per_return_order": 1.3,
    "per_fulfilled_shipment": 0.8,
}

DEFAULT_STORE_CONFIG: dict[str, Any] = {
    "bundle_prices_sar": {"1": 199, "2": 279, "3": 349},
    "upsell_price_sar": 99,
    # Per-product tier overrides (shahr-hadi ad price + naseej / vitaflow).
    "product_bundle_prices_sar": {
        "shahr-hadi": {"1": 199, "2": 279, "3": 349},
        "naseej": {"1": 189, "2": 219, "3": 279},
        "vitaflow": {"1": 189, "2": 219, "3": 279},
    },
    # Exact-cart combo deals (SAR).
    "combo_deals_sar": {
        "rawnaq_shahr": 349,  # 1× رونق C + 2× شهر هادئ
        "powder_trio": 349,  # 1× شهر هادئ + نسيج + فيتا فلو
    },
    "pricing_schema": 6,
    "sar_per_usd": 3.75,
    "cod_fees_usd": copy.deepcopy(_DEFAULT_COD_FEES_USD),
    "profit_defaults": {
        "cpl_usd": 0.0,
        "confirmation_pct": 50.0,
        "delivery_pct": 70.0,
        "product_cost_usd": 0.0,
        "upsell_attach_pct": 0.0,
        "avg_main_pieces": 1.0,
    },
    # Manual Meta/TikTok spend runs for Ads Lab (admin dashboard).
    "ad_lab_logs": [],
    # Daily brand work log (creatives + étapes) for Nabta Labo admin.
    "brand_day_logs": [],
    "brand_day_defaults": {
        "creatives_per_day": 10,
        # Challenge window: from start through end of September 2026.
        "period_start": "2026-08-03",
        "period_end": "2026-09-30",
    },
}

_CACHE_TTL_SEC = 30.0
_cache: tuple[float, dict[str, Any]] | None = None


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, val in patch.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def _env_float(name: str) -> float | None:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _apply_env_overrides(cfg: dict[str, Any]) -> dict[str, Any]:
    """EasyPanel env still wins when explicitly set (ops override)."""

    out = copy.deepcopy(cfg)
    sar = _env_float("SAR_PER_USD")
    if sar and sar > 0:
        out["sar_per_usd"] = sar
    fee_map = {
        "per_confirmed_lead": "COD_FEE_CONFIRMATION_USD",
        "per_delivered_order": "COD_FEE_DELIVERY_USD",
        "per_return_order": "COD_FEE_RETURN_USD",
        "per_fulfilled_shipment": "COD_FEE_WAREHOUSE_USD",
    }
    fees = dict(out.get("cod_fees_usd") or {})
    for key, env_key in fee_map.items():
        v = _env_float(env_key)
        if v is not None and v >= 0:
            fees[key] = v
    out["cod_fees_usd"] = fees
    return out


def _normalize_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    merged = _deep_merge(DEFAULT_STORE_CONFIG, raw or {})
    bundles = merged.get("bundle_prices_sar") or {}
    normalized_bundles: dict[str, int] = {}
    for qty in (1, 2, 3):
        key = str(qty)
        try:
            normalized_bundles[key] = max(0, int(bundles.get(key, DEFAULT_STORE_CONFIG["bundle_prices_sar"][key])))
        except (TypeError, ValueError):
            normalized_bundles[key] = int(DEFAULT_STORE_CONFIG["bundle_prices_sar"][key])
    merged["bundle_prices_sar"] = normalized_bundles
    try:
        schema = int(merged.get("pricing_schema") or 1)
    except (TypeError, ValueError):
        schema = 1
    # One-time in-memory upgrade so live checkout picks new catalog without waiting for admin save.
    if schema < 2:
        merged["upsell_price_sar"] = int(DEFAULT_STORE_CONFIG["upsell_price_sar"])
        merged["product_bundle_prices_sar"] = copy.deepcopy(
            DEFAULT_STORE_CONFIG["product_bundle_prices_sar"]
        )
        merged["combo_deals_sar"] = copy.deepcopy(DEFAULT_STORE_CONFIG["combo_deals_sar"])
        merged["pricing_schema"] = 2
    if schema < 3:
        # Revert upsell to 99 SAR (ops request).
        merged["upsell_price_sar"] = 99
        merged["pricing_schema"] = 3
    if schema < 4:
        # Hormonal Balance (shahr-hadi) ad landing price cut — keep Rawnaq at default bundles.
        product_bundles = merged.get("product_bundle_prices_sar")
        if not isinstance(product_bundles, dict):
            product_bundles = {}
        product_bundles["shahr-hadi"] = {"1": 179, "2": 259, "3": 329}
        merged["product_bundle_prices_sar"] = product_bundles
        merged["pricing_schema"] = 4
    if schema < 5:
        product_bundles = merged.get("product_bundle_prices_sar")
        if not isinstance(product_bundles, dict):
            product_bundles = {}
        product_bundles["shahr-hadi"] = {"1": 189, "2": 269, "3": 339}
        merged["product_bundle_prices_sar"] = product_bundles
        merged["pricing_schema"] = 5
    if schema < 6:
        product_bundles = merged.get("product_bundle_prices_sar")
        if not isinstance(product_bundles, dict):
            product_bundles = {}
        product_bundles["shahr-hadi"] = {"1": 199, "2": 279, "3": 349}
        merged["product_bundle_prices_sar"] = product_bundles
        merged["pricing_schema"] = 6
    try:
        merged["upsell_price_sar"] = max(0, int(merged.get("upsell_price_sar", 99)))
    except (TypeError, ValueError):
        merged["upsell_price_sar"] = 99
    product_bundles_raw = merged.get("product_bundle_prices_sar") or {}
    product_bundles: dict[str, dict[str, int]] = {}
    if isinstance(product_bundles_raw, dict):
        for pid, tiers in product_bundles_raw.items():
            if not isinstance(tiers, dict):
                continue
            key = str(pid).strip().lower()
            if not key:
                continue
            normalized_tiers: dict[str, int] = {}
            for qty in (1, 2, 3):
                qk = str(qty)
                try:
                    normalized_tiers[qk] = max(0, int(tiers.get(qk, merged["bundle_prices_sar"][qk])))
                except (TypeError, ValueError):
                    normalized_tiers[qk] = int(merged["bundle_prices_sar"][qk])
            product_bundles[key] = normalized_tiers
    merged["product_bundle_prices_sar"] = product_bundles
    combos_raw = merged.get("combo_deals_sar") or {}
    combos: dict[str, int] = {}
    if isinstance(combos_raw, dict):
        for name, price in combos_raw.items():
            try:
                combos[str(name)] = max(0, int(price))
            except (TypeError, ValueError):
                continue
    for name, price in DEFAULT_STORE_CONFIG["combo_deals_sar"].items():
        combos.setdefault(name, int(price))
    merged["combo_deals_sar"] = combos
    try:
        merged["sar_per_usd"] = max(0.01, float(merged.get("sar_per_usd", 3.75)))
    except (TypeError, ValueError):
        merged["sar_per_usd"] = 3.75
    return _apply_env_overrides(merged)


def invalidate_store_config_cache() -> None:
    global _cache
    _cache = None


def get_store_config(db: Session | None = None) -> dict[str, Any]:
    global _cache
    now = time.time()
    if _cache and now - _cache[0] < _CACHE_TTL_SEC:
        return copy.deepcopy(_cache[1])

    owns_session = db is None
    if owns_session:
        db = SessionLocal()
    try:
        row = db.get(StoreSettings, 1) if db is not None else None
        raw = row.config if row is not None else {}
        cfg = _normalize_config(raw if isinstance(raw, dict) else {})
        _cache = (now, cfg)
        return copy.deepcopy(cfg)
    except Exception:
        logger.exception("[store_settings] load failed — using defaults")
        cfg = _normalize_config({})
        _cache = (now, cfg)
        return copy.deepcopy(cfg)
    finally:
        if owns_session and db is not None:
            db.close()


def save_store_config(db: Session, patch: dict[str, Any]) -> dict[str, Any]:
    row = db.get(StoreSettings, 1)
    current = row.config if row is not None and isinstance(row.config, dict) else {}
    persisted = _deep_merge(current, patch)
    if row is None:
        row = StoreSettings(id=1, config=persisted)
        db.add(row)
    else:
        row.config = persisted
    db.commit()
    invalidate_store_config_cache()
    return get_store_config(db)


def bundle_prices_sar_int() -> dict[int, int]:
    cfg = get_store_config()
    raw = cfg.get("bundle_prices_sar") or {}
    return {int(k): int(v) for k, v in raw.items()}


def upsell_price_sar_int() -> int:
    return int(get_store_config().get("upsell_price_sar", 99))


def product_bundle_prices_sar_int(product_id: str) -> dict[int, int]:
    """Tier prices for one product — override map, else default bundles."""

    defaults = bundle_prices_sar_int()
    pid = product_id.strip().lower()
    overrides = get_store_config().get("product_bundle_prices_sar") or {}
    raw = overrides.get(pid) if isinstance(overrides, dict) else None
    if not isinstance(raw, dict):
        return defaults
    out: dict[int, int] = {}
    for qty in (1, 2, 3):
        try:
            out[qty] = int(raw.get(str(qty), defaults[qty]))
        except (TypeError, ValueError):
            out[qty] = defaults[qty]
    return out


def combo_deal_sar(combo_id: str) -> int:
    combos = get_store_config().get("combo_deals_sar") or {}
    if combo_id not in combos:
        raise ValueError(f"Unknown combo: {combo_id}")
    return int(combos[combo_id])


def sar_per_usd_rate() -> float:
    return float(get_store_config().get("sar_per_usd", 3.75))


def cod_fees_usd_map() -> dict[str, float]:
    fees = get_store_config().get("cod_fees_usd") or {}
    return {k: float(v) for k, v in fees.items()}
