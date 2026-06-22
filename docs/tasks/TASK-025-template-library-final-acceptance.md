# TASK-025：导入模板库总体验收与回归修复

状态：OPEN
执行者：
开始时间：
完成时间：

## 目标

对 `TASK-019` 到 `TASK-024` 的成果做最终验收和最小回归修复，确保导入模板库作为一个完整闭环可用。

本任务只修验收发现的问题，不新增新功能。

## 前置依赖

- 必须等待 `TASK-019` 到 `TASK-024` 全部完成并通过总指挥验收。
- 开始前阅读 `docs/COMMAND_CENTER.md` 和本任务。
- 开始前运行 `git status --short`。

## 允许修改范围

可以修改：

- `backend/app/`
- `backend/tests/`
- `frontend/src/`
- `docs/COMMAND_CENTER.md`
- `docs/tasks/`
- `.gitignore`

不要修改：

- 与导入模板库无关的大范围重构
- 项目技术栈
- Docker 架构

## 必须完成

1. 后端全量测试通过。
2. 前端构建通过。
3. `git diff --check` 通过。
4. 浏览器验收完整闭环：
   - 打开模板列表页。
   - 上传样本生成模板草稿。
   - 保存模板。
   - 导入页自动推荐模板。
   - 用户确认模板后执行导入。
   - 重复表头映射正确，不串列。
5. 更新 `docs/COMMAND_CENTER.md`：
   - 标记 `TASK-019` 到 `TASK-025` 的最终验收状态。
   - 记录最终验收日期、命令和结论。
6. 保留必要截图策略：
   - 默认截图只本地保留。
   - 如果提交截图，必须说明提交原因。
7. 确认真实上传文件和运行日志不会进入 Git。

## 最终验收命令

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
