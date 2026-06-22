# 审计系统总指挥任务看板

本文件是给其他 AI 使用的入口。用户不需要复制长命令，只需要告诉其他 AI：

```text
进入项目，先阅读 docs/COMMAND_CENTER.md，领取一个可执行任务，严格按任务文件执行，完成后按 docs/tasks/DONE_TEMPLATE.md 写回结果。
```

## 当前项目

- 项目路径：`D:\APP\Codex-项目\13、审计系统`
- 后端：Python + FastAPI + SQLAlchemy
- 前端：Vue 3 + Element Plus + TypeScript
- 数据库：开发默认 SQLite，Docker 使用 PostgreSQL
- 当前基础验证：
  - `cd frontend; npm run build` 已通过
  - `cd backend; python -m compileall app` 已通过

## 工作规则

所有 AI 必须遵守：

1. 开始前先读本文件和自己领取的任务文件。
2. 开始前运行 `git status --short`，确认已有改动，不要回滚别人改动。
3. 只修改任务文件列出的 `允许修改范围`。
4. 不要跨任务重构，不要顺手美化无关代码。
5. 如果发现任务需要修改范围外文件，先在任务文件里记录为阻塞，不要擅自扩大范围。
6. 完成后必须运行任务文件列出的验收命令。
7. 完成后按 `docs/tasks/DONE_TEMPLATE.md` 的格式，把结果写到任务文件底部的“完成回报”。

## 状态协议

任务文件顶部有状态字段：

- `OPEN`：无人领取，可以开始。
- `IN_PROGRESS`：已有 AI 正在做，其他 AI 不要领取。
- `BLOCKED`：被阻塞，需要总指挥处理。
- `DONE`：已完成，等待总指挥验收。
- `REVIEW_NEEDED`：做完但有风险，需要人工或总指挥复核。

领取任务时，将状态改为：

```text
状态：IN_PROGRESS
执行者：你的名称或工具名
开始时间：YYYY-MM-DD HH:mm
```

完成时改为 `DONE` 或 `REVIEW_NEEDED`。

## 任务队列

优先级从上到下。

