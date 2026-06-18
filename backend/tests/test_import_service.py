"""测试导入服务 — ORM 字段映射、空金额处理、import_data 流程"""

import uuid
import os
import tempfile
import pytest
from decimal import Decimal
from sqlalchemy import select
from app.services.import_service import import_data, preview_import, MODEL_MAP
from app.models.trial_balance import TrialBalance
from app.models.journal_entry import JournalEntry
from app.models.subsidiary_ledger import SubsidiaryLedger


def _write_csv(path: str, content: str, encoding: str = "utf-8"):
    with open(path, "w", encoding=encoding, newline="") as f:
        f.write(content)


class TestModelFieldMapping:
    """检查 MODEL_MAP 和数据流中字段是否与 ORM 匹配"""

    def test_trial_balance_fields_match_model(self):
        """TrialBalance 模型字段应与 TYPE_FIELDS 一致"""
        from app.services.column_matcher import TYPE_FIELDS
        model = TrialBalance
        # 获取 ORM 列名（排除 id, created_at, extra_fields, company_id）
        orm_columns = set(model.__table__.columns.keys())
        expected = TYPE_FIELDS["trial_balance"] + ["company_id"]
        # id 和 created_at 应该由 DB 自动生成，不应传入
        auto_fields = {"id", "created_at", "extra_fields"}
        relevant_orm = orm_columns - auto_fields
        relevant_expected = set(expected)
        # 所有期望字段都应在模型中，且不超过模型字段
        assert relevant_expected.issubset(relevant_orm | {"company_id"}), \
            f"TYPE_FIELDS has extra: {relevant_expected - relevant_orm}"

    def test_journal_fields_match_model(self):
        """JournalEntry 模型字段应与 TYPE_FIELDS 一致"""
        from app.services.column_matcher import TYPE_FIELDS
        model = JournalEntry
        orm_columns = set(model.__table__.columns.keys())
        expected = TYPE_FIELDS["journal"] + ["company_id"]
        auto_fields = {"id", "created_at"}
        relevant_orm = orm_columns - auto_fields
        relevant_expected = set(expected)
        assert relevant_expected.issubset(relevant_orm | {"company_id"}), \
            f"TYPE_FIELDS has extra: {relevant_expected - relevant_orm}"

    def test_subsidiary_fields_match_model(self):
        """SubsidiaryLedger 模型字段应与 TYPE_FIELDS 一致"""
        from app.services.column_matcher import TYPE_FIELDS
        model = SubsidiaryLedger
        orm_columns = set(model.__table__.columns.keys())
        expected = TYPE_FIELDS["subsidiary"] + ["company_id"]
        auto_fields = {"id", "created_at"}
        relevant_orm = orm_columns - auto_fields
        relevant_expected = set(expected)
        assert relevant_expected.issubset(relevant_orm | {"company_id"}), \
            f"TYPE_FIELDS has extra: {relevant_expected - relevant_orm}"


class TestImportDataTrialBalance:
    """科目余额表导入"""

    @pytest.mark.asyncio
    async def test_import_trial_balance_success(self, db, sample_company_id):
        """完整导入科目余额表"""
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        csv_content = (
            "科目编码,科目名称,会计年度,会计期间,"
            "期初借方余额,期初贷方余额,"
            "本期借方发生额,本期贷方发生额,"
            "期末借方余额,期末贷方余额\r\n"
            "1001,现金,2024,1,10000,0,5000,2000,13000,0\r\n"
            "1002,银行存款,2024,1,50000,0,0,10000,40000,0"
        )
        tmp.write(csv_content)
        tmp.close()
        try:
            result = await import_data(
                db=db, company_id=sample_company_id,
                file_path=tmp.name, data_type="trial_balance",
            )
            assert result["total"] == 2
            assert result["success"] == 2
            assert result["errors"] == []

            # 验证入库数据
            stmt = select(TrialBalance).where(TrialBalance.company_id == sample_company_id)
            res = await db.execute(stmt)
            rows = res.scalars().all()
            assert len(rows) == 2
            # 金额应为 Decimal
            assert rows[0].opening_debit == Decimal("10000")
            assert rows[0].ending_debit == Decimal("13000")
        finally:
            os.unlink(tmp.name)

    @pytest.mark.asyncio
    async def test_import_trial_balance_empty_amounts_become_zero(self, db, sample_company_id):
        """空金额应标准化为 0"""
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        csv_content = (
            "科目编码,科目名称,会计年度,会计期间,"
            "期初借方余额,期初贷方余额,"
            "本期借方发生额,本期贷方发生额,"
            "期末借方余额,期末贷方余额\r\n"
            "1001,现金,2024,1,,,,,,"  # 所有金额为空
        )
        tmp.write(csv_content)
        tmp.close()
        try:
            result = await import_data(
                db=db, company_id=sample_company_id,
                file_path=tmp.name, data_type="trial_balance",
            )
            assert result["success"] == 1

            stmt = select(TrialBalance).where(TrialBalance.company_id == sample_company_id)
            res = await db.execute(stmt)
            row = res.scalars().one()
            # 空金额应为 0（ORM 默认值）
            assert row.opening_debit == Decimal("0")
            assert row.opening_credit == Decimal("0")
            assert row.current_debit == Decimal("0")
            assert row.ending_debit == Decimal("0")
        finally:
            os.unlink(tmp.name)


