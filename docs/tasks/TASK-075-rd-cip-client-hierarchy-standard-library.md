# TASK-075：修复研发支出/在建工程匹配、补开发支出二级标准科目、查询树展示客户中间层级

**Status:** TODO  
**Priority:** P0  
**Owner:** 待领取  

## 验收记录

2026-06-24 验收未通过，详见 `docs/tasks/TASK-076-client-hierarchy-synthesis-and-standard-level-fix.md`：

- 后端测试和前端构建通过，但真实文件查询树仍没有客户中间层。
- 真实文件导入后 `2221`、`170402` 下 `client_group_count=0`，仍然直接展示末级 entry。
- 真实文件 raw row 的 `parent_raw_row_id` 对 `222101/22210101/530101/53010101` 等为 `null`，说明不能只依赖原始父级行；需要从客户科目代码/名称分段合成客户层级。
- `170401/170402` 已挂到 `1704`，但 `level` 仍为 1，不符合二级科目要求。

## 背景

用户最新截图暴露 3 个问题：

1. `160402 在建工程_生产线` 仍显示在标准科目 `160402 减：在建工程-减值准备` 下面。这个绝对不对。只要客户名称没有“减值/准备/资产减值损失”等含义，`在建工程_生产线/在安装设备/工程项目/装修费用` 都应进入 `160401 在建工程-原值`。
2. 数据查询树只显示客户末级明细，看不到客户科目余额表里的二级、三级中间层。用户希望像原始科目余额表一样能展开客户侧层级，而不是标准科目下面直接铺一堆末级。
3. `研发费用` 与 `研发支出` 当前混在一起。用户明确要求：
   - 客户 `660401 研发费用` 才是损益表最终数，应匹配标准 `660201 减：研发费用`。
   - 客户 `研发支出_*` 不应再匹配 `660201 减：研发费用`。
   - 标准库里 `1704 开发支出` 下要新增二级明细：
     - `170401 研发支出-资本化支出`
     - `170402 研发支出-费用化支出`
   - 客户 `研发支出_资本化支出_*` 应匹配 `170401`。
   - 客户 `研发支出_费用化支出_*` 应匹配 `170402`。

## 总目标

真实文件 `aglq710-科目余额表 20251231.xlsx` 重新导入后：

- `160402 在建工程_生产线` 不得进入 `160402 减：在建工程-减值准备`，必须进入 `160401 在建工程-原值`。
- `研发支出_费用化支出_*` 必须进入 `170402 研发支出-费用化支出`。
- `研发支出_资本化支出_*` 必须进入 `170401 研发支出-资本化支出`。
- `660401 研发费用` 必须进入 `660201 减：研发费用`。
- 数据查询树在标准科目下要保留客户原始科目的中间层级，不能只显示末级。

---

## 关键判断

### 1. 在建工程误入减值准备，很可能是历史映射污染

当前代码里已经有备抵/减值冲突检测，但截图仍然错，说明不能只看 `code_match`。高概率原因是旧导入保存了错误经验：

```text
client 160402 在建工程_生产线 -> standard 160402 减：在建工程-减值准备
```

历史映射候选优先级高于语义候选，所以旧错配会继续自动套用。必须让历史映射也经过同一套“名称冲突/备抵减值冲突”校验。

### 2. 当前查询树丢了客户中间层

`standard_trial_balance_import_service.py` 已经保存了 `StandardTrialBalanceRawRow`，但当前 `standard_trial_balance_service.get_tree()` 只按 `StandardTrialBalanceEntry.standard_account_id` 把末级 entry 直接挂到标准科目节点下。

结果就是：

```text
2221 应交税费
  2221010101 客户 进项税额_货物进项税
  2221010102 客户 进项税额_固定资产进项税
```

用户想要的是：

```text
2221 应交税费
  222101 应交增值税
    22210101 进项税额
      2221010101 货物进项税
      2221010102 固定资产进项税
```

必须使用导入时保存的 `raw_rows.parent_raw_row_id` 复原客户侧层级。

### 3. 标准库新增科目不能只改 seed 文件

