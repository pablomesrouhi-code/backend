from __future__ import annotations

from pydantic import BaseModel, Field


class CheckoutCaptureLineIn(BaseModel):
    product_id: str = Field(min_length=1, max_length=64)
    offer_qty: int = Field(ge=1, le=10)


class CheckoutCaptureIn(BaseModel):
    """Checkout failed after name+phone — capture to Sheet so Meta funnel gaps are not lost."""

    customer_name: str = Field(min_length=1, max_length=200)
    phone: str = Field(min_length=8, max_length=32)
    items: list[CheckoutCaptureLineIn] = Field(min_length=1, max_length=10)
    failure_status: int | None = Field(default=None, ge=400, le=599)
    failure_detail: str | None = Field(default=None, max_length=400)
    source_page: str | None = Field(default=None, max_length=2048)
