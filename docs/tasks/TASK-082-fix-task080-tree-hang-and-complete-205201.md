# TASK-082：修复 TASK-080 当前验收超时，先解决会展树构建卡死，再完成 205201 全链路

**Status:** TODO  
**Priority:** P0  
**Created:** 2026-06-25  
**Owner:** 待领取  

## 硬性约束

除非用户明确发布命令，否则不允许新增、删除或修改标准库科目。

本次验收已确认当前标准库语义未变化：

```json
{
  "old_count": 207,
  "new_count": 207,
  "added_code_count": 0,
  "removed_code_count": 0,
  "changed_count": 0
}
```

后续修复必须继续保持：

```text
added_code_count == 0
removed_code_count == 0
changed_count == 0
```

禁止通过修改 `backend/app/data/standard_accounts_seed.py` 跑通样本。允许修改算法、解析、crosswalk、父级继承、性能和验收脚本。

## 本次验收结论

TASK-080 仍未通过。

已通过：

```text
backend 定向测试：136 passed
backend 全量测试：385 passed
frontend npm run build：通过
标准库语义比对：0 新增、0 删除、0 修改
```

未通过：

```text
D:\python\python.exe scripts\acceptance_task080_six_trial_balance_templates.py
```

完整 6 文件验收脚本 15 分钟超时，没有输出 `TASK080_SIX_TRIAL_BALANCE_TEMPLATES_PASSED`。

## 当前关键事实

### 1. 验收脚本已经加入标准库保护和 tree_error 断言

`backend/scripts/acceptance_task080_six_trial_balance_templates.py` 已包含：

```text
assert_standard_seed_not_changed
tree_error
tree_total_nodes > 0
TASK080_SIX_TRIAL_BALANCE_TEMPLATES_PASSED
```

这一点是正确的。后续不要移除这些断言。

### 2. 当前完整脚本超时的第一阻塞是会展中心

按 `REAL_FILES` 顺序，第一张就是：

```text
D:/APP/谷歌/文件下载/会展中心余额表.xlsx
```

单独跑 `run_one(会展中心)` 3 分钟超时。

拆阶段结果：

```json
{
  "file": "会展中心余额表.xlsx",
  "preview_rows": 266,
  "preview_sec": 0.03,
  "analyze_recs": 266,
  "analyze_errors": 0,
  "analyze_warnings": 0,
  "analyze_sec": 9.82,
  "confirmed": 188,
  "execute_status": "executed",
  "entry_count": 188,
  "execute_sec": 1.11,
  "tree_status": "timeout_or_hang"
}
```

结论：会展中心不是 preview/analyze/execute 卡住，是 `get_tree(db, batch_id=...)` 卡住或无限递归。

### 3. 已确认通过的单文件

以下 4 张当前单文件可执行、可查树：

```json
[
  {
    "file": "1-12科目余额表.xls",
    "preview_total_rows": 1011,
    "active_recommendations": 926,
    "unmatched_count": 0,
    "unsafe_count": 0,
    "non_parent_warning_count": 0,
    "execute_status": "executed",
    "entry_count": 926,
    "tree_error": null,
    "tree_total_nodes": 975,
    "analyze_sec": 28.77,
    "execute_sec": 7.94
  },
  {
    "file": "科目余额表2023年导入.xls",
    "preview_total_rows": 181,
    "active_recommendations": 160,
    "unmatched_count": 0,
    "unsafe_count": 0,
    "non_parent_warning_count": 0,
    "execute_status": "executed",
    "entry_count": 160,
    "tree_error": null,
    "tree_total_nodes": 290,
    "analyze_sec": 2.76,
    "execute_sec": 1.07
  },
  {
    "file": "医疗3月31日序时账及余额表.xlsx",
    "preview_total_rows": 154,
    "active_recommendations": 87,
    "unmatched_count": 0,
    "unsafe_count": 0,
    "non_parent_warning_count": 0,
    "execute_status": "executed",
    "entry_count": 87,
    "tree_error": null,
    "tree_total_nodes": 269,
    "analyze_sec": 4.44,
    "execute_sec": 1.09
  },
  {
    "file": "科目余额表-成都迪康-240930.xls",
    "preview_total_rows": 404,
    "active_recommendations": 293,
    "unmatched_count": 0,
    "unsafe_count": 0,
    "non_parent_warning_count": 0,
    "execute_status": "executed",
    "entry_count": 293,
    "tree_error": null,
    "tree_total_nodes": 491,
    "analyze_sec": 14.45,
    "execute_sec": 2.81
  }
]
```

不要修一个问题又破坏这 4 张。

### 4. 205201 当前只确认 parse/preview 快，全链路还没有通过

轻量检查：

```json
{
  "file": "205201-2023.xls",
  "parse_rows": 98460,
  "data_start_row": 1,
  "headers": ["选择", "公司", "科目代码", "科目全称", "币种", "核算1", "核算1名", "核算2"],
  "parse_sec": 3.15,
  "preview_total_rows": 98455,
  "preview_sec": 3.53
}
```

但上次 `run_one(205201)` 单独运行 10 分钟超时。当前完整脚本还没跑到 205201 就被会展中心挡住，所以修完会展后必须重新验收 205201 全链路。

## 必须修复

### Task A：修复会展中心 get_tree 卡死

**文件：**

```text
backend/app/services/standard_trial_balance_service.py
backend/app/services/standard_trial_balance_import_service.py
backend/app/services/trial_balance_transform.py
backend/tests/test_standard_trial_balance_view.py
```

**复现方式：**

用临时 DB 导入：

```text
D:/APP/谷歌/文件下载/会展中心余额表.xlsx
```

字段映射：

