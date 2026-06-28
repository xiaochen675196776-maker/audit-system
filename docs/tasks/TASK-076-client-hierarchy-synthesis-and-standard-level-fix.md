# TASK-076：真实文件客户中间层级仍缺失，合成 client_group 并修 170401/170402 level

**Status:** TODO  
**Priority:** P0  
**Owner:** 待领取  

## 验收失败证据

2026-06-24 对 TASK-075 做真实文件验收：

```text
文件：D:/NAS/xiaochen/**/aglq710-*20251231.xlsx
总行数：289
入库条目：201
未匹配：0
warning：0
error：0
```

后端测试通过：

```text
D:\python\python.exe -m pytest -q
380 passed
```

前端构建通过：

```text
npm run build
✓ built
```

但真实查询树仍失败：

```json
{
  "tree": {
    "170402": {
      "entry_count": 24,
      "client_group_count": 0,
      "entry_node_count": 24
    },
    "2221": {
      "entry_count": 11,
      "client_group_count": 0,
      "entry_node_count": 11
    },
    "has_client_group_530101_under_170402": false,
    "has_client_group_222101_under_2221": false
  },
  "raw_parent_checks": {
    "222101_parent": null,
    "22210101_parent": null,
    "2221010101_parent": null,
    "530101_parent": null,
    "53010101_parent": null,
    "5301010101_parent": null
  }
}
```

同时标准科目 level 有问题：

```json
{
  "1704": {"level": 1, "is_leaf": false, "parent_code": null},
  "170401": {"level": 1, "is_leaf": true, "parent_code": "1704"},
  "170402": {"level": 1, "is_leaf": true, "parent_code": "1704"}
}
```

`170401/170402` 已有 `parent_id=1704`，但 `level` 仍是 1。它们必须是二级，`level=2`。

## 已经通过的部分

不要回退这些已通过点：

```json
{
  "160402": {
    "client_name": "在建工程_生产线",
    "standard_code": "160401",
    "standard_name": "在建工程-原值"
  },
  "660401": {
    "client_name": "研发费用",
    "standard_code": "660201",
    "standard_name": "减：研发费用"
  },
  "5301010101": {
    "client_name": "研发支出_费用化支出_人工_工资及奖金",
    "standard_code": "170402",
    "standard_name": "研发支出-费用化支出"
  }
}
```

`160402 减值准备` 已经作为 `code_match_conflict` 降级；`160401 在建工程-原值` 是安全候选。这个不要改坏。

---

## 根因判断

TASK-075 的实现只在 `raw_rows.parent_raw_row_id` 存在时复原客户层级。但真实文件中很多中间科目行并不存在，或者层级识别没有把它们保存成 raw parent。

真实文件里客户名称本身带完整路径：

```text
2221010101 应交税费_应交增值税_进项税额_货物进项税
5301010101 研发支出_费用化支出_人工_工资及奖金
```

即使没有 `222101`、`22210101`、`530101`、`53010101` 的 raw parent 行，也应该从客户科目代码和名称分段合成客户层级。

当前查询树仍是：

```text
2221 应交税费
  2221010101 客户 应交税费_应交增值税_进项税额_货物进项税
  2221010102 客户 应交税费_应交增值税_进项税额_固定资产进项税
```

应该是：

```text
2221 应交税费
  222101 应交增值税
    22210101 进项税额
      2221010101 货物进项税
      2221010102 固定资产进项税
```

研发支出应类似：

```text
1704 开发支出
  170402 研发支出-费用化支出
    530101 研发支出_费用化支出
      53010101 人工
        5301010101 工资及奖金
      53010112 直接投入
        <科目代码样例005> 机物料_仓存机物料
```

---

## 任务 1：修标准科目同步后的 level 重算

### 目标

`170401/170402` 必须：

```text
parent_code = 1704
level = 2
is_leaf = true
```

`1704` 必须：

```text
level = 1
is_leaf = false
parent_id = null
```

### 修改文件

- `backend/app/services/standard_account_service.py`
- `backend/tests/test_standard_account_import.py`

### 实施要求

在标准科目同步/导入完成、`parent_id` 建立之后，必须重新计算所有本次涉及科目的 `level`：

```python
def _compute_level(account: StandardAccount, id_to_account: dict[uuid.UUID, StandardAccount]) -> int:
    level = 1
    current = account
    seen = set()
    while current.parent_id is not None:
        if current.id in seen:
            break
        seen.add(current.id)
        parent = id_to_account.get(current.parent_id)
        if parent is None:
            break
        level += 1
        current = parent
    return level
```

同步流程顺序必须是：

