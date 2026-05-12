"""Analytics events (trusted clicks classification server-side)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Index, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"
    __table_args__ = (
        Index("ix_analytics_events_created_at", "created_at"),
        Index("ix_analytics_events_counts_trusted_created", "counts_as_trusted", "created_at"),
        Index("ix_analytics_events_event_type_created", "event_type", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    path: Mapped[str | None] = mapped_column(Text, nullable=True)
    referrer: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    country_iso: Mapped[str | None] = mapped_column(String(8), nullable=True)
    mm_risk_score: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    mm_is_vpn: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    mm_is_proxy: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    mm_is_tor: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    mm_is_hosting: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ipqs_vpn: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ipqs_proxy: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ipqs_tor: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    counts_as_trusted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    raw_flags: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
