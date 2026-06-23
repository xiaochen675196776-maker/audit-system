"""标准科目与标准科目余额表模型底座测试 — TASK-039"""

import uuid
import pytest
from decimal import Decimal
from sqlalchemy import select

from app.models.standard_account import StandardAccount
from app.models.client_account_mapping import ClientAccountMapping
from app.models.standard_trial_balance_import_batch import StandardTrialBalanceImportBatch
from app.models.standard_trial_balance_raw_row import StandardTrialBalanceRawRow
from app.models.standard_trial_balance_entry import StandardTrialBalanceEntry


# ── StandardAccount 测试 ──────────────────────────────

class TestStandardAccount:
    """标准科目模型测试"""

    @pytest.mark.asyncio
    async def test_create_basic(self, db):
        """创建基础标准科目"""
        sa = StandardAccount(
            account_code="1001",
            account_name="库存现金",
            account_category="asset",
            balance_direction="debit",
            level=1,
            is_leaf=True,
            is_active=True,
            source_row_index=0,
        )
        db.add(sa)
        await db.flush()

        assert sa.id is not None
        assert sa.account_code == "1001"
        assert sa.account_name == "库存现金"
        assert sa.account_category == "asset"
        assert sa.balance_direction == "debit"
        assert sa.level == 1
        assert sa.is_leaf is True
        assert sa.is_active is True
        assert sa.source_row_index == 0
        assert sa.created_at is not None
        assert sa.updated_at is not None

    @pytest.mark.asyncio
    async def test_account_code_unique(self, db):
        """科目代码唯一约束"""
        sa1 = StandardAccount(account_code="1001", account_name="库存现金")
        sa2 = StandardAccount(account_code="1001", account_name="现金(重复)")
        db.add(sa1)
        await db.flush()
        db.add(sa2)
        with pytest.raises(Exception):
            await db.flush()

    @pytest.mark.asyncio
    async def test_default_field_values(self, db):
        """默认字段值"""
        sa = StandardAccount(account_code="2001", account_name="短期借款")
        db.add(sa)
        await db.flush()

        assert sa.is_leaf is True
        assert sa.is_active is True
        assert sa.account_category is None
        assert sa.balance_direction is None
        assert sa.level is None
        assert sa.parent_id is None
        assert sa.source_row_index is None
        assert sa.created_at is not None
        assert sa.updated_at is not None

    @pytest.mark.asyncio
    async def test_is_active_toggle(self, db):
        """标准科目停用/启用"""
        sa = StandardAccount(account_code="1002", account_name="银行存款", is_active=True)
        db.add(sa)
        await db.flush()
        assert sa.is_active is True

        # 停用
        sa.is_active = False
        await db.flush()
        assert sa.is_active is False

        # 重新启用
        sa.is_active = True
        await db.flush()
        assert sa.is_active is True

    @pytest.mark.asyncio
    async def test_parent_child_hierarchy(self, db):
        """父子层级自引用"""
        parent = StandardAccount(
            account_code="1001", account_name="库存现金",
            level=1, is_leaf=False
        )
        db.add(parent)
        await db.flush()

        child = StandardAccount(
            account_code="1001001", account_name="人民币",
            level=2, parent_id=parent.id, is_leaf=True
        )
        db.add(child)
        await db.flush()

        assert child.parent_id == parent.id
        assert child.level == 2

    @pytest.mark.asyncio
    async def test_optional_fields_nullable(self, db):
        """可选字段允许为 NULL"""
        sa = StandardAccount(account_code="5001", account_name="主营业务收入")
        db.add(sa)
        await db.flush()

        assert sa.account_category is None
        assert sa.balance_direction is None
        assert sa.level is None
        assert sa.parent_id is None
        assert sa.source_row_index is None

    @pytest.mark.asyncio
    async def test_repr(self, db):
        """__repr__ 输出"""
        sa = StandardAccount(
            account_code="1001", account_name="库存现金",
            is_active=True
        )
        db.add(sa)
        await db.flush()
        r = repr(sa)
        assert "StandardAccount" in r
        assert "1001" in r
        assert "库存现金" in r


# ── ClientAccountMapping 测试 ─────────────────────────

