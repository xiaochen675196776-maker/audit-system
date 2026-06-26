# TASK-085：优化 TASK-080 六表验收性能并修复验收脚本目标未断言

**Status:** TODO  
**Priority:** P1  
**Created:** 2026-06-26  
**Owner:** 待领取  

## 背景

最新验收已经证明 TASK-084 的核心问题已修复：`205201-2023.xls` 不再被误判为无金额文件，真实金额列已经读出并完成入库。

命令：

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
$env:PYTHONIOENCODING='utf-8'
D:\python\python.exe scripts\acceptance_task080_six_trial_balance_templates.py
```

结果：

```text
TASK080_SIX_TRIAL_BALANCE_TEMPLATES_PASSED
```

但仍有两个验收质量问题：

1. 脚本打印 `[overall] 总耗时 379.04s (目标 <=180s)`，却没有把超过 180 秒作为失败。
2. `205201-2023.xls` 的 `execute_sec=265.03s`，单文件总耗时 `335.4s`，性能明显偏慢。
3. 脚本结束时出现 SQLAlchemy 警告：`SAWarning: fully NULL primary key identity cannot load any object. This condition may raise an error in a future release.`

## 硬性红线

除非用户明确发布命令，否则不允许新增、删除或修改标准库科目。

禁止用以下方式处理：

```text
1. 不允许修改 backend/app/data/standard_accounts_seed.py 的标准科目内容。
2. 不允许恢复 205201-2023.xls 的 entry_count=0 特殊放行。
3. 不允许增加 allow_zero_import 或类似跳过配置。
4. 不允许放宽 unmatched_count / unsafe_count / non_parent_warning_count / tree_error / dup_node_id_count 断言。
5. 不允许为了变快而减少真实入库行数。
```

## 当前最新验收事实

标准库真实比对通过：

```json
{
  "old_count": 207,
  "new_count": 207,
  "added_code_count": 0,
  "removed_code_count": 0,
  "changed_count": 0
}
```

205201 诊断脚本已确认金额列存在：

```text
col_15 期初余额：nonempty=27876, nonzero=23077
col_16 借方发生数：nonempty=27567, nonzero=26747
col_17 贷方发生数：nonempty=37718, nonzero=32234
col_18 本期结余：nonempty=48543, nonzero=21997
BIFF NUMBER 记录：141704 条
```

六表验收摘要：

```json
[
  {
    "file": "会展中心余额表.xlsx",
    "entry_count": 188,
    "tree_total_nodes": 305,
    "parse_sec": 0.03,
    "preview_sec": 0.02,
    "analyze_sec": 6.31,
    "execute_sec": 0.55,
    "tree_sec": 0.02
  },
  {
    "file": "1-12科目余额表.xls",
    "entry_count": 926,
    "tree_total_nodes": 1085,
    "parse_sec": 0.03,
    "preview_sec": 0.02,
    "analyze_sec": 15.4,
    "execute_sec": 2.7,
    "tree_sec": 0.07
  },
  {
    "file": "205201-2023.xls",
    "preview_total_rows": 98456,
    "active_recommendations": 18984,
    "ignored_zero_amount_rows": 56619,
    "ignored_summary_total_rows": 3888,
    "unmatched_count": 0,
    "unsafe_count": 0,
    "non_parent_warning_count": 0,
    "execute_status": "executed",
    "entry_count": 18984,
    "tree_error": null,
    "tree_total_nodes": 12872,
    "dup_node_id_count": 0,
    "parse_sec": 1.97,
    "preview_sec": 2.22,
    "analyze_sec": 55.49,
    "execute_sec": 265.03,
    "tree_sec": 10.12
  }
]
```

后端和前端验证：

```text
定向测试：207 passed
后端全量测试：388 passed
前端 npm run build：通过
```

## 必须修复

### Task A：把 180 秒目标变成真实断言

**文件：**

```text
backend/scripts/acceptance_task080_six_trial_balance_templates.py
```

当前脚本只打印：

```text
[overall] 总耗时 379.04s (目标 <=180s)
```

但仍输出：

```text
TASK080_SIX_TRIAL_BALANCE_TEMPLATES_PASSED
```

要求：

1. 增加常量：

```python
OVERALL_TARGET_SEC = 180
```

2. 在最终断言中加入：

```python
if overall_sec > OVERALL_TARGET_SEC:
    _print(f"[FAIL] overall_sec: {overall_sec}s > {OVERALL_TARGET_SEC}s")
    all_ok = False
