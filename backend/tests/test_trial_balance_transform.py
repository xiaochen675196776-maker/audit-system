"""科目余额表层级识别与金额拆分引擎测试 — TASK-042"""

from decimal import Decimal
import pytest

from app.services.trial_balance_transform import (
    AmountConfig,
    RowInput,
    TransformResult,
    BatchTransformResult,
    detect_hierarchy_by_code,
    detect_hierarchy_by_indent,
    assign_flat_hierarchy,
    merge_hierarchy,
    validate_parent_amounts,
    transform_amounts,
    transform_rows,
    get_leaf_rows,
    get_summary_rows,
    has_blocking_errors,
    _safe_decimal,
    _split_single_amount,
)


# ── 工具函数测试 ────────────────────────────────────

class TestSafeDecimal:
    """安全 Decimal 转换"""

    def test_int(self):
        assert _safe_decimal(100) == Decimal("100")

    def test_str(self):
        assert _safe_decimal("12345.67") == Decimal("12345.67")

    def test_empty(self):
        assert _safe_decimal("") is None

    def test_none(self):
        assert _safe_decimal(None) is None

    def test_comma(self):
        assert _safe_decimal("1,234.56") == Decimal("1234.56")

    def test_chinese_comma(self):
        assert _safe_decimal("1，234.56") == Decimal("1234.56")

    def test_invalid(self):
        assert _safe_decimal("abc") is None


# ── 层级识别：代码前缀 ──────────────────────────────

class TestHierarchyByCode:
    """按科目代码前缀识别层级"""

    def test_single_code_level_1(self):
        """只有一个代码 → level=1, is_leaf=True"""
        rows = [RowInput(row_index=0, client_account_code="1001", client_account_name="库存现金")]
        results, warnings = detect_hierarchy_by_code(rows)
        assert len(results) == 1
        assert results[0]["level"] == 1
        assert results[0]["parent_key"] is None
        assert results[0]["is_leaf"] is True
        assert results[0]["is_summary"] is False
        assert results[0]["level_source"] == "code_prefix"

    def test_two_level_hierarchy(self):
        """两级科目：1001 父级、1001001 子级"""
        rows = [
            RowInput(row_index=0, client_account_code="1001", client_account_name="库存现金"),
            RowInput(row_index=1, client_account_code="1001001", client_account_name="人民币"),
        ]
        results, warnings = detect_hierarchy_by_code(rows)

        # 父级 1001
        assert results[0]["level"] == 1
        assert results[0]["parent_key"] is None
        assert results[0]["is_leaf"] is False
        assert results[0]["is_summary"] is True
        assert results[0]["level_source"] == "code_prefix"

        # 子级 1001001 — level = ancestor_count + 1 = 2
        assert results[1]["level"] == 2
        assert results[1]["parent_key"] == "1001"
        assert results[1]["is_leaf"] is True
        assert results[1]["is_summary"] is False
        assert results[1]["level_source"] == "code_prefix"

    def test_three_level_hierarchy(self):
        """三级科目：1 → 1001 → 1001001"""
        rows = [
            RowInput(row_index=0, client_account_code="1", client_account_name="资产"),
            RowInput(row_index=1, client_account_code="1001", client_account_name="库存现金"),
            RowInput(row_index=2, client_account_code="1001001", client_account_name="人民币"),
        ]
        results, warnings = detect_hierarchy_by_code(rows)

        # 1: 一级，有子级
        assert results[0]["level"] == 1
        assert results[0]["is_leaf"] is False
        assert results[0]["is_summary"] is True

        # 1001: 二级（父级="1"，ancestor_count=1 → level=2），有子级
        assert results[1]["level"] == 2
        assert results[1]["parent_key"] == "1"
        assert results[1]["is_leaf"] is False
        assert results[1]["is_summary"] is True

        # 1001001: 三级（父级="1001"，ancestor_count=2 → level=3），末级
        assert results[2]["level"] == 3
        assert results[2]["parent_key"] == "1001"
        assert results[2]["is_leaf"] is True
        assert results[2]["is_summary"] is False

    def test_no_code_keeps_none(self):
        """无代码行保留 level=None 等待其他策略"""
        rows = [
            RowInput(row_index=0, client_account_code="1001", client_account_name="库存现金"),
            RowInput(row_index=1, client_account_code=None, client_account_name="未知"),
        ]
        results, warnings = detect_hierarchy_by_code(rows)
        assert results[1]["level"] is None
        assert results[1]["level_source"] == "flat"

    def test_duplicate_codes_handled(self):
        """重复代码不崩溃"""
        rows = [
            RowInput(row_index=0, client_account_code="1001", client_account_name="库存现金"),
            RowInput(row_index=1, client_account_code="1001", client_account_name="库存现金(重复)"),
        ]
        results, warnings = detect_hierarchy_by_code(rows)
        assert len(results) == 2

    def test_many_siblings(self):
        """多个同级子级"""
        rows = [
            RowInput(row_index=0, client_account_code="1001", client_account_name="库存现金"),
            RowInput(row_index=1, client_account_code="1001001", client_account_name="人民币"),
            RowInput(row_index=2, client_account_code="1001002", client_account_name="美元"),
            RowInput(row_index=3, client_account_code="1001003", client_account_name="港币"),
        ]
        results, warnings = detect_hierarchy_by_code(rows)

        # 父级 1001 有多个子级
        assert results[0]["is_summary"] is True

        # 三个子级都是末级
        for i in range(1, 4):
            assert results[i]["is_leaf"] is True
            assert results[i]["parent_key"] == "1001"


