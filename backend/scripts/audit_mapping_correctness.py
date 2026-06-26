"""TASK-088：科目余额表匹配真实数据回归及收尾验收 — 增强抽检脚本。

对 6 张真实文件执行 preview → analyze（不跑 execute），逐表输出：
  - 候选分布统计（自动确认/人工确认/conflict/unknown/ambiguous）
  - 重大错配自动检测（成本→权益、资产→负债、原值→备抵等 7 类）
  - 专项科目明细（4101/4105/4107/研发支出/包装物/坏账准备/累计折旧等）
  - 性能计时（每表耗时、每千科目耗时）

生成：
  - backend/test_reports/task_088_mapping_regression.json
  - backend/test_reports/task_088_mapping_regression.csv
  - backend/test_reports/task_088_mapping_regression.md
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

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.core.database import Base
from app.services.standard_account_service import seed_standard_accounts
from app.services.standard_trial_balance_import_service import (
    preview_standard_import,
    analyze_standard_import,
)
from app.services.client_account_mapping_service import (
    _is_safe_candidate,
    _pick_auto_confirm_candidate,
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


def _detect_major_mismatch(rec: dict, picked: dict | None) -> list[dict]:
    """检测重大错配，返回错配记录列表。"""
    if not picked:
        return []
    mismatches = []
    client_code = (rec.get("client_account_code") or "").strip()
    client_name = (rec.get("client_account_name") or "").strip()
    std_code = (picked.get("standard_account_code") or "").strip()
    std_name = (picked.get("standard_account_name") or "").strip()
    compat = (picked.get("compatibility_status") or "")

    if not std_code or compat == "conflict":
        return mismatches

    # A. 成本类误配权益类 — 必须客户科目名称含成本关键词
    client_cost = (
        "生产成本" in client_name or "制造费用" in client_name or "劳务成本" in client_name
    )
    std_equity = any(std_code.startswith(p) for p in _EQUITY_CODE_PREFIXES)
    if client_cost and std_equity and compat == "compatible":
        mismatches.append({"type": "成本→权益", "client": f"{client_code} {client_name}",
                          "target": f"{std_code} {std_name}", "compat": compat})

    # B. 资产类误配负债类
    if client_code and std_code:
        client_is_asset = "应收" in client_name or client_code.startswith(("1",))
        std_is_liability = std_code.startswith(_LIABILITY_CODE_PREFIXES)
        client_is_liability = "应付" in client_name or client_code.startswith(("2",))
        std_is_asset = std_code.startswith(_ASSET_CODE_PREFIXES)
        if "应收" in client_name and not "应付" in client_name and "应付" in std_name:
            mismatches.append({"type": "资产→负债", "client": f"{client_code} {client_name}",
                              "target": f"{std_code} {std_name}", "compat": compat})
        if "应付" in client_name and not "应收" in client_name and "应收" in std_name:
            mismatches.append({"type": "负债→资产", "client": f"{client_code} {client_name}",
                              "target": f"{std_code} {std_name}", "compat": compat})

    # C/D. 原值误配备抵 / 备抵误配原值
    client_has_reserve = any(kw in client_name for kw in _RESERVE_NAME_KEYWORDS)
    std_has_reserve = any(kw in std_name for kw in _RESERVE_NAME_KEYWORDS)
    if std_has_reserve and not client_has_reserve:
        # 检查是否是原值/固定资产/应收账款等方向
        if any(kw in client_name for kw in ("固定资产", "在建工程", "应收账款", "无形资产", "存货")):
            mismatches.append({"type": "原值→备抵", "client": f"{client_code} {client_name}",
                              "target": f"{std_code} {std_name}", "compat": compat})
    if client_has_reserve and not std_has_reserve:
        if any(kw in std_name for kw in ("固定资产", "在建工程", "应收账款", "无形资产", "存货")):
            mismatches.append({"type": "备抵→原值", "client": f"{client_code} {client_name}",
                              "target": f"{std_code} {std_name}", "compat": compat})

    # E/F. 研发费用化/资本化误配
    rd_expensing = "费用化" in client_name or "研发费用" in client_name
    rd_capitalizing = "资本化" in client_name
    if rd_expensing and any(std_code.startswith(p) for p in _CAPITALIZED_RD_CODES):
        mismatches.append({"type": "费用化→资本化", "client": f"{client_code} {client_name}",
                          "target": f"{std_code} {std_name}", "compat": compat})
    if rd_capitalizing and any(std_code.startswith(p) for p in _EXPENSED_RD_CODES):
        mismatches.append({"type": "资本化→费用化", "client": f"{client_code} {client_name}",
                          "target": f"{std_code} {std_name}", "compat": compat})

    # G. 收入成本方向相反
    if "收入" in client_name and any(std_code.startswith(p) for p in _COST_EXPENSE_CODE_PREFIXES):
        mismatches.append({"type": "收入→成本/费用", "client": f"{client_code} {client_name}",
                          "target": f"{std_code} {std_name}", "compat": compat})
    if "成本" in client_name and any(std_code.startswith(p) for p in _REVENUE_CODE_PREFIXES):
        mismatches.append({"type": "成本→收入", "client": f"{client_code} {client_name}",
                          "target": f"{std_code} {std_name}", "compat": compat})

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

async def audit_one(file_def, db):
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

    # ── 候选分布统计 ──
    auto_confirm = 0
    manual_confirm = 0
    conflict_count = 0
    unknown_count = 0
    ambiguous_count = 0
    no_candidate = 0
    name_exact = 0
    semantic_alias = 0
    code_match = 0
    old_code_crosswalk = 0
    parent_inherited = 0
    name_similarity = 0
    # 红线统计
    warning_auto = 0
    fuzzy_auto = 0
    multi_safe_auto = 0
    disabled_auto = 0
    all_mismatches = []
    focus_results = {k: [] for k in _FOCUS_PATTERNS}

    # 用于去重统计有效科目
    unique_keys = set()

    for r in active_recs:
        key = (r.get("client_account_code") or "", r.get("client_account_name") or "")
        unique_keys.add(key)

        candidates = r.get("candidates") or []
        if not candidates:
            no_candidate += 1
            continue

        auto_pick = _pick_auto_confirm_candidate(candidates)
        picked = auto_pick if auto_pick is not None else None
        compat_status = picked.get("compatibility_status", "") if picked else ""
        source = picked.get("source", "") if picked else ""
        warning = picked.get("warning") if picked else None

        # 自动确认状态
        has_safe = [c for c in candidates if _is_safe_candidate(c)]
        safe_ids = {c.get("standard_account_id") for c in has_safe}

        if len(safe_ids) > 1:
            ambiguous_count += 1
        if compat_status == "conflict":
            conflict_count += 1
        elif compat_status == "unknown":
            unknown_count += 1

        if auto_pick is not None:
            auto_confirm += 1
            # 红线检查
            if warning:
                warning_auto += 1
            if source == "name_similarity":
                fuzzy_auto += 1
            if len(safe_ids) > 1:
                multi_safe_auto += 1
            if not (picked.get("standard_account_is_active") if picked else True):
                disabled_auto += 1
        else:
            manual_confirm += 1

        # 来源统计（按 picked 的来源）
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
        elif source == "name_similarity":
            name_similarity += 1

        # 重大错配检测（仅检查自动确认的）
        if auto_pick is not None:
            mism = _detect_major_mismatch(r, picked)
            all_mismatches.extend(mism)

        # 专项科目收集
        for label, pattern in _FOCUS_PATTERNS.items():
            if pattern(r):
                info = {
                    "code": r.get("client_account_code") or "",
                    "name": r.get("client_account_name") or "",
                    "parent": r.get("parent_client_account_name") or "",
                    "path": r.get("client_account_full_path") or "",
                    "auto_target": f"{picked.get('standard_account_code')} {picked.get('standard_account_name')}" if picked else "(无)",
                    "source": source,
                    "compat": compat_status,
                    "warning": warning or "",
                    "reason": picked.get("compatibility_reason", "") if picked else "",
                }
                focus_results[label].append(info)

    effective_accounts = len(unique_keys)
    summary = {
        "file": file_name,
        "total_rows": total_rows,
        "effective_accounts": effective_accounts,
        "auto_confirm": auto_confirm,
        "manual_confirm": manual_confirm,
        "conflict": conflict_count,
        "unknown": unknown_count,
        "ambiguous": ambiguous_count,
        "no_candidate": no_candidate,
        "name_exact": name_exact,
        "semantic_alias": semantic_alias,
        "code_match": code_match,
        "old_code_crosswalk": old_code_crosswalk,
        "parent_inherited": parent_inherited,
        "name_similarity": name_similarity,
        "warning_auto": warning_auto,
        "fuzzy_auto": fuzzy_auto,
        "disabled_auto": disabled_auto,
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
    _print(f"\n  总行数: {s['total_rows']}  有效科目: {s['effective_accounts']}")
    _print(f"  自动确认: {s['auto_confirm']}  人工确认: {s['manual_confirm']}  no_candidate: {s['no_candidate']}")
    _print(f"  conflict: {s['conflict']}  unknown: {s['unknown']}  ambiguous: {s['ambiguous']}")
    _print(f"  name_exact: {s['name_exact']}  semantic_alias: {s['semantic_alias']}  code_match: {s['code_match']}")
    _print(f"  old_code_crosswalk: {s['old_code_crosswalk']}  parent_inherited: {s['parent_inherited']}  name_similarity: {s['name_similarity']}")
    _print(f"  ⚠ warning_auto: {s['warning_auto']}  fuzzy_auto: {s['fuzzy_auto']}  disabled_auto: {s['disabled_auto']}")
    _print(f"  🔴 重大错配: {s['major_mismatch_count']}")
    _print(f"  ⏱ preview: {s['preview_sec']}s  analyze: {s['analyze_sec']}s  total: {s['total_sec']}s  per_1k: {s['sec_per_1k']}s")


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
    json_path = output_dir / "task_088_mapping_regression.json"
    json_data = {
        "task": "TASK-088",
        "description": "科目余额表匹配真实数据回归",
        "files": [
            {
                "file": s.get("file"),
                "total_rows": s.get("total_rows"),
                "effective_accounts": s.get("effective_accounts"),
                "auto_confirm": s.get("auto_confirm"),
                "manual_confirm": s.get("manual_confirm"),
                "conflict": s.get("conflict"),
                "unknown": s.get("unknown"),
                "ambiguous": s.get("ambiguous"),
                "no_candidate": s.get("no_candidate"),
                "name_exact": s.get("name_exact"),
                "semantic_alias": s.get("semantic_alias", 0),
                "code_match": s.get("code_match", 0),
                "old_code_crosswalk": s.get("old_code_crosswalk", 0),
                "parent_inherited": s.get("parent_inherited", 0),
                "name_similarity": s.get("name_similarity", 0),
                "warning_auto": s.get("warning_auto"),
                "fuzzy_auto": s.get("fuzzy_auto"),
                "disabled_auto": s.get("disabled_auto", 0),
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
            "total_major_mismatches": sum(s.get("major_mismatch_count", 0) or 0 for s in summaries),
        },
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    _print(f"\n📄 JSON 报告已生成: {json_path}")

    # CSV
    csv_path = output_dir / "task_088_mapping_regression.csv"
    csv_fields = [
        "file", "total_rows", "effective_accounts", "auto_confirm", "manual_confirm",
        "conflict", "unknown", "ambiguous", "no_candidate",
        "name_exact", "semantic_alias", "code_match", "old_code_crosswalk",
        "parent_inherited", "name_similarity",
        "warning_auto", "fuzzy_auto", "disabled_auto", "major_mismatch_count",
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
    md_path = output_dir / "task_088_mapping_regression.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# TASK-088 科目余额表匹配真实数据回归报告\n\n")
        f.write(f"**执行时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")

        # 逐表统计
        f.write("## 逐表统计\n\n")
        f.write("| 文件 | 有效科目 | 自动确认 | 人工确认 | conflict | unknown | ambiguous | 无候选 | 重大错配 | 耗时(s) |\n")
        f.write("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n")
        for s in summaries:
            if s.get("error"):
                f.write(f"| {s['file']} | ❌ {s['error']} |\n")
            else:
                f.write(f"| {s['file']} | {s['effective_accounts']} | {s['auto_confirm']} | "
                        f"{s['manual_confirm']} | {s['conflict']} | {s['unknown']} | "
                        f"{s['ambiguous']} | {s['no_candidate']} | {s['major_mismatch_count']} | "
                        f"{s['total_sec']} |\n")

        totals = json_data["totals"]
        f.write(f"| **合计** | **{totals['total_effective_accounts']}** | | | | | | | "
                f"**{totals['total_major_mismatches']}** | **{totals['total_sec']}** |\n\n")

        # 红线检查
        f.write("## 红线检查\n\n")
        f.write("| 文件 | warning_auto | fuzzy_auto | disabled_auto |\n")
        f.write("|---:|---:|---:|---:|\n")
        for s in summaries:
            if not s.get("error"):
                red_flags = "🔴" if s["warning_auto"] or s["fuzzy_auto"] or s["disabled_auto"] else "✅"
                f.write(f"| {s['file']} {red_flags} | {s['warning_auto']} | {s['fuzzy_auto']} | {s['disabled_auto']} |\n")
        f.write("\n")

        # 重大错配
        f.write("## 重大错配明细\n\n")
        all_mm = []
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
        f.write("| 文件 | 有效科目 | 总耗时(s) | 每千科目耗时(s) |\n")
        f.write("|---:|---:|---:|---:|\n")
        for s in summaries:
            if not s.get("error"):
                f.write(f"| {s['file']} | {s['effective_accounts']} | {s['total_sec']} | {s['sec_per_1k']} |\n")
        f.write("\n")

    _print(f"📄 Markdown 报告已生成: {md_path}")


# ════════════════════════════════════════════════════════
# 主入口
# ════════════════════════════════════════════════════════

async def run_audit():
    _print("=" * 70)
    _print("TASK-088 科目余额表匹配真实数据回归及收尾验收 — 增强抽检脚本")
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
            for fdef in REAL_FILES:
                try:
                    summary = await asyncio.wait_for(audit_one(fdef, db), timeout=300)
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
        ttl_mm = sum(s.get("major_mismatch_count", 0) or 0 for s in summaries)
        ttl_warn = sum(s.get("warning_auto", 0) or 0 for s in summaries)
        ttl_fuzzy = sum(s.get("fuzzy_auto", 0) or 0 for s in summaries)

        _print(f"  总有效科目: {ttl_eff}  总耗时: {ttl_sec}s  总重大错配: {ttl_mm}")
        _print(f"  warning_auto累计: {ttl_warn}  fuzzy_auto累计: {ttl_fuzzy}")
        _print(f"  性能要求: ≤180s → {'✅ 通过' if ttl_sec <= 180 else '❌ 超限'}")
        _print(f"  重大错配: {'✅ 全部为0' if ttl_mm == 0 else '❌ 存在错配'}")

        _print("\n说明：")
        _print("  - 本次仅诊断，不改任何规则")
        _print("  - JSON/CSV/MD 报告已输出到 backend/test_reports/")
    finally:
        await engine.dispose()
        try:
            os.unlink(db_path)
        except OSError:
            pass


if __name__ == "__main__":
    asyncio.run(run_audit())
