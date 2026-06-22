# TASK-021：导入模板库后端模型与 API

状态：OPEN
执行者：
开始时间：
完成时间：

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

按 `docs/tasks/DONE_TEMPLATE.md` 追加到本文件底部。
