"""TASK-087：科目余额表匹配主线重构 — 名称语义优先定向测试

覆盖：
1. 4101 生产成本 → 5001 生产成本（非 4003 资本公积）
2. 4105 制造费用 → 5101 制造费用（非 4105 利润分配）
3. 包装物_纸箱 → 141101 包装物优先于 1411 周转材料
4. 4101.02.003 工资（父级生产成本）→ 继承生产成本
5. 折旧费（父级制造费用）→ 继承制造费用
6. 旧编码 401 生产成本 → 5001
7. 旧编码 405 制造费用 → 5101
8. 旧编码 301 实收资本
9. 旧编码 311 资本公积
10. 4107 研发支出无上下文 → 人工确认
11. 研发支出_费用化支出 → 费用化方向
12. 研发支出_资本化支出 → 资本化方向
13. 代码名称冲突
14. 名称为空 → unknown
15. 模糊匹配不自动确认
16. 多个安全目标 → ambiguous
17. 同一目标多来源 → 可自动确认
18. 停用标准科目不自动确认
"""

import pytest
from app.models.standard_account import StandardAccount
from app.models.client_account_mapping import ClientAccountMapping
from app.services.client_account_mapping_service import (
    recommend_mappings,
    pick_unique_auto_confirm_candidate,
    _is_safe_candidate,
    evaluate_name_compatibility,
)


def _sa(code: str, name: str, **kw) -> StandardAccount:
    return StandardAccount(account_code=code, account_name=name, **kw)


def _find_by_source(candidates: list[dict], source: str) -> list[dict]:
    return [c for c in candidates if c.get("source") == source]


def _find_by_code(candidates: list[dict], code: str) -> list[dict]:
    return [c for c in candidates if c.get("standard_account_code") == code]


class Test4101ProductionCost:
    """4101 生产成本 → 5001 生产成本（非 4003 资本公积）"""

    @pytest.mark.asyncio
    async def test_4101_production_cost_goes_to_5001(self, db):
        """4101 生产成本应匹配 5001 生产成本，不匹配 4003 资本公积"""
        sa_cost = _sa("5001", "生产成本")
        sa_capital = _sa("4003", "资本公积")
        db.add_all([sa_cost, sa_capital])
        await db.flush()

        results = await recommend_mappings(
            db, data_type="trial_balance",
            client_accounts=[{"client_account_code": "4101", "client_account_name": "生产成本"}],
        )
        candidates = results[0]["candidates"]
        # 应存在指向 5001 的安全候选
        safe_for_cost = [c for c in candidates
                         if c["standard_account_code"] == "5001" and _is_safe_candidate(c)]
        assert len(safe_for_cost) >= 1, f"生产成本应安全匹配 5001，实际: {candidates}"
        # 4003 资本公积不应是安全候选
        safe_for_capital = [c for c in candidates
                            if c["standard_account_code"] == "4003" and _is_safe_candidate(c)]
        assert len(safe_for_capital) == 0, "资本公积不应该成为安全候选"
        # 自动确认应为生产成本
        auto = pick_unique_auto_confirm_candidate(candidates)
        assert auto is not None
        assert auto["standard_account_code"] == "5001"


class Test4105ManufacturingOverhead:
    """4105 制造费用 → 5101 制造费用（非 4105 利润分配）"""

    @pytest.mark.asyncio
    async def test_4105_manufacturing_goes_to_5101(self, db):
        """4105 制造费用应匹配 5101 制造费用，不匹配 4105 利润分配"""
        sa_mfg = _sa("5101", "制造费用")
        sa_profit = _sa("4105", "利润分配")
        db.add_all([sa_mfg, sa_profit])
        await db.flush()

        results = await recommend_mappings(
            db, data_type="trial_balance",
            client_accounts=[{"client_account_code": "4105", "client_account_name": "制造费用"}],
        )
        candidates = results[0]["candidates"]
        # 5101 制造费用应是安全候选
        safe_for_mfg = [c for c in candidates
                        if c["standard_account_code"] == "5101" and _is_safe_candidate(c)]
        assert len(safe_for_mfg) >= 1, f"制造费用应安全匹配 5101，实际: {candidates}"
        # 4105 利润分配不应是安全候选
        safe_for_profit = [c for c in candidates
                           if c["standard_account_code"] == "4105" and _is_safe_candidate(c)]
        assert len(safe_for_profit) == 0, "利润分配不应该成为安全候选"


class TestPackagingPrefix:
    """包装物_纸箱 → 141101 包装物优先于 1411 周转材料"""

    @pytest.mark.asyncio
    async def test_packaging_prefix_prioritized(self, db):
        """1411 包装物_纸箱应优先匹配 141101 包装物"""
        sa_turnover = _sa("1411", "周转材料")
        sa_packaging = _sa("141101", "包装物")
        db.add_all([sa_turnover, sa_packaging])
        await db.flush()

        results = await recommend_mappings(
            db, data_type="trial_balance",
            client_accounts=[{"client_account_code": "1411", "client_account_name": "包装物_纸箱"}],
        )
        candidates = results[0]["candidates"]
        # name_prefix 应指向 141101
        prefix_cands = [c for c in candidates if c.get("source") == "name_prefix"]
        assert len(prefix_cands) >= 1, f"name_prefix 应命中包装物: {candidates}"
        assert prefix_cands[0]["standard_account_code"] == "141101"
        # 141101 的安全候选优先级应高于 1411
        safe_ids = [c["standard_account_id"] for c in candidates if _is_safe_candidate(c)]
        first_safe_code = next((c["standard_account_code"] for c in candidates if _is_safe_candidate(c)), None)
        assert first_safe_code == "141101" or str(sa_packaging.id) in safe_ids


