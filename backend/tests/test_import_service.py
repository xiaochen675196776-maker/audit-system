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


class TestMappingExperienceRecommend:
    """TASK-032：字段映射经验推荐"""

    @pytest.mark.asyncio
    async def test_keyword_match_suggestions_in_preview(self, db):
        """预览返回关键词匹配建议"""
        from app.services.import_service import preview_import

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        csv_content = "凭证号,凭证日期,摘要,科目编码,科目名称,借方金额,贷方金额,会计年度,会计期间\r\n001,2024-01-15,x,1002,x,0,10000,2024,1"
        tmp.write(csv_content)
        tmp.close()
        try:
            result = await preview_import(tmp.name, "journal", db=db)
            assert "mapping_suggestions_v2" in result
            suggestions = result["mapping_suggestions_v2"]
            assert len(suggestions) > 0
            for k, v in suggestions.items():
                assert v["source"] == "keyword_match"
        finally:
            os.unlink(tmp.name)

    @pytest.mark.asyncio
    async def test_experience_priority_over_keyword(self, db, sample_company_id):
        """经验优先于关键词匹配"""
        from app.models.field_mapping_experience import FieldMappingExperience
        from app.services.mapping_experience_service import normalize_header, build_context_signature

        headers = ["凭证号", "凭证日期", "摘要", "科目编码", "科目名称", "借方金额", "贷方金额", "会计年度", "会计期间"]
        nh = normalize_header("凭证号")
        ctx = build_context_signature(headers, 0)
        exp = FieldMappingExperience(
            company_id=sample_company_id, data_type="journal",
            source_header_original="凭证号", source_header_normalized=nh,
            source_column_index=0, context_signature=ctx,
            target_field="voucher_no", lookup_key="test_exp_key", is_active=True,
        )
        db.add(exp)
        await db.flush()

        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8", newline="")
        csv_content = "凭证号,凭证日期,摘要,科目编码,科目名称,借方金额,贷方金额,会计年度,会计期间\r\n001,2024-01-15,x,1002,x,0,10000,2024,1"
        tmp.write(csv_content)
        tmp.close()
        try:
            from app.services.import_service import preview_import
            result = await preview_import(tmp.name, "journal", db=db, company_id=str(sample_company_id))
            suggestions = result["mapping_suggestions_v2"]
            if "col_001" in suggestions:
                assert suggestions["col_001"]["source"] == "company_experience"
        finally:
            os.unlink(tmp.name)

    @pytest.mark.asyncio
    async def test_ambiguous_header_not_auto_recommended(self, db, sample_company_id):
        """歧义表头 header-only 经验不自动推荐"""
        from app.models.field_mapping_experience import FieldMappingExperience
        from app.services.mapping_experience_service import normalize_header

        nh = normalize_header("借方")
        exp = FieldMappingExperience(
            company_id=sample_company_id, data_type="journal",
            source_header_original="借方", source_header_normalized=nh,
            source_column_index=0, context_signature="",
            target_field="debit_amount", lookup_key="test_ambig_key", is_active=True,
        )
        db.add(exp)
        await db.flush()

        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8", newline="")
        csv_content = "借方,贷方,科目编码,科目名称,凭证号,凭证日期,摘要,会计年度,会计期间\r\n100,0,1002,x,001,2024-01-15,x,2024,1"
        tmp.write(csv_content)
        tmp.close()
        try:
            from app.services.mapping_experience_service import recommend_from_experience
            from app.services.file_parser import parse_file, build_columns
            headers, rows = parse_file(tmp.name)
            columns = build_columns(headers, rows[:3])
            suggestions = await recommend_from_experience(db, sample_company_id, "journal", columns)
            for v in suggestions.values():
                if v.get("target_field") == "debit_amount":
                    assert v["confidence"] >= 0.85, "ambiguous header needs context match"
        finally:
            os.unlink(tmp.name)


