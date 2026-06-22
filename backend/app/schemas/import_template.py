"""导入模板 Schema — 创建/更新/响应/测试"""

import uuid
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


VALID_DATA_TYPES = ("trial_balance", "journal", "subsidiary")


def _validate_data_type(v: str) -> str:
    if v not in VALID_DATA_TYPES:
        raise ValueError(f"不支持的数据类型: {v}，可选: trial_balance / journal / subsidiary")
    return v


# ── 创建 ──────────────────────────────────────────────

class TemplateCreate(BaseModel):
    """手动创建模板"""
    name: str = Field(..., min_length=1, max_length=200, description="模板名称")
    data_type: str = Field(..., description="数据类型")
    source_label: str | None = Field(None, max_length=200, description="来源标识")
    is_active: bool = Field(True, description="是否启用")
    header_signature: dict | None = Field(None, description="表头特征签名")
    parse_config: dict = Field(default_factory=dict, description="解析配置")
    column_rules: dict = Field(default_factory=dict, description="映射规则")
    default_values: dict | None = Field(None, description="默认值")

    @field_validator("data_type")
    @classmethod
    def check_data_type(cls, v: str) -> str:
        return _validate_data_type(v)


# ── 更新 ──────────────────────────────────────────────

class TemplateUpdate(BaseModel):
    """更新模板"""
    name: str | None = Field(None, min_length=1, max_length=200)
    source_label: str | None = Field(None, max_length=200)
    is_active: bool | None = Field(None)
    parse_config: dict | None = Field(None)
    column_rules: dict | None = Field(None)
    default_values: dict | None = Field(None)


# ── 响应 ──────────────────────────────────────────────

class TemplateResponse(BaseModel):
    """模板详情响应"""
    id: uuid.UUID
    name: str
    data_type: str
    source_label: str | None
    is_active: bool
    header_signature: dict | None
    parse_config: dict
    column_rules: dict
    default_values: dict | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TemplateListResponse(BaseModel):
    """模板列表响应"""
    items: list[TemplateResponse]
    total: int


# ── 样本生成 ──────────────────────────────────────────

class FromSampleRequest(BaseModel):
    """从样本文件生成模板草稿"""
    data_type: str = Field(..., description="数据类型")
    name: str | None = Field(None, max_length=200, description="模板名称（可选）")
    save: bool = Field(False, description="是否直接保存（默认仅返回草稿）")

    @field_validator("data_type")
    @classmethod
    def check_data_type(cls, v: str) -> str:
        return _validate_data_type(v)


# ── 测试结果 ──────────────────────────────────────────

class TemplateTestResult(BaseModel):
    """模板测试结果"""
    applicable: bool = Field(..., description="是否可套用")
    hit_fields: list[str] = Field(default_factory=list, description="命中字段")
    missing_fields: list[str] = Field(default_factory=list, description="缺失字段")
    warnings: list[str] = Field(default_factory=list, description="重复/冲突警告")
    column_mapping_v2: dict[str, str] = Field(
        default_factory=dict,
        description="建议的列 ID 映射 {col_001: standard_field, ...}"
    )
    message: str = Field("", description="中文结果说明")
