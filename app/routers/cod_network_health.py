"""`/api/cod-network-status` — whether COD Network lead push is configured."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.services.cod_network import _api_token, cod_network_enabled

router = APIRouter()


class CodNetworkStatus(BaseModel):
    enabled: bool
    token_configured: bool
    hint: str


def _status_response() -> CodNetworkStatus:
    token_ok = bool(_api_token())
    enabled = cod_network_enabled()
    return CodNetworkStatus(
        enabled=enabled,
        token_configured=token_ok,
        hint=(
            "Set COD_NETWORK_ENABLED=true, COD_NETWORK_API_TOKEN, and COD_NETWORK_SKU_MAP "
            "(or COD_NETWORK_DEFAULT_SKU) on the API service, then restart. "
            "After a test order, check orders.cod_network_sent_at / cod_network_error in Postgres."
        ),
    )


@router.get("/cod-network-status", response_model=CodNetworkStatus)
def cod_network_status() -> CodNetworkStatus:
    return _status_response()
