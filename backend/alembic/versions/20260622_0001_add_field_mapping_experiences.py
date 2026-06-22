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
    op.create_table(
        "field_mapping_experiences",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("company_id", sa.Uuid(), sa.ForeignKey("companies.id", ondelete="SET NULL"), nullable=True),
        sa.Column("data_type", sa.String(50), nullable=False),
        sa.Column("software_code", sa.String(200), nullable=False, server_default=""),
        sa.Column("layout_fingerprint", sa.String(200), nullable=False, server_default=""),
        sa.Column("source_header_original", sa.String(500), nullable=False),
        sa.Column("source_header_normalized", sa.String(500), nullable=False),
        sa.Column("source_column_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("context_signature", sa.String(64), nullable=False, server_default=""),
        sa.Column("target_field", sa.String(100), nullable=False),
        sa.Column("confirmation_type", sa.String(50), nullable=False, server_default="user_confirmed"),
        sa.Column("lookup_key", sa.String(200), nullable=False),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conflict_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_fme_company_id", "field_mapping_experiences", ["company_id"])
    op.create_index("ix_fme_data_type", "field_mapping_experiences", ["data_type"])
    op.create_index("ix_fme_src_header_norm", "field_mapping_experiences", ["source_header_normalized"])
    op.create_index("ix_fme_lookup_key", "field_mapping_experiences", ["lookup_key"])
    op.create_index("ix_fme_is_active", "field_mapping_experiences", ["is_active"])


def downgrade() -> None:
    op.drop_table("field_mapping_experiences")
