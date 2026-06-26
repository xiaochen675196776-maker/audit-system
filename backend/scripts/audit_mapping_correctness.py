"""TASK-089：科目余额表匹配真实数据回归 — 验收缺陷修复后的回归脚本。

对 6 张真实文件执行 preview → analyze（不跑 execute），逐表输出：
  - 候选分布统计（自动确认/人工确认/conflict/unknown/ambiguous）
  - 重大错配自动检测（成本→权益、资产→负债、原值→备抵等 7 类）
  - 专项科目明细（4101/4105/4107/研发支出/包装物/坏账准备/累计折旧等）
  - 性能计时（每表耗时、每千科目耗时）

统计口径（TASK-089）：
  - 唯一统计对象：以 (client_account_code, client_account_name, client_account_full_path)
    三元组去重的有效客户科目数。
  - 自动确认 / 人工确认 / 多目标歧义 = 有效科目数 (强制勾稽)
  - 红线（warning_auto / fuzzy_auto / disabled_auto / multi_safe_auto /
    empty_id_auto / conflict_auto / unknown_auto）必须全部为 0。
  - 唯一安全候选判定使用 pick_unique_auto_confirm_candidate，
    禁止再调用已废弃的回退首候选 _pick_auto_confirm_candidate。

生成：
  - backend/test_reports/task_089_mapping_regression.json
  - backend/test_reports/task_089_mapping_regression.csv
  - backend/test_reports/task_089_mapping_regression.md
"""
import sys
import os
import asyncio
import tempfile
import uuid
import json
import csv
import time
from pathlib import Path


def _print(msg: str) -> None:
    print(msg, flush=True)


sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.core.database import Base
from app.models.standard_account import StandardAccount
from app.services.standard_account_service import seed_standard_accounts
from app.services.standard_trial_balance_import_service import (
    preview_standard_import,
    analyze_standard_import,
)
from app.services.client_account_mapping_service import (
    _is_safe_candidate,
    pick_unique_auto_confirm_candidate,
    _normalize_name,
    _GENERIC_LEAF_NAMES,
)

# ── 文件配置 ──
REAL_FILES = [
    {
        "path": "D:/APP/谷歌/文件下载/会展中心余额表.xlsx",
        "customer_label": "会展中心",
        "field_mappings": [
            {"column_id": "col_0", "field_name": "account_code"},
            {"column_id": "col_1", "field_name": "account_name"},
            {"column_id": "col_3", "field_name": "opening_amount", "period_type": "opening",
             "split_mode": "single_by_source_direction", "direction_column_id": "col_2"},
            {"column_id": "col_4", "field_name": "current_debit", "period_type": "current",
             "split_mode": "two_column", "debit_column_id": "col_4", "credit_column_id": "col_5"},
            {"column_id": "col_5", "field_name": "current_credit", "period_type": "current",
             "split_mode": "two_column", "debit_column_id": "col_4", "credit_column_id": "col_5"},
            {"column_id": "col_7", "field_name": "ending_amount", "period_type": "ending",
             "split_mode": "single_by_source_direction", "direction_column_id": "col_6"},
        ],
    },
    {
        "path": "D:/APP/谷歌/文件下载/1-12科目余额表.xls",
        "customer_label": "1-12科目余额表客户",
        "field_mappings": [
            {"column_id": "col_0", "field_name": "account_code"},
            {"column_id": "col_1", "field_name": "account_name"},
            {"column_id": "col_3", "field_name": "opening_debit", "period_type": "opening",
             "split_mode": "two_column", "debit_column_id": "col_3", "credit_column_id": "col_4"},
            {"column_id": "col_4", "field_name": "opening_credit", "period_type": "opening",
             "split_mode": "two_column", "debit_column_id": "col_3", "credit_column_id": "col_4"},
            {"column_id": "col_5", "field_name": "current_debit", "period_type": "current",
             "split_mode": "two_column", "debit_column_id": "col_5", "credit_column_id": "col_6"},
            {"column_id": "col_6", "field_name": "current_credit", "period_type": "current",
             "split_mode": "two_column", "debit_column_id": "col_5", "credit_column_id": "col_6"},
            {"column_id": "col_9", "field_name": "ending_debit", "period_type": "ending",
             "split_mode": "two_column", "debit_column_id": "col_9", "credit_column_id": "col_10"},
            {"column_id": "col_10", "field_name": "ending_credit", "period_type": "ending",
             "split_mode": "two_column", "debit_column_id": "col_9", "credit_column_id": "col_10"},
        ],
    },
    {
        "path": "D:/APP/谷歌/文件下载/205201-2023.xls",
        "customer_label": "205201客户",
        "field_mappings": [
            {"column_id": "col_2", "field_name": "account_code"},
            {"column_id": "col_3", "field_name": "account_name"},
            {"column_id": "col_15", "field_name": "opening_amount", "period_type": "opening",
             "split_mode": "single_as_debit"},
            {"column_id": "col_16", "field_name": "current_debit", "period_type": "current",
             "split_mode": "two_column", "debit_column_id": "col_16", "credit_column_id": "col_17"},
            {"column_id": "col_17", "field_name": "current_credit", "period_type": "current",
             "split_mode": "two_column", "debit_column_id": "col_16", "credit_column_id": "col_17"},
            {"column_id": "col_18", "field_name": "ending_amount", "period_type": "ending",
             "split_mode": "single_as_debit"},
        ],
    },
    {
        "path": "D:/APP/谷歌/文件下载/科目余额表2023年导入.xls",
        "customer_label": "科目余额表2023年客户",
        "field_mappings": [
            {"column_id": "col_0", "field_name": "account_code"},
            {"column_id": "col_1", "field_name": "account_name"},
            {"column_id": "col_3", "field_name": "opening_debit", "period_type": "opening",
             "split_mode": "two_column", "debit_column_id": "col_3", "credit_column_id": "col_4"},
            {"column_id": "col_4", "field_name": "opening_credit", "period_type": "opening",
             "split_mode": "two_column", "debit_column_id": "col_3", "credit_column_id": "col_4"},
            {"column_id": "col_5", "field_name": "current_debit", "period_type": "current",
             "split_mode": "two_column", "debit_column_id": "col_5", "credit_column_id": "col_6"},
            {"column_id": "col_6", "field_name": "current_credit", "period_type": "current",
             "split_mode": "two_column", "debit_column_id": "col_5", "credit_column_id": "col_6"},
            {"column_id": "col_9", "field_name": "ending_debit", "period_type": "ending",
             "split_mode": "two_column", "debit_column_id": "col_9", "credit_column_id": "col_10"},
            {"column_id": "col_10", "field_name": "ending_credit", "period_type": "ending",
             "split_mode": "two_column", "debit_column_id": "col_9", "credit_column_id": "col_10"},
        ],
    },
    {
        "path": "D:/APP/谷歌/文件下载/医疗3月31日序时账及余额表.xlsx",
        "customer_label": "医疗",
        "field_mappings": [
            {"column_id": "col_0", "field_name": "account_code"},
            {"column_id": "col_1", "field_name": "account_name"},
            {"column_id": "col_3", "field_name": "opening_amount", "period_type": "opening",
             "split_mode": "single_by_source_direction", "direction_column_id": "col_2"},
            {"column_id": "col_4", "field_name": "current_debit", "period_type": "current",
             "split_mode": "two_column", "debit_column_id": "col_4", "credit_column_id": "col_5"},
            {"column_id": "col_5", "field_name": "current_credit", "period_type": "current",
             "split_mode": "two_column", "debit_column_id": "col_4", "credit_column_id": "col_5"},
            {"column_id": "col_9", "field_name": "ending_amount", "period_type": "ending",
             "split_mode": "single_by_source_direction", "direction_column_id": "col_8"},
        ],
    },
    {
        "path": "D:/APP/谷歌/文件下载/科目余额表-成都迪康-240930.xls",
        "customer_label": "成都迪康",
        "field_mappings": [
            {"column_id": "col_0", "field_name": "account_code"},
            {"column_id": "col_1", "field_name": "account_name"},
            {"column_id": "col_3", "field_name": "opening_amount", "period_type": "opening",
             "split_mode": "single_by_source_direction", "direction_column_id": "col_2"},
            {"column_id": "col_4", "field_name": "current_debit", "period_type": "current",
             "split_mode": "two_column", "debit_column_id": "col_4", "credit_column_id": "col_5"},
            {"column_id": "col_5", "field_name": "current_credit", "period_type": "current",
             "split_mode": "two_column", "debit_column_id": "col_4", "credit_column_id": "col_5"},
            {"column_id": "col_7", "field_name": "ending_amount", "period_type": "ending",
             "split_mode": "single_by_source_direction", "direction_column_id": "col_6"},
        ],
    },
]


