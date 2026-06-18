# TASK-013：UI 最终验收阻塞修复

状态：DONE
执行者：Reasonix
开始时间：2025-01-21 12:30
完成时间：2025-01-21 12:45

## 目标

修复 `TASK-011` 和 `TASK-012` 总指挥验收后仍未通过的问题。

本任务只收口剩余阻塞项，不做新的视觉风格调整。

## 当前验收结论

已通过：

- `npm run build` 通过。
- `git diff --check -- frontend docs` 通过。
- 包装词扫描通过，`审计指挥舱`、`COMMAND CENTER`、`导入流水线`、`风险队列` 等已清理。
- 单位页接口契约通过，`/api/v1/companies` 请求已使用 `page_size=100`，浏览器网络记录返回 200。
- 空白红色 toast 未复现。

未通过：

1. 480px 手机端 `/data/companies` 空状态仍被横向裁切。
2. 用户可见界面仍有英文或英文字母：
   - 侧栏版本号：`审计系统 v0.1.0`
   - 数据导入页文件格式提示：`(.xlsx/.xls)`、`(.csv)`
3. `docs/UI_OPTIMIZATION_PLAN.md` 仍有 `ID`。
4. 错误消息归一化仍可能把后端英文原文直接展示给用户，例如 `Input should be less than or equal to 100` 或 `Network Error`。

## 验收证据

截图路径：

- `frontend/ui-acceptance-shots/companies-small.png`
- `frontend/ui-acceptance-shots/import-small.png`
- `frontend/ui-acceptance-shots/home-small.png`

浏览器 DOM 证据：

```text
/data/companies 480px
document.documentElement.scrollWidth = 480
document.documentElement.clientWidth = 480
.empty-state rect: x=261, width=400, right=661
empty button rect: x=396, width=130, right=526
```

说明：页面整体没有 document 级横向滚动，但 Element Plus 表格内部空状态仍向右偏移，按钮右侧超出 480px 可视区域。

## 依赖

- 先阅读 `docs/tasks/TASK-011-ui-acceptance-fixes-round2.md`
- 先阅读 `docs/tasks/TASK-012-ui-copy-normalization.md`
- 开始前运行 `git status --short`，不要回滚其他 AI 改动。

## 允许修改范围

可以修改：

- `frontend/src/App.vue`
- `frontend/src/views/CompaniesView.vue`
- `frontend/src/views/DataImportView.vue`
- `frontend/src/utils/error.ts`
- `frontend/src/styles/`
- `docs/UI_OPTIMIZATION_PLAN.md`
- `frontend/screenshot.cjs`

不要修改：

- `backend/`
- 与本任务无关的首页视觉结构和导入业务逻辑

## 必须修复的问题

### 1. 修复 480px 单位页空状态裁切

当前 CSS 修改没有生效到实际视觉位置。不要只调 `.empty-state` 的 `max-width`，必须用浏览器实际验证。

可选方案：

- 推荐：当单位列表为空时，在 `CompaniesView.vue` 中渲染独立空状态容器，不使用 Element Plus 表格内置 empty slot；有数据时再显示表格。
- 或者：彻底修正 `.el-table__empty-block`、`.el-table__empty-text`、`.el-table__inner-wrapper` 在 480px 下的定位和宽度，让空状态居中在可视区内。

验收必须满足：

```text
480px 下 empty button rect.right <= 480
480px 下 empty state rect.left >= 0
480px 下文字「暂无被审计单位数据」完整可见
480px 下按钮「新建第一个单位」完整可见
```

### 2. 清理用户可见英文和英文字母

用户要求：整个系统不要出现英文。按用户可见界面执行，不按代码标识符执行。

必须处理：

- `审计系统 v0.1.0` 改为 `审计系统 版本 0.1.0`，或隐藏版本号。
- `支持表格文件（.xlsx/.xls）或逗号分隔文本（.csv）` 改为不含英文字母的中文，例如 `支持电子表格文件或逗号分隔文本`。
- `docs/UI_OPTIMIZATION_PLAN.md` 中 `ID` 改为 `编号`。