# ── 层级识别：Excel 缩进 ─────────────────────────────

class TestHierarchyByIndent:
    """按 Excel 缩进识别建议层级"""

    def test_single_indent_level(self):
        """单行缩进 → level=indent+1"""
        rows = [
            RowInput(row_index=0, client_account_name="资产", indent_level=0),
        ]
        results, warnings = detect_hierarchy_by_indent(rows)
        assert results[0]["level"] == 1
        assert results[0]["level_source"] == "indent_suggested"
        assert results[0]["is_leaf"] is True

    def test_two_level_indent(self):
        """两级缩进"""
        rows = [
            RowInput(row_index=0, client_account_name="资产", indent_level=0),
            RowInput(row_index=1, client_account_name="库存现金", indent_level=1),
        ]
        results, warnings = detect_hierarchy_by_indent(rows)

        # 缩进0 → level=1, 是父级
        assert results[0]["level"] == 1
        assert results[0]["is_summary"] is True
        assert results[0]["is_leaf"] is False

        # 缩进1 → level=2, 是末级，parent_key=0
        assert results[1]["level"] == 2
        assert results[1]["is_leaf"] is True
        assert results[1]["parent_key"] == "0"

    def test_three_level_indent(self):
        """三级缩进"""
        rows = [
            RowInput(row_index=0, client_account_name="资产", indent_level=0),
            RowInput(row_index=1, client_account_name="流动资产", indent_level=1),
            RowInput(row_index=2, client_account_name="库存现金", indent_level=2),
        ]
        results, warnings = detect_hierarchy_by_indent(rows)

        assert results[0]["is_summary"] is True  # 资产有下级
        assert results[1]["is_summary"] is True  # 流动资产有下级
        assert results[2]["is_leaf"] is True     # 库存现金末级

        # 库存现金的 parent 是流动资产(row_index=1)
        assert results[2]["parent_key"] == "1"
        # 流动资产的 parent 是资产(row_index=0)
        assert results[1]["parent_key"] == "0"

    def test_mixed_indent_pattern(self):
        """混合缩进：同级 + 缩进 + 缩回"""
        rows = [
            RowInput(row_index=0, client_account_name="资产", indent_level=0),
            RowInput(row_index=1, client_account_name="库存现金", indent_level=1),
            RowInput(row_index=2, client_account_name="银行存款", indent_level=1),  # 缩回同级
            RowInput(row_index=3, client_account_name="负债", indent_level=0),      # 缩回一级
        ]
        results, warnings = detect_hierarchy_by_indent(rows)

        # 库存现金 parent=资产(0)
        assert results[1]["parent_key"] == "0"
        # 银行存款 parent=资产(0)，不是库存现金
        assert results[2]["parent_key"] == "0"
        # 负债 parent=None
        assert results[3]["parent_key"] is None

    def test_no_indent_rows_ignored(self):
        """无缩进行保留 level=None"""
        rows = [
            RowInput(row_index=0, client_account_name="资产", indent_level=0),
            RowInput(row_index=1, client_account_name="未知"),  # 无 indent
        ]
        results, warnings = detect_hierarchy_by_indent(rows)
        assert results[0]["level"] == 1
        assert results[1]["level"] is None

    def test_all_no_indent(self):
        """全部无缩进 → 全部 level=None"""
        rows = [
            RowInput(row_index=0, client_account_name="A"),
            RowInput(row_index=1, client_account_name="B"),
        ]
        results, warnings = detect_hierarchy_by_indent(rows)
        for r in results:
            assert r["level"] is None


# ── 层级识别：平铺 ──────────────────────────────────

class TestFlatHierarchy:
    """无代码无缩进平铺策略"""

    def test_all_flat(self):
        """所有行都是 level=1 末级"""
        rows = [
            RowInput(row_index=0, client_account_name="A"),
            RowInput(row_index=1, client_account_name="B"),
            RowInput(row_index=2, client_account_name="C"),
        ]
        results = assign_flat_hierarchy(rows)
        for r in results:
            assert r["level"] == 1
            assert r["is_leaf"] is True
            assert r["is_summary"] is False
            assert r["level_source"] == "flat"
            assert r["parent_key"] is None