# ════════════════════════════════════════════════════════
# 重大错配检测
# ════════════════════════════════════════════════════════

# 成本类标准科目代码前缀
_COST_CODE_PREFIXES = ("5001", "5101")  # 生产成本、制造费用
# 权益类标准科目代码前缀
_EQUITY_CODE_PREFIXES = ("4001", "4003", "4101", "4103", "4105")  # 实收资本、资本公积、盈余公积等
# 资产类标准科目代前缀
_ASSET_CODE_PREFIXES = ("1",)  # 所有 1 开头
# 负债类标准科目代码前缀
_LIABILITY_CODE_PREFIXES = ("2",)
# 备抵/减值类标准科目名称关键词
_RESERVE_NAME_KEYWORDS = ("累计折旧", "累计摊销", "坏账准备", "减值准备", "跌价准备", "资产减值损失")
# 费用化 RD 标准科目代码
_EXPENSED_RD_CODES = ("660201", "170402")  # 研发费用, 研发支出-费用化
# 资本化 RD 标准科目代码
_CAPITALIZED_RD_CODES = ("170401",)  # 研发支出-资本化支出
# 收入类 vs 成本类
_REVENUE_CODE_PREFIXES = ("6001", "6051", "6111", "6301")  # 主营业务收入等
_COST_EXPENSE_CODE_PREFIXES = ("6401", "6402", "6403")  # 主营业务成本等

# TASK-089 §7.5：成本语义识别必须基于明确成本语义组，
# 而非字符串包含。"摊余成本"/"成本法"/"历史成本" 不属于生产成本/营业成本。
_COST_KEYWORDS = ("生产成本", "制造费用", "劳务成本", "营业成本", "销售成本", "主营业务成本")


def _is_production_cost_term(name: str) -> bool:
    """TASK-089 §7.5：判断客户名称是否包含明确的生产/营业成本语义。

    必须排除"摊余成本"/"成本法"/"历史成本"等会计计量术语。
    """
    if not name:
        return False
    # 包含"生产成本"/"制造费用"/"营业成本"/"主营业务成本"等明确的成本类别词
    if any(kw in name for kw in _COST_KEYWORDS):
        return True
    # 仅在名称完全是"成本"或以"成本"独立成段时才视为成本类
    import re as _re
    tokens = _re.split(r"[_\-/\\\s\(\)\[\]【】（）,，:：;；]+", name)
    tokens = [t.strip() for t in tokens if t.strip()]
    return any(t == "成本" for t in tokens)


