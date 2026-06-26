"""客户科目映射经验 ORM 模型 — 记录客户科目到标准科目的确认映射"""

import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Boolean, Float, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ClientAccountMapping(Base):
    """客户科目映射经验 — 记录用户确认过的客户科目到标准科目的映射"""

    __tablename__ = "client_account_mappings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    data_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True,
        comment="数据类型: trial_balance / journal / subsidiary"
    )
    customer_label: Mapped[str | None] = mapped_column(
        String(200), nullable=True, index=True, comment="客户标识（被审计单位名称/代码）"
    )
    source_label: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="来源标识（财务软件名称/版本）"
    )

    # 客户科目信息
    client_account_code: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True, comment="客户科目代码"
    )
    client_account_name: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="客户科目名称（原始）"
    )
    normalized_client_account_name: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="客户科目名称（标准化后）"
    )
    client_account_full_path: Mapped[str | None] = mapped_column(
        String(2000), nullable=True, comment="客户科目完整路径（继承式映射用）"
    )

    # 映射到标准科目
    standard_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("standard_accounts.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="标准科目ID"
    )
    standard_account_code_snapshot: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="映射时的标准科目代码快照"
    )
    standard_account_name_snapshot: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="映射时的标准科目名称快照"
    )

    # 置信度与范围
    confidence: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, comment="置信度 0-1"
    )
    scope: Mapped[str] = mapped_column(
        String(50), nullable=False, default="global",
        comment="经验范围: global / company"
    )
    mapping_kind: Mapped[str] = mapped_column(
        String(50), nullable=False, default="anchor",
        comment="映射类型: anchor(锚点) / override(显式覆盖); 不得用于普通 inherited 行"
    )

    # 使用统计
    usage_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="使用次数"
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="最后使用时间"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True, comment="是否启用"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"<ClientAccountMapping "
            f"{self.client_account_code or '?'} → {self.standard_account_code_snapshot or '?'} "
            f"[{self.data_type}] active={self.is_active}>"
        )
