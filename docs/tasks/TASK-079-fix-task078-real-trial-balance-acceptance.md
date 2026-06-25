# TASK-079：修复 TASK-078 真实科目余额表验收失败

**Status:** TODO  
**Priority:** P0  
**Created:** 2026-06-25  
**Owner:** 待领取  

## 背景

TASK-078 已经有人实现了一轮，但本次验收没有通过。

验收目标仍然是：三张真实科目余额表都能通过标准化科目余额表导入链路，使用临时 SQLite DB，不能污染正式数据库，最终脚本必须输出：

```text
TASK078_THREE_REAL_TRIAL_BALANCES_PASSED
```

三张真实文件：

```text
D:/NAS/xiaochen/李辉辉项目组/SynologyDrive/道恩钛业2025年年审-2025.12.31/1、中普账套/科目汇总表查询结果-道恩钛业20251231.xlsx
D:/NAS/xiaochen/项目汇总文件夹/SynologyDrive/海钦股份2025年报审计/1、企业提供的资料/1、财务账套、账表资料/2025年序时账及科目余额表/广西海钦发生额及余额表.xlsx
D:/NAS/xiaochen/项目汇总文件夹/SynologyDrive/海钦股份2025年报审计/1、企业提供的资料/1、财务账套、账表资料/2025年序时账及科目余额表/金碟软件公司科目余额表.xlsx
```

## 本次验收命令与结果

### 1. 定向测试通过

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest tests/test_file_parser.py tests/test_standard_trial_balance_import.py tests/test_client_account_mapping_service.py tests/test_standard_trial_balance_view.py -q
```

结果：

```text
136 passed, 1 warning
```

### 2. 全量后端测试通过

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest -q
```

结果：

```text
385 passed, 3 warnings
```

### 3. 前端构建通过

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

结果：构建成功，但有 Vite chunk size warning，不影响本任务验收。

### 4. TASK-078 真实表验收脚本失败

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
$env:PYTHONIOENCODING='utf-8'
D:\python\python.exe scripts\acceptance_task078_three_real_trial_balances.py
```

当前直接失败：

```text
File "backend/scripts/acceptance_task078_three_real_trial_balances.py", line 213
    assert execute := None  # placeholder; we'll execute right below
                   ^^
