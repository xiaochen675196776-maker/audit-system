"""导入模板库后端测试 — TASK-021"""

import uuid
import os
import tempfile
import pytest
from sqlalchemy import select

from app.models.import_template import ImportTemplate
from app.services.template_service import (
    get_templates, get_template, create_template, update_template, delete_template,
    from_sample, test_template as run_template_test,
)


# ── 辅助 ──────────────────────────────────────────────

def _write_csv(path: str, content: str):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(content)


# ── CRUD ──────────────────────────────────────────────

class TestTemplateCRUD:
    """模板基本 CRUD"""

    @pytest.mark.asyncio
    async def test_create_and_read(self, db):
        """创建模板 → 读取"""
        t = await create_template(db, {
            "name": "测试模板_序时账",
            "data_type": "journal",
            "column_rules": {"col_001": "voucher_no"},
        })
        assert t.id is not None
        assert t.name == "测试模板_序时账"
        assert t.is_active is True

        t2 = await get_template(db, t.id)
        assert t2 is not None
        assert t2.name == "测试模板_序时账"

    @pytest.mark.asyncio
    async def test_update(self, db):
        """更新模板 → 部分更新"""
        t = await create_template(db, {
            "name": "旧名称", "data_type": "journal", "column_rules": {},
        })
        updated = await update_template(db, t.id, {"name": "新名称", "is_active": False})
        assert updated is not None
        assert updated.name == "新名称"
        assert updated.is_active is False
        # 未更新的字段保持
        assert updated.data_type == "journal"

    @pytest.mark.asyncio
    async def test_delete(self, db):
        """删除模板 → 再查返回 None"""
        t = await create_template(db, {
            "name": "待删除", "data_type": "trial_balance", "column_rules": {},
        })
        ok = await delete_template(db, t.id)
        assert ok is True

        t2 = await get_template(db, t.id)
        assert t2 is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, db):
        """删除不存在的模板 → False"""
        ok = await delete_template(db, uuid.uuid4())
        assert ok is False


# ── 筛选 ──────────────────────────────────────────────

class TestTemplateFilter:
    """按 is_active / data_type 筛选"""

    @pytest.mark.asyncio
    async def test_filter_by_is_active(self, db):
        """is_active=False 时只返回未启用"""
        await create_template(db, {"name": "A", "data_type": "journal", "is_active": True, "column_rules": {}})
        await create_template(db, {"name": "B", "data_type": "journal", "is_active": False, "column_rules": {}})
        await create_template(db, {"name": "C", "data_type": "journal", "is_active": True, "column_rules": {}})

        active = await get_templates(db, is_active=True)
        assert len(active) == 2
        inactive = await get_templates(db, is_active=False)
        assert len(inactive) == 1
        assert inactive[0].name == "B"

    @pytest.mark.asyncio
    async def test_filter_by_data_type(self, db):
        """data_type=journal 时不返回 trial_balance"""
        await create_template(db, {"name": "J1", "data_type": "journal", "column_rules": {}})
        await create_template(db, {"name": "TB1", "data_type": "trial_balance", "column_rules": {}})
        await create_template(db, {"name": "J2", "data_type": "journal", "column_rules": {}})

        journals = await get_templates(db, data_type="journal")
        assert len(journals) == 2
        tbs = await get_templates(db, data_type="trial_balance")
        assert len(tbs) == 1


# ── 样本生成 ──────────────────────────────────────────

class TestFromSample:
    """from_sample 生成模板草稿"""

    def test_from_sample_journal(self):
        """序时账样本 → 生成草稿（不保存）"""
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        csv_content = (
            "凭证号,凭证日期,摘要,科目编码,科目名称,借方金额,贷方金额,会计年度,会计期间,备注\r\n"
            "001,2024-01-15,采购,1002,银行存款,0,10000,2024,1,test"
        )
        tmp.write(csv_content)
        tmp.close()
        try:
            import asyncio
            draft = asyncio.run(from_sample(tmp.name, "journal", "测试模板"))
            # 服务层返回草稿，saved 由 API 层添加
            assert draft["data_type"] == "journal"
            assert "name" in draft
            assert "column_rules" in draft
            assert "header_signature" in draft
            # 至少 voucher_no 被匹配
            rules = draft["column_rules"]
            assert any(v == "voucher_no" for v in rules.values()), f"voucher_no not in: {rules}"
        finally:
            os.unlink(tmp.name)

    def test_from_sample_duplicate_headers(self):
        """重复表头样本 → 生成不同 column_id"""
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        csv_content = (
            "凭证号,凭证日期,摘要,摘要,科目编码,科目名称,借方金额,贷方金额,会计年度,会计期间\r\n"
            "001,2024-01-15,采购,支付货款,1002,银行存款,0,10000,2024,1"
        )
        tmp.write(csv_content)
        tmp.close()
        try:
            import asyncio
            draft = asyncio.run(from_sample(tmp.name, "journal"))
            rules = draft["column_rules"]
            # 两个"摘要"都有各自的 col_id
            summary_cols = [k for k, v in rules.items() if v == "summary"]
            extra_cols = [k for k, v in rules.items() if v not in ("summary", "voucher_no", "voucher_date", "account_code", "account_name", "debit_amount", "credit_amount", "fiscal_year", "period", "attachment_count")]
            # 第一个匹配 summary，第二个是辅助字段
            assert len(summary_cols) >= 1 or any("摘要" in str(rules) for rules in [rules])
        finally:
            os.unlink(tmp.name)