`seed_standard_accounts()` 当前如果库里已有标准科目，会跳过创建，只做层级修复。新增 `170401/170402` 后，用户本地已有 DB 不会自动补进去。

必须让内置标准科目 seed 同步支持“已有库 upsert 缺失内置科目”，不能只在空库生效。

---

## 涉及文件

后端：

- `backend/app/data/standard_accounts_seed.py`
- `backend/app/services/standard_account_service.py`
- `backend/app/services/client_account_mapping_service.py`
- `backend/app/services/standard_trial_balance_import_service.py`
- `backend/app/services/standard_trial_balance_service.py`
- `backend/app/schemas/standard_trial_balance.py`
- `backend/tests/test_standard_account_import.py`
- `backend/tests/test_client_account_mapping_service.py`
- `backend/tests/test_standard_trial_balance_import.py`
- `backend/tests/test_standard_trial_balance_view.py`

前端：

- `frontend/src/views/DataView.vue`
- 如有类型定义需要同步：`frontend/src/types/index.ts`

验收脚本：

- 可新增：`backend/scripts/acceptance_real_trial_balance.py`
- 或复用已有临时脚本，但最终要能一键跑出真实文件导入结果。

---

## 任务 1：补标准库 `170401/170402`，并让已有 DB 自动 upsert

### 要求

在内置标准科目中新增：

```python
{"account_code": "170401", "account_name": "研发支出-资本化支出", "balance_direction": "debit", "account_category": "资产类（明细）"}
{"account_code": "170402", "account_name": "研发支出-费用化支出", "balance_direction": "debit", "account_category": "资产类（明细）"}
```

层级必须是：

```text
1704 开发支出
  170401 研发支出-资本化支出
  170402 研发支出-费用化支出
```

`1704` 应为 `is_leaf=False`，`170401/170402` 应为 `is_leaf=True`。

### 实施要点

1. 修改 `backend/app/data/standard_accounts_seed.py`，在 `1704 开发支出` 附近加入 `170401/170402`。
2. 修改 `backend/app/services/standard_account_service.py`：
   - `seed_standard_accounts()` 在已有标准科目时不能只跳过。
   - 新增或复用一个同步函数，例如：

```python
async def sync_builtin_standard_accounts(db: AsyncSession) -> dict:
    """把内置标准科目同步进已有 DB。

    - 已存在代码：更新 name/category/direction/source 信息；
    - 不存在代码：创建；
    - 同步后重新推断 parent_id / level / is_leaf；
    - 应继续应用 BUSINESS_ROOT_ACCOUNT_CODES 展示层级 override；
    - 不删除用户库里已有但 seed 缺失的科目，可保持 active 状态，避免破坏历史数据。
    """
```

3. `seed_standard_accounts()` 的已有数据分支应调用这个同步函数：

```python
if count and count > 0:
    sync = await sync_builtin_standard_accounts(db)
    repair = await repair_builtin_standard_account_hierarchy(db)
    return {
        "created_count": sync["created_count"],
        "updated_count": sync["updated_count"],
        "skipped": True,
        "repaired_count": repair["updated_count"],
    }
```

4. 不要让新增的 `170401/170402` 被 `BUSINESS_ROOT_ACCOUNT_CODES` 提为一级。它们必须挂在 `1704` 下。

### 必写测试

在 `backend/tests/test_standard_account_import.py` 增加：

```python
@pytest.mark.asyncio
async def test_seed_sync_adds_rd_development_children_to_existing_db(db):
    from app.models.standard_account import StandardAccount
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

    result = await seed_standard_accounts(db)
    assert result["created_count"] >= 2

    rows = (await db.execute(select(StandardAccount))).scalars().all()
    by_code = {r.account_code: r for r in rows}

    assert "170401" in by_code
    assert "170402" in by_code
    assert by_code["170401"].account_name == "研发支出-资本化支出"
    assert by_code["170402"].account_name == "研发支出-费用化支出"
    assert by_code["1704"].is_leaf is False
    assert by_code["170401"].parent_id == by_code["1704"].id
    assert by_code["170402"].parent_id == by_code["1704"].id
    assert by_code["170401"].level == 2
    assert by_code["170402"].level == 2
```

