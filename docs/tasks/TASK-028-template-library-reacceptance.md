# TASK-028：导入模板库修复后复验

状态：DONE
执行者：Reasonix
开始时间：2026-06-22 16:00
完成时间：2026-06-22 16:15

## 目标

对 `TASK-026` 和 `TASK-027` 的修复做总体验收，确认导入模板库不会错套模板、重复表头不串列、模板解析配置和默认值真实生效。

本任务只做验收和最小回归修复，不新增新功能。

## 前置依赖

- 必须等待 `TASK-026` 完成并通过总指挥验收。
- 必须等待 `TASK-027` 完成并通过总指挥验收。
- 开始前必须阅读 `docs/COMMAND_CENTER.md` 和本任务。
- 开始前运行 `git status --short`。

## 允许修改范围

可以修改：

- `backend/app/`
- `backend/tests/`
- `frontend/src/`
- `docs/COMMAND_CENTER.md`
- `docs/tasks/`

不要修改：

- 与导入模板库无关的大范围重构
- 项目技术栈
- Docker 架构

## 必须验收

### 后端验收

1. 完全不相关的同列数文件不能被推荐为高分模板。
2. 显式指定不匹配模板时，不能生成完整 `column_mapping_v2` 并继续导入。
3. `summary,summary` 重复表头样本生成模板时，第一列 `summary` 不被第二列覆盖。
4. 模板 `parse_config.header_row/data_start_row` 对预览、测试、导入都生效。
5. 模板 `default_values.fiscal_year/period` 对导入生效。
6. 用户手动年度/期间优先于模板默认值。

### 前端验收

1. `/data/templates` 可打开，无 Vue 运行时错误。
2. 模板测试能展示不匹配文件的中文失败原因。
3. `/data/import` 上传文件后，只展示安全候选；低分或不匹配模板不能误导用户点击套用。
4. 套用模板后，重复表头展示列序号，执行导入提交正确 `column_mapping_v2`。
5. 如果模板默认值补齐年度/期间，导入检查面板不误报缺失。

## 最终验收命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest
```

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m compileall app
```

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

```powershell
cd D:\APP\Codex-项目\13、审计系统
git diff --check -- backend frontend docs .gitignore
```

## 浏览器验收

启动后端和前端，打开：

```text
http://127.0.0.1:5173/data/templates
http://127.0.0.1:5173/data/import
```

至少保留本地验收截图，不默认提交截图。

## 完成回报

按 `docs/tasks/DONE_TEMPLATE.md` 追加到本文件底部。
