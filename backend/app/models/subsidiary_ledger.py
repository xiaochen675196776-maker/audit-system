"""辅助明细账模型"""

import uuid
from datetime import datetime, date
from decimal import Decimal
from sqlalchemy import String, Integer, Date, DateTime, ForeignKey, Numeric, Text, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class SubsidiaryLedger(Base):
    """辅助明细账 — 带辅助核算维度的明细账务数据"""

    __tablename__ = "subsidiary_ledgers"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False, comment="会计年度")
    period: Mapped[int] = mapped_column(Integer, nullable=False, comment="会计期间（1-12月）")

    voucher_no: Mapped[str] = mapped_column(String(50), nullable=False, comment="凭证号")
    voucher_date: Mapped[date] = mapped_column(Date, nullable=False, comment="凭证日期")
    summary: Mapped[str] = mapped_column(Text, nullable=False, comment="摘要")

    account_code: Mapped[str] = mapped_column(String(50), nullable=False, comment="科目编码")
    account_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="科目名称")

    debit_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), default=0, comment="借方金额"
    )
    credit_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), default=0, comment="贷方金额"
    )

    # 辅助核算维度
    auxiliary_type: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="辅助核算类型"
    )
    auxiliary_code: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="辅助核算编码"
    )
    auxiliary_name: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="辅助核算名称"
    )

    attachment_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="附件数")

    # 灵活扩展（不同财务软件或用户自定义映射的额外列）
    extra_fields: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="额外字段")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # 关联
    company: Mapped["Company"] = relationship(back_populates="subsidiary_ledgers")

    def __repr__(self) -> str:
        return f"<SubsidiaryLedger {self.auxiliary_type}:{self.auxiliary_code} {self.account_code}>"
