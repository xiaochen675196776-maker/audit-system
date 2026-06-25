"""标准科目表导入后端测试 — TASK-040"""

import uuid
import tempfile
import os
import pytest
from pathlib import Path
from io import BytesIO

import openpyxl
from sqlalchemy import select

from app.models.standard_account import StandardAccount
from app.services.standard_account_service import (
    parse_standard_accounts_excel,
    infer_hierarchy,
    import_standard_accounts,
    get_standard_accounts,
    get_standard_account,
)


# ── 测试辅助：生成 Excel 文件 ────────────────────────

def _make_excel(headers: list[str], rows: list[list]) -> str:
    """生成临时 Excel 文件，返回文件路径。"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    wb.save(tmp.name)
    tmp.close()
    return tmp.name


def _cleanup(path: str):
    """清理临时文件"""
    try:
        os.unlink(path)
    except Exception:
        pass


# ── parse_standard_accounts_excel 测试 ────────────────

class TestParseExcel:
    """Excel 解析测试"""

    def test_basic_parse(self):
        """基本解析：四列齐全"""
        path = _make_excel(
            ["科目代码", "科目名称", "余额方向", "科目类别"],
            [
                ["1001", "库存现金", "debit", "asset"],
                ["1002", "银行存款", "debit", "asset"],
            ],
        )
        try:
            accounts, errors = parse_standard_accounts_excel(path)
            assert len(accounts) == 2
            assert len(errors) == 0
            assert accounts[0]["account_code"] == "1001"
            assert accounts[0]["account_name"] == "库存现金"
            assert accounts[0]["balance_direction"] == "debit"
            assert accounts[0]["account_category"] == "asset"
        finally:
            _cleanup(path)

    def test_missing_code_column(self):
        """缺少科目代码列时，缺代码行报错"""
        path = _make_excel(
            ["科目名称", "余额方向", "科目类别"],
            [
                ["库存现金", "debit", "asset"],
            ],
        )
        try:
            accounts, errors = parse_standard_accounts_excel(path)
            assert len(accounts) == 0
            assert len(errors) == 1
            assert "缺少科目代码" in errors[0]["reason"]
        finally:
            _cleanup(path)

    def test_missing_name_column_allowed(self):
        """缺少科目名称列，有代码仍可导入"""
        path = _make_excel(
            ["科目代码", "余额方向", "科目类别"],
            [
                ["1001", "debit", "asset"],
            ],
        )
        try:
            accounts, errors = parse_standard_accounts_excel(path)
            assert len(accounts) == 1
            assert len(errors) == 0
            assert accounts[0]["account_code"] == "1001"
            assert accounts[0]["account_name"] == ""
        finally:
            _cleanup(path)

    def test_empty_direction_and_category(self):
        """余额方向和科目类别为空仍允许导入"""
        path = _make_excel(
            ["科目代码", "科目名称", "余额方向", "科目类别"],
            [
                ["1001", "库存现金", "", ""],
                ["1002", "银行存款", "", ""],
            ],
        )
        try:
            accounts, errors = parse_standard_accounts_excel(path)
            assert len(accounts) == 2
            assert len(errors) == 0
            assert accounts[0]["balance_direction"] is None
            assert accounts[0]["account_category"] is None
        finally:
            _cleanup(path)

    def test_skip_empty_rows(self):
        """跳过完全空行"""
        path = _make_excel(
            ["科目代码", "科目名称", "余额方向", "科目类别"],
            [
                ["1001", "库存现金", "debit", "asset"],
                ["", "", "", ""],
                ["1002", "银行存款", "debit", "asset"],
            ],
        )
        try:
            accounts, errors = parse_standard_accounts_excel(path)
            assert len(accounts) == 2
        finally:
            _cleanup(path)

    def test_missing_code_with_name_reports_error(self):
        """有名称无代码的行报错"""
        path = _make_excel(
            ["科目代码", "科目名称", "余额方向", "科目类别"],
            [
                ["1001", "库存现金", "debit", "asset"],
                ["", "银行存款", "debit", "asset"],
            ],
        )
        try:
            accounts, errors = parse_standard_accounts_excel(path)
            assert len(accounts) == 1
            assert len(errors) == 1
            assert "银行存款" in errors[0]["reason"]
        finally:
            _cleanup(path)


# ── infer_hierarchy 测试 ──────────────────────────────

class TestInferHierarchy:
    """层级推断测试"""

    def test_basic_level_detection(self):
        """基本层级检测"""
        accounts = [
            {"account_code": "1", "account_name": "资产"},
            {"account_code": "1001", "account_name": "库存现金"},
            {"account_code": "1002", "account_name": "银行存款"},
        ]
        result = infer_hierarchy(accounts)
        # 代码 "1" 长度最短，是父级
        root = [a for a in result if a["account_code"] == "1"][0]
        child1 = [a for a in result if a["account_code"] == "1001"][0]
        child2 = [a for a in result if a["account_code"] == "1002"][0]

        assert root["is_leaf"] is False  # 有子级
        assert child1["is_leaf"] is True  # 无子级
        assert child2["is_leaf"] is True

        assert child1["parent_code"] == "1"
        assert child2["parent_code"] == "1"
        assert root["parent_code"] is None

    def test_multi_level_hierarchy(self):
        """多级层级"""
        accounts = [
            {"account_code": "1", "account_name": "资产"},
            {"account_code": "10", "account_name": "流动资产"},
            {"account_code": "1001", "account_name": "库存现金"},
            {"account_code": "1002", "account_name": "银行存款"},
        ]
        result = infer_hierarchy(accounts)

        root = [a for a in result if a["account_code"] == "1"][0]
        mid = [a for a in result if a["account_code"] == "10"][0]
        leaf1 = [a for a in result if a["account_code"] == "1001"][0]

        assert root["is_leaf"] is False
        assert mid["is_leaf"] is False
        assert leaf1["is_leaf"] is True
        assert mid["parent_code"] == "1"
        assert leaf1["parent_code"] == "10"

    def test_no_parent_found(self):
        """无父级可推断时保留为顶级"""
        accounts = [
            {"account_code": "5001", "account_name": "主营业务收入"},
            {"account_code": "6001", "account_name": "管理费用"},
        ]
        result = infer_hierarchy(accounts)
        for a in result:
            assert a["parent_code"] is None
            assert a["is_leaf"] is True

    def test_dotted_codes(self):
        """带点号分隔符的代码层级"""
        accounts = [
            {"account_code": "1", "account_name": "资产"},
            {"account_code": "1.1", "account_name": "流动资产"},
            {"account_code": "1.1.1", "account_name": "库存现金"},
        ]
        result = infer_hierarchy(accounts)

        leaf = [a for a in result if a["account_code"] == "1.1.1"][0]
        mid = [a for a in result if a["account_code"] == "1.1"][0]
        root = [a for a in result if a["account_code"] == "1"][0]

        assert leaf["parent_code"] == "1.1"
        assert mid["parent_code"] == "1"
        assert root["parent_code"] is None


# ── import_standard_accounts 集成测试 ─────────────────

class TestImportStandardAccounts:
    """导入标准科目全量同步集成测试"""

    @pytest.mark.asyncio
    async def test_first_import(self, db):
        """首次导入：全部新增"""
        path = _make_excel(
            ["科目代码", "科目名称", "余额方向", "科目类别"],
            [
                ["1001", "库存现金", "debit", "asset"],
                ["1002", "银行存款", "debit", "asset"],
                ["2001", "短期借款", "credit", "liability"],
            ],
        )
        try:
            result = await import_standard_accounts(db, path)
            assert result["created_count"] == 3
            assert result["updated_count"] == 0
            assert result["deactivated_count"] == 0
            assert len(result["error_rows"]) == 0

            # 验证入库
            items = await get_standard_accounts(db)
            assert len(items) == 3
            codes = {a.account_code for a in items}
            assert codes == {"1001", "1002", "2001"}

            # 验证层级
            sa_1001 = [a for a in items if a.account_code == "1001"][0]
            assert sa_1001.is_active is True
        finally:
            _cleanup(path)

    @pytest.mark.asyncio
    async def test_second_sync_update(self, db):
        """二次全量同步：更新已有科目、新增科目"""
        # 先导入第一批
        path1 = _make_excel(
            ["科目代码", "科目名称", "余额方向", "科目类别"],
            [
                ["1001", "库存现金", "debit", "asset"],
                ["1002", "银行存款", "debit", "asset"],
            ],
        )
        try:
            result1 = await import_standard_accounts(db, path1)
            assert result1["created_count"] == 2
        finally:
            _cleanup(path1)

        # 第二批：更新 1001 名称，新增 2001
        path2 = _make_excel(
            ["科目代码", "科目名称", "余额方向", "科目类别"],
            [
                ["1001", "库存现金(更新)", "debit", "asset"],
                ["1002", "银行存款", "debit", "asset"],
                ["2001", "短期借款", "credit", "liability"],
            ],
        )
        try:
            result2 = await import_standard_accounts(db, path2)
            assert result2["created_count"] == 1
            assert result2["updated_count"] == 2
            assert result2["deactivated_count"] == 0

            # 验证更新
            items = await get_standard_accounts(db)
            sa_1001 = [a for a in items if a.account_code == "1001"][0]
            assert sa_1001.account_name == "库存现金(更新)"
        finally:
            _cleanup(path2)

    @pytest.mark.asyncio
    async def test_deactivate_missing_accounts(self, db):
        """缺失旧科目自动停用"""
        # 先导入 3 个科目
        path1 = _make_excel(
            ["科目代码", "科目名称", "余额方向", "科目类别"],
            [
                ["1001", "库存现金", "debit", "asset"],
                ["1002", "银行存款", "debit", "asset"],
                ["2001", "短期借款", "credit", "liability"],
            ],
        )
        try:
            await import_standard_accounts(db, path1)
        finally:
            _cleanup(path1)

        # 第二批只含 2 个科目
        path2 = _make_excel(
            ["科目代码", "科目名称", "余额方向", "科目类别"],
            [
                ["1001", "库存现金", "debit", "asset"],
                ["2001", "短期借款", "credit", "liability"],
            ],
        )
        try:
            result = await import_standard_accounts(db, path2)
            assert result["created_count"] == 0
            assert result["updated_count"] == 2
            assert result["deactivated_count"] == 1

            # 验证停用
            all_items = await get_standard_accounts(db)
            sa_1002 = [a for a in all_items if a.account_code == "1002"][0]
            assert sa_1002.is_active is False

            # 按 is_active 筛选
            active_items = await get_standard_accounts(db, is_active=True)
            assert len(active_items) == 2
        finally:
            _cleanup(path2)

    @pytest.mark.asyncio
    async def test_duplicate_codes_block_import(self, db):
        """上传文件内重复代码阻止导入"""
        path = _make_excel(
            ["科目代码", "科目名称", "余额方向", "科目类别"],
            [
                ["1001", "库存现金", "debit", "asset"],
                ["1002", "银行存款", "debit", "asset"],
                ["1001", "库存现金(重复)", "debit", "asset"],
            ],
        )
        try:
            result = await import_standard_accounts(db, path)
            assert result["created_count"] == 0
            assert result["updated_count"] == 0
            assert len(result["error_rows"]) > 0
            assert any("重复" in e["reason"] for e in result["error_rows"])

            # 确认没有入库
            items = await get_standard_accounts(db)
            assert len(items) == 0
        finally:
            _cleanup(path)

    @pytest.mark.asyncio
    async def test_empty_direction_category_allowed(self, db):
        """余额方向/科目类别为空允许导入"""
        path = _make_excel(
            ["科目代码", "科目名称", "余额方向", "科目类别"],
            [
                ["1001", "库存现金", "", ""],
                ["2001", "短期借款", "", ""],
            ],
        )
        try:
            result = await import_standard_accounts(db, path)
            assert result["created_count"] == 2
            assert len(result["error_rows"]) == 0

            items = await get_standard_accounts(db)
            for item in items:
                assert item.balance_direction is None
                assert item.account_category is None
        finally:
            _cleanup(path)

    @pytest.mark.asyncio
    async def test_deactivated_reactivated_on_reimport(self, db):
        """被停用的科目在重新导入时恢复启用"""
        # 第一批导入
        path1 = _make_excel(
            ["科目代码", "科目名称", "余额方向", "科目类别"],
            [
                ["1001", "库存现金", "debit", "asset"],
                ["2001", "短期借款", "credit", "liability"],
            ],
        )
        try:
            await import_standard_accounts(db, path1)
        finally:
            _cleanup(path1)

        # 第二批只保留 1001，2001 被停用
        path2 = _make_excel(
            ["科目代码", "科目名称", "余额方向", "科目类别"],
            [["1001", "库存现金", "debit", "asset"]],
        )
        try:
            result2 = await import_standard_accounts(db, path2)
            assert result2["deactivated_count"] == 1
        finally:
            _cleanup(path2)

        # 验证 2001 停用
        items = await get_standard_accounts(db)
        sa_2001 = [a for a in items if a.account_code == "2001"][0]
        assert sa_2001.is_active is False

        # 第三批重新包含 2001
        path3 = _make_excel(
            ["科目代码", "科目名称", "余额方向", "科目类别"],
            [
                ["1001", "库存现金", "debit", "asset"],
                ["2001", "短期借款(恢复)", "credit", "liability"],
            ],
        )
        try:
            result3 = await import_standard_accounts(db, path3)
            assert result3["deactivated_count"] == 0
        finally:
            _cleanup(path3)

        # 验证 2001 重新启用
        items = await get_standard_accounts(db)
        sa_2001 = [a for a in items if a.account_code == "2001"][0]
        assert sa_2001.is_active is True
        assert sa_2001.account_name == "短期借款(恢复)"

    @pytest.mark.asyncio
    async def test_import_clears_old_parent_id_for_business_roots(self, db):
        """TASK-073：更新已有科目时清空旧 parent_id，避免层级残留。

        场景：直接在 DB 中构造 141101 挂在 1411 下的状态（模拟历史数据），
        再导入含 1411 + 141101 的标准科目表（BUSINESS_ROOT_ACCOUNT_CODES override），
        验证 141101.parent_id 被清空、level 变为 1。
        """
        # 直接在 DB 中构造历史残留状态：141101 挂在 1411 下
        sa_1411 = StandardAccount(
            account_code="1411", account_name="周转材料",
            level=1, is_leaf=False, is_active=True,
        )
        db.add(sa_1411)
        await db.flush()

        sa_141101 = StandardAccount(
            account_code="141101", account_name="包装物",
            level=2, is_leaf=True, is_active=True,
            parent_id=sa_1411.id,
        )
        db.add(sa_141101)
        await db.flush()

        # 确认初始状态
        assert sa_141101.parent_id == sa_1411.id

        # 导入含 1411 + 141101 的标准科目表
        path = _make_excel(
            ["科目代码", "科目名称", "余额方向", "科目类别"],
            [
                ["1411", "周转材料", "debit", "资产类"],
                ["141101", "包装物", "debit", "资产类"],
            ],
        )
        try:
            result = await import_standard_accounts(db, path)
            assert result["updated_count"] == 2
        finally:
            _cleanup(path)

        # 验证更新后 141101.parent_id 被清空
        await db.refresh(sa_141101)
        assert sa_141101.parent_id is None, (
            "更新已有科目时旧 parent_id 残留，141101 应为顶级科目"
        )
        assert sa_141101.level == 1


# ── get_standard_accounts 筛选测试 ────────────────────

class TestQueryFilters:
    """查询筛选测试"""

    @pytest.mark.asyncio
    async def test_filter_by_is_active(self, db):
        """按启用状态筛选"""
        path = _make_excel(
            ["科目代码", "科目名称", "余额方向", "科目类别"],
            [
                ["1001", "库存现金", "debit", "asset"],
                ["2001", "短期借款", "credit", "liability"],
            ],
        )
        try:
            await import_standard_accounts(db, path)
        finally:
            _cleanup(path)

        # 停用一个
        items = await get_standard_accounts(db)
        items[0].is_active = False
        await db.flush()

        active = await get_standard_accounts(db, is_active=True)
        inactive = await get_standard_accounts(db, is_active=False)
        assert len(active) == 1
        assert len(inactive) == 1

    @pytest.mark.asyncio
    async def test_filter_by_category(self, db):
        """按科目类别筛选"""
        path = _make_excel(
            ["科目代码", "科目名称", "余额方向", "科目类别"],
            [
                ["1001", "库存现金", "debit", "asset"],
                ["2001", "短期借款", "credit", "liability"],
            ],
        )
        try:
            await import_standard_accounts(db, path)
        finally:
            _cleanup(path)

        asset_items = await get_standard_accounts(db, account_category="asset")
        assert len(asset_items) == 1
        assert asset_items[0].account_code == "1001"

    @pytest.mark.asyncio
    async def test_filter_by_direction(self, db):
        """按余额方向筛选"""
        path = _make_excel(
            ["科目代码", "科目名称", "余额方向", "科目类别"],
            [
                ["1001", "库存现金", "debit", "asset"],
                ["2001", "短期借款", "credit", "liability"],
            ],
        )
        try:
            await import_standard_accounts(db, path)
        finally:
            _cleanup(path)

        debit_items = await get_standard_accounts(db, balance_direction="debit")
        assert len(debit_items) == 1
        assert debit_items[0].account_code == "1001"

    @pytest.mark.asyncio
    async def test_filter_by_keyword(self, db):
        """按关键词搜索"""
        path = _make_excel(
            ["科目代码", "科目名称", "余额方向", "科目类别"],
            [
                ["1001", "库存现金", "debit", "asset"],
                ["1002", "银行存款", "debit", "asset"],
                ["2001", "短期借款", "credit", "liability"],
            ],
        )
        try:
            await import_standard_accounts(db, path)
        finally:
            _cleanup(path)

        # 按代码搜
        result1 = await get_standard_accounts(db, keyword="1001")
        assert len(result1) == 1
        assert result1[0].account_code == "1001"

        # 按名称模糊搜
        result2 = await get_standard_accounts(db, keyword="银行")
        assert len(result2) == 1
        assert result2[0].account_code == "1002"

        # 关键词包含在名称中
        result3 = await get_standard_accounts(db, keyword="借款")
        assert len(result3) == 1
        assert result3[0].account_code == "2001"


# ── 内置种子数据测试 — TASK-049 ────────────────────

class TestSeedFromResource:
    """内置 JSON 资源加载与初始化测试"""

    def test_load_seed_from_resource(self):
        """内置资源可加载，返回非空列表"""
        from app.services.standard_account_service import load_seed_accounts_from_resource

        accounts = load_seed_accounts_from_resource()
        assert len(accounts) > 0, "内置种子数据不应为空"
        # 每个条目必须有 account_code 和 account_name
        for a in accounts:
            assert a["account_code"], f"缺少 account_code: {a}"
            assert "account_name" in a, f"缺少 account_name: {a}"
        # 验证至少有一条已知科目
        codes = {a["account_code"] for a in accounts}
        assert "1001" in codes, "应包含科目代码 1001（库存现金）"
        assert "1002" in codes, "应包含科目代码 1002（银行存款）"

    def test_load_seed_direction_normalized(self):
        """种子数据中的余额方向应为 debit/credit 或 None"""
        from app.services.standard_account_service import load_seed_accounts_from_resource

        accounts = load_seed_accounts_from_resource()
        for a in accounts:
            d = a.get("balance_direction")
            assert d is None or d in ("debit", "credit"), \
                f"科目 {a['account_code']} 的余额方向无效: {d}"

    @pytest.mark.asyncio
    async def test_seed_into_empty_db(self, db):
        """空数据库初始化标准科目"""
        from app.services.standard_account_service import seed_standard_accounts

        result = await seed_standard_accounts(db)
        assert result["created_count"] > 0
        assert result["skipped"] is False

        # 验证入库
        items = await get_standard_accounts(db)
        assert len(items) == result["created_count"]
        assert all(item.is_active for item in items)

    @pytest.mark.asyncio
    async def test_seed_skips_when_data_exists(self, db):
        """数据库已有数据时应同步缺失内置科目，不覆盖已有数据。"""
        from app.services.standard_account_service import seed_standard_accounts

        # 先手动插入一条
        sa = StandardAccount(
            account_code="9999",
            account_name="测试科目",
            is_active=True,
        )
        db.add(sa)
        await db.flush()

        # 执行初始化 — 现在会同步缺失内置科目
        result = await seed_standard_accounts(db)
        assert result["skipped"] is True
        # sync 会创建缺失的 seed 科目
        assert result["created_count"] >= 1

        # 确认原来的自定义科目没被删除
        items = await get_standard_accounts(db)
        codes = {i.account_code for i in items}
        assert "9999" in codes

    @pytest.mark.asyncio
    async def test_seed_accounts_have_hierarchy(self, db):
        """种子数据入库后应有层级关系"""
        from app.services.standard_account_service import seed_standard_accounts

        await seed_standard_accounts(db)

        items = await get_standard_accounts(db)
        # 至少有一些科目有父级
        has_parent = [a for a in items if a.parent_id is not None]
        assert len(has_parent) > 0, "种子数据应有层级关系"

        # 至少有一些父级科目（is_leaf=False）
        parents = [a for a in items if not a.is_leaf]
        assert len(parents) > 0, "种子数据应有父级科目"


class TestPublicUploadNotExposed:
    """公开上传接口不可用测试"""

    def test_import_endpoint_not_in_router(self):
        """验证标准科目路由不再包含 POST /import"""
        from app.api.standard_accounts import router
        routes = {r.path: r.methods for r in router.routes}
        # 不应有 /import 路径
        assert "/import" not in routes, (
            "POST /standard-accounts/import 不应注册为公开路由"
        )
        # 应有查询路由（FastAPI 会把 prefix 拼到 route.path 里）
        assert "/standard-accounts" in routes, f"GET /standard-accounts 应存在，当前路由: {routes}"
        assert "/standard-accounts/{account_id}" in routes, f"GET /standard-accounts/{{id}} 应存在，当前路由: {routes}"


# ── TASK-072：业务展示层级 override 与已有 DB 修复 ──

class TestBusinessRootHierarchyOverrides:
    """141101/141102/660201 必须作为一级科目（parent_code=None, level=1, is_leaf=True）。"""

    def test_business_root_account_overrides(self):
        from app.services.standard_account_service import infer_hierarchy

        accounts = [
            {"account_code": "1411", "account_name": "周转材料"},
            {"account_code": "141101", "account_name": "包装物"},
            {"account_code": "141102", "account_name": "低值易耗品"},
            {"account_code": "6602", "account_name": "减：管理费用"},
            {"account_code": "660201", "account_name": "减：研发费用"},
            {"account_code": "1001", "account_name": "资产"},
            {"account_code": "1001001", "account_name": "库存现金"},
        ]

        result = infer_hierarchy(accounts)
        by_code = {a["account_code"]: a for a in result}

        assert by_code["141101"]["parent_code"] is None
        assert by_code["141101"]["level"] == 1
        assert by_code["141101"]["is_leaf"] is True

        assert by_code["141102"]["parent_code"] is None
        assert by_code["141102"]["level"] == 1
        assert by_code["141102"]["is_leaf"] is True

        assert by_code["1411"]["parent_code"] is None
        assert by_code["1411"]["level"] == 1
        # 141101/141102 被提为一级后，1411 没有子级，应为末级
        assert by_code["1411"]["is_leaf"] is True

        assert by_code["660201"]["parent_code"] is None
        assert by_code["660201"]["level"] == 1
        assert by_code["660201"]["is_leaf"] is True

        assert by_code["6602"]["parent_code"] is None
        assert by_code["6602"]["level"] == 1
        # 660201 被提为一级后，6602 没有子级，应为末级
        assert by_code["6602"]["is_leaf"] is True

        # 正常代码前缀层级不能被破坏
        assert by_code["1001001"]["parent_code"] == "1001"
        assert by_code["1001"]["is_leaf"] is False

    @pytest.mark.asyncio
    async def test_seed_repairs_existing_business_root_parent_ids(self, db):
        from app.services.standard_account_service import seed_standard_accounts

        parent_1411 = StandardAccount(account_code="1411", account_name="周转材料", level=1, is_leaf=False)
        parent_6602 = StandardAccount(account_code="6602", account_name="减：管理费用", level=1, is_leaf=False)
        db.add_all([parent_1411, parent_6602])
        await db.flush()

        packaging = StandardAccount(
            account_code="141101",
            account_name="包装物",
            level=2,
            is_leaf=True,
            parent_id=parent_1411.id,
        )
        consumables = StandardAccount(
            account_code="141102",
            account_name="低值易耗品",
            level=2,
            is_leaf=True,
            parent_id=parent_1411.id,
        )
        rd = StandardAccount(
            account_code="660201",
            account_name="减：研发费用",
            level=2,
            is_leaf=True,
            parent_id=parent_6602.id,
        )
        db.add_all([packaging, consumables, rd])
        await db.flush()

        result = await seed_standard_accounts(db)
        assert result["skipped"] is True
        # sync 或 repair 会修正层级（sync 先跑，可能已经修正了，repaired_count 可能为 0）

        await db.refresh(packaging)
        await db.refresh(consumables)
        await db.refresh(rd)
        for sa in (packaging, consumables, rd):
            assert sa.parent_id is None
            assert sa.level == 1
            assert sa.is_leaf is True

    @pytest.mark.asyncio
    async def test_repair_function_directly_fixes_existing_root_parent_ids(self, db):
        from app.services.standard_account_service import repair_builtin_standard_account_hierarchy

        parent_1411 = StandardAccount(account_code="1411", account_name="周转材料", level=1, is_leaf=False)
        db.add(parent_1411)
        await db.flush()

        packaging = StandardAccount(
            account_code="141101",
            account_name="包装物",
            level=2,
            is_leaf=True,
            parent_id=parent_1411.id,
        )
        db.add(packaging)
        await db.flush()

        result = await repair_builtin_standard_account_hierarchy(db)
        assert result["updated_count"] >= 1
        await db.refresh(packaging)
        assert packaging.parent_id is None
        assert packaging.level == 1
        assert packaging.is_leaf is True


# ── TASK-075：内置标准科目同步到已有 DB ──

class TestSeedSync:
    """seed_standard_accounts() 在已有 DB 时应同步缺失内置科目。"""

    @pytest.mark.asyncio
    async def test_seed_existing_db_recomputes_rd_development_child_levels(self, db):
        """已有库中 170401/170402 的 level 应被重算为 2。"""
        from sqlalchemy import select
        from app.services.standard_account_service import seed_standard_accounts

        db.add(StandardAccount(
            account_code="1704",
            account_name="开发支出",
            balance_direction="debit",
            account_category="资产类",
            level=1,
            is_leaf=True,
            is_active=True,
        ))
        await db.flush()

        await seed_standard_accounts(db)
        rows = (await db.execute(select(StandardAccount))).scalars().all()
        by_code = {r.account_code: r for r in rows}

        assert by_code["1704"].level == 1
        assert by_code["1704"].is_leaf is False
        assert by_code["170401"].parent_id == by_code["1704"].id
        assert by_code["170402"].parent_id == by_code["1704"].id
        assert by_code["170401"].level == 2
        assert by_code["170402"].level == 2

    @pytest.mark.asyncio
    async def test_seed_sync_preserves_existing_accounts(self, db):
        """同步不删除用户库里已有但 seed 缺失的科目。"""
        from app.services.standard_account_service import seed_standard_accounts

        # 先插入一个不在 seed 里的自定义科目
        db.add(StandardAccount(
            account_code="999999",
            account_name="自定义测试科目",
            is_active=True,
        ))
        await db.flush()

        result = await seed_standard_accounts(db)
        # 应该创建了新 seed 科目
        assert result["created_count"] >= 1

        # 自定义科目仍在
        rows = (await db.execute(select(StandardAccount))).scalars().all()
        by_code = {r.account_code: r for r in rows}
        assert "999999" in by_code
        assert by_code["999999"].account_name == "自定义测试科目"
