"""标准科目余额表数据查看后端测试 — TASK-046"""

import uuid
import pytest
from decimal import Decimal
from datetime import datetime, timezone

from sqlalchemy import select
from app.models.standard_account import StandardAccount
from app.models.standard_trial_balance_import_batch import StandardTrialBalanceImportBatch
from app.models.standard_trial_balance_entry import StandardTrialBalanceEntry
from app.models.standard_trial_balance_raw_row import StandardTrialBalanceRawRow
from app.services.standard_trial_balance_service import (
    get_batches,
    get_tree,
    get_entries,
    delete_batch,
)


# ── 辅助函数 ──────────────────────────────────────────

async def _create_account(db, code, name, **kwargs):
    """创建标准科目并返回。"""
    sa = StandardAccount(account_code=code, account_name=name, **kwargs)
    db.add(sa)
    await db.flush()
    return sa


async def _create_batch(db, **kwargs):
    """创建导入批次并返回。"""
    defaults = {
        "file_name": "test.xlsx",
        "fiscal_year": 2024,
        "period": 1,
        "status": "completed",
    }
    defaults.update(kwargs)
    batch = StandardTrialBalanceImportBatch(**defaults)
    db.add(batch)
    await db.flush()
    return batch


async def _create_entry(db, batch_id, sa, **kwargs):
    """创建标准余额表明细并返回。"""
    defaults = {
        "batch_id": batch_id,
        "standard_account_id": sa.id,
        "standard_account_code_snapshot": sa.account_code,
        "standard_account_name_snapshot": sa.account_name,
        "standard_account_category_snapshot": sa.account_category,
        "standard_balance_direction_snapshot": sa.balance_direction,
        "fiscal_year": 2024,
        "period": 1,
    }
    defaults.update(kwargs)
    entry = StandardTrialBalanceEntry(**defaults)
    db.add(entry)
    await db.flush()
    return entry


# ── 批次列表测试 ──────────────────────────────────────

class TestBatchList:
    """批次列表查询测试"""

    @pytest.mark.asyncio
    async def test_list_all_batches(self, db):
        """列出所有批次"""
        b1 = await _create_batch(db, file_name="file1.xlsx", customer_label="公司A")
        b2 = await _create_batch(db, file_name="file2.xlsx", customer_label="公司B")

        result = await get_batches(db)
        assert len(result) == 2
        file_names = {r["file_name"] for r in result}
        assert file_names == {"file1.xlsx", "file2.xlsx"}
        assert result[0]["entry_count"] == 0

    @pytest.mark.asyncio
    async def test_filter_by_customer_label(self, db):
        """按客户标识筛选"""
        await _create_batch(db, file_name="a.xlsx", customer_label="科技公司")
        await _create_batch(db, file_name="b.xlsx", customer_label="贸易公司")
        await _create_batch(db, file_name="c.xlsx", customer_label="科技集团")

        result = await get_batches(db, customer_label="科技")
        assert len(result) == 2
        labels = {r["customer_label"] for r in result}
        assert labels == {"科技公司", "科技集团"}

    @pytest.mark.asyncio
    async def test_filter_by_fiscal_year(self, db):
        """按年度筛选"""
        await _create_batch(db, file_name="2023.xlsx", fiscal_year=2023)
        await _create_batch(db, file_name="2024.xlsx", fiscal_year=2024)

        result = await get_batches(db, fiscal_year=2024)
        assert len(result) == 1
        assert result[0]["file_name"] == "2024.xlsx"

    @pytest.mark.asyncio
    async def test_filter_by_period(self, db):
        """按期间筛选"""
        await _create_batch(db, file_name="p1.xlsx", period=1)
        await _create_batch(db, file_name="p6.xlsx", period=6)

        result = await get_batches(db, period=6)
        assert len(result) == 1
        assert result[0]["file_name"] == "p6.xlsx"

    @pytest.mark.asyncio
    async def test_filter_by_import_time_range(self, db):
        """按导入时间范围筛选"""
        b1 = await _create_batch(db, file_name="old.xlsx")
        # 手动设置 created_at（需要 flush 后更新）
        import datetime as dt
        b2 = await _create_batch(db, file_name="new.xlsx")

        now = dt.datetime.now(dt.timezone.utc)
        # 所有批次都在今天创建，范围应覆盖
        result = await get_batches(
            db,
            import_start=now - dt.timedelta(days=1),
            import_end=now + dt.timedelta(days=1),
        )
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_entry_count_in_batch(self, db):
        """批次中条目计数"""
        sa = await _create_account(db, "1001", "库存现金")
        batch = await _create_batch(db, file_name="with_entries.xlsx")
        await _create_entry(db, batch.id, sa)
        await _create_entry(db, batch.id, sa, client_account_code="1001-A")

        result = await get_batches(db)
        assert len(result) == 1
        assert result[0]["entry_count"] == 2


# ── 树形视图测试 ──────────────────────────────────────

