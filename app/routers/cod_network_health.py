"""`/api/cod-network-status` — whether COD Network lead push is configured + live probe."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.catalog import PRODUCT_SKUS, SELLABLE_PRODUCT_IDS
from app.services.cod_network import probe_cod_network_api, resolve_cod_sku

router = APIRouter()


class CodNetworkStatus(BaseModel):
    enabled: bool
    token_configured: bool
    api_connected: bool
    cod_sku: str | None = None
    probe_error: str | None = None
    hint: str
    sellable_skus: dict[str, str] = Field(default_factory=dict)
    sample_skus_from_cod: list[str] = Field(default_factory=list)
    sku_overrides: dict[str, str] = Field(default_factory=dict)
    probed_path: str | None = None


def _status_response() -> CodNetworkStatus:
    probe = probe_cod_network_api()
    sellable = {pid: resolve_cod_sku(pid) for pid in sorted(SELLABLE_PRODUCT_IDS)}
    # Keep catalog keys available for debugging even if not sellable
    _ = PRODUCT_SKUS

    token_ok = bool(probe.get("token_configured"))
    enabled = bool(probe.get("enabled"))
    http_ok = bool(probe.get("http_ok"))
    api_connected = enabled and token_ok and (http_ok or not probe.get("probe_error"))

    hint = (
        "Checkout POSTs leads sync to COD Network. "
        "If leads fail, open the order in Admin and read «خطأ COD Network». "
        "SKU must match your COD Network seller products exactly — "
        "set COD_NETWORK_SKU_OVERRIDES=product_id:SKU if needed "
        "(example: rawnaq-c:MP-39GYGBTANIO7,shahr-hadi:CLCYPWFHH)."
    )
    if probe.get("sample_skus"):
        hint += f" Sample SKUs from COD API: {', '.join(probe['sample_skus'][:8])}."

    return CodNetworkStatus(
        enabled=enabled,
        token_configured=token_ok,
        api_connected=api_connected,
        cod_sku=probe.get("default_sku"),
        probe_error=probe.get("probe_error"),
        hint=hint,
        sellable_skus=sellable,
        sample_skus_from_cod=list(probe.get("sample_skus") or []),
        sku_overrides=dict(probe.get("sku_overrides") or {}),
        probed_path=probe.get("probed_path"),
    )


@router.get("/cod-network-status", response_model=CodNetworkStatus)
def cod_network_status() -> CodNetworkStatus:
    return _status_response()


@router.get("/cod-network-status/raw")
def cod_network_status_raw() -> dict[str, Any]:
    """Debug JSON with full probe payload."""

    return {"ok": True, "probe": probe_cod_network_api(), "status": _status_response().model_dump()}
