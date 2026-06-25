# TASK-072：修复查询页错层级、错匹配、行换行和导入数据删除

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` and implement this task task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复用户截图中的 5 个问题：展开客户明细行过高/自动换行，包装物和低值易耗品仍显示在周转材料下面，在建工程被归入在建工程减值准备，管理费用/研发费用层级和匹配错位，数据查询页缺少删除导入数据按钮。

**Architecture:** 这不是单纯 UI 问题。必须同时修标准科目主数据层级、科目匹配冲突规则、查询树展示、前端表格布局和批次删除接口。先写后端失败测试确认真实归类和树形结构，再改 UI。

**Tech Stack:** FastAPI + SQLAlchemy async + Pydantic；Vue 3 + Element Plus；pytest；真实测试文件：`D:/NAS/xiaochen/李辉辉项目组/SynologyDrive/汇达228股改审计/1.账套/aglq710-科目余额表 20251231.xlsx`。

---

## 用户反馈

截图和反馈对应 5 个具体缺陷：

1. 数据查询页展开客户明细后，行高度过高，科目名称列明明横向空间够，却自动换行。
2. `包装物` 和 `低值易耗品` 仍显示在 `周转材料` 下面；用户明确要求它们是一级科目，不要作为 `1411 周转材料` 的子级展示。
3. 客户 `160402 在建工程_生产线` 被归入 `160402 减：在建工程-减值准备`，应归入 `160401 在建工程-原值`。
4. `管理费用` / `研发费用` 层级错位。截图里 `660201 减：研发费用` 展示在 `6602 减：管理费用` 下；用户不接受。两者应作为独立一级展示线。同时客户名称含 `管理费用` 的行不得因代码命中 `660201` 而归入研发费用。
5. 数据查询页需要新增删除按钮，删除已经导入的科目余额表数据。

---

## 当前已知代码位置

重点文件：

- `backend/app/services/standard_account_service.py`
  - `infer_hierarchy()` 目前按科目代码前缀推断父级，导致 `141101` 自动挂到 `1411`、`660201` 自动挂到 `6602`。
  - `seed_standard_accounts()` 当前当库里已有标准科目时直接跳过，修改 seed 不会修复用户本地已有 DB。
  - `import_standard_accounts()` 更新已有科目时，如果新 `parent_code=None`，需要显式清空旧 `parent_id`，否则旧父级会残留。

- `backend/app/services/client_account_mapping_service.py`
  - `_check_code_match_name_conflict()` 当前只判断客户名称锚点是否包含在标准科目 canonical 名称中。
  - 这个规则太宽：客户 `在建工程_生产线` 的锚点 `在建工程` 被认为包含在 `在建工程减值准备` 中，所以 `160402` 精确代码会被当成安全候选。
  - 对带 `减：/减值准备/坏账准备/跌价准备/累计折旧/累计摊销` 的备抵/减值类标准科目，应要求客户名称也明确包含对应负向词，否则代码相同也必须降级为冲突候选。

- `backend/app/services/standard_trial_balance_service.py`
  - `get_tree()` 按 `StandardAccount.parent_id` 构树。
  - 如果标准科目 `parent_id` 错，查询页一定错。
  - 这里应新增删除批次服务，例如 `delete_batch(db, batch_id) -> dict`。

- `backend/app/api/standard_trial_balances.py`
  - 目前只有批次列表、树形视图、明细列表接口。
  - 需要新增 `DELETE /standard-trial-balances/batches/{batch_id}`。

- `frontend/src/views/DataView.vue`
  - 当前 `科目代码` 和 `科目名称 / 客户明细` 是 fixed 列。
  - 客户明细行把“客户标签、客户名称、标准标签”塞进同一个 320px frozen 列，且 `.account-name-cell { white-space: normal; }`，所以自动换行。
  - 需要拆出标准科目列或调整布局，禁止客户明细单元格换行。
  - 需要新增删除当前选中批次按钮。

- `frontend/src/types/index.ts`
  - 需要新增删除接口响应类型，或在页面里局部定义。

---

## 重要方向变更

本任务覆盖 `TASK-071` 的旧展示假设。

旧方向允许：

```text
1411 周转材料
  141101 包装物
  141102 低值易耗品
