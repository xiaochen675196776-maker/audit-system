# TASK-077：修复安全候选排序和客户层级重复挂载，真实文件不得再把 160402 入减值准备

**Status:** DONE  
**Priority:** P0  
**Owner:** 待领取  
**Created:** 2026-06-24  

## 验收记录

2026-06-25 已验收通过：

```text
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest tests/test_client_account_mapping_service.py tests/test_standard_trial_balance_import.py tests/test_standard_trial_balance_view.py -q
120 passed, 1 warning

D:\python\python.exe -m pytest -q
385 passed, 3 warnings
```

```text
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
build passed
```

真实文件验收：

```text
cd D:\APP\Codex-项目\13、审计系统\backend
$env:PYTHONIOENCODING='utf-8'
D:\python\python.exe scripts\acceptance_task076_real_file.py
TASK076_REAL_ACCEPTANCE_PASSED
```

关键输出：

```json
{
  "preview_total_rows": 289,
  "active_recommendations": 201,
  "unmatched_count": 0,
  "warning_count": 0,
  "error_count": 0,
  "entry_count": 201,
  "raw_row_count": 289,
  "snapshots": {
    "141201": "141101",
    "141301": "141102",
    "160402": "160401",
    "660401": "660201",
    "5301010101": "170402",
    "<科目代码样例005>": "170402"
  },
  "tree": {
    "170402_entry_count": 24,
    "170402_recursive_entry_nodes": 24,
    "2221_entry_count": 11,
    "2221_recursive_entry_nodes": 11,
    "660201_entry_count": 1,
    "660201_recursive_entry_nodes": 1
  }
}
```

独立补充校验也已通过：真实 Excel 中 `160402 在建工程_生产线` 的 `candidates[0]` 已是安全候选 `160401 在建工程-原值`，`160402 减：在建工程-减值准备` 降级为第二候选且带 warning。用 `candidates[0]` 全量自动确认后，仍然入库 201 条，`160402 -> 160401`，并且 `170402/2221/660201` 递归 entry 节点数与 `entry_count` 一致。

## 背景

TASK-076 的单元测试和构建能通过，但真实文件验收仍失败。

真实文件：

```text
D:/NAS/xiaochen/**/aglq710-*20251231.xlsx
```

已跑过的验证：

```text
D:\python\python.exe -m pytest tests/test_standard_account_import.py tests/test_standard_trial_balance_view.py tests/test_standard_trial_balance_import.py tests/test_client_account_mapping_service.py -q
149 passed

D:\python\python.exe -m pytest -q
382 passed

npm run build
build passed
```

自带脚本 `backend/scripts/acceptance_task076_real_file.py` 在 UTF-8 输出下能通过，但它不是严格真实文件验收：脚本内部手工创建了少量 raw row / entry，并没有真正执行真实 Excel 的 `preview -> analyze -> execute` 导入链路。因此它不能作为 TASK-076 完成依据，必须改掉。

## 真实文件验收结果

我用临时 SQLite DB 跑了真实文件导入，不污染开发数据库。导入链路本身能跑通：

```json
{
  "preview_total_rows": 289,
  "recommendations": 289,
  "active_recommendations": 201,
  "confirmed_mappings": 201,
  "unmatched_count": 0,
  "all_warned_count": 0,
  "warning_count": 0,
  "error_count": 0,
  "execute": {
    "status": "executed",
    "entry_count": 201,
    "raw_row_count": 289,
    "mapping_saved_count": 0
  }
}
```

但是关键映射失败：

```json
{
  "160402": {
    "client_name": "在建工程_生产线",
    "standard_code": "160402",
    "standard_name": "减：在建工程-减值准备"
  }
}
```

期望：

```json
{
  "160402": {
    "client_name": "在建工程_生产线",
    "standard_code": "160401",
    "standard_name": "在建工程-原值"
  }
}
```

这说明用户截图里的问题还没有修完：客户 `160402 在建工程_生产线` 仍然进入标准科目 `160402 减：在建工程-减值准备`。

## 失败根因 1：warning 候选排在安全候选前

真实 Excel 的 `160402 在建工程_生产线` 分析候选如下：

```json
{
  "client_account_code": "160402",
  "client_account_name": "在建工程_生产线",
  "candidates": [
    {
      "standard_account_code": "160402",
      "standard_account_name": "减：在建工程-减值准备",
      "score": 0.72,
      "source": "code_match_conflict",
      "warning": "代码相同但标准科目为备抵/减值类「减：在建工程-减值准备」，客户名称「在建工程_生产线」未体现减值/准备/累计折旧等含义，请勿自动归入",
      "standard_balance_direction": "credit"
    },
    {
      "standard_account_code": "160401",
      "standard_account_name": "在建工程-原值",
      "score": 0.93,
      "source": "semantic_alias",
      "warning": null,
      "standard_balance_direction": "debit"
    }
  ],
  "row_index": 45,
  "is_leaf": true,
  "participates_in_entry": true
}
```

