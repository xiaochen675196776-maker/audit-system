# TASK-069：数据查看页去掉“查看明细”按钮，改成树形展开显示客户原始明细

> 交给其他 AI 执行时，请完整复制本文件。不要只看标题。  
> 目标是修复数据查看 UI，不要改科目匹配算法；匹配算法另见 TASK-068。

## 背景

用户反馈当前数据查看页的“查询明细”体验不对：

- 现在是右侧一列“查看明细”按钮。
- 点按钮后弹出明细对话框。
- 用户希望不要这样做。
- 应改成树形结构，类似截图里的行首展开箭头：点一下该行，明细就在树下面展开出来。

当前代码位置：

```text
frontend/src/views/DataView.vue
backend/app/services/standard_trial_balance_service.py
backend/app/schemas/standard_trial_balance.py
backend/app/api/standard_trial_balances.py
frontend/src/types/index.ts
backend/tests/test_standard_trial_balance_view.py
```

当前前端其实已经用了 `el-table` 的树表：

```vue
<el-table
  :data="treeData"
  row-key="standard_account_id"
  :tree-props="{ children: 'children', hasChildren: 'has_children' }"
>
```

但明细仍然是：

```vue
<el-table-column label="操作" fixed="right">
  <el-button @click="openDetail(row)">查看明细</el-button>
</el-table-column>

<el-dialog v-model="detailVisible">...</el-dialog>
```

这就是用户不满意的点。

## 目标体验

数据查看页应是一张树形表：

```text
> 1411 周转材料          汇总金额...
  > 141101 包装物        汇总金额...
      141101-001 客户包装物A      客户原始明细金额...
      141101-002 客户包装物B      客户原始明细金额...
  > 141102 低值易耗品    汇总金额...
      141102-001 客户低值易耗品A  客户原始明细金额...
```

要求：

- 删除“操作 / 查看明细”列。
- 删除明细弹窗。
- 标准科目节点仍显示标准科目代码和名称。
- 客户原始明细作为子节点展示在对应标准科目下面。
- 客户明细行应有轻微视觉区分，例如名称列显示“客户：xxx”，或使用较浅颜色/缩进。
- 展开/收起使用表格左侧树形箭头，不再通过按钮。
- 金额列沿用六列：期初借、期初贷、本期借、本期贷、期末借、期末贷。
- 大金额不能被省略；表格需要允许横向滚动，不能因为 fixed 右列或 overflow 导致金额被截断。

## 推荐架构

推荐后端直接把客户明细行拼进 `/standard-trial-balances/tree` 响应的 `children` 中，这样前端只渲染一棵树，不再额外请求 `/entries`。

原因：

- 当前弹窗逻辑每次点按钮会请求 `/entries` 后再前端过滤，数据流绕。
- 树形展开需要在标准科目节点下展示客户明细，后端已经最清楚每条 entry 属于哪个 `standard_account_id`。
- 让 tree API 返回完整树可以减少前端状态：不需要 `detailVisible/detailEntries/detailLoading/detailAccountId`。

## 数据结构要求

扩展树节点类型，加入节点类型字段。

标准科目节点：

```json
{
  "node_id": "account:<standard_account_id>",
  "node_type": "account",
  "standard_account_id": "...",
  "account_code": "141101",
  "account_name": "包装物",
  "client_account_code": null,
  "client_account_name": null,
  "entry_id": null,
  "children": [...]
}
```

客户明细节点：

```json
{
  "node_id": "entry:<entry_id>",
  "node_type": "entry",
  "standard_account_id": "...",
  "account_code": "141101-客户原始代码",
  "account_name": "客户：包装物_明细A",
  "client_account_code": "客户原始代码",
  "client_account_name": "包装物_明细A",
  "entry_id": "...",
  "children": [],
  "entry_count": 1,
  "has_children": false
}
```

注意：

- `row-key` 必须改成 `node_id`，不能继续用 `standard_account_id`，否则同一标准科目下多个 entry 会 key 冲突。
- 客户明细节点金额就是该 entry 自己的金额。
- 标准科目节点金额仍是汇总金额。
- 标准科目节点 `entry_count` 是其自身及子孙 entry 汇总数。
- 客户明细节点 `entry_count` 固定为 1。

## 后端任务

### 1. 修改 schema

文件：

```text
backend/app/schemas/standard_trial_balance.py
```

修改 `TreeNodeResponse`：

```python
class TreeNodeResponse(BaseModel):
    node_id: str
    node_type: Literal["account", "entry"] = "account"

    standard_account_id: uuid.UUID
    account_code: str
    account_name: str
    account_category: str | None = None
    balance_direction: str | None = None
    level: int | None = None
    is_leaf: bool = False

    entry_id: uuid.UUID | None = None
    client_account_code: str | None = None
    client_account_name: str | None = None

    opening_debit: Decimal = Decimal("0")
    opening_credit: Decimal = Decimal("0")
    current_debit: Decimal = Decimal("0")
    current_credit: Decimal = Decimal("0")
    ending_debit: Decimal = Decimal("0")
    ending_credit: Decimal = Decimal("0")

    children: list["TreeNodeResponse"] = Field(default_factory=list)
    entry_count: int = 0
    has_children: bool = False
```

