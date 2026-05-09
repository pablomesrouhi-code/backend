"""initial nabtalabo schema (orders, prechecks, tracking_events).

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-07

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_number", sa.String(length=64), nullable=False),
        sa.Column("customer_name", sa.Text(), nullable=False),
        sa.Column("phone_local", sa.Text(), nullable=False),
        sa.Column("phone_e164", sa.Text(), nullable=False),
        sa.Column("phone_digits", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("subtotal_sar", sa.Integer(), nullable=False),
        sa.Column("upsell_total_sar", sa.Integer(), nullable=False),
        sa.Column("total_sar", sa.Integer(), nullable=False),
        sa.Column(
            "currency",
            sa.String(length=8),
            server_default=sa.text("'SAR'"),
            nullable=False,
        ),
        sa.Column("accepted_upsell", sa.Boolean(), nullable=False),
        sa.Column("upsell_product_id", sa.Text(), nullable=True),
        sa.Column("source_page", sa.Text(), nullable=True),
        sa.Column("client_event_id", sa.Text(), nullable=True),
        sa.Column("purchase_event_id", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("maxmind_country_iso", sa.String(length=8), nullable=True),
        sa.Column("maxmind_risk_score", sa.Numeric(10, 4), nullable=True),
        sa.Column("maxmind_is_vpn", sa.Boolean(), nullable=True),
        sa.Column("maxmind_is_proxy", sa.Boolean(), nullable=True),
        sa.Column("maxmind_is_tor", sa.Boolean(), nullable=True),
        sa.Column("maxmind_is_hosting", sa.Boolean(), nullable=True),
        sa.Column("sheet_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sheet_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_number"),
    )
    op.create_index("ix_orders_phone_local", "orders", ["phone_local"], unique=False)
    op.create_index("ix_orders_created_at", "orders", ["created_at"], unique=False)

    op.create_table(
        "order_prechecks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_name", sa.Text(), nullable=False),
        sa.Column("phone_local", sa.Text(), nullable=False),
        sa.Column("phone_e164", sa.Text(), nullable=False),
        sa.Column("phone_digits", sa.Text(), nullable=False),
        sa.Column(
            "cart_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("selected_upsell_product_id", sa.Text(), nullable=True),
        sa.Column("upsell_price_sar", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip_address", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "maxmind_response",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("is_allowed", sa.Boolean(), nullable=False),
        sa.Column("block_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_order_prechecks_phone_local",
        "order_prechecks",
        ["phone_local"],
        unique=False,
    )

    op.create_table(
        "order_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", sa.Text(), nullable=False),
        sa.Column("product_name_ar", sa.Text(), nullable=False),
        sa.Column("product_name_en", sa.Text(), nullable=False),
        sa.Column("item_type", sa.Text(), nullable=False),
        sa.Column("offer_qty", sa.Integer(), nullable=False),
        sa.Column("unit_price_sar", sa.Integer(), nullable=False),
        sa.Column("line_total_sar", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"], unique=False)

    op.create_table(
        "tracking_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_name", sa.Text(), nullable=False),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_tracking_events_event_id",
        "tracking_events",
        ["event_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_tracking_events_event_id", table_name="tracking_events")
    op.drop_table("tracking_events")
    op.drop_index("ix_order_items_order_id", table_name="order_items")
    op.drop_table("order_items")
    op.drop_index("ix_order_prechecks_phone_local", table_name="order_prechecks")
    op.drop_table("order_prechecks")
    op.drop_index("ix_orders_created_at", table_name="orders")
    op.drop_index("ix_orders_phone_local", table_name="orders")
    op.drop_table("orders")