def _detect_major_mismatch(rec: dict, picked: dict | None) -> list[dict]:
    """TASK-089：检测重大错配，返回错配记录列表。

    修复：
    1. 仅在 picked 为安全自动确认候选时检查（避免人工确认被统计）。
    2. "其他应付款/保证金" → "其他应收款" 必须命中负债→资产。
    3. "管理费用/无形资产摊销" → "累计摊销" 必须命中原值→备抵（路径含费用语义）。
    4. "成本→收入" 必须基于明确成本语义组（排除"摊余成本"）。
    5. "其他存货" → "存货跌价准备" 必须命中原值→备抵。
    6. "固定资产减值准备" → "固定资产原值" 必须命中备抵→原值。
    """
    if not picked:
        return []
    # TASK-089：只在自动确认且为 compatible 时检查（避免对 conflict 重复报警）
    if picked.get("compatibility_status") != "compatible":
        return []
    if picked.get("warning"):
        return []
    if not _is_safe_candidate(picked):
        return []

    mismatches: list[dict] = []
    client_code = (rec.get("client_account_code") or "").strip()
    client_name = (rec.get("client_account_name") or "").strip()
    client_path = (rec.get("client_account_full_path") or "").strip()
    std_code = (picked.get("standard_account_code") or "").strip()
    std_name = (picked.get("standard_account_name") or "").strip()

    if not std_code:
        return mismatches

    # 合并 path 作为方向证据（路径含"其他应付款"应优先于叶子"保证金"）
    direction_text = " ".join([client_name, client_path])

    # A. 成本类误配权益类 — 必须客户科目名称含明确成本关键词
    client_cost = _is_production_cost_term(client_name) or _is_production_cost_term(client_path)
    std_equity = any(std_code.startswith(p) for p in _EQUITY_CODE_PREFIXES)
    if client_cost and std_equity:
        mismatches.append({"type": "成本→权益", "client": f"{client_code} {client_name}",
                          "target": f"{std_code} {std_name}", "compat": "compatible"})

    # B. 资产/负债方向相反 — 路径含"其他应付款"时优先于叶子"保证金"
    client_has_payable = "应付" in direction_text or client_code.startswith(("2",))
    client_has_receivable = ("应收" in client_name and "应付" not in client_name) or client_code.startswith(("1",))
    std_is_liability = std_code.startswith(_LIABILITY_CODE_PREFIXES)
    std_is_asset = std_code.startswith(_ASSET_CODE_PREFIXES)
    if client_has_payable and not client_has_receivable and std_is_asset and "应收" in std_name:
        mismatches.append({"type": "负债→资产", "client": f"{client_code} {client_name}",
                          "target": f"{std_code} {std_name}", "compat": "compatible"})
    if client_has_receivable and not client_has_payable and std_is_liability and "应付" in std_name:
        mismatches.append({"type": "资产→负债", "client": f"{client_code} {client_name}",
                          "target": f"{std_code} {std_name}", "compat": "compatible"})

    # C/D. 原值误配备抵 / 备抵误配原值 — 路径含费用语义时也视为原值方向
    client_has_reserve = any(kw in direction_text for kw in _RESERVE_NAME_KEYWORDS)
    std_has_reserve = any(kw in std_name for kw in _RESERVE_NAME_KEYWORDS)
    if std_has_reserve and not client_has_reserve:
        # 路径/名称含"存货"/"固定资产"/"应收账款"/"无形资产"/"在建工程"等
        # 视为原值方向，不应匹配备抵/累计类
        if any(kw in direction_text for kw in (
            "固定资产", "在建工程", "应收账款", "无形资产", "存货", "管理费用", "销售费用", "制造费用"
        )):
            mismatches.append({"type": "原值→备抵", "client": f"{client_code} {client_name}",
                              "target": f"{std_code} {std_name}", "compat": "compatible"})
    if client_has_reserve and not std_has_reserve:
        # 客户含减值/准备语义，目标却是原值类 → 备抵→原值
        if any(kw in std_name for kw in ("固定资产", "在建工程", "应收账款", "无形资产", "存货")):
            mismatches.append({"type": "备抵→原值", "client": f"{client_code} {client_name}",
                              "target": f"{std_code} {std_name}", "compat": "compatible"})

    # E/F. 研发费用化/资本化误配
    rd_expensing = "费用化" in direction_text or "研发费用" in direction_text
    rd_capitalizing = "资本化" in direction_text
    if rd_expensing and any(std_code.startswith(p) for p in _CAPITALIZED_RD_CODES):
        mismatches.append({"type": "费用化→资本化", "client": f"{client_code} {client_name}",
                          "target": f"{std_code} {std_name}", "compat": "compatible"})
    if rd_capitalizing and any(std_code.startswith(p) for p in _EXPENSED_RD_CODES):
        mismatches.append({"type": "资本化→费用化", "client": f"{client_code} {client_name}",
                          "target": f"{std_code} {std_name}", "compat": "compatible"})

    # G. 收入成本方向相反（仅当名称中"收入"/"成本"语义明确时）
    # TASK-089 §7.5：必须基于明确成本语义组，不能仅因包含"成本"二字
    if "收入" in client_name and any(std_code.startswith(p) for p in _COST_EXPENSE_CODE_PREFIXES):
        mismatches.append({"type": "收入→成本/费用", "client": f"{client_code} {client_name}",
                          "target": f"{std_code} {std_name}", "compat": "compatible"})
    if _is_production_cost_term(client_name) and any(std_code.startswith(p) for p in _REVENUE_CODE_PREFIXES):
        mismatches.append({"type": "成本→收入", "client": f"{client_code} {client_name}",
                          "target": f"{std_code} {std_name}", "compat": "compatible"})

    return mismatches