如果项目没有引入 `Literal`，从 `typing` 导入：

```python
from typing import Literal
```

不要继续使用 `children: list[...] = []`，改成 `Field(default_factory=list)`，避免可变默认值风险。

### 2. 修改 tree service

文件：

```text
backend/app/services/standard_trial_balance_service.py
```

在 `get_tree()` 中，构造 `entries_by_account_id`：

```python
entries_by_account_id: dict[uuid.UUID, list[StandardTrialBalanceEntry]] = defaultdict(list)
for entry in entries:
    entries_by_account_id[entry.standard_account_id].append(entry)
```

构造标准科目节点时：

- 先递归构造标准子科目 `child_nodes`。
- 再构造当前标准科目的客户明细子节点 `entry_nodes`。
- `children = child_nodes + entry_nodes`。

客户明细节点示例：

```python
def _build_entry_node(entry: StandardTrialBalanceEntry, level: int | None) -> dict:
    code = entry.client_account_code or entry.standard_account_code_snapshot
    name = entry.client_account_name or entry.standard_account_name_snapshot
    return {
        "node_id": f"entry:{entry.id}",
        "node_type": "entry",
        "standard_account_id": entry.standard_account_id,
        "entry_id": entry.id,
        "account_code": code or "",
        "account_name": name or "",
        "client_account_code": entry.client_account_code,
        "client_account_name": entry.client_account_name,
        "account_category": entry.standard_account_category_snapshot,
        "balance_direction": entry.standard_balance_direction_snapshot,
        "level": (level or 1) + 1,
        "is_leaf": True,
        "opening_debit": entry.opening_debit,
        "opening_credit": entry.opening_credit,
        "current_debit": entry.current_debit,
        "current_credit": entry.current_credit,
        "ending_debit": entry.ending_debit,
        "ending_credit": entry.ending_credit,
        "children": [],
        "entry_count": 1,
        "has_children": False,
    }
```

标准科目节点必须加：

```python
"node_id": f"account:{sa.id}",
"node_type": "account",
"entry_id": None,
"client_account_code": None,
"client_account_name": None,
```

`has_children` 应为：

```python
has_children = len(child_nodes) + len(entry_nodes) > 0
```

`only_with_amounts=True` 时：

- 如果一个标准科目及其子孙没有金额，也没有客户明细，则过滤。
- 客户明细节点只有在所属标准科目保留时展示。

### 3. 后端测试

文件：

```text
backend/tests/test_standard_trial_balance_view.py
```

新增测试：

```python
@pytest.mark.asyncio
async def test_tree_includes_entry_children_under_standard_account(self, db):
    parent = await _create_account(db, "1411", "周转材料", level=1, is_leaf=False)
    child = await _create_account(
        db, "141101", "包装物", level=2, is_leaf=True, parent_id=parent.id
    )
    batch = await _create_batch(db)
    await _create_entry(
        db,
        batch.id,
        child,
        client_account_code="C1411",
        client_account_name="包装物",
        opening_debit=Decimal("100"),
        ending_debit=Decimal("100"),
    )

    nodes, total = await get_tree(db, batch_id=batch.id)
    assert len(nodes) == 1
    parent_node = nodes[0]
    child_node = parent_node["children"][0]

    assert parent_node["node_type"] == "account"
    assert child_node["node_type"] == "account"
    assert child_node["account_code"] == "141101"
    assert child_node["entry_count"] == 1

    entry_node = child_node["children"][0]
    assert entry_node["node_type"] == "entry"
    assert entry_node["client_account_code"] == "C1411"
    assert entry_node["client_account_name"] == "包装物"
    assert entry_node["opening_debit"] == Decimal("100")
    assert entry_node["has_children"] is False
    assert entry_node["children"] == []
```

也要更新已有树测试中对 `has_children` 的断言：如果某个叶子标准科目有 entry 子节点，那么它现在应 `has_children=True`。

## 前端任务

### 1. 修改类型

文件：

```text
frontend/src/types/index.ts
```

扩展 `TreeNode`：

```ts
export type TreeNodeType = 'account' | 'entry'

export interface TreeNode {
  node_id: string
  node_type: TreeNodeType
  standard_account_id: string
  entry_id: string | null
  account_code: string
  account_name: string
  client_account_code: string | null
  client_account_name: string | null
  account_category: string | null
  balance_direction: string | null
  level: number | null
  is_leaf: boolean
  opening_debit: string
  opening_credit: string
  current_debit: string
  current_credit: string
  ending_debit: string
  ending_credit: string
  children: TreeNode[]
  entry_count: number
  has_children: boolean
}
```

### 2. 修改 DataView 树表

文件：

```text
frontend/src/views/DataView.vue
```

必须做：

- `row-key` 从 `standard_account_id` 改为 `node_id`。
- 删除“操作”列。
- 删除 `el-dialog` 明细弹窗。
- 删除这些状态和函数：

```ts
detailVisible
detailTitle
detailLoading
detailEntries
detailAccountId
fetchEntries()
openDetail()
nextTick
TrialBalanceEntry
TrialBalanceEntryListResponse
```