class TestTreeView:
    """树形视图查询测试"""

    @pytest.mark.asyncio
    async def test_empty_tree(self, db):
        """无标准科目时返回空"""
        nodes, total = await get_tree(db)
        assert nodes == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_flat_tree_single_account(self, db):
        """单层单科目树"""
        sa = await _create_account(db, "1001", "库存现金", level=1, is_leaf=True)
        batch = await _create_batch(db)
        await _create_entry(
            db, batch.id, sa,
            opening_debit=Decimal("10000"),
            current_debit=Decimal("5000"),
            ending_debit=Decimal("15000"),
        )

        nodes, total = await get_tree(db, batch_id=batch.id)
        assert total == 2  # 1 标准科目节点 + 1 客户明细节点
        assert len(nodes) == 1
        assert nodes[0]["account_code"] == "1001"
        assert nodes[0]["opening_debit"] == Decimal("10000")
        assert nodes[0]["current_debit"] == Decimal("5000")
        assert nodes[0]["ending_debit"] == Decimal("15000")
        assert nodes[0]["entry_count"] == 1
        # 叶子科目有客户明细节点，应可展开
        assert nodes[0]["has_children"] is True
        # 客户明细节点拼在 children 中
        entry_node = nodes[0]["children"][0]
        assert entry_node["node_type"] == "entry"
        assert entry_node["has_children"] is False
        assert entry_node["children"] == []

    @pytest.mark.asyncio
    async def test_parent_aggregates_children(self, db):
        """父级动态汇总子级金额"""
        # 父级: 1001 资产
        parent = await _create_account(
            db, "1001", "资产", level=1, is_leaf=False
        )
        # 子级1: 1001001 库存现金
        child1 = await _create_account(
            db, "1001001", "库存现金", level=2, is_leaf=True,
            parent_id=parent.id
        )
        # 子级2: 1001002 银行存款
        child2 = await _create_account(
            db, "1001002", "银行存款", level=2, is_leaf=True,
            parent_id=parent.id
        )

        batch = await _create_batch(db)

        # 子级1 有两条条目
        await _create_entry(
            db, batch.id, child1,
            opening_debit=Decimal("1000"),
            current_debit=Decimal("200"),
        )
        await _create_entry(
            db, batch.id, child1,
            opening_debit=Decimal("500"),
            current_credit=Decimal("100"),
        )

        # 子级2 有一条条目
        await _create_entry(
            db, batch.id, child2,
            opening_debit=Decimal("3000"),
            ending_debit=Decimal("3000"),
        )

        nodes, total = await get_tree(db, batch_id=batch.id)
        assert total == 6  # 3 标准科目 + 3 客户明细
        assert len(nodes) == 1  # 只有一个根节点

        parent_node = nodes[0]
        assert parent_node["account_code"] == "1001"
        assert parent_node["has_children"] is True
        assert len(parent_node["children"]) == 2

        # 父级金额 = 子级汇总
        # opening_debit: 1000 + 500 + 3000 = 4500
        assert parent_node["opening_debit"] == Decimal("4500")
        # current_debit: 200
        assert parent_node["current_debit"] == Decimal("200")
        # current_credit: 100
        assert parent_node["current_credit"] == Decimal("100")
        # ending_debit: 3000
        assert parent_node["ending_debit"] == Decimal("3000")
        # entry_count: 3
        assert parent_node["entry_count"] == 3

    @pytest.mark.asyncio
    async def test_deep_hierarchy_aggregation(self, db):
        """三级科目树动态汇总"""
        # 1 级: 资产
        level1 = await _create_account(db, "1", "资产", level=1, is_leaf=False)
        # 2 级: 流动资产
        level2 = await _create_account(
            db, "11", "流动资产", level=2, is_leaf=False, parent_id=level1.id
        )
        # 3 级: 库存现金
        level3 = await _create_account(
            db, "111", "库存现金", level=3, is_leaf=True, parent_id=level2.id
        )

        batch = await _create_batch(db)
        await _create_entry(
            db, batch.id, level3,
            opening_debit=Decimal("100"),
            current_debit=Decimal("50"),
            ending_debit=Decimal("150"),
        )

        nodes, total = await get_tree(db, batch_id=batch.id)
        assert total == 4  # 3 标准科目 + 1 客户明细

        root = nodes[0]  # 资产
        assert root["account_code"] == "1"
        assert root["opening_debit"] == Decimal("100")
        assert root["entry_count"] == 1

        mid = root["children"][0]  # 流动资产
        assert mid["account_code"] == "11"
        assert mid["opening_debit"] == Decimal("100")
        assert mid["entry_count"] == 1

        leaf = mid["children"][0]  # 库存现金
        assert leaf["account_code"] == "111"
        assert leaf["is_leaf"] is True
        assert leaf["opening_debit"] == Decimal("100")

    @pytest.mark.asyncio
    async def test_only_with_amounts_filter(self, db):
        """只看有金额科目"""
        sa_with = await _create_account(db, "1001", "库存现金", level=1, is_leaf=True)
        sa_without = await _create_account(db, "2001", "短期借款", level=1, is_leaf=True)

        batch = await _create_batch(db)
        await _create_entry(
            db, batch.id, sa_with,
            opening_debit=Decimal("5000"),
        )
        # sa_without 没有条目

        nodes, total = await get_tree(db, batch_id=batch.id, only_with_amounts=True)
        assert total == 2  # 1 标准科目 + 1 客户明细
        assert len(nodes) == 1
        assert nodes[0]["account_code"] == "1001"

    @pytest.mark.asyncio
    async def test_only_with_amounts_parent_hides_empty_children(self, db):
        """有金额筛选：父级有子级金额时显示，子级无金额时隐藏"""
        parent = await _create_account(db, "1001", "资产", level=1, is_leaf=False)
        child_with = await _create_account(
            db, "1001001", "库存现金", level=2, is_leaf=True, parent_id=parent.id
        )
        child_without = await _create_account(
            db, "1001002", "银行存款", level=2, is_leaf=True, parent_id=parent.id
        )

        batch = await _create_batch(db)
        await _create_entry(
            db, batch.id, child_with,
            opening_debit=Decimal("1000"),
        )
        # child_without 无条目 → 应该被隐藏

        nodes, total = await get_tree(db, batch_id=batch.id, only_with_amounts=True)
        assert total == 3  # 父级 + 有金额子级 + 客户明细
        assert len(nodes) == 1
        parent_node = nodes[0]
        assert parent_node["account_code"] == "1001"
        assert len(parent_node["children"]) == 1
        assert parent_node["children"][0]["account_code"] == "1001001"

    @pytest.mark.asyncio
    async def test_filter_by_batch_id(self, db):
        """按批次筛选树形视图"""
        sa = await _create_account(db, "1001", "库存现金", level=1, is_leaf=True)
        batch1 = await _create_batch(db, file_name="b1.xlsx")
        batch2 = await _create_batch(db, file_name="b2.xlsx")

        await _create_entry(db, batch1.id, sa, opening_debit=Decimal("100"))
        await _create_entry(db, batch2.id, sa, opening_debit=Decimal("200"))

        # 只查 batch1
        nodes, total = await get_tree(db, batch_id=batch1.id)
        assert total == 2  # 1 标准科目 + 1 客户明细
        assert nodes[0]["opening_debit"] == Decimal("100")

        # 只查 batch2
        nodes, total = await get_tree(db, batch_id=batch2.id)
        assert total == 2
        assert nodes[0]["opening_debit"] == Decimal("200")

    @pytest.mark.asyncio
    async def test_filter_by_fiscal_year_and_period(self, db):
        """按年度和期间筛选树形视图"""
        sa = await _create_account(db, "1001", "库存现金", level=1, is_leaf=True)
        batch = await _create_batch(db)

        await _create_entry(db, batch.id, sa, fiscal_year=2024, period=1,
                            opening_debit=Decimal("100"))
        await _create_entry(db, batch.id, sa, fiscal_year=2024, period=2,
                            opening_debit=Decimal("200"))
        await _create_entry(db, batch.id, sa, fiscal_year=2025, period=1,
                            opening_debit=Decimal("300"))

        # 2024 年
        nodes, total = await get_tree(db, fiscal_year=2024)
        assert nodes[0]["opening_debit"] == Decimal("300")  # 100+200

        # 2024 年 2 月
        nodes, total = await get_tree(db, fiscal_year=2024, period=2)
        assert nodes[0]["opening_debit"] == Decimal("200")

        # 2025 年
        nodes, total = await get_tree(db, fiscal_year=2025)
        assert nodes[0]["opening_debit"] == Decimal("300")

    @pytest.mark.asyncio
    async def test_tree_includes_entry_children_under_standard_account(self, db):
        """标准科目节点下应拼接客户原始明细节点"""
        parent = await _create_account(db, "1411", "周转材料", level=1, is_leaf=False)
        child = await _create_account(
            db, "141101", "包装物", level=2, is_leaf=True, parent_id=parent.id
        )
        batch = await _create_batch(db)
        await _create_entry(
            db,
            batch.id,
            child,
            client_account_code="C1411",
            client_account_name="包装物",
            opening_debit=Decimal("100"),
            ending_debit=Decimal("100"),
        )

        nodes, total = await get_tree(db, batch_id=batch.id)
        assert len(nodes) == 1
        parent_node = nodes[0]
        child_node = parent_node["children"][0]

        assert parent_node["node_type"] == "account"
        assert parent_node["node_id"] == f"account:{parent.id}"
        assert child_node["node_type"] == "account"
        assert child_node["account_code"] == "141101"
        assert child_node["entry_count"] == 1

        entry_node = child_node["children"][0]
        assert entry_node["node_type"] == "entry"
        assert entry_node["node_id"] == f"entry:{entry_node['entry_id']}"
        assert entry_node["client_account_code"] == "C1411"
        assert entry_node["client_account_name"] == "包装物"
        assert entry_node["opening_debit"] == Decimal("100")
        assert entry_node["has_children"] is False
        assert entry_node["children"] == []

    @pytest.mark.asyncio
    async def test_six_column_aggregation(self, db):
        """六列金额均正确汇总"""
        sa = await _create_account(db, "1001", "库存现金", level=1, is_leaf=True)
        batch = await _create_batch(db)

        await _create_entry(
            db, batch.id, sa,
            opening_debit=Decimal("100"),
            opening_credit=Decimal("50"),
            current_debit=Decimal("200"),
            current_credit=Decimal("80"),
            ending_debit=Decimal("220"),
            ending_credit=Decimal("50"),
        )
        await _create_entry(
            db, batch.id, sa,
            opening_debit=Decimal("300"),
            opening_credit=Decimal("10"),
            current_debit=Decimal("400"),
            current_credit=Decimal("20"),
            ending_debit=Decimal("680"),
            ending_credit=Decimal("10"),
        )

        nodes, total = await get_tree(db, batch_id=batch.id)
        assert nodes[0]["opening_debit"] == Decimal("400")   # 100+300
        assert nodes[0]["opening_credit"] == Decimal("60")   # 50+10
        assert nodes[0]["current_debit"] == Decimal("600")   # 200+400
        assert nodes[0]["current_credit"] == Decimal("100")  # 80+20
        assert nodes[0]["ending_debit"] == Decimal("900")    # 220+680
        assert nodes[0]["ending_credit"] == Decimal("60")    # 50+10