```

用户现在明确否定这个展示。新的验收口径是：

```text
1411   周转材料        一级科目
141101 包装物          一级科目
141102 低值易耗品      一级科目
6602   减：管理费用    一级科目
660201 减：研发费用    一级科目
```

注意：这不是把客户科目代码改成标准代码，也不是删除 `1411`。这是标准科目展示层级和匹配目标的业务修正。

---

## 任务 1：修标准科目层级推断和已有 DB 修复

**目标：**

- `141101 包装物` 必须是一级科目，`parent_id is None`。
- `141102 低值易耗品` 必须是一级科目，`parent_id is None`。
- `660201 减：研发费用` 必须是一级科目，`parent_id is None`。
- `1411 周转材料` 和 `6602 减：管理费用` 仍是一级科目。
- 正常父子层级不能全盘禁用，例如测试里的 `1001 -> 1001001` 仍应能推断。
- 用户已有数据库中已经错误挂父级的标准科目，启动或服务调用后也要被修正，不允许只修新 seed。

**建议实现：**

在 `backend/app/services/standard_account_service.py` 增加业务层级覆盖表。

```python
BUSINESS_ROOT_ACCOUNT_CODES = {
    "141101",  # 包装物：用户要求一级展示，不挂周转材料
    "141102",  # 低值易耗品：用户要求一级展示，不挂周转材料
    "660201",  # 研发费用：利润表独立展示线，不挂管理费用
}


def _apply_business_hierarchy_overrides(accounts: list[dict]) -> None:
    """修正标准科目业务展示层级。

    不能只靠代码前缀判断父子关系：部分报表展示行虽然代码有前缀关系，
    但业务上是并列一级项目。
    """
    for account in accounts:
        code = account.get("account_code")
        if code in BUSINESS_ROOT_ACCOUNT_CODES:
            account["parent_code"] = None
            account["level"] = 1

    children_by_parent: dict[str, int] = {}
    for account in accounts:
        parent_code = account.get("parent_code")
        if parent_code:
            children_by_parent[parent_code] = children_by_parent.get(parent_code, 0) + 1

    for account in accounts:
        code = account.get("account_code")
        account["is_leaf"] = children_by_parent.get(code, 0) == 0
```

在 `infer_hierarchy()` 中：

- 先按现有逻辑算 `parent_code`；
- 调用 `_apply_business_hierarchy_overrides(accounts)`；
- 不要再用 `other.startswith(code)` 直接算 `is_leaf`，否则 `1411` 仍会因为 `141101` 前缀而被标为非末级；
- `is_leaf` 应基于最终 `parent_code` 关系重算。

在 `import_standard_accounts()` 和 `seed_standard_accounts()` 中：

- 更新/创建标准科目后，补 `parent_id` 之前，先清空本次上传/种子涉及科目的 `parent_id`：

```python
for a in accounts:
    code_to_id[a["account_code"]].parent_id = None
```

- 然后只对 `parent_code` 非空的账号设置父级；
- 否则旧 DB 里原来的 `parent_id` 会残留。

再新增一个幂等修复函数，修用户已有数据库：

```python
async def repair_builtin_standard_account_hierarchy(db: AsyncSession) -> dict:
    """修复内置标准科目的业务展示层级。

    seed_standard_accounts() 在已有数据时会跳过，所以这里负责把历史 DB 中
    错误的 parent_id 修正回来。
    """
    result = await db.execute(
        select(StandardAccount).where(
            StandardAccount.account_code.in_(BUSINESS_ROOT_ACCOUNT_CODES)
        )
    )
    accounts = list(result.scalars().all())
    changed = 0
    for account in accounts:
        if account.parent_id is not None or account.level != 1 or not account.is_leaf:
            account.parent_id = None
            account.level = 1
            account.is_leaf = True
            changed += 1
    await db.flush()
    return {"updated_count": changed}