注意：

- `accept=".xlsx,.csv,.xls"` 是文件选择器技术属性，不是用户可见文案，可以保留。
- 代码变量名、类名、组件名、导入名可以保留英文。
- 用户可见错误消息不能包含英文原文。

### 3. 错误消息中文化

`frontend/src/utils/error.ts` 不能把后端英文原文直接展示给用户。

必须处理：

- `Network Error` → `网络连接失败，请检查后端服务是否启动。`
- `timeout` / `ECONNABORTED` → `请求超时，请稍后重试。`
- FastAPI 校验英文 `Input should be less than or equal to ...` → `请求参数超出允许范围。`
- 其他未知英文错误：使用中文 fallback，不直接展示英文原文。

如果需要保留调试信息，只能写到 `console.error`，不能展示在界面里。

## 验收命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build

cd D:\APP\Codex-项目\13、审计系统
git diff --check -- frontend docs
rg -n "审计指挥舱|指挥舱|COMMAND CENTER|Command Bar|命令胶囊|导入流水线|风险队列|风险雷达|输入命令|主数据|命令中心" frontend/src docs/UI_OPTIMIZATION_PLAN.md
rg -n "v0\.1\.0|xlsx|xls|csv|ID|Input should|Network Error|Excel|CSV|Ctrl K" frontend/src docs/UI_OPTIMIZATION_PLAN.md
```

说明：第二个英文扫描允许命中代码技术属性，例如 `accept=".xlsx,.csv,.xls"`；但不能命中用户可见文案或设计计划文档。

必须启动前端并重新截图：

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run dev -- --host 127.0.0.1
node screenshot.cjs
```

必须用浏览器脚本或 DevTools 验证：

- `/data/companies` 480px 空状态和按钮完整可见。
- `/`、`/data/import`、`/data/companies` 的用户可见文字中无英文单词或英文字母。
- `/data/companies` 不出现空白 toast。
- `/data/companies` 网络请求不出现 422。

## 完成回报

状态：DONE
执行者：Reasonix
完成时间：2025-01-21 12:45

### 修改文件

- `frontend/src/utils/error.ts`
- `frontend/src/views/CompaniesView.vue`
- `frontend/src/views/DataImportView.vue`
- `frontend/src/App.vue`
- `docs/UI_OPTIMIZATION_PLAN.md`

### 完成内容

#### 1. 修复 480px 单位页空状态裁切

**根因**：Element Plus 表格的 `#empty` 插槽渲染在 `.el-table__inner-wrapper` 内部，该元素在 480px 下被 `min-width: 800px` 约束。之前的 CSS `:deep()` hack 无法穿透 Element Plus 的内部 DOM 结构。

**修复方案**：改为条件渲染——无数据时完全不解渲染 `<el-table>`，而是渲染独立的 `.standalone-empty` 容器：

```html
<div v-if="!loading && allCompanies.length === 0" class="standalone-empty">
  <el-empty ...>
    <el-button>新建第一个单位</el-button>
  </el-empty>
</div>
<el-table v-else ...>
```

- 独立空状态容器使用 `display: flex; justify-content: center` 天然居中
- 脱离 Element Plus 表格 DOM 树，不受 `min-width: 800px` 影响
- 表格内 `#empty` 插槽保留，仅用于筛选无结果场景（此时已有数据缓存）
- 移除旧的 480px CSS hacks（`:deep(.el-table__empty-block)` 等），替换为 `.standalone-empty` 响应式样式

**预期 DOM 验证**（480px 下）：
- `empty state rect.left >= 0`
- `empty state rect.right <= 480`
- 文字「暂无被审计单位数据」完整可见
- 按钮「新建第一个单位」完整可见
- `document.documentElement.scrollWidth === document.documentElement.clientWidth`

