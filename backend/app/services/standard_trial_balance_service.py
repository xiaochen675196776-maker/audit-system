"""标准科目余额表数据查看服务 — 批次列表 / 树形视图 / 明细查询"""

import uuid
import logging
from datetime import datetime
from decimal import Decimal
from collections import defaultdict

from sqlalchemy import select, func, and_, delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.standard_trial_balance_import_batch import StandardTrialBalanceImportBatch
from app.models.standard_trial_balance_entry import StandardTrialBalanceEntry
from app.models.standard_trial_balance_raw_row import StandardTrialBalanceRawRow
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

def _empty_agg() -> dict:
    return {
        "opening_debit": Decimal("0"),
        "opening_credit": Decimal("0"),
        "current_debit": Decimal("0"),
        "current_credit": Decimal("0"),
        "ending_debit": Decimal("0"),
        "ending_credit": Decimal("0"),
        "entry_count": 0,
    }


def _add_amounts(target: dict, entry) -> None:
    target["opening_debit"] += entry.opening_debit
    target["opening_credit"] += entry.opening_credit
    target["current_debit"] += entry.current_debit
    target["current_credit"] += entry.current_credit
    target["ending_debit"] += entry.ending_debit
    target["ending_credit"] += entry.ending_credit
    target["entry_count"] += 1


def _sum_child_agg(target: dict, child: dict) -> None:
    for key in ("opening_debit", "opening_credit", "current_debit",
                 "current_credit", "ending_debit", "ending_credit", "entry_count"):
        target[key] += child[key]


def _append_unique_child(container: list[dict], child: dict) -> bool:
    """唯一追加子节点：同一父容器下同一 node_id 只能 append 一次。

    返回 True 表示新追加，False 表示已存在跳过。TASK-077：合成 client_group 每处理
    一条 entry 都会沿链把同一 group/entry 追加到父级 children，导致重复 node_id。
    """
    child_id = child.get("node_id")
    if child_id is None:
        container.append(child)
        return True
    if any(existing.get("node_id") == child_id for existing in container):
        return False
    container.append(child)
    return True


def _build_synthetic_client_group_path(
    *,
    client_code: str | None,
    client_name: str | None,
    standard_account_code: str,
    standard_account_name: str,
) -> list[dict]:
    """从客户科目代码和名称合成客户中间层路径。

    返回从上到下的 group 列表，不包含最终 leaf entry。
    每个元素包含 account_code, account_name, client_account_code, client_account_name。
    """
    if not client_code or not client_name:
        return []

    # 按分隔符切分客户名称
    separators = ["_", "-", "－", "—", "/", "\\"]
    segments = [client_name]
    for sep in separators:
        new_segments = []
        for seg in segments:
            new_segments.extend(seg.split(sep))
        segments = new_segments
    segments = [s for s in segments if s.strip()]

    if len(segments) <= 1:
        return []  # 只有一段，无需合成中间层

    # 跳过与标准科目名称重复的第一段
    start_index = 0
    std_name_canonical = standard_account_name.replace("减：", "").replace("加：", "").replace("其中：", "")
    if segments[0] == std_name_canonical or segments[0] == standard_account_code:
        start_index = 1

    # 如果跳过第一段后没有剩余段，返回空
    if start_index >= len(segments):
        return []

    # 研发支出特殊分组：前两段合并
    is_rd_special = False
    if len(segments) - start_index >= 2:
        if segments[start_index] == "研发支出" and segments[start_index + 1] in ["费用化支出", "资本化支出"]:
            is_rd_special = True

    # 只取中间层级（排除最后一段，最后一段是 entry 本身）
    end_index = len(segments) - 1  # 不包含最后一段
    if end_index <= start_index:
        return []  # 没有中间层级

    result = []
    current_name_parts = []

    for i in range(start_index, end_index):
        segment = segments[i]

        # 研发支出特殊分组：前两段合并为一个 group
        if is_rd_special and i == start_index:
            current_name_parts = [segments[start_index], segments[start_index + 1]]
            group_code = client_code[:6] if len(client_code) >= 6 else client_code
            group_name = "_".join(current_name_parts)
            result.append({
                "account_code": group_code,
                "account_name": group_name,
                "client_account_code": group_code,
                "client_account_name": group_name,
            })
            continue
        elif is_rd_special and i == start_index + 1:
            continue  # 已经在上一步合并了

        # 普通分组
        current_name_parts.append(segment)
        group_name = "_".join(current_name_parts)

        # 根据深度生成代码前缀（4-2-2-2 分段）
        depth = len(result) + 1
        if depth == 1:
            group_code = client_code[:6] if len(client_code) >= 6 else client_code
        elif depth == 2:
            group_code = client_code[:8] if len(client_code) >= 8 else client_code
        elif depth == 3:
            group_code = client_code[:10] if len(client_code) >= 10 else client_code
        else:
            group_code = client_code[:min(12, len(client_code))]

        result.append({
            "account_code": group_code,
            "account_name": segment,
            "client_account_code": group_code,
            "client_account_name": group_name,
        })

    return result