```

在 `seed_standard_accounts()` 中，即使已有数据而跳过创建，也调用这个修复函数：

```python
if count and count > 0:
    repair = await repair_builtin_standard_account_hierarchy(db)
    logger.info("标准科目表已有 %d 条数据，跳过初始化；层级修复 %d 条", count, repair["updated_count"])
    return {"created_count": 0, "skipped": True, "repaired_count": repair["updated_count"]}
```

**必须新增/修改测试：**

`backend/tests/test_standard_account_import.py`

新增测试：

```python
def test_business_root_account_overrides():
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
    assert by_code["1411"]["is_leaf"] is True

    assert by_code["660201"]["parent_code"] is None
    assert by_code["660201"]["level"] == 1
    assert by_code["660201"]["is_leaf"] is True

    assert by_code["6602"]["parent_code"] is None
    assert by_code["6602"]["level"] == 1
    assert by_code["6602"]["is_leaf"] is True

    # 正常代码前缀层级不能被破坏
    assert by_code["1001001"]["parent_code"] == "1001"
    assert by_code["1001"]["is_leaf"] is False
```

新增 async 测试：

```python
@pytest.mark.asyncio
async def test_seed_repairs_existing_business_root_parent_ids(db):
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
    rd = StandardAccount(
        account_code="660201",
        account_name="减：研发费用",
        level=2,
        is_leaf=True,
        parent_id=parent_6602.id,
    )
    db.add_all([packaging, rd])
    await db.flush()

    result = await seed_standard_accounts(db)
    assert result["skipped"] is True
    assert result["repaired_count"] >= 2

    await db.refresh(packaging)
    await db.refresh(rd)
    assert packaging.parent_id is None
    assert packaging.level == 1
    assert packaging.is_leaf is True
    assert rd.parent_id is None
    assert rd.level == 1
    assert rd.is_leaf is True
```

---

## 任务 2：修 `在建工程` 被归入减值准备的匹配规则

**目标：**

这些必须自动安全匹配到 `160401 在建工程-原值`：

```text
160402 在建工程
160402 在建工程_生产线
160402 在建工程-生产线
160402 工程项目A
160402 装修费用
```

这些才允许匹配到 `160402 减：在建工程-减值准备`：

```text
160402 在建工程减值准备
160402 在建工程_减值准备
160402 减：在建工程-减值准备
```

**根因：**

`_check_code_match_name_conflict()` 目前只判断 `anchor_norm in sa_canonical`。  
`在建工程` 是 `在建工程减值准备` 的子串，所以代码相同 `160402` 会被误认为安全。

**建议实现：**

在 `backend/app/services/client_account_mapping_service.py` 增加负向/备抵词判断。

```python
NEGATIVE_RESERVE_TOKENS = (
    "减值准备",
    "资产减值损失",
    "坏账准备",
    "跌价准备",
    "累计折旧",
    "累计摊销",
    "减值",
    "准备",
)


def _has_negative_reserve_semantics(name: str | None) -> bool:
    canonical = _canonical_name(name)
    if not canonical:
        return False
    return any(_normalize_name(token) in canonical for token in NEGATIVE_RESERVE_TOKENS)
```

在 `_check_code_match_name_conflict(sa, client_name)` 中，在 `anchor_norm in sa_canonical` 判定安全之前加入：

```python
if _has_negative_reserve_semantics(sa.account_name) and not _has_negative_reserve_semantics(client_name):
    return {
        "score": 0.72,
        "warning": (
            f"代码相同但标准科目为备抵/减值类「{sa.account_name}」，"
            f"客户名称「{client_name}」未体现减值/准备/累计折旧等含义，请勿自动归入"
        ),
    }