# ── 明细列表测试 ──────────────────────────────────────

class TestEntryList:
    """明细列表查询测试"""

    @pytest.mark.asyncio
    async def test_snapshot_fields_returned(self, db):
        """标准科目快照字段返回"""
        sa = await _create_account(
            db, "1001", "库存现金",
            account_category="asset", balance_direction="debit",
        )
        batch = await _create_batch(db)
        entry = await _create_entry(
            db, batch.id, sa,
            client_account_code="CASH",
            client_account_name="现金(原)",
            opening_debit=Decimal("10000"),
        )

        results = await get_entries(db, batch_id=batch.id)
        assert len(results) == 1
        e = results[0]
        assert e.standard_account_code_snapshot == "1001"
        assert e.standard_account_name_snapshot == "库存现金"
        assert e.standard_account_category_snapshot == "asset"
        assert e.standard_balance_direction_snapshot == "debit"
        assert e.client_account_code == "CASH"
        assert e.client_account_name == "现金(原)"
        assert e.opening_debit == Decimal("10000")

    @pytest.mark.asyncio
    async def test_filter_by_standard_account_code(self, db):
        """按标准科目代码筛选"""
        sa1 = await _create_account(db, "1001", "库存现金")
        sa2 = await _create_account(db, "1002", "银行存款")
        batch = await _create_batch(db)
        await _create_entry(db, batch.id, sa1)
        await _create_entry(db, batch.id, sa2)

        results = await get_entries(db, standard_account_code="1001")
        assert len(results) == 1
        assert results[0].standard_account_code_snapshot == "1001"

    @pytest.mark.asyncio
    async def test_filter_by_client_account_code(self, db):
        """按客户科目代码筛选（模糊匹配）"""
        sa = await _create_account(db, "1001", "库存现金")
        batch = await _create_batch(db)
        await _create_entry(db, batch.id, sa, client_account_code="ABC-001")
        await _create_entry(db, batch.id, sa, client_account_code="XYZ-002")

        results = await get_entries(db, batch_id=batch.id, client_account_code="ABC")
        assert len(results) == 1
        assert results[0].client_account_code == "ABC-001"

    @pytest.mark.asyncio
    async def test_filter_by_fiscal_year_and_period(self, db):
        """按年度和期间筛选明细"""
        sa = await _create_account(db, "1001", "库存现金")
        batch = await _create_batch(db)
        await _create_entry(db, batch.id, sa, fiscal_year=2024, period=1)
        await _create_entry(db, batch.id, sa, fiscal_year=2024, period=2)
        await _create_entry(db, batch.id, sa, fiscal_year=2025, period=1)

        # 年度
        results = await get_entries(db, fiscal_year=2024)
        assert len(results) == 2

        # 年度+期间
        results = await get_entries(db, fiscal_year=2024, period=2)
        assert len(results) == 1
        assert results[0].period == 2

    @pytest.mark.asyncio
    async def test_multiple_filters_combined(self, db):
        """多条件组合筛选"""
        sa1 = await _create_account(db, "1001", "库存现金")
        sa2 = await _create_account(db, "1002", "银行存款")
        batch1 = await _create_batch(db, file_name="b1.xlsx")
        batch2 = await _create_batch(db, file_name="b2.xlsx")

        await _create_entry(db, batch1.id, sa1, fiscal_year=2024, period=1,
                            client_account_code="C001")
        await _create_entry(db, batch1.id, sa2, fiscal_year=2024, period=1,
                            client_account_code="C002")
        await _create_entry(db, batch2.id, sa1, fiscal_year=2025, period=2,
                            client_account_code="C001")

        # batch1 + 2024
        results = await get_entries(db, batch_id=batch1.id, fiscal_year=2024)
        assert len(results) == 2

        # batch1 + 1001
        results = await get_entries(db, batch_id=batch1.id, standard_account_code="1001")
        assert len(results) == 1
        assert results[0].standard_account_code_snapshot == "1001"

    @pytest.mark.asyncio
    async def test_preserves_snapshot_after_account_change(self, db):
        """快照在标准科目变更后保持不变"""
        sa = await _create_account(
            db, "1001", "库存现金",
            account_category="asset", balance_direction="debit",
        )
        batch = await _create_batch(db)
        entry = await _create_entry(db, batch.id, sa)

        # 修改标准科目
        sa.account_name = "库存现金（已更名）"
        sa.account_category = "liability"
        sa.balance_direction = "credit"
        await db.flush()

        results = await get_entries(db, batch_id=batch.id)
        e = results[0]
        # 快照应保持导入时的值
        assert e.standard_account_code_snapshot == "1001"
        assert e.standard_account_name_snapshot == "库存现金"
        assert e.standard_account_category_snapshot == "asset"
        assert e.standard_balance_direction_snapshot == "debit"


