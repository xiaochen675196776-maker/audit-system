# TASK-025：导入模板库总体验收与回归修复

状态：REVIEW_NEEDED
执行者：Reasonix
开始时间：2026-06-23 14:15
完成时间：2026-06-23 14:30

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

---

状态：REVIEW_NEEDED
执行者：Codex
完成时间：2026-06-22 12:30

### 总指挥验收结论

不通过，需要后续修复。

### 阻塞问题

1. 模板匹配没有以当前文件表头为硬门槛。完全不相关的 9 列文件也能被序时账模板判为候选，分数可达 63，并生成完整字段映射，存在错导数据风险。
2. 显式套用模板时按 `col_001`、`col_002` 位置直接套用，没有校验当前文件表头是否匹配模板签名。
3. 从样本生成模板时使用 `{header: column_id}` 反查，同名表头会保留最后一列；`summary,summary` 样本中第二个 `summary` 覆盖了第一个。
4. `parse_config` 和 `default_values` 目前只被保存/展示，没有参与模板测试、预览或导入。

### 后续任务

- `TASK-026`：修复模板匹配安全和重复表头纠偏。
- `TASK-027`：让模板解析配置和默认值真实生效。
- `TASK-028`：修复后重新总体验收。

### 已执行验收命令

- `D:\python\python.exe -m pytest`：通过，120 passed，1 个 Pydantic 预存警告。
- `D:\python\python.exe -m compileall app`：通过。
- `npm run build`：通过，存在预存 Vite 大 chunk / VueUse 注释警告。
- `git diff --check -- backend frontend docs .gitignore`：通过，仅 CRLF 提示。
- 浏览器烟测：`/data/templates` 和 `/data/import` 可打开，未捕获控制台错误。
