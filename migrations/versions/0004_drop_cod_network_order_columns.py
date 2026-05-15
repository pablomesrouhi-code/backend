"""Remove orders.cod_network_* (COD Network integration removed).

Revision ID: 0004_drop_cod_network
Revises: 0003_cod_network
Create Date: 2026-05-15

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_drop_cod_network"
down_revision: Union[str, None] = "0003_cod_network"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF EXISTS: safe if DB was never migrated to 0003 or columns were partially added.
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS cod_network_error")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS cod_network_sent_at")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS cod_network_lead_id")


def downgrade() -> None:
    op.add_column("orders", sa.Column("cod_network_lead_id", sa.BigInteger(), nullable=True))
    op.add_column(
        "orders",
        sa.Column("cod_network_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("orders", sa.Column("cod_network_error", sa.Text(), nullable=True))