# ── 层级合并 ────────────────────────────────────────

class TestMergeHierarchy:
    """合并多策略层级结果"""

    def test_code_priority_over_indent(self):
        """有代码时优先用代码识别"""
        rows = [
            RowInput(row_index=0, client_account_code="1001", client_account_name="库存现金", indent_level=1),
            RowInput(row_index=1, client_account_code="1001001", client_account_name="人民币", indent_level=2),
        ]
        code_results, _ = detect_hierarchy_by_code(rows)
        indent_results, _ = detect_hierarchy_by_indent(rows)
        flat_results = assign_flat_hierarchy(rows)

        merged = merge_hierarchy(code_results, indent_results, flat_results)
        # 有代码，应该用 code_results
        assert merged[0]["level_source"] == "code_prefix"
        assert merged[1]["level_source"] == "code_prefix"

    def test_indent_fallback_when_no_code(self):
        """无代码有缩进时用缩进建议"""
        rows = [
            RowInput(row_index=0, client_account_name="资产", indent_level=0),
            RowInput(row_index=1, client_account_name="库存现金", indent_level=1),
        ]
        code_results, _ = detect_hierarchy_by_code(rows)
        indent_results, _ = detect_hierarchy_by_indent(rows)
        flat_results = assign_flat_hierarchy(rows)

        merged = merge_hierarchy(code_results, indent_results, flat_results)
        assert merged[0]["level_source"] == "indent_suggested"
        assert merged[1]["level_source"] == "indent_suggested"

    def test_flat_fallback(self):
        """无代码无缩进 → 平铺"""
        rows = [
            RowInput(row_index=0, client_account_name="A"),
            RowInput(row_index=1, client_account_name="B"),
        ]
        code_results, _ = detect_hierarchy_by_code(rows)
        indent_results, _ = detect_hierarchy_by_indent(rows)
        flat_results = assign_flat_hierarchy(rows)

        merged = merge_hierarchy(code_results, indent_results, flat_results)
        for m in merged:
            assert m["level"] == 1
            assert m["level_source"] == "flat"


# ── 金额拆分 ────────────────────────────────────────

