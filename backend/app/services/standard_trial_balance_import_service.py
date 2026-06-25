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
from app.services.file_parser import (
    parse_trial_balance_import,
    slice_data_rows,
)
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
    _pick_auto_confirm_candidate,
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


def _row_amount_is_zero(value: Any) -> bool:
    """单格金额值是否为空/0。非数字（含 None / ''）视为 0。"""
    if value is None:
        return True
    s = str(value).strip()
    if not s or s in ("None", "—", "-", "·"):
        return True
    try:
        from decimal import Decimal as _D, InvalidOperation as _IO
        return _D(s.replace(",", "").replace("，", "")) == _D("0")
    except Exception:
        return True


def _collect_zero_amount_template_rows(
    rows: list[list],
    period_configs: list[dict],
    col_id_to_index: dict[str, int],
) -> set[int]:
    """返回所有金额字段（已映射的借/贷/单列金额）都为 0/空 的行索引集合。

    只要任何一个已映射金额字段有非零值，行就不被跳过。若没有任何金额字段被映射
    （period_configs 为空），则不跳过任何行（无法判定）。
    """
    if not period_configs:
        return set()

    amount_cell_indices: list[int] = []
    for pc in period_configs:
        if pc.get("mode") == "two_column":
            for f in (pc.get("debit_field"), pc.get("credit_field")):
                ci = col_id_to_index.get(f) if f else None
                if ci is not None:
                    amount_cell_indices.append(ci)
        else:
            f = pc.get("amount_field")
            ci = col_id_to_index.get(f) if f else None
            if ci is not None:
                amount_cell_indices.append(ci)
    amount_cell_indices = sorted(set(amount_cell_indices))
    if not amount_cell_indices:
        return set()

    skip: set[int] = set()
    for ri, row in enumerate(rows):
        all_zero = True
        for ci in amount_cell_indices:
            val = row[ci] if ci < len(row) else None
            if not _row_amount_is_zero(val):
                all_zero = False
                break
        if all_zero:
            skip.add(ri)
    return skip


def _collect_summary_total_skip_rows(
    rows: list[list],
    col_id_to_index: dict[str, int],
    code_col_id: str | None,
    name_col_id: str | None,
) -> set[int]:
    """返回科目编码/名称含「小计」「合计」的行索引集合，这些行不参与映射与入库。

    广西：(资产)小计：、(负债)小计： 等；金蝶：合计 行。
    """
    code_idx = col_id_to_index.get(code_col_id) if code_col_id else None
    name_idx = col_id_to_index.get(name_col_id) if name_col_id else None
    skip: set[int] = set()
    for ri, row in enumerate(rows):
        code = _safe_str(row[code_idx]) if code_idx is not None and code_idx < len(row) else ""
        name = _safe_str(row[name_idx]) if name_idx is not None and name_idx < len(row) else ""
        combined = f"{code} {name}"
        if any(kw in combined for kw in ("小计", "合计")):
            skip.add(ri)
    return skip


# ── TASK-078：辅助核算明细行识别与父科目继承 ────────────


def _is_auxiliary_detail_name(name: str) -> bool:
    """客户科目名称为辅助核算对象（无科目代码）的判定。

    典型形态：「[0010004] 茂名市润源丰化工有限公司」「 客户:黄林兰」。
    只要名称包含中文方括号、半角方括号或以「客户:」「供应商:」「部门:」「项目:」
    等辅助类型关键字开头，且没有科目代码段，即视为辅助核算对象。
    """
    if not name:
        return False
    s = str(name).strip()
    # 全/半角空白开头的辅助对象（广西的「 [0010004] ...」）
    if "[" in s or "【" in s:
        return True
    auxi_prefixes = ("客户:", "客户：", "供应商:", "供应商：",
                     "部门:", "部门：", "项目:", "项目：", "银行账户:")
    for p in auxi_prefixes:
        if s.replace("\u3000", "").lstrip().startswith(p):
            return True
    return False


