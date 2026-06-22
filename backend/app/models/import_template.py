"""导入模板 ORM 模型 — 保存解析+映射规则，跨单位复用"""

import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, JSON, func, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ImportTemplate(Base):
    """导入模板 — 记录解析规则 + 字段映射 + 默认值"""

    __tablename__ = "import_templates"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    name: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="模板名称"
    )
    data_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True,
        comment="数据类型: trial_balance / journal / subsidiary"
    )
    source_label: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="来源标识（财务软件名称/版本）"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, index=True, comment="是否启用"
    )

    # 表头特征签名（用于模板匹配）
    header_signature: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment="表头特征签名: {col_001: '凭证号', col_002: '凭证日期', ...}"
    )

    # 解析配置
    parse_config: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict,
        comment="解析配置: {header_row, data_start_row, encoding, ...}"
    )

    # 字段映射规则（列 ID → 标准字段 / 辅助字段名 / ignore）
    column_rules: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict,
        comment="映射规则: {col_001: 'voucher_no', col_010: 'custom_remark', col_020: 'ignore'}"
    )

    # 默认值（年度/期间等）
    default_values: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment="默认值: {fiscal_year: 2024, period: 1}"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<ImportTemplate {self.name} [{self.data_type}] active={self.is_active}>"
