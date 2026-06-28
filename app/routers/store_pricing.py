"""Public storefront pricing (same source as checkout backend)."""

from __future__ import annotations

from fastapi import APIRouter

from app.services.store_settings import bundle_prices_sar_int, get_store_config, upsell_price_sar_int

router = APIRouter()


@router.get("/pricing")
def public_pricing() -> dict[str, object]:
    cfg = get_store_config()
    bundles = bundle_prices_sar_int()
    return {
        "currency": "SAR",
        "bundles": {str(k): v for k, v in sorted(bundles.items())},
        "upsell_sar": upsell_price_sar_int(),
        "sar_per_usd": cfg.get("sar_per_usd"),
    }
