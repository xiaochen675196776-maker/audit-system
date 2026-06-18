"""科目字典模型"""

import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False, comment="科目编码")
    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="科目名称")
    level: Mapped[int] = mapped_column(Integer, default=1, comment="科目级别（1/2/3级）")
    parent_code: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="上级科目编码")
    direction: Mapped[str] = mapped_column(String(10), default="debit", comment="余额方向：debit借方/credit贷方")
    category: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="科目类别")
    is_active: Mapped[bool] = mapped_column(default=True, comment="是否启用")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # 关联
    company: Mapped["Company"] = relationship(back_populates="accounts")

    def __repr__(self) -> str:
        return f"<Account {self.code} {self.name}>"
