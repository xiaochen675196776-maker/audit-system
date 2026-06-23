"""科目余额表标准化导入服务 — TASK-044

完整流程：
  preview → analyze → execute

状态机: previewed → analyzed → blocked → executed → failed
"""

import uuid
import os
import shutil
import logging
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.services.file_parser import parse_file
from app.services.trial_balance_transform import (
    RowInput,
    AmountConfig,
    transform_rows,
    get_leaf_rows,
    BatchTransformResult,
)
from app.services.client_account_mapping_service import (
    recommend_mappings,
    save_mapping,
)
from app.models.standard_trial_balance_import_batch import StandardTrialBalanceImportBatch
from app.models.standard_trial_balance_raw_row import StandardTrialBalanceRawRow
from app.models.standard_trial_balance_entry import StandardTrialBalanceEntry
from app.models.standard_account import StandardAccount

logger = logging.getLogger(__name__)
settings = get_settings()


# ── 工具 ───────────────────────────────────────────

def _build_column_id(col_index: int, header: str) -> str:
    """生成稳定的列 ID"""
    return f"col_{col_index}"


def _safe_str(val: Any) -> str:
    if val is None:
        return ""
    return str(val).strip()


# ── Preview ────────────────────────────────────────

async def preview_standard_import(
    db: AsyncSession,
    file_path: str,
    file_name: str,
    *,
    fiscal_year: int | None = None,
    period: int | None = None,
    customer_label: str | None = None,
    source_label: str | None = None,
) -> dict:
    """
    预览上传文件：解析表头、样本行、创建 draft 批次。

    Returns:
        dict with batch_id, columns, sample_rows, total_rows, fiscal_year, period
    """
    headers, rows = parse_file(file_path)

    # 生成列信息
    columns = []
    for i, h in enumerate(headers):
        columns.append({
            "column_id": _build_column_id(i, h),
            "header_text": h or f"(空列{i})",
            "column_index": i,
        })

    # 取最多 10 行样本
    sample_rows = []
    for r in rows[:10]:
        sample_rows.append({_build_column_id(j, headers[j] if j < len(headers) else ""): _safe_str(v)
                           for j, v in enumerate(r)})

    # 创建 draft 批次
    batch = StandardTrialBalanceImportBatch(
        file_name=file_name,
        customer_label=customer_label,
        source_label=source_label,
        fiscal_year=fiscal_year,
        period=period,
        status="previewed",
    )
    db.add(batch)
    await db.flush()

    return {
        "batch_id": str(batch.id),
        "file_name": file_name,
        "columns": columns,
        "sample_rows": sample_rows,
        "total_rows": len(rows),
        "fiscal_year": fiscal_year,
        "period": period,
        "customer_label": customer_label,
    }


# ── Analyze ────────────────────────────────────────