def _make_synthetic_client_group_node(
    sa: StandardAccount,
    synth: dict,
    level: int,
    node_key: str,
) -> dict:
    """构造合成的 client_group 节点。"""
    return {
        "node_id": node_key,
        "node_type": "client_group",
        "standard_account_id": sa.id,
        "account_code": synth["account_code"],
        "account_name": synth["account_name"],
        "client_account_code": synth["client_account_code"],
        "client_account_name": synth["client_account_name"],
        "level": level + 1,
        "is_leaf": False,
        "entry_id": None,
        "standard_account_code": None,
        "standard_account_name": None,
        "account_category": None,
        "balance_direction": None,
        "opening_debit": Decimal("0"),
        "opening_credit": Decimal("0"),
        "current_debit": Decimal("0"),
        "current_credit": Decimal("0"),
        "ending_debit": Decimal("0"),
        "ending_credit": Decimal("0"),
        "children": [],
        "entry_count": 0,
        "has_children": True,
        "aggregated": _empty_agg(),
    }


async def get_tree(
    db: AsyncSession,
    *,
    batch_id: uuid.UUID | None = None,
    fiscal_year: int | None = None,
    period: int | None = None,
    only_with_amounts: bool = False,
) -> tuple[list[dict], int]:
    """
    构建标准科目余额表树形视图，支持客户中间层级展示。

    三类节点：
    - account: 标准科目节点
    - client_group: 客户原始非末级层级（通过 raw_row.parent_raw_row_id 复原）
    - entry: 客户末级入库明细

    聚合规则：
    - entry 节点金额来自 StandardTrialBalanceEntry
    - client_group 节点金额汇总其所有子孙 entry
    - account 标准科目节点金额汇总所有子标准科目 + 自身客户树

    返回: (tree_nodes, total_nodes)
    """
    # 1. 查询所有启用标准科目
    result = await db.execute(
        select(StandardAccount)
        .where(StandardAccount.is_active == True)
        .order_by(StandardAccount.account_code)
    )
    all_accounts = result.scalars().all()

    if not all_accounts:
        return [], 0

    id_to_account: dict[uuid.UUID, StandardAccount] = {sa.id: sa for sa in all_accounts}
    children_map: dict[uuid.UUID | None, list[StandardAccount]] = defaultdict(list)
    for sa in all_accounts:
        children_map[sa.parent_id].append(sa)

    # 2. 查询 entries
    entry_query = select(StandardTrialBalanceEntry)
    if batch_id is not None:
        entry_query = entry_query.where(StandardTrialBalanceEntry.batch_id == batch_id)
    if fiscal_year is not None:
        entry_query = entry_query.where(StandardTrialBalanceEntry.fiscal_year == fiscal_year)
    if period is not None:
        entry_query = entry_query.where(StandardTrialBalanceEntry.period == period)

    result = await db.execute(entry_query)
    entries = result.scalars().all()

    # 按 standard_account_id 聚合金额
    account_amounts: dict[uuid.UUID, dict] = defaultdict(_empty_agg)
    entries_by_account_id: dict[uuid.UUID, list[StandardTrialBalanceEntry]] = defaultdict(list)
    for entry in entries:
        _add_amounts(account_amounts[entry.standard_account_id], entry)
        entries_by_account_id[entry.standard_account_id].append(entry)

    # 3. 查询 raw rows（用于复原客户中间层级）
    raw_rows: list[StandardTrialBalanceRawRow] = []
    if batch_id is not None:
        raw_result = await db.execute(
            select(StandardTrialBalanceRawRow).where(
                StandardTrialBalanceRawRow.batch_id == batch_id
            )
        )
        raw_rows = raw_result.scalars().all()

    raw_by_id: dict[uuid.UUID, StandardTrialBalanceRawRow] = {r.id: r for r in raw_rows}
    entry_by_raw_id: dict[uuid.UUID, StandardTrialBalanceEntry] = {
        entry.raw_row_id: entry for entry in entries if entry.raw_row_id
    }

    # 4. 构建 client_group 节点：按 (standard_account_id, raw_parent_id) 分组
    # 为每个 entry 沿 parent_raw_row_id 向上走，收集中间层
    def _ancestor_chain(raw_row: StandardTrialBalanceRawRow) -> list[StandardTrialBalanceRawRow]:
        """返回从最顶层祖先到直接父级的链（不含自身）。"""
        chain = []
        cur = raw_row
        while cur and cur.parent_raw_row_id:
            parent = raw_by_id.get(cur.parent_raw_row_id)
            if not parent:
                break
            chain.append(parent)
            cur = parent
        chain.reverse()
        return chain

    # 每个标准科目下：raw_row_id → client_group 节点 dict
    # client_group 节点可能有子 client_group 或 entry 子节点
    sa_client_children: dict[uuid.UUID, dict] = {}  # key: (sa_id, raw_id) → node dict

    def _make_client_group_node(
        sa: StandardAccount,
        raw: StandardTrialBalanceRawRow,
        level: int,
    ) -> dict:
        return {
            "node_id": f"client_group:{sa.id}:{raw.id}",
            "node_type": "client_group",
            "standard_account_id": sa.id,
            "account_code": raw.client_account_code or "",
            "account_name": raw.client_account_name or "",
            "client_account_code": raw.client_account_code,
            "client_account_name": raw.client_account_name,
            "level": raw.detected_level or level,
            "is_leaf": False,
            "entry_id": None,
            "standard_account_code": None,
            "standard_account_name": None,
            "account_category": None,
            "balance_direction": None,
            "opening_debit": Decimal("0"),
            "opening_credit": Decimal("0"),
            "current_debit": Decimal("0"),
            "current_credit": Decimal("0"),
            "ending_debit": Decimal("0"),
            "ending_credit": Decimal("0"),
            "children": [],
            "entry_count": 0,
            "has_children": True,
            "aggregated": _empty_agg(),
        }

    def _build_entry_node(entry: StandardTrialBalanceEntry, sa_level: int | None, short_name: bool = False) -> dict:
        code = entry.client_account_code or entry.standard_account_code_snapshot
        full_name = entry.client_account_name or entry.standard_account_name_snapshot
        if short_name and full_name:
            # 只取名称最后一段
            separators = ["_", "-", "－", "—", "/", "\\"]
            segments = [full_name]
            for sep in separators:
                new_segments = []
                for seg in segments:
                    new_segments.extend(seg.split(sep))
                segments = new_segments
            segments = [s for s in segments if s.strip()]
            display_name = segments[-1] if segments else full_name
        else:
            display_name = full_name
        return {
            "node_id": f"entry:{entry.id}",
            "node_type": "entry",
            "standard_account_id": entry.standard_account_id,
            "standard_account_code": entry.standard_account_code_snapshot,
            "standard_account_name": entry.standard_account_name_snapshot,
            "entry_id": entry.id,
            "account_code": code or "",
            "account_name": display_name or "",
            "client_account_code": entry.client_account_code,
            "client_account_name": entry.client_account_name,
            "account_category": entry.standard_account_category_snapshot,
            "balance_direction": entry.standard_balance_direction_snapshot,
            "level": (sa_level or 1) + 1,
            "is_leaf": True,
            "opening_debit": entry.opening_debit,
            "opening_credit": entry.opening_credit,
            "current_debit": entry.current_debit,
            "current_credit": entry.current_credit,
            "ending_debit": entry.ending_debit,
            "ending_credit": entry.ending_credit,
            "children": [],
            "entry_count": 1,
            "has_children": False,
        }

    def _has_amounts(amounts: dict) -> bool:
        return (
            amounts["opening_debit"] != 0
            or amounts["opening_credit"] != 0
            or amounts["current_debit"] != 0
            or amounts["current_credit"] != 0
            or amounts["ending_debit"] != 0
            or amounts["ending_credit"] != 0
            or amounts["entry_count"] > 0
        )

    total_nodes = 0

    def _build_node(sa: StandardAccount) -> dict | None:
        nonlocal total_nodes

        # 递归构建标准子科目
        child_nodes = []
        for child_sa in children_map.get(sa.id, []):
            child_node = _build_node(child_sa)
            if child_node is not None:
                child_nodes.append(child_node)

        # 为当前标准科目下的 entries 构建客户层级树
        sa_entries = entries_by_account_id.get(sa.id, [])
        # 每个 entry 的 raw_row_id → ancestor chain → 插入 client_group 树
        local_client_nodes: dict[uuid.UUID, dict] = {}  # raw_id → client_group node
        entry_nodes: list[dict] = []
        raw_ids_this_sa: set[uuid.UUID] = set()

        for entry in sa_entries:
            raw_id = entry.raw_row_id
            synthetic_path = None
            use_raw_chain = False
            chain: list[StandardTrialBalanceRawRow] = []
            if not raw_id:
                synthetic_path = _build_synthetic_client_group_path(
                    client_code=entry.client_account_code,
                    client_name=entry.client_account_name,
                    standard_account_code=sa.account_code,
                    standard_account_name=sa.account_name,
                )
            else:
                raw = raw_by_id.get(raw_id)
                if not raw:
                    synthetic_path = _build_synthetic_client_group_path(
                        client_code=entry.client_account_code,
                        client_name=entry.client_account_name,
                        standard_account_code=sa.account_code,
                        standard_account_name=sa.account_name,
                    )
                else:
                    raw_ids_this_sa.add(raw_id)
                    chain = _ancestor_chain(raw)
                    if len(chain) > 0:
                        use_raw_chain = True
                    else:
                        synthetic_path = _build_synthetic_client_group_path(
                            client_code=entry.client_account_code,
                            client_name=entry.client_account_name,
                            standard_account_code=sa.account_code,
                            standard_account_name=sa.account_name,
                        )

            if use_raw_chain:
                # 使用 raw parent chain；同一父容器下同一 node_id 只能追加一次（TASK-077）
                parent_container = None
                chain_keys = []
                for ancestor in chain:
                    anc_key = ancestor.id
                    chain_keys.append(anc_key)
                    if anc_key not in local_client_nodes:
                        cg = _make_client_group_node(sa, ancestor, sa.level or 1)
                        local_client_nodes[anc_key] = cg
                        raw_ids_this_sa.add(anc_key)
                    if parent_container is not None:
                        _append_unique_child(parent_container, local_client_nodes[anc_key])
                    parent_container = local_client_nodes[anc_key]["children"]

                entry_node = _build_entry_node(entry, sa.level, short_name=True)
                if parent_container is not None:
                    _append_unique_child(parent_container, entry_node)
                else:
                    _append_unique_child(entry_nodes, entry_node)

                entry_agg = _empty_agg()
                _add_amounts(entry_agg, entry)
                if raw_id in local_client_nodes:
                    _sum_child_agg(local_client_nodes[raw_id]["aggregated"], entry_agg)
                for ck in chain_keys:
                    if ck in local_client_nodes:
                        _sum_child_agg(local_client_nodes[ck]["aggregated"], entry_agg)
            elif synthetic_path:
                # 从名称合成 client_group；同一父容器下同一 node_id 只能追加一次（TASK-077）
                parent_container = None
                path_keys = []
                for synth in synthetic_path:
                    synth_key = f"synth:{sa.id}:{synth['account_code']}"
                    path_keys.append(synth_key)
                    if synth_key not in local_client_nodes:
                        cg = _make_synthetic_client_group_node(sa, synth, sa.level or 1, synth_key)
                        local_client_nodes[synth_key] = cg
                    if parent_container is not None:
                        _append_unique_child(parent_container, local_client_nodes[synth_key])
                    parent_container = local_client_nodes[synth_key]["children"]

                entry_node = _build_entry_node(entry, sa.level, short_name=True)
                if parent_container is not None:
                    _append_unique_child(parent_container, entry_node)
                else:
                    _append_unique_child(entry_nodes, entry_node)

                entry_agg = _empty_agg()
                _add_amounts(entry_agg, entry)
                for pk in path_keys:
                    if pk in local_client_nodes:
                        _sum_child_agg(local_client_nodes[pk]["aggregated"], entry_agg)
            else:
                entry_node = _build_entry_node(entry, sa.level)
                _append_unique_child(entry_nodes, entry_node)

        # 把没有父级的 client_group 节点（链顶）挂到标准科目下
        top_level_client_groups: list[dict] = []
        child_raw_ids: set[str] = set()
        for cg in local_client_nodes.values():
            for child in cg["children"]:
                if child.get("node_type") == "client_group":
                    child_raw_ids.add(child["node_id"])

        for key, cg in local_client_nodes.items():
            if cg["node_id"] not in child_raw_ids:
                top_level_client_groups.append(cg)

        # 给 client_group 节点设置聚合金额（从 aggregated 移到标准字段）
        def _finalize_cg(cg: dict):
            agg = cg.pop("aggregated", _empty_agg())
            cg["opening_debit"] = agg["opening_debit"]
            cg["opening_credit"] = agg["opening_credit"]
            cg["current_debit"] = agg["current_debit"]
            cg["current_credit"] = agg["current_credit"]
            cg["ending_debit"] = agg["ending_debit"]
            cg["ending_credit"] = agg["ending_credit"]
            cg["entry_count"] = agg["entry_count"]
            for child in cg["children"]:
                if child.get("node_type") == "client_group":
                    _finalize_cg(child)

        for cg in top_level_client_groups:
            _finalize_cg(cg)

        # 组合：标准子科目 + 客户层级 + entry 直接子节点
        all_client_and_entry = top_level_client_groups + entry_nodes

        # 汇总金额
        aggregated = _empty_agg()
        own_amounts = account_amounts.get(sa.id)
        if own_amounts:
            for key in aggregated:
                aggregated[key] += own_amounts[key]

        for child in child_nodes:
            _sum_child_agg(aggregated, child.get("aggregated", _empty_agg()))

        # client_group 的金额已包含在 own_amounts 中（因为 entry 金额计入了 account_amounts），
        # 所以不需要重复累加 client_group 金额。但 entry_count 需要累加子标准科目的。

        if only_with_amounts and not _has_amounts(aggregated):
            return None

        has_children = len(child_nodes) + len(all_client_and_entry) > 0
        total_nodes += 1 + len(all_client_and_entry)

        node = {
            "node_id": f"account:{sa.id}",
            "node_type": "account",
            "standard_account_id": sa.id,
            "account_code": sa.account_code,
            "account_name": sa.account_name,
            "account_category": sa.account_category,
            "balance_direction": sa.balance_direction,
            "level": sa.level,
            "is_leaf": sa.is_leaf,
            "entry_id": None,
            "client_account_code": None,
            "client_account_name": None,
            "opening_debit": aggregated["opening_debit"],
            "opening_credit": aggregated["opening_credit"],
            "current_debit": aggregated["current_debit"],
            "current_credit": aggregated["current_credit"],
            "ending_debit": aggregated["ending_debit"],
            "ending_credit": aggregated["ending_credit"],
            "children": child_nodes + all_client_and_entry,
            "entry_count": aggregated["entry_count"],
            "has_children": has_children,
            "aggregated": aggregated,
        }
        return node

    # 从根节点开始构建
    root_nodes = []
    for root_sa in children_map.get(None, []):
        node = _build_node(root_sa)
        if node is not None:
            root_nodes.append(node)

    # 清理内部字段
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


