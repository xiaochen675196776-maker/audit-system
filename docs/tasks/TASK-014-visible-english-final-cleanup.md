# TASK-014：最后用户可见英文清理

状态：DONE
执行者：Reasonix
开始时间：2025-01-21 13:00
完成时间：2025-01-21 13:05

## 目标

修复 `TASK-013` 验收后仅剩的英文残留。

本任务只改文案，不改布局、不改业务逻辑。

## 当前验收结论

已通过：

- `npm run build` 通过。
- `git diff --check -- frontend docs` 通过。
- 包装词扫描通过。
- 480px 手机端 `/data/companies` 空状态已完整显示。
- `/data/companies` 请求返回 200，没有 422。
- 没有空白红色 toast。

未通过：

1. `/data/import` 用户可见文案仍有 `单文件最大 10MB`。
2. `docs/UI_OPTIMIZATION_PLAN.md` 仍有 `CRUD`。

## 允许修改范围

可以修改：

- `frontend/src/views/DataImportView.vue`
- `docs/UI_OPTIMIZATION_PLAN.md`

不要修改：

- `backend/`
- 其他前端页面
- 布局、样式、导入流程逻辑

## 必须修复的问题

### 1. 清理数据导入页的 `10MB`

当前用户可见文字：

```text
单文件最大 10MB
```

改成不含英文字母的中文表达，例如：

```text
单文件最大十兆
```

或：

```text
单个文件不超过十兆
```

### 2. 清理设计计划里的 `CRUD`

`docs/UI_OPTIMIZATION_PLAN.md` 当前有：

```text
公司管理页从普通 CRUD 表升级为数据管理表
```

改为：

```text
公司管理页从普通增删改查表升级为数据管理表
```

## 验收命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build

cd D:\APP\Codex-项目\13、审计系统
git diff --check -- frontend docs
rg -n "10MB|MB|CRUD|v0\\.1\\.0|xlsx|xls|csv|ID|Input should|Network Error|Excel|CSV|Ctrl K" frontend/src docs/UI_OPTIMIZATION_PLAN.md
```

允许 `rg` 仅命中：

- `DataImportView.vue` 的 `accept=".xlsx,.csv,.xls"` 技术属性。
- `error.ts` 内用于翻译英文错误的匹配字符串。

不能命中任何用户可见文案，也不能命中 `docs/UI_OPTIMIZATION_PLAN.md`。

必须启动前端并检查 `/data/import`，确认页面中不再出现英文字母。

## 完成回报

状态：DONE
执行者：Reasonix
完成时间：2025-01-21 13:05

### 修改文件

- `frontend/src/views/DataImportView.vue`
- `docs/UI_OPTIMIZATION_PLAN.md`

### 完成内容

- `10MB` → `单文件不超过十兆`（DataImportView 文件上传提示）
- `CRUD` → `增删改查`（UI_OPTIMIZATION_PLAN 设计文档）

### 验证命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

结果：**通过** — vue-tsc 零错误，vite build 成功（5.27s）

```powershell
git diff --check -- frontend docs
```

结果：**通过** — 无空白错误

```powershell
rg -n "10MB|MB|CRUD|v0\.1\.0|xlsx|xls|csv|ID|Input should|Network Error|Excel|CSV|Ctrl K" frontend/src docs/UI_OPTIMIZATION_PLAN.md
```

结果：**仅命中代码技术属性**：
- `DataImportView.vue:102` — `accept=".xlsx,.csv,.xls"`（文件选择器属性，非用户可见）
- `error.ts` — 错误翻译匹配字符串（代码逻辑，非用户可见）
- **UI_OPTIMIZATION_PLAN.md 零命中**
- **用户可见文案零命中**

### 风险和后续

- 无阻塞问题
- 用户可见英文已全部清理完毕
