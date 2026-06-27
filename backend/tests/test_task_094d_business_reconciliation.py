"""TASK-094D：业务金额勾稽单元测试。

覆盖任务文档第 10 节场景 7 + 9：
7. 业务金额勾稽（eligible + ignored == entry）；
9. 汇总不计入业务来源金额（summary/duplicate 不出现在 eligible 中）。

``summarize_amount_reconciliation`` 是纯函数，直接构造输入验证
各字段 (source / entry / eligible / ignored / difference / ok)。
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.standard_trial_balance_import_service import (
    summarize_amount_reconciliation,
)


# ── 工具 ───────────────────────────────────────────────


FIELDS = ["opening_debit", "opening_credit", "current_debit"]


def _row_amounts(field_values: dict[str, Decimal | int | float | str]) -> dict[str, Decimal]:
    return {k: Decimal(str(v)) for k, v in field_values.items()}


# ── 场景 7：业务金额勾稽 ──────────────────────────────


def test_reconciliation_balanced_when_entry_matches_eligible():
    """entry 完全等于 eligible → difference = 0，ok = true。"""
    eligible = {0, 1, 2}
    ignored = set()
    row_amount_lookups = {
        0: _row_amounts({"opening_debit": 100, "opening_credit": 0, "current_debit": 50}),
        1: _row_amounts({"opening_debit": 200, "opening_credit": 50, "current_debit": 30}),
        2: _row_amounts({"opening_debit": 0, "opening_credit": 300, "current_debit": 80}),
    }
    # entry_amount_totals 必须等于 eligible 总额（entry 仅来自 eligible）
    entry_amount_totals = {
        "opening_debit": Decimal("300"),    # 100 + 200 + 0
        "opening_credit": Decimal("350"),   # 0 + 50 + 300
        "current_debit": Decimal("160"),    # 50 + 30 + 80
    }

    out = summarize_amount_reconciliation(
        eligible_business_leaf_rows=eligible,
        ignored_business_rows=ignored,
        entry_amount_totals=entry_amount_totals,
        row_amount_lookups=row_amount_lookups,
        fields=FIELDS,
    )

    for f in FIELDS:
        rec = out[f]
        assert rec["ok"] == "true", f"{f} not balanced: {rec}"
        assert Decimal(rec["difference"]) == Decimal("0")
        assert Decimal(rec["eligible"]) == entry_amount_totals[f]
        assert Decimal(rec["ignored"]) == Decimal("0")


def test_reconciliation_balanced_with_ignored_bucket():
    """eligible + ignored == entry_amount 时也 balanced。"""
    eligible = {0, 1}
    ignored = {2}
    row_amount_lookups = {
        0: _row_amounts({"opening_debit": 100}),
        1: _row_amounts({"opening_debit": 50}),
        2: _row_amounts({"opening_debit": 30}),
    }
    # entry 仅来自 eligible（ignored 行不生成 entry）
    entry_amount_totals = {"opening_debit": Decimal("150")}

    out = summarize_amount_reconciliation(
        eligible_business_leaf_rows=eligible,
        ignored_business_rows=ignored,
        entry_amount_totals=entry_amount_totals,
        row_amount_lookups=row_amount_lookups,
        fields=["opening_debit"],
    )

    rec = out["opening_debit"]
    assert rec["ok"] == "true"
    assert Decimal(rec["source"]) == Decimal("180")     # 100+50+30
    assert Decimal(rec["entry"]) == Decimal("150")
    assert Decimal(rec["eligible"]) == Decimal("150")
    assert Decimal(rec["ignored"]) == Decimal("30")
    assert Decimal(rec["difference"]) == Decimal("0")   # source - entry - ignored = 180-150-30=0


def test_reconciliation_detects_entry_leak():
    """如果 entry 总额 != eligible 总额（漏算或多算） → difference != 0。"""
    eligible = {0, 1}
    ignored = set()
    row_amount_lookups = {
        0: _row_amounts({"opening_debit": 100}),
        1: _row_amounts({"opening_debit": 50}),
    }
    # 故意让 entry 比 eligible 少 50（漏算 row 1）
    entry_amount_totals = {"opening_debit": Decimal("100")}

    out = summarize_amount_reconciliation(
        eligible_business_leaf_rows=eligible,
        ignored_business_rows=ignored,
        entry_amount_totals=entry_amount_totals,
        row_amount_lookups=row_amount_lookups,
        fields=["opening_debit"],
    )

    rec = out["opening_debit"]
    assert rec["ok"] == "false"
    assert Decimal(rec["difference"]) == Decimal("50")  # source(150) - entry(100) - ignored(0)


def test_reconciliation_within_tolerance():
    """0.01 内的差异仍判定 ok（与 _AMOUNT_RECON_TOLERANCE 一致）。"""
    eligible = {0}
    ignored = set()
    row_amount_lookups = {
        0: _row_amounts({"opening_debit": 100}),
    }
    # entry 与 eligible 差 0.005（< 0.01 容差）
    entry_amount_totals = {"opening_debit": Decimal("99.995")}

    out = summarize_amount_reconciliation(
        eligible_business_leaf_rows=eligible,
        ignored_business_rows=ignored,
        entry_amount_totals=entry_amount_totals,
        row_amount_lookups=row_amount_lookups,
        fields=["opening_debit"],
    )

    rec = out["opening_debit"]
    assert rec["ok"] == "true"
    assert abs(Decimal(rec["difference"])) <= Decimal("0.01")


# ── 场景 9：汇总不计入业务来源金额 ──────────────────────


def test_summary_rows_excluded_from_business_reconciliation():
    """汇总 / 重复 行即使有金额，也不进 business reconciliation 的 source。"""
    # row 0/1 是业务末级；row 2/3 是汇总行（不应进 source）
    eligible = {0, 1}
    ignored = set()
    row_amount_lookups = {
        0: _row_amounts({"opening_debit": 100}),
        1: _row_amounts({"opening_debit": 50}),
        2: _row_amounts({"opening_debit": 150}),  # 汇总行
        3: _row_amounts({"opening_debit": 150}),  # 重复汇总行
    }
    entry_amount_totals = {"opening_debit": Decimal("150")}

    out = summarize_amount_reconciliation(
        eligible_business_leaf_rows=eligible,
        ignored_business_rows=ignored,
        entry_amount_totals=entry_amount_totals,
        row_amount_lookups=row_amount_lookups,
        fields=["opening_debit"],
    )

    rec = out["opening_debit"]
    # source = eligible + ignored = 100 + 50 = 150（不含汇总行的 150）
    assert Decimal(rec["source"]) == Decimal("150")
    assert Decimal(rec["eligible"]) == Decimal("150")
    assert Decimal(rec["ignored"]) == Decimal("0")
    assert Decimal(rec["entry"]) == Decimal("150")
    assert Decimal(rec["difference"]) == Decimal("0")
    assert rec["ok"] == "true"


def test_reconciliation_empty_eligible_produces_zero():
    """空 eligible → 全零。"""
    out = summarize_amount_reconciliation(
        eligible_business_leaf_rows=set(),
        ignored_business_rows=set(),
        entry_amount_totals={"opening_debit": Decimal("0")},
        row_amount_lookups={},
        fields=["opening_debit"],
    )

    rec = out["opening_debit"]
    assert Decimal(rec["source"]) == Decimal("0")
    assert Decimal(rec["entry"]) == Decimal("0")
    assert Decimal(rec["eligible"]) == Decimal("0")
    assert Decimal(rec["ignored"]) == Decimal("0")
    assert Decimal(rec["difference"]) == Decimal("0")
    assert rec["ok"] == "true"


def test_reconciliation_multiple_fields_independent():
    """多字段独立计算（每个字段有自己的 source/entry/eligible/ignored）。"""
    eligible = {0}
    ignored = {1}
    row_amount_lookups = {
        0: _row_amounts({
            "opening_debit": 100, "opening_credit": 50,
            "current_debit": 30, "current_credit": 0,
        }),
        1: _row_amounts({
            "opening_debit": 10, "opening_credit": 5,
            "current_debit": 3, "current_credit": 1,
        }),
    }
    entry_amount_totals = {
        "opening_debit": Decimal("100"),
        "opening_credit": Decimal("50"),
        "current_debit": Decimal("30"),
        "current_credit": Decimal("0"),
    }

    out = summarize_amount_reconciliation(
        eligible_business_leaf_rows=eligible,
        ignored_business_rows=ignored,
        entry_amount_totals=entry_amount_totals,
        row_amount_lookups=row_amount_lookups,
        fields=["opening_debit", "opening_credit", "current_debit", "current_credit"],
    )

    # 每字段都 balanced
    for f in ("opening_debit", "opening_credit", "current_debit", "current_credit"):
        rec = out[f]
        assert rec["ok"] == "true", f"{f} not ok: {rec}"
        assert Decimal(rec["difference"]) == Decimal("0")
    # 验证 ignored 字段值
    assert Decimal(out["opening_debit"]["ignored"]) == Decimal("10")
    assert Decimal(out["current_credit"]["ignored"]) == Decimal("1")