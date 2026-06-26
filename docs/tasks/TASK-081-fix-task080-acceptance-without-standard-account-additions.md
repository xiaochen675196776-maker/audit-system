# TASK-081：修复 TASK-080 验收剩余问题，禁止新增标准库科目

**Status:** TODO  
**Priority:** P0  
**Created:** 2026-06-25  
**Owner:** 待领取  

## 硬性约束

**除非用户明确发布命令，否则不允许新增、删除或修改标准库科目。**

禁止修改或通过修改以下文件来“跑通样本”：

```text
backend/app/data/standard_accounts_seed.py
```

允许的方向：

1. 解析能力：支持 `.xls`、多行表头、方向列、空金额。
2. 匹配算法：父级路径、旧编码 crosswalk、辅助核算继承、低质量候选降权。
3. 性能优化：大文件预过滤、去重、批处理、缓存。
4. 人工确认机制：确实无法自动判断的，应进入待确认，不得偷偷加标准科目。

当前验收中我已经做了语义比对：

```json
{
  "old_count": 207,
  "new_count": 207,
  "added_code_count": 0,
  "added_codes": [],
  "removed_code_count": 0,
  "removed_codes": [],
  "changed_count": 0
}
```

也就是说当前这轮没有语义新增标准科目，这一点是对的。后续修复必须保持这个结果。

## 本次验收结论

TASK-080 仍未通过。

已验证：

1. `.xls` 解析依赖已经补上，环境中 `xlrd=True`、`python_calamine=True`。
2. 6 个文件单独解析均可读，包括 `205201-2023.xls`。
3. 5 个非 `205201` 文件导入主体能执行成功。
4. 但仍有两个 P0 问题：
   - `会展中心余额表.xlsx` 执行后 `get_tree` 报 `maximum recursion depth exceeded`，验收脚本却没有判失败。
   - `205201-2023.xls` 全链路单独运行 10 分钟超时，完整 `acceptance_task080_six_trial_balance_templates.py` 也超时。

## 实测证据

### 标准库科目检查

命令：解析 `HEAD:backend/app/data/standard_accounts_seed.py` 与当前文件的 `SEED_ACCOUNTS`，按 `account_code` 和完整 dict 比对。

结果：

```text
old_count=207
new_count=207
added_code_count=0
removed_code_count=0
changed_count=0
```

验收要求：后续仍必须保持 `added_code_count=0`、`removed_code_count=0`、`changed_count=0`。

