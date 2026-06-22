"""add field_mapping_experiences table

Revision ID: 20260622_0001
Revises: 514f9f31aab1
Create Date: 2026-06-22 18:00:00
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '20260622_0001'
down_revision: Union[str, None] = '514f9f31aab1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Table created by Base.metadata.create_all() at runtime;
    # migration kept for tracking purposes.
    pass


def downgrade() -> None:
    pass