```python
[
    {"column_id": "col_0", "field_name": "account_code"},
    {"column_id": "col_1", "field_name": "account_name"},
    {"column_id": "col_3", "field_name": "opening_amount", "period_type": "opening", "split_mode": "single_by_source_direction", "direction_column_id": "col_2"},
    {"column_id": "col_4", "field_name": "current_debit", "period_type": "current", "split_mode": "two_column", "debit_column_id": "col_4", "credit_column_id": "col_5"},
    {"column_id": "col_5", "field_name": "current_credit", "period_type": "current", "split_mode": "two_column", "debit_column_id": "col_4", "credit_column_id": "col_5"},
    {"column_id": "col_7", "field_name": "ending_amount", "period_type": "ending", "split_mode": "single_by_source_direction", "direction_column_id": "col_6"}
]
```

执行：

```python
nodes, total = await get_tree(db, batch_id=batch_id)
```

当前现象：卡死或超时。

**要求：**

1. 给树构建增加环检测，不能无限递归。
2. 找出会展中心数据中造成环的节点，修复父子关系生成逻辑。
3. 如果发现客户科目代码/名称导致同一个节点既是父又是子，要在构树前断开错误父链。
4. `get_tree` 必须满足：

```text
tree_error is None
tree_total_nodes > 0
dup_node_id_count == 0
tree_sec < 5
```

5. 新增或修正测试，至少覆盖：

```text
自引用 parent_id
两节点互相引用
重复 node_id
会展中心真实数据导入后 get_tree 不超时
```

### Task B：修复完整验收脚本超时定位能力

**文件：**

```text
backend/scripts/acceptance_task080_six_trial_balance_templates.py
```

当前完整脚本超时时，外部只能看到：

```text
command timed out
```

要求：

1. 每张表开始前必须 `flush=True` 输出文件名。
2. 每个阶段结束都 `flush=True` 输出耗时：

```text
parse_sec
preview_sec
analyze_sec
execute_sec
tree_sec
```

3. 单文件超过 120 秒时，应明确失败并进入下一张或退出，不要无输出卡死。
4. 可以使用 `asyncio.wait_for` 包住单文件：

```python
summary = await asyncio.wait_for(run_one(fdef, db), timeout=120)
```

但注意：如果被 timeout，必须输出该文件名和阶段，不要吞掉。

### Task C：会展修复后继续验收 205201 全链路

**文件：**

```text
backend/scripts/acceptance_task080_six_trial_balance_templates.py
backend/app/services/standard_trial_balance_import_service.py
backend/app/services/client_account_mapping_service.py
```

205201 基本信息：

```text
rows = 98455
headers = 选择 / 公司 / 科目代码 / 科目全称 / 币种 / 核算1 / 核算1名 / ...
preview_sec = 3.53
```

要求：

1. 修完会展后，必须单独跑 `run_one(205201)`。
2. 如果 analyze/execute 仍超时，继续优化：
   - 金额全空行不要进入推荐匹配。
   - 空科目代码行不要进入推荐匹配。
   - 同一 `科目代码 + 科目全称 + 核算维度` 组合要去重。
   - 标准科目查询、crosswalk 查询要缓存。
   - 辅助核算明细应继承父级科目，不要每个银行账号/客户都独立推荐。
3. 目标：

```text
205201 全链路 <= 120 秒
完整 6 文件验收 <= 180 秒
```

如果达不到，必须输出瓶颈阶段和行数，不允许无输出超时。

### Task D：验收标准保持严格

**文件：**

```text
backend/scripts/acceptance_task080_six_trial_balance_templates.py
```

最终脚本必须同时检查：

```text
standard_seed_added_code_count == 0
standard_seed_removed_code_count == 0
standard_seed_changed_count == 0
execute_status == executed
entry_count > 0
unmatched_count == 0
unsafe_count == 0
non_parent_warning_count == 0
tree_error is None
tree_total_nodes > 0
dup_node_id_count == 0
```

最终必须输出：

```text
TASK080_SIX_TRIAL_BALANCE_TEMPLATES_PASSED
```

## 必跑命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest tests/test_file_parser.py tests/test_standard_trial_balance_import.py tests/test_client_account_mapping_service.py tests/test_standard_trial_balance_view.py -q
D:\python\python.exe -m pytest -q
$env:PYTHONIOENCODING='utf-8'
D:\python\python.exe scripts\acceptance_task080_six_trial_balance_templates.py
```

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

## 给执行 AI 的提示词

你要修 TASK-082。先读：

```text
docs/tasks/TASK-080-six-new-trial-balance-template-acceptance.md
docs/tasks/TASK-081-fix-task080-acceptance-without-standard-account-additions.md
docs/tasks/TASK-082-fix-task080-tree-hang-and-complete-205201.md
```

红线：不要新增、删除或修改标准库科目。不要修改 `backend/app/data/standard_accounts_seed.py` 来跑通样本。

当前最新验收：

1. 标准库语义比对通过：新增 0、删除 0、修改 0。
2. 后端全量测试通过：`385 passed`。
3. 前端 build 通过。
4. 完整 TASK-080 验收脚本 15 分钟超时。
5. 会展中心 `preview/analyze/execute` 都正常，但 `get_tree` 卡死。
6. 205201 解析和 preview 快，但完整链路还未通过，修完会展后必须继续验。

你先修会展中心 `get_tree` 卡死，再跑完整 6 文件验收。交付时贴出 6 张表每张的：

```text
preview_total_rows / active_recommendations / unmatched_count / unsafe_count /
warning_count / non_parent_warning_count / error_count / execute_status /
entry_count / tree_error / tree_total_nodes / dup_node_id_count /
parse_sec / preview_sec / analyze_sec / execute_sec / tree_sec
```

没有看到 `TASK080_SIX_TRIAL_BALANCE_TEMPLATES_PASSED`，不能说完成。
