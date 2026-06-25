# TASK-071：修复数据查询页分类展示、期末贷方不可见、科目代码/名称冻结

> 交给其他 AI 执行时，请完整复制本文件。  
> 本任务是用户最新反馈，不要只跑旧的 TASK-068/069/070 测试就说完成。

## 用户反馈

1. `包装物` 和 `低值易耗品` 还是“归类到周转材料下面”。
2. 数据查询界面只能看见 `期末借方余额`，看不了 `期末贷方余额`。
3. UI 应当将 `科目代码` 和 `科目名称` 都做成冻结单元格。

## 当前已知现状

当前代码位置：

```text
backend/app/services/client_account_mapping_service.py
backend/app/services/standard_trial_balance_service.py
backend/tests/test_client_account_mapping_service.py
backend/tests/test_standard_trial_balance_view.py
frontend/src/views/DataView.vue
frontend/src/types/index.ts
```

当前 `DataView.vue` 已有：

```vue
<el-table-column prop="account_code" label="科目代码" width="150" fixed="left" />
<el-table-column prop="account_name" label="科目名称 / 客户明细" min-width="260">
```

也就是说现在只冻结了 `科目代码`，没有冻结 `科目名称`。

当前金额列里已经有 `期末贷方余额`：

```vue
<el-table-column label="期末贷方余额" width="160" align="right">
  {{ formatAmount(row.ending_credit) }}
</el-table-column>
```

所以“看不了期末贷方余额”大概率不是字段缺失，而是横向滚动/列宽/fixed 布局导致右侧列被挡住或无法滚到。

关于 `包装物/低值易耗品`：

标准库当前确实是：

```text
1411   周转材料
141101 包装物
141102 低值易耗品
```

但用户已经明确不接受“看起来归到周转材料下面”的效果。因此这次不能只解释“这是标准层级”。必须先核验实际入库目标，如果实际写入 `1411` 就修匹配/导入；如果实际写入 `141101/141102`，就修查询页展示，让用户能明确看到它们是独立标准明细科目，不是被汇总成 `1411 周转材料`。

## 目标

### 目标 A：包装物/低值易耗品不得实际入库到 1411

必须验证并保证：

```text
客户 1411 包装物           -> 入库 standard_account_code_snapshot = 141101
客户 1411 包装物_纸箱      -> 入库 standard_account_code_snapshot = 141101
客户 1411 低值易耗品       -> 入库 standard_account_code_snapshot = 141102
客户 1411 低值易耗品_工具  -> 入库 standard_account_code_snapshot = 141102
客户 1411 周转材料         -> 入库 standard_account_code_snapshot = 1411
```

不能只看推荐候选，要走到 `execute_standard_import()` 之后查 `StandardTrialBalanceEntry`。

### 目标 B：查询页不要让用户误以为包装物/低值易耗品被“归入周转材料”

数据查看树里必须满足：

- `1411 周转材料` 可以作为标准父级存在，但客户明细不得直接挂在 `1411` 下，除非它真实入库标准科目就是 `1411`。
- `包装物` 客户明细必须挂在 `141101 包装物` 节点下。
- `低值易耗品` 客户明细必须挂在 `141102 低值易耗品` 节点下。
- UI 上要清楚显示 entry 行对应的标准科目代码/名称，避免用户只看到父级。

推荐展示：

```text
1411 周转材料
  141101 包装物
    客户明细：1411 包装物_纸箱       标准：141101 包装物
  141102 低值易耗品
    客户明细：1411 低值易耗品_工具   标准：141102 低值易耗品
```

如果当前视觉上仍然让用户感觉“都归到周转材料”，需要在 entry 行增加 `标准科目` 标签或列，例如：

```text
客户：包装物_纸箱   标准：141101 包装物
```

不要只显示客户名称。

### 目标 C：查询表格能看到所有 6 个金额列

金额列必须都能看见：

```text
期初借方余额
期初贷方余额
本期借方发生额
本期贷方发生额
期末借方余额
期末贷方余额
```

尤其是 `期末贷方余额` 不能被挡住、不能只能靠不可见滚动条猜测。

### 目标 D：冻结科目代码和科目名称

数据查询页表格左侧必须冻结两列：

```text
科目代码
科目名称 / 客户明细
```

滚动金额列时，代码和名称两列保持可见。

## 任务 1：后端入库与树结构核验

### 修改/新增测试

文件：