class TestAmountSplitting:
    """金额映射与拆分"""

    def test_two_column_direct_mapping(self):
        """借方/贷方两列直接映射"""
        rows = [
            RowInput(
                row_index=0,
                client_account_code="1001",
                client_account_name="库存现金",
                standard_direction="debit",
                values={
                    "opening_dr": "10000.00",
                    "opening_cr": "0",
                    "current_dr": "5000.00",
                    "current_cr": "2000.00",
                    "ending_dr": "13000.00",
                    "ending_cr": "0",
                },
                amount_configs=[
                    AmountConfig("opening", "two_column", debit_field="opening_dr", credit_field="opening_cr"),
                    AmountConfig("current", "two_column", debit_field="current_dr", credit_field="current_cr"),
                    AmountConfig("ending", "two_column", debit_field="ending_dr", credit_field="ending_cr"),
                ],
            ),
        ]
        results, warnings, errors = transform_amounts(rows)
        assert len(results) == 1
        r = results[0]
        assert r.opening_debit == Decimal("10000.00")
        assert r.opening_credit == Decimal("0")
        assert r.current_debit == Decimal("5000.00")
        assert r.current_credit == Decimal("2000.00")
        assert r.ending_debit == Decimal("13000.00")
        assert r.ending_credit == Decimal("0")
        assert len(errors) == 0

    def test_single_by_direction_debit_positive(self):
        """单列金额按标准方向拆：借方正数 → 进借方"""
        rows = [
            RowInput(
                row_index=0,
                client_account_code="1001",
                client_account_name="库存现金",
                standard_direction="debit",
                values={"ending_balance": "10000.00"},
                amount_configs=[
                    AmountConfig("ending", "single_by_direction", amount_field="ending_balance"),
                ],
            ),
        ]
        results, warnings, errors = transform_amounts(rows)
        assert results[0].ending_debit == Decimal("10000.00")
        assert results[0].ending_credit == Decimal("0")
        assert len(errors) == 0

    def test_single_by_direction_debit_negative(self):
        """单列金额按标准方向拆：借方负数 → 进贷方 + 警告"""
        rows = [
            RowInput(
                row_index=0,
                client_account_code="1001",
                client_account_name="库存现金",
                standard_direction="debit",
                values={"ending_balance": "-500.00"},
                amount_configs=[
                    AmountConfig("ending", "single_by_direction", amount_field="ending_balance"),
                ],
            ),
        ]
        results, warnings, errors = transform_amounts(rows)
        assert results[0].ending_debit == Decimal("0")
        assert results[0].ending_credit == Decimal("500.00")
        assert len(warnings) == 1
        assert "负数" in warnings[0]

    def test_single_by_direction_credit_positive(self):
        """单列金额按标准方向拆：贷方正数 → 进贷方"""
        rows = [
            RowInput(
                row_index=0,
                client_account_code="2001",
                client_account_name="短期借款",
                standard_direction="credit",
                values={"ending_balance": "50000.00"},
                amount_configs=[
                    AmountConfig("ending", "single_by_direction", amount_field="ending_balance"),
                ],
            ),
        ]
        results, warnings, errors = transform_amounts(rows)
        assert results[0].ending_debit == Decimal("0")
        assert results[0].ending_credit == Decimal("50000.00")
        assert len(errors) == 0

    def test_single_by_direction_credit_negative(self):
        """单列金额按标准方向拆：贷方负数 → 进借方 + 警告"""
        rows = [
            RowInput(
                row_index=0,
                client_account_code="2001",
                client_account_name="短期借款",
                standard_direction="credit",
                values={"ending_balance": "-1000.00"},
                amount_configs=[
                    AmountConfig("ending", "single_by_direction", amount_field="ending_balance"),
                ],
            ),
        ]
        results, warnings, errors = transform_amounts(rows)
        assert results[0].ending_debit == Decimal("1000.00")
        assert results[0].ending_credit == Decimal("0")
        assert len(warnings) == 1

    def test_user_override_as_debit_positive(self):
        """用户覆盖为借方：正数进借方"""
        rows = [
            RowInput(
                row_index=0,
                client_account_code="5001",
                client_account_name="营业收入",
                standard_direction=None,
                values={"ending_balance": "80000.00"},
                amount_configs=[
                    AmountConfig("ending", "single_as_debit", amount_field="ending_balance"),
                ],
            ),
        ]
        results, warnings, errors = transform_amounts(rows)
        assert results[0].ending_debit == Decimal("80000.00")
        assert results[0].ending_credit == Decimal("0")

    def test_user_override_as_debit_negative(self):
        """用户覆盖为借方：负数绝对值进贷方 + 警告"""
        rows = [
            RowInput(
                row_index=0,
                client_account_code="5001",
                client_account_name="营业收入",
                standard_direction=None,
                values={"ending_balance": "-800.00"},
                amount_configs=[
                    AmountConfig("ending", "single_as_debit", amount_field="ending_balance"),
                ],
            ),
        ]
        results, warnings, errors = transform_amounts(rows)
        assert results[0].ending_debit == Decimal("0")
        assert results[0].ending_credit == Decimal("800.00")
        assert len(warnings) == 1
        assert "负数" in warnings[0]

    def test_user_override_as_credit_positive(self):
        """用户覆盖为贷方：正数进贷方"""
        rows = [
            RowInput(
                row_index=0,
                client_account_code="5001",
                client_account_name="营业收入",
                standard_direction=None,
                values={"ending_balance": "80000.00"},
                amount_configs=[
                    AmountConfig("ending", "single_as_credit", amount_field="ending_balance"),
                ],
            ),
        ]
        results, warnings, errors = transform_amounts(rows)
        assert results[0].ending_debit == Decimal("0")
        assert results[0].ending_credit == Decimal("80000.00")

    def test_user_override_as_credit_negative(self):
        """用户覆盖为贷方：负数绝对值进借方 + 警告"""
        rows = [
            RowInput(
                row_index=0,
                client_account_code="5001",
                client_account_name="营业收入",
                standard_direction=None,
                values={"ending_balance": "-800.00"},
                amount_configs=[
                    AmountConfig("ending", "single_as_credit", amount_field="ending_balance"),
                ],
            ),
        ]
        results, warnings, errors = transform_amounts(rows)
        assert results[0].ending_debit == Decimal("800.00")
        assert results[0].ending_credit == Decimal("0")
        assert len(warnings) == 1

    def test_direction_missing_error(self):
        """标准方向缺失时按方向拆分 → 错误"""
        rows = [
            RowInput(
                row_index=0,
                client_account_code="9999",
                client_account_name="未知科目",
                standard_direction=None,
                values={"ending_balance": "1000.00"},
                amount_configs=[
                    AmountConfig("ending", "single_by_direction", amount_field="ending_balance"),
                ],
            ),
        ]
        results, warnings, errors = transform_amounts(rows)
        assert len(errors) == 1
        assert "方向缺失" in errors[0] or "无法按标准方向拆分" in errors[0]
        # 金额应保持为 0（未被拆分）
        assert results[0].ending_debit == Decimal("0")
        assert results[0].ending_credit == Decimal("0")

    def test_multiple_periods_single_column(self):
        """多个期间（期初+期末）均按单列拆分"""
        rows = [
            RowInput(
                row_index=0,
                client_account_code="1001",
                client_account_name="库存现金",
                standard_direction="debit",
                values={
                    "opening_bal": "10000.00",
                    "ending_bal": "13000.00",
                },
                amount_configs=[
                    AmountConfig("opening", "single_by_direction", amount_field="opening_bal"),
                    AmountConfig("ending", "single_by_direction", amount_field="ending_bal"),
                ],
            ),
        ]
        results, warnings, errors = transform_amounts(rows)
        assert results[0].opening_debit == Decimal("10000.00")
        assert results[0].ending_debit == Decimal("13000.00")

    def test_invalid_amount_field(self):
        """金额字段无法解析 → 警告"""
        rows = [
            RowInput(
                row_index=0,
                client_account_code="1001",
                client_account_name="库存现金",
                standard_direction="debit",
                values={"ending_balance": "N/A"},
                amount_configs=[
                    AmountConfig("ending", "single_by_direction", amount_field="ending_balance"),
                ],
            ),
        ]
        results, warnings, errors = transform_amounts(rows)
        assert len(warnings) == 1
        assert "无法解析为数字" in warnings[0]


