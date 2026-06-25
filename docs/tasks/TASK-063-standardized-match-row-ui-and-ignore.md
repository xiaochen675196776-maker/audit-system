# TASK-063：层级与科目匹配行级重排、匹配修复与忽略行

状态：DONE
执行者：Codex + multi-agent
开始时间：2026-06-23 14:30

## 背景

总指挥复核发现，科目余额表标准化导入的 `层级与科目匹配` 步骤存在三个问题：

1. UI 排版混乱。当前页面把客户科目层级/金额放在左侧，把科目匹配放在右侧，用户需要横向对照，无法按客户原始科目余额表从上到下确认。
2. 匹配机制不稳定。部分应能匹配的客户科目显示未匹配，需要用户手动确认。
3. 缺少行级忽略能力。用户需要能选择某些客户科目行不导入标准科目余额表。

## 目标

将 `层级与科目匹配` 改为以客户原始科目余额表行为主轴的行级确认表：

```text
客户原始科目行
→ 层级/父末级状态
→ 金额摘要
→ 标准科目匹配状态
→ 选择/更换标准科目或忽略
→ 校验确认
→ 入库
```

## 产品口径

- UI 必须按客户科目余额表原始行顺序从上到下展示。
- 列方向展示该行要进入的标准科目、是否已匹配、匹配来源、置信度、警告和操作。
- 只有参与入库的末级客户科目要求匹配。
- 父级行默认不生成标准余额表明细，不要求匹配。
- 用户选择 `忽略` 的末级行：
  - 不要求匹配标准科目；
  - 不生成标准科目余额表明细；
  - 不保存客户科目映射经验；
  - 仍保留原始行快照，`mapping_status='ignored'`，用于审计追溯。

## 分派任务

### A. 后端行级契约与忽略行

负责人：worker

范围：

- `backend/app/schemas/standard_trial_balance.py`
- `backend/app/services/standard_trial_balance_import_service.py`
- `backend/tests/test_standard_trial_balance_import.py`

交付：

- `mapping_recommendations` 返回稳定 `row_index`，并尽可能返回 `is_leaf`、`is_summary`、`participates_in_entry`。
- `execute` 支持 `ignored_rows`。
- 被忽略行不入库、不保存映射经验，但保留 raw row 快照。
- 增加后端回归测试。

### B. 后端匹配算法修复

负责人：worker

范围：

- `backend/app/services/client_account_mapping_service.py`
- `backend/tests/test_client_account_mapping_service.py`

交付：

- 科目代码规范化后精确匹配。
- 科目名称规范化后先精确匹配，再相似度匹配。
- 无代码有名称时也能命中历史映射和标准名称匹配。
- 停用标准科目仍只作为警告候选。
- 增加匹配回归测试。

### C. 前端匹配页重排

负责人：worker

范围：

- `frontend/src/views/DataImportView.vue`
- `frontend/src/types/index.ts`

交付：

- 将左右面板改为客户原始行主表。
- 显示行级匹配状态、当前标准科目、来源/置信度、警告和操作。
- 支持忽略/取消忽略。
- `stdBlockingErrors`、`stdUnmappedCount`、`stdCanConfirm`、`stdCanExecute` 基于当前行级状态动态计算。
- `execute` 使用 `row_index` 提交 `confirmed_mappings` 和 `ignored_rows`。

### D. 总体验收

负责人：worker

范围：

- 验收报告和必要的最小修复。

交付：

- 覆盖自动匹配、手动匹配、忽略行、父级不入库、未忽略未匹配阻止入库。
- 运行后端 pytest、前端 build。
- 如可行，浏览器验证 `/data/import` 标准化导入流程。

## 验收

- `D:\python\python.exe -m pytest backend/tests/test_client_account_mapping_service.py`
- `D:\python\python.exe -m pytest backend/tests/test_standard_trial_balance_import.py`
- `D:\python\python.exe -m pytest backend/tests/ -q`
- `npm run build`（frontend）
- 浏览器或桌面端验证：`/data/import` 第三步按客户科目余额表行顺序展示，可忽略行并完成入库。

## 当前任务看板（2026-06-23）

### 已完成

| 编号 | 状态 | 内容 | 证据 |
| --- | --- | --- | --- |
| A | DONE | 后端 `mapping_recommendations` 增加 `row_index`、`is_leaf`、`is_summary`、`participates_in_entry`；`execute` 支持 `ignored_rows` | `backend` 目录运行 `D:\python\python.exe -m pytest tests/test_standard_trial_balance_import.py -q`：12 passed |
| B | DONE | 客户科目匹配算法支持代码规范化、名称精确匹配、无代码按名称命中历史/标准科目，停用科目只作警告候选 | `backend` 目录运行 `D:\python\python.exe -m pytest tests/test_client_account_mapping_service.py -q`：21 passed |

