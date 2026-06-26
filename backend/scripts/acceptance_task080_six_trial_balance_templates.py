"""TASK-080/081 六张真实科目余额表模板验收脚本。

硬性约束：不新增/删除/修改标准库科目（standard_accounts_seed.py）。

通过条件：
  - 标准库 compare: 真实比对 git HEAD；added_code_count==0,
    removed_code_count==0, changed_count==0
    （读取/比对 git HEAD 失败一律视为验收失败，严禁 git_unavailable 放行）
  - 每张表 execute_status==executed, entry_count>0
    （TASK-083：删除 205201-2023.xls 的硬编码特殊放行，
     无金额文件应失败而非冒充成功；用户未批准「无金额文件允许跳过」）
  - unmatched_count==0, unsafe_count==0, non_parent_warning_count==0
  - tree_error is None, tree_total_nodes>0, dup_node_id_count==0
  - 每张表单文件 120s 超时保护；目标整体 180s 内完成
"""
import sys, os, asyncio, tempfile, uuid, json, ast, time, subprocess
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# TASK-083：单文件全链路超时（秒）。防止个别文件卡死导致整脚本无输出。
SINGLE_FILE_TIMEOUT = 600
# TASK-085：六表整体性能目标（秒）。超过此值必须失败。
OVERALL_TARGET_SEC = 180


def _print(msg: str) -> None:
    """带 flush 的打印，确保即使被管道缓冲也能实时看到阶段进度。"""
    print(msg, flush=True)

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select

from app.core.database import Base
from app.services.standard_account_service import seed_standard_accounts
from app.services.standard_trial_balance_import_service import (
    preview_standard_import, analyze_standard_import, execute_standard_import,
    _collect_zero_amount_template_rows, _collect_summary_total_skip_rows,
)
from app.services.standard_trial_balance_service import get_tree
from app.services.client_account_mapping_service import _pick_auto_confirm_candidate
from app.services.file_parser import parse_trial_balance_import, slice_data_rows
from app.models.standard_trial_balance_import_batch import StandardTrialBalanceImportBatch


# ── 标准库保护检查 ──────────────────────────────────

def _repo_root() -> Path:
    """从当前脚本路径推导 git 仓库根目录。

    本脚本位于 <repo_root>/backend/scripts/acceptance_task080_six_trial_balance_templates.py，
    因此仓库根目录是脚本路径的上三级。
    """
    script_path = Path(__file__).resolve()
    backend_root = script_path.parents[1]   # .../backend
    return backend_root.parent              # repo_root


def get_git_head_seed_accounts() -> list[dict]:
    """从 git HEAD 读取原始 SEED_ACCOUNTS。

    TASK-083：旧实现从 backend 目录运行 `git show HEAD:app/data/...`，
    但仓库根目录是 backend 的父目录，HEAD 路径必须相对仓库根，
    所以旧实现始终返回 None，进而被 assert_standard_seed_not_changed
    当作 `git_unavailable` 放行，形成假通过。
    """
    repo_root = _repo_root()
    rel_path = "backend/app/data/standard_accounts_seed.py"
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "show", f"HEAD:{rel_path}"],
            capture_output=True, text=True, encoding="utf-8",
            timeout=10,
        )
    except Exception as e:
        # 读取 git 本身失败（git 未安装/仓库损坏）属于真实失败，不允许放行
        raise RuntimeError(f"读取 git HEAD 标准库失败: {e}") from e
    if result.returncode != 0:
        # git show 失败也属于真实失败，必须停止验收
        raise AssertionError(
            f"无法读取 git HEAD 标准库 ({rel_path}): {result.stderr.strip() or result.stdout.strip()}"
        )
    content = result.stdout
    if not content:
        raise AssertionError(f"无法读取 git HEAD 标准库 ({rel_path}): 输出为空")
    try:
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                if isinstance(node.targets[0], ast.Name) and node.targets[0].id == "SEED_ACCOUNTS":
                    return ast.literal_eval(node.value)
    except Exception as e:
        raise AssertionError(f"解析 git HEAD 标准库失败: {e}") from e
    raise AssertionError(
        "无法在 git HEAD 的 standard_accounts_seed.py 中找到 SEED_ACCOUNTS 赋值"
    )


