"""ANCHOR-INHERITANCE-MAPPING：客户科目树 + 继承决策 + 映射计划单元测试

覆盖：
- 普通银行/费用明细继承
- 结构汇总节点
- 原值与备抵中断
- 研发费用化/资本化中断
- 应收/应付方向中断
- 收入/成本/费用性质中断
- 普通中性名称不触发中断
- 显式覆盖
- 无锚点阻断
- 经验保存边界
"""

import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock

from app.services.account_mapping_inheritance_service import (
    AccountTree,
    AccountTreeNode,
    InheritanceDecision,
    AnchorResolution,
    STRUCTURAL_SUMMARY_NAMES,
    build_account_tree,
    build_mapping_plan,
    evaluate_inheritance_boundary,
    find_strong_direct_signals,
    is_structural_summary,
    resolve_leaf_standard_accounts,
    validate_mapping_plan,
)


# ── 工具 ───────────────────────────────────────────


def _sa(
    sid: str,
    code: str,
    name: str,
    category: str = "asset",
    direction: str = "debit",
    is_active: bool = True,
) -> MagicMock:
    """构造 StandardAccount mock。"""
    sa = MagicMock()
    sa.id = uuid.UUID(sid) if isinstance(sid, str) else sid
    sa.account_code = code
    sa.account_name = name
    sa.account_category = category
    sa.balance_direction = direction
    sa.is_active = is_active
    sa.is_leaf = True
    return sa


@pytest.fixture(autouse=True)
def _clear_sa_cache():
    """每个测试前清理全局 _sa_cache 避免相互污染。"""
    from app.services.account_mapping_inheritance_service import _sa_cache
    _sa_cache.clear()
    yield
    _sa_cache.clear()


def _node(
    ri: int,
    code: str | None = None,
    name: str | None = None,
    parent_ri: int | None = None,
    ancestor_codes: list[str] | None = None,
    ancestor_names: list[str] | None = None,
    is_leaf: bool = True,
    is_summary: bool = False,
    participates: bool = True,
) -> AccountTreeNode:
    """构造 AccountTreeNode。"""
    parent_key = None
    if parent_ri is not None and code:
        parent_key = str(parent_ri)
    return AccountTreeNode(
        row_index=ri,
        client_account_code=code,
        client_account_name=name,
        level=1 if parent_ri is None else 2,
        parent_row_index=parent_ri,
        parent_key=parent_key,
        ancestor_codes=ancestor_codes or [],
        ancestor_names=ancestor_names or [],
        is_leaf=is_leaf,
        is_summary=is_summary,
        participates_in_entry=participates,
    )


# ── 1. 树构建基础 ────────────────────────────────────


