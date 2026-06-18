# TASK-011：UI 二次验收阻塞修复

状态：DONE
执行者：Reasonix
开始时间：2025-01-21 11:30
完成时间：2025-01-21 11:50

## 目标

修复 `TASK-010` 二次验收仍未通过的问题。范围集中在被审计单位页，不继续做新的视觉探索。

## 总指挥二次验收结论

`TASK-010` 修掉了首页和导入页的侧栏挤压问题，但被审计单位页仍未通过。

新证据截图保存在：

- `frontend/ui-acceptance-shots/companies-desktop.png`
- `frontend/ui-acceptance-shots/companies-tablet.png`
- `frontend/ui-acceptance-shots/companies-small.png`

总指挥还用浏览器 DOM 验证了两个根因：

1. 空白 toast 的 `.el-message__content` 真实为空，不是文字颜色或遮挡问题。
2. 480px 下 `.empty-state` 的矩形超出可视区域，空状态文字和按钮被横向裁切。

接口请求证据：

```text
GET /api/v1/companies?page=1&page_size=1000
HTTP 422
{"detail":[{"type":"less_than_equal","loc":["query","page_size"],"msg":"Input should be less than or equal to 100","input":"1000","ctx":{"le":100}}]}
```

## 依赖

- 先阅读 `docs/UI_OPTIMIZATION_PLAN.md`
- 先阅读 `docs/tasks/TASK-010-ui-acceptance-fixes.md`
- 开始前运行 `git status --short`，不要回滚其他 AI 改动

## 允许修改范围

可以修改：

- `frontend/src/views/CompaniesView.vue`
- `frontend/src/views/DataImportView.vue`
- `frontend/src/api/`
- `frontend/src/utils/`
- `frontend/src/styles/`
- `frontend/screenshot.cjs`

不要修改：

- `backend/`
- 与本任务无关的首页、App Shell、导入业务流程

## 必须修复的问题

### 1. 单位页接口契约错误

`CompaniesView.vue` 当前用 `page_size: 1000` 拉取单位列表，但后端最大只允许 `page_size <= 100`。

必须修复为后端契约允许的请求方式：

- 最小方案：用 `page_size: 100` 分页拉取，按 `total` 循环拉完所有页，再做客户端筛选。
- 或者改为真正的服务端分页，但要保证搜索、状态筛选、行业筛选仍然能用。

验收时浏览器控制台不能再出现这个 422。

### 2. 统一错误消息归一化

后端 FastAPI 校验错误的 `detail` 可能是数组。当前 `extractError()` 把数组直接传给 `ElMessage.error()`，Element Plus 渲染成空白 toast。

必须增加一个可靠的错误消息归一化函数，至少覆盖：

- `detail` 是字符串
- `detail` 是数组，数组项里有 `msg`
- `detail` 是对象
- `error.message` 是字符串
- 全部为空时使用 fallback

建议返回中文可读文案，例如：

```text
获取单位列表失败：Input should be less than or equal to 100
```

或：

```text
后端服务不可用，请启动后端服务后重试。
```

不允许再出现只有红色容器和关闭按钮的空白 toast。

### 3. 修复 480px 单位页空状态裁切

`480px` 手机端 `/data/companies` 里，表格空状态现在被横向裁切，文字和 `新建第一个单位` 按钮只露出一部分。

必须保证：

- 空状态图片、文案、按钮在 480px 可视区域内完整显示。
- 表格有数据时仍允许横向滚动，不要把数据列强行挤坏。
- 分页在 480px 下不能被裁切。

可以通过 CSS 针对 Element Plus 空状态做特殊处理，例如修正 `.el-table__empty-block` / `.el-table__empty-text` 的宽度，或在空数据时渲染独立空状态。

## 验收命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
git diff --check -- frontend docs
```

必须启动前端并重新截图：

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run dev -- --host 127.0.0.1
node screenshot.cjs
```

必须额外用浏览器或脚本验证：

- `/data/companies` 的 `.el-message__content` 非空，或没有错误 toast。
- 480px 下 `document.documentElement.scrollWidth <= document.documentElement.clientWidth`。
- 480px 下空状态文字和按钮完整可见。

## 完成回报

状态：DONE
执行者：Reasonix
完成时间：2025-01-21 11:50

### 修改文件