SyntaxError: invalid syntax
```

必须删除这行占位代码。验收脚本不能有语法错误。

## 绕过语法错误后的真实结果

为了继续确认业务链路，我临时在内存里去掉第 213 行后运行验收逻辑。

### 1. 道恩钛业：已经基本跑通

```json
{
  "file": "科目汇总表查询结果-道恩钛业20251231.xlsx",
  "preview_total_rows": 345,
  "data_start_row": 1,
  "active_recommendations": 294,
  "inherited_auxiliary_rows": 0,
  "ignored_header_rows": [0],
  "unmatched_count": 0,
  "unsafe_count": 0,
  "warning_count": 0,
  "error_count": 0,
  "execute_status": "executed",
  "entry_count": 294,
  "tree_total_nodes": 396,
  "ignored_zero_amount_rows": 1
}
```

道恩这张可以作为正向回归样本，修广西和金碟时不能让它退化。

### 2. 广西海钦：仍未跑通

绕过语法错误后，广西执行失败：

```text
ValueError: 存在 4 个末级客户科目未映射到启用标准科目:
行 166「(资产)小计： ?」;
行 241「(负债)小计： ?」;
行 249「(权益)小计： ?」;
行 310「(损益)小计： ?」
```

只读诊断结果：

```json
{
  "file": "广西海钦发生额及余额表.xlsx",
  "preview_total_rows": 314,
  "data_start_row": 9,
  "active_recommendations": 274,
  "inherited_auxiliary_rows": 149,
  "ignored_header_rows": [6, 7, 8],
  "unmatched_count": 4,
  "unsafe_count": 19,
  "warning_count": 23,
  "non_parent_warning_count": 19,
  "error_count": 4
}
```

未匹配样本：

```json
[
  {"row_index": 166, "code": "(资产)小计：", "name": null},
  {"row_index": 241, "code": "(负债)小计：", "name": null},
  {"row_index": 249, "code": "(权益)小计：", "name": null},
  {"row_index": 310, "code": "(损益)小计：", "name": null}
]
```

unsafe 样本：

```json
[
  {
    "row_index": 9,
    "code": "1122001",
    "name": "业务款项",
    "picked": "112201 应收账款",
    "score": 0.86,
    "source": "code_category_anchor"
  },
  {
    "row_index": 125,
    "code": "1221001",
    "name": "个人",
    "picked": "122101 其他应收款",
    "score": 0.86,
    "source": "code_category_anchor"
  },
  {
    "row_index": 139,
    "code": "1601003",
    "name": "电子设备",
    "picked": "160101 固定资产原值",
    "score": 0.86,
    "source": "code_category_anchor"
  }
]
```

必须修：

1. `(资产)小计：`、`(负债)小计：`、`(权益)小计：`、`(损益)小计：` 这类小计行必须自动识别并跳过，不能参与科目匹配和入账。
2. `1122001 业务款项 -> 112201 应收账款`、`1221001/1221002 -> 122101 其他应收款`、`1601003/1601004001/... -> 160101 固定资产原值` 这类客户明细科目，当前还有 warning/unsafe。若有代码前缀、父级、名称类别三重证据，应提升为安全候选。
3. 广西已识别 `inherited_auxiliary_rows = 149`，说明辅助明细继承逻辑有进展，不能回退。

### 3. 金碟软件公司：仍未跑通

只读诊断结果：

```json
{
  "file": "金碟软件公司科目余额表.xlsx",
  "preview_total_rows": 12288,
  "data_start_row": 2,
  "active_recommendations": 131,
  "inherited_auxiliary_rows": 0,
  "ignored_header_rows": [0, 1],
  "unmatched_count": 4,
  "unsafe_count": 20,
  "warning_count": 37,
  "non_parent_warning_count": 17,
  "error_count": 4
}
```

未匹配样本：

```json
[
  {"row_index": 3823, "code": "1705.001", "name": "充电场站"},
  {"row_index": 3863, "code": "1705.002", "name": "办公租赁"},
  {"row_index": 3906, "code": "1706.001", "name": "充电场站"},
  {"row_index": 12262, "code": null, "name": "合计"}
]
```

unsafe 样本：

```json
[
  {
    "row_index": 515,
    "code": "1122.001",
    "name": "业务款项",
    "picked": "112201 应收账款",
    "score": 0.86,
    "source": "code_category_anchor"
  },
  {
    "row_index": 809,
    "code": "1221.001",
    "name": "个人",
    "picked": "122101 其他应收款",
    "score": 0.86,
    "source": "code_category_anchor"
  },
  {
    "row_index": 2259,
    "code": "1477",
    "name": "合同取得成本",
    "picked": "1475 合同履约成本",
    "score": 0.73,
    "source": "name_similarity"
  },
  {
    "row_index": 2367,
    "code": "1511",
    "name": "长期股权投资",
    "picked": "151101 长期股权投资-原值",
    "score": 0.83,
    "source": "name_similarity"
  },
  {
    "row_index": 2429,
    "code": "1521",
    "name": "投资性房地产",
    "picked": "152101 投资性房地产-原值",
    "score": 0.83,
    "source": "name_similarity"
  }
]
```

必须修：

1. 空编码 `合计` 行必须自动跳过，不能参与科目匹配和入账。
2. `1705.001 充电场站`、`1705.002 办公租赁`、`1706.001 充电场站` 未匹配。需要判断标准库是否缺少 `使用权资产累计折旧/租赁负债相关` 科目，或客户代码 `1705/1706` 应归入哪个标准科目，并补标准库/语义规则。
3. 小数点明细代码仍未完全安全化。`1122.001 -> 112201 应收账款`、`1221.001/1221.002/1221.004 -> 122101 其他应收款` 不应继续是 warning。
4. `1477 合同取得成本` 不应硬映射到 `1475 合同履约成本`，除非标准库明确没有合同取得成本且业务确认归类。更合理的是补标准科目 `1477 合同取得成本` 或建立明确规则。
5. 一级客户科目映射到标准明细时要谨慎：`1511 长期股权投资 -> 151101 长期股权投资-原值`、`1521 投资性房地产 -> 152101 投资性房地产-原值` 当前 score 低于 0.9，若这是系统标准结构，需要提高安全规则；若不应自动入明细，则应保留到标准一级/合成节点。

## 必须修改的文件范围

优先检查这些文件：

```text
backend/scripts/acceptance_task078_three_real_trial_balances.py
backend/app/services/file_parser.py
backend/app/services/standard_trial_balance_import_service.py
backend/app/services/client_account_mapping_service.py
backend/app/data/standard_accounts_seed.py
backend/tests/test_file_parser.py
backend/tests/test_standard_trial_balance_import.py
backend/tests/test_client_account_mapping_service.py
backend/tests/test_standard_trial_balance_view.py
```

如涉及 UI 显示，再检查：

```text
frontend/src/views/DataImportView.vue
frontend/src/views/DataView.vue
```

## 修复要求

### A. 修复验收脚本自身

删除：

```python
assert execute := None  # placeholder; we'll execute right below
```

脚本必须可以直接运行，不能依赖人工临时 patch。

### B. 自动跳过汇总/小计/合计行

新增或修正行过滤规则：

1. 科目编码或科目名称包含以下模式时，且不是有效科目代码，应自动跳过：
   - `合计`
   - `小计`
   - `(资产)小计：`
   - `(负债)小计：`
   - `(权益)小计：`
   - `(损益)小计：`
2. 这些行不得产生：
   - `mapping_recommendations`
   - `unmapped_account`
   - `warnings`
   - 入账分录
3. 需要在 analyze 返回的统计里能看见被跳过数量，至少验收脚本要能统计。

### C. 强化明细科目安全匹配

以下规则不能继续 warning：

```text
1122001 业务款项 -> 112201 应收账款
1122.001 业务款项 -> 112201 应收账款
1221001 个人 -> 122101 其他应收款
1221002 单位 -> 122101 其他应收款
1221.001 个人 -> 122101 其他应收款
1221.002 单位 -> 122101 其他应收款
1221.004 职员 -> 122101 其他应收款
1601003 电子设备 -> 160101 固定资产原值
1601004001 高压设备 -> 160101 固定资产原值
1601004002 充电桩设备 -> 160101 固定资产原值
1601004003 建安工程 -> 160101 固定资产原值
1601005 办公设备 -> 160101 固定资产原值
```

安全条件建议：

1. 客户代码去掉小数点后，与标准科目或标准科目父级存在稳定前缀关系。
2. 客户科目名称属于该类别的合理明细词，如 `业务款项`、`个人`、`单位`、`职员`、`电子设备`、`办公设备`。
3. 没有更强的同名标准科目候选。
4. 候选标准科目必须启用。

满足以上条件时，score 应 >= 0.9，且 `warning` 必须为 null。

### D. 补齐或明确标准科目

重点处理：

```text
1477 合同取得成本
1705.001 充电场站
1705.002 办公租赁
1706.001 充电场站
1511 长期股权投资
1521 投资性房地产
1523 投资性房地产减值准备
```

要求：

1. 如果企业会计准则标准库应存在这些一级或二级科目，就补入标准库。
2. 如果客户科目需要归入现有标准科目，必须写明确语义规则，不能只靠低分名称相似度。
3. 不能把不同性质科目强行归错类。例如 `1477 合同取得成本` 不能无依据归入 `1475 合同履约成本`。

### E. 验收脚本必须严格

`backend/scripts/acceptance_task078_three_real_trial_balances.py` 最后必须检查：

```text
每张表 execute.status == executed
每张表 entry_count > 0
每张表 unmatched_count == 0
每张表 unsafe_count == 0
每张表 non_parent_warning_count == 0
查询树 node_id 不重复
```

不要写这种永远放行的断言：

```python
assert s["warning_count"] == 0 or True
```

如果确实允许 `parent_amount_mismatch`，必须只允许这个 category，且在输出里列出数量和样本。

## 必跑命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest tests/test_file_parser.py tests/test_standard_trial_balance_import.py tests/test_client_account_mapping_service.py tests/test_standard_trial_balance_view.py -q
D:\python\python.exe -m pytest -q
$env:PYTHONIOENCODING='utf-8'
D:\python\python.exe scripts\acceptance_task078_three_real_trial_balances.py
```

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