---

## 任务 2：修匹配规则，研发支出进开发支出二级；研发费用仍进损益研发费用

### 要求

客户科目名称规则：

```text
研发支出_资本化支出_* -> 170401 研发支出-资本化支出
研发支出_费用化支出_* -> 170402 研发支出-费用化支出
研发费用 / 660401 研发费用 -> 660201 减：研发费用
```

禁止：

```text
研发支出_费用化支出_* -> 660201 减：研发费用
研发支出_资本化支出_* -> 660201 减：研发费用
```

### 实施要点

在 `backend/app/services/client_account_mapping_service.py`：

1. 在 `_NAME_ANCHORS` 中加入更具体锚点，并且排在 `研发费用` 前：

```python
"研发支出_资本化支出",
"研发支出_费用化支出",
"研发支出",
```

2. 在 `_SEMANTIC_ACCOUNT_GROUPS` 增加两个更具体语义组：

```python
"rd_capitalized_development": {
    "canonical": "研发支出-资本化支出",
    "client_aliases": ["研发支出_资本化支出", "研发支出-资本化支出", "资本化支出"],
    "standard_aliases": ["研发支出资本化支出", "研发支出-资本化支出"],
    "negative_aliases": ["费用化支出", "研发费用"],
},
"rd_expensed_development": {
    "canonical": "研发支出-费用化支出",
    "client_aliases": ["研发支出_费用化支出", "研发支出-费用化支出", "费用化支出"],
    "standard_aliases": ["研发支出费用化支出", "研发支出-费用化支出"],
    "negative_aliases": ["资本化支出", "研发费用"],
},
```

3. 现有 `rd_expense` 或类似语义组必须加负向排除：

```python
negative_aliases = ["研发支出", "资本化支出", "费用化支出", "开发支出"]
```

4. `_detect_semantic_group()` 必须优先命中更具体组。建议按 `client_aliases` 最长优先，而不是 dict 顺序碰运气。

5. 如果客户名称同时有 `研发支出` 和 `费用化支出/资本化支出`，不得落入 `研发费用` 组。

### 必写测试

在 `backend/tests/test_client_account_mapping_service.py` 增加或修改：

```python
@pytest.mark.asyncio
async def test_rd_development_expensed_maps_to_170402_not_rd_expense(db):
    dev = _make_standard_account("1704", "开发支出", balance_direction="debit")
    cap = _make_standard_account("170401", "研发支出-资本化支出", parent_id=dev.id, balance_direction="debit")
    exp = _make_standard_account("170402", "研发支出-费用化支出", parent_id=dev.id, balance_direction="debit")
    rd_expense = _make_standard_account("660201", "减：研发费用", balance_direction="debit")
    db.add_all([dev, cap, exp, rd_expense])
    await db.flush()

    result = await recommend_mappings(
        db,
        data_type="trial_balance",
        customer_label=None,
        client_accounts=[
            {"client_account_code": "530101120201", "client_account_name": "研发支出_费用化支出_直接投入_机物料_仓存机物料"},
        ],
    )
    cands = result[0]["candidates"]
    safe_170402 = [c for c in cands if c["standard_account_code"] == "170402" and c["warning"] is None and c["score"] >= 0.9]
    bad_660201 = [c for c in cands if c["standard_account_code"] == "660201" and c["warning"] is None and c["score"] >= 0.9]
    assert safe_170402, cands
    assert not bad_660201, cands
    assert cands[0]["standard_account_code"] == "170402"
```

```python
@pytest.mark.asyncio
async def test_rd_development_capitalized_maps_to_170401(db):
    dev = _make_standard_account("1704", "开发支出", balance_direction="debit")
    cap = _make_standard_account("170401", "研发支出-资本化支出", parent_id=dev.id, balance_direction="debit")
    exp = _make_standard_account("170402", "研发支出-费用化支出", parent_id=dev.id, balance_direction="debit")
    rd_expense = _make_standard_account("660201", "减：研发费用", balance_direction="debit")
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
    assert safe_170401, cands
    assert not bad_660201, cands
    assert cands[0]["standard_account_code"] == "170401"
```