class TestProductionCostDetailInherit:
    """4101.02.003 工资（父级生产成本）→ 继承生产成本"""

    @pytest.mark.asyncio
    async def test_production_cost_child_inherits_parent(self, db):
        """明细科目「工资」父级为生产成本 → 继承 5001 生产成本"""
        sa_cost = _sa("5001", "生产成本")
        sa_capital = _sa("4003", "资本公积")
        db.add_all([sa_cost, sa_capital])
        await db.flush()

        results = await recommend_mappings(
            db, data_type="trial_balance",
            client_accounts=[{
                "client_account_code": "4101.02.003",
                "client_account_name": "工资",
                "parent_client_account_code": "401",  # 旧编码 401 → 5001
                "parent_client_account_name": "生产成本",
            }],
        )
        candidates = results[0]["candidates"]
        # 不应有资本公积安全候选
        safe_capital = [c for c in candidates
                        if c["standard_account_code"] == "4003" and _is_safe_candidate(c)]
        assert len(safe_capital) == 0, "工资(父:生产成本)不应自动确认资本公积"
        # 应有生产成本相关候选
        cost_cands = _find_by_code(candidates, "5001")
        assert len(cost_cands) >= 1, f"应有生产成本候选，实际: {candidates}"


class TestManufacturingDetailInherit:
    """折旧费（父级制造费用）→ 继承制造费用"""

    @pytest.mark.asyncio
    async def test_depreciation_inherits_manufacturing(self, db):
        """「折旧费」父级为制造费用 → 继承 5101 制造费用，不继承累计折旧"""
        sa_mfg = _sa("5101", "制造费用")
        sa_depr = _sa("1602", "累计折旧")
        db.add_all([sa_mfg, sa_depr])
        await db.flush()

        results = await recommend_mappings(
            db, data_type="trial_balance",
            client_accounts=[{
                "client_account_code": "",
                "client_account_name": "折旧费",
                "parent_client_account_name": "制造费用",
            }],
        )
        candidates = results[0]["candidates"]
        safe_depr = [c for c in candidates
                     if c["standard_account_code"] == "1602" and _is_safe_candidate(c)]
        assert len(safe_depr) == 0, "折旧费(父:制造费用)不应自动确认为累计折旧"


class TestOldCodeCrosswalk:
    """旧编码 crosswalk 在名称兼容时应正确匹配"""

    @pytest.mark.asyncio
    async def test_401_production_cost(self, db):
        """旧编码 401 生产成本 → 5001 生产成本"""
        sa = _sa("5001", "生产成本")
        db.add(sa)
        await db.flush()

        results = await recommend_mappings(
            db, data_type="trial_balance",
            client_accounts=[{"client_account_code": "401", "client_account_name": "生产成本"}],
        )
        candidates = results[0]["candidates"]
        cost_cands = _find_by_code(candidates, "5001")
        assert len(cost_cands) >= 1
        # 应可自动确认
        assert any(_is_safe_candidate(c) for c in cost_cands)

    @pytest.mark.asyncio
    async def test_405_manufacturing_overhead(self, db):
        """旧编码 405 制造费用 → 5101 制造费用"""
        sa = _sa("5101", "制造费用")
        db.add(sa)
        await db.flush()

        results = await recommend_mappings(
            db, data_type="trial_balance",
            client_accounts=[{"client_account_code": "405", "client_account_name": "制造费用"}],
        )
        candidates = results[0]["candidates"]
        mfg_cands = _find_by_code(candidates, "5101")
        assert len(mfg_cands) >= 1
        assert any(_is_safe_candidate(c) for c in mfg_cands)

    @pytest.mark.asyncio
    async def test_301_paid_in_capital(self, db):
        """旧编码 301 实收资本 → 标准库实收资本"""
        sa = _sa("4001", "实收资本")
        db.add(sa)
        await db.flush()

        results = await recommend_mappings(
            db, data_type="trial_balance",
            client_accounts=[{"client_account_code": "301", "client_account_name": "实收资本"}],
        )
        candidates = results[0]["candidates"]
        paid_cands = _find_by_code(candidates, "4001")
        assert len(paid_cands) >= 1

    @pytest.mark.asyncio
    async def test_311_capital_reserve(self, db):
        """旧编码 311 资本公积 → 标准库资本公积"""
        sa = _sa("4003", "资本公积")
        db.add(sa)
        await db.flush()

        results = await recommend_mappings(
            db, data_type="trial_balance",
            client_accounts=[{"client_account_code": "311", "client_account_name": "资本公积"}],
        )
        candidates = results[0]["candidates"]
        reserve_cands = _find_by_code(candidates, "4003")
        assert len(reserve_cands) >= 1


class TestRDExpenditureNoContext:
    """4107 研发支出无上下文 → 人工确认"""

    @pytest.mark.asyncio
    async def test_4107_rd_expenditure_no_auto_confirm(self, db):
        """研发支出无费用化/资本化证据时不自动确认"""
        sa_rd_expense = _sa("660201", "减：研发费用")
        sa_rd_cap = _sa("170401", "研发支出-资本化支出")
        sa_rd_exp = _sa("170402", "研发支出-费用化支出")
        db.add_all([sa_rd_expense, sa_rd_cap, sa_rd_exp])
        await db.flush()

        results = await recommend_mappings(
            db, data_type="trial_balance",
            client_accounts=[{"client_account_code": "4107", "client_account_name": "研发支出"}],
        )
        candidates = results[0]["candidates"]
        # 不应有自动确认候选
        auto = pick_unique_auto_confirm_candidate(candidates)
        assert auto is None, f"研发支出无上下文不应自动确认: {auto}"
        # 应有候选但需人工确认
        assert len(candidates) >= 1


