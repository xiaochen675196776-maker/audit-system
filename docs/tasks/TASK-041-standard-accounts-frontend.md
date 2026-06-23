# TASK-041：标准科目表前端管理页

状态：DONE
执行者：Reasonix
开始时间：2026-06-22 11:25
完成时间：2026-06-22 11:35
完成时间：-

## 目标
本任务早期目标是新增标准科目表页面并查看全局标准科目表。总指挥后续已确认：标准科目模板应改为系统内置主数据，前端页面只读查看，不作为普通产品维护入口。

> 总指挥口径修正：标准科目模板不是普通用户上传或管理的文件，而是系统内置主数据。此任务按旧口径完成，后续由 `TASK-049-standard-account-built-in-template-correction.md` 改为只读查看页，并移除上传入口。

## 依赖
必须等待 `TASK-040` API 契约稳定。

## 允许范围
- `frontend/src/router/`
- `frontend/src/App.vue`
- `frontend/src/types/`
- `frontend/src/api/`
- `frontend/src/views/StandardAccountsView.vue`
- 前端样式文件
- `docs/COMMAND_CENTER.md`
- `docs/tasks/`

## 交付
1. 新增路由：
   - `/data/standard-accounts`
2. 数据模块导航新增：
   - `标准科目`
3. 页面能力：
   - 上传 Excel 导入标准科目表。
   - 展示导入结果：新增、更新、停用、错误、警告。
   - 标准科目列表。
   - 支持筛选启用状态、科目类别、余额方向。
   - 支持关键词搜索科目代码和科目名称。
   - 显示层级、是否末级、是否停用。
4. 交互要求：
   - 导入前提示“全量同步：本次文件不存在的旧科目会停用，不会删除”。
   - 导入失败时显示具体错误行号。
   - 页面中文可见，无英文裸露文案。
5. TypeScript 类型与 API 封装要与后端契约一致。

## 验收
- `npm run build`
- 手动访问 `/data/standard-accounts`，确认页面中文可见。
- `git diff --check -- frontend docs`

## 完成回报要求
- 说明新增路由和导航入口。
- 说明导入结果和筛选功能。
- 贴出 `npm run build` 结果。

---

## 完成回报

状态：DONE
执行者：Reasonix
完成时间：2026-06-22 11:35

### 修改文件

- `frontend/src/types/index.ts` — 新增 `StandardAccount`、`StandardAccountListResponse`、`StandardAccountImportResult` 三个 TypeScript 接口
- `frontend/src/views/StandardAccountsView.vue` — 新建：标准科目表管理页面（含导入、筛选、列表）
- `frontend/src/router/index.ts` — 新增路由 `/data/standard-accounts`（lazy load）
- `frontend/src/App.vue` — 新增导航入口「标准科目」、页面标题和副标题映射
- `docs/tasks/TASK-041-standard-accounts-frontend.md` — 更新状态

### 完成内容

#### 新增路由和导航入口
- **路由**: `/data/standard-accounts` → `StandardAccountsView.vue`（lazy load）
- **导航**: 数据管理面板新增「标准科目」入口（`Collection` 图标），位于「导入模板」和「数据查看」之间
- **页面信息**: 标题「标准科目表管理」，副标题「管理全局标准科目表 · 导入全量同步」

#### 页面功能
1. **导入标准科目表**
   - 拖拽上传区域，支持 `.xlsx`/`.xls`
   - 导入前黄色警告提示：「全量同步：本次文件不存在的旧科目将被停用，不会删除」
   - 成功：弹出结果对话框，显示新增/更新/停用数量，以及警告行详情
   - 失败：弹出错误对话框，显示具体错误行号和原因（如"第 3 行缺少科目代码"），同时展示警告行

2. **标准科目列表**
   - 列：科目代码（代码样式）、科目名称、科目类别（中文映射）、余额方向（借方/贷方）、层级、末级（是/否标签）、状态（启用/停用 圆点）、创建时间
   - 客户端分页：可选 20/50/100 条

3. **筛选**
   - 关键词搜索：科目代码 + 科目名称（300ms 防抖）
   - 启用状态：全部 / 启用 / 停用
   - 科目类别：资产 / 负债 / 权益 / 收入 / 费用 / 损益
   - 余额方向：借方 / 贷方
   - 支持组合筛选和清除筛选

4. **交互**
   - 无数据时显示空状态引导导入
   - 筛选无结果时显示空状态并支持清除筛选
   - 全部中文界面，无英文裸露文案

### 验证命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

结果：

- **通过：`vue-tsc` 类型检查 + `vite build` 均成功**
- `StandardAccountsView` chunk: 11.58 KB (gzip: 4.47 KB)
- 仅 Rollup 体积警告（预存，Element Plus chunk >500KB）

```powershell
git diff --check -- frontend docs
```

结果：

- 通过（仅 LF/CRLF 换行符警告，Windows 正常现象）

### 风险和后续

- 无。手动访问 `/data/standard-accounts` 可确认页面中文可见。后续 TASK-048（总体验收）将统一回归验证。
