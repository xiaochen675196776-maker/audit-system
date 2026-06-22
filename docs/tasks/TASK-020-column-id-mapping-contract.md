# TASK-020：列 ID 与映射契约 v2

状态：OPEN
执行者：
开始时间：
完成时间：

## 目标

把后端导入映射从“表头文本取值”升级为“稳定列 ID / 列序号取值”，并保持旧 `column_mapping` 兼容。

当前问题：真实 74 列样本中有大量重复表头，例如 `摘要`、`说明`、`说明(简称)`、`交易对象简称`。现有 `headers.index(header)` 会取第一个同名列，导致重复表头映射错列。

## 前置依赖

- 必须等待 `TASK-019` 完成并验收。
- 开始前阅读 `docs/COMMAND_CENTER.md` 和本任务。
- 开始前运行 `git status --short`。

## 允许修改范围

可以修改：

- `backend/app/services/file_parser.py`
- `backend/app/services/column_matcher.py`
- `backend/app/services/import_service.py`
- `backend/app/api/imports.py`
- `backend/tests/`

不要修改：

- 前端页面
- ORM 模型
- 模板库相关模型/API
- `docs/UI_OPTIMIZATION_PLAN.md`

## 必须完成

1. 新增统一列描述结构，至少包含：
   - `column_id`：稳定列 ID，格式建议 `col_001`
   - `index`：0 基或 1 基列序号，但 API 文档和测试中必须一致
   - `header`：原始表头
   - `normalized_header`：规范化表头
   - `sample_values`：预览样例值
   - `duplicate_group`：重复表头分组信息；无重复时可为空
2. `/imports/preview` 返回 `columns`。
3. `/imports/preview` 继续保留旧字段：
   - `headers`
   - `matched`
   - `unmatched`
   - `missing`
   - `preview_rows`
4. `/imports/execute` 新增表单字段 `column_mapping_v2`，JSON 格式：

```json
{
  "col_001": "voucher_date",
  "col_010": "summary",
  "col_026": "department_desc"
}
```

5. 旧 `column_mapping` 仍支持，旧测试不能破。
6. `import_data()` 内部按列 ID / 列序号取值，不能再依赖 `headers.index(header)` 处理 v2 映射。
7. 对空表头也要生成列 ID，例如第 73 列空表头仍可被忽略或映射为辅助字段。
8. 错误提示必须是中文，不能直接把 JSON decode 或 KeyError 原文展示给用户。

## 建议实现边界

- 可以新增小型 helper，例如 `build_columns()`、`map_row_by_column_ids()`。
- 不要在本任务实现模板库、模板匹配分数或前端展示。
- 旧路径可以继续使用 `map_row()`，但 v2 路径必须覆盖重复表头场景。

## 必须测试

后端测试至少覆盖：

1. 重复表头生成不同 `column_id`。
2. 空表头生成稳定 `column_id`。
3. v2 映射能读取第二个或后续重复表头，不会取第一列。
4. 旧 `column_mapping` 仍能导入。
5. `/imports/preview` 返回 `columns` 且旧字段仍存在。
6. `column_mapping_v2` JSON 无效时返回中文错误。

测试样本必须合成生成，不提交真实 `backend/uploads/import_*.xlsx`。

## 验收命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest
```

```powershell
cd D:\APP\Codex-项目\13、审计系统
git diff --check -- backend docs
```

## 完成回报

按 `docs/tasks/DONE_TEMPLATE.md` 追加到本文件底部。