```

3. 如果超过 180 秒，必须输出：

```text
TASK080_SIX_TRIAL_BALANCE_TEMPLATES_FAILED
```

4. 保留单文件超时保护，但不要用 600 秒掩盖总体目标：

```python
SINGLE_FILE_TIMEOUT = 600
OVERALL_TARGET_SEC = 180
```

### Task B：定位 `205201` execute 慢的具体阶段

**文件：**

```text
backend/app/services/standard_trial_balance_import_service.py
backend/scripts/acceptance_task080_six_trial_balance_templates.py
```

当前 `205201` 慢点：

```text
analyze_sec = 55.49
execute_sec = 265.03
tree_sec = 10.12
```

要求在 `execute_standard_import` 内部增加临时或正式阶段计时，至少拆出：

```text
load_rows_sec
build_hierarchy_sec
transform_amounts_sec
confirmed_mapping_lookup_sec
raw_row_insert_sec
entry_insert_sec
mapping_experience_save_sec
flush_commit_sec
```

输出方式可以通过 logger 或返回 debug 字段，但验收脚本必须能打印出来。

目标是找出 `execute_sec=265s` 的主因，不允许盲改。

### Task C：优化大文件入库性能

**文件：**

```text
backend/app/services/standard_trial_balance_import_service.py
backend/app/services/client_account_mapping_service.py
backend/tests/test_standard_trial_balance_import.py
```

优先检查并优化：

1. 是否逐行 `await db.flush()`。
2. 是否逐行查询标准科目或 mapping experience。
3. 是否逐行保存 mapping experience。
4. 是否对 18,984 条 entry 和 raw_row 使用 ORM 单条插入导致慢。
5. 是否重复解析 98,456 行大文件。

建议方向：

```text
1. 标准科目、confirmed_mappings、row_index 映射一次性建 dict。
2. raw_row / entry 尽量批量 add_all 后一次 flush。
3. mapping experience 按 (client_code, client_name, standard_account_id, customer_label) 去重后批量 upsert/更新。
4. 不重复执行 parse_trial_balance_import；复用 batch.hierarchy_config.parse_config。
5. 对跳过行、汇总行、零金额行先建 set，后续 O(1) 判断。
```

验收目标：

```text
205201 execute_sec <= 120s
205201 file_total <= 180s
六表 overall_sec <= 180s
```

如果本机性能无法稳定达到 180 秒，必须至少：

```text
1. 把 execute_sec 从 265s 降到 <=120s；
2. 在任务结论里贴出瓶颈阶段；
3. 说明剩余瓶颈是否来自 tree/query/SQLite/ORM。
```

### Task D：修复 SQLAlchemy `fully NULL primary key identity` 警告

**文件：**

```text
backend/app/services/standard_trial_balance_import_service.py
backend/app/services/standard_trial_balance_service.py
backend/tests/test_standard_trial_balance_import.py
```

当前验收结束后出现：

```text
SAWarning: fully NULL primary key identity cannot load any object.
```

要求：

1. 找到触发 `db.get(Model, None)` 或等价空主键查询的位置。
2. 在查询前加显式判断：

```python
if some_id is None:
    ...
```

3. 增加测试，保证空 raw_row_id / parent_raw_row_id / standard_account_id 不触发该警告。

## 必跑命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest tests/test_file_parser.py tests/test_standard_trial_balance_import.py tests/test_client_account_mapping_service.py tests/test_standard_trial_balance_view.py tests/test_trial_balance_transform.py -q
D:\python\python.exe -m pytest -q
$env:PYTHONIOENCODING='utf-8'
D:\python\python.exe scripts\diagnose_205201_trial_balance.py
D:\python\python.exe scripts\acceptance_task080_six_trial_balance_templates.py
```

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

## 完成标准

必须同时满足：

```text
标准库真实比对 old=207 new=207 added=0 removed=0 changed=0
205201 active_recommendations > 0
205201 execute_status == executed
205201 entry_count > 0
六张表 unmatched_count == 0
六张表 unsafe_count == 0
六张表 non_parent_warning_count == 0
六张表 tree_error is None
六张表 dup_node_id_count == 0
六表 overall_sec <= 180s，或者如果暂时达不到，脚本必须按失败处理并清楚输出瓶颈
不再出现 SAWarning: fully NULL primary key identity
后端全量测试通过
前端 build 通过
```

## 给执行 AI 的提示词

你领取 `docs/tasks/TASK-085-optimize-task080-acceptance-performance.md`。

当前功能已经跑通：`205201-2023.xls` 可以读出金额并入库，六表脚本输出 `TASK080_SIX_TRIAL_BALANCE_TEMPLATES_PASSED`。但是严格验收还有性能问题：总耗时 379 秒，超过目标 180 秒，而脚本没有把这个目标作为失败断言。

红线：

```text
不要新增、删除或修改标准库科目。
不要恢复 205201 entry_count=0 放行。
不要放宽 unmatched/unsafe/warning/tree 断言。
不要为了变快减少真实入库行数。
```

你先给 `execute_standard_import` 增加阶段计时，定位 `205201 execute_sec=265s` 的主因，再做批量入库/缓存/去重优化。最后跑完整命令，贴出优化前后：

```text
205201 analyze_sec
205201 execute_sec
205201 tree_sec
205201 file_total
overall_sec
```

如果仍超过 180 秒，脚本必须失败并明确瓶颈，不能继续输出通过。