def _build_inherited_candidate(
    picked_candidate: dict,
    client_name: str,
) -> dict:
    """从父科目命中候选构造「辅助核算继承父科目」候选。

    安全（warning=None, score=0.92），不会再走辅助对象名称匹配。
    """
    sa_id = picked_candidate.get("standard_account_id")
    sa_code = picked_candidate.get("standard_account_code")
    sa_name = picked_candidate.get("standard_account_name")
    sa_dir = picked_candidate.get("standard_balance_direction")
    return {
        "standard_account_id": sa_id,
        "standard_account_code": sa_code,
        "standard_account_name": sa_name,
        "standard_balance_direction": sa_dir,
        "score": 0.92,
        "source": "auxiliary_inherited_parent",
        "reason": f"辅助核算明细继承父科目 → {sa_code} {sa_name}",
        "warning": None,
    }


def _inject_auxiliary_inherited_candidates(
    mapping_recommendations: list[dict],
    rows: list[list],
    code_col_id: str | None,
    name_col_id: str | None,
    col_id_to_index: dict[str, int],
) -> int:
    """对「无科目代码、名称为辅助核算对象」的行，继承最近前置有代码行的安全候选。

    返回注入的候选数量。
    """
    if not code_col_id and not name_col_id:
        return 0
    code_idx = col_id_to_index.get(code_col_id) if code_col_id else None
    name_idx = col_id_to_index.get(name_col_id) if name_col_id else None

    rec_by_row: dict[int, dict] = {}
    for rec in mapping_recommendations:
        ri = rec.get("row_index")
        if ri is not None:
            rec_by_row[ri] = rec

    inherited_count = 0
    # 最近有科目代码的前置行「安全候选」
    last_picked: dict | None = None
    seq_index_to_row_idx: list[int] = []
    # row_index in recs is data-row index. We iterate in original data row order.
    # mapping_recommendations 顺序对应 client_accounts_for_mapping，按 data row 顺序。
    for rec in mapping_recommendations:
        ri = rec.get("row_index")
        if ri is None:
            continue
        seq_index_to_row_idx.append(ri)

    # Build code/name per row to flag auxiliary rows
    code_by_row: dict[int, str] = {}
    name_by_row: dict[int, str] = {}
    for ri in seq_index_to_row_idx:
        row = rows[ri] if 0 <= ri < len(rows) else None
        if row is None:
            continue
        code = _safe_str(row[code_idx]) if code_idx is not None and code_idx < len(row) else ""
        name = _safe_str(row[name_idx]) if name_idx is not None and name_idx < len(row) else ""
        code_by_row[ri] = code
        name_by_row[ri] = name

    for ri in seq_index_to_row_idx:
        rec = rec_by_row.get(ri)
        if rec is None:
            continue
        code = code_by_row.get(ri, "")
        name = name_by_row.get(ri, "")
        if code:
            # 有代码行：更新 last_picked
            picked = _pick_auto_confirm_candidate(rec.get("candidates", []))
            if picked and picked.get("warning") is None:
                last_picked = picked
            continue
        # 无代码行
        if name and _is_auxiliary_detail_name(name):
            if last_picked is None:
                continue
            existing = [c for c in rec.get("candidates", [])
                        if c.get("warning") is None and c.get("source") in
                        ("code_match", "name_exact", "semantic_alias", "name_prefix",
                         "auxiliary_inherited_parent")]
            ids = {c.get("standard_account_id") for c in existing}
            if last_picked.get("standard_account_id") in ids:
                # 已有同样安全候选指向同一标准科目，跳过
                continue
            cand = _build_inherited_candidate(last_picked, name)
            rec.setdefault("candidates", []).insert(0, cand)
            inherited_count += 1
    return inherited_count


# ── TASK-078：文件解析统一入口 ──────────────────────────