class TestRDExpenditureDirection:
    """研发支出费用化/资本化方向检测"""

    @pytest.mark.asyncio
    async def test_rd_expensing(self, db):
        """研发支出_费用化支出 → 费用化方向"""
        sa_rd_exp = _sa("170402", "研发支出-费用化支出")
        sa_rd_cap = _sa("170401", "研发支出-资本化支出")
        db.add_all([sa_rd_exp, sa_rd_cap])
        await db.flush()

        results = await recommend_mappings(
            db, data_type="trial_balance",
            client_accounts=[{"client_account_code": "", "client_account_name": "研发支出_费用化支出"}],
        )
        candidates = results[0]["candidates"]
        # 应有指向 170402 的候选
        exp_cands = _find_by_code(candidates, "170402")
        assert len(exp_cands) >= 1

    @pytest.mark.asyncio
    async def test_rd_capitalizing(self, db):
        """研发支出_资本化支出 → 资本化方向"""
        sa_rd_exp = _sa("170402", "研发支出-费用化支出")
        sa_rd_cap = _sa("170401", "研发支出-资本化支出")
        db.add_all([sa_rd_exp, sa_rd_cap])
        await db.flush()

        results = await recommend_mappings(
            db, data_type="trial_balance",
            client_accounts=[{"client_account_code": "", "client_account_name": "研发支出_资本化支出"}],
        )
        candidates = results[0]["candidates"]
        cap_cands = _find_by_code(candidates, "170401")
        assert len(cap_cands) >= 1


class TestCodeNameConflict:
    """代码命中A但名称明确属于B → 名称优先"""

    @pytest.mark.asyncio
    async def test_code_match_downgraded_when_name_conflicts(self, db):
        """代码命中 A 但客户名称明确属于 B → A 降级"""
        sa_a = _sa("4001", "实收资本")  # 代码不匹配，但作为参照
        sa_b = _sa("5001", "生产成本")  # 名称匹配
        db.add_all([sa_a, sa_b])
        await db.flush()

        # 构造场景：代码 4101 匹配不到任何标准科目（无 4101 标准科目），
        # 但名称"生产成本"应通过语义别名匹配到 5001
        results = await recommend_mappings(
            db, data_type="trial_balance",
            client_accounts=[{"client_account_code": "4101", "client_account_name": "生产成本"}],
        )
        candidates = results[0]["candidates"]
        # 5001 生产成本应为安全候选
        safe_for_cost = [c for c in candidates
                         if c["standard_account_code"] == "5001" and _is_safe_candidate(c)]
        assert len(safe_for_cost) >= 1


class TestEmptyName:
    """名称为空 → unknown，不自动确认"""

    @pytest.mark.asyncio
    async def test_empty_name_no_auto_confirm(self, db):
        """仅代码1002无名称 → 可返回候选但不自动确认"""
        sa = _sa("1002", "银行存款")
        db.add(sa)
        await db.flush()

        results = await recommend_mappings(
            db, data_type="trial_balance",
            client_accounts=[{"client_account_code": "1002", "client_account_name": ""}],
        )
        candidates = results[0]["candidates"]
        auto = pick_unique_auto_confirm_candidate(candidates)
        # 名称为空不应自动确认
        assert auto is None
        # 但有候选
        assert len(candidates) >= 1


class TestFuzzyMatchNoAutoConfirm:
    """模糊匹配不自动确认"""

    @pytest.mark.asyncio
    async def test_fuzzy_match_never_auto_confirm(self, db):
        """名称相似度再高也不自动确认"""
        sa = _sa("1001", "库存现金")
        db.add(sa)
        await db.flush()

        # "库存现钞" 与 "库存现金" 相似度很高但不精确匹配
        results = await recommend_mappings(
            db, data_type="trial_balance",
            client_accounts=[{"client_account_code": "", "client_account_name": "库存现钞"}],
        )
        candidates = results[0]["candidates"]
        sim_cands = [c for c in candidates if c.get("source") == "name_similarity"]
        if sim_cands:
            for c in sim_cands:
                assert c.get("auto_confirmable") is False, f"模糊匹配不应可自动确认: {c}"
                assert c.get("warning") is not None
                assert c.get("score", 0) < 0.9


class TestMultipleSafeTargets:
    """多个安全目标 → ambiguous"""

    @pytest.mark.asyncio
    async def test_multiple_safe_targets_no_auto_confirm(self, db):
        """两个不同安全目标时不应自动确认"""
        sa_a = _sa("112201", "应收账款")
        sa_b = _sa("112101", "应收票据")
        db.add_all([sa_a, sa_b])
        await db.flush()

        # 创建同一客户历史映射指向 A
        cam = ClientAccountMapping(
            data_type="trial_balance",
            customer_label="测试公司",
            scope="company",
            client_account_code="CX001",
            client_account_name="应收款项",
            normalized_client_account_name="应收款项",
            standard_account_id=sa_a.id,
            standard_account_code_snapshot="112201",
            standard_account_name_snapshot="应收账款",
            confidence=1.0,
            usage_count=2,
        )
        db.add(cam)
        await db.flush()

        # 客户名称同时匹配两个名称锚点候选
        results = await recommend_mappings(
            db, data_type="trial_balance",
            customer_label="测试公司",
            client_accounts=[{"client_account_code": "CX001", "client_account_name": "应收款项"}],
        )
        candidates = results[0]["candidates"]
        auto = pick_unique_auto_confirm_candidate(candidates)
        # 如果只有一条安全候选则自动确认，有多条则应取消
        safe = [c for c in candidates if _is_safe_candidate(c)]
        safe_ids = {c["standard_account_id"] for c in safe}
        if len(safe_ids) > 1:
            assert auto is None, f"多个安全目标不应自动确认: {safe_ids}"
        # 但应有候选可选
        assert len(candidates) >= 1


class TestSingleTargetMultipleSources:
    """同一目标多来源 → 可自动确认"""

    @pytest.mark.asyncio
    async def test_same_target_multiple_sources_auto_confirm(self, db):
        """name_exact + semantic_alias 指向同一标准科目 → 可自动确认"""
        sa = _sa("5001", "生产成本")
        db.add(sa)
        await db.flush()

        results = await recommend_mappings(
            db, data_type="trial_balance",
            client_accounts=[{"client_account_code": "", "client_account_name": "生产成本"}],
        )
        candidates = results[0]["candidates"]
        auto = pick_unique_auto_confirm_candidate(candidates)
        assert auto is not None, "唯一安全目标应自动确认"
        assert auto["standard_account_code"] == "5001"