问题不是没有识别出 `160401`，而是 `code_match_conflict` 带 warning 的候选仍排在第一。导入确认逻辑或 UI 只要取 `candidates[0]`，就会错。

已有测试只断言：

```python
safe_original exists
bad_impairment does not exist as safe candidate
```

这个断言不够。必须新增断言：

```python
cands[0]["standard_account_code"] == "160401"
cands[0]["warning"] is None
float(cands[0]["score"]) >= 0.9
```

## 失败根因 2：合成客户层级重复挂载

真实文件导入后查询树已经能出现客户中间层，但存在重复挂载：

```json
{
  "170402": {
    "entry_count": 24,
    "client_group_count": 41,
    "entry_node_count": 122,
    "client_group_codes_head": [
      "530101",
      "53010101",
      "5301010102",
      "5301010102",
      "5301010102"
    ]
  },
  "2221": {
    "entry_count": 11,
    "client_group_count": 14,
    "entry_node_count": 25,
    "client_group_codes_head": [
      "222101",
      "22210101",
      "22210101",
      "22210101"
    ]
  },
  "660201": {
    "entry_count": 7,
    "client_group_count": 23,
    "entry_node_count": 19
  }
}
```

对于这些标准科目节点，`entry_node_count` 不应大于 `entry_count`。同一个 `client_group` / `entry` 不能被重复追加到父级 `children`。

高概率位置：

```text
backend/app/services/standard_trial_balance_service.py
```

`_build_node()` 内构造 synthetic path 时，已经用 `local_client_nodes[synth_key]` 去复用节点，但每处理一条 entry 都会再次把同一个 group append 到父级 `children`。需要用 edge 去重，或者在 append 前检查 parent container 里是否已有相同 `node_id`。

## 必修任务

### 1. 修正候选排序，安全候选必须排在 warning 候选前

文件：

```text
backend/app/services/client_account_mapping_service.py
```

要求：

1. 增加统一候选排序函数，例如 `_sort_candidates(candidates)`。
2. 排序规则必须先区分“可自动确认安全候选”：
   - 安全候选：`warning is None` 且 `score >= 0.9`。
   - 非安全候选：`warning != None` 或 `score < 0.9`。
3. 只要存在安全候选，安全候选必须排在所有非安全候选前。
4. 安全候选内部再按既有来源优先级排序：
   - `company_history`
   - `global_history`
   - `code_match` / `name_exact` / `name_prefix`
   - `semantic_alias`
   - 其他安全兜底
5. 非安全候选内部也可以按既有来源优先级和 score 排序，但不能排到安全候选前。
6. 在 `recommend_mappings()` 每个 entry 完成所有候选构造、冲突降级、兜底补充后，统一排序，再截断前 10 个候选。
7. 不要只在 `_resolve_exact_code_vs_exact_name_conflict()` 触发时排序。`_build_code_match_candidate()` 自己产生的 `code_match_conflict` 也必须被排序收口。

关键断言：

```python
result = await recommend_mappings(
    db,
    data_type="trial_balance",
    client_accounts=[{"client_account_code": "160402", "client_account_name": "在建工程_生产线"}],
)
cands = result[0]["candidates"]
assert cands[0]["standard_account_code"] == "160401"
assert cands[0]["warning"] is None
assert float(cands[0]["score"]) >= 0.9
assert any(c["standard_account_code"] == "160402" and c["warning"] for c in cands)
```

### 2. 自动确认逻辑不能盲取 warning 首项

搜索所有自动确认候选的位置：

```text
rg -n "candidates\\[0\\]|cands\\[0\\]|candidates\\.at\\(0\\)|mapping_recommendations" backend frontend
```

要求：

1. 后端、前端、验收脚本中凡是“自动选中推荐候选”的逻辑，都应优先取第一条安全候选：

```python
safe = next(
    (c for c in candidates if not c.get("warning") and float(c.get("score", 0) >= 0.9)),
    None,
)
picked = safe or candidates[0]
```

TypeScript 同理。

2. 如果没有安全候选，才允许 fallback 到首项，并且 UI 必须仍显示需要人工确认。
3. 真实文件验收脚本需要保留对候选排序的硬断言：`160402` 的 `candidates[0]` 必须是 `160401`，避免以后又回退。