```

再让 `construction_in_progress` 语义组和名称锚点继续提供 `160401` 安全候选。

**必须新增测试：**

`backend/tests/test_client_account_mapping_service.py`

```python
@pytest.mark.asyncio
async def test_construction_in_progress_same_code_not_impairment(db):
    original = _make_standard_account("160401", "在建工程-原值")
    impairment = _make_standard_account("160402", "减：在建工程-减值准备")
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
        candidates = await recommend_mappings(
            db,
            [{"client_account_code": code, "client_account_name": name}],
        )
        cands = candidates[0]["candidates"]
        safe_original = [
            c for c in cands
            if c["standard_account_code"] == "160401"
            and c["warning"] is None
            and c["score"] >= 0.9
        ]
        bad_impairment = [
            c for c in cands
            if c["standard_account_code"] == "160402"
            and c["warning"] is None
            and c["score"] >= 0.9
        ]
        assert safe_original, f"{code} {name} 应安全匹配 160401，实际: {cands}"
        assert not bad_impairment, f"{code} {name} 不得安全匹配 160402，实际: {cands}"


@pytest.mark.asyncio
async def test_construction_impairment_still_matches_impairment(db):
    original = _make_standard_account("160401", "在建工程-原值")
    impairment = _make_standard_account("160402", "减：在建工程-减值准备")
    db.add_all([original, impairment])
    await db.flush()

    candidates = await recommend_mappings(
        db,
        [{"client_account_code": "160402", "client_account_name": "在建工程减值准备"}],
    )
    safe_impairment = [
        c for c in candidates[0]["candidates"]
        if c["standard_account_code"] == "160402"
        and c["warning"] is None
        and c["score"] >= 0.9
    ]
    assert safe_impairment, candidates[0]["candidates"]
```

---

## 任务 3：修管理费用/研发费用层级和名称冲突

**目标：**

- `6602 减：管理费用` 是一级科目。
- `660201 减：研发费用` 是一级科目。
- 客户 `660201 管理费用_办公费` 不得因为代码精确命中 `660201` 而归入研发费用，应安全候选到 `6602 减：管理费用`。
- 客户 `660401 研发费用`、`660201 研发费用_工资` 仍应能安全匹配 `660201 减：研发费用`。

**必须新增测试：**

`backend/tests/test_client_account_mapping_service.py`

```python
@pytest.mark.asyncio
async def test_management_expense_name_wins_over_660201_code(db):
    mgmt = _make_standard_account("6602", "减：管理费用")
    rd = _make_standard_account("660201", "减：研发费用")
    db.add_all([mgmt, rd])
    await db.flush()

    candidates = await recommend_mappings(
        db,
        [{"client_account_code": "660201", "client_account_name": "管理费用_办公费"}],
    )
    cands = candidates[0]["candidates"]
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
    assert safe_mgmt, f"管理费用_办公费 应安全匹配 6602，实际: {cands}"
    assert not bad_rd, f"管理费用_办公费 不得安全匹配 660201 研发费用，实际: {cands}"


@pytest.mark.asyncio
async def test_research_expense_still_matches_660201(db):
    mgmt = _make_standard_account("6602", "减：管理费用")
    rd = _make_standard_account("660201", "减：研发费用")
    db.add_all([mgmt, rd])
    await db.flush()

    for code, name in [
        ("660401", "研发费用"),
        ("660201", "研发费用_工资"),
        ("660201", "研发支出_费用化支出"),
    ]:
        candidates = await recommend_mappings(
            db,
            [{"client_account_code": code, "client_account_name": name}],
        )
        safe_rd = [
            c for c in candidates[0]["candidates"]
            if c["standard_account_code"] == "660201"
            and c["warning"] is None
            and c["score"] >= 0.9
        ]
        assert safe_rd, f"{code} {name} 应安全匹配 660201，实际: {candidates[0]['candidates']}"
