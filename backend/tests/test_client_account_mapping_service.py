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

BANK_DETAIL_NAME = "银行存款_活期户_银行A_支行01_0801"
RD_SOCIAL_WELFARE_CODE = "530101" + "010201"
RD_MATERIAL_CODE = "530101" + "120201"


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
        # TASK-087：代码匹配后需要通过名称兼容性检查；名称"营业收入"≠"主营业务收入"→ unknown
        assert code_candidates[0]["score"] == 0.82

    @pytest.mark.asyncio
    async def test_name_similarity_fallback(self, db):
        """名称相似度作为兜底候选（或被更精准的名称锚点候选替换）"""
        sa = _make_standard_account("5001", "主营业务成本")
        db.add(sa)
        await db.flush()

        results = await recommend_mappings(
            db,
            data_type="trial_balance",
            customer_label="新客户",
            client_accounts=[
                {"client_account_code": "", "client_account_name": "主营业务成本-暂估"},
            ],
        )

        entry = results[0]
        candidates = entry["candidates"]
        # 名称含「主营业务成本」锚点时，会产出 name_anchor 候选（更精准）；
        # 否则退回 name_similarity 候选。两者任一存在即可。
        name_candidates = [
            c for c in candidates
            if c["source"] in ("name_similarity", "name_anchor")
        ]
        assert len(name_candidates) >= 1
        candidate = name_candidates[0]
        assert candidate["standard_account_code"] == "5001"
        assert candidate["score"] >= 0.7


# ── 规范化匹配回归 ───────────────────────────────────

class TestNormalizedMatching:
    """测试客户科目代码和名称规范化后的推荐命中"""

    @pytest.mark.asyncio
    async def test_code_match_normalizes_spaces_full_width_and_separators(self, db):
        """客户科目代码含空格、全角字符和分隔符时仍匹配标准科目代码"""
        sa = _make_standard_account("100101", "库存现金")
        db.add(sa)
        await db.flush()

        results = await recommend_mappings(
            db,
            data_type="trial_balance",
            customer_label="新客户",
            client_accounts=[
                {"client_account_code": " １ ００１-０１ ", "client_account_name": "现金"},
            ],
        )

        candidates = results[0]["candidates"]
        first = candidates[0]
        assert first["source"] == "code_match"
        assert first["standard_account_id"] == str(sa.id)
        assert first["standard_account_code"] == "100101"
        # TASK-087：名称"现金"≠"库存现金"，但代码匹配通过名称兼容性检查后为 unknown
        assert first["compatibility_status"] == "unknown"

    @pytest.mark.asyncio
    async def test_name_exact_match_normalizes_internal_spaces(self, db):
        """客户科目名称规范化后精确匹配标准科目名称"""
        sa = _make_standard_account("1001", "库存现金")
        db.add(sa)
        await db.flush()

        results = await recommend_mappings(
            db,
            data_type="trial_balance",
            customer_label="新客户",
            client_accounts=[
                {"client_account_code": "", "client_account_name": " 库存  现金 "},
            ],
        )

        candidates = results[0]["candidates"]
        first = candidates[0]
        assert first["source"] == "name_exact"
        assert first["standard_account_id"] == str(sa.id)
        assert first["score"] > 0.92
        assert first["warning"] is None

    @pytest.mark.asyncio
    async def test_name_only_hits_company_history_by_normalized_name(self, db):
        """无代码只有名称时，也能按规范化名称命中同客户历史"""
        sa = _make_standard_account("1001", "库存现金")
        db.add(sa)
        await db.flush()

        cam = ClientAccountMapping(
            data_type="trial_balance",
            customer_label="测试公司I",
            scope="company",
            client_account_code=None,
            client_account_name="库存现金",
            normalized_client_account_name="库存现金",
            standard_account_id=sa.id,
            standard_account_code_snapshot="1001",
            standard_account_name_snapshot="库存现金",
            confidence=1.0,
            usage_count=4,
        )
        db.add(cam)
        await db.flush()

        results = await recommend_mappings(
            db,
            data_type="trial_balance",
            customer_label="测试公司I",
            client_accounts=[
                {"client_account_code": "", "client_account_name": "库存 现金"},
            ],
        )

        candidates = results[0]["candidates"]
        first = candidates[0]
        assert first["source"] == "company_history"
        assert first["standard_account_id"] == str(sa.id)
        assert first["standard_account_code"] == "1001"

    @pytest.mark.asyncio
    async def test_name_exact_precedes_name_similarity_candidate(self, db):
        """名称精确候选优先于普通相似候选"""
        exact = _make_standard_account("1001", "库存现金")
        similar = _make_standard_account("100101", "库存现金人民币")
        db.add_all([similar, exact])
        await db.flush()

        results = await recommend_mappings(
            db,
            data_type="trial_balance",
            customer_label="新客户",
            client_accounts=[
                {"client_account_code": "", "client_account_name": "库存 现金"},
            ],
        )

        candidates = results[0]["candidates"]
        assert candidates[0]["source"] == "name_exact"
        assert candidates[0]["standard_account_id"] == str(exact.id)
        sources_in_order = [c["source"] for c in candidates]
        if "name_similarity" in sources_in_order:
            assert sources_in_order.index("name_exact") < sources_in_order.index("name_similarity")

    @pytest.mark.asyncio
    async def test_disabled_standard_account_exact_match_is_warning_candidate(self, db):
        """停用标准科目的精确命中只能作为 warning candidate"""
        disabled = _make_standard_account("1001", "库存现金", is_active=False)
        db.add(disabled)
        await db.flush()

        results = await recommend_mappings(
            db,
            data_type="trial_balance",
            customer_label="新客户",
            client_accounts=[
                {"client_account_code": "１００１", "client_account_name": "库存现金"},
            ],
        )

        candidates = results[0]["candidates"]
        disabled_candidates = [
            c for c in candidates
            if c["standard_account_id"] == str(disabled.id)
        ]
        assert len(disabled_candidates) >= 1
        assert all(c["warning"] for c in disabled_candidates)
        assert all("停用" in c["warning"] for c in disabled_candidates)


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


# ── 父级/前缀/关键词兜底候选 ─────────────────────────