# ════════════════════════════════════════════════════════
# 专项科目检测关键词
# ════════════════════════════════════════════════════════

_FOCUS_PATTERNS = {
    "4101 生产成本": lambda r: (r.get("client_account_code") or "").split(".")[0] == "4101" or "生产成本" in (r.get("client_account_name") or "").split("_")[0],
    "4105 制造费用": lambda r: (r.get("client_account_code") or "").split(".")[0] == "4105" or (r.get("client_account_name") or "").split("_")[0] == "制造费用",
    "4107 研发支出": lambda r: (r.get("client_account_code") or "").split(".")[0] == "4107",
    "研发支出_费用化": lambda r: "费用化支出" in (r.get("client_account_name") or ""),
    "研发支出_资本化": lambda r: "资本化支出" in (r.get("client_account_name") or ""),
    "包装物": lambda r: "包装物" in (r.get("client_account_name") or ""),
    "坏账准备": lambda r: "坏账准备" in (r.get("client_account_name") or ""),
    "累计折旧": lambda r: "累计折旧" in (r.get("client_account_name") or ""),
    "累计摊销": lambda r: "累计摊销" in (r.get("client_account_name") or ""),
    "存货跌价准备": lambda r: "存货跌价准备" in (r.get("client_account_name") or ""),
    "资产减值准备": lambda r: "资产减值准备" in (r.get("client_account_name") or ""),
}


# ════════════════════════════════════════════════════════
# 单表审计
# ════════════════════════════════════════════════════════


def _unique_account_key(r: dict) -> tuple:
    """TASK-089：唯一有效客户科目键。
    按 (client_account_code, client_account_name, client_account_full_path)
    三元组去重，避免同一科目在多行/多方向中重复计入统计。
    """
    return (
        (r.get("client_account_code") or "").strip(),
        (r.get("client_account_name") or "").strip(),
        (r.get("client_account_full_path") or "").strip(),
    )


