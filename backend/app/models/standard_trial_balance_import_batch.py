"""标准化导入批次 ORM 模型 — 记录每次科目余额表标准化导入的批次信息"""

import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, JSON, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class StandardTrialBalanceImportBatch(Base):
    """标准化导入批次 — 每次标准化导入一条批次记录"""

    __tablename__ = "standard_trial_balance_import_batches"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    file_name: Mapped[str] = mapped_column(
        String(500), nullable=False, comment="原始文件名"
    )
    customer_label: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="客户标识（被审计单位名称/代码）"
    )
    source_label: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="来源标识（财务软件名称/版本）"
    )
    fiscal_year: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="会计年度"
    )
    period: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="会计期间（1-12月）"
    )

    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="draft", index=True,
        comment="批次状态: draft / processing / completed / failed"
    )

    # 配置快照
    field_mapping: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="字段映射配置"
    )
    amount_mapping_config: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="金额映射与拆分配置"
    )
    hierarchy_config: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="层级识别与校验配置"
    )

    # 结果汇总
    warnings: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="警告信息汇总"
    )
    errors: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="错误信息汇总"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"<StandardTrialBalanceImportBatch {self.file_name} "
            f"[{self.status}] {self.fiscal_year}-{self.period}>"
        )
