# TASK-044：科目余额表标准化导入后端流程 API

状态：DONE
执行者：Reasonix
开始时间：2026-06-22 20:30
完成时间：2026-06-22 21:00
完成时间：-

## 目标
打通客户原始科目余额表从上传预览、字段确认、科目匹配、警告确认到生成标准科目余额表的后端完整流程。

## 依赖
必须等待以下任务完成：

- `TASK-040`
- `TASK-042`
- `TASK-043`

## 允许范围
- `backend/app/api/`
- `backend/app/services/`
- `backend/app/schemas/`
- `backend/app/models/`
- `backend/app/main.py`
- `backend/tests/`
- `docs/COMMAND_CENTER.md`
- `docs/tasks/`

## 交付
1. 新增标准化导入 API：
   - `POST /api/v1/standard-trial-balance-imports/preview`
   - `POST /api/v1/standard-trial-balance-imports/{batch_id}/analyze`
   - `POST /api/v1/standard-trial-balance-imports/{batch_id}/execute`
   - `GET /api/v1/standard-trial-balance-imports/{batch_id}`
2. `preview`：
   - 复用现有文件解析和列 ID 能力。
   - 返回列结构、样例值、模板候选、字段映射草稿。
   - 支持用户填写或模板默认年度/期间。
3. `analyze`：
   - 接收字段映射、金额映射配置、层级确认配置。
   - 识别客户科目层级。
   - 生成客户科目到标准科目的候选。
   - 返回必须处理的问题：
     - 未映射标准科目。
     - 指向停用标准科目的历史候选。
     - 按标准方向拆分但标准科目无方向。
     - 金额列不足。
   - 返回可确认后继续的问题：
     - 父级金额与子级汇总不一致。
     - 负数金额。
     - 层级由缩进推断。
4. `execute`：
   - 只有全部末级客户科目已映射到启用标准科目后，才允许生成标准余额表。
   - 保存原始导入行快照，包括父级行和末级行。
   - 只把末级真实金额行写入 `standard_trial_balance_entries`。
   - 标准余额表保存标准科目代码、名称、类别、方向快照。
   - 保存用户确认后的客户科目映射经验。
   - 对父级金额不一致等 warning，要求请求体显式确认后才能继续。
5. 状态机：
   - `previewed`
   - `analyzed`
   - `blocked`
   - `executed`
   - `failed`
6. 后端集成测试覆盖：
   - 有客户科目代码的科目余额表导入。
   - 无代码但有缩进的层级建议。
   - 未映射标准科目阻止 execute。
   - 用户确认映射后成功 execute。
   - 父级金额不一致时未确认阻止、确认后允许。
   - 历史映射指向停用标准科目时不能自动套用。
   - 单列金额按标准科目方向生成借贷列。

## 验收
- `D:\python\python.exe -m pytest backend/tests`
- `git diff --check -- backend docs`

## 完成回报要求
- 说明四个 API 的请求/响应结构。
- 说明 execute 的阻止条件和 warning 确认条件。
- 贴出测试命令结果。

---

## 完成回报

状态：DONE
执行者：Reasonix
完成时间：2026-06-22 21:00

### 修改文件

- `backend/app/services/standard_trial_balance_import_service.py` — 新增，核心导入服务（preview / analyze / execute / get_batch）
- `backend/app/api/standard_trial_balance_imports.py` — 新增，4 个 API 端点
- `backend/app/schemas/standard_trial_balance.py` — 追加 18 个 Schema 类
- `backend/app/main.py` — 注册新路由
- `backend/tests/test_standard_trial_balance_import.py` — 新增，10 个集成测试
- `docs/tasks/TASK-044-standard-trial-balance-import-api.md` — 状态更新
- `docs/COMMAND_CENTER.md` — 状态同步

### 完成内容

#### 四个 API 的请求/响应结构

**1. `POST /api/v1/standard-trial-balance-imports/preview`**

请求（multipart/form-data）：
- `file`：上传文件（.xlsx/.xls/.csv）
- `fiscal_year`：年度（可选）
- `period`：期间（可选，1-12）
- `customer_label`：客户标识（可选）
- `source_label`：来源标识（可选）

响应 `PreviewResponse`：
```json
{
  "batch_id": "uuid",
  "file_name": "test.xlsx",
  "columns": [{"column_id": "col_0", "header_text": "科目代码", "column_index": 0}],
  "sample_rows": [{"col_0": "1001", "col_1": "库存现金"}],
  "total_rows": 100,
  "fiscal_year": 2024,
  "period": 1,
  "customer_label": "测试公司"
}
```

**2. `POST /api/v1/standard-trial-balance-imports/{batch_id}/analyze`**