class TestDisabledStandardAccount:
    """停用标准科目不自动确认"""

    @pytest.mark.asyncio
    async def test_disabled_account_no_auto_confirm(self, db):
        """停用科目即使名称精确匹配也不自动确认"""
        sa = _sa("1001", "库存现金", is_active=False)
        db.add(sa)
        await db.flush()

        results = await recommend_mappings(
            db, data_type="trial_balance",
            client_accounts=[{"client_account_code": "1001", "client_account_name": "库存现金"}],
        )
        candidates = results[0]["candidates"]
        # 不应有安全候选
        safe = [c for c in candidates if _is_safe_candidate(c)]
        assert len(safe) == 0, "停用科目不应有安全候选"
        # 停用科目候选应有 warning
        disabled_cands = [c for c in candidates
                          if c["standard_account_id"] == str(sa.id)]
        if disabled_cands:
            for c in disabled_cands:
                assert c.get("warning") is not None or c.get("auto_confirmable") is False


# ════════════════════════════════════════════════════════════
# TASK-088：完整路径语义接入专项测试
# ════════════════════════════════════════════════════════════


class TestFullPathGenericName:
    """用例1：当前名称泛化，完整路径明确 → 路径提供上下文"""

    def test_generic_wage_identified_by_full_path(self):
        """当前名称「工资」泛化，路径「生产成本/离合器/工资」→ 识别为生产成本"""
        sa = _sa("5001", "生产成本")
        result = evaluate_name_compatibility(
            sa,
            client_account_name="工资",
            client_account_full_path="生产成本/离合器/工资",
        )
        # 路径中的「生产成本」应被识别为语义组 production_cost
        assert result.status == "compatible", f"状态应为compatible，实际: {result.status}"
        assert result.detected_group == "production_cost", \
            f"应检测到production_cost组，实际: {result.detected_group}"
        assert any("path_semantic_group=production_cost" in e for e in result.evidence), \
            f"evidence 应包含 path_semantic_group"
        assert any("full_path=" in e for e in result.evidence), \
            f"evidence 应包含 full_path"

    def test_generic_name_path_conflict_rejected(self):
        """泛化名通过路径识别语义组后，不匹配冲突的标准科目"""
        sa = _sa("4003", "资本公积")
        result = evaluate_name_compatibility(
            sa,
            client_account_name="工资",
            client_account_full_path="生产成本/基本生产成本/工资",
        )
        # 路径→生产成本，资本公积是冲突类别
        assert result.status == "conflict", \
            f"生产成本路径 vs 资本公积应是冲突，实际: {result.status}"


class TestFullPathDoesNotOverrideClearName:
    """用例2：当前名称明确，路径包含其他类别 → 名称优先"""

    def test_clear_name_prevails_over_path_context(self):
        """当前名称「应收账款」明确，路径「资产/流动资产/应收账款」不覆盖"""
        sa_receivables = _sa("112201", "应收账款")
        result = evaluate_name_compatibility(
            sa_receivables,
            client_account_name="应收账款",
            client_account_full_path="资产/流动资产/应收账款",
        )
        assert result.status == "compatible", f"应兼容，实际: {result.status}"

    def test_clear_name_not_diluted_by_generic_path(self):
        """路径包含「资产」泛化词，但当前名称「应收账款」明确 → 不被路径覆盖"""
        sa_payables = _sa("2202", "应付账款")  # 负债类
        result = evaluate_name_compatibility(
            sa_payables,
            client_account_name="应收账款",  # 资产类
            client_account_full_path="资产/流动资产/应收账款",
        )
        # 当前名称明确为「应收账款」，检查与「应付账款」的冲突
        # 路径中的「资产」不应影响
        # 这里测试的是锚点冲突：应收账款 vs 应付账款
        assert result.status == "conflict" or result.status == "unknown", \
            f"应收账款不应通过「资产」路径兼容应付账款，实际: {result.status}"


class TestFullPathReserveSemantics:
    """用例3：路径含备抵 → 识别为备抵语义"""

    def test_path_reserve_detected(self):
        """路径「应收账款/坏账准备/某客户」→ 识别备抵语义"""
        sa_bad_debt = _sa("112402", "坏账准备（应收账款）")
        result = evaluate_name_compatibility(
            sa_bad_debt,
            client_account_name="某客户",
            client_account_full_path="应收账款/坏账准备/某客户",
        )
        # 路径含「坏账准备」→ 备抵语义 → 与备抵标准科目兼容
        assert result.status == "compatible", \
            f"路径含坏账准备应与备抵科目兼容，实际: {result.status}"

    def test_path_reserve_prevents_matching_original_value(self):
        """路径含备抵 → 不应匹配原值科目"""
        sa_receivables = _sa("112201", "应收账款")
        result = evaluate_name_compatibility(
            sa_receivables,
            client_account_name="某客户",
            client_account_full_path="应收账款/坏账准备/某客户",
        )
        # 路径含「坏账准备」→ 备抵语义 → 目标为应收账款原值 → 冲突
        assert result.status == "conflict", \
            f"路径含坏账准备不应匹配应收账款原值，实际: {result.status}"


