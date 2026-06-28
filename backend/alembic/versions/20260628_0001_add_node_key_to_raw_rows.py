"""add node key traceability to raw rows

Revision ID: 20260628_0001
Revises: 20260626_0001
Create Date: 2026-06-28 00:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260628_0001"
down_revision: Union[str, None] = "20260626_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("standard_trial_balance_raw_rows") as batch_op:
        batch_op.add_column(sa.Column("node_key", sa.String(100), nullable=True))
        batch_op.add_column(sa.Column("anchor_node_key", sa.String(100), nullable=True))
        batch_op.create_index("ix_standard_trial_balance_raw_rows_node_key", ["node_key"])


def downgrade() -> None:
    with op.batch_alter_table("standard_trial_balance_raw_rows") as batch_op:
        batch_op.drop_index("ix_standard_trial_balance_raw_rows_node_key")
        batch_op.drop_column("anchor_node_key")
        batch_op.drop_column("node_key")