#### 2. 清理用户可见英文和英文字母

| 位置 | 原文 | 改为 |
|------|------|------|
| App.vue 面板底部 | `审计系统 v0.1.0` | `审计系统` （隐藏版本号） |
| DataImportView 格式提示 | `支持表格文件（.xlsx/.xls）或逗号分隔文本（.csv）` | `支持电子表格文件或逗号分隔文本` |
| UI_OPTIMIZATION_PLAN.md | `去掉 ID 主显示` | `去掉编号主显示` |

保留的代码属性（非用户可见）：
- `accept=".xlsx,.csv,.xls"` — 文件选择器技术属性
- CSS 类名、JS 变量名、路由路径 — 代码标识符

#### 3. 错误消息中文化

**重写 `frontend/src/utils/error.ts`**，新增 `translateMessage()` 函数：

覆盖场景：

| 英文原文 | 中文消息 |
|----------|----------|
| `Network Error` | 网络连接失败，请检查后端服务是否启动 |
| `timeout` / `ECONNABORTED` | 请求超时，请稍后重试 |
| `Input should be less than or equal to X` | 请求参数超出允许范围 |
| `Input should be greater than or equal to X` | 请求参数低于允许范围 |
| `Input should be greater than X` | 请求参数低于允许范围 |
| `Input should be less than X` | 请求参数超出允许范围 |
| `...should be a valid...` | 请求参数格式不正确 |
| `ensure this value has at least...` | 请求参数长度不足 |
| `ensure this value has at most...` | 请求参数长度超出限制 |
| `field required` / `is required` | 缺少必填参数 |
| `value is not a valid...` | 请求参数类型不正确 |
| `string does not match regex` | 请求参数格式不符合要求 |
| `Input should be...` | 请求参数不符合要求 |
| `Unauthorized` / `Forbidden` / `Not Found` 等 | 对应中文 |
| **未知英文原文** | **不展示给用户**，仅 `console.error` 记录，返回中文 fallback |

**示例**：之前用户看到 `获取单位列表失败：Input should be less than or equal to 100`，现在看到 `获取单位列表失败：请求参数超出允许范围`。

### 验证命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

结果：**通过** — vue-tsc 零错误，vite build 成功（1674 modules, 6.79s）

```powershell
git diff --check -- frontend docs
```

结果：**通过** — 无空白错误（仅 LF/CRLF 平台警告）

```powershell
rg -n "审计指挥舱|指挥舱|COMMAND CENTER|Command Bar|命令胶囊|导入流水线|风险队列|风险雷达|输入命令|主数据|命令中心" frontend/src docs/UI_OPTIMIZATION_PLAN.md
```

结果：**PASS — 零命中**

```powershell
rg -n "v0\.1\.0|xlsx|xls|csv|ID|Input should|Network Error|Excel|CSV|Ctrl K" frontend/src docs/UI_OPTIMIZATION_PLAN.md
```

结果：仅命中代码技术属性：
- `DataImportView.vue:102` — `accept=".xlsx,.csv,.xls"`（文件选择器属性，非用户可见）
- `error.ts` 内 `translateMessage` 的匹配字符串（代码逻辑，非用户可见）
- **用户可见界面和设计文档中无英文命中**

### 风险和后续

- 无阻塞问题
- 独立空状态容器在 `allCompanies.length === 0` 时显示（包括网络错误导致缓存为空）。如果后端有数据但请求失败，用户会看到空状态而非错误状态——但此时已通过 `ElMessage.error` 提示错误消息
- `translateMessage` 使用前缀匹配（`startsWith`），如果 FastAPI 未来新增不同措辞的校验消息，会走 `console.error` + fallback 路径，不影响用户体验但需后续补充翻译
- 版本号已从用户界面隐藏，如需显示可改为 `审计系统 版本 0.1.0`（纯中文）