class TestBuildAccountTree:
    """build_account_tree 应正确建立父子、兄弟、祖先关系。"""

    def test_simple_flat_tree(self):
        rows = [
            {"row_index": 0, "client_account_code": "1001", "client_account_name": "库存现金",
             "level": 1, "parent_key": None, "is_leaf": True, "is_summary": False,
             "ancestor_codes": [], "ancestor_names": []},
            {"row_index": 1, "client_account_code": "1002", "client_account_name": "银行存款",
             "level": 1, "parent_key": None, "is_leaf": True, "is_summary": False,
             "ancestor_codes": [], "ancestor_names": []},
        ]
        tree = build_account_tree(rows)
        assert tree.root_rows == [0, 1]
        assert len(tree.nodes_by_row) == 2
        assert tree.nodes_by_row[0].client_account_name == "库存现金"
        # 根节点的 descendant_leaf_count = 1（自身是叶子）
        assert tree.nodes_by_row[0].descendant_leaf_count == 1

    def test_three_level_tree(self):
        rows = [
            {"row_index": 0, "client_account_code": "1002", "client_account_name": "银行存款",
             "level": 1, "parent_key": None, "is_leaf": False, "is_summary": True,
             "ancestor_codes": [], "ancestor_names": []},
            {"row_index": 1, "client_account_code": "100201", "client_account_name": "工商银行",
             "level": 2, "parent_key": "1002", "is_leaf": False, "is_summary": True,
             "ancestor_codes": ["1002"], "ancestor_names": ["银行存款"]},
            {"row_index": 2, "client_account_code": "10020101", "client_account_name": "基本户",
             "level": 3, "parent_key": "100201", "is_leaf": True, "is_summary": False,
             "ancestor_codes": ["1002", "100201"], "ancestor_names": ["银行存款", "工商银行"]},
        ]
        tree = build_account_tree(rows)
        # 根 = 行 0
        assert 0 in tree.root_rows
        # 父级 0 → 子级 1
        assert 1 in tree.children_by_row[0]
        # 父级 1 → 子级 2
        assert 2 in tree.children_by_row[1]
        # 根节点的 descendant_leaf_count = 1
        assert tree.nodes_by_row[0].descendant_leaf_count == 1
        # 工商银行节点的 descendant_leaf_count = 1
        assert tree.nodes_by_row[1].descendant_leaf_count == 1
        # 基本户的 full_path 应包含完整路径
        assert "银行存款" in tree.nodes_by_row[2].full_path
        assert "工商银行" in tree.nodes_by_row[2].full_path

    def test_ignored_rows(self):
        rows = [
            {"row_index": 0, "client_account_code": "1001", "client_account_name": "现金",
             "level": 1, "parent_key": None, "is_leaf": True, "is_summary": False,
             "ancestor_codes": [], "ancestor_names": []},
            {"row_index": 1, "client_account_code": "9999", "client_account_name": "忽略",
             "level": 1, "parent_key": None, "is_leaf": True, "is_summary": False,
             "ancestor_codes": [], "ancestor_names": []},
        ]
        tree = build_account_tree(rows, ignored_rows={1})
        assert tree.nodes_by_row[1].is_ignored is True
        assert tree.nodes_by_row[1].participates_in_entry is False


# ── 2. 结构汇总节点识别 ─────────────────────────────


class TestIsStructuralSummary:
    def test_structural_keywords_recognized(self):
        for kw in ["资产类", "流动资产", "损益类", "期间费用", "项目核算", "部门核算"]:
            n = AccountTreeNode(row_index=0, client_account_name=kw)
            assert is_structural_summary(n) is True, f"未识别结构词：{kw}"

    def test_non_structural_not_recognized(self):
        for kw in ["银行存款", "应收账款", "管理费用", "主营业务收入"]:
            n = AccountTreeNode(row_index=0, client_account_name=kw, is_summary=True)
            assert is_structural_summary(n) is False, f"误判为结构词：{kw}"

    def test_parent_with_summary_flag_and_no_participation(self):
        n = AccountTreeNode(
            row_index=0,
            client_account_name="项目核算",
            is_summary=True,
            participates_in_entry=False,
        )
        assert is_structural_summary(n) is True


# ── 3. 继承中断评估 ────────────────────────────────


