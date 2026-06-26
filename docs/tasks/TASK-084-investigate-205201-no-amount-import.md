# TASK-084：定位并处理 205201-2023.xls 无金额导入导致真实验收失败

**Status:** TODO  
**Priority:** P0  
**Created:** 2026-06-25  
**Owner:** 待领取  

## 背景

TASK-083 修复后，验收脚本不再假通过：

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
$env:PYTHONIOENCODING='utf-8'
D:\python\python.exe scripts\acceptance_task080_six_trial_balance_templates.py
```

当前结果是 **正确失败**：

```text
TASK080_SIX_TRIAL_BALANCE_TEMPLATES_FAILED
```

失败原因只剩一项：

```text
[FAIL] 205201-2023.xls: execute_status (status=skipped)
[FAIL] 205201-2023.xls: entry_count (entry_count=0)
```

其他 5 张真实表已经通过：

```text
会展中心余额表.xlsx：executed，entry_count=188，tree_nodes=305
1-12科目余额表.xls：executed，entry_count=926，tree_nodes=975
科目余额表2023年导入.xls：executed，entry_count=160，tree_nodes=290
医疗3月31日序时账及余额表.xlsx：executed，entry_count=87，tree_nodes=270
科目余额表-成都迪康-240930.xls：executed，entry_count=293，tree_nodes=491
```

## 硬性红线

除非用户明确发布命令，否则不允许新增、删除或修改标准库科目。

禁止用以下方式“修复”：

```text
1. 不允许修改 backend/app/data/standard_accounts_seed.py 的标准科目内容。
2. 不允许恢复 205201-2023.xls 的 entry_count=0 特殊放行。
3. 不允许增加 allow_zero_import 或类似跳过配置，除非用户明确允许无金额文件跳过通过。
4. 不允许让 execute_standard_import 在没有 confirmed_mappings 时返回 executed。
```

## 当前验收事实

### 标准库检查已经通过

独立语义比对结果：

```json
{
  "old_count": 207,
  "new_count": 207,
  "added_code_count": 0,
  "removed_code_count": 0,
  "changed_count": 0
}
```

验收脚本输出：

```text
[SEED-CHECK] old=207 new=207 added=0 removed=0 changed=0
```

### 205201 当前解析结果

文件：

```text
D:/APP/谷歌/文件下载/205201-2023.xls
```

验收脚本当前摘要：

```json
{
  "file": "205201-2023.xls",
  "preview_total_rows": 98455,
  "data_start_row": 1,
  "active_recommendations": 0,
  "ignored_zero_amount_rows": 98455,
  "ignored_summary_total_rows": 84,
  "unmatched_count": 0,
  "unsafe_count": 0,
  "warning_count": 0,
  "non_parent_warning_count": 0,
  "error_count": 0,
  "execute_status": "skipped",
  "entry_count": 0,
  "tree_error": null,
  "tree_total_nodes": 207,
  "dup_node_id_count": 0,
  "parse_sec": 2.04,
  "preview_sec": 2.45,
  "analyze_sec": 49.22,
  "execute_sec": 0.0,
  "tree_sec": 0.01
}
```

已知表头：

```text
选择 / 公司 / 科目代码 / 科目全称 / 币种 / 核算1 / 核算1名 / 核算2 / 核算2名 / 核算3 / 核算3名 / 核算4 / 核算4名 / 核算5 / 核算5名 / 期初余额 / 借方发生数 / 贷方发生数 / 本期结余 / ...
```

当前解析后，验收映射使用：

```python
[
    {"column_id": "col_2", "field_name": "account_code"},
    {"column_id": "col_3", "field_name": "account_name"},
    {"column_id": "col_15", "field_name": "opening_amount", "period_type": "opening", "split_mode": "single_as_debit"},
    {"column_id": "col_16", "field_name": "current_debit", "period_type": "current", "split_mode": "two_column", "debit_column_id": "col_16", "credit_column_id": "col_17"},
    {"column_id": "col_17", "field_name": "current_credit", "period_type": "current", "split_mode": "two_column", "debit_column_id": "col_16", "credit_column_id": "col_17"},
    {"column_id": "col_18", "field_name": "ending_amount", "period_type": "ending", "split_mode": "single_as_debit"},
]
```

但当前抽查显示：

```text
col_15 期初余额：98455 行全部为空
col_16 借方发生数：98455 行全部为空
col_17 贷方发生数：98455 行全部为空
col_18 本期结余：98455 行全部为空
```

因此所有行都被识别成零金额行，`active_recommendations=0`，最终 `execute_status=skipped`。

## 目标

判断 `205201-2023.xls` 到底是：

```text
A. 文件本身就是无金额明细/辅助核算清单，不应该作为科目余额表验收样本；
B. 文件里有金额，但当前 .xls 解析器没有读出来；
C. 文件里有金额，但字段映射列选错了；
D. 文件格式特殊，金额在隐藏字段、后续 sheet、二进制记录或其他区域，需要增强解析。
```

处理原则：

```text
如果是 A：保持验收失败，并在任务结论中说明样本不满足科目余额表导入条件，请用户更换样本或明确允许跳过。
如果是 B/C/D：修复解析器或验收字段映射，使 205201 能产生 entry_count > 0。
```

## 任务拆解

### Task A：写一个 205201 诊断脚本，输出所有列的非空/非零统计

**文件：**

```text
backend/scripts/diagnose_205201_trial_balance.py
```

**要求：**

脚本必须只读真实文件，不写数据库：

```python
from app.services.file_parser import parse_trial_balance_import, slice_data_rows
```

输出内容必须包含：

```text
1. 文件路径
2. data_start_row
3. headers 全量列表
4. row_count
5. 每一列：index / header / nonempty_count / numeric_nonzero_count / first_5_nonempty_examples
6. 对 col_15-col_18 单独打印样本
7. 如果有多 sheet，输出每个 sheet 的名称、行数、列数、疑似金额列
```

如果 `openpyxl` 不支持 `.xls`，必须用 `xlrd` 或现有自定义解析分支，不允许静默失败。

运行命令：

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
$env:PYTHONIOENCODING='utf-8'
D:\python\python.exe scripts\diagnose_205201_trial_balance.py
```

