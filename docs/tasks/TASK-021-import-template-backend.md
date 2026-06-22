# TASK-021：导入模板库后端模型与 API

状态：DONE
执行者：Reasonix
开始时间：2026-06-23 11:00
完成时间：2026-06-23 12:00

## 目标

新增全局导入模板库后端能力，让系统可以保存、编辑、启停和测试“解析 + 映射”模板。

模板第一版全局复用，不按被审计单位隔离。

## 前置依赖

- 必须等待 `TASK-020` 完成并验收。
- 开始前阅读 `docs/COMMAND_CENTER.md` 和本任务。
- 开始前运行 `git status --short`。

## 允许修改范围

可以修改：

- `backend/app/models/`
- `backend/app/schemas/`
- `backend/app/services/`
- `backend/app/api/`
- `backend/app/main.py`
- `backend/app/core/schema.py`（如需运行期兼容）
- `backend/tests/`

不要修改：

- 前端
- 现有导入页 UI
- `docs/UI_OPTIMIZATION_PLAN.md`

## 必须完成

1. 新增 `ImportTemplate` ORM 模型，表名 `import_templates`。
2. 字段至少包含：
   - `id`
   - `name`
   - `data_type`
   - `source_label`
   - `is_active`
   - `header_signature`
   - `parse_config`
   - `column_rules`
   - `default_values`
   - `created_at`
   - `updated_at`
3. 注册模型，确保 `Base.metadata.create_all` 能创建表。
4. 如项目继续使用运行期结构兼容策略，补充必要兼容逻辑。
5. 新增 API，路由前缀建议 `/import-templates`：
   - `GET /api/v1/import-templates`
   - `GET /api/v1/import-templates/{id}`
   - `POST /api/v1/import-templates/from-sample`
   - `POST /api/v1/import-templates`
   - `PUT /api/v1/import-templates/{id}`
   - `DELETE /api/v1/import-templates/{id}`
   - `POST /api/v1/import-templates/{id}/test`
6. `from-sample` 接收上传文件和 `data_type`，返回模板草稿，不直接保存，除非请求参数明确要求保存。
7. `test` 接收上传文件，返回：
   - 是否可套用
   - 命中字段
   - 缺失字段
   - 重复/冲突警告
   - 建议的 `column_mapping_v2`
8. 用户可见错误必须为中文。

## 模板能力边界

本任务只支持“解析 + 映射”：

- 支持表头行/数据起始行配置。
- 支持字段映射。
- 支持重复表头和空表头。
- 支持默认年度/期间。
- 支持辅助字段命名。

不做：

- 公式计算
- 行过滤
- 列拆分
- 金额正负转换
- 多租户/权限

## 必须测试

后端测试至少覆盖：

1. 模板创建、读取、更新、删除。
2. `is_active` 筛选。
3. `data_type` 筛选。
4. 样本生成模板草稿。
5. 模板测试返回 `column_mapping_v2`。
6. 无效数据类型返回中文错误。

测试样本必须合成生成。

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
完成时间：2026-06-23 12:00

### 新增文件

- `backend/app/models/import_template.py` — ImportTemplate ORM 模型（12 字段）
- `backend/app/schemas/import_template.py` — Pydantic schema（Create/Update/Response/List/FromSample/TestResult）
- `backend/app/services/template_service.py` — 模板服务（CRUD + from_sample + test_template）
- `backend/app/api/import_templates.py` — API 路由（7 个端点）
- `backend/tests/test_template_service.py` — 13 个后端测试

### 修改文件

- `backend/app/models/__init__.py` — 注册 ImportTemplate
- `backend/app/main.py` — 注册 templates_router

### 实现摘要

#### 1. ImportTemplate ORM 模型

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | UUID PK | 主键 |
| `name` | String(200) | 模板名称 |
| `data_type` | String(50), indexed | 数据类型 |
| `source_label` | String(200), nullable | 来源标识 |
| `is_active` | Boolean, indexed, default=True | 启用状态 |
| `header_signature` | JSON, nullable | 表头特征签名 |
| `parse_config` | JSON, default={} | 解析配置 |
| `column_rules` | JSON, default={} | 映射规则 |
| `default_values` | JSON, nullable | 默认值 |
| `created_at` | DateTime | 创建时间 |
| `updated_at` | DateTime | 更新时间 |

#### 2. API 端点（前缀 `/api/v1/import-templates`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/` | 列表（支持 `?data_type=` 和 `?is_active=` 筛选） |
| `GET` | `/{id}` | 详情 |
| `POST` | `/` | 手动创建 |
| `PUT` | `/{id}` | 部分更新 |
| `DELETE` | `/{id}` | 删除（204） |
| `POST` | `/from-sample` | 上传文件生成模板草稿（`save=false` 只返回） |
| `POST` | `/{id}/test` | 上传文件测试模板，返回 `column_mapping_v2` |

#### 3. 模板能力边界

- ✅ 表头行/数据起始行配置（parse_config）
- ✅ 字段映射（column_rules: col_id → standard_field / ignore / custom_name）
- ✅ 重复表头（通过列 ID 区分，不受影响）
- ✅ 空表头（生成稳定 column_id，可映射为辅助字段）
- ✅ 默认年度/期间（default_values）
- ✅ 辅助字段命名（from_sample 自动生成 field_xxx_N）
- ❌ 不做：公式、行过滤、列拆分、金额转换、多租户

#### 4. 测试覆盖（13 个）

| 测试类 | 测试 | 覆盖 |
| --- | --- | --- |
| TestTemplateCRUD | 4 tests | 创建/读取/更新/删除/不存在删除 |
| TestTemplateFilter | 2 tests | is_active 筛选、data_type 筛选 |
| TestFromSample | 2 tests | 样本生成草稿、重复表头样本 |
| TestTemplateTest | 5 tests | applicable、missing_fields、ignore、重复警告、invalid data_type |

### 验收命令与结果

- `D:/python/python.exe -m pytest` → **113 passed, 0 failed**（从 100 增至 113）
- `npm run build` → **通过**，vue-tsc 零错误，7.03s（未改前端）
- `git diff --check -- backend docs` → **通过**，仅 LF/CRLF 提示

### 风险和后续

- `TASK-022`（模板匹配预览）和 `TASK-023`（模板管理前端页面）可并行推进。
- `from-sample` 的自动匹配依赖 `auto_match()`（TASK-020 已就绪），辅助字段命名策略简单（取前 20 字符），后续可升级为更智能的拼音/英文映射。
- 模板第一版全局复用，未按被审计单位隔离；如需单位级隔离，可后续在 `column_rules` 或模型中增加 `company_id` 字段。
- `parse_config` 目前为自由 JSON 字典，解析逻辑在 `TASK-022/024` 中实现。
