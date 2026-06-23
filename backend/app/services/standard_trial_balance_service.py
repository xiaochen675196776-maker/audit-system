"""标准科目余额表数据查看服务 — 批次列表 / 树形视图 / 明细查询"""

import uuid
import logging
from datetime import datetime
from decimal import Decimal
from collections import defaultdict

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.standard_trial_balance_import_batch import StandardTrialBalanceImportBatch
from app.models.standard_trial_balance_entry import StandardTrialBalanceEntry
from app.models.standard_account import StandardAccount

logger = logging.getLogger(__name__)


# ── 批次列表 ──────────────────────────────────────────

async def get_batches(
    db: AsyncSession,
    *,
    customer_label: str | None = None,
    fiscal_year: int | None = None,
    period: int | None = None,
    import_start: datetime | None = None,
    import_end: datetime | None = None,
) -> list[dict]:
    """查询导入批次列表，支持按客户标识、年度、期间、导入时间筛选。"""
    # 先查询批次，并子查询统计条目数
    query = select(
        StandardTrialBalanceImportBatch,
        func.count(StandardTrialBalanceEntry.id).label("entry_count"),
    ).outerjoin(
        StandardTrialBalanceEntry,
        StandardTrialBalanceEntry.batch_id == StandardTrialBalanceImportBatch.id,
    )

    if customer_label:
        query = query.where(
            StandardTrialBalanceImportBatch.customer_label.ilike(f"%{customer_label}%")
        )
    if fiscal_year is not None:
        query = query.where(StandardTrialBalanceImportBatch.fiscal_year == fiscal_year)
    if period is not None:
        query = query.where(StandardTrialBalanceImportBatch.period == period)
    if import_start is not None:
        query = query.where(StandardTrialBalanceImportBatch.created_at >= import_start)
    if import_end is not None:
        query = query.where(StandardTrialBalanceImportBatch.created_at <= import_end)

    query = query.group_by(StandardTrialBalanceImportBatch.id)
    query = query.order_by(StandardTrialBalanceImportBatch.created_at.desc())

    result = await db.execute(query)
    rows = result.all()

    batches = []
    for batch, entry_count in rows:
        batches.append({
            "id": batch.id,
            "file_name": batch.file_name,
            "customer_label": batch.customer_label,
            "source_label": batch.source_label,
            "fiscal_year": batch.fiscal_year,
            "period": batch.period,
            "status": batch.status,
            "entry_count": entry_count,
            "created_at": batch.created_at,
            "updated_at": batch.updated_at,
        })

    return batches


# ── 树形视图 ──────────────────────────────────────────

