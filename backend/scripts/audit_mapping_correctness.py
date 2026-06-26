"""TASK-086：科目余额表导入匹配正确性人工抽检脚本。

只读诊断：对 6 张真实文件跑 preview → analyze（不跑 execute），
导出 mapping_recommendations，按高危类别分组打印自动确认候选，
供人工核对"配对/配错"。

高危类别：
  1. 泛化叶子名（工资/材料费/检测费/其他费用）在研发/费用路径下的指向
  2. 旧准则编码（101/102/137/502/521 等）crosswalk 结果
  3. 坏账准备/其他应收款（123102 / 1231）指向
  4. 银行/客户往来明细继承父级结果
  5. 点分层级代码（1009.010.003）继承结果
  6. 研发支出/研发费用明细（5301 / 1704 / 6604）上下文

输出每条高危样本：
  客户编码 | 客户名称 | 父级路径 | → 标准编码 标准名称 | score | source | warning

红线：不改业务代码、不改标准库、不改映射规则。仅产出诊断清单。
"""
import sys
import os
import asyncio
import tempfile
import uuid
import json
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def _print(msg: str) -> None:
    print(msg, flush=True)


sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select

from app.core.database import Base
from app.services.standard_account_service import seed_standard_accounts
from app.services.standard_trial_balance_import_service import (
    preview_standard_import,
    analyze_standard_import,
)
from app.services.client_account_mapping_service import (
    _pick_auto_confirm_candidate,
    _GENERIC_LEAF_NAMES,
    _normalize_name,
)
from app.models.standard_trial_balance_import_batch import StandardTrialBalanceImportBatch


# ── 复用 acceptance_task080 的文件配置 ──────────────────
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


# ── 高危分类规则 ────────────────────────────────────────

# 泛化叶子名：规范化后命中 _GENERIC_LEAF_NAMES
_GENERIC_NORM_SET = {_normalize_name(n) for n in _GENERIC_LEAF_NAMES}

# 旧准则编码前缀（出现在客户代码开头）
_OLD_CODE_PREFIXES = (
    "101", "102", "109", "111", "112", "113", "114", "115", "119",
    "121", "122", "123", "124", "128", "129", "131", "137", "139",
    "141", "151", "161", "165", "169", "171", "181", "191",
    "201", "202", "203", "204", "209", "211", "214", "221", "229",
    "301", "311", "312", "313", "321", "322",
    "401", "405",
    "501", "502", "503", "504", "511", "512", "521", "522", "531", "541", "542", "550", "560",
)

# 坏账准备/其他应收款相关客户代码或名称关键词
_BAD_DEBT_KEYWORDS = ("坏账准备", "123102", "1231")

# 研发相关：客户代码前缀或父级路径含研发
_RD_CODE_PREFIXES = ("5301", "1704", "6604")
_RD_NAME_KEYWORDS = ("研发支出", "研发费用", "资本化支出", "费用化支出", "委托外部研究开发")

# 银行/往来明细：客户名称含银行/支行/公司等后缀且无独立标准代码
_BANK_COMPANY_SUFFIXES = ("银行", "支行", "营业部", "公司", "工厂", "基金", "信托", "分理处")

# 点分层级代码（含 . 或 - 分隔的多段数字）
import re as _re
_DOTTED_CODE_RE = _re.compile(r"^\d+[\.\-]\d+")


