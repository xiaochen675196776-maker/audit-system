"""客户科目映射经验服务测试 — TASK-043

覆盖：
1. 客户历史映射优先
2. 全局候选兜底
3. 停用标准科目只作为警告候选
4. 确认保存后下次推荐命中
5. 冲突映射需要确认覆盖
"""

import uuid
import pytest
from sqlalchemy import select

from app.models.standard_account import StandardAccount
from app.models.client_account_mapping import ClientAccountMapping
from app.services.client_account_mapping_service import (
    recommend_mappings,
    save_mapping,
)


# ── helpers ────────────────────────────────────────────

def _make_standard_account(account_code: str, account_name: str, **kwargs) -> StandardAccount:
    return StandardAccount(
        account_code=account_code,
        account_name=account_name,
        **kwargs,
    )


# ── 客户历史映射优先 ───────────────────────────────────

class TestCustomerHistoryPriority:
    """测试同一客户历史确认映射优先级最高"""

    @pytest.mark.asyncio
    async def test_company_history_takes_priority(self, db):
        """同一客户历史映射优先于全局候选和代码匹配"""
        # 创建标准科目
        sa1 = _make_standard_account("1001", "库存现金")
        sa2 = _make_standard_account("1002", "银行存款")
        db.add_all([sa1, sa2])
        await db.flush()

        # 创建同一客户历史映射（company scope）
        cam = ClientAccountMapping(
            data_type="trial_balance",
            customer_label="测试公司A",
            scope="company",
            client_account_code="CX001",
            client_account_name="现金",
            normalized_client_account_name="现金",
            standard_account_id=sa2.id,
            standard_account_code_snapshot="1002",
            standard_account_name_snapshot="银行存款",
            confidence=1.0,
            usage_count=5,
        )
        db.add(cam)
        await db.flush()

        # 创建全局映射（相同客户科目，但指向不同标准科目）
        cam_global = ClientAccountMapping(
            data_type="trial_balance",
            customer_label=None,
            scope="global",
            client_account_code="CX001",
            client_account_name="现金",
            normalized_client_account_name="现金",
            standard_account_id=sa1.id,
            standard_account_code_snapshot="1001",
            standard_account_name_snapshot="库存现金",
            confidence=0.8,
        )
        db.add(cam_global)
        await db.flush()

        # 推荐
        results = await recommend_mappings(
            db,
            data_type="trial_balance",
            customer_label="测试公司A",
            client_accounts=[
                {"client_account_code": "CX001", "client_account_name": "现金"},
            ],
        )

        assert len(results) == 1
        entry = results[0]
        candidates = entry["candidates"]
        assert len(candidates) >= 1

        # 第一候选应为 company_history 且指向 sa2
        first = candidates[0]
        assert first["source"] == "company_history"
        assert first["standard_account_id"] == str(sa2.id)
        assert first["standard_account_code"] == "1002"
        assert first["score"] == 1.0
        assert first["warning"] is None


# ── 全局候选兜底 ───────────────────────────────────────

