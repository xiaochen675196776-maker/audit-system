"""TASK-094D：汇总 / 重复 父子金额勾稽单元测试。

覆盖任务文档第 10 节场景 8：
8. 汇总金额勾稽（summary / duplicate aggregate 父级金额 ≈ 子级金额合计，
   允许 0.01 误差，否则 warning=summary_amount_mismatch）。

``summarize_summary_reconciliation`` 是纯函数，对 hierarchy 中所有
summary / duplicate 行做父子金额对比。
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.standard_trial_balance_import_service import (
    summarize_summary_reconciliation,
)


# ── 工具 ───────────────────────────────────────────────


FIELDS = ["opening_debit", "opening_credit", "current_debit"]


def _row_amounts(field_values: dict[str, Decimal | int | float | str]) -> dict[str, Decimal]:
    return {k: Decimal(str(v)) for k, v in field_values.items()}


# ── 场景 8：汇总金额勾稽 ──────────────────────────────


def test_summary_reconciliation_balanced_exact():
    """父级金额 == 子级合计 → mismatch_count=0, warning=None。"""
    # row 0 = 父级，row 1/2 = 子级 leaf
    row_amount_lookups = {
        0: _row_amounts({"opening_debit": 150, "opening_credit": 30, "current_debit": 80}),
        1: _row_amounts({"opening_debit": 100, "opening_credit": 10, "current_debit": 50}),
        2: _row_amounts({"opening_debit": 50, "opening_credit": 20, "current_debit": 30}),
    }
    children_by_row = {0: [1, 2]}
    hierarchy_summary_rows = {0}
    summary_total_rows = set()
    duplicate_aggregate_rows = set()

    out = summarize_summary_reconciliation(
        summary_total_rows=summary_total_rows,
        duplicate_aggregate_rows=duplicate_aggregate_rows,
        hierarchy_summary_rows=hierarchy_summary_rows,
        children_by_row=children_by_row,
        row_amount_lookups=row_amount_lookups,
        fields=FIELDS,
    )

    assert "0" in out
    rec = out["0"]
    assert rec["mismatch_count"] == 0
    assert rec["warning"] is None
    for f in FIELDS:
        per_field = rec["fields"][f]
        assert per_field["ok"] == "true"
        assert Decimal(per_field["difference"]) == Decimal("0")


def test_summary_reconciliation_within_tolerance():
    """父子差异 0.005 → 仍 ok（< 0.01 容差）。"""
    row_amount_lookups = {
        0: _row_amounts({"opening_debit": 100.005}),  # 子级 100，差异 0.005
        1: _row_amounts({"opening_debit": 100}),
    }
    children_by_row = {0: [1]}

    out = summarize_summary_reconciliation(
        summary_total_rows=set(),
        duplicate_aggregate_rows=set(),
        hierarchy_summary_rows={0},
        children_by_row=children_by_row,
        row_amount_lookups=row_amount_lookups,
        fields=["opening_debit"],
    )

    rec = out["0"]
    assert rec["mismatch_count"] == 0
    assert rec["warning"] is None
    assert rec["fields"]["opening_debit"]["ok"] == "true"


def test_summary_reconciliation_mismatch_triggers_warning():
    """父子差异 > 容差 → warning=summary_amount_mismatch。"""
    row_amount_lookups = {
        0: _row_amounts({"opening_debit": 200, "opening_credit": 50}),  # 父级
        1: _row_amounts({"opening_debit": 100, "opening_credit": 30}),  # 子级
    }
    children_by_row = {0: [1]}

    out = summarize_summary_reconciliation(
        summary_total_rows=set(),
        duplicate_aggregate_rows=set(),
        hierarchy_summary_rows={0},
        children_by_row=children_by_row,
        row_amount_lookups=row_amount_lookups,
        fields=["opening_debit", "opening_credit"],
    )

    rec = out["0"]
    # opening_debit: 200 vs 100，差异 100 → mismatch
    # opening_credit: 50 vs 30，差异 20 → mismatch
    assert rec["mismatch_count"] == 2
    assert rec["warning"] == "summary_amount_mismatch"
    assert rec["fields"]["opening_debit"]["ok"] == "false"
    assert rec["fields"]["opening_credit"]["ok"] == "false"


def test_summary_reconciliation_mismatch_ignored_when_zero():
    """父子双方都 ≈ 0 → 即使差值略大也不计 mismatch（avoid 浮点误报）。"""
    row_amount_lookups = {
        0: _row_amounts({"opening_debit": 0.005}),  # 父级极小值
        1: _row_amounts({"opening_debit": 0}),       # 子级 0
    }
    children_by_row = {0: [1]}

    out = summarize_summary_reconciliation(
        summary_total_rows=set(),
        duplicate_aggregate_rows=set(),
        hierarchy_summary_rows={0},
        children_by_row=children_by_row,
        row_amount_lookups=row_amount_lookups,
        fields=["opening_debit"],
    )

    rec = out["0"]
    # 双方都 ≈ 0，不计 mismatch
    assert rec["mismatch_count"] == 0
    assert rec["warning"] is None


def test_summary_reconciliation_includes_summary_total_rows():
    """summary_total_rows（关键词行）也进入勾稽范围。"""
    # row 0 = 父级（hierarchy_summary）
    # row 1 = 含「合计」关键词的 leaf（summary_total）
    row_amount_lookups = {
        0: _row_amounts({"opening_debit": 300}),
        1: _row_amounts({"opening_debit": 300}),
        2: _row_amounts({"opening_debit": 100}),
        3: _row_amounts({"opening_debit": 200}),
    }
    children_by_row = {
        0: [1],       # 父级直接子级是「合计」行
        1: [2, 3],    # 「合计」行下挂两个 leaf
    }

    out = summarize_summary_reconciliation(
        summary_total_rows={1},
        duplicate_aggregate_rows=set(),
        hierarchy_summary_rows={0},
        children_by_row=children_by_row,
        row_amount_lookups=row_amount_lookups,
        fields=["opening_debit"],
    )

    # row 0 = 父级，子级只有 row 1（合计 300）→ ok
    # row 1 = 合计行，子级 [2, 3] 合计 300 → ok
    assert "0" in out and "1" in out
    assert out["0"]["warning"] is None
    assert out["1"]["warning"] is None
    assert out["0"]["mismatch_count"] == 0
    assert out["1"]["mismatch_count"] == 0


def test_summary_reconciliation_duplicate_aggregate_covered():
    """duplicate_aggregate_rows 也进入勾稽范围（与 summary_total 一致）。"""
    row_amount_lookups = {
        5: _row_amounts({"opening_debit": 80}),   # duplicate 行
        6: _row_amounts({"opening_debit": 50}),
        7: _row_amounts({"opening_debit": 30}),
    }
    children_by_row = {5: [6, 7]}

    out = summarize_summary_reconciliation(
        summary_total_rows=set(),
        duplicate_aggregate_rows={5},
        hierarchy_summary_rows=set(),
        children_by_row=children_by_row,
        row_amount_lookups=row_amount_lookups,
        fields=["opening_debit"],
    )

    rec = out["5"]
    assert rec["mismatch_count"] == 0
    assert rec["warning"] is None
    assert rec["fields"]["opening_debit"]["ok"] == "true"


def test_summary_reconciliation_empty_inputs_returns_empty_dict():
    """无 hierarchy / 无 children → 返回空 dict。"""
    out = summarize_summary_reconciliation(
        summary_total_rows=set(),
        duplicate_aggregate_rows=set(),
        hierarchy_summary_rows=set(),
        children_by_row={},
        row_amount_lookups={},
        fields=FIELDS,
    )
    assert out == {}


def test_summary_reconciliation_skips_parent_without_children():
    """无 children 的父级行不进入勾稽结果（避免空记录噪声）。"""
    row_amount_lookups = {
        0: _row_amounts({"opening_debit": 100}),
    }
    out = summarize_summary_reconciliation(
        summary_total_rows=set(),
        duplicate_aggregate_rows=set(),
        hierarchy_summary_rows={0},
        children_by_row={},  # row 0 没有子级
        row_amount_lookups=row_amount_lookups,
        fields=["opening_debit"],
    )
    assert out == {}