# ── TASK-071：包装物/低值易耗品挂在子级节点下 ───────────

def _find_node_by_code(nodes: list[dict], code: str) -> dict | None:
    """在树中按 account_code 查找 account 节点（标准科目节点）。"""
    for n in nodes:
        if n.get("node_type") == "account" and n.get("account_code") == code:
            return n
        found = _find_node_by_code(n.get("children", []), code)
        if found is not None:
            return found
    return None


class TestPackagingConsumablesTreePlacement:
    """TASK-071：查询树中，包装物/低值易耗品客户明细必须挂在 141101/141102 节点下，
    不得直接挂在 1411 下。并且 entry 节点应回带标准科目快照代码/名称。
    """

    @pytest.mark.asyncio
    async def test_tree_places_packaging_entries_under_child_nodes_not_parent(self, db):
        parent = await _create_account(db, "1411", "周转材料", level=1, is_leaf=False)
        packaging = await _create_account(
            db, "141101", "包装物", level=2, is_leaf=True, parent_id=parent.id
        )
        consumables = await _create_account(
            db, "141102", "低值易耗品", level=2, is_leaf=True, parent_id=parent.id
        )
        batch = await _create_batch(db)

        # 直接挂 141101（包装物_纸箱）、141102（低值易耗品_工具）的条目
        await _create_entry(
            db, batch.id, packaging,
            client_account_code="1411", client_account_name="包装物_纸箱",
            ending_debit=Decimal("300"),
        )
        await _create_entry(
            db, batch.id, consumables,
            client_account_code="1411", client_account_name="低值易耗品_工具",
            ending_debit=Decimal("400"),
        )

        nodes, total = await get_tree(db, batch_id=batch.id)

        root_1411 = _find_node_by_code(nodes, "1411")
        node_141101 = _find_node_by_code(nodes, "141101")
        node_141102 = _find_node_by_code(nodes, "141102")
        assert root_1411 is not None, "应存在 1411 节点"
        assert node_141101 is not None, "应存在 141101 节点"
        assert node_141102 is not None, "应存在 141102 节点"

        # 客户明细挂在子级节点下
        packaging_entry_children = [
            child for child in node_141101["children"]
            if child["node_type"] == "entry" and child["client_account_name"] == "包装物_纸箱"
        ]
        consumables_entry_children = [
            child for child in node_141102["children"]
            if child["node_type"] == "entry" and child["client_account_name"] == "低值易耗品_工具"
        ]
        assert packaging_entry_children, "包装物_纸箱 应挂在 141101 下"
        assert consumables_entry_children, "低值易耗品_工具 应挂在 141102 下"

        # 不得直接挂在 1411 下
        direct_entries_under_1411 = [
            child for child in root_1411["children"]
            if child["node_type"] == "entry"
            and child["client_account_name"] in {"包装物_纸箱", "低值易耗品_工具"}
        ]
        assert not direct_entries_under_1411, (
            f"包装物/低值易耗品不得直接挂在 1411 下: {direct_entries_under_1411}"
        )

        # entry 节点应携带标准科目快照代码/名称，便于前端展示「标准：141101 包装物」
        pkg_entry = packaging_entry_children[0]
        assert pkg_entry.get("standard_account_code") == "141101"
        assert pkg_entry.get("standard_account_name") == "包装物"