async def analyze_standard_import(
    db: AsyncSession,
    batch_id: uuid.UUID,
    file_path: str,
    *,
    field_mappings: list[dict],
    fiscal_year: int,
    period: int,
    customer_label: str | None = None,
    source_label: str | None = None,
    hierarchy_mode: str = "auto",
) -> dict:
    """
    分析导入：字段映射 → 层级识别 → 科目映射推荐 → 金额拆分。

    Returns:
        dict with hierarchy, mapping_recommendations, amounts, errors, warnings
    """
    # 1. 查批次
    result = await db.execute(
        select(StandardTrialBalanceImportBatch).where(
            StandardTrialBalanceImportBatch.id == batch_id
        )
    )
    batch = result.scalar_one_or_none()
    if batch is None:
        raise ValueError(f"批次 {batch_id} 不存在")

    # 2. 解析文件
    headers, rows = parse_file(file_path)

    # 3. 构建 column_id → (col_index, header) 映射
    col_id_to_index: dict[str, int] = {}
    col_id_to_header: dict[str, str] = {}
    for i, h in enumerate(headers):
        cid = _build_column_id(i, h)
        col_id_to_index[cid] = i
        col_id_to_header[cid] = h or f"(空列{i})"

    # 4. 构建字段映射：field_name → column_id
    # 同时收集金额配置
    field_to_col: dict[str, str] = {}  # field_name → column_id
    period_configs: list[dict] = []    # per-period amount config for all rows
    amount_fields: set[str] = set()

    for fm in field_mappings:
        cid = fm.get("column_id", "")
        fname = fm.get("field_name", "")
        if not cid or not fname:
            continue

        field_to_col[fname] = cid

        # 收集金额字段配置
        period_type = fm.get("period_type")
        split_mode = fm.get("split_mode")
        if period_type and split_mode:
            period_configs.append({
                "period_type": period_type,
                "mode": split_mode,
                "debit_field": fm.get("debit_column_id"),
                "credit_field": fm.get("credit_column_id"),
                "amount_field": cid,  # for single column modes
            })
            amount_fields.add(cid)

    # 5. 提取客户科目信息（先构建不带方向的 row_inputs）
    code_col_id = field_to_col.get("account_code")
    name_col_id = field_to_col.get("account_name")

    row_inputs_no_dir: list[RowInput] = []
    client_accounts_for_mapping: list[dict] = []
    all_values_by_row: list[dict] = []

    for row_idx, row in enumerate(rows):
        code = ""
        name = ""
        if code_col_id and code_col_id in col_id_to_index:
            ci = col_id_to_index[code_col_id]
            if ci < len(row):
                code = _safe_str(row[ci])
        if name_col_id and name_col_id in col_id_to_index:
            ni = col_id_to_index[name_col_id]
            if ni < len(row):
                name = _safe_str(row[ni])

        # 构建该行的 values dict（用 column_id 作 key）
        values: dict[str, Any] = {}
        for cid, ci in col_id_to_index.items():
            if ci < len(row):
                values[cid] = row[ci]

        all_values_by_row.append(values)

        row_inputs_no_dir.append(RowInput(
            row_index=row_idx,
            client_account_code=code if code else None,
            client_account_name=name if name else None,
            indent_level=None,
            values=values,
            amount_configs=[],  # 稍后填充
            standard_direction=None,
        ))

        if code or name:
            client_accounts_for_mapping.append({
                "client_account_code": code if code else None,
                "client_account_name": name if name else None,
            })

    # 6. 先运行层级识别（不需要方向）
    # 临时用空 amount_configs 做层级识别
    from app.services.trial_balance_transform import detect_hierarchy_by_code, detect_hierarchy_by_indent, assign_flat_hierarchy, merge_hierarchy

    code_hier, _ = detect_hierarchy_by_code(row_inputs_no_dir)
    indent_hier, _ = detect_hierarchy_by_indent(row_inputs_no_dir)
    flat_hier = assign_flat_hierarchy(row_inputs_no_dir)

    if hierarchy_mode == "code":
        merged_hier = code_hier
    elif hierarchy_mode == "indent":
        merged_hier = indent_hier
    elif hierarchy_mode == "flat":
        merged_hier = flat_hier
    else:
        merged_hier = merge_hierarchy(code_hier, indent_hier, flat_hier)

    # 7. 构建层级响应
    hierarchy = []
    for i, ri in enumerate(row_inputs_no_dir):
        h = merged_hier[i] if i < len(merged_hier) else {}
        hierarchy.append({
            "row_index": ri.row_index,
            "client_account_code": ri.client_account_code,
            "client_account_name": ri.client_account_name,
            "level": h.get("level"),
            "parent_key": h.get("parent_key"),
            "is_leaf": h.get("is_leaf", True),
            "is_summary": h.get("is_summary", False),
            "level_source": h.get("level_source", "flat"),
        })

    # 8. 运行科目映射推荐
    mapping_recommendations = await recommend_mappings(
        db=db,
        data_type="trial_balance",
        client_accounts=client_accounts_for_mapping,
        customer_label=customer_label,
        source_label=source_label,
    )

    # 9. 建立 (code,name) → top direction 的快速查找
    # 先补充方向信息到候选人（查询标准科目）
    sa_ids: set[uuid.UUID] = set()
    for rec in mapping_recommendations:
        for c in rec.get("candidates", []):
            sid = c.get("standard_account_id")
            if sid:
                try:
                    sa_ids.add(uuid.UUID(sid))
                except (ValueError, TypeError):
                    pass

    sa_map: dict[uuid.UUID, StandardAccount] = {}
    if sa_ids:
        sa_result = await db.execute(
            select(StandardAccount).where(StandardAccount.id.in_(list(sa_ids)))
        )
        for sa in sa_result.scalars().all():
            sa_map[sa.id] = sa

    # 补充方向信息到候选人
    for rec in mapping_recommendations:
        for c in rec.get("candidates", []):
            sid = c.get("standard_account_id")
            if sid:
                try:
                    sa = sa_map.get(uuid.UUID(sid))
                    c["standard_balance_direction"] = sa.balance_direction if sa else None
                except (ValueError, TypeError):
                    c["standard_balance_direction"] = None
            else:
                c["standard_balance_direction"] = None

    # 现在构建方向查找映射
    rec_direction_map: dict[tuple, str | None] = {}
    for rec in mapping_recommendations:
        key = (rec.get("client_account_code"), rec.get("client_account_name"))
        candidates = rec.get("candidates", [])
        if candidates:
            top = candidates[0]
            rec_direction_map[key] = top.get("standard_balance_direction")
        else:
            rec_direction_map[key] = None

    # 10. 重新构建带方向和金额配置的 row_inputs 并运行金额拆分
    row_inputs: list[RowInput] = []
    for ri in row_inputs_no_dir:
        amt_configs = []
        for pc in period_configs:
            mode = pc["mode"]
            if mode == "two_column":
                amt_configs.append(AmountConfig(
                    period_type=pc["period_type"],
                    mode=mode,
                    debit_field=pc.get("debit_field"),
                    credit_field=pc.get("credit_field"),
                ))
            else:
                af = pc.get("amount_field")
                if af:
                    amt_configs.append(AmountConfig(
                        period_type=pc["period_type"],
                        mode=mode,
                        amount_field=af,
                    ))

        # 从推荐中获取最佳方向
        key = (ri.client_account_code, ri.client_account_name)
        best_direction = rec_direction_map.get(key)
        if best_direction is None and ri.client_account_code:
            # fallback: 用代码查找
            for k, v in rec_direction_map.items():
                if k[0] == ri.client_account_code:
                    best_direction = v
                    break

        row_inputs.append(RowInput(
            row_index=ri.row_index,
            client_account_code=ri.client_account_code,
            client_account_name=ri.client_account_name,
            indent_level=ri.indent_level,
            values=ri.values,
            amount_configs=amt_configs,
            standard_direction=best_direction,
        ))

    transform_result = transform_rows(row_inputs, hierarchy_mode=hierarchy_mode)
    amounts = []
    for r in transform_result.rows:
        amounts.append({
            "row_index": r.row_index,
            "opening_debit": r.opening_debit,
            "opening_credit": r.opening_credit,
            "current_debit": r.current_debit,
            "current_credit": r.current_credit,
            "ending_debit": r.ending_debit,
            "ending_credit": r.ending_credit,
            "warnings": list(r.warnings),
            "errors": list(r.errors),
        })

    # 11. 收集 errors 和 warnings
    errors: list[dict] = []
    warnings: list[dict] = []

    # 来自转换引擎的错误
    for e in transform_result.global_errors:
        errors.append({
            "row_index": None,
            "code": "",
            "message": e,
            "category": "no_direction" if "方向缺失" in e or "无法按标准方向" in e else "missing_amount",
        })

    # 来自转换引擎的警告
    for w in transform_result.global_warnings:
        cat = "parent_amount_mismatch" if "不一致" in w else "negative_amount" if "负数" in w else "indent_suggested" if "缩进" in w else "other"
        warnings.append({
            "row_index": None,
            "code": "",
            "message": w,
            "category": cat,
        })

    # 层级建议警告
    for h in hierarchy:
        if h["level_source"] == "indent_suggested":
            warnings.append({
                "row_index": h["row_index"],
                "code": h.get("client_account_code") or "",
                "message": f"行 {h['row_index']} 的层级由缩进推断，level_source=indent_suggested，建议用户确认",
                "category": "indent_suggested",
            })

    # 检查未映射客户科目（没有任何候选人的）
    for rec in mapping_recommendations:
        if not rec.get("candidates"):
            errors.append({
                "row_index": None,
                "code": rec.get("client_account_code") or "",
                "message": f"客户科目「{rec.get('client_account_code') or '?'} {rec.get('client_account_name') or '?'}」未能匹配任何标准科目，请手动映射",
                "category": "unmapped_account",
            })

    # 检查有候选人但全是 warning 的
    for rec in mapping_recommendations:
        candidates = rec.get("candidates", [])
        all_warned = candidates and all(c.get("warning") for c in candidates)
        if all_warned:
            warnings.append({
                "row_index": None,
                "code": rec.get("client_account_code") or "",
                "message": f"客户科目「{rec.get('client_account_code') or '?'} {rec.get('client_account_name') or '?'}」所有候选均警告（可能指向已停用标准科目），建议用户手动选择",
                "category": "disabled_standard_account",
            })

    # 检查金额列不足
    if not period_configs:
        errors.append({
            "row_index": None,
            "code": "",
            "message": "至少需要映射一个期间金额列（期初/本期/期末），并指定拆分方式",
            "category": "missing_amount",
        })

    # 更新批次状态和配置
    batch.status = "analyzed"
    batch.field_mapping = {"mappings": field_mappings}
    batch.amount_mapping_config = {"period_configs": period_configs}
    batch.hierarchy_config = {"mode": hierarchy_mode}
    batch.fiscal_year = fiscal_year
    batch.period = period
    batch.customer_label = customer_label or batch.customer_label
    batch.source_label = source_label or batch.source_label
    batch.warnings = {"count": len(warnings), "items": warnings}
    batch.errors = {"count": len(errors), "items": errors}
    await db.flush()

    return {
        "batch_id": str(batch.id),
        "status": batch.status,
        "hierarchy": hierarchy,
        "mapping_recommendations": mapping_recommendations,
        "amounts": amounts,
        "errors": errors,
        "warnings": warnings,
    }


