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

# Stable SKU per product (shown in Sheets / integrations).
PRODUCT_SKUS: dict[str, str] = {
    "rawnaq-c": "NBL-RWQ-849102",
    "khiffabiotic": "NBL-KHF-572903",
    "laylmag": "NBL-LYM-318467",
}


def resolve_product(product_id: str) -> tuple[str, str]:
    key = product_id.strip().lower()
    if key not in PRODUCT_NAMES:
        raise ValueError(f"Unknown product_id: {product_id}")
    return PRODUCT_NAMES[key]


def resolve_sku(product_id: str) -> str:
    key = product_id.strip().lower()
    if key not in PRODUCT_SKUS:
        raise ValueError(f"Unknown product_id for sku: {product_id}")
    return PRODUCT_SKUS[key]


def sheet_product_labels(product_id: str) -> str:
    """Short Arabic product title for Sheets (matches storefront names)."""
    ar, _en = resolve_product(product_id)
    if " - " in ar:
        return ar.split(" - ", 1)[0].strip()
    return ar.strip()