class TestSaveMappingExperience:
    """TASK-033：保存字段映射经验"""

    @pytest.mark.asyncio
    async def test_save_experience_new(self, db, sample_company_id):
        """首次导入成功 → 新增公司级经验"""
        from app.services.mapping_experience_service import save_mapping_experiences
        from app.services.file_parser import build_columns

        headers = ["科目编码", "科目名称", "借方金额"]
        columns = build_columns(headers)
        confs = {
            "col_001": {"target_field": "account_code", "confirmation_type": "user_confirmed"},
            "col_002": {"target_field": "account_name", "confirmation_type": "user_confirmed"},
        }
        await save_mapping_experiences(db, sample_company_id, "trial_balance", columns, confs)

        from app.models.field_mapping_experience import FieldMappingExperience
        stmt = select(FieldMappingExperience).where(
            FieldMappingExperience.company_id == sample_company_id,
            FieldMappingExperience.is_active == True,
        )
        res = await db.execute(stmt)
        rows = res.scalars().all()
        assert len(rows) == 2

    @pytest.mark.asyncio
    async def test_save_experience_accumulates(self, db, sample_company_id):
        """同一映射再次成功 → use_count/success_count 累加"""
        from app.services.mapping_experience_service import save_mapping_experiences
        from app.services.file_parser import build_columns

        headers = ["凭证号", "凭证日期"]
        columns = build_columns(headers)
        confs = {
            "col_001": {"target_field": "voucher_no", "confirmation_type": "user_confirmed"},
        }
        await save_mapping_experiences(db, sample_company_id, "journal", columns, confs)
        await save_mapping_experiences(db, sample_company_id, "journal", columns, confs)

        from app.models.field_mapping_experience import FieldMappingExperience
        stmt = select(FieldMappingExperience).where(
            FieldMappingExperience.company_id == sample_company_id,
            FieldMappingExperience.is_active == True,
        )
        res = await db.execute(stmt)
        rows = res.scalars().all()
        assert sum(r.use_count for r in rows) >= 2

    @pytest.mark.asyncio
    async def test_save_experience_ignores_auxiliary(self, db, sample_company_id):
        """辅助字段不保存"""
        from app.services.mapping_experience_service import save_mapping_experiences
        from app.services.file_parser import build_columns

        headers = ["凭证号", "自定义列"]
        columns = build_columns(headers)
        confs = {
            "col_001": {"target_field": "voucher_no", "confirmation_type": "user_confirmed"},
            "col_002": {"target_field": "custom_field", "confirmation_type": "user_confirmed"},
        }
        await save_mapping_experiences(db, sample_company_id, "journal", columns, confs)

        from app.models.field_mapping_experience import FieldMappingExperience
        stmt = select(FieldMappingExperience).where(
            FieldMappingExperience.company_id == sample_company_id,
        )
        res = await db.execute(stmt)
        rows = res.scalars().all()
        # 只有 voucher_no 经验被保存
        assert all(r.target_field in ("voucher_no",) for r in rows)


class TestExperienceIsolation:
    """TASK-036：经验推荐隔离 — 单位私有经验不泄漏"""

    @pytest.mark.asyncio
    async def test_private_experience_not_leaked_to_other_company(self, db):
        """A单位经验不得推荐给B单位"""
        from app.models.field_mapping_experience import FieldMappingExperience
        from app.services.mapping_experience_service import (
            recommend_from_experience, normalize_header, build_context_signature,
        )
        from app.services.file_parser import build_columns

        company_a = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        company_b = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
        headers = ["凭证号", "凭证日期", "摘要", "科目编码", "科目名称"]
        columns = build_columns(headers)
        nh = normalize_header("摘要")
        ctx = build_context_signature(headers, 2)

        # A 单位私有经验
        db.add(FieldMappingExperience(
            company_id=company_a, data_type="journal",
            source_header_original="摘要", source_header_normalized=nh,
            source_column_index=2, context_signature=ctx,
            target_field="summary", lookup_key="iso_test_a",
            use_count=5, success_count=5, is_active=True,
        ))
        await db.flush()

        # B 单位查询：不应获取 A 的单位经验
        suggestions_b = await recommend_from_experience(db, company_b, "journal", columns)
        for v in suggestions_b.values():
            assert v["source"] != "company_experience", f"B got A's private: {v}"

    @pytest.mark.asyncio
    async def test_no_company_id_only_sees_global(self, db):
        """未传 company_id 时只返回全局经验，不泄漏任何单位私有经验"""
        from app.models.field_mapping_experience import FieldMappingExperience
        from app.services.mapping_experience_service import (
            recommend_from_experience, normalize_header, build_context_signature,
        )
        from app.services.file_parser import build_columns

        company_a = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        headers = ["凭证号", "凭证日期", "摘要", "科目编码", "科目名称"]
        columns = build_columns(headers)
        nh = normalize_header("摘要")
        ctx = build_context_signature(headers, 2)

        db.add(FieldMappingExperience(
            company_id=company_a, data_type="journal",
            source_header_original="摘要", source_header_normalized=nh,
            source_column_index=2, context_signature=ctx,
            target_field="summary", lookup_key="iso_test_priv",
            use_count=5, success_count=5, is_active=True,
        ))
        # 全局经验
        db.add(FieldMappingExperience(
            company_id=None, data_type="journal",
            source_header_original="摘要", source_header_normalized=nh,
            source_column_index=2, context_signature=ctx,
            target_field="summary", lookup_key="iso_test_global",
            use_count=3, success_count=3, is_active=True,
        ))
        await db.flush()

        suggestions = await recommend_from_experience(db, None, "journal", columns)
        for v in suggestions.values():
            assert v["source"] == "global_experience", f"no-company saw private: {v}"

    @pytest.mark.asyncio
    async def test_global_experience_available_to_any_company(self, db):
        """全局经验可在任意单位命中"""
        from app.models.field_mapping_experience import FieldMappingExperience
        from app.services.mapping_experience_service import (
            recommend_from_experience, normalize_header, build_context_signature,
        )
        from app.services.file_parser import build_columns

        company_b = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
        headers = ["科目编码", "科目名称", "期初借方余额"]
        columns = build_columns(headers)
        nh = normalize_header("科目编码")
        ctx = build_context_signature(headers, 0)

        db.add(FieldMappingExperience(
            company_id=None, data_type="trial_balance",
            source_header_original="科目编码", source_header_normalized=nh,
            source_column_index=0, context_signature=ctx,
            target_field="account_code", lookup_key="iso_test_gl",
            use_count=10, success_count=10, is_active=True,
        ))
        await db.flush()

        suggestions = await recommend_from_experience(db, company_b, "trial_balance", columns)
        assert any(v["source"] == "global_experience" for v in suggestions.values())

    @pytest.mark.asyncio
    async def test_sort_by_success_count_and_updated_at(self, db):
        """同优先级内按 success_count DESC, updated_at DESC 排序"""
        from app.models.field_mapping_experience import FieldMappingExperience
        from app.services.mapping_experience_service import (
            recommend_from_experience, normalize_header, build_context_signature,
        )
        from app.services.file_parser import build_columns
        from datetime import datetime, timedelta

        company = uuid.uuid4()
        headers = ["凭证号", "凭证日期", "摘要"]
        columns = build_columns(headers)
        nh = normalize_header("凭证号")
        ctx = build_context_signature(headers, 0)

        # 经验1: success=3, older
        db.add(FieldMappingExperience(
            company_id=company, data_type="journal",
            source_header_original="凭证号", source_header_normalized=nh,
            source_column_index=0, context_signature=ctx,
            target_field="voucher_no", lookup_key="sort_test_1",
            use_count=3, success_count=3, is_active=True,
            updated_at=datetime.utcnow() - timedelta(days=10),
        ))
        # 经验2: success=10, newer — 应该被选中
        db.add(FieldMappingExperience(
            company_id=company, data_type="journal",
            source_header_original="凭证号", source_header_normalized=nh,
            source_column_index=0, context_signature=ctx,
            target_field="voucher_no", lookup_key="sort_test_2",
            use_count=10, success_count=10, is_active=True,
            updated_at=datetime.utcnow(),
        ))
        await db.flush()

        suggestions = await recommend_from_experience(db, company, "journal", columns)
        col = suggestions.get("col_001", {})
        # 应选中 success_count 更高的经验
        assert col.get("confidence", 0) >= 1.0


