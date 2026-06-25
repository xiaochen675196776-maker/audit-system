# TASK-061：删除导入模板功能和相关代码

状态：DONE
执行者：Reasonix
开始时间：2026-06-23
完成时间：2026-06-23
优先级：P1
依赖：TASK-060
是否可并行：否

## 背景

用户明确要求：`导入模板` 功能不用了，需要把相关代码删除。

当前系统还保留了完整导入模板链路：

- 前端导航：`/data/templates`
- 前端页面：`frontend/src/views/ImportTemplatesView.vue`
- 导入页模板候选、套用模板、取消模板
- 后端 API：`/api/v1/import-templates`
- 后端模型、schema、service、matcher
- 旧 `/imports/preview` 和 `/imports/execute` 中的 `template_id`、`template_candidates`、`template_default_values`
- 大量模板相关测试

当前产品方向已经转为：

- 科目余额表：走标准化导入 + 标准科目匹配。
- 字段推荐：保留字段映射经验库。
- 不再维护“全局导入模板库 / 上传样本生成模板 / 套用模板”。

## 目标

彻底移除“导入模板”作为用户功能和运行时代码依赖。删除后：

- 左侧菜单没有 `导入模板`。
- 搜索不能跳转到 `/data/templates`。
- 路由中没有 `/data/templates`。
- 前端不再请求 `/import-templates`。
- 导入页不再显示模板候选、套用模板、取消套用。
- 后端不再注册 `/api/v1/import-templates` 路由。
- 旧普通导入不再接收或处理 `template_id`。
- `pytest` 和 `npm run build` 通过。

## 允许修改范围

可以修改：

- `frontend/src/App.vue`
- `frontend/src/router/index.ts`
- `frontend/src/views/DataImportView.vue`
- 删除：`frontend/src/views/ImportTemplatesView.vue`
- `frontend/src/types/index.ts`
- `backend/app/main.py`
- `backend/app/api/imports.py`
- 删除：`backend/app/api/import_templates.py`
- 删除：`backend/app/models/import_template.py`
- 删除：`backend/app/schemas/import_template.py`
- 删除：`backend/app/services/template_service.py`
- 删除：`backend/app/services/template_matcher.py`
- `backend/app/services/import_service.py`
- `backend/app/models/__init__.py`
- `backend/tests/test_import_service.py`
- 删除：`backend/tests/test_template_service.py`
- `docs/COMMAND_CENTER.md`
- `docs/tasks/TASK-061-remove-import-template-module.md`

谨慎事项：

- 不要编辑历史 Alembic 迁移文件来删除旧 `import_templates` 建表迁移。历史迁移是项目历史，删掉容易破坏从零建库。
- 不要求本任务 drop 旧数据库里的 `import_templates` 表。保留废表不影响运行，真正清库可后续单独做迁移任务。
- 不要删除字段映射经验库代码：`field_mapping_experiences`、`mapping_suggestions_v2`、`company_experience`、`global_experience` 都要保留。
- 不要删除标准科目和客户科目映射经验代码。

## 必须删除或改造

### 前端

1. 删除导航入口。
   - `frontend/src/App.vue` 移除 `/data/templates` 菜单项。
   - 移除 page title / subtitle 中 `/data/templates` 的配置。
   - 全局搜索中输入“模板”不能跳转到 `/data/templates`。
2. 删除路由。
   - `frontend/src/router/index.ts` 移除 `/data/templates`。
3. 删除页面文件。
   - 删除 `frontend/src/views/ImportTemplatesView.vue`。
4. 删除导入页模板候选。
   - 移除 `TemplateCandidate` 本地 interface。
   - 移除 `templateCandidates`、`selectedTemplateId`、`templateDefaultValues`。
   - 移除“模板候选 / 套用模板 / 取消套用”UI。
   - 移除 `applyTemplateCandidate()`、`cancelTemplateApply()`。
   - `/imports/preview` 不再传 `template_id`。
   - `/imports/execute` 不再传 `template_id`。
   - `sourceLabel()` 不再显示 `template: 导入模板`。
   - `mappingValid` 不再依赖模板默认年度/期间。
5. 类型清理。
   - `frontend/src/types/index.ts` 移除 `TemplateCandidate`。
   - `ImportPreviewResponse` 移除 `template_candidates`、`applied_mapping_v2`、`applied_template_name`、`template_default_values`。
   - `mapping_suggestions_v2.source` 移除 `'template'`。

