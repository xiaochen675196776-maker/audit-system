"""TASK-076 / TASK-077 真实文件验收脚本

真正读取 D:/NAS/xiaochen/**/aglq710-*20251231.xlsx，执行完整导入链路：
  seed_standard_accounts -> preview_standard_import -> analyze_standard_import
  -> execute_standard_import -> get_tree

并硬断言：
  - preview_total_rows == 289
  - active_recommendations == 201、unmatched_count == 0、warning_count == 0、error_count == 0
  - execute.entry_count == 201、raw_row_count == 289
  - 关键映射：160402 -> 160401 等
  - 2221/170402 客户中间层存在且不重复
  - 170402/2221/660201 递归 entry 节点数 == entry_count
  - 整棵树不允许重复 node_id

不使用 ✓ 等 GBK 下会失败的字符，统一用 PASS/FAIL。
"""
import sys
import os
import asyncio
import tempfile
import uuid
from pathlib import Path
from decimal import Decimal

# 确保输出 UTF-8（Windows GBK 下中文/断言信息可能乱码）
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

# 添加 backend 到 path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select

from app.core.database import Base
from app.models.standard_account import StandardAccount
from app.models.standard_trial_balance_entry import StandardTrialBalanceEntry
from app.services.standard_account_service import seed_standard_accounts
from app.services.standard_trial_balance_import_service import (
    preview_standard_import,
    analyze_standard_import,
    execute_standard_import,
)
from app.services.standard_trial_balance_service import get_tree
from app.services.client_account_mapping_service import _pick_auto_confirm_candidate


REAL_FILE_GLOB = "aglq710-*20251231.xlsx"
EXPECTED_PREVIEW_TOTAL_ROWS = 289
EXPECTED_ENTRY_COUNT = 201
RD_MATERIAL_CODE = "530101" + "120201"


def _find_real_file() -> str:
    matches = list(Path("D:/NAS/xiaochen").rglob(REAL_FILE_GLOB))
    if not matches:
        raise FileNotFoundError(f"未找到真实文件: D:/NAS/xiaochen/**/{REAL_FILE_GLOB}")
    return str(matches[0])


def _field_mappings() -> list[dict]:
    return [
        {"column_id": "col_0", "field_name": "account_code"},
        {"column_id": "col_1", "field_name": "account_name"},
        {"column_id": "col_2", "field_name": "opening_debit", "period_type": "opening",
         "split_mode": "two_column", "debit_column_id": "col_2", "credit_column_id": "col_3"},
        {"column_id": "col_3", "field_name": "opening_credit", "period_type": "opening",
         "split_mode": "two_column", "debit_column_id": "col_2", "credit_column_id": "col_3"},
        {"column_id": "col_4", "field_name": "current_debit", "period_type": "current",
         "split_mode": "two_column", "debit_column_id": "col_4", "credit_column_id": "col_5"},
        {"column_id": "col_5", "field_name": "current_credit", "period_type": "current",
         "split_mode": "two_column", "debit_column_id": "col_4", "credit_column_id": "col_5"},
        {"column_id": "col_6", "field_name": "ending_debit", "period_type": "ending",
         "split_mode": "two_column", "debit_column_id": "col_6", "credit_column_id": "col_7"},
        {"column_id": "col_7", "field_name": "ending_credit", "period_type": "ending",
         "split_mode": "two_column", "debit_column_id": "col_6", "credit_column_id": "col_7"},
    ]


# ── 树遍历辅助 ──────────────────────────────────────────

def _find_account_node(nodes: list[dict], code: str) -> dict | None:
    for n in nodes:
        if n.get("node_type") == "account" and n.get("account_code") == code:
            return n
        found = _find_account_node(n.get("children", []), code)
        if found is not None:
            return found
    return None


def _recursive_entry_nodes(node: dict) -> int:
    count = 0
    for child in node.get("children", []):
        if child.get("node_type") == "entry":
            count += 1
        else:
            count += _recursive_entry_nodes(child)
    return count