### 定向测试

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest tests/test_file_parser.py tests/test_standard_trial_balance_import.py tests/test_client_account_mapping_service.py tests/test_standard_trial_balance_view.py -q
```

结果：

```text
136 passed, 1 warning
```

### 单独解析 6 个文件

```text
会展中心余额表.xlsx: headers=8, data_start=1, rows=267, sec=0.38
1-12科目余额表.xls: headers=11, data_start=1, rows=1012, sec=0.04
205201-2023.xls: headers=29, data_start=1, rows=98460, sec=2.31
科目余额表2023年导入.xls: headers=11, data_start=1, rows=182, sec=0.02
医疗3月31日序时账及余额表.xlsx: headers=10, data_start=9, rows=163, sec=0.29
科目余额表-成都迪康-240930.xls: headers=9, data_start=5, rows=409, sec=0.02
```

### 5 个非 205201 文件导入结果

```json
[
  {
    "file": "会展中心余额表.xlsx",
    "preview_total_rows": 266,
    "active_recommendations": 188,
    "unmatched_count": 0,
    "unsafe_count": 0,
    "warning_count": 0,
    "non_parent_warning_count": 0,
    "error_count": 0,
    "execute_status": "executed",
    "entry_count": 188,
    "get_tree_error": "maximum recursion depth exceeded",
    "tree_total_nodes": 0
  },
  {
    "file": "1-12科目余额表.xls",
    "preview_total_rows": 1011,
    "active_recommendations": 926,
    "unmatched_count": 0,
    "unsafe_count": 0,
    "warning_count": 8,
    "non_parent_warning_count": 0,
    "execute_status": "executed",
    "entry_count": 926,
    "tree_total_nodes": 975
  },
  {
    "file": "科目余额表2023年导入.xls",
    "preview_total_rows": 181,
    "active_recommendations": 160,
    "unmatched_count": 0,
    "unsafe_count": 0,
    "warning_count": 0,
    "non_parent_warning_count": 0,
    "execute_status": "executed",
    "entry_count": 160,
    "tree_total_nodes": 290
  },
  {
    "file": "医疗3月31日序时账及余额表.xlsx",
    "preview_total_rows": 154,
    "active_recommendations": 87,
    "unmatched_count": 0,
    "unsafe_count": 0,
    "warning_count": 2,
    "non_parent_warning_count": 0,
    "execute_status": "executed",
    "entry_count": 87,
    "tree_total_nodes": 269
  },
  {
    "file": "科目余额表-成都迪康-240930.xls",
    "preview_total_rows": 404,
    "active_recommendations": 293,
    "unmatched_count": 0,
    "unsafe_count": 0,
    "warning_count": 0,
    "non_parent_warning_count": 0,
    "execute_status": "executed",
    "entry_count": 293,
    "tree_total_nodes": 491
  }
]
```

注意：会展中心虽然 `execute_status=executed`，但 `get_tree` 失败，因此不能算通过。

### 205201-2023.xls 单独情况

解析结果：

```json
{
  "headers": ["选择", "公司", "科目代码", "科目全称", "币种", "核算1", "核算1名", "核算2", "核算2名", "核算3", "核算3名", "核算4", "核算4名", "核算5", "核算5名", "期初余额", "借方发生数", "贷方发生数", "本期结余", "纳税人类型", "发票类型", "采集号", "业务员", "客户类型（A/B）", "客户类型", "客户性质", "v_PRINT", "V_acctfullname2", "大部门"],
  "data_start_row": 1,
  "data_rows": 98455
}
```

样例：

```json
[
  ["", "101", "1001", "库存现金", "RMB", "X01", "现金", "现金账本(01-1)", "现金账本(01-1)", "", "", "", "", "", "", "", "", "", ""],
  ["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "库存现金_现金_现金账本(01-1)", "库存现金", ""],
  ["", "101", "1002", "银行存款", "RMB", "Y020001", "深圳美的支付-备付金账户", "1002507573", "1002507573", "", "", "", "", "", "", "", "", "", ""]
]
```

`preview_standard_import` 单独跑得很快：

```json
{
  "stage": "preview",
  "total_rows": 98455,
  "sec": 2.53
}
```

但 `run_one(205201)` 单独运行 10 分钟超时，完整 `acceptance_task080_six_trial_balance_templates.py` 也超时。卡点在 `analyze/execute/get_tree` 的大数据处理阶段，不是文件解析。

## 必须修复

### Task A：验收脚本不能吞掉 get_tree 失败

**文件：**

```text
backend/scripts/acceptance_task080_six_trial_balance_templates.py
```

当前问题：

`run_one` 捕获 `get_tree` 异常后只打印：

```text
get_tree FAILED: maximum recursion depth exceeded
```

然后继续返回：

```json
{
  "tree_total_nodes": 0,
  "dup_node_id_count": 0
}
```

最终断言只检查 `dup_node_id_count == 0`，所以会错误放行。

修复要求：

1. 增加字段：

```python
tree_error = None
```

2. `get_tree` 异常时必须记录：

```python
tree_error = f"{type(e).__name__}: {e}"
```

3. summary 加入：

```python
"tree_error": tree_error
```

4. 最终断言必须检查：

```python
if s.get("tree_error"):
    print(f"[FAIL] {s['file']}: tree_error={s['tree_error']}")
    all_ok = False
if s["tree_total_nodes"] <= 0:
    print(f"[FAIL] {s['file']}: tree_total_nodes={s['tree_total_nodes']} (expected > 0)")
    all_ok = False
```

5. 不允许 `get_tree` 失败时输出 `TASK080_SIX_TRIAL_BALANCE_TEMPLATES_PASSED`。

### Task B：修复会展中心 get_tree 递归爆栈

**文件：**

```text
backend/app/services/standard_trial_balance_service.py
backend/app/services/standard_trial_balance_import_service.py
backend/app/services/trial_balance_transform.py
backend/tests/test_standard_trial_balance_view.py
```

当前问题：

`会展中心余额表.xlsx`：

```text
execute_status: executed
entry_count: 188
get_tree FAILED: maximum recursion depth exceeded
```

可能原因：

1. 数据查询树构建时产生 parent/child 环。
2. 同一 node_id 或 parent_key 递归引用自身。
3. 标准科目节点与客户明细节点合成时去重逻辑不正确。

修复要求：

1. 给 `get_tree` 的树构建函数增加环检测：

```python
visiting: set[str] = set()
visited: set[str] = set()
```

当发现节点再次进入 `visiting`，应：

```python
raise ValueError(f"tree cycle detected: {node_id}")
```

2. 修复实际数据产生环的根因，不能只靠吞异常。
3. 增加回归测试，构造一个自父级或循环父级样本，确认不会无限递归。
4. 用真实会展中心文件跑 `get_tree`，要求：

```text
tree_error is None
tree_total_nodes > 0
dup_node_id_count == 0
```

### Task C：205201-2023.xls 大文件 analyze 性能优化

**文件：**

```text
backend/app/services/standard_trial_balance_import_service.py
backend/app/services/client_account_mapping_service.py
backend/scripts/acceptance_task080_six_trial_balance_templates.py
backend/tests/test_standard_trial_balance_import.py
backend/tests/test_client_account_mapping_service.py
```

当前问题：

`205201-2023.xls` 有 98,455 数据行。preview 只需 2.53 秒，但 `run_one` 超过 10 分钟仍未完成。

必须优化点：

1. 在 `recommend_mappings` 前先做预过滤：
   - 全部金额字段为空/0 的行，不参与映射。
   - 空科目代码、空科目名称，仅用于展示或辅助信息的行，不参与映射。
   - 如果是 `V_acctfullname2` 展示行，不作为独立科目映射。
2. 对 `client_accounts_for_mapping` 按归一化键去重：

```python
key = (
    normalized_client_account_code,
    normalized_client_account_name,
    tuple(ancestor_codes),
    tuple(ancestor_names),
)
```

同一 key 只调用一次推荐，然后回填到所有同类行。

3. 对旧编码 crosswalk、标准科目代码查询加内存缓存，不要 98k 行反复查 DB。
4. 对辅助核算维度 `核算1/核算1名/...` 做继承：
   - 科目代码 `1002`、科目全称 `银行存款`，核算名是银行账户时，应继承 `1002 银行存款` 的映射。
   - 不应给每个银行账号单独做标准科目匹配。
5. 验收脚本应打印分阶段耗时：

```text
parse_sec
preview_sec
analyze_sec
execute_sec
tree_sec
```

6. 性能目标：

```text
205201-2023.xls 全链路 <= 120 秒
完整 6 文件验收 <= 180 秒
```

如果 120 秒目标做不到，必须至少在任务输出里说明瓶颈阶段和行数，不允许无输出卡 10 分钟。

### Task D：修复 205201 字段映射

**文件：**

```text
backend/scripts/acceptance_task080_six_trial_balance_templates.py
backend/app/services/column_matcher.py
backend/app/services/standard_trial_balance_import_service.py
```

205201 headers：

```text
col_2 科目代码
col_3 科目全称
col_15 期初余额
col_16 借方发生数
col_17 贷方发生数
col_18 本期结余
```

验收脚本动态映射必须明确生成：

```python
[
    {"column_id": "col_2", "field_name": "account_code"},
    {"column_id": "col_3", "field_name": "account_name"},
    {"column_id": "col_15", "field_name": "opening_amount", "period_type": "opening", "split_mode": "..."},
    {"column_id": "col_16", "field_name": "current_debit", "period_type": "current", "split_mode": "two_column", "debit_column_id": "col_16", "credit_column_id": "col_17"},
    {"column_id": "col_17", "field_name": "current_credit", "period_type": "current", "split_mode": "two_column", "debit_column_id": "col_16", "credit_column_id": "col_17"},
    {"column_id": "col_18", "field_name": "ending_amount", "period_type": "ending", "split_mode": "..."}
]
```

如果没有方向列，`期初余额/本期结余` 不能强行按标准方向导致大量 no_direction。应使用：

1. 标准方向可用时按标准方向拆。
2. 标准方向不可用但金额为 0/空时不报错。
3. 标准方向不可用且金额非 0 时进入人工确认，不得静默归类。

### Task E：禁止新增标准库科目的测试

**文件：**

```text
backend/scripts/acceptance_task080_six_trial_balance_templates.py
backend/tests/test_standard_account_import.py
```

验收脚本增加标准库保护检查：

```python
def assert_standard_seed_not_changed():
    # 读取 git HEAD 的 backend/app/data/standard_accounts_seed.py
    # 读取当前文件
    # ast 解析 SEED_ACCOUNTS
    # 比较 account_code 集合和每个 dict
```

要求：

```text
added_code_count == 0
removed_code_count == 0
changed_count == 0
```

如果不满足，脚本必须失败，并打印新增/删除/修改的科目代码。

注意：允许在 `client_account_mapping_service.py` 里维护旧编码 crosswalk，但 crosswalk 只能映射到已有标准科目，不能引用不存在的标准科目。

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

## 通过标准

必须全部满足：

1. 标准库语义比对：
   - `added_code_count == 0`
   - `removed_code_count == 0`
   - `changed_count == 0`
2. 6 个原始文件都直接读取，不需要手工转换。
3. 6 个文件都 `execute_status == executed`。
4. 6 个文件都 `entry_count > 0`。
5. 6 个文件都 `unmatched_count == 0`。
6. 6 个文件都 `unsafe_count == 0`。
7. 6 个文件都 `non_parent_warning_count == 0`。
8. 6 个文件都 `tree_error is None`。
9. 6 个文件都 `tree_total_nodes > 0`。
10. 6 个文件都 `dup_node_id_count == 0`。
11. `205201-2023.xls` 全链路不能超时。
12. 脚本输出：

```text
TASK080_SIX_TRIAL_BALANCE_TEMPLATES_PASSED
```

## 给执行 AI 的提示词

你要修 TASK-081。先读：

```text
docs/tasks/TASK-080-six-new-trial-balance-template-acceptance.md
docs/tasks/TASK-081-fix-task080-acceptance-without-standard-account-additions.md
```

红线：**不要新增、删除、修改标准库科目。不要改 `backend/app/data/standard_accounts_seed.py` 来跑通样本。**  
如果你认为缺标准科目，也不能直接加。你只能做算法、crosswalk、父级继承、人工确认或性能优化。crosswalk 必须映射到现有标准科目。

当前状态：

1. 定向测试 `136 passed`。
2. `SEED_ACCOUNTS` 语义比对无变化：新增 0、删除 0、修改 0。
3. 5 个非 `205201` 文件的 execute 能跑，但 `会展中心余额表.xlsx` 的 `get_tree` 爆栈，验收脚本目前错误放行。
4. `205201-2023.xls` 解析和 preview 很快，但全链路 `run_one` 10 分钟超时。preview 结果是 `98455` 行，2.53 秒。

你要完成：

1. 修验收脚本，不能吞掉 `get_tree` 异常，必须要求 `tree_total_nodes > 0`。
2. 修会展中心 `get_tree` 递归爆栈，找到环或父子引用错误根因。
3. 优化 `205201-2023.xls` 的 analyze/execute：预过滤、去重、缓存、辅助核算继承，目标全链路 120 秒内。
4. 明确 205201 字段映射，不要让动态映射误判。
5. 在验收脚本里加入标准库保护检查，确认没有新增/删除/修改标准科目。

完成后运行：

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest tests/test_file_parser.py tests/test_standard_trial_balance_import.py tests/test_client_account_mapping_service.py tests/test_standard_trial_balance_view.py -q
D:\python\python.exe -m pytest -q
$env:PYTHONIOENCODING='utf-8'
D:\python\python.exe scripts\acceptance_task080_six_trial_balance_templates.py
```

再运行：

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

交付时贴出：

```text
standard_seed_added_code_count / removed_code_count / changed_count
每张表 preview_total_rows / active_recommendations / unmatched_count /
unsafe_count / warning_count / non_parent_warning_count / error_count /
execute_status / entry_count / tree_error / tree_total_nodes /
dup_node_id_count / parse_sec / preview_sec / analyze_sec / execute_sec / tree_sec
```

没有看到 `TASK080_SIX_TRIAL_BALANCE_TEMPLATES_PASSED`，不能说完成。
