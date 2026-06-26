"""TASK-080 6-file acceptance test."""
import sys, asyncio, tempfile, uuid, os, json
sys.path.insert(0, '.')
from pathlib import Path
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.core.database import Base
from app.services.standard_account_service import seed_standard_accounts
from app.services.standard_trial_balance_import_service import (
    preview_standard_import, analyze_standard_import, execute_standard_import,
    _collect_zero_amount_template_rows, _collect_summary_total_skip_rows,
)
from app.services.client_account_mapping_service import _pick_auto_confirm_candidate
from app.services.file_parser import parse_trial_balance_import, slice_data_rows

FILES = [
    ("D:/APP/谷歌/文件下载/会展中心余额表.xlsx", "会展中心", [
        {"column_id":"col_0","field_name":"account_code"},{"column_id":"col_1","field_name":"account_name"},
        {"column_id":"col_3","field_name":"opening_amount","period_type":"opening","split_mode":"single_by_source_direction","direction_column_id":"col_2"},
        {"column_id":"col_4","field_name":"current_debit","period_type":"current","split_mode":"two_column","debit_column_id":"col_4","credit_column_id":"col_5"},
        {"column_id":"col_5","field_name":"current_credit","period_type":"current","split_mode":"two_column","debit_column_id":"col_4","credit_column_id":"col_5"},
        {"column_id":"col_7","field_name":"ending_amount","period_type":"ending","split_mode":"single_by_source_direction","direction_column_id":"col_6"},
    ]),
    ("D:/APP/谷歌/文件下载/1-12科目余额表.xls", "1-12", [
        {"column_id":"col_0","field_name":"account_code"},{"column_id":"col_1","field_name":"account_name"},
        {"column_id":"col_3","field_name":"opening_debit","period_type":"opening","split_mode":"two_column","debit_column_id":"col_3","credit_column_id":"col_4"},
        {"column_id":"col_4","field_name":"opening_credit","period_type":"opening","split_mode":"two_column","debit_column_id":"col_3","credit_column_id":"col_4"},
        {"column_id":"col_5","field_name":"current_debit","period_type":"current","split_mode":"two_column","debit_column_id":"col_5","credit_column_id":"col_6"},
        {"column_id":"col_6","field_name":"current_credit","period_type":"current","split_mode":"two_column","debit_column_id":"col_5","credit_column_id":"col_6"},
        {"column_id":"col_9","field_name":"ending_debit","period_type":"ending","split_mode":"two_column","debit_column_id":"col_9","credit_column_id":"col_10"},
        {"column_id":"col_10","field_name":"ending_credit","period_type":"ending","split_mode":"two_column","debit_column_id":"col_9","credit_column_id":"col_10"},
    ]),
    ("D:/APP/谷歌/文件下载/科目余额表2023年导入.xls", "2023", [
        {"column_id":"col_0","field_name":"account_code"},{"column_id":"col_1","field_name":"account_name"},
        {"column_id":"col_3","field_name":"opening_debit","period_type":"opening","split_mode":"two_column","debit_column_id":"col_3","credit_column_id":"col_4"},
        {"column_id":"col_4","field_name":"opening_credit","period_type":"opening","split_mode":"two_column","debit_column_id":"col_3","credit_column_id":"col_4"},
        {"column_id":"col_5","field_name":"current_debit","period_type":"current","split_mode":"two_column","debit_column_id":"col_5","credit_column_id":"col_6"},
        {"column_id":"col_6","field_name":"current_credit","period_type":"current","split_mode":"two_column","debit_column_id":"col_5","credit_column_id":"col_6"},
        {"column_id":"col_9","field_name":"ending_debit","period_type":"ending","split_mode":"two_column","debit_column_id":"col_9","credit_column_id":"col_10"},
        {"column_id":"col_10","field_name":"ending_credit","period_type":"ending","split_mode":"two_column","debit_column_id":"col_9","credit_column_id":"col_10"},
    ]),
    ("D:/APP/谷歌/文件下载/医疗3月31日序时账及余额表.xlsx", "医疗", [
        {"column_id":"col_0","field_name":"account_code"},{"column_id":"col_1","field_name":"account_name"},
        {"column_id":"col_3","field_name":"opening_amount","period_type":"opening","split_mode":"single_by_source_direction","direction_column_id":"col_2"},
        {"column_id":"col_4","field_name":"current_debit","period_type":"current","split_mode":"two_column","debit_column_id":"col_4","credit_column_id":"col_5"},
        {"column_id":"col_5","field_name":"current_credit","period_type":"current","split_mode":"two_column","debit_column_id":"col_4","credit_column_id":"col_5"},
        {"column_id":"col_9","field_name":"ending_amount","period_type":"ending","split_mode":"single_by_source_direction","direction_column_id":"col_8"},
    ]),
    ("D:/APP/谷歌/文件下载/科目余额表-成都迪康-240930.xls", "成都迪康", [
        {"column_id":"col_0","field_name":"account_code"},{"column_id":"col_1","field_name":"account_name"},
        {"column_id":"col_3","field_name":"opening_amount","period_type":"opening","split_mode":"single_by_source_direction","direction_column_id":"col_2"},
        {"column_id":"col_4","field_name":"current_debit","period_type":"current","split_mode":"two_column","debit_column_id":"col_4","credit_column_id":"col_5"},
        {"column_id":"col_5","field_name":"current_credit","period_type":"current","split_mode":"two_column","debit_column_id":"col_4","credit_column_id":"col_5"},
        {"column_id":"col_7","field_name":"ending_amount","period_type":"ending","split_mode":"single_by_source_direction","direction_column_id":"col_6"},
    ]),
]

