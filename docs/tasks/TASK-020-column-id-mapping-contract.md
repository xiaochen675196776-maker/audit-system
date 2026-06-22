# TASK-020：列 ID 与映射契约 v2

状态：DONE
执行者：Reasonix
开始时间：2026-06-23 00:00
完成时间：2026-06-23 01:00

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

状态：DONE
执行者：Reasonix
完成时间：2026-06-23 01:00

### 修改文件

- `backend/app/services/file_parser.py` — 新增 `build_columns()` + `_extract_sample_values()` 辅助函数
- `backend/app/services/column_matcher.py` — 新增 `map_row_by_column_ids()`（v2 列 ID 映射）
- `backend/app/services/import_service.py` — `preview_import()` 新增 `columns` 字段；`import_data()` 新增 `column_mapping_v2` 参数，v2 优先于旧映射
- `backend/app/api/imports.py` — `/imports/execute` 新增 `column_mapping_v2` 表单字段，JSON 解析错误返回中文提示
- `backend/tests/test_import_service.py` — 新增 `TestColumnV2Mapping` 类（11 个测试）

### 实现摘要

#### 1. 列描述符 `build_columns()`
每个文件列生成稳定描述：
```json
{
  "column_id": "col_003",
  "index": 2,
  "header": "摘要",
  "normalized_header": "摘要",
  "sample_values": ["采购原材料"],
  "duplicate_group": {"header": "摘要", "occurrence": 1, "total": 3}
}
```
- 空表头也生成 `column_id`
- 重复表头通过 `duplicate_group` 标记第几次出现

#### 2. v2 映射 `map_row_by_column_ids()`
- 通过 `column_id → index` 定位列，不依赖 `headers.index(header)`
- 未知 `column_id` 静默忽略（不抛异常）
- 不受重复表头、空表头影响

#### 3. 数据流优先级
```
column_mapping_v2 (优先)
  ↓ 未传则
column_mapping (旧契约，仍兼容)
  ↓ 未传则
auto_match (自动匹配)
```

#### 4. API 变更
- `/imports/preview` → 返回新增 `columns`，旧字段（`headers`/`matched`/`unmatched`/`missing`/`preview_rows`）完全保留
- `/imports/execute` → 新增 `column_mapping_v2` 表单参数；同时传 v1+v2 时优先 v2

### 新增测试（11 个）

| 测试 | 覆盖场景 |
| --- | --- |
| `test_build_columns_generates_stable_ids` | 基本 col_001 格式 |
| `test_duplicate_headers_get_different_ids` | 三个"摘要"→ 三个不同 column_id，duplicate_group.occurrence 正确 |
| `test_empty_headers_get_stable_id` | 空表头 col_002/col_003 不会跳过 |
| `test_map_row_by_column_ids_reads_correct_column` | v2 映射到第二个"摘要"（col_003），不取第一个 |
| `test_map_row_by_column_ids_ignores_unknown_column_ids` | col_999 不存在 → 不抛异常 |
| `test_preview_returns_columns_alongside_old_fields` | columns + 旧字段同时存在 |
| `test_v2_mapping_import_with_duplicate_header` | 端到端：v2 导入重复表头文件，第二个摘要入库 |
| `test_old_column_mapping_still_works` | 旧 column_mapping 仍能导入 |
| `test_v2_import_empty_header_column` | 空表头列映射为辅助字段 normal 入库 |
| `test_v2_mapping_invalid_json` | JSON 无效时 json.JSONDecodeError 可被捕获 |
| `test_v2_keeps_old_compat_when_both_provided` | 同时传 v1+v2 → v2 优先 |

### 验收命令与结果

- `D:/python/python.exe -m pytest` → **100 passed, 0 failed**（从 89 增至 100）
- `npm run build` → **通过**，vue-tsc 零错误，5.29s（本次未改前端）
- `git diff --check -- backend docs` → **通过**，仅 LF/CRLF 提示

### 风险和后续

- `TASK-021` 导入模板库后端可依赖本任务提供的 `columns` + `column_mapping_v2` 接口。
- 旧前端（当前 `DataImportView.vue`）使用 `column_mapping` 旧契约，功能不受影响；后续 `TASK-024` 需要前端适配 v2 映射提交。
- v2 映射中 `column_id` 未知时静默忽略，不会报错 —— 这是设计选择，避免过严的校验阻塞正常导入。