async def audit_one(file_def, db, sa_active_lookup: dict[str, bool] | None = None):
    file_path = file_def["path"]
    file_name = Path(file_path).name

    _print(f"\n{'='*70}")
    _print(f"文件: {file_name}")
    _print(f"{'='*70}")

    if not Path(file_path).exists():
        _print(f"  [SKIP] 文件不存在")
        return None

    customer_label = file_def["customer_label"]
    field_mappings = file_def["field_mappings"]

    t_start = time.time()

    try:
        preview = await preview_standard_import(
            db, file_path, file_name, fiscal_year=2025, period=12,
            customer_label=customer_label,
        )
        batch_id = uuid.UUID(preview["batch_id"])
        t_preview = time.time() - t_start

        analyze = await analyze_standard_import(
            db, batch_id, file_path,
            field_mappings=field_mappings, fiscal_year=2025, period=12,
            customer_label=customer_label, hierarchy_mode="auto",
        )
        t_total = time.time() - t_start
        t_analyze = t_total - t_preview
    except Exception as e:
        _print(f"  [ERROR] 失败: {type(e).__name__}: {e}")
        return {"file": file_name, "error": str(e), "elapsed_sec": round(time.time() - t_start, 2)}

    recs = analyze["mapping_recommendations"]
    active_recs = [r for r in recs if r.get("participates_in_entry", True)]
    total_rows = len(recs)

    # ── TASK-089：以唯一客户科目为统计单位 ──
    # 每个 unique key 只统计一次，避免明细行/方向行重复计入。
    unique_accounts: dict[tuple, dict] = {}

    # ── 候选分布统计（基于唯一科目去重） ──
    auto_confirm = 0
    manual_confirm = 0
    no_safe_candidate = 0  # 最终无安全候选（人工确认的一部分）
    multi_target_ambiguous = 0  # 多安全目标歧义（人工确认的一部分）
    conflict_candidate_count = 0  # 候选中含 conflict 的唯一科目数
    unknown_candidate_count = 0  # 候选中含 unknown 的唯一科目数
    no_candidate = 0  # 没有任何候选的唯一科目数

    name_exact = 0
    semantic_alias = 0
    code_match = 0
    old_code_crosswalk = 0
    parent_inherited = 0
    name_similarity = 0
    name_prefix = 0
    code_prefix_parent = 0
    code_category_anchor = 0
    name_anchor = 0

    # ── 红线统计（只针对最终自动确认的候选） ──
    warning_auto = 0
    fuzzy_auto = 0
    multi_safe_auto = 0
    disabled_auto = 0
    empty_id_auto = 0
    conflict_auto = 0
    unknown_auto = 0

    all_mismatches: list[dict] = []
    focus_results: dict[str, list[dict]] = {k: [] for k in _FOCUS_PATTERNS}

    for r in active_recs:
        key = _unique_account_key(r)
        if key in unique_accounts:
            # 已统计过同一唯一科目，跳过
            continue
        unique_accounts[key] = r

        candidates = r.get("candidates") or []
        if not candidates:
            no_candidate += 1
            continue

        # TASK-089：使用唯一安全候选判定（不再回退到首项）
        picked = pick_unique_auto_confirm_candidate(candidates)
        # 安全候选集合（去重 target 后多目标判定）
        safe_candidates = [c for c in candidates if _is_safe_candidate(c)]
        safe_ids = {c.get("standard_account_id") for c in safe_candidates if c.get("standard_account_id")}
        has_conflict_candidate = any(c.get("compatibility_status") == "conflict" for c in candidates)
        has_unknown_candidate = any(c.get("compatibility_status") == "unknown" for c in candidates)

        # conflict / unknown 候选统计（不区分自动/人工）
        if has_conflict_candidate:
            conflict_candidate_count += 1
        if has_unknown_candidate:
            unknown_candidate_count += 1

        # 多目标歧义（人工确认的一种）
        if picked is None and len(safe_ids) > 1:
            multi_target_ambiguous += 1

        if picked is None:
            # 无唯一安全候选 → 人工确认
            manual_confirm += 1
            if not safe_ids:
                no_safe_candidate += 1
        else:
            auto_confirm += 1
            # 红线检查（基于 picked 候选）
            if picked.get("warning"):
                warning_auto += 1
            if picked.get("source") == "name_similarity":
                fuzzy_auto += 1
            if len(safe_ids) > 1:
                multi_safe_auto += 1
            # TASK-089：标准科目 ID 为空也算红线
            if not picked.get("standard_account_id"):
                empty_id_auto += 1
            # TASK-089：停用科目用 is False 判定（候选可能未带该字段，从索引补充）
            sa_id = picked.get("standard_account_id")
            is_active: bool | None = picked.get("standard_account_is_active")
            if is_active is None and sa_id and sa_active_lookup is not None:
                is_active = sa_active_lookup.get(str(sa_id), True)
            if is_active is False:
                disabled_auto += 1
            # TASK-089：conflict_auto / unknown_auto（自动确认不应为 conflict/unknown）
            if picked.get("compatibility_status") == "conflict":
                conflict_auto += 1
            if picked.get("compatibility_status") == "unknown":
                unknown_auto += 1

            # 来源统计（仅自动确认计入）
            source = picked.get("source", "")
            if source == "name_exact":
                name_exact += 1
            elif source == "semantic_alias":
                semantic_alias += 1
            elif source == "code_match":
                code_match += 1
            elif source == "old_code_crosswalk":
                old_code_crosswalk += 1
            elif "parent_inherited" in source:
                parent_inherited += 1
            elif source == "name_prefix":
                name_prefix += 1
            elif source == "code_prefix_parent":
                code_prefix_parent += 1
            elif source == "code_category_anchor":
                code_category_anchor += 1
            elif source == "name_anchor":
                name_anchor += 1
            elif source == "name_similarity":
                name_similarity += 1

            # 重大错配检测（仅检查自动确认的）
            mism = _detect_major_mismatch(r, picked)
            all_mismatches.extend(mism)

        # 专项科目收集（基于实际 picked，不论 auto/manual）
        for label, pattern in _FOCUS_PATTERNS.items():
            if pattern(r):
                info = {
                    "code": r.get("client_account_code") or "",
                    "name": r.get("client_account_name") or "",
                    "parent": r.get("parent_client_account_name") or "",
                    "path": r.get("client_account_full_path") or "",
                    "auto_target": (
                        f"{picked.get('standard_account_code')} {picked.get('standard_account_name')}"
                        if picked else "(无)"
                    ),
                    "source": picked.get("source", "") if picked else "",
                    "compat": picked.get("compatibility_status", "") if picked else "",
                    "warning": (picked.get("warning") or "") if picked else "",
                    "reason": picked.get("compatibility_reason", "") if picked else "",
                    "auto_confirmed": picked is not None,
                }
                focus_results[label].append(info)

    effective_accounts = len(unique_accounts)

    # ── 强制勾稽：auto_confirm + manual_confirm == effective_accounts ──
    # manual_confirm = no_safe_candidate + multi_target_ambiguous + (其它手动情形)
    # 其它手动情形：候选均为 conflict/unknown 但无安全候选
    if auto_confirm + manual_confirm != effective_accounts:
        _print(f"  ⚠ 勾稽不平：auto({auto_confirm})+manual({manual_confirm})={auto_confirm+manual_confirm} ≠ effective({effective_accounts})")

    summary = {
        "file": file_name,
        "total_rows": total_rows,
        "effective_accounts": effective_accounts,
        "auto_confirm": auto_confirm,
        "manual_confirm": manual_confirm,
        "no_safe_candidate": no_safe_candidate,
        "multi_target_ambiguous": multi_target_ambiguous,
        "conflict_candidate_count": conflict_candidate_count,
        "unknown_candidate_count": unknown_candidate_count,
        "no_candidate": no_candidate,
        "name_exact": name_exact,
        "semantic_alias": semantic_alias,
        "code_match": code_match,
        "old_code_crosswalk": old_code_crosswalk,
        "parent_inherited": parent_inherited,
        "name_prefix": name_prefix,
        "code_prefix_parent": code_prefix_parent,
        "code_category_anchor": code_category_anchor,
        "name_anchor": name_anchor,
        "name_similarity": name_similarity,
        "warning_auto": warning_auto,
        "fuzzy_auto": fuzzy_auto,
        "multi_safe_auto": multi_safe_auto,
        "disabled_auto": disabled_auto,
        "empty_id_auto": empty_id_auto,
        "conflict_auto": conflict_auto,
        "unknown_auto": unknown_auto,
        "major_mismatch_count": len(all_mismatches),
        "major_mismatches": all_mismatches,
        "preview_sec": round(t_preview, 2),
        "analyze_sec": round(t_analyze, 2),
        "total_sec": round(t_total, 2),
        "sec_per_1k": round(t_total / max(effective_accounts, 1) * 1000, 2),
        "focus": {k: len(v) for k, v in focus_results.items()},
        "focus_details": focus_results,
    }

    _print_summary(summary)
    _print_focus(focus_results)
    _print_mismatches(all_mismatches)

    return summary


