# TASK-083：修复 TASK-080/082 验收脚本假通过问题

**Status:** DONE  
**Priority:** P0  
**Created:** 2026-06-25  
**Owner:** xiaochen  
**Completed:** 2026-06-25  

## 背景

本次重新验收后，`backend/scripts/acceptance_task080_six_trial_balance_templates.py` 已经可以在约 108 秒内跑完 6 个真实文件，并输出：

```text
TASK080_SIX_TRIAL_BALANCE_TEMPLATES_PASSED
```

但这个通过结论不能直接接受，因为验收脚本存在放行漏洞：

1. 脚本内部标准库检查没有真正比对 git HEAD，输出了 `git_unavailable` 后仍然按通过处理。
2. `205201-2023.xls` 的 `entry_count=0` 被特殊放行。
3. 脚本头部写着“每张表 entry_count>0”，但实际断言写成了 `entry_count > 0 or fn == "205201-2023.xls"`。
4. TASK-082 要求的单文件/单阶段超时保护仍未实现，当前 `get_tree` 已快，但脚本仍可能在未来样本上无输出卡死。
5. TASK-082 要求的自引用、互相引用、重复 node_id 测试没有明确覆盖。

## 硬性红线

除非用户明确发布命令，否则不允许新增、删除或修改标准库科目。

禁止通过修改以下文件的科目内容来跑通验收：

```text
backend/app/data/standard_accounts_seed.py
```

本次独立语义比对结果是通过的，必须保持：

```json
{
  "old_count": 207,
  "new_count": 207,
  "added_code_count": 0,
  "removed_code_count": 0,
  "changed_count": 0
}
```

允许修改算法、解析器、验收脚本、测试和状态语义；不允许改标准库科目本身。

## 本次验收事实

### 已通过的命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest tests/test_file_parser.py tests/test_standard_trial_balance_import.py tests/test_client_account_mapping_service.py tests/test_standard_trial_balance_view.py -q
```

结果：

```text
136 passed, 1 warning
```

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest -q
```

结果：

```text
385 passed, 3 warnings
```

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

结果：构建成功，仅有 Vite chunk size warning 和 Rollup 注释 warning。

### 6 文件脚本当前输出

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
$env:PYTHONIOENCODING='utf-8'
D:\python\python.exe scripts\acceptance_task080_six_trial_balance_templates.py
```

结果：exit code 0，约 108 秒，输出 `TASK080_SIX_TRIAL_BALANCE_TEMPLATES_PASSED`。

其中关键摘要：

```json
[
  {
    "file": "会展中心余额表.xlsx",
    "active_recommendations": 188,
    "entry_count": 188,
    "tree_error": null,
    "tree_total_nodes": 305,
    "dup_node_id_count": 0,
    "tree_sec": 0.03
  },
  {
    "file": "1-12科目余额表.xls",
    "active_recommendations": 926,
    "entry_count": 926,
    "tree_error": null,
    "tree_total_nodes": 975,
    "dup_node_id_count": 0,
    "tree_sec": 0.06
  },
  {
    "file": "205201-2023.xls",
    "preview_total_rows": 98455,
    "active_recommendations": 0,
    "ignored_zero_amount_rows": 98455,
    "entry_count": 0,
    "tree_error": null,
    "tree_total_nodes": 207,
    "dup_node_id_count": 0
  },
  {
    "file": "科目余额表2023年导入.xls",
    "active_recommendations": 160,
    "entry_count": 160,
    "tree_error": null,
    "tree_total_nodes": 290,
    "dup_node_id_count": 0
  },
  {
    "file": "医疗3月31日序时账及余额表.xlsx",
    "active_recommendations": 87,
    "entry_count": 87,
    "tree_error": null,
    "tree_total_nodes": 270,
    "dup_node_id_count": 0
  },
  {
    "file": "科目余额表-成都迪康-240930.xls",
    "active_recommendations": 293,
    "entry_count": 293,
    "tree_error": null,
    "tree_total_nodes": 491,
    "dup_node_id_count": 0
  }
]
```

### 205201 原始数据抽查

用 `parse_trial_balance_import` 读取：

```text
headers[15:19] = 期初余额 / 借方发生数 / 贷方发生数 / 本期结余
row_count = 98455
```

统计结果：

```json
{
  "col_15_期初余额_nonempty": 0,
  "col_16_借方发生数_nonempty": 0,
  "col_17_贷方发生数_nonempty": 0,
  "col_18_本期结余_nonempty": 0
}
```

也就是说，当前解析结果下 `205201-2023.xls` 没有任何可导入金额。它可以被识别为“无金额数据文件”，但不能在没有明确业务说明的情况下冒充“完整导入成功”。

## 必须修复

### Task A：修复标准库检查的假通过

**文件：**

```text
backend/scripts/acceptance_task080_six_trial_balance_templates.py
```

当前代码：

```python
subprocess.run(
    ["git", "show", f"HEAD:app/data/standard_accounts_seed.py"],
    cwd=str(Path(__file__).parent.parent),
)
```

问题：

脚本要求从 `backend` 目录运行，此时 git 仓库根目录仍是上级目录，但 `HEAD:app/data/...` 在仓库根不存在，所以读取失败。脚本随后返回：

```python
{"added_code_count": 0, "removed_code_count": 0, "changed_count": 0, "note": "git_unavailable"}
```

这是假通过。

**修改要求：**

1. 明确计算仓库根目录：

```python
script_path = Path(__file__).resolve()
backend_root = script_path.parents[1]
repo_root = backend_root.parent
```

2. `git show` 必须使用仓库根路径：

```python
result = subprocess.run(
    ["git", "-C", str(repo_root), "show", "HEAD:backend/app/data/standard_accounts_seed.py"],
    capture_output=True,
    text=True,
    encoding="utf-8",
    timeout=10,
)
```

3. 如果读取失败，必须失败，不允许返回 0 变更：

```python
if result.returncode != 0:
    raise AssertionError(f"无法读取 git HEAD 标准库: {result.stderr}")
