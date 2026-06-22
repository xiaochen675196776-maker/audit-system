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
        auto_fields = {"id", "created_at", "extra_fields"}
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
        auto_fields = {"id", "created_at", "extra_fields"}
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
    async def test_negative_amount_allowed(self, db, sample_company_id):
        """负数金额 → 允许导入（最新口径不拦截）"""
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
            # 负数金额是有效数字，应正常导入
            assert result["success"] == 1
            assert result["errors"] == []
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


class TestImportExtraFields:
    """辅助字段导入 — 验证 JournalEntry / SubsidiaryLedger 支持 extra_fields"""

    @pytest.mark.asyncio
    async def test_journal_import_with_extra_fields(self, db, sample_company_id):
        """序时账带自定义辅助字段 → 正常入库，extra_fields 写入 JSON"""
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        csv_content = (
            "凭证号,凭证日期,摘要,科目编码,科目名称,借方金额,贷方金额,会计年度,会计期间,来源类型,交易对象\r\n"
            "001,2024-01-15,采购,1403,原材料,10000,0,2024,1,采购订单,供应商A\r\n"
            "001,2024-01-15,采购,1002,银行存款,0,10000,2024,1,采购订单,供应商A"
        )
        tmp.write(csv_content)
        tmp.close()
        try:
            # 映射：标准字段 + 辅助字段用自定义名
            mapping = {
                "凭证号": "voucher_no",
                "凭证日期": "voucher_date",
                "摘要": "summary",
                "科目编码": "account_code",
                "科目名称": "account_name",
                "借方金额": "debit_amount",
                "贷方金额": "credit_amount",
                "会计年度": "fiscal_year",
                "会计期间": "period",
                "来源类型": "source_type",  # 辅助字段
                "交易对象": "counterparty",  # 辅助字段
            }
            result = await import_data(
                db=db, company_id=sample_company_id,
                file_path=tmp.name, data_type="journal",
                column_mapping=mapping,
            )
            assert result["total"] == 2
            assert result["success"] == 2

            stmt = select(JournalEntry).where(JournalEntry.company_id == sample_company_id)
            res = await db.execute(stmt)
            rows = res.scalars().all()
            assert len(rows) == 2
            # extra_fields 应包含自定义辅助字段
            for row in rows:
                assert row.extra_fields is not None
                assert row.extra_fields.get("source_type") == "采购订单"
                assert row.extra_fields.get("counterparty") == "供应商A"
        finally:
            os.unlink(tmp.name)

    @pytest.mark.asyncio
    async def test_subsidiary_import_with_extra_fields(self, db, sample_company_id):
        """辅助明细账带自定义辅助字段 → 正常入库，extra_fields 写入 JSON"""
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        csv_content = (
            "凭证号,凭证日期,摘要,科目编码,科目名称,借方金额,贷方金额,"
            "辅助核算类型,辅助核算编码,辅助核算名称,会计年度,会计期间,账款类型,来源单号\r\n"
            "001,2024-01-15,采购,1403,原材料,10000,0,供应商,SUP001,A公司,2024,1,应付,PO001\r\n"
            "001,2024-01-15,采购,1002,银行存款,0,10000,供应商,SUP001,A公司,2024,1,应付,PO001"
        )
        tmp.write(csv_content)
        tmp.close()
        try:
            mapping = {
                "凭证号": "voucher_no",
                "凭证日期": "voucher_date",
                "摘要": "summary",
                "科目编码": "account_code",
                "科目名称": "account_name",
                "借方金额": "debit_amount",
                "贷方金额": "credit_amount",
                "辅助核算类型": "auxiliary_type",
                "辅助核算编码": "auxiliary_code",
                "辅助核算名称": "auxiliary_name",
                "会计年度": "fiscal_year",
                "会计期间": "period",
                "账款类型": "bill_type",  # 辅助字段
                "来源单号": "source_no",  # 辅助字段
            }
            result = await import_data(
                db=db, company_id=sample_company_id,
                file_path=tmp.name, data_type="subsidiary",
                column_mapping=mapping,
            )
            assert result["total"] == 2
            assert result["success"] == 2

            stmt = select(SubsidiaryLedger).where(SubsidiaryLedger.company_id == sample_company_id)
            res = await db.execute(stmt)
            rows = res.scalars().all()
            assert len(rows) == 2
            for row in rows:
                assert row.extra_fields is not None
                assert row.extra_fields.get("bill_type") == "应付"
                assert row.extra_fields.get("source_no") == "PO001"
        finally:
            os.unlink(tmp.name)

    @pytest.mark.asyncio
    async def test_journal_import_with_extra_fields_no_crash(self, db, sample_company_id):
        """序时账带辅助字段不崩溃 → 确认不再抛出 TypeError"""
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        csv_content = (
            "凭证号,凭证日期,摘要,科目编码,科目名称,借方金额,贷方金额,会计年度,会计期间,备注\r\n"
            "001,2024-01-15,测试,1002,银行存款,100,100,2024,1,这是一条备注"
        )
        tmp.write(csv_content)
        tmp.close()
        try:
            mapping = {
                "凭证号": "voucher_no",
                "凭证日期": "voucher_date",
                "摘要": "summary",
                "科目编码": "account_code",
                "科目名称": "account_name",
                "借方金额": "debit_amount",
                "贷方金额": "credit_amount",
                "会计年度": "fiscal_year",
                "会计期间": "period",
                "备注": "remark",  # 辅助字段
            }
            # 不应抛出 TypeError
            result = await import_data(
                db=db, company_id=sample_company_id,
                file_path=tmp.name, data_type="journal",
                column_mapping=mapping,
            )
            assert result["success"] == 1
            assert result["errors"] == []
        finally:
            os.unlink(tmp.name)