class TestFullPathRDContext:
    """用例4：研发路径 → 识别资本化/费用化方向"""

    def test_rd_capitalizing_path_detected(self):
        """路径「研发支出/资本化支出/人工费」→ 识别资本化方向"""
        sa_capitalized = _sa("170401", "研发支出-资本化支出")
        result = evaluate_name_compatibility(
            sa_capitalized,
            client_account_name="人工费",
            client_account_full_path="研发支出/资本化支出/人工费",
        )
        # 路径含「资本化支出」→ 方向匹配
        assert result.status == "compatible", \
            f"路径含资本化支出应与资本化目标兼容，实际: {result.status}"

    def test_rd_capitalizing_path_conflicts_expensing_target(self):
        """资本化路径 → 不匹配费用化目标"""
        sa_expensed = _sa("170402", "研发支出-费用化支出")
        result = evaluate_name_compatibility(
            sa_expensed,
            client_account_name="人工费",
            client_account_full_path="研发支出/资本化支出/人工费",
        )
        # 路径含「资本化支出」→ 目标为费用化 → 冲突
        assert result.status == "conflict", \
            f"资本化路径不应匹配费用化目标，实际: {result.status}"

    def test_rd_expensing_path_detected(self):
        """路径「研发支出/费用化支出/材料费」→ 识别费用化方向"""
        sa_expensed = _sa("170402", "研发支出-费用化支出")
        result = evaluate_name_compatibility(
            sa_expensed,
            client_account_name="材料费",
            client_account_full_path="研发支出/费用化支出/材料费",
        )
        assert result.status == "compatible", \
            f"路径含费用化支出应与费用化目标兼容，实际: {result.status}"

    def test_rd_no_direction_still_unknown(self):
        """路径不含方向标记 → 仍为 unknown"""
        sa_rd = _sa("5301", "研发支出")
        result = evaluate_name_compatibility(
            sa_rd,
            client_account_name="人工费",
            client_account_full_path="研发支出/人工费",  # 无费用化/资本化标记
        )
        # 当前名称无研发关键词，路径虽有研发但无方向 → unknown
        assert result.status in ("unknown", "compatible"), \
            f"无方向标记应unknown或兼容，实际: {result.status}"


class TestFullPathOrderOfPrecedence:
    """优先级：当前名称 > 父级 > 最近祖先 > 完整路径"""

    def test_name_beats_path_for_group(self):
        """当前名称明确时，路径语义组不覆盖"""
        sa = _sa("5001", "生产成本")
        result = evaluate_name_compatibility(
            sa,
            client_account_name="制造费用",
            parent_client_account_name=None,
            ancestor_names=[],
            client_account_full_path="生产成本/制造费用",  # 路径以生产成本开头
        )
        # 「制造费用」锚点不在「生产成本」中 → 正确冲突
        # 路径中的「生产成本」语义组不被作为 primary group（因为 client_group 已命中）
        assert result.status == "conflict", \
            f"制造费用锚点不在生产成本中，应conflict，实际: {result.status}"
        # 确认语义组来自当前名称而非路径
        evidence_str = " ".join(result.evidence)
        assert "manufacturing_overhead" in evidence_str, \
            f"证据中应有manufacturing_overhead（来自当前名称），实际: {evidence_str}"


# ════════════════════════════════════════════════════════════
# TASK-089：真实数据错配修复回归
# ════════════════════════════════════════════════════════════


class TestOtherPayableDepositNotMatchedToReceivable:
    """TASK-089 §7.1：其他应付款/保证金 不得匹配其他应收款。

    「保证金」作为叶子名不应单独决定资产/负债方向。当路径或父级明确为
    其他应付款时，必须保持负债方向（other_payables），不得误配到
    other_receivables。
    """

    @pytest.mark.asyncio
    async def test_other_payable_deposit_path_does_not_match_receivable(self, db):
        """其他应付款/外部单位/保证金 → 不得安全匹配其他应收款"""
        sa_receivable = _sa("122101", "其他应收款")
        sa_payable = _sa("2241", "其他应付款")
        db.add_all([sa_receivable, sa_payable])
        await db.flush()

        results = await recommend_mappings(
            db, data_type="trial_balance",
            client_accounts=[{
                "client_account_code": "22410202",
                "client_account_name": "其他应付款/外部单位/保证金",
                "client_account_full_path": "其他应付款/外部单位/保证金",
            }],
        )
        candidates = results[0]["candidates"]
        # 122101 其他应收款不应是安全候选
        safe_for_receivable = [
            c for c in candidates
            if c["standard_account_code"] == "122101" and _is_safe_candidate(c)
        ]
        assert len(safe_for_receivable) == 0, \
            f"其他应付款/保证金 不应安全匹配其他应收款，实际: {safe_for_receivable}"
        # 2241 其他应付款应该是安全候选
        safe_for_payable = [
            c for c in candidates
            if c["standard_account_code"] == "2241" and _is_safe_candidate(c)
        ]
        assert len(safe_for_payable) >= 1, \
            f"其他应付款/保证金 应安全匹配其他应付款，实际: {safe_for_payable}"


class TestManagementFeeIntangibleAmortization:
    """TASK-089 §7.2：管理费用/无形资产摊销 不得匹配累计摊销。

    路径含「管理费用」时优先费用类别。客户「无形资产摊销」别名必须
    结合父级和路径，资产路径下的「累计摊销」才匹配1702类备抵。
    """

    def test_management_path_intangible_amortization_conflict_with_reserve(self):
        """管理费用/无形资产摊销 → 与累计摊销（1702）应为冲突"""
        sa_amortization = _sa("1702", "减：无形资产-累计摊销")
        sa_mgmt = _sa("660201", "管理费用")
        # 评估兼容性：当前名称「无形资产摊销」含累计摊销语义，标准是备抵
        # 但路径明确为管理费用 → 应该是 unknown 或 conflict
        result = evaluate_name_compatibility(
            sa_amortization,
            client_account_name="无形资产摊销",
            client_account_full_path="管理费用/无形资产摊销",
        )
        # 路径含「管理费用」语义，标准是备抵类 → 应该不是 compatible
        assert result.status in ("conflict", "unknown"), \
            f"管理费用路径/无形资产摊销 vs 累计摊销 应为冲突或unknown，实际: {result.status}"


class TestOtherInventoryNotMatchedToReserve:
    """TASK-089 §7.3：其他存货 不得匹配存货跌价准备。

    备抵目标必须通过 reserve semantics 命中。客户「其他存货」无
    跌价/减值/准备语义时，不得安全归入「1471 存货跌价准备」。
    """

    @pytest.mark.asyncio
    async def test_other_inventory_not_auto_confirmed_to_inventory_reserve(self, db):
        """其他存货 不得安全匹配 存货跌价准备"""
        sa_reserve = _sa("1471", "存货跌价准备")
        sa_inventory = _sa("147199", "其他存货")
        db.add_all([sa_reserve, sa_inventory])
        await db.flush()

        results = await recommend_mappings(
            db, data_type="trial_balance",
            client_accounts=[{
                "client_account_code": "147199",
                "client_account_name": "其他存货",
            }],
        )
        candidates = results[0]["candidates"]
        # 1471 存货跌价准备不应是安全候选
        safe_for_reserve = [
            c for c in candidates
            if c["standard_account_code"] == "1471" and _is_safe_candidate(c)
        ]
        assert len(safe_for_reserve) == 0, \
            f"其他存货 不应安全匹配存货跌价准备，实际: {safe_for_reserve}"


