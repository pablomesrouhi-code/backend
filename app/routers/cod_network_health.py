"""`/api/cod-network-status` — whether COD Network lead push is configured."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.services.cod_network import _api_token, cod_network_enabled, default_cod_sku

router = APIRouter()


class CodNetworkStatus(BaseModel):
    enabled: bool
    token_configured: bool
    api_connected: bool
    cod_sku: str | None = None
    probe_error: str | None = None
    hint: str


def _status_response() -> CodNetworkStatus:
    token_ok = bool(_api_token())
    enabled = cod_network_enabled()
    api_connected = False
    cod_sku: str | None = None
    probe_error: str | None = None

    if enabled and token_ok:
        try:
            cod_sku = default_cod_sku()
            api_connected = True
        except Exception as e:
            probe_error = str(e)[:300]

    return CodNetworkStatus(
        enabled=enabled,
        token_configured=token_ok,
        api_connected=api_connected,
        cod_sku=cod_sku,
        probe_error=probe_error,
        hint=(
            "Set COD_NETWORK_API_TOKEN + COD_NETWORK_ENABLED=true on the API service. "
            "Each checkout POSTs a lead to COD Network (SKU RWCFH by default)."
        ),
    )


@router.get("/cod-network-status", response_model=CodNetworkStatus)
def cod_network_status() -> CodNetworkStatus:
    return _status_response()
