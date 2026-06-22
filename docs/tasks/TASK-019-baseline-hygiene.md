# TASK-019：基线收口与仓库卫生

状态：DONE
执行者：Codex
开始时间：2026-06-22 00:00
完成时间：2026-06-22 00:00

## 目标

把 `TASK-018` 已验收成果收口为可继续开发的基线，并清理运行产物噪声，避免后续 AI 在真实上传文件、服务日志、验收截图中迷失。

本任务不实现导入模板库功能，只负责基线、看板和仓库卫生。

## 前置依赖

- `TASK-018` 已通过总指挥验收。
- 开始前必须阅读 `docs/COMMAND_CENTER.md`。
- 开始前必须运行 `git status --short`，确认已有改动，不要回滚别人改动。

## 允许修改范围

可以修改：

- `.gitignore`
- `docs/COMMAND_CENTER.md`
- `docs/tasks/`
- `backend/app/api/imports.py`
- `backend/app/main.py`
- `backend/app/models/journal_entry.py`
- `backend/app/models/subsidiary_ledger.py`
- `backend/app/core/schema.py`
- `backend/tests/test_import_service.py`
- `backend/tests/test_runtime_schema.py`
- `frontend/src/utils/error.ts`

不要修改：

- `frontend/src/views/`
- `backend/app/services/`
- 与 `TASK-018` 收口无关的业务代码
- 当前真实上传样本内容

## 必须完成

1. 保留 `TASK-018` 已验收源码、测试和文档成果。
2. 确认 `.gitignore` 至少覆盖：
   - `backend/uploads/import_*`
   - `*.out.log`
   - `*.err.log`
   - `frontend/vite-ui-acceptance.log`
   - `frontend/ui-acceptance-shots/*`
3. 保留 `.gitkeep` 规则，避免空目录丢失。
4. 在 `docs/COMMAND_CENTER.md` 中登记 `TASK-019` 到 `TASK-025`。
5. 明确截图策略：
   - 真实验收截图可以本地保留。
   - 默认不提交 `frontend/ui-acceptance-shots/` 下的截图。
   - 若某张截图必须作为任务证据提交，需要在对应任务完成回报中说明原因。
6. 不删除用户本地真实上传文件和日志；只通过忽略规则避免误提交。

## 验收命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest
```

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

```powershell
cd D:\APP\Codex-项目\13、审计系统
git diff --check -- backend frontend docs .gitignore
```

## 完成回报

按 `docs/tasks/DONE_TEMPLATE.md` 追加到本文件底部。

---

状态：DONE
执行者：Codex
完成时间：2026-06-22 00:00

### 修改摘要

- 补充 `.gitignore`，忽略 `backend/uploads/import_*`、`*.out.log`、`*.err.log`、`frontend/vite-ui-acceptance.log`、`frontend/ui-acceptance-shots/*` 等运行产物。
- 新增 `TASK-020` 到 `TASK-025` 任务文件，并将 `TASK-019` 本身作为基线收口任务保留。
- 更新 `docs/COMMAND_CENTER.md`，登记导入模板库任务队列、依赖顺序、范围边界和测试策略。
- 明确截图默认只本地保留；如需提交截图，必须在对应任务完成回报中说明原因。

### 验收命令与结果

- `D:\python\python.exe -m pytest`：通过，89 passed，1 个 Pydantic v2 预存弃用警告。
- `npm run build`：通过，存在预存 Vite 大 chunk 警告和 VueUse PURE 注释警告。
- `git diff --check -- backend frontend docs .gitignore`：通过，仅有 CRLF 转换提示。

### 风险和后续

- `TASK-020` 是下一步，其他 AI 应先完成列 ID / 映射契约 v2，再推进模板库后端和前端页面。
- 当前工作区仍包含 `TASK-018` 已验收但未提交的源码、测试和文档改动；后续 AI 不得回滚。