| 任务 | 状态 | 是否可并行 | 说明 |
| --- | --- | --- | --- |
| `docs/tasks/TASK-001-contract-integration.md` | DONE | 已执行 | 修正前后端接口契约不一致 |
| `docs/tasks/TASK-002-backend-import-tests.md` | DONE | 已执行 | 给导入引擎补测试和后端质量检查 |
| `docs/tasks/TASK-003-frontend-ux.md` | DONE | 已执行 | 优化前端体验和错误提示 |
| `docs/tasks/TASK-004-acceptance-fixes.md` | DONE | 已验收 | 修复总指挥验收发现的问题 |
| `docs/tasks/TASK-005-ui-foundation-shell.md` | DONE | 已执行 | UI 基础、设计 tokens、App Shell |
| `docs/tasks/TASK-006-home-dashboard-redesign.md` | DONE | 已执行 | 首页审计工作台重设计 |
| `docs/tasks/TASK-007-import-workflow-redesign.md` | DONE | 已执行 | 数据导入向导重设计 |
| `docs/tasks/TASK-008-companies-table-redesign.md` | DONE | 已执行 | 被审计单位管理页重设计 |
| `docs/tasks/TASK-009-ui-visual-qa.md` | DONE | 已执行但验收未通过 | UI 视觉 QA 与收口 |
| `docs/tasks/TASK-010-ui-acceptance-fixes.md` | DONE | 已执行但验收未通过 | 修复总指挥 UI 验收阻塞项 |
| `docs/tasks/TASK-011-ui-acceptance-fixes-round2.md` | DONE | 已执行但验收未通过 | 修复单位页错误提示、接口契约和手机空状态裁切 |
| `docs/tasks/TASK-012-ui-copy-normalization.md` | DONE | 已执行但验收未通过 | 界面文案去包装化，用户可见界面不出现英文 |
| `docs/tasks/TASK-013-ui-final-acceptance-fixes.md` | DONE | 已执行但验收未通过 | 修复 11/12 验收剩余阻塞项 |
| `docs/tasks/TASK-014-visible-english-final-cleanup.md` | DONE | 已验收 | 清理最后的用户可见英文与设计计划英文 |
| `docs/tasks/TASK-015-backend-import-validation-regression.md` | DONE | 已验收 | 按新口径修复序时账借贷平衡校验并调整后端测试 |
| `docs/tasks/TASK-016-import-initial-validation-hints.md` | DONE | 已验收 | 修复导入页初始红色缺列误提示 |
| `docs/tasks/TASK-017-field-mapping-layout-overflow.md` | DONE | 已验收 | 修复字段映射页横向撑爆和右侧检查面板被挤出 |
| `docs/tasks/TASK-018-import-execute-error-disclosure.md` | DONE | 已验收 | 修复执行导入失败只显示通用文案，并处理辅助字段入库失败 |
| `docs/tasks/TASK-019-baseline-hygiene.md` | DONE | 已验收 | 基线收口、运行产物忽略、任务看板登记 |
| `docs/tasks/TASK-020-column-id-mapping-contract.md` | DONE | 已执行 | 后端导入改为列 ID / 列序号映射，兼容旧表头映射 |
| `docs/tasks/TASK-021-import-template-backend.md` | DONE | 已执行 | 新增全局导入模板库模型、服务和 API |
| `docs/tasks/TASK-022-template-matching-preview.md` | DONE | 已执行 | 预览阶段返回模板候选，支持按模板生成 v2 映射草稿 |
| `docs/tasks/TASK-023-import-template-frontend.md` | DONE | 已执行 | 新增导入模板管理页面 |
| `docs/tasks/TASK-024-import-page-template-apply.md` | DONE | 已执行 | 导入页显示模板候选并提交 column_mapping_v2 |
| `docs/tasks/TASK-025-template-library-final-acceptance.md` | DONE | 已复验 | 导入模板库总体验收（含 TASK-026/027 修复） |
| `docs/tasks/TASK-026-template-match-safety.md` | DONE | 已执行 | 修复模板匹配安全、显式套用校验和重复表头样本生成错列 |
| `docs/tasks/TASK-027-template-config-effective.md` | DONE | 已执行 | 让 parse_config 和 default_values 对测试、预览、导入真实生效 |
| `docs/tasks/TASK-028-template-library-reacceptance.md` | DONE | 已复验 | TASK-025~027 修复后的总体验收与最小回归修复 |
| `docs/tasks/TASK-029-template-execute-end-to-end.md` | DONE | 已复验 | 修复确认套用模板后的最终导入链路 |
| `docs/tasks/TASK-030-template-cancel-state-cleanup.md` | DONE | 已验收 | 修复取消套用模板后的默认值状态残留 |
| `docs/tasks/TASK-031-field-mapping-experience-backend-foundation.md` | DONE | 已执行 | 字段映射经验库后端模型、迁移和核心服务 |
| `docs/tasks/TASK-032-field-mapping-experience-preview.md` | DONE | 已执行 | 预览阶段接入字段映射经验推荐 |
| `docs/tasks/TASK-033-field-mapping-experience-save.md` | DONE | 已执行 | 执行导入成功后保存用户确认的字段映射经验 |
| `docs/tasks/TASK-034-field-mapping-experience-frontend.md` | DONE | 已执行 | 导入页展示推荐来源、记录确认并提交记忆开关 |
| `docs/tasks/TASK-035-field-mapping-experience-final-acceptance.md` | DONE | 验收未通过，见 TASK-036 | 字段映射经验库总体验收与最小回归修复 |
| `docs/tasks/TASK-036-field-mapping-experience-acceptance-fixes.md` | DONE | 复验未通过，见 TASK-037 | 修复字段映射经验库验收阻塞项 |
| `docs/tasks/TASK-037-template-source-confirmation-fixes.md` | DONE | 已执行 | 修复模板套用后的来源、置信度和确认记录 |

## 推荐执行顺序

1. 下一步执行 `TASK-037`，修复模板套用后的来源、置信度和确认记录。
2. `TASK-037` 通过总指挥复验后，字段映射经验库第一版才算收口。
3. 后续新 UI 任务必须先阅读 `docs/UI_OPTIMIZATION_PLAN.md`。
4. 新导入能力扩展必须继续使用合成样本测试，不提交 `backend/uploads` 真实业务文件。

## 导入模板库分派

- 分派日期：2026-06-22
- 目标：把导入能力升级为“全局导入模板库 + 稳定列 ID 映射 + 模板自动推荐 + 用户确认套用”。
- 范围：
  - 支持解析 + 映射模板。
  - 支持重复表头、空表头和列序号稳定映射。
  - 支持模板管理页面和导入页模板候选。
  - 不做公式、行过滤、列拆分、金额正负转换、权限或多租户。
- 测试策略：自动化测试使用合成 Excel/CSV 样本，不提交当前 `backend/uploads` 的真实业务文件。
- 验收负责人：总指挥在每个任务完成后逐项验收，再允许依赖任务继续推进。

