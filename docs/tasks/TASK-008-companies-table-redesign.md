# TASK-008：被审计单位管理页重设计

状态：DONE
执行者：Reasonix
开始时间：2025-01-21 11:00
完成时间：2025-01-21 11:20

## 目标

把公司管理页从普通 CRUD 表格优化成主数据管理页面，提升搜索、筛选、表格密度、状态展示和表单体验。

## 依赖

- 必须等待 `TASK-005` 完成。
- 先阅读 `docs/UI_OPTIMIZATION_PLAN.md`。

## 允许修改范围

可以修改：

- `frontend/src/views/CompaniesView.vue`

不要修改：

- 后端文件
- `frontend/src/views/HomeView.vue`
- `frontend/src/views/DataImportView.vue`
- `frontend/src/types/index.ts`（除非发现现有类型错误，先标记阻塞）

## 具体要求

1. 顶部工具栏：
   - 搜索框、状态筛选、行业筛选、新建单位按钮。
   - 搜索和筛选布局在窄屏可换行。
2. 表格：
   - 弱化 ID，不作为主要视觉信息。
   - 单位名称、编码、税号、行业、状态、创建时间、操作列清晰。
   - 状态标签低饱和。
   - 操作列固定右侧，危险操作保留确认。
3. 表单：
   - 必填字段更清楚。
   - 后端错误继续展示给用户。
   - 编辑状态不允许误改单位编码，除非后端支持。
4. 空状态：
   - 没数据时给明确新建入口。

## 验收命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

## 完成回报

状态：DONE
执行者：Reasonix
完成时间：2025-01-21 11:20

### 修改文件

- `frontend/src/views/CompaniesView.vue`

### 完成内容

**1. 顶部工具栏**
- 新增状态筛选下拉框（全部 / 正常 / 停用），映射 `is_active` 布尔值
- 新增行业筛选下拉框（动态从数据中提取唯一行业列表，支持 filterable）
- 搜索框保留，加入 300ms 防抖输入
- 「新建单位」按钮移至工具栏右侧，与计数信息同行
- 工具栏使用 `flex-wrap`，窄屏自动换行

**2. 表格优化**
- 列顺序重排：单位名称 → 编码 → 税号 → 行业 → 状态 → 创建时间 → ID → 操作
- ID 列弱化：显示为截断等宽字体 `code`（前8位+…），灰色小字，低视觉权重
- 新增「创建时间」列，`YYYY-MM-DD` 格式化，tabula-nums 对齐
- 状态列：用 6px 圆点 + 文字 替代 Element Plus Tag，低饱和设计（绿=正常 / 灰=停用）
- 空状态：使用 `el-empty` 组件，无数据时显示「新建第一个单位」按钮；有筛选条件无结果时显示「清除筛选」
- 表头样式对齐 tokens：背景 `#f7f8fa`，底部 2px `#e4e7ec` 分隔线

**3. 表单优化**
- 必填字段 `required` 属性显式标记（name、code）
- **编辑模式下单位编码禁用输入**（后端 `CompanyUpdate` 不支持修改 code），下方显示提示文字「编码创建后不可修改」
- 后端错误详情通过 `extractError()` 展示 `response.data.detail`，不再只显示通用文案
- 创建/编辑成功后实时更新本地缓存，无需重新请求全量数据

**4. 脚本逻辑重构**
- 改为**客户端全量筛选 + 前端分页**：`fetchAllCompanies(page_size=1000)` 一次性拉取 → `filteredCompanies` computed 多条件筛选 → `companies` computed 分页切片
- 删除操作同步移除本地缓存，避免多余网络请求
- 创建成功后 `unshift` 到缓存顶部，编辑成功后原地更新

### 验证命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

结果：
- **通过** — vue-tsc 类型检查零错误，vite build 成功（1673 modules, 4.67s）

### 风险和后续

- 无阻塞问题
- 客户端全量加载适用于中小规模数据（数百条单位）；如果未来数据量增长至数千条，需将状态/行业筛选参数回传后端，当前架构已预留筛选状态变量可快速迁移
- 编辑时编码禁用依赖前端约束，后端 `CompanyUpdate` 本身不接受 code 字段，双重保障
- 行业列表从 `industry` 字段动态提取，空值自动排除；未来如需预设行业枚举可改为配置驱动

