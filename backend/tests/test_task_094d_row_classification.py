"""TASK-094D：跳过行分类统一 — Analyze 与 Execute 共用入口单元测试。

覆盖任务文档第 10 节场景 1-6 + 10：
1. 零模板识别（所有金额字段均为 0/空）；
2. 非零合计行不识别为 zero（但识别为 summary_total）；
3. 小计行不生成 entry（即不进 eligible_business_leaf_rows）；
4. duplicate aggregate 不生成 entry；
5. 业务末级全部生成 entry（无遗漏、无污染）；
6. Analyze 与 Execute 分类一致（同一函数返回相同结果）；
10. API 计数字段一致（raw_identified_leaf_count / entry_count 等）。

``classify_import_rows`` 是纯函数（无副作用、无 DB 依赖），所有测试
直接传 ``rows / period_configs / col_id_to_index / hierarchy`` 即可。
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.standard_trial_balance_import_service import (
    RowClassificationResult,
    classify_import_rows,
)


# ── 工具 ───────────────────────────────────────────────


def _amount_cfg(
    *,
    code_col_id: str = "code",
    name_col_id: str = "name",
    debit_col_id: str = "opening_debit",
    credit_col_id: str = "opening_credit",
) -> tuple[list[dict], dict[str, int]]:
    """构造最小化的 period_configs + col_id_to_index。"""
    period_configs = [
        {
            "mode": "two_column",
            "debit_field": debit_col_id,
            "credit_field": credit_col_id,
        }
    ]
    col_id_to_index = {
        code_col_id: 0,
        name_col_id: 1,
        debit_col_id: 2,
        credit_col_id: 3,
    }
    return period_configs, col_id_to_index


def _leaf(ri: int, *, parent_key=None) -> dict:
    """构造 leaf 行 hierarchy dict。"""
    return {
        "row_index": ri,
        "is_leaf": True,
        "is_summary": False,
        "parent_key": parent_key,
        "parent_row_index": None,
    }


def _parent(ri: int, *, parent_key=None) -> dict:
    """构造父级（is_summary=True）hierarchy dict。"""
    return {
        "row_index": ri,
        "is_leaf": False,
        "is_summary": True,
        "parent_key": parent_key,
        "parent_row_index": None,
    }


# ── 场景 1：零模板识别 ─────────────────────────────────


def test_zero_amount_template_all_zero_recognized():
    """所有金额字段为 0/空的行 → zero_amount_template_rows。"""
    rows = [
        ["1001", "库存现金", 0, 0],     # leaf, 全零
        ["1002", "银行存款", "", ""],   # leaf, 全空
        ["", "", None, None],          # leaf, 无 code/name → 不入 base
    ]
    period_configs, col_id_to_index = _amount_cfg()
    hierarchy = [_leaf(0), _leaf(1)]  # row 2 无 code/name，被剔除

    result = classify_import_rows(
        rows=rows,
        period_configs=period_configs,
        col_id_to_index=col_id_to_index,
        code_col_id="code",
        name_col_id="name",
        hierarchy=hierarchy,
    )

    assert result.zero_amount_template_rows == {0, 1}
    assert result.eligible_business_leaf_rows == set()
    assert result.raw_identified_leaf_count == 2


# ── 场景 2：非零合计行不识别为 zero ─────────────────────


def test_nonzero_summary_total_not_zero():
    """金额非零的合计行 → summary_total_rows（不是 zero）。

    注意：父级（is_summary=True）命中 summary 关键词时进 structural_rows，
    不进 ``summary_total_rows`` 字段（该字段保留给 leaf 命中）。
    """
    rows = [
        ["1001", "库存现金", 100, 0],
        ["1001", "合计", 100, 0],       # 名称含「合计」，金额非零
    ]
    period_configs, col_id_to_index = _amount_cfg()
    # row 0 = leaf；row 1 = 父级（按 hierarchy 识别）
    hierarchy = [_leaf(0), _parent(1)]

    result = classify_import_rows(
        rows=rows,
        period_configs=period_configs,
        col_id_to_index=col_id_to_index,
        code_col_id="code",
        name_col_id="name",
        hierarchy=hierarchy,
    )

    # 强制红线：非零合计不能称为 zero skip
    assert 1 not in result.zero_amount_template_rows
    # 父级命中 summary 关键词 → 进 structural_rows
    assert 1 in result.structural_rows
    assert result.zero_amount_template_rows == set()


def test_nonzero_summary_total_leaf_in_summary_total_rows():
    """金额非零且是 leaf 的「合计」行 → summary_total_rows（不是 zero）。"""
    rows = [
        ["1001", "库存现金", 100, 0],     # leaf → eligible
        ["", "合计", 100, 0],             # leaf + 名称含「合计」 → summary_total
    ]
    period_configs, col_id_to_index = _amount_cfg()
    hierarchy = [_leaf(0), _leaf(1)]

    result = classify_import_rows(
        rows=rows,
        period_configs=period_configs,
        col_id_to_index=col_id_to_index,
        code_col_id="code",
        name_col_id="name",
        hierarchy=hierarchy,
    )

    # 强制红线：非零合计不能称为 zero skip
    assert 1 not in result.zero_amount_template_rows
    assert 1 in result.summary_total_rows
    assert 0 in result.eligible_business_leaf_rows


# ── 场景 3：小计行不生成 entry ─────────────────────────


def test_summary_total_leaf_not_eligible():
    """名称含「小计」的 leaf 行 → summary_total_rows，不入 eligible。"""
    rows = [
        ["1001", "库存现金", 50, 0],
        ["1002", "小计", 50, 0],
        ["1003", "银行存款", 200, 0],
    ]
    period_configs, col_id_to_index = _amount_cfg()
    hierarchy = [_leaf(0), _leaf(1), _leaf(2)]

    result = classify_import_rows(
        rows=rows,
        period_configs=period_configs,
        col_id_to_index=col_id_to_index,
        code_col_id="code",
        name_col_id="name",
        hierarchy=hierarchy,
    )

    assert 1 in result.summary_total_rows
    assert 1 not in result.eligible_business_leaf_rows
    assert result.eligible_business_leaf_rows == {0, 2}
    assert result.entry_count == 2


# ── 场景 4：duplicate aggregate 不生成 entry ──────────


def test_duplicate_aggregate_parent_not_leaf():
    """重复汇总（父级且金额 ≈ 子级）不进 eligible（只标记 duplicate_aggregate）。"""
    # row 0 = 父级，金额与两个子级合计一致
    # row 1, 2 = 子级 leaf
    rows = [
        ["1001", "应收账款", 300, 0],   # 父级
        ["100101", "应收A", 100, 0],   # leaf
        ["100102", "应收B", 200, 0],   # leaf
    ]
    period_configs, col_id_to_index = _amount_cfg()
    hierarchy = [
        _parent(0),
        {**_leaf(1), "parent_key": 0},
        {**_leaf(2), "parent_key": 0},
    ]

    result = classify_import_rows(
        rows=rows,
        period_configs=period_configs,
        col_id_to_index=col_id_to_index,
        code_col_id="code",
        name_col_id="name",
        hierarchy=hierarchy,
    )

    # duplicate_aggregate 是父级，不进 leaf 五类分配，但 structural_rows 包含
    assert 0 in result.structural_rows
    # 子级正常入 eligible
    assert result.eligible_business_leaf_rows == {1, 2}
    assert result.entry_count == 2


# ── 场景 5：业务末级全部生成 entry ─────────────────────


def test_all_business_leaves_eligible():
    """全部 leaf 都是业务末级（无关键词、无零、无重复）→ 全入 eligible。"""
    rows = [
        ["1001", "库存现金", 100, 0],
        ["1002", "银行存款", 200, 50],
        ["1122", "应收账款", 0, 300],
    ]
    period_configs, col_id_to_index = _amount_cfg()
    hierarchy = [_leaf(0), _leaf(1), _leaf(2)]

    result = classify_import_rows(
        rows=rows,
        period_configs=period_configs,
        col_id_to_index=col_id_to_index,
        code_col_id="code",
        name_col_id="name",
        hierarchy=hierarchy,
    )

    assert result.eligible_business_leaf_rows == {0, 1, 2}
    assert result.entry_count == 3
    assert result.zero_amount_template_rows == set()
    assert result.summary_total_rows == set()
    assert result.duplicate_aggregate_rows == set()


# ── 场景 6：Analyze 与 Execute 分类一致 ─────────────────


def test_classification_deterministic_for_same_input():
    """同一输入两次调用结果一致（幂等性 + Analyze/Execute 共享入口基础）。

    注意：页脚关键词（_FOOTER_KEYWORDS）仅在 code 列检测；配置关键词
    （_CONFIG_NAME_KEYWORDS）在 name 列检测 — 这是与旧
    ``_collect_summary_total_skip_rows`` 一致的产品语义。
    """
    rows = [
        ["1001", "库存现金", 100, 0],
        ["1001", "合计", 100, 0],
        ["核算单位", "公司名", "", ""],   # footer keyword 在 code 列
        ["1002", "不过帐设置用", 0, 0],   # config keyword 在 name 列
        ["1003", "银行存款", 50, 0],
    ]
    period_configs, col_id_to_index = _amount_cfg()
    hierarchy = [_leaf(0), _parent(1), _leaf(2), _leaf(3), _leaf(4)]

    r1 = classify_import_rows(
        rows=rows,
        period_configs=period_configs,
        col_id_to_index=col_id_to_index,
        code_col_id="code",
        name_col_id="name",
        hierarchy=hierarchy,
    )
    r2 = classify_import_rows(
        rows=rows,
        period_configs=period_configs,
        col_id_to_index=col_id_to_index,
        code_col_id="code",
        name_col_id="name",
        hierarchy=hierarchy,
    )

    assert r1.eligible_business_leaf_rows == r2.eligible_business_leaf_rows
    assert r1.summary_total_rows == r2.summary_total_rows
    assert r1.zero_amount_template_rows == r2.zero_amount_template_rows
    assert r1.duplicate_aggregate_rows == r2.duplicate_aggregate_rows
    assert r1.ignored_business_rows == r2.ignored_business_rows
    # 含页脚/配置关键词的行进 summary_total（与旧 _collect_summary_total_skip_rows 一致）
    assert 2 in r1.summary_total_rows  # 核算单位（code 列）
    assert 3 in r1.summary_total_rows  # 不过帐设置用（name 列）
    assert r1.eligible_business_leaf_rows == {0, 4}


def test_user_ignored_only_changes_ignored_bucket():
    """user_ignored_rows 只影响 ignored_business_rows，不影响其他分类。"""
    rows = [
        ["1001", "库存现金", 100, 0],
        ["1002", "银行存款", 200, 0],
    ]
    period_configs, col_id_to_index = _amount_cfg()
    hierarchy = [_leaf(0), _leaf(1)]

    no_ignored = classify_import_rows(
        rows=rows,
        period_configs=period_configs,
        col_id_to_index=col_id_to_index,
        code_col_id="code",
        name_col_id="name",
        hierarchy=hierarchy,
        user_ignored_rows=set(),
    )
    with_ignored = classify_import_rows(
        rows=rows,
        period_configs=period_configs,
        col_id_to_index=col_id_to_index,
        code_col_id="code",
        name_col_id="name",
        hierarchy=hierarchy,
        user_ignored_rows={1},
    )

    assert no_ignored.eligible_business_leaf_rows == {0, 1}
    assert with_ignored.eligible_business_leaf_rows == {0}
    assert with_ignored.ignored_business_rows == {1}
    # 五类集合计数仍守恒
    assert with_ignored.raw_identified_leaf_count == 2
    assert with_ignored.entry_count == 1


# ── 场景 10：API 计数字段一致 ─────────────────────────


def test_count_identity_holds():
    """raw_identified_leaf_count == eligible + zero + summary + duplicate + ignored。"""
    rows = [
        ["1001", "库存现金", 100, 0],         # leaf → eligible
        ["1002", "银行存款", 0, 0],           # leaf → zero_template
        ["1003", "合计", 50, 0],              # leaf → summary_total
        ["1004", "应收账款", 200, 0],         # leaf → eligible
        ["", "不过帐设置用", "", ""],          # leaf → summary_total (config kw)
    ]
    period_configs, col_id_to_index = _amount_cfg()
    hierarchy = [_leaf(0), _leaf(1), _leaf(2), _leaf(3), _leaf(4)]

    result = classify_import_rows(
        rows=rows,
        period_configs=period_configs,
        col_id_to_index=col_id_to_index,
        code_col_id="code",
        name_col_id="name",
        hierarchy=hierarchy,
        user_ignored_rows={3},
    )

    # 计数恒等式
    assert result.raw_identified_leaf_count == (
        len(result.eligible_business_leaf_rows)
        + len(result.zero_amount_template_rows)
        + len(result.summary_total_rows)
        + len(result.duplicate_aggregate_rows)
        + len(result.ignored_business_rows)
    )
    # entry_count == eligible
    assert result.entry_count == len(result.eligible_business_leaf_rows)
    # raw == base_leaf_rows size（base 范围 == 五类并集）
    assert result.raw_identified_leaf_count == len(result.base_leaf_rows)


def test_priority_assignment_is_strict():
    """priority: ignored > summary_total > zero > duplicate > eligible（互斥）。"""
    # 构造一行同时命中多个条件（按设计 ignored 优先级最高）
    rows = [
        ["1001", "合计", 0, 0],   # 既含关键词、又是全零，又被忽略
    ]
    period_configs, col_id_to_index = _amount_cfg()
    hierarchy = [_leaf(0)]

    result = classify_import_rows(
        rows=rows,
        period_configs=period_configs,
        col_id_to_index=col_id_to_index,
        code_col_id="code",
        name_col_id="name",
        hierarchy=hierarchy,
        user_ignored_rows={0},
    )

    # ignored 优先级最高
    assert 0 in result.ignored_business_rows
    assert 0 not in result.summary_total_rows
    assert 0 not in result.zero_amount_template_rows
    assert 0 not in result.eligible_business_leaf_rows
    assert 0 not in result.duplicate_aggregate_rows
    # 不在 summary_leaf 但仍可能因关键词被检测到 summary_total_rows（整体集合）
    # 但 priority 分配让它进 ignored 而非 summary_leaf


def test_summary_total_aggregate_for_complex_fixture():
    """更复杂的真实形态：混合业务末级 + 合计 + 子级小计。

    注意：页脚关键词仅在 code 列检测；所以 row 5 把「制单人」放 code 列才能进 summary。
    """
    rows = [
        ["1001", "库存现金", 100, 0],         # row 0 leaf → eligible
        ["1002", "银行存款", 200, 50],        # row 1 leaf → eligible
        ["1003", "应收账款", 300, 100],       # row 2 leaf → eligible
        ["", "（资产）小计", 600, 150],        # row 3 leaf → summary_total
        ["", "总计", 600, 150],                # row 4 leaf → summary_total
        ["制单人", "", "", ""],                # row 5 leaf → summary_total (footer in code)
    ]
    period_configs, col_id_to_index = _amount_cfg()
    hierarchy = [_leaf(i) for i in range(6)]

    result = classify_import_rows(
        rows=rows,
        period_configs=period_configs,
        col_id_to_index=col_id_to_index,
        code_col_id="code",
        name_col_id="name",
        hierarchy=hierarchy,
    )

    assert result.eligible_business_leaf_rows == {0, 1, 2}
    assert result.summary_total_rows == {3, 4, 5}
    assert result.zero_amount_template_rows == set()
    assert result.entry_count == 3
    # raw == 6（6 行都有 code 或 name）
    assert result.raw_identified_leaf_count == 6