class TestGlobalFallback:
    """测试全局映射经验兜底"""

    @pytest.mark.asyncio
    async def test_global_history_as_fallback(self, db):
        """无客户级历史时，全局历史映射作为候选"""
        sa = _make_standard_account("2001", "短期借款")
        db.add(sa)
        await db.flush()

        cam = ClientAccountMapping(
            data_type="trial_balance",
            customer_label=None,
            scope="global",
            client_account_code="CX002",
            client_account_name="短期借款",
            standard_account_id=sa.id,
            standard_account_code_snapshot="2001",
            standard_account_name_snapshot="短期借款",
            confidence=0.9,
            usage_count=3,
        )
        db.add(cam)
        await db.flush()

        results = await recommend_mappings(
            db,
            data_type="trial_balance",
            customer_label="测试公司B",
            client_accounts=[
                {"client_account_code": "CX002", "client_account_name": "短期借款"},
            ],
        )

        entry = results[0]
        candidates = entry["candidates"]
        assert len(candidates) >= 1

        # 应该有 global_history 候选
        global_candidates = [c for c in candidates if c["source"] == "global_history"]
        assert len(global_candidates) >= 1
        assert global_candidates[0]["standard_account_code"] == "2001"
        assert global_candidates[0]["score"] == 0.9

    @pytest.mark.asyncio
    async def test_code_match_fallback(self, db):
        """无历史映射时，标准科目代码精确匹配作为候选"""
        sa = _make_standard_account("4001", "主营业务收入")
        db.add(sa)
        await db.flush()

        results = await recommend_mappings(
            db,
            data_type="trial_balance",
            customer_label="新客户",
            client_accounts=[
                {"client_account_code": "4001", "client_account_name": "营业收入"},
            ],
        )

        entry = results[0]
        candidates = entry["candidates"]
        code_candidates = [c for c in candidates if c["source"] == "code_match"]
        assert len(code_candidates) >= 1
        assert code_candidates[0]["standard_account_code"] == "4001"
        assert code_candidates[0]["score"] == 0.95

    @pytest.mark.asyncio
    async def test_name_similarity_fallback(self, db):
        """名称相似度作为兜底候选"""
        sa = _make_standard_account("5001", "主营业务成本")
        db.add(sa)
        await db.flush()

        results = await recommend_mappings(
            db,
            data_type="trial_balance",
            customer_label="新客户",
            client_accounts=[
                {"client_account_code": "", "client_account_name": "主营业务成本"},
            ],
        )

        entry = results[0]
        candidates = entry["candidates"]
        name_candidates = [c for c in candidates if c["source"] == "name_similarity"]
        assert len(name_candidates) >= 1
        candidate = name_candidates[0]
        assert candidate["standard_account_code"] == "5001"
        assert candidate["score"] >= 0.7


# ── 停用标准科目只作为警告候选 ────────────────────────

class TestDisabledStandardAccount:
    """测试停用标准科目处理"""

    @pytest.mark.asyncio
    async def test_disabled_account_is_warning_only(self, db):
        """历史映射指向停用标准科目：不自动套用，返回警告"""
        sa = _make_standard_account("9001", "已废弃科目", is_active=False)
        db.add(sa)
        await db.flush()

        cam = ClientAccountMapping(
            data_type="trial_balance",
            customer_label="测试公司C",
            scope="company",
            client_account_code="CX003",
            client_account_name="废弃科目",
            standard_account_id=sa.id,
            standard_account_code_snapshot="9001",
            standard_account_name_snapshot="已废弃科目",
            confidence=1.0,
        )
        db.add(cam)
        await db.flush()

        results = await recommend_mappings(
            db,
            data_type="trial_balance",
            customer_label="测试公司C",
            client_accounts=[
                {"client_account_code": "CX003", "client_account_name": "废弃科目"},
            ],
        )

        entry = results[0]
        candidates = entry["candidates"]
        assert len(candidates) >= 1

        first = candidates[0]
        assert first["source"] == "company_history"
        assert first["warning"] is not None
        assert "停用" in first["warning"]
        assert first["standard_account_code"] == "9001"

    @pytest.mark.asyncio
    async def test_disabled_global_mapping_is_warning(self, db):
        """全局历史指向停用标准科目：也返回警告"""
        sa = _make_standard_account("9002", "另一个废弃科目", is_active=False)
        db.add(sa)
        await db.flush()

        cam = ClientAccountMapping(
            data_type="trial_balance",
            customer_label=None,
            scope="global",
            client_account_code="CX004",
            client_account_name="废弃科目2",
            standard_account_id=sa.id,
            standard_account_code_snapshot="9002",
            standard_account_name_snapshot="另一个废弃科目",
        )
        db.add(cam)
        await db.flush()

        results = await recommend_mappings(
            db,
            data_type="trial_balance",
            customer_label="任意公司",
            client_accounts=[
                {"client_account_code": "CX004", "client_account_name": "废弃科目2"},
            ],
        )

        entry = results[0]
        candidates = entry["candidates"]
        global_cands = [c for c in candidates if c["source"] == "global_history"]
        assert len(global_cands) >= 1
        assert global_cands[0]["warning"] is not None
        assert "停用" in global_cands[0]["warning"]