# ── 父级金额校验 ────────────────────────────────────

class TestParentAmountValidation:
    """父级金额与子级汇总不一致 → warning"""

    def test_parent_child_consistent(self):
        """父级=子级汇总 → 无 warning"""
        from app.services.trial_balance_transform import TransformResult

        rows = [
            TransformResult(
                row_index=0, client_account_code="1001", client_account_name="库存现金",
                opening_debit=Decimal("30000"), ending_debit=Decimal("30000"),
            ),
            TransformResult(
                row_index=1, client_account_code="1001001", client_account_name="人民币",
                opening_debit=Decimal("10000"), ending_debit=Decimal("10000"),
            ),
            TransformResult(
                row_index=2, client_account_code="1001002", client_account_name="美元",
                opening_debit=Decimal("20000"), ending_debit=Decimal("20000"),
            ),
        ]
        hierarchy = [
            {"row_index": 0, "level": 1, "parent_key": None, "is_leaf": False, "is_summary": True, "level_source": "code_prefix"},
            {"row_index": 1, "level": 2, "parent_key": "1001", "is_leaf": True, "is_summary": False, "level_source": "code_prefix"},
            {"row_index": 2, "level": 2, "parent_key": "1001", "is_leaf": True, "is_summary": False, "level_source": "code_prefix"},
        ]

        warnings = validate_parent_amounts(rows, hierarchy)
        assert len(warnings) == 0  # 10000 + 20000 = 30000 ✓

    def test_parent_child_inconsistent(self):
        """父级金额 ≠ 子级汇总 → warning"""
        from app.services.trial_balance_transform import TransformResult

        rows = [
            TransformResult(
                row_index=0, client_account_code="1001", client_account_name="库存现金",
                opening_debit=Decimal("35000"), ending_debit=Decimal("35000"),
            ),
            TransformResult(
                row_index=1, client_account_code="1001001", client_account_name="人民币",
                opening_debit=Decimal("10000"), ending_debit=Decimal("10000"),
            ),
            TransformResult(
                row_index=2, client_account_code="1001002", client_account_name="美元",
                opening_debit=Decimal("20000"), ending_debit=Decimal("20000"),
            ),
        ]
        hierarchy = [
            {"row_index": 0, "level": 1, "parent_key": None, "is_leaf": False, "is_summary": True, "level_source": "code_prefix"},
            {"row_index": 1, "level": 2, "parent_key": "1001", "is_leaf": True, "is_summary": False, "level_source": "code_prefix"},
            {"row_index": 2, "level": 2, "parent_key": "1001", "is_leaf": True, "is_summary": False, "level_source": "code_prefix"},
        ]

        warnings = validate_parent_amounts(rows, hierarchy)
        assert len(warnings) == 2  # 期初和期末都有差异
        assert "不一致" in warnings[0]

    def test_parent_child_credit_inconsistent(self):
        """贷方父级汇总不一致"""
        from app.services.trial_balance_transform import TransformResult

        rows = [
            TransformResult(
                row_index=0, client_account_code="2001", client_account_name="短期借款",
                opening_credit=Decimal("60000"), ending_credit=Decimal("60000"),
            ),
            TransformResult(
                row_index=1, client_account_code="2001001", client_account_name="银行A",
                opening_credit=Decimal("40000"), ending_credit=Decimal("40000"),
            ),
            TransformResult(
                row_index=2, client_account_code="2001002", client_account_name="银行B",
                opening_credit=Decimal("10000"), ending_credit=Decimal("10000"),
            ),
        ]
        hierarchy = [
            {"row_index": 0, "level": 1, "parent_key": None, "is_leaf": False, "is_summary": True, "level_source": "code_prefix"},
            {"row_index": 1, "level": 2, "parent_key": "2001", "is_leaf": True, "is_summary": False, "level_source": "code_prefix"},
            {"row_index": 2, "level": 2, "parent_key": "2001", "is_leaf": True, "is_summary": False, "level_source": "code_prefix"},
        ]

        warnings = validate_parent_amounts(rows, hierarchy)
        assert len(warnings) == 2  # 差异 60000 vs 50000
        assert "贷方" in warnings[0] or "不一致" in warnings[0]

    def test_no_children_no_warning(self):
        """没有子级时不对父级校验"""
        from app.services.trial_balance_transform import TransformResult

        rows = [
            TransformResult(
                row_index=0, client_account_code="1001", client_account_name="库存现金",
                opening_debit=Decimal("30000"),
            ),
        ]
        hierarchy = [
            {"row_index": 0, "level": 1, "parent_key": None, "is_leaf": True, "is_summary": False, "level_source": "code_prefix"},
        ]
        warnings = validate_parent_amounts(rows, hierarchy)
        assert len(warnings) == 0

    def test_small_difference_tolerated(self):
        """差异 ≤ 0.01 容忍"""
        from app.services.trial_balance_transform import TransformResult

        rows = [
            TransformResult(
                row_index=0, client_account_code="1001", client_account_name="库存现金",
                opening_debit=Decimal("30000.00"),
            ),
            TransformResult(
                row_index=1, client_account_code="1001001", client_account_name="人民币",
                opening_debit=Decimal("15000.00"),
            ),
            TransformResult(
                row_index=2, client_account_code="1001002", client_account_name="美元",
                opening_debit=Decimal("14999.99"),
            ),
        ]
        hierarchy = [
            {"row_index": 0, "level": 1, "parent_key": None, "is_leaf": False, "is_summary": True, "level_source": "code_prefix"},
            {"row_index": 1, "level": 2, "parent_key": "1001", "is_leaf": True, "is_summary": False, "level_source": "code_prefix"},
            {"row_index": 2, "level": 2, "parent_key": "1001", "is_leaf": True, "is_summary": False, "level_source": "code_prefix"},
        ]

        warnings = validate_parent_amounts(rows, hierarchy)
        assert len(warnings) == 0  # 差异 0.01，容忍


