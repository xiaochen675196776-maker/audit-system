"""TASK-078 / TASK-079 三张真实科目余额表验收脚本。

真实读取三张真实科目余额表，临时 SQLite DB 直跑：
  seed_standard_accounts -> preview_standard_import -> analyze_standard_import
  -> execute_standard_import -> get_tree

通过条件：
  - 每张表 execute.status == executed
  - entry_count > 0
  - unmatched_count == 0
  - unsafe_count == 0
  - non_parent_warning_count == 0
  - 查询树 node_id 不重复

脚本最后输出 TASK078_THREE_REAL_TRIAL_BALANCES_PASSED。
"""
import sys
import os
import asyncio
import tempfile
import uuid
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.core.database import Base
from app.services.standard_account_service import seed_standard_accounts
from app.services.standard_trial_balance_import_service import (
    preview_standard_import,
    analyze_standard_import,
    execute_standard_import,
    _collect_zero_amount_template_rows,
    _collect_summary_total_skip_rows,
)
from app.services.standard_trial_balance_service import get_tree
from app.services.client_account_mapping_service import _pick_auto_confirm_candidate
from app.services.file_parser import parse_trial_balance_import, slice_data_rows


# ── 三张真实文件 ──────────────────────────────────────
REAL_FILES = [
    {
        "path": "D:/NAS/xiaochen/李辉辉项目组/SynologyDrive/道恩钛业2025年年审-2025.12.31/1、中普账套/科目汇总表查询结果-道恩钛业20251231.xlsx",
        "customer_label": "道恩钛业",
        "field_mappings": [
            {"column_id": "col_1", "field_name": "account_code"},
            {"column_id": "col_2", "field_name": "account_name"},
            {"column_id": "col_5", "field_name": "opening_debit", "period_type": "opening",
             "split_mode": "two_column", "debit_column_id": "col_5", "credit_column_id": "col_6"},
            {"column_id": "col_6", "field_name": "opening_credit", "period_type": "opening",
             "split_mode": "two_column", "debit_column_id": "col_5", "credit_column_id": "col_6"},
            {"column_id": "col_7", "field_name": "current_debit", "period_type": "current",
             "split_mode": "two_column", "debit_column_id": "col_7", "credit_column_id": "col_8"},
            {"column_id": "col_8", "field_name": "current_credit", "period_type": "current",
             "split_mode": "two_column", "debit_column_id": "col_7", "credit_column_id": "col_8"},
            {"column_id": "col_9", "field_name": "ending_debit", "period_type": "ending",
             "split_mode": "two_column", "debit_column_id": "col_9", "credit_column_id": "col_10"},
            {"column_id": "col_10", "field_name": "ending_credit", "period_type": "ending",
             "split_mode": "two_column", "debit_column_id": "col_9", "credit_column_id": "col_10"},
        ],
    },
    {
        "path": "D:/NAS/xiaochen/项目汇总文件夹/SynologyDrive/海钦股份2025年报审计/1、企业提供的资料/1、财务账套、账表资料/2025年序时账及科目余额表/广西海钦发生额及余额表.xlsx",
        "customer_label": "广西海钦",
        "field_mappings": [
            {"column_id": "col_2", "field_name": "account_code"},
            {"column_id": "col_3", "field_name": "account_name"},
            {"column_id": "col_6", "field_name": "opening_debit", "period_type": "opening",
             "split_mode": "two_column", "debit_column_id": "col_6", "credit_column_id": "col_8"},
            {"column_id": "col_8", "field_name": "opening_credit", "period_type": "opening",
             "split_mode": "two_column", "debit_column_id": "col_6", "credit_column_id": "col_8"},
            {"column_id": "col_10", "field_name": "current_debit", "period_type": "current",
             "split_mode": "two_column", "debit_column_id": "col_10", "credit_column_id": "col_12"},
            {"column_id": "col_12", "field_name": "current_credit", "period_type": "current",
             "split_mode": "two_column", "debit_column_id": "col_10", "credit_column_id": "col_12"},
            {"column_id": "col_18", "field_name": "ending_debit", "period_type": "ending",
             "split_mode": "two_column", "debit_column_id": "col_18", "credit_column_id": "col_20"},
            {"column_id": "col_20", "field_name": "ending_credit", "period_type": "ending",
             "split_mode": "two_column", "debit_column_id": "col_18", "credit_column_id": "col_20"},
        ],
    },
    {
        "path": "D:/NAS/xiaochen/项目汇总文件夹/SynologyDrive/海钦股份2025年报审计/1、企业提供的资料/1、财务账套、账表资料/2025年序时账及科目余额表/金碟软件公司科目余额表.xlsx",
        "customer_label": "金碟软件公司",
        "field_mappings": [
            {"column_id": "col_0", "field_name": "account_code"},
            {"column_id": "col_1", "field_name": "account_name"},
            {"column_id": "col_8", "field_name": "opening_debit", "period_type": "opening",
             "split_mode": "two_column", "debit_column_id": "col_8", "credit_column_id": "col_9"},
            {"column_id": "col_9", "field_name": "opening_credit", "period_type": "opening",
             "split_mode": "two_column", "debit_column_id": "col_8", "credit_column_id": "col_9"},
            {"column_id": "col_10", "field_name": "current_debit", "period_type": "current",
             "split_mode": "two_column", "debit_column_id": "col_10", "credit_column_id": "col_11"},
            {"column_id": "col_11", "field_name": "current_credit", "period_type": "current",
             "split_mode": "two_column", "debit_column_id": "col_10", "credit_column_id": "col_11"},
            {"column_id": "col_14", "field_name": "ending_debit", "period_type": "ending",
             "split_mode": "two_column", "debit_column_id": "col_14", "credit_column_id": "col_15"},
            {"column_id": "col_15", "field_name": "ending_credit", "period_type": "ending",
             "split_mode": "two_column", "debit_column_id": "col_14", "credit_column_id": "col_15"},
        ],
    },
]


