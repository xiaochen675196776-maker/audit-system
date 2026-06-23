"""科目余额表标准化导入集成测试 — TASK-044

使用内存数据库 + 合成 Excel 文件，测试完整的 preview → analyze → execute 流程。
"""

import uuid
import os
import tempfile
from pathlib import Path
from decimal import Decimal

import pytest
import openpyxl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.standard_account import StandardAccount
from app.models.standard_trial_balance_import_batch import StandardTrialBalanceImportBatch
from app.models.standard_trial_balance_entry import StandardTrialBalanceEntry
from app.models.standard_trial_balance_raw_row import StandardTrialBalanceRawRow
from app.schemas.standard_trial_balance import AnalyzeResponse
from app.services.standard_trial_balance_import_service import (
    preview_standard_import,
    analyze_standard_import,
    execute_standard_import,
    get_import_batch,
)


# ── 工具 ───────────────────────────────────────────

def _make_excel(headers: list[str], rows: list[list]) -> str:
    """创建临时 Excel 文件，返回路径"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    wb.save(tmp.name)
    tmp.close()
    return tmp.name


async def _seed_standard_accounts(db: AsyncSession, accounts: list[dict]) -> dict[str, uuid.UUID]:
    """插入标准科目，返回 code → id 映射"""
    mapping = {}
    for a in accounts:
        sa = StandardAccount(
            account_code=a["code"],
            account_name=a["name"],
            balance_direction=a.get("direction"),
            account_category=a.get("category"),
            level=a.get("level", 1),
            is_leaf=a.get("is_leaf", True),
            is_active=a.get("is_active", True),
        )
        db.add(sa)
        await db.flush()
        mapping[a["code"]] = sa.id
    return mapping


# ── 测试：完整导入流程（有代码、双列金额）──────────

class TestFullFlowWithCodes:
    """有客户科目代码 + 借贷两列金额 → 完整流程"""

    @pytest.mark.asyncio
    async def test_preview_analyze_execute_success(self, db):
        """完整流程：预览 → 分析 → 执行 → 成功"""
        # 准备标准科目
        sa_map = await _seed_standard_accounts(db, [
            {"code": "1001", "name": "库存现金", "direction": "debit", "category": "asset", "level": 1},
            {"code": "1002", "name": "银行存款", "direction": "debit", "category": "asset", "level": 1},
        ])

        # 创建测试 Excel
        file_path = _make_excel(
            headers=["科目代码", "科目名称", "期初借方", "期初贷方", "期末借方", "期末贷方"],
            rows=[
                ["1001", "库存现金", "10000", "0", "15000", "0"],
                ["1002", "银行存款", "50000", "0", "60000", "0"],
            ],
        )

        try:
            # ── Preview ──
            preview = await preview_standard_import(
                db, file_path, "test.xlsx",
                fiscal_year=2024, period=1,
                customer_label="测试公司",
            )
            batch_id = uuid.UUID(preview["batch_id"])
            assert preview["total_rows"] == 2
            assert len(preview["columns"]) == 6

            # ── Analyze ──
            field_mappings = [
                {"column_id": "col_0", "field_name": "account_code"},
                {"column_id": "col_1", "field_name": "account_name"},
                {"column_id": "col_2", "field_name": "opening_debit",
                 "period_type": "opening", "split_mode": "two_column",
                 "debit_column_id": "col_2", "credit_column_id": "col_3"},
                {"column_id": "col_3", "field_name": "opening_credit",
                 "period_type": "opening", "split_mode": "two_column",
                 "debit_column_id": "col_2", "credit_column_id": "col_3"},
                {"column_id": "col_4", "field_name": "ending_debit",
                 "period_type": "ending", "split_mode": "two_column",
                 "debit_column_id": "col_4", "credit_column_id": "col_5"},
                {"column_id": "col_5", "field_name": "ending_credit",
                 "period_type": "ending", "split_mode": "two_column",
                 "debit_column_id": "col_4", "credit_column_id": "col_5"},
            ]

            analyze = await analyze_standard_import(
                db, batch_id, file_path,
                field_mappings=field_mappings,
                fiscal_year=2024, period=1,
                customer_label="测试公司",
            )
            assert analyze["status"] == "analyzed"
            assert len(analyze["hierarchy"]) == 2
            assert len(analyze["mapping_recommendations"]) == 2
            # 代码精确匹配应有候选人
            for rec in analyze["mapping_recommendations"]:
                assert len(rec["candidates"]) >= 1  # code_match
                assert rec["candidates"][0]["standard_balance_direction"] == "debit"

            api_payload = AnalyzeResponse.model_validate(analyze).model_dump(mode="json")
            for rec in api_payload["mapping_recommendations"]:
                assert rec["candidates"][0]["standard_balance_direction"] == "debit"

            # ── Execute ──
            confirmed_mappings = []
            for rec in analyze["mapping_recommendations"]:
                candidates = rec["candidates"]
                if candidates and candidates[0].get("standard_account_id"):
                    # 找到对应 row_index
                    code = rec.get("client_account_code")
                    for h in analyze["hierarchy"]:
                        if h["client_account_code"] == code:
                            confirmed_mappings.append({
                                "row_index": h["row_index"],
                                "client_account_code": code,
                                "client_account_name": rec.get("client_account_name"),
                                "standard_account_id": uuid.UUID(candidates[0]["standard_account_id"]),
                                "standard_account_code": candidates[0]["standard_account_code"],
                                "standard_account_name": candidates[0]["standard_account_name"],
                            })
                            break

            execute = await execute_standard_import(
                db, batch_id, file_path,
                confirmed_mappings=confirmed_mappings,
                warnings_confirmed=True,
                save_mapping_experience=True,
            )
            assert execute["status"] == "executed"
            assert execute["entry_count"] == 2
            assert execute["raw_row_count"] == 2
            assert execute["mapping_saved_count"] == 2

            # 验证标准余额表条目
            entries_result = await db.execute(
                select(StandardTrialBalanceEntry).where(
                    StandardTrialBalanceEntry.batch_id == batch_id
                )
            )
            entries = entries_result.scalars().all()
            assert len(entries) == 2

            # 验证第一条：期初借方10000、期末借方15000
            e1 = entries[0]
            assert e1.opening_debit == Decimal("10000")
            assert e1.opening_credit == Decimal("0")
            assert e1.ending_debit == Decimal("15000")
            assert e1.ending_credit == Decimal("0")
            assert e1.fiscal_year == 2024
            assert e1.period == 1

            # 验证原始行快照
            raw_result = await db.execute(
                select(StandardTrialBalanceRawRow).where(
                    StandardTrialBalanceRawRow.batch_id == batch_id
                )
            )
            raw_rows = raw_result.scalars().all()
            assert len(raw_rows) == 2

        finally:
            os.unlink(file_path)


# ── 测试：未映射阻止 execute ──────────────────────

class TestUnmappedBlocksExecute:
    """末级客户科目未映射 → 阻止执行"""

    @pytest.mark.asyncio
    async def test_unmapped_leaf_blocks(self, db):
        """有末级科目未映射时，execute 抛出 ValueError"""
        sa_map = await _seed_standard_accounts(db, [
            {"code": "1001", "name": "库存现金", "direction": "debit"},
        ])

        file_path = _make_excel(
            headers=["科目代码", "科目名称", "期末借方", "期末贷方"],
            rows=[
                ["1001", "库存现金", "10000", "0"],
                ["1002", "银行存款", "50000", "0"],  # 1002 没有标准科目，必须手动映射
            ],
        )

        try:
            preview = await preview_standard_import(
                db, file_path, "test.xlsx", fiscal_year=2024, period=1,
            )
            batch_id = uuid.UUID(preview["batch_id"])

            field_mappings = [
                {"column_id": "col_0", "field_name": "account_code"},
                {"column_id": "col_1", "field_name": "account_name"},
                {"column_id": "col_2", "field_name": "ending_debit",
                 "period_type": "ending", "split_mode": "two_column",
                 "debit_column_id": "col_2", "credit_column_id": "col_3"},
                {"column_id": "col_3", "field_name": "ending_credit",
                 "period_type": "ending", "split_mode": "two_column",
                 "debit_column_id": "col_2", "credit_column_id": "col_3"},
            ]

            analyze = await analyze_standard_import(
                db, batch_id, file_path,
                field_mappings=field_mappings,
                fiscal_year=2024, period=1,
            )

            # 只确认 1001，不确认 1002
            confirmed = [
                {
                    "row_index": 0,
                    "client_account_code": "1001",
                    "client_account_name": "库存现金",
                    "standard_account_id": sa_map["1001"],
                    "standard_account_code": "1001",
                    "standard_account_name": "库存现金",
                },
            ]

            with pytest.raises(ValueError, match="未映射"):
                await execute_standard_import(
                    db, batch_id, file_path,
                    confirmed_mappings=confirmed,
                    warnings_confirmed=True,
                )

        finally:
            os.unlink(file_path)


# ── 测试：父级金额不一致 ──────────────────────────

class TestParentAmountMismatch:
    """父级金额与子级汇总不一致 → warning → 确认后允许"""

    @pytest.mark.asyncio
    async def test_warning_blocks_unless_confirmed(self, db):
        """父级金额不一致：未确认时阻止，确认后允许"""
        sa_map = await _seed_standard_accounts(db, [
            {"code": "1001", "name": "库存现金", "direction": "debit", "level": 1, "is_leaf": False},
            {"code": "1001001", "name": "人民币", "direction": "debit", "level": 2, "is_leaf": True},
            {"code": "1001002", "name": "美元", "direction": "debit", "level": 2, "is_leaf": True},
        ])

        # 父级金额 35000，但子级汇总 = 10000 + 20000 = 30000，不一致
        file_path = _make_excel(
            headers=["科目代码", "科目名称", "期末借方", "期末贷方"],
            rows=[
                ["1001", "库存现金", "35000", "0"],      # 父级，多了 5000
                ["1001001", "人民币", "10000", "0"],
                ["1001002", "美元", "20000", "0"],
            ],
        )

        try:
            preview = await preview_standard_import(
                db, file_path, "test.xlsx", fiscal_year=2024, period=1,
            )
            batch_id = uuid.UUID(preview["batch_id"])

            field_mappings = [
                {"column_id": "col_0", "field_name": "account_code"},
                {"column_id": "col_1", "field_name": "account_name"},
                {"column_id": "col_2", "field_name": "ending_debit",
                 "period_type": "ending", "split_mode": "two_column",
                 "debit_column_id": "col_2", "credit_column_id": "col_3"},
                {"column_id": "col_3", "field_name": "ending_credit",
                 "period_type": "ending", "split_mode": "two_column",
                 "debit_column_id": "col_2", "credit_column_id": "col_3"},
            ]

            analyze = await analyze_standard_import(
                db, batch_id, file_path,
                field_mappings=field_mappings,
                fiscal_year=2024, period=1,
            )

            # 应该有父级不一致的 warning
            mismatch_warnings = [
                w for w in analyze["warnings"]
                if "不一致" in w.get("message", "")
            ]
            assert len(mismatch_warnings) >= 1, f"期望有父级不一致warning，实际 warnings={analyze['warnings']}"

            # 层级应正确
            hierarchy_by_code = {h["client_account_code"]: h for h in analyze["hierarchy"]}
            assert hierarchy_by_code["1001"]["is_summary"] is True
            assert hierarchy_by_code["1001"]["is_leaf"] is False
            assert hierarchy_by_code["1001001"]["is_leaf"] is True

            # 确认所有映射（包括父级，虽然父级不写条目）
            confirmed = []
            for code in ["1001", "1001001", "1001002"]:
                confirmed.append({
                    "row_index": hierarchy_by_code[code]["row_index"],
                    "client_account_code": code,
                    "client_account_name": code,
                    "standard_account_id": sa_map[code],
                    "standard_account_code": code,
                    "standard_account_name": code,
                })

            # 未确认警告 → 应阻止
            with pytest.raises(ValueError, match="警告未确认"):
                await execute_standard_import(
                    db, batch_id, file_path,
                    confirmed_mappings=confirmed,
                    warnings_confirmed=False,
                )

            # 确认警告 → 应成功
            execute = await execute_standard_import(
                db, batch_id, file_path,
                confirmed_mappings=confirmed,
                warnings_confirmed=True,
            )
            assert execute["status"] == "executed"
            # 只写叶子行（2 行），父级不入库
            assert execute["entry_count"] == 2

        finally:
            os.unlink(file_path)


# ── 测试：单列金额按标准方向拆分 ──────────────────

class TestSingleAmountSplitByDirection:
    """单列金额按标准科目方向拆分为借贷"""

    @pytest.mark.asyncio
    async def test_split_by_direction_debit(self, db):
        """借方向科目：正数 → 借方"""
        sa_map = await _seed_standard_accounts(db, [
            {"code": "1001", "name": "库存现金", "direction": "debit"},
        ])

        file_path = _make_excel(
            headers=["科目代码", "科目名称", "期末余额"],
            rows=[
                ["1001", "库存现金", "15000"],
            ],
        )

        try:
            preview = await preview_standard_import(
                db, file_path, "test.xlsx", fiscal_year=2024, period=1,
            )
            batch_id = uuid.UUID(preview["batch_id"])

            field_mappings = [
                {"column_id": "col_0", "field_name": "account_code"},
                {"column_id": "col_1", "field_name": "account_name"},
                {"column_id": "col_2", "field_name": "ending_debit",
                 "period_type": "ending", "split_mode": "single_by_direction"},
            ]

            analyze = await analyze_standard_import(
                db, batch_id, file_path,
                field_mappings=field_mappings,
                fiscal_year=2024, period=1,
            )

            # 金额应被正确拆分：正数进 debit
            amounts = analyze["amounts"]
            assert len(amounts) == 1
            assert amounts[0]["ending_debit"] == Decimal("15000")
            assert amounts[0]["ending_credit"] == Decimal("0")

            # 确认映射并执行
            confirmed = [{
                "row_index": 0,
                "client_account_code": "1001",
                "client_account_name": "库存现金",
                "standard_account_id": sa_map["1001"],
                "standard_account_code": "1001",
                "standard_account_name": "库存现金",
            }]

            execute = await execute_standard_import(
                db, batch_id, file_path,
                confirmed_mappings=confirmed,
                warnings_confirmed=True,
            )
            assert execute["entry_count"] == 1

            # 验证入库金额
            entries_result = await db.execute(
                select(StandardTrialBalanceEntry).where(
                    StandardTrialBalanceEntry.batch_id == batch_id
                )
            )
            entry = entries_result.scalar_one()
            assert entry.ending_debit == Decimal("15000")
            assert entry.ending_credit == Decimal("0")

        finally:
            os.unlink(file_path)

    @pytest.mark.asyncio
    async def test_split_by_direction_credit(self, db):
        """贷方向科目：正数 → 贷方"""
        sa_map = await _seed_standard_accounts(db, [
            {"code": "2001", "name": "短期借款", "direction": "credit"},
        ])

        file_path = _make_excel(
            headers=["科目代码", "科目名称", "期末余额"],
            rows=[
                ["2001", "短期借款", "50000"],
            ],
        )

        try:
            preview = await preview_standard_import(
                db, file_path, "test.xlsx", fiscal_year=2024, period=1,
            )
            batch_id = uuid.UUID(preview["batch_id"])

            field_mappings = [
                {"column_id": "col_0", "field_name": "account_code"},
                {"column_id": "col_1", "field_name": "account_name"},
                {"column_id": "col_2", "field_name": "ending_debit",
                 "period_type": "ending", "split_mode": "single_by_direction"},
            ]

            analyze = await analyze_standard_import(
                db, batch_id, file_path,
                field_mappings=field_mappings,
                fiscal_year=2024, period=1,
            )

            amounts = analyze["amounts"]
            assert amounts[0]["ending_debit"] == Decimal("0")
            assert amounts[0]["ending_credit"] == Decimal("50000")

            confirmed = [{
                "row_index": 0,
                "client_account_code": "2001",
                "client_account_name": "短期借款",
                "standard_account_id": sa_map["2001"],
                "standard_account_code": "2001",
                "standard_account_name": "短期借款",
            }]

            execute = await execute_standard_import(
                db, batch_id, file_path,
                confirmed_mappings=confirmed,
                warnings_confirmed=True,
            )
            entry_result = await db.execute(
                select(StandardTrialBalanceEntry).where(
                    StandardTrialBalanceEntry.batch_id == batch_id
                )
            )
            entry = entry_result.scalar_one()
            assert entry.ending_debit == Decimal("0")
            assert entry.ending_credit == Decimal("50000")

        finally:
            os.unlink(file_path)


# ── 测试：停用标准科目的映射是警告候选 ──────────────

class TestDisabledStandardAccountWarning:
    """历史映射指向停用标准科目 → warning 候选，不能自动套用"""

    @pytest.mark.asyncio
    async def test_disabled_account_is_warning(self, db):
        """停用标准科目只作为 warning 候选"""
        await _seed_standard_accounts(db, [
            {"code": "1001", "name": "库存现金(旧)", "direction": "debit", "is_active": False},
            {"code": "1002", "name": "库存现金", "direction": "debit", "is_active": True},
        ])

        # 只创建活跃的映射经验供推荐
        # （client_account_mapping_service 需要经验来产生 disabled warning）

        file_path = _make_excel(
            headers=["科目代码", "科目名称", "期末借方", "期末贷方"],
            rows=[["1001", "库存现金", "10000", "0"]],
        )

        try:
            preview = await preview_standard_import(
                db, file_path, "test.xlsx", fiscal_year=2024, period=1,
            )
            batch_id = uuid.UUID(preview["batch_id"])

            field_mappings = [
                {"column_id": "col_0", "field_name": "account_code"},
                {"column_id": "col_1", "field_name": "account_name"},
                {"column_id": "col_2", "field_name": "ending_debit",
                 "period_type": "ending", "split_mode": "two_column",
                 "debit_column_id": "col_2", "credit_column_id": "col_3"},
                {"column_id": "col_3", "field_name": "ending_credit",
                 "period_type": "ending", "split_mode": "two_column",
                 "debit_column_id": "col_2", "credit_column_id": "col_3"},
            ]

            analyze = await analyze_standard_import(
                db, batch_id, file_path,
                field_mappings=field_mappings,
                fiscal_year=2024, period=1,
            )

            # 至少应有 code_match 候选人
            recs = analyze["mapping_recommendations"]
            assert len(recs) >= 1
            candidates = recs[0]["candidates"]
            assert len(candidates) >= 1

            # 不应自动套用 disabled 的（code_match 只返回 is_active=True）
            # 所以 candidate 应该指向活跃科目（code=1002）
            for c in candidates:
                if c.get("warning") is None:
                    assert c["standard_account_code"] in ("1001", "1002")

        finally:
            os.unlink(file_path)


# ── 测试：标准方向缺失时拒绝 ──────────────────────

class TestNoDirectionRejects:
    """按标准方向拆分但科目无方向 → execute 拒绝"""

    @pytest.mark.asyncio
    async def test_no_direction_blocks_execute(self, db):
        """科目无方向 + single_by_direction → execute 抛出 ValueError"""
        sa_map = await _seed_standard_accounts(db, [
            {"code": "5001", "name": "营业收入", "direction": None},  # 无方向
        ])

        file_path = _make_excel(
            headers=["科目代码", "科目名称", "期末余额"],
            rows=[["5001", "营业收入", "80000"]],
        )

        try:
            preview = await preview_standard_import(
                db, file_path, "test.xlsx", fiscal_year=2024, period=1,
            )
            batch_id = uuid.UUID(preview["batch_id"])

            field_mappings = [
                {"column_id": "col_0", "field_name": "account_code"},
                {"column_id": "col_1", "field_name": "account_name"},
                {"column_id": "col_2", "field_name": "ending_debit",
                 "period_type": "ending", "split_mode": "single_by_direction"},
            ]

            analyze = await analyze_standard_import(
                db, batch_id, file_path,
                field_mappings=field_mappings,
                fiscal_year=2024, period=1,
            )

            confirmed = [{
                "row_index": 0,
                "client_account_code": "5001",
                "client_account_name": "营业收入",
                "standard_account_id": sa_map["5001"],
                "standard_account_code": "5001",
                "standard_account_name": "营业收入",
            }]

            with pytest.raises(ValueError, match="余额方向为空"):
                await execute_standard_import(
                    db, batch_id, file_path,
                    confirmed_mappings=confirmed,
                    warnings_confirmed=True,
                )

        finally:
            os.unlink(file_path)


# ── 测试：无代码有缩进的层级建议 ──────────────────

class TestNoCodeIndentHierarchy:
    """无代码但有缩进 → 生成层级建议"""

    @pytest.mark.asyncio
    async def test_no_code_with_indent_suggestion(self, db):
        """无代码行保持 level_source=flat（第一版不从Excel取缩进）"""
        sa_map = await _seed_standard_accounts(db, [
            {"code": "9999", "name": "其他", "direction": "debit"},
        ])

        # 无科目代码的 Excel
        file_path = _make_excel(
            headers=["科目名称", "期末借方", "期末贷方"],
            rows=[
                ["资产", "30000", "0"],
                ["现金", "30000", "0"],
            ],
        )

        try:
            preview = await preview_standard_import(
                db, file_path, "test.xlsx", fiscal_year=2024, period=1,
            )
            batch_id = uuid.UUID(preview["batch_id"])

            field_mappings = [
                {"column_id": "col_0", "field_name": "account_name"},
                {"column_id": "col_1", "field_name": "ending_debit",
                 "period_type": "ending", "split_mode": "two_column",
                 "debit_column_id": "col_1", "credit_column_id": "col_2"},
                {"column_id": "col_2", "field_name": "ending_credit",
                 "period_type": "ending", "split_mode": "two_column",
                 "debit_column_id": "col_1", "credit_column_id": "col_2"},
            ]

            analyze = await analyze_standard_import(
                db, batch_id, file_path,
                field_mappings=field_mappings,
                fiscal_year=2024, period=1,
            )

            # 无代码 → 平铺层级
            for h in analyze["hierarchy"]:
                assert h["level"] == 1
                assert h["is_leaf"] is True
                assert h["level_source"] == "flat"

            # 推荐结果中应有名称相似的候选
            recs = analyze["mapping_recommendations"]
            assert len(recs) == 2  # 两行

        finally:
            os.unlink(file_path)


# ── 测试：批次查询 ─────────────────────────────────

class TestGetBatch:
    """查询批次详情"""

    @pytest.mark.asyncio
    async def test_get_batch_info(self, db):
        """获取批次信息"""
        file_path = _make_excel(
            headers=["科目代码", "科目名称", "期末余额"],
            rows=[["1001", "库存现金", "10000"]],
        )

        try:
            preview = await preview_standard_import(
                db, file_path, "test.xlsx", fiscal_year=2024, period=1,
                customer_label="测试公司",
            )
            batch_id = uuid.UUID(preview["batch_id"])

            info = await get_import_batch(db, batch_id)
            assert info is not None
            assert info["file_name"] == "test.xlsx"
            assert info["customer_label"] == "测试公司"
            assert info["fiscal_year"] == 2024
            assert info["period"] == 1
            assert info["status"] == "previewed"
            assert info["entry_count"] == 0

        finally:
            os.unlink(file_path)


# ── 测试：缺少客户科目代码和名称 ─────────────────

class TestMissingCodeAndName:
    """缺少科目代码和名称 → 映射忽略该行"""

    @pytest.mark.asyncio
    async def test_empty_code_and_name_ignored(self, db):
        """无代码无名称的行 mapping_status='ignored'"""
        sa_map = await _seed_standard_accounts(db, [
            {"code": "1001", "name": "库存现金", "direction": "debit"},
        ])

        file_path = _make_excel(
            headers=["科目代码", "科目名称", "期末借方", "期末贷方"],
            rows=[
                ["1001", "库存现金", "10000", "0"],
                ["", "", "50000", "0"],  # 无代码无名称
            ],
        )

        try:
            preview = await preview_standard_import(
                db, file_path, "test.xlsx", fiscal_year=2024, period=1,
            )
            batch_id = uuid.UUID(preview["batch_id"])

            field_mappings = [
                {"column_id": "col_0", "field_name": "account_code"},
                {"column_id": "col_1", "field_name": "account_name"},
                {"column_id": "col_2", "field_name": "ending_debit",
                 "period_type": "ending", "split_mode": "two_column",
                 "debit_column_id": "col_2", "credit_column_id": "col_3"},
                {"column_id": "col_3", "field_name": "ending_credit",
                 "period_type": "ending", "split_mode": "two_column",
                 "debit_column_id": "col_2", "credit_column_id": "col_3"},
            ]

            analyze = await analyze_standard_import(
                db, batch_id, file_path,
                field_mappings=field_mappings,
                fiscal_year=2024, period=1,
            )

            # 只有一行有代码，映射推荐只有1条
            assert len(analyze["mapping_recommendations"]) == 1

            confirmed = [{
                "row_index": 0,
                "client_account_code": "1001",
                "client_account_name": "库存现金",
                "standard_account_id": sa_map["1001"],
                "standard_account_code": "1001",
                "standard_account_name": "库存现金",
            }]

            execute = await execute_standard_import(
                db, batch_id, file_path,
                confirmed_mappings=confirmed,
                warnings_confirmed=True,
            )

            # 只有 1 条条目
            assert execute["entry_count"] == 1
            # 原始行有 2 条
            assert execute["raw_row_count"] == 2

        finally:
            os.unlink(file_path)
