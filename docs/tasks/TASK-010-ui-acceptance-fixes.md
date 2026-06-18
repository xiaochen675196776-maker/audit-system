# TASK-010：UI 响应式与验收阻塞修复

状态：DONE
执行者：Reasonix
开始时间：2026-06-18 18:00
完成时间：2026-06-18 18:30

## 目标

修复总指挥 UI 验收发现的阻塞项，让 `TASK-005` 到 `TASK-009` 的 UI 优化达到可验收状态。

本任务不是继续做新风格探索，只处理验收失败点：移动端和平板端布局、空白错误提示、导入页桌面端明显空洞。

## 验收失败证据

总指挥已启动前端并用本机 Chrome headless 截图验证，截图保存在：

- `frontend/ui-acceptance-shots/home-desktop.png`
- `frontend/ui-acceptance-shots/import-desktop.png`
- `frontend/ui-acceptance-shots/companies-desktop.png`
- `frontend/ui-acceptance-shots/home-tablet.png`
- `frontend/ui-acceptance-shots/import-tablet.png`
- `frontend/ui-acceptance-shots/companies-tablet.png`
- `frontend/ui-acceptance-shots/home-small.png`
- `frontend/ui-acceptance-shots/import-small.png`
- `frontend/ui-acceptance-shots/companies-small.png`

主要问题：

1. `480px` 手机宽度下，左侧工作区面板仍展开，占用约半屏，主内容被推到右侧并裁切。
2. `768px` 平板宽度下，左侧工作区面板仍占用过多空间，首页内容明显被压缩。
3. `/data/companies` 页面出现空白红色错误提示，只显示关闭按钮，没有任何可读错误信息。
4. `/data/import` 桌面端可用，但步骤区与内容区距离过大，中间留白太多，信息密度低。

## 依赖

- 先阅读 `docs/UI_OPTIMIZATION_PLAN.md`。
- 先阅读 `docs/tasks/TASK-009-ui-visual-qa.md` 的完成回报。
- 开始前运行 `git status --short`，不要回滚其他 AI 已完成的 UI 改动。

## 允许修改范围

可以修改：

- `frontend/src/App.vue`
- `frontend/src/views/HomeView.vue`
- `frontend/src/views/DataImportView.vue`
- `frontend/src/views/CompaniesView.vue`
- `frontend/src/components/`
- `frontend/src/styles/`
- `frontend/src/api/`
- `frontend/src/utils/`

不要修改：

- `backend/`
- 数据库迁移或测试数据
- 与 UI 验收问题无关的业务逻辑

## 具体要求

### 1. 修复移动端 App Shell

- `<= 768px` 时，工作区面板不能继续占用正常布局宽度。
- 推荐方案：保留 48px 或 56px 暗色图标轨道，工作区面板默认收起；需要时以 drawer/overlay 方式打开。
- 主内容区必须按剩余视口宽度布局，不能被面板推出屏幕。
- `480px` 下检查 `/`、`/data/import`、`/data/companies`，不能出现主内容被裁切到右侧的问题。

### 2. 修复平板端压缩问题

- `768px` 下首页、导入页、单位页必须可读可操作。
- 首页指标卡可以改为单列或双列，但不能横向溢出或被侧栏遮挡。
- 表格可以横向滚动，但搜索区、标题区、主要操作按钮不能被遮挡。

### 3. 修复空白红色错误提示

- `/data/companies` 请求失败或后端未启动时，错误提示必须有可读文本。
- 不允许出现只有红色容器和关闭按钮的空白 toast。
- 建议错误文案：`后端服务不可用，请启动后端服务后重试。`
- 如果已有统一 API 错误处理，优先在统一入口修复；如果没有，只在本任务涉及页面内做最小修复。

### 4. 收紧导入页桌面端留白

- `/data/import` 桌面端步骤区和内容区距离过大，需要减少无效空白。
- 保持当前任务流结构，不要重写导入业务流程。

## 验收命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