### 3. 修复合成客户层级重复挂载

文件：

```text
backend/app/services/standard_trial_balance_service.py
```

要求：

1. `_build_node()` 合成 synthetic client_group 时，同一父节点下同一 `node_id` 只能 append 一次。
2. 可以实现一个小函数：

```python
def _append_unique_child(container: list[dict], child: dict) -> None:
    if not any(existing.get("node_id") == child.get("node_id") for existing in container):
        container.append(child)
```

3. 每次 `parent_container.append(local_client_nodes[synth_key])` 都改为唯一追加。
4. raw parent chain 分支也要检查是否会重复 append，同样做唯一追加。
5. 同一条 entry 节点只能出现一次，不允许同一 `entry_id` 在同一标准科目子树下重复出现。
6. 修复后真实文件应满足：

```text
170402 entry_count == 24，递归 entry 节点数量 == 24
2221 entry_count == 11，递归 entry 节点数量 == 11
660201 entry_count == 7，递归 entry 节点数量 == 7
```

### 4. 重写真实文件验收脚本

文件：

```text
backend/scripts/acceptance_task076_real_file.py
```

要求：

1. 不要再手工构造 raw row / entry。
2. 必须真正执行：

```text
seed_standard_accounts
preview_standard_import
analyze_standard_import
execute_standard_import
get_tree
```

3. 使用真实文件：

```python
file_path = list(Path("D:/NAS/xiaochen").rglob("aglq710-*20251231.xlsx"))[0]
```

4. 字段映射：

```python
field_mappings = [
    {"column_id": "col_0", "field_name": "account_code"},
    {"column_id": "col_1", "field_name": "account_name"},
    {"column_id": "col_2", "field_name": "opening_debit", "period_type": "opening", "split_mode": "two_column", "debit_column_id": "col_2", "credit_column_id": "col_3"},
    {"column_id": "col_3", "field_name": "opening_credit", "period_type": "opening", "split_mode": "two_column", "debit_column_id": "col_2", "credit_column_id": "col_3"},
    {"column_id": "col_4", "field_name": "current_debit", "period_type": "current", "split_mode": "two_column", "debit_column_id": "col_4", "credit_column_id": "col_5"},
    {"column_id": "col_5", "field_name": "current_credit", "period_type": "current", "split_mode": "two_column", "debit_column_id": "col_4", "credit_column_id": "col_5"},
    {"column_id": "col_6", "field_name": "ending_debit", "period_type": "ending", "split_mode": "two_column", "debit_column_id": "col_6", "credit_column_id": "col_7"},
    {"column_id": "col_7", "field_name": "ending_credit", "period_type": "ending", "split_mode": "two_column", "debit_column_id": "col_6", "credit_column_id": "col_7"},
]
```

5. 脚本断言必须覆盖：

```text
preview_total_rows == 289
active_recommendations == 201
unmatched_count == 0
warning_count == 0
error_count == 0
execute.entry_count == 201
raw_row_count == 289

141201 -> 141101
141301 -> 141102
160402 -> 160401
660401 -> 660201
5301010101 -> 170402
<科目代码样例005> -> 170402

170401.level == 2 and parent_code == 1704
170402.level == 2 and parent_code == 1704

2221 下存在 client_group 222101 和 22210101
170402 下存在 client_group 530101 和 53010101

170402 递归 entry 节点数量 == 170402.entry_count == 24
2221 递归 entry 节点数量 == 2221.entry_count == 11
660201 递归 entry 节点数量 == 660201.entry_count == 7

整棵树不能出现重复 node_id
```

6. 不要打印 `✓` 这类 Windows GBK 下会失败的字符；用 `PASS` / `FAIL` 即可，或者在脚本顶部明确要求 UTF-8。

## 必补测试

### 后端匹配测试

文件：

```text
backend/tests/test_client_account_mapping_service.py
```

补强已有 `TestConstructionImpairmentConflict.test_construction_in_progress_same_code_not_impairment`：

```python
assert cands[0]["standard_account_code"] == "160401"
assert cands[0]["warning"] is None
assert float(cands[0]["score"]) >= 0.9
```

同时保留：

```python
assert not bad_impairment
assert any(c["standard_account_code"] == "160402" and c["warning"] for c in cands)
```

### 标准余额表导入集成测试

文件：

```text
backend/tests/test_standard_trial_balance_import.py
```

新增测试：构造一张最小 Excel：

```text
科目代码 | 科目名称         | 期初借方 | 期初贷方 | 本期借方 | 本期贷方 | 期末借方 | 期末贷方
160402   | 在建工程_生产线  | 0       | 0       | 100     | 0       | 100     | 0
```