def _classify(rec, picked, full_path, ancestor_codes, ancestor_names):
    """返回该样本命中的高危类别列表。"""
    code = (rec.get("client_account_code") or "").strip()
    name = (rec.get("client_account_name") or "").strip()
    name_norm = _normalize_name(name)
    path_str = full_path or ""
    ancestor_str = " ".join(ancestor_names or [])
    categories = []

    # 1. 泛化叶子名
    if name_norm and name_norm in _GENERIC_NORM_SET:
        categories.append("generic_leaf")

    # 2. 旧准则编码
    if code:
        for pfx in _OLD_CODE_PREFIXES:
            if code.startswith(pfx) and code != pfx:
                # 仅当不是标准 4 位新编码（避免 1001 这类误判）
                # 旧编码典型是 3 位或带点分
                if len(pfx) <= 3 or "." in code or "-" in code:
                    categories.append("old_code")
                    break

    # 3. 坏账准备/其他应收款
    if any(kw in code for kw in _BAD_DEBT_KEYWORDS) or any(kw in name for kw in _BAD_DEBT_KEYWORDS):
        categories.append("bad_debt_other_recv")

    # 4. 研发上下文
    is_rd = any(code.startswith(p) for p in _RD_CODE_PREFIXES)
    if not is_rd:
        if any(kw in name for kw in _RD_NAME_KEYWORDS) or any(kw in ancestor_str for kw in _RD_NAME_KEYWORDS):
            is_rd = True
    if is_rd:
        categories.append("rd_context")

    # 5. 银行/客户往来明细
    if any(suf in name for suf in _BANK_COMPANY_SUFFIXES):
        # 且被自动确认到银行存款/应收账款/其他应收款/应付账款等上级科目
        std_name = (picked.get("standard_account_name") or "") if picked else ""
        if any(k in std_name for k in ("银行存款", "应收账款", "其他应收款", "应付账款", "预付")):
            categories.append("bank_aux_detail")

    # 6. 点分层级
    if code and _DOTTED_CODE_RE.match(code):
        categories.append("dotted_hierarchy")

    return categories


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

    try:
        preview = await preview_standard_import(
            db, file_path, file_name, fiscal_year=2025, period=12,
            customer_label=customer_label,
        )
        batch_id = uuid.UUID(preview["batch_id"])

        analyze = await analyze_standard_import(
            db, batch_id, file_path,
            field_mappings=field_mappings, fiscal_year=2025, period=12,
            customer_label=customer_label, hierarchy_mode="auto",
        )
    except Exception as e:
        _print(f"  [ERROR] analyze 失败: {type(e).__name__}: {e}")
        return None

    recs = analyze["mapping_recommendations"]
    active_recs = [r for r in recs if r.get("participates_in_entry", True)]

    _print(f"  active_recommendations={len(active_recs)}")

    # 收集高危样本
    high_risk_samples = []
    for r in active_recs:
        cands = r.get("candidates", []) or []
        if not cands:
            continue
        picked = _pick_auto_confirm_candidate(cands)
        if not picked:
            continue
        # 只看会被自动确认的（score >= 0.85，与验收脚本一致）
        if float(picked.get("score", 0) or 0) < 0.85:
            continue

        full_path = r.get("client_account_full_path")
        ancestor_codes = r.get("ancestor_codes") or []
        ancestor_names = r.get("ancestor_names") or []
        cats = _classify(r, picked, full_path, ancestor_codes, ancestor_names)
        if cats:
            high_risk_samples.append({
                "code": r.get("client_account_code") or "",
                "name": r.get("client_account_name") or "",
                "path": full_path or "",
                "ancestor_names": ancestor_names,
                "std_code": picked.get("standard_account_code") or "",
                "std_name": picked.get("standard_account_name") or "",
                "score": picked.get("score"),
                "source": picked.get("source") or "",
                "warning": picked.get("warning"),
                "categories": cats,
            })

    # 去重：同 (code, name, std_code) 只保留一条
    seen = set()
    deduped = []
    for s in high_risk_samples:
        key = (s["code"], s["name"], s["std_code"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(s)

    _print(f"  高危自动确认样本（去重后）: {len(deduped)}")

    # 按类别分组打印
    by_cat = {}
    for s in deduped:
        for cat in s["categories"]:
            by_cat.setdefault(cat, []).append(s)

    cat_labels = {
        "generic_leaf": "① 泛化叶子名（工资/材料费等）自动确认指向",
        "old_code": "② 旧准则编码 crosswalk 结果",
        "bad_debt_other_recv": "③ 坏账准备/其他应收款指向",
        "rd_context": "④ 研发支出/费用上下文",
        "bank_aux_detail": "⑤ 银行/客户往来明细继承父级",
        "dotted_hierarchy": "⑥ 点分层级代码继承",
    }

    for cat in ("generic_leaf", "old_code", "bad_debt_other_recv",
                "rd_context", "bank_aux_detail", "dotted_hierarchy"):
        samples = by_cat.get(cat, [])
        if not samples:
            _print(f"\n  [{cat_labels[cat]}] 无")
            continue
        _print(f"\n  [{cat_labels[cat]}] {len(samples)} 条")
        _print(f"  {'客户编码':<18} | {'客户名称':<22} | {'父级路径':<20} | → {'标准编码':<8} {'标准名称':<18} | {'src':<22} | s | warn")
        _print(f"  {'-'*120}")
        for s in samples[:40]:  # 每类最多打印 40 条
            code = (s["code"] or "")[:17]
            name = (s["name"] or "")[:21]
            path = (s["path"] or "")[:19]
            std_c = (s["std_code"] or "")[:8]
            std_n = (s["std_name"] or "")[:17]
            src = (s["source"] or "")[:21]
            sc = f"{s['score']:.2f}" if s["score"] is not None else "?"
            warn = "!" if s["warning"] else " "
            _print(f"  {code:<18} | {name:<22} | {path:<20} | → {std_c:<8} {std_n:<18} | {src:<22} | {sc} | {warn}")
        if len(samples) > 40:
            _print(f"  ... 另有 {len(samples)-40} 条未打印")

    return {
        "file": file_name,
        "active_recommendations": len(active_recs),
        "high_risk_count": len(deduped),
        "by_category": {cat: len(by_cat.get(cat, [])) for cat in cat_labels},
    }


async def run_audit():
    _print("=" * 70)
    _print("TASK-086 科目余额表导入匹配正确性人工抽检")
    _print("（只读：preview → analyze，不跑 execute；不改业务代码/标准库/规则）")
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
                    summary = await asyncio.wait_for(audit_one(fdef, db), timeout=180)
                except asyncio.TimeoutError:
                    await db.rollback()
                    fn = Path(fdef["path"]).name
                    _print(f"\n  [TIMEOUT] {fn}: analyze 超过 180s")
                    summary = {"file": fn, "error": "TIMEOUT"}
                if summary:
                    summaries.append(summary)

        _print("\n" + "=" * 70)
        _print("抽检汇总")
        _print("=" * 70)
        print(json.dumps(summaries, ensure_ascii=False, indent=2), flush=True)

        _print("\n说明：")
        _print("  - 只统计 score>=0.85 的自动确认候选（与验收脚本自动确认阈值一致）")
        _print("  - warn 列 '!' 表示该候选带 warning（不应被自动确认，需检查为何出现在 picked）")
        _print("  - 本次仅诊断，不改任何规则；若发现系统性误配，记录到文档后单独评估")
    finally:
        await engine.dispose()
        try:
            os.unlink(db_path)
        except OSError:
            pass


if __name__ == "__main__":
    asyncio.run(run_audit())