# ── TASK-072 Task4：包装物/低值易耗品/研发费用为一级节点 ──

class TestPackagingConsumablesResearchRootNodes:
    """141101/141102/660201 必须作为查询树顶层节点展示，不得挂在父级下。"""

    @pytest.mark.asyncio
    async def test_packaging_consumables_are_root_nodes_not_under_turnover_materials(self, db):
        turnover = await _create_account(db, "1411", "周转材料", level=1, is_leaf=True)
        packaging = await _create_account(db, "141101", "包装物", level=1, is_leaf=True)
        consumables = await _create_account(db, "141102", "低值易耗品", level=1, is_leaf=True)
        batch = await _create_batch(db)

        await _create_entry(
            db, batch.id, packaging,
            client_account_code="1411", client_account_name="包装物_纸箱",
            ending_debit=Decimal("100"),
        )
        await _create_entry(
            db, batch.id, consumables,
            client_account_code="1411", client_account_name="低值易耗品_工具",
            ending_debit=Decimal("200"),
        )

        nodes, total = await get_tree(db, batch_id=batch.id, only_with_amounts=True)
        root_codes = [node["account_code"] for node in nodes]
        assert "141101" in root_codes, f"141101 应为顶层节点，实际: {root_codes}"
        assert "141102" in root_codes, f"141102 应为顶层节点，实际: {root_codes}"

        # 包装物/低值易耗品的 entry 必须挂在自己的根节点下
        packaging_node = next(n for n in nodes if n["account_code"] == "141101")
        consumables_node = next(n for n in nodes if n["account_code"] == "141102")
        assert any(
            child["node_type"] == "entry" and child["client_account_name"] == "包装物_纸箱"
            for child in packaging_node["children"]
        )
        assert any(
            child["node_type"] == "entry" and child["client_account_name"] == "低值易耗品_工具"
            for child in consumables_node["children"]
        )

    @pytest.mark.asyncio
    async def test_management_and_research_are_root_nodes(self, db):
        mgmt = await _create_account(db, "6602", "减：管理费用", level=1, is_leaf=True)
        rd = await _create_account(db, "660201", "减：研发费用", level=1, is_leaf=True)
        batch = await _create_batch(db)
        await _create_entry(db, batch.id, mgmt, client_account_code="6602",
                            client_account_name="管理费用", current_debit=Decimal("10"))
        await _create_entry(db, batch.id, rd, client_account_code="6604",
                            client_account_name="研发费用", current_debit=Decimal("20"))

        nodes, _ = await get_tree(db, batch_id=batch.id, only_with_amounts=True)
        root_codes = [node["account_code"] for node in nodes]
        assert "6602" in root_codes, f"6602 应为顶层节点，实际: {root_codes}"
        assert "660201" in root_codes, f"660201 应为顶层节点，实际: {root_codes}"

        mgmt_node = next(n for n in nodes if n["account_code"] == "6602")
        assert not any(
            child["account_code"] == "660201" for child in mgmt_node.get("children", [])
        ), "660201 不应挂在 6602 下"