1. upsert 标准科目。
2. 清理旧 `parent_id`。
3. 按代码前缀/业务 override 建立 `parent_id`。
4. 重新计算 `level`。
5. 重新计算 `is_leaf`。
6. flush。

不要只在空库 seed 时算 level，已有 DB upsert 也必须算。

### 必写测试

在 `backend/tests/test_standard_account_import.py` 加测试，覆盖空库和已有库：

```python
@pytest.mark.asyncio
async def test_seed_empty_db_sets_rd_development_child_levels(db):
    from sqlalchemy import select
    from app.models.standard_account import StandardAccount
    from app.services.standard_account_service import seed_standard_accounts

    await seed_standard_accounts(db)
    rows = (await db.execute(select(StandardAccount))).scalars().all()
    by_code = {r.account_code: r for r in rows}

    assert by_code["1704"].level == 1
    assert by_code["1704"].is_leaf is False
    assert by_code["170401"].parent_id == by_code["1704"].id
    assert by_code["170402"].parent_id == by_code["1704"].id
    assert by_code["170401"].level == 2
    assert by_code["170402"].level == 2
    assert by_code["170401"].is_leaf is True
    assert by_code["170402"].is_leaf is True
```

已有库分支：

```python
@pytest.mark.asyncio
async def test_seed_existing_db_recomputes_rd_development_child_levels(db):
    from sqlalchemy import select
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

    await seed_standard_accounts(db)
    rows = (await db.execute(select(StandardAccount))).scalars().all()
    by_code = {r.account_code: r for r in rows}

    assert by_code["1704"].level == 1
    assert by_code["1704"].is_leaf is False
    assert by_code["170401"].parent_id == by_code["1704"].id
    assert by_code["170402"].parent_id == by_code["1704"].id
    assert by_code["170401"].level == 2
    assert by_code["170402"].level == 2
```

---

## 任务 2：查询树在 raw parent 缺失时，按客户名称/代码合成 client_group

### 目标

即使 `StandardTrialBalanceRawRow.parent_raw_row_id` 为空，也要从 leaf entry 的客户名称和代码合成中间层级。

### 修改文件

- `backend/app/services/standard_trial_balance_service.py`
- `backend/tests/test_standard_trial_balance_view.py`

### 节点类型

沿用 TASK-075 已加入的：

```python
node_type = "client_group"
```

### 合成规则

实现一个独立 helper，方便测试：

```python
def _build_synthetic_client_group_path(
    *,
    client_code: str | None,
    client_name: str | None,
    standard_account_code: str,
    standard_account_name: str,
) -> list[dict]:
    """从客户科目代码和名称合成客户中间层路径。

    返回从上到下的 group 列表，不包含最终 leaf entry。
    每个元素：
    {
      "account_code": "...",
      "account_name": "...",
      "client_account_code": "...",
      "client_account_name": "...",
    }
    """
```

#### 名称分段

先按以下分隔符切分：

```python
["_", "-", "－", "—", "/", "\\"]
```

过滤空段。

示例：

```text
应交税费_应交增值税_进项税额_货物进项税
=> ["应交税费", "应交增值税", "进项税额", "货物进项税"]

研发支出_费用化支出_人工_工资及奖金
=> ["研发支出", "费用化支出", "人工", "工资及奖金"]
```

最终 leaf entry 使用最后一段；client_group 使用前面的段。

#### 跳过与标准科目重复的第一段

如果第一段与标准科目名称 canonical 等价，或第一段已经被标准节点表示，则跳过。

示例：

```text
标准：2221 应交税费
客户名：应交税费_应交增值税_进项税额_货物进项税
跳过第一段“应交税费”，从“应交增值税”开始建 group。
```

#### 研发支出特殊分组

如果前两段是：

```text
研发支出 + 费用化支出
研发支出 + 资本化支出
```

则第一个 client_group 用前两段合并：

```text
530101 研发支出_费用化支出
530102 研发支出_资本化支出
```

不要生成一个单独的 `5301 研发支出` 层级挂在 `170402` 下面。标准科目 `170402` 已经表达了“研发支出-费用化支出”，客户层级第一层应是对应客户科目层级 `530101 研发支出_费用化支出`。

#### 代码前缀生成

对真实文件采用会计科目常见 4-2-2-2 分段：

```python
def _code_prefix_by_depth(code: str, depth: int) -> str:
    # depth 从 1 开始
    lengths = [4, 6, 8, 10, 12, 14]
    if depth <= len(lengths):
        return code[:min(lengths[depth - 1], len(code))]
    return code
```

但是研发支出特殊分组第一层是前两段合并，应使用 `code[:6]`：

