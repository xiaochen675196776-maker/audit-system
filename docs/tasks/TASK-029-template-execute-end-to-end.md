# TASK-029：套用模板后的最终导入链路修复

状态：DONE
执行者：Reasonix
开始时间：2026-06-22 16:30
完成时间：2026-06-22 17:00

## 背景

`TASK-028` 复验未通过。后端模板匹配安全、重复表头样本生成、`parse_config/default_values` 的服务层能力已经修复，但导入页最终执行导入时没有把用户已确认的模板 ID 提交给 `/imports/execute`。

结果是：预览阶段用模板正确跳过标题行、生成 `column_mapping_v2` 和返回默认年度/期间；最终导入阶段却按普通文件重新解析，模板 `parse_config` 和 `default_values` 失效。包含标题行且文件无年度/期间列的样本会在确认模板后仍导入失败。

同时，导入页字段映射表仍只显示原始列名，没有按要求显示列序号；模板默认值也没有参与前端缺失字段检查。

## 目标

修复“用户确认套用模板 → 执行导入”的端到端链路，保证确认后的模板配置真实参与最终导入。

## 允许修改范围

可以修改：

- `frontend/src/views/DataImportView.vue`
- `frontend/src/types/`
- `backend/app/api/imports.py`
- `backend/app/services/import_service.py`
- `backend/tests/`
- `docs/COMMAND_CENTER.md`
- `docs/tasks/`

不要修改：

- 模板匹配评分算法，除非本任务验收复现直接需要。
- 模板管理页大范围 UI。
- 与导入模板库无关的模块。

## 必须交付

1. 导入页在用户点击模板候选并成功套用后，执行导入请求必须提交 `template_id`。
2. `/imports/execute` 收到 `template_id` 时必须校验模板存在、启用、`data_type` 一致；不满足时返回中文 400 错误，不能静默忽略。
3. `/imports/execute` 必须使用该模板的 `parse_config` 和 `default_values` 完成最终导入；用户手动年度/期间仍优先于模板默认值。
4. 前端套用模板后，要把预览返回的 `template_default_values` 纳入缺失字段检查；模板默认值能补齐 `fiscal_year/period` 时，不应阻止用户开始导入。
5. 字段映射表展示列名时附带列序号，例如 `说明（第 26 列）`；重复表头必须能看出第几列。
6. 取消套用模板后，后续执行不得继续提交旧的 `template_id`；用户仍可保留并手动调整当前映射。

## 必须补充测试

后端至少增加：

1. API 或服务层回归：文件第 1 行是标题、第 2 行是表头、无年度/期间列；预览指定模板生成 `column_mapping_v2` 后，执行导入传入 `template_id + column_mapping_v2` 应成功入库，并写入模板默认年度/期间。
2. `/imports/execute` 传入不存在模板、停用模板、数据类型不一致模板时返回中文错误。
3. 用户手动年度/期间覆盖模板默认值。

前端至少通过构建，并用代码实现覆盖：

1. `goExecute()` 在 `selectedTemplateId` 存在时 append `template_id`。
2. 模板默认值参与 `mappingValid` 判断。
3. 映射表列名展示带列序号。

## 验收命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest
```

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m compileall app
```

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

```powershell
cd D:\APP\Codex-项目\13、审计系统
git diff --check -- backend frontend docs .gitignore
```

## 手工验收场景

1. 创建或使用一个模板：`parse_config.header_row=1`、`data_start_row=2`、`default_values={"fiscal_year": 2024, "period": 3}`。
2. 上传样本：第 1 行标题、第 2 行表头，文件无年度/期间列。
3. 在导入页确认套用模板。
4. 检查字段映射表显示列序号。
5. 不手工填写年度/期间，直接执行导入。
6. 期望：导入成功，数据库记录年度为 2024、期间为 3。

## 完成回报

按 `docs/tasks/DONE_TEMPLATE.md` 追加到本文件底部。

## 总指挥复验结论

- 验收日期：2026-06-22
- 结论：不通过，需先执行 `TASK-030-template-cancel-state-cleanup.md`。
- 已通过项：
  - `D:\python\python.exe -m pytest`：通过，134 passed。
  - `D:\python\python.exe -m compileall app`：通过。
  - `npm run build`：通过。
  - `git diff --check -- backend frontend docs .gitignore`：通过。
  - `/imports/execute` 带 `template_id + column_mapping_v2` 能按模板 `parse_config/default_values` 成功导入。
  - `/imports/execute` 对不存在、停用、类型不一致、非法 UUID 模板返回中文 400 错误。
- 阻塞项：
  - 前端点击“取消套用”只清空 `selectedTemplateId`，没有清空 `templateDefaultValues`。
  - 重新普通预览时也没有清空旧的 `templateDefaultValues`。
  - 因此前端可能继续用旧模板默认年度/期间放行校验，但最终执行请求不带 `template_id`，后端不会补默认值。

## 总指挥二次复验结论

- 验收日期：2026-06-22
- 结论：通过；`TASK-030` 已修复本任务遗留的前端默认值状态残留。
- 验收结果：
  - `D:\python\python.exe -m pytest`：通过，134 passed。
  - `D:\python\python.exe -m compileall app`：通过。
  - `npm run build`：通过。
  - `git diff --check -- backend frontend docs .gitignore`：通过。
  - `/imports/execute` 模板执行链路保持通过。
  - 取消套用、普通预览、套用失败均不会残留旧模板默认值。