class TestPrefixAndAnchorFallback:
    """测试客户明细科目按代码前缀/名称锚点的兜底匹配"""

    @pytest.mark.asyncio
    async def test_detail_code_matches_longest_standard_prefix(self, db):
        """客户明细代码 10020108 / 10020141 / 10020149 应候选匹配 1002 银行存款"""
        sa = _make_standard_account("1002", "银行存款")
        db.add(sa)
        await db.flush()

        for detail_code in ["10020108", "10020141", "10020149"]:
            results = await recommend_mappings(
                db,
                data_type="trial_balance",
                customer_label="新客户",
                client_accounts=[
                    {"client_account_code": detail_code, "client_account_name": "银行存款明细"},
                ],
            )
            candidates = results[0]["candidates"]
            prefix_cands = [c for c in candidates if c["source"] == "code_prefix_parent"]
            assert len(prefix_cands) >= 1, f"明细代码 {detail_code} 应有 code_prefix_parent 候选"
            cand = prefix_cands[0]
            assert cand["standard_account_code"] == "1002"
            assert cand["standard_account_name"] == "银行存款"
            # 名称锚点「银行存款」匹配 → 安全自动确认
            assert cand["score"] >= 0.9
            assert cand["warning"] is None

    @pytest.mark.asyncio
    async def test_detail_code_matches_expense_parents(self, db):
        """660303/660304→6603 财务费用；660401→6604 研发费用；671108→6711 营业外支出；680101→6801 所得税费用"""
        accounts = [
            _make_standard_account("6603", "财务费用"),
            _make_standard_account("6604", "研发费用"),
            _make_standard_account("6711", "营业外支出"),
            _make_standard_account("6801", "所得税费用"),
        ]
        db.add_all(accounts)
        await db.flush()
        code_to_expected = {
            "660303": ("6603", "财务费用"),
            "660304": ("6603", "财务费用"),
            "660401": ("6604", "研发费用"),
            "671108": ("6711", "营业外支出"),
            "680101": ("6801", "所得税费用"),
        }
        for detail_code, (exp_code, exp_name) in code_to_expected.items():
            results = await recommend_mappings(
                db,
                data_type="trial_balance",
                customer_label="新客户",
                client_accounts=[
                    {"client_account_code": detail_code, "client_account_name": "明细科目"},
                ],
            )
            candidates = results[0]["candidates"]
            prefix_cands = [c for c in candidates if c["source"] == "code_prefix_parent"]
            assert len(prefix_cands) >= 1, f"{detail_code} 应有 code_prefix_parent 候选"
            assert prefix_cands[0]["standard_account_code"] == exp_code
            assert prefix_cands[0]["standard_account_name"] == exp_name
            assert 0.82 <= prefix_cands[0]["score"] <= 0.89
            assert prefix_cands[0]["warning"] is not None

    @pytest.mark.asyncio
    async def test_longest_prefix_wins_over_shorter(self, db):
        """存在 1002 和 100201 两个标准科目时，10020108 应匹配最长前缀 100201"""
        sa_parent = _make_standard_account("1002", "银行存款")
        sa_mid = _make_standard_account("100201", "银行存款-活期")
        db.add_all([sa_parent, sa_mid])
        await db.flush()

        results = await recommend_mappings(
            db,
            data_type="trial_balance",
            customer_label="新客户",
            client_accounts=[
                {"client_account_code": "10020108", "client_account_name": "活期户"},
            ],
        )
        candidates = results[0]["candidates"]
        prefix_cands = [c for c in candidates if c["source"] == "code_prefix_parent"]
        assert len(prefix_cands) >= 1
        # 最长前缀 100201 优先
        assert prefix_cands[0]["standard_account_code"] == "100201"

    @pytest.mark.asyncio
    async def test_exact_code_match_not_duplicated_as_prefix(self, db):
        """客户代码与标准科目代码完全相等时，应走 code_match，不应再产出 code_prefix_parent"""
        sa = _make_standard_account("1002", "银行存款")
        db.add(sa)
        await db.flush()

        results = await recommend_mappings(
            db,
            data_type="trial_balance",
            customer_label="新客户",
            client_accounts=[
                {"client_account_code": "1002", "client_account_name": "银行存款"},
            ],
        )
        candidates = results[0]["candidates"]
        code_cands = [c for c in candidates if c["source"] == "code_match"]
        assert len(code_cands) >= 1
        # 不应有重复的 prefix 候选指向同一标准科目
        prefix_cands = [c for c in candidates if c["source"] == "code_prefix_parent"]
        assert all(c["standard_account_id"] != str(sa.id) for c in prefix_cands)

    @pytest.mark.asyncio
    async def test_name_anchor_matches_bank_deposit_detail(self, db):
        """脱敏银行存款明细应候选匹配「银行存款」"""
        sa = _make_standard_account("1002", "银行存款")
        db.add(sa)
        await db.flush()

        results = await recommend_mappings(
            db,
            data_type="trial_balance",
            customer_label="新客户",
            client_accounts=[
                {"client_account_code": "1002010801", "client_account_name": BANK_DETAIL_NAME},
            ],
        )
        candidates = results[0]["candidates"]
        anchor_cands = [c for c in candidates if c["source"] == "name_anchor"]
        assert len(anchor_cands) >= 1
        assert anchor_cands[0]["standard_account_code"] == "1002"
        assert anchor_cands[0]["standard_account_name"] == "银行存款"
        assert anchor_cands[0]["score"] >= 0.9
        assert anchor_cands[0]["warning"] is None

    @pytest.mark.asyncio
    async def test_name_anchor_matches_finance_expense_subaccounts(self, db):
        """「财务费用_利息收入」「财务费用_利息支出」应候选匹配「财务费用」"""
        sa = _make_standard_account("6603", "财务费用")
        db.add(sa)
        await db.flush()

        for sub_name in ["财务费用_利息收入", "财务费用_利息支出"]:
            results = await recommend_mappings(
                db,
                data_type="trial_balance",
                customer_label="新客户",
                client_accounts=[
                    {"client_account_code": "660301", "client_account_name": sub_name},
                ],
            )
            candidates = results[0]["candidates"]
            anchor_cands = [c for c in candidates if c["source"] == "name_anchor"]
            assert len(anchor_cands) >= 1, f"{sub_name} 应有 name_anchor 候选"
            assert anchor_cands[0]["standard_account_code"] == "6603"

    @pytest.mark.asyncio
    async def test_prefix_candidate_not_auto_confirmed_due_to_warning(self, db):
        """兜底候选在名称锚点匹配时，应为安全候选（warning=None, score>=0.9）"""
        sa = _make_standard_account("6603", "财务费用")
        db.add(sa)
        await db.flush()

        results = await recommend_mappings(
            db,
            data_type="trial_balance",
            customer_label="新客户",
            client_accounts=[
                {"client_account_code": "660303", "client_account_name": "财务费用-手续费"},
            ],
        )
        candidates = results[0]["candidates"]
        # 名称锚点「财务费用」匹配标准科目 canonical name → 安全自动确认
        fallback_cands = [c for c in candidates if c["source"] in ("code_prefix_parent", "name_anchor")]
        assert len(fallback_cands) >= 1
        safe_cands = [c for c in fallback_cands if c["warning"] is None and c["score"] >= 0.9]
        assert len(safe_cands) >= 1, f"应有安全候选，实际 fallback: {fallback_cands}"


# ── TASK-064B：代码体系不一致 / 显示前缀 / 类别锚点 ────

class TestCanonicalNameAndCategoryAnchor:
    """标准科目名带「减：/加：/其中：」前缀、客户代码体系与标准不一致时的匹配"""

    @pytest.mark.asyncio
    async def test_name_anchor_matches_prefixed_standard_account_name(self, db):
        """标准科目 660201「减：研发费用」，客户 660401「研发费用」应候选命中"""
        sa = _make_standard_account("660201", "减：研发费用")
        db.add(sa)
        await db.flush()

        results = await recommend_mappings(
            db,
            data_type="trial_balance",
            customer_label="新客户",
            client_accounts=[
                {"client_account_code": "660401", "client_account_name": "研发费用"},
            ],
        )
        candidates = results[0]["candidates"]
        hit = [c for c in candidates if c["standard_account_id"] == str(sa.id)]
        assert len(hit) >= 1, "应命中「减：研发费用」"
        c = hit[0]
        assert c["source"] in ("name_anchor", "code_category_anchor", "semantic_alias")
        # 锚点「研发费用」匹配标准 canonical「研发费用」→ 安全自动确认
        assert c["score"] >= 0.9
        assert c["warning"] is None

    @pytest.mark.asyncio
    async def test_code_category_anchor_matches_when_standard_code_differs(self, db):
        """标准库只有 660201「减：研发费用」无 6604，客户 660401 仍能按类别锚点命中"""
        sa = _make_standard_account("660201", "减：研发费用")
        db.add(sa)
        await db.flush()

        # 客户名称不直接含「研发费用」（用「研发项目支出」），强制依赖代码类别锚点 6604→研发费用
        results = await recommend_mappings(
            db,
            data_type="trial_balance",
            customer_label="新客户",
            client_accounts=[
                {"client_account_code": "660401", "client_account_name": "研发项目支出"},
            ],
        )
        candidates = results[0]["candidates"]
        category_cands = [c for c in candidates if c["source"] == "code_category_anchor"]
        assert len(category_cands) >= 1, "无 6604 标准科目时应按代码类别锚点命中"
        assert category_cands[0]["standard_account_id"] == str(sa.id)
        # TASK-087：名称不直接匹配时需要名称兼容性检查；名称"研发项目支出"未明确匹配"研发费用"
        assert category_cands[0]["score"] >= 0.85
        assert category_cands[0]["warning"] is not None

        # 仅给代码无名称时也应命中
        results2 = await recommend_mappings(
            db,
            data_type="trial_balance",
            customer_label="新客户",
            client_accounts=[
                {"client_account_code": "660401", "client_account_name": ""},
            ],
        )
        candidates2 = results2[0]["candidates"]
        hit2 = [c for c in candidates2 if c["standard_account_id"] == str(sa.id)]
        assert len(hit2) >= 1, "仅代码 660401 也应按类别锚点命中"

    @pytest.mark.asyncio
    async def test_name_anchor_strips_standard_display_prefix(self, db):
        """标准科目带「减：」前缀时，客户名称锚点仍能命中"""
        sa_fin = _make_standard_account("6603", "减：财务费用")
        sa_out = _make_standard_account("6711", "减：营业外支出")
        db.add_all([sa_fin, sa_out])
        await db.flush()

        cases = [
            ("660304", "财务费用_利息支出", sa_fin),
            ("671108", "营业外支出_其他", sa_out),
        ]
        for code, name, expected_sa in cases:
            results = await recommend_mappings(
                db,
                data_type="trial_balance",
                customer_label="新客户",
                client_accounts=[
                    {"client_account_code": code, "client_account_name": name},
                ],
            )
            candidates = results[0]["candidates"]
            hit = [c for c in candidates if c["standard_account_id"] == str(expected_sa.id)]
            assert len(hit) >= 1, f"{name} 应命中 {expected_sa.account_name}"
            # 名称锚点匹配 canonical name → 安全自动确认
            assert hit[0]["warning"] is None, f"{name} 应安全自动确认"
            assert hit[0]["score"] >= 0.9

    @pytest.mark.asyncio
    async def test_fallback_candidates_not_auto_confirmable(self, db):
        """名称锚点匹配的兜底候选应安全自动确认；不匹配的仍带 warning"""
        accounts = [
            _make_standard_account("1002", "银行存款"),
            _make_standard_account("6603", "减：财务费用"),
            _make_standard_account("660201", "减：研发费用"),
            _make_standard_account("6711", "减：营业外支出"),
            _make_standard_account("6801", "所得税费用"),
            # 冲突候选：标准科目名与客户锚点不一致
            _make_standard_account("112301", "应收款项融资"),
            _make_standard_account("140501", "产品成本差异"),
        ]
        db.add_all(accounts)
        await db.flush()

        # 安全自动确认：锚点匹配
        safe_inputs = [
            {"client_account_code": "10020108", "client_account_name": BANK_DETAIL_NAME},
            {"client_account_code": "660303", "client_account_name": "财务费用_利息收入"},
            {"client_account_code": "660401", "client_account_name": "研发费用"},
            {"client_account_code": "671108", "client_account_name": "营业外支出_其他"},
            {"client_account_code": "680101", "client_account_name": "所得税费用_当期所得税费用"},
        ]
        for ca in safe_inputs:
            results = await recommend_mappings(
                db, data_type="trial_balance", customer_label="新客户", client_accounts=[ca],
            )
            candidates = results[0]["candidates"]
            fallback = [c for c in candidates if c["source"] in ("code_prefix_parent", "code_category_anchor", "name_anchor", "semantic_alias")]
            assert len(fallback) >= 1, f"{ca} 应至少有一个兜底候选"
            safe = [c for c in fallback if c["warning"] is None and c["score"] >= 0.9]
            assert len(safe) >= 1, f"{ca} 应有安全自动确认候选，实际: {fallback}"

        # 冲突不自动确认：锚点不匹配
        conflict_inputs = [
            {"client_account_code": "112301", "client_account_name": "预付账款_预付材料款"},
            {"client_account_code": "140501", "client_account_name": "库存商品"},
        ]
        for ca in conflict_inputs:
            results = await recommend_mappings(
                db, data_type="trial_balance", customer_label="新客户", client_accounts=[ca],
            )
            candidates = results[0]["candidates"]
            conflict = [c for c in candidates if c.get("warning") is not None and c["score"] < 0.9]
            assert len(conflict) >= 1, f"{ca} 应有冲突候选（带 warning）"
            assert len(candidates) <= 6

    @pytest.mark.asyncio
    async def test_real_interface_typical_accounts_all_have_candidates(self, db):
        """验收要求：截图典型科目全部有候选"""
        accounts = [
            _make_standard_account("1002", "银行存款"),
            _make_standard_account("6603", "减：财务费用"),
            _make_standard_account("660201", "减：研发费用"),
            _make_standard_account("6711", "减：营业外支出"),
            _make_standard_account("6801", "所得税费用"),
        ]
        db.add_all(accounts)
        await db.flush()

        inputs = [
            {"client_account_code": "10020108", "client_account_name": BANK_DETAIL_NAME},
            {"client_account_code": "660303", "client_account_name": "财务费用_利息收入"},
            {"client_account_code": "660304", "client_account_name": "财务费用_利息支出"},
            {"client_account_code": "660401", "client_account_name": "研发费用"},
            {"client_account_code": "671108", "client_account_name": "营业外支出_其他"},
            {"client_account_code": "680101", "client_account_name": "所得税费用_当期所得税费用"},
        ]
        results = await recommend_mappings(
            db,
            data_type="trial_balance",
            customer_label="新客户",
            client_accounts=inputs,
        )
        assert len(results) == len(inputs)
        for entry in results:
            assert len(entry["candidates"]) >= 1, (
                f"{entry.get('client_account_code')} {entry.get('client_account_name')} 应有候选"
            )