```text
5301010101 -> 530101 研发支出_费用化支出
5301010101 -> 53010101 人工
5301010101 leaf -> 工资及奖金
```

应交税费示例：

```text
2221010101 -> 标准 2221 应交税费
client_group: 222101 应交增值税
client_group: 22210101 进项税额
entry: 2221010101 货物进项税
```

如果 `client_code` 很短，不能切出对应长度，就用当前可用 code，不要报错。

### 与 raw parent 的关系

优先级：

1. 如果 `raw parent chain` 存在并且能形成中间层，优先使用 raw parent chain。
2. 如果 raw parent chain 为空或只有无意义节点，则用合成路径。
3. 不要重复展示 raw chain 和 synthetic chain。

### entry 展示名

当前 entry 仍显示完整客户路径：

```text
2221010101 应交税费_应交增值税_进项税额_货物进项税
```

在有 client_group 的情况下，entry 行建议显示末段名，避免重复：

```text
2221010101 货物进项税
```

但必须保留完整原始名字段：

```python
client_account_name = 原完整名称
account_name = 末段显示名称
```

前端 tooltip 可以继续展示完整名称。

### 金额汇总

client_group 金额必须等于所有子孙 entry 汇总。

不要让标准科目金额重复加总：

- 标准 account 金额仍来自 `account_amounts` + 子标准 account。
- client_group 只是展示结构，金额用于显示；不要再额外加入标准 account 汇总。

### 必写测试 1：无 raw parent 时按名称合成应交税费层级

在 `backend/tests/test_standard_trial_balance_view.py` 增加：

```python
@pytest.mark.asyncio
async def test_tree_synthesizes_client_groups_from_leaf_name_when_raw_parent_missing(db):
    std = await _create_account(db, "2221", "应交税费", level=1, is_leaf=True)
    batch = await _create_batch(db, file_name="tax.xlsx")

    raw = StandardTrialBalanceRawRow(
        batch_id=batch.id,
        row_index=0,
        raw_values={},
        client_account_code="2221010101",
        client_account_name="应交税费_应交增值税_进项税额_货物进项税",
        detected_level=4,
        is_leaf=True,
        mapped_standard_account_id=std.id,
        mapping_status="mapped",
    )
    db.add(raw)
    await db.flush()

    await _create_entry(
        db,
        batch.id,
        std,
        raw_row_id=raw.id,
        client_account_code="2221010101",
        client_account_name="应交税费_应交增值税_进项税额_货物进项税",
        ending_credit=Decimal("100.00"),
    )

    nodes, _ = await get_tree(db, batch_id=batch.id)
    std_node = _find_node_by_code(nodes, "2221")
    group_222101 = _find_child_by_code(std_node, "222101", node_type="client_group")
    group_22210101 = _find_child_by_code(group_222101, "22210101", node_type="client_group")
    entry = _find_child_by_code(group_22210101, "2221010101", node_type="entry")

    assert group_222101["account_name"] == "应交增值税"
    assert group_22210101["account_name"] == "进项税额"
    assert entry["account_name"] == "货物进项税"
    assert group_222101["entry_count"] == 1
    assert group_222101["ending_credit"] == Decimal("100.00")
```

### 必写测试 2：研发支出费用化合成客户层级

```python
@pytest.mark.asyncio
async def test_tree_synthesizes_rd_expensed_client_groups_under_170402(db):
    dev = await _create_account(db, "1704", "开发支出", level=1, is_leaf=False)
    exp = await _create_account(db, "170402", "研发支出-费用化支出", level=2, is_leaf=True, parent_id=dev.id)
    batch = await _create_batch(db, file_name="rd.xlsx")

    raw = StandardTrialBalanceRawRow(
        batch_id=batch.id,
        row_index=0,
        raw_values={},
        client_account_code="5301010101",
        client_account_name="研发支出_费用化支出_人工_工资及奖金",
        detected_level=4,
        is_leaf=True,
        mapped_standard_account_id=exp.id,
        mapping_status="mapped",
    )
    db.add(raw)
    await db.flush()

    await _create_entry(
        db,
        batch.id,
        exp,
        raw_row_id=raw.id,
        client_account_code="5301010101",
        client_account_name="研发支出_费用化支出_人工_工资及奖金",
        current_debit=Decimal("200.00"),
    )

    nodes, _ = await get_tree(db, batch_id=batch.id)
    node_170402 = _find_node_by_code(nodes, "170402")
    group_530101 = _find_child_by_code(node_170402, "530101", node_type="client_group")
    group_53010101 = _find_child_by_code(group_530101, "53010101", node_type="client_group")
    entry = _find_child_by_code(group_53010101, "5301010101", node_type="entry")

    assert group_530101["account_name"] == "研发支出_费用化支出"
    assert group_53010101["account_name"] == "人工"
    assert entry["account_name"] == "工资及奖金"
    assert group_530101["current_debit"] == Decimal("200.00")
```

