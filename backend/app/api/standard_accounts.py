"""标准科目查询 API（系统内置主数据，只读）"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.standard_trial_balance import (
    StandardAccountResponse,
    StandardAccountListResponse,
)
from app.services.standard_account_service import (
    get_standard_accounts,
    get_standard_account,
)

router = APIRouter(prefix="/standard-accounts", tags=["标准科目表"])


# ── 查询列表 ──────────────────────────────────────────

@router.get("", response_model=StandardAccountListResponse)
async def list_standard_accounts(
    is_active: bool | None = Query(None, description="按启用状态筛选"),
    account_category: str | None = Query(None, description="按科目类别筛选"),
    balance_direction: str | None = Query(None, description="按余额方向筛选"),
    keyword: str | None = Query(None, description="按代码或名称搜索"),
    db: AsyncSession = Depends(get_db),
):
    """获取系统内置标准科目列表，支持按 is_active / account_category / balance_direction / keyword 筛选。标准科目为系统内置主数据，不由用户上传维护。"""
    items = await get_standard_accounts(
        db,
        is_active=is_active,
        account_category=account_category,
        balance_direction=balance_direction,
        keyword=keyword,
    )
    return StandardAccountListResponse(
        items=[StandardAccountResponse.model_validate(item) for item in items],
        total=len(items),
    )


# ── 查询详情 ──────────────────────────────────────────

@router.get("/{account_id}", response_model=StandardAccountResponse)
async def get_account(
    account_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """获取单个标准科目详情"""
    account = await get_standard_account(db, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="标准科目不存在")
    return StandardAccountResponse.model_validate(account)