def _print_summary(s: dict):
    _print(f"\n  总行数: {s['total_rows']}  有效科目(去重): {s['effective_accounts']}")
    _print(f"  自动确认: {s['auto_confirm']}  人工确认: {s['manual_confirm']}  "
           f"(无安全候选={s['no_safe_candidate']}, 多目标歧义={s['multi_target_ambiguous']})")
    _print(f"  conflict候选科目数: {s['conflict_candidate_count']}  unknown候选科目数: {s['unknown_candidate_count']}  无候选科目数: {s['no_candidate']}")
    _print(f"  name_exact: {s['name_exact']}  semantic_alias: {s['semantic_alias']}  "
           f"code_match: {s['code_match']}  name_prefix: {s['name_prefix']}")
    _print(f"  old_code_crosswalk: {s['old_code_crosswalk']}  parent_inherited: {s['parent_inherited']}  "
           f"name_anchor: {s['name_anchor']}  name_similarity: {s['name_similarity']}")
    _print(f"  code_prefix_parent: {s['code_prefix_parent']}  code_category_anchor: {s['code_category_anchor']}")
    _print(f"  ⚠ warning_auto: {s['warning_auto']}  fuzzy_auto: {s['fuzzy_auto']}  "
           f"multi_safe_auto: {s['multi_safe_auto']}  disabled_auto: {s['disabled_auto']}")
    _print(f"  ⚠ empty_id_auto: {s['empty_id_auto']}  conflict_auto: {s['conflict_auto']}  unknown_auto: {s['unknown_auto']}")
    _print(f"  🔴 重大错配: {s['major_mismatch_count']}")
    _print(f"  ⏱ preview: {s['preview_sec']}s  analyze: {s['analyze_sec']}s  total: {s['total_sec']}s  per_1k: {s['sec_per_1k']}s")
    # 强制勾稽
    if s['auto_confirm'] + s['manual_confirm'] != s['effective_accounts']:
        _print(f"  ❌ 勾稽不平：auto({s['auto_confirm']})+manual({s['manual_confirm']})={s['auto_confirm']+s['manual_confirm']} ≠ effective({s['effective_accounts']})")


def _print_focus(focus: dict):
    for label, items in focus.items():
        if not items:
            continue
        _print(f"\n  ── {label} ({len(items)}条) ──")
        for item in items[:10]:
            _print(f"    {item['code']:<12} {item['name']:<20} → {item['auto_target']:<25}"
                   f" [{item['source']:<20}] {item['compat']:<12} {'!' if item['warning'] else ' '}")
        if len(items) > 10:
            _print(f"    ... 另有 {len(items)-10} 条未打印")


def _print_mismatches(mismatches: list):
    if not mismatches:
        _print("\n  ✅ 未检测到重大性质错配")
        return
    _print(f"\n  🔴 检测到 {len(mismatches)} 条重大性质错配:")
    for m in mismatches[:20]:
        _print(f"    [{m['type']}] {m['client']} → {m['target']} ({m['compat']})")
    if len(mismatches) > 20:
        _print(f"    ... 另有 {len(mismatches)-20} 条未打印")


# ════════════════════════════════════════════════════════
# 报告生成
# ════════════════════════════════════════════════════════