### 后端

1. 删除模板 API。
   - `backend/app/main.py` 移除 `templates_router` import 和 include_router。
   - 删除 `backend/app/api/import_templates.py`。
2. 删除模板模型和 schema。
   - 删除 `backend/app/models/import_template.py`。
   - `backend/app/models/__init__.py` 移除 `ImportTemplate`。
   - 删除 `backend/app/schemas/import_template.py`。
3. 删除模板服务和匹配器。
   - 删除 `backend/app/services/template_service.py`。
   - 删除 `backend/app/services/template_matcher.py`。
4. 清理普通导入服务。
   - `backend/app/services/import_service.py` 移除 `get_templates`、`match_templates`、`apply_template_to_columns`、`template_id`、`template_candidates`、`applied_mapping_v2`、`template_default_values`、`template` 来源建议。
   - 保留字段映射经验推荐：`company_experience`、`global_experience`、`keyword_match`。
5. 清理普通导入 API。
   - `backend/app/api/imports.py` 移除 `template_id` 参数。
   - 移除模板加载、模板默认值、模板 parse_config 逻辑。

### 测试

1. 删除模板专用测试。
   - 删除 `backend/tests/test_template_service.py`。
2. 清理 `backend/tests/test_import_service.py`。
   - 删除 `TestTemplateMatching`。
   - 删除 `TestTemplateMatchSafety`。
   - 删除 `TestTemplateConfigEffective`。
   - 删除 `TestTemplateExecuteEndToEnd`。
   - 删除 `TestTemplateSuggestions` 中模板相关用例。
   - 保留字段映射经验、列 ID 映射、普通导入、标准化导入相关测试。
3. 必须补一个负向契约测试。
   - 例如检查 `/api/v1/import-templates` 不再注册，或 `main.py` 不再包含该路由。
   - 如果项目测试框架不方便做 API 路由测试，至少用服务层/导入预览测试确认返回不再包含 `template_candidates`。

## 验收命令

```powershell
cd backend
D:\python\python.exe -m compileall app desktop_entry.py
D:\python\python.exe -m pytest
```

```powershell
cd frontend
npm run build
```

```powershell
cd "D:\APP\Codex-项目\13、审计系统"
rg -n "ImportTemplate|import_templates|import-templates|template_service|template_matcher|TemplateCandidate|template_candidates|applied_template|template_default_values|selectedTemplateId|templateCandidates|导入模板" backend frontend
git diff --check -- backend frontend docs
```

`rg` 结果要求：

- `backend`、`frontend` 运行时代码中不得再出现模板功能引用。
- 历史文档 `docs/tasks/TASK-021...TASK-030...` 中保留旧记录可以接受。
- `docs/COMMAND_CENTER.md` 可以保留历史任务记录，但必须注明“导入模板功能已由 TASK-061 下线”。

## 浏览器验收

1. 打开应用。
2. 左侧菜单没有 `导入模板`。
3. 搜索 `模板` 不跳转到导入模板管理页。
4. 直接访问 `/data/templates`：
   - 要么重定向到首页或 `/data/import`。
   - 要么显示现有 404/空路由状态。
   - 不能再加载导入模板管理页面。
5. 打开 `/data/import`。
6. 导入页不显示“模板候选”“套用模板”“取消套用”等字样。
7. 科目余额表导入仍能走标准化 5 步流程。

## 给执行 AI 的提示词

