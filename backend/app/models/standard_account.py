"""标准科目模型 — 全局统一科目表模板"""

import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class StandardAccount(Base):
    """标准科目表 — 全局统一科目模板，从用户导入的科目余额表 Excel 全量同步"""

    __tablename__ = "standard_accounts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    account_code: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, comment="科目代码"
    )
    account_name: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="科目名称"
    )
    account_category: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="科目类别: asset/liability/equity/revenue/expense/profit_loss"
    )
    balance_direction: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="余额方向: debit/credit"
    )
    level: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="科目层级（1起）"
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("standard_accounts.id", ondelete="SET NULL"),
        nullable=True, comment="上级科目ID（自引用）"
    )
    is_leaf: Mapped[bool] = mapped_column(
        Boolean, default=True, comment="是否末级科目"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, index=True, comment="是否启用"
    )
    source_row_index: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="导入来源行序号"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<StandardAccount {self.account_code} {self.account_name} active={self.is_active}>"
