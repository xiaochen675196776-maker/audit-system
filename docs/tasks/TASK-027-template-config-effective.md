# TASK-027：模板解析配置与默认值必须生效

状态：DONE
执行者：Reasonix
开始时间：2026-06-22 15:30
完成时间：2026-06-22 16:00

## 目标

修复模板库“保存了 `parse_config/default_values` 但实际不生效”的问题。模板第一版承诺支持“解析 + 映射”，因此表头行、数据起始行、默认年度/期间不能只是展示字段。

## 前置依赖

- 必须等待 `TASK-026` 完成并通过总指挥验收。
- 开始前必须阅读 `docs/COMMAND_CENTER.md` 和本任务。
- 开始前运行 `git status --short`，不要回滚已有改动。

## 允许修改范围

可以修改：

- `backend/app/services/file_parser.py`
- `backend/app/services/import_service.py`
- `backend/app/services/template_service.py`
- `backend/app/services/template_matcher.py`
- `backend/app/api/imports.py`
- `backend/app/api/import_templates.py`
- `backend/tests/test_file_parser.py`
- `backend/tests/test_template_service.py`
- `backend/tests/test_import_service.py`
- `frontend/src/views/ImportTemplatesView.vue`
- `frontend/src/views/DataImportView.vue`（仅当需要展示或传递默认值）
- `frontend/src/types/index.ts`
- `docs/tasks/TASK-027-template-config-effective.md`

不要修改：

- ORM 模型，除非发现当前字段无法表达本任务要求并先在完成回报中说明
- 与模板解析无关的公司管理、首页、视觉重构

## 必须修复

### 1. `parse_config` 生效

模板支持的解析配置至少包括：

- `header_row`：表头行，建议 0 基。
- `data_start_row`：数据起始行，建议 0 基。
- `encoding`：CSV 编码，`auto` 可继续走现有探测。

硬性要求：

- `from_sample()` 生成草稿时可以继续默认 `{"header_row": 0, "data_start_row": 1, "encoding": "auto"}`。
- `test_template()` 必须使用模板的 `parse_config` 解析文件。
- `/imports/preview` 指定 `template_id` 时必须使用该模板的 `parse_config`。
- `/imports/execute` 如果传入 `template_id`，必须使用该模板的 `parse_config` 和映射规则。

### 2. `default_values` 生效

模板默认值至少支持：

- `fiscal_year`
- `period`

硬性要求：

- 当文件中没有年度/期间列，且模板 `default_values` 提供了对应值时，导入必须使用模板默认值。
- 用户手动传入的 `fiscal_year` / `period` 优先级高于模板默认值。
- 如果文件列、用户手动值、模板默认值都没有，仍按现有校验返回中文缺失原因。

### 3. 前端模板管理页不能误导用户

如果 UI 允许编辑默认值，就必须确保这些值能参与测试/导入。

硬性要求：

- 模板测试结果里能体现默认年度/期间是否补齐。
- 导入页套用模板后，若模板默认值补齐年度/期间，检查面板不能继续误报缺失。

## 必须新增测试

至少新增这些测试：

1. `test_parse_file_with_template_config_header_row`
   - 文件第一行是标题说明，第二行才是表头。
   - 使用 `header_row=1, data_start_row=2` 能正确解析。

2. `test_test_template_uses_parse_config`
   - 模板配置 `header_row=1`。
   - `test_template()` 能识别第二行表头。

3. `test_preview_with_template_id_uses_parse_config`
   - 指定模板预览，返回列信息来自配置指定的表头行。

4. `test_import_uses_template_default_fiscal_year_period`
   - 文件不含年度/期间列。
   - 模板 `default_values={"fiscal_year": 2024, "period": 12}`。
   - 导入成功，入库数据年度期间正确。

5. `test_manual_fiscal_year_period_override_template_defaults`
   - 模板默认值为 2024/12。
   - 用户手动传入 2025/1。
   - 入库使用 2025/1。

## 验收命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest tests/test_file_parser.py tests/test_template_service.py tests/test_import_service.py
```

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest
```

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

```powershell
cd D:\APP\Codex-项目\13、审计系统
git diff --check -- backend frontend docs
```

## 完成回报

按 `docs/tasks/DONE_TEMPLATE.md` 追加到本文件底部。
