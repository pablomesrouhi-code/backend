"""Restore orders.cod_network_* for COD Network lead sync.

Revision ID: 0005_restore_cod_network
Revises: 0004_drop_cod_network
Create Date: 2026-05-28

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_restore_cod_network"
down_revision: Union[str, None] = "0004_drop_cod_network"
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