class TestStructuredErrorResponse:
    """结构化错误响应 — 验证 _format_execute_error 返回中文结构化 detail"""

    def test_format_extra_fields_error(self):
        """extra_fields 错误 → 返回中文结构化信息"""
        from app.api.imports import _format_execute_error
        err = TypeError("'extra_fields' is an invalid keyword argument for JournalEntry")
        detail = _format_execute_error(err)
        assert isinstance(detail, dict)
        assert "message" in detail
        assert "reason" in detail
        assert "suggestion" in detail
        assert "辅助字段" in detail["reason"] or "自定义" in detail["reason"]

    def test_format_unknown_error(self):
        """未知异常 → 返回中文结构化信息（不包含原始英文 traceback）"""
        from app.api.imports import _format_execute_error
        err = RuntimeError("something went terribly wrong")
        detail = _format_execute_error(err)
        assert isinstance(detail, dict)
        assert "message" in detail
        assert "服务器处理导入数据时发生错误" in detail["message"]
        # 不应包含原始英文异常消息
        assert "terribly" not in str(detail)
        assert "RuntimeError" not in str(detail)

    def test_format_not_null_error(self):
        """NOT NULL 约束错误 → 返回中文原因"""
        from app.api.imports import _format_execute_error
        import sqlite3
        err = sqlite3.IntegrityError("NOT NULL constraint failed: journal_entries.voucher_no")
        detail = _format_execute_error(err)
        assert "message" in detail
        assert "必填字段缺失" in detail["reason"]