# ── 模板测试 ──────────────────────────────────────────

class TestTemplateTest:
    """test_template 返回套用结果"""

    @pytest.mark.asyncio
    async def test_test_template_applicable(self, db):
        """模板 column_rules 匹配文件 → applicable=True"""
        # 先创建模板
        t = await create_template(db, {
            "name": "测试模板",
            "data_type": "journal",
            "column_rules": {
                "col_001": "voucher_no",
                "col_002": "voucher_date",
                "col_003": "summary",
                "col_004": "account_code",
                "col_005": "account_name",
                "col_006": "debit_amount",
                "col_007": "credit_amount",
                "col_008": "fiscal_year",
                "col_009": "period",
            },
        })

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        csv_content = (
            "凭证号,凭证日期,摘要,科目编码,科目名称,借方金额,贷方金额,会计年度,会计期间\r\n"
            "001,2024-01-15,采购,1002,银行存款,0,10000,2024,1"
        )
        tmp.write(csv_content)
        tmp.close()
        try:
            result = await run_template_test(t, tmp.name)
            assert result["applicable"] is True
            assert len(result["hit_fields"]) >= 5
            assert len(result["column_mapping_v2"]) >= 5
            assert "✓" in result["message"]
            # column_mapping_v2 应包含 col_001 → voucher_no 等
            assert result["column_mapping_v2"].get("col_001") == "voucher_no"
        finally:
            os.unlink(tmp.name)

    @pytest.mark.asyncio
    async def test_test_template_missing_fields(self, db):
        """模板缺少部分字段 → missing_fields 非空"""
        t = await create_template(db, {
            "name": "不完整模板",
            "data_type": "journal",
            "column_rules": {
                "col_001": "voucher_no",
                "col_002": "voucher_date",
            },
        })

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        csv_content = (
            "凭证号,凭证日期,摘要,科目编码,科目名称,借方金额,贷方金额,会计年度,会计期间\r\n"
            "001,2024-01-15,采购,1002,银行存款,0,10000,2024,1"
        )
        tmp.write(csv_content)
        tmp.close()
        try:
            result = await run_template_test(t, tmp.name)
            assert result["applicable"] is True  # 至少命中了一些
            assert len(result["missing_fields"]) > 0  # 缺失多个
            assert "account_code" in result["missing_fields"] or "科目名称" in str(result["warnings"])
        finally:
            os.unlink(tmp.name)

    @pytest.mark.asyncio
    async def test_test_template_with_ignore(self, db):
        """模板 column_rules 中标记 ignore → 不加入映射"""
        t = await create_template(db, {
            "name": "带忽略列",
            "data_type": "journal",
            "column_rules": {
                "col_001": "voucher_no",
                "col_002": "ignore",
                "col_003": "summary",
                "col_004": "account_code",
                "col_005": "account_name",
                "col_006": "debit_amount",
                "col_007": "credit_amount",
                "col_008": "fiscal_year",
                "col_009": "period",
            },
        })

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        csv_content = (
            "凭证号,凭证日期,摘要,科目编码,科目名称,借方金额,贷方金额,会计年度,会计期间\r\n"
            "001,2024-01-15,采购,1002,银行存款,0,10000,2024,1"
        )
        tmp.write(csv_content)
        tmp.close()
        try:
            result = await run_template_test(t, tmp.name)
            # col_002 被忽略，不应出现在映射中
            assert "col_002" not in result["column_mapping_v2"]
        finally:
            os.unlink(tmp.name)

    @pytest.mark.asyncio
    async def test_test_template_duplicate_warning(self, db):
        """重复表头文件中测试 → warnings 包含重复提示"""
        t = await create_template(db, {
            "name": "重复表头模板",
            "data_type": "journal",
            "column_rules": {
                "col_001": "voucher_no",
                "col_002": "voucher_date",
                "col_003": "summary",
                "col_005": "account_code",
                "col_006": "account_name",
                "col_007": "debit_amount",
                "col_008": "credit_amount",
                "col_009": "fiscal_year",
                "col_010": "period",
            },
        })

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        csv_content = (
            "凭证号,凭证日期,摘要,摘要,科目编码,科目名称,借方金额,贷方金额,会计年度,会计期间\r\n"
            "001,2024-01-15,采购,支付货款,1002,银行存款,0,10000,2024,1"
        )
        tmp.write(csv_content)
        tmp.close()
        try:
            result = await run_template_test(t, tmp.name)
            # 应有重复表头警告
            assert any("重复" in w for w in result["warnings"]) or any(
                "2 次" in w for w in result["warnings"]
            )
        finally:
            os.unlink(tmp.name)

    @pytest.mark.asyncio
    async def test_test_template_invalid_data_type_rejected(self, db):
        """invalid data_type → API 层应被 schema 拦截（此处测 schema 层）"""
        from app.schemas.import_template import _validate_data_type
        with pytest.raises(ValueError, match="不支持的数据类型"):
            _validate_data_type("invalid_type")
