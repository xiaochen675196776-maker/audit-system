"""add anchor inheritance mapping traceability columns

Revision ID: 20260626_0001
Revises: 20260622_0002
Create Date: 2026-06-26 22:55:00

ANCHOR-INHERITANCE-MAPPING 方案：
- raw row: mapping_role / mapping_mode / mapping_source / mapping_anchor_raw_row_id /
           inheritance_reason / inheritance_break_reason / requires_manual_confirmation
- entry:   mapping_mode_snapshot / mapping_source_snapshot /
           mapping_anchor_client_account_code_snapshot /
           mapping_anchor_client_account_name_snapshot
- client_account_mapping: client_account_full_path / mapping_kind
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '20260626_0001'
down_revision: Union[str, None] = '20260622_0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── raw rows 追溯字段 ──
    with op.batch_alter_table("standard_trial_balance_raw_rows") as batch_op:
        batch_op.add_column(sa.Column("mapping_role", sa.String(50), nullable=True))
        batch_op.add_column(sa.Column("mapping_mode", sa.String(50), nullable=True))
        batch_op.add_column(sa.Column("mapping_source", sa.String(80), nullable=True))
        batch_op.add_column(
            sa.Column(
                "mapping_anchor_raw_row_id",
                sa.Uuid(),
                sa.ForeignKey("standard_trial_balance_raw_rows.id", ondelete="SET NULL"),
                nullable=True,
            )
        )
        batch_op.add_column(sa.Column("inheritance_reason", sa.String(500), nullable=True))
        batch_op.add_column(sa.Column("inheritance_break_reason", sa.String(80), nullable=True))
        batch_op.add_column(
            sa.Column(
                "requires_manual_confirmation",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )
        batch_op.create_index(
            "ix_stbrr_mapping_anchor_raw_row_id",
            ["mapping_anchor_raw_row_id"],
        )

    # ── entry 快照字段 ──
    with op.batch_alter_table("standard_trial_balance_entries") as batch_op:
        batch_op.add_column(sa.Column("mapping_mode_snapshot", sa.String(50), nullable=True))
        batch_op.add_column(sa.Column("mapping_source_snapshot", sa.String(80), nullable=True))
        batch_op.add_column(
            sa.Column(
                "mapping_anchor_client_account_code_snapshot",
                sa.String(100),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "mapping_anchor_client_account_name_snapshot",
                sa.String(500),
                nullable=True,
            )
        )

    # ── client_account_mapping 经验库扩展 ──
    with op.batch_alter_table("client_account_mappings") as batch_op:
        batch_op.add_column(sa.Column("client_account_full_path", sa.String(2000), nullable=True))
        batch_op.add_column(
            sa.Column(
                "mapping_kind",
                sa.String(50),
                nullable=False,
                server_default="anchor",
            )
        )
        batch_op.create_index("ix_cam_mapping_kind", ["mapping_kind"])


def downgrade() -> None:
    with op.batch_alter_table("client_account_mappings") as batch_op:
        batch_op.drop_index("ix_cam_mapping_kind")
        batch_op.drop_column("mapping_kind")
        batch_op.drop_column("client_account_full_path")

    with op.batch_alter_table("standard_trial_balance_entries") as batch_op:
        batch_op.drop_column("mapping_anchor_client_account_name_snapshot")
        batch_op.drop_column("mapping_anchor_client_account_code_snapshot")
        batch_op.drop_column("mapping_source_snapshot")
        batch_op.drop_column("mapping_mode_snapshot")

    with op.batch_alter_table("standard_trial_balance_raw_rows") as batch_op:
        batch_op.drop_index("ix_stbrr_mapping_anchor_raw_row_id")
        batch_op.drop_column("requires_manual_confirmation")
        batch_op.drop_column("inheritance_break_reason")
        batch_op.drop_column("inheritance_reason")
        batch_op.drop_column("mapping_anchor_raw_row_id")
        batch_op.drop_column("mapping_source")
        batch_op.drop_column("mapping_mode")
        batch_op.drop_column("mapping_role")
