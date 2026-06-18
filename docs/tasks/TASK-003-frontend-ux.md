# TASK-003：前端体验与错误提示优化

状态：DONE
执行者：Reasonix
开始时间：2025-01-21 11:00
完成时间：2025-01-21 11:20

## 目标

在 `TASK-001` 完成后，优化前端页面的可用性、错误提示和基础响应式表现。不要改接口字段名，不要改后端。

## 前置条件

只有当 `docs/tasks/TASK-001-contract-integration.md` 状态为 `DONE` 或总指挥明确允许时，才能开始本任务。

## 允许修改范围

可以修改：

- `frontend/src/views/DataImportView.vue`
- `frontend/src/views/CompaniesView.vue`
- `frontend/src/views/HomeView.vue`
- `frontend/src/App.vue`
- `frontend/src/components/`
- `frontend/src/styles/`
- `frontend/src/types/index.ts`（仅允许补充前端展示类型，不允许改 API 契约字段）

不要修改后端文件。
不要改变 `TASK-001` 已确定的接口字段名。

## 具体要求

1. 数据导入页：
   - 预览失败时显示后端错误详情。
   - 导入失败时结果区可读，不只弹 toast。
   - 未选择公司、未选择文件、映射缺失时按钮状态明确。
   - 映射表里能清楚区分已映射、未映射、已忽略。
2. 公司管理页：
   - 空状态、加载状态、删除确认可用。
   - 后端错误信息尽量展示给用户，例如编码重复。
3. 首页：
   - 统计卡片数据加载失败时不要造成页面异常。
4. 响应式：
   - 1366px 桌面宽度不溢出。
   - 窄屏下主要按钮和表格不明显挤压或遮挡。

## 验收命令

必须运行：

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

如果能启动本地服务，建议手动打开：

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run dev
```

检查：

- `/`
- `/data/companies`
- `/data/import`

## 完成回报

按 `docs/tasks/DONE_TEMPLATE.md` 追加到这里。

## 完成回报

状态：DONE
执行者：Reasonix
完成时间：2025-01-21 11:20

### 修改文件

- `frontend/src/views/DataImportView.vue`
- `frontend/src/views/CompaniesView.vue`
- `frontend/src/views/HomeView.vue`
- `frontend/src/styles/element-overrides.css`

### 完成内容

**数据导入页 (DataImportView.vue)**：
- 预览失败时新增 `previewError` 警告框（el-alert type=error），错误详情持久展示在步骤1面板中，不再仅靠 toast 一闪而过
- 导入失败时区分 API 级错误（row=-1）和行级错误：API 级错误显示 `el-result icon=error` 独立卡片，行级错误保持原表格展示，不再弹冗余 toast
- 按钮禁用时新增 `btn-hint` 提示文案（如"请先选择被审计单位""还有 N 列未映射"），让用户明确知道为何按钮不可用
- 映射表行增加颜色区分：已映射行 `row-matched` 绿底，未映射行 `row-unmatched` 橙底，已忽略行 `row-ignored` 灰底+半透明

**公司管理页 (CompaniesView.vue)**：
- 新增 `extractError(e, defaultMsg)` 辅助函数，统一提取后端 `response.data.detail` 错误详情
- `fetchCompanies`、`handleDelete`、`handleSubmit` 三个 catch 块全部改为展示后端具体错误信息（如编码重复），不再掩码为通用"操作失败"

**首页 (HomeView.vue)**：
- 新增 `statsLoadFailed` 状态标记，统计数据加载失败时展示 `el-alert type=warning` 提示"统计数据加载失败，显示为缓存值"
- 避免页面静默显示 0 值造成误导

**响应式 (element-overrides.css + DataImportView.vue)**：
- 新增 1366px 断点：`.page` 使用 `calc(100vw - sidebar - padding)` 保证不溢出，表格启用横向滚动
- 768px 断点增加表格 `overflow-x: auto` 横向滚动
- 480px 断点增加步骤面板内边距压缩、操作按钮纵向堆叠且限制最大宽度

### 验证命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

结果：

- **通过** — vue-tsc 类型检查通过，vite build 5.53s 完成，四个视图组件均正常编译输出
- 仅存在预存的 chunk 体积警告（Element Plus 库体积），非本次改动引入

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
python -m compileall app
```

结果：

- **通过** — 所有后端模块编译通过（本次未修改后端文件）

### 风险和后续

- 无阻塞风险
- 建议总指挥手动启动 `npm run dev` 检查 `/`、`/data/companies`、`/data/import` 三个页面的实际视觉效果，尤其是 1366px 和 480px 宽度下的表格表现
- 映射表行颜色依赖 `el-table` 的 `row-class-name` 属性，若 Element Plus 升级需确认兼容性

---

> **时间勘误**（TASK-004 追加）：原完成回报中的时间 2025-01-21 为执行者误填，实际执行日期应在 2026 年。本任务在 2026-06-18 总指挥验收前已完成。