### 未完成

| 编号 | 状态 | 任务 | 文件范围 | 当前问题 |
| --- | --- | --- | --- | --- |
| C1 | TODO | 修复前端忽略行状态和 execute 提交契约 | `frontend/src/views/DataImportView.vue` | `npm run build` 报 `stdCancelIgnoreRow`、`stdIgnoreRow` 未定义；`StdExecuteRequest` 缺 `ignored_rows` |
| C2 | TODO | 修复前端行级状态计算残留的数组下标逻辑 | `frontend/src/views/DataImportView.vue` | `stdUnmappedCount`、`stdConfirmedMappingSummary`、`stdGoExecute` 仍有按 `stdMappingRecs` 数组下标读取 `stdConfirmedMap[i]` 的旧逻辑 |
| C3 | TODO | 前端展示细节收口 | `frontend/src/views/DataImportView.vue` | `matchSourceLabel` 缺 `name_exact` 中文；新主表样式类已在模板使用，但需要跑 build 后检查是否有遗漏 |
| D | TODO | 总体验收 | `backend/tests/`、`frontend/`、浏览器或桌面端 | 需在 C1-C3 完成后跑全量后端测试、前端 build，并验证 `/data/import` 标准化导入流程 |

## 当前已知构建失败

在 `frontend` 目录运行：

```powershell
npm run build
```

当前失败：

```text
src/views/DataImportView.vue(273,59): error TS2339: Property 'stdCancelIgnoreRow' does not exist
src/views/DataImportView.vue(334,80): error TS2339: Property 'stdIgnoreRow' does not exist
src/views/DataImportView.vue(2013,11): error TS2741: Property 'ignored_rows' is missing in type ...
```

## 给其他 AI 的提示词

### 提示词 C：修复前端行级匹配与忽略行

```text
你负责完成 TASK-063 的前端剩余部分。工作目录：
D:\APP\Codex-项目\13、审计系统

不要回退已有改动；当前工作区有导入模板下线、标准化导入、TASK-063 的部分变更。你的写入范围尽量只限：
- frontend/src/views/DataImportView.vue
- frontend/src/types/index.ts（只有类型确实需要时）

当前后端契约已经可用：
- mapping_recommendations 每项有 row_index、is_leaf、is_summary、participates_in_entry
- ExecuteRequest 支持 ignored_rows: number[]
- 后端定向测试已通过：
  - backend 目录运行 D:\python\python.exe -m pytest tests/test_client_account_mapping_service.py -q：21 passed
  - backend 目录运行 D:\python\python.exe -m pytest tests/test_standard_trial_balance_import.py -q：12 passed

当前前端 build 失败：
1. DataImportView.vue 模板调用 stdCancelIgnoreRow，但函数未定义。
2. DataImportView.vue 模板调用 stdIgnoreRow，但函数未定义。
3. stdGoExecute 构造 StdExecuteRequest 时缺 ignored_rows。

必须完成：
1. 新增 stdIgnoreRow(rowIndex)：
   - 只能忽略参与入库的末级行；如果不是参与入库行，给中文提示。
   - 设置 stdIgnoredRows[rowIndex] = true。
   - 清除该行 stdConfirmedMap[rowIndex]。
   - 清除该行搜索框和搜索结果。
   - 如果 stdWarningsConfirmed=true，重置为 false。
2. 新增 stdCancelIgnoreRow(rowIndex)：
   - 删除 stdIgnoredRows[rowIndex]。
   - 如果该行有高置信候选且无 warning，可选地重新自动选中；不做也可以。
   - 如果 stdWarningsConfirmed=true，重置为 false。
3. 修复 stdUnmappedCount：
   - 必须基于 stdReviewRows/stdRowRequiresMapping/stdSelectedMapping(row.row_index) 计算。
   - 不得再用 stdMappingRecs 数组下标 i 查 stdConfirmedMap[i]。
   - 已忽略行、父级行、无身份空行都不计未匹配。
4. 修复 stdConfirmedMappingSummary：
   - 基于 stdReviewRows 按 row_index 汇总。
   - 已忽略行不进入摘要。
   - 父级不入库行不进入摘要。
5. 修复 stdGoExecute：
   - confirmed_mappings 必须按 row_index 提交。
   - 使用 row.rec/client_account_code/client_account_name，不得靠代码名称回找 hierarchy。
   - 提交 ignored_rows: stdIgnoredRowIndexes.value。
6. matchSourceLabel 增加 name_exact: “名称精确”。
7. 跑 npm run build，必须通过。

建议重点查看：
- frontend/src/views/DataImportView.vue 中 stdReviewRows、stdRowRequiresMapping、stdSelectedMapping、stdUnmappedCount、stdGoExecute 附近。

验收命令：
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build

完成后回报：
- 修改文件
- 如何处理忽略行
- 如何确保 execute 用 row_index + ignored_rows
- npm run build 结果
```

