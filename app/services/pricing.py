"""Bundle and upsell pricing (never trust frontend totals)."""

from __future__ import annotations

from app.services.store_settings import bundle_prices_sar_int, upsell_price_sar_int

# Back-compat for imports; live values come from admin store_settings.
BUNDLE_PRICES_SAR: dict[int, int] = {1: 199, 2: 279, 3: 349}
UPSELL_PRICE_SAR = 99


def _bundle_prices() -> dict[int, int]:
    return bundle_prices_sar_int()


def upsell_price_sar() -> int:
    return upsell_price_sar_int()


def bundle_total_sar(total_offer_qty: int) -> int:
    prices = _bundle_prices()
    if total_offer_qty not in prices:
        raise ValueError("Cart must have 1, 2, or 3 items for standard bundle pricing")
    return prices[total_offer_qty]


def allocate_line_totals(bundle: int, quantities: list[int]) -> list[int]:
    """Split bundle SAR across lines so amounts sum exactly to bundle."""
    total_q = sum(quantities)
    if total_q == 0:
        raise ValueError("Empty quantities")
    parts: list[int] = [(bundle * q) // total_q for q in quantities]
    drift = bundle - sum(parts)
    remainders = [(bundle * q) % total_q for q in quantities]
    order = sorted(range(len(parts)), key=lambda i: -remainders[i])
    i = 0
    while drift > 0:
        parts[order[i % len(order)]] += 1
        drift -= 1
        i += 1
    return parts


def line_unit_prices(line_totals: list[int], quantities: list[int]) -> list[int]:
    return [total // qty if qty else 0 for total, qty in zip(line_totals, quantities, strict=True)]