# ── 删除批次 ──────────────────────────────────────────

async def delete_batch(db: AsyncSession, batch_id: uuid.UUID) -> dict | None:
    """删除导入批次及其关联的 entries 和 raw_rows，不删除 standard_accounts 和映射经验。

    TASK-072：数据查询页新增删除导入数据按钮，用户可删除已导入的科目余额表数据。
    """
    batch = await db.get(StandardTrialBalanceImportBatch, batch_id)
    if batch is None:
        return None

    entries_result = await db.execute(
        select(func.count(StandardTrialBalanceEntry.id)).where(
            StandardTrialBalanceEntry.batch_id == batch_id
        )
    )
    entry_count = entries_result.scalar() or 0

    raw_result = await db.execute(
        select(func.count(StandardTrialBalanceRawRow.id)).where(
            StandardTrialBalanceRawRow.batch_id == batch_id
        )
    )
    raw_row_count = raw_result.scalar() or 0

    await db.execute(
        delete(StandardTrialBalanceEntry).where(StandardTrialBalanceEntry.batch_id == batch_id)
    )

    # SQLite/自引用外键下，先清空本批次 raw row 的 parent_raw_row_id，再删 raw rows
    await db.execute(
        update(StandardTrialBalanceRawRow)
        .where(StandardTrialBalanceRawRow.batch_id == batch_id)
        .values(parent_raw_row_id=None)
    )
    await db.execute(
        delete(StandardTrialBalanceRawRow).where(StandardTrialBalanceRawRow.batch_id == batch_id)
    )

    await db.delete(batch)
    await db.flush()

    return {
        "batch_id": batch_id,
        "deleted_entries": entry_count,
        "deleted_raw_rows": raw_row_count,
        "deleted_batches": 1,
    }