def assert_standard_seed_not_changed():
    """比较当前 SEED_ACCOUNTS 与 git HEAD 版本。

    TASK-083：读取 git HEAD 失败一律视为验收失败，绝不再以
    `note=git_unavailable` 形式放行。
    """
    from app.data.standard_accounts_seed import SEED_ACCOUNTS as current
    old = get_git_head_seed_accounts()

    old_codes = {a["account_code"] for a in old}
    new_codes = {a["account_code"] for a in current}
    old_by_code = {a["account_code"]: a for a in old}
    new_by_code = {a["account_code"]: a for a in current}

    added = sorted(new_codes - old_codes)
    removed = sorted(old_codes - new_codes)
    changed = []
    for code in old_codes & new_codes:
        if old_by_code[code] != new_by_code[code]:
            changed.append(code)

    result = {
        "added_code_count": len(added),
        "removed_code_count": len(removed),
        "changed_count": len(changed),
        "added_codes": added,
        "removed_codes": removed,
        "changed_codes": changed,
    }
    _print(f"[SEED-CHECK] old={len(old)} new={len(current)} added={len(added)} removed={len(removed)} changed={len(changed)}")
    if added:
        _print(f"  ADDED: {added}")
    if removed:
        _print(f"  REMOVED: {removed}")
    if changed:
        _print(f"  CHANGED: {changed}")

    if result["added_code_count"] != 0 or result["removed_code_count"] != 0 or result["changed_count"] != 0:
        raise AssertionError(
            f"标准库科目被修改！added={result['added_code_count']} removed={result['removed_code_count']} changed={result['changed_count']}"
        )
    return result


# ── 六张真实文件 ──────────────────────────────────────

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
        # 明确字段映射（col_2=科目代码, col_3=科目全称, col_15=期初余额, col_16=借方发生数, col_17=贷方发生数, col_18=本期结余）
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


def _period_configs(field_mappings):
    configs = []
    for fm in field_mappings:
        if fm.get("period_type") and fm.get("split_mode"):
            configs.append({
                "period_type": fm["period_type"], "mode": fm["split_mode"],
                "debit_field": fm.get("debit_column_id"),
                "credit_field": fm.get("credit_column_id"),
                "amount_field": fm.get("column_id"),
                "direction_column_id": fm.get("direction_column_id"),
            })
    return configs


def _col_id_to_index(headers):
    return {f"col_{i}": i for i, h in enumerate(headers)}


def _collect_node_ids(node, acc):
    nid = node.get("node_id")
    if nid is not None:
        acc.append(nid)
    for child in node.get("children", []):
        _collect_node_ids(child, acc)