def _generate_reports(summaries: list[dict], output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)

    # JSON
    json_path = output_dir / "task_089_mapping_regression.json"
    json_data = {
        "task": "TASK-089",
        "description": "科目余额表匹配真实数据回归（TASK-089 验收缺陷修复后）",
        "files": [
            {
                "file": s.get("file"),
                "total_rows": s.get("total_rows"),
                "effective_accounts": s.get("effective_accounts"),
                "auto_confirm": s.get("auto_confirm"),
                "manual_confirm": s.get("manual_confirm"),
                "no_safe_candidate": s.get("no_safe_candidate", 0),
                "multi_target_ambiguous": s.get("multi_target_ambiguous", 0),
                "conflict_candidate_count": s.get("conflict_candidate_count", 0),
                "unknown_candidate_count": s.get("unknown_candidate_count", 0),
                "no_candidate": s.get("no_candidate", 0),
                "name_exact": s.get("name_exact", 0),
                "semantic_alias": s.get("semantic_alias", 0),
                "code_match": s.get("code_match", 0),
                "old_code_crosswalk": s.get("old_code_crosswalk", 0),
                "parent_inherited": s.get("parent_inherited", 0),
                "name_prefix": s.get("name_prefix", 0),
                "code_prefix_parent": s.get("code_prefix_parent", 0),
                "code_category_anchor": s.get("code_category_anchor", 0),
                "name_anchor": s.get("name_anchor", 0),
                "name_similarity": s.get("name_similarity", 0),
                "warning_auto": s.get("warning_auto"),
                "fuzzy_auto": s.get("fuzzy_auto"),
                "multi_safe_auto": s.get("multi_safe_auto", 0),
                "disabled_auto": s.get("disabled_auto", 0),
                "empty_id_auto": s.get("empty_id_auto", 0),
                "conflict_auto": s.get("conflict_auto", 0),
                "unknown_auto": s.get("unknown_auto", 0),
                "major_mismatch_count": s.get("major_mismatch_count"),
                "total_sec": s.get("total_sec"),
                "sec_per_1k": s.get("sec_per_1k"),
            }
            for s in summaries if not s.get("error")
        ],
        "errors": [s for s in summaries if s.get("error")],
        "totals": {
            "total_sec": round(sum(s.get("total_sec", 0) or 0 for s in summaries), 2),
            "total_effective_accounts": sum(s.get("effective_accounts", 0) or 0 for s in summaries),
            "total_auto_confirm": sum(s.get("auto_confirm", 0) or 0 for s in summaries),
            "total_manual_confirm": sum(s.get("manual_confirm", 0) or 0 for s in summaries),
            "total_major_mismatches": sum(s.get("major_mismatch_count", 0) or 0 for s in summaries),
            "total_warning_auto": sum(s.get("warning_auto", 0) or 0 for s in summaries),
            "total_fuzzy_auto": sum(s.get("fuzzy_auto", 0) or 0 for s in summaries),
            "total_multi_safe_auto": sum(s.get("multi_safe_auto", 0) or 0 for s in summaries),
            "total_disabled_auto": sum(s.get("disabled_auto", 0) or 0 for s in summaries),
            "total_empty_id_auto": sum(s.get("empty_id_auto", 0) or 0 for s in summaries),
            "total_conflict_auto": sum(s.get("conflict_auto", 0) or 0 for s in summaries),
            "total_unknown_auto": sum(s.get("unknown_auto", 0) or 0 for s in summaries),
        },
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    _print(f"\n📄 JSON 报告已生成: {json_path}")

    # CSV
    csv_path = output_dir / "task_089_mapping_regression.csv"
    csv_fields = [
        "file", "total_rows", "effective_accounts", "auto_confirm", "manual_confirm",
        "no_safe_candidate", "multi_target_ambiguous",
        "conflict_candidate_count", "unknown_candidate_count", "no_candidate",
        "name_exact", "semantic_alias", "code_match", "old_code_crosswalk",
        "parent_inherited", "name_prefix",
        "code_prefix_parent", "code_category_anchor", "name_anchor", "name_similarity",
        "warning_auto", "fuzzy_auto", "multi_safe_auto", "disabled_auto",
        "empty_id_auto", "conflict_auto", "unknown_auto",
        "major_mismatch_count",
        "total_sec", "sec_per_1k",
    ]
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        for s in summaries:
            if not s.get("error"):
                writer.writerow(s)
    _print(f"📄 CSV 报告已生成: {csv_path}")

    # Markdown
    md_path = output_dir / "task_089_mapping_regression.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# TASK-089 科目余额表匹配真实数据回归报告\n\n")
        f.write(f"**执行时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("**统计口径**：以 (client_account_code, client_account_name, client_account_full_path) "
                "三元组去重的有效客户科目数为唯一统计对象；唯一安全候选判定使用 `pick_unique_auto_confirm_candidate`，"
                "禁止回退到首候选；自动确认 + 人工确认 = 有效科目数。\n\n")

        # 逐表统计
        f.write("## 逐表统计\n\n")
        f.write("| 文件 | 有效科目 | 自动确认 | 人工确认 | 无安全候选 | 多目标歧义 | conflict候选 | unknown候选 | 重大错配 | 耗时(s) |\n")
        f.write("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n")
        for s in summaries:
            if s.get("error"):
                f.write(f"| {s['file']} | ❌ {s['error']} |\n")
            else:
                f.write(f"| {s['file']} | {s['effective_accounts']} | {s['auto_confirm']} | "
                        f"{s['manual_confirm']} | {s['no_safe_candidate']} | "
                        f"{s['multi_target_ambiguous']} | {s['conflict_candidate_count']} | "
                        f"{s['unknown_candidate_count']} | {s['major_mismatch_count']} | "
                        f"{s['total_sec']} |\n")

        totals = json_data["totals"]
        f.write(f"| **合计** | **{totals['total_effective_accounts']}** | "
                f"**{totals['total_auto_confirm']}** | **{totals['total_manual_confirm']}** | | | | | "
                f"**{totals['total_major_mismatches']}** | **{totals['total_sec']}** |\n\n")

        # 勾稽校验
        recon_ok = (totals["total_auto_confirm"] + totals["total_manual_confirm"] == totals["total_effective_accounts"])
        f.write(f"**勾稽校验**：自动确认 + 人工确认 = {totals['total_auto_confirm']} + "
                f"{totals['total_manual_confirm']} = {totals['total_auto_confirm'] + totals['total_manual_confirm']} "
                f"{'==' if recon_ok else '≠'} 有效科目 {totals['total_effective_accounts']} → "
                f"{'✅ 通过' if recon_ok else '❌ 不平'}\n\n")

        # 红线检查
        f.write("## 红线检查（仅针对最终自动确认候选）\n\n")
        f.write("| 文件 | warning_auto | fuzzy_auto | disabled_auto | multi_safe_auto | empty_id_auto | conflict_auto | unknown_auto |\n")
        f.write("|---:|---:|---:|---:|---:|---:|---:|---:|\n")
        for s in summaries:
            if not s.get("error"):
                red_count = (
                    s["warning_auto"] + s["fuzzy_auto"] + s["disabled_auto"] +
                    s["multi_safe_auto"] + s["empty_id_auto"] + s["conflict_auto"] + s["unknown_auto"]
                )
                red_flags = "🔴" if red_count else "✅"
                f.write(f"| {s['file']} {red_flags} | {s['warning_auto']} | {s['fuzzy_auto']} | "
                        f"{s['disabled_auto']} | {s['multi_safe_auto']} | {s['empty_id_auto']} | "
                        f"{s['conflict_auto']} | {s['unknown_auto']} |\n")
        f.write("\n")

        # 重大错配
        f.write("## 重大错配明细\n\n")
        all_mm: list[dict] = []
        for s in summaries:
            if not s.get("error") and s.get("major_mismatches"):
                all_mm.extend(s["major_mismatches"])
        if all_mm:
            f.write("| 类型 | 客户科目 | 目标科目 | 兼容状态 |\n")
            f.write("|---|---|---|---|\n")
            for m in all_mm:
                f.write(f"| {m['type']} | {m['client']} | {m['target']} | {m['compat']} |\n")
        else:
            f.write("✅ 未检测到重大性质错配\n")
        f.write("\n")

        # 性能
        f.write("## 性能\n\n")
        f.write("| 文件 | 总行数 | 有效科目 | 总耗时(s) | 每千科目耗时(s) |\n")
        f.write("|---:|---:|---:|---:|---:|\n")
        for s in summaries:
            if not s.get("error"):
                f.write(f"| {s['file']} | {s['total_rows']} | {s['effective_accounts']} | "
                        f"{s['total_sec']} | {s['sec_per_1k']} |\n")
        f.write("\n")

    _print(f"📄 Markdown 报告已生成: {md_path}")