## 字段映射经验库分派

- 分派日期：2026-06-22
- 来源方案：`D:\APP\谷歌\文件下载\审计系统字段映射经验库改造方案.md`
- 采纳结论：采纳核心方向，但按当前项目架构做收口后执行。
- 目标流程：

```text
上传文件
→ 识别完整导入模板
→ 查询字段映射经验
→ 固定关键词匹配
→ 用户确认或修改
→ 执行导入
→ 成功写入后保存映射经验
```

- 当前第一版范围：
  - 只做逐列字段映射经验。
  - 不做财务软件自动识别。
  - 不做布局指纹自动识别。
  - 不做数据清洗规则。
  - 不做科目标准化映射。
  - 不改正式业务数据表结构。
- 与现有模板库的边界：
  - `ImportTemplate` 继续负责整张表：表头行、数据起始行、编码、默认年度/期间、完整列映射。
  - `FieldMappingExperience` 只负责逐列表头到标准字段的历史确认经验。
- 优化后的工程约束：
  - `lookup_key` 不得设置唯一约束，因为冲突处理需要保留停用历史记录。
  - 歧义表头如 `借方`、`贷方`、`余额` 必须依赖上下文命中才能高置信推荐，header-only 经验不得自动填入。
  - 推荐和确认都必须使用 `column_id`，不得用表头文本当 key。
  - 经验只在导入成功写入至少一行后保存，预览阶段不得保存。
  - 第一版只保存标准字段经验，不保存辅助字段和自定义字段经验。
- 任务拆分：
  - `TASK-031`：后端模型、迁移、规范化、上下文签名、lookup key。
  - `TASK-032`：预览接口增加 `company_id` 并返回 `mapping_suggestions_v2`。
  - `TASK-033`：执行接口增加记忆开关和确认信息，成功导入后保存经验。
  - `TASK-034`：前端展示推荐来源、记录确认/修改、提交记忆开关。
  - `TASK-035`：总体验收，覆盖首次学习、再次推荐、冲突、关闭记忆、失败不保存、歧义字段、模板优先和重复表头。
  - `TASK-036`：修复总指挥验收发现的经验隔离、迁移、模板优先、前端展示和确认记录问题。
  - `TASK-037`：收口显式套用模板后的来源、置信度和确认记录。

## 导入模板库验收未通过记录

- 验收日期：2026-06-22
- 结论：`TASK-025` 不通过，必须先执行 `TASK-026`、`TASK-027`、`TASK-028`。
- 阻塞项：
  - 模板候选评分没有校验当前文件表头是否匹配模板签名，不相关同列数文件也可能得到高分候选。
  - 显式套用模板时按列位置直接生成 `column_mapping_v2`，缺少签名安全校验。
  - 样本生成模板时重复表头反查会被最后一列覆盖，可能把标准字段保存到错误列。
  - `parse_config` 和 `default_values` 只被保存/展示，没有在测试、预览和导入中生效。
- 已执行验证：
  - `D:\python\python.exe -m pytest`：通过，120 passed。
  - `D:\python\python.exe -m compileall app`：通过。
  - `npm run build`：通过。
  - `git diff --check -- backend frontend docs .gitignore`：通过。
  - 浏览器烟测：`/data/templates`、`/data/import` 可打开，无控制台错误。

## 导入模板库复验未通过记录

- 验收日期：2026-06-22
- 结论：`TASK-028` 不通过，必须先执行 `TASK-029`。
- 阻塞项：
  - 导入页最终执行导入时没有提交已确认的 `template_id`，导致模板 `parse_config` 和 `default_values` 在最后一步失效。
  - 后端 `/imports/execute` 收到 `template_id` 时缺少存在性、启用状态和数据类型一致性校验。
  - 套用模板后，前端缺失字段检查没有把模板默认年度/期间纳入判断，文件无年度/期间列时仍可能阻止导入。
  - 字段映射表仍只显示原始列名，没有按要求显示 `说明（第 26 列）` 这类列序号。
- 已执行验证：
  - `D:\python\python.exe -m pytest`：通过，130 passed。
  - `D:\python\python.exe -m compileall app`：通过。
  - `npm run build`：通过。
  - `git diff --check -- backend frontend docs .gitignore`：通过。
  - 针对性服务层复现：带标题行、模板默认年度/期间的样本，预览指定模板成功；最终导入不带模板配置失败，带模板配置成功。
  - 模板安全回归：不相关文件已被拒绝；`summary,summary` 样本生成保留第一列为 `summary`。
  - 浏览器烟测：`/data/templates`、`/data/import` 可打开，无控制台错误。

