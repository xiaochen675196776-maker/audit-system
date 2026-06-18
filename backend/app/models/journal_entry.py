"""序时账（日记账）模型"""

import uuid
from datetime import datetime, date
from decimal import Decimal
from sqlalchemy import String, Integer, Date, DateTime, ForeignKey, Numeric, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class JournalEntry(Base):
    """序时账 — 按凭证逐笔记录的明细账务数据"""

    __tablename__ = "journal_entries"

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

    attachment_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="附件数")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # 关联
    company: Mapped["Company"] = relationship(back_populates="journal_entries")

    def __repr__(self) -> str:
        return f"<JournalEntry {self.voucher_no} {self.account_code}>"