seed / 插入标准科目：

```text
160401 在建工程-原值，debit
160402 减：在建工程-减值准备，credit
```

测试必须模拟真实自动确认：直接取 `rec["candidates"][0]` 作为确认目标。执行后断言：

```python
entry.client_account_code == "160402"
entry.standard_account_code_snapshot == "160401"
```

这个测试是为了防止“列表里有正确候选但排第二”的回归。

### 查询树去重测试

文件：

```text
backend/tests/test_standard_trial_balance_view.py
```

新增测试：同一个标准科目下多条客户明细共享同一个合成父级，例如：

```text
5301010101 研发支出_费用化支出_人工_工资及奖金
5301010102 研发支出_费用化支出_人工_福利费
5301010201 研发支出_费用化支出_直接投入_材料
```

都映射到 `170402`。

断言：

```python
node_170402["entry_count"] == 3
recursive_entry_count(node_170402) == 3
has_client_group("530101") is True
has_client_group("53010101") is True
len(all_node_ids) == len(set(all_node_ids))
```

再补一个 `2221` 示例也可以：

```text
2221010101 应交税费_应交增值税_进项税额_货物进项税
2221010102 应交税费_应交增值税_进项税额_固定资产进项税
```

都映射到 `2221`，断言 `222101/22210101` 只出现一次层级链，不重复。

## 验收命令

必须全部通过：

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest tests/test_client_account_mapping_service.py tests/test_standard_trial_balance_import.py tests/test_standard_trial_balance_view.py -q
D:\python\python.exe -m pytest -q
```

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
$env:PYTHONIOENCODING='utf-8'
D:\python\python.exe scripts\acceptance_task076_real_file.py
```

真实文件验收脚本最后必须输出类似：

```text
TASK076_REAL_ACCEPTANCE_PASSED
```

并列出这些关键摘要：

```json
{
  "preview_total_rows": 289,
  "active_recommendations": 201,
  "unmatched_count": 0,
  "warning_count": 0,
  "error_count": 0,
  "entry_count": 201,
  "snapshots": {
    "141201": "141101",
    "141301": "141102",
    "160402": "160401",
    "660401": "660201",
    "5301010101": "170402",
    "<科目代码样例005>": "170402"
  },
  "tree": {
    "170402_entry_count": 24,
    "170402_recursive_entry_nodes": 24,
    "2221_entry_count": 11,
    "2221_recursive_entry_nodes": 11,
    "660201_entry_count": 7,
    "660201_recursive_entry_nodes": 7
  }
}
```

## 给执行 AI 的提示词

你要修 TASK-077。先阅读 `docs/tasks/TASK-077-safe-candidate-order-and-synthetic-tree-dedup.md`，不要跳过验收失败证据。核心问题有两个：

1. 真实 Excel 中 `160402 在建工程_生产线` 的候选列表里，`160402 减：在建工程-减值准备` 已经被降级为 `code_match_conflict` 且有 warning，但它仍排在第一，安全候选 `160401 在建工程-原值` 排在第二，导致自动确认取首项时错导入。你必须修候选排序：只要存在 `warning is None` 且 `score >= 0.9` 的安全候选，它必须排在所有 warning/低分候选前。补测试断言 `cands[0] == 160401`，不能只断言列表里有 160401。

2. 查询树的 synthetic client_group 重复挂载。真实文件下 `170402.entry_count=24`，但递归 entry 节点数是 122；`2221.entry_count=11`，但递归 entry 节点数是 25。修 `standard_trial_balance_service.py` 的合成客户层级构造，同一父节点下同一 `node_id` 只能 append 一次，整棵树不能重复 node_id。

同时重写 `backend/scripts/acceptance_task076_real_file.py`，它现在是假真实验收，手工造数据。必须改成真正读取 `D:/NAS/xiaochen/**/aglq710-*20251231.xlsx`，执行 `preview_standard_import -> analyze_standard_import -> execute_standard_import -> get_tree`，并硬断言 289 行、201 条入库、未匹配 0、warning/error 0、`160402 -> 160401`、`2221/170402` 客户中间层存在且不重复。

完成后跑：

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest tests/test_client_account_mapping_service.py tests/test_standard_trial_balance_import.py tests/test_standard_trial_balance_view.py -q
D:\python\python.exe -m pytest -q
$env:PYTHONIOENCODING='utf-8'
D:\python\python.exe scripts\acceptance_task076_real_file.py
```

再跑：

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

交付时必须贴出真实文件验收摘要，尤其是 `160402` 映射、`170402/2221/660201` 的 entry_count 与递归 entry 节点数一致性。
