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
            "In EasyPanel (API service env only): COD_NETWORK_ENABLED=true and COD_NETWORK_API_TOKEN. "
            "SKU is picked automatically from your COD account. Restart API after saving."
        ),
    )


@router.get("/cod-network-status", response_model=CodNetworkStatus)
def cod_network_status() -> CodNetworkStatus:
    return _status_response()