# ── TASK-072 Task6：删除批次 ──

class TestDeleteBatch:
    """delete_batch 删除 entries/raw_rows/batch，但不删 standard_accounts。"""

    @pytest.mark.asyncio
    async def test_delete_batch_removes_entries_and_raw_rows_but_keeps_standard_accounts(self, db):
        sa = await _create_account(db, "1001", "库存现金", level=1, is_leaf=True)
        batch = await _create_batch(db, file_name="delete_me.xlsx")
        raw = StandardTrialBalanceRawRow(
            batch_id=batch.id,
            row_index=0,
            raw_values={"科目代码": "1001"},
            client_account_code="1001",
            client_account_name="库存现金",
            is_leaf=True,
            mapping_status="mapped",
        )
        db.add(raw)
        await db.flush()
        await _create_entry(db, batch.id, sa, raw_row_id=raw.id, ending_debit=Decimal("1"))

        result = await delete_batch(db, batch.id)
        assert result["deleted_entries"] == 1
        assert result["deleted_raw_rows"] == 1
        assert result["deleted_batches"] == 1

        assert await db.get(StandardTrialBalanceImportBatch, batch.id) is None
        assert await db.get(StandardTrialBalanceRawRow, raw.id) is None

        entries = await db.execute(
            select(StandardTrialBalanceEntry).where(StandardTrialBalanceEntry.batch_id == batch.id)
        )
        assert entries.scalars().all() == []
        # standard_accounts 不应被删除
        assert await db.get(StandardAccount, sa.id) is not None

    @pytest.mark.asyncio
    async def test_delete_batch_returns_none_for_nonexistent(self, db):
        result = await delete_batch(db, uuid.uuid4())
        assert result is None


# ── TASK-076：客户层级合成测试 ──

