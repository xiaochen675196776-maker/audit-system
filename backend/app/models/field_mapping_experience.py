"""字段映射经验 ORM 模型 — 逐列历史确认经验，独立于整表模板"""

import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Boolean, Float, DateTime, JSON, func, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FieldMappingExperience(Base):
    """字段映射经验 — 记录用户确认过的逐列表头到标准字段映射"""

    __tablename__ = "field_mapping_experiences"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="被审计单位ID，空表示全局经验"
    )
    data_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True,
        comment="数据类型: trial_balance / journal / subsidiary"
    )

    # 预留扩展字段
    software_code: Mapped[str] = mapped_column(
        String(200), nullable=False, default="", comment="财务软件代码，预留"
    )
    layout_fingerprint: Mapped[str] = mapped_column(
        String(200), nullable=False, default="", comment="布局指纹，预留"
    )

    # 列信息
    source_header_original: Mapped[str] = mapped_column(
        String(500), nullable=False, comment="原始表头"
    )
    source_header_normalized: Mapped[str] = mapped_column(
        String(500), nullable=False, index=True, comment="标准化表头"
    )
    source_column_index: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="源列序号"
    )
    context_signature: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", comment="上下文签名（sha256）"
    )

    # 映射结果
    target_field: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="映射到的标准字段"
    )
    confirmation_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="user_confirmed",
        comment="user_confirmed / user_corrected / system_reused"
    )

    # 查找与统计
    lookup_key: Mapped[str] = mapped_column(
        String(200), nullable=False, index=True, comment="查找键（不唯一）"
    )
    use_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="使用次数"
    )
    success_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="成功导入次数"
    )
    conflict_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="被用户纠正次数"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True, comment="是否启用"
    )

    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="最后使用时间"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"<FieldMappingExperience "
            f"{self.source_header_normalized} → {self.target_field} "
            f"[{self.data_type}] active={self.is_active}>"
        )