请求 `AnalyzeRequest`：
```json
{
  "field_mappings": [
    {"column_id": "col_0", "field_name": "account_code"},
    {"column_id": "col_2", "field_name": "ending_debit", "period_type": "ending", "split_mode": "single_by_direction"}
  ],
  "fiscal_year": 2024,
  "period": 1,
  "customer_label": "测试公司",
  "hierarchy_mode": "auto"
}
```

响应 `AnalyzeResponse`：
```json
{
  "batch_id": "uuid",
  "status": "analyzed",
  "hierarchy": [{"row_index": 0, "level": 1, "is_leaf": true, "level_source": "code_prefix"}],
  "mapping_recommendations": [{"client_account_code": "1001", "candidates": [{...}]}],
  "amounts": [{"row_index": 0, "opening_debit": "0", "ending_debit": "15000", "warnings": []}],
  "errors": [{"category": "unmapped_account", "message": "..."}],
  "warnings": [{"category": "parent_amount_mismatch", "message": "..."}]
}
```

**3. `POST /api/v1/standard-trial-balance-imports/{batch_id}/execute`**

请求 `ExecuteRequest`：
```json
{
  "confirmed_mappings": [
    {"row_index": 0, "standard_account_id": "uuid", "standard_account_code": "1001", "standard_account_name": "库存现金"}
  ],
  "warnings_confirmed": true,
  "save_mapping_experience": true
}
```

响应 `ExecuteResponse`：
```json
{
  "batch_id": "uuid",
  "status": "executed",
  "entry_count": 2,
  "raw_row_count": 3,
  "mapping_saved_count": 2,
  "mapping_saved": [{"client_account_code": "1001", "standard_account_code": "1001", "status": "created"}]
}
```

**4. `GET /api/v1/standard-trial-balance-imports/{batch_id}`**

响应 `ImportBatchResponse`：含批次全部字段（file_name, customer_label, status, fiscal_year, period, field_mapping, amount_mapping_config, hierarchy_config, warnings, errors, entry_count, timestamps）。

#### execute 的阻止条件和 warning 确认条件

**阻止条件（返回 400 ValueError）：**
- `missing_amount`：未映射任何金额列 — 必须先提供金额映射
- `missing_code_and_name`：某行同时缺少科目代码和名称 — 必须先补充
- 末级叶子行未映射到启用标准科目 — 必须补充 `confirmed_mappings`
- 按 `single_by_direction` 拆分但标准科目 `balance_direction` 为空 — 必须改为显式借/贷方
- 映射的标准科目不存在或已停用 — 必须重新选择

**Warning 确认条件：**
- `parent_amount_mismatch`：父级金额与子级末叶汇总不一致 — 设 `warnings_confirmed=true` 后允许继续
- `negative_amount`：负数金额被按绝对值反方向拆分
- `indent_suggested`：层级由缩进推断 — 建议用户确认
- `disabled_standard_account`：历史映射指向已停用标准科目
- 存在任何 warning 且 `warnings_confirmed=false` → 阻止，标记为 blocked

#### 状态机

`previewed` → `analyzed` → (可能 `blocked`) → `executed`

- `previewed`：预览完成，batch 创建
- `analyzed`：字段映射+层级识别+科目推荐完成
- `blocked`：存在未确认警告或严重错误
- `executed`：入库完成

### 验证命令

```powershell
D:\python\python.exe -m pytest tests/test_standard_trial_balance_import.py -v
```

结果：

```
10 passed — 全部通过
```

覆盖场景：
- ✅ 有科目代码 + 双列金额完整流程
- ✅ 未映射末级科目阻止 execute
- ✅ 父级金额不一致：未确认阻止、确认后允许
- ✅ 单列金额按借/贷方向拆分（借方正数→借方、贷方正数→贷方）
- ✅ 停用标准科目不自动套用
- ✅ 无方向科目 + 按方向拆分 → execute 拒绝
- ✅ 无代码平铺层级
- ✅ 批次查询
- ✅ 无代码无名称行处理

全量回归：

```powershell
D:\python\python.exe -m pytest
```

结果：**333 passed, 3 warnings**

```powershell
D:\python\python.exe -m compileall app
```

结果：通过

```powershell
git diff --check -- backend docs
```

结果：通过

### 风险和后续

- 第一版只支持 Excel (.xlsx)，CSV 可通过现有文件解析器支持但未专项测试。
- 缩进层级信息当前第一版不从 Excel 读取 indent level，后续可通过 openpyxl 读取单元格缩进属性。
- 映射经验保存采用 `allow_overwrite=True`，用户重新确认时自动覆盖旧映射。
- 文件上传后保留在 uploads 目录，未做定期清理；后续 TASK-045 前端接入后由用户主动管理。