# ── 确认保存后下次推荐命中 ─────────────────────────────

class TestSaveThenRecommend:
    """测试保存后下次推荐能命中"""

    @pytest.mark.asyncio
    async def test_save_new_mapping_and_recommend(self, db):
        """确认保存新映射后，下次推荐能命中"""
        sa = _make_standard_account("6001", "管理费用")
        db.add(sa)
        await db.flush()

        # 保存
        result = await save_mapping(
            db=db,
            data_type="trial_balance",
            customer_label="测试公司D",
            client_account_code="CX010",
            client_account_name="管理费用",
            standard_account_id=sa.id,
            standard_account_code="6001",
            standard_account_name="管理费用",
            source="user_confirmed",
        )
        assert result["status"] == "created"
        assert result["mapping_id"] is not None

        # 推荐：应该命中
        recommendations = await recommend_mappings(
            db,
            data_type="trial_balance",
            customer_label="测试公司D",
            client_accounts=[
                {"client_account_code": "CX010", "client_account_name": "管理费用"},
            ],
        )

        entry = recommendations[0]
        candidates = entry["candidates"]
        company_cands = [c for c in candidates if c["source"] == "company_history"]
        assert len(company_cands) >= 1
        assert company_cands[0]["standard_account_code"] == "6001"
        assert company_cands[0]["score"] == 1.0

    @pytest.mark.asyncio
    async def test_save_updates_same_mapping(self, db):
        """相同映射再次保存：累加 usage_count"""
        sa = _make_standard_account("6002", "销售费用")
        db.add(sa)
        await db.flush()

        # 第一次保存
        r1 = await save_mapping(
            db=db,
            data_type="trial_balance",
            customer_label="测试公司E",
            client_account_code="CX020",
            client_account_name="销售费用",
            standard_account_id=sa.id,
            standard_account_code="6002",
            standard_account_name="销售费用",
        )
        assert r1["status"] == "created"

        # 第二次保存（相同）
        r2 = await save_mapping(
            db=db,
            data_type="trial_balance",
            customer_label="测试公司E",
            client_account_code="CX020",
            client_account_name="销售费用",
            standard_account_id=sa.id,
            standard_account_code="6002",
            standard_account_name="销售费用",
        )
        assert r2["status"] == "updated"
        assert r2["mapping_id"] == r1["mapping_id"]

        # 验证 usage_count 累加
        stmt = select(ClientAccountMapping).where(
            ClientAccountMapping.id == uuid.UUID(r1["mapping_id"])
        )
        result = await db.execute(stmt)
        cam = result.scalar_one()
        assert cam.usage_count >= 1
        assert cam.last_used_at is not None


# ── 冲突映射需要确认覆盖 ──────────────────────────────