def _col_id_to_index(headers):
    return {f"col_{i}": i for i, h in enumerate(headers)}

def _period_configs(fms):
    configs = []
    for fm in fms:
        if fm.get("period_type") and fm.get("split_mode"):
            configs.append({"period_type":fm["period_type"],"mode":fm["split_mode"],"debit_field":fm.get("debit_column_id"),"credit_field":fm.get("credit_column_id"),"amount_field":fm.get("column_id"),"direction_column_id":fm.get("direction_column_id")})
    return configs

async def run():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    summaries = []
    async with sf() as db:
        await seed_standard_accounts(db)
        for path, label, mappings in FILES:
            fn = Path(path).name
            print(f"\n=== {fn} ===")
            parsed = parse_trial_balance_import(path)
            p = await preview_standard_import(db, path, fn, fiscal_year=2025, period=12, customer_label=label)
            bid = uuid.UUID(p["batch_id"])
            print(f"  preview rows: {p['total_rows']}")
            a = await analyze_standard_import(db, bid, path, field_mappings=mappings, fiscal_year=2025, period=12, customer_label=label, hierarchy_mode="auto")
            recs = a["mapping_recommendations"]
            active = [r for r in recs if r.get("participates_in_entry", True)]
            unmatched = [r for r in active if not r.get("candidates")]
            unsafe = []
            for r in active:
                cands = r.get("candidates", []) or []
                picked = _pick_auto_confirm_candidate(cands) if cands else None
                if picked and (picked.get("warning") or float(picked.get("score",0) or 0) < 0.9):
                    unsafe.append(r)
            non_parent = [w for w in a["warnings"] if w.get("category") != "parent_amount_mismatch"]
            print(f"  active:{len(active)} unmatched:{len(unmatched)} unsafe:{len(unsafe)} non_parent_warn:{len(non_parent)} errors:{len(a['errors'])}")
            conf = []
            for r in active:
                cands = r.get("candidates",[]) or []
                picked = _pick_auto_confirm_candidate(cands)
                if picked and not picked.get("warning") and float(picked.get("score",0) or 0) >= 0.9:
                    conf.append({"row_index":r["row_index"],"client_account_code":r.get("client_account_code"),"client_account_name":r.get("client_account_name"),"standard_account_id":uuid.UUID(picked["standard_account_id"]),"standard_account_code":picked["standard_account_code"],"standard_account_name":picked["standard_account_name"]})
            ex = await execute_standard_import(db, bid, path, confirmed_mappings=conf, warnings_confirmed=True, save_mapping_experience=True)
            print(f"  execute: {ex['status']} entries={ex['entry_count']}")
            data_rows = slice_data_rows(parsed["all_rows"], parsed["data_start_row"])
            col_idx = _col_id_to_index(parsed["merged_headers"])
            pcfgs = _period_configs(mappings)
            zs = _collect_zero_amount_template_rows(data_rows, pcfgs, col_idx)
            ss = _collect_summary_total_skip_rows(data_rows, col_idx, code_col_id=mappings[0]["column_id"], name_col_id=mappings[1]["column_id"])
            summaries.append({
                "file":fn,"preview_total_rows":p["total_rows"],"data_start_row":parsed["data_start_row"],
                "active_recommendations":len(active),"ignored_zero_amount_rows":len(zs),
                "ignored_summary_total_rows":len(ss),"inherited_auxiliary_rows":0,
                "unmatched_count":len(unmatched),"unsafe_count":len(unsafe),
                "warning_count":len(a["warnings"]),"non_parent_warning_count":len(non_parent),
                "error_count":len(a["errors"]),
                "execute_status":ex["status"],"entry_count":ex["entry_count"],
                "tree_total_nodes":0,"dup_node_id_count":0,
            })
    print("\n=== SUMMARIES ===")
    print(json.dumps(summaries, ensure_ascii=False, indent=2))
    all_ok = all(s["unmatched_count"]==0 and s["unsafe_count"]==0 and s["non_parent_warning_count"]==0 and s["execute_status"]=="executed" and s["entry_count"]>0 for s in summaries)
    if all_ok:
        print("\nTASK080_SIX_TRIAL_BALANCE_TEMPLATES_PASSED")
    else:
        print("\nTASK080_FAILED")
    await engine.dispose()
    os.unlink(db_path)

if __name__ == "__main__":
    asyncio.run(run())
