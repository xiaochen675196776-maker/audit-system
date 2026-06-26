"""科目余额表标准化导入服务 — TASK-044 + ANCHOR-INHERITANCE-MAPPING

完整流程：
  preview → analyze → execute

状态机: previewed → analyzed → blocked → executed → failed

ANCHOR-INHERITANCE-MAPPING：
- analyze 阶段调用 account_mapping_inheritance_service 决定每行的映射角色
  （anchor / inherited / breakpoint / explicit_override / unresolved /
   structural_summary / ignored）
- execute 阶段复用同一份 build_account_tree + evaluate_inheritance_boundary
  重新解析映射计划，然后只对 anchor / breakpoint / explicit_override 节点应用
  用户提交的目标，对 inherited 节点自动沿树传播。
- 任一参与入库的末级未解析唯一标准科目 → 阻止 execute。
"""

import uuid
import os
import re
import shutil
import logging
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select, func
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
    detect_hierarchy_by_code,
    detect_hierarchy_by_indent,
    assign_flat_hierarchy,
    merge_hierarchy,
    BatchTransformResult,
)
from app.services.client_account_mapping_service import (
    recommend_mappings,
    save_mapping,
    _pick_auto_confirm_candidate,
    pick_unique_auto_confirm_candidate,
)
from app.services.account_mapping_inheritance_service import (
    AccountTree,
    AccountTreeNode,
    AnchorResolution,
    MappingPlanSummary,
    build_account_tree,
    build_mapping_plan as build_anchor_mapping_plan,
    validate_mapping_plan,
    resolve_leaf_standard_accounts,
    is_structural_summary,
    evaluate_inheritance_boundary,
    find_strong_direct_signals,
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
    """返回科目编码/名称含「合计」「总计」「小计」的行索引集合，这些行不参与映射与入库。

    广西：(资产)小计：、(负债)小计： 等；金蝶：合计 行；医疗：总计 行。
    也覆盖「本页合计」「本月合计」「累计」等模式。
    同时过滤配置科目（如 code=9999「不过帐设置用」）和页脚元数据行。
    """
    code_idx = col_id_to_index.get(code_col_id) if code_col_id else None
    name_idx = col_id_to_index.get(name_col_id) if name_col_id else None

    # 汇总关键词（含中文括号变体）
    _SUMMARY_KEYWORDS = (
        "合计", "总计", "小计", "本页合计", "本月合计", "累计",
        "（资产）小计", "(资产)小计", "（负债）小计", "(负债)小计",
        "（权益）小计", "(权益)小计", "（损益）小计", "(损益)小计",
        "资产）小计", "资产)小计", "负债）小计", "负债)小计",
        "权益）小计", "权益)小计", "损益）小计", "损益)小计",
    )
    # 页脚元数据关键词
    _FOOTER_KEYWORDS = (
        "核算单位", "制单人", "打印时间", "打印日期", "编制单位",
        "审核人", "记账人", "财务主管", "单位负责人",
    )
    # 配置科目/非过帐科目关键词（名称中含这些关键词的行不参与导入）
    _CONFIG_NAME_KEYWORDS = (
        "不过帐", "不记帐", "不记账", "设置用", "系统设置", "暂存",
    )

    skip: set[int] = set()
    for ri, row in enumerate(rows):
        code = _safe_str(row[code_idx]) if code_idx is not None and code_idx < len(row) else ""
        name = _safe_str(row[name_idx]) if name_idx is not None and name_idx < len(row) else ""
        # 单独检查 code 和 name，也检查组合
        if any(kw in code for kw in _SUMMARY_KEYWORDS):
            skip.add(ri)
            continue
        if any(kw in name for kw in _SUMMARY_KEYWORDS):
            skip.add(ri)
            continue
        combined = f"{code} {name}"
        if any(kw in combined for kw in _SUMMARY_KEYWORDS):
            skip.add(ri)
            continue
        # 页脚元数据：科目编码列包含非科目类的元数据关键词
        if any(kw in code for kw in _FOOTER_KEYWORDS):
            skip.add(ri)
            continue
        # 配置科目/非过帐科目：名称含配置关键词（如「不过帐设置用」）
        if any(kw in name for kw in _CONFIG_NAME_KEYWORDS):
            skip.add(ri)
            continue
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
            # 有代码行：更新 last_picked（使用后端 auto_confirm_candidate）
            picked = rec.get("auto_confirm_candidate") or pick_unique_auto_confirm_candidate(rec.get("candidates", []))
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
                "direction_column_id": fm.get("direction_column_id"),
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
            # TASK-081：预过滤 — 跳过完全空代码和空名称的行（辅助核算展示行）
            # 205201 大量 (code="", name="") 行仅用于展示核算维度，不参与映射
            if not code.strip() and not name.strip():
                continue
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

    # 6b. 构建代码→行信息索引（用于父级/祖先上下文查找）
    code_to_row_info: dict[str, dict] = {}
    for ri in row_inputs_no_dir:
        if ri.client_account_code:
            code_to_row_info[ri.client_account_code.strip()] = {
                "row_index": ri.row_index,
                "code": ri.client_account_code.strip(),
                "name": ri.client_account_name or "",
            }

    # 6c. 为每个 client_account 补充父级/祖先上下文
    # TASK-081 优化：先建 row_index → hierarchy 映射，避免 O(n²) 嵌套扫描
    row_index_to_hier: dict[int, dict] = {}
    for h in merged_hier:
        row_index_to_hier[h.get("row_index")] = h

    for ca_entry in client_accounts_for_mapping:
        ca_code = (ca_entry.get("client_account_code") or "").strip()
        # 找父级
        parent_code = None
        parent_name = None
        if ca_code:
            h = row_index_to_hier.get(ca_entry["row_index"])
            if h and h.get("parent_key"):
                parent_info = code_to_row_info.get(h["parent_key"])
                if parent_info:
                    parent_code = parent_info["code"]
                    parent_name = parent_info["name"]

        # 收集祖先链（沿 parent_key 回溯，TASK-081 优化：O(len(code)) 替代 O(n)）
        ancestor_codes: list[str] = []
        ancestor_names: list[str] = []
        if ca_code:
            current_code = ca_code
            visited: set[str] = set()
            while current_code and current_code not in visited:
                visited.add(current_code)
                # 从末尾逐步缩短找到最长前缀父级
                found_parent = None
                for end in range(len(current_code) - 1, 0, -1):
                    candidate = current_code[:end]
                    if candidate in code_to_row_info and candidate != current_code:
                        found_parent = candidate
                        break
                if found_parent:
                    info = code_to_row_info[found_parent]
                    ancestor_codes.append(info["code"])
                    ancestor_names.append(info["name"])
                    current_code = found_parent
                else:
                    break

        # 构建完整路径
        full_path_parts = [ca_entry.get("client_account_name") or ""]
        full_path_parts.extend(reversed(ancestor_names))
        full_path = "\\".join(p for p in full_path_parts if p)

        ca_entry["parent_client_account_code"] = parent_code
        ca_entry["parent_client_account_name"] = parent_name
        ca_entry["ancestor_codes"] = ancestor_codes
        ca_entry["ancestor_names"] = ancestor_names
        ca_entry["client_account_full_path"] = full_path

        # TASK-080 Fallback: 如果层级检测没找到父级，从代码本身推导
        # 逐步缩短代码（去掉末尾数字），直到找到可识别的父级前缀
        if not parent_code and not ancestor_codes and ca_code and len(ca_code) >= 4:
            derived_parents = []
            for end in range(len(ca_code) - 1, 1, -1):
                candidate_parent = ca_code[:end]
                # 至少保留 2 位数字
                if len(candidate_parent) >= 2:
                    derived_parents.append(candidate_parent)
            ca_entry["ancestor_codes"] = derived_parents[:5]  # 最多 5 层祖先

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

    # 9. 运行科目映射推荐（TASK-081：大文件先去重）
    # 对 client_accounts_for_mapping 按 (code, name, ancestors) 去重，
    # 只对唯一 key 调用 recommend_mappings，然后回填到所有相同 key 的行。
    _dedup_key_to_first_idx: dict[tuple, int] = {}
    for idx, ca in enumerate(client_accounts_for_mapping):
        key = (
            (ca.get("client_account_code") or "").strip(),
            (ca.get("client_account_name") or "").strip(),
            tuple(ca.get("ancestor_codes") or []),
            tuple(ca.get("ancestor_names") or []),
        )
        if key not in _dedup_key_to_first_idx:
            _dedup_key_to_first_idx[key] = idx

    unique_accounts = [client_accounts_for_mapping[i] for i in _dedup_key_to_first_idx.values()]
    unique_recommendations = await recommend_mappings(
        db=db,
        data_type="trial_balance",
        client_accounts=unique_accounts,
        customer_label=customer_label,
        source_label=source_label,
    )

    # 回填：把去重结果映射回原始列表
    _dedup_result_map: dict[tuple, dict] = {}
    for idx, rec in enumerate(unique_recommendations):
        ca = unique_accounts[idx]
        key = (
            (ca.get("client_account_code") or "").strip(),
            (ca.get("client_account_name") or "").strip(),
            tuple(ca.get("ancestor_codes") or []),
            tuple(ca.get("ancestor_names") or []),
        )
        _dedup_result_map[key] = rec

    mapping_recommendations = []
    for ca in client_accounts_for_mapping:
        key = (
            (ca.get("client_account_code") or "").strip(),
            (ca.get("client_account_name") or "").strip(),
            tuple(ca.get("ancestor_codes") or []),
            tuple(ca.get("ancestor_names") or []),
        )
        rec = _dedup_result_map.get(key, {"candidates": []})
        # 复制一份，不共享 candidates 引用（避免后续修改互相影响）
        mapping_recommendations.append({
            "client_account_code": ca.get("client_account_code"),
            "client_account_name": ca.get("client_account_name"),
            "candidates": list(rec.get("candidates", [])),
        })

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
            # TASK-087：使用后端 auto_confirm_candidate，只有唯一安全候选时才取方向
            top = rec.get("auto_confirm_candidate") or pick_unique_auto_confirm_candidate(candidates)
            rec_direction_map[key] = top.get("standard_balance_direction") if top else None
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
                        direction_column_id=pc.get("direction_column_id"),
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

    # 来自转换引擎的警告（过滤掉 auto_skip_rows 中的行的警告）
    for w in transform_result.global_warnings:
        # 提取警告中的行号（格式："行 N: ..."）
        m = re.match(r"行 (\d+):", w)
        if m:
            row_idx = int(m.group(1))
            if row_idx in auto_skip_rows:
                continue  # 跳过的行不产生警告
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

    # ANCHOR-INHERITANCE-MAPPING：构建客户科目树并运行继承映射计划
    # 1) 准备 rows_meta + row_mapping_meta
    ca_by_row: dict[int, dict] = {
        ca.get("row_index"): ca for ca in client_accounts_for_mapping
        if ca.get("row_index") is not None
    }
    rows_meta_for_tree: list[dict] = []
    for i, ri in enumerate(row_inputs_no_dir):
        h = merged_hier[i] if i < len(merged_hier) else {}
        ca = ca_by_row.get(ri.row_index, {})
        rows_meta_for_tree.append({
            "row_index": ri.row_index,
            "client_account_code": ri.client_account_code,
            "client_account_name": ri.client_account_name,
            "level": h.get("level"),
            "parent_key": h.get("parent_key"),
            "is_leaf": h.get("is_leaf", True),
            "is_summary": h.get("is_summary", False),
            "ancestor_codes": ca.get("ancestor_codes") or [],
            "ancestor_names": ca.get("ancestor_names") or [],
        })

    tree = build_account_tree(
        rows_meta=rows_meta_for_tree,
        row_mapping_meta={
            h["row_index"]: {
                "is_leaf": h.get("is_leaf", True),
                "is_summary": h.get("is_summary", False),
                "participates_in_entry": row_mapping_meta.get(h["row_index"], {}).get(
                    "participates_in_entry", True
                ),
            }
            for h in hierarchy
        },
    )

    # 2) 准备 per-row recommendation lookup（用 recommend_mappings 已有结果作为锚点推荐源）
    rec_by_row: dict[int, dict] = {}
    for rec in mapping_recommendations:
        ri = rec.get("row_index")
        if ri is not None:
            rec_by_row[ri] = rec

    async def _recommend_anchor(node: AccountTreeNode) -> AnchorResolution | None:
        """对 anchor / breakpoint 节点执行完整推荐（已用 recommend_mappings 跑过）。"""
        rec = rec_by_row.get(node.row_index)
        if rec is None:
            return AnchorResolution(
                standard_account_id=None,
                standard_account_code=None,
                standard_account_name=None,
                source=None,
                reason="无推荐结果",
                is_resolved=False,
            )
        # 优先使用后端 auto_confirm_candidate，否则尝试 pick unique safe
        cand = rec.get("auto_confirm_candidate") or pick_unique_auto_confirm_candidate(
            rec.get("candidates", [])
        )
        if cand:
            sa_id = cand.get("standard_account_id")
            return AnchorResolution(
                standard_account_id=sa_id,
                standard_account_code=cand.get("standard_account_code"),
                standard_account_name=cand.get("standard_account_name"),
                source=cand.get("source") or "auto",
                reason=cand.get("reason") or "唯一安全候选",
                is_resolved=True,
                auto_confirm_status=rec.get("auto_confirm_status") or "unique_safe",
                auto_confirm_reason=rec.get("auto_confirm_reason"),
            )
        # 没有自动确认候选：从已有候选中挑选 score 最高的（不自动确认）
        cands = rec.get("candidates", [])
        if cands:
            best = max(cands, key=lambda c: float(c.get("score", 0) or 0))
            return AnchorResolution(
                standard_account_id=best.get("standard_account_id"),
                standard_account_code=best.get("standard_account_code"),
                standard_account_name=best.get("standard_account_name"),
                source=best.get("source"),
                reason=best.get("reason"),
                is_resolved=bool(best.get("standard_account_id")),
                auto_confirm_status=rec.get("auto_confirm_status") or "none",
                auto_confirm_reason=rec.get("auto_confirm_reason") or "需用户手动选择",
            )
        return AnchorResolution(
            standard_account_id=None,
            standard_account_code=None,
            standard_account_name=None,
            source=None,
            reason="无候选",
            is_resolved=False,
            auto_confirm_status=rec.get("auto_confirm_status") or "none",
            auto_confirm_reason=rec.get("auto_confirm_reason") or "无候选，需用户手动选择",
        )

    # 3) 运行继承映射计划
    tree, mapping_summary = await build_anchor_mapping_plan(
        tree=tree,
        db=db,
        customer_label=customer_label,
        source_label=source_label,
        recommend_anchor_fn=_recommend_anchor,
    )

    # 4) 把映射角色 / 模式合并进 mapping_recommendations
    for rec in mapping_recommendations:
        ri = rec.get("row_index")
        if ri is None:
            continue
        node = tree.nodes_by_row.get(ri)
        if node is None:
            continue
        rec["mapping_role"] = node.mapping_role
        rec["mapping_mode"] = node.mapping_mode
        rec["requires_confirmation"] = node.requires_confirmation
        rec["anchor_row_index"] = node.anchor_row_index
        rec["anchor_client_account_code"] = node.anchor_client_account_code
        rec["anchor_client_account_name"] = node.anchor_client_account_name
        rec["resolved_standard_account_id"] = node.resolved_standard_account_id
        rec["resolved_standard_account_code"] = node.resolved_standard_account_code
        rec["resolved_standard_account_name"] = node.resolved_standard_account_name
        rec["resolution_source"] = node.resolution_source
        rec["resolution_reason"] = node.resolution_reason
        rec["inheritance_break_reason"] = node.inheritance_break_reason
        rec["inheritance_evidence"] = list(node.inheritance_evidence)
        rec["descendant_leaf_count"] = node.descendant_leaf_count
        rec["auto_confirm_status"] = node.auto_confirm_status
        rec["auto_confirm_reason"] = node.auto_confirm_reason
        rec["parent_row_index"] = node.parent_row_index
        rec["parent_client_account_code"] = (
            tree.nodes_by_row[node.parent_row_index].client_account_code
            if node.parent_row_index is not None
            and node.parent_row_index in tree.nodes_by_row
            else None
        )
        rec["parent_client_account_name"] = (
            tree.nodes_by_row[node.parent_row_index].client_account_name
            if node.parent_row_index is not None
            and node.parent_row_index in tree.nodes_by_row
            else None
        )
        rec["client_account_full_path"] = node.full_path
        # 普通 inherited 行不显示独立候选（避免被误解为可选）
        if node.mapping_role == "inherited":
            rec["candidates"] = []
            rec["auto_confirm_candidate"] = None
        elif node.mapping_role in {"structural_summary", "ignored"}:
            rec["candidates"] = []
            rec["auto_confirm_candidate"] = None

    # 5) 未解析叶子行单独检查（基于新映射角色）
    for rec in mapping_recommendations:
        if not rec.get("participates_in_entry", True):
            continue
        if rec.get("mapping_role") in {"inherited", "anchor", "breakpoint", "explicit_override"}:
            if rec.get("resolved_standard_account_id"):
                continue
        if rec.get("mapping_role") == "unresolved":
            errors.append({
                "row_index": rec.get("row_index"),
                "code": rec.get("client_account_code") or "",
                "message": (
                    f"客户科目「{rec.get('client_account_code') or '?'} "
                    f"{rec.get('client_account_name') or '?'}」"
                    f"未能通过锚点/继承解析唯一标准科目，请手动选择"
                ),
                "category": "unmapped_account",
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
        "mapping_strategy": "anchor_inheritance_v1",
        "mapping_strategy_version": 1,
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
        "mapping_summary": mapping_summary_to_dict(mapping_summary),
        "mapping_strategy": "anchor_inheritance_v1",
    }


def mapping_summary_to_dict(s: MappingPlanSummary) -> dict:
    """将 MappingPlanSummary 序列化成 dict。"""
    return {
        "total_nodes": s.total_nodes,
        "structural_summary_count": s.structural_summary_count,
        "anchor_count": s.anchor_count,
        "inherited_count": s.inherited_count,
        "breakpoint_count": s.breakpoint_count,
        "explicit_override_count": s.explicit_override_count,
        "unresolved_count": s.unresolved_count,
        "confirmation_required_count": s.confirmation_required_count,
        "participating_leaf_count": s.participating_leaf_count,
        "resolved_participating_leaf_count": s.resolved_participating_leaf_count,
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
    mapping_strategy_version: int = 1,
) -> dict:
    """
    执行导入：校验 → 保存原始行 → 生成标准余额表 → 保存映射经验。

    ANCHOR-INHERITANCE-MAPPING：confirmed_mappings 只提交锚点 / 中断点 /
    显式覆盖。execute 重新构建树和映射计划，对 inherited 节点自动沿树
    继承解析后的标准科目。任一参与入库的末级未解析唯一标准科目 → 阻止执行。

    Returns:
        dict with entry_count, raw_row_count, mapping_saved_count, mapping_saved,
              debug_timings (各阶段耗时秒数)
    """
    import time as _time
    _timings: dict[str, float] = {}

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

    # TASK-083: 如果没有确认映射，直接跳过解析和执行，避免大文件（如205201 98k行）空跑。
    # 不得返回 status=executed，否则调用方会误判「导入成功」。改为 skipped 语义，
    # 验收脚本必须把 skipped 视为未完成导入（除非显式配置允许跳过）。
    if not confirmed_mappings:
        logger.info("execute_standard_import: no confirmed mappings, skipping execution")
        if batch.status not in ("previewed", "analyzed"):
            # 保留批次原状态，不擅自改成 executed
            await db.flush()
        return {
            "status": "skipped",
            "reason": "no_confirmed_mappings",
            "entry_count": 0,
            "mapping_saved_count": 0,
            "raw_row_count": 0,
        }

    _t0 = _time.time()
    headers, rows, data_start, header_rows = _load_import_rows(file_path, parse_config)
    _timings["load_rows"] = round(_time.time() - _t0, 2)

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
                "direction_column_id": fm.get("direction_column_id"),
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

    # TASK-084 性能优化：预加载所有涉及的 StandardAccount 到内存，
    # 避免后续逐行 DB 查询（98k 行 × 2 次查询 = 196k 次 → 1 次批量查询）。
    all_sa_ids: set[uuid.UUID] = set()
    for cm in confirmed_mappings:
        sid = cm.get("standard_account_id")
        if not sid:
            continue
        try:
            all_sa_ids.add(sid if isinstance(sid, uuid.UUID) else uuid.UUID(str(sid)))
        except (ValueError, TypeError):
            pass
    sa_cache: dict[uuid.UUID, StandardAccount] = {}
    if all_sa_ids:
        sa_result = await db.execute(
            select(StandardAccount).where(StandardAccount.id.in_(list(all_sa_ids)))
        )
        for sa in sa_result.scalars().all():
            sa_cache[sa.id] = sa

    # 重新构建 row_inputs 并运行 transform
    _t0 = _time.time()
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
                        direction_column_id=pc.get("direction_column_id"),
                    ))

        # 确定标准方向（从缓存读取，不再逐行查 DB）
        cm = confirmed_by_row.get(row_idx)
        std_dir = None
        if cm:
            sa_id = cm.get("standard_account_id")
            if sa_id:
                sa = sa_cache.get(sa_id)
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
    _timings["build_and_transform"] = round(_time.time() - _t0, 2)

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

    # ANCHOR-INHERITANCE-MAPPING：在 execute 阶段重新构建客户科目树，
    # 应用用户提交的 confirmed_mappings（仅锚点 / 显式覆盖），重新计算
    # 继承映射计划。普通 inherited 节点会自动沿树继承解析后的标准科目。
    _t0_tree = _time.time()
    rows_meta_exec: list[dict] = []
    code_to_row_idx_exec: dict[str, int] = {}
    for ri in row_inputs:
        if ri.client_account_code:
            code_to_row_idx_exec[ri.client_account_code.strip()] = ri.row_index

    hier_code, _ = detect_hierarchy_by_code(row_inputs)
    hier_indent, _ = detect_hierarchy_by_indent(row_inputs)
    hier_flat = assign_flat_hierarchy(row_inputs)
    if hierarchy_mode == "code":
        hier_merged_exec = hier_code
    elif hierarchy_mode == "indent":
        hier_merged_exec = hier_indent
    elif hierarchy_mode == "flat":
        hier_merged_exec = hier_flat
    else:
        hier_merged_exec = merge_hierarchy(hier_code, hier_indent, hier_flat)

    hier_by_row_exec = {h.get("row_index"): h for h in hier_merged_exec}

    for ri in row_inputs:
        h = hier_by_row_exec.get(ri.row_index, {})
        # 父级 / 祖先
        parent_key = h.get("parent_key")
        parent_row_index = None
        if parent_key:
            if parent_key in code_to_row_idx_exec:
                parent_row_index = code_to_row_idx_exec[parent_key]
            else:
                try:
                    parent_row_index = int(parent_key)
                except (ValueError, TypeError):
                    parent_row_index = None

        ancestor_codes: list[str] = []
        ancestor_names: list[str] = []
        if ri.client_account_code:
            cur = ri.client_account_code.strip()
            visited: set[str] = set()
            while cur and cur not in visited:
                visited.add(cur)
                found = None
                for end in range(len(cur) - 1, 0, -1):
                    c = cur[:end]
                    if c in code_to_row_idx_exec and c != cur:
                        found = c
                        break
                if found:
                    anc_ri = code_to_row_idx_exec[found]
                    anc_input = next((x for x in row_inputs if x.row_index == anc_ri), None)
                    if anc_input:
                        ancestor_codes.append(anc_input.client_account_code)
                        ancestor_names.append(anc_input.client_account_name or "")
                    cur = found
                else:
                    break

        rows_meta_exec.append({
            "row_index": ri.row_index,
            "client_account_code": ri.client_account_code,
            "client_account_name": ri.client_account_name,
            "level": h.get("level"),
            "parent_key": parent_key,
            "is_leaf": h.get("is_leaf", True),
            "is_summary": h.get("is_summary", False),
            "ancestor_codes": ancestor_codes,
            "ancestor_names": ancestor_names,
        })

    tree_exec = build_account_tree(
        rows_meta=rows_meta_exec,
        row_mapping_meta={
            ri.row_index: {
                "is_leaf": hier_by_row_exec.get(ri.row_index, {}).get("is_leaf", True),
                "is_summary": hier_by_row_exec.get(ri.row_index, {}).get("is_summary", False),
                "participates_in_entry": (
                    bool(ri.client_account_code or ri.client_account_name)
                    and hier_by_row_exec.get(ri.row_index, {}).get("is_leaf", True)
                    and not hier_by_row_exec.get(ri.row_index, {}).get("is_summary", False)
                    and ri.row_index not in execute_auto_skip_rows
                ),
            }
            for ri in row_inputs
        },
        ignored_rows=ignored_row_set,
    )

    # 把用户确认的映射（锚点 / 显式覆盖）转成 override 字典
    explicit_overrides: dict[int, str] = {}
    override_full_paths: dict[int, str] = {}
    for cm in confirmed_mappings:
        ri = cm.get("row_index")
        if ri is None:
            continue
        sa_id = cm.get("standard_account_id")
        if not sa_id:
            continue
        try:
            sa_id_str = str(uuid.UUID(str(sa_id)))
        except (ValueError, TypeError):
            sa_id_str = str(sa_id)
        explicit_overrides[ri] = sa_id_str
        # 完整路径
        node = tree_exec.nodes_by_row.get(ri)
        if node is not None:
            override_full_paths[ri] = node.full_path

    # 用户确认的锚点也要补 mapping_role
    for ri, cm in {cm.get("row_index"): cm for cm in confirmed_mappings}.items():
        if ri is None:
            continue
        node = tree_exec.nodes_by_row.get(ri)
        if node is None:
            continue
        if node.mapping_role not in {"anchor", "breakpoint", "explicit_override"}:
            # 之前是 inherited/unresolved → 用户确认后转为显式锚点
            node.mapping_role = "anchor"
            node.mapping_mode = "direct_confirmed"

    # 对所有用户确认的目标，把目标 ID 应用到对应节点
    for ri, target_id in explicit_overrides.items():
        node = tree_exec.nodes_by_row.get(ri)
        if node is None:
            continue
        sa = sa_cache.get(uuid.UUID(target_id)) if isinstance(target_id, str) else None
        if sa is None:
            try:
                sa = sa_cache.get(uuid.UUID(target_id))
            except (ValueError, TypeError):
                sa = None
        if sa is None:
            # 重新查
            try:
                stmt = select(StandardAccount).where(
                    StandardAccount.id == uuid.UUID(target_id)
                )
                sa = (await db.execute(stmt)).scalar_one_or_none()
                if sa is not None:
                    sa_cache[sa.id] = sa
            except Exception:
                sa = None
        if sa is not None:
            node.resolved_standard_account_id = str(sa.id)
            node.resolved_standard_account_code = sa.account_code
            node.resolved_standard_account_name = sa.account_name

    # 重新运行继承映射计划（保留用户已应用的目标）
    # 先把 confirmed_mappings 视为「预设 anchor」，传入
    def _user_confirmed_anchor_lookup(ri: int) -> dict | None:
        for cm in confirmed_mappings:
            if cm.get("row_index") == ri:
                return cm
        return None

    # 用 evaluate_inheritance_boundary 沿树重新解析
    # 第一步：标记所有用户确认的锚点
    anchor_targets: dict[int, dict] = {}
    for cm in confirmed_mappings:
        ri = cm.get("row_index")
        if ri is None:
            continue
        anchor_targets[ri] = cm

    # 第二步：从根到叶传播
    async def _propagate(ri: int, inherited: dict | None) -> None:
        node = tree_exec.nodes_by_row[ri]
        if node.is_ignored:
            node.mapping_role = "ignored"
            node.mapping_mode = "none"
            return
        if is_structural_summary(node):
            node.mapping_role = "structural_summary"
            node.mapping_mode = "none"
            for ch in tree_exec.children_by_row.get(ri, []):
                await _propagate(ch, None)
            return
        if ri in anchor_targets:
            cm = anchor_targets[ri]
            sa = None
            try:
                sa = sa_cache.get(uuid.UUID(str(cm["standard_account_id"])))
            except Exception:
                sa = None
            if sa is None:
                # 强制查询
                try:
                    stmt = select(StandardAccount).where(
                        StandardAccount.id == uuid.UUID(str(cm["standard_account_id"]))
                    )
                    sa = (await db.execute(stmt)).scalar_one_or_none()
                    if sa is not None:
                        sa_cache[sa.id] = sa
                except Exception:
                    sa = None
            if sa is not None:
                if cm.get("mapping_action") == "override" or node.mapping_role == "explicit_override":
                    node.mapping_role = "explicit_override"
                    node.mapping_mode = "override_confirmed"
                else:
                    node.mapping_role = "anchor"
                    node.mapping_mode = "direct_confirmed"
                node.resolved_standard_account_id = str(sa.id)
                node.resolved_standard_account_code = sa.account_code
                node.resolved_standard_account_name = sa.account_name
                node.resolution_source = "user_confirmed"
                node.resolution_reason = cm.get("selection_source") or "用户确认"
                node.requires_confirmation = False
                new_inh = {
                    "sa": sa,
                    "row_index": ri,
                }
                for ch in tree_exec.children_by_row.get(ri, []):
                    await _propagate(ch, new_inh)
                return
            # 找不到标准科目 → 失败
            node.mapping_role = "unresolved"
            node.requires_confirmation = True
            return

        if inherited is None:
            # 无上级锚点：unresolved（execute 阶段不应有未确认锚点）
            node.mapping_role = "unresolved"
            node.requires_confirmation = True
            return

        anc_sa = inherited["sa"]
        decision = evaluate_inheritance_boundary(
            node=node,
            inherited_standard_account=anc_sa,
            strong_direct_signal=None,  # execute 不重新查询历史信号，依靠 confirm
        )
        if not decision.should_break:
            node.mapping_role = "inherited"
            node.mapping_mode = "inherited_ancestor"
            node.anchor_row_index = inherited["row_index"]
            anc_node = tree_exec.nodes_by_row.get(inherited["row_index"])
            if anc_node is not None:
                node.anchor_client_account_code = anc_node.client_account_code
                node.anchor_client_account_name = anc_node.client_account_name
            node.resolved_standard_account_id = str(anc_sa.id)
            node.resolved_standard_account_code = anc_sa.account_code
            node.resolved_standard_account_name = anc_sa.account_name
            node.resolution_source = "inherited_ancestor"
            node.resolution_reason = decision.reason
            node.inheritance_evidence = list(decision.evidence)
            for ch in tree_exec.children_by_row.get(ri, []):
                await _propagate(ch, inherited)
            return
        # 中断：execute 不应再有 unresolved 中断点（应由用户在 analyze 阶段解决）
        node.mapping_role = "unresolved"
        node.inheritance_break_reason = decision.reason_code
        node.inheritance_evidence = list(decision.evidence)
        node.requires_confirmation = True
        for ch in tree_exec.children_by_row.get(ri, []):
            await _propagate(ch, None)

    for root_ri in tree_exec.root_rows:
        await _propagate(root_ri, None)

    _timings["anchor_plan_rebuild"] = round(_time.time() - _t0_tree, 2)

    # 校验：所有参与入库的末级必须有唯一解析
    unmapped_leaves: list[dict] = []
    for n in tree_exec.nodes_by_row.values():
        if n.is_ignored or n.is_summary or not n.participates_in_entry:
            continue
        if n.mapping_role in {"structural_summary", "ignored"}:
            continue
        if n.mapping_role == "unresolved" or not n.resolved_standard_account_id:
            unmapped_leaves.append({
                "row_index": n.row_index,
                "client_account_code": n.client_account_code,
                "client_account_name": n.client_account_name,
            })

    if unmapped_leaves:
        detail = "; ".join(
            f"行 {u['row_index']}「{u.get('client_account_code') or '?'} {u.get('client_account_name') or '?'}」"
            for u in unmapped_leaves[:5]
        )
        batch.status = "blocked"
        await db.flush()
        raise ValueError(
            f"存在 {len(unmapped_leaves)} 个末级客户科目无法通过上级锚点、继承规则或用户覆盖确定标准科目: {detail}"
        )

    # 7. 校验：按标准方向拆分的叶子行必须有方向
    for n in tree_exec.nodes_by_row.values():
        if n.is_ignored or n.is_summary or not n.participates_in_entry:
            continue
        if not n.resolved_standard_account_id:
            continue
        sa = sa_cache.get(uuid.UUID(n.resolved_standard_account_id))
        if sa is None or not sa.is_active:
            batch.status = "blocked"
            await db.flush()
            raise ValueError(
                f"行 {n.row_index} 映射的标准科目「{n.resolved_standard_account_code}」"
                f"{'不存在' if sa is None else '已停用'}，请重新选择"
            )

    # 重新按 row_inputs 检查方向
    leaf_by_row = {leaf.row_index: leaf for leaf in leaves}
    for ri in row_inputs:
        if ri.row_index in ignored_row_set:
            continue
        n = tree_exec.nodes_by_row.get(ri.row_index)
        if n is None or not n.resolved_standard_account_id:
            continue
        try:
            sa = sa_cache.get(uuid.UUID(n.resolved_standard_account_id))
        except Exception:
            sa = None
        if sa is None:
            continue
        for ac in ri.amount_configs:
            if ac.mode == "single_by_direction":
                if not sa.balance_direction:
                    batch.status = "blocked"
                    await db.flush()
                    raise ValueError(
                        f"行 {ri.row_index} 金额列 '{ac.amount_field}' 选择了「按标准方向拆分」，"
                        f"但映射的标准科目「{sa.account_code} {sa.account_name}」余额方向为空，请改为显式借/贷方"
                    )

    # 8. 保存原始行快照（所有行，包括父级和末级）
    # ANCHOR-INHERITANCE-MAPPING：每行携带 mapping_role / mapping_mode /
    # mapping_source / mapping_anchor_raw_row_id / inheritance_*
    _t0 = _time.time()
    raw_row_map: dict[int, uuid.UUID] = {}  # row_index → raw_row_id
    raw_row_obj_map: dict[int, StandardTrialBalanceRawRow] = {}  # TASK-085: row_index → ORM object
    result_by_row = {r.row_index: r for r in transform_result.rows}  # 所有行的转换结果
    # TASK-085: 预建 leaf dict 避免 O(n²) 查找
    leaf_by_row = {leaf.row_index: leaf for leaf in leaves}

    # 用 tree_exec 节点来填充 mapping_role / anchor_raw_row_id
    for ri in row_inputs:
        leaf = leaf_by_row.get(ri.row_index)
        is_leaf = leaf is not None
        is_user_ignored = ri.row_index in ignored_row_set
        node = tree_exec.nodes_by_row.get(ri.row_index)
        resolved_sa_id = node.resolved_standard_account_id if node else None

        if is_user_ignored:
            mapping_status = "ignored"
        elif resolved_sa_id:
            mapping_status = "mapped"
        elif node and node.mapping_role in {"structural_summary", "ignored"}:
            mapping_status = "ignored"
        elif ri.client_account_code or ri.client_account_name:
            mapping_status = "unmapped"
        else:
            mapping_status = "ignored"

        # 优先用 transform_result 的层级信息（覆盖所有行，不仅叶子）
        tr = result_by_row.get(ri.row_index)
        detected_level = tr.level if tr else (leaf.level if leaf else None)
        raw_is_leaf = bool(tr and tr.is_leaf and not tr.is_summary) if tr else is_leaf
        row_warnings = {"warnings": leaf.warnings, "errors": leaf.errors} if leaf else None

        # ANCHOR-INHERITANCE-MAPPING：追溯字段
        anchor_row_id = None
        if node and node.anchor_row_index is not None:
            anchor_row_id = raw_row_map.get(node.anchor_row_index)
        if node and node.mapping_role in {"anchor", "breakpoint", "explicit_override"}:
            anchor_row_id_for_self = None  # self, will be set after flush
        else:
            anchor_row_id_for_self = anchor_row_id

        # mapped_standard_account_id 需要 UUID 对象（ORM Mapped[uuid.UUID|None]）
        resolved_sa_uuid = None
        if resolved_sa_id:
            try:
                resolved_sa_uuid = uuid.UUID(resolved_sa_id)
            except (ValueError, TypeError):
                resolved_sa_uuid = None

        raw_row = StandardTrialBalanceRawRow(
            batch_id=batch_id,
            row_index=ri.row_index,
            raw_values=ri.values,
            client_account_code=ri.client_account_code,
            client_account_name=ri.client_account_name,
            detected_level=detected_level,
            is_leaf=raw_is_leaf,
            mapped_standard_account_id=resolved_sa_uuid,
            mapping_status=mapping_status,
            mapping_role=node.mapping_role if node else None,
            mapping_mode=node.mapping_mode if node else None,
            mapping_source=node.resolution_source if node else None,
            mapping_anchor_raw_row_id=anchor_row_id_for_self,
            inheritance_reason=node.resolution_reason if node else None,
            inheritance_break_reason=node.inheritance_break_reason if node else None,
            requires_manual_confirmation=bool(node.requires_confirmation) if node else False,
            warnings=row_warnings,
        )
        db.add(raw_row)
        raw_row_map[ri.row_index] = raw_row.id
        # TASK-085：同时保留 ORM 对象引用，供后续 parent_assign 直接使用
        raw_row_obj_map[ri.row_index] = raw_row

    # flush 一次后，再次扫描：把 anchor/breakpoint 节点的 anchor_raw_row_id
    # 设为 self（继承行已经指向它们了）
    await db.flush()
    for ri in row_inputs:
        node = tree_exec.nodes_by_row.get(ri.row_index)
        if node is None:
            continue
        if node.mapping_role in {"anchor", "breakpoint", "explicit_override"}:
            self_id = raw_row_map.get(ri.row_index)
            if self_id is not None:
                raw_row_obj_map[ri.row_index].mapping_anchor_raw_row_id = self_id

    # 一次性 flush 所有 raw rows，获取数据库分配的 id
    await db.flush()
    _timings["raw_row_insert"] = round(_time.time() - _t0, 2)

    # 9. 给所有行补 parent_raw_row_id（不只是叶子行）
    # TASK-085 优化：直接使用 step 8 保留的 ORM 对象引用，
    # 避免逐行 db.get(StandardTrialBalanceRawRow, row_id) 查询（98k 行 → 0 次额外查询）。
    _t0 = _time.time()
    # 用代码→行索引的快速查找替代逐行扫描
    code_to_row_idx: dict[str, int] = {}
    for ri in row_inputs:
        if ri.client_account_code:
            code_to_row_idx[ri.client_account_code.strip()] = ri.row_index

    for tr in transform_result.rows:
        if not tr.parent_key:
            continue
        # parent_key 可能是代码或 row_index 字符串
        parent_idx = None
        try:
            parent_idx = int(tr.parent_key)
        except (ValueError, TypeError):
            parent_idx = code_to_row_idx.get(tr.parent_key)

        if parent_idx is not None and parent_idx in raw_row_obj_map and tr.row_index in raw_row_obj_map:
            parent_id = raw_row_map.get(parent_idx)
            if parent_id is not None:
                raw_row_obj_map[tr.row_index].parent_raw_row_id = parent_id

    await db.flush()
    _timings["parent_assign"] = round(_time.time() - _t0, 2)

    # 10. 生成标准科目余额表明细（只写叶子行）
    # ANCHOR-INHERITANCE-MAPPING：使用 tree_exec 的解析结果，不依赖逐行 confirmed_by_row。
    # TASK-084 性能优化：使用预加载的 sa_cache，不再逐行查 DB。
    _t0 = _time.time()
    # 构建叶子行 set 加速查找
    leaf_row_indices = {leaf.row_index for leaf in leaves}
    entry_count = 0
    for leaf in leaves:
        if leaf.row_index in ignored_row_set:
            continue
        node = tree_exec.nodes_by_row.get(leaf.row_index)
        if node is None or not node.resolved_standard_account_id:
            continue

        # 从缓存获取标准科目快照
        try:
            sa = sa_cache.get(uuid.UUID(node.resolved_standard_account_id))
        except Exception:
            sa = None
        if sa is None:
            continue

        # ANCHOR-INHERITANCE-MAPPING：entry 携带映射来源快照
        anc_node = (
            tree_exec.nodes_by_row.get(node.anchor_row_index)
            if node.anchor_row_index is not None
            else None
        )

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
            mapping_mode_snapshot=node.mapping_mode,
            mapping_source_snapshot=node.resolution_source,
            mapping_anchor_client_account_code_snapshot=(
                anc_node.client_account_code if anc_node else node.anchor_client_account_code
            ),
            mapping_anchor_client_account_name_snapshot=(
                anc_node.client_account_name if anc_node else node.anchor_client_account_name
            ),
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
    _timings["entry_insert"] = round(_time.time() - _t0, 2)

    # 11. 保存映射经验 — ANCHOR-INHERITANCE-MAPPING：
    # 只保存 anchor / breakpoint / explicit_override 行；
    # 普通 inherited 行不进入经验库（防止经验污染）。
    # TASK-085 性能优化：按 (code, name, standard_account_id) 去重。
    _t0 = _time.time()
    mapping_saved: list[dict] = []
    if save_mapping_experience:
        seen_keys: set[tuple] = set()
        for n in tree_exec.nodes_by_row.values():
            if n.is_ignored:
                continue
            if n.mapping_role not in {"anchor", "breakpoint", "explicit_override"}:
                continue
            if not n.resolved_standard_account_id:
                continue
            if n.is_summary and not n.participates_in_entry:
                # 非参与父级锚点：仍可保存映射经验（用于跨批次）
                pass
            if not n.client_account_code and not n.client_account_name:
                continue
            try:
                sa = sa_cache.get(uuid.UUID(n.resolved_standard_account_id))
            except Exception:
                sa = None
            if sa is None:
                continue

            # 去重：同 (code, name, sa_id) 只保存一次
            dedup_key = (
                (n.client_account_code or "").strip(),
                (n.client_account_name or "").strip(),
                n.resolved_standard_account_id,
            )
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            mapping_kind = (
                "override" if n.mapping_role == "explicit_override" else "anchor"
            )
            try:
                result = await save_mapping(
                    db=db,
                    data_type="trial_balance",
                    customer_label=customer_label,
                    client_account_code=n.client_account_code,
                    client_account_name=n.client_account_name,
                    standard_account_id=sa.id,
                    standard_account_code=sa.account_code,
                    standard_account_name=sa.account_name,
                    source=(
                        "user_confirmed"
                        if n.mapping_mode in {"direct_confirmed", "override_confirmed"}
                        else "user_corrected"
                    ),
                    confidence=1.0,
                    allow_overwrite=True,
                    client_account_full_path=n.full_path or None,
                    mapping_kind=mapping_kind,
                )
                mapping_saved.append({
                    "client_account_code": n.client_account_code,
                    "standard_account_code": sa.account_code,
                    "status": result.get("status", "unknown"),
                    "mapping_kind": mapping_kind,
                    "client_account_full_path": n.full_path or None,
                })
            except Exception as e:
                logger.warning(f"保存映射经验失败: {e}")

    _timings["save_mapping"] = round(_time.time() - _t0, 2)

    # 12. 更新批次状态 + 统计
    batch.status = "executed"
    await db.flush()

    # ANCHOR-INHERITANCE-MAPPING：映射角色统计
    role_count = {"anchor": 0, "inherited": 0, "breakpoint": 0,
                  "explicit_override": 0, "unresolved": 0, "structural_summary": 0, "ignored": 0}
    for n in tree_exec.nodes_by_row.values():
        role_count[n.mapping_role] = role_count.get(n.mapping_role, 0) + 1

    return {
        "batch_id": str(batch.id),
        "status": batch.status,
        "entry_count": entry_count,
        "raw_row_count": len(row_inputs),
        "mapping_saved_count": len(mapping_saved),
        "mapping_saved": mapping_saved,
        "anchor_count": role_count["anchor"],
        "breakpoint_count": role_count["breakpoint"],
        "inherited_count": role_count["inherited"],
        "explicit_override_count": role_count["explicit_override"],
        "unresolved_leaf_count": sum(
            1
            for n in tree_exec.nodes_by_row.values()
            if n.mapping_role == "unresolved" and n.participates_in_entry
        ),
        "mapping_strategy_version": mapping_strategy_version,
        "debug_timings": _timings,
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

    # TASK-085：用 count 查询替代全量加载（205201 有 18984 条 entry）
    count_result = await db.execute(
        select(func.count(StandardTrialBalanceEntry.id)).where(
            StandardTrialBalanceEntry.batch_id == batch_id
        )
    )
    entry_count = count_result.scalar() or 0

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
        "entry_count": entry_count,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "updated_at": batch.updated_at.isoformat() if batch.updated_at else None,
    }