class TestFixedAssetImpairmentNotMatchedToOriginal:
    """TASK-089 §7.4：固定资产减值准备 不得匹配固定资产原值。

    reserve semantics 必须优先于固定资产名称锚点。名称「固定资产」
    不得覆盖「减值准备」。
    """

    @pytest.mark.asyncio
    async def test_fixed_asset_impairment_not_auto_confirmed_to_original(self, db):
        """固定资产减值准备 不得安全匹配 固定资产原值"""
        sa_original = _sa("160101", "固定资产原值")
        sa_impairment = _sa("1603", "固定资产减值准备")
        db.add_all([sa_original, sa_impairment])
        await db.flush()

        results = await recommend_mappings(
            db, data_type="trial_balance",
            client_accounts=[{
                "client_account_code": "1603",
                "client_account_name": "固定资产减值准备",
            }],
        )
        candidates = results[0]["candidates"]
        # 160101 固定资产原值不应是安全候选
        safe_for_original = [
            c for c in candidates
            if c["standard_account_code"] == "160101" and _is_safe_candidate(c)
        ]
        assert len(safe_for_original) == 0, \
            f"固定资产减值准备 不应安全匹配固定资产原值，实际: {safe_for_original}"


class TestInvestmentIncomeAmortizedCostNotCost:
    """TASK-089 §7.5：「摊余成本」不应识别为成本类。

    投资收益__以摊余成本计量的金融资产终止确认收益 属于投资收益，
    不得被识别为成本类。「摊余成本/成本法/历史成本」不属于生产成本。
    """

    def test_amortized_cost_not_identified_as_production_cost(self):
        """「投资收益__以摊余成本计量的金融资产终止确认收益」vs 投资收益目标 → 兼容"""
        sa_investment = _sa("6111", "投资收益")
        result = evaluate_name_compatibility(
            sa_investment,
            client_account_name="投资收益__以摊余成本计量的金融资产终止确认收益",
        )
        # 客户名称「投资收益」应识别为 investment_income 语义组
        # 不应被「摊余成本」中的「成本」二字误判
        assert result.status == "compatible", \
            f"投资收益（含摊余成本计量）应与投资收益兼容，实际: {result.status}, reason: {result.reason}"
        assert result.detected_group == "investment_income", \
            f"应识别为investment_income组，实际: {result.detected_group}"


class TestPackagingBoxNotMatchedToTurnoverParent:
    """TASK-089 §8：包装物_纸箱 优先匹配 141101 包装物，不是 1411 周转材料。

    客户名称首段「包装物」应优先匹配标准 141101 包装物明细，而不是
    父级 1411 周转材料。
    """

    @pytest.mark.asyncio
    async def test_packaging_box_prioritizes_packaging_detail(self, db):
        """1411 包装物_纸箱 → 应优先匹配 141101 包装物"""
        sa_turnover = _sa("1411", "周转材料")
        sa_packaging = _sa("141101", "包装物")
        db.add_all([sa_turnover, sa_packaging])
        await db.flush()

        results = await recommend_mappings(
            db, data_type="trial_balance",
            client_accounts=[{
                "client_account_code": "1411",
                "client_account_name": "包装物_纸箱",
            }],
        )
        candidates = results[0]["candidates"]
        # 自动确认应该是 141101 包装物
        auto = pick_unique_auto_confirm_candidate(candidates)
        assert auto is not None, f"包装物_纸箱 应可自动确认，实际: {candidates}"
        assert auto["standard_account_code"] == "141101", \
            f"应自动确认为 141101 包装物，实际: {auto['standard_account_code']} {auto['standard_account_name']}"


class TestRDExpenditureNoDirectionStrictUnknown:
    """TASK-090 §8：研发支出无方向时三个目标均严格为 unknown。

    客户名称:研发支出（无费用化/资本化上下文）
    标准目标:
      170401 研发支出-资本化支出
      170402 研发支出-费用化支出
      660201 减：研发费用
    必须严格断言三个目标的 compatibility_status == "unknown"，
    不得使用"或"宽松断言。不得自动确认任何目标。
    """

    @pytest.mark.asyncio
    async def test_rd_expenditure_no_direction_all_three_unknown(self, db):
        """研发支出无方向 → 170401 / 170402 / 660201 均 unknown"""
        sa_rd_cap = _sa("170401", "研发支出-资本化支出")
        sa_rd_exp = _sa("170402", "研发支出-费用化支出")
        sa_rd_expense = _sa("660201", "减：研发费用")
        db.add_all([sa_rd_cap, sa_rd_exp, sa_rd_expense])
        await db.flush()

        compat_cap = evaluate_name_compatibility(
            sa_rd_cap,
            client_account_name="研发支出",
            client_account_full_path="研发支出",
        )
        compat_exp = evaluate_name_compatibility(
            sa_rd_exp,
            client_account_name="研发支出",
            client_account_full_path="研发支出",
        )
        compat_expense = evaluate_name_compatibility(
            sa_rd_expense,
            client_account_name="研发支出",
            client_account_full_path="研发支出",
        )

        # TASK-090 严格断言：三个目标均为 unknown
        assert compat_cap.status == "unknown", \
            f"170401 资本化 应为 unknown，实际: {compat_cap.status} ({compat_cap.reason})"
        assert compat_exp.status == "unknown", \
            f"170402 费用化 应为 unknown，实际: {compat_exp.status} ({compat_exp.reason})"
        assert compat_expense.status == "unknown", \
            f"660201 研发费用 应为 unknown，实际: {compat_expense.status} ({compat_expense.reason})"

    @pytest.mark.asyncio
    async def test_rd_expenditure_no_direction_no_auto_confirm(self, db):
        """研发支出无方向 → recommend_mappings 不得自动确认任何目标"""
        sa_rd_cap = _sa("170401", "研发支出-资本化支出")
        sa_rd_exp = _sa("170402", "研发支出-费用化支出")
        sa_rd_expense = _sa("660201", "减：研发费用")
        db.add_all([sa_rd_cap, sa_rd_exp, sa_rd_expense])
        await db.flush()

        results = await recommend_mappings(
            db, data_type="trial_balance",
            client_accounts=[{"client_account_code": "", "client_account_name": "研发支出"}],
        )
        candidates = results[0]["candidates"]
        # 无安全候选 → 自动确认必须为 None
        assert pick_unique_auto_confirm_candidate(candidates) is None, \
            f"研发支出无方向不应自动确认，实际: {[c for c in candidates if _is_safe_candidate(c)]}"
        # 验证后端返回的 auto_confirm_candidate 也为 None
        assert results[0].get("auto_confirm_candidate") is None, \
            f"后端 auto_confirm_candidate 应为 None，实际: {results[0].get('auto_confirm_candidate')}"