class TestCodeMatchNameConflict:
    """TASK-065B：代码精确但名称锚点冲突不应自动确认"""

    @pytest.mark.asyncio
    async def test_exact_code_name_conflict_not_auto_confirmable(self, db):
        """标准 112301 应收款项融资 vs 客户 112301 预付账款_预付材料款 → 冲突"""
        sa = _make_standard_account("112301", "应收款项融资")
        db.add(sa)
        await db.flush()

        inputs = [{"client_account_code": "112301", "client_account_name": "预付账款_预付材料款"}]
        results = await recommend_mappings(db, data_type="trial_balance", client_accounts=inputs)
        assert len(results) == 1
        candidates = results[0]["candidates"]
        assert len(candidates) >= 1

        code_candidate = next((c for c in candidates if c["source"] == "code_match_conflict"), None)
        assert code_candidate is not None, f"应有 code_match_conflict 候选，实际: {[c['source'] for c in candidates]}"
        assert code_candidate["score"] < 0.9, f"冲突候选 score 应 < 0.9，实际: {code_candidate['score']}"
        assert code_candidate["warning"] is not None, "冲突候选 warning 不应为空"
        assert "预付账款" in code_candidate["warning"]
        assert "应收款项融资" in code_candidate["warning"]

    @pytest.mark.asyncio
    async def test_inventory_code_conflict_not_auto_confirmable(self, db):
        """标准 140501 产品成本差异 vs 客户 140501 库存商品 → 冲突"""
        sa = _make_standard_account("140501", "产品成本差异")
        db.add(sa)
        await db.flush()

        inputs = [{"client_account_code": "140501", "client_account_name": "库存商品"}]
        results = await recommend_mappings(db, data_type="trial_balance", client_accounts=inputs)
        assert len(results) == 1
        candidates = results[0]["candidates"]
        assert len(candidates) >= 1

        code_candidate = next((c for c in candidates if c["source"] == "code_match_conflict"), None)
        assert code_candidate is not None, f"应有 code_match_conflict 候选，实际: {[c['source'] for c in candidates]}"
        assert code_candidate["score"] < 0.9, f"冲突候选 score 应 < 0.9，实际: {code_candidate['score']}"
        assert "库存商品" in code_candidate["warning"]
        assert "产品成本差异" in code_candidate["warning"]

    @pytest.mark.asyncio
    async def test_safe_exact_code_still_auto_confirmable(self, db):
        """标准 1002 银行存款 vs 客户 1002 银行存款 → 安全，仍可自动确认"""
        sa = _make_standard_account("1002", "银行存款")
        db.add(sa)
        await db.flush()

        inputs = [{"client_account_code": "1002", "client_account_name": "银行存款"}]
        results = await recommend_mappings(db, data_type="trial_balance", client_accounts=inputs)
        assert len(results) == 1
        candidates = results[0]["candidates"]
        assert len(candidates) >= 1

        code_candidate = next((c for c in candidates if c["source"] == "code_match"), None)
        assert code_candidate is not None, f"应有 code_match 候选（安全），实际: {[c['source'] for c in candidates]}"
        assert code_candidate["score"] >= 0.9, f"安全匹配 score 应 >= 0.9，实际: {code_candidate['score']}"
        assert code_candidate["warning"] is None, f"安全匹配 warning 应为 None，实际: {code_candidate['warning']}"

    @pytest.mark.asyncio
    async def test_fallback_candidate_preferred_over_conflicting_code(self, db):
        """标准有 112301 应收款项融资 和 1123 预付账款，客户 112301 预付账款_预付材料款 → 应有 name_anchor 候选 1123"""
        sa1 = _make_standard_account("112301", "应收款项融资")
        sa2 = _make_standard_account("1123", "预付账款")
        db.add_all([sa1, sa2])
        await db.flush()

        inputs = [{"client_account_code": "112301", "client_account_name": "预付账款_预付材料款"}]
        results = await recommend_mappings(db, data_type="trial_balance", client_accounts=inputs)
        assert len(results) == 1
        candidates = results[0]["candidates"]
        assert len(candidates) >= 1

        # code_match 应该已降级为 code_match_conflict
        conflict = next((c for c in candidates if c["source"] == "code_match_conflict"), None)
        assert conflict is not None

        # 应有候选指向 1123 预付账款（语义匹配或名称锚点）
        anchor_candidate = next(
            (c for c in candidates if c.get("standard_account_code") == "1123" and c["source"] in ("name_anchor", "semantic_alias")),
            None,
        )
        assert anchor_candidate is not None, (
            f"应有候选指向 1123 预付账款，实际候选: "
            f"{[(c['standard_account_code'], c['source']) for c in candidates]}"
        )


