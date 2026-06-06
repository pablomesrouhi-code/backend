"""Persistence models for orders, prechecks, and tracking (see docs/09-database-and-migrations.md)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_phone_local", "phone_local"),
        Index("ix_orders_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_number: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    customer_name: Mapped[str] = mapped_column(Text, nullable=False)
    phone_local: Mapped[str] = mapped_column(Text, nullable=False)
    phone_e164: Mapped[str] = mapped_column(Text, nullable=False)
    phone_digits: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    subtotal_sar: Mapped[int] = mapped_column(Integer, nullable=False)
    upsell_total_sar: Mapped[int] = mapped_column(Integer, nullable=False)
    total_sar: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default=text("'SAR'")
    )
    accepted_upsell: Mapped[bool] = mapped_column(Boolean, nullable=False)
    upsell_product_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_page: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_event_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    purchase_event_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    maxmind_country_iso: Mapped[str | None] = mapped_column(String(8), nullable=True)
    maxmind_risk_score: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    maxmind_is_vpn: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    maxmind_is_proxy: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    maxmind_is_tor: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    maxmind_is_hosting: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    sheet_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sheet_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cod_network_lead_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    cod_network_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cod_network_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    items: Mapped[list["OrderItem"]] = relationship(
        "OrderItem", back_populates="order", cascade="all, delete-orphan"
    )
    tracking_events: Mapped[list["TrackingEvent"]] = relationship(
        "TrackingEvent", back_populates="order"
    )


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (Index("ix_order_items_order_id", "order_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[str] = mapped_column(Text, nullable=False)
    product_name_ar: Mapped[str] = mapped_column(Text, nullable=False)
    product_name_en: Mapped[str] = mapped_column(Text, nullable=False)
    item_type: Mapped[str] = mapped_column(Text, nullable=False)
    offer_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_sar: Mapped[int] = mapped_column(Integer, nullable=False)
    line_total_sar: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    order: Mapped["Order"] = relationship("Order", back_populates="items")


class OrderPrecheck(Base):
    __tablename__ = "order_prechecks"
    __table_args__ = (Index("ix_order_prechecks_phone_local", "phone_local"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    customer_name: Mapped[str] = mapped_column(Text, nullable=False)
    phone_local: Mapped[str] = mapped_column(Text, nullable=False)
    phone_e164: Mapped[str] = mapped_column(Text, nullable=False)
    phone_digits: Mapped[str] = mapped_column(Text, nullable=False)
    cart_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    selected_upsell_product_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    upsell_price_sar: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    maxmind_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    is_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    block_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TrackingEvent(Base):
    __tablename__ = "tracking_events"
    __table_args__ = (Index("ix_tracking_events_event_id", "event_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_name: Mapped[str] = mapped_column(Text, nullable=False)
    event_id: Mapped[str] = mapped_column(Text, nullable=False)
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="SET NULL"),
        nullable=True,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    order: Mapped["Order | None"] = relationship("Order", back_populates="tracking_events")
