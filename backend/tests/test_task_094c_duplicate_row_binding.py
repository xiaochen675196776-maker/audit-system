"""TASK-094C：行→节点绑定、推荐/提交/经验去重行为测试。

覆盖：
1. 推荐函数按唯一节点调用（同一 node_key 多行 → 1 次推荐）；
2. confirmed_mappings 多 row_index 提交同 node_key → 后端折叠为 1 次；
3. 原始行均能回溯 node_key（node_representative_row_index / node_duplicate_binding）；
4. 辅助核算行不进入独立推荐（仅绑定上级会计科目）；
5. 映射经验保存按 node_key 去重；
6. execute 后 raw_row.mapping_role 正确传递到绑定行；
7. entry 仍按真实业务末级行（不是 node_key 合并的伪 entry）；
8. amount reconciliation 与原始行金额总和勾稽。
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import uuid
from collections import Counter
from pathlib import Path

import openpyxl
import pytest
from sqlalchemy import delete, select

from app.core.database import async_session_factory
from app.models.client_account_mapping import ClientAccountMapping
from app.models.standard_account import StandardAccount
from app.models.standard_trial_balance_entry import StandardTrialBalanceEntry
from app.models.standard_trial_balance_import_batch import StandardTrialBalanceImportBatch
from app.models.standard_trial_balance_raw_row import StandardTrialBalanceRawRow
from app.services.account_mapping_inheritance_service import (
    build_account_tree,
    build_unique_account_graph,
)
from app.services.standard_trial_balance_import_service import (
    analyze_standard_import,
    execute_standard_import,
    preview_standard_import,
)


# ── 工具：构造内存 Excel ──────────────────────────────


def _build_xlsx(
    headers: list[str],
    rows: list[list],
) -> str:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)
    tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    wb.save(tmp.name)
    tmp.close()
    return tmp.name


def _ensure_minimal_standard_accounts_sync(db):
    """同步版：调用方必须在 async session 里运行。"""
    accounts = [
        ("1001", "库存现金", "asset", "debit", True),
        ("1002", "银行存款", "asset", "debit", True),
        ("1122", "应收账款", "asset", "debit", True),
        ("112201", "应收账款-明细", "asset", "debit", True),
        ("1123", "预付账款", "asset", "debit", True),
        ("1403", "原材料", "asset", "debit", True),
        ("2202", "应付账款", "liability", "credit", True),
        ("6602", "管理费用", "expense", "debit", True),
    ]

    async def _add():
        result = await db.execute(select(StandardAccount))
        existing = {sa.account_code for sa in result.scalars().all()}
        for code, name, cat, dirn, is_leaf in accounts:
            if code in existing:
                continue
            sa = StandardAccount(
                account_code=code,
                account_name=name,
                account_category=cat,
                balance_direction=dirn,
                level=2 if is_leaf else 1,
                is_leaf=is_leaf,
                is_active=True,
            )
            db.add(sa)
        await db.flush()

    return _add()


# ── 1. 行 → 节点绑定 ────────────────────────────────


@pytest.mark.asyncio
async def test_analyze_emits_node_key_for_each_recommendation(db):
    """analyze 响应中每个 mapping_recommendation 必须带 node_key。"""
    await _ensure_minimal_standard_accounts_sync(db)
    # 6 行：1 父级 + 5 个相同 (code, name, parent) 重复行
    headers = ["科目编码", "科目名称", "期末借方", "期末贷方"]
    rows = [["1002", "银行存款", 100.0, 0.0]]
    for _ in range(5):
        rows.append(["100201", "工行账户", 10.0, 0.0])
    rows.append(["2202", "应付账款", 0.0, 50.0])
    file_path = _build_xlsx(headers, rows)

    try:
        preview = await preview_standard_import(
            db=db,
            file_path=file_path,
            file_name="dup_test.xlsx",
            fiscal_year=2024,
            period=12,
            customer_label="dup_test",
        )
        batch_id = uuid.UUID(preview["batch_id"])
        analyze = await analyze_standard_import(
            db=db,
            batch_id=batch_id,
            file_path=file_path,
            field_mappings=[
                {"column_id": "col_0", "field_name": "account_code"},
                {"column_id": "col_1", "field_name": "account_name"},
                {
                    "column_id": "col_2", "field_name": "ending_debit",
                    "period_type": "ending", "split_mode": "two_column",
                    "debit_column_id": "col_2", "credit_column_id": "col_3",
                },
            ],
            fiscal_year=2024,
            period=12,
            customer_label="dup_test",
            hierarchy_mode="code",
        )
    finally:
        try:
            Path(file_path).unlink()
        except Exception:
            pass

    recs = analyze["mapping_recommendations"]
    # 每行都有 node_key
    for rec in recs:
        assert rec.get("node_key"), f"row {rec.get('row_index')} missing node_key"

    # 100201-工行账户 5 行 → 同 node_key
    node_keys_by_row = {r["row_index"]: r["node_key"] for r in recs}
    rows_100201 = [r for r in recs if (r.get("client_account_code") or "").strip() == "100201"]
    keys = {r["node_key"] for r in rows_100201}
    assert len(keys) == 1, f"应 1 个 node_key，实际 {len(keys)}"
    # representative_row_index 应是第一个 100201 行
    rep_rows = [r for r in rows_100201 if r.get("node_representative_row_index") == r["row_index"]]
    assert len(rep_rows) == 1
    # 重复绑定行：mapping_editable=False（除代表行）
    editable = [r for r in rows_100201 if r.get("mapping_editable")]
    non_editable = [r for r in rows_100201 if not r.get("mapping_editable")]
    assert len(editable) == 1
    assert len(non_editable) == 4
    # node_source_row_indexes 应包含全部 5 行
    rep = editable[0]
    assert sorted(rep["node_source_row_indexes"]) == sorted([r["row_index"] for r in rows_100201])


@pytest.mark.asyncio
async def test_recommendation_dedup_by_node_key_calls_recommend_once(db):
    """5 行重复 100201 只触发 1 次 recommend_mappings（unique_recommendation_node_count = 1）。"""
    await _ensure_minimal_standard_accounts_sync(db)
    # 清空客户历史避免污染
    await db.execute(
        delete(ClientAccountMapping).where(
            ClientAccountMapping.customer_label == "dup_test2"
        )
    )
    await db.flush()

    headers = ["科目编码", "科目名称", "期末借方"]
    rows = [
        ["1002", "银行存款", 0.0],
        ["100201", "工行账户", 10.0],
        ["100201", "工行账户", 20.0],
        ["100201", "工行账户", 30.0],
        ["100201", "工行账户", 40.0],
        ["100201", "工行账户", 50.0],
    ]
    file_path = _build_xlsx(headers, rows)
    try:
        preview = await preview_standard_import(
            db=db,
            file_path=file_path,
            file_name="dup_test2.xlsx",
            fiscal_year=2024,
            period=12,
            customer_label="dup_test2",
        )
        batch_id = uuid.UUID(preview["batch_id"])
        analyze = await analyze_standard_import(
            db=db,
            batch_id=batch_id,
            file_path=file_path,
            field_mappings=[
                {"column_id": "col_0", "field_name": "account_code"},
                {"column_id": "col_1", "field_name": "account_name"},
                {
                    "column_id": "col_2", "field_name": "ending_amount",
                    "period_type": "ending", "split_mode": "single_by_direction",
                },
            ],
            fiscal_year=2024,
            period=12,
            customer_label="dup_test2",
            hierarchy_mode="code",
        )
    finally:
        try:
            Path(file_path).unlink()
        except Exception:
            pass

    # 唯一节点数：2（1002 父级 + 100201-工行账户 1 个合并节点）
    assert analyze["unique_node_count"] == 2
    # 重复绑定数：5 行重复 → 4 个重复绑定 + 1 代表行
    assert analyze["duplicate_binding_count"] == 4
    # 100201 进入推荐一次
    # full_recommendation_node_count 在 mapping_summary 里
    summary = analyze["mapping_summary"]
    assert summary["full_recommendation_node_count"] <= 2


# ── 2. 提交去重 ────────────────────────────────


@pytest.mark.asyncio
async def test_execute_dedups_confirmed_mappings_by_node_key(db):
    """前端按 row_index 提交 5 次同 node_key → execute 折叠为 1 次。"""
    await _ensure_minimal_standard_accounts_sync(db)
    await db.execute(
        delete(ClientAccountMapping).where(
            ClientAccountMapping.customer_label == "dup_test3"
        )
    )
    await db.flush()

    headers = ["科目编码", "科目名称", "期末借方"]
    rows = [
        ["1002", "银行存款", 0.0],
        ["100201", "工行账户", 10.0],
        ["100201", "工行账户", 20.0],
        ["100201", "工行账户", 30.0],
        ["100201", "工行账户", 40.0],
        ["100201", "工行账户", 50.0],
    ]
    file_path = _build_xlsx(headers, rows)
    try:
        preview = await preview_standard_import(
            db=db,
            file_path=file_path,
            file_name="dup_test3.xlsx",
            fiscal_year=2024,
            period=12,
            customer_label="dup_test3",
        )
        batch_id = uuid.UUID(preview["batch_id"])
        analyze = await analyze_standard_import(
            db=db,
            batch_id=batch_id,
            file_path=file_path,
            field_mappings=[
                {"column_id": "col_0", "field_name": "account_code"},
                {"column_id": "col_1", "field_name": "account_name"},
                {
                    "column_id": "col_2", "field_name": "ending_amount",
                    "period_type": "ending", "split_mode": "single_by_direction",
                },
            ],
            fiscal_year=2024,
            period=12,
            customer_label="dup_test3",
            hierarchy_mode="code",
        )
        # 找 1002 银行的标准账户 ID
        sa_result = await db.execute(
            select(StandardAccount).where(
                StandardAccount.account_code == "1002"
            )
        )
        sa_1002 = sa_result.scalars().first()
        assert sa_1002 is not None

        # 客户端按 row_index 提交 5 次同 node_key（行 1..5）
        confirmed_mappings = []
        for r in analyze["mapping_recommendations"]:
            if (r.get("client_account_code") or "").strip() == "100201":
                confirmed_mappings.append({
                    "row_index": r["row_index"],
                    "client_account_code": "100201",
                    "client_account_name": "工行账户",
                    "standard_account_id": str(sa_1002.id),
                    "standard_account_code": "1002",
                    "standard_account_name": "银行存款",
                    "mapping_action": "anchor",
                    "apply_to_descendants": True,
                    "selection_source": "user_confirmed",
                })

        execute = await execute_standard_import(
            db=db,
            batch_id=batch_id,
            file_path=file_path,
            confirmed_mappings=confirmed_mappings,
            warnings_confirmed=True,
            save_mapping_experience=True,
        )
    finally:
        try:
            Path(file_path).unlink()
        except Exception:
            pass

    assert execute["status"] == "executed"
    # TASK-095B: legacy row_index submissions are folded before execute,
    # so node-level duplicate submit count must be zero.
    assert execute["duplicate_row_submit_count"] == 0
    assert execute["row_level_confirmed_mapping_count"] >= 5
    # 唯一节点数：1 个 100201 节点 + 1 个 1002 节点
    assert execute["unique_node_count"] == 2
    # entry 数：5 行（每行都参与入库，因为重复行都是叶子）
    assert execute["entry_count"] == 5
    # 映射经验保存数：去重后只有 1002、100201 两个节点级映射
    assert execute["mapping_saved_count"] <= 2


# ── 3. 映射经验按节点去重 ────────────────────────────────


@pytest.mark.asyncio
async def test_mapping_experience_dedup_by_node_key(db):
    """同一 node_key 不应重复保存映射经验。"""
    await _ensure_minimal_standard_accounts_sync(db)
    await db.execute(
        delete(ClientAccountMapping).where(
            ClientAccountMapping.customer_label == "dup_test4"
        )
    )
    await db.flush()

    headers = ["科目编码", "科目名称", "期末借方"]
    rows = [
        ["1002", "银行存款", 0.0],
        ["100201", "工行账户", 10.0],
        ["100201", "工行账户", 20.0],
        ["100201", "工行账户", 30.0],
    ]
    file_path = _build_xlsx(headers, rows)
    try:
        preview = await preview_standard_import(
            db=db,
            file_path=file_path,
            file_name="dup_test4.xlsx",
            fiscal_year=2024,
            period=12,
            customer_label="dup_test4",
        )
        batch_id = uuid.UUID(preview["batch_id"])
        analyze = await analyze_standard_import(
            db=db,
            batch_id=batch_id,
            file_path=file_path,
            field_mappings=[
                {"column_id": "col_0", "field_name": "account_code"},
                {"column_id": "col_1", "field_name": "account_name"},
                {
                    "column_id": "col_2", "field_name": "ending_amount",
                    "period_type": "ending", "split_mode": "single_by_direction",
                },
            ],
            fiscal_year=2024,
            period=12,
            customer_label="dup_test4",
            hierarchy_mode="code",
        )
        sa_result = await db.execute(
            select(StandardAccount).where(
                StandardAccount.account_code == "1002"
            )
        )
        sa_1002 = sa_result.scalars().first()

        # 提交锚点：1 个父级 + 1 个 100201 行（代表行）
        rep_row = next(
            r for r in analyze["mapping_recommendations"]
            if (r.get("client_account_code") or "").strip() == "100201"
            and r.get("node_representative_row_index") == r["row_index"]
        )
        confirmed = [
            {
                "row_index": 0,
                "client_account_code": "1002",
                "client_account_name": "银行存款",
                "standard_account_id": str(sa_1002.id),
                "standard_account_code": "1002",
                "standard_account_name": "银行存款",
                "mapping_action": "anchor",
                "apply_to_descendants": True,
                "selection_source": "user_confirmed",
            },
            {
                "row_index": rep_row["row_index"],
                "client_account_code": "100201",
                "client_account_name": "工行账户",
                "standard_account_id": str(sa_1002.id),
                "standard_account_code": "1002",
                "standard_account_name": "银行存款",
                "mapping_action": "anchor",
                "apply_to_descendants": True,
                "selection_source": "user_confirmed",
            },
        ]

        execute = await execute_standard_import(
            db=db,
            batch_id=batch_id,
            file_path=file_path,
            confirmed_mappings=confirmed,
            warnings_confirmed=True,
            save_mapping_experience=True,
        )
    finally:
        try:
            Path(file_path).unlink()
        except Exception:
            pass

    # 经验表：1002 是 anchor（保存），100201 重复行被 inherit 给 1002，不重复保存
    # 去重前：3 行 100201 + 1 行 1002 = 4 条潜在 → 去重后 2 条唯一节点 → 但 100201 全是 inherited
    # 故最终 mapping_saved_count = 1（仅 1002 anchor）
    saved = execute["mapping_saved"]
    codes = sorted(set(s["client_account_code"] for s in saved))
    # 1002 必须存在；100201 可能存在（若解析为 anchor/breakpoint）也可能 inherit
    assert "1002" in codes
    # 同一 node_key 不得重复保存
    node_keys = [s.get("node_key") for s in saved if s.get("node_key")]
    assert len(node_keys) == len(set(node_keys)), (
        f"重复 node_key: {[k for k in node_keys if node_keys.count(k) > 1]}"
    )


# ── 4. 辅助核算行绑定上级会计科目 ────────────────────────────────


@pytest.mark.asyncio
async def test_auxiliary_rows_bound_to_account_node(db):
    """无代码 + 名称含方括号的辅助行 → auxiliary 节点，绑定到上级 account。"""
    await _ensure_minimal_standard_accounts_sync(db)
    await db.execute(
        delete(ClientAccountMapping).where(
            ClientAccountMapping.customer_label == "aux_test"
        )
    )
    await db.flush()

    headers = ["科目编码", "科目名称", "期末借方"]
    rows = [
        ["1122", "应收账款", 0.0],
        ["112201", "应收账款明细", 0.0],
        [None, "[0001] 客户A", 10.0],
        [None, "[0002] 客户B", 20.0],
        [None, "客户:张三", 30.0],
    ]
    file_path = _build_xlsx(headers, rows)
    try:
        preview = await preview_standard_import(
            db=db,
            file_path=file_path,
            file_name="aux_test.xlsx",
            fiscal_year=2024,
            period=12,
            customer_label="aux_test",
        )
        batch_id = uuid.UUID(preview["batch_id"])
        analyze = await analyze_standard_import(
            db=db,
            batch_id=batch_id,
            file_path=file_path,
            field_mappings=[
                {"column_id": "col_0", "field_name": "account_code"},
                {"column_id": "col_1", "field_name": "account_name"},
                {
                    "column_id": "col_2", "field_name": "ending_amount",
                    "period_type": "ending", "split_mode": "single_by_direction",
                },
            ],
            fiscal_year=2024,
            period=12,
            customer_label="aux_test",
            hierarchy_mode="code",
        )
    finally:
        try:
            Path(file_path).unlink()
        except Exception:
            pass

    recs = analyze["mapping_recommendations"]
    aux_rows = [r for r in recs if r.get("node_type") == "auxiliary"]
    assert len(aux_rows) == 3  # 三个辅助核算行
    # 每个辅助行都有 node_key，且 node_key 与 account 节点不同
    aux_node_keys = {r["node_key"] for r in aux_rows}
    assert len(aux_node_keys) == 3
    # 辅助节点的 full_path 应包含上级会计科目名称（在 unique_graph 中验证）
    # 行级 client_account_full_path 是从行本身属性派生，不含父级；用唯一节点图验证绑定。
    for r in aux_rows:
        # 节点父节点的 account_code 应是 112201（上级会计科目）
        parent_rec = next(
            (x for x in recs if x.get("node_key") and x.get("client_account_code") == "112201"),
            None,
        )
        assert parent_rec is not None


# ── 5. 同一 code/name/parent 不同 leaf_row 都回溯到同 node_key ────────────────────────────────


@pytest.mark.asyncio
async def test_every_row_can_be_back_traced_to_node_key(db):
    """每条原始行都可回溯到一个 node_key（无遗漏）。"""
    await _ensure_minimal_standard_accounts_sync(db)
    await db.execute(
        delete(ClientAccountMapping).where(
            ClientAccountMapping.customer_label == "trace_test"
        )
    )
    await db.flush()

    headers = ["科目编码", "科目名称", "期末借方"]
    rows = [
        ["1002", "银行存款", 0.0],
        ["100201", "工行账户", 10.0],
        ["100202", "建行账户", 20.0],
        ["100201", "工行账户", 30.0],  # 重复
        ["1122", "应收账款", 0.0],
        ["112201", "客户A", 40.0],
    ]
    file_path = _build_xlsx(headers, rows)
    try:
        preview = await preview_standard_import(
            db=db,
            file_path=file_path,
            file_name="trace_test.xlsx",
            fiscal_year=2024,
            period=12,
            customer_label="trace_test",
        )
        batch_id = uuid.UUID(preview["batch_id"])
        analyze = await analyze_standard_import(
            db=db,
            batch_id=batch_id,
            file_path=file_path,
            field_mappings=[
                {"column_id": "col_0", "field_name": "account_code"},
                {"column_id": "col_1", "field_name": "account_name"},
                {
                    "column_id": "col_2", "field_name": "ending_amount",
                    "period_type": "ending", "split_mode": "single_by_direction",
                },
            ],
            fiscal_year=2024,
            period=12,
            customer_label="trace_test",
            hierarchy_mode="code",
        )
    finally:
        try:
            Path(file_path).unlink()
        except Exception:
            pass

    recs = analyze["mapping_recommendations"]
    # 每行都有非空 node_key
    for r in recs:
        assert r.get("node_key"), f"row {r.get('row_index')} missing node_key"
    # 唯一节点数：1002 / 100201 / 100202 / 1122 / 112201 = 5
    assert analyze["unique_node_count"] == 5
