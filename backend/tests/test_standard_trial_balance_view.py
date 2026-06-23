"""标准科目余额表数据查看后端测试 — TASK-046"""

import uuid
import pytest
from decimal import Decimal
from datetime import datetime, timezone

from app.models.standard_account import StandardAccount
from app.models.standard_trial_balance_import_batch import StandardTrialBalanceImportBatch
from app.models.standard_trial_balance_entry import StandardTrialBalanceEntry
from app.services.standard_trial_balance_service import (
    get_batches,
    get_tree,
    get_entries,
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
        assert total == 1
        assert len(nodes) == 1
        assert nodes[0]["account_code"] == "1001"
        assert nodes[0]["opening_debit"] == Decimal("10000")
        assert nodes[0]["current_debit"] == Decimal("5000")
        assert nodes[0]["ending_debit"] == Decimal("15000")
        assert nodes[0]["entry_count"] == 1
        assert nodes[0]["has_children"] is False

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
        assert total == 3
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
        assert total == 3

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
        assert total == 1
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
        assert total == 2  # 父级 + 有金额子级
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
        assert total == 1
        assert nodes[0]["opening_debit"] == Decimal("100")

        # 只查 batch2
        nodes, total = await get_tree(db, batch_id=batch2.id)
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