class TestClientAccountMapping:
    """客户科目映射经验模型测试"""

    @pytest.mark.asyncio
    async def test_create_basic(self, db):
        """创建基础映射经验"""
        # 先创建标准科目
        sa = StandardAccount(account_code="1001", account_name="库存现金")
        db.add(sa)
        await db.flush()

        cam = ClientAccountMapping(
            data_type="trial_balance",
            customer_label="测试公司",
            client_account_code="1001",
            client_account_name="现金",
            normalized_client_account_name="现金",
            standard_account_id=sa.id,
            standard_account_code_snapshot="1001",
            standard_account_name_snapshot="库存现金",
            confidence=0.95,
            scope="global",
        )
        db.add(cam)
        await db.flush()

        assert cam.id is not None
        assert cam.data_type == "trial_balance"
        assert cam.customer_label == "测试公司"
        assert cam.client_account_code == "1001"
        assert cam.client_account_name == "现金"
        assert cam.normalized_client_account_name == "现金"
        assert cam.standard_account_id == sa.id
        assert cam.standard_account_code_snapshot == "1001"
        assert cam.standard_account_name_snapshot == "库存现金"
        assert cam.confidence == 0.95
        assert cam.scope == "global"
        assert cam.usage_count == 0
        assert cam.is_active is True

    @pytest.mark.asyncio
    async def test_default_field_values(self, db):
        """默认字段值"""
        cam = ClientAccountMapping(data_type="trial_balance")
        db.add(cam)
        await db.flush()

        assert cam.confidence == 0.0
        assert cam.scope == "global"
        assert cam.usage_count == 0
        assert cam.is_active is True
        assert cam.customer_label is None
        assert cam.client_account_code is None
        assert cam.client_account_name is None
        assert cam.standard_account_id is None
        assert cam.last_used_at is None

    @pytest.mark.asyncio
    async def test_usage_count_and_last_used(self, db):
        """使用计数和最后使用时间"""
        from datetime import datetime, timezone

        cam = ClientAccountMapping(data_type="trial_balance", client_account_code="1001")
        db.add(cam)
        await db.flush()

        assert cam.usage_count == 0
        assert cam.last_used_at is None

        cam.usage_count += 1
        cam.last_used_at = datetime.now(timezone.utc)
        await db.flush()

        assert cam.usage_count == 1
        assert cam.last_used_at is not None

    @pytest.mark.asyncio
    async def test_scope_values(self, db):
        """scope 字段 global/company"""
        cam_global = ClientAccountMapping(
            data_type="trial_balance", scope="global", client_account_code="G001"
        )
        cam_company = ClientAccountMapping(
            data_type="trial_balance", scope="company", client_account_code="C001"
        )
        db.add_all([cam_global, cam_company])
        await db.flush()

        assert cam_global.scope == "global"
        assert cam_company.scope == "company"

    @pytest.mark.asyncio
    async def test_is_active_toggle(self, db):
        """停用/启用映射经验"""
        cam = ClientAccountMapping(data_type="trial_balance", client_account_code="1001")
        db.add(cam)
        await db.flush()

        assert cam.is_active is True
        cam.is_active = False
        await db.flush()
        assert cam.is_active is False

    @pytest.mark.asyncio
    async def test_data_types(self, db):
        """支持三种数据类型"""
        for dt in ("trial_balance", "journal", "subsidiary"):
            cam = ClientAccountMapping(data_type=dt)
            db.add(cam)
        await db.flush()

        result = await db.execute(select(ClientAccountMapping))
        rows = result.scalars().all()
        assert len(rows) == 3
        data_types = {r.data_type for r in rows}
        assert data_types == {"trial_balance", "journal", "subsidiary"}

    @pytest.mark.asyncio
    async def test_repr(self, db):
        """__repr__ 输出"""
        cam = ClientAccountMapping(
            data_type="trial_balance",
            client_account_code="1001",
            standard_account_code_snapshot="1001",
        )
        db.add(cam)
        await db.flush()
        r = repr(cam)
        assert "ClientAccountMapping" in r
        assert "1001" in r


# ── StandardTrialBalanceImportBatch 测试 ──────────────