```python
@pytest.mark.asyncio
async def test_plain_rd_expense_still_maps_to_660201(db):
    db.add(_make_standard_account("170402", "研发支出-费用化支出", balance_direction="debit"))
    db.add(_make_standard_account("660201", "减：研发费用", balance_direction="debit"))
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
    assert safe_660201, cands
    assert not bad_170402, cands
```

---

## 任务 3：历史映射也必须经过冲突校验，禁止旧错配继续自动套用

### 要求

如果历史映射指向的标准科目与客户名称存在明显冲突，则不能作为安全候选。

典型场景：

```text
历史经验：160402 在建工程_生产线 -> 160402 减：在建工程-减值准备
当前推荐：必须降级为 warning 候选，安全候选应是 160401 在建工程-原值
```

```text
历史经验：研发支出_费用化支出_* -> 660201 减：研发费用
当前推荐：必须降级为 warning 候选，安全候选应是 170402 研发支出-费用化支出
```

### 实施要点

在 `client_account_mapping_service.py`：

1. 找到 `_build_candidate()`，它负责把 `ClientAccountMapping` 历史经验构造成候选。
2. 给历史候选增加冲突校验。可以复用 `_check_code_match_name_conflict()`，但不要只按“代码相同”判断，要按“标准科目名称 vs 客户科目名称”判断。
3. 建议新增函数：

```python
def _check_standard_name_conflict(sa: StandardAccount, client_name: str | None) -> str | None:
    """判断标准科目与客户名称是否存在强冲突。

    返回 None 表示不冲突；返回字符串表示冲突原因。
    必须覆盖：
    - 标准科目是备抵/减值/准备类，但客户名称没有减值/准备/坏账/跌价/累计折旧/累计摊销语义；
    - 标准科目是研发费用，但客户名称是研发支出_费用化支出或研发支出_资本化支出；
    - 标准科目是研发支出-费用化支出，但客户名称是研发费用；
    - 标准科目是研发支出-资本化支出，但客户名称包含费用化支出。
    """
```

4. `_build_candidate()` 中如果存在冲突：

```python
candidate["source"] = f"{source}_conflict"
candidate["score"] = min(candidate["score"], 0.75)
candidate["warning"] = conflict_reason
candidate["reason"] = f"历史映射与当前客户科目名称冲突：{conflict_reason}"
```

5. 冲突历史候选不得排在安全语义候选前。必要时调整 `_CANDIDATE_SOURCE_PRIORITY`。

### 必写测试

```python
@pytest.mark.asyncio
async def test_stale_history_to_cip_impairment_is_demoted(db):
    original = _make_standard_account("160401", "在建工程-原值", balance_direction="debit")
    impairment = _make_standard_account("160402", "减：在建工程-减值准备", balance_direction="credit")
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
    assert safe_original, cands
    assert not bad_impairment, cands
```

```python
@pytest.mark.asyncio
async def test_stale_history_rd_development_to_rd_expense_is_demoted(db):
    exp_dev = _make_standard_account("170402", "研发支出-费用化支出", balance_direction="debit")
    rd_expense = _make_standard_account("660201", "减：研发费用", balance_direction="debit")
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
    assert safe_170402, cands
    assert not bad_660201, cands
```

---

## 任务 4：保存并复原客户原始中间层级

### 当前问题

`standard_trial_balance_import_service.py` 第 8-9 步保存 `StandardTrialBalanceRawRow`，但补 `parent_raw_row_id` 时只处理了 `leaves`：

```python
leaf = next((lr for lr in leaves if lr.row_index == ri.row_index), None)
if leaf and leaf.parent_key:
    ...
```

这意味着非末级父级行的 `parent_raw_row_id` 没有完整保存。查询树自然无法复原二级、三级客户层级。

### 要求

1. 保存 raw row 时，要为所有 `transform_result.rows` 保存：
   - `detected_level`
   - `parent_raw_row_id`
   - `is_leaf`
   - `is_summary`