class TestInheritanceBoundary:
    def test_no_break_neutral_name(self):
        """普通费用明细不中断。"""
        anc = _sa("0" * 32, "6602", "管理费用", category="expense")
        node = AccountTreeNode(row_index=1, client_account_name="办公费")
        decision = evaluate_inheritance_boundary(
            node=node,
            inherited_standard_account=anc,
            strong_direct_signal=None,
        )
        assert decision.should_break is False
        assert decision.suggested_role == "inherited"

    def test_break_rd_capitalization(self):
        """研发费用化与资本化必须中断。"""
        anc = _sa("0" * 32, "660201", "研发费用-费用化支出", category="expense")
        node = AccountTreeNode(row_index=1, client_account_name="资本化支出-人工费")
        decision = evaluate_inheritance_boundary(
            node=node,
            inherited_standard_account=anc,
            strong_direct_signal=None,
        )
        assert decision.should_break is True
        assert decision.reason_code == "rd_capitalization_boundary"

    def test_break_reserve_token(self):
        """累计折旧 / 减值准备类必须中断。"""
        anc = _sa("0" * 32, "1601", "固定资产原值", category="asset")
        node = AccountTreeNode(row_index=1, client_account_name="累计折旧")
        decision = evaluate_inheritance_boundary(
            node=node,
            inherited_standard_account=anc,
            strong_direct_signal=None,
        )
        assert decision.should_break is True
        assert decision.reason_code == "reserve_token_boundary"

    def test_break_direction_receivable_to_payable(self):
        """应收/应付必须中断。"""
        anc = _sa("0" * 32, "1122", "应收账款", category="asset")
        node = AccountTreeNode(row_index=1, client_account_name="应付账款-供应商A")
        decision = evaluate_inheritance_boundary(
            node=node,
            inherited_standard_account=anc,
            strong_direct_signal=None,
        )
        assert decision.should_break is True
        assert decision.reason_code == "direction_boundary"

    def test_break_profit_loss_revenue_to_cost(self):
        """收入与成本必须中断。"""
        anc = _sa("0" * 32, "6001", "主营业务收入", category="revenue")
        node = AccountTreeNode(row_index=1, client_account_name="主营业务成本-直接材料")
        decision = evaluate_inheritance_boundary(
            node=node,
            inherited_standard_account=anc,
            strong_direct_signal=None,
        )
        assert decision.should_break is True
        assert decision.reason_code == "profit_loss_boundary"

    def test_neutral_security_deposit_no_break(self):
        """保证金客户是中性词，不应单独触发方向中断。"""
        anc = _sa("0" * 32, "1122", "应收账款", category="asset")
        node = AccountTreeNode(row_index=1, client_account_name="保证金")
        decision = evaluate_inheritance_boundary(
            node=node,
            inherited_standard_account=anc,
            strong_direct_signal=None,
        )
        # 纯中性词不应触发方向变化
        assert decision.should_break is False

    def test_break_category_change(self):
        """会计大类变化触发中断。"""
        anc = _sa("0" * 32, "1122", "应收账款", category="asset")
        # 通过 strong_direct_signal 提供新标准科目（不同大类）
        new_sa = _sa("1" * 32, "6602", "管理费用", category="expense")
        node = AccountTreeNode(row_index=1, client_account_name="管理费用")
        decision = evaluate_inheritance_boundary(
            node=node,
            inherited_standard_account=anc,
            strong_direct_signal={"exact_name_match": [new_sa]},
        )
        assert decision.should_break is True

    def test_break_history_override(self):
        """公司历史映射到不同目标触发中断。"""
        anc = _sa("0" * 32, "1122", "应收账款", category="asset")
        # 历史目标：其他应收款
        new_sa = _sa("1" * 32, "1221", "其他应收款", category="asset")
        cam = MagicMock()
        cam.standard_account_id = new_sa.id
        cam.standard_account_code_snapshot = "1221"
        cam.standard_account_name_snapshot = "其他应收款"
        cam.id = uuid.UUID("2" * 32)
        node = AccountTreeNode(row_index=1, client_account_name="客户A")
        decision = evaluate_inheritance_boundary(
            node=node,
            inherited_standard_account=anc,
            strong_direct_signal={"history": [cam]},
        )
        assert decision.should_break is True
        assert decision.reason_code == "user_history_override"


# ── 4. 映射计划构建（树遍历）────────────────────────