async def get_tree(
    db: AsyncSession,
    *,
    batch_id: uuid.UUID | None = None,
    fiscal_year: int | None = None,
    period: int | None = None,
    only_with_amounts: bool = False,
) -> tuple[list[dict], int]:
    """
    构建标准科目余额表树形视图。

    聚合规则：
    - 末级科目：直接从 standard_trial_balance_entries 取金额
    - 父级科目：动态汇总所有子孙末级科目的金额
    - 不读取 raw_rows 中的父级导入金额

    返回: (tree_nodes, total_nodes)
    """
    # 1. 查询所有启用标准科目，按 account_code 排序
    result = await db.execute(
        select(StandardAccount)
        .where(StandardAccount.is_active == True)
        .order_by(StandardAccount.account_code)
    )
    all_accounts = result.scalars().all()

    if not all_accounts:
        return [], 0

    # 建立 id → account 索引
    id_to_account: dict[uuid.UUID, StandardAccount] = {sa.id: sa for sa in all_accounts}

    # 建立 parent_id → children 索引
    children_map: dict[uuid.UUID | None, list[StandardAccount]] = defaultdict(list)
    for sa in all_accounts:
        children_map[sa.parent_id].append(sa)

    # 2. 查询所有符合条件的末级条目，按标准科目 ID 汇总
    entry_query = select(StandardTrialBalanceEntry)
    if batch_id is not None:
        entry_query = entry_query.where(StandardTrialBalanceEntry.batch_id == batch_id)
    if fiscal_year is not None:
        entry_query = entry_query.where(StandardTrialBalanceEntry.fiscal_year == fiscal_year)
    if period is not None:
        entry_query = entry_query.where(StandardTrialBalanceEntry.period == period)

    result = await db.execute(entry_query)
    entries = result.scalars().all()

    # 按 standard_account_id 汇总六列金额 + 条目数
    account_amounts: dict[uuid.UUID, dict] = defaultdict(lambda: {
        "opening_debit": Decimal("0"),
        "opening_credit": Decimal("0"),
        "current_debit": Decimal("0"),
        "current_credit": Decimal("0"),
        "ending_debit": Decimal("0"),
        "ending_credit": Decimal("0"),
        "entry_count": 0,
    })

    for entry in entries:
        agg = account_amounts[entry.standard_account_id]
        agg["opening_debit"] += entry.opening_debit
        agg["opening_credit"] += entry.opening_credit
        agg["current_debit"] += entry.current_debit
        agg["current_credit"] += entry.current_credit
        agg["ending_debit"] += entry.ending_debit
        agg["ending_credit"] += entry.ending_credit
        agg["entry_count"] += 1

    # 3. 递归构建树节点
    total_nodes = 0

    def _has_amounts(amounts: dict) -> bool:
        """判断是否有非零金额"""
        return (
            amounts["opening_debit"] != 0
            or amounts["opening_credit"] != 0
            or amounts["current_debit"] != 0
            or amounts["current_credit"] != 0
            or amounts["ending_debit"] != 0
            or amounts["ending_credit"] != 0
        )

    def _build_node(sa: StandardAccount) -> dict | None:
        """递归构建单个树节点。返回 None 表示该节点应被过滤掉（only_with_amounts 且无金额）。"""
        nonlocal total_nodes

        # 递归构建子节点
        child_nodes = []
        for child_sa in children_map.get(sa.id, []):
            child_node = _build_node(child_sa)
            if child_node is not None:
                child_nodes.append(child_node)

        has_children = len(child_nodes) > 0

        # 汇总金额：自身叶子条目 + 所有子节点
        aggregated = {
            "opening_debit": Decimal("0"),
            "opening_credit": Decimal("0"),
            "current_debit": Decimal("0"),
            "current_credit": Decimal("0"),
            "ending_debit": Decimal("0"),
            "ending_credit": Decimal("0"),
            "entry_count": 0,
        }

        # 如果该科目是叶子且有直接条目，加上自身金额
        own_amounts = account_amounts.get(sa.id)
        if own_amounts:
            for key in aggregated:
                aggregated[key] += own_amounts[key]

        # 累加所有子节点金额
        for child in child_nodes:
            for key in ("opening_debit", "opening_credit", "current_debit",
                         "current_credit", "ending_debit", "ending_credit", "entry_count"):
                aggregated[key] += child["aggregated"][key]

        # 若启用 only_with_amounts 且自身及所有子孙都无金额，过滤掉
        if only_with_amounts and not _has_amounts(aggregated):
            return None

        total_nodes += 1

        node = {
            "standard_account_id": sa.id,
            "account_code": sa.account_code,
            "account_name": sa.account_name,
            "account_category": sa.account_category,
            "balance_direction": sa.balance_direction,
            "level": sa.level,
            "is_leaf": sa.is_leaf,
            "opening_debit": aggregated["opening_debit"],
            "opening_credit": aggregated["opening_credit"],
            "current_debit": aggregated["current_debit"],
            "current_credit": aggregated["current_credit"],
            "ending_debit": aggregated["ending_debit"],
            "ending_credit": aggregated["ending_credit"],
            "children": child_nodes,
            "entry_count": aggregated["entry_count"],
            "has_children": has_children,
            # 内部使用，构建完成后移除
            "aggregated": aggregated,
        }
        return node

    # 从根节点（parent_id 为空）开始构建
    root_nodes = []
    for root_sa in children_map.get(None, []):
        node = _build_node(root_sa)
        if node is not None:
            root_nodes.append(node)

    # 清理内部字段 aggregated
    def _clean_aggregated(nodes: list[dict]):
        for n in nodes:
            n.pop("aggregated", None)
            _clean_aggregated(n.get("children", []))

    _clean_aggregated(root_nodes)

    return root_nodes, total_nodes


# ── 明细列表 ──────────────────────────────────────────

async def get_entries(
    db: AsyncSession,
    *,
    batch_id: uuid.UUID | None = None,
    standard_account_code: str | None = None,
    client_account_code: str | None = None,
    fiscal_year: int | None = None,
    period: int | None = None,
) -> list[StandardTrialBalanceEntry]:
    """
    查询标准科目余额表明细列表，支持多条件筛选。

    返回完整 StandardTrialBalanceEntry 对象，包含标准科目快照、
    客户原始科目代码/名称、六个标准金额字段。
    """
    query = select(StandardTrialBalanceEntry)

    if batch_id is not None:
        query = query.where(StandardTrialBalanceEntry.batch_id == batch_id)
    if standard_account_code:
        query = query.where(
            StandardTrialBalanceEntry.standard_account_code_snapshot.ilike(
                f"%{standard_account_code}%"
            )
        )
    if client_account_code:
        query = query.where(
            StandardTrialBalanceEntry.client_account_code.ilike(f"%{client_account_code}%")
        )
    if fiscal_year is not None:
        query = query.where(StandardTrialBalanceEntry.fiscal_year == fiscal_year)
    if period is not None:
        query = query.where(StandardTrialBalanceEntry.period == period)

    query = query.order_by(
        StandardTrialBalanceEntry.standard_account_code_snapshot,
        StandardTrialBalanceEntry.fiscal_year,
        StandardTrialBalanceEntry.period,
    )

    result = await db.execute(query)
    return list(result.scalars().all())