def _period_configs(field_mappings):
    configs = []
    for fm in field_mappings:
        if fm.get("period_type") and fm.get("split_mode"):
            configs.append({
                "period_type": fm["period_type"], "mode": fm["split_mode"],
                "debit_field": fm.get("debit_column_id"),
                "credit_field": fm.get("credit_column_id"),
                "amount_field": fm.get("column_id"),
            })
    return configs


def _col_id_to_index(merged_headers_or_parsed):
    out = {}
    for i, h in enumerate(merged_headers_or_parsed if isinstance(merged_headers_or_parsed, list)
                          else (merged_headers_or_parsed.get("merged_headers") or [])):
        out[f"col_{i}"] = i
    return out


def _collect_node_ids(node, acc):
    nid = node.get("node_id")
    if nid is not None:
        acc.append(nid)
    for child in node.get("children", []):
        _collect_node_ids(child, acc)


async def run_one(file_def, db):
    file_path = file_def["path"]
    file_name = Path(file_path).name
    print(f"\n=== 文件: {file_name} ===")
    if not Path(file_path).exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")

    customer_label = file_def["customer_label"]
    field_mappings = file_def["field_mappings"]

    # ── Preview ──
    preview = await preview_standard_import(
        db, file_path, file_name,
        fiscal_year=2025, period=12,
        customer_label=customer_label,
    )
    batch_id = uuid.UUID(preview["batch_id"])
    preview_total_rows = preview["total_rows"]
    print(f"preview_total_rows: {preview_total_rows}")

    # ── Analyze ──
    analyze = await analyze_standard_import(
        db, batch_id, file_path,
        field_mappings=field_mappings,
        fiscal_year=2025, period=12,
        customer_label=customer_label,
        hierarchy_mode="auto",
    )
    recs = analyze["mapping_recommendations"]
    errors = analyze["errors"]
    warnings = analyze["warnings"]

    active_recs = [r for r in recs if r.get("participates_in_entry", True)]
    unmatched = [r for r in active_recs if not r.get("candidates")]
    unsafe = []
    for r in active_recs:
        cands = r.get("candidates", []) or []
        picked = _pick_auto_confirm_candidate(cands) if cands else None
        if picked is None:
            continue
        if picked.get("warning") is not None or float(picked.get("score", 0) or 0) < 0.9:
            unsafe.append(r)

    non_mismatch_warnings = [
        w for w in warnings if w.get("category") != "parent_amount_mismatch"
    ]

    active_recommendations = len(active_recs)
    print(f"active_recommendations: {active_recommendations}")
    print(f"unmatched_count: {len(unmatched)}")
    print(f"unsafe_count: {len(unsafe)}")
    print(f"warning_count: {len(warnings)}")
    print(f"non_parent_warning_count: {len(non_mismatch_warnings)}")
    print(f"error_count: {len(errors)}")

    # ── 自动确认映射 ──
    confirmed_mappings = []
    for rec in active_recs:
        cands = rec.get("candidates", []) or []
        if not cands:
            continue
        picked = _pick_auto_confirm_candidate(cands)
        if picked is None:
            continue
        confirmed_mappings.append({
            "row_index": rec["row_index"],
            "client_account_code": rec.get("client_account_code"),
            "client_account_name": rec.get("client_account_name"),
            "standard_account_id": uuid.UUID(picked["standard_account_id"]),
            "standard_account_code": picked["standard_account_code"],
            "standard_account_name": picked["standard_account_name"],
        })

    # ── Execute ──
    execute = await execute_standard_import(
        db, batch_id, file_path,
        confirmed_mappings=confirmed_mappings,
        warnings_confirmed=True,
        save_mapping_experience=True,
    )
    print(f"execute status: {execute['status']}")
    print(f"entry_count: {execute['entry_count']}")

    # ── 收集统计信息 ──
    parsed = parse_trial_balance_import(file_path)
    from sqlalchemy import select
    from app.models.standard_trial_balance_import_batch import StandardTrialBalanceImportBatch
    batch = (await db.execute(
        select(StandardTrialBalanceImportBatch).where(
            StandardTrialBalanceImportBatch.id == batch_id
        )
    )).scalar_one()
    hc = batch.hierarchy_config or {}
    pc = hc.get("parse_config") or {}
    data_start_row = int(pc.get("data_start_row") or parsed["data_start_row"])
    ignored_header_rows = pc.get("header_rows") or parsed.get("header_rows") or []

    merged = pc.get("merged_headers") or parsed["merged_headers"]
    col_to_idx = _col_id_to_index(merged)
    rows = slice_data_rows(parsed["all_rows"], data_start_row)

    period_cfgs = _period_configs(field_mappings)
    zero_skip = _collect_zero_amount_template_rows(rows, period_cfgs, col_to_idx)
    summary_skip = _collect_summary_total_skip_rows(
        rows, col_to_idx,
        code_col_id="col_0" if "col_0" in col_to_idx else None,
        name_col_id="col_1" if "col_1" in col_to_idx else None,
    )
    ignored_zero_amount_rows = len(zero_skip)
    ignored_summary_total_rows = len(summary_skip)

    inherited_auxiliary_rows = int(hc.get("inherited_auxiliary_rows") or 0)

    # ── 树 ──
    nodes, total_nodes = await get_tree(db, batch_id=batch_id)
    all_ids = []
    for root in nodes:
        _collect_node_ids(root, all_ids)
    dup_ids = [i for i in set(all_ids) if all_ids.count(i) > 1]

    print(f"data_start_row: {data_start_row}")
    print(f"ignored_header_rows: {ignored_header_rows}")
    print(f"ignored_zero_amount_rows: {ignored_zero_amount_rows}")
    print(f"ignored_summary_total_rows: {ignored_summary_total_rows}")
    print(f"inherited_auxiliary_rows: {inherited_auxiliary_rows}")
    print(f"tree_total_nodes: {total_nodes}")

    # ── 断言 ──
    assert execute["status"] == "executed", f"execute 状态: {execute['status']}"
    assert execute["entry_count"] > 0, f"entry_count 应 > 0，实际 {execute['entry_count']}"
    assert len(unmatched) == 0, (
        f"未匹配应为 0，实际 {len(unmatched)}: {unmatched[:3]}"
    )
    assert len(unsafe) == 0, (
        f"unsafe candidates 应为 0，实际 {len(unsafe)}: {unsafe[:3]}"
    )
    assert len(non_mismatch_warnings) == 0, (
        f"非 parent_amount_mismatch 警告应为 0，实际 {len(non_mismatch_warnings)}: "
        f"{[(w.get('category'), w.get('message','')[:60]) for w in non_mismatch_warnings[:5]]}"
    )
    assert len(dup_ids) == 0, f"节点 node_id 重复: {dup_ids[:10]}"

    return {
        "file": file_name,
        "preview_total_rows": preview_total_rows,
        "data_start_row": data_start_row,
        "active_recommendations": active_recommendations,
        "ignored_header_rows": ignored_header_rows,
        "ignored_zero_amount_rows": ignored_zero_amount_rows,
        "ignored_summary_total_rows": ignored_summary_total_rows,
        "inherited_auxiliary_rows": inherited_auxiliary_rows,
        "unmatched_count": len(unmatched),
        "unsafe_count": len(unsafe),
        "warning_count": len(warnings),
        "non_parent_warning_count": len(non_mismatch_warnings),
        "entry_count": execute["entry_count"],
        "tree_total_nodes": total_nodes,
    }


async def run_acceptance():
    summaries = []
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    print(f"[temp_db] {db_path}")

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with session_factory() as db:
            seed_result = await seed_standard_accounts(db)
            print(f"seed_result: {seed_result}")

            for fdef in REAL_FILES:
                summary = await run_one(fdef, db)
                summaries.append(summary)

        print("\n=== 三张表摘要 ===")
        import json
        print(json.dumps(summaries, ensure_ascii=False, indent=2))

        for s in summaries:
            assert s["entry_count"] > 0
            assert s["unmatched_count"] == 0
            assert s["unsafe_count"] == 0
            assert s["non_parent_warning_count"] == 0

        print("\nTASK078_THREE_REAL_TRIAL_BALANCES_PASSED")
    finally:
        await engine.dispose()
        try:
            os.unlink(db_path)
        except OSError:
            pass


if __name__ == "__main__":
    asyncio.run(run_acceptance())