def _load_import_rows(
    file_path: str,
    parse_config: dict | None = None,
) -> tuple[list[str], list[list], int, list[int]]:
    """读取文件，返回 (merged_headers, data_rows, data_start_row, header_rows)。

    若 parse_config 提供 data_start_row 则沿用；否则使用自动识别结果并把元数据
    写回 parse_config（由调用方持久化到批次）。
    """
    parsed = parse_trial_balance_import(file_path)
    parse_config = parse_config or {}
    if parse_config.get("data_start_row") is not None:
        data_start = int(parse_config["data_start_row"])
    else:
        data_start = int(parsed["data_start_row"])

    merged_headers = parsed["merged_headers"]
    header_rows = parsed["header_rows"]
    data_rows = slice_data_rows(parsed["all_rows"], data_start)
    return merged_headers, data_rows, data_start, header_rows


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
    headers, rows, data_start, header_rows = _load_import_rows(file_path)

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
    batch.hierarchy_config = {
        "parse_config": {
            "data_start_row": data_start,
            "header_rows": header_rows,
            "merged_headers": headers,
        },
    }
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

    # 2. 解析文件（使用批次的 parse_config；若无则自动识别并回写）
    parse_config = (batch.hierarchy_config or {}).get("parse_config") or {}
    headers, rows, data_start, header_rows = _load_import_rows(file_path, parse_config)
    if not parse_config:
        parse_config = {
            "data_start_row": data_start,
            "header_rows": header_rows,
            "merged_headers": headers,
        }
        # save back to batch
        batch.hierarchy_config = dict(batch.hierarchy_config or {})
        batch.hierarchy_config["parse_config"] = parse_config

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
                "row_index": row_idx,
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

    row_mapping_meta: dict[int, dict] = {}
    for h in hierarchy:
        participates_in_entry = (
            h.get("is_leaf", True)
            and not h.get("is_summary", False)
            and bool(h.get("client_account_code") or h.get("client_account_name"))
        )
        row_mapping_meta[h["row_index"]] = {
            "is_leaf": h.get("is_leaf", True),
            "is_summary": h.get("is_summary", False),
            "participates_in_entry": participates_in_entry,
        }

    # TASK-078：自动跳过零金额模板行（金蝶在每个模板科目下甚至成片空金额行）。
    # 仅当「该行所有已配置金额字段都为空/0」时，且本身不是带非空子行的父级，
    # 才认定为零金额模板行，跳过其入库参与与标准映射校验。
    auto_skip_rows = _collect_zero_amount_template_rows(
        rows, period_configs, col_id_to_index,
    )
    # TASK-079：小计/合计行也自动跳过
    summary_skip_rows = _collect_summary_total_skip_rows(
        rows, col_id_to_index, code_col_id=code_col_id, name_col_id=name_col_id,
    )
    auto_skip_rows |= summary_skip_rows
    for ridx in auto_skip_rows:
        if ridx in row_mapping_meta:
            row_mapping_meta[ridx]["participates_in_entry"] = False
            row_mapping_meta[ridx]["_zero_amount_template"] = True

    # 8. 把 row_mapping_meta（is_leaf/participates）合并进 client_accounts_for_mapping，
    # 供科目映射推荐使用，决定是否允许安全自动归入
    for entry in client_accounts_for_mapping:
        ri = entry.get("row_index")
        if ri is not None and ri in row_mapping_meta:
            entry.update(row_mapping_meta[ri])

    # 9. 运行科目映射推荐
    mapping_recommendations = await recommend_mappings(
        db=db,
        data_type="trial_balance",
        client_accounts=client_accounts_for_mapping,
        customer_label=customer_label,
        source_label=source_label,
    )

    for idx, rec in enumerate(mapping_recommendations):
        source_row = client_accounts_for_mapping[idx] if idx < len(client_accounts_for_mapping) else {}
        row_index = source_row.get("row_index")
        meta = row_mapping_meta.get(row_index, {}) if row_index is not None else {}
        rec["row_index"] = row_index
        rec["is_leaf"] = meta.get("is_leaf")
        rec["is_summary"] = meta.get("is_summary")
        rec["participates_in_entry"] = meta.get("participates_in_entry")

    # TASK-078：辅助核算明细行继承父科目候选注入。
    # 在补充层级 / 方向等元信息之后、统一方向查找之前补充继承候选，
    # 让辅助行也有安全候选可被自动确认，不再产生 unmapped_account。
    inherited_auxiliary_rows = _inject_auxiliary_inherited_candidates(
        mapping_recommendations=mapping_recommendations,
        rows=rows,
        code_col_id=code_col_id,
        name_col_id=name_col_id,
        col_id_to_index=col_id_to_index,
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
    rec_direction_by_row: dict[int, str | None] = {}
    for rec in mapping_recommendations:
        key = (rec.get("client_account_code"), rec.get("client_account_name"))
        candidates = rec.get("candidates", [])
        if candidates:
            # TASK-077：自动选中优先取安全候选，避免盲取 candidates[0] 命中 warning
            top = _pick_auto_confirm_candidate(candidates)
            rec_direction_map[key] = top.get("standard_balance_direction")
        else:
            rec_direction_map[key] = None
        row_index = rec.get("row_index")
        if row_index is not None:
            rec_direction_by_row[row_index] = rec_direction_map[key]

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
        best_direction = rec_direction_by_row.get(ri.row_index)
        if best_direction is None:
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
        if not rec.get("participates_in_entry", True):
            continue
        if not rec.get("candidates"):
            errors.append({
                "row_index": rec.get("row_index"),
                "code": rec.get("client_account_code") or "",
                "message": f"客户科目「{rec.get('client_account_code') or '?'} {rec.get('client_account_name') or '?'}」未能匹配任何标准科目，请手动映射",
                "category": "unmapped_account",
            })

    # 检查有候选人但全是 warning 的
    for rec in mapping_recommendations:
        if not rec.get("participates_in_entry", True):
            continue
        candidates = rec.get("candidates", [])
        all_warned = candidates and all(c.get("warning") for c in candidates)
        if all_warned:
            warnings.append({
                "row_index": rec.get("row_index"),
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
    # 保留预览阶段写入的 parse_config（含 data_start_row / header_rows / merged_headers）
    existing_hierarchy_config = batch.hierarchy_config or {}
    existing_parse_config = existing_hierarchy_config.get("parse_config") or {}
    if not existing_parse_config:
        existing_parse_config = {
            "data_start_row": data_start,
            "header_rows": header_rows,
            "merged_headers": headers,
        }
    batch.hierarchy_config = {
        "mode": hierarchy_mode,
        "parse_config": existing_parse_config,
        "inherited_auxiliary_rows": inherited_auxiliary_rows,
    }
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
    ignored_rows: list[int] | None = None,
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

    ignored_rows = ignored_rows or []
    if any(row_index < 0 for row_index in ignored_rows):
        raise ValueError("ignored_rows 只能包含非负行序号")
    if len(set(ignored_rows)) != len(ignored_rows):
        raise ValueError("ignored_rows 不能包含重复行序号")
    ignored_row_set = set(ignored_rows)

    # 2. 获取分析结果
    parse_config = (batch.hierarchy_config or {}).get("parse_config") or {}
    headers, rows, data_start, header_rows = _load_import_rows(file_path, parse_config)

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
    # TASK-078：重算零金额模板行（与 analyze 一致规则），自动不参与入库/映射校验。
    execute_auto_skip_rows = _collect_zero_amount_template_rows(
        rows, period_configs, col_id_to_index,
    )
    # TASK-079：小计/合计行也自动跳过
    execute_auto_skip_rows |= _collect_summary_total_skip_rows(
        rows, col_id_to_index, code_col_id=code_col_id, name_col_id=name_col_id,
    )
    participating_leaf_rows = {
        leaf.row_index
        for leaf in leaves
        if (leaf.client_account_code or leaf.client_account_name)
        and leaf.row_index not in execute_auto_skip_rows
    }
    invalid_ignored_rows = sorted(ignored_row_set - participating_leaf_rows)
    if invalid_ignored_rows:
        batch.status = "blocked"
        await db.flush()
        detail = "、".join(str(row_index) for row_index in invalid_ignored_rows[:10])
        raise ValueError(
            f"忽略行只能选择参与入库的末级客户科目行，以下行不可忽略: {detail}"
        )

    unmapped_leaves: list[dict] = []
    for leaf in leaves:
        # 无代码且无名称的行不需要映射
        if not leaf.client_account_code and not leaf.client_account_name:
            continue
        if leaf.row_index in ignored_row_set:
            continue
        # TASK-078：零金额模板行自动跳过，不参与入库也不会产生未映射错误
        if leaf.row_index in execute_auto_skip_rows:
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
        if leaf.row_index in ignored_row_set:
            continue
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
        if ri.row_index in ignored_row_set:
            continue
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
    result_by_row = {r.row_index: r for r in transform_result.rows}  # 所有行的转换结果

    for ri in row_inputs:
        leaf = next((lr for lr in leaves if lr.row_index == ri.row_index), None)
        is_leaf = leaf is not None
        is_user_ignored = ri.row_index in ignored_row_set
        cm = None if is_user_ignored else confirmed_by_row.get(ri.row_index)
        if is_user_ignored or (not ri.client_account_code and not ri.client_account_name):
            mapping_status = "ignored"
        elif cm:
            mapping_status = "mapped"
        else:
            mapping_status = "unmapped"

        # 优先用 transform_result 的层级信息（覆盖所有行，不仅叶子）
        tr = result_by_row.get(ri.row_index)
        detected_level = tr.level if tr else (leaf.level if leaf else None)
        raw_is_leaf = bool(tr and tr.is_leaf and not tr.is_summary) if tr else is_leaf
        row_warnings = {"warnings": leaf.warnings, "errors": leaf.errors} if leaf else None

        raw_row = StandardTrialBalanceRawRow(
            batch_id=batch_id,
            row_index=ri.row_index,
            raw_values=ri.values,
            client_account_code=ri.client_account_code,
            client_account_name=ri.client_account_name,
            detected_level=detected_level,
            is_leaf=raw_is_leaf,
            mapped_standard_account_id=cm["standard_account_id"] if cm else None,
            mapping_status=mapping_status,
            warnings=row_warnings,
        )
        db.add(raw_row)
        await db.flush()
        raw_row_map[ri.row_index] = raw_row.id

    # 9. 给所有行补 parent_raw_row_id（不只是叶子行）
    for tr in transform_result.rows:
        if not tr.parent_key:
            continue
        # parent_key 可能是代码或 row_index 字符串
        try:
            parent_idx = int(tr.parent_key)
        except (ValueError, TypeError):
            parent_idx = None
            # 代码形式：找对应代码的行
            for ri2 in row_inputs:
                if ri2.client_account_code and ri2.client_account_code.strip() == tr.parent_key:
                    parent_idx = ri2.row_index
                    break

        if parent_idx is not None and parent_idx in raw_row_map and tr.row_index in raw_row_map:
            row_id = raw_row_map[tr.row_index]
            parent_id = raw_row_map[parent_idx]
            rr = await db.get(StandardTrialBalanceRawRow, row_id)
            if rr:
                rr.parent_raw_row_id = parent_id

    await db.flush()

    # 10. 生成标准科目余额表明细（只写叶子行）
    entry_count = 0
    for leaf in leaves:
        if leaf.row_index in ignored_row_set:
            continue
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
            if leaf.row_index in ignored_row_set:
                continue
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
