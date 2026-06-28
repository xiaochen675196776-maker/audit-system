"""上级锚点与下级继承式映射服务 — ANCHOR-INHERITANCE-MAPPING v2

TASK-092：本版本将生产闭环拆成两阶段推荐：

1. 轻量阶段 — 仅构建客户科目树、识别结构汇总和强信号（discover_anchor_candidates），
   对每个节点只判断：structural_summary / account_anchor_candidate / ordinary_detail。
   不调用 recommend_mappings 的全局模糊兜底。
2. 完整推荐阶段 — 仅对 anchor / breakpoint / explicit_override / unresolved root
   调用 recommend_mappings；普通 inherited / structural_summary / ignored 节点不再
   进入完整推荐。

主流程：

1. build_account_tree：构建完整客户科目树（支持 3+ 级）
2. discover_anchor_candidates：先做轻量语义识别与强信号收集，
   划分 structural_summary / anchor_candidate / breakpoint_candidate /
   inherited_candidate / ordinary_detail，并统计完整推荐节点数。
3. build_mapping_plan：仅对 anchor / breakpoint / explicit_override 调用完整推荐。
4. validate_mapping_plan / resolve_leaf_standard_accounts：参与末级未解析 → 阻断。
5. Execute 复用同一份 build_account_tree + build_mapping_plan 重新解析。

硬约束：
- 不得为任何客户、任何 Excel、任何具体科目代码写硬编码。
- 不得使用 candidates[0] 对未确认行兜底；生产代码统一使用
  pick_unique_auto_confirm_candidate / _is_safe_candidate 决定。
- 普通 inherited 行不保存为映射经验。
- 任一参与入库的末级若未解析唯一标准科目，必须阻止 execute。
- 普通明细节点（mapping_role=inherited）不得调用 recommend_mappings。
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_account_mapping import ClientAccountMapping
from app.models.standard_account import StandardAccount


# ── TASK-094C：唯一节点类型常量 ────────────────────────────

# 节点类型：account = 会计科目节点（形成锚点/候选）；
#          auxiliary = 辅助核算明细（继承上级会计科目，不形成独立推荐）；
#          summary = 结构汇总（不参与入库）。
UNIQUE_NODE_TYPES = ("account", "auxiliary", "summary")


# ── 角色与模式常量 ────────────────────────────────────────

MAPPING_ROLES = (
    "structural_summary",
    "anchor",
    "inherited",
    "breakpoint",
    "explicit_override",
    "unresolved",
    "ignored",
)

MAPPING_MODES = (
    "direct_auto",
    "direct_confirmed",
    "inherited_ancestor",
    "override_confirmed",
    "none",
)


# 通用结构汇总词：识别大类标签，不参与金额入库，也不向下强制传播标准科目
STRUCTURAL_SUMMARY_NAMES: set[str] = {
    "资产类", "负债类", "所有者权益类", "共同类", "成本类", "损益类",
    "流动资产", "非流动资产", "流动负债", "非流动负债",
    "期间费用", "收入类", "费用类",
    "项目核算", "部门核算", "往来核算", "明细科目", "辅助核算",
    "所有者权益", "权益类", "资产", "负债", "权益",
    "收入", "成本", "费用",
    # 研发相关：未明确方向的研发科目视为结构节点
    "研发支出",
}


# 明确会计科目锚点词：即使非末级，也应成为锚点候选（不是结构汇总）
# 注意：这些是常见的明确会计科目，本身应建立锚点让子级继承，
# 而不是作为分类标题下沉。
ACCOUNT_ANCHOR_TOKENS: tuple[str, ...] = (
    "银行存款", "库存现金", "其他货币资金",
    "应收账款", "预付账款", "其他应收款", "坏账准备", "应收票据",
    "应付账款", "预收账款", "其他应付款", "应付票据",
    "固定资产", "累计折旧", "在建工程", "无形资产", "长期待摊费用",
    "原材料", "库存商品", "周转材料",
    "短期借款", "长期借款",
    "实收资本", "资本公积", "盈余公积", "未分配利润", "本年利润", "利润分配",
    "生产成本", "制造费用",
    "主营业务收入", "其他业务收入", "营业外收入",
    "主营业务成本", "其他业务成本",
    "销售费用", "管理费用", "财务费用", "营业外支出",
    "所得税费用",
    "研发费用", "开发支出",
)


# 沿树 walk 时的特殊标记
class _NoParent:
    """sentinel：根行首调用的 parent_target_id。"""
    pass


class _InheritedFlag:
    """sentinel：父级是锚点但还没有具体 target id（仅语义识别）。"""
    pass


_NO_PARENT = _NoParent()
_INHERITED_FLAG = _InheritedFlag()


# 不应触发继承中断的中性名称片段（普通客户名称）
_NON_BREAKING_NEUTRAL_TOKENS: set[str] = {
    "银行", "账户", "供应商", "客户", "员工", "部门", "项目", "地区",
    "费用项目", "产品", "存货", "设备", "机器", "运输", "车辆",
    "保证金", "押金", "备用金", "个人", "内部", "公司",
}


# 方向相反词对
_DIRECTION_OPPOSITES: tuple[tuple[str, str], ...] = (
    ("应收", "应付"),
    ("预付", "预收"),
    ("预付", "合同负债"),
    ("其他应收", "其他应付"),
    ("应收票据", "应付票据"),
    ("预收", "预付"),
    ("应付", "应收"),
)


# 收入/成本/费用方向词
_PROFIT_LOSS_OPPOSITES: tuple[tuple[str, str], ...] = (
    ("收入", "成本"),
    ("收入", "费用"),
    ("成本", "费用"),
    ("营业外收入", "营业外支出"),
    ("营业外支出", "营业外收入"),
)


# 研发方向词
_RD_DIRECTION_TOKENS: tuple[str, ...] = (
    "费用化", "资本化", "开发支出", "研发费用", "研发支出",
)


# 备抵/原值词
_RESERVE_TOKENS: tuple[str, ...] = (
    "累计折旧", "累计摊销", "坏账准备", "存货跌价准备", "减值准备",
    "跌价准备", "资产减值", "信用减值",
)


# ── 数据类 ───────────────────────────────────────────────


@dataclass
class AccountTreeNode:
    """客户科目树节点。"""
    row_index: int
    client_account_code: str | None = None
    client_account_name: str | None = None
    level: int | None = None
    parent_row_index: int | None = None
    parent_key: str | None = None
    ancestor_row_indexes: list[int] = field(default_factory=list)
    ancestor_codes: list[str] = field(default_factory=list)
    ancestor_names: list[str] = field(default_factory=list)
    full_path: str = ""
    is_leaf: bool = True
    is_summary: bool = False
    participates_in_entry: bool = True
    children: list[int] = field(default_factory=list)
    is_ignored: bool = False
    # TASK-092：轻量语义分类（structural_summary / account_anchor_candidate / ordinary_detail）
    semantic_role: str = "ordinary_detail"

    # ── 解析后状态（由 build_mapping_plan 填充）──
    mapping_role: str = "unresolved"
    mapping_mode: str = "none"
    requires_confirmation: bool = False
    anchor_row_index: int | None = None
    anchor_client_account_code: str | None = None
    anchor_client_account_name: str | None = None
    resolved_standard_account_id: str | None = None
    resolved_standard_account_code: str | None = None
    resolved_standard_account_name: str | None = None
    # TASK-092：suggested / resolved 拆分 — 只有唯一安全候选或用户确认才能 resolved；
    # 未确认的最高分候选只能作为 suggested，不得算 resolved。
    suggested_standard_account_id: str | None = None
    suggested_standard_account_code: str | None = None
    suggested_standard_account_name: str | None = None
    resolution_source: str | None = None
    resolution_reason: str | None = None
    inheritance_break_reason: str | None = None
    inheritance_evidence: list[str] = field(default_factory=list)
    descendant_leaf_count: int = 0
    auto_confirm_status: str | None = None
    auto_confirm_reason: str | None = None


@dataclass
class AccountTree:
    """完整客户科目树。"""
    nodes_by_row: dict[int, AccountTreeNode] = field(default_factory=dict)
    children_by_row: dict[int, list[int]] = field(default_factory=dict)
    root_rows: list[int] = field(default_factory=list)


@dataclass
class InheritanceDecision:
    """继承中断决策。"""
    should_break: bool
    reason_code: str | None
    reason: str
    evidence: list[str] = field(default_factory=list)
    suggested_role: str = "inherited"


@dataclass
class AnchorResolution:
    """锚点的标准科目解析结果。

    TASK-092 拆分 suggested 与 resolved：
    - suggested_*：最高分候选（哪怕未唯一安全）；可作为前端的默认建议展示。
    - resolved_*：仅当唯一安全候选（unique_safe）或用户确认时才填。
    - is_resolved：仅当 resolved_* 真实填入时为 True。
    """
    standard_account_id: str | None
    standard_account_code: str | None
    standard_account_name: str | None
    source: str | None
    reason: str | None
    is_resolved: bool = False
    auto_confirm_status: str | None = None
    auto_confirm_reason: str | None = None
    # 新增：未确认建议（即使 resolved 为 None 也可填）
    suggested_standard_account_id: str | None = None
    suggested_standard_account_code: str | None = None
    suggested_standard_account_name: str | None = None
    suggested_source: str | None = None
    suggested_reason: str | None = None


@dataclass
class MappingPlanSummary:
    """映射计划统计。"""
    total_nodes: int = 0
    structural_summary_count: int = 0
    anchor_count: int = 0
    inherited_count: int = 0
    breakpoint_count: int = 0
    explicit_override_count: int = 0
    unresolved_count: int = 0
    confirmation_required_count: int = 0
    participating_leaf_count: int = 0
    resolved_participating_leaf_count: int = 0
    # TASK-092 性能指标：完整推荐 vs 轻量分析
    full_recommendation_node_count: int = 0
    light_signal_node_count: int = 0
    inherited_without_recommendation_count: int = 0


@dataclass
class MappingPlanResult:
    tree: "AccountTree"
    summary: MappingPlanSummary
    leaf_standard_accounts: dict[int, AnchorResolution] = field(default_factory=dict)
    validation_errors: list[str] = field(default_factory=list)


# ── TASK-094C：唯一科目节点图 ─────────────────────────────


def _normalize_for_node_key(value: str | None) -> str:
    """用于 node_key 的标准化：
    - 去首尾空白；
    - 折叠内部连续空白；
    - 大写；
    - 全角括号 / 冒号统一替换。
    """
    if not value:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    s = " ".join(s.split())
    # 全角空格 → 半角空格
    s = s.replace("\u3000", " ")
    # 全角冒号、破折号、半角括号保留原样（中文括号常出现在名称中）
    return s.upper()


def _normalize_parent_path(value: str | None) -> str:
    """用于 node_key 的父路径标准化（与名称同样的处理）。"""
    return _normalize_for_node_key(value)


def compute_unique_node_key(
    client_account_code: str | None,
    client_account_name: str | None,
    parent_full_path: str | None,
    *,
    customer_label: str | None = None,
) -> str:
    """生成唯一节点 key。

    构成：sha256(normalized_code | normalized_name | normalized_parent_path)

    - 同代码 / 同名称 / 同父路径 → 同 node_key（去重原始行重复展开）
    - 同代码不同父路径 → 不同 node_key（避免误合并）
    - 同代码同父路径但不同名称 → 不同 node_key（区分同名不同码）
    - 空代码与空名称保留（不当作 None 跳过）
    """
    customer = _normalize_for_node_key(customer_label)
    code = _normalize_for_node_key(client_account_code)
    name = _normalize_for_node_key(client_account_name)
    parent = _normalize_parent_path(parent_full_path)
    payload = f"{customer}|{code}|{name}|{parent}".encode("utf-8")
    return "uak:v2:" + hashlib.sha256(payload).hexdigest()


def classify_node_type(
    client_account_code: str | None,
    client_account_name: str | None,
    is_summary: bool,
) -> str:
    """节点类型分类（基于客户科目代码与名称特征）。

    - summary：结构汇总（如「资产类」「流动资产」「合计」等空代码纯分类标题）
    - auxiliary：辅助核算明细（无代码 + 名称含客户/供应商/部门/项目/银行账户等）
    - account：会计科目节点
    """
    code = (client_account_code or "").strip()
    name = (client_account_name or "").strip()
    if not code and not name:
        return "summary"
    if is_summary and not code:
        # 空代码且是父级：结构汇总
        return "summary"
    if not code:
        # 无代码 + 名称为辅助核算对象
        if _is_auxiliary_detail_name_strict(name):
            return "auxiliary"
        # 即使不带辅助关键词，只要没代码且不是明显会计科目（如「[0010004] 茂名市润源丰化工」）
        return "auxiliary"
    return "account"


# 严格版辅助核算识别：含方括号或客户/供应商/部门/项目/银行账户等前缀
_AUXILIARY_DETAIL_PREFIXES: tuple[str, ...] = (
    "客户:", "客户：",
    "供应商:", "供应商：",
    "部门:", "部门：",
    "项目:", "项目：",
    "银行账户:", "银行账户：",
    "员工:", "员工：",
)


def _is_auxiliary_detail_name_strict(name: str | None) -> bool:
    if not name:
        return False
    s = str(name).strip()
    if not s:
        return False
    # 全/半角方括号包裹的对象
    if "[" in s or "【" in s or "]" in s or "】" in s:
        return True
    stripped = s.replace("\u3000", "").lstrip()
    for p in _AUXILIARY_DETAIL_PREFIXES:
        if stripped.startswith(p):
            return True
    return False


@dataclass
class UniqueAccountNode:
    """唯一科目节点 — TASK-094C

    代表「同一客户科目路径」的去重节点。
    一条原始行通过 row_to_node_key 绑定到唯一节点。
    """
    node_key: str
    account_code: str | None
    account_name: str | None
    full_path: str
    parent_node_key: str | None
    level: int | None
    source_row_indexes: list[int] = field(default_factory=list)
    representative_row_index: int | None = None
    node_type: str = "account"  # account / auxiliary / summary
    # 解析后字段（与 AccountTreeNode 对齐）
    mapping_role: str = "unresolved"
    mapping_mode: str = "none"
    requires_confirmation: bool = False
    resolved_standard_account_id: str | None = None
    resolved_standard_account_code: str | None = None
    resolved_standard_account_name: str | None = None
    suggested_standard_account_id: str | None = None
    suggested_standard_account_code: str | None = None
    suggested_standard_account_name: str | None = None
    resolution_source: str | None = None
    resolution_reason: str | None = None
    inheritance_break_reason: str | None = None
    auto_confirm_status: str | None = None
    auto_confirm_reason: str | None = None
    anchor_node_key: str | None = None
    candidate_count: int = 0
    candidates: list[dict] = field(default_factory=list)
    auto_confirm_candidate: dict | None = None


@dataclass
class UniqueAccountGraph:
    """唯一科目节点图 — TASK-094C

    - nodes_by_key：按 node_key 索引的节点表
    - row_to_node_key：原始行 → 唯一节点的绑定关系
    - children_by_key：父 → 子节点 key 列表（树状）
    - root_keys：根节点 key 列表
    """
    nodes_by_key: dict[str, UniqueAccountNode] = field(default_factory=dict)
    row_to_node_key: dict[int, str] = field(default_factory=dict)
    children_by_key: dict[str, list[str]] = field(default_factory=dict)
    root_keys: list[str] = field(default_factory=list)


# ── 工具函数 ─────────────────────────────────────────────


def _normalize_name(value: str | None) -> str:
    if not value:
        return ""
    return value.strip()


def _has_any_token(text: str | None, tokens: Iterable[str]) -> bool:
    if not text:
        return False
    return any(token in text for token in tokens)


def _direction_pair(text_a: str | None, text_b: str | None) -> bool:
    """判断两个名称是否构成方向相反（应收/应付 等）。"""
    if not text_a or not text_b:
        return False
    a, b = text_a, text_b
    for x, y in _DIRECTION_OPPOSITES:
        if x in a and y in b:
            return True
        if y in a and x in b:
            return True
    return False


def _profit_loss_pair(text_a: str | None, text_b: str | None) -> bool:
    if not text_a or not text_b:
        return False
    a, b = text_a, text_b
    for x, y in _PROFIT_LOSS_OPPOSITES:
        if x in a and y in b:
            return True
        if y in a and x in b:
            return True
    return False


# ── 1. 客户科目树构建 ──────────────────────────────────────


def build_account_tree(
    rows_meta: list[dict],
    row_mapping_meta: dict[int, dict] | None = None,
    ignored_rows: set[int] | None = None,
) -> AccountTree:
    """从 row_inputs/merged_hier 推导出 AccountTree。

    rows_meta 每项至少包含:
        - row_index
        - client_account_code
        - client_account_name
        - level
        - parent_key
        - is_leaf
        - is_summary
        - ancestor_codes
        - ancestor_names

    row_mapping_meta[row_index] 提供:
        - participates_in_entry (bool)
        - is_ignored (bool)
    """
    ignored_rows = ignored_rows or set()
    row_mapping_meta = row_mapping_meta or {}

    nodes_by_row: dict[int, AccountTreeNode] = {}
    children_by_row: dict[int, list[int]] = {}
    code_to_row: dict[str, int] = {}

    # 第一遍：建立基础节点 + 找父级（按 parent_key 优先；其次 code 前缀）
    for meta in rows_meta:
        ri = meta["row_index"]
        code = (meta.get("client_account_code") or "").strip() or None
        name = (meta.get("client_account_name") or "").strip() or None
        level = meta.get("level")
        parent_key = meta.get("parent_key")
        ancestor_codes = list(meta.get("ancestor_codes") or [])
        ancestor_names = list(meta.get("ancestor_names") or [])

        mapping_meta = row_mapping_meta.get(ri, {})
        participates = bool(mapping_meta.get("participates_in_entry", True))
        is_ignored = ri in ignored_rows

        # 父级 row_index：parent_key 是代码时取 code_to_row；否则尝试作为 row_index
        has_explicit_parent_row_index = "parent_row_index" in meta
        parent_row_index: int | None = meta.get("parent_row_index")
        if parent_row_index is None and parent_key and not has_explicit_parent_row_index:
            if parent_key in code_to_row:
                parent_row_index = code_to_row[parent_key]
            else:
                try:
                    parent_row_index = int(parent_key)
                except (ValueError, TypeError):
                    parent_row_index = None

        # 父级 code 名字
        parent_code: str | None = None
        parent_name: str | None = None
        if parent_row_index is not None and parent_row_index in nodes_by_row:
            p = nodes_by_row[parent_row_index]
            parent_code = p.client_account_code
            parent_name = p.client_account_name

        # ancestor row indexes：从 ancestor_codes 反查
        ancestor_row_indexes: list[int] = []
        for ac in ancestor_codes:
            if ac in code_to_row:
                ancestor_row_indexes.append(code_to_row[ac])
        if parent_row_index is not None and (
            not ancestor_row_indexes
            or ancestor_row_indexes[-1] != parent_row_index
        ):
            ancestor_row_indexes.append(parent_row_index)

        # full_path：用名称拼接
        names_for_path = list(reversed(ancestor_names)) + ([name] if name else [])
        full_path = "\\".join(p for p in names_for_path if p)

        node = AccountTreeNode(
            row_index=ri,
            client_account_code=code,
            client_account_name=name,
            level=level,
            parent_row_index=parent_row_index,
            parent_key=parent_key,
            ancestor_row_indexes=ancestor_row_indexes,
            ancestor_codes=ancestor_codes,
            ancestor_names=ancestor_names,
            full_path=full_path,
            is_leaf=bool(meta.get("is_leaf", True)),
            is_summary=bool(meta.get("is_summary", False)),
            participates_in_entry=participates and not is_ignored,
            is_ignored=is_ignored,
        )
        nodes_by_row[ri] = node
        if code:
            code_to_row[code] = ri

    # 第二遍：建立 children 关系
    for ri, node in nodes_by_row.items():
        if node.parent_row_index is not None and node.parent_row_index in nodes_by_row:
            children_by_row.setdefault(node.parent_row_index, []).append(ri)

    # 第三遍：根行
    root_rows = [ri for ri, n in nodes_by_row.items() if n.parent_row_index is None]

    # 第四遍：计算每个节点的 descendant_leaf_count
    def _descendant_leaf_count(ri: int) -> int:
        node = nodes_by_row[ri]
        if node.is_leaf and not node.is_summary:
            return 1
        total = 0
        for ch in children_by_row.get(ri, []):
            total += _descendant_leaf_count(ch)
        return total

    for ri in nodes_by_row:
        nodes_by_row[ri].descendant_leaf_count = _descendant_leaf_count(ri)

    return AccountTree(
        nodes_by_row=nodes_by_row,
        children_by_row=children_by_row,
        root_rows=root_rows,
    )


# ── 1b. TASK-094C：唯一科目节点图 ──────────────────────────


def build_unique_account_graph(
    tree: "AccountTree",
    rows_meta: list[dict] | None = None,
    *,
    customer_label: str | None = None,
) -> UniqueAccountGraph:
    """从已构建的客户科目树派生唯一节点图。

    关键步骤：
    1. 沿树 walk 计算每个节点的 full_path（用于 node_key 的 parent 维度）；
    2. 计算每个节点自身的 node_key（基于 code + name + parent_path）；
    3. 聚合 source_row_indexes（同 node_key 多行合并到 representative_row_index 第一条）；
    4. 构造 children_by_key + root_keys。

    rows_meta 为 None 时，按 tree 现有数据重建 full_path；
    rows_meta 给出时优先用 rows_meta 中 ancestor_names 重建 full_path。

    不会修改原 tree 结构。
    """
    graph = UniqueAccountGraph()

    if not tree.nodes_by_row:
        return graph

    # 1) 准备 ancestor / full_path 缓存
    rows_meta_by_row: dict[int, dict] = {}
    if rows_meta:
        for meta in rows_meta:
            ri = meta.get("row_index")
            if ri is not None:
                rows_meta_by_row[ri] = meta

    # 2) 按 row_index 排序遍历，先建立 path → key 映射
    #    先 root，再子层；按 level 升序更稳定
    sorted_rows = sorted(
        tree.nodes_by_row.values(),
        key=lambda n: (n.level or 0, n.row_index),
    )

    # row_index → full_path
    full_path_by_row: dict[int, str] = {}
    parent_path_by_row: dict[int, str] = {}
    # row_index → node_key
    key_by_row: dict[int, str] = {}
    # row_index → parent_node_key
    parent_key_by_row: dict[int, str | None] = {}

    # 先尝试用 rows_meta 中的 ancestor_names 重建 full_path；
    # 否则根据 tree 关系重建。
    def _build_path_for_node(node: AccountTreeNode) -> str:
        meta = rows_meta_by_row.get(node.row_index)
        if meta:
            ancestor_names = list(meta.get("ancestor_names") or [])
            names_for_path = list(reversed(ancestor_names)) + (
                [node.client_account_name] if node.client_account_name else []
            )
            return "\\".join(p for p in names_for_path if p)
        return node.full_path or ""

    def _build_parent_path_for_node(node: AccountTreeNode) -> str:
        if node.parent_row_index is not None:
            return full_path_by_row.get(node.parent_row_index, "")
        meta = rows_meta_by_row.get(node.row_index)
        if meta:
            ancestor_names = list(meta.get("ancestor_names") or [])
            return "\\".join(p for p in reversed(ancestor_names) if p)
        return ""

    for node in sorted_rows:
        path = _build_path_for_node(node)
        full_path_by_row[node.row_index] = path
        parent_path = _build_parent_path_for_node(node)
        parent_path_by_row[node.row_index] = parent_path

        # parent_node_key：找 parent_row_index 对应的 node_key
        parent_key: str | None = None
        if node.parent_row_index is not None:
            parent_key = key_by_row.get(node.parent_row_index)
        parent_key_by_row[node.row_index] = parent_key

        node_key = compute_unique_node_key(
            client_account_code=node.client_account_code,
            client_account_name=node.client_account_name,
            parent_full_path=parent_path,
            customer_label=customer_label,
        )
        key_by_row[node.row_index] = node_key

    # 3) 构造 / 合并 UniqueAccountNode
    for node in sorted_rows:
        node_key = key_by_row[node.row_index]
        path = full_path_by_row[node.row_index]
        parent_key = parent_key_by_row[node.row_index]

        if node_key in graph.nodes_by_key:
            un = graph.nodes_by_key[node_key]
        else:
            un = UniqueAccountNode(
                node_key=node_key,
                account_code=node.client_account_code,
                account_name=node.client_account_name,
                full_path=path,
                parent_node_key=parent_key,
                level=node.level,
                node_type=classify_node_type(
                    client_account_code=node.client_account_code,
                    client_account_name=node.client_account_name,
                    is_summary=node.is_summary,
                ),
            )
            graph.nodes_by_key[node_key] = un

        un.source_row_indexes.append(node.row_index)
        if un.representative_row_index is None or node.row_index < un.representative_row_index:
            un.representative_row_index = node.row_index

        # 把 mapping_role/mode 等继承给节点（保留已解析的更具体状态）
        # 注意：节点级信息优先保留「已 resolved」的，避免后续被未解析的覆盖
        if (
            not un.resolved_standard_account_id
            and node.resolved_standard_account_id
        ):
            un.resolved_standard_account_id = node.resolved_standard_account_id
            un.resolved_standard_account_code = node.resolved_standard_account_code
            un.resolved_standard_account_name = node.resolved_standard_account_name
            un.mapping_role = node.mapping_role or un.mapping_role
            un.mapping_mode = node.mapping_mode or un.mapping_mode
            un.resolution_source = node.resolution_source or un.resolution_source
            un.resolution_reason = node.resolution_reason or un.resolution_reason
            un.auto_confirm_status = node.auto_confirm_status or un.auto_confirm_status
            un.auto_confirm_reason = node.auto_confirm_reason or un.auto_confirm_reason
            un.requires_confirmation = node.requires_confirmation
            un.suggested_standard_account_id = node.suggested_standard_account_id
            un.suggested_standard_account_code = node.suggested_standard_account_code
            un.suggested_standard_account_name = node.suggested_standard_account_name
            un.inheritance_break_reason = node.inheritance_break_reason
        elif (
            node.mapping_role in {"anchor", "breakpoint", "explicit_override"}
            and un.mapping_role not in {"anchor", "breakpoint", "explicit_override"}
        ):
            un.mapping_role = node.mapping_role
            un.mapping_mode = node.mapping_mode
            un.requires_confirmation = node.requires_confirmation
            un.suggested_standard_account_id = node.suggested_standard_account_id
            un.suggested_standard_account_code = node.suggested_standard_account_code
            un.suggested_standard_account_name = node.suggested_standard_account_name
            un.inheritance_break_reason = node.inheritance_break_reason

        # row → node 绑定（重复原始行覆盖同一个 key）
        graph.row_to_node_key[node.row_index] = node_key

    # 4) 构造 children_by_key + root_keys
    for key, un in graph.nodes_by_key.items():
        if un.parent_node_key and un.parent_node_key in graph.nodes_by_key:
            graph.children_by_key.setdefault(un.parent_node_key, []).append(key)
        else:
            graph.root_keys.append(key)

    # 子节点排序：按 row_index 升序
    for k in graph.children_by_key:
        graph.children_by_key[k].sort(
            key=lambda ck: graph.nodes_by_key[ck].representative_row_index or 0
        )
    graph.root_keys.sort(
        key=lambda k: graph.nodes_by_key[k].representative_row_index or 0
    )

    return graph


# ── 2. 结构汇总节点识别 ────────────────────────────────────


def classify_node_semantic_role(
    node: AccountTreeNode,
    children: list[AccountTreeNode] | None = None,
    strong_signals: dict | None = None,
) -> str:
    """轻量语义分类（不调用 recommend_mappings）。

    返回：
    - structural_summary：分类标题/大类标签，不参与入库
    - account_anchor_candidate：明确会计科目（即使非末级也可作为锚点）
    - ordinary_detail：普通客户明细，等待继承或显式确认
    """
    name = _normalize_name(node.client_account_name)
    if not name:
        return "structural_summary"

    # 1) 通用结构词（资产类 / 损益类 / 流动资产 / 期间费用 / 研发支出 等）
    if name in STRUCTURAL_SUMMARY_NAMES:
        return "structural_summary"

    # 2) 强信号命中（精确代码 / 名称）→ 锚点候选
    sigs = (strong_signals or {}).get(node.row_index)
    if sigs:
        if sigs.get("history") or sigs.get("exact_code_standard") or sigs.get("exact_name_match"):
            return "account_anchor_candidate"

    # 3) 名称本身就是明确会计科目（即使非末级也要做锚点）
    for token in ACCOUNT_ANCHOR_TOKENS:
        if name == token or token in name:
            return "account_anchor_candidate"

    # 4) 父级但其下子节点明显属于多个会计大类 → 结构汇总
    if children and node.is_summary:
        categories: set[str] = set()
        for ch in children:
            ch_name = _normalize_name(ch.client_account_name)
            if ch_name:
                ch_token = _infer_account_category_token(ch_name)
                if ch_token:
                    categories.add(ch_token)
        if len(categories) >= 2:
            return "structural_summary"

    # 5) 父级且不参与入库，且没有任何具体语义 → 仍是结构汇总
    if node.is_summary and not node.participates_in_entry and name not in ACCOUNT_ANCHOR_TOKENS:
        return "structural_summary"

    return "ordinary_detail"


def _infer_account_category_token(name: str) -> str | None:
    """从客户名称粗略推断会计大类标签（用于识别「流动资产」下的多个子类）。"""
    asset_kw = ("现金", "存款", "应收", "预付", "存货", "固定", "无形", "投资", "货币")
    liability_kw = ("应付", "预收", "借款", "应交", "应付职工")
    equity_kw = ("实收", "资本", "盈余", "本年利润", "利润分配")
    revenue_kw = ("收入", "收益")
    expense_kw = ("费用", "成本", "支出")
    if any(k in name for k in asset_kw):
        return "asset"
    if any(k in name for k in liability_kw):
        return "liability"
    if any(k in name for k in equity_kw):
        return "equity"
    if any(k in name for k in revenue_kw):
        return "revenue"
    if any(k in name for k in expense_kw):
        return "expense"
    return None


def is_structural_summary(node: AccountTreeNode) -> bool:
    """判断节点是否是结构汇总节点。

    TASK-092 修正：
    - 不得仅凭 `is_summary=True and not participates_in_entry` 认定结构汇总。
    - 银行存款、管理费用、应收账款等明确会计科目应能成为锚点候选。
    - 仅以下情形视为结构汇总：
      1. 名称属于 STRUCTURAL_SUMMARY_NAMES（资产类 / 流动资产 / 期间费用等）
      2. 没有代码 + 名称明显是分类标题
      3. 节点 semantic_role == "structural_summary"（在 build_mapping_plan 之前已标注）
    """
    name = _normalize_name(node.client_account_name)
    if not name:
        return True
    if name in STRUCTURAL_SUMMARY_NAMES:
        return True
    if not node.client_account_code and name in STRUCTURAL_SUMMARY_NAMES:
        return True
    if node.semantic_role == "structural_summary":
        return True
    return False


# ── 3. 轻量级子节点强信号检测 ─────────────────────────────


async def find_strong_direct_signals(
    db: AsyncSession,
    nodes: list[AccountTreeNode],
    customer_label: str | None,
    standard_account_index: dict[str, StandardAccount] | None = None,
) -> dict[int, dict]:
    """批量查找每个节点的强直接信号（公司历史、精确代码、精确名称等）。

    返回 row_index → {
        "history": [ClientAccountMapping, ...] | None,
        "exact_code_standard": StandardAccount | None,
        "exact_name_match": [StandardAccount, ...] | None,
        "semantic_group": [StandardAccount, ...] | None,
    }
    """
    result: dict[int, dict] = {}

    # 预加载标准科目索引
    if standard_account_index is None:
        sa_rows = (await db.execute(
            select(StandardAccount).where(StandardAccount.is_active == True)
        )).scalars().all()
        standard_account_index = {sa.account_code: sa for sa in sa_rows}
    # 同时按名称构建
    name_index: dict[str, list[StandardAccount]] = {}
    for sa in standard_account_index.values():
        if not sa.account_name:
            continue
        norm = _normalize_name(sa.account_name)
        name_index.setdefault(norm, []).append(sa)

    # 预加载公司历史
    history_by_row: dict[int, list[ClientAccountMapping]] = {}
    if customer_label:
        codes = {(n.client_account_code or "").strip() for n in nodes if n.client_account_code}
        names = {(n.client_account_name or "").strip() for n in nodes if n.client_account_name}
        codes.discard("")
        names.discard("")
        if codes or names:
            stmt = select(ClientAccountMapping).where(
                ClientAccountMapping.data_type == "trial_balance",
                ClientAccountMapping.is_active == True,
                ClientAccountMapping.customer_label == customer_label,
            )
            for col in (ClientAccountMapping.client_account_code, ClientAccountMapping.client_account_name):
                vals = codes if col is ClientAccountMapping.client_account_code else names
                if not vals:
                    continue
                # 按 code/name 分别查询，合并结果
                sub = stmt.where(col.in_(list(vals)))
                rows = (await db.execute(sub)).scalars().all()
                # 按 code/name 反查 row_index
                idx_by_code = {n.client_account_code: n.row_index for n in nodes if n.client_account_code}
                idx_by_name = {n.client_account_name: n.row_index for n in nodes if n.client_account_name}
                for cam in rows:
                    if col is ClientAccountMapping.client_account_code and cam.client_account_code:
                        key = cam.client_account_code
                        ri = idx_by_code.get(key)
                    elif cam.client_account_name:
                        key = cam.client_account_name
                        ri = idx_by_name.get(key)
                    else:
                        continue
                    if ri is None:
                        continue
                    history_by_row.setdefault(ri, []).append(cam)

    # 名称语义组（使用简单词典：仅覆盖方向/原值/备抵/研发等强信号组）
    semantic_groups: dict[str, set[str]] = {
        "rd_expense": {"6602", "660201", "660202"},
        "rd_capital": {"170401", "1704"},
        "accumulated_depreciation": {"1602"},
        "fixed_asset_cost": {"1601", "160101"},
        "bad_debt": {"1231", "112402", "112403"},
        "accounts_receivable": {"1122", "112201"},
        "accounts_payable": {"2202"},
    }

    # 名称 → 可能的组
    name_group_lookup = {
        "累计折旧": "accumulated_depreciation",
        "固定资产原值": "fixed_asset_cost",
        "坏账准备": "bad_debt",
        "费用化支出": "rd_expense",
        "资本化支出": "rd_capital",
    }

    for n in nodes:
        if n.is_ignored or not (n.client_account_code or n.client_account_name):
            continue
        info: dict[str, Any] = {}

        # 历史
        if history_by_row.get(n.row_index):
            info["history"] = history_by_row[n.row_index]
        # 精确代码
        if n.client_account_code:
            sa = standard_account_index.get(n.client_account_code.strip())
            if sa:
                info["exact_code_standard"] = sa
        # 精确名称
        if n.client_account_name:
            nrm = _normalize_name(n.client_account_name)
            if nrm in name_index:
                info["exact_name_match"] = name_index[nrm]
        # 语义组
        for token, group in name_group_lookup.items():
            if n.client_account_name and token in n.client_account_name:
                codes = semantic_groups.get(group, set())
                matches = [
                    standard_account_index[c] for c in codes
                    if c in standard_account_index
                ]
                if matches:
                    info["semantic_group"] = matches
                break

        if info:
            result[n.row_index] = info

    return result


# ── 4. 继承中断评估 ───────────────────────────────────────


def evaluate_inheritance_boundary(
    node: AccountTreeNode,
    inherited_standard_account: StandardAccount | None,
    strong_direct_signal: dict | None,
    customer_history: list | None = None,
) -> InheritanceDecision:
    """判断给定节点是否应该中断对上级锚点的继承。

    任何一项强信号触发即中断；其余情况默认继承。
    """
    customer_history = customer_history or []

    if inherited_standard_account is None:
        return InheritanceDecision(
            should_break=False,
            reason_code=None,
            reason="上级锚点未解析，不产生中断",
            suggested_role="inherited",
        )

    # 1) 用户/公司历史明确覆盖
    if strong_direct_signal and strong_direct_signal.get("history"):
        for cam in strong_direct_signal["history"]:
            if not cam.standard_account_id:
                continue
            if str(cam.standard_account_id) != str(inherited_standard_account.id):
                return InheritanceDecision(
                    should_break=True,
                    reason_code="user_history_override",
                    reason=(
                        f"用户/公司历史明确将该客户科目映射到「"
                        f"{cam.standard_account_code_snapshot} {cam.standard_account_name_snapshot}」"
                        f"，与上级锚点「{inherited_standard_account.account_code} {inherited_standard_account.account_name}」不同"
                    ),
                    evidence=[f"history_id={cam.id}"],
                    suggested_role="breakpoint",
                )

    # 2) 精确代码命中不同目标
    if strong_direct_signal and strong_direct_signal.get("exact_code_standard"):
        sa = strong_direct_signal["exact_code_standard"]
        if str(sa.id) != str(inherited_standard_account.id):
            # 同时检查名称兼容性：客户名称与新标准科目兼容 → 中断
            client_name = node.client_account_name or ""
            new_name = sa.account_name or ""
            # 名称包含空 / 仅数字代码 → 拒绝，避免碰巧代码撞车
            if client_name and new_name and any(ch in client_name for ch in new_name):
                return InheritanceDecision(
                    should_break=True,
                    reason_code="exact_code_different_target",
                    reason=(
                        f"客户科目代码「{node.client_account_code}」精确命中"
                        f"「{sa.account_code} {sa.account_name}」，与上级锚点不同"
                    ),
                    evidence=[f"client_code={node.client_account_code}"],
                    suggested_role="breakpoint",
                )

    # 3) 精确名称命中不同目标（必须严格，compatibility==compatible）
    if strong_direct_signal and strong_direct_signal.get("exact_name_match"):
        for sa in strong_direct_signal["exact_name_match"]:
            if str(sa.id) == str(inherited_standard_account.id):
                continue
            if sa.is_active:
                return InheritanceDecision(
                    should_break=True,
                    reason_code="exact_name_different_target",
                    reason=(
                        f"客户科目名称「{node.client_account_name}」精确匹配标准科目"
                        f"「{sa.account_code} {sa.account_name}」，与上级锚点不同"
                    ),
                    evidence=[f"sa_id={sa.id}"],
                    suggested_role="breakpoint",
                )

    # 4) 语义组命中
    if strong_direct_signal and strong_direct_signal.get("semantic_group"):
        for sa in strong_direct_signal["semantic_group"]:
            if str(sa.id) == str(inherited_standard_account.id):
                continue
            if sa.is_active:
                return InheritanceDecision(
                    should_break=True,
                    reason_code="semantic_group_different_target",
                    reason=(
                        f"客户科目名称「{node.client_account_name}」命中语义组「{sa.account_name}」，"
                        f"与上级锚点不同"
                    ),
                    evidence=[f"sa_id={sa.id}"],
                    suggested_role="breakpoint",
                )

    # 5) 原值/备抵变化
    if _has_any_token(node.client_account_name, _RESERVE_TOKENS):
        if not _has_any_token(inherited_standard_account.account_name, _RESERVE_TOKENS):
            return InheritanceDecision(
                should_break=True,
                reason_code="reserve_token_boundary",
                reason=(
                    f"客户科目「{node.client_account_name}」含备抵/减值语义，"
                    f"上级锚点为「{inherited_standard_account.account_name}」（原值类），方向不一致"
                ),
                evidence=[node.client_account_name or ""],
                suggested_role="breakpoint",
            )
        # 双方都是备抵类但名称不同 → 仍允许继承，避免空触发

    # 6) 研发方向变化
    if node.client_account_name and inherited_standard_account.account_name:
        node_has_cap = "资本化" in node.client_account_name
        node_has_exp = "费用化" in node.client_account_name
        anc_has_cap = "资本化" in inherited_standard_account.account_name
        anc_has_exp = "费用化" in inherited_standard_account.account_name
        # 节点是研发分支（费用化 or 资本化），且与上级方向不同 → 中断
        if (node_has_cap or node_has_exp):
            if (node_has_cap and not anc_has_cap) or (node_has_exp and not anc_has_exp):
                return InheritanceDecision(
                    should_break=True,
                    reason_code="rd_capitalization_boundary",
                    reason="研发费用化与资本化方向不同，必须分别建立新锚点",
                    evidence=[node.client_account_name or "", inherited_standard_account.account_name or ""],
                    suggested_role="breakpoint",
                )

    # 7) 资产/负债方向变化
    if _direction_pair(node.client_account_name, inherited_standard_account.account_name):
        # 仅当中性词不同时才中断（保证金不触发）
        node_text = node.client_account_name or ""
        anc_text = inherited_standard_account.account_name or ""
        # 若对方只是中性描述词，不应当作证据
        only_neutral = all(token in _NON_BREAKING_NEUTRAL_TOKENS for token in [node_text.strip()])
        if not only_neutral:
            return InheritanceDecision(
                should_break=True,
                reason_code="direction_boundary",
                reason=(
                    f"客户科目「{node.client_account_name}」与上级锚点「{anc_text}」"
                    "方向相反（资产/负债）"
                ),
                evidence=[node.client_account_name or "", anc_text],
                suggested_role="breakpoint",
            )

    # 8) 收入/成本/费用性质变化
    if _profit_loss_pair(node.client_account_name, inherited_standard_account.account_name):
        return InheritanceDecision(
            should_break=True,
            reason_code="profit_loss_boundary",
            reason=(
                f"客户科目「{node.client_account_name}」与上级锚点「"
                f"{inherited_standard_account.account_name}」损益性质不同"
            ),
            evidence=[node.client_account_name or "", inherited_standard_account.account_name or ""],
            suggested_role="breakpoint",
        )

    # 9) 会计大类变化（基于 standard_account.account_category）
    cur_cat = inherited_standard_account.account_category
    new_cat = None
    if strong_direct_signal and strong_direct_signal.get("exact_code_standard"):
        new_cat = strong_direct_signal["exact_code_standard"].account_category
    elif strong_direct_signal and strong_direct_signal.get("exact_name_match"):
        for sa in strong_direct_signal["exact_name_match"]:
            if sa.is_active:
                new_cat = sa.account_category
                break
    if cur_cat and new_cat and cur_cat != new_cat:
        return InheritanceDecision(
            should_break=True,
            reason_code="account_category_boundary",
            reason=(
                f"客户科目「{node.client_account_name or node.client_account_code}」"
                f"会计大类由 {cur_cat} 变为 {new_cat}"
            ),
            evidence=[f"from={cur_cat}", f"to={new_cat}"],
            suggested_role="breakpoint",
        )

    # 10) 默认继承
    return InheritanceDecision(
        should_break=False,
        reason_code=None,
        reason=(
            f"继承最近映射锚点：{inherited_standard_account.account_code} "
            f"{inherited_standard_account.account_name}"
        ),
        suggested_role="inherited",
    )


# ── 5. 锚点发现阶段（轻量，不调用 recommend_mappings） ────────


@dataclass
class AnchorDiscoveryResult:
    """轻量锚点发现结果。

    anchor_rows：需要完整推荐 recommend_mappings 的节点；
    structural_rows：识别为结构汇总（不下传、不参与）；
    breakpoint_candidate_rows：检测到继承中断但还未确认；
    inherited_candidate_rows：仅作继承候选（无需完整推荐）；
    """
    anchor_rows: set[int] = field(default_factory=set)
    structural_rows: set[int] = field(default_factory=set)
    breakpoint_candidate_rows: set[int] = field(default_factory=set)
    inherited_candidate_rows: set[int] = field(default_factory=set)
    strong_signals: dict[int, dict] = field(default_factory=dict)


async def discover_anchor_candidates(
    tree: AccountTree,
    db: AsyncSession,
    customer_label: str | None = None,
) -> AnchorDiscoveryResult:
    """轻量级识别锚点 / 中断点 / 结构汇总。

    不得调用 recommend_mappings 的全局模糊兜底。只做：
    - 层级识别（已在 build_account_tree 完成）
    - 强信号收集（公司历史、精确代码、精确名称、语义组）
    - 语义分类（classify_node_semantic_role）
    - 沿树判断中断点（evaluate_inheritance_boundary）

    返回的 anchor_rows + breakpoint_candidate_rows 是后续必须调用
    recommend_mappings 的行；其余行（inherited / structural / ignored）
    不会触发完整推荐。
    """
    result = AnchorDiscoveryResult()
    nodes = tree.nodes_by_row

    # 1) 收集强信号
    result.strong_signals = await find_strong_direct_signals(
        db, list(nodes.values()), customer_label=customer_label
    )

    # 2) 对每个节点做轻量分类
    for ri, node in nodes.items():
        if node.is_ignored:
            continue
        children = [nodes[ch] for ch in tree.children_by_row.get(ri, []) if ch in nodes]
        node.semantic_role = classify_node_semantic_role(
            node,
            children=children,
            strong_signals=result.strong_signals,
        )
        if node.semantic_role == "structural_summary":
            result.structural_rows.add(ri)
        elif node.semantic_role == "account_anchor_candidate":
            # 强信号命中或名称本身就是明确会计科目 → 直接作为锚点
            result.anchor_rows.add(ri)
        else:
            result.inherited_candidate_rows.add(ri)

    # 3) 沿树做继承中断检测（轻量版，不依赖 StandardAccount 实例）：
    #    - 根行默认作为首批锚点
    #    - 子节点若在强信号中命中与父级不同的目标 → 中断点
    # 注：此处只做信号层判断（基于 code/name 命中），不真正调用 evaluate_inheritance_boundary
    #     （那需要 SA 实例）。真正的 boundary evaluation 由 build_mapping_plan 在拿到
    #     recommend_mappings 结果后完成。
    sig_by_row: dict[int, dict] = result.strong_signals

    def _sig_target_id(sig: dict | None) -> str | None:
        if not sig:
            return None
        # 精确代码 > 精确名称 > 历史
        sa = sig.get("exact_code_standard")
        if sa is not None:
            return str(getattr(sa, "id", ""))
        ems = sig.get("exact_name_match") or []
        if ems:
            return str(getattr(ems[0], "id", ""))
        hist = sig.get("history") or []
        if hist:
            return str(getattr(hist[0], "standard_account_id", ""))
        return None

    async def _walk_for_breakpoints(
        ri: int,
        parent_target_id: Any,
    ) -> None:
        """沿树走一遍：

        - parent_target_id：父级已解析到的目标 SA id（字符串），
          特殊值 _NO_PARENT 表示「无上级锚点」（仅根行首调用），
          字符串（即使是空串 ""）表示「父级是锚点，需要继承判断」。
        - 节点根据自身信号 vs parent_target_id 决定：
          * 不同 → breakpoint
          * 相同或自身无信号 → 沿继承
        - 根行（_NO_PARENT）→ 自身成为首批锚点，children 沿 _ANCESTOR_ANCHOR 走。
        """
        node = nodes[ri]
        if node.is_ignored:
            return
        if ri in result.structural_rows:
            # 结构汇总不下传
            for ch in tree.children_by_row.get(ri, []):
                await _walk_for_breakpoints(ch, _NO_PARENT)
            return

        self_target_id = _sig_target_id(sig_by_row.get(ri))

        # 根行（首次调用 _NO_PARENT）：成为首批锚点
        if parent_target_id is _NO_PARENT:
            if ri not in result.anchor_rows:
                result.anchor_rows.add(ri)
            # 把「锚点存在」标志传给 children（用 self_target_id 或空串标记）
            for ch in tree.children_by_row.get(ri, []):
                # 父级锚点存在 → 用 self_target_id（或 _INHERITED_FLAG）传给 children
                await _walk_for_breakpoints(ch, self_target_id if self_target_id else _INHERITED_FLAG)
            return

        # 子节点：检查是否需要中断继承
        # 1) 自身强信号命中与父级不同的目标 → 中断点
        if self_target_id and self_target_id != parent_target_id and parent_target_id != _INHERITED_FLAG:
            result.breakpoint_candidate_rows.add(ri)
            if ri not in result.anchor_rows:
                result.anchor_rows.add(ri)
            for ch in tree.children_by_row.get(ri, []):
                await _walk_for_breakpoints(ch, self_target_id if self_target_id else _INHERITED_FLAG)
            return

        # 2) 名称与父级明显方向相反（应收/应付）→ 中断点
        if self_target_id is None and isinstance(parent_target_id, str) and parent_target_id != _INHERITED_FLAG:
            parent_name = ""
            for p_ri, p_node in nodes.items():
                if _sig_target_id(sig_by_row.get(p_ri)) == parent_target_id:
                    parent_name = p_node.client_account_name or ""
                    break
            if node.client_account_name and parent_name and _direction_pair(
                node.client_account_name, parent_name
            ):
                result.breakpoint_candidate_rows.add(ri)
                if ri not in result.anchor_rows:
                    result.anchor_rows.add(ri)
                for ch in tree.children_by_row.get(ri, []):
                    await _walk_for_breakpoints(ch, _NO_PARENT)
                return

        # 3) 其它情况：沿父级继承
        for ch in tree.children_by_row.get(ri, []):
            await _walk_for_breakpoints(ch, parent_target_id)

    for root_ri in tree.root_rows:
        root_node = nodes[root_ri]
        if root_node.is_ignored:
            continue
        await _walk_for_breakpoints(root_ri, _NO_PARENT)

    # 4) 整理 inherited_without_recommendation 计数
    inherited_only = (
        result.inherited_candidate_rows
        - result.anchor_rows
        - result.breakpoint_candidate_rows
    )
    result.inherited_candidate_rows = inherited_only

    return result


# ── 6. 映射计划构建 ───────────────────────────────────────


async def build_mapping_plan(
    tree: AccountTree,
    db: AsyncSession,
    customer_label: str | None = None,
    source_label: str | None = None,
    recommend_anchor_fn=None,
    explicit_overrides: dict[int, str] | None = None,
    discovery: AnchorDiscoveryResult | None = None,
) -> tuple[AccountTree, MappingPlanSummary]:
    """遍历客户科目树，生成完整映射计划。

    Args:
        tree: 完整客户科目树
        db: 数据库会话
        customer_label: 客户标识
        source_label: 来源标识
        recommend_anchor_fn: 异步函数 (node) -> AnchorResolution，
            对 anchor/breakpoint/explicit_override 节点执行完整推荐。
            调用方负责传入具体的 recommend_mappings 实现。
        explicit_overrides: row_index -> standard_account_id，用户在 UI 上
            显式对继承行指定的目标。
        discovery: 可选外部传入的轻量发现结果（避免重复执行）。

    Returns:
        (更新后的 tree, summary)
    """
    explicit_overrides = explicit_overrides or {}
    nodes = tree.nodes_by_row

    # 1) 轻量锚点发现（如果没有外部传入）
    if discovery is None:
        discovery = await discover_anchor_candidates(
            tree=tree, db=db, customer_label=customer_label,
        )

    # 把 discovery 的分类写回每个节点的 semantic_role（已在 discovery 内完成，
    # 但显式 overrides 可能改变结构）
    strong_signals = discovery.strong_signals
    anchor_rows = set(discovery.anchor_rows)
    breakpoint_rows = set(discovery.breakpoint_candidate_rows)
    structural_rows = set(discovery.structural_rows)

    # 2) 深度优先遍历
    async def _visit(ri: int, inherited_anchor: AnchorResolution | None) -> None:
        node = nodes[ri]
        if node.is_ignored:
            node.mapping_role = "ignored"
            node.mapping_mode = "none"
            return

        # 1) 结构汇总：不下传锚点
        if ri in structural_rows or is_structural_summary(node):
            node.mapping_role = "structural_summary"
            node.mapping_mode = "none"
            # 递归子节点（不传 inherited_anchor，让子节点重新发现）
            for ch in tree.children_by_row.get(ri, []):
                await _visit(ch, None)
            return

        # 2) 用户显式覆盖：直接采用用户目标，建立新锚点
        if ri in explicit_overrides:
            target_id = explicit_overrides[ri]
            sa = await _lookup_standard_account_async(db, target_id)
            if sa is None:
                node.mapping_role = "unresolved"
                node.requires_confirmation = True
                return
            node.mapping_role = "explicit_override"
            node.mapping_mode = "override_confirmed"
            node.resolved_standard_account_id = str(sa.id)
            node.resolved_standard_account_code = sa.account_code
            node.resolved_standard_account_name = sa.account_name
            node.resolution_source = "user_override"
            node.resolution_reason = "用户在前端将该继承行单独映射为新锚点"
            node.requires_confirmation = False
            new_anchor = AnchorResolution(
                standard_account_id=str(sa.id),
                standard_account_code=sa.account_code,
                standard_account_name=sa.account_name,
                source="explicit_override",
                reason="用户显式覆盖",
                is_resolved=True,
            )
            for ch in tree.children_by_row.get(ri, []):
                await _visit(ch, new_anchor)
            return

        # 3) 没有上级锚点：建立新锚点（首批锚点）
        if inherited_anchor is None:
            resolution = None
            if recommend_anchor_fn is not None:
                resolution = await recommend_anchor_fn(node)
            if resolution is None or not resolution.is_resolved:
                node.mapping_role = "unresolved"
                node.requires_confirmation = True
                node.auto_confirm_status = resolution.auto_confirm_status if resolution else "none"
                node.auto_confirm_reason = (
                    resolution.auto_confirm_reason if resolution
                    else "无锚点推荐结果，需用户手动选择"
                )
                # 记录 suggested（即使未确认）
                if resolution is not None:
                    node.suggested_standard_account_id = resolution.suggested_standard_account_id or resolution.standard_account_id
                    node.suggested_standard_account_code = resolution.suggested_standard_account_code or resolution.standard_account_code
                    node.suggested_standard_account_name = resolution.suggested_standard_account_name or resolution.standard_account_name
                # 子节点也无法继承，仍各自尝试建立锚点
                for ch in tree.children_by_row.get(ri, []):
                    await _visit(ch, None)
                return

            node.mapping_role = "anchor"
            node.mapping_mode = (
                "direct_auto"
                if resolution.auto_confirm_status == "unique_safe"
                else "direct_confirmed"
            )
            node.resolved_standard_account_id = resolution.standard_account_id
            node.resolved_standard_account_code = resolution.standard_account_code
            node.resolved_standard_account_name = resolution.standard_account_name
            node.suggested_standard_account_id = resolution.standard_account_id
            node.suggested_standard_account_code = resolution.standard_account_code
            node.suggested_standard_account_name = resolution.standard_account_name
            node.resolution_source = resolution.source
            node.resolution_reason = resolution.reason
            node.auto_confirm_status = resolution.auto_confirm_status
            node.auto_confirm_reason = resolution.auto_confirm_reason
            node.requires_confirmation = (
                resolution.auto_confirm_status != "unique_safe"
            )
            new_anchor = resolution
            for ch in tree.children_by_row.get(ri, []):
                await _visit(ch, new_anchor)
            return

        # 4) 存在上级锚点：判断是否中断继承
        anc_sa = await _lookup_standard_account_async(db, inherited_anchor.standard_account_id)
        if anc_sa is None:
            # 上级锚点不可用，回退到发现新锚点
            for ch in tree.children_by_row.get(ri, []):
                await _visit(ch, None)
            return

        decision = evaluate_inheritance_boundary(
            node=node,
            inherited_standard_account=anc_sa,
            strong_direct_signal=strong_signals.get(ri),
        )

        if not decision.should_break:
            # 继承
            node.mapping_role = "inherited"
            node.mapping_mode = "inherited_ancestor"
            node.anchor_row_index = _find_anchor_row(tree, ri, inherited_anchor)
            # anchor 链路信息
            anc_node = _find_anchor_node_by_id(tree, inherited_anchor.standard_account_id)
            if anc_node is not None:
                node.anchor_client_account_code = anc_node.client_account_code
                node.anchor_client_account_name = anc_node.client_account_name
                node.anchor_row_index = anc_node.row_index
            node.resolved_standard_account_id = inherited_anchor.standard_account_id
            node.resolved_standard_account_code = inherited_anchor.standard_account_code
            node.resolved_standard_account_name = inherited_anchor.standard_account_name
            node.resolution_source = "inherited_ancestor"
            node.resolution_reason = decision.reason
            node.inheritance_evidence = list(decision.evidence)
            for ch in tree.children_by_row.get(ri, []):
                await _visit(ch, inherited_anchor)
            return

        # 中断：建立新锚点
        resolution = None
        if recommend_anchor_fn is not None:
            resolution = await recommend_anchor_fn(node)
        if resolution is None or not resolution.is_resolved:
            node.mapping_role = "unresolved"
            node.requires_confirmation = True
            node.inheritance_break_reason = decision.reason_code
            node.inheritance_evidence = list(decision.evidence)
            # 记录 suggested（即使未确认）
            if resolution is not None:
                node.suggested_standard_account_id = resolution.suggested_standard_account_id or resolution.standard_account_id
                node.suggested_standard_account_code = resolution.suggested_standard_account_code or resolution.standard_account_code
                node.suggested_standard_account_name = resolution.suggested_standard_account_name or resolution.standard_account_name
            # 子节点无法继承
            for ch in tree.children_by_row.get(ri, []):
                await _visit(ch, None)
            return

        node.mapping_role = "breakpoint"
        node.mapping_mode = (
            "direct_auto"
            if resolution.auto_confirm_status == "unique_safe"
            else "direct_confirmed"
        )
        node.resolved_standard_account_id = resolution.standard_account_id
        node.resolved_standard_account_code = resolution.standard_account_code
        node.resolved_standard_account_name = resolution.standard_account_name
        node.suggested_standard_account_id = resolution.standard_account_id
        node.suggested_standard_account_code = resolution.standard_account_code
        node.suggested_standard_account_name = resolution.standard_account_name
        node.resolution_source = resolution.source
        node.resolution_reason = decision.reason + " → " + (resolution.reason or "")
        node.inheritance_break_reason = decision.reason_code
        node.inheritance_evidence = list(decision.evidence)
        node.auto_confirm_status = resolution.auto_confirm_status
        node.auto_confirm_reason = resolution.auto_confirm_reason
        node.requires_confirmation = (
            resolution.auto_confirm_status != "unique_safe"
        )
        new_anchor = resolution
        for ch in tree.children_by_row.get(ri, []):
            await _visit(ch, new_anchor)

    for root_ri in tree.root_rows:
        await _visit(root_ri, None)

    summary = _build_summary(
        tree,
        full_recommendation_node_count=len(anchor_rows) + len(breakpoint_rows),
        light_signal_node_count=len(nodes) - len(structural_rows),
        inherited_without_recommendation_count=len(
            [
                n for n in nodes.values()
                if n.mapping_role == "inherited"
            ]
        ),
    )
    return tree, summary


# ── 6. 校验与解析 ─────────────────────────────────────────


def validate_mapping_plan(
    tree: AccountTree,
    explicit_overrides: dict[int, str] | None = None,
) -> list[str]:
    """校验映射计划：所有参与入库的末级必须有唯一解析结果。"""
    explicit_overrides = explicit_overrides or {}
    errors: list[str] = []

    participating_leaves: list[AccountTreeNode] = []
    unresolved_leaves: list[AccountTreeNode] = []
    for n in tree.nodes_by_row.values():
        if n.is_ignored:
            continue
        if n.is_summary:
            continue
        if not n.participates_in_entry:
            continue
        if n.mapping_role == "structural_summary":
            continue
        if n.mapping_role in {"anchor", "breakpoint", "inherited", "explicit_override"} and \
                n.resolved_standard_account_id:
            participating_leaves.append(n)
        else:
            unresolved_leaves.append(n)

    if unresolved_leaves:
        for n in unresolved_leaves[:5]:
            code = n.client_account_code or ""
            name = n.client_account_name or ""
            errors.append(
                f"行 {n.row_index}「{code} {name}」无法通过上级锚点、继承规则或用户覆盖确定标准科目"
            )
        if len(unresolved_leaves) > 5:
            errors.append(f"…另有 {len(unresolved_leaves) - 5} 行未解析")
    return errors


def resolve_leaf_standard_accounts(
    tree: AccountTree,
) -> dict[int, AnchorResolution]:
    """返回 row_index → 标准科目解析（仅参与入库的末级行）。"""
    out: dict[int, AnchorResolution] = {}
    for n in tree.nodes_by_row.values():
        if n.is_ignored or n.is_summary or not n.participates_in_entry:
            continue
        if n.mapping_role == "structural_summary":
            continue
        if not n.resolved_standard_account_id:
            continue
        out[n.row_index] = AnchorResolution(
            standard_account_id=n.resolved_standard_account_id,
            standard_account_code=n.resolved_standard_account_code,
            standard_account_name=n.resolved_standard_account_name,
            source=n.resolution_source,
            reason=n.resolution_reason,
            is_resolved=True,
            auto_confirm_status=n.auto_confirm_status,
            auto_confirm_reason=n.auto_confirm_reason,
        )
    return out


# ── 7. 内部辅助 ───────────────────────────────────────────


async def resolve_mapping_plan(
    db: AsyncSession,
    tree: AccountTree,
    customer_label: str | None,
    source_label: str | None,
    confirmed_mappings: list[dict] | None,
    ignored_rows: Iterable[int] | None,
    mode: str,
    *,
    recommend_anchor_fn=None,
    discovery: AnchorDiscoveryResult | None = None,
) -> MappingPlanResult:
    """Unified production entry for analyze and execute mapping resolution."""
    ignored_row_set = set(ignored_rows or [])
    for row_index in ignored_row_set:
        node = tree.nodes_by_row.get(row_index)
        if node is not None:
            node.is_ignored = True
            node.mapping_role = "ignored"
            node.mapping_mode = "none"
            node.participates_in_entry = False

    confirmed_by_row: dict[int, dict] = {}
    standard_ids: set[uuid.UUID] = set()
    for cm in confirmed_mappings or []:
        try:
            row_index = int(cm.get("row_index"))
        except (TypeError, ValueError):
            continue
        standard_account_id = cm.get("standard_account_id")
        if not standard_account_id:
            continue
        confirmed_by_row[row_index] = cm
        try:
            standard_ids.add(uuid.UUID(str(standard_account_id)))
        except (TypeError, ValueError):
            continue

    standard_by_id: dict[str, StandardAccount] = {}
    if standard_ids:
        result = await db.execute(
            select(StandardAccount).where(StandardAccount.id.in_(list(standard_ids)))
        )
        for sa in result.scalars().all():
            standard_by_id[str(sa.id)] = sa

    explicit_overrides: dict[int, str] = {}
    for row_index, cm in confirmed_by_row.items():
        if cm.get("mapping_action") == "override":
            explicit_overrides[row_index] = str(cm.get("standard_account_id"))

    async def _confirmed_or_recommended_anchor(node: AccountTreeNode) -> AnchorResolution | None:
        cm = confirmed_by_row.get(node.row_index)
        if cm is not None:
            sa = standard_by_id.get(str(cm.get("standard_account_id")))
            if sa is None:
                return AnchorResolution(
                    standard_account_id=None,
                    standard_account_code=None,
                    standard_account_name=None,
                    source=None,
                    reason="confirmed standard account not found",
                    is_resolved=False,
                    auto_confirm_status="none",
                    auto_confirm_reason="confirmed standard account not found",
                )
            return AnchorResolution(
                standard_account_id=str(sa.id),
                standard_account_code=sa.account_code,
                standard_account_name=sa.account_name,
                source=cm.get("selection_source") or "user_confirmed",
                reason=cm.get("review_reason") or cm.get("selection_source") or "user_confirmed",
                is_resolved=True,
                auto_confirm_status="user_confirmed",
                auto_confirm_reason=cm.get("review_reason") or "user confirmed mapping",
                suggested_standard_account_id=str(sa.id),
                suggested_standard_account_code=sa.account_code,
                suggested_standard_account_name=sa.account_name,
                suggested_source=cm.get("selection_source") or "user_confirmed",
                suggested_reason=cm.get("review_reason") or "user confirmed mapping",
            )
        if recommend_anchor_fn is None:
            return None
        return await recommend_anchor_fn(node)

    resolved_tree, summary = await build_mapping_plan(
        tree=tree,
        db=db,
        customer_label=customer_label,
        source_label=source_label,
        recommend_anchor_fn=_confirmed_or_recommended_anchor,
        explicit_overrides=explicit_overrides,
        discovery=discovery,
    )
    errors = validate_mapping_plan(resolved_tree, explicit_overrides)
    leaf_accounts = resolve_leaf_standard_accounts(resolved_tree)
    return MappingPlanResult(
        tree=resolved_tree,
        summary=summary,
        leaf_standard_accounts=leaf_accounts,
        validation_errors=errors,
    )


_sa_cache: dict[str, StandardAccount] = {}


async def _lookup_standard_account_async(
    db: AsyncSession, sa_id: str | None
) -> StandardAccount | None:
    if not sa_id:
        return None
    key = str(sa_id)
    if key in _sa_cache:
        return _sa_cache[key]
    try:
        uid = uuid.UUID(key)
    except (ValueError, TypeError):
        return None
    sa = await db.get(StandardAccount, uid)
    if sa is None:
        # 兜底：用 select 查
        try:
            stmt = select(StandardAccount).where(StandardAccount.id == uid)
            res = await db.execute(stmt)
            sa = res.scalar_one_or_none()
        except Exception:
            sa = None
    if sa is not None:
        _sa_cache[key] = sa
    return sa


def _find_anchor_row(
    tree: AccountTree,
    current_ri: int,
    inherited_anchor: AnchorResolution,
) -> int | None:
    """找到 inherited_anchor 实际对应的 row_index。"""
    target_id = inherited_anchor.standard_account_id
    for ri, n in tree.nodes_by_row.items():
        if n.resolved_standard_account_id == target_id and n.mapping_role in {
            "anchor", "breakpoint", "explicit_override",
        }:
            return ri
    return None


def _find_anchor_node_by_id(
    tree: AccountTree, target_id: str | None
) -> AccountTreeNode | None:
    if not target_id:
        return None
    for n in tree.nodes_by_row.values():
        if n.resolved_standard_account_id == target_id and n.mapping_role in {
            "anchor", "breakpoint", "explicit_override",
        }:
            return n
    return None


def _build_summary(
    tree: AccountTree,
    full_recommendation_node_count: int | None = None,
    light_signal_node_count: int | None = None,
    inherited_without_recommendation_count: int | None = None,
) -> MappingPlanSummary:
    s = MappingPlanSummary(total_nodes=len(tree.nodes_by_row))
    for n in tree.nodes_by_row.values():
        role = n.mapping_role
        # 统计 participating_leaf
        is_participating_leaf = (
            not n.is_summary
            and not n.is_ignored
            and role != "structural_summary"
            and n.participates_in_entry
        )
        if is_participating_leaf:
            s.participating_leaf_count += 1
            if n.resolved_standard_account_id:
                s.resolved_participating_leaf_count += 1
        # 角色统计（在 participating_leaf 范围内）
        if role == "structural_summary":
            s.structural_summary_count += 1
        elif role == "anchor":
            s.anchor_count += 1
        elif role == "inherited":
            s.inherited_count += 1
        elif role == "breakpoint":
            s.breakpoint_count += 1
        elif role == "explicit_override":
            s.explicit_override_count += 1
        elif role == "unresolved":
            s.unresolved_count += 1
        if n.requires_confirmation:
            s.confirmation_required_count += 1

    # TASK-092 性能统计（调用方传入更精确的数字）
    if full_recommendation_node_count is not None:
        s.full_recommendation_node_count = full_recommendation_node_count
    else:
        # fallback：以 anchor + breakpoint + explicit_override 作为完整推荐节点
        s.full_recommendation_node_count = (
            s.anchor_count + s.breakpoint_count + s.explicit_override_count
        )
    if light_signal_node_count is not None:
        s.light_signal_node_count = light_signal_node_count
    else:
        s.light_signal_node_count = max(
            s.total_nodes - s.structural_summary_count, 0
        )
    if inherited_without_recommendation_count is not None:
        s.inherited_without_recommendation_count = inherited_without_recommendation_count
    else:
        s.inherited_without_recommendation_count = s.inherited_count

    return s


# ── 8. 顶层 API 包装（便于 service 调用） ─────────────────


async def run_anchor_inheritance_mapping(
    db: AsyncSession,
    rows_meta: list[dict],
    row_mapping_meta: dict[int, dict],
    customer_label: str | None,
    source_label: str | None,
    recommend_anchor_fn,
    ignored_rows: set[int] | None = None,
    explicit_overrides: dict[int, str] | None = None,
) -> tuple[AccountTree, MappingPlanSummary]:
    """一次跑完：构建树 → 找强信号 → 遍历 → 统计。"""
    tree = build_account_tree(rows_meta, row_mapping_meta, ignored_rows)
    tree, summary = await build_mapping_plan(
        tree=tree,
        db=db,
        customer_label=customer_label,
        source_label=source_label,
        recommend_anchor_fn=recommend_anchor_fn,
        explicit_overrides=explicit_overrides,
    )
    return tree, summary