```text
backend/tests/test_standard_trial_balance_import.py
backend/tests/test_standard_trial_balance_view.py
```

新增一个集成测试，构造最小科目余额表或直接调用推荐/执行服务，必须走到 `StandardTrialBalanceEntry` 查询。

测试意图：

```python
@pytest.mark.asyncio
async def test_packaging_consumables_execute_to_child_standard_accounts(db):
    """包装物/低值易耗品不能实际入库到 1411 周转材料"""
```

测试数据至少包含：

```text
1411   包装物             期末借 100
1411   低值易耗品          期末借 200
1411   包装物_纸箱         期末借 300
1411   低值易耗品_工具     期末借 400
1411   周转材料            期末借 500
```

验收断言：

```python
entries = await db.execute(select(StandardTrialBalanceEntry))
rows = entries.scalars().all()

by_client_name = {e.client_account_name: e for e in rows}
assert by_client_name["包装物"].standard_account_code_snapshot == "141101"
assert by_client_name["低值易耗品"].standard_account_code_snapshot == "141102"
assert by_client_name["包装物_纸箱"].standard_account_code_snapshot == "141101"
assert by_client_name["低值易耗品_工具"].standard_account_code_snapshot == "141102"
assert by_client_name["周转材料"].standard_account_code_snapshot == "1411"
```

同时在 `test_standard_trial_balance_view.py` 增加树结构测试：

```python
@pytest.mark.asyncio
async def test_tree_places_packaging_entries_under_child_nodes_not_parent(db):
    """查询树中，包装物/低值易耗品客户明细必须挂在 141101/141102 节点下，不得直接挂在 1411 下"""
```

断言：

```python
root_1411 = find_node(nodes, "1411")
node_141101 = find_node(nodes, "141101")
node_141102 = find_node(nodes, "141102")

assert any(child["node_type"] == "entry" and child["client_account_name"] == "包装物_纸箱" for child in node_141101["children"])
assert any(child["node_type"] == "entry" and child["client_account_name"] == "低值易耗品_工具" for child in node_141102["children"])
assert not any(child["node_type"] == "entry" and child["client_account_name"] in {"包装物_纸箱", "低值易耗品_工具"} for child in root_1411["children"])
```

如果这些测试失败，先修后端数据流，不要先改 UI。

## 任务 2：前端展示标准科目归属，避免误读为父级

文件：

```text
frontend/src/types/index.ts
frontend/src/views/DataView.vue
```

### 类型要求

如果 `TreeNode` 还没有 entry 对应的标准快照字段，补齐：

```ts
standard_account_code?: string | null
standard_account_name?: string | null
```

或者复用现有 `standard_account_id/account_code/account_name`，但 entry 行必须能明确展示“标准：141101 包装物”。

### UI 要求

在 entry 行的名称列中显示：

```vue
<template v-if="row.node_type === 'entry'">
  <el-tag size="small" type="info" effect="plain">客户</el-tag>
  <span>{{ row.client_account_code }} {{ row.client_account_name }}</span>
  <el-tag size="small" type="success" effect="plain">
    标准：{{ row.standard_account_code || row.parent_account_code || row.account_code }}
    {{ row.standard_account_name || row.parent_account_name || row.account_name }}
  </el-tag>
</template>
```

具体字段名按后端实际返回来定，但视觉必须能看出来：

```text
客户：1411 包装物_纸箱
标准：141101 包装物
```

不要让 entry 行只显示 `包装物_纸箱`，否则用户看父级树时仍然会以为它被归入 `周转材料`。

## 任务 3：冻结科目代码和科目名称两列

文件：

```text
frontend/src/views/DataView.vue
```

修改为：

```vue
<el-table-column
  prop="account_code"
  label="科目代码"
  width="150"
  fixed="left"
/>

<el-table-column
  prop="account_name"
  label="科目名称 / 客户明细"
  width="320"
  fixed="left"
>
```

注意：

- 第二列要有明确 `width`，不要只用 `min-width`，否则 Element Plus 的 fixed left 计算可能不稳定。
- 两个 fixed left 列宽度合计约 `470px`，金额表体从右侧开始横向滚动。
- 如果名称过长，名称列内部换行或 tooltip，不能撑坏 fixed 列。

建议 CSS：

```css
.account-name-cell {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  white-space: normal;
  line-height: 1.4;
}
```

## 任务 4：修复期末贷方余额不可见

文件：

```text
frontend/src/views/DataView.vue
```

