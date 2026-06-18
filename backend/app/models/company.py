"""被审计单位模型"""

import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="公司名称")
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, comment="公司编码")
    tax_id: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="税号")
    address: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="地址")
    industry: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="行业")

    # 多租户预留
    firm_id: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True, comment="事务所ID（预留）"
    )

    is_active: Mapped[bool] = mapped_column(default=True, comment="是否启用")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # 关联
    accounts: Mapped[list["Account"]] = relationship(back_populates="company", lazy="selectin")
    trial_balances: Mapped[list["TrialBalance"]] = relationship(back_populates="company", lazy="selectin")
    journal_entries: Mapped[list["JournalEntry"]] = relationship(back_populates="company", lazy="selectin")
    subsidiary_ledgers: Mapped[list["SubsidiaryLedger"]] = relationship(back_populates="company", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Company {self.code} {self.name}>"
