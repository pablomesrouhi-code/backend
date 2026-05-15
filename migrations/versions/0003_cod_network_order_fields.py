"""orders.cod_network_* — track COD Network lead delivery.

Revision ID: 0003_cod_network
Revises: 0002_analytics_events
Create Date: 2026-05-15

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_cod_network"
down_revision: Union[str, None] = "0002_analytics_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("cod_network_lead_id", sa.BigInteger(), nullable=True))
    op.add_column(
        "orders",
        sa.Column("cod_network_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("orders", sa.Column("cod_network_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "cod_network_error")
    op.drop_column("orders", "cod_network_sent_at")
    op.drop_column("orders", "cod_network_lead_id")