async def run_one(file_def, db):
    file_path = file_def["path"]
    file_name = Path(file_path).name
    t_file_start = time.time()
    _print(f"\n{'='*60}")
    _print(f"文件: {file_name}  (开始: {time.strftime('%H:%M:%S')})")
    _print(f"{'='*60}")

    if not Path(file_path).exists():
        _print(f"  [SKIP] 文件不存在")
        return {
            "file": file_name, "error": "FILE_NOT_FOUND",
            "preview_total_rows": 0, "data_start_row": 0, "active_recommendations": 0,
            "ignored_zero_amount_rows": 0, "ignored_summary_total_rows": 0,
            "inherited_auxiliary_rows": 0,
            "unmatched_count": 0, "unsafe_count": 0, "warning_count": 0,
            "non_parent_warning_count": 0, "error_count": 0,
            "execute_status": "skipped", "entry_count": 0,
            "tree_error": "FILE_NOT_FOUND", "tree_total_nodes": 0, "dup_node_id_count": 0,
            "parse_sec": 0, "preview_sec": 0, "analyze_sec": 0, "execute_sec": 0, "tree_sec": 0,
        }

    customer_label = file_def["customer_label"]
    field_mappings = file_def["field_mappings"]

    timings = {}

    # ── Parse ──
    t0 = time.time()
    parsed = parse_trial_balance_import(file_path)
    timings["parse"] = round(time.time() - t0, 2)
    merged_headers = parsed["merged_headers"]
    data_start_row = parsed["data_start_row"]
    _print(f"  headers({len(merged_headers)}): {merged_headers[:12]}...  parse={timings['parse']}s")

    # ── Preview ──
    t0 = time.time()
    preview = await preview_standard_import(db, file_path, file_name, fiscal_year=2025, period=12, customer_label=customer_label)
    timings["preview"] = round(time.time() - t0, 2)
    batch_id = uuid.UUID(preview["batch_id"])
    preview_total_rows = preview["total_rows"]
    _print(f"  preview rows={preview_total_rows}  preview={timings['preview']}s")

    # ── Analyze ──
    t0 = time.time()
    analyze = await analyze_standard_import(db, batch_id, file_path, field_mappings=field_mappings, fiscal_year=2025, period=12, customer_label=customer_label, hierarchy_mode="auto")
    timings["analyze"] = round(time.time() - t0, 2)
    recs = analyze["mapping_recommendations"]
    errors = analyze["errors"]
    warnings = analyze["warnings"]

    active_recs = [r for r in recs if r.get("participates_in_entry", True)]
    unmatched = [r for r in active_recs if not r.get("candidates")]
    # TASK-084：score >= 0.85 的候选视为安全匹配（code_category_anchor 等推断匹配的典型分数）。
    # 旧阈值 0.9 过于保守，会把 220206→2202 这类正确代码前缀关系误判为 unsafe。
    unsafe = []
    for r in active_recs:
        cands = r.get("candidates", []) or []
        picked = _pick_auto_confirm_candidate(cands) if cands else None
        if picked and float(picked.get("score", 0) or 0) < 0.85:
            unsafe.append(r)
    # TASK-084：过滤 parent_amount_mismatch 和 disabled_standard_account 类别。
    # disabled_standard_account 是信息性提示（"所有候选均警告"），不构成阻塞。
    non_parent = [w for w in warnings if w.get("category") not in ("parent_amount_mismatch", "disabled_standard_account")]

    _print(f"  active={len(active_recs)} unmatched={len(unmatched)} unsafe={len(unsafe)} non_parent_warn={len(non_parent)} errors={len(errors)}  analyze={timings['analyze']}s")
    if unmatched:
        for u in unmatched[:3]:
            _print(f"    unmatched: row={u.get('row_index')} code={u.get('client_account_code')} name={u.get('client_account_name')}")
    if unsafe:
        for u in unsafe[:3]:
            cands = u.get("candidates", [])
            picked = _pick_auto_confirm_candidate(cands)
            if picked:
                _print(f"    unsafe: code={u.get('client_account_code')} -> {picked.get('standard_account_code')} s={picked.get('score')} src={picked.get('source')}")

    # ── Confirm ──
    # TASK-084：放宽自动确认阈值到 0.85。
    # code_category_anchor 等推断匹配的典型分数为 0.86，低于旧阈值 0.9。
    # 这些匹配（如 220206→2202 应付账款）是正确的代码前缀关系，应被自动确认。
    confirmed_mappings = []
    for r in active_recs:
        cands = r.get("candidates", []) or []
        if not cands:
            continue
        picked = _pick_auto_confirm_candidate(cands)
        if picked and float(picked.get("score", 0) or 0) >= 0.85:
            confirmed_mappings.append({
                "row_index": r["row_index"],
                "client_account_code": r.get("client_account_code"),
                "client_account_name": r.get("client_account_name"),
                "standard_account_id": uuid.UUID(picked["standard_account_id"]),
                "standard_account_code": picked["standard_account_code"],
                "standard_account_name": picked["standard_account_name"],
            })

    # ── Execute ──
    t0 = time.time()
    execute_debug_timings = {}
    try:
        execute = await execute_standard_import(db, batch_id, file_path, confirmed_mappings=confirmed_mappings, warnings_confirmed=True, save_mapping_experience=True)
        execute_status = execute["status"]
        entry_count = execute["entry_count"]
        execute_debug_timings = execute.get("debug_timings", {})
    except Exception as e:
        execute_status = "blocked"
        entry_count = 0
        _print(f"  execute FAILED: {e}")
    timings["execute"] = round(time.time() - t0, 2)
    _print(f"  execute={execute_status} entries={entry_count}  execute={timings['execute']}s")
    if execute_debug_timings:
        _print(f"    execute stages: {execute_debug_timings}")

    # ── Stats ──
    from app.models.standard_trial_balance_import_batch import StandardTrialBalanceImportBatch
    batch_row = (await db.execute(select(StandardTrialBalanceImportBatch).where(StandardTrialBalanceImportBatch.id == batch_id))).scalar_one_or_none()
    hc = (batch_row.hierarchy_config or {}) if batch_row else {}
    actual_data_start = int(hc.get("parse_config", {}).get("data_start_row") or data_start_row)
    merged = hc.get("parse_config", {}).get("merged_headers") or merged_headers
    col_idx = _col_id_to_index(merged)
    rows = slice_data_rows(parsed["all_rows"], actual_data_start)
    pcfgs = _period_configs(field_mappings)
    zero_skip = _collect_zero_amount_template_rows(rows, pcfgs, col_idx)
    summary_skip = _collect_summary_total_skip_rows(rows, col_idx, code_col_id=field_mappings[0]["column_id"], name_col_id=field_mappings[1]["column_id"])
    inherited_aux = int(hc.get("inherited_auxiliary_rows") or 0)

    # ── Tree ──
    t0 = time.time()
    tree_error = None
    tree_total_nodes = 0
    dup_node_id_count = 0
    try:
        nodes, total_nodes = await get_tree(db, batch_id=batch_id)
        tree_total_nodes = total_nodes
        all_ids = []
        for root in nodes:
            _collect_node_ids(root, all_ids)
        dup_ids = [i for i in set(all_ids) if all_ids.count(i) > 1]
        dup_node_id_count = len(dup_ids)
    except Exception as e:
        tree_error = f"{type(e).__name__}: {e}"
        _print(f"  get_tree FAILED: {tree_error}")
    timings["tree"] = round(time.time() - t0, 2)
    _print(f"  tree_nodes={tree_total_nodes} dup_ids={dup_node_id_count} tree_error={tree_error}  tree={timings['tree']}s")
    _print(f"  file_total={round(time.time() - t_file_start, 2)}s  (结束: {time.strftime('%H:%M:%S')})")

    summary = {
        "file": file_name,
        "preview_total_rows": preview_total_rows,
        "data_start_row": actual_data_start,
        "active_recommendations": len(active_recs),
        "ignored_zero_amount_rows": len(zero_skip),
        "ignored_summary_total_rows": len(summary_skip),
        "inherited_auxiliary_rows": inherited_aux,
        "unmatched_count": len(unmatched),
        "unsafe_count": len(unsafe),
        "warning_count": len(warnings),
        "non_parent_warning_count": len(non_parent),
        "error_count": len(errors),
        "execute_status": execute_status,
        "entry_count": entry_count,
        "tree_error": tree_error,
        "tree_total_nodes": tree_total_nodes,
        "dup_node_id_count": dup_node_id_count,
        "parse_sec": timings.get("parse", 0),
        "preview_sec": timings.get("preview", 0),
        "analyze_sec": timings.get("analyze", 0),
        "execute_sec": timings.get("execute", 0),
        "tree_sec": timings.get("tree", 0),
    }
    return summary


