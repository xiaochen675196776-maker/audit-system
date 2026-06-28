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

TASK-094D：跳过行分类统一 — Analyze 与 Execute 调用同一个
``classify_import_rows``，得到五类行：
  - eligible_business_leaf_rows：应入库的业务末级（生成 entry）
  - zero_amount_template_rows：所有金额字段均为 0/空 的模板占位行
  - summary_total_rows：名称或结构含「合计/小计/总计/累计」的行
  - duplicate_aggregate_rows：金额约等于子级汇总、但未带合计关键词的行
  - ignored_business_rows：用户主动忽略的真实业务末级
"""

import uuid
import os
import re
import shutil
import logging
from dataclasses import dataclass, field
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
    AnchorDiscoveryResult,
    MappingPlanSummary,
    UniqueAccountGraph,
    UniqueAccountNode,
    build_account_tree,
    build_unique_account_graph,
    discover_anchor_candidates,
    resolve_mapping_plan,
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


def _coerce_uuid_str(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return str(value if isinstance(value, uuid.UUID) else uuid.UUID(str(value)))
    except (TypeError, ValueError):
        return None


def _require_v2_node_key(node_key: str | None) -> str:
    if not node_key or not str(node_key).startswith("uak:v2:"):
        raise ValueError(f"unsupported node_key version: {node_key}")
    return str(node_key)


def _serialize_row_node_bindings(graph: UniqueAccountGraph) -> list[dict]:
    bindings: list[dict] = []
    for row_index, node_key in sorted(graph.row_to_node_key.items()):
        un = graph.nodes_by_key.get(node_key)
        representative = un.representative_row_index if un else None
        bindings.append({
            "row_index": row_index,
            "node_key": node_key,
            "representative_row_index": representative,
            "is_representative": representative == row_index,
        })
    return bindings


def _serialize_unique_mapping_nodes(
    graph: UniqueAccountGraph,
    rec_by_row: dict[int, dict] | None = None,
) -> list[dict]:
    rec_by_row = rec_by_row or {}
    out: list[dict] = []
    for node_key, un in sorted(
        graph.nodes_by_key.items(),
        key=lambda item: item[1].representative_row_index
        if item[1].representative_row_index is not None
        else 10**12,
    ):
        if un.representative_row_index is None:
            continue
        rep_rec = rec_by_row.get(un.representative_row_index, {})
        auto = rep_rec.get("auto_confirm_candidate") or {}
        suggested_id = (
            un.suggested_standard_account_id
            or rep_rec.get("suggested_standard_account_id")
            or auto.get("standard_account_id")
        )
        out.append({
            "node_key": node_key,
            "representative_row_index": un.representative_row_index,
            "source_row_count": len(un.source_row_indexes),
            "source_row_indexes": list(un.source_row_indexes),
            "account_code": un.account_code,
            "account_name": un.account_name,
            "full_path": un.full_path,
            "parent_node_key": un.parent_node_key,
            "node_type": un.node_type,
            "mapping_role": un.mapping_role,
            "requires_confirmation": un.requires_confirmation,
            "resolved_standard_account_id": un.resolved_standard_account_id,
            "suggested_standard_account_id": suggested_id,
            "candidates": list(rep_rec.get("candidates") or un.candidates or []),
        })
    return out


def _collapse_confirmed_mappings_to_node_mappings(
    *,
    graph: UniqueAccountGraph,
    tree: AccountTree,
    confirmed_mappings: list[dict] | None,
    confirmed_node_mappings: list[dict] | None,
) -> tuple[list[dict], int, int, int]:
    by_node: dict[str, dict] = {}

    def add_mapping(node_key_value: str | None, payload: dict, source: str) -> None:
        node_key = _require_v2_node_key(node_key_value)
        un = graph.nodes_by_key.get(node_key)
        if un is None:
            raise ValueError(f"unknown node_key: {node_key}")
        standard_id = _coerce_uuid_str(payload.get("standard_account_id"))
        if standard_id is None:
            raise ValueError(f"confirmed mapping for node_key {node_key} missing standard_account_id")
        existing = by_node.get(node_key)
        if existing is not None:
            existing_id = _coerce_uuid_str(existing.get("standard_account_id"))
            if existing_id != standard_id:
                raise ValueError(
                    f"same node_key maps to different standard accounts: {node_key}"
                )
            return

        representative = un.representative_row_index
        if representative is None:
            raise ValueError(f"node_key {node_key} has no representative row")
        node = tree.nodes_by_row.get(representative)
        row_payload = {
            "row_index": representative,
            "client_account_code": (
                payload.get("client_account_code")
                or (node.client_account_code if node else None)
            ),
            "client_account_name": (
                payload.get("client_account_name")
                or (node.client_account_name if node else None)
            ),
            "standard_account_id": uuid.UUID(standard_id),
            "standard_account_code": payload.get("standard_account_code"),
            "standard_account_name": payload.get("standard_account_name"),
            "mapping_action": payload.get("mapping_action") or "anchor",
            "apply_to_descendants": bool(payload.get("apply_to_descendants", True)),
            "selection_source": payload.get("selection_source") or "user_confirmed",
            "node_key": node_key,
            "confirmation_source": source,
        }
        by_node[node_key] = row_payload

    for cm in confirmed_node_mappings or []:
        add_mapping(cm.get("node_key"), cm, "node")

    for cm in confirmed_mappings or []:
        try:
            row_index = int(cm.get("row_index"))
        except (TypeError, ValueError):
            continue
        node_key = graph.row_to_node_key.get(row_index)
        if node_key is None:
            raise ValueError(f"row_index {row_index} has no node_key binding")
        add_mapping(node_key, cm, "row")

    normalized = sorted(by_node.values(), key=lambda cm: int(cm["row_index"]))
    auto_count = sum(
        1 for cm in normalized
        if cm.get("selection_source") == "auto_confirmed"
    )
    manual_count = len(normalized) - auto_count
    return normalized, len(normalized), auto_count, manual_count


def _count_unresolved_unique_nodes(
    graph: UniqueAccountGraph,
    tree: AccountTree,
) -> int:
    count = 0
    for un in graph.nodes_by_key.values():
        participating_rows = [
            ri for ri in un.source_row_indexes
            if (
                tree.nodes_by_row.get(ri) is not None
                and tree.nodes_by_row[ri].participates_in_entry
                and not tree.nodes_by_row[ri].is_ignored
            )
        ]
        if not participating_rows:
            continue
        if not any(
            tree.nodes_by_row[ri].resolved_standard_account_id
            for ri in participating_rows
        ):
            count += 1
    return count


def _propagate_unique_node_resolution(
    graph: UniqueAccountGraph,
    tree: AccountTree,
) -> None:
    fields = (
        "mapping_role",
        "mapping_mode",
        "requires_confirmation",
        "anchor_row_index",
        "anchor_client_account_code",
        "anchor_client_account_name",
        "resolved_standard_account_id",
        "resolved_standard_account_code",
        "resolved_standard_account_name",
        "suggested_standard_account_id",
        "suggested_standard_account_code",
        "suggested_standard_account_name",
        "resolution_source",
        "resolution_reason",
        "inheritance_break_reason",
        "auto_confirm_status",
        "auto_confirm_reason",
    )
    for un in graph.nodes_by_key.values():
        source_node = None
        for row_index in un.source_row_indexes:
            node = tree.nodes_by_row.get(row_index)
            if node is not None and node.resolved_standard_account_id:
                source_node = node
                break
        if source_node is None:
            continue
        for row_index in un.source_row_indexes:
            node = tree.nodes_by_row.get(row_index)
            if node is None or node is source_node:
                continue
            for field_name in fields:
                setattr(node, field_name, getattr(source_node, field_name))
            node.inheritance_evidence = list(source_node.inheritance_evidence)


def _apply_confirmed_descendant_propagation(
    tree: AccountTree,
    confirmed_mappings: list[dict],
) -> None:
    confirmed_rows = {
        int(cm["row_index"])
        for cm in confirmed_mappings
        if cm.get("row_index") is not None
    }

    def iter_descendants(row_index: int):
        for child_row in tree.children_by_row.get(row_index, []):
            yield child_row
            yield from iter_descendants(child_row)

    for cm in confirmed_mappings:
        if not cm.get("apply_to_descendants", True):
            continue
        try:
            source_row = int(cm.get("row_index"))
        except (TypeError, ValueError):
            continue
        source = tree.nodes_by_row.get(source_row)
        if source is None or not source.resolved_standard_account_id:
            continue
        for child_row in iter_descendants(source_row):
            if child_row in confirmed_rows:
                continue
            node = tree.nodes_by_row.get(child_row)
            if node is None or node.is_ignored:
                continue
            if node.mapping_role in {"anchor", "breakpoint", "explicit_override"}:
                continue
            node.mapping_role = "inherited"
            node.mapping_mode = "inherited_ancestor"
            node.requires_confirmation = False
            node.anchor_row_index = source.row_index
            node.anchor_client_account_code = source.client_account_code
            node.anchor_client_account_name = source.client_account_name
            node.resolved_standard_account_id = source.resolved_standard_account_id
            node.resolved_standard_account_code = source.resolved_standard_account_code
            node.resolved_standard_account_name = source.resolved_standard_account_name
            node.suggested_standard_account_id = source.suggested_standard_account_id
            node.suggested_standard_account_code = source.suggested_standard_account_code
            node.suggested_standard_account_name = source.suggested_standard_account_name
            node.resolution_source = "node_binding"
            node.resolution_reason = "inherited from confirmed node mapping"
            node.inheritance_break_reason = None
            node.inheritance_evidence = [f"anchor_row_index={source.row_index}"]
            node.auto_confirm_status = source.auto_confirm_status
            node.auto_confirm_reason = source.auto_confirm_reason


def _resolve_hierarchy_parent_row_index(
    h: dict,
    code_to_row_index: dict[str, int],
) -> int | None:
    """Resolve hierarchy parent without treating numeric account codes as row indexes."""
    parent_key = h.get("parent_key")
    if not parent_key:
        return None
    parent_key_str = str(parent_key)
    if parent_key_str in code_to_row_index:
        return code_to_row_index[parent_key_str]
    if h.get("level_source") == "indent_suggested":
        try:
            return int(parent_key_str)
        except (ValueError, TypeError):
            return None
    return None


def _parent_row_is_code_compatible(
    child_code: str | None,
    parent_code: str | None,
) -> bool:
    if not child_code or not parent_code:
        return True
    child = child_code.strip()
    parent = parent_code.strip()
    if not child or not parent:
        return True
    return child != parent and child.startswith(parent)


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


# ── TASK-094D：跳过行分类与勾稽口径统一 ─────────────


# TASK-094D：合计/小计/总计 关键词集合（与 _collect_summary_total_skip_rows 一致）
_SUMMARY_TOTAL_KEYWORDS = (
    "合计", "总计", "小计", "本页合计", "本月合计", "累计",
    "（资产）小计", "(资产)小计", "（负债）小计", "(负债)小计",
    "（权益）小计", "(权益)小计", "（损益）小计", "(损益)小计",
    "资产）小计", "资产)小计", "负债）小计", "负债)小计",
    "权益）小计", "权益)小计", "损益）小计", "损益)小计",
)

# TASK-094D：页脚元数据关键词（与 _collect_summary_total_skip_rows 一致）
_FOOTER_KEYWORDS = (
    "核算单位", "制单人", "打印时间", "打印日期", "编制单位",
    "审核人", "记账人", "财务主管", "单位负责人",
)

# TASK-094D：配置科目 / 非过帐科目关键词（与 _collect_summary_total_skip_rows 一致）
_CONFIG_NAME_KEYWORDS = (
    "不过帐", "不记帐", "不记账", "设置用", "系统设置", "暂存",
)

# TASK-094D：金额容差（与现有 amount_reconciliation 一致）
_AMOUNT_RECON_TOLERANCE = Decimal("0.01")


def _amount_field_indices(period_configs: list[dict], col_id_to_index: dict[str, int]) -> list[int]:
    """提取 period_configs 中所有「金额」单元格索引。"""
    indices: list[int] = []
    for pc in period_configs:
        if pc.get("mode") == "two_column":
            for f in (pc.get("debit_field"), pc.get("credit_field")):
                ci = col_id_to_index.get(f) if f else None
                if ci is not None:
                    indices.append(ci)
        else:
            f = pc.get("amount_field")
            ci = col_id_to_index.get(f) if f else None
            if ci is not None:
                indices.append(ci)
    return sorted(set(indices))


def _row_decimal_amounts(row: list, amount_cell_indices: list[int]) -> dict[int, Decimal]:
    """读取一行中所有金额单元格的 Decimal 值（无法解析视为 0）。"""
    out: dict[int, Decimal] = {}
    for ci in amount_cell_indices:
        val = row[ci] if ci < len(row) else None
        out[ci] = _amount_decimal_or_zero(val)
    return out


def _amount_decimal_or_zero(value: Any) -> Decimal:
    """与 _amount_decimal 类似，但更宽松（无法解析视为 0）。"""
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        try:
            return Decimal(str(value))
        except Exception:
            return Decimal("0")
    s = str(value).strip()
    if not s or s in ("None", "—", "-", "·"):
        return Decimal("0")
    try:
        return Decimal(s.replace(",", "").replace("，", ""))
    except Exception:
        return Decimal("0")


def _row_has_summary_keyword(code: str, name: str) -> bool:
    """合计/小计/总计/累计 关键词判定（与 _collect_summary_total_skip_rows 一致）。"""
    code_s = (code or "").strip()
    name_s = (name or "").strip()
    combined = f"{code_s} {name_s}"
    return any(kw in code_s or kw in name_s or kw in combined for kw in _SUMMARY_TOTAL_KEYWORDS)


def _row_is_footer_or_config(code: str, name: str) -> bool:
    """页脚元数据或非过帐配置科目标识（与 _collect_summary_total_skip_rows 一致）。

    旧逻辑把这些行也归入 auto_skip_rows；TASK-094D 将其归入
    ``zero_amount_template_rows`` / ``summary_total_rows`` 的姊妹分类：
    不参与入库、不计入业务金额。本函数返回 True 的行不进 eligible。
    """
    code_s = (code or "").strip()
    name_s = (name or "").strip()
    if any(kw in code_s for kw in _FOOTER_KEYWORDS):
        return True
    if any(kw in name_s for kw in _CONFIG_NAME_KEYWORDS):
        return True
    return False


@dataclass
class RowClassificationResult:
    """TASK-094D：统一行分类结果。

    五类行集合（在 leaf 行范围内两两不相交）：
    - ``eligible_business_leaf_rows``：应入库的业务末级（生成 entry）
    - ``zero_amount_template_rows``：所有金额字段均为 0/空 的纯模板占位
    - ``summary_total_rows``：名称或代码含「合计/小计/总计/累计」关键词
    - ``duplicate_aggregate_rows``：非关键词，但金额约等于子级汇总
    - ``ignored_business_rows``：用户主动忽略的真实业务末级

    附加：
    - ``structural_rows``：父级（is_summary=True）行 + 上三类行；用于
      build_account_tree 时排除，避免结构性汇总污染参与末级。
    - ``base_leaf_rows``：分类的输入域（即「所有有身份且 is_leaf 且 !is_summary」的
      原始行），五类行集合均 ⊆ ``base_leaf_rows``。
    """

    eligible_business_leaf_rows: set[int] = field(default_factory=set)
    zero_amount_template_rows: set[int] = field(default_factory=set)
    summary_total_rows: set[int] = field(default_factory=set)
    duplicate_aggregate_rows: set[int] = field(default_factory=set)
    ignored_business_rows: set[int] = field(default_factory=set)
    base_leaf_rows: set[int] = field(default_factory=set)
    structural_rows: set[int] = field(default_factory=set)

    # 兼容旧字段语义：所有「自动跳过」行的并集（不含 user-ignored）。
    def auto_skip_rows(self) -> set[int]:
        return (
            self.zero_amount_template_rows
            | self.summary_total_rows
            | self.duplicate_aggregate_rows
        )

    @property
    def raw_identified_leaf_count(self) -> int:
        """五类行集合计数之和（应等于 base_leaf_rows 大小）。"""
        return (
            len(self.eligible_business_leaf_rows)
            + len(self.zero_amount_template_rows)
            + len(self.summary_total_rows)
            + len(self.duplicate_aggregate_rows)
            + len(self.ignored_business_rows)
        )

    @property
    def entry_count(self) -> int:
        return len(self.eligible_business_leaf_rows)


def classify_import_rows(
    *,
    rows: list[list],
    period_configs: list[dict],
    col_id_to_index: dict[str, int],
    code_col_id: str | None,
    name_col_id: str | None,
    hierarchy: list[dict],
    user_ignored_rows: set[int] | None = None,
    tolerance: Decimal | None = None,
) -> RowClassificationResult:
    """TASK-094D：统一行分类 — Analyze 与 Execute 共用入口。

    参数：
    - ``rows`` / ``period_configs`` / ``col_id_to_index``：与
      ``_collect_zero_amount_template_rows`` 一致。
    - ``code_col_id`` / ``name_col_id``：用于读取每行 code/name。
    - ``hierarchy``：``merge_hierarchy`` 输出（list of dict），含
      ``row_index / is_leaf / is_summary / parent_key / parent_row_index``。
    - ``user_ignored_rows``：用户主动忽略的行（仅 leaf）。
    - ``tolerance``：duplicate_aggregate 检测的金额容差。

    返回 ``RowClassificationResult``。该函数无副作用、纯计算，可在 Analyze
    与 Execute 中分别调用得到一致的分类口径。
    """
    user_ignored_rows = set(user_ignored_rows or set())
    tol = tolerance if tolerance is not None else _AMOUNT_RECON_TOLERANCE

    code_idx = col_id_to_index.get(code_col_id) if code_col_id else None
    name_idx = col_id_to_index.get(name_col_id) if name_col_id else None
    amount_indices = _amount_field_indices(period_configs, col_id_to_index)

    # 1) 收集 base_leaf_rows 与 hierarchy_summary_rows
    hier_by_row: dict[int, dict] = {h.get("row_index"): h for h in hierarchy}
    base_leaf_rows: set[int] = set()
    hierarchy_summary_rows: set[int] = set()
    for ri, row in enumerate(rows):
        h = hier_by_row.get(ri, {})
        code = _safe_str(row[code_idx]) if code_idx is not None and code_idx < len(row) else ""
        name = _safe_str(row[name_idx]) if name_idx is not None and name_idx < len(row) else ""
        is_leaf = bool(h.get("is_leaf", True))
        is_summary = bool(h.get("is_summary", False))
        if not (code or name):
            continue
        if is_summary:
            hierarchy_summary_rows.add(ri)
            continue
        if is_leaf:
            base_leaf_rows.add(ri)

    # 2) 计算每行六个金额字段值（leaf + 父级都计算，用于 duplicate_aggregate 检测）
    row_amounts: dict[int, dict[int, Decimal]] = {}
    for ri in (base_leaf_rows | hierarchy_summary_rows):
        if 0 <= ri < len(rows):
            row_amounts[ri] = _row_decimal_amounts(rows[ri], amount_indices)

    def _row_sum(r: int) -> Decimal:
        amts = row_amounts.get(r, {})
        s = Decimal("0")
        for v in amts.values():
            s += v
        return s

    # 3) 名称 / 代码读出（仅 leaf + parent）
    code_name_by_row: dict[int, tuple[str, str]] = {}
    for ri in (base_leaf_rows | hierarchy_summary_rows):
        if 0 <= ri < len(rows):
            row = rows[ri]
            code = _safe_str(row[code_idx]) if code_idx is not None and code_idx < len(row) else ""
            name = _safe_str(row[name_idx]) if name_idx is not None and name_idx < len(row) else ""
            code_name_by_row[ri] = (code, name)

    # 4) duplicate_aggregate 检测：父级（is_summary=True）且非关键词，
    #    且任一金额字段约等于其直接子级金额合计。
    children_by_row: dict[int, list[int]] = {}
    for ri in hierarchy_summary_rows:
        for child_ri in base_leaf_rows:
            h_child = hier_by_row.get(child_ri, {})
            pk = h_child.get("parent_key")
            if pk is None:
                continue
            parent_match = False
            try:
                if int(pk) == ri:
                    parent_match = True
            except (ValueError, TypeError):
                if pk == code_name_by_row.get(ri, ("", ""))[0]:
                    parent_match = True
            if parent_match:
                children_by_row.setdefault(ri, []).append(child_ri)

    duplicate_aggregate_rows: set[int] = set()
    for ri in hierarchy_summary_rows:
        code, name = code_name_by_row.get(ri, ("", ""))
        if _row_has_summary_keyword(code, name):
            continue
        children = children_by_row.get(ri, [])
        if not children:
            continue
        amts_self = row_amounts.get(ri, {})
        amts_children = [row_amounts.get(c, {}) for c in children]
        # 至少有一个金额字段「父级 ≈ 子级合计」才算 duplicate aggregate
        match_count = 0
        nonzero_count = 0
        for ci, amt_self in amts_self.items():
            child_sum = sum((a.get(ci, Decimal("0")) for a in amts_children), Decimal("0"))
            if abs(amt_self) > Decimal("0") or abs(child_sum) > Decimal("0"):
                nonzero_count += 1
            if abs(amt_self - child_sum) <= tol:
                match_count += 1
        if nonzero_count > 0 and match_count == len(amts_self):
            duplicate_aggregate_rows.add(ri)

    # 5) zero_amount_template：所有金额字段均为 0/空（无论是否叶子）
    zero_amount_template_rows: set[int] = set()
    for ri in (base_leaf_rows | hierarchy_summary_rows):
        amts = row_amounts.get(ri, {})
        if not amts:
            continue
        if all(abs(v) <= tol for v in amts.values()):
            zero_amount_template_rows.add(ri)

    # 6) summary_total：名称 / 代码含合计关键词 OR 页脚/配置关键词（与旧逻辑一致）
    summary_total_rows: set[int] = set()
    for ri in (base_leaf_rows | hierarchy_summary_rows):
        code, name = code_name_by_row.get(ri, ("", ""))
        if _row_has_summary_keyword(code, name) or _row_is_footer_or_config(code, name):
            summary_total_rows.add(ri)

    # 7) ignored_business：仅 leaf 中由用户主动忽略的部分
    ignored_business_rows: set[int] = set(user_ignored_rows & base_leaf_rows)

    # 8) 在 leaf 范围内做「优先级降序」分配（互斥）：
    #    ignored > summary_total > zero_amount_template > duplicate_aggregate > eligible
    assigned: set[int] = set()
    eligible: set[int] = set()
    zero_leaf: set[int] = set()
    summary_leaf: set[int] = set()
    duplicate_leaf: set[int] = set()

    for ri in base_leaf_rows:
        if ri in ignored_business_rows:
            continue  # ignored_business_rows 已记录
        if ri in summary_total_rows:
            summary_leaf.add(ri)
            assigned.add(ri)
            continue
        if ri in zero_amount_template_rows:
            zero_leaf.add(ri)
            assigned.add(ri)
            continue
        if ri in duplicate_aggregate_rows:
            duplicate_leaf.add(ri)
            assigned.add(ri)
            continue
        eligible.add(ri)
        assigned.add(ri)

    # 9) structural_rows = 父级 + leaf 中的 summary_total + leaf 中的 duplicate_aggregate
    structural_rows: set[int] = set(hierarchy_summary_rows)
    structural_rows |= summary_leaf
    structural_rows |= duplicate_leaf

    return RowClassificationResult(
        eligible_business_leaf_rows=eligible,
        zero_amount_template_rows=zero_leaf,
        summary_total_rows=summary_leaf,
        duplicate_aggregate_rows=duplicate_leaf,
        ignored_business_rows=ignored_business_rows,
        base_leaf_rows=set(base_leaf_rows),
        structural_rows=structural_rows,
    )


def summarize_amount_reconciliation(
    *,
    eligible_business_leaf_rows: set[int],
    ignored_business_rows: set[int],
    entry_amount_totals: dict[str, Decimal],
    row_amount_lookups: dict[int, dict[str, Decimal]],
    fields: list[str],
    tolerance: Decimal | None = None,
) -> dict[str, dict[str, str]]:
    """TASK-094D：业务金额勾稽 — 仅使用真正业务末级（不混入汇总/重复）。

    等式（任务文档第 5 节）：
        eligible_business_leaf_amount = entry_amount + ignored_business_amount
    其中 eligible_business_leaf_amount 在任务文档上下文中指「全部业务末级
    金额」= eligible + ignored；eligible 是「应生成 entry 的末级集合」
    （去掉了 user-ignored）。

    注：此等式是分类正确性的恒等式 — 当分类正确时，entry 仅来自 eligible
    集合（被 ignored 的行不会再生成 entry），ignored 与 entry 互斥。
    任何「eligible 行但 entry 漏算」或「ignored 行但生成了 entry」都会让
    difference 非零。该函数暴露四个分量供报告与断言使用。
    """
    tol = tolerance if tolerance is not None else _AMOUNT_RECON_TOLERANCE
    out: dict[str, dict[str, str]] = {}
    for field in fields:
        eligible_total = sum(
            (row_amount_lookups.get(ri, {}).get(field, Decimal("0"))
             for ri in eligible_business_leaf_rows),
            Decimal("0"),
        )
        ignored_total = sum(
            (row_amount_lookups.get(ri, {}).get(field, Decimal("0"))
             for ri in ignored_business_rows),
            Decimal("0"),
        )
        entry_total = entry_amount_totals.get(field, Decimal("0"))
        # 任务文档口径：eligible_business_leaf_amount = entry + ignored
        # 也就是 total_business_leaf_amount = entry + ignored
        total_business_leaf_amount = eligible_total + ignored_total
        difference = total_business_leaf_amount - entry_total - ignored_total
        out[field] = {
            "source": str(total_business_leaf_amount),
            "entry": str(entry_total),
            "eligible": str(eligible_total),
            "ignored": str(ignored_total),
            "difference": str(difference),
            "ok": "true" if abs(difference) <= tol else "false",
        }
    return out


def summarize_summary_reconciliation(
    *,
    summary_total_rows: set[int],
    duplicate_aggregate_rows: set[int],
    hierarchy_summary_rows: set[int],
    children_by_row: dict[int, list[int]],
    row_amount_lookups: dict[int, dict[str, Decimal]],
    fields: list[str],
    tolerance: Decimal | None = None,
) -> dict[str, dict[str, Any]]:
    """TASK-094D：汇总 / 重复 行父子金额勾稽 — 与业务勾稽分离。

    等式：父级金额 ≈ 直接或全部子级金额合计（允许 0.01 误差）。
    不通过则 ``warning=summary_amount_mismatch``，但仍可生成 entry（汇总行
    不参与 entry，所以该告警只是诊断信息）。
    """
    tol = tolerance if tolerance is not None else _AMOUNT_RECON_TOLERANCE
    out: dict[str, dict[str, Any]] = {}
    parent_rows = (hierarchy_summary_rows | summary_total_rows | duplicate_aggregate_rows)
    for ri in parent_rows:
        amts_self = row_amount_lookups.get(ri, {})
        children = children_by_row.get(ri, [])
        if not children:
            continue
        per_field: dict[str, dict[str, str]] = {}
        mismatch_count = 0
        for field in fields:
            v_self = amts_self.get(field, Decimal("0"))
            v_child = sum(
                (row_amount_lookups.get(c, {}).get(field, Decimal("0"))
                 for c in children),
                Decimal("0"),
            )
            diff = v_self - v_child
            ok = abs(diff) <= tol
            if not ok and (abs(v_self) > tol or abs(v_child) > tol):
                mismatch_count += 1
            per_field[field] = {
                "self": str(v_self),
                "children_sum": str(v_child),
                "difference": str(diff),
                "ok": "true" if ok else "false",
            }
        out[str(ri)] = {
            "fields": per_field,
            "mismatch_count": mismatch_count,
            "warning": None if mismatch_count == 0 else "summary_amount_mismatch",
        }
    return out


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
    batch_id: uuid.UUID | str,
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
    # TASK-091：防御性转换 batch_id 为 UUID 对象（ORM id 字段是 uuid.UUID）
    if isinstance(batch_id, str):
        try:
            batch_id = uuid.UUID(batch_id)
        except (ValueError, TypeError):
            raise ValueError(f"批次 {batch_id} 不是合法 UUID")

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
    code_counts: dict[str, int] = {}
    for ri in row_inputs_no_dir:
        if ri.client_account_code:
            code = ri.client_account_code.strip()
            code_counts[code] = code_counts.get(code, 0) + 1

    code_to_row_info: dict[str, dict] = {}
    for ri in row_inputs_no_dir:
        if ri.client_account_code:
            code = ri.client_account_code.strip()
            if code_counts.get(code, 0) != 1:
                continue
            code_to_row_info[code] = {
                "row_index": ri.row_index,
                "code": code,
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
    code_to_row_idx_unique = {
        code: info["row_index"]
        for code, info in code_to_row_info.items()
    }
    row_input_no_dir_by_row = {ri.row_index: ri for ri in row_inputs_no_dir}
    for i, ri in enumerate(row_inputs_no_dir):
        h = merged_hier[i] if i < len(merged_hier) else {}
        parent_row_index = _resolve_hierarchy_parent_row_index(
            h,
            code_to_row_idx_unique,
        )
        if parent_row_index is not None:
            parent_input = row_input_no_dir_by_row.get(parent_row_index)
            if parent_input and not _parent_row_is_code_compatible(
                ri.client_account_code,
                parent_input.client_account_code,
            ):
                parent_row_index = None
        hierarchy.append({
            "row_index": ri.row_index,
            "client_account_code": ri.client_account_code,
            "client_account_name": ri.client_account_name,
            "level": h.get("level"),
            "parent_key": h.get("parent_key"),
            "parent_row_index": parent_row_index,
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

    # TASK-094D：统一行分类 — Analyze 与 Execute 共用 classify_import_rows。
    # 五类行：eligible / zero / summary_total / duplicate_aggregate / ignored。
    # Analyze 阶段 user_ignored 暂为空集（前端尚未提交忽略）。
    classification = classify_import_rows(
        rows=rows,
        period_configs=period_configs,
        col_id_to_index=col_id_to_index,
        code_col_id=code_col_id,
        name_col_id=name_col_id,
        hierarchy=hierarchy,
        user_ignored_rows=set(),
    )
    # 兼容旧字段语义：所有「自动跳过」行（不含 user-ignored）
    auto_skip_rows = classification.auto_skip_rows()
    # TASK-094C：从 auto_skip_rows 中排除父级（is_summary=True）行。
    # 父级即使金额为 0，仍然应当作为 anchor / 继承源点参与映射计划，
    # 否则其子节点无法继承，会全部变成 unresolved。
    hierarchy_summary_rows = {
        h["row_index"]
        for h in hierarchy
        if h.get("is_summary")
    }
    auto_skip_rows = {
        ri for ri in auto_skip_rows
        if ri not in hierarchy_summary_rows
    }
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

    # 9. ANCHOR-INHERITANCE-MAPPING v2：
    #    先构建客户科目树，做轻量级结构汇总 + 锚点发现；
    #    再仅对 anchor / breakpoint 调用 recommend_mappings；
    #    普通 inherited / structural_summary / ignored 节点不进入完整推荐。
    ca_by_row: dict[int, dict] = {
        ca.get("row_index"): ca for ca in client_accounts_for_mapping
        if ca.get("row_index") is not None
    }
    rows_meta_for_tree: list[dict] = []
    for i, ri in enumerate(row_inputs_no_dir):
        h = hierarchy[i] if i < len(hierarchy) else {}
        ca = ca_by_row.get(ri.row_index, {})
        rows_meta_for_tree.append({
            "row_index": ri.row_index,
            "client_account_code": ri.client_account_code,
            "client_account_name": ri.client_account_name,
            "level": h.get("level"),
            "parent_key": h.get("parent_key"),
            "parent_row_index": h.get("parent_row_index"),
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

    # TASK-094C：构建唯一科目节点图 + 行→节点绑定
    unique_graph = build_unique_account_graph(
        tree=tree,
        rows_meta=rows_meta_for_tree,
        customer_label=customer_label,
    )
    row_to_node_key_map = dict(unique_graph.row_to_node_key)
    node_by_key_map = dict(unique_graph.nodes_by_key)

    # 10. 轻量锚点发现（不做 recommend_mappings，仅分类 + 强信号 + 中断检测）
    discovery = await discover_anchor_candidates(
        tree=tree,
        db=db,
        customer_label=customer_label,
    )

    # 11. 决定哪些 client_accounts 必须送进 recommend_mappings：
    #     anchor_rows + breakpoint_candidate_rows
    #     普通 inherited / structural / ignored 一律跳过
    # TASK-094C：把 anchor/breakpoint 行集合按 node_key 折叠，
    # 避免同一唯一节点被送进多次完整推荐。
    # 注意：折叠会导致锚点丢失 + 继承链断裂（不同行同 node_key 但有各自子节点），
    # 因此保留原始行集合但注入 node_key 元数据供后续处理。
    full_rec_row_indexes: set[int] = (
        discovery.anchor_rows | discovery.breakpoint_candidate_rows
    )

    # 12. 把 client_accounts_for_mapping 拆成「需完整推荐」+「轻量处理」
    full_rec_accounts: list[dict] = []
    full_rec_index_map: dict[tuple, int] = {}  # dedup_key → index in full_rec_accounts
    for ca in client_accounts_for_mapping:
        ri = ca.get("row_index")
        if ri is None:
            continue
        if ri not in full_rec_row_indexes:
            continue
        full_rec_accounts.append(ca)

    # TASK-081：大文件先去重（按 code/name/ancestors）
    _dedup_key_to_first_idx: dict[tuple, int] = {}
    for idx, ca in enumerate(full_rec_accounts):
        key = (
            (ca.get("client_account_code") or "").strip(),
            (ca.get("client_account_name") or "").strip(),
            tuple(ca.get("ancestor_codes") or []),
            tuple(ca.get("ancestor_names") or []),
        )
        if key not in _dedup_key_to_first_idx:
            _dedup_key_to_first_idx[key] = idx

    unique_full_rec = [
        full_rec_accounts[i] for i in _dedup_key_to_first_idx.values()
    ]
    unique_full_recommendation_node_count = len(unique_full_rec)
    if unique_full_rec:
        unique_recommendations = await recommend_mappings(
            db=db,
            data_type="trial_balance",
            client_accounts=unique_full_rec,
            customer_label=customer_label,
            source_label=source_label,
        )
    else:
        unique_recommendations = []

    # 回填去重结果
    _dedup_result_map: dict[tuple, dict] = {}
    for idx, rec in enumerate(unique_recommendations):
        ca = unique_full_rec[idx]
        key = (
            (ca.get("client_account_code") or "").strip(),
            (ca.get("client_account_name") or "").strip(),
            tuple(ca.get("ancestor_codes") or []),
            tuple(ca.get("ancestor_names") or []),
        )
        _dedup_result_map[key] = rec

    # 13. 为所有 client_accounts_for_mapping 构造 mapping_recommendations
    #     anchor/breakpoint 行：填充完整推荐结果
    #     inherited 行：candidates=[]，等 build_mapping_plan 阶段填 inherited 信息
    #     structural/ignored 行：candidates=[]
    mapping_recommendations: list[dict] = []
    for ca in client_accounts_for_mapping:
        ri = ca.get("row_index")
        key = (
            (ca.get("client_account_code") or "").strip(),
            (ca.get("client_account_name") or "").strip(),
            tuple(ca.get("ancestor_codes") or []),
            tuple(ca.get("ancestor_names") or []),
        )
        rec: dict
        if ri in full_rec_row_indexes and key in _dedup_result_map:
            src = _dedup_result_map[key]
            rec = {
                "client_account_code": ca.get("client_account_code"),
                "client_account_name": ca.get("client_account_name"),
                "candidates": list(src.get("candidates", [])),
                "auto_confirm_candidate": src.get("auto_confirm_candidate"),
                "auto_confirm_status": src.get("auto_confirm_status"),
                "auto_confirm_reason": src.get("auto_confirm_reason"),
            }
        else:
            # 普通 inherited / structural / ignored → 不进入完整推荐
            rec = {
                "client_account_code": ca.get("client_account_code"),
                "client_account_name": ca.get("client_account_name"),
                "candidates": [],
                "auto_confirm_candidate": None,
                "auto_confirm_status": None,
                "auto_confirm_reason": None,
            }
        rec["row_index"] = ri
        meta = row_mapping_meta.get(ri, {}) if ri is not None else {}
        rec["is_leaf"] = meta.get("is_leaf")
        rec["is_summary"] = meta.get("is_summary")
        rec["participates_in_entry"] = meta.get("participates_in_entry")
        rec["parent_row_index"] = (
            tree.nodes_by_row[ri].parent_row_index if ri in tree.nodes_by_row else None
        )
        rec["parent_client_account_code"] = (
            tree.nodes_by_row[ri].parent_key if ri in tree.nodes_by_row else None
        )
        # TASK-094C：注入 node_key 与节点级元数据
        nk = row_to_node_key_map.get(ri) if ri is not None else None
        rec["node_key"] = nk
        if nk and nk in node_by_key_map:
            un = node_by_key_map[nk]
            rec["node_type"] = un.node_type
            rec["node_source_row_indexes"] = list(un.source_row_indexes)
            rec["node_representative_row_index"] = un.representative_row_index
            rec["node_duplicate_binding"] = (
                un.representative_row_index != ri
            )
            rec["mapping_editable"] = (
                un.representative_row_index == ri and un.node_type == "account"
            )
            rec["deprecated"] = bool(rec["node_duplicate_binding"])
        else:
            rec["node_type"] = "account"
            rec["node_source_row_indexes"] = [ri] if ri is not None else []
            rec["node_representative_row_index"] = ri
            rec["node_duplicate_binding"] = False
            rec["mapping_editable"] = ri is not None
            rec["deprecated"] = False
        mapping_recommendations.append(rec)

    # TASK-078：辅助核算明细行继承父科目候选注入。
    # 仅对有完整推荐结果的 anchor/breakpoint 行注入；
    # 普通 inherited 行不需注入（由 build_mapping_plan 自动继承）。
    inherited_auxiliary_rows = _inject_auxiliary_inherited_candidates(
        mapping_recommendations=mapping_recommendations,
        rows=rows,
        code_col_id=code_col_id,
        name_col_id=name_col_id,
        col_id_to_index=col_id_to_index,
    )

    # 14. 建立 (code,name) → top direction 的快速查找（只对有完整推荐的行）
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

    # 方向查找：先 auto_confirm_candidate，再 pick_unique_auto_confirm_candidate
    rec_direction_map: dict[tuple, str | None] = {}
    rec_direction_by_row: dict[int, str | None] = {}
    for rec in mapping_recommendations:
        key = (rec.get("client_account_code"), rec.get("client_account_name"))
        candidates = rec.get("candidates", [])
        if candidates:
            top = rec.get("auto_confirm_candidate") or pick_unique_auto_confirm_candidate(candidates)
            rec_direction_map[key] = top.get("standard_balance_direction") if top else None
        else:
            rec_direction_map[key] = None
        row_index = rec.get("row_index")
        if row_index is not None:
            rec_direction_by_row[row_index] = rec_direction_map[key]

    # 15. 重新构建带方向和金额配置的 row_inputs 并运行金额拆分
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

        key = (ri.client_account_code, ri.client_account_name)
        best_direction = rec_direction_by_row.get(ri.row_index)
        if best_direction is None:
            best_direction = rec_direction_map.get(key)
        if best_direction is None and ri.client_account_code:
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

    # 16. 收集 errors 和 warnings
    errors: list[dict] = []
    warnings: list[dict] = []

    for e in transform_result.global_errors:
        errors.append({
            "row_index": None,
            "code": "",
            "message": e,
            "category": "no_direction" if "方向缺失" in e or "无法按标准方向" in e else "missing_amount",
        })

    for w in transform_result.global_warnings:
        m = re.match(r"行 (\d+):", w)
        if m:
            row_idx = int(m.group(1))
            if row_idx in auto_skip_rows:
                continue
        cat = "parent_amount_mismatch" if "不一致" in w else "negative_amount" if "负数" in w else "indent_suggested" if "缩进" in w else "other"
        warnings.append({
            "row_index": None,
            "code": "",
            "message": w,
            "category": cat,
        })

    for h in hierarchy:
        if h["level_source"] == "indent_suggested":
            warnings.append({
                "row_index": h["row_index"],
                "code": h.get("client_account_code") or "",
                "message": f"行 {h['row_index']} 的层级由缩进推断，level_source=indent_suggested，建议用户确认",
                "category": "indent_suggested",
            })

    if not period_configs:
        errors.append({
            "row_index": None,
            "code": "",
            "message": "至少需要映射一个期间金额列（期初/本期/期末），并指定拆分方式",
            "category": "missing_amount",
        })

    # 17. ANCHOR-INHERITANCE-MAPPING v2：
    #     构建轻量映射计划，仅对 anchor/breakpoint 调用完整推荐。
    rec_by_row: dict[int, dict] = {}
    for rec in mapping_recommendations:
        ri = rec.get("row_index")
        if ri is not None:
            rec_by_row[ri] = rec

    async def _recommend_anchor(node: AccountTreeNode) -> AnchorResolution | None:
        """对 anchor / breakpoint 节点执行完整推荐（已有 recommend_mappings 结果）。"""
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
        # TASK-090/092：先尝试后端 auto_confirm_candidate（仅当它是安全候选时）
        auto = rec.get("auto_confirm_candidate")
        candidates = rec.get("candidates", [])
        # 安全候选：score >= 0.9 + warning is None + auto_confirmable=True
        safe = [
            c for c in candidates
            if c.get("warning") is None
            and c.get("auto_confirmable") is True
            and float(c.get("score", 0) or 0) >= 0.9
            and c.get("standard_account_id")
        ]
        # 唯一安全候选 → resolved
        unique_safe_ids = {c.get("standard_account_id") for c in safe}
        if len(unique_safe_ids) == 1 and auto:
            sa_id = auto.get("standard_account_id")
            return AnchorResolution(
                standard_account_id=sa_id,
                standard_account_code=auto.get("standard_account_code"),
                standard_account_name=auto.get("standard_account_name"),
                source=auto.get("source") or "auto",
                reason=auto.get("reason") or "唯一安全候选",
                is_resolved=True,
                auto_confirm_status="unique_safe",
                auto_confirm_reason=rec.get("auto_confirm_reason") or "唯一安全候选",
                suggested_standard_account_id=auto.get("standard_account_id"),
                suggested_standard_account_code=auto.get("standard_account_code"),
                suggested_standard_account_name=auto.get("standard_account_name"),
                suggested_source=auto.get("source"),
                suggested_reason=auto.get("reason"),
            )
        # 多候选 / 不安全：仅 suggested，不得 resolved
        if candidates:
            # 找分数最高且非空 ID 的候选
            sorted_cands = sorted(
                [c for c in candidates if c.get("standard_account_id")],
                key=lambda c: float(c.get("score", 0) or 0),
                reverse=True,
            )
            if sorted_cands:
                best = sorted_cands[0]
                return AnchorResolution(
                    standard_account_id=None,
                    standard_account_code=None,
                    standard_account_name=None,
                    source=None,
                    reason="未确认最高分候选，仅作为 suggested",
                    is_resolved=False,
                    auto_confirm_status="ambiguous",
                    auto_confirm_reason=(
                        f"存在 {len(sorted_cands)} 个候选，无唯一安全自动确认"
                        if len(sorted_cands) > 1
                        else "候选不安全"
                    ),
                    suggested_standard_account_id=best.get("standard_account_id"),
                    suggested_standard_account_code=best.get("standard_account_code"),
                    suggested_standard_account_name=best.get("standard_account_name"),
                    suggested_source=best.get("source"),
                    suggested_reason=best.get("reason"),
                )
        return AnchorResolution(
            standard_account_id=None,
            standard_account_code=None,
            standard_account_name=None,
            source=None,
            reason="无候选",
            is_resolved=False,
            auto_confirm_status="none",
            auto_confirm_reason="无候选，需用户手动选择",
        )

    # 18. 运行继承映射计划（传入已 discovery 复用）
    mapping_plan = await resolve_mapping_plan(
        db=db,
        tree=tree,
        customer_label=customer_label,
        source_label=source_label,
        confirmed_mappings=[],
        ignored_rows=auto_skip_rows,
        mode="analyze",
        recommend_anchor_fn=_recommend_anchor,
        discovery=discovery,
    )
    tree = mapping_plan.tree
    mapping_summary = mapping_plan.summary
    mapping_summary.full_recommendation_node_count = unique_full_recommendation_node_count

    # 19. 把映射角色 / 模式合并进 mapping_recommendations
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
        rec["suggested_standard_account_id"] = node.suggested_standard_account_id
        rec["suggested_standard_account_code"] = node.suggested_standard_account_code
        rec["suggested_standard_account_name"] = node.suggested_standard_account_name
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

    # 20. 未解析叶子行单独检查（基于新映射角色 + 修正 inheritance_break）
    unique_graph = build_unique_account_graph(
        tree=tree,
        rows_meta=rows_meta_for_tree,
        customer_label=customer_label,
    )
    row_to_node_key_map = dict(unique_graph.row_to_node_key)
    node_by_key_map = dict(unique_graph.nodes_by_key)
    unique_mapping_nodes = _serialize_unique_mapping_nodes(unique_graph, rec_by_row)
    row_node_bindings = _serialize_row_node_bindings(unique_graph)

    for rec in mapping_recommendations:
        if not rec.get("participates_in_entry", True):
            continue
        if rec.get("mapping_role") in {"inherited", "anchor", "breakpoint", "explicit_override"}:
            if rec.get("resolved_standard_account_id"):
                continue
        if rec.get("mapping_role") == "unresolved":
            role = rec.get("mapping_role")
            inheritance_break = rec.get("inheritance_break_reason")
            if inheritance_break:
                cat = "inheritance_break_unconfirmed"
                msg = (
                    f"客户科目「{rec.get('client_account_code') or '?'} "
                    f"{rec.get('client_account_name') or '?'}」"
                    f"继承中断（{inheritance_break}）但未确认目标，请手动选择"
                )
            elif rec.get("is_summary"):
                continue  # 父级不入库行不产生 unmapped
            else:
                cat = "mapping_anchor_unconfirmed"
                msg = (
                    f"客户科目「{rec.get('client_account_code') or '?'} "
                    f"{rec.get('client_account_name') or '?'}」"
                    f"作为映射锚点未确认标准科目，请手动选择"
                )
            errors.append({
                "row_index": rec.get("row_index"),
                "code": rec.get("client_account_code") or "",
                "message": msg,
                "category": cat,
            })

    # 更新批次状态和配置
    batch.status = "analyzed"
    batch.field_mapping = {"mappings": field_mappings}
    batch.amount_mapping_config = {"period_configs": period_configs}
    existing_hierarchy_config = batch.hierarchy_config or {}
    existing_parse_config = existing_hierarchy_config.get("parse_config") or {}
    if not existing_parse_config:
        existing_parse_config = {
            "data_start_row": data_start,
            "header_rows": header_rows,
            "merged_headers": headers,
        }
    # TASK-094C：唯一节点统计
    node_type_count = {"account": 0, "auxiliary": 0, "summary": 0}
    account_node_count = 0
    auxiliary_node_count = 0
    for un in unique_graph.nodes_by_key.values():
        node_type_count[un.node_type] = node_type_count.get(un.node_type, 0) + 1
        if un.node_type == "account":
            account_node_count += 1
        elif un.node_type == "auxiliary":
            auxiliary_node_count += 1
    duplicate_binding_count = sum(
        max(len(un.source_row_indexes) - 1, 0)
        for un in unique_graph.nodes_by_key.values()
    )
    batch.hierarchy_config = {
        "mode": hierarchy_mode,
        "parse_config": existing_parse_config,
        "inherited_auxiliary_rows": inherited_auxiliary_rows,
        "mapping_strategy": "anchor_inheritance_v2",
        "mapping_strategy_version": 2,
        "full_recommendation_node_count": mapping_summary.full_recommendation_node_count,
        "inherited_without_recommendation_count": mapping_summary.inherited_without_recommendation_count,
        # TASK-094C：唯一节点图统计
        "unique_node_count": len(unique_graph.nodes_by_key),
        "account_node_count": account_node_count,
        "auxiliary_node_count": auxiliary_node_count,
        "summary_node_count": node_type_count.get("summary", 0),
        "duplicate_binding_count": duplicate_binding_count,
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
        "mapping_strategy": "anchor_inheritance_v2",
        "unique_mapping_nodes": unique_mapping_nodes,
        "row_node_bindings": row_node_bindings,
        # TASK-094C：唯一节点图统计（前端可直接展示压缩率）
        "unique_node_count": len(unique_graph.nodes_by_key),
        "account_node_count": account_node_count,
        "auxiliary_node_count": auxiliary_node_count,
        "summary_node_count": node_type_count.get("summary", 0),
        "duplicate_binding_count": duplicate_binding_count,
        "raw_row_compression_ratio": (
            round(len(client_accounts_for_mapping) / max(len(unique_graph.nodes_by_key), 1), 2)
        ),
        # TASK-094D：Analyze 阶段返回 5 类行集合计数（Execute 同口径）
        "raw_identified_leaf_count": classification.raw_identified_leaf_count,
        "eligible_business_leaf_count": len(classification.eligible_business_leaf_rows),
        "ignored_business_count": len(classification.ignored_business_rows),
        "zero_template_count": len(classification.zero_amount_template_rows),
        "summary_total_count": len(classification.summary_total_rows),
        "duplicate_aggregate_count": len(classification.duplicate_aggregate_rows),
        "classification": {
            "eligible_business_leaf_rows": sorted(classification.eligible_business_leaf_rows),
            "zero_amount_template_rows": sorted(classification.zero_amount_template_rows),
            "summary_total_rows": sorted(classification.summary_total_rows),
            "duplicate_aggregate_rows": sorted(classification.duplicate_aggregate_rows),
            "ignored_business_rows": sorted(classification.ignored_business_rows),
            "base_leaf_rows": sorted(classification.base_leaf_rows),
            "structural_rows": sorted(classification.structural_rows),
        },
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
        "full_recommendation_node_count": s.full_recommendation_node_count,
        "light_signal_node_count": s.light_signal_node_count,
        "inherited_without_recommendation_count": s.inherited_without_recommendation_count,
    }


# ── Execute ────────────────────────────────────────

async def execute_standard_import(
    db: AsyncSession,
    batch_id: uuid.UUID | str,
    file_path: str,
    *,
    confirmed_mappings: list[dict] | None = None,
    confirmed_node_mappings: list[dict] | None = None,
    ignored_rows: list[int] | None = None,
    warnings_confirmed: bool = False,
    save_mapping_experience: bool = True,
    mapping_strategy_version: int = 2,
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
    confirmed_mappings = confirmed_mappings or []
    confirmed_node_mappings = confirmed_node_mappings or []
    row_level_confirmed_mapping_count = len(confirmed_mappings)

    # TASK-091：防御性转换 batch_id 为 UUID 对象（ORM id 字段是 uuid.UUID）
    if isinstance(batch_id, str):
        try:
            batch_id = uuid.UUID(batch_id)
        except (ValueError, TypeError):
            raise ValueError(f"批次 {batch_id} 不是合法 UUID")

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
    if not confirmed_mappings and not confirmed_node_mappings:
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
            "confirmed_node_mapping_count": 0,
            "auto_confirmed_node_count": 0,
            "manual_confirmed_node_count": 0,
            "duplicate_row_submit_count": 0,
            "row_level_confirmed_mapping_count": row_level_confirmed_mapping_count,
            "mapping_experience_saved_count": 0,
            "unresolved_node_count": 0,
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
    for cm in confirmed_node_mappings:
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

    _timings["build_base_rows"] = round(_time.time() - _t0, 2)

    # ANCHOR-INHERITANCE-MAPPING：在 execute 阶段重新构建客户科目树，
    # 应用用户提交的 confirmed_mappings（仅锚点 / 显式覆盖），重新计算
    # 继承映射计划。普通 inherited 节点会自动沿树继承解析后的标准科目。
    _t0_tree = _time.time()
    rows_meta_exec: list[dict] = []
    code_counts_exec: dict[str, int] = {}
    for ri in row_inputs:
        if ri.client_account_code:
            code = ri.client_account_code.strip()
            code_counts_exec[code] = code_counts_exec.get(code, 0) + 1
    code_to_row_idx_exec: dict[str, int] = {}
    for ri in row_inputs:
        if ri.client_account_code:
            code = ri.client_account_code.strip()
            if code_counts_exec.get(code, 0) == 1:
                code_to_row_idx_exec[code] = ri.row_index

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
    base_leaf_rows = {
        ri.row_index
        for ri in row_inputs
        if bool(ri.client_account_code or ri.client_account_name)
        and hier_by_row_exec.get(ri.row_index, {}).get("is_leaf", True)
        and not hier_by_row_exec.get(ri.row_index, {}).get("is_summary", False)
    }
    # TASK-094D：Analyze / Execute 共用同一份行分类逻辑。
    # 五类行：eligible / zero_amount_template / summary_total /
    #         duplicate_aggregate / ignored_business。
    # 与 Analyze 的差异：Execute 阶段把 user-ignored 真正从
    # eligible / zero / summary / duplicate 中扣减（优先级降序）。
    execute_classification = classify_import_rows(
        rows=rows,
        period_configs=period_configs,
        col_id_to_index=col_id_to_index,
        code_col_id=code_col_id,
        name_col_id=name_col_id,
        hierarchy=hier_merged_exec,
        user_ignored_rows=ignored_row_set,
    )
    eligible_business_leaf_rows = set(execute_classification.eligible_business_leaf_rows)
    zero_amount_template_leaf_rows = set(execute_classification.zero_amount_template_rows)
    summary_total_leaf_rows = set(execute_classification.summary_total_rows)
    duplicate_aggregate_leaf_rows = set(execute_classification.duplicate_aggregate_rows)
    ignored_leaf_rows = set(execute_classification.ignored_business_rows)
    # 兼容旧字段 auto_skip_rows：去掉 ignored 的部分（旧逻辑语义）
    execute_auto_skip_rows = (
        zero_amount_template_leaf_rows
        | summary_total_leaf_rows
        | duplicate_aggregate_leaf_rows
    )
    invalid_ignored_rows = sorted(ignored_row_set - base_leaf_rows)
    if invalid_ignored_rows:
        batch.status = "blocked"
        await db.flush()
        detail = "、".join(str(row_index) for row_index in invalid_ignored_rows[:10])
        raise ValueError(
            f"忽略行只能选择参与入库的末级客户科目行，以下行不可忽略: {detail}"
        )
    participating_leaf_rows = base_leaf_rows
    row_input_by_row = {ri.row_index: ri for ri in row_inputs}

    for ri in row_inputs:
        h = hier_by_row_exec.get(ri.row_index, {})
        # 父级 / 祖先
        parent_key = h.get("parent_key")
        parent_row_index = _resolve_hierarchy_parent_row_index(
            h,
            code_to_row_idx_exec,
        )
        if parent_row_index is not None:
            parent_input = row_input_by_row.get(parent_row_index)
            if parent_input and not _parent_row_is_code_compatible(
                ri.client_account_code,
                parent_input.client_account_code,
            ):
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
                    anc_input = row_input_by_row.get(anc_ri)
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
            "parent_row_index": parent_row_index,
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

    pre_resolution_unique_graph = build_unique_account_graph(
        tree=tree_exec,
        rows_meta=rows_meta_exec,
        customer_label=customer_label,
    )
    (
        confirmed_mappings,
        confirmed_node_mapping_count,
        auto_confirmed_node_count,
        manual_confirmed_node_count,
    ) = _collapse_confirmed_mappings_to_node_mappings(
        graph=pre_resolution_unique_graph,
        tree=tree_exec,
        confirmed_mappings=confirmed_mappings,
        confirmed_node_mappings=confirmed_node_mappings,
    )

    mapping_plan = await resolve_mapping_plan(
        db=db,
        tree=tree_exec,
        customer_label=customer_label,
        source_label=batch.source_label,
        confirmed_mappings=confirmed_mappings,
        ignored_rows=ignored_row_set,
        mode="execute",
    )
    tree_exec = mapping_plan.tree
    _apply_confirmed_descendant_propagation(tree_exec, confirmed_mappings)

    # TASK-094C：构建唯一节点图（用于统计报告 + DB 去重，不改变解析结果）
    execute_unique_graph = build_unique_account_graph(
        tree=tree_exec,
        rows_meta=rows_meta_exec,
        customer_label=customer_label,
    )
    _propagate_unique_node_resolution(execute_unique_graph, tree_exec)
    execute_unique_graph = build_unique_account_graph(
        tree=tree_exec,
        rows_meta=rows_meta_exec,
        customer_label=customer_label,
    )
    leaf_standard_accounts = resolve_leaf_standard_accounts(tree_exec)
    execute_node_by_key: dict[str, UniqueAccountNode] = dict(execute_unique_graph.nodes_by_key)
    execute_row_to_node_key: dict[int, str] = dict(execute_unique_graph.row_to_node_key)
    unresolved_node_count = _count_unresolved_unique_nodes(execute_unique_graph, tree_exec)

    # 统计重复提交行数（同 node_key 不同 row_index 的 confirmed 提交）
    duplicate_row_bindings: int = 0
    for cm in confirmed_mappings:
        ri = cm.get("row_index")
        if ri is None:
            continue
        nk = execute_row_to_node_key.get(ri)
        if nk and nk in execute_node_by_key:
            un = execute_node_by_key[nk]
            if un.representative_row_index is not None and un.representative_row_index != ri:
                duplicate_row_bindings += 1

    structural_skipped_leaf_rows = {
        row_index
        for row_index in participating_leaf_rows
        if (
            tree_exec.nodes_by_row.get(row_index) is not None
            and tree_exec.nodes_by_row[row_index].mapping_role == "structural_summary"
        )
    }
    if structural_skipped_leaf_rows:
        participating_leaf_rows = participating_leaf_rows - structural_skipped_leaf_rows
        ignored_leaf_rows = ignored_leaf_rows - structural_skipped_leaf_rows
        zero_amount_template_leaf_rows = (
            zero_amount_template_leaf_rows - structural_skipped_leaf_rows
        )
        summary_total_leaf_rows = summary_total_leaf_rows - structural_skipped_leaf_rows
        duplicate_aggregate_leaf_rows = (
            duplicate_aggregate_leaf_rows - structural_skipped_leaf_rows
        )
        eligible_business_leaf_rows = (
            eligible_business_leaf_rows - structural_skipped_leaf_rows
        )

    _timings["anchor_plan_rebuild"] = round(_time.time() - _t0_tree, 2)

    # 校验：所有参与入库的末级必须有唯一解析
    unmapped_leaves: list[dict] = []
    resolved_sa_ids: set[uuid.UUID] = set()
    for resolution in leaf_standard_accounts.values():
        if not resolution.standard_account_id:
            continue
        try:
            resolved_sa_ids.add(uuid.UUID(str(resolution.standard_account_id)))
        except (TypeError, ValueError):
            continue
    missing_sa_ids = resolved_sa_ids - set(sa_cache)
    if missing_sa_ids:
        sa_result = await db.execute(
            select(StandardAccount).where(StandardAccount.id.in_(list(missing_sa_ids)))
        )
        for sa in sa_result.scalars().all():
            sa_cache[sa.id] = sa

    standard_direction_by_row: dict[int, str | None] = {}
    for row_index, resolution in leaf_standard_accounts.items():
        if not resolution.standard_account_id:
            standard_direction_by_row[row_index] = None
            continue
        try:
            sa = sa_cache.get(uuid.UUID(str(resolution.standard_account_id)))
        except (TypeError, ValueError):
            sa = None
        standard_direction_by_row[row_index] = sa.balance_direction if sa else None

    def _amount_configs_for_execute() -> list[AmountConfig]:
        configs: list[AmountConfig] = []
        for pc in period_configs:
            mode = pc["mode"]
            if mode == "two_column":
                configs.append(AmountConfig(
                    period_type=pc["period_type"],
                    mode=mode,
                    debit_field=pc.get("debit_field"),
                    credit_field=pc.get("credit_field"),
                ))
            else:
                amount_field = pc.get("amount_field")
                if amount_field:
                    configs.append(AmountConfig(
                        period_type=pc["period_type"],
                        mode=mode,
                        amount_field=amount_field,
                        direction_column_id=pc.get("direction_column_id"),
                    ))
        return configs

    _t0 = _time.time()
    row_inputs = [
        RowInput(
            row_index=ri.row_index,
            client_account_code=ri.client_account_code,
            client_account_name=ri.client_account_name,
            indent_level=ri.indent_level,
            values=ri.values,
            amount_configs=_amount_configs_for_execute(),
            standard_direction=standard_direction_by_row.get(ri.row_index),
        )
        for ri in row_inputs
    ]
    transform_result = transform_rows(row_inputs, hierarchy_mode=hierarchy_mode)
    leaves = get_leaf_rows(transform_result)
    _timings["transform_after_mapping_plan"] = round(_time.time() - _t0, 2)

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
        is_auto_skipped = ri.row_index in execute_auto_skip_rows
        node = tree_exec.nodes_by_row.get(ri.row_index)
        resolved_sa_id = node.resolved_standard_account_id if node else None
        row_node_key = execute_row_to_node_key.get(ri.row_index)
        anchor_node_key = None
        if node and node.anchor_row_index is not None:
            anchor_node_key = execute_row_to_node_key.get(node.anchor_row_index)
        if node and node.mapping_role in {"anchor", "breakpoint", "explicit_override"}:
            anchor_node_key = anchor_node_key or row_node_key

        if is_user_ignored or is_auto_skipped:
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
            mapping_source="node_binding" if resolved_sa_uuid else (node.resolution_source if node else None),
            node_key=row_node_key,
            anchor_node_key=anchor_node_key,
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
    amount_fields = [
        "opening_debit",
        "opening_credit",
        "current_debit",
        "current_credit",
        "ending_debit",
        "ending_credit",
    ]

    def _amount_decimal(value: Any) -> Decimal:
        if value is None:
            return Decimal("0")
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    def _empty_amount_totals() -> dict[str, Decimal]:
        return {field: Decimal("0") for field in amount_fields}

    def _sum_leaf_amounts(row_indices: set[int]) -> dict[str, Decimal]:
        totals = _empty_amount_totals()
        for leaf_row in leaves:
            if leaf_row.row_index not in row_indices:
                continue
            for field in amount_fields:
                totals[field] += _amount_decimal(getattr(leaf_row, field, None))
        return totals

    entry_amount_totals = _empty_amount_totals()
    entry_count = 0
    for leaf in leaves:
        if leaf.row_index in ignored_row_set:
            continue
        if leaf.row_index in execute_auto_skip_rows:
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
        for field in amount_fields:
            entry_amount_totals[field] += _amount_decimal(getattr(leaf, field, None))
        entry_count += 1

    await db.flush()
    _timings["entry_insert"] = round(_time.time() - _t0, 2)

    # TASK-094D：5 类行集合计数之和 = base_leaf_rows 数量（业务末级）
    raw_identified_leaf_count = (
        len(eligible_business_leaf_rows)
        + len(zero_amount_template_leaf_rows)
        + len(summary_total_leaf_rows)
        + len(duplicate_aggregate_leaf_rows)
        + len(ignored_leaf_rows)
    )
    participating_leaf_count = len(participating_leaf_rows)
    if participating_leaf_count != raw_identified_leaf_count:
        batch.status = "blocked"
        await db.flush()
        raise ValueError(
            "raw_identified_leaf_count reconciliation failed: "
            "base_leaf_rows == eligible + zero + summary + duplicate + ignored "
            f"({participating_leaf_count} != {raw_identified_leaf_count})"
        )
    if entry_count != len(eligible_business_leaf_rows):
        batch.status = "blocked"
        await db.flush()
        raise ValueError(
            "entry reconciliation failed: "
            "entry_count must equal eligible_business_leaf_count "
            f"({entry_count} != {len(eligible_business_leaf_rows)})"
        )

    # TASK-094D：业务金额勾稽 — 仅使用真正业务末级（不混入汇总/重复）
    # 等式：eligible_business_leaf_amount + ignored_business_amount == entry_amount
    def _sum_by_row_indices(row_indices: set[int]) -> dict[str, Decimal]:
        totals = _empty_amount_totals()
        for leaf_row in leaves:
            if leaf_row.row_index not in row_indices:
                continue
            for field in amount_fields:
                totals[field] += _amount_decimal(getattr(leaf_row, field, None))
        return totals

    row_amount_lookups: dict[int, dict[str, Decimal]] = {}
    for leaf_row in leaves:
        row_amount_lookups[leaf_row.row_index] = {
            field: _amount_decimal(getattr(leaf_row, field, None))
            for field in amount_fields
        }
    # 也覆盖父级（汇总/重复勾稽需要）
    for tr in transform_result.rows:
        if tr.row_index in row_amount_lookups:
            continue
        row_amount_lookups[tr.row_index] = {
            field: _amount_decimal(getattr(tr, field, None))
            for field in amount_fields
        }

    business_amount_reconciliation = summarize_amount_reconciliation(
        eligible_business_leaf_rows=eligible_business_leaf_rows,
        ignored_business_rows=ignored_leaf_rows,
        entry_amount_totals=entry_amount_totals,
        row_amount_lookups=row_amount_lookups,
        fields=amount_fields,
    )
    amount_tolerance = Decimal("0.01")
    for field in amount_fields:
        info = business_amount_reconciliation[field]
        if info["ok"] != "true":
            batch.status = "blocked"
            await db.flush()
            raise ValueError(
                f"business amount reconciliation failed for {field}: "
                f"difference={info['difference']} (eligible={info['eligible']}, "
                f"ignored={info['ignored']}, entry={info['entry']})"
            )

    # TASK-094D：汇总 / 重复 父子金额勾稽 — 与业务勾稽分离
    # children_by_row 基于 hier_merged_exec 的 parent_key 重新推导
    summary_children_by_row: dict[int, list[int]] = {}
    for ri, h in hier_by_row_exec.items():
        pk = h.get("parent_key")
        if pk is None:
            continue
        parent_idx = None
        try:
            parent_idx = int(pk)
        except (ValueError, TypeError):
            parent_idx = code_to_row_idx_exec.get(str(pk).strip())
        if parent_idx is None or parent_idx == ri:
            continue
        summary_children_by_row.setdefault(parent_idx, []).append(ri)
    hierarchy_summary_rows_exec = {
        h["row_index"]
        for h in hier_merged_exec
        if h.get("is_summary")
    }
    summary_amount_reconciliation = summarize_summary_reconciliation(
        summary_total_rows=summary_total_leaf_rows,
        duplicate_aggregate_rows=duplicate_aggregate_leaf_rows,
        hierarchy_summary_rows=hierarchy_summary_rows_exec,
        children_by_row=summary_children_by_row,
        row_amount_lookups=row_amount_lookups,
        fields=amount_fields,
    )

    # 兼容旧 API 字段（保留 zero_skip 命名用于历史报告脚本）
    legacy_zero_amount_totals = _sum_by_row_indices(zero_amount_template_leaf_rows)
    legacy_source_amount_totals = _sum_by_row_indices(participating_leaf_rows)
    legacy_ignored_amount_totals = _sum_by_row_indices(ignored_leaf_rows)
    legacy_amount_reconciliation: dict[str, dict[str, str]] = {}
    for field in amount_fields:
        legacy_difference = (
            legacy_source_amount_totals[field]
            - entry_amount_totals[field]
            - legacy_ignored_amount_totals[field]
            - legacy_zero_amount_totals[field]
        )
        legacy_amount_reconciliation[field] = {
            "source": str(legacy_source_amount_totals[field]),
            "entry": str(entry_amount_totals[field]),
            "ignored": str(legacy_ignored_amount_totals[field]),
            "zero_skip": str(legacy_zero_amount_totals[field]),
            "difference": str(legacy_difference),
            # TASK-094D：标记新口径
            "deprecated": "true",
            "use_business_amount_reconciliation": "true",
        }

    # 11. 保存映射经验 — ANCHOR-INHERITANCE-MAPPING：
    # 只保存 anchor / breakpoint / explicit_override 行；
    # 普通 inherited 行不进入经验库（防止经验污染）。
    # TASK-085 性能优化：按 (code, name, standard_account_id) 去重。
    # TASK-094C：按 node_key 去重 — 同一唯一节点（不论绑定多少行）只保存一次。
    _t0 = _time.time()
    mapping_saved: list[dict] = []
    mapping_saved_node_keys: set[str] = set()
    if save_mapping_experience:
        for node_key, un in execute_node_by_key.items():
            if un.node_type == "summary":
                continue
            rep_ri = un.representative_row_index
            if rep_ri is None:
                continue
            n = tree_exec.nodes_by_row.get(rep_ri)
            if n is None:
                continue
            if n.is_ignored:
                continue
            if n.mapping_role not in {"anchor", "breakpoint", "explicit_override"}:
                continue
            if not n.resolved_standard_account_id:
                continue
            if not n.client_account_code and not n.client_account_name:
                continue
            try:
                sa = sa_cache.get(uuid.UUID(n.resolved_standard_account_id))
            except Exception:
                sa = None
            if sa is None:
                continue

            # TASK-094C：node_key 级去重 — 同一唯一节点只保存一次。
            if node_key in mapping_saved_node_keys:
                continue
            mapping_saved_node_keys.add(node_key)

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
                    "node_key": node_key,
                    "duplicate_source_row_count": max(len(un.source_row_indexes) - 1, 0),
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

    # TASK-094C：唯一节点图统计
    node_type_count = {"account": 0, "auxiliary": 0, "summary": 0}
    account_node_count = 0
    auxiliary_node_count = 0
    for un in execute_unique_graph.nodes_by_key.values():
        node_type_count[un.node_type] = node_type_count.get(un.node_type, 0) + 1
        if un.node_type == "account":
            account_node_count += 1
        elif un.node_type == "auxiliary":
            auxiliary_node_count += 1
    duplicate_binding_count = sum(
        max(len(un.source_row_indexes) - 1, 0)
        for un in execute_unique_graph.nodes_by_key.values()
    )
    execute_full_recommendation_node_count = len({
        nk for nk, un in execute_node_by_key.items()
        if un.representative_row_index is not None
    })

    return {
        "batch_id": str(batch.id),
        "status": batch.status,
        "entry_count": entry_count,
        # TASK-094D：5 类行集合计数 — Analyze / Execute 同口径
        "raw_identified_leaf_count": raw_identified_leaf_count,
        "eligible_business_leaf_count": len(eligible_business_leaf_rows),
        "ignored_business_count": len(ignored_leaf_rows),
        "zero_template_count": len(zero_amount_template_leaf_rows),
        "summary_total_count": len(summary_total_leaf_rows),
        "duplicate_aggregate_count": len(duplicate_aggregate_leaf_rows),
        "business_amount_reconciliation": business_amount_reconciliation,
        "summary_amount_reconciliation": summary_amount_reconciliation,
        # 兼容旧字段（标记 deprecated）
        "participating_leaf_count": participating_leaf_count,
        "ignored_leaf_count": len(ignored_leaf_rows),
        "zero_amount_skipped_leaf_count": (
            len(zero_amount_template_leaf_rows)
            + len(summary_total_leaf_rows)
            + len(duplicate_aggregate_leaf_rows)
        ),
        "amount_reconciliation": legacy_amount_reconciliation,
        "amount_reconciliation_deprecated": True,
        "raw_row_count": len(row_inputs),
        "mapping_saved_count": len(mapping_saved),
        "mapping_experience_saved_count": len(mapping_saved),
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
        "confirmed_node_mapping_count": confirmed_node_mapping_count,
        "auto_confirmed_node_count": auto_confirmed_node_count,
        "manual_confirmed_node_count": manual_confirmed_node_count,
        "row_level_confirmed_mapping_count": row_level_confirmed_mapping_count,
        "unresolved_node_count": unresolved_node_count,
        "debug_timings": _timings,
        # TASK-094C：唯一节点图统计
        "unique_node_count": len(execute_unique_graph.nodes_by_key),
        "account_node_count": account_node_count,
        "auxiliary_node_count": auxiliary_node_count,
        "summary_node_count": node_type_count.get("summary", 0),
        "duplicate_binding_count": duplicate_binding_count,
        "duplicate_row_submit_count": duplicate_row_bindings,
        "row_to_node_key_size": len(execute_unique_graph.row_to_node_key),
        "full_recommendation_node_count": execute_full_recommendation_node_count,
        "raw_row_compression_ratio": (
            round(len(row_inputs) / max(len(execute_unique_graph.nodes_by_key), 1), 2)
        ),
        # TASK-094D：分类行集合本身，供前端展示
        "classification": {
            "eligible_business_leaf_rows": sorted(eligible_business_leaf_rows),
            "zero_amount_template_rows": sorted(zero_amount_template_leaf_rows),
            "summary_total_rows": sorted(summary_total_leaf_rows),
            "duplicate_aggregate_rows": sorted(duplicate_aggregate_leaf_rows),
            "ignored_business_rows": sorted(ignored_leaf_rows),
            "base_leaf_rows": sorted(participating_leaf_rows),
            "structural_rows": sorted(
                set(hierarchy_summary_rows_exec)
                | set(summary_total_leaf_rows)
                | set(duplicate_aggregate_leaf_rows)
            ),
        },
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