class TestImportBatch:
    """标准化导入批次模型测试"""

    @pytest.mark.asyncio
    async def test_create_basic(self, db):
        """创建基础导入批次"""
        batch = StandardTrialBalanceImportBatch(
            file_name="科目余额表2024.xlsx",
            customer_label="测试公司",
            source_label="用友U8",
            fiscal_year=2024,
            period=1,
        )
        db.add(batch)
        await db.flush()

        assert batch.id is not None
        assert batch.file_name == "科目余额表2024.xlsx"
        assert batch.customer_label == "测试公司"
        assert batch.source_label == "用友U8"
        assert batch.fiscal_year == 2024
        assert batch.period == 1
        assert batch.status == "draft"
        assert batch.field_mapping is None
        assert batch.amount_mapping_config is None
        assert batch.hierarchy_config is None
        assert batch.warnings is None
        assert batch.errors is None

    @pytest.mark.asyncio
    async def test_default_field_values(self, db):
        """默认字段值"""
        batch = StandardTrialBalanceImportBatch(file_name="test.xlsx")
        db.add(batch)
        await db.flush()

        assert batch.status == "draft"
        assert batch.fiscal_year is None
        assert batch.period is None
        assert batch.customer_label is None
        assert batch.source_label is None
        assert batch.field_mapping is None
        assert batch.errors is None

    @pytest.mark.asyncio
    async def test_status_transitions(self, db):
        """批次状态流转"""
        batch = StandardTrialBalanceImportBatch(file_name="test.xlsx")
        db.add(batch)
        await db.flush()

        for status in ("draft", "processing", "completed", "failed"):
            batch.status = status
            await db.flush()
            assert batch.status == status

    @pytest.mark.asyncio
    async def test_json_configs(self, db):
        """JSON 配置字段"""
        batch = StandardTrialBalanceImportBatch(
            file_name="test.xlsx",
            field_mapping={"科目代码": "account_code", "科目名称": "account_name"},
            amount_mapping_config={"mode": "split_by_direction"},
            hierarchy_config={"detect_levels": True, "check_parent_sums": True},
            warnings=[{"level": "warning", "message": "父级金额不一致"}],
            errors=None,
        )
        db.add(batch)
        await db.flush()

        assert batch.field_mapping["科目代码"] == "account_code"
        assert batch.amount_mapping_config["mode"] == "split_by_direction"
        assert batch.hierarchy_config["detect_levels"] is True
        assert len(batch.warnings) == 1

    @pytest.mark.asyncio
    async def test_repr(self, db):
        """__repr__ 输出"""
        batch = StandardTrialBalanceImportBatch(
            file_name="test.xlsx", fiscal_year=2024, period=1
        )
        db.add(batch)
        await db.flush()
        r = repr(batch)
        assert "StandardTrialBalanceImportBatch" in r
        assert "test.xlsx" in r
        assert "draft" in r


# ── StandardTrialBalanceRawRow 测试 ───────────────────

class TestRawRow:
    """原始行快照模型测试"""

    @pytest.mark.asyncio
    async def test_create_basic(self, db):
        """创建基础原始行快照"""
        batch = StandardTrialBalanceImportBatch(file_name="test.xlsx")
        db.add(batch)
        await db.flush()

        row = StandardTrialBalanceRawRow(
            batch_id=batch.id,
            row_index=0,
            raw_values={"科目代码": "1001", "科目名称": "库存现金", "期末余额": "10000.00"},
            client_account_code="1001",
            client_account_name="库存现金",
            detected_level=1,
            is_leaf=True,
            mapping_status="pending",
        )
        db.add(row)
        await db.flush()

        assert row.id is not None
        assert row.batch_id == batch.id
        assert row.row_index == 0
        assert row.raw_values["科目代码"] == "1001"
        assert row.client_account_code == "1001"
        assert row.client_account_name == "库存现金"
        assert row.detected_level == 1
        assert row.is_leaf is True
        assert row.mapping_status == "pending"
        assert row.parent_raw_row_id is None

    @pytest.mark.asyncio
    async def test_default_field_values(self, db):
        """默认字段值"""
        batch = StandardTrialBalanceImportBatch(file_name="test.xlsx")
        db.add(batch)
        await db.flush()

        row = StandardTrialBalanceRawRow(
            batch_id=batch.id,
            row_index=0,
            raw_values={},
        )
        db.add(row)
        await db.flush()

        assert row.is_leaf is False
        assert row.mapping_status == "pending"
        assert row.client_account_code is None
        assert row.client_account_name is None
        assert row.detected_level is None
        assert row.mapped_standard_account_id is None

    @pytest.mark.asyncio
    async def test_mapping_status_values(self, db):
        """映射状态枚举值"""
        batch = StandardTrialBalanceImportBatch(file_name="test.xlsx")
        db.add(batch)
        await db.flush()

        for status in ("pending", "mapped", "unmapped", "ignored"):
            row = StandardTrialBalanceRawRow(
                batch_id=batch.id,
                row_index=0,
                raw_values={},
                mapping_status=status,
            )
            db.add(row)
        await db.flush()

        result = await db.execute(select(StandardTrialBalanceRawRow))
        rows = result.scalars().all()
        statuses = {r.mapping_status for r in rows}
        assert statuses == {"pending", "mapped", "unmapped", "ignored"}

    @pytest.mark.asyncio
    async def test_map_to_standard_account(self, db):
        """映射到标准科目"""
        batch = StandardTrialBalanceImportBatch(file_name="test.xlsx")
        db.add(batch)
        await db.flush()

        sa = StandardAccount(account_code="1001", account_name="库存现金")
        db.add(sa)
        await db.flush()

        row = StandardTrialBalanceRawRow(
            batch_id=batch.id,
            row_index=0,
            raw_values={"code": "1001"},
            client_account_code="1001",
            mapped_standard_account_id=sa.id,
            mapping_status="mapped",
        )
        db.add(row)
        await db.flush()

        assert row.mapped_standard_account_id == sa.id
        assert row.mapping_status == "mapped"

    @pytest.mark.asyncio
    async def test_parent_child_hierarchy(self, db):
        """原始行父子层级"""
        batch = StandardTrialBalanceImportBatch(file_name="test.xlsx")
        db.add(batch)
        await db.flush()

        parent = StandardTrialBalanceRawRow(
            batch_id=batch.id, row_index=0, raw_values={"name": "资产"},
            detected_level=1, is_leaf=False,
        )
        db.add(parent)
        await db.flush()

        child = StandardTrialBalanceRawRow(
            batch_id=batch.id, row_index=1, raw_values={"name": "库存现金"},
            detected_level=2, is_leaf=True, parent_raw_row_id=parent.id,
        )
        db.add(child)
        await db.flush()

        assert child.parent_raw_row_id == parent.id
        assert child.is_leaf is True
        assert parent.is_leaf is False

    @pytest.mark.asyncio
    async def test_warnings_field(self, db):
        """警告字段"""
        batch = StandardTrialBalanceImportBatch(file_name="test.xlsx")
        db.add(batch)
        await db.flush()

        row = StandardTrialBalanceRawRow(
            batch_id=batch.id,
            row_index=0,
            raw_values={},
            warnings={"level": "warning", "message": "科目代码为空"},
        )
        db.add(row)
        await db.flush()

        assert row.warnings["message"] == "科目代码为空"

    @pytest.mark.asyncio
    async def test_repr(self, db):
        """__repr__ 输出"""
        batch = StandardTrialBalanceImportBatch(file_name="test.xlsx")
        db.add(batch)
        await db.flush()

        row = StandardTrialBalanceRawRow(
            batch_id=batch.id, row_index=5, mapping_status="mapped"
        )
        db.add(row)
        await db.flush()
        r = repr(row)
        assert "StandardTrialBalanceRawRow" in r
        assert "mapped" in r