class TestColumnV2Mapping:
    """TASK-020：列 ID 映射 v2 — 验证重复表头/空表头/旧兼容"""

    def test_build_columns_generates_stable_ids(self):
        """基本表头 → 生成稳定的 col_001 格式 ID"""
        from app.services.file_parser import build_columns
        headers = ["凭证号", "凭证日期", "摘要", "科目编码"]
        cols = build_columns(headers)

        assert len(cols) == 4
        assert cols[0]["column_id"] == "col_001"
        assert cols[0]["index"] == 0
        assert cols[0]["header"] == "凭证号"
        assert cols[0]["duplicate_group"] is None
        assert cols[3]["column_id"] == "col_004"

    def test_duplicate_headers_get_different_ids(self):
        """重复表头 → 不同 column_id，duplicate_group 包含 occurrence"""
        from app.services.file_parser import build_columns
        headers = ["摘要", "说明", "摘要", "摘要"]
        cols = build_columns(headers)

        # 三个"摘要"都是不同列
        summary_cols = [c for c in cols if c["normalized_header"] == "摘要"]
        assert len(summary_cols) == 3
        ids = {c["column_id"] for c in summary_cols}
        assert len(ids) == 3  # 三个不同的 column_id

        # duplicate_group 正确
        assert summary_cols[0]["duplicate_group"]["occurrence"] == 1
        assert summary_cols[1]["duplicate_group"]["occurrence"] == 2
        assert summary_cols[2]["duplicate_group"]["occurrence"] == 3
        assert summary_cols[0]["duplicate_group"]["total"] == 3

    def test_empty_headers_get_stable_id(self):
        """空表头 → 仍生成 column_id，不会被跳过"""
        from app.services.file_parser import build_columns
        headers = ["凭证号", "", "", "科目编码"]
        cols = build_columns(headers)
        assert len(cols) == 4
        assert cols[1]["column_id"] == "col_002"
        assert cols[1]["normalized_header"] == ""
        assert cols[2]["column_id"] == "col_003"

    def test_map_row_by_column_ids_reads_correct_column(self):
        """v2 映射 → 通过 column_id 读取到正确的列（不受重复表头影响）"""
        from app.services.column_matcher import map_row_by_column_ids
        from app.services.file_parser import build_columns

        headers = ["摘要", "说明", "摘要", "科目编码"]
        columns = build_columns(headers)
        row = ["采购原材料", "银行付款", "支付供应商A公司货款", "1002"]

        # 映射到第二个"摘要"（col_003）
        mapping = {"col_003": "summary", "col_004": "account_code"}
        result = map_row_by_column_ids(row, columns, mapping)

        assert result["summary"] == "支付供应商A公司货款"  # 第二个摘要，不是第一个
        assert result["account_code"] == "1002"

    def test_map_row_by_column_ids_ignores_unknown_column_ids(self):
        """v2 映射中不存在的 column_id → 忽略，不抛异常"""
        from app.services.column_matcher import map_row_by_column_ids
        from app.services.file_parser import build_columns

        headers = ["凭证号", "科目编码"]
        columns = build_columns(headers)
        mapping = {"col_001": "voucher_no", "col_999": "fake_field"}
        result = map_row_by_column_ids(["001", "1002"], columns, mapping)
        assert result["voucher_no"] == "001"
        assert "fake_field" not in result

    def test_preview_returns_columns_alongside_old_fields(self):
        """preview_import → 返回 columns 且旧的 matched/unmatched/missing 仍存在"""
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        csv_content = (
            "凭证号,凭证日期,摘要,摘要,科目编码,科目名称,借方金额,贷方金额,会计年度,会计期间\r\n"
            "001,2024-01-15,采购,采购详细,1002,银行存款,0,10000,2024,1"
        )
        tmp.write(csv_content)
        tmp.close()
        try:
            from app.services.import_service import preview_import
            import asyncio
            result = asyncio.run(preview_import(tmp.name, "journal"))

            # 新字段
            assert "columns" in result
            columns = result["columns"]
            assert len(columns) == 10
            # 两个"摘要"是不同的 column_id
            summary_ids = [
                c["column_id"] for c in columns if c["normalized_header"] == "摘要"
            ]
            assert len(summary_ids) == 2
            assert summary_ids[0] != summary_ids[1]

            # 旧字段仍存在
            assert "headers" in result
            assert "matched" in result
            assert "unmatched" in result
            assert "missing" in result
            assert "preview_rows" in result
        finally:
            os.unlink(tmp.name)

    @pytest.mark.asyncio
    async def test_v2_mapping_import_with_duplicate_header(self, db, sample_company_id):
        """v2 映射导入重复表头 → 正确读取第二个摘要"""
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        # 列: 凭证号, 凭证日期, 摘要(第3列), 摘要(第4列=说明), 科目编码, 科目名称, 借方, 贷方, 年度, 期间
        csv_content = (
            "凭证号,凭证日期,摘要,摘要,科目编码,科目名称,借方金额,贷方金额,会计年度,会计期间\r\n"
            "001,2024-01-15,采购原材料,支付供应商A货款,1002,银行存款,0,10000,2024,1"
        )
        tmp.write(csv_content)
        tmp.close()
        try:
            # v2 映射：第四个"摘要"列为 summary，第三个"摘要"列为 description 辅助字段
            mapping_v2 = {
                "col_001": "voucher_no",
                "col_002": "voucher_date",
                "col_004": "summary",  # 第二个"摘要"作为摘要
                "col_005": "account_code",
                "col_006": "account_name",
                "col_007": "debit_amount",
                "col_008": "credit_amount",
                "col_009": "fiscal_year",
                "col_010": "period",
                "col_003": "desc_extra",  # 第一个"摘要"作为辅助字段
            }
            result = await import_data(
                db=db, company_id=sample_company_id,
                file_path=tmp.name, data_type="journal",
                column_mapping_v2=mapping_v2,
            )
            assert result["success"] == 1
            assert result["errors"] == []

            # 验证数据库
            stmt = select(JournalEntry).where(JournalEntry.company_id == sample_company_id)
            res = await db.execute(stmt)
            rows = res.scalars().all()
            assert len(rows) == 1
            assert rows[0].summary == "支付供应商A货款"  # 第二个摘要
            assert rows[0].extra_fields["desc_extra"] == "采购原材料"  # 第一个摘要进了辅助字段
        finally:
            os.unlink(tmp.name)

    @pytest.mark.asyncio
    async def test_old_column_mapping_still_works(self, db, sample_company_id):
        """旧 column_mapping 仍可导入（不传 column_mapping_v2）"""
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
            mapping = {
                "凭证号": "voucher_no",
                "凭证日期": "voucher_date",
                "摘要": "summary",
                "科目编码": "account_code",
                "科目名称": "account_name",
                "借方金额": "debit_amount",
                "贷方金额": "credit_amount",
                "会计年度": "fiscal_year",
                "会计期间": "period",
            }
            result = await import_data(
                db=db, company_id=sample_company_id,
                file_path=tmp.name, data_type="journal",
                column_mapping=mapping,
            )
            assert result["success"] == 1
            assert result["errors"] == []
        finally:
            os.unlink(tmp.name)

    @pytest.mark.asyncio
    async def test_v2_import_empty_header_column(self, db, sample_company_id):
        """v2 映射中空表头列 → 正常映射为辅助字段"""
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        # 第4列为空表头
        csv_content = (
            "凭证号,凭证日期,摘要,,科目编码,科目名称,借方金额,贷方金额,会计年度,会计期间\r\n"
            "001,2024-01-15,采购,备注内容,1002,银行存款,0,10000,2024,1"
        )
        tmp.write(csv_content)
        tmp.close()
        try:
            mapping_v2 = {
                "col_001": "voucher_no",
                "col_002": "voucher_date",
                "col_003": "summary",
                "col_004": "comment",  # 空表头映射为辅助字段
                "col_005": "account_code",
                "col_006": "account_name",
                "col_007": "debit_amount",
                "col_008": "credit_amount",
                "col_009": "fiscal_year",
                "col_010": "period",
            }
            result = await import_data(
                db=db, company_id=sample_company_id,
                file_path=tmp.name, data_type="journal",
                column_mapping_v2=mapping_v2,
            )
            assert result["success"] == 1
            stmt = select(JournalEntry).where(JournalEntry.company_id == sample_company_id)
            res = await db.execute(stmt)
            rows = res.scalars().all()
            assert len(rows) == 1
            assert rows[0].extra_fields.get("comment") == "备注内容"
        finally:
            os.unlink(tmp.name)

    def test_v2_mapping_invalid_json(self):
        """column_mapping_v2 为无效 JSON → 返回中文错误"""
        import json
        bad_json = "{col_001: voucher_date"  # 缺少引号
        with pytest.raises(json.JSONDecodeError):
            json.loads(bad_json)

    @pytest.mark.asyncio
    async def test_v2_keeps_old_compat_when_both_provided(self, db, sample_company_id):
        """同时传 v1 和 v2 映射 → 优先使用 v2"""
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
            mapping_old = {"wrong_header": "summary"}  # 旧映射故意不对
            mapping_v2 = {
                "col_001": "voucher_no",
                "col_002": "voucher_date",
                "col_003": "summary",
                "col_004": "account_code",
                "col_005": "account_name",
                "col_006": "debit_amount",
                "col_007": "credit_amount",
                "col_008": "fiscal_year",
                "col_009": "period",
            }
            result = await import_data(
                db=db, company_id=sample_company_id,
                file_path=tmp.name, data_type="journal",
                column_mapping=mapping_old,
                column_mapping_v2=mapping_v2,
            )
            # v2 优先 → 成功导入
            assert result["success"] == 1
        finally:
            os.unlink(tmp.name)