2. 当前模型没有 `is_summary` 字段，可以不加数据库字段；但至少要用 `is_leaf=False` 表达父级行。
3. 第 9 步补父级时必须遍历 `transform_result.rows`，不能只遍历 `leaves`。

### 实施建议

在 `standard_trial_balance_import_service.py` 里建立：

```python
result_by_row = {r.row_index: r for r in transform_result.rows}
```

保存 raw row 时：

```python
tr = result_by_row.get(ri.row_index)
is_leaf = bool(tr and tr.is_leaf and not tr.is_summary)

raw_row = StandardTrialBalanceRawRow(
    ...
    detected_level=tr.level if tr else None,
    is_leaf=is_leaf,
    warnings={"warnings": tr.warnings, "errors": tr.errors} if tr else None,
)
```

补 parent 时：

```python
for tr in transform_result.rows:
    if not tr.parent_key:
        continue
    parent_idx = resolve_parent_row_index(tr.parent_key, row_inputs)
    if parent_idx is not None and parent_idx in raw_row_map:
        rr = await db.get(StandardTrialBalanceRawRow, raw_row_map[tr.row_index])
        rr.parent_raw_row_id = raw_row_map[parent_idx]
```

注意：`parent_key` 可能是父级代码，也可能是父级 row_index 字符串。要沿用现有解析逻辑。

### 必写测试

在 `backend/tests/test_standard_trial_balance_import.py` 增加：

```python
@pytest.mark.asyncio
async def test_execute_persists_parent_links_for_non_leaf_raw_rows(db):
    # 构造 2221 -> 222101 -> 22210101 -> 2221010101
    # 只末级 2221010101 入库，但 raw_rows 必须保存完整 parent_raw_row_id 链。
```

测试断言：

```python
raw_rows = (await db.execute(
    select(StandardTrialBalanceRawRow).where(StandardTrialBalanceRawRow.batch_id == batch_id)
)).scalars().all()
by_code = {r.client_account_code: r for r in raw_rows}

assert by_code["222101"].parent_raw_row_id == by_code["2221"].id
assert by_code["22210101"].parent_raw_row_id == by_code["222101"].id
assert by_code["2221010101"].parent_raw_row_id == by_code["22210101"].id
assert by_code["2221"].is_leaf is False
assert by_code["222101"].is_leaf is False
assert by_code["22210101"].is_leaf is False
assert by_code["2221010101"].is_leaf is True
```

---

## 任务 5：查询树按标准科目 + 客户层级展示，不只铺末级

### 要求

`get_tree()` 返回结构应支持三类节点：

```python
node_type = "account"       # 标准科目
node_type = "client_group"  # 客户原始非末级层级
node_type = "entry"         # 客户末级入库明细
```

`TreeNodeResponse.node_type` 要从：

```python
Literal["account", "entry"]
```

改为：

```python
Literal["account", "client_group", "entry"]
```

### 树形结构规则

标准科目层级仍按标准科目展示：

```text
1704 开发支出
  170401 研发支出-资本化支出
  170402 研发支出-费用化支出
```

标准末级科目下，如果有客户原始中间层，则要展示客户中间层：

```text
170402 研发支出-费用化支出
  530101 研发支出_费用化支出
    53010112 研发支出_费用化支出_直接投入
      530101120201 研发支出_费用化支出_直接投入_机物料_仓存机物料
```

如果某标准科目下只有一个末级、没有中间层，可以直接显示 entry，但不能丢失已有中间层。

### 金额规则

- `entry` 节点金额来自 `StandardTrialBalanceEntry`。
- `client_group` 节点金额应动态汇总其所有子孙 entry 的六列金额。
- `account` 标准科目节点金额仍按所有子标准科目 + 自身客户树汇总。

### 实施建议

在 `standard_trial_balance_service.py` 中：

1. 查询 entries 时同时取 raw rows：

```python
raw_result = await db.execute(
    select(StandardTrialBalanceRawRow).where(StandardTrialBalanceRawRow.batch_id == batch_id)
)
raw_rows = raw_result.scalars().all()
raw_by_id = {r.id: r for r in raw_rows}
```