# ── Execute ────────────────────────────────────────

async def execute_standard_import(
    db: AsyncSession,
    batch_id: uuid.UUID,
    file_path: str,
    *,
    confirmed_mappings: list[dict],
    warnings_confirmed: bool = False,
    save_mapping_experience: bool = True,
) -> dict:
    """
    执行导入：校验 → 保存原始行 → 生成标准余额表 → 保存映射经验。

    Returns:
        dict with entry_count, raw_row_count, mapping_saved_count, mapping_saved
    """
    # 1. 查批次
    result = await db.execute(
        select(StandardTrialBalanceImportBatch).where(
            StandardTrialBalanceImportBatch.id == batch_id
        )
    )
    batch = result.scalar_one_or_none()
    if batch is None:
        raise ValueError(f"批次 {batch_id} 不存在")
    if batch.status not in ("previewed", "analyzed", "blocked"):
        raise ValueError(f"批次状态为 {batch.status}，不能执行导入（需要 previewed/analyzed/blocked）")

    # 2. 获取分析结果
    headers, rows = parse_file(file_path)

    field_mapping_data = batch.field_mapping or {}
    fm_list = field_mapping_data.get("mappings", [])
    hierarchy_mode = (batch.hierarchy_config or {}).get("mode", "auto")
    fiscal_year = batch.fiscal_year
    period = batch.period
    customer_label = batch.customer_label

    if fiscal_year is None or period is None:
        raise ValueError("批次缺少年度/期间信息，无法执行导入")

    # 3. 重建列索引和字段映射
    col_id_to_index: dict[str, int] = {}
    for i, h in enumerate(headers):
        col_id_to_index[_build_column_id(i, h)] = i

    field_to_col: dict[str, str] = {}
    period_configs: list[dict] = []
    for fm in fm_list:
        cid = fm.get("column_id", "")
        fname = fm.get("field_name", "")
        if cid and fname:
            field_to_col[fname] = cid
        pt = fm.get("period_type")
        sm = fm.get("split_mode")
        if pt and sm:
            period_configs.append({
                "period_type": pt,
                "mode": sm,
                "debit_field": fm.get("debit_column_id"),
                "credit_field": fm.get("credit_column_id"),
                "amount_field": cid,
            })

    # 4. 验证：获取现有警告和错误
    existing_warnings = (batch.warnings or {}).get("items", [])
    existing_errors = (batch.errors or {}).get("items", [])

    # 只对真正致命的错误类型阻止（未映射和方向缺失在执行阶段自行校验）
    blocking_categories = {"missing_amount", "missing_code_and_name"}
    blocking_errors = [
        e for e in existing_errors
        if e.get("category") in blocking_categories
    ]

    if blocking_errors and batch.status != "blocked":
        batch.status = "blocked"
        await db.flush()
        error_detail = "; ".join(e.get("message", "")[:80] for e in blocking_errors[:3])
        raise ValueError(f"存在阻止入库的错误: {error_detail}")

    # 如果有警告且未确认，阻止
    if existing_warnings and not warnings_confirmed:
        batch.status = "blocked"
        await db.flush()
        raise ValueError(f"存在 {len(existing_warnings)} 条警告未确认，请设置 warnings_confirmed=true 后重试。")

    # 5. 校验：所有末级客户科目已映射到启用标准科目
    code_col_id = field_to_col.get("account_code")
    name_col_id = field_to_col.get("account_name")

    # 构建确认映射索引: row_index → standard_account
    confirmed_by_row: dict[int, dict] = {}
    for cm in confirmed_mappings:
        confirmed_by_row[cm.get("row_index", -1)] = cm

    # 重新构建 row_inputs 并运行 transform
    row_inputs: list[RowInput] = []
    for row_idx, row in enumerate(rows):
        code = ""
        name = ""
        if code_col_id and code_col_id in col_id_to_index:
            ci = col_id_to_index[code_col_id]
            if ci < len(row):
                code = _safe_str(row[ci])
        if name_col_id and name_col_id in col_id_to_index:
            ni = col_id_to_index[name_col_id]
            if ni < len(row):
                name = _safe_str(row[ni])

        values: dict[str, Any] = {}
        for cid, ci in col_id_to_index.items():
            if ci < len(row):
                values[cid] = row[ci]

        amt_configs = []
        for pc in period_configs:
            mode = pc["mode"]
            if mode == "two_column":
                amt_configs.append(AmountConfig(
                    period_type=pc["period_type"],
                    mode=mode,
                    debit_field=pc.get("debit_field"),
                    credit_field=pc.get("credit_field"),
                ))
            else:
                af = pc.get("amount_field")
                if af:
                    amt_configs.append(AmountConfig(
                        period_type=pc["period_type"],
                        mode=mode,
                        amount_field=af,
                    ))

        # 确定标准方向
        cm = confirmed_by_row.get(row_idx)
        std_dir = None
        if cm:
            sa_id = cm.get("standard_account_id")
            if sa_id:
                # 查标准科目方向
                sa_result = await db.execute(
                    select(StandardAccount).where(StandardAccount.id == sa_id)
                )
                sa = sa_result.scalar_one_or_none()
                if sa:
                    std_dir = sa.balance_direction

        row_inputs.append(RowInput(
            row_index=row_idx,
            client_account_code=code if code else None,
            client_account_name=name if name else None,
            indent_level=None,
            values=values,
            amount_configs=amt_configs,
            standard_direction=std_dir,
        ))

    transform_result = transform_rows(row_inputs, hierarchy_mode=hierarchy_mode)

    # 6. 获取叶子行，校验每个叶子行都有映射（跳过无代码无名称的行）
    leaves = get_leaf_rows(transform_result)
    unmapped_leaves: list[dict] = []
    for leaf in leaves:
        # 无代码且无名称的行不需要映射
        if not leaf.client_account_code and not leaf.client_account_name:
            continue
        cm = confirmed_by_row.get(leaf.row_index)
        if not cm:
            unmapped_leaves.append({
                "row_index": leaf.row_index,
                "client_account_code": leaf.client_account_code,
                "client_account_name": leaf.client_account_name,
            })

    if unmapped_leaves:
        detail = "; ".join(
            f"行 {u['row_index']}「{u.get('client_account_code') or '?'} {u.get('client_account_name') or '?'}」"
            for u in unmapped_leaves[:5]
        )
        batch.status = "blocked"
        await db.flush()
        raise ValueError(f"存在 {len(unmapped_leaves)} 个末级客户科目未映射到启用标准科目: {detail}")

    # 7. 校验：按标准方向拆分的叶子行必须有方向
    for leaf in leaves:
        cm = confirmed_by_row.get(leaf.row_index)
        if cm:
            sa_result = await db.execute(
                select(StandardAccount).where(StandardAccount.id == cm["standard_account_id"])
            )
            sa = sa_result.scalar_one_or_none()
            if sa is None or not sa.is_active:
                batch.status = "blocked"
                await db.flush()
                raise ValueError(
                    f"行 {leaf.row_index} 映射的标准科目「{cm.get('standard_account_code')}」"
                    f"{'不存在' if sa is None else '已停用'}，请重新选择"
                )

            # 检查是否使用 single_by_direction 且方向为空
            for ac in leaf.amount_configs if hasattr(leaf, 'amount_configs') else []:
                # amount_configs 不在 TransformResult 上，改用 row_inputs
                pass

    # 重新按 row_inputs 检查
    for ri in row_inputs:
        cm = confirmed_by_row.get(ri.row_index)
        if not cm:
            continue
        for ac in ri.amount_configs:
            if ac.mode == "single_by_direction":
                sa_result = await db.execute(
                    select(StandardAccount).where(StandardAccount.id == cm["standard_account_id"])
                )
                sa = sa_result.scalar_one_or_none()
                if sa and not sa.balance_direction:
                    batch.status = "blocked"
                    await db.flush()
                    raise ValueError(
                        f"行 {ri.row_index} 金额列 '{ac.amount_field}' 选择了「按标准方向拆分」，"
                        f"但映射的标准科目「{sa.account_code} {sa.account_name}」余额方向为空，请改为显式借/贷方"
                    )

    # 8. 保存原始行快照（所有行，包括父级和末级）
    raw_row_map: dict[int, uuid.UUID] = {}  # row_index → raw_row_id

    for ri in row_inputs:
        leaf = next((lr for lr in leaves if lr.row_index == ri.row_index), None)
        is_leaf = leaf is not None
        cm = confirmed_by_row.get(ri.row_index)

        raw_row = StandardTrialBalanceRawRow(
            batch_id=batch_id,
            row_index=ri.row_index,
            raw_values=ri.values,
            client_account_code=ri.client_account_code,
            client_account_name=ri.client_account_name,
            detected_level=leaf.level if leaf else None,
            is_leaf=is_leaf,
            mapped_standard_account_id=cm["standard_account_id"] if cm else None,
            mapping_status="mapped" if cm else ("unmapped" if (ri.client_account_code or ri.client_account_name) else "ignored"),
            warnings={"warnings": leaf.warnings, "errors": leaf.errors} if leaf else None,
        )
        db.add(raw_row)
        await db.flush()
        raw_row_map[ri.row_index] = raw_row.id

    # 9. 给原始行补 parent_raw_row_id
    for ri in row_inputs:
        leaf = next((lr for lr in leaves if lr.row_index == ri.row_index), None)
        if leaf and leaf.parent_key:
            # parent_key 可能是代码或 row_index 字符串
            try:
                parent_idx = int(leaf.parent_key)
            except (ValueError, TypeError):
                parent_idx = None
                # 代码形式：找对应代码的行
                for ri2 in row_inputs:
                    if ri2.client_account_code and ri2.client_account_code.strip() == leaf.parent_key:
                        parent_idx = ri2.row_index
                        break

            if parent_idx is not None and parent_idx in raw_row_map:
                row_id = raw_row_map[ri.row_index]
                parent_id = raw_row_map[parent_idx]
                rr = await db.get(StandardTrialBalanceRawRow, row_id)
                if rr:
                    rr.parent_raw_row_id = parent_id

    await db.flush()

    # 10. 生成标准科目余额表明细（只写叶子行）
    entry_count = 0
    for leaf in leaves:
        cm = confirmed_by_row.get(leaf.row_index)
        if not cm:
            continue

        # 获取标准科目快照
        sa_result = await db.execute(
            select(StandardAccount).where(StandardAccount.id == cm["standard_account_id"])
        )
        sa = sa_result.scalar_one_or_none()
        if sa is None:
            continue

        entry = StandardTrialBalanceEntry(
            batch_id=batch_id,
            raw_row_id=raw_row_map.get(leaf.row_index),
            standard_account_id=sa.id,
            standard_account_code_snapshot=sa.account_code,
            standard_account_name_snapshot=sa.account_name,
            standard_account_category_snapshot=sa.account_category,
            standard_balance_direction_snapshot=sa.balance_direction,
            client_account_code=leaf.client_account_code,
            client_account_name=leaf.client_account_name,
            fiscal_year=fiscal_year,
            period=period,
            opening_debit=leaf.opening_debit,
            opening_credit=leaf.opening_credit,
            current_debit=leaf.current_debit,
            current_credit=leaf.current_credit,
            ending_debit=leaf.ending_debit,
            ending_credit=leaf.ending_credit,
        )
        db.add(entry)
        entry_count += 1

    await db.flush()

    # 11. 保存映射经验
    mapping_saved: list[dict] = []
    if save_mapping_experience:
        for leaf in leaves:
            cm = confirmed_by_row.get(leaf.row_index)
            if not cm:
                continue
            if not leaf.client_account_code and not leaf.client_account_name:
                continue

            try:
                result = await save_mapping(
                    db=db,
                    data_type="trial_balance",
                    customer_label=customer_label,
                    client_account_code=leaf.client_account_code,
                    client_account_name=leaf.client_account_name,
                    standard_account_id=cm["standard_account_id"],
                    standard_account_code=cm["standard_account_code"],
                    standard_account_name=cm["standard_account_name"],
                    source="user_confirmed",
                    confidence=1.0,
                    allow_overwrite=True,
                )
                mapping_saved.append({
                    "client_account_code": leaf.client_account_code,
                    "standard_account_code": cm.get("standard_account_code", ""),
                    "status": result.get("status", "unknown"),
                })
            except Exception as e:
                logger.warning(f"保存映射经验失败: {e}")

    # 12. 更新批次状态
    batch.status = "executed"
    await db.flush()

    return {
        "batch_id": str(batch.id),
        "status": batch.status,
        "entry_count": entry_count,
        "raw_row_count": len(row_inputs),
        "mapping_saved_count": len(mapping_saved),
        "mapping_saved": mapping_saved,
    }


# ── 批次查询 ────────────────────────────────────────

async def get_import_batch(
    db: AsyncSession,
    batch_id: uuid.UUID,
) -> dict | None:
    """查询导入批次详情"""
    result = await db.execute(
        select(StandardTrialBalanceImportBatch).where(
            StandardTrialBalanceImportBatch.id == batch_id
        )
    )
    batch = result.scalar_one_or_none()
    if batch is None:
        return None

    # 统计条目数
    count_result = await db.execute(
        select(StandardTrialBalanceEntry).where(
            StandardTrialBalanceEntry.batch_id == batch_id
        )
    )
    entries = count_result.scalars().all()

    return {
        "id": str(batch.id),
        "file_name": batch.file_name,
        "customer_label": batch.customer_label,
        "source_label": batch.source_label,
        "fiscal_year": batch.fiscal_year,
        "period": batch.period,
        "status": batch.status,
        "field_mapping": batch.field_mapping,
        "amount_mapping_config": batch.amount_mapping_config,
        "hierarchy_config": batch.hierarchy_config,
        "warnings": batch.warnings,
        "errors": batch.errors,
        "entry_count": len(entries),
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "updated_at": batch.updated_at.isoformat() if batch.updated_at else None,
    }