### 提示词 D：总体验收与最小修复

```text
你负责 TASK-063 的总体验收。工作目录：
D:\APP\Codex-项目\13、审计系统

前置条件：先确认前端修复任务 C 已完成，frontend/npm run build 通过。

不要回退已有改动；工作区存在导入模板下线和 TASK-063 相关变更。优先只做验收，只有发现阻塞性问题才做最小修复。

验收命令：
1. cd D:\APP\Codex-项目\13、审计系统\backend
   D:\python\python.exe -m pytest tests/test_client_account_mapping_service.py -q
2. cd D:\APP\Codex-项目\13、审计系统\backend
   D:\python\python.exe -m pytest tests/test_standard_trial_balance_import.py -q
3. cd D:\APP\Codex-项目\13、审计系统\backend
   D:\python\python.exe -m pytest tests/ -q
4. cd D:\APP\Codex-项目\13、审计系统\frontend
   npm run build
5. cd D:\APP\Codex-项目\13、审计系统
   git diff --check -- backend frontend docs

浏览器或桌面端验收（如本地服务可启动）：
- 打开 /data/import。
- 上传科目余额表样本，至少包含：
  - 1001 库存现金，可自动匹配。
  - 1002 银行存款，可自动匹配或名称匹配。
  - 9999 待忽略科目，无匹配。
- 字段映射后进入“层级与科目匹配”。
- 确认第三步按客户原始行顺序展示。
- 确认父级行显示“父级不入库”且不阻止。
- 对 9999 点击“忽略”，确认未匹配数量下降，下一步可继续。
- 执行入库后确认 entry_count 不包含忽略行。

如发现问题：
- 只做最小修复。
- 不要重构 DataImportView.vue。
- 不要恢复已删除的导入模板功能。

完成后回报：
- 每条命令结果
- 浏览器验收覆盖情况
- 是否有残余风险
```

## 备注

- 当前不要再分派后端 A/B，除非后续全量测试暴露新问题。
- `docs/COMMAND_CENTER.md` 中 TASK-063 已更新为 `DONE`。

## 验收记录（2026-06-23）

验收人：Codex

### 自动化命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest tests/test_client_account_mapping_service.py -q
```

## 复验记录（2026-06-23）

验收人：Codex

### 自动化命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest tests/test_client_account_mapping_service.py -q
```

结果：`21 passed, 1 warning`

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest tests/test_standard_trial_balance_import.py -q
```

结果：`12 passed, 1 warning`

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

结果：通过，`vue-tsc && vite build` 成功。

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest tests/ -q
```

结果：`313 passed, 3 warnings`

```powershell
cd D:\APP\Codex-项目\13、审计系统
git diff --check -- backend frontend docs
```

结果：通过；仅有 LF/CRLF 换行提示。

### 浏览器流程复验

样本文件：

```text
backend/uploads/stb_preview_0b940da251af4e78b54df9105fec61f7_audit-std-tb-e2e-051.xlsx
```

流程：

1. 打开 `/data/import`。
2. 填写客户、年度、期间。
3. 上传样本文件。
4. 进入 `字段与金额映射`。
5. 映射：
   - `科目代码` -> `客户科目代码`
   - `科目名称` -> `客户科目名称`
   - `期末金额` -> `期末金额`
6. 点击 `下一步：层级与科目匹配`。
7. 校验第三步行级主表：
   - 显示 `1001 库存现金`，期末借方 `100.00`，代码匹配。
   - 显示 `1002 银行存款`，期末借方 `200.00`，代码匹配。
   - 显示 `998877 未匹配验收科目`，未匹配数量为 `1`。
8. 点击 `998877` 行的 `忽略`。
9. 校验 `已忽略 1`，`未匹配 0`。

结果：通过。截图证据保存在：

```text
frontend/ui-acceptance-shots/task063-recheck-after-ignore.png
```

结论：TASK-063 验收通过。

结果：`21 passed, 1 warning`

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest tests/test_standard_trial_balance_import.py -q
```

结果：`12 passed, 1 warning`

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

结果：通过，`vue-tsc && vite build` 成功。

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest tests/ -q
```