---

## 任务 3：真实文件验收必须改成硬断言

### 目标

不要再只看单元测试。必须用真实文件跑出以下断言。

### 可新增脚本

建议新增：

```text
backend/scripts/acceptance_task076_real_file.py
```

脚本必须：

1. 使用临时 SQLite DB。
2. `seed_standard_accounts()`。
3. 预览、分析、确认安全候选、执行导入。
4. 调 `get_tree()`。
5. 断言关键映射和树结构。

### 必须断言

```python
assert unmatched_count == 0
assert errors_count == 0

assert account("170401").parent_code == "1704"
assert account("170401").level == 2
assert account("170402").parent_code == "1704"
assert account("170402").level == 2

assert entry("160402").standard_code == "160401"
assert entry("660401").standard_code == "660201"
assert entry("5301010101").standard_code == "170402"
assert entry("<科目代码样例005>").standard_code == "170402"

assert node("160402").entry_count == 0
assert node("160401").entry_count >= 6
assert node("660201").entry_count == 1
assert node("170402").entry_count >= 20

assert has_client_group_under("2221", "222101")
assert has_client_group_under("2221", "22210101")
assert has_client_group_under("170402", "530101")
assert has_client_group_under("170402", "53010101")
```

如果真实文件没有资本化支出样本，脚本要输出：

```text
capitalized_samples: 0
```

但单元测试仍必须覆盖资本化支出。

---

## 任务 4：页面验收

启动临时后端/前端后，在数据查询页面检查：

1. 展开 `2221 应交税费` 能看到 `客户层级 222101 应交增值税`，再展开看到 `22210101 进项税额`，再展开看到末级。
2. 展开 `1704 开发支出 -> 170402 研发支出-费用化支出` 能看到 `客户层级 530101 研发支出_费用化支出`。
3. 横向滚动仍可看到 `期末贷方余额`。
4. 删除当前导入数据仍可用。

可以复用：

```powershell
cd frontend
$env:QA_URL = 'http://127.0.0.1:<port>/data/view'
node scripts\qa-data-view-scroll.mjs
```

但还要额外用 Puppeteer/Playwright 检查页面文本中出现：

```text
客户层级
222101
530101
```

---

## 必跑命令

```powershell
cd backend
D:\python\python.exe -m pytest tests/test_standard_account_import.py -q
D:\python\python.exe -m pytest tests/test_standard_trial_balance_view.py -q
D:\python\python.exe -m pytest tests/test_standard_trial_balance_import.py -q
D:\python\python.exe -m pytest tests/test_client_account_mapping_service.py -q
D:\python\python.exe -m pytest -q
D:\python\python.exe scripts\acceptance_task076_real_file.py

cd ..\frontend
npm run build
```

---

## 验收报告必须包含

1. `170401/170402` 的 `parent_code` 和 `level`。
2. 真实文件关键映射：
   - `160402 -> 160401`
   - `660401 -> 660201`
   - `5301010101 -> 170402`
3. 查询树证据：
   - `2221` 下 `client_group_count > 0`
   - `170402` 下 `client_group_count > 0`
   - `has_client_group_222101_under_2221 = true`
   - `has_client_group_530101_under_170402 = true`
4. 页面截图或 DOM 证据。
5. 后端全量测试和前端构建结果。

---

## 给其他 AI 的提示词

你来领取 `docs/tasks/TASK-076-client-hierarchy-synthesis-and-standard-level-fix.md`。TASK-075 映射大部分修好了，但真实文件验收仍失败：`2221`、`170402` 下 `client_group_count=0`，还是只铺末级；`raw_parent_checks` 全是 null，说明真实 Excel 没有可用的 raw parent 链，不能只依赖 `parent_raw_row_id`。你必须在 `standard_trial_balance_service.get_tree()` 中增加“从客户科目代码和名称分段合成 client_group”的逻辑。

同时修标准科目同步：`170401/170402` 已挂到 `1704`，但 level 仍是 1，必须重算为 level=2。先写失败测试，再改实现。真实文件验收必须硬断言：`160402 -> 160401`、`660401 -> 660201`、`5301010101 -> 170402`，并且 `2221` 下能看到 `222101/22210101` 客户层级，`170402` 下能看到 `530101/53010101` 客户层级。跑全量后端测试、前端 build、真实文件脚本和页面检查后再交付。