```

---

## 任务 4：修查询树结构验收

**目标：**

在 `/standard-trial-balances/tree` 中：

- `1411`、`141101`、`141102` 都应作为根节点出现在 `items` 顶层。
- `141101` 的客户明细挂在 `141101` 下，不在 `1411` 下。
- `141102` 的客户明细挂在 `141102` 下，不在 `1411` 下。
- `6602` 和 `660201` 都应作为根节点出现在 `items` 顶层。
- `160402 在建工程_生产线` 经过重新导入后，客户明细应挂在 `160401 在建工程-原值` 下，不在 `160402 减：在建工程-减值准备` 下。

**修改测试：**

`backend/tests/test_standard_trial_balance_view.py`

已有 TASK-071 测试若仍写死 `1411 -> 141101 -> entry`，必须更新为新的一级展示口径，不能删除测试逃避。

新增/改写：

```python
@pytest.mark.asyncio
async def test_packaging_consumables_are_root_nodes_not_under_turnover_materials(db):
    turnover = await _create_account(db, "1411", "周转材料", level=1, is_leaf=True)
    packaging = await _create_account(db, "141101", "包装物", level=1, is_leaf=True)
    consumables = await _create_account(db, "141102", "低值易耗品", level=1, is_leaf=True)
    batch = await _create_batch(db)

    await _create_entry(
        db,
        batch.id,
        packaging,
        client_account_code="1411",
        client_account_name="包装物_纸箱",
        ending_debit=Decimal("100"),
    )
    await _create_entry(
        db,
        batch.id,
        consumables,
        client_account_code="1411",
        client_account_name="低值易耗品_工具",
        ending_debit=Decimal("200"),
    )

    nodes, total = await get_tree(db, batch_id=batch.id, only_with_amounts=True)
    root_codes = [node["account_code"] for node in nodes]
    assert "141101" in root_codes
    assert "141102" in root_codes
    assert "1411" not in root_codes or not any(
        child.get("client_account_name") in {"包装物_纸箱", "低值易耗品_工具"}
        for node in nodes if node["account_code"] == "1411"
        for child in node.get("children", [])
    )

    packaging_node = next(node for node in nodes if node["account_code"] == "141101")
    consumables_node = next(node for node in nodes if node["account_code"] == "141102")
    assert any(child["node_type"] == "entry" and child["client_account_name"] == "包装物_纸箱" for child in packaging_node["children"])
    assert any(child["node_type"] == "entry" and child["client_account_name"] == "低值易耗品_工具" for child in consumables_node["children"])
```

新增：

```python
@pytest.mark.asyncio
async def test_management_and_research_are_root_nodes(db):
    mgmt = await _create_account(db, "6602", "减：管理费用", level=1, is_leaf=True)
    rd = await _create_account(db, "660201", "减：研发费用", level=1, is_leaf=True)
    batch = await _create_batch(db)
    await _create_entry(db, batch.id, mgmt, client_account_code="6602", client_account_name="管理费用", current_debit=Decimal("10"))
    await _create_entry(db, batch.id, rd, client_account_code="6604", client_account_name="研发费用", current_debit=Decimal("20"))

    nodes, _ = await get_tree(db, batch_id=batch.id, only_with_amounts=True)
    root_codes = [node["account_code"] for node in nodes]
    assert "6602" in root_codes
    assert "660201" in root_codes
    mgmt_node = next(node for node in nodes if node["account_code"] == "6602")
    assert not any(child["account_code"] == "660201" for child in mgmt_node.get("children", []))
```

---

## 任务 5：修数据查询页 UI：明细行不换行、冻结代码和名称、金额不省略

**目标：**

- 展开树形明细时，客户明细行保持一行，不自动换成 2-3 行。
- 左侧冻结列仍是：
  - `科目代码`
  - `科目名称 / 客户明细`
- 不要把“标准：xxx”继续塞进冻结的名称列里导致换行。
- 建议新增单独的 `标准科目` 列，非冻结，宽度 260-320。
- 大金额列不省略，表格可横向滚动。

**建议改法：**

`frontend/src/views/DataView.vue`

把当前名称列里的标准 tag 拆出去：

```vue
<el-table-column
  prop="account_name"
  label="科目名称 / 客户明细"
  width="360"
  fixed="left"
  show-overflow-tooltip
>
  <template #default="{ row }">
    <span v-if="row.node_type === 'entry'" class="name-inline" :title="customerTitle(row)">
      <el-tag size="small" type="info" effect="plain">客户</el-tag>
      <span class="single-line-text">{{ clientLabel(row) }}</span>
    </span>
    <span v-else class="single-line-text" :title="`${row.account_code || ''} ${row.account_name || ''}`">
      {{ row.account_name }}
    </span>
  </template>
