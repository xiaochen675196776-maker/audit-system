"""科目余额表模型"""

import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Integer, DateTime, ForeignKey, Numeric, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class TrialBalance(Base):
    """科目余额表 — 按期间汇总的各科目期初/本期/期末余额"""

    __tablename__ = "trial_balances"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False, comment="会计年度")
    period: Mapped[int] = mapped_column(Integer, nullable=False, comment="会计期间（1-12月）")

    account_code: Mapped[str] = mapped_column(String(50), nullable=False, comment="科目编码")
    account_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="科目名称")
    account_level: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="科目级别")

    # 期初余额
    opening_debit: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), default=0, comment="期初借方余额"
    )
    opening_credit: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), default=0, comment="期初贷方余额"
    )

    # 本期发生额
    current_debit: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), default=0, comment="本期借方发生额"
    )
    current_credit: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), default=0, comment="本期贷方发生额"
    )

    # 期末余额
    ending_debit: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), default=0, comment="期末借方余额"
    )
    ending_credit: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), default=0, comment="期末贷方余额"
    )

    # 灵活扩展（不同财务软件导出的额外列）
    extra_fields: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="额外字段")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # 关联
    company: Mapped["Company"] = relationship(back_populates="trial_balances")

    def __repr__(self) -> str:
        return f"<TrialBalance {self.fiscal_year}-{self.period} {self.account_code}>"