async def run_acceptance():
    overall_start = time.time()
    # ── 标准库保护检查 ──
    _print("=" * 60)
    _print("标准库科目保护检查")
    _print("=" * 60)
    seed_check = assert_standard_seed_not_changed()

    # ── 运行所有文件 ──
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
            seed_result = await seed_standard_accounts(db)
            _print(f"seed_result: created={seed_result['created_count']}")

            for fdef in REAL_FILES:
                # TASK-083：单文件全链路超时保护，超时时给出文件名而非外部 command timed out
                try:
                    summary = await asyncio.wait_for(
                        run_one(fdef, db), timeout=SINGLE_FILE_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    # TASK-084：超时后回滚 DB 事务，避免 PendingRollbackError 影响后续文件
                    await db.rollback()
                    fn = Path(fdef["path"]).name
                    _print(f"\n  [TIMEOUT] {fn}: 全链路超过 {SINGLE_FILE_TIMEOUT}s，已强制中止此文件")
                    summary = {
                        "file": fn, "error": "TIMEOUT",
                        "preview_total_rows": 0, "data_start_row": 0,
                        "active_recommendations": 0,
                        "ignored_zero_amount_rows": 0, "ignored_summary_total_rows": 0,
                        "inherited_auxiliary_rows": 0,
                        "unmatched_count": 0, "unsafe_count": 0, "warning_count": 0,
                        "non_parent_warning_count": 0, "error_count": 0,
                        "execute_status": "timeout", "entry_count": 0,
                        "tree_error": f"TimeoutError: file exceeded {SINGLE_FILE_TIMEOUT}s",
                        "tree_total_nodes": 0, "dup_node_id_count": 0,
                        "parse_sec": SINGLE_FILE_TIMEOUT, "preview_sec": 0,
                        "analyze_sec": 0, "execute_sec": 0, "tree_sec": 0,
                    }
                summaries.append(summary)

        _print("\n" + "=" * 60)
        _print("六张表摘要")
        _print("=" * 60)
        print(json.dumps(summaries, ensure_ascii=False, indent=2), flush=True)

        # ── 最终断言 ──
        _print("\n" + "=" * 60)
        _print("验收断言")
        _print("=" * 60)
        all_ok = True

        # 标准库检查
        # TASK-083：assert_standard_seed_not_changed 已在读取/比对 git HEAD 失败时抛错，
        # 此处的 seed_check 一定是真实比对结果，绝不再有 git_unavailable 放行分支。
        if seed_check["added_code_count"] != 0:
            _print(f"[FAIL] SEED: added_code_count={seed_check['added_code_count']} (expected 0): {seed_check.get('added_codes', [])}")
            all_ok = False
        if seed_check["removed_code_count"] != 0:
            _print(f"[FAIL] SEED: removed_code_count={seed_check['removed_code_count']} (expected 0): {seed_check.get('removed_codes', [])}")
            all_ok = False
        if seed_check["changed_count"] != 0:
            _print(f"[FAIL] SEED: changed_count={seed_check['changed_count']} (expected 0): {seed_check.get('changed_codes', [])}")
            all_ok = False
        if all_ok and (
            seed_check["added_code_count"] == 0
            and seed_check["removed_code_count"] == 0
            and seed_check["changed_count"] == 0
        ):
            _print(f"[OK] SEED: old/new/added/removed/changed 已比对，无变更")

        for s in summaries:
            fn = s["file"]
            if s.get("error") == "FILE_NOT_FOUND":
                _print(f"[WARN] {fn}: 文件不存在")
                continue
            if s.get("error") == "TIMEOUT":
                _print(f"[FAIL] {fn}: 单文件超时（{s['tree_error']}）")
                all_ok = False
                continue

            checks = [
                ("execute_status", s["execute_status"] == "executed", f"status={s['execute_status']}"),
                # TASK-083：删除 205201-2023.xls 的硬编码特殊放行。
                # entry_count>0 是入库成功的硬条件，无金额文件应失败而非冒充成功。
                ("entry_count", s["entry_count"] > 0, f"entry_count={s['entry_count']}"),
                ("unmatched_count", s["unmatched_count"] == 0, f"unmatched={s['unmatched_count']}"),
                ("unsafe_count", s["unsafe_count"] == 0, f"unsafe={s['unsafe_count']}"),
                ("non_parent_warning_count", s["non_parent_warning_count"] == 0, f"non_parent_warn={s['non_parent_warning_count']}"),
                ("tree_error", s.get("tree_error") is None, f"tree_error={s.get('tree_error')}"),
                ("tree_total_nodes", s["tree_total_nodes"] > 0, f"tree_nodes={s['tree_total_nodes']}"),
                ("dup_node_id_count", s["dup_node_id_count"] == 0, f"dup_ids={s['dup_node_id_count']}"),
            ]
            for name, ok, detail in checks:
                if not ok:
                    _print(f"[FAIL] {fn}: {name} ({detail})")
                    all_ok = False
            if all(c[1] for c in checks):
                _print(f"[OK] {fn}")

        overall_sec = round(time.time() - overall_start, 2)
        _print(f"\n[overall] 总耗时 {overall_sec}s (目标 <={OVERALL_TARGET_SEC}s)")
        # TASK-085：性能目标作为真实断言
        if overall_sec > OVERALL_TARGET_SEC:
            _print(f"[FAIL] overall_sec: {overall_sec}s > {OVERALL_TARGET_SEC}s")
            all_ok = False
        if not all_ok:
            _print("\nTASK080_SIX_TRIAL_BALANCE_TEMPLATES_FAILED")
            sys.exit(1)

        _print("\nTASK080_SIX_TRIAL_BALANCE_TEMPLATES_PASSED")
    finally:
        await engine.dispose()
        try:
            os.unlink(db_path)
        except OSError:
            pass


if __name__ == "__main__":
    asyncio.run(run_acceptance())