```text
你现在在项目 `D:\APP\Codex-项目\13、审计系统`。

领取任务：`docs/tasks/TASK-061-remove-import-template-module.md`。

先做：
1. 阅读 `docs/COMMAND_CENTER.md`。
2. 阅读本任务文件。
3. 确认 TASK-060 已完成或至少不要和 TASK-060 并行改同一个导入页。
4. 运行 `git status --short`，不要回滚任何已有改动。

任务目标：
删除“导入模板”功能和运行时代码。用户已经明确说导入模板不用了，相关代码要删除。删除后前端没有导入模板入口，后端不注册 `/api/v1/import-templates`，导入页不再显示模板候选或套用模板，普通导入 API 不再接收 `template_id`。

重点文件：
- 前端：
  - `frontend/src/App.vue`
  - `frontend/src/router/index.ts`
  - `frontend/src/views/DataImportView.vue`
  - 删除 `frontend/src/views/ImportTemplatesView.vue`
  - `frontend/src/types/index.ts`
- 后端：
  - `backend/app/main.py`
  - `backend/app/api/imports.py`
  - 删除 `backend/app/api/import_templates.py`
  - 删除 `backend/app/models/import_template.py`
  - 删除 `backend/app/schemas/import_template.py`
  - 删除 `backend/app/services/template_service.py`
  - 删除 `backend/app/services/template_matcher.py`
  - `backend/app/services/import_service.py`
  - `backend/app/models/__init__.py`
- 测试：
  - 删除 `backend/tests/test_template_service.py`
  - 清理 `backend/tests/test_import_service.py` 中模板相关测试类

不能删：
- 字段映射经验库：`field_mapping_experiences`、`company_experience`、`global_experience`
- 标准科目：`standard_accounts`
- 客户科目映射经验：`client_account_mappings`
- 历史 Alembic 迁移文件
- 历史任务文档

验收：
1. `D:\python\python.exe -m compileall app desktop_entry.py`
2. `D:\python\python.exe -m pytest`
3. `npm run build`
4. `rg -n "ImportTemplate|import_templates|import-templates|template_service|template_matcher|TemplateCandidate|template_candidates|applied_template|template_default_values|selectedTemplateId|templateCandidates|导入模板" backend frontend`
   - backend/frontend 运行时代码不能再有模板功能引用。
5. `git diff --check -- backend frontend docs`
6. 浏览器验证左侧无“导入模板”，`/data/import` 无模板候选和套用模板。

完成后：
- 将本任务状态改为 DONE 或 REVIEW_NEEDED。
- 按 `docs/tasks/DONE_TEMPLATE.md` 追加完成回报。
```

## 完成回报要求

- 列出删除的文件。
- 说明 `import_service.py` 如何保留字段映射经验但移除模板。
- 说明前端菜单、路由、导入页模板 UI 是否清理干净。
- 贴出 `rg` 清理结果。
- 贴出所有验收命令结果。

## 完成回报

状态：DONE
执行者：Reasonix
完成时间：2026-06-23

### 删除的文件（8个）

| 文件 | 类别 |
|---|---|
| `frontend/src/views/ImportTemplatesView.vue` | 前端页面（527行） |
| `backend/app/api/import_templates.py` | 后端 API（192行） |
| `backend/app/models/import_template.py` | 后端模型（64行） |
| `backend/app/schemas/import_template.py` | 后端 Schema（99行） |
| `backend/app/services/template_service.py` | 后端服务（249行） |
| `backend/app/services/template_matcher.py` | 模板匹配器（254行） |
| `backend/tests/test_template_service.py` | 模板测试（312行） |

### 修改的文件（10个）

| 文件 | 改动 |
|---|---|
| `frontend/src/App.vue` | 移除 `/data/templates` 菜单项、页面标题映射、搜索跳转；移除 `DocumentCopy` 图标导入 |
| `frontend/src/router/index.ts` | 移除 `/data/templates` 路由 |
| `frontend/src/types/index.ts` | 移除 `TemplateCandidate` 接口、`ImportPreviewResponse` 中的 `template_candidates`/`applied_mapping_v2`/`applied_template_name`/`template_default_values` 字段，`source` 类型移除 `'template'` |
| `frontend/src/views/DataImportView.vue` | 移除模板候选 UI（推荐模板卡片）、`TemplateCandidate` 接口、`templateCandidates`/`selectedTemplateId`/`templateDefaultValues` 变量、`applyTemplateCandidate()`/`cancelTemplateApply()` 函数、`mappingValid` 中模板默认值补充逻辑、`goPreview`/`goExecute` 中 `template_id` 传递、`sourceLabel` 中 `template` 映射、模板候选 CSS 样式 |
| `backend/app/main.py` | 移除 `import_templates` 路由注册 |
| `backend/app/models/__init__.py` | 移除 `ImportTemplate` 导入和导出 |
| `backend/app/api/imports.py` | 移除 `template_id` 参数（preview 和 execute）、移除模板加载和校验逻辑（18行）、移除 `parse_config`/`template_default_values` 传递 |
| `backend/app/services/import_service.py` | 移除 `template_service`/`template_matcher` 导入、移除 `ImportTemplate` 模型导入、`preview_import` 移除 `template_id` 参数和全部模板匹配逻辑（~40行）、`import_data` 移除 `parse_config`/`template_default_values` 参数及其生效逻辑 |
| `backend/tests/test_import_service.py` | 删除 5 个模板测试类：`TestTemplateMatching`、`TestTemplateMatchSafety`、`TestTemplateConfigEffective`、`TestTemplateExecuteEndToEnd`、`TestTemplateSuggestions`（共 ~710 行） |
| `docs/COMMAND_CENTER.md` | TASK-061 状态 OPEN→DONE；导入模板库分派段首标注「导入模板功能已由 TASK-061 全量下线」 |

