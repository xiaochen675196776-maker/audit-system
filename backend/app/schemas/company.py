"""被审计单位 Schema"""

import uuid
from datetime import datetime
from pydantic import BaseModel, Field


class CompanyCreate(BaseModel):
    """创建被审计单位"""
    name: str = Field(..., min_length=1, max_length=200, description="公司名称")
    code: str = Field(..., min_length=1, max_length=50, description="公司编码")
    tax_id: str | None = Field(None, max_length=50, description="税号")
    address: str | None = Field(None, max_length=500, description="地址")
    industry: str | None = Field(None, max_length=100, description="行业")


class CompanyUpdate(BaseModel):
    """更新被审计单位"""
    name: str | None = Field(None, min_length=1, max_length=200, description="公司名称")
    tax_id: str | None = Field(None, max_length=50, description="税号")
    address: str | None = Field(None, max_length=500, description="地址")
    industry: str | None = Field(None, max_length=100, description="行业")
    is_active: bool | None = Field(None, description="是否启用")


class CompanyResponse(BaseModel):
    """被审计单位响应"""
    id: uuid.UUID
    name: str
    code: str
    tax_id: str | None
    address: str | None
    industry: str | None
    firm_id: uuid.UUID | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class CompanyListResponse(BaseModel):
    """被审计单位列表"""
    items: list[CompanyResponse]
    total: int