2. 对每个 entry，根据 `entry.raw_row_id` 找 ancestor chain：

```python
def _ancestor_chain(raw_row):
    chain = []
    cur = raw_row
    while cur and cur.parent_raw_row_id:
        parent = raw_by_id.get(cur.parent_raw_row_id)
        if not parent:
            break
        chain.append(parent)
        cur = parent
    chain.reverse()
    return chain
```

3. 在每个标准科目下构造客户树。建议用 `(standard_account_id, raw_row_id)` 作为 client_group node_id：

```python
node_id = f"client_group:{standard_account_id}:{raw.id}"
```

4. 对每个 entry：
   - 如果 ancestor chain 非空，把 entry 插到 chain 最末节点下面。
   - 如果 ancestor chain 空，直接挂到标准科目下面。

5. client_group 节点字段建议：

```python
{
    "node_id": f"client_group:{sa.id}:{raw.id}",
    "node_type": "client_group",
    "standard_account_id": sa.id,
    "standard_account_code": sa.account_code,
    "standard_account_name": sa.account_name,
    "account_code": raw.client_account_code or "",
    "account_name": raw.client_account_name or "",
    "client_account_code": raw.client_account_code,
    "client_account_name": raw.client_account_name,
    "level": raw.detected_level,
    "is_leaf": False,
    "entry_id": None,
    "children": [],
    "entry_count": 0,
    "has_children": True,
}
```

6. 不要把同一个 raw parent 同时挂到多个标准科目下，除非它确实有不同子孙 entry 映射到不同标准科目。此时可以在不同标准科目下复制展示客户 group，这是可接受的，因为查询树第一层主轴是标准科目。

### 前端要求

`frontend/src/views/DataView.vue`：

1. `clientLabel(row)` 要支持 `client_group`：

```ts
if (row.node_type === 'client_group') {
  return `${row.client_account_code || row.account_code || ''} ${row.client_account_name || row.account_name || ''}`.trim()
}
```

2. 模板里：

```vue
<template v-if="row.node_type === 'entry'">
  <el-tag size="small" type="info" effect="plain">客户</el-tag>
  ...
</template>
<template v-else-if="row.node_type === 'client_group'">
  <el-tag size="small" type="warning" effect="plain">客户层级</el-tag>
  ...
</template>
<template v-else>
  ...
</template>
```

3. `条目数` 列：
   - `account`：显示 `entry_count`
   - `client_group`：显示其子孙 entry_count
   - `entry`：显示 `明细`

### 必写测试

在 `backend/tests/test_standard_trial_balance_view.py` 增加：

```python
@pytest.mark.asyncio
async def test_tree_preserves_client_raw_hierarchy_under_standard_account(db):
    # 标准科目：2221 应交税费
    # raw rows：2221 -> 222101 -> 22210101 -> 2221010101
    # entry 只对应 2221010101
    # get_tree 后必须看到 client_group 222101 和 22210101，而不是 2221010101 直接挂在标准 2221 下。
```

断言结构：

```python
std_2221 = find_node(nodes, "2221")
client_222101 = find_child(std_2221, "222101", node_type="client_group")
client_22210101 = find_child(client_222101, "22210101", node_type="client_group")
entry = find_child(client_22210101, "2221010101", node_type="entry")

assert entry["client_account_name"].endswith("货物进项税")
assert client_222101["entry_count"] == 1
assert client_22210101["entry_count"] == 1
```

---

## 任务 6：真实文件验收脚本

必须拿真实文件跑一遍，不允许只靠单元测试：

```text
D:/NAS/xiaochen/李辉辉项目组/SynologyDrive/汇达228股改审计/1.账套/aglq710-科目余额表 20251231.xlsx
```

如果 PowerShell 中文路径编码出问题，用：

```python
files = list(Path("D:/NAS/xiaochen").rglob("aglq710-*20251231.xlsx"))
FILE = files[0]
```

### 真实文件必须断言

