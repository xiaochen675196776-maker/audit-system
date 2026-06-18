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
| `docs/tasks/TASK-014-visible-english-final-cleanup.md` | OPEN | 先执行 | 清理最后的用户可见英文与设计计划英文 |

## 推荐执行顺序

1. 当前优先执行 `TASK-014`，清理最后的用户可见英文和设计计划英文。
2. `TASK-014` 通过前，不再领取新的 UI 美化任务。
3. 新 UI 任务必须先阅读 `docs/UI_OPTIMIZATION_PLAN.md`。

## 最近一次总指挥验收

- 验收日期：2026-06-18
- 结论：不通过，已发布 `TASK-014` 修复最后阻塞项
- 验收范围：`TASK-013`，重点复核 480px 单位页空状态、用户可见英文、接口请求和空白错误提示。
- 验收结果：
  - `npm run build`：通过
  - `git diff --check`：通过
  - 包装词扫描：通过，`审计指挥舱`、`COMMAND CENTER`、`导入流水线`、`风险队列` 等零命中。
  - 单位页接口契约：通过，请求为 `page_size=100`，浏览器网络记录返回 200，不再出现 422。
  - 空白错误提示：通过，本轮没有空白红色 toast。
  - 480px 单位页空状态：通过，独立空状态容器和按钮完整显示，按钮右侧未超出 480px 可视区。
  - 用户可见英文：未通过，数据导入页仍显示 `单文件最大 10MB`。
  - 设计计划文档：未通过，`docs/UI_OPTIMIZATION_PLAN.md` 仍有 `CRUD`。

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