### 必须检查并修复

当前 `.tree-table-wrap` 已有：

```css
overflow-x: auto;
```

但用户仍然看不到右侧 `期末贷方余额`，所以不要只说“已经有 overflow-x”。

需要实际验证 Element Plus 表格横向滚动条是否出现、是否能滚到最右。

建议修改：

```vue
<el-table
  class="trial-balance-tree-table"
  :data="treeData"
  row-key="node_id"
  ...
>
```

CSS：

```css
.tree-table-wrap {
  width: 100%;
  overflow: hidden;
}

.trial-balance-tree-table {
  width: 100%;
}

.trial-balance-tree-table :deep(.el-table__inner-wrapper) {
  min-width: 1510px;
}

.trial-balance-tree-table :deep(.el-scrollbar__wrap) {
  overflow-x: auto !important;
}

.trial-balance-tree-table :deep(.el-table__body-wrapper) {
  overflow-x: auto !important;
}
```

更稳的方案是让列宽总和明确：

```text
科目代码 150 fixed
科目名称 320 fixed
方向 70
期初借 150
期初贷 150
本期借 150
本期贷 150
期末借 150
期末贷 150
条目数 80
合计 = 1520
```

所以表格内部最小宽度不应低于：

```css
min-width: 1520px;
```

不要使用全局：

```css
.tree-table-wrap :deep(.cell) {
  overflow: visible;
}
```

这个可能破坏 Element Plus fixed/scroll 裁剪计算。改为只对金额文本做 nowrap：

```css
.amount-cell {
  display: inline-block;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
```

## 任务 5：视觉验收必须做截图

不能只跑 `npm run build`。

用浏览器打开数据查询页，至少验证两个视口：

```text
1366 x 768
1920 x 1080
```

人工/截图验收：

- 左侧 `科目代码`、`科目名称 / 客户明细` 两列固定。
- 向右滚动后，左侧两列仍可见。
- 向右滚动到最右后，能看到 `期末贷方余额`。
- `期末贷方余额` 的金额完整显示，不被截断，不被 fixed 列盖住。
- 包装物/低值易耗品 entry 行能看到“标准：141101 包装物 / 141102 低值易耗品”。

如果当前没有浏览器自动化工具，至少运行前端 dev server 并让用户截图确认；但优先使用 Playwright/浏览器工具实际截图。

## 验收命令

后端：

```powershell
cd backend
D:\python\python.exe -m pytest tests/test_client_account_mapping_service.py -q
D:\python\python.exe -m pytest tests/test_standard_trial_balance_import.py -q
D:\python\python.exe -m pytest tests/test_standard_trial_balance_view.py -q
D:\python\python.exe -m pytest tests/ -q
```

前端：

```powershell
cd frontend
npm run build
```

真实文件回归：

继续使用：

```text
D:\NAS\xiaochen\李辉辉项目组\SynologyDrive\汇达228股改审计\1.账套\aglq710-科目余额表 20251231.xlsx
```

要求：

```text
unmatched = 0
warnings = 0
execute status = executed
rollback 完成
```

## 给执行 AI 的提示词

你来领取并执行这个任务：

```text
D:/APP/Codex-项目/13、审计系统/docs/tasks/TASK-071-data-view-classification-and-frozen-columns.md
```

请完整阅读任务文件后再动代码。  
用户最新反馈有三个点：  
1. 包装物/低值易耗品看起来还是归类到周转材料下面；  
2. 数据查询页只能看到期末借方余额，看不到期末贷方余额；  
3. 科目代码和科目名称都要冻结。  

你必须先区分“实际入库到了 1411”还是“树形展示父级路径导致用户误解”。新增后端测试要走到 `StandardTrialBalanceEntry`，断言包装物/低值易耗品实际入库标准科目是 `141101/141102`，不是 `1411`。查询树中客户明细必须挂在 `141101/141102` 节点下，不得直接挂在 `1411` 下。  

前端 `DataView.vue` 要冻结左侧两列：`科目代码` 和 `科目名称 / 客户明细`。修复横向滚动，确保能滚到并看到 `期末贷方余额`。entry 行要显示客户原始科目和标准科目归属，例如 `客户：1411 包装物_纸箱`、`标准：141101 包装物`，避免用户误以为被归入周转材料。  

必须跑后端专项测试、全量后端测试、`npm run build`，并用浏览器截图或人工确认横向滚动和冻结列。