class TestImportDataJournal:
    """序时账导入"""

    @pytest.mark.asyncio
    async def test_import_journal_success(self, db, sample_company_id):
        """完整导入序时账"""
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        csv_content = (
            "凭证号,凭证日期,摘要,科目编码,科目名称,借方金额,贷方金额,会计年度,会计期间\r\n"
            "001,2024-01-15,采购原材料,1403,原材料,10000,0,2024,1\r\n"
            "001,2024-01-15,采购原材料,1002,银行存款,0,10000,2024,1"
        )
        tmp.write(csv_content)
        tmp.close()
        try:
            result = await import_data(
                db=db, company_id=sample_company_id,
                file_path=tmp.name, data_type="journal",
            )
            assert result["total"] == 2
            assert result["success"] == 2
            assert result["errors"] == []

            stmt = select(JournalEntry).where(JournalEntry.company_id == sample_company_id)
            res = await db.execute(stmt)
            rows = res.scalars().all()
            assert len(rows) == 2
            assert rows[0].debit_amount == Decimal("10000")
        finally:
            os.unlink(tmp.name)

    @pytest.mark.asyncio
    async def test_import_journal_unbalanced_voucher(self, db, sample_company_id):
        """借贷不平衡的凭证应被检出但已平衡的仍入库"""
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        csv_content = (
            "凭证号,凭证日期,摘要,科目编码,科目名称,借方金额,贷方金额,会计年度,会计期间\r\n"
            "001,2024-01-15,不平衡凭证,1403,原材料,10000,0,2024,1\r\n"
            "001,2024-01-15,不平衡凭证,1002,银行存款,0,8000,2024,1"
        )
        tmp.write(csv_content)
        tmp.close()
        try:
            result = await import_data(
                db=db, company_id=sample_company_id,
                file_path=tmp.name, data_type="journal",
            )
            # 平衡校验发现不平衡
            assert len(result["errors"]) >= 1
            assert any("借贷不平衡" in e["message"] for e in result["errors"])
        finally:
            os.unlink(tmp.name)


class TestImportDataSubsidiary:
    """辅助明细账导入"""

    @pytest.mark.asyncio
    async def test_import_subsidiary_success(self, db, sample_company_id):
        """完整导入辅助明细账"""
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        csv_content = (
            "凭证号,凭证日期,摘要,科目编码,科目名称,借方金额,贷方金额,"
            "辅助核算类型,辅助核算编码,辅助核算名称,会计年度,会计期间\r\n"
            "001,2024-01-15,采购,1403,原材料,10000,0,供应商,SUP001,A公司,2024,1\r\n"
            "001,2024-01-15,采购,1002,银行存款,0,10000,供应商,SUP001,A公司,2024,1"
        )
        tmp.write(csv_content)
        tmp.close()
        try:
            result = await import_data(
                db=db, company_id=sample_company_id,
                file_path=tmp.name, data_type="subsidiary",
            )
            assert result["total"] == 2
            assert result["success"] == 2

            stmt = select(SubsidiaryLedger).where(SubsidiaryLedger.company_id == sample_company_id)
            res = await db.execute(stmt)
            rows = res.scalars().all()
            assert len(rows) == 2
            assert rows[0].auxiliary_type == "供应商"
            assert rows[0].auxiliary_code == "SUP001"
        finally:
            os.unlink(tmp.name)


