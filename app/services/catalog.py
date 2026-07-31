"""Canonical product IDs and display names (docs scope)."""

from __future__ import annotations

PRODUCT_NAMES: dict[str, tuple[str, str]] = {
    "rawnaq-c": (
        "رونق C - علكات البيوتين والزنك وفيتامين D للشعر والأظافر والبشرة",
        "Rawnaq-C Hair Skin & Nails Gummies",
    ),
    "khiffabiotic": (
        "خفّة بيوتك - علكات البروبيوتيك والألياف",
        "KhiffaBiotic Probiotic Gummies",
    ),
    "laylmag": (
        "ليل ماج - مسحوق المغنيسيوم 14 في 1 و L-Theanine",
        "LaylMag 14-in-1 Magnesium Powder",
    ),
    "quwwat-sha3r": (
        "قوة شعر - مسحوق كولاجين بحري للشعر",
        "Quwwat Sha3r Marine Collagen Hair Powder",
    ),
    "wudouh": (
        "وضوح - مسحوق غلوتاثيون وكولاجين للبشرة",
        "Wudouh Clear Skin Glow Powder",
    ),
    "shahr-hadi": (
        "شهر هادئ - مسحوق دعم الدورة والتوازن الهرموني",
        "Shahr Hadi PMS Calm Support Powder",
    ),
    "naseej": (
        "نسيج - مسحوق كولاجين متعدد لقوام الوجه من الداخل",
        "Naseej Multi Collagen Peptides Powder",
    ),
    "vitaflow": (
        "فيتا فلو - مسحوق طاقة بنكهة الكراميل",
        "VitaFlow Caramel Energy Powder",
    ),
}

# Seller SKU per product — used in Google Sheet webhook and COD Network leads.
PRODUCT_SKUS: dict[str, str] = {
    "rawnaq-c": "MP-39GYGBTANIO7",
    "khiffabiotic": "PRBTCS",
    "laylmag": "MGAGFD",
    "quwwat-sha3r": "SRHRPW",
    "wudouh": "PSPFH",
    "shahr-hadi": "CLCYPWFHH",
    "naseej": "MP-ZTYR4BRMRP0F",
    "vitaflow": "MP-P9XG0HKJNKRZ",
}

# يبقى الكاتالوغ الكامل أعلاه لقراءة الطلبات القديمة، لكن البيع الحالي محصور هنا.
SELLABLE_PRODUCT_IDS: frozenset[str] = frozenset({"rawnaq-c", "shahr-hadi", "naseej", "vitaflow"})


def resolve_product(product_id: str) -> tuple[str, str]:
    key = product_id.strip().lower()
    if key not in PRODUCT_NAMES:
        raise ValueError(f"Unknown product_id: {product_id}")
    return PRODUCT_NAMES[key]


def ensure_product_sellable(product_id: str) -> str:
    """Validate a new cart/upsell line against the current live inventory."""

    key = product_id.strip().lower()
    resolve_product(key)
    if key not in SELLABLE_PRODUCT_IDS:
        raise ValueError("نفدت كمية هذا المنتج حالياً. يرجى اختيار منتج متوفر.")
    return key


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