```

4. 最终脚本输出必须出现真实比对：

```text
[SEED-CHECK] old=207 new=207 added=0 removed=0 changed=0
```

5. 不允许再出现：

```text
git_unavailable
```

### Task B：修复 205201 的 `entry_count=0` 假通过

**文件：**

```text
backend/scripts/acceptance_task080_six_trial_balance_templates.py
backend/app/services/standard_trial_balance_import_service.py
backend/tests/test_standard_trial_balance_import.py
```

当前代码：

```python
("entry_count", s["entry_count"] > 0 or fn == "205201-2023.xls", f"entry_count={s['entry_count']}")
```

必须删除这个特殊放行。

**必须先做判断：**

1. 如果 `205201-2023.xls` 实际有金额，只是解析/字段映射错了：
   - 修复解析器或字段映射；
   - 要求 `active_recommendations > 0`；
   - 要求 `entry_count > 0`。

2. 如果 `205201-2023.xls` 确认是一张无金额数据文件：
   - 脚本不能输出 `TASK080_SIX_TRIAL_BALANCE_TEMPLATES_PASSED`；
   - 应输出明确失败原因：

```text
[FAIL] 205201-2023.xls: no importable amount rows, entry_count=0
```

3. 只有用户明确允许“无金额文件按跳过通过”后，才可以新增显式配置：

```python
"allow_zero_import": True
```

但当前用户没有发布这个命令，所以本任务不允许增加该例外。

**服务层状态要求：**

当前 `execute_standard_import` 在没有 `confirmed_mappings` 时返回：

```python
{"status": "executed", "entry_count": 0}
```

这会误导调用方。需要改成更明确的状态之一：

```python
{"status": "skipped", "reason": "no_confirmed_mappings", "entry_count": 0}
```

或：

```python
{"status": "blocked", "reason": "no_confirmed_mappings", "entry_count": 0}
```

建议用 `skipped`，但验收脚本必须把 `skipped` 视为未完成导入，除非文件配置明确允许跳过。

**新增测试：**

在 `backend/tests/test_standard_trial_balance_import.py` 加一个测试：

```python
async def test_execute_without_confirmed_mappings_is_not_executed_success(db):
    result = await execute_standard_import(
        db=db,
        batch_id=batch.id,
        file_path=file_path,
        confirmed_mappings=[],
        warnings_confirmed=True,
    )
    assert result["status"] in {"skipped", "blocked"}
    assert result["entry_count"] == 0
```

测试中按现有测试模式创建 batch 和临时 CSV/XLSX，不要依赖真实文件路径。

### Task C：增加验收脚本超时保护

**文件：**

```text
backend/scripts/acceptance_task080_six_trial_balance_templates.py
```

当前 `run_acceptance()` 直接：

```python
summary = await run_one(fdef, db)
```

必须改成带单文件超时：

```python
try:
    summary = await asyncio.wait_for(run_one(fdef, db), timeout=120)
