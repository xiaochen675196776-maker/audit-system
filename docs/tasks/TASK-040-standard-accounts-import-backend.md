# TASK-040：标准科目表导入后端 API

状态：DONE
执行者：Reasonix
开始时间：2026-06-22 20:30
完成时间：2026-06-22 20:45
完成时间：-

## 目标
本任务早期目标是提供标准科目 Excel 同步能力和标准科目查询能力。总指挥后续已确认：标准科目模板应改为系统内置主数据，不作为普通产品导入入口。

> 总指挥口径修正：标准科目模板不是普通用户导入的文件，而是系统内置主数据。此任务按旧口径完成，后续由 `TASK-049-standard-account-built-in-template-correction.md` 修正公开上传 API 和内置模板初始化逻辑。

## 依赖
必须等待 `TASK-039` 完成。

## 允许范围
- `backend/app/api/`
- `backend/app/services/`
- `backend/app/schemas/`
- `backend/app/models/`
- `backend/app/main.py`
- `backend/tests/`
- `docs/COMMAND_CENTER.md`
- `docs/tasks/`

## 标准模板格式
用户标准模板来自 `科目余额表.xlsx`，当前表头为：

- `科目代码`
- `科目名称`
- `余额方向`
- `科目类别`
- `期初借方余额`
- `期初贷方余额`
- `本期借方发生额`
- `本期贷方发生额`
- `期末借方余额`
- `期末贷方余额`

本任务只导入前四列作为标准科目字段；后六列作为后续标准余额表目标金额字段的语义参考，不作为标准科目余额导入。

## 交付
1. 新增标准科目 API：
   - `GET /api/v1/standard-accounts`
   - `GET /api/v1/standard-accounts/{id}`
   - `POST /api/v1/standard-accounts/import`
2. `GET /api/v1/standard-accounts` 支持筛选：
   - `is_active`
   - `account_category`
   - `balance_direction`
   - `keyword`
3. Excel 导入规则：
   - 按表头读取，不依赖固定列序。
   - 只要求能读取 `科目代码` 和 `科目名称` 中至少一个；但标准科目落库建议以 `科目代码` 为主键来源，缺代码行必须进入错误列表，不直接入库。
   - `余额方向`、`科目类别` 可为空。
   - 忽略公式语义，按 Excel 当前单元格值导入。
   - 上传文件中同一 `科目代码` 重复时阻止导入，并返回重复行号。
4. 全量同步规则：
   - 同代码已存在：更新名称、类别、方向、层级等字段。
   - 新代码：新增。
   - 数据库存在但本次 Excel 不存在：置为 `is_active=false`，不删除。
5. 识别标准科目层级：
   - 优先根据科目代码前缀推断父子级。
   - 可保守推断；无法判断父级时保留为顶级，并在结果 warnings 中说明。
   - 标记 `level`、`parent_id`、`is_leaf`。
6. 返回导入结果：
   - `created_count`
   - `updated_count`
   - `deactivated_count`
   - `error_rows`
   - `warning_rows`
7. 后端测试覆盖：
   - 首次导入。
   - 二次全量同步更新。
   - 缺失旧科目自动停用。
   - 上传文件重复代码阻止导入。
   - 余额方向/科目类别为空仍允许导入。

## 验收
- `D:\python\python.exe -m pytest backend/tests`
- `git diff --check -- backend docs`

## 完成回报要求
- 说明 API 路径和请求/响应结构。
- 说明全量同步策略已覆盖的测试。
- 贴出测试命令结果。

## 完成回报

状态：DONE
执行者：Reasonix
完成时间：2026-06-22 20:45

### 修改文件

- `backend/app/services/standard_account_service.py` — 新增：标准科目服务（Excel解析、层级推断、全量同步、查询）
- `backend/app/api/standard_accounts.py` — 新增：标准科目 API 路由（3 个端点）
- `backend/app/main.py` — 修改：注册 standard_accounts 路由
- `backend/tests/test_standard_account_import.py` — 新增：20 个测试用例
- `docs/tasks/TASK-040-standard-accounts-import-backend.md` — 修改：状态更新
- `docs/COMMAND_CENTER.md` — 修改：任务队列状态

### 完成内容

#### API 路径和请求/响应结构

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/standard-accounts` | GET | 查询列表，支持 `is_active`/`account_category`/`balance_direction`/`keyword` 筛选 |
| `/api/v1/standard-accounts/{account_id}` | GET | 查询单个标准科目详情 |
| `/api/v1/standard-accounts/import` | POST | 上传 Excel 全量同步导入 |

**GET 查询列表响应：**
```json
{
  "items": [{ "id": "uuid", "account_code": "1001", "account_name": "库存现金", ... }],
  "total": 42
}
```

**POST 导入成功响应：**
```json
{
  "message": "导入成功",
  "created_count": 5,
  "updated_count": 10,
  "deactivated_count": 2,
  "warning_rows": [...]
}
```

**POST 导入失败响应（HTTP 400）：**
```json
{
  "detail": {
    "message": "导入失败，存在数据错误",
    "errors": [{ "row_index": 3, "reason": "..." }],
    "warnings": [...]
  }
}
```

#### Excel 导入规则实现

1. **按表头读取，不依赖固定列序** — 使用 `_build_column_index()` 建立列名→列序号映射
2. **科目代码缺省阻止** — 缺代码行进入 `errors` 列表，不入库
3. **余额方向/科目类别可为空** — 空值存为 NULL
4. **忽略公式语义** — openpyxl `data_only=True` 读取计算值
5. **上传文件内重复代码阻止导入** — 全量扫描后检测重复，发现则 `created_count=0`

#### 全量同步策略

| 场景 | 行为 | 测试覆盖 |
|------|------|----------|
| 同代码已存在 | 更新名称、类别、方向、层级 | `test_second_sync_update` |
| 新代码 | 新增 | `test_first_import` |
| 旧代码不在本次 Excel | 置 `is_active=false` | `test_deactivate_missing_accounts` |
| 已停用科目重新出现 | 恢复 `is_active=true` 并更新 | `test_deactivated_reactivated_on_reimport` |
| 文件内重复代码 | 阻止导入，返回重复行号 | `test_duplicate_codes_block_import` |
| 空余额方向/科目类别 | 允许导入 | `test_empty_direction_category_allowed` |

#### 层级推断

- 根据科目代码前缀推断父子级（`infer_hierarchy`）
- 支持分隔符 `-` `.` `_`
- 无法推断父级时保留为顶级，记录 warning
- 测试覆盖：`test_basic_level_detection`、`test_multi_level_hierarchy`、`test_dotted_codes`、`test_no_parent_found`

### 验证命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest backend/tests
```

结果：

- `pytest`：**218 passed**（198 已有 + 20 新增），3 warnings（已有代码）
- `git diff --check -- backend docs`：通过（仅有 CRLF 换行符警告）

### 风险和后续

- 无阻塞项。
- TASK-041（前端标准科目管理页）现在可以开工。
- 临时上传文件保存在 `uploads/standard_accounts/` 目录，导入后自动清理。