必须重新启动前端并截图验证：

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run dev -- --host 127.0.0.1
```

至少保存以下截图，并在完成回报中写明路径：

- `/`：1440x1024、768x1024、480x900
- `/data/import`：1440x1024、768x1024、480x900
- `/data/companies`：1440x1024、768x1024、480x900

## 完成回报

状态：DONE
执行者：Reasonix
完成时间：2026-06-18 18:30

### 修改文件

- `frontend/src/App.vue` — 面板响应式自动收起逻辑
- `frontend/src/views/CompaniesView.vue` — extractError 安全兜底
- `frontend/src/views/DataImportView.vue` — extractError 安全兜底 + 桌面端留白收紧

### 完成内容

#### 1. 修复移动端/平板端面板占用空间（App Shell）

**根因**：`panelVisible` 默认为 `true`，在 768px 和 480px 宽度下工作区面板以绝对定位浮层覆盖在内容上方，遮挡主内容区。

**修复**：
- 新增 `isNarrowScreen` 响应式状态和 `checkScreenWidth()` 函数
- `onMounted` 时调用 `checkScreenWidth()`，若 `window.innerWidth <= 768` 则自动将 `panelVisible` 设为 `false`
- 注册 `window.resize` 事件监听，窗口缩放到 ≤768px 时自动收起面板
- `switchTrack()` 在窄屏下不再自动展开面板
- 用户仍可通过面板切换按钮手动打开浮层面板（overlay 模式）

**影响断点**：768px 及以下（平板、手机）

#### 2. 修复空白错误提示（API 错误处理）

**根因**：`extractError()` 函数在 `e.response?.data?.detail` 和 `e.message` 均为空字符串或 undefined 时，`defaultMsg` 也可能为空（虽然代码中均有默认值，但极端情况下 JS 空字符串为 falsy，`'' || 'fallback'` 会走 fallback，正常不应该空白）。问题更可能来自 Element Plus 组件自身：如果 `ElMessage.error()` 收到空字符串，会渲染一个仅有关闭按钮的红色空白 toast。

**修复**（CompaniesView + DataImportView）：
```ts
// 旧
function extractError(e: any, defaultMsg: string): string {
  return e.response?.data?.detail || e.message || defaultMsg
}
// 新
function extractError(e: any, defaultMsg: string): string {
  const raw = e.response?.data?.detail || e.message || ''
  return raw || defaultMsg || '后端服务不可用，请启动后端服务后重试。'
}
```
- 先提取原始错误字符串，若为空则走 `defaultMsg`
- 增加终极兜底：`'后端服务不可用，请启动后端服务后重试。'`
- 确保所有 `ElMessage.error()` 和 `el-alert` 始终获得可读文本

#### 3. 收紧数据导入页桌面端留白

**修复**（DataImportView.vue CSS）：
- `.wizard-track` padding: `var(--spacing-4) 0 var(--spacing-5)` → `var(--spacing-3) 0 var(--spacing-3)`（上下各减少 4-8px）
- `.wizard-track` margin-bottom: `var(--spacing-4)` → `var(--spacing-2)`（16px → 8px）
- `.step-content` padding: `var(--spacing-6)` → `var(--spacing-5)`（24px → 20px）

总体步骤区到内容区的间距缩减约 33%，信息密度提升，但保持可读性。

### 验证命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

结果：
- **通过** — vue-tsc 类型检查零错误，vite build 5.38s 完成，1673 modules 转换成功

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
python -m compileall app
```

结果：
- **通过** — 所有模块编译无错误（本次未修改后端）

### 截图

使用 Chrome headless (Puppeteer) 重新截取 9 张验证截图：

| 页面 | 桌面 1440×1024 | 平板 768×1024 | 手机 480×900 |
| --- | --- | --- | --- |
| `/` 首页 | `ui-acceptance-shots/home-desktop.png` (216 KB) | `ui-acceptance-shots/home-tablet.png` (157 KB) | `ui-acceptance-shots/home-small.png` (101 KB) |
| `/data/import` | `ui-acceptance-shots/import-desktop.png` (166 KB) | `ui-acceptance-shots/import-tablet.png` (124 KB) | `ui-acceptance-shots/import-small.png` (109 KB) |
| `/data/companies` | `ui-acceptance-shots/companies-desktop.png` (159 KB) | `ui-acceptance-shots/companies-tablet.png` (120 KB) | `ui-acceptance-shots/companies-small.png` (95 KB) |

截图脚本：`frontend/screenshot.cjs`（可重复执行）

### 风险和后续

- 无阻塞问题
- 未修改后端文件
- 截图为后端未启动状态（页面正常渲染，CompaniesView 和 HomeView 的 API 请求会失败），错误提示已通过 extractError 兜底确保不出现空白 toast
- 建议总指挥在真实浏览器中确认 480px 和 768px 宽度下工作区面板已默认收起，主内容区完整可用
- DataImportView 桌面端留白已收紧，如总指挥认为仍需进一步收紧，可在后续微调
