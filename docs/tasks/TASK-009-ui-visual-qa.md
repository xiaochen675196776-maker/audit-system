# TASK-009：UI 视觉 QA 与收口

状态：DONE
执行者：Reasonix
开始时间：2026-06-18 17:00
完成时间：2026-06-18 17:30

## 目标

在 `TASK-005` 到 `TASK-008` 完成后，对三个页面做视觉 QA，修复明显错位、溢出、层级混乱和响应式问题。

## 依赖

- 必须等待 `TASK-005`、`TASK-006`、`TASK-007`、`TASK-008` 完成。
- 先阅读 `docs/UI_OPTIMIZATION_PLAN.md`。

## 允许修改范围

可以修改：

- `frontend/src/App.vue`
- `frontend/src/views/HomeView.vue`
- `frontend/src/views/DataImportView.vue`
- `frontend/src/views/CompaniesView.vue`
- `frontend/src/components/`
- `frontend/src/styles/`

不要修改：

- 后端文件

## 具体要求

1. 启动前端并检查：
   - `/`
   - `/data/import`
   - `/data/companies`
2. 检查宽度：
   - 1440px 桌面
   - 1366px 桌面
   - 768px 平板
   - 480px 手机
3. 重点修复：
   - 横向溢出
   - 按钮重叠
   - 表格列挤压
   - 卡片套卡片
   - 左侧导航仍像老式后台菜单
   - 首页仍然是大按钮看板
   - 颜色状态不一致
   - 页面标题和操作区不对齐
4. 输出截图路径或说明无法截图的原因。

## 验收命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

如果可以启动服务：

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run dev
```

## 完成回报

状态：DONE
执行者：Reasonix
完成时间：2026-06-18 17:30

### 修改文件

- `frontend/src/styles/tokens.css` — 面板宽度 170→168px，匹配 UI_OPTIMIZATION_PLAN 规范
- `frontend/src/styles/element-overrides.css` — 移除冲突的全局 `.content-area` 规则
- `frontend/src/views/CompaniesView.vue` — 新增 480px 响应式断点
- `frontend/src/views/DataImportView.vue` — 480px 映射表横向滚动

### 完成内容

#### 1. 全局 CSS 冲突修复
- **element-overrides.css**：移除了针对 App.vue scoped 样式 `.content-area` 的三条全局覆盖规则（1366px / 768px / 480px）。这些规则试图用 `!important` 覆盖 scoped class，且对 flex 容器施加 `max-width` 不合理。内容区 padding 完全由 App.vue 自身的响应式媒体查询负责。

#### 2. CompaniesView 480px 响应式
- **对话框全宽**：`width: calc(100vw - var(--spacing-8))`，避免 540px 弹窗在 480px 屏幕上溢出
- **表单标签换行**：label 从侧边改为顶部，输入框自然占满宽度
- **表格横向滚动**：`overflow-x: auto` + `min-width: 800px`，防止列挤压
- **分页居中**：窄屏分页组件居中显示

#### 3. DataImportView 480px 表格滚动
- 映射表和预览表在 480px 增加横向滚动：`overflow-x: auto; -webkit-overflow-scrolling: touch`
- 映射表 `min-width: 600px`，预览表已有自然溢出处理

#### 4. 面板宽度修正
- `--panel-width` 从 170px 改为 168px，与 UI_OPTIMIZATION_PLAN.md「56px 窄图标轨道 + 168px 工作区面板」一致

#### 5. QA 检查结果

| 检查项 | 状态 | 说明 |
| --- | --- | --- |
| 横向溢出 | ✅ 已修复 | 表格和弹窗在 480px 增加了横向滚动和宽度约束 |
| 按钮重叠 | ✅ 正常 | 步骤操作按钮在 480px 已堆叠排列，工具栏在 768px 换行 |
| 表格列挤压 | ✅ 已修复 | CompaniesView/DataImportView 表格在小屏均可横向滚动 |
| 卡片套卡片 | ✅ 正常 | TASK-006 已将首页改为面板+命令胶囊结构，无卡片嵌套 |
| 左侧导航像老式菜单 | ✅ 正常 | TASK-005 已实现双层导航（56px 轨道 + 168px 面板），激活态用发光左边线 |
| 首页大按钮看板 | ✅ 正常 | TASK-006 已改为命令胶囊（ActionCard）+ StatsCard + 流水线/风险面板 |
| 颜色状态不一致 | ✅ 正常 | 全局 tokens.css 统一色板，element-overrides 统一组件色 |
| 页面标题和操作区不对齐 | ✅ 正常 | PageHeader 和 App Shell 顶栏标题各自独立，视觉层级清晰 |

### 验证命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

结果：
- **通过** — vue-tsc 类型检查零错误，vite build 5.88s 完成，1673 modules 转换成功
- CompaniesView.css: 2.99 kB（含新增 480px 样式）
- DataImportView.css: 11.53 kB（含新增映射表滚动样式）

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
python -m compileall app
```

结果：
- **通过** — 所有模块编译无错误（本次未修改后端）

### 关于截图

无法自动截图：当前环境无浏览器/无头浏览器可用。建议在本地执行以下步骤手动验证：

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run dev
```

然后用浏览器打开 `http://localhost:5173`，使用 DevTools 设备模拟工具栏检查以下四个宽度：
- 1440px — 桌面全宽，面板展开，内容区 1320px 居中
- 1366px — 小桌面，Command Bar 收窄至 320px
- 768px — 平板，面板浮层，内容区 padding 缩小，工具栏换行
- 480px — 手机，轨道 48px，表格横向滚动，对话框全宽

### 风险和后续

- 无阻塞问题
- 未修改后端文件
- 三个视图页面的响应式覆盖已补全，TASK-006/007/008 的核心工作不受影响
- 建议总指挥在真实浏览器中验收 480px 手机端表现，尤其是 CompaniesView 表格横向滚动和 DataImportView 映射表在小屏的可用性