## 通过标准

必须同时满足：

1. 定向测试通过。
2. 全量后端测试通过。
3. 前端构建通过。
4. `acceptance_task078_three_real_trial_balances.py` 直接运行成功。
5. 脚本最后输出 `TASK078_THREE_REAL_TRIAL_BALANCES_PASSED`。
6. 三张表摘要里：
   - `unmatched_count == 0`
   - `unsafe_count == 0`
   - `non_parent_warning_count == 0`
   - `entry_count > 0`
7. 不允许通过手工 ignored_rows 把真实业务行绕过去。只允许自动识别并跳过表头、说明行、合计/小计行、零金额模板行。

## 给执行 AI 的提示词

你要修复 TASK-079。先阅读：

```text
docs/tasks/TASK-078-three-real-trial-balance-imports.md
docs/tasks/TASK-079-fix-task078-real-trial-balance-acceptance.md
```

不要只跑单元测试，当前单元测试和前端构建已经能过，但真实表验收仍失败。

第一步先修 `backend/scripts/acceptance_task078_three_real_trial_balances.py` 第 213 行语法错误，保证脚本可以直接运行。

第二步修真实业务问题：

1. 广西海钦的 `(资产)小计：`、`(负债)小计：`、`(权益)小计：`、`(损益)小计：` 必须自动跳过，不能当科目。
2. 金碟的空编码 `合计` 行必须自动跳过，不能当科目。
3. 广西和金碟里 `1122/1221/1601` 这类客户明细科目的安全匹配还不够，不能继续 warning。
4. 金碟的 `1705.001/1705.002/1706.001` 仍未匹配，要查明这些科目应进入哪个标准科目，必要时补标准库。
5. `1477 合同取得成本` 不要错误归入 `1475 合同履约成本`，标准库应补则补。

完成后必须运行：

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest tests/test_file_parser.py tests/test_standard_trial_balance_import.py tests/test_client_account_mapping_service.py tests/test_standard_trial_balance_view.py -q
D:\python\python.exe -m pytest -q
$env:PYTHONIOENCODING='utf-8'
D:\python\python.exe scripts\acceptance_task078_three_real_trial_balances.py
```

再运行：

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

交付时贴出三张表各自的摘要，至少包括：

```text
preview_total_rows
data_start_row
active_recommendations
ignored_header_rows
ignored_zero_amount_rows
inherited_auxiliary_rows
unmatched_count
unsafe_count
warning_count
non_parent_warning_count
entry_count
tree_total_nodes
```

没有看到 `TASK078_THREE_REAL_TRIAL_BALANCES_PASSED`，就不能说完成。