# ── 全流程集成测试 ──────────────────────────────────

class TestTransformRowsFullPipeline:
    """全流程：层级 + 金额 + 父级校验"""

    def test_full_pipeline_code_hierarchy(self):
        """完整流程：代码前缀层级 + 两列金额"""
        rows = [
            RowInput(
                row_index=0, client_account_code="1001", client_account_name="库存现金",
                standard_direction="debit",
                values={"op_dr": "30000", "op_cr": "0", "end_dr": "30000", "end_cr": "0"},
                amount_configs=[
                    AmountConfig("opening", "two_column", debit_field="op_dr", credit_field="op_cr"),
                    AmountConfig("ending", "two_column", debit_field="end_dr", credit_field="end_cr"),
                ],
            ),
            RowInput(
                row_index=1, client_account_code="1001001", client_account_name="人民币",
                standard_direction="debit",
                values={"op_dr": "10000", "op_cr": "0", "end_dr": "10000", "end_cr": "0"},
                amount_configs=[
                    AmountConfig("opening", "two_column", debit_field="op_dr", credit_field="op_cr"),
                    AmountConfig("ending", "two_column", debit_field="end_dr", credit_field="end_cr"),
                ],
            ),
            RowInput(
                row_index=2, client_account_code="1001002", client_account_name="美元",
                standard_direction="debit",
                values={"op_dr": "20000", "op_cr": "0", "end_dr": "20000", "end_cr": "0"},
                amount_configs=[
                    AmountConfig("opening", "two_column", debit_field="op_dr", credit_field="op_cr"),
                    AmountConfig("ending", "two_column", debit_field="end_dr", credit_field="end_cr"),
                ],
            ),
        ]

        result = transform_rows(rows, hierarchy_mode="code")

        # 层级正确
        assert result.rows[0].is_summary is True
        assert result.rows[0].is_leaf is False
        assert result.rows[0].level_source == "code_prefix"

        assert result.rows[1].is_leaf is True
        assert result.rows[1].parent_key == "1001"

        assert result.rows[2].is_leaf is True
        assert result.rows[2].parent_key == "1001"

        # 金额正确
        assert result.rows[0].opening_debit == Decimal("30000")
        assert result.rows[1].opening_debit == Decimal("10000")
        assert result.rows[2].opening_debit == Decimal("20000")

        # 父级金额一致，无 warning
        assert len(result.global_warnings) == 0

    def test_full_pipeline_indent_hierarchy(self):
        """完整流程：缩进层级 + 单列拆分"""
        rows = [
            RowInput(
                row_index=0, client_account_name="资产", indent_level=0,
                standard_direction="debit",
                values={"bal": "30000"},
                amount_configs=[
                    AmountConfig("ending", "single_by_direction", amount_field="bal"),
                ],
            ),
            RowInput(
                row_index=1, client_account_name="现金", indent_level=1,
                standard_direction="debit",
                values={"bal": "30000"},
                amount_configs=[
                    AmountConfig("ending", "single_by_direction", amount_field="bal"),
                ],
            ),
        ]

        result = transform_rows(rows, hierarchy_mode="indent")

        assert result.rows[0].is_summary is True
        assert result.rows[0].level == 1
        assert result.rows[0].level_source == "indent_suggested"
        assert result.rows[1].is_leaf is True
        assert result.rows[1].level == 2

    def test_full_pipeline_flat(self):
        """完整流程：平铺"""
        rows = [
            RowInput(
                row_index=0, client_account_name="项目A",
                standard_direction="debit",
                values={"dr": "1000", "cr": "0"},
                amount_configs=[
                    AmountConfig("ending", "two_column", debit_field="dr", credit_field="cr"),
                ],
            ),
            RowInput(
                row_index=1, client_account_name="项目B",
                standard_direction="debit",
                values={"dr": "2000", "cr": "0"},
                amount_configs=[
                    AmountConfig("ending", "two_column", debit_field="dr", credit_field="cr"),
                ],
            ),
        ]

        result = transform_rows(rows, hierarchy_mode="flat")
        for r in result.rows:
            assert r.level == 1
            assert r.is_leaf is True
            assert r.level_source == "flat"

    def test_full_pipeline_auto_with_code(self):
        """auto 模式：有代码优先代码"""
        rows = [
            RowInput(
                row_index=0, client_account_code="1001", client_account_name="库存现金",
                indent_level=0,
                values={"dr": "1000", "cr": "0"},
                amount_configs=[
                    AmountConfig("ending", "two_column", debit_field="dr", credit_field="cr"),
                ],
            ),
            RowInput(
                row_index=1, client_account_code="1001001", client_account_name="人民币",
                indent_level=1,
                values={"dr": "1000", "cr": "0"},
                amount_configs=[
                    AmountConfig("ending", "two_column", debit_field="dr", credit_field="cr"),
                ],
            ),
        ]

        result = transform_rows(rows, hierarchy_mode="auto")
        # 有代码，应使用代码前缀
        assert result.rows[0].level_source == "code_prefix"
        assert result.rows[1].level_source == "code_prefix"

    def test_full_pipeline_auto_without_code(self):
        """auto 模式：无代码有缩进 → 缩进建议"""
        rows = [
            RowInput(
                row_index=0, client_account_name="资产", indent_level=0,
                values={"dr": "3000", "cr": "0"},
                amount_configs=[
                    AmountConfig("ending", "two_column", debit_field="dr", credit_field="cr"),
                ],
            ),
            RowInput(
                row_index=1, client_account_name="现金", indent_level=1,
                values={"dr": "3000", "cr": "0"},
                amount_configs=[
                    AmountConfig("ending", "two_column", debit_field="dr", credit_field="cr"),
                ],
            ),
        ]

        result = transform_rows(rows, hierarchy_mode="auto")
        assert result.rows[0].level_source == "indent_suggested"
        assert result.rows[1].level_source == "indent_suggested"

    def test_full_pipeline_parent_child_warning(self):
        """全流程：父级金额不一致 → warning"""
        rows = [
            RowInput(
                row_index=0, client_account_code="1001", client_account_name="库存现金",
                standard_direction="debit",
                values={"op_dr": "35000", "op_cr": "0"},
                amount_configs=[
                    AmountConfig("opening", "two_column", debit_field="op_dr", credit_field="op_cr"),
                ],
            ),
            RowInput(
                row_index=1, client_account_code="1001001", client_account_name="人民币",
                standard_direction="debit",
                values={"op_dr": "10000", "op_cr": "0"},
                amount_configs=[
                    AmountConfig("opening", "two_column", debit_field="op_dr", credit_field="op_cr"),
                ],
            ),
            RowInput(
                row_index=2, client_account_code="1001002", client_account_name="美元",
                standard_direction="debit",
                values={"op_dr": "20000", "op_cr": "0"},
                amount_configs=[
                    AmountConfig("opening", "two_column", debit_field="op_dr", credit_field="op_cr"),
                ],
            ),
        ]

        result = transform_rows(rows, hierarchy_mode="code")
        # 父级 35000 vs 子级汇总 30000
        assert len(result.global_warnings) > 0
        assert any("不一致" in w for w in result.global_warnings)