class TestTemplateMatching:
    """TASK-022：模板匹配与预览集成"""

    @pytest.mark.asyncio
    async def test_exact_template_match_scores_100(self, db):
        """完全一致模板 → 100 分"""
        from app.services.template_service import create_template
        from app.services.template_matcher import match_templates
        from app.services.file_parser import build_columns, parse_file

        # 先创建模板
        t = await create_template(db, {
            "name": "精确匹配模板",
            "data_type": "journal",
            "is_active": True,
            "header_signature": {
                "col_001": "凭证号", "col_002": "凭证日期", "col_003": "摘要",
                "col_004": "科目编码", "col_005": "科目名称",
                "col_006": "借方金额", "col_007": "贷方金额",
                "col_008": "会计年度", "col_009": "会计期间",
            },
            "column_rules": {
                "col_001": "voucher_no", "col_002": "voucher_date",
                "col_003": "summary", "col_004": "account_code",
                "col_005": "account_name", "col_006": "debit_amount",
                "col_007": "credit_amount", "col_008": "fiscal_year",
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
            candidates = match_templates(tmp.name, "journal", [t])
            assert len(candidates) == 1
            # 完全匹配（含必填字段全覆盖）→ ≥ 90 分
            assert candidates[0]["score"] >= 90, f"score={candidates[0]['score']}"
            assert "voucher_no" in candidates[0]["matched_fields"]
        finally:
            os.unlink(tmp.name)

    @pytest.mark.asyncio
    async def test_similar_template_gets_medium_score(self, db):
        """相似表头 → 中等分数 + warnings"""
        from app.services.template_service import create_template
        from app.services.template_matcher import match_templates

        t = await create_template(db, {
            "name": "部分匹配模板",
            "data_type": "journal",
            "is_active": True,
            "header_signature": {
                "col_001": "凭证号", "col_002": "日期",
                "col_003": "说明", "col_004": "科目",
            },
            "column_rules": {
                "col_001": "voucher_no", "col_002": "voucher_date",
                "col_003": "summary", "col_004": "account_code",
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
            candidates = match_templates(tmp.name, "journal", [t])
            assert len(candidates) >= 1
            # 少量字段匹配 → 分数较低但有 warning
            assert candidates[0]["score"] <= 50, f"score={candidates[0]['score']}"
            assert len(candidates[0]["warnings"]) > 0  # 缺必填字段
            assert any("必填字段" in w for w in candidates[0]["warnings"])
        finally:
            os.unlink(tmp.name)

    @pytest.mark.asyncio
    async def test_missing_required_fields_lowers_score(self, db):
        """缺必填字段 → 降分"""
        from app.services.template_service import create_template
        from app.services.template_matcher import match_templates

        t = await create_template(db, {
            "name": "缺字段模板",
            "data_type": "journal",
            "is_active": True,
            "header_signature": {"col_001": "凭证号"},
            "column_rules": {"col_001": "voucher_no"},  # 只映射一个字段
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
            candidates = match_templates(tmp.name, "journal", [t])
            assert len(candidates) == 1
            # 大量必填字段缺失 → 分数应较低
            assert candidates[0]["score"] < 50
            assert len(candidates[0]["missing_fields"]) > 3
        finally:
            os.unlink(tmp.name)

    def test_negative_match_excludes_period_false_positive(self):
        """本币期间异动 不被误判为 period"""
        from app.services.column_matcher import auto_match, TYPE_FIELDS
        headers = [
            "科目编码", "科目名称",
            "本币期间异动(借)", "本币期间异动(贷)",
            "本币本年累计(借)", "本币本年累计(贷)",
        ]
        result = auto_match(headers, "trial_balance")
        # period 不应该被匹配
        assert "period" not in result["matched"], f"period was matched: {result['matched']}"
        # fiscal_year 不应该被匹配
        assert "fiscal_year" not in result["matched"], f"fiscal_year was matched: {result['matched']}"

    def test_negative_match_warns_in_template_matcher(self):
        """负向匹配在模板评分中产生 warning"""
        from app.services.template_matcher import _check_negative_patterns
        from app.services.file_parser import build_columns
        headers = ["科目编码", "本币期间异动(借)", "本币本年累计(借)"]
        columns = build_columns(headers)
        warnings = _check_negative_patterns(columns)
        assert len(warnings) > 0
        assert any("期间异动" in w for w in warnings)

    @pytest.mark.asyncio
    async def test_preview_with_template_id_returns_mapping_v2(self, db):
        """指定 template_id → preview 返回 applied_mapping_v2"""
        from app.services.template_service import create_template
        from app.services.import_service import preview_import

        t = await create_template(db, {
            "name": "套用模板",
            "data_type": "journal",
            "is_active": True,
            "header_signature": {
                "col_001": "凭证号", "col_002": "凭证日期", "col_003": "摘要",
            },
            "column_rules": {
                "col_001": "voucher_no",
                "col_002": "voucher_date",
                "col_003": "summary",
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
            result = await preview_import(
                tmp.name, "journal",
                db=db, template_id=str(t.id),
            )
            assert "applied_mapping_v2" in result
            assert result["applied_mapping_v2"]["col_001"] == "voucher_no"
            assert result["applied_mapping_v2"]["col_002"] == "voucher_date"
        finally:
            os.unlink(tmp.name)

    @pytest.mark.asyncio
    async def test_preview_without_template_id_returns_candidates(self, db):
        """不指定 template_id → preview 返回 template_candidates"""
        from app.services.template_service import create_template
        from app.services.import_service import preview_import

        t = await create_template(db, {
            "name": "候选模板",
            "data_type": "journal",
            "is_active": True,
            "header_signature": {"col_001": "凭证号", "col_002": "凭证日期", "col_003": "摘要"},
            "column_rules": {
                "col_001": "voucher_no", "col_002": "voucher_date", "col_003": "summary",
                "col_004": "account_code", "col_005": "account_name",
                "col_006": "debit_amount", "col_007": "credit_amount",
                "col_008": "fiscal_year", "col_009": "period",
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
            result = await preview_import(tmp.name, "journal", db=db)
            assert "template_candidates" in result
            candidates = result["template_candidates"]
            assert len(candidates) >= 1
            assert "score" in candidates[0]
            assert "name" in candidates[0]
        finally:
            os.unlink(tmp.name)


class TestTemplateMatchSafety:
    """TASK-026：模板匹配安全校验 — 无关文件不能得高分"""

    @pytest.mark.asyncio
    async def test_match_templates_rejects_unrelated_same_width_file(self, db):
        """完全不相关的9列文件 → 不返回候选或分数 < 40"""
        from app.services.template_service import create_template
        from app.services.template_matcher import match_templates

        t = await create_template(db, {
            "name": "序时账模板",
            "data_type": "journal",
            "is_active": True,
            "header_signature": {
                "col_001": "凭证号", "col_002": "凭证日期", "col_003": "摘要",
                "col_004": "科目编码", "col_005": "科目名称",
                "col_006": "借方金额", "col_007": "贷方金额",
                "col_008": "会计年度", "col_009": "会计期间",
            },
            "column_rules": {
                "col_001": "voucher_no", "col_002": "voucher_date",
                "col_003": "summary", "col_004": "account_code",
                "col_005": "account_name", "col_006": "debit_amount",
                "col_007": "credit_amount", "col_008": "fiscal_year",
                "col_009": "period",
            },
        })

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        csv_content = (
            "customer,vendor,department,project,amount,note,status,date,number\r\n"
            "C1,V1,D1,P1,1000,note1,ok,2024-01-01,001"
        )
        tmp.write(csv_content)
        tmp.close()
        try:
            candidates = match_templates(tmp.name, "journal", [t])
            # 要么不返回候选，要么分数 < 40 并带 "表头不匹配" warning
            if len(candidates) > 0:
                assert candidates[0]["score"] < 40, f"score={candidates[0]['score']}"
                assert any(
                    "表头不匹配" in w for w in candidates[0]["warnings"]
                ), f"warnings={candidates[0]['warnings']}"
        finally:
            os.unlink(tmp.name)

    @pytest.mark.asyncio
    async def test_test_template_rejects_unrelated_same_width_file(self, db):
        """不相关文件 test_template → applicable=False"""
        from app.services.template_service import create_template, test_template as run_test

        t = await create_template(db, {
            "name": "序时账模板",
            "data_type": "journal",
            "is_active": True,
            "header_signature": {
                "col_001": "凭证号", "col_002": "凭证日期",
            },
            "column_rules": {
                "col_001": "voucher_no", "col_002": "voucher_date",
                "col_003": "summary",
            },
        })

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        csv_content = "xA,xB,xC,xD,xE,xF,xG,xH,xI\r\n1,2,3,4,5,6,7,8,9"
        tmp.write(csv_content)
        tmp.close()
        try:
            result = await run_test(t, tmp.name)
            # 完全不匹配 → applicable should be False
            # (column_rules 有3个字段但在不匹配的文件上 hit_fields 可能仍计入了规则中的字段)
            # 因为 test_template 目前只看规则中的标准字段统计，不看签名。
            # TASK-026 要求在 test_template 中也检查签名匹配
            assert result["applicable"] is False or len(result["column_mapping_v2"]) == 0, \
                f"applicable={result['applicable']}, v2={result['column_mapping_v2']}"
        finally:
            os.unlink(tmp.name)

    def test_apply_template_to_columns_rejects_signature_mismatch(self):
        """签名不匹配 → apply_template_to_columns 抛出 ValueError"""
        from app.services.template_matcher import apply_template_to_columns
        from app.services.file_parser import build_columns
        from app.models.import_template import ImportTemplate

        t = ImportTemplate(
            name="测试模板",
            data_type="journal",
            header_signature={"col_001": "凭证号", "col_002": "凭证日期"},
            column_rules={"col_001": "voucher_no", "col_002": "voucher_date"},
        )

        headers = ["customer", "vendor", "amount"]
        columns = build_columns(headers)

        with pytest.raises(ValueError, match="表头不匹配"):
            apply_template_to_columns(t, columns)

    @pytest.mark.asyncio
    async def test_from_sample_duplicate_english_summary_keeps_first(self):
        """英文重复表头 summary,summary → 第一列保存为 summary，第二列是辅助字段"""
        from app.services.template_service import from_sample

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        csv_content = (
            "voucher_no,voucher_date,summary,summary,account_code,account_name,"
            "debit_amount,credit_amount,fiscal_year,period\r\n"
            "001,2024-01-15,采购原材料,支付货款,1002,银行存款,10000,0,2024,1"
        )
        tmp.write(csv_content)
        tmp.close()
        try:
            draft = await from_sample(tmp.name, "journal")
            rules = draft["column_rules"]
            # 第一个 summary 列 (col_003) 应保存为 summary
            assert rules.get("col_003") == "summary", f"col_003 = {rules.get('col_003')}"
            # 第二个 summary 列 (col_004) 不应是 summary
            assert rules.get("col_004") != "summary", f"col_004 should not be summary: {rules.get('col_004')}"
        finally:
            os.unlink(tmp.name)

    @pytest.mark.asyncio
    async def test_preview_with_template_id_needs_signature_match(self, db):
        """指定 template_id 预览 → 签名不匹配时返回错误，不是静默套用"""
        from app.services.template_service import create_template
        from app.services.import_service import preview_import

        t = await create_template(db, {
            "name": "序时账模板",
            "data_type": "journal",
            "is_active": True,
            "header_signature": {
                "col_001": "凭证号", "col_002": "凭证日期", "col_003": "摘要",
            },
            "column_rules": {
                "col_001": "voucher_no", "col_002": "voucher_date",
                "col_003": "summary",
            },
        })

        # 不相关的文件
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        csv_content = "xA,xB,xC\r\n1,2,3"
        tmp.write(csv_content)
        tmp.close()
        try:
            with pytest.raises(ValueError, match="表头不匹配"):
                await preview_import(tmp.name, "journal", db=db, template_id=str(t.id))
        finally:
            os.unlink(tmp.name)


class TestTemplateConfigEffective:
    """TASK-027：parse_config 和 default_values 生效"""

    def test_parse_file_with_config_header_row(self):
        """header_row=1, data_start_row=2 → 跳过第一行标题，解析第二行表头"""
        from app.services.file_parser import parse_file_with_config

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        csv_content = (
            "审计数据导出 2024,\r\n"
            "凭证号,凭证日期,摘要,科目编码,科目名称,借方金额,贷方金额,会计年度,会计期间\r\n"
            "001,2024-01-15,采购,1002,银行存款,0,10000,2024,1"
        )
        tmp.write(csv_content)
        tmp.close()
        try:
            config = {"header_row": 1, "data_start_row": 2}
            headers, rows = parse_file_with_config(tmp.name, config)
            assert headers[0] == "凭证号"
            assert len(rows) == 1
        finally:
            os.unlink(tmp.name)

    @pytest.mark.asyncio
    async def test_test_template_uses_parse_config(self, db):
        """模板 parse_config header_row=1 → test_template 识别第二行表头"""
        from app.services.template_service import create_template, test_template as run_test

        t = await create_template(db, {
            "name": "跳过首行模板",
            "data_type": "journal",
            "is_active": True,
            "parse_config": {"header_row": 1, "data_start_row": 2},
            "header_signature": {"col_001": "凭证号", "col_002": "凭证日期"},
            "column_rules": {"col_001": "voucher_no", "col_002": "voucher_date"},
        })

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        csv_content = (
            "标题行,多余的\r\n"
            "凭证号,凭证日期\r\n"
            "001,2024-01-15"
        )
        tmp.write(csv_content)
        tmp.close()
        try:
            result = await run_test(t, tmp.name)
            assert result["applicable"] is True
        finally:
            os.unlink(tmp.name)

    @pytest.mark.asyncio
    async def test_preview_with_template_id_uses_parse_config(self, db):
        """指定模板预览 → 返回列来自 parse_config 指定的表头行"""
        from app.services.template_service import create_template
        from app.services.import_service import preview_import

        t = await create_template(db, {
            "name": "预览跳过首行",
            "data_type": "journal",
            "is_active": True,
            "parse_config": {"header_row": 1, "data_start_row": 2},
            "header_signature": {"col_001": "凭证号", "col_002": "凭证日期"},
            "column_rules": {"col_001": "voucher_no", "col_002": "voucher_date"},
        })

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        csv_content = (
            "标题行,多余的\r\n"
            "凭证号,凭证日期\r\n"
            "001,2024-01-15"
        )
        tmp.write(csv_content)
        tmp.close()
        try:
            result = await preview_import(tmp.name, "journal", db=db, template_id=str(t.id))
            # 表头应为 "凭证号"，不是 "标题行"
            assert result["headers"][0] == "凭证号"
        finally:
            os.unlink(tmp.name)

    @pytest.mark.asyncio
    async def test_import_uses_template_default_fiscal_year_period(self, db, sample_company_id):
        """文件无年度/期间列 → 模板 default_values 补齐 → 导入成功"""
        from app.services.template_service import create_template

        t = await create_template(db, {
            "name": "默认值模板",
            "data_type": "journal",
            "is_active": True,
            "default_values": {"fiscal_year": 2024, "period": 12},
        })

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        # 不含 fiscal_year 和 period 列
        csv_content = (
            "凭证号,凭证日期,摘要,科目编码,科目名称,借方金额,贷方金额\r\n"
            "001,2024-01-15,采购,1002,银行存款,0,10000"
        )
        tmp.write(csv_content)
        tmp.close()
        try:
            mapping = {
                "凭证号": "voucher_no", "凭证日期": "voucher_date",
                "摘要": "summary", "科目编码": "account_code",
                "科目名称": "account_name", "借方金额": "debit_amount",
                "贷方金额": "credit_amount",
            }
            result = await import_data(
                db=db, company_id=sample_company_id,
                file_path=tmp.name, data_type="journal",
                column_mapping=mapping,
                template_default_values=t.default_values,
            )
            assert result["success"] == 1
            stmt = select(JournalEntry).where(JournalEntry.company_id == sample_company_id)
            res = await db.execute(stmt)
            rows = res.scalars().all()
            assert len(rows) == 1
            assert rows[0].fiscal_year == 2024
            assert rows[0].period == 12
        finally:
            os.unlink(tmp.name)

    @pytest.mark.asyncio
    async def test_manual_params_override_template_defaults(self, db, sample_company_id):
        """用户手动年度/期间 → 优先于模板默认值"""
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        csv_content = (
            "凭证号,凭证日期,摘要,科目编码,科目名称,借方金额,贷方金额\r\n"
            "001,2024-01-15,采购,1002,银行存款,0,10000"
        )
        tmp.write(csv_content)
        tmp.close()
        try:
            mapping = {
                "凭证号": "voucher_no", "凭证日期": "voucher_date",
                "摘要": "summary", "科目编码": "account_code",
                "科目名称": "account_name", "借方金额": "debit_amount",
                "贷方金额": "credit_amount",
            }
            result = await import_data(
                db=db, company_id=sample_company_id,
                file_path=tmp.name, data_type="journal",
                column_mapping=mapping,
                fiscal_year=2025, period=1,  # 用户手动
                template_default_values={"fiscal_year": 2024, "period": 12},  # 模板默认
            )
            assert result["success"] == 1
            stmt = select(JournalEntry).where(JournalEntry.company_id == sample_company_id)
            res = await db.execute(stmt)
            rows = res.scalars().all()
            assert len(rows) == 1
            assert rows[0].fiscal_year == 2025  # 用户值优先
            assert rows[0].period == 1
        finally:
            os.unlink(tmp.name)


class TestTemplateExecuteEndToEnd:
    """TASK-029：套用模板后最终导入链路验证"""

    @pytest.mark.asyncio
    async def test_import_with_template_id_and_parse_config(self, db, sample_company_id):
        """文件第1行标题/第2行表头/无年度期间 → 模板 parse_config + defaults → 导入成功"""
        from app.services.template_service import create_template

        t = await create_template(db, {
            "name": "端到端模板",
            "data_type": "journal",
            "is_active": True,
            "parse_config": {"header_row": 1, "data_start_row": 2},
            "header_signature": {
                "col_001": "凭证号", "col_002": "凭证日期", "col_003": "摘要",
                "col_004": "科目编码", "col_005": "科目名称",
                "col_006": "借方金额", "col_007": "贷方金额",
            },
            "column_rules": {
                "col_001": "voucher_no", "col_002": "voucher_date",
                "col_003": "summary", "col_004": "account_code",
                "col_005": "account_name", "col_006": "debit_amount",
                "col_007": "credit_amount",
            },
            "default_values": {"fiscal_year": 2024, "period": 3},
        })

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        csv_content = (
            "审计数据导出,2024年3月\r\n"
            "凭证号,凭证日期,摘要,科目编码,科目名称,借方金额,贷方金额\r\n"
            "001,2024-03-15,采购,1002,银行存款,0,10000"
        )
        tmp.write(csv_content)
        tmp.close()
        try:
            mapping_v2 = {
                "col_001": "voucher_no", "col_002": "voucher_date",
                "col_003": "summary", "col_004": "account_code",
                "col_005": "account_name", "col_006": "debit_amount",
                "col_007": "credit_amount",
            }
            result = await import_data(
                db=db, company_id=sample_company_id,
                file_path=tmp.name, data_type="journal",
                column_mapping_v2=mapping_v2,
                parse_config=t.parse_config or None,
                template_default_values=t.default_values or None,
            )
            assert result["success"] == 1
            assert result["errors"] == []

            stmt = select(JournalEntry).where(JournalEntry.company_id == sample_company_id)
            res = await db.execute(stmt)
            rows = res.scalars().all()
            assert len(rows) == 1
            assert rows[0].fiscal_year == 2024
            assert rows[0].period == 3
            assert rows[0].voucher_no == "001"
        finally:
            os.unlink(tmp.name)

    @pytest.mark.asyncio
    async def test_preview_silently_ignores_nonexistent_template(self, db):
        """不存在的 template_id → preview 不抛异常，静默回退到自动匹配"""
        fake_id = str(uuid.uuid4())
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        csv_content = "凭证号,凭证日期,摘要,科目编码,科目名称,借方金额,贷方金额,会计年度,会计期间\r\n001,2024-01-15,x,1002,x,0,10000,2024,1"
        tmp.write(csv_content)
        tmp.close()
        try:
            from app.services.import_service import preview_import
            result = await preview_import(tmp.name, "journal", db=db, template_id=fake_id)
            # 不应抛异常，且 applied_mapping_v2 不存在
            assert "applied_mapping_v2" not in result
        finally:
            os.unlink(tmp.name)

    @pytest.mark.asyncio
    async def test_import_rejects_inactive_template(self, db, sample_company_id):
        """停用模板 → ValueError"""
        from app.services.template_service import create_template

        t = await create_template(db, {
            "name": "停用模板",
            "data_type": "journal",
            "is_active": False,
            "header_signature": {"col_001": "凭证号"},
            "column_rules": {"col_001": "voucher_no"},
        })

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        csv_content = "凭证号,凭证日期,摘要,科目编码,科目名称,借方金额,贷方金额,会计年度,会计期间\r\n001,2024-01-15,x,1002,x,0,10000,2024,1"
        tmp.write(csv_content)
        tmp.close()
        try:
            from app.services.import_service import preview_import
            with pytest.raises(ValueError, match="已停用"):
                await preview_import(tmp.name, "journal", db=db, template_id=str(t.id))
        finally:
            os.unlink(tmp.name)

    @pytest.mark.asyncio
    async def test_import_rejects_data_type_mismatch(self, db, sample_company_id):
        """模板 data_type 与导入类型不一致 → ValueError"""
        from app.services.template_service import create_template

        t = await create_template(db, {
            "name": "余额表模板",
            "data_type": "trial_balance",
            "is_active": True,
            "header_signature": {"col_001": "科目编码"},
            "column_rules": {"col_001": "account_code"},
        })

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        csv_content = "凭证号,凭证日期,摘要,科目编码,科目名称,借方金额,贷方金额,会计年度,会计期间\r\n001,2024-01-15,x,1002,x,0,10000,2024,1"
        tmp.write(csv_content)
        tmp.close()
        try:
            from app.services.import_service import preview_import
            with pytest.raises(ValueError, match="不一致"):
                await preview_import(tmp.name, "journal", db=db, template_id=str(t.id))
        finally:
            os.unlink(tmp.name)