class TestClientGroupSynthesis:
    """测试从客户科目代码和名称合成 client_group 节点。"""

    @pytest.mark.asyncio
    async def test_tree_synthesizes_client_groups_from_leaf_name_when_raw_parent_missing(self, db):
        """无 raw parent 时，按名称合成应交税费层级。"""
        std = await _create_account(db, "2221", "应交税费", level=1, is_leaf=True)
        batch = await _create_batch(db, file_name="tax.xlsx")

        raw = StandardTrialBalanceRawRow(
            batch_id=batch.id,
            row_index=0,
            raw_values={},
            client_account_code="2221010101",
            client_account_name="应交税费_应交增值税_进项税额_货物进项税",
            detected_level=4,
            is_leaf=True,
            mapped_standard_account_id=std.id,
            mapping_status="mapped",
        )
        db.add(raw)
        await db.flush()

        await _create_entry(
            db,
            batch.id,
            std,
            raw_row_id=raw.id,
            client_account_code="2221010101",
            client_account_name="应交税费_应交增值税_进项税额_货物进项税",
            ending_credit=Decimal("100.00"),
        )

        nodes, _ = await get_tree(db, batch_id=batch.id)
        std_node = _find_node_by_code(nodes, "2221")
        assert std_node is not None, "应存在 2221 标准科目节点"

        # 查找 client_group 子节点
        client_groups = [
            child for child in std_node["children"]
            if child.get("node_type") == "client_group"
        ]
        assert len(client_groups) > 0, "2221 下应有 client_group 节点"

        # 查找 222101 客户层级
        group_222101 = None
        for cg in client_groups:
            if cg.get("account_code") == "222101":
                group_222101 = cg
                break
        assert group_222101 is not None, "应存在 222101 客户层级"

        # 查找 22210101 客户层级
        group_22210101 = None
        for child in group_222101.get("children", []):
            if child.get("node_type") == "client_group" and child.get("account_code") == "22210101":
                group_22210101 = child
                break
        assert group_22210101 is not None, "应存在 22210101 客户层级"

        # 查找 entry 节点
        entry = None
        for child in group_22210101.get("children", []):
            if child.get("node_type") == "entry" and child.get("account_code") == "2221010101":
                entry = child
                break
        assert entry is not None, "应存在 2221010101 entry 节点"

        assert group_222101["account_name"] == "应交增值税"
        assert group_22210101["account_name"] == "进项税额"
        assert entry["account_name"] == "货物进项税"
        assert group_222101["entry_count"] == 1
        assert group_222101["ending_credit"] == Decimal("100.00")

    @pytest.mark.asyncio
    async def test_tree_synthesizes_rd_expensed_client_groups_under_170402(self, db):
        """研发支出费用化合成客户层级。"""
        dev = await _create_account(db, "1704", "开发支出", level=1, is_leaf=False)
        exp = await _create_account(db, "170402", "研发支出-费用化支出", level=2, is_leaf=True, parent_id=dev.id)
        batch = await _create_batch(db, file_name="rd.xlsx")

        raw = StandardTrialBalanceRawRow(
            batch_id=batch.id,
            row_index=0,
            raw_values={},
            client_account_code="5301010101",
            client_account_name="研发支出_费用化支出_人工_工资及奖金",
            detected_level=4,
            is_leaf=True,
            mapped_standard_account_id=exp.id,
            mapping_status="mapped",
        )
        db.add(raw)
        await db.flush()

        await _create_entry(
            db,
            batch.id,
            exp,
            raw_row_id=raw.id,
            client_account_code="5301010101",
            client_account_name="研发支出_费用化支出_人工_工资及奖金",
            current_debit=Decimal("200.00"),
        )

        nodes, _ = await get_tree(db, batch_id=batch.id)

        # Debug: 打印树结构
        import json
        def print_tree(nodes, indent=0):
            for n in nodes:
                print("  " * indent + f"{n['node_type']}: {n.get('account_code', '')} {n.get('account_name', '')[:20]}")
                if n.get('children'):
                    print_tree(n['children'], indent+1)

        print("\n=== Tree Structure ===")
        print_tree(nodes)
        print("=====================\n")

        # 查找 170402 标准科目节点
        node_170402 = _find_node_by_code(nodes, "170402")
        assert node_170402 is not None, "应存在 170402 标准科目节点"

        # 查找 530101 客户层级
        group_530101 = None
        for child in node_170402["children"]:
            if child.get("node_type") == "client_group" and child.get("account_code") == "530101":
                group_530101 = child
                break
        assert group_530101 is not None, "应存在 530101 客户层级"

        # 查找 53010101 客户层级
        group_53010101 = None
        for child in group_530101.get("children", []):
            if child.get("node_type") == "client_group" and child.get("account_code") == "53010101":
                group_53010101 = child
                break
        assert group_53010101 is not None, "应存在 53010101 客户层级"

        # 查找 entry 节点
        entry = None
        for child in group_53010101.get("children", []):
            if child.get("node_type") == "entry" and child.get("account_code") == "5301010101":
                entry = child
                break
        assert entry is not None, "应存在 5301010101 entry 节点"

        assert group_530101["account_name"] == "研发支出_费用化支出"
        assert group_53010101["account_name"] == "人工"
        assert entry["account_name"] == "工资及奖金"
        assert group_530101["current_debit"] == Decimal("200.00")


# ── TASK-077：合成客户层级去重测试 ──

def _recursive_entry_nodes(node: dict) -> int:
    """递归统计一棵子树下 entry 节点的数量（不去重，用于与 entry_count 对比）。"""
    count = 0
    for child in node.get("children", []):
        if child.get("node_type") == "entry":
            count += 1
        else:
            count += _recursive_entry_nodes(child)
    return count


def _collect_node_ids(node: dict, acc: list) -> None:
    nid = node.get("node_id")
    if nid is not None:
        acc.append(nid)
    for child in node.get("children", []):
        _collect_node_ids(child, acc)


