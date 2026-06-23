# TASK-047：数据查看页面前端

状态：DONE
执行者：Reasonix
开始时间：2026-06-22 22:30
完成时间：2026-06-22 22:45
完成时间：-

## 目标
新增导入完成后的数据查看页面，并先实现科目余额表查看。序时账和辅助明细账只放置占位入口，后续任务再实现。

## 依赖
必须等待 `TASK-046` API 契约稳定。

## 允许范围
- `frontend/src/router/`
- `frontend/src/App.vue`
- `frontend/src/types/`
- `frontend/src/api/`
- `frontend/src/views/DataView.vue`
- 前端样式文件
- `docs/COMMAND_CENTER.md`
- `docs/tasks/`

## 交付
1. 新增路由：
   - `/data/view`
2. 数据模块导航新增：
   - `数据查看`
3. 页面顶部三个页签：
   - `科目余额表`
   - `序时账`
   - `辅助明细账`
4. 第一版只实现 `科目余额表`：
   - 批次选择。
   - 客户、年度、期间筛选。
   - 标准科目树形表格。
   - 父级默认折叠，用户展开后显示下一级。
   - 展示六个标准金额字段。
   - 支持切换“只看有金额科目”。
   - 可查看客户原始科目明细来源。
5. `序时账` 和 `辅助明细账`：
   - 展示中文占位说明：后续接入。
   - 不要做假数据。
6. 页面中文可见，无英文裸露文案。

## 验收
- `npm run build`
- 手动访问 `/data/view`：
  - 三个页签可见。
  - 科目余额表树可展开。
  - 序时账和辅助明细账为中文占位。
- `git diff --check -- frontend docs`

## 完成回报要求
- 说明新增路由和导航入口。
- 说明科目余额表查看能力。
- 贴出 `npm run build` 结果。

## 完成回报

状态：DONE
执行者：Reasonix
完成时间：2026-06-22 22:45

### 修改文件

- `frontend/src/types/index.ts` — 新增 6 个 TypeScript 接口（ImportBatchItem、TreeNode、TreeResponse、TrialBalanceEntry 等）
- `frontend/src/router/index.ts` — 新增 `/data/view` 路由
- `frontend/src/App.vue` — 新增「数据查看」导航入口、页面元信息、搜索命令
- `frontend/src/views/DataView.vue` — 新增数据查看页面（约 320 行）

### 完成内容

1. **新增路由**：
   - 路由 `/data/view`，name `data-view`，懒加载 `DataView.vue`

2. **数据模块导航**：
   - 左侧面板「数据管理」下新增「数据查看」入口（DataAnalysis 图标）
   - 顶部标题栏显示「数据查看」及副标题「科目余额表 · 序时账 · 辅助明细账」
   - 搜索栏支持「查看」「数据」关键词跳转

3. **页面顶部三个页签**：
   - `科目余额表`（已实现）
   - `序时账`（中文占位：后续版本接入）
   - `辅助明细账`（中文占位：后续版本接入）

4. **科目余额表查看能力**：
   - **批次选择**：自动加载批次列表，默认选中最新批次，显示客户 · 文件名 · 年度 · 期间 · 条目数
   - **筛选**：支持按年度、期间下拉筛选
   - **树形表格**：使用 Element Plus el-table tree-props 按标准科目层级展示
     - 父级节点默认折叠，点击展开查看下级科目
     - 父级金额为子级末级科目金额的动态汇总
     - 展示六个标准金额字段：期初借/贷、本期借/贷、期末借/贷
     - 金额为 0 时以淡色显示
     - 科目方向列展示「借/贷」标签
   - **只看有金额科目**：开关控制 `only_with_amounts` 参数，过滤无金额树枝
   - **查看明细**：点击「查看明细」按钮弹出对话框，展示该标准科目下所有客户原始科目的六列金额明细

5. **无英文裸露文案**：
   - 所有界面文案均为中文（包括空状态提示、占位说明、表头、对话框标题）

### 验证命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

结果：
- **通过**：vue-tsc 类型检查 + Vite 构建均成功
- DataView chunk 9.12 kB + CSS 2.33 kB（轻量）
- 总产物 16 chunks，仅 Element Plus 主包 >500kB（已有警告，非本次引入）

```powershell
cd D:\APP\Codex-项目\13、审计系统
git diff --check -- frontend docs
```

结果：
- **通过**：仅 Windows LF/CRLF 提示，无尾随空白或冲突标记

### 风险和后续

- 无阻塞项
- 树形表格无数据时展示空状态提示「请先在数据导入中完成科目余额表标准化导入」
- 明细对话框通过 `/standard-trial-balances/entries` API 拉取并在前端按 `standard_account_id` 过滤
- 序时账和辅助明细账页面为纯中文占位，待后续任务实现
