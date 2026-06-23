"""add standard trial balance model foundation tables

Revision ID: 20260622_0002
Revises: 20260622_0001
Create Date: 2026-06-22 20:00:00

新增 5 张表：
- standard_accounts          标准科目表
- client_account_mappings    客户科目映射经验
- standard_trial_balance_import_batches  标准化导入批次
- standard_trial_balance_raw_rows       原始行快照
- standard_trial_balance_entries        标准科目余额表明细
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '20260622_0002'
down_revision: Union[str, None] = '20260622_0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── standard_accounts ──────────────────────────────
    op.create_table(
        "standard_accounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("account_code", sa.String(50), unique=True, nullable=False),
        sa.Column("account_name", sa.String(200), nullable=False),
        sa.Column("account_category", sa.String(50), nullable=True),
        sa.Column("balance_direction", sa.String(20), nullable=True),
        sa.Column("level", sa.Integer(), nullable=True),
        sa.Column("parent_id", sa.Uuid(),
                  sa.ForeignKey("standard_accounts.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("is_leaf", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("source_row_index", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_sa_is_active", "standard_accounts", ["is_active"])

    # ── client_account_mappings ────────────────────────
    op.create_table(
        "client_account_mappings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("data_type", sa.String(50), nullable=False),
        sa.Column("customer_label", sa.String(200), nullable=True),
        sa.Column("source_label", sa.String(200), nullable=True),
        sa.Column("client_account_code", sa.String(100), nullable=True),
        sa.Column("client_account_name", sa.String(500), nullable=True),
        sa.Column("normalized_client_account_name", sa.String(500), nullable=True),
        sa.Column("standard_account_id", sa.Uuid(),
                  sa.ForeignKey("standard_accounts.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("standard_account_code_snapshot", sa.String(50), nullable=True),
        sa.Column("standard_account_name_snapshot", sa.String(200), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("scope", sa.String(50), nullable=False, server_default="global"),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_cam_data_type", "client_account_mappings", ["data_type"])
    op.create_index("ix_cam_customer_label", "client_account_mappings", ["customer_label"])
    op.create_index("ix_cam_client_account_code", "client_account_mappings", ["client_account_code"])
    op.create_index("ix_cam_standard_account_id", "client_account_mappings", ["standard_account_id"])
    op.create_index("ix_cam_is_active", "client_account_mappings", ["is_active"])

    # ── standard_trial_balance_import_batches ──────────
    op.create_table(
        "standard_trial_balance_import_batches",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("file_name", sa.String(500), nullable=False),
        sa.Column("customer_label", sa.String(200), nullable=True),
        sa.Column("source_label", sa.String(200), nullable=True),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("period", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="draft"),
        sa.Column("field_mapping", sa.JSON(), nullable=True),
        sa.Column("amount_mapping_config", sa.JSON(), nullable=True),
        sa.Column("hierarchy_config", sa.JSON(), nullable=True),
        sa.Column("warnings", sa.JSON(), nullable=True),
        sa.Column("errors", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_stbib_status", "standard_trial_balance_import_batches", ["status"])

    # ── standard_trial_balance_raw_rows ────────────────
    op.create_table(
        "standard_trial_balance_raw_rows",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("batch_id", sa.Uuid(),
                  sa.ForeignKey("standard_trial_balance_import_batches.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("raw_values", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("client_account_code", sa.String(100), nullable=True),
        sa.Column("client_account_name", sa.String(500), nullable=True),
        sa.Column("client_balance_direction", sa.String(20), nullable=True),
        sa.Column("client_account_category", sa.String(50), nullable=True),
        sa.Column("detected_level", sa.Integer(), nullable=True),
        sa.Column("parent_raw_row_id", sa.Uuid(),
                  sa.ForeignKey("standard_trial_balance_raw_rows.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("is_leaf", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("mapped_standard_account_id", sa.Uuid(),
                  sa.ForeignKey("standard_accounts.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("mapping_status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("warnings", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_stbrr_batch_id", "standard_trial_balance_raw_rows", ["batch_id"])

    # ── standard_trial_balance_entries ─────────────────
    op.create_table(
        "standard_trial_balance_entries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("batch_id", sa.Uuid(),
                  sa.ForeignKey("standard_trial_balance_import_batches.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("raw_row_id", sa.Uuid(),
                  sa.ForeignKey("standard_trial_balance_raw_rows.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("standard_account_id", sa.Uuid(),
                  sa.ForeignKey("standard_accounts.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("standard_account_code_snapshot", sa.String(50), nullable=False),
        sa.Column("standard_account_name_snapshot", sa.String(200), nullable=False),
        sa.Column("standard_account_category_snapshot", sa.String(50), nullable=True),
        sa.Column("standard_balance_direction_snapshot", sa.String(20), nullable=True),
        sa.Column("client_account_code", sa.String(100), nullable=True),
        sa.Column("client_account_name", sa.String(500), nullable=True),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("period", sa.Integer(), nullable=False),
        sa.Column("opening_debit", sa.Numeric(20, 2), nullable=False, server_default="0"),
        sa.Column("opening_credit", sa.Numeric(20, 2), nullable=False, server_default="0"),
        sa.Column("current_debit", sa.Numeric(20, 2), nullable=False, server_default="0"),
        sa.Column("current_credit", sa.Numeric(20, 2), nullable=False, server_default="0"),
        sa.Column("ending_debit", sa.Numeric(20, 2), nullable=False, server_default="0"),
        sa.Column("ending_credit", sa.Numeric(20, 2), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_stbe_batch_id", "standard_trial_balance_entries", ["batch_id"])
    op.create_index("ix_stbe_standard_account_id", "standard_trial_balance_entries", ["standard_account_id"])


def downgrade() -> None:
    op.drop_table("standard_trial_balance_entries")
    op.drop_table("standard_trial_balance_raw_rows")
    op.drop_table("standard_trial_balance_import_batches")
    op.drop_table("client_account_mappings")
    op.drop_table("standard_accounts")