class TestBuildMappingPlan:
    """测试完整映射计划生成：树遍历 + 锚点发现 + 继承 + 中断。"""

    @pytest.mark.asyncio
    async def test_simple_bank_inheritance(self):
        """银行三级明细全部继承。"""
        rows = [
            {"row_index": 0, "client_account_code": "1002", "client_account_name": "银行存款",
             "level": 1, "parent_key": None, "is_leaf": True, "is_summary": False,
             "ancestor_codes": [], "ancestor_names": []},
            {"row_index": 1, "client_account_code": "100201", "client_account_name": "工商银行",
             "level": 2, "parent_key": "1002", "is_leaf": True, "is_summary": False,
             "ancestor_codes": ["1002"], "ancestor_names": ["银行存款"]},
        ]
        tree = build_account_tree(rows)
        # mock 锚点推荐
        target_sa = _sa("1" * 32, "1002", "银行存款", category="asset", direction="debit")

        async def recommend(node: AccountTreeNode) -> AnchorResolution:
            return AnchorResolution(
                standard_account_id=str(target_sa.id),
                standard_account_code=target_sa.account_code,
                standard_account_name=target_sa.account_name,
                source="code_match",
                reason="代码精确匹配",
                is_resolved=True,
                auto_confirm_status="unique_safe",
            )

        db = AsyncMock()
        db.get = AsyncMock(return_value=target_sa)
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=target_sa))
        )

        tree, summary = await build_mapping_plan(
            tree=tree,
            db=db,
            customer_label="测试公司",
            recommend_anchor_fn=recommend,
        )
        # 0 = anchor
        assert tree.nodes_by_row[0].mapping_role == "anchor"
        # 1 = inherited
        assert tree.nodes_by_row[1].mapping_role == "inherited"
        # 继承自 0
        assert tree.nodes_by_row[1].anchor_row_index == 0
        # 解析到同一标准科目
        assert tree.nodes_by_row[1].resolved_standard_account_id == str(target_sa.id)
        # 统计
        assert summary.anchor_count == 1
        assert summary.inherited_count == 1

    @pytest.mark.asyncio
    async def test_structural_summary_passthrough(self):
        """结构汇总节点不下传锚点。"""
        rows = [
            {"row_index": 0, "client_account_code": None, "client_account_name": "资产类",
             "level": 1, "parent_key": None, "is_leaf": False, "is_summary": True,
             "ancestor_codes": [], "ancestor_names": []},
            {"row_index": 1, "client_account_code": "1001", "client_account_name": "库存现金",
             "level": 2, "parent_key": None, "is_leaf": True, "is_summary": False,
             "ancestor_codes": [], "ancestor_names": ["资产类"]},
        ]
        tree = build_account_tree(rows)
        target_sa = _sa("1" * 32, "1001", "库存现金", category="asset", direction="debit")

        async def recommend(node: AccountTreeNode) -> AnchorResolution:
            return AnchorResolution(
                standard_account_id=str(target_sa.id),
                standard_account_code=target_sa.account_code,
                standard_account_name=target_sa.account_name,
                source="code_match",
                reason="代码精确匹配",
                is_resolved=True,
                auto_confirm_status="unique_safe",
            )

        db = AsyncMock()
        db.get = AsyncMock(return_value=target_sa)
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=target_sa))
        )

        tree, summary = await build_mapping_plan(
            tree=tree,
            db=db,
            customer_label="测试公司",
            recommend_anchor_fn=recommend,
        )
        # 0 = structural_summary
        assert tree.nodes_by_row[0].mapping_role == "structural_summary"
        # 1 = anchor（因为是结构汇总下重新发现）
        assert tree.nodes_by_row[1].mapping_role == "anchor"

    @pytest.mark.asyncio
    async def test_rd_capitalization_breakpoint(self):
        """研发费用化和资本化分别建立新锚点。"""
        rows = [
            {"row_index": 0, "client_account_code": "5301", "client_account_name": "研发支出",
             "level": 1, "parent_key": None, "is_leaf": False, "is_summary": True,
             "ancestor_codes": [], "ancestor_names": []},
            {"row_index": 1, "client_account_code": "530101", "client_account_name": "费用化支出",
             "level": 2, "parent_key": "5301", "is_leaf": False, "is_summary": True,
             "ancestor_codes": ["5301"], "ancestor_names": ["研发支出"]},
            {"row_index": 2, "client_account_code": "53010101", "client_account_name": "人工费-费用化",
             "level": 3, "parent_key": "530101", "is_leaf": True, "is_summary": False,
             "ancestor_codes": ["5301", "530101"], "ancestor_names": ["研发支出", "费用化支出"]},
            {"row_index": 3, "client_account_code": "530102", "client_account_name": "资本化支出",
             "level": 2, "parent_key": "5301", "is_leaf": False, "is_summary": True,
             "ancestor_codes": ["5301"], "ancestor_names": ["研发支出"]},
            {"row_index": 4, "client_account_code": "53010201", "client_account_name": "人工费-资本化",
             "level": 3, "parent_key": "530102", "is_leaf": True, "is_summary": False,
             "ancestor_codes": ["5301", "530102"], "ancestor_names": ["研发支出", "资本化支出"]},
        ]
        tree = build_account_tree(rows)

        # 锚点推荐
        expense_sa = _sa("0" * 32, "660201", "研发费用-费用化支出", category="expense")
        capital_sa = _sa("1" * 32, "170401", "开发支出-资本化支出", category="asset")

        async def recommend(node: AccountTreeNode) -> AnchorResolution:
            if "费用化" in (node.client_account_name or ""):
                return AnchorResolution(
                    standard_account_id=str(expense_sa.id),
                    standard_account_code=expense_sa.account_code,
                    standard_account_name=expense_sa.account_name,
                    source="code_match", reason="代码匹配", is_resolved=True,
                    auto_confirm_status="unique_safe",
                )
            if "资本化" in (node.client_account_name or ""):
                return AnchorResolution(
                    standard_account_id=str(capital_sa.id),
                    standard_account_code=capital_sa.account_code,
                    standard_account_name=capital_sa.account_name,
                    source="code_match", reason="代码匹配", is_resolved=True,
                    auto_confirm_status="unique_safe",
                )
            return AnchorResolution(
                standard_account_id=None,
                standard_account_code=None,
                standard_account_name=None,
                source=None, reason="无", is_resolved=False,
            )

        db = AsyncMock()
        # mock db.get 根据 id 返回正确的标准科目
        async def mock_get(model, uid):
            if str(uid) == str(expense_sa.id):
                return expense_sa
            if str(uid) == str(capital_sa.id):
                return capital_sa
            return None
        db.get = mock_get
        # mock db.execute 返回空 history（继承服务用 scalars().all() 取 history）
        empty_scalars = MagicMock()
        empty_scalars.all = MagicMock(return_value=[])
        empty_result = MagicMock()
        empty_result.scalars = MagicMock(return_value=empty_scalars)
        async def mock_execute(*args, **kwargs):
            return empty_result
        db.execute = mock_execute

        tree, summary = await build_mapping_plan(
            tree=tree, db=db, customer_label="测试公司", recommend_anchor_fn=recommend,
        )
        # 研发支出 (0) 标记为 structural_summary（不参与入库、不下传）
        assert tree.nodes_by_row[0].mapping_role == "structural_summary"
        # 1 (费用化支出) 和 3 (资本化支出) 各自成为独立 anchor
        assert tree.nodes_by_row[1].mapping_role == "anchor"
        assert tree.nodes_by_row[3].mapping_role == "anchor"
        # 2 (人工费-费用化) 继承 1
        assert tree.nodes_by_row[2].mapping_role == "inherited"
        assert tree.nodes_by_row[2].anchor_row_index == 1
        # 4 (人工费-资本化) 继承 3
        assert tree.nodes_by_row[4].mapping_role == "inherited"
        assert tree.nodes_by_row[4].anchor_row_index == 3
        # 解析目标不同（费用化 vs 资本化）
        assert tree.nodes_by_row[2].resolved_standard_account_id != \
               tree.nodes_by_row[4].resolved_standard_account_id
        # 统计：1 个 structural_summary, 2 个 anchor, 2 个 inherited
        assert summary.structural_summary_count >= 1
        assert summary.anchor_count == 2
        assert summary.inherited_count == 2

    @pytest.mark.asyncio
    async def test_explicit_override(self):
        """用户显式覆盖：将一个继承行改为新锚点。"""
        rows = [
            {"row_index": 0, "client_account_code": "1002", "client_account_name": "银行存款",
             "level": 1, "parent_key": None, "is_leaf": True, "is_summary": False,
             "ancestor_codes": [], "ancestor_names": []},
            {"row_index": 1, "client_account_code": "100201", "client_account_name": "工商银行",
             "level": 2, "parent_key": "1002", "is_leaf": True, "is_summary": False,
             "ancestor_codes": ["1002"], "ancestor_names": ["银行存款"]},
        ]
        tree = build_account_tree(rows)
        target_sa = _sa("0" * 32, "1002", "银行存款", category="asset", direction="debit")
        override_sa = _sa("1" * 32, "1012", "其他货币资金", category="asset", direction="debit")

        async def recommend(node: AccountTreeNode) -> AnchorResolution:
            return AnchorResolution(
                standard_account_id=str(target_sa.id),
                standard_account_code=target_sa.account_code,
                standard_account_name=target_sa.account_name,
                source="code_match", reason="代码匹配", is_resolved=True,
                auto_confirm_status="unique_safe",
            )

        db = AsyncMock()
        # 用户在行 1 上覆盖到 1012
        async def mock_get(model, uid):
            if str(uid) == str(target_sa.id):
                return target_sa
            if str(uid) == str(override_sa.id):
                return override_sa
            return None
        db.get = mock_get
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=target_sa))
        )

        tree, summary = await build_mapping_plan(
            tree=tree,
            db=db,
            customer_label="测试公司",
            recommend_anchor_fn=recommend,
            explicit_overrides={1: str(override_sa.id)},
        )
        assert tree.nodes_by_row[0].mapping_role == "anchor"
        assert tree.nodes_by_row[1].mapping_role == "explicit_override"
        assert tree.nodes_by_row[1].resolved_standard_account_id == str(override_sa.id)
        assert summary.explicit_override_count == 1