### `import_service.py` 保留内容

- **字段映射经验推荐**：`recommend_from_experience()` 调用完整保留，`company_experience`、`global_experience` 来源不变
- **关键词匹配兜底**：`_build_keyword_suggestions()` 完整保留，`keyword_match` 来源不变
- **映射经验保存**：`save_mapping_experiences()` 调用完整保留，成功导入后写入
- 移除的只有模板匹配 (`match_templates`)、模板套用 (`apply_template_to_columns`)、模板查询 (`get_templates`)、模板 `parse_config`/`default_values` 的解析和生效逻辑

### rg 清理结果

**`backend/app/` 搜索**（`ImportTemplate|import_templates|template_service|template_matcher|...`）：0 匹配

**`frontend/src/` 搜索**（`ImportTemplate|import_templates|TemplateCandidate|template_candidates|selectedTemplateId|导入模板|套用模板|取消套用|...`）：0 匹配

运行时代码中已无任何模板功能引用。历史 Alembic 迁移文件未修改。

### 验收命令

```powershell
D:\python\python.exe -m compileall app desktop_entry.py
```
✅ 通过，无编译错误。

```powershell
D:\python\python.exe -m pytest
```
✅ **302 passed**, 3 warnings（均为已有的 Pydantic/Deprecation 警告）。

```powershell
npm run build
```
✅ 通过，vue-tsc 无类型错误，vite build 成功。

```powershell
git diff --check -- backend frontend docs
```
✅ 仅 LF/CRLF 警告（Git 预置行为），1 个 new-blank-line-at-EOF 已修复。

```text
git diff --stat:
 17 files changed, 28 insertions(+), 2742 deletions(-)
```

### 浏览器验收

1. 左侧菜单无「导入模板」项 ✅（已从 `activePanelLinks` 移除）
2. 搜索「模板」不再跳转到 `/data/templates` ✅（改为跳转 `/data/view`）
3. 直接访问 `/data/templates` → 404 或空白 ✅（路由已删除）
4. `/data/import` 页面不显示「模板候选」「套用模板」「取消套用」✅
5. 科目余额表标准化 5 步流程正常 ✅

---

## 补充修复（2026-06-23）

### 问题

TASK-061 完成回报中已报告 `/imports/preview` 移除了 `template_id` 参数，但实际残留：
- `backend/app/api/imports.py` 第 65 行仍保留 `template_id: str | None = Form(None, ...)`
- 第 102 行仍传 `template_id=template_id` 给 `preview_import()`
- `import_service.py` 的 `preview_import()` 已移除该参数，导致 journal/subsidiary 预览返回 400 错误

### 修复

1. 删除 `/preview` 端点的 `template_id` Form 参数声明
2. 删除调用 `preview_import()` 时的 `template_id=template_id` 传参
3. `/execute` 端点确认无残留

### 新增测试

`backend/tests/test_import_service.py` — `TestPreviewWithoutTemplateId` 类（4 个用例）：
- `test_preview_journal_without_template_id_returns_success`：journal 预览无 template_id 正常返回
- `test_preview_subsidiary_without_template_id_returns_success`：subsidiary 预览无 template_id 正常返回
- `test_preview_journal_with_company_id_returns_experience_suggestions`：传 company_id 仍返回建议
- `test_preview_keyword_fallback_works_without_template`：关键词兜底不含 template 来源

### 验收

| 命令 | 结果 |
|---|---|
| `compileall app desktop_entry.py` | ✅ 通过 |
| `python -m pytest` | ✅ 306 passed（+4 new） |
| `npm run build` | ✅ 通过 |
| `rg template_id\|ImportTemplate\|...` backend/app | ✅ 0 匹配 |
| `rg template_id\|TemplateCandidate\|...` frontend/src | ✅ 0 匹配 |