## 导入模板执行链路复验未通过记录

- 验收日期：2026-06-22
- 结论：`TASK-029` 不通过，必须先执行 `TASK-030`。
- 已通过项：
  - `D:\python\python.exe -m pytest`：通过，134 passed。
  - `D:\python\python.exe -m compileall app`：通过。
  - `npm run build`：通过。
  - `git diff --check -- backend frontend docs .gitignore`：通过。
  - 针对性接口复现：`/imports/execute` 带 `template_id + column_mapping_v2` 能按模板 `parse_config/default_values` 成功导入。
  - 针对性接口复现：不存在、停用、类型不一致、非法 UUID 模板均返回中文 400 错误。
- 阻塞项：
  - 点击“取消套用”只清空 `selectedTemplateId`，没有清空 `templateDefaultValues`。
  - 重新普通预览时没有清空旧的 `templateDefaultValues`。
  - 前端可能继续用旧模板默认年度/期间放行校验，但最终执行请求不带 `template_id`，后端不会补默认值。

## 导入模板库最终复验通过记录

- 验收日期：2026-06-22
- 结论：`TASK-029` / `TASK-030` 通过，导入模板库链路当前无阻塞。
- 验收结果：
  - `D:\python\python.exe -m pytest`：通过，134 passed。
  - `D:\python\python.exe -m compileall app`：通过。
  - `npm run build`：通过。
  - `git diff --check -- backend frontend docs .gitignore`：通过。
  - 取消套用模板会同时清空 `selectedTemplateId` 和 `templateDefaultValues`。
  - 重新普通预览和套用模板失败都会清空旧模板默认值。
  - `mappingValid` 只有在仍选中模板时才使用模板默认年度/期间补齐。
  - 浏览器烟测：`/data/import`、`/data/templates` 可打开，无控制台错误。

## 最近一次总指挥验收

- 验收日期：2026-06-22
- 结论：`TASK-036` 不通过，必须先执行 `TASK-037`。
- 验收范围：字段映射经验库验收阻塞修复，重点复核跨单位经验隔离、排序、迁移、模板优先、前端来源/置信度展示和确认记录。
- 已通过验证：
  - `D:\python\python.exe -m pytest`：通过，163 passed，3 warnings。
  - `D:\python\python.exe -m compileall app`：通过。
  - `npm run build`：通过；保留 Vite/Rollup 体积和注释警告。
  - `git diff --check -- backend frontend docs .gitignore`：通过。
  - 跨单位泄漏复现脚本：通过，`company_b {}`、`no_company {}`。
  - `recommend_from_experience()` 已限制为当前单位或全局经验，并按 `success_count` / `updated_at` 排序。
  - Alembic 迁移已真实创建 `field_mapping_experiences` 表和索引。
- 阻塞项：
  - 指定 `template_id` 预览时，后端返回 `applied_mapping_v2`，但 `mapping_suggestions_v2` 为空，模板来源没有按实际模板映射补齐。
  - 前端 `applyTemplateCandidate()` 套用模板时只更新 `field_key/status`，没有把 `suggestion_source` 设为 `template`、`suggestion_confidence` 设为 `1.0`、`original_field_key` 设为模板字段。
  - 因此套用模板后界面可能不显示“导入模板 / 100%”，执行时也可能把未修改模板推荐误记为 `user_corrected`。
- 新任务：`docs/tasks/TASK-037-template-source-confirmation-fixes.md`

## 最新缺陷分派

- 分派日期：2026-06-22
- 新任务：`docs/tasks/TASK-037-template-source-confirmation-fixes.md`
- 状态：OPEN
- 触发问题：`TASK-036` 复验发现模板套用后的来源、置信度和确认记录仍未闭环。
- 初步根因：
  - 后端指定 `template_id` 预览只返回 `applied_mapping_v2`，没有把模板映射补进 `mapping_suggestions_v2`。
  - 前端套用模板只改字段值，没有同步推荐来源、置信度和确认基准。
- 验收重点：指定模板预览必须返回 `source=template`、`confidence=1.0` 的建议；套用模板后界面显示“导入模板 / 100%”；未修改模板推荐提交 `user_confirmed`，修改后提交 `user_corrected`。

## 总指挥验收命令

总指挥在收口时至少运行：

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build

cd D:\APP\Codex-项目\13、审计系统\backend
python -m compileall app
```

如果后端任务新增了 pytest，还要运行：

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
python -m pytest
```