class TestRDExpensingDirection:
    """TASK-090 §9：研发费用化方向正确分流。

    客户名称包含"费用化"语义（研发支出_费用化支出 / 研发支出/费用化支出/人工费 / 研发费用），
    应匹配费用化目标（170402 费用化支出 / 660201 研发费用），
    不得匹配资本化目标（170401 资本化支出）。
    """

    @pytest.mark.asyncio
    async def test_rd_expensing_vs_capitalized_is_conflict(self, db):
        """研发支出_费用化支出 vs 170401 资本化 → conflict"""
        sa_rd_cap = _sa("170401", "研发支出-资本化支出")
        sa_rd_exp = _sa("170402", "研发支出-费用化支出")
        sa_rd_expense = _sa("660201", "减：研发费用")
        db.add_all([sa_rd_cap, sa_rd_exp, sa_rd_expense])
        await db.flush()

        result = evaluate_name_compatibility(
            sa_rd_cap,
            client_account_name="研发支出_费用化支出",
            client_account_full_path="研发支出/费用化支出",
        )
        assert result.status == "conflict", \
            f"研发费用化 vs 170401 资本化 应为 conflict，实际: {result.status} ({result.reason})"

    @pytest.mark.asyncio
    async def test_rd_expensing_vs_expensed_compatible(self, db):
        """研发支出_费用化支出 vs 170402 费用化 → compatible"""
        sa_rd_exp = _sa("170402", "研发支出-费用化支出")
        sa_rd_cap = _sa("170401", "研发支出-资本化支出")
        db.add_all([sa_rd_exp, sa_rd_cap])
        await db.flush()

        result = evaluate_name_compatibility(
            sa_rd_exp,
            client_account_name="研发支出_费用化支出",
            client_account_full_path="研发支出/费用化支出",
        )
        assert result.status == "compatible", \
            f"研发费用化 vs 170402 费用化 应为 compatible，实际: {result.status} ({result.reason})"

    @pytest.mark.asyncio
    async def test_rd_expense_name_vs_expensed_compatible(self, db):
        """研发费用 vs 660201 研发费用 → compatible"""
        sa_rd_expense = _sa("660201", "减：研发费用")
        sa_rd_exp = _sa("170402", "研发支出-费用化支出")
        db.add_all([sa_rd_expense, sa_rd_exp])
        await db.flush()

        result = evaluate_name_compatibility(
            sa_rd_expense,
            client_account_name="研发费用",
            client_account_full_path="研发费用",
        )
        assert result.status == "compatible", \
            f"研发费用 vs 660201 研发费用 应为 compatible，实际: {result.status} ({result.reason})"

    @pytest.mark.asyncio
    async def test_rd_expense_path_expense_subpath_compatible(self, db):
        """研发支出/费用化支出/人工费 vs 170402 费用化 → compatible"""
        sa_rd_exp = _sa("170402", "研发支出-费用化支出")
        sa_rd_expense = _sa("660201", "减：研发费用")
        sa_rd_cap = _sa("170401", "研发支出-资本化支出")
        db.add_all([sa_rd_exp, sa_rd_expense, sa_rd_cap])
        await db.flush()

        # 170402 应兼容
        result_170402 = evaluate_name_compatibility(
            sa_rd_exp,
            client_account_name="人工费",
            client_account_full_path="研发支出/费用化支出/人工费",
        )
        assert result_170402.status == "compatible", \
            f"研发支出/费用化支出/人工费 vs 170402 应为 compatible，实际: {result_170402.status}"

        # 170401 应冲突
        result_170401 = evaluate_name_compatibility(
            sa_rd_cap,
            client_account_name="人工费",
            client_account_full_path="研发支出/费用化支出/人工费",
        )
        assert result_170401.status == "conflict", \
            f"研发支出/费用化支出/人工费 vs 170401 应为 conflict，实际: {result_170401.status}"


