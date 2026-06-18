# TASK-006：首页审计工作台重设计

状态：DONE
执行者：Reasonix
开始时间：2026-06-18 16:00
完成时间：2026-06-18 16:25

## 目标

把首页从“欢迎页 + 大卡片入口”改成审计指挥舱。用户一进来就看到当前账期、数据流转、风险队列和下一步建议动作，而不是普通看板按钮。

## 依赖

- 必须等待 `TASK-005` 完成。
- 先阅读 `docs/UI_OPTIMIZATION_PLAN.md`。

## 允许修改范围

可以修改：

- `frontend/src/views/HomeView.vue`
- `frontend/src/components/StatsCard.vue`
- `frontend/src/components/ActionCard.vue`

不要修改：

- `frontend/src/App.vue`
- `frontend/src/views/DataImportView.vue`
- `frontend/src/views/CompaniesView.vue`
- 后端文件

## 具体要求

1. 首页信息架构：
   - 顶部标题改为“审计指挥舱”或“审计工作台”，副标题体现当前账期。
   - 顶部放 Command Bar：搜索单位、输入命令、导入文件。
   - 第一行显示 4 个紧凑指标：被审计单位、凭证条数、辅助核算条目、待处理错误。
2. 最近动态：
   - 做成表格式/列表式“最近导入批次”区域。
   - 当前没有真实数据时使用明确空状态，不要假装有数据。
3. 操作入口：
   - 禁止再做“大按钮看板”。
   - 改为“下一步建议动作”：命令胶囊、任务队列、智能推荐。
   - “数据查询”保持即将上线，但作为低优先级命令，不抢主操作。
4. 视觉：
   - 少用渐变和 hover 动效。
   - 指标卡不要太高，适合工作台密度。
   - 可以加入细线数据流、状态点、低饱和蓝青色进度轨迹，增强先进感。

## 验收命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

## 完成回报

状态：DONE
执行者：Reasonix
完成时间：2026-06-18 16:25

### 修改文件

- `frontend/src/views/HomeView.vue` — 全面重写为审计指挥舱
- `frontend/src/components/StatsCard.vue` — 从大图标卡片改为紧凑指标条
- `frontend/src/components/ActionCard.vue` — 从大按钮卡片改为命令胶囊

### 完成内容

#### 1. 信息架构重组

```
之前：欢迎页 + 3 个大统计卡片 + 3 个大按钮卡片 + 空动态列表
现在：指挥舱 = 指标条 + 导入流水线 + 风险队列 + 命令胶囊
```

- **PageHeader**：启用 `eyebrow="COMMAND CENTER"`，标题"审计指挥舱"，副标题体现当前账期
- **4 个紧凑指标**：被审计单位、序时账条目、辅助核算条目、待处理错误 — 每个指标仅 64px 高，适合工作台密度
- **导入流水线面板**：左侧面板，表格/列表式展示最近导入批次（状态点 + 文件名 + 类型 + 成功/总数 + 时间）
- **风险队列面板**：右侧面板，列出高风险/中风险/低风险项（级别色点 + 描述 + 元信息）
- **建议动作**：底部 3 个命令胶囊（导入序时账 → 新增单位 → 数据查询），替代原大按钮看板

#### 2. StatsCard → 紧凑指标条

- 从 `56px 渐变图标 + 大数字` 改为 `32px 浅灰底图标 + 行内数字/标签`
- 新增 `trend` prop：显示百分比趋势（绿色上箭头 / 红色下箭头）
- 新增 `iconColor` prop 替代 `iconBg` gradient
- 卡片高度从 ~100px 降至 64px，信息密度提升
- 大数字自动格式化为万单位（≥10000 显示 1.2w）

#### 3. ActionCard → 命令胶囊

- 从 `100px+ 垂直居中大卡片` 改为 `行内胶囊按钮`
- 横向布局：图标 + 标题/描述 + 箭头，hover 时箭头右移
- 宽度 100% 适应网格，hover 淡蓝灰底 + 边框高亮
- `badge` 存在时自动 disabled（如"即将上线"），降低视觉权重
- active 微缩放反馈 (scale 0.98)

#### 4. 空状态设计

- **导入流水线空状态**：Upload 图标 + "暂无导入记录" + 引导链接"开始导入"
- **风险队列空状态**：绿色 SuccessFilled 图标 + "无待处理风险" + 系统正常提示
- 两个面板均在没有真实数据时展示明确空状态，不做假数据

#### 5. 响应式

- 1024px：双栏改为单栏堆叠，命令胶囊 3 列变 1 列
- 768px：指标条 4 列变 2 列
- 480px：指标条变单列，流水线行可换行

### 验证命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

结果：
- **通过** — vue-tsc 类型检查零错误，vite build 4.83s
- HomeView 从 4.5KB 增加到 6KB（CSS 8KB），三个组件正常编译

### 风险和后续

- 无阻塞问题
- 导入流水线和风险队列当前使用空状态占位，需要后端提供导入历史 API 和校验错误统计 API 后才能展示真实数据
- 指标中的 voucherCount/ledgerCount 当前硬编码为 0，后续需对接后端统计接口
- `StatsCard` 的 `iconBg` 和 `iconClass` prop 已移除，替换为 `iconColor`；已确认仅 HomeView 使用该组件，无兼容性影响
- `ActionCard` 的 API 保持向后兼容，但行为略有变化：有 badge 时自动禁用点击