class TestClientGroupDedup:
    """TASK-077：同一标准科目下共享合成父级的多条客户明细，client_group 不得重复挂载，
    递归 entry 节点数必须等于标准科目 entry_count，整棵树不允许重复 node_id。
    """

    @pytest.mark.asyncio
    async def test_170402_shared_synth_parent_no_dup(self, db):
        dev = await _create_account(db, "1704", "开发支出", level=1, is_leaf=False)
        exp = await _create_account(db, "170402", "研发支出-费用化支出",
                                    level=2, is_leaf=True, parent_id=dev.id)
        batch = await _create_batch(db, file_name="rd_multi.xlsx")

        rows = [
            ("5301010101", "研发支出_费用化支出_人工_工资及奖金", Decimal("100.00")),
            ("5301010102", "研发支出_费用化支出_人工_福利费", Decimal("50.00")),
            ("5301010201", "研发支出_费用化支出_直接投入_材料", Decimal("200.00")),
        ]
        for idx, (code, name, amt) in enumerate(rows):
            raw = StandardTrialBalanceRawRow(
                batch_id=batch.id, row_index=idx, raw_values={},
                client_account_code=code, client_account_name=name,
                detected_level=4, is_leaf=True,
                mapped_standard_account_id=exp.id, mapping_status="mapped",
            )
            db.add(raw)
            await db.flush()
            await _create_entry(db, batch.id, exp,
                                raw_row_id=raw.id,
                                client_account_code=code,
                                client_account_name=name,
                                current_debit=amt)

        nodes, _ = await get_tree(db, batch_id=batch.id)
        node_170402 = _find_node_by_code(nodes, "170402")
        assert node_170402 is not None, "应存在 170402 标准科目节点"

        assert node_170402["entry_count"] == 3, \
            f"170402 entry_count 应为 3，实际: {node_170402['entry_count']}"
        assert _recursive_entry_nodes(node_170402) == 3, \
            f"170402 递归 entry 节点应为 3，实际: {_recursive_entry_nodes(node_170402)}"

        # 530101 / 53010101 中间层各只出现一次
        def _has_client_group(node, code):
            for child in node.get("children", []):
                if child.get("node_type") == "client_group" and child.get("account_code") == code:
                    return True
            return False
        assert _has_client_group(node_170402, "530101"), "170402 下应存在 530101 客户层级"
        # 53010101 在 530101 下只出现一次
        group_530101 = next(c for c in node_170402["children"]
                            if c.get("node_type") == "client_group"
                            and c.get("account_code") == "530101")
        g53010101_count = sum(
            1 for c in group_530101["children"]
            if c.get("node_type") == "client_group" and c.get("account_code") == "53010101"
        )
        assert g53010101_count == 1, f"53010101 层级应只出现一次，实际: {g53010101_count}"

        # 整棵树不允许重复 node_id
        all_ids: list = []
        for root in nodes:
            _collect_node_ids(root, all_ids)
        assert len(all_ids) == len(set(all_ids)), \
            f"整棵树存在重复 node_id，重复项: {[i for i in all_ids if all_ids.count(i) > 1]}"

    @pytest.mark.asyncio
    async def test_2221_shared_synth_parent_no_dup(self, db):
        std = await _create_account(db, "2221", "应交税费", level=1, is_leaf=True)
        batch = await _create_batch(db, file_name="tax_multi.xlsx")

        rows = [
            ("2221010101", "应交税费_应交增值税_进项税额_货物进项税", Decimal("60.00")),
            ("2221010102", "应交税费_应交增值税_进项税额_固定资产进项税", Decimal("40.00")),
        ]
        for idx, (code, name, amt) in enumerate(rows):
            raw = StandardTrialBalanceRawRow(
                batch_id=batch.id, row_index=idx, raw_values={},
                client_account_code=code, client_account_name=name,
                detected_level=4, is_leaf=True,
                mapped_standard_account_id=std.id, mapping_status="mapped",
            )
            db.add(raw)
            await db.flush()
            await _create_entry(db, batch.id, std,
                                raw_row_id=raw.id,
                                client_account_code=code,
                                client_account_name=name,
                                ending_credit=amt)

        nodes, _ = await get_tree(db, batch_id=batch.id)
        node_2221 = _find_node_by_code(nodes, "2221")
        assert node_2221 is not None
        assert node_2221["entry_count"] == 2, \
            f"2221 entry_count 应为 2，实际: {node_2221['entry_count']}"
        assert _recursive_entry_nodes(node_2221) == 2, \
            f"2221 递归 entry 节点应为 2，实际: {_recursive_entry_nodes(node_2221)}"

        # 222101 / 22210101 链路各只出现一次
        group_222101_count = sum(
            1 for c in node_2221["children"]
            if c.get("node_type") == "client_group" and c.get("account_code") == "222101"
        )
        assert group_222101_count == 1, f"222101 层级应只出现一次，实际: {group_222101_count}"
        group_222101 = next(c for c in node_2221["children"]
                            if c.get("node_type") == "client_group"
                            and c.get("account_code") == "222101")
        group_22210101_count = sum(
            1 for c in group_222101["children"]
            if c.get("node_type") == "client_group" and c.get("account_code") == "22210101"
        )
        assert group_22210101_count == 1, f"22210101 层级应只出现一次，实际: {group_22210101_count}"

        all_ids: list = []
        for root in nodes:
            _collect_node_ids(root, all_ids)
        assert len(all_ids) == len(set(all_ids)), "整棵树存在重复 node_id"