# ════════════════════════════════════════════════════════
# 主入口
# ════════════════════════════════════════════════════════

async def run_audit():
    _print("=" * 70)
    _print("TASK-089 科目余额表匹配真实数据回归 — 验收缺陷修复后")
    _print("=" * 70)

    summaries = []
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    _print(f"\n[temp_db] {db_path}")

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with session_factory() as db:
            await seed_standard_accounts(db)
            # TASK-089：构建标准科目 active 状态查找表（候选可能未带 is_active 字段）
            sa_rows = (await db.execute(select(StandardAccount))).scalars().all()
            sa_active_lookup = {str(sa.id): bool(sa.is_active) for sa in sa_rows}
            _print(f"  [seed] 标准科目 {len(sa_active_lookup)} 条")

            for fdef in REAL_FILES:
                try:
                    summary = await asyncio.wait_for(
                        audit_one(fdef, db, sa_active_lookup=sa_active_lookup),
                        timeout=300,
                    )
                except asyncio.TimeoutError:
                    fn = Path(fdef["path"]).name
                    _print(f"\n  [TIMEOUT] {fn}: analyze 超过 300s")
                    summary = {"file": fn, "error": "TIMEOUT"}
                if summary:
                    summaries.append(summary)

        # 生成报告
        output_dir = Path(__file__).parent.parent / "test_reports"
        _generate_reports(summaries, output_dir)

        # 总汇总
        _print("\n" + "=" * 70)
        _print("六表回归总汇总")
        _print("=" * 70)
        ttl_sec = round(sum(s.get("total_sec", 0) or 0 for s in summaries), 2)
        ttl_eff = sum(s.get("effective_accounts", 0) or 0 for s in summaries)
        ttl_auto = sum(s.get("auto_confirm", 0) or 0 for s in summaries)
        ttl_manual = sum(s.get("manual_confirm", 0) or 0 for s in summaries)
        ttl_mm = sum(s.get("major_mismatch_count", 0) or 0 for s in summaries)
        ttl_warn = sum(s.get("warning_auto", 0) or 0 for s in summaries)
        ttl_fuzzy = sum(s.get("fuzzy_auto", 0) or 0 for s in summaries)
        ttl_multi = sum(s.get("multi_safe_auto", 0) or 0 for s in summaries)
        ttl_disabled = sum(s.get("disabled_auto", 0) or 0 for s in summaries)
        ttl_empty = sum(s.get("empty_id_auto", 0) or 0 for s in summaries)
        ttl_conflict = sum(s.get("conflict_auto", 0) or 0 for s in summaries)
        ttl_unknown = sum(s.get("unknown_auto", 0) or 0 for s in summaries)
        ttl_red = ttl_warn + ttl_fuzzy + ttl_multi + ttl_disabled + ttl_empty + ttl_conflict + ttl_unknown

        _print(f"  总有效科目: {ttl_eff}  自动确认: {ttl_auto}  人工确认: {ttl_manual}")
        _print(f"  总耗时: {ttl_sec}s  重大错配: {ttl_mm}")
        _print(f"  红线累计: warning_auto={ttl_warn}  fuzzy_auto={ttl_fuzzy}  multi_safe_auto={ttl_multi}  "
                f"disabled_auto={ttl_disabled}  empty_id_auto={ttl_empty}  conflict_auto={ttl_conflict}  unknown_auto={ttl_unknown}")
        _print(f"  性能要求: ≤180s → {'✅ 通过' if ttl_sec <= 180 else '❌ 超限'}")
        _print(f"  重大错配: {'✅ 全部为0' if ttl_mm == 0 else '❌ 存在错配'}")
        _print(f"  红线清零: {'✅ 全部为0' if ttl_red == 0 else f'❌ 累计 {ttl_red}'}")
        _print(f"  勾稽: auto({ttl_auto})+manual({ttl_manual})={ttl_auto+ttl_manual} "
              f"{'==' if ttl_auto+ttl_manual==ttl_eff else '≠'} effective({ttl_eff})")

        _print("\n说明：")
        _print("  - 唯一安全候选判定使用 pick_unique_auto_confirm_candidate（不再回退首项）")
        _print("  - 统计口径：按 (code, name, path) 三元组去重的唯一客户科目数")
        _print("  - JSON/CSV/MD 报告已输出到 backend/test_reports/task_089_*")
    finally:
        await engine.dispose()
        try:
            os.unlink(db_path)
        except OSError:
            pass


if __name__ == "__main__":
    asyncio.run(run_audit())