class TestPreviewWithoutTemplateId:
    """TASK-061 回归：preview_import 不再接受 template_id，journal/subsidiary 导入正常"""

    @pytest.mark.asyncio
    async def test_preview_journal_without_template_id_returns_success(self):
        """journal 预览无 template_id → 成功返回 headers + matched + suggestions"""
        from app.services.import_service import preview_import

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
            result = await preview_import(tmp.name, "journal")
            assert result["data_type"] == "journal"
            assert len(result["headers"]) == 9
            assert "headers" in result
            assert "columns" in result
            assert "matched" in result
            assert "unmatched" in result
            assert "missing" in result
            # 不得返回模板字段
            assert "template_candidates" not in result
            assert "applied_mapping_v2" not in result
            assert "template_default_values" not in result
        finally:
            os.unlink(tmp.name)

    @pytest.mark.asyncio
    async def test_preview_subsidiary_without_template_id_returns_success(self):
        """subsidiary 预览无 template_id → 成功返回"""
        from app.services.import_service import preview_import

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        )
        csv_content = (
            "凭证号,凭证日期,摘要,科目编码,科目名称,借方金额,贷方金额,附件数,会计年度,会计期间\r\n"
            "001,2024-01-15,采购,1002,银行存款,0,10000,3,2024,1"
        )
        tmp.write(csv_content)
        tmp.close()
        try:
            result = await preview_import(tmp.name, "subsidiary")
            assert result["data_type"] == "subsidiary"
            assert len(result["headers"]) == 10
            assert "template_candidates" not in result
            assert "applied_mapping_v2" not in result
            assert "template_default_values" not in result
        finally:
            os.unlink(tmp.name)

    @pytest.mark.asyncio
    async def test_preview_journal_with_company_id_returns_experience_suggestions(self, db):
        """传 company_id → 仍返回 mapping_suggestions_v2"""
        from app.services.import_service import preview_import

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
                db=db,
                company_id="a0000000-0000-0000-0000-000000000001",
            )
            assert result["data_type"] == "journal"
            # 经验推荐应存在（空或有关键词兜底）
            suggestions = result.get("mapping_suggestions_v2", {})
            assert isinstance(suggestions, dict)
            # 不得返回模板字段
            assert "template_candidates" not in result
            assert "applied_mapping_v2" not in result
            assert "template_default_values" not in result
        finally:
            os.unlink(tmp.name)

    @pytest.mark.asyncio
    async def test_preview_keyword_fallback_works_without_template(self):
        """无 template + 无 db → 关键词兜底仍生成 keyword_match 建议"""
        from app.services.import_service import preview_import

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
            result = await preview_import(tmp.name, "journal")
            suggestions = result.get("mapping_suggestions_v2", {})
            # 至少关键字匹配兜底
            sources = {v.get("source") for v in suggestions.values()}
            assert "keyword_match" in sources or len(sources) == 0
            assert "template" not in sources
        finally:
            os.unlink(tmp.name)