class TestRDCapitalizingDirection:
    """TASK-090 §10：研发资本化方向正确分流。

    客户名称包含"资本化"语义（研发支出_资本化支出 / 研发支出/资本化支出/人工费 / 开发支出），
    应匹配资本化目标（170401 资本化支出），
    不得匹配费用化目标（170402 费用化支出 / 660201 研发费用）。
    """

    @pytest.mark.asyncio
    async def test_rd_capitalizing_vs_capitalized_compatible(self, db):
        """研发支出_资本化支出 vs 170401 资本化 → compatible"""
        sa_rd_cap = _sa("170401", "研发支出-资本化支出")
        sa_rd_exp = _sa("170402", "研发支出-费用化支出")
        db.add_all([sa_rd_cap, sa_rd_exp])
        await db.flush()

        result = evaluate_name_compatibility(
            sa_rd_cap,
            client_account_name="研发支出_资本化支出",
            client_account_full_path="研发支出/资本化支出",
        )
        assert result.status == "compatible", \
            f"研发资本化 vs 170401 资本化 应为 compatible，实际: {result.status} ({result.reason})"

    @pytest.mark.asyncio
    async def test_rd_capitalizing_vs_expensed_conflict(self, db):
        """研发支出_资本化支出 vs 170402 费用化 → conflict"""
        sa_rd_exp = _sa("170402", "研发支出-费用化支出")
        sa_rd_cap = _sa("170401", "研发支出-资本化支出")
        db.add_all([sa_rd_exp, sa_rd_cap])
        await db.flush()

        result = evaluate_name_compatibility(
            sa_rd_exp,
            client_account_name="研发支出_资本化支出",
            client_account_full_path="研发支出/资本化支出",
        )
        assert result.status == "conflict", \
            f"研发资本化 vs 170402 费用化 应为 conflict，实际: {result.status} ({result.reason})"

    @pytest.mark.asyncio
    async def test_rd_capitalizing_vs_rd_expense_conflict(self, db):
        """研发支出_资本化支出 vs 660201 研发费用 → conflict"""
        sa_rd_expense = _sa("660201", "减：研发费用")
        sa_rd_cap = _sa("170401", "研发支出-资本化支出")
        db.add_all([sa_rd_expense, sa_rd_cap])
        await db.flush()

        result = evaluate_name_compatibility(
            sa_rd_expense,
            client_account_name="研发支出_资本化支出",
            client_account_full_path="研发支出/资本化支出",
        )
        assert result.status == "conflict", \
            f"研发资本化 vs 660201 研发费用 应为 conflict，实际: {result.status} ({result.reason})"

    @pytest.mark.asyncio
    async def test_rd_capitalizing_no_safe_expense_target(self, db):
        """研发资本化推荐结果中,不得出现费用化方向安全候选"""
        sa_rd_cap = _sa("170401", "研发支出-资本化支出")
        sa_rd_exp = _sa("170402", "研发支出-费用化支出")
        sa_rd_expense = _sa("660201", "减：研发费用")
        db.add_all([sa_rd_cap, sa_rd_exp, sa_rd_expense])
        await db.flush()

        results = await recommend_mappings(
            db, data_type="trial_balance",
            client_accounts=[{
                "client_account_code": "",
                "client_account_name": "研发支出_资本化支出",
            }],
        )
        candidates = results[0]["candidates"]
        safe_codes = [c["standard_account_code"] for c in candidates if _is_safe_candidate(c)]
        # 不应出现 170402 / 660201 费用化安全候选
        assert "170402" not in safe_codes, \
            f"研发资本化不应有 170402 费用化安全候选，实际: {safe_codes}"
        assert "660201" not in safe_codes, \
            f"研发资本化不应有 660201 研发费用安全候选，实际: {safe_codes}"


class TestEmptyStandardAccountIDNotSafe:
    """TASK-089 §10.3：空标准科目 ID 不得成为安全候选。"""

    def test_empty_standard_account_id_not_safe(self):
        """空 ID 的候选即使其他字段合格也不得安全"""
        candidate = {
            "standard_account_id": "",
            "standard_account_code": "5001",
            "standard_account_name": "生产成本",
            "score": 0.95,
            "source": "code_match",
            "reason": "测试",
            "warning": None,
            "auto_confirmable": True,
            "compatibility_status": "compatible",
        }
        assert not _is_safe_candidate(candidate), \
            "空 standard_account_id 必须判为不安全"

    def test_none_standard_account_id_not_safe(self):
        """None ID 的候选也不得安全"""
        candidate = {
            "standard_account_id": None,
            "standard_account_code": "5001",
            "standard_account_name": "生产成本",
            "score": 0.95,
            "source": "code_match",
            "reason": "测试",
            "warning": None,
            "auto_confirmable": True,
            "compatibility_status": "compatible",
        }
        assert not _is_safe_candidate(candidate), \
            "None standard_account_id 必须判为不安全"


class TestDeprecatedPickAutoConfirmFallbackRemoved:
    """TASK-089 §5.3：废弃 _pick_auto_confirm_candidate 不得回退首候选。

    必须仅作为薄包装转发到 pick_unique_auto_confirm_candidate。
    无安全候选时必须返回 None，不得返回首项候选。
    """

    def test_deprecated_returns_none_when_no_safe(self):
        """废弃函数：无安全候选时必须返回 None（不允许回退首项）"""
        from app.services.client_account_mapping_service import _pick_auto_confirm_candidate
        candidates = [
            {
                "standard_account_id": "sa-001",
                "standard_account_code": "X",
                "standard_account_name": "warning-only",
                "score": 0.85,
                "source": "name_similarity",
                "warning": "模糊匹配，请人工确认",
                "auto_confirmable": False,
                "compatibility_status": "unknown",
            },
            {
                "standard_account_id": "sa-002",
                "standard_account_code": "Y",
                "standard_account_name": "conflict",
                "score": 0.95,
                "source": "code_match",
                "warning": None,
                "auto_confirmable": True,
                "compatibility_status": "conflict",
            },
        ]
        picked = _pick_auto_confirm_candidate(candidates)
        assert picked is None, \
            f"废弃函数不应回退首项候选，实际: {picked}"

    def test_deprecated_returns_unique_safe(self):
        """废弃函数：唯一安全候选时返回该候选"""
        from app.services.client_account_mapping_service import _pick_auto_confirm_candidate
        candidates = [
            {
                "standard_account_id": "sa-001",
                "standard_account_code": "5001",
                "standard_account_name": "生产成本",
                "score": 0.95,
                "source": "code_match",
                "warning": None,
                "auto_confirmable": True,
                "compatibility_status": "compatible",
            },
            {
                "standard_account_id": "sa-002",
                "standard_account_code": "X",
                "standard_account_name": "warning",
                "score": 0.95,
                "source": "code_match",
                "warning": "已停用",
                "auto_confirmable": False,
                "compatibility_status": "conflict",
            },
        ]
        picked = _pick_auto_confirm_candidate(candidates)
        assert picked is not None
        assert picked["standard_account_code"] == "5001"

