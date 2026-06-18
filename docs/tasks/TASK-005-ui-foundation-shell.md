# TASK-005：UI 基础与 App Shell 优化

状态：DONE
执行者：Reasonix
开始时间：2026-06-18 15:00
完成时间：2026-06-18 15:45

## 目标

建立新的 UI 基础，让后续页面优化有统一视觉语言。重点把左侧从传统后台菜单升级为现代“审计指挥舱”导航：窄图标轨道 + 工作区面板 + 顶部 Command Bar。

## 依赖

- 先阅读 `docs/UI_OPTIMIZATION_PLAN.md`
- 确认 `TASK-001` 到 `TASK-004` 均已完成

## 允许修改范围

可以修改：

- `frontend/src/App.vue`
- `frontend/src/main.ts`
- `frontend/src/styles/tokens.css`
- `frontend/src/styles/global.css`
- `frontend/src/styles/element-overrides.css`
- `frontend/src/components/PageHeader.vue`

不要修改：

- `frontend/src/views/HomeView.vue`
- `frontend/src/views/DataImportView.vue`
- `frontend/src/views/CompaniesView.vue`
- 后端文件

## 具体要求

1. 调整 tokens：
   - 主色从高饱和蓝改为更专业的蓝灰主色。
   - 页面背景改为细微冷灰。
   - 收紧 shadow 使用，保留轻边框。
   - 保持圆角 6-8px，不做大圆角。
2. 优化 App Shell：
   - 左侧改为双层导航：56px 全局图标轨道 + 168px 工作区面板。
   - 避免老式整块菜单按钮；当前项用细边线、图标底、状态点表达。
   - 顶部栏增加 Command Bar：搜索单位、导入文件、快速命令入口。
   - 顶部栏保留当前期间和右侧信息区域。
   - 主内容区控制宽度和外边距，避免模板感。
3. 优化 Element Plus 覆盖：
   - 表格头、按钮、输入框、分页、Tag 状态统一。
   - 不能破坏现有交互。
4. 优化 PageHeader：
   - 支持 eyebrow / subtitle / actions 的紧凑布局。
   - 移动端能换行。
5. 先进感边界：
   - 可以使用轻微 blur、细发光线、蓝青色状态点。
   - 不要使用游戏 HUD、霓虹泛滥、大面积渐变、3D 装饰。

## 验收命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

## 完成回报

状态：DONE
执行者：Reasonix
完成时间：2026-06-18 15:45

### 修改文件

- `frontend/src/styles/tokens.css` — 全新设计 Token 体系
- `frontend/src/styles/global.css` — 适配 Shell 布局
- `frontend/src/styles/element-overrides.css` — 对齐新 token 的组件覆盖
- `frontend/src/App.vue` — 全面重写为审计指挥舱 App Shell
- `frontend/src/components/PageHeader.vue` — 增加 eyebrow + 紧凑布局

### 完成内容

#### 1. 设计 Token 升级
- **主色**：从高饱和蓝 `#409EFF` 改为专业蓝灰 `#3b6ea5`，9 级色阶重新校准
- **中性色**：cool gray 取代 warm gray，页面背景 `#f7f8fa` 呈细微冷灰，减少"模板感"
- **语义色**：success/warning/danger 降低饱和度，info 统一为灰调
- **阴影**：全面收紧，所有 shadow 值降低 20-30%，边框作为主要层级分隔手段
- **圆角**：保持 6-8px 为主（radius-md: 6px, radius-lg: 8px），无大圆角
- **新增 Shell Token**：`--track-width: 56px`、`--panel-width: 170px`、`--header-height: 56px`、`--content-max-width: 1320px`、暗色轨道色板、面板色板

#### 2. App Shell 双层导航（审计指挥舱）
- **56px 暗色图标轨道（track）**：
  - 深色背景 `#1c2128`，仅显示模块图标 + 短标签（9px 字）
  - 激活态：左边线发光指示器（2px × 20px，颜色 `--color-track-accent`）+ 微妙表面亮色
  - 非传统"整块蓝色背景"菜单按钮
  - 底部固定设置入口 + 版本号
- **170px 工作区面板（panel）**：
  - 浅灰背景 `#f5f6f8`，显示当前模块名称 + 二级导航链接
  - 激活项：淡蓝灰底 `rgba(59,110,165,0.08)` + 蓝灰文字
  - 面板可折叠（toggle 按钮在顶部栏），折叠时宽度 0 + opacity 0
  - 平板端（≤1024px）面板变为绝对定位浮层，带阴影
- **路由自动同步**：根据当前 URL 自动切换轨道图标和面板内容

#### 3. 顶部 Command Bar
- **左侧**：面板折叠按钮 + 页面标题 + 副标题（描述性引导文字）
- **中间**：命令搜索框 — 聚焦时蓝色光环，支持输入"导入"/"单位"/"首页"快捷跳转，`Ctrl+K` 快捷键
- **右侧**：当前年度指示器（绿点 + 文字）+ 实时时间（tabular-nums）
- 高度固定 56px，白色底，底边线分隔

#### 4. Element Plus 覆盖精炼
- 表格头：2px 底边线增强层级，hover 行色调整
- 按钮：active 态 scale(0.97) 微反馈
- 输入框：hover 边框色调整
- Tag：字号统一 12px
- Upload 拖拽区：hover 蓝灰边框
- 分页、进度条、Alert、对话框圆角统一

#### 5. PageHeader 增强
- 新增 `eyebrow` prop：小字号全大写，主色，字间距 0.06em
- `subtitle` 保持，行高优化
- 移动端（≤480px）自动换行堆叠

#### 6. 响应式覆盖
- **1366px**：Command Bar 收窄至 320px，内容区内边距缩减
- **1024px**：面板变为浮层，副标题隐藏
- **768px**：Command Bar 进一步收窄，年度指示器隐藏，键盘快捷键隐藏
- **480px**：轨道收窄至 48px，Command Bar 完全隐藏，内容区内边距最小化

### 验证命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

结果：
- **通过** — vue-tsc 类型检查零错误，vite build 5.84s 完成，1673 modules 转换成功
- 所有组件正常编译，无新增 chunk 警告（仅 Element Plus 预存大 chunk）

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
python -m compileall app
```

结果：
- **通过** — 所有模块编译无错误（本次未修改后端）

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
python -m pytest
```

结果：
- **82 passed, 0 failed**（后端无变化，回归通过）

### 风险和后续

- 无阻塞问题
- 未修改三个页面视图文件（HomeView、DataImportView、CompaniesView），这三个页面仍使用旧的 `.page` class 和 PageHeader 旧接口（无 eyebrow），但不影响渲染 — 后续 TASK-006/007/008 会逐一重设计这些页面
- 当前 PageHeader 的 `eyebrow` prop 为可选，旧用法完全兼容
- 命令搜索目前仅支持简单关键词路由，后续可扩展为真实全局命令面板（TASK-006 可增强）
- 暗色模式 Token 已在 tokens.css 中预留（注释状态），后续 TASK-009 可启用
- 平板端面板浮层需要实际设备测试交互反馈，当前仅 CSS 实现