# ── StandardTrialBalanceEntry 测试 ────────────────────

class TestTrialBalanceEntry:
    """标准科目余额表明细模型测试"""

    @pytest.mark.asyncio
    async def test_create_basic(self, db):
        """创建基础标准余额表明细"""
        batch = StandardTrialBalanceImportBatch(file_name="test.xlsx")
        db.add(batch)
        await db.flush()

        sa = StandardAccount(
            account_code="1001", account_name="库存现金",
            account_category="asset", balance_direction="debit"
        )
        db.add(sa)
        await db.flush()

        entry = StandardTrialBalanceEntry(
            batch_id=batch.id,
            standard_account_id=sa.id,
            standard_account_code_snapshot="1001",
            standard_account_name_snapshot="库存现金",
            standard_account_category_snapshot="asset",
            standard_balance_direction_snapshot="debit",
            client_account_code="1001",
            client_account_name="库存现金",
            fiscal_year=2024,
            period=1,
            opening_debit=Decimal("10000.00"),
            opening_credit=Decimal("0"),
            current_debit=Decimal("5000.00"),
            current_credit=Decimal("2000.00"),
            ending_debit=Decimal("13000.00"),
            ending_credit=Decimal("0"),
        )
        db.add(entry)
        await db.flush()

        assert entry.id is not None
        assert entry.batch_id == batch.id
        assert entry.standard_account_id == sa.id
        assert entry.standard_account_code_snapshot == "1001"
        assert entry.standard_account_name_snapshot == "库存现金"
        assert entry.standard_account_category_snapshot == "asset"
        assert entry.standard_balance_direction_snapshot == "debit"
        assert entry.fiscal_year == 2024
        assert entry.period == 1
        assert entry.opening_debit == Decimal("10000.00")
        assert entry.opening_credit == Decimal("0")
        assert entry.current_debit == Decimal("5000.00")
        assert entry.current_credit == Decimal("2000.00")
        assert entry.ending_debit == Decimal("13000.00")
        assert entry.ending_credit == Decimal("0")

    @pytest.mark.asyncio
    async def test_amount_defaults(self, db):
        """金额默认值为0"""
        batch = StandardTrialBalanceImportBatch(file_name="test.xlsx")
        db.add(batch)
        await db.flush()

        sa = StandardAccount(account_code="1001", account_name="库存现金")
        db.add(sa)
        await db.flush()

        entry = StandardTrialBalanceEntry(
            batch_id=batch.id,
            standard_account_id=sa.id,
            standard_account_code_snapshot="1001",
            standard_account_name_snapshot="库存现金",
            fiscal_year=2024,
            period=1,
        )
        db.add(entry)
        await db.flush()

        assert entry.opening_debit == Decimal("0")
        assert entry.opening_credit == Decimal("0")
        assert entry.current_debit == Decimal("0")
        assert entry.current_credit == Decimal("0")
        assert entry.ending_debit == Decimal("0")
        assert entry.ending_credit == Decimal("0")

    @pytest.mark.asyncio
    async def test_snapshot_fields_preserved(self, db):
        """快照字段在标准科目变更后仍保留原始快照"""
        batch = StandardTrialBalanceImportBatch(file_name="test.xlsx")
        db.add(batch)
        await db.flush()

        sa = StandardAccount(
            account_code="1001", account_name="库存现金",
            account_category="asset", balance_direction="debit"
        )
        db.add(sa)
        await db.flush()

        # 创建条目（快照导入时的值）
        entry = StandardTrialBalanceEntry(
            batch_id=batch.id,
            standard_account_id=sa.id,
            standard_account_code_snapshot="1001",
            standard_account_name_snapshot="库存现金",
            standard_account_category_snapshot="asset",
            standard_balance_direction_snapshot="debit",
            fiscal_year=2024,
            period=1,
        )
        db.add(entry)
        await db.flush()

        # 修改标准科目（模拟后续更新）
        sa.account_name = "库存现金（已更名）"
        sa.account_category = "liability"
        await db.flush()

        # 快照不应改变
        assert entry.standard_account_code_snapshot == "1001"
        assert entry.standard_account_name_snapshot == "库存现金"
        assert entry.standard_account_category_snapshot == "asset"
        assert entry.standard_balance_direction_snapshot == "debit"

    @pytest.mark.asyncio
    async def test_raw_row_link(self, db):
        """关联原始行快照"""
        batch = StandardTrialBalanceImportBatch(file_name="test.xlsx")
        db.add(batch)
        await db.flush()

        sa = StandardAccount(account_code="1001", account_name="库存现金")
        db.add(sa)
        await db.flush()

        raw_row = StandardTrialBalanceRawRow(
            batch_id=batch.id, row_index=0, raw_values={},
        )
        db.add(raw_row)
        await db.flush()

        entry = StandardTrialBalanceEntry(
            batch_id=batch.id,
            raw_row_id=raw_row.id,
            standard_account_id=sa.id,
            standard_account_code_snapshot="1001",
            standard_account_name_snapshot="库存现金",
            fiscal_year=2024,
            period=1,
        )
        db.add(entry)
        await db.flush()

        assert entry.raw_row_id == raw_row.id

    @pytest.mark.asyncio
    async def test_decimal_precision(self, db):
        """金额精度 Numeric(20,2)"""
        batch = StandardTrialBalanceImportBatch(file_name="test.xlsx")
        db.add(batch)
        await db.flush()

        sa = StandardAccount(account_code="1001", account_name="库存现金")
        db.add(sa)
        await db.flush()

        entry = StandardTrialBalanceEntry(
            batch_id=batch.id,
            standard_account_id=sa.id,
            standard_account_code_snapshot="1001",
            standard_account_name_snapshot="库存现金",
            fiscal_year=2024,
            period=1,
            opening_debit=Decimal("123456789012345678.99"),
        )
        db.add(entry)
        await db.flush()

        assert entry.opening_debit == Decimal("123456789012345678.99")

    @pytest.mark.asyncio
    async def test_repr(self, db):
        """__repr__ 输出"""
        batch = StandardTrialBalanceImportBatch(file_name="test.xlsx")
        db.add(batch)
        await db.flush()

        sa = StandardAccount(account_code="1001", account_name="库存现金")
        db.add(sa)
        await db.flush()

        entry = StandardTrialBalanceEntry(
            batch_id=batch.id,
            standard_account_id=sa.id,
            standard_account_code_snapshot="1001",
            standard_account_name_snapshot="库存现金",
            fiscal_year=2024,
            period=1,
        )
        db.add(entry)
        await db.flush()
        r = repr(entry)
        assert "StandardTrialBalanceEntry" in r
        assert "1001" in r
        assert "2024" in r