# ── 便捷函数测试 ────────────────────────────────────

class TestHelperFunctions:
    """便捷辅助函数"""

    def test_get_leaf_rows(self):
        """提取末级行"""
        r1 = TransformResult(row_index=0, is_leaf=False, is_summary=True)
        r2 = TransformResult(row_index=1, is_leaf=True, is_summary=False)
        r3 = TransformResult(row_index=2, is_leaf=True, is_summary=False)

        batch = BatchTransformResult(rows=[r1, r2, r3])
        leaves = get_leaf_rows(batch)
        assert len(leaves) == 2
        assert leaves[0].row_index == 1
        assert leaves[1].row_index == 2

    def test_get_summary_rows(self):
        """提取汇总父级行"""
        r1 = TransformResult(row_index=0, is_summary=True)
        r2 = TransformResult(row_index=1, is_summary=False)
        r3 = TransformResult(row_index=2, is_summary=True)

        batch = BatchTransformResult(rows=[r1, r2, r3])
        summaries = get_summary_rows(batch)
        assert len(summaries) == 2
        assert summaries[0].row_index == 0
        assert summaries[1].row_index == 2

    def test_has_blocking_errors(self):
        """是否有阻止入库的错误"""
        batch_no_errors = BatchTransformResult(rows=[], global_errors=[])
        assert has_blocking_errors(batch_no_errors) is False

        batch_with_errors = BatchTransformResult(rows=[], global_errors=["方向缺失"])
        assert has_blocking_errors(batch_with_errors) is True