预期输出要能回答：

```text
205201 是否有任意金额列？
金额是否在 col_15-col_18 之外？
金额是否在其他 sheet？
```

### Task B：如果金额列存在，修复字段映射或解析器

**文件：**

```text
backend/scripts/acceptance_task080_six_trial_balance_templates.py
backend/app/services/file_parser.py
backend/tests/test_file_parser.py
```

执行逻辑：

1. 如果诊断脚本发现金额在其他列：
   - 修改 `REAL_FILES` 中 `205201-2023.xls` 的字段映射；
   - 不改业务逻辑。

2. 如果诊断脚本发现 `xlrd` 没读出金额，但二进制里有金额：
   - 修复 `_parse_xls_custom_binary()`；
   - 增加一个最小单元测试，使用小型二进制 fixture 或 monkeypatch，验证数值字段能被解析。

3. 如果金额在其他 sheet：
   - 修复解析器支持选择有效 sheet；
   - 选择逻辑应优先含“科目代码/科目全称/期初余额/借方发生数/贷方发生数/本期结余”的 sheet；
   - 增加测试覆盖多 sheet 选择。

修复后，`205201-2023.xls` 必须满足：

```text
active_recommendations > 0
execute_status == executed
entry_count > 0
tree_error is None
dup_node_id_count == 0
```

### Task C：如果文件确认没有金额，保持失败并输出清晰原因

**文件：**

```text
backend/scripts/acceptance_task080_six_trial_balance_templates.py
docs/tasks/TASK-084-investigate-205201-no-amount-import.md
```

如果诊断结论是文件无金额，必须：

1. 不修改验收脚本放行逻辑。
2. 继续让脚本失败。
3. 把失败原因写清楚，例如：

```text
[FAIL] 205201-2023.xls: no importable amount rows; all mapped amount columns are empty
```

4. 在任务文件中补充诊断结论：

```text
205201-2023.xls 不是可导入科目余额表，属于无金额辅助核算清单/不完整导出。
需要用户提供带金额列的原始科目余额表，或明确批准无金额文件跳过通过。
```

### Task D：跑完整验收

必须运行：

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

最终只能有两种结论：

```text
结论 1：205201 修复后 entry_count > 0，六张表全部通过，输出 TASK080_SIX_TRIAL_BALANCE_TEMPLATES_PASSED。
结论 2：205201 文件无金额，保持失败，并明确要求用户更换样本或授权跳过无金额文件。
```

## 给执行 AI 的提示词

你领取 `docs/tasks/TASK-084-investigate-205201-no-amount-import.md`。

当前系统测试都通过，但真实六表验收仍失败，唯一阻塞是：

```text
205201-2023.xls: execute_status=skipped, entry_count=0
```

注意红线：

```text
不要新增、删除或修改标准库科目。
不要把 205201 的 entry_count=0 重新特殊放行。
不要让 execute_standard_import 在没有 confirmed_mappings 时返回 executed。
不要加 allow_zero_import，除非用户明确批准。
```

你的第一步不是改代码，而是写并运行诊断脚本：

```text
backend/scripts/diagnose_205201_trial_balance.py
```

输出每列非空/非零统计，确认金额是否真的不存在。如果金额在其他列或其他 sheet，再修字段映射/解析器；如果文件真的没有金额，就保持验收失败并写清楚样本不合格。

最终交付必须贴出：

```text
205201 每列非空/非零统计摘要
判断 A/B/C/D 哪一种
如果修复：entry_count、active_recommendations、tree_total_nodes
如果不修复：为什么该文件不是可导入科目余额表
```
