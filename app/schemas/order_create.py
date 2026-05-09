from __future__ import annotations

from pydantic import BaseModel, Field


class CartLineIn(BaseModel):
    product_id: str = Field(min_length=1, max_length=64)
    offer_qty: int = Field(ge=1, le=10)


class CreateOrderRequest(BaseModel):
    customer_name: str = Field(min_length=1, max_length=200)
    phone: str = Field(min_length=8, max_length=32)
    items: list[CartLineIn] = Field(min_length=1, max_length=10)
    accepted_upsell: bool = False
    upsell_product_id: str | None = Field(default=None, max_length=64)
    source_page: str | None = Field(default=None, max_length=2048)
    client_event_id: str | None = None
    purchase_event_id: str | None = None


class CreateOrderResponse(BaseModel):
    order_id: str
    order_number: str
    subtotal_sar: int
    upsell_total_sar: int
    total_sar: int