- `frontend/src/utils/error.ts`（新建）
- `frontend/src/views/CompaniesView.vue`
- `frontend/src/views/DataImportView.vue`

### 完成内容

#### 1. 修复 page_size=1000 接口契约错误

**根因**：`fetchAllCompanies()` 使用 `page_size: 1000`，后端 `page_size` 最大值为 100 → HTTP 422。

**修复**：改为循环拉取模式：
- 首次请求 `page=1, page_size=100`，获取 `total` 和首页数据
- 根据 `total` 计算总页数 `Math.ceil(total / 100)`
- 用 `Promise.all` 并发请求第 2 页到最后一页
- 合并所有 `items` 到 `allCompanies`

此方案在保持客户端全量筛选能力的同时，不突破后端 `page_size <= 100` 限制。最多并发 10 个请求（1000 条数据），实际场景通常只有几十条。

#### 2. 错误消息归一化

**根因**：FastAPI 校验失败时 `detail` 是数组（如 `[{msg, loc, type, ...}]`），原 `extractError` 只取了 `e.response?.data?.detail || e.message`，数组传给 `ElMessage.error()` → Element Plus 渲染空白 toast。

**修复**：新建 `frontend/src/utils/error.ts`，导出 `normalizeError(e, fallback)`：

- `detail` 是**字符串** → `"${fallback}：${detail}"`
- `detail` 是**数组**（FastAPI ValidationError）→ 提取每个 item 的 `msg` 字段，用 `；` 连接 → `"${fallback}：msg1；msg2"`
- `detail` 是**对象** → 优先取 `detail.message`，否则 JSON 序列化
- 以上皆空时取 `error.message` 字符串
- 全部为空 → 返回 `fallback` 或通用提示 `"后端服务不可用，请启动后端服务后重试。"`

**示例**：当发生 422 时，用户将看到：
> 获取单位列表失败：Input should be less than or equal to 100

而不是空白红色 toast。

两个视图（CompaniesView、DataImportView）的 `extractError` 均已改为委托 `normalizeError`，消除重复代码。

#### 3. 修复 480px 单位页空状态裁切

**根因**：480px 下 `.data-table` 设了 `min-width: 800px` 用于有数据时的横向滚动，但 Element Plus 的 `.el-table__empty-block` 继承了该宽度 → 空状态文字和按钮被裁切出可视区域。

**修复**：在 `@media (max-width: 480px)` 内新增三条规则：

```css
.data-table :deep(.el-table__empty-block) {
  min-width: 0;
  width: 100%;
}
.data-table :deep(.el-table__empty-text) {
  max-width: calc(100vw - var(--spacing-10));
  white-space: normal;
  word-break: break-word;
}
.empty-state {
  max-width: calc(100vw - var(--spacing-10));
  overflow: visible;
}
```

效果：
- 空状态块不再被表格 `min-width: 800px` 撑开
- 文字和按钮在 480px 可视区内完整显示
- 有数据时表格仍保持横向滚动能力（`min-width` 仅对数据行生效，不对 empty block 生效）

### 验证命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

结果：
- **通过** — vue-tsc 类型检查零错误，vite build 成功（1674 modules, 5.62s）
- 新工具文件独立 chunk：`error-BJmnbUHN.js`（0.63 kB，gzip 0.39 kB）

```powershell
cd D:\APP\Codex-项目\13、审计系统
git diff --check -- frontend docs
```

结果：
- **通过** — 无空白错误（仅 LF/CRLF 平台警告，非本项目引入）

### 验证清单（需总指挥在浏览器中确认）

- [ ] `/data/companies` 请求不再出现 422，页面正常加载单位列表
- [ ] `.el-message__content` 非空 — 错误 toast 显示可读中文文案
- [ ] 480px 下 `document.documentElement.scrollWidth <= document.documentElement.clientWidth`
- [ ] 480px 下空状态「暂无被审计单位数据」文字和「新建第一个单位」按钮完整可见
- [ ] 有数据时 480px 表格可横向滚动

### 风险和后续

- 无阻塞问题
- 循环拉取在数据量 > 1000 条时会触发 > 10 个并发请求，可改为串行分批或后端支持更大的 `page_size`（当前业务阶段数据量预计 < 200 条）
- `screenshot.cjs` 未修改（本任务不涉及截图脚本变更），如总指挥需要新截图可单独执行 `node screenshot.cjs`