class TestImportDataErrors:
    """导入错误处理"""

    @pytest.mark.asyncio
    async def test_required_field_missing(self, db, sample_company_id):
        """必填字段缺失 → 进入错误行"""
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        csv_content = (
            "凭证号,凭证日期,摘要,科目编码,科目名称,借方金额,贷方金额,会计年度,会计期间\r\n"
            "001,2024-01-15,,,原材料,10000,0,2024,1"  # 科目编码为空 → 必填字段缺失
        )
        tmp.write(csv_content)
        tmp.close()
        try:
            result = await import_data(
                db=db, company_id=sample_company_id,
                file_path=tmp.name, data_type="journal",
            )
            assert result["success"] == 0
            assert len(result["errors"]) >= 1
        finally:
            os.unlink(tmp.name)

    @pytest.mark.asyncio
    async def test_negative_amount_rejected(self, db, sample_company_id):
        """负数金额 → 进入错误行"""
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        csv_content = (
            "凭证号,凭证日期,摘要,科目编码,科目名称,借方金额,贷方金额,会计年度,会计期间\r\n"
            "001,2024-01-15,测试,1002,银行存款,-500,0,2024,1"
        )
        tmp.write(csv_content)
        tmp.close()
        try:
            result = await import_data(
                db=db, company_id=sample_company_id,
                file_path=tmp.name, data_type="journal",
            )
            assert result["success"] == 0
            assert len(result["errors"]) >= 1
            assert any("不能为负数" in e["message"] for e in result["errors"])
        finally:
            os.unlink(tmp.name)

    @pytest.mark.asyncio
    async def test_invalid_data_type_raises(self, db, sample_company_id):
        """未知数据类型抛出异常"""
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        tmp.write("a,b\n1,2")
        tmp.close()
        try:
            with pytest.raises(ValueError, match="未知的数据类型"):
                await import_data(
                    db=db, company_id=sample_company_id,
                    file_path=tmp.name, data_type="invalid_type",
                )
        finally:
            os.unlink(tmp.name)

    # === 回归测试：缺失 fiscal_year/period ===

    @pytest.mark.asyncio
    async def test_missing_fiscal_year_no_manual_returns_error(self, db, sample_company_id):
        """文件无 fiscal_year/period 且未传手动参数 → 返回错误（不触发 IntegrityError）"""
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        # 文件只有科目编码/名称/金额，没有年度/期间列
        csv_content = (
            "科目编码,科目名称,期初借方余额,期初贷方余额,"
            "本期借方发生额,本期贷方发生额,期末借方余额,期末贷方余额\r\n"
            "1001,现金,10000,0,5000,0,15000,0"
        )
        tmp.write(csv_content)
        tmp.close()
        try:
            result = await import_data(
                db=db, company_id=sample_company_id,
                file_path=tmp.name, data_type="trial_balance",
                # 不传 fiscal_year 和 period
            )
            # 不应成功入库
            assert result["success"] == 0
            # 应有错误信息
            assert len(result["errors"]) >= 1
            error_msgs = [e["message"] for e in result["errors"]]
            assert any("缺少会计年度" in msg for msg in error_msgs) or \
                   any("fiscal_year" in msg for msg in error_msgs)
        finally:
            os.unlink(tmp.name)

    @pytest.mark.asyncio
    async def test_missing_fiscal_year_with_manual_params_succeeds(self, db, sample_company_id):
        """文件无 fiscal_year/period 但传入手动参数 → 正常导入"""
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        csv_content = (
            "科目编码,科目名称,期初借方余额,期初贷方余额,"
            "本期借方发生额,本期贷方发生额,期末借方余额,期末贷方余额\r\n"
            "1001,现金,10000,0,5000,0,15000,0"
        )
        tmp.write(csv_content)
        tmp.close()
        try:
            result = await import_data(
                db=db, company_id=sample_company_id,
                file_path=tmp.name, data_type="trial_balance",
                fiscal_year=2024,
                period=1,
            )
            # 手动指定了年度和期间，应正常导入
            assert result["success"] == 1
            assert result["errors"] == []

            # 验证入库数据的年度/期间
            stmt = select(TrialBalance).where(TrialBalance.company_id == sample_company_id)
            res = await db.execute(stmt)
            row = res.scalars().one()
            assert row.fiscal_year == 2024
            assert row.period == 1
        finally:
            os.unlink(tmp.name)

    @pytest.mark.asyncio
    async def test_missing_period_only_returns_partial_error(self, db, sample_company_id):
        """文件有 fiscal_year 但缺少 period → 也应该报错"""
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        csv_content = (
            "科目编码,科目名称,会计年度,期初借方余额,期初贷方余额,"
            "本期借方发生额,本期贷方发生额,期末借方余额,期末贷方余额\r\n"
            "1001,现金,2024,10000,0,5000,0,15000,0"
        )
        tmp.write(csv_content)
        tmp.close()
        try:
            result = await import_data(
                db=db, company_id=sample_company_id,
                file_path=tmp.name, data_type="trial_balance",
            )
            # period 缺失
            assert result["success"] == 0
            error_msgs = [e["message"] for e in result["errors"]]
            assert any("缺少会计期间" in msg or "period" in msg for msg in error_msgs)
        finally:
            os.unlink(tmp.name)


class TestPreviewImport:
    """预览导入"""

    @pytest.mark.asyncio
    async def test_preview_returns_structure(self):
        """preview_import 返回正确结构"""
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        csv_content = "科目编码,科目名称,期初借方余额\r\n1001,现金,10000"
        tmp.write(csv_content)
        tmp.close()
        try:
            result = await preview_import(tmp.name, "trial_balance")
            assert result["file_name"].endswith(".csv")
            assert "headers" in result
            assert "matched" in result
            assert "unmatched" in result
            assert "missing" in result
            assert "preview_rows" in result
            assert result["row_count"] == 1
        finally:
            os.unlink(tmp.name)
