"""Bundle, per-product, combo, and upsell pricing (never trust frontend totals)."""

from __future__ import annotations

from collections import Counter

from app.services.store_settings import (
    bundle_prices_sar_int,
    combo_deal_sar,
    product_bundle_prices_sar_int,
    upsell_price_sar_int,
)

# Back-compat for imports; live values come from admin store_settings.
BUNDLE_PRICES_SAR: dict[int, int] = {1: 199, 2: 279, 3: 349}
UPSELL_PRICE_SAR = 89


def _bundle_prices() -> dict[int, int]:
    return bundle_prices_sar_int()


def upsell_price_sar() -> int:
    return upsell_price_sar_int()


def product_tier_price_sar(product_id: str, offer_qty: int) -> int:
    prices = product_bundle_prices_sar_int(product_id)
    if offer_qty not in prices:
        raise ValueError("كل منتج يجب أن يكون بكمية 1 أو 2 أو 3")
    return prices[offer_qty]


def _qty_by_product(lines: list[tuple[str, int]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for pid, qty in lines:
        counts[pid.strip().lower()] += int(qty)
    return dict(counts)


def match_named_combo(lines: list[tuple[str, int]]) -> str | None:
    """Exact-cart combos (no extra products)."""

    d = _qty_by_product(lines)
    if (
        set(d) == {"rawnaq-c", "shahr-hadi"}
        and d.get("rawnaq-c") == 1
        and d.get("shahr-hadi") == 2
    ):
        return "rawnaq_shahr"
    if (
        set(d) == {"shahr-hadi", "naseej", "vitaflow"}
        and d.get("shahr-hadi") == 1
        and d.get("naseej") == 1
        and d.get("vitaflow") == 1
    ):
        return "powder_trio"
    return None


def cart_subtotal_sar(lines: list[tuple[str, int]]) -> int:
    """Server-side cart total: named combo or sum of per-product tiers."""

    if not lines:
        raise ValueError("السلة فارغة")
    combo = match_named_combo(lines)
    if combo:
        return combo_deal_sar(combo)
    total = 0
    for pid, qty in lines:
        total += product_tier_price_sar(pid, int(qty))
    return total


def bundle_total_sar(total_offer_qty: int) -> int:
    """Legacy helper — prefer cart_subtotal_sar for mixed catalogs."""

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
