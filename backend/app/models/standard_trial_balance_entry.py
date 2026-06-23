"""标准科目余额表明细 ORM 模型 — 标准化后的科目余额表明细数据"""

import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Integer, DateTime, ForeignKey, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class StandardTrialBalanceEntry(Base):
    """标准科目余额表明细 — 按批次、标准科目、年度、期间存储标准化后的余额数据"""

    __tablename__ = "standard_trial_balance_entries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("standard_trial_balance_import_batches.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属批次ID"
    )
    raw_row_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("standard_trial_balance_raw_rows.id", ondelete="SET NULL"),
        nullable=True, comment="关联原始行快照ID"
    )

    # 标准科目快照（导入时的标准科目信息）
    standard_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("standard_accounts.id", ondelete="RESTRICT"),
        nullable=False, index=True, comment="标准科目ID"
    )
    standard_account_code_snapshot: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="导入时的标准科目代码快照"
    )
    standard_account_name_snapshot: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="导入时的标准科目名称快照"
    )
    standard_account_category_snapshot: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="导入时的科目类别快照"
    )
    standard_balance_direction_snapshot: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="导入时的余额方向快照"
    )

    # 客户科目信息
    client_account_code: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="客户科目代码"
    )
    client_account_name: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="客户科目名称"
    )

    # 期间信息
    fiscal_year: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="会计年度"
    )
    period: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="会计期间（1-12月）"
    )

    # 金额六列（标准借贷）
    opening_debit: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), default=0, comment="期初借方余额"
    )
    opening_credit: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), default=0, comment="期初贷方余额"
    )
    current_debit: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), default=0, comment="本期借方发生额"
    )
    current_credit: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), default=0, comment="本期贷方发生额"
    )
    ending_debit: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), default=0, comment="期末借方余额"
    )
    ending_credit: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), default=0, comment="期末贷方余额"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"<StandardTrialBalanceEntry "
            f"{self.standard_account_code_snapshot} "
            f"{self.fiscal_year}-{self.period}>"
        )
