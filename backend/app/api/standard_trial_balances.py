"""标准科目余额表数据查看 API — 批次列表 / 树形视图 / 明细查询 / 删除"""

import uuid
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.standard_trial_balance import (
    BatchFilterParams,
    BatchListResponse,
    BatchListItem,
    TreeResponse,
    TreeNodeResponse,
    EntryFilterParams,
    TrialBalanceEntryResponse,
    TrialBalanceEntryListResponse,
)
from app.services.standard_trial_balance_service import (
    get_batches,
    get_tree,
    get_entries,
    delete_batch,
)

router = APIRouter(prefix="/standard-trial-balances", tags=["科目余额表数据查看"])
logger = logging.getLogger(__name__)


# ── 批次列表 ──────────────────────────────────────────

@router.get("/batches", response_model=BatchListResponse)
async def list_batches(
    customer_label: str | None = Query(None, description="客户标识（模糊匹配）"),
    fiscal_year: int | None = Query(None, description="会计年度"),
    period: int | None = Query(None, ge=1, le=12, description="会计期间"),
    import_start: datetime | None = Query(None, description="导入时间起（ISO 8601）"),
    import_end: datetime | None = Query(None, description="导入时间止（ISO 8601）"),
    db: AsyncSession = Depends(get_db),
):
    """
    获取标准化导入批次列表。

    支持按客户标识、年度、期间和导入时间范围筛选。
    每个批次返回条目数量。
    """
    items = await get_batches(
        db,
        customer_label=customer_label,
        fiscal_year=fiscal_year,
        period=period,
        import_start=import_start,
        import_end=import_end,
    )
    return BatchListResponse(
        items=[BatchListItem(**item) for item in items],
        total=len(items),
    )


# ── 树形视图 ──────────────────────────────────────────

@router.get("/tree", response_model=TreeResponse)
async def view_tree(
    batch_id: uuid.UUID | None = Query(None, description="按批次筛选"),
    fiscal_year: int | None = Query(None, description="会计年度"),
    period: int | None = Query(None, ge=1, le=12, description="会计期间"),
    only_with_amounts: bool = Query(False, description="只看有余额/发生额的科目"),
    db: AsyncSession = Depends(get_db),
):
    """
    获取标准科目余额表树形视图。

    - 按标准科目层级展示。
    - 父级节点金额由子级末级科目动态汇总。
    - 支持只看有余额/发生额的科目。
    """
    nodes, total_nodes = await get_tree(
        db,
        batch_id=batch_id,
        fiscal_year=fiscal_year,
        period=period,
        only_with_amounts=only_with_amounts,
    )
    return TreeResponse(
        items=[TreeNodeResponse(**node) for node in nodes],
        total_nodes=total_nodes,
    )


# ── 明细列表 ──────────────────────────────────────────

@router.get("/entries", response_model=TrialBalanceEntryListResponse)
async def list_entries(
    batch_id: uuid.UUID | None = Query(None, description="按批次筛选"),
    standard_account_code: str | None = Query(None, description="标准科目代码（模糊匹配）"),
    client_account_code: str | None = Query(None, description="客户科目代码（模糊匹配）"),
    fiscal_year: int | None = Query(None, description="会计年度"),
    period: int | None = Query(None, ge=1, le=12, description="会计期间"),
    db: AsyncSession = Depends(get_db),
):
    """
    获取标准科目余额表明细列表。

    展示标准科目快照、客户原始科目代码和名称、六个标准金额字段。
    支持按标准科目、客户科目、年度、期间筛选。
    """
    entries = await get_entries(
        db,
        batch_id=batch_id,
        standard_account_code=standard_account_code,
        client_account_code=client_account_code,
        fiscal_year=fiscal_year,
        period=period,
    )
    return TrialBalanceEntryListResponse(
        items=[TrialBalanceEntryResponse.model_validate(e) for e in entries],
        total=len(entries),
    )


# ── 删除批次 ──────────────────────────────────────────

@router.delete("/batches/{batch_id}")
async def delete_imported_batch(
    batch_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    删除当前导入批次及关联数据。

    删除范围：
    - entries（标准化明细）
    - raw_rows（原始行快照）
    - batch 本身

    不删除：standard_accounts（标准科目主数据）、client_account_mappings（映射经验）。
    """
    result = await delete_batch(db, batch_id=batch_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"批次 {batch_id} 不存在")
    await db.commit()
    return result
