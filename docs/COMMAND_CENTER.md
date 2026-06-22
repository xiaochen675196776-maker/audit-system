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
| `docs/tasks/TASK-020-column-id-mapping-contract.md` | OPEN | 否，先做 | 后端导入改为列 ID / 列序号映射，兼容旧表头映射 |
| `docs/tasks/TASK-021-import-template-backend.md` | OPEN | 否，需等待 TASK-020 | 新增全局导入模板库模型、服务和 API |
| `docs/tasks/TASK-022-template-matching-preview.md` | OPEN | 否，需等待 TASK-020/021 | 预览阶段返回模板候选，支持按模板生成 v2 映射草稿 |
| `docs/tasks/TASK-023-import-template-frontend.md` | OPEN | 否，需等待 TASK-021 | 新增导入模板管理页面 |
| `docs/tasks/TASK-024-import-page-template-apply.md` | OPEN | 否，需等待 TASK-022 | 导入页显示模板候选并提交 column_mapping_v2 |
| `docs/tasks/TASK-025-template-library-final-acceptance.md` | OPEN | 否，最后执行 | 导入模板库总体验收与回归修复 |

## 推荐执行顺序

1. 当前 `TASK-019` 已验收通过。
2. 下一步执行 `TASK-020`，这是后续模板库和导入页改造的后端契约基础。
3. `TASK-021` 在 `TASK-020` 后执行，建立导入模板库后端能力。
4. `TASK-022` 在 `TASK-020` 和 `TASK-021` 后执行，负责模板匹配与预览集成。
5. `TASK-023` 可在 `TASK-021` API 初稿验收后执行，负责独立模板管理页面。
6. `TASK-024` 在 `TASK-022` 后执行，负责导入页套用模板。
7. `TASK-025` 最后执行，只做总体验收和回归修复，不新增新功能。
8. 新 UI 任务必须先阅读 `docs/UI_OPTIMIZATION_PLAN.md`。

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

## 最近一次总指挥验收

- 验收日期：2026-06-20
- 结论：`TASK-018` 通过；验收中补充了旧库运行期补列，当前无新的阻塞任务
- 验收范围：导入执行失败原因展示、序时账/辅助明细账辅助字段入库、旧 SQLite 库结构兼容、后端测试、前端构建、浏览器失败页。
- 验收结果：
  - `D:\python\python.exe -m compileall app`：通过。
  - `D:\python\python.exe -m pytest`：通过，89 passed。
  - `npm run build`：通过。
  - `git diff --check -- backend frontend docs`：通过。
  - 旧 `backend/audit.db` 启动后已补齐 `journal_entries.extra_fields` 和 `subsidiary_ledgers.extra_fields`。
  - 实际 API 验收：序时账带辅助字段 `source_type` 导入返回 `success=2`、`errors=[]`。
  - 浏览器验收：失败页显示结构化具体原因，不再只显示“导入失败”；无 Vue 运行时错误。
  - 验收截图：`frontend/ui-acceptance-shots/task-018-error-display.png`。

## 最新缺陷分派

- 分派日期：2026-06-18
- 新任务：`docs/tasks/TASK-018-import-execute-error-disclosure.md`
- 状态：已验收
- 触发问题：用户导入 74 列、12502 行的序时账类文件时，第 2 步提示“所有检查通过”，第 3 步只显示“导入请求失败 / 导入失败”，没有具体原因。
- 初步根因：
  - 前端 `normalizeError()` 会把无法识别的后端 `detail` 吞掉，只返回兜底“导入失败”。
  - 后端 `/imports/execute` 对异常使用 `detail=str(e)`，没有结构化中文错误。
  - 序时账/辅助明细账使用自定义辅助字段时，后端会生成 `extra_fields`，但 `JournalEntry` 和 `SubsidiaryLedger` 模型当前不支持该字段。
- 验收重点：失败页必须显示具体中文原因；辅助字段导入要么支持入库，要么在导入前明确阻止；不得再出现只有“导入失败”的结果页。

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