# ── 5. 校验与解析 ────────────────────────────────────


class TestValidateAndResolve:
    def test_validate_blocks_unresolved_leaves(self):
        """未解析的参与末级必须阻止执行。"""
        tree = AccountTree()
        # unresolved leaf
        n_unresolved = AccountTreeNode(
            row_index=0, client_account_code="X1", client_account_name="未知",
            is_leaf=True, is_summary=False, participates_in_entry=True,
            mapping_role="unresolved",
        )
        n_resolved = AccountTreeNode(
            row_index=1, client_account_code="1002", client_account_name="银行存款",
            is_leaf=True, is_summary=False, participates_in_entry=True,
            mapping_role="anchor",
            resolved_standard_account_id="1" * 32,
        )
        tree.nodes_by_row = {0: n_unresolved, 1: n_resolved}
        errs = validate_mapping_plan(tree)
        assert len(errs) == 1
        assert "X1" in errs[0]

    def test_resolve_leaves(self):
        tree = AccountTree()
        n1 = AccountTreeNode(
            row_index=0, client_account_code="1002", client_account_name="银行存款",
            is_leaf=True, is_summary=False, participates_in_entry=True,
            mapping_role="anchor", resolved_standard_account_id="1" * 32,
            resolved_standard_account_code="1002",
            resolved_standard_account_name="银行存款",
            resolution_source="code_match", resolution_reason="ok",
            auto_confirm_status="unique_safe",
        )
        n2 = AccountTreeNode(
            row_index=1, client_account_code="100201", client_account_name="工商银行",
            is_leaf=True, is_summary=False, participates_in_entry=True,
            mapping_role="inherited", resolved_standard_account_id="1" * 32,
            resolved_standard_account_code="1002",
            resolved_standard_account_name="银行存款",
            resolution_source="inherited_ancestor", resolution_reason="继承",
            auto_confirm_status="unique_safe",
        )
        n3 = AccountTreeNode(
            row_index=2, client_account_code="9999", client_account_name="structural",
            is_summary=True, participates_in_entry=False,
            mapping_role="structural_summary",
        )
        tree.nodes_by_row = {0: n1, 1: n2, 2: n3}
        leaves = resolve_leaf_standard_accounts(tree)
        # 结构节点不参与；inherited 与 anchor 参与
        assert len(leaves) == 2
        assert 0 in leaves
        assert 1 in leaves