```python
assert unmatched_count == 0
assert errors_count == 0

assert snapshot["141201"].standard_code == "141101"
assert snapshot["141301"].standard_code == "141102"
assert snapshot["160402"].standard_code == "160401"  # 在建工程_生产线
assert snapshot["660401"].standard_code == "660201"  # 研发费用
assert snapshot["5301010101"].standard_code == "170402"  # 研发支出_费用化支出_人工_工资及奖金
```

如果真实文件里存在资本化支出样本，也要断言：

```python
assert capitalized_rd_sample.standard_code == "170401"
```

树结构必须断言：

```python
assert tree_has("1704")
assert tree_has("170401")
assert tree_has("170402")
assert node("170402").entry_count > 0
assert node("660201").entry_count == 1  # 至少不得再包含研发支出费用化明细；真实数量按文件确认
assert node("160402").entry_count == 0  # 除非真实客户科目名称明确是减值准备
assert tree_contains_client_group_under("170402", "530101")
```

---

## 必跑命令

```powershell
cd backend
D:\python\python.exe -m pytest tests/test_standard_account_import.py -q
D:\python\python.exe -m pytest tests/test_client_account_mapping_service.py -q
D:\python\python.exe -m pytest tests/test_standard_trial_balance_import.py -q
D:\python\python.exe -m pytest tests/test_standard_trial_balance_view.py -q
D:\python\python.exe -m pytest -q

cd ..\frontend
npm run build
```

再启动临时库跑真实文件验收，不要污染 `backend/audit.db`。

---

## 最终验收口径

验收报告必须列出：

1. 新增标准科目：
   - `170401 研发支出-资本化支出`
   - `170402 研发支出-费用化支出`
   - 父级均为 `1704 开发支出`
2. 真实文件导入结果：
   - 总行数
   - 入库条目数
   - 未匹配数
   - warning/error 数
3. 关键科目快照：
   - `160402 在建工程_生产线 -> 160401 在建工程-原值`
   - `660401 研发费用 -> 660201 减：研发费用`
   - `530101... 研发支出_费用化支出_* -> 170402 研发支出-费用化支出`
   - 如果有资本化支出：`研发支出_资本化支出_* -> 170401`
4. 查询树截图或 DOM 证据：
   - `1704 -> 170402 -> 客户中间层 -> 末级明细`
   - `2221 应交税费` 下能看到客户二级/三级层级，而不是只看到末级。
5. 删除按钮、横向滚动不要回退。

---

## 给其他 AI 的提示词

你来领取 `docs/tasks/TASK-075-rd-cip-client-hierarchy-standard-library.md`。这不是单点 UI 修复，必须同时修标准库、匹配、导入 raw 层级保存、查询树展示。

用户指出 3 个问题：

1. `160402 在建工程_生产线` 仍进入了 `160402 减：在建工程-减值准备`，必须改成 `160401 在建工程-原值`。注意旧的客户科目映射经验可能污染推荐，历史映射也必须经过名称冲突/备抵减值冲突校验，不能让旧错配继续作为安全候选。
2. 数据查询树只显示末级客户明细，丢了客户科目余额表的二级、三级层级。导入时已经保存 `StandardTrialBalanceRawRow`，你要修 `standard_trial_balance_import_service.py` 保存所有 raw row 的 parent 链，并修 `standard_trial_balance_service.get_tree()` 用 `parent_raw_row_id` 在标准科目下复原客户中间层，新增 `node_type="client_group"`。
3. 研发费用和研发支出要分开。`660401 研发费用` 是损益最终数，仍匹配 `660201 减：研发费用`；`研发支出_费用化支出_*` 要匹配新增标准科目 `170402 研发支出-费用化支出`；`研发支出_资本化支出_*` 要匹配新增标准科目 `170401 研发支出-资本化支出`。这两个标准科目要挂在 `1704 开发支出` 下面，并且已有数据库启动时也要自动 upsert，不能只对空库有效。

先写失败测试，再改实现。必须跑后端相关测试、全量 pytest、前端 build，并用真实文件 `D:/NAS/xiaochen/**/aglq710-*20251231.xlsx` 跑一次导入验收。验收报告必须列出未匹配数、关键科目映射快照、`1704/170401/170402` 树结构、客户中间层展示证据。
