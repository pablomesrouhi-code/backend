"""analytics_events for trusted-click analytics.

Revision ID: 0002_analytics_events
Revises: 0001_initial
Create Date: 2026-05-12

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002_analytics_events"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "analytics_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("referrer", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("country_iso", sa.String(length=8), nullable=True),
        sa.Column("mm_risk_score", sa.Numeric(10, 4), nullable=True),
        sa.Column("mm_is_vpn", sa.Boolean(), nullable=True),
        sa.Column("mm_is_proxy", sa.Boolean(), nullable=True),
        sa.Column("mm_is_tor", sa.Boolean(), nullable=True),
        sa.Column("mm_is_hosting", sa.Boolean(), nullable=True),
        sa.Column("ipqs_vpn", sa.Boolean(), nullable=True),
        sa.Column("ipqs_proxy", sa.Boolean(), nullable=True),
        sa.Column("ipqs_tor", sa.Boolean(), nullable=True),
        sa.Column("counts_as_trusted", sa.Boolean(), nullable=False),
        sa.Column(
            "raw_flags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_analytics_events_created_at",
        "analytics_events",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_analytics_events_counts_trusted_created",
        "analytics_events",
        ["counts_as_trusted", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_analytics_events_event_type_created",
        "analytics_events",
        ["event_type", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_analytics_events_event_type_created", table_name="analytics_events")
    op.drop_index("ix_analytics_events_counts_trusted_created", table_name="analytics_events")
    op.drop_index("ix_analytics_events_created_at", table_name="analytics_events")
    op.drop_table("analytics_events")
