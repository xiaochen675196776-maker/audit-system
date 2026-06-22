# TASK-024：导入页套用模板

状态：OPEN
执行者：
开始时间：
完成时间：

## 目标

把现有三步导入向导接入模板候选和 v2 映射。用户上传文件后能看到系统推荐的模板，确认后套用模板映射；无模板时仍能手动映射。

## 前置依赖

- 必须等待 `TASK-020` 完成并验收。
- 必须等待 `TASK-022` 完成并验收。
- 建议等待 `TASK-023` 完成并验收，以便类型和 API 调用保持一致。
- 开始前阅读 `docs/COMMAND_CENTER.md` 和本任务。
- 开始前运行 `git status --short`。

## 允许修改范围

可以修改：

- `frontend/src/views/DataImportView.vue`
- `frontend/src/types/`
- `frontend/src/utils/error.ts`
- `frontend/src/api/`

不要修改：

- 后端
- `frontend/src/views/ImportTemplatesView.vue`
- 首页和被审计单位页
- `docs/UI_OPTIMIZATION_PLAN.md`

## 必须完成

1. 预览后显示模板候选：
   - 模板名称
   - 匹配分数
   - 命中字段数
   - 缺失字段
   - 冲突/警告
2. 默认推荐最高分模板，但必须用户确认后才套用。
3. 用户可以：
   - 确认套用推荐模板
   - 改选其他模板
   - 取消模板，继续手动映射
   - 手动覆盖模板映射结果
4. 映射表内部使用 `column_id`。
5. 展示列名时附带列序号，例如：

```text
说明（第 26 列）
```

6. 执行导入优先提交 `column_mapping_v2`。
7. 保留旧无模板路径：如果后端没有返回 `template_candidates` 或 `columns`，页面仍能按旧逻辑手动映射。
8. 不能回滚已验收的字段映射布局修复：
   - `teleported=true`
   - `popper-class="map-select-popper"`
   - 局部横向滚动
   - 窄屏布局

## 必须验收的场景

1. 无模板：上传文件后手动映射仍可执行。
2. 有模板：显示候选，确认套用后字段自动映射。
3. 重复表头：同名列展示列序号，映射不会串列。
4. 模板警告：缺字段或冲突时页面显示中文原因。
5. 执行请求中包含 `column_mapping_v2`。

## 验收命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

```powershell
cd D:\APP\Codex-项目\13、审计系统
git diff --check -- frontend docs
```

## 浏览器验收

启动前后端后打开：

```text
http://127.0.0.1:5173/data/import
```

至少检查：

1. 桌面宽度字段映射不横向撑爆。
2. 480px 窄屏不阻断核心操作。
3. 模板候选和警告文案都是中文。
4. 控制台没有新的 Vue 运行时错误。

## 完成回报

按 `docs/tasks/DONE_TEMPLATE.md` 追加到本文件底部。