</el-table-column>

<el-table-column
  label="标准科目"
  width="280"
  show-overflow-tooltip
>
  <template #default="{ row }">
    <span v-if="row.node_type === 'entry'" class="standard-inline" :title="standardTitle(row)">
      {{ standardLabel(row) }}
    </span>
    <span v-else class="muted">-</span>
  </template>
</el-table-column>
```

CSS 要求：

```css
.name-inline,
.standard-inline {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  white-space: nowrap;
  overflow: hidden;
}

.single-line-text {
  display: inline-block;
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
}

.amount-cell {
  display: inline-block;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
```

更新表格最小宽度：

```css
/* fixed 150 + fixed 360 + 标准科目 280 + 方向 70 + 6 金额列*150 + 条目数/操作 */
.trial-balance-tree-table :deep(.el-table__inner-wrapper) {
  min-width: 1760px;
}
```

不要使用 `.account-name-cell { white-space: normal; }`。

**视觉验收：**

必须用浏览器实际打开 `/data/view` 或对应路由，在 1366x768 和 1920x1080 下检查：

- 展开 `1602/1411/6602` 附近明细后，客户明细行不超过一行高度。
- `科目代码` 和 `科目名称 / 客户明细` 两列冻结，横向滚动时仍固定。
- `期末贷方余额` 可见，金额不被省略成 `...`。
- `标准科目` 列显示 entry 行对应标准归属，例如 `160401 在建工程-原值`。

---

## 任务 6：数据查询页新增删除导入数据按钮

**目标：**

用户可以在数据查询页删除当前选中的导入批次，删除后：

- `standard_trial_balance_entries` 中该批次的标准化明细被删除；
- `standard_trial_balance_raw_rows` 中该批次的原始行快照被删除；
- `standard_trial_balance_import_batches` 中该批次被删除；
- 不删除 `standard_accounts`；
- 不删除 `client_account_mappings` 历史经验；
- 前端刷新批次列表和树形数据；
- 当前选中批次被删后，自动选中最新剩余批次；如果没有剩余批次，则显示空状态。

**后端实现：**

`backend/app/services/standard_trial_balance_service.py`

新增：

```python
from sqlalchemy import delete, update
from app.models.standard_trial_balance_raw_row import StandardTrialBalanceRawRow


async def delete_batch(db: AsyncSession, batch_id: uuid.UUID) -> dict | None:
    batch = await db.get(StandardTrialBalanceImportBatch, batch_id)
    if batch is None:
        return None

    entries_result = await db.execute(
        select(func.count(StandardTrialBalanceEntry.id)).where(
            StandardTrialBalanceEntry.batch_id == batch_id
        )
    )
    entry_count = entries_result.scalar() or 0

    raw_result = await db.execute(
        select(func.count(StandardTrialBalanceRawRow.id)).where(
            StandardTrialBalanceRawRow.batch_id == batch_id
        )
    )
    raw_row_count = raw_result.scalar() or 0

    await db.execute(
        delete(StandardTrialBalanceEntry).where(StandardTrialBalanceEntry.batch_id == batch_id)
    )

    # SQLite/自引用外键下，先清空本批次 raw row 的 parent_raw_row_id，再删 raw rows。
    await db.execute(
        update(StandardTrialBalanceRawRow)
        .where(StandardTrialBalanceRawRow.batch_id == batch_id)
        .values(parent_raw_row_id=None)
    )
    await db.execute(
        delete(StandardTrialBalanceRawRow).where(StandardTrialBalanceRawRow.batch_id == batch_id)
    )

    await db.delete(batch)
    await db.flush()

    return {
        "batch_id": batch_id,
        "deleted_entries": entry_count,
        "deleted_raw_rows": raw_row_count,
        "deleted_batches": 1,
    }
```

`backend/app/api/standard_trial_balances.py`

新增：

```python
from fastapi import HTTPException
from app.services.standard_trial_balance_service import delete_batch


@router.delete("/batches/{batch_id}")
async def delete_imported_batch(
    batch_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await delete_batch(db, batch_id=batch_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"批次 {batch_id} 不存在")
    await db.commit()
    return result
```

如果项目已有事务统一提交机制，按项目现有模式处理；但测试必须确认删除真正落库。

**后端测试：**

`backend/tests/test_standard_trial_balance_view.py`

```python
@pytest.mark.asyncio
async def test_delete_batch_removes_entries_and_raw_rows_but_keeps_standard_accounts(db):
    sa = await _create_account(db, "1001", "库存现金", level=1, is_leaf=True)
    batch = await _create_batch(db, file_name="delete_me.xlsx")
    raw = StandardTrialBalanceRawRow(
        batch_id=batch.id,
        row_index=0,
        raw_values={"科目代码": "1001"},
        client_account_code="1001",
        client_account_name="库存现金",
        is_leaf=True,
        mapping_status="mapped",
    )
    db.add(raw)
    await db.flush()
    await _create_entry(db, batch.id, sa, raw_row_id=raw.id, ending_debit=Decimal("1"))

    result = await delete_batch(db, batch.id)
    assert result["deleted_entries"] == 1
    assert result["deleted_raw_rows"] == 1
    assert result["deleted_batches"] == 1

    assert await db.get(StandardTrialBalanceImportBatch, batch.id) is None
    assert await db.get(StandardTrialBalanceRawRow, raw.id) is None

    entries = await db.execute(
        select(StandardTrialBalanceEntry).where(StandardTrialBalanceEntry.batch_id == batch.id)
    )
    assert entries.scalars().all() == []
    assert await db.get(StandardAccount, sa.id) is not None
```

需要补 import：

```python
from app.models.standard_trial_balance_raw_row import StandardTrialBalanceRawRow
from app.services.standard_trial_balance_service import delete_batch
```

**前端实现：**

`frontend/src/views/DataView.vue`

在筛选栏右侧增加删除按钮：

```vue
<el-popconfirm
  v-if="selectedBatchId"
  title="确认删除当前导入批次？删除后该批次的科目余额表数据不可在查询页查看。"
  confirm-button-text="删除"
  cancel-button-text="取消"
  confirm-button-type="danger"
  @confirm="deleteSelectedBatch"
>
  <template #reference>
    <el-button type="danger" plain :loading="deleteLoading">
      删除当前导入数据
    </el-button>
  </template>
</el-popconfirm>
```

脚本新增：

```ts
const deleteLoading = ref(false)

async function deleteSelectedBatch() {
  if (!selectedBatchId.value) return
  deleteLoading.value = true
  try {
    await api.delete(`/standard-trial-balances/batches/${selectedBatchId.value}`)
    ElMessage.success('已删除当前导入数据')
    selectedBatchId.value = null
    treeData.value = []
    totalNodes.value = 0
    await fetchBatches()
    if (selectedBatchId.value) {
      await fetchTree()
    }
  } catch (e) {
    console.error('删除导入数据失败', e)
    ElMessage.error(normalizeError(e, '删除导入数据失败'))
  } finally {
    deleteLoading.value = false
  }
}
```

需要补 import：

```ts
import { ElMessage } from 'element-plus'
import { normalizeError } from '@/utils/error'
```

如果 `normalizeError` 签名不同，按项目现有页面用法改，但错误提示必须友好。

---

## 任务 7：真实文件回归验证

修完后必须用真实文件跑一遍，不允许只跑单元测试。

真实文件：

```text
D:/NAS/xiaochen/李辉辉项目组/SynologyDrive/汇达228股改审计/1.账套/aglq710-科目余额表 20251231.xlsx
```

要求：

- preview 成功；
- 字段自动映射成功；
- analyze 成功；
- unmatched 数为 0；
- blocking errors 为 0；
- warnings 如仍存在，必须列出类别和数量，不能一句话带过；
- execute 成功；
- 抽查导入后的 `StandardTrialBalanceEntry`：
  - 客户名含 `包装物` 的 entry 标准快照为 `141101 包装物`；
  - 客户名含 `低值易耗品` 的 entry 标准快照为 `141102 低值易耗品`；
  - 客户名是 `在建工程_生产线` 或含 `在建工程` 但不含 `减值/准备` 的 entry 标准快照为 `160401 在建工程-原值`；
  - 客户名含 `管理费用` 的 entry 不得是 `660201 减：研发费用`；
  - 客户名含 `研发费用/研发支出费用化` 的 entry 可为 `660201 减：研发费用`；
- 查询树 `/standard-trial-balances/tree?batch_id=...&only_with_amounts=true` 中：
  - `141101`、`141102` 是顶层节点；
  - `660201` 是顶层节点；
  - `160401` 下能看到在建工程客户明细；
  - `160402` 下只应有真实减值准备类客户明细。

验证后要使用新增删除接口删除本次测试批次，确认：

- 批次列表不再出现测试批次；
- entries/raw_rows 删除；
- standard_accounts 不受影响。

---

## 必跑命令

后端：

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest tests/test_standard_account_import.py -q
D:\python\python.exe -m pytest tests/test_client_account_mapping_service.py -q
D:\python\python.exe -m pytest tests/test_standard_trial_balance_view.py -q
D:\python\python.exe -m pytest tests/test_standard_trial_balance_import.py -q
D:\python\python.exe -m pytest -q
```

前端：

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

视觉验收：

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run dev
```

打开数据查询页，检查 1366x768 和 1920x1080：

- 展开层级后行不换行；
- 左侧两列冻结；
- 金额列可横向滚动到 `期末贷方余额`；
- 有删除当前导入数据按钮；
- 删除需要二次确认。

---

## 完成标准

提交结果必须包含：

1. 哪些文件改了。
2. 说明 `141101/141102/660201` 的 `parent_id` 已修成 `None`，不是只改 UI。
3. 说明 `160402 在建工程_生产线` 为什么不会再匹配减值准备。
4. 说明 `660201 管理费用_办公费` 为什么不会再匹配研发费用。
5. 真实文件导入结果：未匹配数、warning 分类/数量、execute 状态。
6. 删除接口验证结果：删除前 entries/raw_rows/batch 数量，删除后数量。
7. 前端截图或明确视觉检查结论：明细行不换行、冻结列正常、期末贷方可见。

---

## 给执行 AI 的提示词

```text
你来领取并执行：

D:/APP/Codex-项目/13、审计系统/docs/tasks/TASK-072-data-view-root-hierarchy-mapping-delete.md

这次不要只改 UI。用户截图暴露了 5 个问题：
1. 数据查询页展开明细行会自动换行，行太高；
2. 包装物和低值易耗品仍挂在周转材料下面，但用户要求它们是一级科目；
3. 在建工程被匹配到了在建工程减值准备；
4. 管理费用/研发费用层级和匹配错位；
5. 数据查询页需要删除当前导入数据按钮。

你必须先写后端失败测试：
- 141101/141102/660201 的 parent_id 必须是 None；
- 160402 在建工程_生产线 必须安全匹配 160401，不得安全匹配 160402 减值准备；
- 660201 管理费用_办公费 必须安全匹配 6602 管理费用，不得安全匹配 660201 研发费用；
- 查询树中 141101/141102/660201 必须是顶层节点；
- 删除批次必须删除 entries/raw_rows/batch，但不删除 standard_accounts。

然后再实现：
- standard_account_service 的业务层级 override 和已有 DB 修复；
- client_account_mapping_service 的备抵/减值类冲突判断；
- standard_trial_balance_service + API 的删除批次；
- DataView.vue 的单行布局、标准科目列、冻结列、删除按钮。

最后必须跑真实文件：
D:/NAS/xiaochen/李辉辉项目组/SynologyDrive/汇达228股改审计/1.账套/aglq710-科目余额表 20251231.xlsx

验收报告必须列出：未匹配数、warning 分类/数量、execute 是否成功、包装物/低值易耗品/在建工程/管理费用/研发费用的实际标准科目快照、删除接口验证结果、前端 build 和视觉检查结果。
```