class TestConflictMapping:
    """测试冲突映射处理"""

    @pytest.mark.asyncio
    async def test_conflict_without_allow_overwrite(self, db):
        """相同客户科目已有不同标准科目映射：不允许覆盖时返回冲突"""
        sa1 = _make_standard_account("7001", "财务费用")
        sa2 = _make_standard_account("7002", "利息费用")
        db.add_all([sa1, sa2])
        await db.flush()

        # 先保存到 sa1
        await save_mapping(
            db=db,
            data_type="trial_balance",
            customer_label="测试公司F",
            client_account_code="CX030",
            client_account_name="财务费用",
            standard_account_id=sa1.id,
            standard_account_code="7001",
            standard_account_name="财务费用",
        )

        # 尝试映射到 sa2，不允许覆盖
        result = await save_mapping(
            db=db,
            data_type="trial_balance",
            customer_label="测试公司F",
            client_account_code="CX030",
            client_account_name="财务费用",
            standard_account_id=sa2.id,
            standard_account_code="7002",
            standard_account_name="利息费用",
            allow_overwrite=False,
        )

        assert result["status"] == "conflict"
        assert result["conflict_detail"] is not None
        assert "7001" in result["conflict_detail"]["message"]
        assert result["conflict_detail"]["existing_standard_account_code"] == "7001"

        # 验证旧映射仍为 active
        stmt = select(ClientAccountMapping).where(
            ClientAccountMapping.client_account_code == "CX030",
            ClientAccountMapping.customer_label == "测试公司F",
            ClientAccountMapping.is_active == True,
        )
        res = await db.execute(stmt)
        active_mappings = res.scalars().all()
        assert len(active_mappings) == 1
        assert active_mappings[0].standard_account_code_snapshot == "7001"

    @pytest.mark.asyncio
    async def test_conflict_with_allow_overwrite(self, db):
        """允许覆盖时：停用旧映射，创建新映射"""
        sa1 = _make_standard_account("7101", "租金费用")
        sa2 = _make_standard_account("7102", "物业费用")
        db.add_all([sa1, sa2])
        await db.flush()

        # 保存到 sa1
        await save_mapping(
            db=db,
            data_type="trial_balance",
            customer_label="测试公司G",
            client_account_code="CX040",
            client_account_name="租金费用",
            standard_account_id=sa1.id,
            standard_account_code="7101",
            standard_account_name="租金费用",
        )

        # 覆盖到 sa2
        result = await save_mapping(
            db=db,
            data_type="trial_balance",
            customer_label="测试公司G",
            client_account_code="CX040",
            client_account_name="租金费用",
            standard_account_id=sa2.id,
            standard_account_code="7102",
            standard_account_name="物业费用",
            allow_overwrite=True,
        )

        assert result["status"] == "created"

        # 旧映射应被停用
        stmt_old = select(ClientAccountMapping).where(
            ClientAccountMapping.client_account_code == "CX040",
            ClientAccountMapping.customer_label == "测试公司G",
            ClientAccountMapping.is_active == False,
        )
        res_old = await db.execute(stmt_old)
        old_mappings = res_old.scalars().all()
        assert len(old_mappings) >= 1

        # 新映射为 active
        stmt_new = select(ClientAccountMapping).where(
            ClientAccountMapping.client_account_code == "CX040",
            ClientAccountMapping.customer_label == "测试公司G",
            ClientAccountMapping.is_active == True,
        )
        res_new = await db.execute(stmt_new)
        new_mappings = res_new.scalars().all()
        assert len(new_mappings) == 1
        assert new_mappings[0].standard_account_code_snapshot == "7102"


# ── 边界情况 ──────────────────────────────────────────