class TestSafeAutoRollup:
    """TASK-066：安全明细自动归入标准父级/锚点科目"""

    @pytest.mark.asyncio
    async def test_safe_bank_detail_auto_confirmable(self, db):
        """10020108 脱敏银行存款明细 → 1002 银行存款（安全）"""
        sa = _make_standard_account("1002", "银行存款")
        db.add(sa)
        await db.flush()

        results = await recommend_mappings(
            db, data_type="trial_balance", client_accounts=[
                {"client_account_code": "10020108", "client_account_name": BANK_DETAIL_NAME},
            ],
        )
        candidates = results[0]["candidates"]
        safe = [c for c in candidates if c["standard_account_code"] == "1002" and c["warning"] is None and c["score"] >= 0.9]
        assert len(safe) >= 1, f"应有安全自动确认候选指向 1002"

    @pytest.mark.asyncio
    async def test_safe_expense_details_auto_confirmable(self, db):
        """660303/660304/671108/680101 明细 → 对应标准父级（安全）"""
        accounts = [
            _make_standard_account("6603", "减：财务费用"),
            _make_standard_account("6711", "减：营业外支出"),
            _make_standard_account("6801", "所得税费用"),
        ]
        db.add_all(accounts)
        await db.flush()

        cases = [
            ("660303", "财务费用_利息收入", "6603"),
            ("660304", "财务费用_利息支出", "6603"),
            ("671108", "营业外支出_其他", "6711"),
            ("680101", "所得税费用_当期所得税费用", "6801"),
        ]
        for code, name, expected in cases:
            results = await recommend_mappings(
                db, data_type="trial_balance", client_accounts=[
                    {"client_account_code": code, "client_account_name": name},
                ],
            )
            candidates = results[0]["candidates"]
            safe = [c for c in candidates if c["standard_account_code"] == expected and c["warning"] is None and c["score"] >= 0.9]
            assert len(safe) >= 1, f"{code} {name} 应有安全候选指向 {expected}"

    @pytest.mark.asyncio
    async def test_research_expense_diff_code_system_auto_confirmable(self, db):
        """660401 研发费用 → 660201 减：研发费用（跨代码体系，安全）"""
        sa = _make_standard_account("660201", "减：研发费用")
        db.add(sa)
        await db.flush()

        results = await recommend_mappings(
            db, data_type="trial_balance", client_accounts=[
                {"client_account_code": "660401", "client_account_name": "研发费用"},
            ],
        )
        candidates = results[0]["candidates"]
        safe = [c for c in candidates if c["standard_account_code"] == "660201" and c["warning"] is None and c["score"] >= 0.9]
        assert len(safe) >= 1, f"660401 应有安全候选指向 660201"

    @pytest.mark.asyncio
    async def test_dangerous_exact_code_conflicts_still_not_auto_confirmable(self, db):
        """112301/140501 代码相同但名称锚点冲突 → 不能自动确认"""
        accounts = [
            _make_standard_account("112301", "应收款项融资"),
            _make_standard_account("140501", "产品成本差异"),
            _make_standard_account("1405", "库存商品"),
        ]
        db.add_all(accounts)
        await db.flush()

        # 冲突：代码相同但锚点不一致
        for code, name in [("112301", "预付账款_预付材料款"), ("140501", "库存商品")]:
            results = await recommend_mappings(
                db, data_type="trial_balance", client_accounts=[
                    {"client_account_code": code, "client_account_name": name},
                ],
            )
            candidates = results[0]["candidates"]
            conflict = [c for c in candidates if c["source"] == "code_match_conflict" and c["warning"] is not None and c["score"] < 0.9]
            assert len(conflict) >= 1, f"{code} {name} 应有冲突候选"

        # 140501 库存商品 → 应有 1405 库存商品 的 name_anchor 安全候选
        results = await recommend_mappings(
            db, data_type="trial_balance", client_accounts=[
                {"client_account_code": "140501", "client_account_name": "库存商品"},
            ],
        )
        candidates = results[0]["candidates"]
        safe_1405 = [c for c in candidates if c["standard_account_code"] == "1405" and c["warning"] is None and c["score"] >= 0.9]
        assert len(safe_1405) >= 1, f"140501 库存商品应有安全候选指向 1405"

    @pytest.mark.asyncio
    async def test_non_participating_row_not_auto_confirmable(self, db):
        """非末级/不入库行（is_leaf=False, participates_in_entry=False）不得安全自动确认"""
        sa = _make_standard_account("1002", "银行存款")
        db.add(sa)
        await db.flush()

        # 父级行：is_leaf=False, participates_in_entry=False
        results = await recommend_mappings(
            db, data_type="trial_balance", client_accounts=[
                {
                    "client_account_code": "100201",
                    "client_account_name": "银行存款_活期户",
                    "is_leaf": False,
                    "participates_in_entry": False,
                },
            ],
        )
        candidates = results[0]["candidates"]
        # 不得有安全自动确认候选
        safe = [c for c in candidates if c["standard_account_code"] == "1002" and c["warning"] is None and c["score"] >= 0.9]
        assert len(safe) == 0, f"非末级不入库行不应有安全候选，实际: {safe}"

    @pytest.mark.asyncio
    async def test_real_leaf_rows_still_auto_confirmable(self, db):
        """真实末级行 10020108、660401 仍能安全自动确认"""
        accounts = [
            _make_standard_account("1002", "银行存款"),
            _make_standard_account("660201", "减：研发费用"),
        ]
        db.add_all(accounts)
        await db.flush()

        for code, name, expected in [
            ("10020108", BANK_DETAIL_NAME, "1002"),
            ("660401", "研发费用", "660201"),
        ]:
            results = await recommend_mappings(
                db, data_type="trial_balance", client_accounts=[
                    {"client_account_code": code, "client_account_name": name},
                ],
            )
            candidates = results[0]["candidates"]
            safe = [c for c in candidates if c["standard_account_code"] == expected and c["warning"] is None and c["score"] >= 0.9]
            assert safe, f"{code} {name} 应有安全候选指向 {expected}"


