"""标准化导入原始行快照 ORM 模型 — 保存每行客户原始数据的完整快照"""

import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, JSON, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class StandardTrialBalanceRawRow(Base):
    """原始行快照 — 保存导入时每行客户原始数据的完整快照，用于追溯和复查"""

    __tablename__ = "standard_trial_balance_raw_rows"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("standard_trial_balance_import_batches.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属批次ID"
    )
    row_index: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="原始行序号（0起）"
    )

    # 原始数据完整快照
    raw_values: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict, comment="原始行全部列值"
    )

    # 客户科目信息
    client_account_code: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="客户科目代码"
    )
    client_account_name: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="客户科目名称"
    )
    client_balance_direction: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="客户科目余额方向"
    )
    client_account_category: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="客户科目类别"
    )

    # 层级识别结果
    detected_level: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="检测到的科目层级"
    )
    parent_raw_row_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("standard_trial_balance_raw_rows.id", ondelete="SET NULL"),
        nullable=True, comment="上级行ID（自引用，用于父子层级）"
    )
    is_leaf: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="是否末级真实金额行"
    )

    # 映射状态
    mapped_standard_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("standard_accounts.id", ondelete="SET NULL"),
        nullable=True, comment="映射到的标准科目ID"
    )
    mapping_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending",
        comment="映射状态: pending / mapped / unmapped / ignored"
    )

    # ANCHOR-INHERITANCE-MAPPING：映射角色与追溯字段
    mapping_role: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
        comment="映射角色: structural_summary/anchor/inherited/breakpoint/explicit_override/unresolved/ignored"
    )
    mapping_mode: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
        comment="映射模式: direct_auto/direct_confirmed/inherited_ancestor/override_confirmed/none"
    )
    mapping_source: Mapped[str | None] = mapped_column(
        String(80), nullable=True,
        comment="映射来源: company_history/code_exact/name_exact/semantic_alias/inherited_ancestor/user_override..."
    )
    mapping_anchor_raw_row_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("standard_trial_balance_raw_rows.id", ondelete="SET NULL"),
        nullable=True, comment="追溯继承自哪个原始行"
    )
    inheritance_reason: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="为什么允许继承"
    )
    inheritance_break_reason: Mapped[str | None] = mapped_column(
        String(80), nullable=True, comment="为什么中断继承"
    )
    requires_manual_confirmation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="是否需要人工确认"
    )

    # 行级警告
    warnings: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="行级警告信息"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"<StandardTrialBalanceRawRow batch={self.batch_id} row={self.row_index} "
            f"status={self.mapping_status}>"
        )