# ── AmountConfig 校验 ───────────────────────────────

class TestAmountConfig:
    """AmountConfig 数据校验"""

    def test_valid_two_column(self):
        cfg = AmountConfig("opening", "two_column", debit_field="dr", credit_field="cr")
        assert cfg.mode == "two_column"

    def test_valid_single_by_direction(self):
        cfg = AmountConfig("ending", "single_by_direction", amount_field="bal")
        assert cfg.mode == "single_by_direction"

    def test_valid_single_as_debit(self):
        cfg = AmountConfig("current", "single_as_debit", amount_field="amt")
        assert cfg.mode == "single_as_debit"

    def test_valid_single_as_credit(self):
        cfg = AmountConfig("current", "single_as_credit", amount_field="amt")
        assert cfg.mode == "single_as_credit"

    def test_invalid_mode(self):
        with pytest.raises(ValueError, match="不支持的模式"):
            AmountConfig("ending", "invalid_mode", amount_field="x")

    def test_two_column_missing_fields(self):
        with pytest.raises(ValueError, match="必须提供"):
            AmountConfig("ending", "two_column")

    def test_single_missing_amount_field(self):
        with pytest.raises(ValueError, match="必须提供 amount_field"):
            AmountConfig("ending", "single_by_direction")

    def test_two_column_should_not_have_amount_field(self):
        with pytest.raises(ValueError, match="不应提供 amount_field"):
            AmountConfig("ending", "two_column", debit_field="a", credit_field="b", amount_field="c")

    def test_single_should_not_have_debit_credit(self):
        with pytest.raises(ValueError, match="不应提供 debit_field"):
            AmountConfig("ending", "single_as_debit", amount_field="a", debit_field="b")


# ── _split_single_amount 直接测试 ────────────────────

class TestSplitSingleAmount:
    """底层拆分函数"""

    def test_debit_positive(self):
        d, c, w, e = _split_single_amount(Decimal("100"), "debit", "single_by_direction")
        assert d == Decimal("100")
        assert c == Decimal("0")
        assert len(w) == 0
        assert len(e) == 0

    def test_debit_negative(self):
        d, c, w, e = _split_single_amount(Decimal("-100"), "debit", "single_by_direction")
        assert d == Decimal("0")
        assert c == Decimal("100")
        assert len(w) == 1
        assert "负数" in w[0]

    def test_credit_positive(self):
        d, c, w, e = _split_single_amount(Decimal("200"), "credit", "single_by_direction")
        assert d == Decimal("0")
        assert c == Decimal("200")

    def test_credit_negative(self):
        d, c, w, e = _split_single_amount(Decimal("-200"), "credit", "single_by_direction")
        assert d == Decimal("200")
        assert c == Decimal("0")
        assert len(w) == 1

    def test_direction_none_error(self):
        d, c, w, e = _split_single_amount(Decimal("100"), None, "single_by_direction")
        assert d == Decimal("0")
        assert c == Decimal("0")
        assert len(e) == 1

    def test_as_debit_positive(self):
        d, c, w, e = _split_single_amount(Decimal("100"), None, "single_as_debit")
        assert d == Decimal("100")
        assert c == Decimal("0")

    def test_as_debit_negative(self):
        d, c, w, e = _split_single_amount(Decimal("-100"), None, "single_as_debit")
        assert d == Decimal("0")
        assert c == Decimal("100")
        assert len(w) == 1

    def test_as_credit_positive(self):
        d, c, w, e = _split_single_amount(Decimal("200"), None, "single_as_credit")
        assert d == Decimal("0")
        assert c == Decimal("200")

    def test_as_credit_negative(self):
        d, c, w, e = _split_single_amount(Decimal("-200"), None, "single_as_credit")
        assert d == Decimal("200")
        assert c == Decimal("0")
        assert len(w) == 1

    def test_zero_amount(self):
        d, c, w, e = _split_single_amount(Decimal("0"), "debit", "single_by_direction")
        assert d == Decimal("0")
        assert c == Decimal("0")
        assert len(w) == 0