class TestEdgeCases:
    """边界情况测试"""

    @pytest.mark.asyncio
    async def test_empty_client_accounts(self, db):
        """空科目列表"""
        results = await recommend_mappings(
            db,
            data_type="trial_balance",
            client_accounts=[],
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_no_code_no_name(self, db):
        """无代码无名称的科目"""
        results = await recommend_mappings(
            db,
            data_type="trial_balance",
            client_accounts=[
                {"client_account_code": "", "client_account_name": ""},
            ],
        )
        entry = results[0]
        assert entry["candidates"] == []

    @pytest.mark.asyncio
    async def test_multiple_client_accounts(self, db):
        """多个客户科目同时推荐"""
        sa1 = _make_standard_account("1001", "库存现金")
        sa2 = _make_standard_account("1002", "银行存款")
        db.add_all([sa1, sa2])
        await db.flush()

        results = await recommend_mappings(
            db,
            data_type="trial_balance",
            client_accounts=[
                {"client_account_code": "1001", "client_account_name": "库存现金"},
                {"client_account_code": "1002", "client_account_name": "银行存款"},
            ],
        )

        assert len(results) == 2
        for entry in results:
            candidates = entry["candidates"]
            code_cands = [c for c in candidates if c["source"] == "code_match"]
            assert len(code_cands) >= 1

    @pytest.mark.asyncio
    async def test_global_scope_without_customer_label(self, db):
        """不传 customer_label 时只查全局经验"""
        sa = _make_standard_account("8001", "营业外收入")
        db.add(sa)
        await db.flush()

        # 全局经验
        cam_global = ClientAccountMapping(
            data_type="trial_balance",
            scope="global",
            client_account_code="CX050",
            client_account_name="营业外收入",
            standard_account_id=sa.id,
            standard_account_code_snapshot="8001",
            standard_account_name_snapshot="营业外收入",
        )
        # 公司私有经验（另一个公司）
        cam_private = ClientAccountMapping(
            data_type="trial_balance",
            customer_label="其他公司",
            scope="company",
            client_account_code="CX050",
            client_account_name="营业外收入",
            standard_account_id=sa.id,
            standard_account_code_snapshot="8001",
            standard_account_name_snapshot="营业外收入",
        )
        db.add_all([cam_global, cam_private])
        await db.flush()

        results = await recommend_mappings(
            db,
            data_type="trial_balance",
            customer_label=None,  # 不传客户
            client_accounts=[
                {"client_account_code": "CX050", "client_account_name": "营业外收入"},
            ],
        )

        entry = results[0]
        candidates = entry["candidates"]
        # 不应该有 company_history
        company_cands = [c for c in candidates if c["source"] == "company_history"]
        assert len(company_cands) == 0

        # 应该有 global_history
        global_cands = [c for c in candidates if c["source"] == "global_history"]
        assert len(global_cands) >= 1

    @pytest.mark.asyncio
    async def test_save_without_code_uses_name_only(self, db):
        """无代码只有名称时也允许保存"""
        sa = _make_standard_account("8101", "其他收益")
        db.add(sa)
        await db.flush()

        result = await save_mapping(
            db=db,
            data_type="trial_balance",
            customer_label="测试公司H",
            client_account_code=None,
            client_account_name="其他收益",
            standard_account_id=sa.id,
            standard_account_code="8101",
            standard_account_name="其他收益",
        )
        assert result["status"] == "created"

    @pytest.mark.asyncio
    async def test_recommend_priority_order(self, db):
        """验证推荐按优先级排序：company_history > global_history > code_match > name_similarity"""
        sa1 = _make_standard_account("1005", "标准科目一")
        sa2 = _make_standard_account("CX100", "标准科目二")
        sa3 = _make_standard_account("CX101", "标准科目三")
        db.add_all([sa1, sa2, sa3])
        await db.flush()

        # 全局历史
        cam_global = ClientAccountMapping(
            data_type="trial_balance",
            scope="global",
            client_account_code="CX100",
            client_account_name="科目X",
            standard_account_id=sa2.id,
            standard_account_code_snapshot="CX100",
            standard_account_name_snapshot="标准科目二",
        )
        db.add(cam_global)
        await db.flush()

        results = await recommend_mappings(
            db,
            data_type="trial_balance",
            customer_label="测试公司Z",
            client_accounts=[
                {"client_account_code": "CX100", "client_account_name": "科目X"},
            ],
        )

        entry = results[0]
        candidates = entry["candidates"]
        sources_in_order = [c["source"] for c in candidates]
        # global_history 应排在 code_match 前面
        if "global_history" in sources_in_order and "code_match" in sources_in_order:
            gh_idx = sources_in_order.index("global_history")
            cm_idx = sources_in_order.index("code_match")
            assert gh_idx < cm_idx, f"Expected global_history before code_match, got {sources_in_order}"
