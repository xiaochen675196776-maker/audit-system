"""上级锚点与下级继承式映射服务 — ANCHOR-INHERITANCE-MAPPING

本模块取代「每个末级客户科目独立匹配标准科目」的主流程。新的主流程：

1. 先解析完整客户科目树（build_account_tree）
2. 识别结构汇总节点（is_structural_summary）
3. 发现首批映射锚点（discover_mapping_anchors）
4. 沿树向下传播，每个子节点判断是否需要中断继承
   （evaluate_inheritance_boundary）
5. 生成完整映射计划（build_mapping_plan / propagate_anchor_mapping）
6. 执行阶段重新构建同一棵树，校验锚点并解析叶子的标准科目
   （validate_mapping_plan / resolve_leaf_standard_accounts）

普通子节点不再调用 recommend_mappings 的全局兜底逻辑（name_similarity、
code_prefix_parent、code_category_anchor、name_anchor）。只有 anchor /
breakpoint / explicit_override 节点才会触发完整推荐。

硬约束：
- 不得为任何客户、任何 Excel、任何具体科目代码写硬编码。
- 不得使用 candidates[0] 对未确认行兜底。
- 普通 inherited 行不保存为映射经验。
- 任一参与入库的末级若未解析唯一标准科目，必须阻止 execute。

继承中断点（强信号）必须由以下证据之一触发：
- 用户/公司历史明确覆盖；
- 精确标准代码命中不同目标；
- 精确标准名称/明确语义命中不同目标；
- 原值与备抵变化（累计折旧、减值准备、坏账准备等）；
- 研发费用化与资本化方向变化；
- 资产与负债方向变化（应收/应付 等）；
- 收入/成本/费用性质变化；
- 会计大类变化（资产/负债/权益/收入/成本/费用）；
- 用户在前端显式单独映射。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_account_mapping import ClientAccountMapping
from app.models.standard_account import StandardAccount


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
    """锚点的标准科目解析结果。"""
    standard_account_id: str | None
    standard_account_code: str | None
    standard_account_name: str | None
    source: str | None
    reason: str | None
    is_resolved: bool = False
    auto_confirm_status: str | None = None
    auto_confirm_reason: str | None = None


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
        parent_row_index: int | None = None
        if parent_key:
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


# ── 2. 结构汇总节点识别 ────────────────────────────────────


def is_structural_summary(node: AccountTreeNode) -> bool:
    """判断节点是否是结构汇总节点。"""
    # 已是父级但其下子节点映射到不同会计大类的也视为结构汇总
    name = _normalize_name(node.client_account_name)
    if not name:
        return True
    if name in STRUCTURAL_SUMMARY_NAMES:
        return True
    # 没有任何客户科目代码 + 名称属于结构词
    if not node.client_account_code and name in STRUCTURAL_SUMMARY_NAMES:
        return True
    # 父级且不参与入库
    if node.is_summary and not node.participates_in_entry:
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


# ── 5. 映射计划构建 ───────────────────────────────────────


async def build_mapping_plan(
    tree: AccountTree,
    db: AsyncSession,
    customer_label: str | None = None,
    source_label: str | None = None,
    recommend_anchor_fn=None,
    explicit_overrides: dict[int, str] | None = None,
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

    Returns:
        (更新后的 tree, summary)
    """
    explicit_overrides = explicit_overrides or {}
    nodes = tree.nodes_by_row

    # 1) 预加载所有节点的强信号
    strong_signals = await find_strong_direct_signals(
        db, list(nodes.values()), customer_label=customer_label
    )

    # 2) 深度优先遍历
    async def _visit(ri: int, inherited_anchor: AnchorResolution | None) -> None:
        node = nodes[ri]
        if node.is_ignored:
            node.mapping_role = "ignored"
            node.mapping_mode = "none"
            return

        # 1) 结构汇总：不下传锚点
        if is_structural_summary(node):
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

    summary = _build_summary(tree)
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


def _build_summary(tree: AccountTree) -> MappingPlanSummary:
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