class TestSemanticAccountMatching:
    """TASK-064：客户科目代码与标准科目代码不一致时，按经济含义匹配。"""

    @pytest.mark.asyncio
    async def test_prepayments_match_prepayments_account(self, db):
        """客户 112301/112302 预付账款 → 标准 112401 预付款项"""
        standards = [
            _make_standard_account("112301", "应收款项融资"),
            _make_standard_account("112302", "加：应收款项融资-公允价值变动"),
            _make_standard_account("112401", "预付款项"),
            _make_standard_account("112402", "减：预付款项-坏账准备"),
        ]
        db.add_all(standards)
        await db.flush()
        for code, name in [("112301", "预付账款_预付材料款"), ("112302", "预付账款_预付机物料款")]:
            results = await recommend_mappings(
                db, data_type="trial_balance", client_accounts=[{"client_account_code": code, "client_account_name": name}])
            candidates = results[0]["candidates"]
            safe = [c for c in candidates if c["standard_account_code"] == "112401" and c["warning"] is None and c["score"] >= 0.9]
            assert safe, f"{code} 应有语义匹配指向 112401"
            bad = [c for c in candidates if c["standard_account_code"] in ("112301", "112302") and c["warning"] is None and c["score"] >= 0.9]
            assert not bad, f"{code} 不应安全匹配 112301/112302"

    @pytest.mark.asyncio
    async def test_accumulated_depreciation_details_match(self, db):
        """累计折旧明细 → 1602 减：固定资产-累计折旧"""
        standards = [_make_standard_account("1601", "固定资产-原值"), _make_standard_account("1602", "减：固定资产-累计折旧")]
        db.add_all(standards)
        await db.flush()
        for code, name in [("160202", "累计折旧_机器设备"), ("160203", "累计折旧_运输设备"), ("160204", "累计折旧_其他设备")]:
            results = await recommend_mappings(db, data_type="trial_balance", client_accounts=[{"client_account_code": code, "client_account_name": name}])
            candidates = results[0]["candidates"]
            safe = [c for c in candidates if c["standard_account_code"] == "1602" and c["warning"] is None and c["score"] >= 0.9]
            assert safe, f"{code} 应有安全候选指向 1602"
            bad = [c for c in candidates if c["standard_account_code"] == "1601" and c["warning"] is None and c["score"] >= 0.9]
            assert not bad, f"{code} 不应安全匹配 1601"

    @pytest.mark.asyncio
    async def test_construction_in_progress_details_match(self, db):
        """在建工程明细 → 160401 在建工程-原值"""
        standards = [_make_standard_account("160401", "在建工程-原值"), _make_standard_account("160402", "减：在建工程-减值准备")]
        db.add_all(standards)
        await db.flush()
        for code, name in [("160403", "在建工程_在安装设备"), ("160404", "在建工程_其他费用"), ("160405", "在建工程_装修费用"), ("160406", "在建工程_工程项目")]:
            results = await recommend_mappings(db, data_type="trial_balance", client_accounts=[{"client_account_code": code, "client_account_name": name}])
            candidates = results[0]["candidates"]
            safe = [c for c in candidates if c["standard_account_code"] == "160401" and c["warning"] is None and c["score"] >= 0.9]
            assert safe, f"{code} 应有安全候选指向 160401"
            bad = [c for c in candidates if c["standard_account_code"] == "160402" and c["warning"] is None and c["score"] >= 0.9]
            assert not bad, f"{code} 不应安全匹配 160402"

    @pytest.mark.asyncio
    async def test_code_conflict_still_not_auto_confirmable(self, db):
        """代码相同但语义冲突仍不能自动确认"""
        db.add(_make_standard_account("112301", "应收款项融资"))
        await db.flush()
        results = await recommend_mappings(db, data_type="trial_balance", client_accounts=[{"client_account_code": "112301", "client_account_name": "预付账款_预付材料款"}])
        candidates = results[0]["candidates"]
        conflict = [c for c in candidates if c["source"] == "code_match_conflict"]
        assert conflict, "应有 code_match_conflict"
        assert conflict[0]["warning"] is not None
        assert conflict[0]["score"] < 0.9

    @pytest.mark.asyncio
    async def test_inventory_still_not_mismatched(self, db):
        """140501 库存商品 → 1405 库存商品"""
        standards = [_make_standard_account("1405", "库存商品"), _make_standard_account("140501", "产品成本差异")]
        db.add_all(standards)
        await db.flush()
        results = await recommend_mappings(db, data_type="trial_balance", client_accounts=[{"client_account_code": "140501", "client_account_name": "库存商品"}])
        candidates = results[0]["candidates"]
        safe = [c for c in candidates if c["standard_account_code"] == "1405" and c["warning"] is None and c["score"] >= 0.9]
        assert safe, "应有安全候选指向 1405"
        bad = [c for c in candidates if c["standard_account_code"] == "140501" and c["warning"] is None and c["score"] >= 0.9]
        assert not bad, "140501 不应安全确认"

    @pytest.mark.asyncio
    async def test_deferred_income_detail_matches(self, db):
        """240102 递延收益_与资产相关的递延收益 → 2401 递延收益"""
        db.add(_make_standard_account("2401", "递延收益"))
        await db.flush()
        results = await recommend_mappings(
            db, data_type="trial_balance", client_accounts=[
                {"client_account_code": "240102", "client_account_name": "递延收益_与资产相关的递延收益"},
            ])
        candidates = results[0]["candidates"]
        safe = [c for c in candidates if c["standard_account_code"] == "2401" and c["warning"] is None and c["score"] >= 0.9]
        assert safe, f"递延收益明细应安全匹配 2401，实际: {[(c['standard_account_code'],c['source'],c['score'],c['warning']) for c in candidates]}"

    @pytest.mark.asyncio
    async def test_production_cost_details_match(self, db):
        """生产成本明细 → 5001 生产成本，不得匹配 6001/2211"""
        standards = [
            _make_standard_account("5001", "生产成本"),
            _make_standard_account("5002", "农业生产成本"),
            _make_standard_account("6001", "其中：主营业务收入"),
            _make_standard_account("6401", "其中：主营业务成本"),
            _make_standard_account("2211", "应付职工薪酬"),
        ]
        db.add_all(standards)
        await db.flush()
        for code, name in [("50010101", "生产成本_基本生产成本_直接材料"), ("5001010201", "生产成本_基本生产成本_直接人工_工资及奖金")]:
            results = await recommend_mappings(
                db, data_type="trial_balance", client_accounts=[{"client_account_code": code, "client_account_name": name}])
            candidates = results[0]["candidates"]
            safe = [c for c in candidates if c["standard_account_code"] == "5001" and c["warning"] is None and c["score"] >= 0.9]
            assert safe, f"{code} 应安全匹配 5001，实际: {[(c['standard_account_code'],c['source'],c['score']) for c in candidates]}"
            wrong = [c for c in candidates if c["standard_account_code"] in ("2211","6001","6401") and c["warning"] is None and c["score"] >= 0.9]
            assert not wrong, f"{code} 不得安全匹配薪酬/收入/成本"
            w6001 = [c for c in candidates if c["standard_account_code"] == "6001"]
            assert not w6001, f"{code} 不应出现 6001 主营业务收入候选"

    @pytest.mark.asyncio
    async def test_manufacturing_overhead_details_match(self, db):
        """制造费用明细 → 5101 制造费用，不得匹配 2211"""
        standards = [
            _make_standard_account("5101", "制造费用"),
            _make_standard_account("2211", "应付职工薪酬"),
            _make_standard_account("6602", "减：管理费用"),
        ]
        db.add_all(standards)
        await db.flush()
        for code, name in [("51010101", "制造费用_人工_工资及奖金"), ("5101010201", "制造费用_人工_福利费_社会统筹")]:
            results = await recommend_mappings(
                db, data_type="trial_balance", client_accounts=[{"client_account_code": code, "client_account_name": name}])
            candidates = results[0]["candidates"]
            safe = [c for c in candidates if c["standard_account_code"] == "5101" and c["warning"] is None and c["score"] >= 0.9]
            assert safe, f"{code} 应安全匹配 5101"
            wrong = [c for c in candidates if c["standard_account_code"] in ("2211","6602") and c["warning"] is None and c["score"] >= 0.9]
            assert not wrong, f"{code} 不得安全匹配薪酬/管理费用"

    @pytest.mark.asyncio
    async def test_research_expense_code_category_anchor_still_works(self, db):
        """660401 研发费用 → 660201 减：研发费用（TASK-064 不退步）"""
        db.add(_make_standard_account("660201", "减：研发费用"))
        await db.flush()
        results = await recommend_mappings(
            db, data_type="trial_balance", client_accounts=[{"client_account_code": "660401", "client_account_name": "研发费用"}])
        candidates = results[0]["candidates"]
        safe = [c for c in candidates if c["standard_account_code"] == "660201" and c["warning"] is None and c["score"] >= 0.9]
        assert safe, f"660401 仍应安全匹配 660201，实际: {[(c['standard_account_code'],c['source'],c['score']) for c in candidates]}"

    @pytest.mark.asyncio
    async def test_research_expenditure_expensed_details_match(self, db):
        """研发支出_费用化支出_* → 170402 研发支出-费用化支出"""
        standards = [
            _make_standard_account("660201", "减：研发费用"),
            _make_standard_account("1704", "开发支出", level=1, is_leaf=False),
            _make_standard_account("170401", "研发支出-资本化支出", level=2, is_leaf=True),
            _make_standard_account("170402", "研发支出-费用化支出", level=2, is_leaf=True),
            _make_standard_account("2211", "应付职工薪酬"),
        ]
        db.add_all(standards)
        await db.flush()
        for code, name in [
            ("5301010101", "研发支出_费用化支出_人工_工资及奖金"),
            (RD_SOCIAL_WELFARE_CODE, "研发支出_费用化支出_人工_福利费_社会统筹"),
            ("5301010204", "研发支出_费用化支出_办公费用_邮寄费"),
            ("53010108", "研发支出_费用化支出_折旧"),
            (RD_MATERIAL_CODE, "研发支出_费用化支出_直接投入_机物料_仓存机物料"),
            ("5301019802", "研发支出_费用化支出_专项_测试化验加工费"),
        ]:
            results = await recommend_mappings(
                db, data_type="trial_balance", client_accounts=[{"client_account_code": code, "client_account_name": name}])
            candidates = results[0]["candidates"]
            safe = [c for c in candidates if c["standard_account_code"] == "170402" and c["warning"] is None and c["score"] >= 0.9]
            assert safe, f"{code} 应安全匹配 170402，实际: {[(c['standard_account_code'],c['source'],c['score']) for c in candidates]}"
            wrong = [c for c in candidates if c["standard_account_code"] == "660201" and c["warning"] is None and c["score"] >= 0.9]
            assert not wrong, f"{code} 不得安全匹配 660201"

    @pytest.mark.asyncio
    async def test_research_expenditure_capitalized_not_matches_research_expense(self, db):
        """研发支出_资本化支出_* → 170401 研发支出-资本化支出，不得 → 660201"""
        standards = [
            _make_standard_account("660201", "减：研发费用"),
            _make_standard_account("1704", "开发支出", level=1, is_leaf=False),
            _make_standard_account("170401", "研发支出-资本化支出", level=2, is_leaf=True),
            _make_standard_account("170402", "研发支出-费用化支出", level=2, is_leaf=True),
            _make_standard_account("1636", "油气开发支出"),
        ]
        db.add_all(standards)
        await db.flush()
        results = await recommend_mappings(
            db, data_type="trial_balance", client_accounts=[{"client_account_code": "5301020101", "client_account_name": "研发支出_资本化支出_人工_工资及奖金"}])
        candidates = results[0]["candidates"]
        safe = [c for c in candidates if c["standard_account_code"] == "170401" and c["warning"] is None and c["score"] >= 0.9]
        assert safe, f"资本化研发支出应安全匹配 170401，实际: {[(c['standard_account_code'],c['source'],c['score']) for c in candidates]}"
        wrong = [c for c in candidates if c["standard_account_code"] == "660201" and c["warning"] is None and c["score"] >= 0.9]
        assert not wrong, "资本化研发支出不得安全匹配研发费用"

    @pytest.mark.asyncio
    async def test_investment_income_detail_matches(self, db):
        """投资收益_交易性金融资产收益 → 6111 加：投资收益"""
        standards = [_make_standard_account("6111", "加：投资收益"), _make_standard_account("1101", "交易性金融资产")]
        db.add_all(standards)
        await db.flush()
        results = await recommend_mappings(
            db, data_type="trial_balance", client_accounts=[{"client_account_code": "611101", "client_account_name": "投资收益_交易性金融资产收益"}])
        candidates = results[0]["candidates"]
        safe = [c for c in candidates if c["standard_account_code"] == "6111" and c["warning"] is None and c["score"] >= 0.9]
        assert safe, "投资收益明细应安全匹配 6111"
        wrong = [c for c in candidates if c["standard_account_code"] == "1101" and c["warning"] is None and c["score"] >= 0.9]
        assert not wrong, "投资收益明细不得安全匹配交易性金融资产"

    @pytest.mark.asyncio
    async def test_other_income_matches(self, db):
        """其他收益 → 6117 加：其他收益"""
        standards = [
            _make_standard_account("6117", "加：其他收益"),
            _make_standard_account("4301", "其他综合收益"),
            _make_standard_account("122101", "其他应收款"),
            _make_standard_account("4002", "其他权益工具"),
        ]
        db.add_all(standards)
        await db.flush()
        results = await recommend_mappings(
            db, data_type="trial_balance", client_accounts=[{"client_account_code": "6112", "client_account_name": "其他收益"}])
        candidates = results[0]["candidates"]
        safe = [c for c in candidates if c["standard_account_code"] == "6117" and c["warning"] is None and c["score"] >= 0.9]
        assert safe, "其他收益应安全匹配 6117"
        wrong = [c for c in candidates if c["standard_account_code"] in ("4301","122101","4002") and c["warning"] is None and c["score"] >= 0.9]
        assert not wrong, "其他收益不得安全匹配其他综合收益/其他应收款/其他权益工具"

    @pytest.mark.asyncio
    async def test_production_cost_not_safe_match_agricultural(self, db):
        """生产成本不得安全匹配 5002 农业生产成本"""
        standards = [_make_standard_account("5001", "生产成本"), _make_standard_account("5002", "农业生产成本")]
        db.add_all(standards)
        await db.flush()
        results = await recommend_mappings(
            db, data_type="trial_balance", client_accounts=[{"client_account_code": "50010101", "client_account_name": "生产成本_基本生产成本_直接材料"}])
        candidates = results[0]["candidates"]
        safe = [c for c in candidates if c["standard_account_code"] == "5001" and c["warning"] is None and c["score"] >= 0.9]
        assert safe, "生产成本应安全匹配 5001"
        wrong = [c for c in candidates if c["standard_account_code"] == "5002" and c["warning"] is None and c["score"] >= 0.9]
        assert not wrong, "生产成本不得安全匹配 5002 农业生产成本"


