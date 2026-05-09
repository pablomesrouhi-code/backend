"""Canonical product IDs and display names (docs scope)."""

from __future__ import annotations

PRODUCT_NAMES: dict[str, tuple[str, str]] = {
    "rawnaq-c": (
        "رونق C - علكات الكولاجين وفيتامين C للبشرة والشعر والأظافر",
        "Rawnaq-C Collagen Gummies",
    ),
    "khiffabiotic": (
        "خفّة بيوتك - علكات البروبيوتيك والألياف",
        "KhiffaBiotic Probiotic Gummies",
    ),
    "laylmag": (
        "ليل ماج - علكات المغنيسيوم و L-Theanine",
        "LaylMag Magnesium Gummies",
    ),
}


def resolve_product(product_id: str) -> tuple[str, str]:
    key = product_id.strip().lower()
    if key not in PRODUCT_NAMES:
        raise ValueError(f"Unknown product_id: {product_id}")
    return PRODUCT_NAMES[key]