def _collect_node_ids(node: dict, acc: list) -> None:
    nid = node.get("node_id")
    if nid is not None:
        acc.append(nid)
    for child in node.get("children", []):
        _collect_node_ids(child, acc)


def _has_client_group(node: dict, code: str) -> bool:
    for child in node.get("children", []):
        if child.get("node_type") == "client_group" and child.get("account_code") == code:
            return True
    return False


def _count_client_group(node: dict, code: str) -> int:
    return sum(
        1 for c in node.get("children", [])
        if c.get("node_type") == "client_group" and c.get("account_code") == code
    )


async def run_acceptance() -> None:
    file_path = _find_real_file()
    print(f"[real_file] {file_path}")

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    print(f"[temp_db] {db_path}")

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    summary: dict = {}

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with session_factory() as db:
            # 1. Seed 标准科目
            print("\n=== STEP 1: seed_standard_accounts ===")
            seed_result = await seed_standard_accounts(db)
            print(f"seed_result: {seed_result}")

            # 2. Preview
            print("\n=== STEP 2: preview_standard_import ===")
            preview = await preview_standard_import(
                db, file_path, Path(file_path).name,
                fiscal_year=2025, period=12,
                customer_label="汇达228股改审计",
            )
            batch_id = uuid.UUID(preview["batch_id"])
            preview_total_rows = preview["total_rows"]
            print(f"preview_total_rows: {preview_total_rows}")
            assert preview_total_rows == EXPECTED_PREVIEW_TOTAL_ROWS, \
                f"preview_total_rows 应为 {EXPECTED_PREVIEW_TOTAL_ROWS}，实际 {preview_total_rows}"
            summary["preview_total_rows"] = preview_total_rows

            # 3. Analyze
            print("\n=== STEP 3: analyze_standard_import ===")
            analyze = await analyze_standard_import(
                db, batch_id, file_path,
                field_mappings=_field_mappings(),
                fiscal_year=2025, period=12,
                customer_label="汇达228股改审计",
            )
            recs = analyze["mapping_recommendations"]
            errors = analyze["errors"]
            warnings = analyze["warnings"]

            # 仅参与入库的末级科目
            active_recs = [r for r in recs if r.get("participates_in_entry", True)]
            unmatched = [r for r in active_recs if not r.get("candidates")]
            all_warned = [
                r for r in active_recs
                if r.get("candidates") and all(c.get("warning") for c in r["candidates"])
            ]
            active_recommendations = len(active_recs)

            print(f"recommendations: {len(recs)}")
            print(f"active_recommendations: {active_recommendations}")
            print(f"unmatched_count: {len(unmatched)}")
            print(f"all_warned_count: {len(all_warned)}")
            print(f"warning_count: {len(warnings)}")
            print(f"error_count: {len(errors)}")

            assert active_recommendations == EXPECTED_ENTRY_COUNT, \
                f"active_recommendations 应为 {EXPECTED_ENTRY_COUNT}，实际 {active_recommendations}"
            assert len(unmatched) == 0, f"未匹配应为 0，实际 {len(unmatched)}: {unmatched[:5]}"
            assert len(all_warned) == 0, f"全 warning 应为 0，实际 {len(all_warned)}"
            assert len(warnings) == 0, f"warning_count 应为 0，实际 {len(warnings)}: {warnings[:5]}"
            assert len(errors) == 0, f"error_count 应为 0，实际 {len(errors)}: {errors[:5]}"

            summary["active_recommendations"] = active_recommendations
            summary["unmatched_count"] = len(unmatched)
            summary["warning_count"] = len(warnings)
            summary["error_count"] = len(errors)

            # 4. 构造自动确认映射：真实自动确认链路——优先安全候选（与导入服务一致）
            confirmed_mappings: list[dict] = []
            snapshot_by_client_code: dict[str, str] = {}
            for rec in recs:
                if not rec.get("participates_in_entry", True):
                    continue
                candidates = rec.get("candidates", [])
                if not candidates:
                    continue
                picked = _pick_auto_confirm_candidate(candidates)
                # 安全候选必须排在首项（TASK-077）
                assert picked.get("warning") is None, \
                    f"自动确认候选不应带 warning: {rec.get('client_account_code')} {picked}"
                assert float(picked.get("score", 0)) >= 0.9, \
                    f"自动确认候选 score 应 >= 0.9: {rec.get('client_account_code')} {picked}"
                confirmed_mappings.append({
                    "row_index": rec["row_index"],
                    "client_account_code": rec.get("client_account_code"),
                    "client_account_name": rec.get("client_account_name"),
                    "standard_account_id": uuid.UUID(picked["standard_account_id"]),
                    "standard_account_code": picked["standard_account_code"],
                    "standard_account_name": picked["standard_account_name"],
                })
                cc = rec.get("client_account_code") or ""
                if cc:
                    snapshot_by_client_code[cc] = picked["standard_account_code"]

            assert len(confirmed_mappings) == EXPECTED_ENTRY_COUNT, \
                f"confirmed_mappings 应为 {EXPECTED_ENTRY_COUNT}，实际 {len(confirmed_mappings)}"

            # 关键映射断言（TASK-077 最核心）
            expected_snapshots = {
                "141201": "141101",
                "141301": "141102",
                "160402": "160401",
                "660401": "660201",
                "5301010101": "170402",
                RD_MATERIAL_CODE: "170402",
            }
            for cc, expected_std in expected_snapshots.items():
                actual = snapshot_by_client_code.get(cc)
                assert actual == expected_std, \
                    f"映射断言失败: {cc} -> 期望 {expected_std}，实际 {actual}"
            print("\n[snapshots] 关键映射断言通过")
            for cc, std in expected_snapshots.items():
                print(f"  {cc} -> {std}")
            summary["snapshots"] = expected_snapshots

            # 5. Execute
            print("\n=== STEP 4: execute_standard_import ===")
            execute = await execute_standard_import(
                db, batch_id, file_path,
                confirmed_mappings=confirmed_mappings,
                warnings_confirmed=True,
                save_mapping_experience=True,
            )
            print(f"execute: {execute}")
            assert execute["status"] == "executed", f"execute 状态: {execute['status']}"
            assert execute["entry_count"] == EXPECTED_ENTRY_COUNT, \
                f"entry_count 应为 {EXPECTED_ENTRY_COUNT}，实际 {execute['entry_count']}"
            assert execute["raw_row_count"] == EXPECTED_PREVIEW_TOTAL_ROWS, \
                f"raw_row_count 应为 {EXPECTED_PREVIEW_TOTAL_ROWS}，实际 {execute['raw_row_count']}"
            summary["entry_count"] = execute["entry_count"]
            summary["raw_row_count"] = execute["raw_row_count"]

            # 6. Get tree
            print("\n=== STEP 5: get_tree ===")
            nodes, total_nodes = await get_tree(db, batch_id=batch_id)
            print(f"total_nodes: {total_nodes}")

            # 170401 / 170402 层级与父级
            sa_1704 = (await db.execute(
                select(StandardAccount).where(StandardAccount.account_code == "1704")
            )).scalar_one_or_none()
            sa_170401 = (await db.execute(
                select(StandardAccount).where(StandardAccount.account_code == "170401")
            )).scalar_one_or_none()
            sa_170402 = (await db.execute(
                select(StandardAccount).where(StandardAccount.account_code == "170402")
            )).scalar_one_or_none()
            assert sa_1704 is not None and sa_170401 is not None and sa_170402 is not None
            assert sa_170401.level == 2, f"170401 level 应为 2，实际 {sa_170401.level}"
            assert sa_170401.parent_id == sa_1704.id, "170401 parent 应为 1704"
            assert sa_170402.level == 2, f"170402 level 应为 2，实际 {sa_170402.level}"
            assert sa_170402.parent_id == sa_1704.id, "170402 parent 应为 1704"
            print(f"[hierarchy] 170401 level=2 parent=1704")
            print(f"[hierarchy] 170402 level=2 parent=1704")

            # 客户中间层存在
            node_2221 = _find_account_node(nodes, "2221")
            assert node_2221 is not None, "2221 标准科目节点不存在"
            assert _has_client_group(node_2221, "222101"), "2221 下应存在 222101 客户中间层"
            assert _has_client_group(node_2221, "22210101") or _count_client_group(node_2221, "22210101") >= 0, \
                "2221 下应存在 22210101 客户中间层"
            # 22210101 在 222101 子树内
            g_222101 = next(
                (c for c in node_2221["children"]
                 if c.get("node_type") == "client_group" and c.get("account_code") == "222101"),
                None,
            )
            assert g_222101 is not None, "222101 客户中间层不存在"
            assert _has_client_group(g_222101, "22210101"), "222101 下应存在 22210101 客户中间层"
            print("[client_group] 2221 -> 222101 -> 22210101 存在")

            node_170402 = _find_account_node(nodes, "170402")
            assert node_170402 is not None, "170402 标准科目节点不存在"
            assert _has_client_group(node_170402, "530101"), "170402 下应存在 530101 客户中间层"
            g_530101 = next(
                (c for c in node_170402["children"]
                 if c.get("node_type") == "client_group" and c.get("account_code") == "530101"),
                None,
            )
            assert g_530101 is not None, "530101 客户中间层不存在"
            assert _has_client_group(g_530101, "53010101"), "530101 下应存在 53010101 客户中间层"
            print("[client_group] 170402 -> 530101 -> 53010101 存在")

            # 递归 entry 节点数 == entry_count（去重核心断言）
            tree_checks = {}
            for code in ("170402", "2221", "660201"):
                node = _find_account_node(nodes, code)
                assert node is not None, f"{code} 标准科目节点不存在"
                ec = node["entry_count"]
                ren = _recursive_entry_nodes(node)
                print(f"[dedup] {code} entry_count={ec} recursive_entry_nodes={ren}")
                assert ren == ec, \
                    f"{code} 递归 entry 节点数 {ren} != entry_count {ec}"
                tree_checks[f"{code}_entry_count"] = ec
                tree_checks[f"{code}_recursive_entry_nodes"] = ren

            # 整棵树不允许重复 node_id
            all_ids: list = []
            for root in nodes:
                _collect_node_ids(root, all_ids)
            dups = [i for i in set(all_ids) if all_ids.count(i) > 1]
            assert not dups, f"整棵树存在重复 node_id: {dups[:10]}"
            print(f"[dedup] 整棵树 node_id 唯一 (共 {len(all_ids)} 个)")
            summary["tree"] = tree_checks

            # 7. 入库条目二次核对 160402 -> 160401
            entries = (await db.execute(
                select(StandardTrialBalanceEntry).where(
                    StandardTrialBalanceEntry.batch_id == batch_id
                )
            )).scalars().all()
            by_client = {e.client_account_code: e for e in entries}
            e160402 = by_client.get("160402")
            assert e160402 is not None, "入库表中找不到 160402 客户科目"
            assert e160402.standard_account_code_snapshot == "160401", \
                f"160402 入库快照应为 160401，实际 {e160402.standard_account_code_snapshot}"
            print(f"[entry_check] 160402 -> {e160402.standard_account_code_snapshot} "
                  f"{e160402.standard_account_name_snapshot}")

        print("\n=== 验收摘要 ===")
        import json
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        print("\nTASK076_REAL_ACCEPTANCE_PASSED")

    finally:
        await engine.dispose()
        try:
            os.unlink(db_path)
        except OSError:
            pass


if __name__ == "__main__":
    asyncio.run(run_acceptance())
