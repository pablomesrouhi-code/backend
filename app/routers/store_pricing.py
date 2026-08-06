"""Public storefront pricing (same source as checkout backend)."""

from __future__ import annotations

from fastapi import APIRouter

from app.services.store_settings import bundle_prices_sar_int, get_store_config, upsell_price_sar_int

router = APIRouter()


@router.get("/pricing")
def public_pricing() -> dict[str, object]:
    cfg = get_store_config()
    bundles = bundle_prices_sar_int()
    product_bundles = cfg.get("product_bundle_prices_sar") or {}
    combos = cfg.get("combo_deals_sar") or {}
    return {
        "currency": "SAR",
        "bundles": {str(k): v for k, v in sorted(bundles.items())},
        "upsell_sar": upsell_price_sar_int(),
        "product_bundles": product_bundles,
        "combos": combos,
        "sar_per_usd": cfg.get("sar_per_usd"),
    }