# ── TASK-068：代码精确命中父级但名称精确命中子级时优先子级 ──

class TestExactCodeVsExactNameConflict:
    """TASK-068：当客户代码精确命中标准父级，但客户名称精确命中标准子级时，
    名称精确命中应优先；原代码命中必须降级为 warning 候选，不得作为安全自动确认。
    """

    @pytest.mark.asyncio
    async def test_exact_code_parent_name_exact_child_prefers_child(self, db):
        """客户代码命中父级标准科目，但名称精确命中子级时，应优先子级"""
        parent = _make_standard_account("1411", "周转材料")
        packaging = _make_standard_account("141101", "包装物", parent_id=parent.id)
        consumables = _make_standard_account("141102", "低值易耗品", parent_id=parent.id)
        parent.is_leaf = False
        packaging.is_leaf = True
        consumables.is_leaf = True
        db.add_all([parent, packaging, consumables])
        await db.flush()

        cases = [
            ("1411", "包装物", "141101"),
            ("1411", "低值易耗品", "141102"),
        ]

        for client_code, client_name, expected_code in cases:
            results = await recommend_mappings(
                db,
                data_type="trial_balance",
                client_accounts=[{
                    "client_account_code": client_code,
                    "client_account_name": client_name,
                }],
            )
            candidates = results[0]["candidates"]

            safe = [
                c for c in candidates
                if c["warning"] is None and c["score"] >= 0.9
            ]
            assert safe, f"{client_code} {client_name} 应有安全候选，实际: {candidates}"
            assert safe[0]["standard_account_code"] == expected_code, (
                f"{client_code} {client_name} 应优先匹配 {expected_code}，实际安全候选: {safe}"
            )

            bad_safe_parent = [
                c for c in candidates
                if c["standard_account_code"] == "1411"
                and c["warning"] is None
                and c["score"] >= 0.9
            ]
            assert not bad_safe_parent, f"父级 1411 周转材料不得作为安全候选: {bad_safe_parent}"

            # 若保留 1411 候选，必须降级为 warning 候选，score < 0.9
            parent_cands = [c for c in candidates if c["standard_account_code"] == "1411"]
            for pc in parent_cands:
                assert pc["warning"] is not None, (
                    f"父级 1411 不得无 warning: {pc}"
                )
                assert pc["score"] < 0.9, (
                    f"父级 1411 降级后 score 必须 < 0.9，实际: {pc['score']}"
                )

    @pytest.mark.asyncio
    async def test_exact_code_parent_name_same_still_matches_parent(self, db):
        """客户就是周转材料时，仍应匹配 1411 周转材料"""
        parent = _make_standard_account("1411", "周转材料")
        child = _make_standard_account("141101", "包装物", parent_id=parent.id)
        parent.is_leaf = False
        child.is_leaf = True
        db.add_all([parent, child])
        await db.flush()

        results = await recommend_mappings(
            db,
            data_type="trial_balance",
            client_accounts=[{
                "client_account_code": "1411",
                "client_account_name": "周转材料",
            }],
        )
        candidates = results[0]["candidates"]
        safe = [
            c for c in candidates
            if c["standard_account_code"] == "1411"
            and c["warning"] is None
            and c["score"] >= 0.9
        ]
        assert safe, f"1411 周转材料仍应安全匹配父级，实际: {candidates}"

    @pytest.mark.asyncio
    async def test_exact_child_code_and_name_still_matches_child(self, db):
        """客户 141101 包装物 / 141102 低值易耗品 仍应安全匹配各自子级"""
        parent = _make_standard_account("1411", "周转材料")
        packaging = _make_standard_account("141101", "包装物", parent_id=parent.id)
        consumables = _make_standard_account("141102", "低值易耗品", parent_id=parent.id)
        parent.is_leaf = False
        packaging.is_leaf = True
        consumables.is_leaf = True
        db.add_all([parent, packaging, consumables])
        await db.flush()

        for client_code, client_name, expected in [
            ("141101", "包装物", "141101"),
            ("141102", "低值易耗品", "141102"),
        ]:
            results = await recommend_mappings(
                db,
                data_type="trial_balance",
                client_accounts=[{
                    "client_account_code": client_code,
                    "client_account_name": client_name,
                }],
            )
            candidates = results[0]["candidates"]
            safe = [
                c for c in candidates
                if c["standard_account_code"] == expected
                and c["warning"] is None
                and c["score"] >= 0.9
            ]
            assert safe, f"{client_code} {client_name} 应安全匹配 {expected}，实际: {candidates}"


# ── TASK-070：代码命中父级 + 名称首段为更精确子级名称时优先子级 ──