except asyncio.TimeoutError:
    summary = {
        "file": Path(fdef["path"]).name,
        "execute_status": "timeout",
        "entry_count": 0,
        "tree_error": "TimeoutError: file exceeded 120s",
        ...
    }
```

要求：

1. 每张表开始前 `print(..., flush=True)`。
2. parse/preview/analyze/execute/tree 每阶段结束都 `flush=True` 输出耗时。
3. 超时时必须输出文件名和阶段，不允许只显示外部 `command timed out`。
4. 完整脚本目标仍是 180 秒内完成。

### Task D：补齐 `get_tree` 环路与重复节点测试

**文件：**

```text
backend/tests/test_standard_trial_balance_view.py
backend/app/services/standard_trial_balance_service.py
```

当前会展中心 `get_tree` 已经从卡死修到 `tree_sec=0.03s`，这是进展。但 TASK-082 明确要求覆盖：

```text
自引用 parent_id
两节点互相引用
重复 node_id
会展中心真实数据导入后 get_tree 不超时
```

目前测试文件没有明确 `cycle/self/mutual` 用例。必须新增测试。

建议测试 1：自引用 raw parent 不递归爆栈

```python
async def test_get_tree_breaks_self_referencing_client_group(db):
    # 创建标准科目、batch、raw_row、entry
    # raw_row.parent_raw_row_id = raw_row.id
    # 调 get_tree(db, batch_id=batch.id)
    # 断言不报错、total > 0、node_id 不重复
```

建议测试 2：两个 raw row 互相引用不递归爆栈

```python
async def test_get_tree_breaks_mutual_client_group_cycle(db):
    # raw_a.parent_raw_row_id = raw_b.id
    # raw_b.parent_raw_row_id = raw_a.id
    # 至少一个 entry 指向 raw_a
    # 调 get_tree 后必须返回，不能 RecursionError
```

建议测试 3：重复 client_group node_id 不应重复出现在同一树中

```python
async def test_get_tree_has_no_duplicate_node_ids_for_shared_synthetic_group(db):
    nodes, _ = await get_tree(db, batch_id=batch.id)
    all_ids = []
    collect recursively
    assert len(all_ids) == len(set(all_ids))
```

注意：如果手工构造数据库违反外键或 ORM 约束，按现有 test helper 模式建对象并 `await db.flush()`。

## 最终验收标准

必须同时满足：

```text
标准库真实比对：old=207 new=207 added=0 removed=0 changed=0
不出现 git_unavailable
不修改 standard_accounts_seed.py 的语义内容
205201-2023.xls 不允许 entry_count=0 时输出 TASK080...PASSED
每个未显式允许跳过的文件 entry_count > 0
每个导入文件 unmatched_count == 0
每个导入文件 unsafe_count == 0
每个导入文件 non_parent_warning_count == 0
每个导入文件 tree_error is None
每个导入文件 tree_total_nodes > 0
每个导入文件 dup_node_id_count == 0
完整脚本有单文件 120 秒超时保护
```

必跑命令：

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

你领取 `docs/tasks/TASK-083-fix-task080-false-positive-acceptance.md`。

当前状态不是完全失败：会展中心 `get_tree` 卡死已经修好，6 文件脚本能在约 108 秒跑完。但现在验收脚本存在假通过：

1. 标准库检查读取 git HEAD 失败后返回 `git_unavailable`，仍然放行。
2. `205201-2023.xls` 的 `entry_count=0` 被硬编码特殊放行。
3. `execute_standard_import` 在没有 confirmed mappings 时返回 `status=executed, entry_count=0`，语义误导。
4. 单文件 `asyncio.wait_for(..., timeout=120)` 未实现。
5. `get_tree` 环路测试没有补齐。

红线：不要新增、删除或修改标准库科目。不要修改 `backend/app/data/standard_accounts_seed.py` 来跑通样本。

你要做的是修验收口径和剩余边界，不是放宽标准。最终没有真实输出：

```text
[SEED-CHECK] old=207 new=207 added=0 removed=0 changed=0
```

不能算通过。`205201-2023.xls` 如果仍然 `entry_count=0`，不能输出：

```text
TASK080_SIX_TRIAL_BALANCE_TEMPLATES_PASSED
```

除非用户之后明确批准“无金额文件允许跳过通过”。
