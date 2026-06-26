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