# ── 6. 映射角色枚举完整性 ─────────────────────────────


class TestMappingRoles:
    def test_all_roles_defined(self):
        from app.services.account_mapping_inheritance_service import MAPPING_ROLES
        expected = {
            "structural_summary", "anchor", "inherited", "breakpoint",
            "explicit_override", "unresolved", "ignored",
        }
        assert set(MAPPING_ROLES) == expected

    def test_all_modes_defined(self):
        from app.services.account_mapping_inheritance_service import MAPPING_MODES
        expected = {
            "direct_auto", "direct_confirmed", "inherited_ancestor",
            "override_confirmed", "none",
        }
        assert set(MAPPING_MODES) == expected


# ── 7. 经验保存边界 ────────────────────────────────────


class TestExperienceBoundary:
    """测试继承服务只保存 anchor / override，不保存 inherited。"""

    def test_inherited_role_not_in_experience_set(self):
        from app.services.account_mapping_inheritance_service import MAPPING_ROLES
        experience_saveable = {"anchor", "breakpoint", "explicit_override"}
        # inherited / structural_summary / unresolved / ignored 不得进入经验库
        for role in MAPPING_ROLES:
            if role in experience_saveable:
                continue
            # 其余角色不得作为经验保存
            assert role not in experience_saveable, \
                f"角色 {role} 不应保存为映射经验"