如果 `nextTick` 没有其他用途，从 Vue import 中删除。

树表改为：

```vue
<el-table
  :data="treeData"
  row-key="node_id"
  :tree-props="{ children: 'children', hasChildren: 'has_children' }"
  :default-expand-all="false"
  border
  stripe
  v-loading="treeLoading"
  size="small"
  style="width: 100%"
  :max-height="tableMaxHeight"
>
```

科目代码列：

```vue
<el-table-column prop="account_code" label="科目代码" width="150" fixed="left">
  <template #default="{ row }">
    <span :class="{ 'entry-code': row.node_type === 'entry' }">
      {{ row.account_code || '-' }}
    </span>
  </template>
</el-table-column>
```

科目名称列：

```vue
<el-table-column prop="account_name" label="科目名称 / 客户明细" min-width="260">
  <template #default="{ row }">
    <span
      class="account-name-cell"
      :class="{ 'entry-row-text': row.node_type === 'entry' }"
      :title="row.node_type === 'entry'
        ? `${row.client_account_code || ''} ${row.client_account_name || ''}`
        : `${row.account_code || ''} ${row.account_name || ''}`"
    >
      <el-tag v-if="row.node_type === 'entry'" size="small" type="info" effect="plain">
        客户
      </el-tag>
      <span>{{ row.account_name }}</span>
    </span>
  </template>
</el-table-column>
```

条目数列：

```vue
<el-table-column label="条目数" width="80" align="center">
  <template #default="{ row }">
    <span v-if="row.node_type === 'account'">{{ row.entry_count || '-' }}</span>
    <span v-else class="entry-count-dot">明细</span>
  </template>
</el-table-column>
```

### 3. 修复横向滚动和金额省略

当前用户指出：金额大了会被省略，且不能左右滑动。

要求：

- `.tree-table-wrap` 必须允许横向滚动。
- 不要让 fixed 右列遮住内容，因为操作列会删除。
- 金额列宽度至少 150，建议 160。
- 金额单元格不允许 `text-overflow: ellipsis`。

CSS 建议：

```css
.tree-table-wrap {
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  overflow-x: auto;
  overflow-y: hidden;
}

.tree-table-wrap :deep(.el-table) {
  min-width: 1320px;
}

.tree-table-wrap :deep(.el-table__body-wrapper),
.tree-table-wrap :deep(.el-scrollbar__wrap) {
  overflow-x: auto;
}

.tree-table-wrap :deep(.cell) {
  overflow: visible;
  text-overflow: initial;
}

.account-name-cell {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  white-space: normal;
  line-height: 1.4;
}

.entry-row-text {
  color: var(--text-secondary);
}

.entry-code {
  color: var(--text-secondary);
  font-family: var(--font-family-mono, monospace);
}

.entry-count-dot {
  color: var(--text-placeholder);
  font-size: var(--font-size-xs);
}
```

如果 Element Plus 内部仍然截断金额，应给金额 span 加 class：

```vue
<span class="amount-cell" :class="{ 'zero-amount': !hasAmount(row.opening_debit) }">
  {{ formatAmount(row.opening_debit) }}
</span>
```

CSS：

```css
.amount-cell {
  display: inline-block;
  min-width: max-content;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
```

### 4. 保持现有筛选逻辑

以下功能必须保留：

- 批次选择。
- 年度筛选。
- 期间筛选。
- 只看有金额科目。
- 自动选中最新批次。
- 空状态展示。

## 验收命令

后端：

```powershell
cd backend
D:\python\python.exe -m pytest tests/test_standard_trial_balance_view.py -q
D:\python\python.exe -m pytest tests/ -q
```

前端：

```powershell
cd frontend
npm run build
```

## 人工验收标准

打开数据查看页后：

1. 表格左侧有树形展开箭头。
2. 不再出现“查看明细”按钮列。
3. 不再弹出“客户原始科目明细”对话框。
4. 展开标准科目后，可以直接看到客户原始科目明细行。
5. 客户明细行有视觉区分，例如“客户”标签。
6. 大金额完整显示，不被省略。
7. 表格可以左右横向滚动。
8. `1411 周转材料 -> 141101 包装物 -> 客户明细` 这种层级能自然展开。

## 给执行 AI 的提示词

你是执行 TASK-069 的代码代理。请只改数据查看树形 UI 和 tree API，不要改科目匹配算法。  
当前问题：数据查看页右侧有“查看明细”按钮，点击后弹窗显示客户原始明细，用户不接受。需要改成树形表：标准科目节点展开后，客户原始明细作为子节点直接显示在表格中，类似行首展开箭头。  
后端 `/standard-trial-balances/tree` 需要返回 `node_id`、`node_type=account/entry`，并把 `StandardTrialBalanceEntry` 拼进对应标准科目的 `children`。前端 `DataView.vue` 用 `row-key=node_id` 渲染一棵树，删除操作列和明细弹窗。还要修复大金额省略和不能横向滚动的问题。  
先写后端失败测试，再改 schema/service/frontend/types，最后跑 `test_standard_trial_balance_view.py`、全量后端测试和 `npm run build`。