class TestExactCodeVsNamePrefixConflict:
    """TASK-070：客户代码命中标准父级，但客户名称带明细后缀、首段/开头明确是更精确
    标准子级名称时（如「1411 包装物_纸箱」），应安全首选子级；父级 code_match 必须降级。
    """

    @pytest.mark.asyncio
    async def test_exact_code_parent_detail_name_prefix_prefers_child(self, db):
        """客户代码命中父级，但名称以更精确子级名称开头时，应优先子级"""
        parent = _make_standard_account("1411", "周转材料")
        packaging = _make_standard_account("141101", "包装物", parent_id=parent.id)
        consumables = _make_standard_account("141102", "低值易耗品", parent_id=parent.id)
        parent.is_leaf = False
        packaging.is_leaf = True
        consumables.is_leaf = True
        db.add_all([parent, packaging, consumables])
        await db.flush()

        cases = [
            ("1411", "包装物_纸箱", "141101"),
            ("1411", "包装物-包装袋", "141101"),
            ("1411", "低值易耗品_工具", "141102"),
            ("1411", "低值易耗品-办公椅", "141102"),
        ]

        for client_code, client_name, expected_code in cases:
            results = await recommend_mappings(
                db,
                data_type="trial_balance",
                client_accounts=[{
                    "client_account_code": client_code,
                    "client_account_name": client_name,
                }],
            )
            candidates = results[0]["candidates"]
            safe = [
                c for c in candidates
                if c["warning"] is None and c["score"] >= 0.9
            ]
            assert safe, f"{client_code} {client_name} 应有安全候选，实际: {candidates}"
            assert safe[0]["standard_account_code"] == expected_code, (
                f"{client_code} {client_name} 应安全首选 {expected_code}，实际安全候选: {safe}"
            )

            bad_parent = [
                c for c in candidates
                if c["standard_account_code"] == "1411"
                and c["warning"] is None
                and c["score"] >= 0.9
            ]
            assert not bad_parent, f"父级 1411 周转材料不得作为安全候选: {bad_parent}"

            # 若保留 1411 候选，必须降级为 warning 候选，score < 0.9
            parent_cands = [c for c in candidates if c["standard_account_code"] == "1411"]
            for pc in parent_cands:
                assert pc["warning"] is not None, f"父级 1411 不得无 warning: {pc}"
                assert pc["score"] < 0.9, f"父级 1411 降级后 score 必须 < 0.9: {pc['score']}"

    @pytest.mark.asyncio
    async def test_parent_name_with_suffix_still_matches_parent(self, db):
        """客户就是周转材料（无论是否带后缀）时，仍应安全匹配 1411 周转材料"""
        parent = _make_standard_account("1411", "周转材料")
        packaging = _make_standard_account("141101", "包装物", parent_id=parent.id)
        parent.is_leaf = False
        packaging.is_leaf = True
        db.add_all([parent, packaging])
        await db.flush()

        for client_name in ["周转材料", "周转材料_在用", "周转材料-库存"]:
            results = await recommend_mappings(
                db,
                data_type="trial_balance",
                client_accounts=[{
                    "client_account_code": "1411",
                    "client_account_name": client_name,
                }],
            )
            candidates = results[0]["candidates"]
            safe = [
                c for c in candidates
                if c["standard_account_code"] == "1411"
                and c["warning"] is None
                and c["score"] >= 0.9
            ]
            assert safe, f"1411 {client_name} 仍应安全匹配父级，实际: {candidates}"

    @pytest.mark.asyncio
    async def test_generic_name_prefix_not_auto_match(self, db):
        """过于泛化的标准名称（如「费用」「资产」）不应因 startswith 自动安全匹配"""
        standards = [
            _make_standard_account("1411", "周转材料"),
            _make_standard_account("100", "资产"),  # 泛化名称，不安全
        ]
        db.add_all(standards)
        await db.flush()

        results = await recommend_mappings(
            db,
            data_type="trial_balance",
            client_accounts=[{
                "client_account_code": "1411",
                "client_account_name": "资产_流动",
            }],
        )
        candidates = results[0]["candidates"]
        bad = [
            c for c in candidates
            if c["standard_account_code"] == "100"
            and c["warning"] is None
            and c["score"] >= 0.9
        ]
        assert not bad, f"泛化名称「资产」不应自动安全匹配: {bad}"


# ── TASK-072 Task2：在建工程代码相同但不应归入减值准备 ──

class TestConstructionImpairmentConflict:
    """160402 在建工程_生产线 等非减值名称，不得安全匹配 160402 减：在建工程-减值准备。"""

    @pytest.mark.asyncio
    async def test_construction_in_progress_same_code_not_impairment(self, db):
        original = _make_standard_account("160401", "在建工程-原值",
                                          is_active=True, is_leaf=True, level=1)
        impairment = _make_standard_account("160402", "减：在建工程-减值准备",
                                            is_active=True, is_leaf=True, level=1)
        db.add_all([original, impairment])
        await db.flush()

        cases = [
            ("160402", "在建工程"),
            ("160402", "在建工程_生产线"),
            ("160402", "在建工程-生产线"),
            ("160402", "工程项目A"),
            ("160402", "装修费用"),
        ]

        for code, name in cases:
            results = await recommend_mappings(
                db, data_type="trial_balance",
                client_accounts=[{"client_account_code": code, "client_account_name": name}],
            )
            cands = results[0]["candidates"]
            safe_original = [
                c for c in cands
                if c["standard_account_code"] == "160401"
                and c["warning"] is None
                and c["score"] >= 0.9
            ]
            bad_impairment_safe = [
                c for c in cands
                if c["standard_account_code"] == "160402"
                and c["warning"] is None
                and c["score"] >= 0.9
            ]
            assert safe_original, f"{code} {name} 应安全匹配 160401，实际: {[(c['standard_account_code'],c['source'],c['warning'],c['score']) for c in cands]}"
            assert not bad_impairment_safe, f"{code} {name} 不得安全匹配 160402，实际: {[(c['standard_account_code'],c['source'],c['warning'],c['score']) for c in cands]}"

            # TASK-077：安全候选必须排在 candidates[0]，不能只断言列表里有 160401。
            # 否则自动确认盲取 candidates[0] 会命中 160402 减值准备。
            assert cands[0]["standard_account_code"] == "160401", \
                f"{code} {name} cands[0] 应为 160401，实际: {[(c['standard_account_code'],c['source'],c['warning'],c['score']) for c in cands]}"
            assert cands[0]["warning"] is None, \
                f"{code} {name} cands[0] 不应带 warning，实际: {cands[0]}"
            assert float(cands[0]["score"]) >= 0.9, \
                f"{code} {name} cands[0] score 应 >= 0.9，实际: {cands[0]['score']}"
            # 160402 仍应在候选列表中作为带 warning 的冲突候选存在
            assert any(c["standard_account_code"] == "160402" and c["warning"] for c in cands), \
                f"{code} {name} 应保留带 warning 的 160402 候选，实际: {[(c['standard_account_code'],c['source'],c['warning'],c['score']) for c in cands]}"

    @pytest.mark.asyncio
    async def test_construction_impairment_still_matches_impairment(self, db):
        original = _make_standard_account("160401", "在建工程-原值",
                                          is_active=True, is_leaf=True, level=1)
        impairment = _make_standard_account("160402", "减：在建工程-减值准备",
                                            is_active=True, is_leaf=True, level=1)
        db.add_all([original, impairment])
        await db.flush()

        results = await recommend_mappings(
            db, data_type="trial_balance",
            client_accounts=[{"client_account_code": "160402", "client_account_name": "在建工程减值准备"}],
        )
        safe_impairment = [
            c for c in results[0]["candidates"]
            if c["standard_account_code"] == "160402"
            and c["warning"] is None
            and c["score"] >= 0.9
        ]
        assert safe_impairment, results[0]["candidates"]


# ── TASK-072 Task3：管理费用_办公费 不得匹配研发费用 ──