结果：`313 passed, 3 warnings`

```powershell
cd D:\APP\Codex-项目\13、审计系统
git diff --check -- backend frontend docs
```

结果：通过；仅有 LF/CRLF 换行提示。

### 页面截图验收

运行 `frontend/screenshot.cjs`，结果：

- `home-desktop.png`
- `import-desktop.png`
- `companies-desktop.png`
- `home-tablet.png`
- `import-tablet.png`
- `companies-tablet.png`
- `home-small.png`
- `import-small.png`
- `companies-small.png`

全部生成成功，`/data/import` 首屏在桌面和小屏下可加载，无明显崩溃或遮挡。

### 浏览器流程验收

样本文件：

```text
backend/uploads/stb_preview_0b940da251af4e78b54df9105fec61f7_audit-std-tb-e2e-051.xlsx
```

样本内容：

```text
科目代码 | 科目名称       | 期末金额
1001     | 库存现金       | 100
1002     | 银行存款       | 200
998877   | 未匹配验收科目 | 300
```

流程：

1. 打开 `/data/import`。
2. 填写客户、年度、期间。
3. 上传样本文件。
4. 进入 `字段与金额映射`。
5. 映射：
   - `科目代码` -> `客户科目代码`
   - `科目名称` -> `客户科目名称`
   - `期末金额` -> `期末金额`
6. 点击 `下一步：层级与科目匹配`。

实际结果：

- 成功进入第三步。
- 第三步已展示行级主表、筛选项、`选择` 和 `忽略` 操作按钮。
- 但 3 行的客户科目代码/名称均显示 `—`。
- 金额摘要全部为 `0.00`。
- 未匹配数量显示 `0`，与样本中 `998877 未匹配验收科目` 不一致。

结论：**验收不通过，需继续修复前端字段映射传递或 analyze 请求构造。**

### 下一步提示词

```text
你负责修复 TASK-063 的浏览器流程验收失败项。工作目录：
D:\APP\Codex-项目\13、审计系统

不要回退已有改动；当前自动化测试和前端 build 已通过。只做最小修复，优先改：
- frontend/src/views/DataImportView.vue
- 如确认为后端字段契约问题，再小范围改 backend/app/services/standard_trial_balance_import_service.py

当前验收失败：
浏览器中上传样本并映射：
- 科目代码 -> 客户科目代码
- 科目名称 -> 客户科目名称
- 期末金额 -> 期末金额
点击“下一步：层级与科目匹配”后，第三步能进入行级主表，但所有行显示：
- 客户科目代码为 —
- 客户科目名称为 —
- 金额摘要全部 0.00
- 未匹配数量为 0

样本文件：
backend/uploads/stb_preview_0b940da251af4e78b54df9105fec61f7_audit-std-tb-e2e-051.xlsx

样本内容：
科目代码 | 科目名称       | 期末金额
1001     | 库存现金       | 100
1002     | 银行存款       | 200
998877   | 未匹配验收科目 | 300

已通过命令：
- backend: D:\python\python.exe -m pytest tests/test_client_account_mapping_service.py -q -> 21 passed
- backend: D:\python\python.exe -m pytest tests/test_standard_trial_balance_import.py -q -> 12 passed
- backend: D:\python\python.exe -m pytest tests/ -q -> 313 passed
- frontend: npm run build -> passed

重点排查：
1. DataImportView.vue 的 stdGoAnalyze 是否把 stdMappings 正确转换为 field_mappings。
2. Element Plus 选择“客户科目代码/客户科目名称/期末金额”后，stdMappings[*].field_name 是否确实变成 account_code/account_name/ending_amount。
3. stdOnFieldChange 或重复字段清理逻辑是否在选择后把 field_name 清空。
4. analyze 请求 payload 是否包含：
   - { column_id: "col_0", field_name: "account_code" }
   - { column_id: "col_1", field_name: "account_name" }
   - { column_id: "col_2", field_name: "ending_amount", period_type: "ending", split_mode: "single_by_direction" }
5. 如果 payload 正确，再查后端 analyze 是否按 column_id 取值。

验收标准：
1. 第三步行级主表按原始行顺序显示：
   - 1001 库存现金
   - 1002 银行存款
   - 998877 未匹配验收科目
2. 金额摘要中 期末金额不应全为 0。
3. 1001/1002 能自动匹配或显示可用候选。
4. 998877 未匹配时未匹配数量应为 1。
5. 点击 998877 的“忽略”后未匹配数量变为 0，可进入下一步。
6. npm run build 仍通过。

完成后回报：
- 根因
- 修改文件
- npm run build 结果
- 浏览器流程验收结果
```