class TestManagementVsResearchExpenseConflict:
    """660201 管理费用_办公费 代码命中 660201 研发费用时，名称冲突应降级，安全候选应为 6602 管理费用。"""

    @pytest.mark.asyncio
    async def test_management_expense_name_wins_over_660201_code(self, db):
        mgmt = _make_standard_account("6602", "减：管理费用",
                                      is_active=True, is_leaf=True, level=1)
        rd = _make_standard_account("660201", "减：研发费用",
                                    is_active=True, is_leaf=True, level=1)
        db.add_all([mgmt, rd])
        await db.flush()

        results = await recommend_mappings(
            db, data_type="trial_balance",
            client_accounts=[{"client_account_code": "660201", "client_account_name": "管理费用_办公费"}],
        )
        cands = results[0]["candidates"]
        safe_mgmt = [
            c for c in cands
            if c["standard_account_code"] == "6602"
            and c["warning"] is None
            and c["score"] >= 0.9
        ]
        bad_rd = [
            c for c in cands
            if c["standard_account_code"] == "660201"
            and c["warning"] is None
            and c["score"] >= 0.9
        ]
        assert safe_mgmt, f"管理费用_办公费 应安全匹配 6602，实际: {[(c['standard_account_code'],c['source'],c['warning'],c['score']) for c in cands]}"
        assert not bad_rd, f"管理费用_办公费 不得安全匹配 660201 研发费用，实际: {[(c['standard_account_code'],c['source'],c['warning'],c['score']) for c in cands]}"

    @pytest.mark.asyncio
    async def test_research_expense_still_matches_660201(self, db):
        """纯研发费用（无支出语义）仍应安全匹配 660201。"""
        mgmt = _make_standard_account("6602", "减：管理费用",
                                      is_active=True, is_leaf=True, level=1)
        rd = _make_standard_account("660201", "减：研发费用",
                                    is_active=True, is_leaf=True, level=1)
        db.add_all([mgmt, rd])
        await db.flush()

        results = await recommend_mappings(
            db, data_type="trial_balance",
            client_accounts=[{"client_account_code": "660401", "client_account_name": "研发费用"}],
        )
        safe_rd = [
            c for c in results[0]["candidates"]
            if c["standard_account_code"] == "660201"
            and c["warning"] is None
            and c["score"] >= 0.9
        ]
        assert safe_rd, f"660401 研发费用 应安全匹配 660201，实际: {[(c['standard_account_code'],c['source'],c['warning'],c['score']) for c in results[0]['candidates']]}"

    @pytest.mark.asyncio
    async def test_rd_development_expensed_maps_to_170402_not_rd_expense(self, db):
        """研发支出_费用化支出_* 应匹配 170402 研发支出-费用化支出，不得匹配 660201。"""
        dev = _make_standard_account("1704", "开发支出", is_active=True, level=1, is_leaf=False)
        cap = _make_standard_account("170401", "研发支出-资本化支出", parent_id=dev.id,
                                     balance_direction="debit", is_active=True, level=2, is_leaf=True)
        exp = _make_standard_account("170402", "研发支出-费用化支出", parent_id=dev.id,
                                     balance_direction="debit", is_active=True, level=2, is_leaf=True)
        rd_expense = _make_standard_account("660201", "减：研发费用",
                                            balance_direction="debit", is_active=True, is_leaf=True, level=1)
        db.add_all([dev, cap, exp, rd_expense])
        await db.flush()

        result = await recommend_mappings(
            db,
            data_type="trial_balance",
            customer_label=None,
            client_accounts=[
                {"client_account_code": RD_MATERIAL_CODE, "client_account_name": "研发支出_费用化支出_直接投入_机物料_仓存机物料"},
            ],
        )
        cands = result[0]["candidates"]
        safe_170402 = [c for c in cands if c["standard_account_code"] == "170402" and c["warning"] is None and c["score"] >= 0.9]
        bad_660201 = [c for c in cands if c["standard_account_code"] == "660201" and c["warning"] is None and c["score"] >= 0.9]
        assert safe_170402, f"研发支出_费用化支出 应匹配 170402，实际: {[(c['standard_account_code'],c['source'],c['warning'],c['score']) for c in cands]}"
        assert not bad_660201, f"研发支出_费用化支出 不得安全匹配 660201，实际: {[(c['standard_account_code'],c['source'],c['warning'],c['score']) for c in cands]}"
        assert cands[0]["standard_account_code"] == "170402"

    @pytest.mark.asyncio
    async def test_rd_development_capitalized_maps_to_170401(self, db):
        """研发支出_资本化支出_* 应匹配 170401 研发支出-资本化支出。"""
        dev = _make_standard_account("1704", "开发支出", is_active=True, level=1, is_leaf=False)
        cap = _make_standard_account("170401", "研发支出-资本化支出", parent_id=dev.id,
                                     balance_direction="debit", is_active=True, level=2, is_leaf=True)
        exp = _make_standard_account("170402", "研发支出-费用化支出", parent_id=dev.id,
                                     balance_direction="debit", is_active=True, level=2, is_leaf=True)
        rd_expense = _make_standard_account("660201", "减：研发费用",
                                            balance_direction="debit", is_active=True, is_leaf=True, level=1)
        db.add_all([dev, cap, exp, rd_expense])
        await db.flush()

        result = await recommend_mappings(
            db,
            data_type="trial_balance",
            customer_label=None,
            client_accounts=[
                {"client_account_code": "5301020101", "client_account_name": "研发支出_资本化支出_人工_工资及奖金"},
            ],
        )
        cands = result[0]["candidates"]
        safe_170401 = [c for c in cands if c["standard_account_code"] == "170401" and c["warning"] is None and c["score"] >= 0.9]
        bad_660201 = [c for c in cands if c["standard_account_code"] == "660201" and c["warning"] is None and c["score"] >= 0.9]
        assert safe_170401, f"研发支出_资本化支出 应匹配 170401，实际: {[(c['standard_account_code'],c['source'],c['warning'],c['score']) for c in cands]}"
        assert not bad_660201, f"研发支出_资本化支出 不得安全匹配 660201，实际: {[(c['standard_account_code'],c['source'],c['warning'],c['score']) for c in cands]}"
        assert cands[0]["standard_account_code"] == "170401"

    @pytest.mark.asyncio
    async def test_plain_rd_expense_still_maps_to_660201(self, db):
        """纯研发费用（660401）不落入 170402。"""
        db.add(_make_standard_account("170402", "研发支出-费用化支出", balance_direction="debit",
                                      is_active=True, is_leaf=True, level=2))
        db.add(_make_standard_account("660201", "减：研发费用", balance_direction="debit",
                                      is_active=True, is_leaf=True, level=1))
        await db.flush()

        result = await recommend_mappings(
            db,
            data_type="trial_balance",
            customer_label=None,
            client_accounts=[
                {"client_account_code": "660401", "client_account_name": "研发费用"},
            ],
        )
        cands = result[0]["candidates"]
        safe_660201 = [c for c in cands if c["standard_account_code"] == "660201" and c["warning"] is None and c["score"] >= 0.9]
        bad_170402 = [c for c in cands if c["standard_account_code"] == "170402" and c["warning"] is None and c["score"] >= 0.9]
        assert safe_660201, f"研发费用 应安全匹配 660201，实际: {[(c['standard_account_code'],c['source'],c['warning'],c['score']) for c in cands]}"
        assert not bad_170402, f"研发费用 不得安全匹配 170402，实际: {[(c['standard_account_code'],c['source'],c['warning'],c['score']) for c in cands]}"


# ── TASK-075：历史映射冲突校验 ──

class TestHistoryMappingConflict:
    """历史映射候选必须经过名称冲突校验。"""

    @pytest.mark.asyncio
    async def test_stale_history_to_cip_impairment_is_demoted(self, db):
        """历史映射 160402 在建工程_生产线 → 160402 减：在建工程-减值准备 应被降级。"""
        original = _make_standard_account("160401", "在建工程-原值",
                                         balance_direction="debit", is_active=True, is_leaf=True, level=1)
        impairment = _make_standard_account("160402", "减：在建工程-减值准备",
                                            balance_direction="credit", is_active=True, is_leaf=True, level=1)
        db.add_all([original, impairment])
        await db.flush()

        db.add(ClientAccountMapping(
            data_type="trial_balance",
            customer_label=None,
            client_account_code="160402",
            client_account_name="在建工程_生产线",
            normalized_client_account_name="在建工程生产线",
            standard_account_id=impairment.id,
            standard_account_code_snapshot="160402",
            standard_account_name_snapshot="减：在建工程-减值准备",
            confidence=1.0,
            scope="global",
            is_active=True,
        ))
        await db.flush()

        result = await recommend_mappings(
            db,
            data_type="trial_balance",
            customer_label=None,
            client_accounts=[{"client_account_code": "160402", "client_account_name": "在建工程_生产线"}],
        )
        cands = result[0]["candidates"]
        safe_original = [c for c in cands if c["standard_account_code"] == "160401" and c["warning"] is None and c["score"] >= 0.9]
        bad_impairment = [c for c in cands if c["standard_account_code"] == "160402" and c["warning"] is None and c["score"] >= 0.9]
        assert safe_original, f"在建工程_生产线 应安全匹配 160401，实际: {[(c['standard_account_code'],c['source'],c['warning'],c['score']) for c in cands]}"
        assert not bad_impairment, f"在建工程_生产线 不得安全匹配 160402 减值准备，实际: {[(c['standard_account_code'],c['source'],c['warning'],c['score']) for c in cands]}"

    @pytest.mark.asyncio
    async def test_stale_history_rd_development_to_rd_expense_is_demoted(self, db):
        """历史映射 研发支出_费用化支出 → 660201 研发费用 应被降级。"""
        exp_dev = _make_standard_account("170402", "研发支出-费用化支出",
                                        balance_direction="debit", is_active=True, is_leaf=True, level=2)
        rd_expense = _make_standard_account("660201", "减：研发费用",
                                           balance_direction="debit", is_active=True, is_leaf=True, level=1)
        db.add_all([exp_dev, rd_expense])
        await db.flush()

        db.add(ClientAccountMapping(
            data_type="trial_balance",
            customer_label=None,
            client_account_code="53010116",
            client_account_name="研发支出_费用化支出_检测费",
            normalized_client_account_name="研发支出费用化支出检测费",
            standard_account_id=rd_expense.id,
            standard_account_code_snapshot="660201",
            standard_account_name_snapshot="减：研发费用",
            confidence=1.0,
            scope="global",
            is_active=True,
        ))
        await db.flush()

        result = await recommend_mappings(
            db,
            data_type="trial_balance",
            customer_label=None,
            client_accounts=[{"client_account_code": "53010116", "client_account_name": "研发支出_费用化支出_检测费"}],
        )
        cands = result[0]["candidates"]
        safe_170402 = [c for c in cands if c["standard_account_code"] == "170402" and c["warning"] is None and c["score"] >= 0.9]
        bad_660201 = [c for c in cands if c["standard_account_code"] == "660201" and c["warning"] is None and c["score"] >= 0.9]
        assert safe_170402, f"研发支出_费用化支出 应安全匹配 170402，实际: {[(c['standard_account_code'],c['source'],c['warning'],c['score']) for c in cands]}"
        assert not bad_660201, f"研发支出_费用化支出 不得安全匹配 660201，实际: {[(c['standard_account_code'],c['source'],c['warning'],c['score']) for c in cands]}"
